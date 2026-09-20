"""Regras negativas: onde e quando um candidato NÃO é citação (docs/03 §6, §9.1.3).

Duas camadas:

1. **Zona proibida**: nada antes de :func:`texto.fim_do_cabecalho` — ali vivem
   ``Autos nº``/``Processo nº`` + CNJ (26/26 documentos), ``Protocolo nº``,
   ``Memorial nº``, ``PARECER JURÍDICO Nº``, ``Valor da causa: R$`` e o CNJ de
   ``Referência: autos nº``. A regra é posicional, não de forma: o conjunto
   cego pode ter cabeçalhos com CNJ "legítimos" (J ∈ {5, 6, 7}).
2. **Contexto imediato** do número (só para os padrões amplos, que não são
   ancorados numa classe): ``fls. NNN/NNN``, ``R$ NNN.NNN,NN``, ``(OAB/UF
   NNNNNN)``, ``NN%``, ``Protocolo/Memorial/Ofício nº``, ``NNN/AAAA``, datas
   por extenso (``12 de março de 2024``) e anos isolados; e, para
   ``Processo/Autos nº <número>``, o número igual ao do cabeçalho (o processo
   do próprio documento).

As frases-armadilha de §6.3 ("orientação dos tribunais superiores é firme no
ponto", "verbete sumular aplicável à espécie"…) não precisam de regra: nenhum
padrão dispara sem número, e o padrão ``vaga`` exige ano + relatoria + nome.
"""
from __future__ import annotations

import logging
import re

from ..normalizacao import numeros_com_posicao
from ..texto import fim_do_cabecalho
from ..tipos import Achado

log = logging.getLogger(__name__)

_MESES = r"(?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
_JANELA = 40

#: Contexto ANTES do início do achado (fim da janela = início do span).
_ANTES: list[tuple[str, re.Pattern[str]]] = [
    ("fls", re.compile(r"\bfls?\.?\s*$", re.I)),
    ("valor_monetario", re.compile(r"R\$\s*$")),
    ("oab", re.compile(r"\bOAB\s*/?\s*[A-Z]{0,2}\s*$")),
    ("referencia", re.compile(r"\b(?:refer[êe]ncia|ref\.?)\s*:?\s*(?:autos|processo)?\s*n?[º°o.]?\s*$", re.I)),
    ("protocolo", re.compile(
        r"\b(?:protocolo|memorial|of[íi]cio|peti[çc][ãa]o|parecer(?:\s+jur[íi]dico)?|nota\s+t[ée]cnica|"
        r"portaria|resolu[çc][ãa]o|edital|contrato|matr[íi]cula|inscri[çc][ãa]o|cnpj|cpf|rg|"
        r"cep|telefone|tel\.?|conta|ag[êe]ncia)\s*n?[º°o.]?\s*:?\s*$", re.I)),
    ("data_numerica", re.compile(r"\d{1,2}/\d{1,2}/\s*$")),
    ("ano_de_data", re.compile(rf"\d{{1,2}}\s+de\s+{_MESES}\s+d[ce]\s*$", re.I)),
]
#: Contexto DEPOIS do fim do achado.
_DEPOIS: list[tuple[str, re.Pattern[str]]] = [
    ("percentual", re.compile(r"^\s*%")),
    ("dia_de_data", re.compile(rf"^\s+de\s+{_MESES}\s+de\s+\d{{4}}", re.I)),
    ("data_numerica", re.compile(r"^/\d{1,2}/\d{2,4}")),
    ("valor_monetario", re.compile(r"^,\d{2}(?![\d])")),
]


def _numeros_do_cabecalho(texto: str, limite: int) -> set[str]:
    """Chaves canônicas dos números do cabeçalho (``Autos nº <CNJ>``): o processo do próprio documento."""
    return {dig for _, _, dig, _ in numeros_com_posicao(texto[:limite])}


def motivo_distrator(texto: str, achado: Achado, limite: int,
                     numeros_cabecalho: set[str] | None = None) -> str | None:
    """Motivo pelo qual o achado é distrator, ou ``None`` se é candidato legítimo."""
    if achado.inicio < limite:
        return "cabecalho"
    if not achado.origem.endswith(":amplo"):
        # padrões estritos: ancorados numa classe/palavra-chave conhecida; nada mais a checar
        return None
    # "Nestes autos nº <CNJ>" no corpo, com o mesmo número do cabeçalho: é o processo do
    # próprio documento, não uma citação (revisão R2-09-ii)
    if achado.familia == "processo" and achado.dados.get("digitos"):
        if numeros_cabecalho is None:
            numeros_cabecalho = _numeros_do_cabecalho(texto, limite)
        if achado.dados["digitos"] in numeros_cabecalho:
            return "numero_do_cabecalho"
    antes = texto[max(0, achado.inicio - _JANELA):achado.inicio]
    depois = texto[achado.fim:achado.fim + _JANELA]
    for nome, rx in _ANTES:
        if rx.search(antes):
            return nome
    for nome, rx in _DEPOIS:
        if rx.search(depois):
            return nome
    return None


def filtrar(texto: str, candidatos: list[Achado], limite: int | None = None) -> list[Achado]:
    """Remove os candidatos que caem numa regra negativa (com log de depuração)."""
    if limite is None:
        limite = fim_do_cabecalho(texto)
    aceitos: list[Achado] = []
    numeros_cabecalho = _numeros_do_cabecalho(texto, limite)
    for a in candidatos:
        motivo = motivo_distrator(texto, a, limite, numeros_cabecalho)
        if motivo is None:
            aceitos.append(a)
        else:
            log.debug("distrator %s em (%d,%d) %s [%s]", motivo, a.inicio, a.fim, a.familia, a.origem)
    return aceitos


__all__ = ["motivo_distrator", "filtrar"]
