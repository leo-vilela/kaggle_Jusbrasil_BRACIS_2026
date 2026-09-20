"""Família ``dispositivo`` (tipo ``lei``): ``art. N[º][, inciso][, alínea][, §] d[ao] <diploma>``.

Fronteira (docs/03 §1, §4): de ``art.``/``art``/``artigo``/``Art.``/``art.º``
até o **fim do nome do diploma**, inclusive número e ano de lei (``da Lei nº
13.105/2015``, ``da Lei Complementar nº 64/1990``, ``do Decreto-Lei nº
5.452/1943``, ``da Lei nº 13.105, de 16 de março de 2015``), nome por extenso
com quebra de linha e OCR (``Constituição\\nFederal``, ``Constituição Fcderal``,
``Código\\nde Processo Penal``) ou sigla com ano (``CF/88``, ``CPC/2015``).
Incisos, alíneas e parágrafos entre o artigo e o diploma entram; vírgula e
ponto finais ficam fora.

O diploma canônico vem de ``normativos.diploma_canonico`` (``CPC``, ``CF``,
``LC64``, ``LEI-9504``…); códigos identificáveis que a base não cobre recebem
uma sigla própria (``CP``, ``CTN``, ``ECA``…) e o resto ``OUTRO`` — nunca vazio
quando há um diploma reconhecível (a resolução trata "fora da base" como
``inventada``, não ``incompleta``; docs/04 h.9).

Padrão amplo (``regex:dispositivo:amplo``, força 0,4): ``art. N`` sem diploma
reconhecível. No dev todo ``art.`` do corpo tem diploma e está no gabarito, por
isso o amplo não dispara ali. A resolução o classifica ``incompleta`` (sem
diploma) e, por ser amplo sem respaldo na base, o **descarta** (ADR 0006 §8):
ele existe para diagnóstico e para o árbitro, não para emissão.
"""
from __future__ import annotations

import logging
import re

from ..base_canonica.normativos import diploma_canonico
from ..normalizacao import CONFUSOES, chave_textual
from ..tipos import Achado
from . import padroes as P

log = logging.getLogger(__name__)

