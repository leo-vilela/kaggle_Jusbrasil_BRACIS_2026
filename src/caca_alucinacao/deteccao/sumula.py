"""Família ``sumula``: ``Súmula [Vinculante] N [do T]`` (docs/03 §5).

Fronteira: de ``Súmula`` (ou ``Súm.``, ``5UMULA``, ``SÚMULA``, ``Sumula``,
``Enunciado``) até o número ou até o tribunal quando presente (``do STJ`` entra,
inclusive com quebra antes ou dentro: ``999\\ndo STF``, ``do\\nSTF``; também
``/STJ``, ``(STJ)``, ``- STJ``, ``, do STJ`` e, antes do tribunal, um item do
verbete: ``Súmula 999, IV, do TST``). Um conector (``nº``, ``n.``) pode aparecer
antes de ``Vinculante`` ou do número (formas ood ``Súmula nº 7``, ``Súmula nº
Vinculante 45``).

O número tolera o OCR letra↔dígito do nível 2 em qualquer posição (``8l``,
``l0``, ``33l``, ``1O``; revisão rodada 2, R4-02): as letras confundíveis coladas
ao número entram no span e são convertidas pelo mapa inverso do gerador
(``normalizacao.CONFUSOES``, bijetivo) — nunca se casa só o prefixo numérico,
que produziria uma súmula "parcial" (``Súmula 8`` de ``Súmula 8l``), e o achado
registra ``letras_ocr`` para que a resolução rebaixe a confiança.

Armadilhas: "verbete sumular aplicável à espécie" e "entendimento sumulado
sobre a matéria" não têm número — não disparam; ``Súmula`` seguida de palavra
(``Súmula do STJ``) também não. O número nunca é seguido de dígito ou letra.
``súmula``/``enunciado``/``verbete`` em minúsculas só disparam com conector ou
tribunal (revisão R2-10 e rodada 2, R4-09).
"""
from __future__ import annotations

import logging
import re

from ..base_canonica.normativos import numero_com_ocr as _numero_com_ocr
from ..base_canonica.normativos import sumula_canonica
from ..normalizacao import CONFUSOES
from ..tipos import Achado
from . import padroes as P
from .vaga import sigla_do_tribunal

log = logging.getLogger(__name__)

