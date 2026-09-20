"""Família ``tema``: ``Tema N da repercussão geral`` (docs/03 §5; 1 caso no dev, com OCR na palavra).

A palavra e o complemento toleram o OCR medido em docs/03 §3.1 (``e``→``c``,
``a``→``ã``, ``u``→``ü``, ``m``→``rn``, ``o``→``0``; ``TEMA``); o número tolera
letras confundíveis coladas (``l.234``, ``1.23O``), convertidas pelo mapa
inverso do gerador e registradas em ``letras_ocr`` (revisão rodada 2, R4-01/02).

Fronteira: de ``Tema`` até o fim do complemento (``da repercussão geral`` entra;
também ``do STF``, ``/STF``, ``dos recursos repetitivos``, ``Tema Repetitivo N``).
Sem complemento o achado sai com força 0,7 (``regex:tema:sem_complemento``) e é
emitido como ``inventada`` **só quando há um indício jurisprudencial a ≤ 80
caracteres, na mesma frase** (``afetado``, ``repercussão``, ``repetitivo``, ``STF``/``STJ``, ``tese``,
``julgamento``, ``precedente``…; rodada 4, R6-16): "Tema 1.234" pode ser um tema de
repercussão geral ou um item de sumário (``Tema 3: Da prescrição``) — sem o indício
a força cai a 0,4 e a resolução descarta. Aposta documentada na ADR 0005.
A base não tem temas: ``tema`` ⇒ ``inventada`` (docs/04 e).
"""
from __future__ import annotations

import logging
import re

from ..tipos import Achado
from . import padroes as P
from .sumula import numero_com_ocr

log = logging.getLogger(__name__)

#: ``da repercussão geral``/``dos recursos repetitivos``/``do STF`` com a tolerância de OCR
#: de ``padroes._regex_palavra`` (``repercüssão``, ``rcpercussão``, ``d0``; revisão rodada 2, R4-03).
_D_OA = rf"(?:{P.P_DO}|{P.P_DA}|[dD][oOaA0ã])"
_COMPLEMENTO = (
    rf"(?:{P.S}(?:{P.P_DA}|{P.P_DE}){P.S}{P.regex_extenso('repercussao geral', inicial_maiuscula=False)}"
    rf"|{P.S}{_D_OA}s?{P.S}{P.regex_extenso('recursos repetitivos', inicial_maiuscula=False)}"
    rf"|{P.S}{_D_OA}{P.S}(?:{P.TRIBUNAL_SIGLA}|{P.TRIBUNAL_EXTENSO})"
    rf"|\s{{0,2}}/\s{{0,2}}{P.TRIBUNAL_SIGLA})(?![A-Za-zÀ-ÿ])"
)
_NUM_TEMA = rf"[\d{P.LETRAS_OCR}]{{1,4}}(?:\.[\d{P.LETRAS_OCR}]{{3}})?(?![A-Za-zÀ-ÿ0-9])"
#: Indício jurisprudencial em torno de um ``Tema N`` sem complemento (rodada 4, R6-16).
#: Só palavras ligadas a temas de repercussão geral/repetitivos — nunca as genéricas da prosa
#: forense (``recurso``, ``tribunal``, ``corte``), que também cercam um item de sumário.
_RE_INDICIO_JURISPRUDENCIAL = re.compile(
    r"repercuss|repetitiv|afetad|sobrest|vinculant|precedente|julgad|julgamento|\btese|controv[ée]rsia"
    r"|STF|STJ|TST|TSE|STM|supremo|ac[óo]rd[ãa]o|firmad|fixad|paradigma",
    re.I,
)
JANELA_INDICIO = 80
FORCA_SEM_COMPLEMENTO = 0.7
FORCA_SEM_INDICIO = 0.4
_RE_FIM_DE_FRASE = re.compile(r"[.;!?]\s|\n\s*\n")


def _mesma_frase(texto: str, inicio: int, fim: int) -> str:
    """Até ``JANELA_INDICIO`` caracteres antes e depois do span, sem atravessar um fim de frase."""
    antes = texto[max(0, inicio - JANELA_INDICIO):inicio]
    cortes = [m.end() for m in _RE_FIM_DE_FRASE.finditer(antes)]
    if cortes:
        antes = antes[cortes[-1]:]
    depois = texto[fim:fim + JANELA_INDICIO]
    m = _RE_FIM_DE_FRASE.search(depois)
    if m:
        depois = depois[:m.start()]
    return antes + depois


RE_TEMA = re.compile(
    rf"""
    (?<![A-Za-zÀ-ÿ])
    (?P<palavra>T[ec]m[aã]|T[EC]M[AÃ])(?P<rep>{P.S}[Rr]epetitivo)?{P.S}
    (?:{P.CONECTOR}{P.S0})?
    (?P<num>{_NUM_TEMA})
    (?P<compl>{_COMPLEMENTO})?
    """,
    re.VERBOSE,
)


def detectar(texto: str) -> list[Achado]:
    """Todos os temas do texto, na ordem."""
    saida: list[Achado] = []
    for m in RE_TEMA.finditer(texto):
        inicio, fim = m.start(), m.end()
        numero, letras_ocr = numero_com_ocr(m.group("num"))
        if not numero:
            continue  # "Tema I" não tem dígito
        compl = m.group("compl") or ""
        tribunal = "STF"
        if m.group("rep"):
            # ``Tema Repetitivo 988``: o adjetivo é o complemento (STJ; rodada 4, R6-16)
            compl = compl or m.group("rep")
            tribunal = "STJ"
        if "STJ" in compl or "petitiv" in compl or "ustiça" in compl or "ustica" in compl:
            tribunal = "STJ"
        dados = {
            "classe": "",
            "cadeia": "",
            "classe_principal": "",
            "numero": m.group("num"),
            "digitos": numero,
            "formato": "",
            "uf": "",
            "tribunal": tribunal,
            "ano": "",
            "relator": "",
            "artigo": "",
            "diploma": "",
            "numero_sumula": "",
            "vinculante": "",
            "numero_tema": numero,
            "letras_ocr": str(letras_ocr),
        }
        if compl:
            saida.append(Achado(inicio, fim, texto[inicio:fim], "tema", "jurisprudencia", dados,
                                "regex:tema", 1.0))
        else:
            # ``Tema 1234`` solto: só com indício jurisprudencial em volta (R6-16); a resolução
            # descarta abaixo de ``FORCA_MINIMA_SEM_CANDIDATO`` (0,7) — o achado fica no rastro
            com_indicio = bool(_RE_INDICIO_JURISPRUDENCIAL.search(_mesma_frase(texto, inicio, fim)))
            dados["indicio_jurisprudencial"] = "1" if com_indicio else "0"
            saida.append(Achado(inicio, fim, texto[inicio:fim], "tema", "jurisprudencia", dados,
                                "regex:tema:sem_complemento",
                                FORCA_SEM_COMPLEMENTO if com_indicio else FORCA_SEM_INDICIO))
    log.debug("tema: %d achados", len(saida))
    return saida


__all__ = ["RE_TEMA", "detectar"]