#: ``art.``/``art``/``arts.``/``artigo(s)``/``Art.``/``art.º`` com o OCR medido em docs/03 §3.1
#: (``i``→``l``/``1``, ``a``→``ã``, ``o``→``0``: ``artlgo``, ``ãrt.``, ``Art1go``; revisão rodada 3,
#: R5-02) — a mesma tolerância das palavras ``Súmula``/``Tema`` e dos nomes de diploma. A
#: inicial continua presa a ``[AaÃã]`` e o ``t`` é literal (``ar1.`` não é ``art.``).
_ART = r"(?:[AaÃã]r[tT](?:[il1I]g[oa0ã]s?|s)?\.?(?:\s?º)?|ARTIGOS?|ARTS?\.?)"
#: Letras confundíveis que podem fechar o número do artigo (``89G``, ``47S``, ``373l``):
#: todas as de :data:`padroes.LETRAS_OCR` menos o ``o`` minúsculo, que no fim do número é
#: o ordinal (``5o`` = ``5º``) — ``o`` só conta como OCR quando seguido de dígito (``1o26``).
_LETRAS_FIM = P.LETRAS_OCR.replace("o", "")
#: Número do artigo: dígitos e pontos, com letras de OCR em qualquer posição (revisão
#: rodada 2, R4-03): 1–2 letras no lugar do primeiro dígito (``l86``, ``lO2``, só se
#: seguidas de dígito), letras no meio (``3l2``, ``1.O26``) e letras no fim (``89G``,
#: ``373l``), nunca seguidas de letra comum. O canônico vem de :func:`_artigo_canonico`.
#: Só no padrão estrito (com diploma) o número pode ser 1–2 letras confundíveis sem dígito
#: (``art. g do Código Penal Militar`` = ``art. 9``): o diploma garante que é citação.
_NUM_ART = (
    rf"(?:[{P.LETRAS_OCR}]{{1,2}}(?=\d))?"
    rf"\d(?:[\d.]|[{P.LETRAS_OCR}](?=[\d.{P.LETRAS_OCR}])|[{_LETRAS_FIM}](?![A-Za-zÀ-ÿ0-9])){{0,6}}"
)
#: Ordinal: ``5º``, ``5o``, ``5°``, ``5ª``, ``5.º`` (ponto antes do ordinal, também em ``§ 8.º``).
_ORDINAL = r"(?:\.?\s?[ºo°ª])?"
_SUFIXO = r"(?:-[A-Z])?"
_ASPAS = "['\"‘’“”«»]"
_ROMANO = r"[IVXLC]{1,8}"
#: Alínea de uma letra minúscula sem aspas logo depois de um inciso (``I, g,``; revisão
#: rodada 2, R4-06): só nessa posição — sozinha, uma letra é artigo/preposição da prosa.
_ALINEA_APOS_INCISO = r"(?:\s{0,2},\s{0,2}[a-z](?![A-Za-zÀ-ÿ/]))?"   # ``, c/c`` não é alínea
#: Alínea de uma letra ENTRE vírgulas sem inciso (``art. 12, a, da CLT``; forma corrente no TST —
#: rodada 4, R6-09): só quando o que segue é a preposição do diploma (``, d[ao]``) ou uma sigla de
#: diploma — sozinha, uma letra é artigo/preposição da prosa.
_ALINEA_ISOLADA = (
    rf"[a-z](?![A-Za-zÀ-ÿ])(?=\s{{0,2}},{P.S}(?:(?:[aA][mM][bB][oa][sS]|[tT][oO][dD][oa][sS]){P.S})?"
    rf"(?:[dD][aoAO0ã][sS]?{P.S}|{P.DIPLOMA_SIGLA}))"
)
_ITEM = (
    r"(?:"
    rf"§{P.S0}\d{{1,3}}{_ORDINAL}{_SUFIXO}"                         # § 1º-A, § 8.º
    rf"|§§{P.S0}\d{{1,3}}{_ORDINAL}{P.S0}(?:e|a){P.S0}\d{{1,3}}{_ORDINAL}"  # §§ 1º e 2º
    rf"|[Pp]ar[áa]grafo{P.S}[úu]nico|PAR[ÁA]GRAFO{P.S}[ÚU]NICO"
    r"|[Cc]aput|CAPUT"
    rf"|(?:[Ii]nc(?:[Ii]s[Oo])?[Ss]?\.?|INC(?:ISO)?S?\.?){P.S}{_ROMANO}(?:{P.S}(?:e|a){P.S}{_ROMANO})?{_ALINEA_APOS_INCISO}"
    rf"|{_ROMANO}(?:{P.S}(?:e|a){P.S}{_ROMANO})?(?![A-Za-zÀ-ÿ]){_ALINEA_APOS_INCISO}"   # IV, LV, XXIX, I e II, I, g
    rf"|(?:[Aa]l[íi]nea|AL[ÍI]NEA){P.S}{_ASPAS}?[a-z]{_ASPAS}?"
    rf"|{_ASPAS}[a-z]{_ASPAS}"                                       # 'c', "g"
    rf"|{_ALINEA_ISOLADA}"                                            # 12, a, da CLT
    rf"|e{P.S}\d{{1,4}}(?:\.\d{{3}})?{_ORDINAL}{_SUFIXO}"           # arts. 5º e 7º, 373 e 1.022
    # enumeração de artigos com o diploma no fim (revisão rodada 3, R3-04): ``arts. 12, 34 e 56 da CF``
    # (número solto depois de vírgula/``e``), ``art. 12 c/c o art. 1.234, ambos do CPC`` (a palavra
    # ``art.`` repetida, com artigo definido opcional). Só no estrito o diploma fecha o span; o amplo
    # continua descartado pela resolução.
    rf"|(?:[oa]{P.S})?{_ART}{P.S0}\d{{1,4}}(?:\.\d{{3}})?{_ORDINAL}{_SUFIXO}(?![\d])"
    rf"|\d{{1,4}}(?:\.\d{{3}})?{_ORDINAL}{_SUFIXO}(?![\d./\-])"
    rf"|(?:[Pp]arte|PARTE){P.S}(?:[Ff]inal|FINAL|[Ii]nicial|INICIAL)|in{P.S}fine"   # parte final, in fine
    rf"|(?:[Pp]rimeira|PRIMEIRA|[Ss]egunda|SEGUNDA){P.S}(?:[Pp]arte|PARTE)"
    r")"
)
#: Itens em sequência, separados por vírgula e/ou ``e``/``c/c`` (``caput e § 8º``; revisão rodada 2, R4-06).
_COMPLEMENTO = rf"(?:\s{{0,2}},?\s{{0,4}}(?:(?:e|c/c){P.S})?{_ITEM})*"
#: ``do``/``da``/``dos``/``das`` em qualquer caixa (``DA CONSTITUIÇÃO``) e com o OCR ``o``→``0``,
#: ``a``→``ã`` (``d0 Código``; revisão rodada 2, R4-03/R4-07).
#: ``, ambos do CPC``/``, todos da CF`` antes da preposição (revisão rodada 3, R3-04).
_AMBOS = r"(?:[aA][mM][bB][oa][sS]|[tT][oO][dD][oa][sS])"
_PREPOSICAO = rf"\s{{0,2}},?{P.S}(?:{_AMBOS}{P.S})?[dD][aoAO0ã][sS]?{P.S}"
#: Sigla do diploma SEM preposição, depois de vírgula ou espaço (``art. 12, caput, CPP``,
#: ``art. 34, CF/88``, ``art 56 CF``; forma telegráfica corrente — revisão rodada 3, R3-07). Só
#: com sigla (o nome por extenso sem preposição não ocorre) e, por isso, só no estrito.
_SEM_PREPOSICAO = rf"(?:\s{{0,2}},{P.S0}|{P.S})(?:{_AMBOS}{P.S})?"