#: ``Súmula`` com o OCR medido em docs/03 §3.1 (``S``→``5`` na inicial, ``a``→``ã``,
#: ``m``→``rn``, ``u``→``ü``, ``l``→``1``), em qualquer caixa (``SÚMULA``,
#: ``Sumula``), abreviada (``Súm.``) ou como ``Enunciado``/``Verbete`` (revisão R2-03).
_UMULA = P.regex_extenso("umula", inicial_maiuscula=False)   # ``l``→``1`` já vem de ``padroes._ACENTOS``
_SUMULA = rf"(?:[S5]{_UMULA}|[S5][úuÚUü][mM]\.|[S5]UMULA)"
#: ``súmula``/``súm.`` em minúsculas: só com conector ou tribunal (grupo ``minuscula``).
_SUMULA_MINUSCULA = rf"(?:s{_UMULA}|s[úuü][mM]\.)"
#: Plural (``Súmulas``, ``SÚMULAS``, ``Enunciados``, ``verbetes``; revisão rodada 3, R3-03/R5-06):
#: o ``s`` final abre uma enumeração (grupo ``plural``).
_VERBETE_SUMULAR = rf"{P.regex_extenso('verbete')}{P.S}{P._regex_palavra('sumular')}"
_PALAVRA = (
    rf"(?:{_VERBETE_SUMULAR}|{_SUMULA}|{P.regex_extenso('enunciado')}|{P.regex_extenso('verbete')}"
    rf"|(?P<minuscula>{_SUMULA_MINUSCULA}|{P.regex_extenso('enunciado', inicial_maiuscula=False)}"
    rf"|{P.regex_extenso('verbete', inicial_maiuscula=False)}))(?P<plural>[sS](?![A-Za-zÀ-ÿ]))?"
)
#: ``Vinculante``/``vinculante``/``VINCULANTE`` (a âncora ``Súmula`` já protege; rodada 3, R3-08).
_VINCULANTE = P.regex_extenso("vinculante", inicial_maiuscula=False) + r"(?:[sS](?![A-Za-zÀ-ÿ]))?"   # ``Súmulas Vinculantes 10 e 37`` (rodada 4, R6-09)
#: Súmula Vinculante pela sigla (``SV 45``, ``SV nº 45``): sempre vinculante, STF implícito.
_SV = r"SV"
#: ``do``/``da`` (e ``de``) em qualquer caixa e com o OCR ``o``→``0``, ``a``→``ã``, ``e``→``c``
#: (``DO STJ`` no ruído de caixa alta do nível 2; revisão rodada 2, R4-07).
_D_OA = r"[dD][oOaA0ãó]"   # ``dó STJ`` (OCR ``o``→``ó``; rodada 4, R4-07)
_D_AE = r"[dD][aAeEcã]"
_TRIB = rf"(?:{P.TRIBUNAL_SIGLA}|{P.TRIBUNAL_EXTENSO})"
#: Depois do número: ``do STJ`` (com quebra antes ou dentro), ``/STJ``, ``(STJ)``, ``- STJ``,
#: ``, do STJ``, e as formas com um complemento no meio — ``da jurisprudência do TST``,
#: ``da Súmula do STJ`` (para ``Enunciado 123 da Súmula do STJ``), ``do Egrégio STF``,
#: ``do Eg. STJ`` — até o tribunal (revisões R2-07 e rodada 2, R4-13).
_MEIO = (
    rf"(?:{P._regex_palavra('jurisprudencia')}(?:{P.S}(?:dominante|pac[ií]fica|consolidada))?"
    rf"|(?:{_SUMULA}|{_SUMULA_MINUSCULA})(?:{P.S}{_VINCULANTE})?|{P.regex_extenso('verbete', inicial_maiuscula=False)}"
    r"|[Ee]gr[ée]gi[oa]|[Cc]olend[oa]|[Ee]g\.|[Ee]\.|[Cc]\.)"
)
#: Item do verbete entre o número e o tribunal (``Súmula 999, IV, do TST``; ``Súmula 9,
#: item II, do STJ``; ``, § 1º``): só entra no span quando o tribunal o segue — fronteira
#: assumida (ADR 0005; revisão rodada 2, R4-10).
_ITEM_SUMULA = rf"(?:,?{P.S}(?:[Ii]tem{P.S})?[IVXLC]{{1,6}}|,?{P.S}§{P.S0}\d{{1,2}}[ºo°]?)"
_TRIBUNAL_DEPOIS = (
    r"(?:"
    rf"(?:{_ITEM_SUMULA})?,?{P.S}{_D_OA}{P.S}(?:{_MEIO}{P.S}(?:{_D_OA}{P.S})?)?{_TRIB}"
    rf"|,?{P.S}{_D_AE}{P.S}{_MEIO}{P.S}{_D_OA}{P.S}{_TRIB}"
    rf"|\s{{0,2}}/\s{{0,2}}{P.TRIBUNAL_SIGLA}"
    rf"|\s{{0,2}}[-–—]\s{{0,2}}{P.TRIBUNAL_SIGLA}"
    rf"|\s{{0,2}}\(\s{{0,2}}{_TRIB}\s{{0,2}}\)"
    rf"|,\s{{0,2}}{P.TRIBUNAL_SIGLA}"
    r")(?![A-Za-zÀ-ÿ])"
)
#: Tribunal ENTRE a palavra e o número (``Súmula STJ 999``, ``Súmula STJ nº 12``, ``Súmula TST/34``;
#: revisão rodada 3, R3-08).
_TRIBUNAL_ANTES = rf"(?:(?P<trib_antes>{P.TRIBUNAL_SIGLA})(?![A-Za-zÀ-ÿ])(?:\s{{0,2}}/\s{{0,2}}|{P.S}))"
#: Item de enumeração depois do primeiro número (só com a palavra no plural; ``Súmulas 12 e 34 do
#: STJ``, ``Súmulas nºs 12 e 34 do STF``, ``Súmulas 12/STJ e 34/TST``, ``Súmulas 12, 34 e 56``):
#: ``,``/``;``/``e`` + [conector] + número [+ tribunal]. Fronteira assumida: UM span por enumeração
#: (ADR 0005, rodada 3); o gabarito é do primeiro número. Quando o primeiro número não traz
#: tribunal, vale o PRIMEIRO tribunal da enumeração e o span fecha nele (``Súmulas 12 e 34 do
#: STJ e 56 do TST`` → ``Súmulas 12 e 34 do STJ``; rodada 4, R6-04).
_ENUM_SEP = rf"(?:\s{{0,2}}[,;]\s{{0,2}}|{P.S}[eE]{P.S})"
#: Número da súmula: 1–4 caracteres numéricos (dígitos ou letras confundíveis coladas),
#: com ponto de milhar opcional (``1.234``); ao menos um dígito é exigido em código.
#: Nunca seguido de letra ou dígito — assim ``8l`` nunca casa só ``8``.
_NUM_SUMULA = rf"[\d{P.LETRAS_OCR}]{{1,4}}(?:\.[\d{P.LETRAS_OCR}]{{3}})?(?![A-Za-zÀ-ÿ0-9])"
RE_SUMULA = re.compile(
    rf"""
    (?<![A-Za-zÀ-ÿ])
    (?:
        (?P<palavra>{_PALAVRA})(?:\s{{0,2}}:)?{P.S}
        (?:{_TRIBUNAL_ANTES})?
        (?:(?:[dD][eE]{P.S})?(?P<con1>{P.CONECTOR}s?){P.S0})?
        (?P<vinc>{_VINCULANTE})?{P.S0}
      | (?P<sv>{_SV})\.?(?:\s{{0,2}}:)?{P.S0}
    )
    (?:(?P<con2>{P.CONECTOR}s?){P.S0})?
    (?P<num>{_NUM_SUMULA})
    (?P<trib>{_TRIBUNAL_DEPOIS})?
    (?(plural)(?P<enum>(?:{_ENUM_SEP}(?:{P.CONECTOR}{P.S0})?{_NUM_SUMULA}(?:{_TRIBUNAL_DEPOIS})?){{1,8}})?)
    """,
    re.VERBOSE,
)
#: Um item da enumeração (para cortar o span no primeiro tribunal; R6-04).
_RE_ITEM_ENUM = re.compile(rf"{_ENUM_SEP}(?:{P.CONECTOR}{P.S0})?{_NUM_SUMULA}(?P<trib>{_TRIBUNAL_DEPOIS})?")
_RE_NUMEROS_ENUM = re.compile(rf"[\d{P.LETRAS_OCR}]{{1,4}}(?:\.[\d{P.LETRAS_OCR}]{{3}})?(?![A-Za-zÀ-ÿ0-9])")
_RE_VINCULANTE = re.compile(_VINCULANTE)


