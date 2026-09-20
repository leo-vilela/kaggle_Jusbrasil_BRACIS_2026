"""Súmulas e dispositivos de lei: tabelas derivadas da base + aliases de diploma.

Os 18 registros não-acórdão da base abrem com uma linha autodeclarada::

    Súmula n. 123 do STJ
    Súmula Vinculante n. 45 do STF
    Artigo 321 da Lei nº 13.105, de 16 de março de 2015
    Artigo 97 da Constituição Federal de 1988

:func:`derivar_normativos` lê essas linhas (nunca à mão) e produz as tabelas
``(tribunal, vinculante, numero) → documento_id`` e ``(diploma, artigo) →
documento_id``. O **diploma canônico** (``CPC``, ``CC``, ``CLT``, ``CF``,
``CPP``, ``CPM``, ``CDC``, ``CE``, ``LC64``) vem de :data:`DIPLOMAS`, que
também lista os aliases aceitos nas citações (sigla, nome por extenso, número
da lei, variações com ruído). Uma lei identificável mas ausente da tabela
(``Lei nº 9.504/1997``) recebe o diploma sintético ``LEI-9504`` — "conhecido,
mas fora da base fechada" — para que a resolução a trate como ``inventada`` e
não como ``incompleta``.
"""
from __future__ import annotations

import re
from typing import Any

from ..normalizacao import CONFUSOES, tolerante
from .classes import sem_acento
from .digitos import corrigir_ocr_em_grupo

TRIBUNAIS: frozenset[str] = frozenset({"STF", "STJ", "TST", "TSE", "STM"})

# sigla canônica → (tipo normativo, número da lei sem pontos, ano, aliases textuais)
DIPLOMAS: dict[str, dict[str, Any]] = {
    "CPC": {
        "lei": ("lei", "13105", "2015"),
        "nome": "Código de Processo Civil (Lei nº 13.105/2015)",
        "aliases": ["cpc", "ncpc", "cpc/2015", "cpc/15", "novo cpc", "codigo de processo civil",
                    "novo codigo de processo civil", "lei processual civil"],
    },
    "CC": {
        "lei": ("lei", "10406", "2002"),
        "nome": "Código Civil (Lei nº 10.406/2002)",
        "aliases": ["cc", "cc/2002", "cc/02", "codigo civil", "codigo civil brasileiro"],
    },
    "CLT": {
        "lei": ("decreto-lei", "5452", "1943"),
        "nome": "Consolidação das Leis do Trabalho (Decreto-Lei nº 5.452/1943)",
        "aliases": ["clt", "consolidacao das leis do trabalho"],
    },
    "CF": {
        "lei": ("constituicao", "1988", "1988"),
        "nome": "Constituição Federal de 1988",
        "aliases": ["cf", "cf/88", "cf/1988", "crfb", "crfb/88", "crfb/1988", "constituicao federal",
                    "constituicao da republica", "constituicao da republica federativa do brasil",
                    "constituicao", "carta magna", "lei maior", "lei fundamental", "texto constitucional"],
    },
    "CPP": {
        "lei": ("decreto-lei", "3689", "1941"),
        "nome": "Código de Processo Penal (Decreto-Lei nº 3.689/1941)",
        "aliases": ["cpp", "codigo de processo penal"],
    },
    "CPM": {
        "lei": ("decreto-lei", "1001", "1969"),
        "nome": "Código Penal Militar (Decreto-Lei nº 1.001/1969)",
        "aliases": ["cpm", "codigo penal militar"],
    },
    "CDC": {
        "lei": ("lei", "8078", "1990"),
        "nome": "Código de Defesa do Consumidor (Lei nº 8.078/1990)",
        "aliases": ["cdc", "codigo de defesa do consumidor", "codigo do consumidor",
                    "codigo de protecao e defesa do consumidor"],
    },
    "CE": {
        "lei": ("lei", "4737", "1965"),
        "nome": "Código Eleitoral (Lei nº 4.737/1965)",
        "aliases": ["ce", "codigo eleitoral"],
    },
    "LC64": {
        "lei": ("lei complementar", "64", "1990"),
        "nome": "Lei Complementar nº 64/1990 (Lei das Inelegibilidades)",
        "aliases": ["lc 64", "lc 64/90", "lc 64/1990", "lc n 64", "lei complementar 64",
                    "lei complementar n 64", "lei das inelegibilidades", "lei de inelegibilidade",
                    "lei de inelegibilidades"],
    },
}