RE_DISPOSITIVO = re.compile(
    rf"""
    (?<![A-Za-zÀ-ÿ])
    (?P<art>{_ART}){P.S0}
    (?P<num>{_NUM_ART}|[{_LETRAS_FIM}]{{1,2}}(?![A-Za-zÀ-ÿ0-9])){_ORDINAL}{_SUFIXO}(?![\d])
    (?P<compl>{_COMPLEMENTO})
    (?:
        (?P<prep>{_PREPOSICAO})(?P<diploma>{P.DIPLOMA})
      | (?P<sem_prep>{_SEM_PREPOSICAO})(?P<diploma_sigla>{P.DIPLOMA_SIGLA})
    )
    """,
    re.VERBOSE,
)
RE_DISPOSITIVO_AMPLO = re.compile(
    rf"""
    (?<![A-Za-zÀ-ÿ])
    (?P<art>{_ART}){P.S0}
    (?P<num>{_NUM_ART}){_ORDINAL}{_SUFIXO}(?![\d])
    (?P<compl>{_COMPLEMENTO})
    """,
    re.VERBOSE,
)

#: Diplomas que ``normativos`` não conhece (ou classifica mal): chave textual → sigla.
_DIPLOMAS_EXTRA: dict[str, str] = {
    "codigo de processo penal militar": "CPPM", "cppm": "CPPM",
    "codigo penal": "CP", "cp": "CP",
    "codigo tributario nacional": "CTN", "ctn": "CTN",
    "codigo de transito brasileiro": "CTB", "ctb": "CTB",
    "estatuto da crianca e do adolescente": "ECA", "eca": "ECA",
    "lei de execucao penal": "LEP", "lei de execucoes penais": "LEP", "lep": "LEP",
    "codigo florestal": "CFLO", "codigo de aguas": "CAGUAS", "codigo brasileiro de aeronautica": "CBA",
    "estatuto do idoso": "EIDOSO", "estatuto da cidade": "ECIDADE", "lei maria da penha": "LEI-11340",
    "lei de improbidade administrativa": "LEI-8429", "lei de licitacoes": "LEI-8666",
    "lei dos juizados especiais": "LEI-9099", "lei das eleicoes": "LEI-9504",
    "lei dos partidos politicos": "LEI-9096", "lei organica da magistratura nacional": "LOMAN",
    "loman": "LOMAN", "lei de drogas": "LEI-11343", "lei de falencias": "LEI-11101",
    "lei do inquilinato": "LEI-8245", "lei de introducao as normas do direito brasileiro": "LINDB",
    "lindb": "LINDB", "ristf": "RISTF", "ristj": "RISTJ", "ritse": "RITSE", "ritst": "RITST",
    "ristm": "RISTM", "regimento interno do supremo tribunal federal": "RISTF",
    "regimento interno do superior tribunal de justica": "RISTJ",
    "regimento interno do tribunal superior eleitoral": "RITSE",
    "regimento interno do tribunal superior do trabalho": "RITST",
    "regimento interno do superior tribunal militar": "RISTM",
}
_RE_ANO_SUFIXO = re.compile(r"\s*(?:/\d{2,4}|de\s+\d{4})$")
#: ``art.`` repetido dentro do complemento (``art. 12, I e II, c/c o art. 34 da CLT``; rodada 4,
#: R6-10): sem a marca de diploma comum (``ambos/todos do``) o diploma só pertence ao ÚLTIMO
#: artigo — o span estrito começa nele e o primeiro fica como amplo (descartado pela resolução).
_RE_ART_REPETIDO = re.compile(rf"(?<![A-Za-zÀ-ÿ]){_ART}{P.S0}\d")
_RE_AMBOS = re.compile(rf"(?:[aA][mM][bB][oa][sS]|[tT][oO][dD][oa][sS]){P.S}")
_RE_SIGLA_PONTUADA = re.compile(r"(?:[A-Z]\.){1,5}[A-Z]?\.?(?:/\d{2,4})?")


