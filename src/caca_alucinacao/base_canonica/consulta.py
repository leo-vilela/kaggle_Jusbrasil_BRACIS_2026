"""Consulta à base canônica pelo índice de números próprios.

Interface definida em docs/02_arquitetura.md (seção ``base_canonica``). A
classe :class:`BaseCanonica` nunca devolve quem apenas *cita* um número: só
registros cujo cabeçalho declara aquele número como o PRÓPRIO processo.
Toda saída é ordenada por ``documento_id`` (determinismo).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .classes import (
    SIGLAS_CANONICAS,
    cadeia_de_classes,
    classe_principal,
    classes_compativeis,
    sem_acento,
)
from .digitos import digitos_canonicos
from .indice import carregar_indice, construir_indice


@dataclass(frozen=True)
class Registro:
    """Um registro da base (acórdão, súmula ou dispositivo)."""

    documento_id: str
    id_canonico: int
    tribunal: str | None
    ano: int | None
    relator: str | None
    natureza: str
    texto_len: int
    classe_propria: str | None   # cadeia canônica ("AGINT ARESP"); None p/ súmula/dispositivo
    uf: str | None = None
    tipo: str = "jurisprudencia"

    @property
    def classe_principal(self) -> str | None:
        return classe_principal(self.classe_propria.split()) if self.classe_propria else None


_STOP_RELATOR = frozenset({"de", "da", "do", "dos", "das", "e", "min", "ministro", "ministra",
                           "des", "desembargador", "desembargadora", "rel", "relator", "relatora"})


def _tokens_relator(nome: str) -> list[str]:
    t = sem_acento(nome).lower()
    t = re.sub(r"[^a-z\s]", " ", t)
    return [p for p in t.split() if p not in _STOP_RELATOR and len(p) >= 2]


def _dist1(a: str, b: str) -> bool:
    """Igualdade tolerante: iguais, ou 1 edição (troca/inserção/remoção) em nomes ≥ 5 letras."""
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    curto, longo = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(longo)):
        if longo[:i] + longo[i + 1:] == curto:
            return True
    return False


def relator_compativel(citado: str | None, registro: str | None) -> bool:
    """Todos os sobrenomes citados aparecem no nome do registro (tolerância de 1 erro)."""
    if not citado or not registro:
        return False
    a, b = _tokens_relator(citado), _tokens_relator(registro)
    if not a or not b:
        return False
    return all(any(_dist1(x, y) for y in b) for x in a)


class BaseCanonica:
    """Acesso à base pelo índice (JSON) — sem SQLite em runtime."""

    def __init__(self, indice: dict[str, Any]) -> None:
        self._indice = indice
        self._registros: dict[str, Registro] = {}
        self._por_id: dict[int, Registro] = {}
        for documento_id in sorted(indice["registros"]):
            r = indice["registros"][documento_id]
            uf = None
            for it in r["identificadores"]:
                if it.get("uf"):
                    uf = it["uf"]
                    break
            reg = Registro(
                documento_id=documento_id,
                id_canonico=int(r["id_canonico"]),
                tribunal=r["tribunal"],
                ano=r["ano"],
                relator=r["relator"],
                natureza=r["natureza"],
                texto_len=int(r["texto_len"]),
                classe_propria=r["classe_propria"] or None,
                uf=uf,
                tipo=r.get("tipo", "jurisprudencia"),
            )
            self._registros[documento_id] = reg
            self._por_id[reg.id_canonico] = reg
        self._por_digitos: dict[str, list[str]] = indice["por_digitos"]
        self._sumulas: dict[str, str] = indice["normativos"]["sumulas"]
        self._dispositivos: dict[str, str] = indice["normativos"]["dispositivos"]

    # -- construção ---------------------------------------------------------
    @classmethod
    def de_arquivo(cls, caminho_json: Path | str) -> BaseCanonica:
        return cls(carregar_indice(caminho_json))

    @classmethod
    def de_banco(cls, caminho_db: Path | str) -> BaseCanonica:
        return cls(construir_indice(caminho_db))

    # -- acesso básico ------------------------------------------------------
    def __len__(self) -> int:
        return len(self._registros)

    def registro(self, documento_id: str) -> Registro | None:
        return self._registros.get(documento_id)

    def por_id_canonico(self, id_canonico: int) -> Registro | None:
        return self._por_id.get(int(id_canonico))

    def registros(self) -> list[Registro]:
        return [self._registros[d] for d in sorted(self._registros)]

    def identificadores(self, documento_id: str) -> list[dict[str, Any]]:
        return list(self._indice["registros"][documento_id]["identificadores"])

    def cabecalho(self, documento_id: str, n: int = 600) -> str:
        return self._indice["registros"][documento_id]["cabecalho"][:n]

    # -- processos ----------------------------------------------------------
    def candidatos_por_numero(self, digitos: str) -> list[Registro]:
        """Registros cujo número PRÓPRIO tem estes dígitos canônicos.

        ``digitos`` pode ser a chave já canônica ou o trecho bruto da citação
        (é passado por :func:`digitos_canonicos` quando contém algo além de dígitos).
        """
        chave = digitos if digitos.isdigit() else digitos_canonicos(digitos)
        if not chave:
            return []
        return [self._registros[d] for d in self._por_digitos.get(chave, [])]

    def candidatos_por_numero_e_classe(
        self,
        digitos: str,
        classe: str | None,
        tribunal: str | None,
        uf: str | None = None,
        estrito: bool = False,
    ) -> list[Registro]:
        """Candidatos filtrados por tribunal, classe processual e UF.

        Ordem de desempate (ver docs/04_analise_base.md, seção h):

        1. tribunal informado → só registros daquele tribunal;
        2. UF informada → descarta registros com UF conhecida e diferente
           (registros sem UF no cabeçalho são mantidos);
        3. classe informada → se algum candidato tem a **cadeia** igual
           (``ED AGINT ARESP``), ficam só esses; senão, ficam os de classe
           principal compatível (``RESP``≈``RESPE``…); com ``estrito=True``
           exige cadeia igual;
        4. classe informada mas sem candidato compatível → lista vazia.
        """
        cands = self.candidatos_por_numero(digitos)
        if tribunal:
            cands = [r for r in cands if r.tribunal == tribunal]
        if uf:
            cands = [r for r in cands if r.uf in (None, uf)]
        cadeia = _cadeia_da_classe(classe)
        if cadeia and cands:
            alvo = " ".join(cadeia)
            exatos = [r for r in cands if r.classe_propria == alvo]
            if exatos:
                return exatos
            if estrito:
                return []
            principal = classe_principal(cadeia)
            cands = [r for r in cands if classes_compativeis(principal, r.classe_principal)]
        return cands

    # -- normativos ---------------------------------------------------------
    def sumula(self, tribunal: str | None, vinculante: bool, numero: int) -> Registro | None:
        """``(tribunal, vinculante, numero)`` → registro; tribunal ``None`` só resolve se único."""
        if tribunal:
            d = self._sumulas.get(f"{tribunal}|{int(vinculante)}|{int(numero)}")
            return self._registros[d] if d else None
        achados = [d for k, d in self._sumulas.items() if k.endswith(f"|{int(vinculante)}|{int(numero)}")]
        return self._registros[achados[0]] if len(achados) == 1 else None

    def dispositivo(self, diploma: str, artigo: str) -> Registro | None:
        """``("CPC", "321")`` → registro. Diploma canônico (ver :mod:`.normativos`)."""
        artigo = str(artigo).replace(".", "").lstrip("0")
        d = self._dispositivos.get(f"{diploma}|{artigo}")
        return self._registros[d] if d else None

    def diplomas_na_base(self) -> list[str]:
        return list(self._indice["normativos"]["diplomas_na_base"])

    # -- citações vagas -----------------------------------------------------
    def por_relator_ano(self, tribunal: str | None, ano: int | None, relator: str | None) -> list[Registro]:
        """Acórdãos que casam com (tribunal, ano, relator~). Serve para medir a
        multiplicidade das citações ``incompleta``; nunca para resolver ``real``."""
        saida = []
        for r in self.registros():
            if r.natureza != "acordao":
                continue
            if tribunal and r.tribunal != tribunal:
                continue
            if ano is not None and r.ano != int(ano):
                continue
            if relator and not relator_compativel(relator, r.relator):
                continue
            saida.append(r)
        return saida


def _cadeia_da_classe(classe: str | None) -> list[str]:
    """Aceita cadeia já canônica (``"AGINT ARESP"``) ou texto bruto (``"AgInt no AREsp"``)."""
    if not classe:
        return []
    tokens = classe.split()
    if all(t in SIGLAS_CANONICAS or re.fullmatch(r"\d+O", t) for t in tokens):
        return tokens
    return cadeia_de_classes(classe)


__all__ = ["Registro", "BaseCanonica", "relator_compativel"]