_LEI_POR_NUMERO: dict[tuple[str, str], str] = {}
for _sigla, _d in DIPLOMAS.items():
    _tipo, _num, _ano = _d["lei"]
    _LEI_POR_NUMERO[(_tipo, _num)] = _sigla

# palavras-chave tolerantes a ruído (ordem importa: "processo civil" antes de "civil")
_REGRAS_TEXTO: list[tuple[str, str]] = [
    (r"\bconstitui", "CF"), (r"\bcrfb\b", "CF"), (r"\bcf\b", "CF"), (r"carta magna", "CF"),
    (r"lei maior", "CF"), (r"lei fundamental", "CF"), (r"texto constitucional", "CF"),
    (r"processo civil", "CPC"), (r"\bn?cpc\b", "CPC"),
    (r"processo penal", "CPP"), (r"\bcpp\b", "CPP"),
    (r"penal militar", "CPM"), (r"\bcpm\b", "CPM"),
    (r"consumidor", "CDC"), (r"\bcdc\b", "CDC"),
    (r"consolidacao das leis do trabalho", "CLT"), (r"leis trabalhistas", "CLT"), (r"\bclt\b", "CLT"),
    (r"codigo eleitoral", "CE"), (r"\bce\b", "CE"),
    (r"inelegibilidade", "LC64"),
    (r"codigo civil", "CC"), (r"\bcc\b", "CC"),
]

# Fallback tolerante a OCR nas palavras do nome do diploma (``Constltuição``,
# ``Consurnidor``, ``Lcis``): cada palavra com ≥ 5 letras admite 1 edição e as de
# 3–4 letras uma troca do mapa de confusões (:func:`normalizacao.tolerante`);
# mesma ordem de precedência das regras acima.
_FRASES_TOLERANTES: list[tuple[str, str]] = [
    ("constituicao", "CF"), ("carta magna", "CF"),
    ("codigo de processo civil", "CPC"),
    ("codigo de processo penal", "CPP"),
    ("codigo penal militar", "CPM"),
    ("codigo de defesa do consumidor", "CDC"), ("codigo do consumidor", "CDC"),
    ("consolidacao das leis do trabalho", "CLT"), ("consolidacao das leis trabalhistas", "CLT"),
    ("codigo eleitoral", "CE"),
    ("lei das inelegibilidades", "LC64"),
    ("codigo civil", "CC"),
]

_RE_LEI = re.compile(
    r"\b(?P<tipo>lei complementar|lc|decreto lei|decreto|dl|lei)\b"
    r"(?:\s+(?:federal|estadual|municipal|ordinaria))?\s*(?:n\s*\.?\s*|n\s*[o°º]\s*|numero\s*)?"
    r"(?P<numero>[0-9OolI|SsgqGBZz][0-9OolI|SsgqGBZz\. ]{0,9}[0-9OolI|SsgqGBZz]|\d)"
    r"(?:\s*(?:/|de\s+\d{1,2}\s+de\s+[a-z]+\s+de\s+|,\s*de\s+\d{1,2}\s+de\s+[a-z]+\s+de\s+|,\s*de\s+|de\s+)\s*(?P<ano>\d{2,4}))?"
)
#: Letras que o OCR põe no lugar de dígitos (as de :data:`normalizacao.CONFUSOES`), com caixa
#: EXATA — estas regex não usam ``re.I`` no número, para que ``L``/``i``/``b`` não virem dígito.
_L = "OolI|SsgqGBZz"
# ``art.``, ``art``, ``arts.``, ``artigo``, ``art.º`` (sinal de ordinal após o ponto). O número
# pode ter letras de OCR em qualquer posição, mas o grupo nunca para antes de uma letra colada
# (``(?![\dL])``): ``12G`` é lido inteiro (126), nunca ``12`` — chave parcial é τ (rodada 2, R4-02/03).
_RE_ARTIGO = re.compile(
    rf"\b[Aa](?:rt|RT)(?:igo|IGO|s|S)?\.?\s*\.?\s*[º°]?\s*(?P<num>[0-9{_L}][0-9{_L}\.]{{0,6}})(?![0-9{_L}])"
)
# ``Súmula``/``Súm.``/``5UMULA``/``Sumula``/``Enunciado`` [nº] [Vinculante] [nº] <número>; o
# número admite letras de OCR (``8l``, ``1O``, ``l0``) e é lido inteiro ou não é lido.
_RE_SUMULA = re.compile(
    r"(?:[sS5]\s?[uúüùUÚ]\s?(?:[mM]|rn)(?:\s?[uúüUÚ]\s?[l1L]\s?[aoãAOÃ]|\.)?|[eE]nunciado|ENUNCIADO|[vV]erbete|VERBETE|\bSV\.?)"
    r"\s*(?:[nN]\s*\.?\s*[o°º]?\s*)?"
    r"(?P<vinc>[vV][il]ncu[l1][aã]nt[ec]|V[Il]NCU[L1][AÃ]NT[EC])?\s*(?:[nN]\s*\.?\s*[o°º]?\s*)?"
    rf"(?P<num>[\d{_L}][\d{_L}\.]{{0,5}})(?![\d{_L}])"
)
_RE_TRIBUNAL = re.compile(r"\b(STF|STJ|TST|TSE|STM)\b")