def diploma_canonico_da_superficie(diploma: str) -> str:
    """Sigla canônica do diploma citado; ``OUTRO`` se reconhecível mas sem sigla.

    ``"CPC"``/``"Lei nº 13.105/2015"`` → ``CPC``; ``"Constituição Fcderal"`` → ``CF``;
    ``"Lei nº 9.504/1997"`` → ``LEI-9504``; ``"Código Penal"`` → ``CP``;
    ``"Código de Processo Penal Militar"`` → ``CPPM`` (antes de ``normativos``, que
    diria ``CPP``); ``"Resolução nº 23.610/2019"`` → ``OUTRO``.
    """
    if _RE_SIGLA_PONTUADA.fullmatch(diploma.strip()):
        diploma = diploma.replace(".", "")          # ``C.P.C.`` → ``CPC`` (rodada 3, R3-07)
    chave = chave_textual(diploma)
    chave_sem_ano = _RE_ANO_SUFIXO.sub("", chave)
    if chave_sem_ano in _DIPLOMAS_EXTRA:
        return _DIPLOMAS_EXTRA[chave_sem_ano]
    canonico = diploma_canonico(diploma)
    if canonico:
        return canonico
    return "OUTRO"


def _artigo_canonico(num: str) -> str:
    """``"1.026"`` → ``"1026"``; ``"3l2"`` → ``"312"``; ``"l86"`` → ``"186"``; ``"89G"`` → ``"896"``; ``"05"`` → ``"5"``.

    Todas as letras confundíveis viram o dígito do mapa inverso do gerador
    (:data:`normalizacao.CONFUSOES`): a regex já garante que o número tem ao menos um
    dígito e que as letras estão coladas a ele — nunca se lê só o prefixo numérico.
    """
    dig = "".join(CONFUSOES.get(c, c) for c in num if c.isdigit() or c in CONFUSOES)
    return dig.lstrip("0") or "0"


