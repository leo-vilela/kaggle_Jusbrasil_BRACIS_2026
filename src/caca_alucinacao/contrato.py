"""Contrato de saída (schema 1.2) do desafio: tipos, escrita e validação.

Formato exato de um arquivo ``<documento_id>.json``::

    {
      "schema_version": "1.2",
      "documento_id": "gen_n1_001",
      "citacoes": [
        {
          "id": "c1",
          "inicio": 589,
          "fim": 652,
          "trecho": "…",
          "tipo": "jurisprudencia" | "lei",
          "classificacao": "real" | "inventada" | "incompleta",
          "resolucao": {"fonte": "jusbrasil", "id_canonico": "1234567890"} | null,
          "confianca": 0.93
        }
      ]
    }

Regras (todas conferidas por :func:`validar`, que espelha o que o
``kaggle_metric.py`` oficial rejeita, mais o que o contrato exige):

* offsets em **codepoints**, ``fim`` exclusivo, ``0 <= inicio < fim``;
* ``trecho == texto[inicio:fim]`` (literal, com quebras de linha e NBSP);
* ``resolucao`` só existe em ``real`` (``id_canonico`` = string só de dígitos);
  nas demais classes é ``null``;
* ``confianca`` em ``[0, 1]`` (ou ``null`` = não informada — sem bônus);
* **duas citações do mesmo documento com IoU ≥ 0,5 invalidam a submissão**;
* ids ``c1..cN`` únicos, atribuídos em ordem de posição por
  :meth:`SaidaDocumento.montar`.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import FONTE, IOU_MIN, SCHEMA_VERSION
from .tipos import CLASSIFICACOES, TIPOS, iou

log = logging.getLogger(__name__)

CHAVES_CITACAO = ("id", "inicio", "fim", "trecho", "tipo", "classificacao", "resolucao", "confianca")
CHAVES_SAIDA = ("schema_version", "documento_id", "citacoes")


class ErroContrato(ValueError):
    """Saída que viola o contrato; ``erros`` traz a lista completa."""

    def __init__(self, erros: list[str]) -> None:
        super().__init__("; ".join(erros))
        self.erros = list(erros)


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Citacao:
    """Uma citação já resolvida, pronta para o JSON.

    ``id_canonico`` é guardado como **string de dígitos** (o exemplo oficial
    usa string; a métrica normaliza zeros à esquerda). ``confianca`` ``None``
    significa "não informada" (a métrica não dá bônus nem pune).
    """

    id: str
    inicio: int
    fim: int
    trecho: str
    tipo: str
    classificacao: str
    id_canonico: str | None = None
    confianca: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.id_canonico, int) and not isinstance(self.id_canonico, bool):
            object.__setattr__(self, "id_canonico", str(self.id_canonico))
        if self.confianca is not None:
            object.__setattr__(self, "confianca", float(self.confianca))

    @property
    def resolucao(self) -> dict[str, str] | None:
        """``{"fonte": "jusbrasil", "id_canonico": "…"}`` em ``real``; senão ``None``."""
        if self.classificacao == "real" and self.id_canonico is not None:
            return {"fonte": FONTE, "id_canonico": str(self.id_canonico)}
        return None

    def para_dicionario(self) -> dict[str, Any]:
        """Dicionário na ordem exata de chaves do contrato."""
        return {
            "id": self.id,
            "inicio": self.inicio,
            "fim": self.fim,
            "trecho": self.trecho,
            "tipo": self.tipo,
            "classificacao": self.classificacao,
            "resolucao": self.resolucao,
            "confianca": self.confianca,
        }

    @classmethod
    def de_dicionario(cls, d: dict[str, Any]) -> Citacao:
        """Constrói a partir do dicionário do JSON (sem validar: use :func:`validar`)."""
        resol = d.get("resolucao") or {}
        idc = resol.get("id_canonico") if isinstance(resol, dict) else None
        return cls(
            id=str(d.get("id", "")),
            inicio=d["inicio"],
            fim=d["fim"],
            trecho=d.get("trecho", ""),
            tipo=d.get("tipo", ""),
            classificacao=d.get("classificacao", ""),
            id_canonico=None if idc is None else str(idc),
            confianca=d.get("confianca"),
        )


@dataclass
class SaidaDocumento:
    """O JSON de um documento."""

    documento_id: str
    citacoes: list[Citacao] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def montar(cls, documento_id: str, citacoes: list[Citacao]) -> SaidaDocumento:
        """Ordena por posição e (re)atribui ids ``c1..cN``."""
        ordenadas = sorted(citacoes, key=lambda c: (c.inicio, c.fim))
        renumeradas = [
            Citacao(
                id=f"c{i}",
                inicio=c.inicio,
                fim=c.fim,
                trecho=c.trecho,
                tipo=c.tipo,
                classificacao=c.classificacao,
                id_canonico=c.id_canonico,
                confianca=c.confianca,
            )
            for i, c in enumerate(ordenadas, start=1)
        ]
        return cls(documento_id=documento_id, citacoes=renumeradas)

    def para_dicionario(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "documento_id": self.documento_id,
            "citacoes": [c.para_dicionario() for c in self.citacoes],
        }

    def para_json(self) -> str:
        """JSON UTF-8 legível (``ensure_ascii=False``, ``indent=2``), com ``\\n`` final."""
        return json.dumps(self.para_dicionario(), ensure_ascii=False, indent=2) + "\n"

    def escrever(self, caminho: Path | str) -> Path:
        """Escreve ``caminho`` (cria a pasta se preciso) e devolve o ``Path``."""
        destino = Path(caminho)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(self.para_json(), encoding="utf-8")
        return destino

    @classmethod
    def de_dicionario(cls, d: dict[str, Any]) -> SaidaDocumento:
        return cls(
            documento_id=str(d.get("documento_id", "")),
            citacoes=[Citacao.de_dicionario(c) for c in d.get("citacoes", [])],
            schema_version=str(d.get("schema_version", "")),
        )


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
def carregar(caminho: Path | str, texto: str | None = None, estrito: bool = True) -> SaidaDocumento:
    """Lê um JSON do contrato. Com ``estrito`` levanta :class:`ErroContrato` se inválido."""
    caminho = Path(caminho)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if estrito:
        erros = validar(dados, texto)
        if erros:
            raise ErroContrato([f"{caminho.name}: {e}" for e in erros])
    return SaidaDocumento.de_dicionario(dados)


def carregar_citacoes(caminho: Path | str, texto: str | None = None) -> list[Citacao]:
    """Lista de :class:`Citacao` de um JSON válido (ordem de posição)."""
    saida = carregar(caminho, texto, estrito=True)
    return sorted(saida.citacoes, key=lambda c: (c.inicio, c.fim))


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------
def _e_inteiro(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _e_numero(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validar_citacao(i: int, c: Any, texto: str | None, erros: list[str]) -> tuple[int, int] | None:
    """Confere uma citação; devolve ``(inicio, fim)`` se o span for utilizável."""
    rotulo = f"citação #{i + 1}"
    if not isinstance(c, dict):
        erros.append(f"{rotulo}: deve ser um objeto JSON")
        return None
    rotulo = f"citação #{i + 1} ({c.get('id', '?')})"
    faltam = [k for k in CHAVES_CITACAO if k not in c]
    if faltam:
        erros.append(f"{rotulo}: campos ausentes {faltam}")
    extras = sorted(set(c) - set(CHAVES_CITACAO))
    if extras:
        erros.append(f"{rotulo}: campos desconhecidos {extras}")

    idc = c.get("id")
    if not isinstance(idc, str) or not idc.strip():
        erros.append(f"{rotulo}: 'id' deve ser string não vazia")

    inicio, fim = c.get("inicio"), c.get("fim")
    span_ok = True
    if not _e_inteiro(inicio):
        erros.append(f"{rotulo}: 'inicio' deve ser inteiro; recebido {inicio!r}")
        span_ok = False
    if not _e_inteiro(fim):
        erros.append(f"{rotulo}: 'fim' deve ser inteiro; recebido {fim!r}")
        span_ok = False
    if span_ok and (inicio < 0 or fim <= inicio):
        erros.append(f"{rotulo}: span inválido ({inicio}, {fim}); exige 0 <= inicio < fim")
        span_ok = False

    trecho = c.get("trecho")
    if not isinstance(trecho, str) or trecho == "":
        erros.append(f"{rotulo}: 'trecho' deve ser string não vazia")
    elif span_ok:
        if len(trecho) != fim - inicio:
            erros.append(f"{rotulo}: len(trecho)={len(trecho)} difere de fim-inicio={fim - inicio}")
        if texto is not None:
            if fim > len(texto):
                erros.append(f"{rotulo}: fim={fim} ultrapassa o texto (len={len(texto)})")
            elif texto[inicio:fim] != trecho:
                erros.append(f"{rotulo}: trecho difere de texto[{inicio}:{fim}]")

    tipo = c.get("tipo")
    if tipo not in TIPOS:
        erros.append(f"{rotulo}: 'tipo' {tipo!r} inválido; use {' | '.join(TIPOS)}")

    classe = c.get("classificacao")
    if classe not in CLASSIFICACOES:
        erros.append(f"{rotulo}: 'classificacao' {classe!r} inválida; use {' | '.join(CLASSIFICACOES)}")

    resol = c.get("resolucao")
    if classe == "real":
        if not isinstance(resol, dict):
            erros.append(f"{rotulo}: classificacao=real exige 'resolucao' {{fonte, id_canonico}}")
        else:
            if resol.get("fonte") != FONTE:
                erros.append(f"{rotulo}: resolucao.fonte deve ser {FONTE!r}; recebido {resol.get('fonte')!r}")
            idcan = resol.get("id_canonico")
            if not isinstance(idcan, str) or not idcan.isdigit():
                erros.append(
                    f"{rotulo}: resolucao.id_canonico deve ser string só de dígitos; recebido {idcan!r}"
                )
            extras_r = sorted(set(resol) - {"fonte", "id_canonico"})
            if extras_r:
                erros.append(f"{rotulo}: resolucao com campos desconhecidos {extras_r}")
    elif classe in CLASSIFICACOES and resol is not None:
        erros.append(f"{rotulo}: 'resolucao' deve ser null quando classificacao={classe}")

    conf = c.get("confianca")
    if conf is not None:
        if not _e_numero(conf):
            erros.append(f"{rotulo}: 'confianca' deve ser número em [0, 1]; recebido {conf!r}")
        elif math.isnan(float(conf)) or not (0.0 <= float(conf) <= 1.0):
            erros.append(f"{rotulo}: 'confianca' {conf} fora de [0, 1]")

    return (inicio, fim) if span_ok else None


def validar_citacao(i: int, c: Any, texto: str | None = None) -> list[str]:
    """Violações de UMA citação (índice ``i``, base 0), sem remontar o documento.

    Mesmas regras de :func:`validar` para o item (campos, tipos, span, trecho,
    classe × resolução, confiança); a sobreposição entre citações e a
    unicidade dos ids só se conferem no documento inteiro.
    """
    erros: list[str] = []
    _validar_citacao(i, c, texto, erros)
    return erros


def validar(saida: Any, texto: str | None = None) -> list[str]:
    """Lista de violações (vazia = válido). Cobre tudo que a métrica rejeita.

    ``texto`` (opcional) habilita a conferência ``trecho == texto[inicio:fim]``.
    """
    erros: list[str] = []
    if not isinstance(saida, dict):
        return ["a saída deve ser um objeto JSON"]

    sv = saida.get("schema_version")
    if sv != SCHEMA_VERSION:
        erros.append(f"schema_version deve ser {SCHEMA_VERSION!r}; recebido {sv!r}")
    doc = saida.get("documento_id")
    if not isinstance(doc, str) or not doc.strip():
        erros.append("documento_id deve ser string não vazia")
    extras = sorted(set(saida) - set(CHAVES_SAIDA))
    if extras:
        erros.append(f"campos desconhecidos na raiz: {extras}")

    citacoes = saida.get("citacoes")
    if not isinstance(citacoes, list):
        erros.append("'citacoes' deve ser uma lista (vazia se não houver citação)")
        return erros

    spans: list[tuple[int, int, int]] = []
    ids_vistos: dict[str, int] = {}
    for i, c in enumerate(citacoes):
        span = _validar_citacao(i, c, texto, erros)
        if span is not None:
            spans.append((i, span[0], span[1]))
        if isinstance(c, dict) and isinstance(c.get("id"), str):
            if c["id"] in ids_vistos:
                erros.append(f"citação #{i + 1}: id {c['id']!r} repetido (já usado na #{ids_vistos[c['id']] + 1})")
            else:
                ids_vistos[c["id"]] = i

    # Erro fatal da métrica: duas predições com IoU >= 0,5 no mesmo documento.
    for a in range(len(spans)):
        ia, a0, a1 = spans[a]
        for b in range(a + 1, len(spans)):
            ib, b0, b1 = spans[b]
            v = iou(a0, a1, b0, b1)
            if v >= IOU_MIN:
                erros.append(
                    f"FATAL: citações #{ia + 1} ({a0},{a1}) e #{ib + 1} ({b0},{b1}) "
                    f"se sobrepõem com IoU={v:.2f} >= {IOU_MIN}"
                )
    return erros


def validar_arquivo(caminho: Path | str, texto: str | None = None) -> list[str]:
    """Lê e valida um JSON; erro de leitura/parsing vira uma violação."""
    caminho = Path(caminho)
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"não foi possível ler {caminho.name}: {exc}"]
    erros = validar(dados, texto)
    if isinstance(dados, dict) and dados.get("documento_id") not in (None, caminho.stem):
        erros.append(f"documento_id {dados.get('documento_id')!r} difere do nome do arquivo {caminho.stem!r}")
    return erros


__all__ = [
    "Citacao", "SaidaDocumento", "ErroContrato", "CHAVES_CITACAO", "CHAVES_SAIDA",
    "carregar", "carregar_citacoes", "validar", "validar_citacao", "validar_arquivo",
]