_RE_SO_TRIBUNAL = re.compile(rf"(?:{P.TRIBUNAL_SIGLA}|{P.TRIBUNAL_EXTENSO})\s*\)?\s*$")
#: Órgão NÃO jurisdicional logo depois de ``Enunciado N``/``Verbete N`` (``do FONAJE``, ``da I
#: Jornada de Direito Civil``, ``do CJF``, ``do CNJ``): não é súmula de tribunal superior — o
#: achado sai com força 0,5 e a resolução o descarta (revisão rodada 2, R4-16; ADR 0005).
_RE_ORGAO_EXTERNO = re.compile(
    r"^\s{1,2}d[aoe]s?\s{1,2}(?:[IVX]{1,4}\s{1,2})?"
    r"(?:FONAJE|FONAJEF|FONAVID|FONACRIM|CJF|CNJ|CNMP|ENFAM|Jornada|Conselho|F[óo]rum|Encontro|"
    r"TJ[A-Z]{2}|TRF|TRT|TRE|Turma\s{1,2}Recursal|Corregedoria)(?![A-Za-zÀ-ÿ])"
)


def numero_com_ocr(num: str) -> tuple[str, int]:
    """``"8l"`` → ``("81", 1)``; ``"1.234"`` → ``("1234", 0)``: dígitos canônicos e letras convertidas.

    Mapa inverso do gerador (:data:`normalizacao.CONFUSOES`, bijetivo): cada letra
    confundível recupera exatamente o dígito trocado. Devolve ``("", n)`` quando não
    há dígito algum (``"lO"`` não é número).
    """
    letras = sum(1 for c in num if c in CONFUSOES)
    return _numero_com_ocr(num) or "", letras   # mesma regra do resolvedor (normativos)