#: Palavras-chave do tipo de norma que podem chegar com OCR (``Deereto``, ``Complcmentar``,
#: ``Lci``); cada uma é reconhecida a 1 edição (:func:`tolerante`) — as de ≥ 5 letras a
#: qualquer edição, ``lei`` (3 letras) só a UMA troca do mapa de confusões do OCR
#: (``lci``, ``1ei``; ``e``→``c`` é a troca mais medida no dev — rodada 4, R6-03).
_PALAVRAS_TIPO = ("decreto", "complementar", "lei", "leis", "federal", "estadual", "municipal", "ordinaria")
_MINIMO_LETRAS_TIPO = 3


def _corrigir_palavras_tipo(t: str) -> str:
    """``"deereto lei"`` → ``"decreto lei"``; ``"lei complcmentar"`` → ``"lei complementar"``;
    ``"lci n 8.078/1990"`` → ``"lei n 8.078/1990"``; ``"dccreto lci"`` → ``"decreto lei"``."""
    saida: list[str] = []
    for w in t.split(" "):
        if len(w) >= _MINIMO_LETRAS_TIPO:
            for alvo in _PALAVRAS_TIPO:
                if w != alvo and tolerante(w, alvo):
                    w = alvo
                    break
        saida.append(w)
    return " ".join(saida)