def _dados(num: str, diploma_sup: str, compl: str) -> dict[str, str]:
    artigo = _artigo_canonico(num)
    letras_ocr = sum(1 for c in num if c in CONFUSOES)
    return {
        "classe": "",
        "cadeia": "",
        "classe_principal": "",
        "numero": num,
        "digitos": artigo,
        "formato": "",
        "uf": "",
        "tribunal": "",
        "ano": "",
        "relator": "",
        "artigo": artigo,
        "diploma": diploma_canonico_da_superficie(diploma_sup) if diploma_sup else "",
        "diploma_superficie": " ".join(diploma_sup.split()),
        "complemento": " ".join(compl.split()),
        "letras_ocr": str(letras_ocr),
        "numero_sumula": "",
        "vinculante": "",
        "numero_tema": "",
    }


def _ultimo_art_repetido(m: re.Match[str]) -> int | None:
    """Offset do último ``art. N`` dentro do complemento quando o diploma não é comum (R6-10)."""
    compl = m.group("compl") or ""
    if not compl:
        return None
    ultimo = None
    for r in _RE_ART_REPETIDO.finditer(compl):
        ultimo = r
    if ultimo is None:
        return None
    prep = m.group("prep") or m.group("sem_prep") or ""
    if _RE_AMBOS.search(prep):
        return None   # ``, ambos do CPC``: um só span (R3-04)
    return m.start("compl") + ultimo.start()


def detectar_estrito(texto: str) -> list[Achado]:
    """``art. N … d[ao] <diploma>`` (força 1,0)."""
    saida: list[Achado] = []
    pos = 0
    while True:
        m = RE_DISPOSITIVO.search(texto, pos)
        if m is None:
            break
        pos = m.end()
        recomeco = _ultimo_art_repetido(m)
        if recomeco is not None:
            m2 = RE_DISPOSITIVO.match(texto, recomeco)
            if m2 is not None:
                log.debug("dispositivo: ``art.`` repetido sem diploma comum; span estrito recomeça em %d", recomeco)
                m = m2
                pos = m.end()
        inicio, fim = m.start(), m.end()
        dados = _dados(m.group("num"), m.group("diploma") or m.group("diploma_sigla"), m.group("compl"))
        saida.append(Achado(inicio, fim, texto[inicio:fim], "dispositivo", "lei", dados,
                            "regex:dispositivo", 1.0))
    return saida


def detectar_amplo(texto: str) -> list[Achado]:
    """``art. N`` sem diploma reconhecível (força 0,4)."""
    saida: list[Achado] = []
    for m in RE_DISPOSITIVO_AMPLO.finditer(texto):
        inicio, fim = m.start(), m.end()
        dados = _dados(m.group("num"), "", m.group("compl"))
        saida.append(Achado(inicio, fim, texto[inicio:fim], "dispositivo", "lei", dados,
                            "regex:dispositivo:amplo", 0.4))
    return saida


def detectar(texto: str) -> list[Achado]:
    """Estrito + amplo, na ordem do texto (a fusão remove as sobreposições)."""
    achados = detectar_estrito(texto) + detectar_amplo(texto)
    achados.sort(key=lambda a: (a.inicio, -a.fim))
    log.debug("dispositivo: %d achados", len(achados))
    return achados


__all__ = ["RE_DISPOSITIVO", "RE_DISPOSITIVO_AMPLO", "detectar", "detectar_estrito",
           "detectar_amplo", "diploma_canonico_da_superficie"]