def _so_tribunal(bloco: str | None) -> str | None:
    """``" do\nSTF"``/``"/STJ"``/``" do Superior Tribunal de Justiça"`` → só o tribunal."""
    if not bloco:
        return None
    m = _RE_SO_TRIBUNAL.search(bloco)
    return m.group(0) if m else bloco


def detectar(texto: str) -> list[Achado]:
    """Todas as súmulas do texto, na ordem, com força 1,0."""
    saida: list[Achado] = []
    for m in RE_SUMULA.finditer(texto):
        if m.group("minuscula") and not (m.group("con1") or m.group("con2") or m.group("trib") or m.group("vinc")):
            # "enunciado 3" em minúsculas e sem nº/tribunal é prosa; "enunciado nº 123 da Súmula do STJ" e
            # "súmula vinculante 45" (rodada 3, R3-08) não
            continue
        inicio, fim = m.start(), m.end()
        enum = m.group("enum")
        if enum and not m.group("trib"):
            # fecha o span no PRIMEIRO tribunal da enumeração (R6-04): o que vem depois pertence a
            # outra corte e não pode dar o tribunal do primeiro número
            pos = 0
            while pos < len(enum):
                it = _RE_ITEM_ENUM.match(enum, pos)
                if it is None:
                    break
                pos = it.end()
                if it.group("trib"):
                    break
            if pos < len(enum):
                fim = m.start("enum") + pos
                enum = enum[:pos]
        trecho = texto[inicio:fim]
        digitos, letras_ocr = numero_com_ocr(m.group("num"))
        if not digitos:
            continue  # "Enunciado I", "Súmula Ss": sem dígito não é número
        numero = int(digitos)
        vinculante = bool(m.group("vinc")) or bool(m.group("sv")) or bool(_RE_VINCULANTE.search(trecho))
        tribunal = sigla_do_tribunal(_so_tribunal(m.group("trib"))) or sigla_do_tribunal(m.group("trib_antes"))
        if not tribunal and enum:
            # ``Súmulas 5 e 7 do STJ``: o tribunal do fim (já cortado no primeiro) vale para todos
            ultimo = _RE_SO_TRIBUNAL.search(enum)
            tribunal = sigla_do_tribunal(ultimo.group(0)) if ultimo else ""
        if not tribunal and not vinculante:
            # cruzamento com a normalização compartilhada (mesma regra da base)
            trib_norm, vinc_norm, _ = sumula_canonica(trecho)
            vinculante = vinculante or vinc_norm
            tribunal = "" if vinculante else (trib_norm or "")
        # ``tribunal`` só é gravado quando EXPLÍCITO no span; "Vinculante ⇒ STF" é
        # inferência da resolução (``sumula:na_tabela:tribunal_implicito``; revisão R1-08).
        dados = {
            "classe": "",
            "cadeia": "",
            "classe_principal": "",
            "numero": m.group("num"),
            "digitos": str(numero),
            "formato": "",
            "uf": "",
            "tribunal": tribunal or "",
            "ano": "",
            "relator": "",
            "artigo": "",
            "diploma": "",
            "numero_sumula": str(numero),
            "vinculante": "1" if vinculante else "0",
            "numero_tema": "",
            "letras_ocr": str(letras_ocr),
        }
        if enum:
            # números seguintes da enumeração (diagnóstico; a resolução usa o primeiro)
            outros = [_numero_com_ocr(n) or "" for n in _RE_NUMEROS_ENUM.findall(enum)]
            dados["enumeracao"] = ",".join(n for n in outros if n)
        if (not m.group("trib") and not vinculante and not m.group("sv") and m.group("palavra")
                and m.group("palavra")[0] not in "S5s" and _RE_ORGAO_EXTERNO.match(texto[fim:fim + 60])):
            # ``Enunciado 12 do CJF``/``da V Jornada``: a resolução descarta SEMPRE (mesmo quando o
            # número existe na tabela de súmulas; rodada 4, R6-11) — fica no rastro para diagnóstico
            dados["orgao_externo"] = "1"
            saida.append(Achado(inicio, fim, trecho, "sumula", "jurisprudencia", dados,
                                "regex:sumula:orgao_externo", 0.5))
            continue
        saida.append(Achado(inicio, fim, trecho, "sumula", "jurisprudencia", dados, "regex:sumula", 1.0))
    log.debug("sumula: %d achados", len(saida))
    return saida


__all__ = ["RE_SUMULA", "detectar", "numero_com_ocr"]