def _norm(texto: str) -> str:
    t = sem_acento(texto).lower().replace("\n", " ")
    t = re.sub(r"[ºª°]", "", t)
    t = re.sub(r"[\-–—]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return _corrigir_palavras_tipo(t)


def _digitos(grupo: str) -> str:
    partes = [corrigir_ocr_em_grupo(p) or "" for p in re.split(r"[\.\s]+", grupo) if p]
    return "".join(partes)


def diploma_canonico(texto: str) -> str | None:
    """Diploma citado → sigla canônica, ``LEI-<n>``/``DL-<n>``/``LC-<n>`` se
    identificável mas fora da tabela, ``None`` se não identificável.

    ``"do CPC"`` → ``CPC``; ``"da Lei nº 13.105/2015"`` → ``CPC``;
    ``"da Constituição Fcderal"`` → ``CF``; ``"da Lei nº 9.504/1997"`` → ``LEI-9504``.
    """
    t = _norm(texto)
    m = _RE_LEI.search(t)
    if m:
        tipo = m.group("tipo")
        tipo = {"lc": "lei complementar", "dl": "decreto-lei", "decreto lei": "decreto-lei",
                "decreto": "decreto-lei"}.get(tipo, tipo)
        numero = _digitos(m.group("numero")).lstrip("0")
        if numero:
            sigla = _LEI_POR_NUMERO.get((tipo, numero))
            if sigla:
                return sigla
            prefixo = {"lei": "LEI", "lei complementar": "LC", "decreto-lei": "DL"}[tipo]
            return f"{prefixo}-{numero}"
    for padrao, sigla in _REGRAS_TEXTO:
        if re.search(padrao, t):
            return sigla
    # dígitos ficam nas palavras: ``C0nstituição`` (0 por o) ainda está a 1 edição de ``constituicao``
    palavras = re.sub(r"[^a-z0-9\s]", " ", t).split()
    for frase, sigla in _FRASES_TOLERANTES:
        if _casa_tolerante(palavras, frase):
            return sigla
    return None


def _casa_tolerante(palavras: list[str], frase: str) -> bool:
    """``frase`` ocorre em ``palavras`` como janela de palavras iguais a menos de 1 erro de OCR cada."""
    alvo = frase.split()
    k = len(alvo)
    for i in range(len(palavras) - k + 1):
        if tolerante(" ".join(palavras[i:i + k]), frase):
            return True
    return False


def numero_com_ocr(num: str) -> str | None:
    """``"8l"`` → ``"81"``; ``"1.234"`` → ``"1234"``; ``"l0"`` → ``"10"``; ``"lO"``/``"No"`` → ``None``.

    Mapa inverso do gerador (:data:`normalizacao.CONFUSOES`, bijetivo): cada letra recupera
    exatamente o dígito trocado. Exige ao menos um dígito real; qualquer outro caractere
    (letra fora do mapa) invalida — o número é lido inteiro ou não é lido, nunca o prefixo.
    """
    if not any(c.isdigit() for c in num):
        return None
    dig = "".join(CONFUSOES.get(c, c) for c in num if c != ".")
    return dig if dig.isdigit() else None


def artigo_canonico(texto: str) -> str | None:
    """``"art. 8º, LV, da CF"`` → ``"5"``; ``"artigo 1.026, § 2º"`` → ``"1026"``; ``"art. 3l9"`` → ``"319"``;
    ``"art. 12G da CLT"`` → ``"126"``; ``"art. 5o do CPC"`` → ``"5"`` (``o`` final é ordinal, não OCR)."""
    m = _RE_ARTIGO.search(texto.replace("\n", " "))
    if not m:
        return None
    num = m.group("num")
    if num.endswith("o") and len(num) >= 2 and num[-2].isdigit():
        num = num[:-1]   # ordinal ``5o``: o ``o`` minúsculo no fim nunca é OCR (deteccao.dispositivo)
    dig = numero_com_ocr(num)
    return (dig.lstrip("0") or None) if dig else None


def sumula_canonica(texto: str) -> tuple[str | None, bool, int | None]:
    """``"5umula 219 do STJ"`` → ``("STJ", False, 219)``; ``"Súmula Vinculante 45"`` → ``("STF", True, 10)``."""
    t = texto.replace("\n", " ")
    m = _RE_SUMULA.search(t)
    if not m:
        return None, False, None
    vinculante = bool(m.group("vinc")) or m.group(0).lstrip().upper().startswith("SV")
    trib = _RE_TRIBUNAL.search(t)
    tribunal = trib.group(1) if trib else ("STF" if vinculante else None)
    dig = numero_com_ocr(m.group("num"))   # inteiro ou nada: ``8l`` → 81, nunca 8 (rodada 2, R4-02)
    return tribunal, vinculante, (int(dig) if dig else None)


# ---------------------------------------------------------------------------
_RE_LINHA_SUMULA = re.compile(r"^S[úu]mula\s+(?P<vinc>Vinculante\s+)?n\.?\s*(?P<num>\d+)\s+do\s+(?P<trib>[A-Z]{3})", re.I)
_RE_LINHA_ARTIGO = re.compile(r"^Artigo\s+(?P<num>[\d\.]+)[ºo°]?\s+(?P<resto>d[ao]\s+.+)$", re.I)


def derivar_normativos(registros: list[tuple[str, str, str | None, str]]) -> dict[str, Any]:
    """Tabelas a partir da primeira linha dos registros não-acórdão.

    ``registros``: ``(documento_id, natureza, tribunal, texto_inicial)``.
    Devolve ``{"sumulas": {"STJ|0|123": documento_id}, "dispositivos":
    {"CPC|321": documento_id}, "diplomas_na_base": ["CC", …], "nao_derivados": [...]}``.
    """
    sumulas: dict[str, str] = {}
    dispositivos: dict[str, str] = {}
    nao_derivados: list[str] = []
    for documento_id, natureza, tribunal, texto in sorted(registros):
        linha = texto.split("\n", 1)[0].strip()
        if natureza == "sumula":
            m = _RE_LINHA_SUMULA.match(linha)
            if not m:
                nao_derivados.append(documento_id)
                continue
            trib = (m.group("trib") or tribunal or "").upper()
            chave = f"{trib}|{int(bool(m.group('vinc')))}|{int(m.group('num'))}"
            sumulas[chave] = documento_id
        elif natureza == "dispositivo":
            m = _RE_LINHA_ARTIGO.match(linha)
            if not m:
                nao_derivados.append(documento_id)
                continue
            diploma = diploma_canonico(m.group("resto"))
            artigo = m.group("num").replace(".", "").lstrip("0")
            if not diploma or not artigo:
                nao_derivados.append(documento_id)
                continue
            dispositivos[f"{diploma}|{artigo}"] = documento_id
    return {
        "sumulas": dict(sorted(sumulas.items())),
        "dispositivos": dict(sorted(dispositivos.items())),
        "diplomas_na_base": sorted({k.split("|")[0] for k in dispositivos}),
        "nao_derivados": nao_derivados,
    }


__all__ = [
    "DIPLOMAS",
    "TRIBUNAIS",
    "diploma_canonico",
    "artigo_canonico",
    "sumula_canonica",
    "numero_com_ocr",
    "derivar_normativos",
]
