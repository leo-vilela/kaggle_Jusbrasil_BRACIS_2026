#!/usr/bin/env python3
"""Cataloga o gabarito de desenvolvimento (goldenset.csv) e gera dados/catalogo_gabarito.json.

Uso:
    python scripts/analise/catalogar_gabarito.py [--dados dados/] [--saida dados/catalogo_gabarito.json]
                                                 [--resumo]   # imprime estatísticas no stdout

Para cada uma das citações do gabarito o script:
  * confere que ``trecho == texto[inicio:fim]`` (offsets em codepoints);
  * infere a família (processo | sumula | dispositivo | tema | vaga), a classe processual de
    superfície e canônica, os prefixos encadeados, o número de superfície, os dígitos após a
    correção de OCR (sem a UF), o formato do número, a UF e seu separador, o tribunal explícito,
    ano, relator, artigo, diploma, número de súmula, rótulos de ruído e contextos;
  * consulta a base canônica (SQLite, somente leitura) para saber se os dígitos da citação
    aparecem em algum registro (em quantos e em que posição mínima), e, para as ``real``, qual é
    a classe própria do registro apontado e onde o número próprio está no texto do registro.

Com ``--resumo`` imprime, além disso, as contagens usadas em ``docs/03_analise_gabarito.md``
(inventário de formas, ruído, distratores, estatísticas de distância, etc.).

Limitações (documentadas):
  * as heurísticas de parsing foram escritas para o gabarito de desenvolvimento (192 citações);
    são regex "de análise", não o detector de produção;
  * a correção de OCR aplicada aos dígitos é a do enunciado (O/o→0, l/I→1, S/s→5, g→9, G→6,
    B→8, Z→2), apenas dentro de grupos numéricos e depois de separar a UF;
  * a existência de um número na base é medida sobre os *tokens numéricos* dos textos
    (sequências de dígitos com pontuação interna), não sobre substrings arbitrárias; a
    comparação é por dígitos (pontuação e espaços removidos) e, para o padrão CNJ, com o
    sequencial preenchido a 7 dígitos (20 dígitos);
  * o "fim do cabeçalho" dos documentos é estimado por heurística (primeira linha de prosa).
Somente biblioteca padrão.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# ----------------------------------------------------------------------------------------------
# Constantes de superfície
# ----------------------------------------------------------------------------------------------

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
    "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

# Mapa de confusões de OCR (só dentro de grupos numéricos)
OCR_MAPA = {"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "s": "5", "g": "9", "G": "6",
            "B": "8", "Z": "2", "z": "2"}
DIGITO_OU_OCR = "0-9OolISsgGBZz"

# Classe processual: superfície (chave textual, minúscula, sem pontos/espaços) -> canônica
CLASSES = {
    # STJ / STF
    "resp": "REsp", "recesp": "REsp", "recursoespecial": "REsp",
    "aresp": "AREsp", "agresp": "AREsp", "agravoemrecursoespecial": "AREsp",
    "agint": "AgInt", "agravointerno": "AgInt",
    "agrg": "AgRg", "agreg": "AgRg", "agravoregimental": "AgRg", "agr": "AgRg",
    "edcl": "EDcl", "ed": "EDcl", "eds": "EDcl", "embargosdedeclaracao": "EDcl",
    "rcl": "Rcl", "recl": "Rcl", "reclamacao": "Rcl",
    "re": "RE", "recursoextraordinario": "RE",
    "rhc": "RHC", "recursoemhabeascorpus": "RHC",
    "hc": "HC", "habeascorpus": "HC",
    "rms": "RMS", "recursoemmandadodeseguranca": "RMS",
    "ar": "AR", "acaorescisoria": "AR",
    "sls": "SLS", "suspensaodeliminaredesentenca": "SLS",
    # STM
    "apl": "APL", "apelacao": "APL", "rse": "RSE",
    # TSE
    "respe": "REspe", "recursoespecialeleitoral": "REspe",
    "arespel": "AREspEl", "ai": "AI", "agravodeinstrumento": "AI",
    "rp": "Rp", "r": "R", "representacao": "Rp",
    # TST
    "rr": "RR", "recursoderevista": "RR", "arr": "ARR", "agarr": "AgARR", "airr": "AIRR",
    "e": "E", "embargos": "E",
    "segundo": "Segundo", "terceiro": "Terceiro",
}
CONECTORES_CLASSE = {"no", "na", "nos", "nas"}
CONECTOR_NUMERO_RE = re.compile(r"(?:n[º°o.]?|N[º°o.]?|nº|Nº|n\.º|N\.º)\s*$")

DIPLOMAS = [
    # (regex de superfície, diploma canônico)
    (r"constitui[cç][aã]o\s+(?:f[ec]d[ec]ral|da\s+rep[uú]blica)", "CF"),
    (r"c[oó]digo\s+de\s+processo\s+civil", "CPC"),
    (r"lei\s+n[º°o.]?\s*13\.?105/2015", "CPC"),
    (r"c[oó]digo\s+de\s+processo\s+penal", "CPP"),
    (r"c[oó]digo\s+penal\s+militar", "CPM"),
    (r"c[oó]digo\s+de\s+defesa\s+do\s+consumidor", "CDC"),
    (r"c[oó]digo\s+civil", "CC"),
    (r"c[oó]digo\s+eleitoral", "CE"),
    (r"consolida[cç][aã]o\s+das\s+leis\s+do\s+trabalho", "CLT"),
    (r"\bclt\b", "CLT"),
    (r"\bcpc\b", "CPC"),
    (r"\bcpp\b", "CPP"),
    (r"\bcf\b", "CF"),
    (r"lei\s+complementar\s+n[º°o.]?\s*64/1990", "LC64"),
    (r"lei\s+n[º°o.]?\s*([\d.]+)/(\d{4})", "LEI_OUTRA"),
]

# Moldes das citações "vagas" (tribunal + ano + relator, sem número)
MOLDES_VAGA = [
    ("julgado_proferido", re.compile(
        r"^julgado\s+do\s+(?P<trib>ST[FJM]|TS[ET])\s+prof\w+\s+em\s+(?P<ano>\d{4})\s+pela\s+relatoria\s+d\w\s+(?P<rel>.+)$", re.S)),
    ("acordao_julgado", re.compile(
        r"^ac[oó]rd[aã]o\s+do\s+(?P<trib>ST[FJM]|TS[ET])\s+julgado\s+em\s+(?P<ano>\d{4})\s+sob\s+relatoria\s+de\s+(?P<rel>.+)$", re.S)),
    ("precedente_de", re.compile(
        r"^precedente\s+do\s+(?P<trib>ST[FJM]|TS[ET])\s+de\s+(?P<ano>\d{4}),\s+da\s+relatoria\s+de\s+(?P<rel>.+)$", re.S)),
    ("classe_do_tribunal_rel", re.compile(
        r"^(?P<classe>.+?)\s+do\s+(?P<trib>ST[FJM]|TS[ET]),\s+de\s+(?P<ano>\d{4}),\s+Rel\.\s+Min\.\s+(?P<rel>.+)$", re.S)),
    ("classe_de_ano_rel", re.compile(
        r"^(?P<classe>[A-Za-z. ]+?)\s+de\s+(?P<ano>\d{4}),\s+Rel\.\s+Min\.\s+(?P<rel>.+)$", re.S)),
]

# Sentenças-modelo sem identificador que já foram citações e SAÍRAM do gabarito (armadilhas)
ARMADILHAS_SEM_ID = [
    "jurisprudência pacífica desta corte",
    "jurisprudência consolidada dos tribunais superiores",
    "entendimento sumulado sobre a matéria",
    "verbete sumular aplicável à espécie",
    "dispositivo constitucional invocado na origem",
    "lei que disciplina a prescrição no caso",
    "normas de regência da matéria",
    "orientação dos tribunais superiores é firme no ponto",
]

# ----------------------------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------------------------


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def chave(s: str) -> str:
    """Minúsculas, sem acento, sem pontuação/espaços — para casar classes de superfície."""
    return re.sub(r"[^a-z0-9]", "", sem_acento(s).lower())


def norm_espacos(s: str) -> str:
    return re.sub(r"[\s\xa0]+", " ", s).strip()


def corrigir_ocr(grupo: str) -> str:
    return "".join(OCR_MAPA.get(c, c) for c in grupo)


def so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s)


CNJ_RE = re.compile(r"^(\d{1,7})(\d{2})(\d{4})(\d)(\d{2})(\d{4})$")


def padrao_cnj(digitos: str) -> str | None:
    """Se a sequência de dígitos tem forma CNJ (sequencial 1-7 + 13 fixos), devolve 20 dígitos."""
    if 14 <= len(digitos) <= 20:
        m = CNJ_RE.match(digitos)
        if m:
            return m.group(1).zfill(7) + "".join(m.groups()[1:])
    return None


# ----------------------------------------------------------------------------------------------
# Parsing das famílias
# ----------------------------------------------------------------------------------------------

UF_FIM_RE = re.compile(
    r"(?P<sep>\s*(?:/|-|–|\()\s*|\s+)(?P<uf>[A-Z]{2})\)?\s*$")


def separar_uf(trecho: str) -> tuple[str, str | None, str | None]:
    """Devolve (trecho sem a UF, uf, separador literal)."""
    m = UF_FIM_RE.search(trecho)
    if m and m.group("uf") in UFS:
        sep = m.group("sep")
        return trecho[: m.start()], m.group("uf"), sep
    return trecho, None, None


NUMERO_RE = re.compile(rf"[0-9][{DIGITO_OU_OCR}.\-–/ \n\xa0]*")


def extrair_numero(corpo: str) -> tuple[str, str, int, int]:
    """Localiza o número (primeiro dígito ASCII até o fim do grupo numérico ruidoso).

    Devolve (cabeca, numero_superficie, inicio, fim) — offsets relativos ao corpo."""
    m = NUMERO_RE.search(corpo)
    if not m:
        return corpo, "", -1, -1
    num = m.group(0)
    # apara à direita tudo o que não é dígito/letra-OCR
    while num and num[-1] not in "0123456789OolISsgGBZz":
        num = num[:-1]
    return corpo[: m.start()], num, m.start(), m.start() + len(num)


def digitos_corrigidos(numero_superficie: str) -> str:
    grupos = re.findall(rf"[{DIGITO_OU_OCR}]+", numero_superficie)
    return "".join(corrigir_ocr(g) for g in grupos)


def formato_numero(digitos: str, numero_superficie: str) -> str:
    if not digitos:
        return "nenhum"
    if padrao_cnj(digitos):
        return "cnj20"
    if re.search(r"\d{4}/\d{7}-\d", numero_superficie):
        return "registro"
    if 4 <= len(digitos) <= 8:
        return "curto"
    return "outro"


def analisar_cabeca(cabeca: str) -> dict:
    """Separa 'processo nº', prefixo de tribunal, cadeia de classes e conector de número."""
    d: dict = {"palavra_processo": None, "tribunal_prefixo": None, "conector_numero": None,
               "cadeia_superficie": None, "prefixos_encadeados": [], "classe_superficie": None,
               "classe_canonica": None, "estilo_cadeia": None}
    h = cabeca
    m = re.match(r"^\s*(processo|Processo)\s+(n[º°o.]?|N[º°o.]?)\s*", h)
    if m:
        d["palavra_processo"] = m.group(0).strip()
        h = h[m.end():]
    m = re.match(r"^\s*(TST)\s*-\s*", h)
    if m:
        d["tribunal_prefixo"] = "TST"
        h = h[m.end():]
    # conector de número no fim (nº / n. / No / Nº / n° ...)
    m = re.search(r"(?:\s|^)(n[º°o.]?|N[º°o.]?|n\.º|N\.º)\s*$", h)
    if m:
        d["conector_numero"] = m.group(1)
        h = h[: m.start()]
    h = h.rstrip(" \n\xa0")
    # a cadeia pode terminar em '-' (TST/TSE: "ED-E-ED-RR-", "AgR-REspe " sem hífen final)
    h = re.sub(r"[\s\-]+$", "", h)
    d["cadeia_superficie"] = norm_espacos(h)
    # tokenização da cadeia
    if re.search(r"\s(no|na|nos|nas)\s", h):
        estilo = "conector_no"
        toks = [t for t in re.split(r"\s+", norm_espacos(h)) if t]
        # agrupa palavras entre conectores
        grupos: list[str] = []
        atual: list[str] = []
        for t in toks:
            if t in CONECTORES_CLASSE:
                grupos.append(" ".join(atual))
                grupos.append(t)
                atual = []
            else:
                atual.append(t)
        grupos.append(" ".join(atual))
    elif "-" in h and re.fullmatch(r"[A-Za-z]+(-[A-Za-z]+)+", norm_espacos(h).replace(" ", "")):
        estilo = "hifen"
        grupos_raw = [t for t in re.split(r"\s*-\s*", norm_espacos(h)) if t]
        grupos = []
        for i, g in enumerate(grupos_raw):
            if i:
                grupos.append("-")
            grupos.append(g)
    else:
        estilo = "simples"
        grupos = [norm_espacos(h)]
    # cadeias mistas: "ED no AgR-REspe" -> o grupo "AgR-REspe" ainda se divide no hífen
    if estilo == "conector_no":
        novos: list[str] = []
        for g in grupos:
            if g not in CONECTORES_CLASSE and re.fullmatch(r"[A-Za-z.]+(-[A-Za-z.]+)+", g):
                partes = g.split("-")
                for i, p in enumerate(partes):
                    if i:
                        novos.append("-")
                    novos.append(p)
                estilo = "misto"
            else:
                novos.append(g)
        grupos = novos
    # ordinais ("Segundo AgRg", "Terceiro AG.REG") viram token próprio, como no cabeçalho dos registros
    novos = []
    for g in grupos:
        m_ord = re.match(r"^(Segundos?|Terceiros?|Quartos?|D[ée]cimos?)\s+(.+)$", g)
        if m_ord:
            novos.extend([m_ord.group(1), m_ord.group(2)])
        else:
            novos.append(g)
    grupos = novos
    d["estilo_cadeia"] = estilo
    grupos = [g for g in grupos if g != ""]
    if grupos:
        d["classe_superficie"] = grupos[-1]
        d["prefixos_encadeados"] = grupos[:-1]
        d["classe_canonica"] = CLASSES.get(chave(grupos[-1]))
        d["prefixos_canonicos"] = [CLASSES.get(chave(g), g) if g not in CONECTORES_CLASSE and g != "-" else g
                                   for g in grupos[:-1]]
        d["cadeia_canonica"] = [CLASSES.get(chave(g), g) for g in grupos if g not in CONECTORES_CLASSE and g != "-"]
    return d


def parse_processo(trecho: str) -> dict:
    sem_uf, uf, sep = separar_uf(trecho)
    cabeca, numero, i0, i1 = extrair_numero(sem_uf)
    d = analisar_cabeca(cabeca)
    digitos = digitos_corrigidos(numero)
    cnj = padrao_cnj(digitos)
    d.update({
        "numero_superficie": numero,
        "digitos": cnj or digitos,
        "digitos_brutos": so_digitos(numero),
        "formato_numero": formato_numero(digitos, numero),
        "uf": uf,
        "separador_uf": sep,
        "sobra_apos_numero": sem_uf[i1:] if i1 >= 0 else "",
    })
    if cnj:
        d["ano_cnj"] = int(cnj[9:13])
        d["segmento_cnj"] = cnj[13]
        d["tribunal_cnj"] = cnj[14:16]
    return d


SUMULA_RE = re.compile(
    r"^(?P<palavra>[5S][úuÚU][mM]\w*\.?|S[ÚU]MULA)\s*(?P<vinc>Vinculante\s+)?(?P<num>[\d.]+)"
    r"(?:\s*(?P<trib>do\s+(?:ST[FJM]|TS[ET])))?\s*$", re.S)


def parse_sumula(trecho: str) -> dict:
    m = SUMULA_RE.match(re.sub(r"[\s\xa0]+", " ", trecho))
    if not m:
        return {"erro_parse": True}
    trib = m.group("trib")
    return {
        "palavra_sumula": m.group("palavra"),
        "vinculante": bool(m.group("vinc")),
        "numero_sumula": int(so_digitos(m.group("num"))),
        "tribunal_explicito": trib.split()[-1] if trib else None,
        "digitos": so_digitos(m.group("num")),
    }


TEMA_RE = re.compile(r"^(?P<palavra>Tem\w+)\s+(?P<num>[\d.]+)\s+(?P<resto>.*)$", re.S)


def parse_tema(trecho: str) -> dict:
    m = TEMA_RE.match(trecho)
    if not m:
        return {"erro_parse": True}
    return {"palavra_tema": m.group("palavra"), "numero_tema": int(so_digitos(m.group("num"))),
            "digitos": so_digitos(m.group("num")), "complemento": norm_espacos(m.group("resto"))}


DISP_RE = re.compile(
    r"^(?P<art>art(?:igo)?\.?)\s*(?P<num>\d[\d.]*)(?P<ord>[ºo°])?"
    r"(?P<sub>(?:,\s*[^,]+)*?)\s*,?\s+(?P<prep>d[ao])\s+(?P<diploma>.+)$", re.S)


def parse_dispositivo(trecho: str) -> dict:
    t = re.sub(r"[\s\xa0]+", " ", trecho)
    m = DISP_RE.match(t)
    if not m:
        return {"erro_parse": True}
    diploma_sup = m.group("diploma").strip()
    diploma = None
    lei_num = None
    for rx, canon in DIPLOMAS:
        mm = re.search(rx, sem_acento(diploma_sup).lower())
        if mm:
            diploma = canon
            if canon == "LEI_OUTRA":
                lei_num = mm.group(1) + "/" + mm.group(2)
                diploma = "Lei " + lei_num
            break
    subdiv = [s.strip() for s in m.group("sub").split(",") if s.strip()]
    return {
        "palavra_artigo": m.group("art"),
        "artigo": so_digitos(m.group("num")),
        "artigo_ordinal": bool(m.group("ord")),
        "subdivisoes": subdiv,
        "preposicao_diploma": m.group("prep"),
        "diploma_superficie": diploma_sup,
        "diploma": diploma,
        "digitos": so_digitos(m.group("num")),
    }


def parse_vaga(trecho: str) -> dict:
    t = trecho
    for nome, rx in MOLDES_VAGA:
        m = rx.match(t)
        if m:
            rel = m.group("rel").strip()
            rel_norm = norm_espacos(rel)
            palavras = rel_norm.split(" ")
            d = {
                "molde": nome,
                "tribunal_explicito": m.groupdict().get("trib"),
                "ano": int(m.group("ano")),
                "relator": rel_norm,
                "relator_bruto": rel,
                "relator_caixa_alta": rel_norm.upper() == rel_norm,
                "relator_n_palavras": len(palavras),
                "relator_quebra_linha": "\n" in rel,
                "classe_vaga": norm_espacos(m.group("classe")) if "classe" in m.groupdict() and m.group("classe") else None,
            }
            return d
    return {"erro_parse": True}


def inferir_familia(r: dict, trecho: str) -> str:
    t = trecho.lstrip()
    if r["tipo"] == "lei":
        return "dispositivo"
    if re.match(r"^(S[úÚuU]m|5[úu]m|SÚM)", t):
        return "sumula"
    if re.match(r"^Tem", t):
        return "tema"
    if re.search(r"relatoria|Rel\.\s*\n?\s*Min\.", t):
        return "vaga"
    return "processo"


# ----------------------------------------------------------------------------------------------
# Ruído
# ----------------------------------------------------------------------------------------------

# Ruído de OCR nas palavras fixas dos moldes: uma palavra do trecho é "OCR" quando, depois de
# dobrar as confusões conhecidas (e↔c, a↔ã, i↔l, m↔rn, o↔0, s↔5, u↔ü), coincide com uma palavra
# do vocabulário dos moldes sem ser igual a ela. Nenhuma forma observada é listada aqui (regra do
# projeto: nada do gabarito nos arquivos versionados); o ruído no NOME do relator é detectado
# comparando com a base (nome que só casa com tolerância de edição -> "ocr_no_nome_do_relator").
VOCABULARIO_MOLDES = frozenset("""
proferido de do da em julgado precedente acordao acórdão decisao decisão aresto relatoria relator
relatora ministro ministra federal constituicao constituição codigo código processo civil penal
tema repercussao repercussão geral sumula súmula vinculante lei complementar consolidacao
consolidação leis trabalho consumidor defesa eleitoral militar
""".split())
_DOBRAS = {"c": "e", "ã": "a", "l": "i", "0": "o", "5": "s", "ü": "u", "1": "i", "|": "i"}
_DOBRADO = {}
for _w in VOCABULARIO_MOLDES:
    _DOBRADO.setdefault("".join(_DOBRAS.get(ch, ch) for ch in _w.lower().replace("rn", "m")), _w)


def palavra_ocr(token: str) -> str | None:
    """Forma limpa se ``token`` é uma palavra dos moldes com OCR (``"Fcderal"`` → ``"federal"``)."""
    t = token.lower()
    if t in VOCABULARIO_MOLDES:
        return None
    limpa = _DOBRADO.get("".join(_DOBRAS.get(ch, ch) for ch in t.replace("rn", "m")))
    return limpa if limpa and limpa != t else None


def palavras_ocr(trecho: str) -> list[str]:
    """Palavras do trecho (fora de números) que estão em forma de OCR."""
    return [w for w in re.findall(r"[^\W\d_][\w]*", trecho) if palavra_ocr(w)]


def rotulos_ruido(trecho: str, familia: str, campos: dict, nivel: int) -> list[str]:
    r: list[str] = []
    if "\n" in trecho:
        r.append("quebra_linha_no_span")
    if "\xa0" in trecho:
        r.append("nbsp")
    if re.search(r"[^\S\n]{2,}", trecho):
        r.append("espaco_duplo")
    num = campos.get("numero_superficie") or ""
    if familia == "processo" and num:
        if re.search(r"[OolISsgGBZz]", num):
            r.append("ocr_letra_em_digito")
        if re.search(r"[ \n\xa0]", num):
            r.append("espaco_no_numero")
        if "\n" in num:
            r.append("quebra_linha_no_numero")
        if re.search(r"--|-\s*\n?\s*\.|\.\s*-|\.-", num) or re.search(r"[.\-]\s+[.\-]", num):
            r.append("pontuacao_irregular_no_numero")
        if campos.get("formato_numero") == "cnj20" and not re.search(r"\d-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", num) \
                and "quebra_linha_no_numero" not in r and "espaco_no_numero" not in r:
            r.append("cnj_sem_pontuacao_padrao")
        elif campos.get("formato_numero") == "cnj20" and re.fullmatch(r"\d{7}-\d{13}", num):
            r.append("cnj_sem_pontuacao_padrao")
        if campos.get("formato_numero") == "curto" and re.fullmatch(r"\d{4,8}", num):
            r.append("numero_sem_pontos_de_milhar")
    cabeca = campos.get("cadeia_superficie") or ""
    if familia == "processo":
        cls = campos.get("classe_superficie") or ""
        if cls and cls.upper() == cls and len(cls) > 2 and campos.get("classe_canonica") and cls != campos["classe_canonica"]:
            r.append("caixa_alta_na_classe")
        if re.search(r"\.", cabeca):
            r.append("classe_com_pontos")
        if campos.get("conector_numero") in {"No", "N°", "n°", "N.", "n", "N", "No"}:
            r.append("conector_numero_nao_padrao")
        if campos.get("separador_uf") and campos["separador_uf"] != "/":
            r.append("separador_uf_nao_padrao")
        if campos.get("sobra_apos_numero"):
            r.append("sobra_apos_numero")
        chv = chave(cls)
        if chv in {"recesp", "resp", "agresp", "recl", "hc"} and cls not in {"REsp", "AREsp", "Rcl", "HC"} and "." in cls:
            r.append("abreviacao_nao_padrao")
        if chv in {"agresp", "recl"}:
            r.append("abreviacao_nao_padrao")
    if familia == "sumula":
        p = campos.get("palavra_sumula") or ""
        if p.startswith("5"):
            r.append("ocr_letra_em_palavra")
        if p.upper() == p and p != "SV":
            r.append("caixa_alta")
        if p.endswith("."):
            r.append("abreviacao_nao_padrao")
    if familia == "dispositivo":
        if campos.get("palavra_artigo") == "art":
            r.append("art_sem_ponto")
        if palavras_ocr(trecho):
            r.append("ocr_palavra")
    if familia == "tema" and campos.get("palavra_tema") != "Tema":
        r.append("ocr_palavra")
    if familia == "vaga":
        if palavras_ocr(trecho):
            r.append("ocr_palavra")
        if re.search(r"Rel\.\s{2,}Min", trecho):
            r.append("espaco_duplo")
    # dedup mantendo ordem
    out: list[str] = []
    for x in r:
        if x not in out:
            out.append(x)
    return out


# ----------------------------------------------------------------------------------------------
# Base canônica: índice de tokens numéricos
# ----------------------------------------------------------------------------------------------

TOKEN_NUM_RE = re.compile(r"\d(?:[\d./\-]|-\s(?=\d)|\s(?=\d{2,}\.\d))*\d|\d")


def tokens_numericos(texto: str) -> list[tuple[int, str, str]]:
    """Tokens numéricos do texto: (offset, superfície, dígitos canônicos)."""
    out = []
    for m in TOKEN_NUM_RE.finditer(texto):
        sup = m.group(0)
        dig = so_digitos(sup)
        cnj = padrao_cnj(dig) if re.search(r"\d-\s?\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", sup) else None
        out.append((m.start(), sup, cnj or dig))
    return out


CLASSE_PROPRIA_RE = {
    # STJ: "[lixo] AgInt no RECURSO ESPECIAL Nº 1.234.567 - PR (2016/0123456-7)"
    "STJ": re.compile(r"(?P<classe>[A-Za-zÀ-ÿ ]{2,120}?)\s+N[º°]\s*(?P<num>[\d. ]+?)\s*-\s*[A-Z]{2}\s*\(", re.S),
    # STF: "[lixo] 22/04/2026 PRIMEIRA TURMA AG.REG. NA RECLAMAÇÃO 76.543 RIO DE JANEIRO"
    "STF": re.compile(r"\d{2}/\d{2}/\d{4}\s+(?:PRIMEIRA TURMA|SEGUNDA TURMA|PLEN[ÁA]RIO|TRIBUNAL PLENO)\s+"
                      r"(?P<classe>[A-ZÇÃÕÉÊÁÍÓÚ.\- ]+?)\s+(?P<num>[\d.]+)\s", re.S),
    # STM: "... APELAÇÃO CRIMINAL Nº 7000078-13.2022.7.00.0000/PR"
    "STM": re.compile(r"(?P<classe>[A-ZÇÃÕÉÊÁÍÓÚ/ ]+?)\s+N[º°]\s*(?P<num>\d{7}-\s?\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})", re.S),
    # TSE: "ACÓRDÃO AGRAVO REGIMENTAL NO RECURSO ESPECIAL ELEITORAL Nº 319-76.2016.6.16.0006"
    "TSE": re.compile(r"(?:AC[ÓO]RD[ÃA]O|AC€RD O|ACÓ)\s+(?:\d*\s*os?\s+|o\s+)?(?P<classe>[A-ZÇÃÕÉÊÁÍÓÚa-z\- ]{5,120}?)\s+(?:N\s*[º°o‚]?\s*)?(?P<num>\d[\d.]*(?:\s*\(\s*[\d.\- ]+\))?[\d.\- ]*)", re.S),
    # TST: "autos de Recurso de Revista nº TST-RR-1234-56.2010.5.15.0042"
    "TST": re.compile(r"autos\s+d[eo]s?\s+(?P<classe>[^\n.;]{3,140}?)\s+n\s*\.?\s*[º°]?\s*TST\s*-\s*(?P<sigla>[A-Za-z]+(?:\s*-\s*[A-Za-z]+)*)\s*-\s*(?P<num>\d{1,7}\s*-\s*\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})", re.S),
}
TST_FALLBACK_RE = re.compile(r"(?:PROCESSO|Processo)\s+N[º°]\s*(?:TST\s*-\s*)?(?P<sigla>[A-Za-z]+(?:\s*-\s*[A-Za-z]+)*)\s*-\s*(?P<num>\d{1,7}\s*-\s*\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})", re.S)

# Nome por extenso (cabeçalho do registro) -> sigla canônica. Ordem: mais longo primeiro.
NOMES_CLASSE = [
    ("AGRAVO EM RECURSO ESPECIAL ELEITORAL", "AREspEl"),
    ("RECURSO ESPECIAL ELEITORAL", "REspe"),
    ("AGRAVO EM RECURSO ESPECIAL", "AREsp"),
    ("EMBARGOS DE DIVERGÊNCIA EM AGRAVO EM RECURSO ESPECIAL", "EAREsp"),
    ("EMBARGOS DE DIVERGÊNCIA EM RESP", "EREsp"),
    ("RECURSO ESPECIAL", "REsp"),
    ("RECURSO EXTRAORDINÁRIO COM AGRAVO", "ARE"),
    ("RECURSO EXTRAORDINÁRIO", "RE"),
    ("RECURSO EM HABEAS CORPUS", "RHC"),
    ("HABEAS CORPUS", "HC"),
    ("RECURSO EM MANDADO DE SEGURANÇA", "RMS"),
    ("RECURSO ORD. EM MANDADO DE SEGURANÇA", "RMS"),
    ("MANDADO DE SEGURANÇA", "MS"),
    ("SUSPENSÃO DE LIMINAR E DE SENTENÇA", "SLS"),
    ("SUSPENSÃO DE SEGURANÇA", "SS"),
    ("AGRAVO REGIMENTAL", "AgRg"),
    ("AG.REG.", "AgRg"),
    ("AGRAVO INTERNO", "AgInt"),
    ("AGRAVO DE INSTRUMENTO", "AI"),
    ("EMBARGOS DE DECLARAÇÃO", "EDcl"),
    ("EMB.DECL.", "EDcl"),
    ("EMB.DIV.", "EDv"),
    ("EMBARGOS INFRINGENTES E DE NULIDADE", "EI"),
    ("RECLAMAÇÃO", "Rcl"),
    ("APELAÇÃO CRIMINAL", "APL"),
    ("APELAÇÃO", "APL"),
    ("RECURSO EM SENTIDO ESTRITO", "RSE"),
    ("AÇÃO RESCISÓRIA", "AR"),
    ("RECURSO NA REPRESENTAÇÃO", "R-Rp"),
    ("REPRESENTAÇÃO", "Rp"),
    ("RECURSO ORDINÁRIO ELEITORAL", "ROEl"),
    ("RECURSO ORDINÁRIO", "RO"),
    ("CONFLITO DE COMPETÊNCIA", "CC"),
    ("CONFLITO DE JURISDIÇÃO", "CJ"),
    ("PETIÇÃO", "Pet"),
    ("AÇÃO PENAL", "AP"),
    ("CAUTELAR INOMINADA CRIMINAL", "CautInomCrim"),
    ("AGINT", "AgInt"), ("AGRG", "AgRg"), ("EDCL", "EDcl"), ("EDV", "EDv"), ("QO", "QO"), ("PEXT", "PExt"),
    ("SEGUNDO", "Segundo"), ("TERCEIRO", "Terceiro"), ("SEGUNDOS", "Segundos"), ("DÉCIMOS", "Decimos"),
    ("REFERENDO", "Referendo"),
]


def cadeia_canonica_registro(classe_propria_txt: str | None) -> list[str]:
    """Converte 'AgInt no AGRAVO EM RECURSO ESPECIAL' -> ['AgInt', 'AREsp']; TST usa a sigla."""
    if not classe_propria_txt:
        return []
    m = re.search(r"\[([A-Za-z\-]+)\]$", classe_propria_txt)
    if m:  # TST: sigla hifenizada
        return [CLASSES.get(chave(p), p) for p in re.split(r"\s*-\s*", m.group(1))]
    # nomes mais longos primeiro; cada trecho casado é "apagado" para não casar de novo
    s = sem_acento(classe_propria_txt.upper())
    achados: list[tuple[int, str]] = []
    for nome, sigla in NOMES_CLASSE:
        nome_sa = sem_acento(nome)
        # fronteira de palavra só para siglas curtas (o cabeçalho pode vir colado: "nosEMBARGOS")
        rx = re.escape(nome_sa) if len(nome_sa) > 6 else r"(?<![A-Z])" + re.escape(nome_sa) + r"(?![A-Z])"
        for mm in re.finditer(rx, s):
            achados.append((mm.start(), sigla))
            s = s[: mm.start()] + "\x00" * len(nome_sa) + s[mm.end():]
    out: list[str] = []
    for _, sig in sorted(achados):
        out.extend(sig.split("-"))
    return out


def classe_propria(tribunal: str | None, texto: str) -> tuple[str | None, int | None, str | None]:
    """Classe processual própria do acórdão (cabeçalho), offset e dígitos do número próprio."""
    if not tribunal:
        return None, None, None
    rx = CLASSE_PROPRIA_RE.get(tribunal)
    if not rx:
        return None, None, None
    janela = texto[:16000] if tribunal == "TST" else texto[:1500]
    m = rx.search(janela)
    if not m and tribunal == "TST":
        m = TST_FALLBACK_RE.search(texto[:16000])
        if m:
            return f"? [{m.group('sigla')}]", m.start("num"), so_digitos(m.group("num"))
    if not m:
        return None, None, None
    cls = norm_espacos(m.group("classe"))
    if tribunal == "STJ":
        cls = re.sub(r"^(Superior Tribunal de Justiça|Revista Eletrônica de Jurisprudência|Exportação de Auto Texto do Word para o Editor de Documentos do STJ)\s*", "", cls)
        cls = re.sub(r"^(Superior Tribunal de Justiça|Revista Eletrônica de Jurisprudência|Exportação de Auto Texto do Word para o Editor de Documentos do STJ)\s*", "", cls)
    if tribunal == "STM":
        cls = re.sub(r"^.*?(Secretaria do Tribunal Pleno|Tribunal Pleno|SUPERIOR TRIBUNAL MILITAR|\d{2}/\d{2}/\d{4})\s+", "", cls)
        cls = re.sub(r"^(A\s+)?", "", cls)
    if tribunal == "TST":
        cls = f"{cls} [{m.group('sigla')}]"
    num_txt = m.group("num")
    # TSE antigo: "Nº 36.123 ( 43210-98.2009.6.00.0000)" -> fica com o CNJ entre parênteses
    mp = re.search(r"\(\s*([\d.\- ]+)\)", num_txt)
    if mp:
        num_txt = mp.group(1)
    num = so_digitos(num_txt)
    num = padrao_cnj(num) or num
    return cls, m.start("num"), num


def distancia_edicao(a: str, b: str, maximo: int = 1) -> int:
    """Levenshtein com corte (basta saber se <= maximo)."""
    if abs(len(a) - len(b)) > maximo:
        return maximo + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class Base:
    def __init__(self, caminho: Path):
        self.con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
        self.registros: dict[int, dict] = {}
        self.indice: dict[str, list[tuple[int, int]]] = defaultdict(list)  # digitos -> [(id, offset)]
        self.proprios: dict[str, list[int]] = defaultdict(list)             # digitos próprios -> [id]
        for (doc, id_, trib, ano, rel, nat, tipo, texto) in self.con.execute(
                "select documento_id, id, tribunal, ano, relator, natureza, tipo, texto from documentos"):
            self.registros[id_] = {"documento_id": doc, "tribunal": trib, "ano": ano, "relator": rel,
                                   "natureza": nat, "tipo": tipo, "texto": texto}
            vistos: dict[str, int] = {}
            for off, sup, dig in tokens_numericos(texto):
                if dig not in vistos:
                    vistos[dig] = off
            for dig, off in vistos.items():
                self.indice[dig].append((id_, off))
            if nat == "acordao":
                cls, off, num = classe_propria(trib, texto)
                self.registros[id_]["classe_propria"] = cls
                self.registros[id_]["cadeia_propria"] = cadeia_canonica_registro(cls)
                self.registros[id_]["numero_proprio"] = num
                self.registros[id_]["numero_proprio_offset"] = off
                if num:
                    self.proprios[num].append(id_)

    def cobertura_numero_proprio(self) -> dict:
        c: Counter = Counter()
        for r in self.registros.values():
            if r["natureza"] == "acordao":
                c[(r["tribunal"], bool(r.get("numero_proprio")))] += 1
        return dict(sorted(c.items()))

    def ocorrencias(self, digitos: str) -> list[tuple[int, int]]:
        """Registros cujo texto contém um token numérico igual aos dígitos (e offset mínimo)."""
        if not digitos:
            return []
        return sorted(self.indice.get(digitos, []), key=lambda x: (x[1], x[0]))

    def ocorrencias_substring(self, digitos: str) -> int:
        """Registros em que os dígitos são substring de algum token numérico (medida frouxa)."""
        if not digitos or len(digitos) < 4:
            return 0
        ids = set()
        for dig, lst in self.indice.items():
            if digitos in dig:
                ids.update(i for i, _ in lst)
        return len(ids)

    def relator_chave(self, nome: str | None, manter_acentos: bool = False) -> str:
        if not nome:
            return ""
        n = (nome if manter_acentos else sem_acento(nome)).lower()
        n = re.sub(r"[^a-zà-ÿ ]", " ", n)
        n = re.sub(r"\b(min|ministro|ministra|des|desembargador)\b", " ", n)
        return norm_espacos(n)

    def por_relator_ano(self, tribunal: str | None, ano: int | None, relator: str,
                        tolerancia: int = 1) -> list[int]:
        """Registros do tribunal/ano cujo relator contém todas as palavras do nome citado
        (tolerância de `tolerancia` edições por palavra, para absorver ruído de OCR)."""
        pal = [p for p in self.relator_chave(relator).split() if p not in {"de", "da", "do", "dos", "das"}]
        out = []
        for id_, r in self.registros.items():
            if r["natureza"] != "acordao":
                continue
            if tribunal and r["tribunal"] != tribunal:
                continue
            if ano and r["ano"] != ano:
                continue
            rk = self.relator_chave(r["relator"]).split()
            if pal and all(any(distancia_edicao(p, q) <= tolerancia for q in rk) for p in pal):
                out.append(id_)
        return sorted(out)


# ----------------------------------------------------------------------------------------------
# Documentos: cabeçalho e distratores
# ----------------------------------------------------------------------------------------------

CHAVE_VALOR_RE = re.compile(r"^[A-ZÀ-Ú][\wÀ-ÿ .()/-]{0,40}:\s")


def fim_do_cabecalho(texto: str) -> tuple[int, str]:
    """Offset da primeira linha de prosa e o começo dessa linha.

    Prosa = linha com >= 60 caracteres, com palavras minúsculas, que não é toda em caixa alta
    nem uma linha "Chave: valor" (Autos nº, Assunto:, Referência:, Autoridade coatora: ...)."""
    pos = 0
    for linha in texto.split("\n"):
        s = linha.strip()
        if (len(s) >= 60 and re.search(r"[a-zà-ú]{3,}\s+[a-zà-ú]{2,}", s) and not s.isupper()
                and not CHAVE_VALOR_RE.match(s)):
            return pos, s[:50]
        pos += len(linha) + 1
    return 0, ""


MESES = "janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"


def classificar_distrator(texto: str, off: int, sup: str, dig: str, fim_cab: int) -> str:
    """Rótulo heurístico para um token numérico que NÃO está em nenhum span do gabarito."""
    antes = texto[max(0, off - 40):off]
    depois = texto[off + len(sup): off + len(sup) + 25]
    a = antes.lower()
    ch_antes = texto[off - 1] if off > 0 else ""
    ch_depois = texto[off + len(sup)] if off + len(sup) < len(texto) else ""
    if (ch_antes.isalpha() or ch_depois.isalpha()) and len(sup) == 1:
        return "ocr_digito_dentro_de_palavra"
    if re.fullmatch(r"\d{1,2}", sup) and re.match(rf"\s+de\s+(?:{MESES})\b", depois, re.I):
        return "data_por_extenso_dia"
    if re.fullmatch(r"\d{4}", sup) and re.search(rf"(?:{MESES})\s+d[ec]\s*$", a):
        return "data_por_extenso_ano"
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", sup):
        return "data_numerica"
    if ch_depois == "%":
        return "percentual"
    if re.search(r"fls?\.\s*$", a) or (re.fullmatch(r"\d+/\d+", sup) and "fls" in a):
        return "referencia_fls"
    if re.search(r"oab[^\n]{0,15}$", a):
        return "oab"
    if re.search(r"r\$\s*$", a) or re.search(r"r\$\s*[\d.]+,$", a):
        return "valor_monetario"
    if re.search(r"(autos|processo|proc\.)\s*n[º°o.]?\s*$", a):
        return "numero_dos_autos_cabecalho" if off < fim_cab else "numero_dos_autos_corpo"
    if re.search(r"(memorial|protocolo|of[ií]cio|peti[cç][aã]o|parecer(?: jur[ií]dico)?)\s*n[º°o.]?\s*$", a):
        return "protocolo_ou_memorial"
    if re.search(r"(art\.?|artigo)\s*$", a):
        return "artigo_fora_do_gabarito"
    if off < fim_cab:
        return "cabecalho_outro"
    return "outro"


# ----------------------------------------------------------------------------------------------
# Programa principal
# ----------------------------------------------------------------------------------------------


def carregar(dados: Path):
    gold = list(csv.DictReader(open(dados / "goldenset.csv", encoding="utf-8-sig", newline="")))
    textos = {}
    for p in sorted((dados / "txt").glob("*.txt")):
        t = p.read_text(encoding="utf-8")
        assert t == unicodedata.normalize("NFC", t), p
        textos[p.stem] = t
    return gold, textos


def catalogar(gold, textos, base: Base) -> list[dict]:
    saida = []
    for r in gold:
        doc = r["documento_id"]
        texto = textos[doc]
        ini, fim = int(r["inicio"]), int(r["fim"])
        trecho = r["trecho"].replace("\\n", "\n")
        assert texto[ini:fim] == trecho, (doc, r["citacao_id"])
        nivel = int(r["nivel"])
        familia = inferir_familia(r, trecho)
        if familia == "processo":
            campos = parse_processo(trecho)
        elif familia == "sumula":
            campos = parse_sumula(trecho)
        elif familia == "tema":
            campos = parse_tema(trecho)
        elif familia == "dispositivo":
            campos = parse_dispositivo(trecho)
        else:
            campos = parse_vaga(trecho)
        e = {
            "documento_id": doc, "nivel": nivel, "citacao_id": r["citacao_id"],
            "inicio": ini, "fim": fim, "trecho": trecho, "tipo": r["tipo"],
            "classificacao": r["classificacao"],
            "id_canonico": int(r["id_canonico"]) if r["id_canonico"] else None,
            "familia": familia,
            "classe_processual": None, "prefixos_encadeados": [], "numero_superficie": None,
            "digitos": campos.get("digitos", ""), "formato_numero": None, "uf": None,
            "separador_uf": None, "tribunal_explicito": campos.get("tribunal_explicito"),
            "ano": campos.get("ano"), "relator": campos.get("relator"),
            "artigo": campos.get("artigo"), "diploma": campos.get("diploma"),
            "numero_sumula": campos.get("numero_sumula"), "vinculante": campos.get("vinculante"),
        }
        if familia == "processo":
            e["classe_processual"] = {"superficie": campos["classe_superficie"],
                                      "canonica": campos["classe_canonica"],
                                      "cadeia_superficie": campos["cadeia_superficie"],
                                      "estilo_cadeia": campos["estilo_cadeia"],
                                      "conector_numero": campos["conector_numero"],
                                      "palavra_processo": campos["palavra_processo"]}
            e["prefixos_encadeados"] = campos["prefixos_encadeados"]
            e["prefixos_canonicos"] = campos.get("prefixos_canonicos", [])
            e["numero_superficie"] = campos["numero_superficie"]
            e["formato_numero"] = campos["formato_numero"]
            e["uf"] = campos["uf"]
            e["separador_uf"] = campos["separador_uf"]
            e["tribunal_explicito"] = campos["tribunal_prefixo"]
            e["digitos_brutos"] = campos["digitos_brutos"]
            for k in ("ano_cnj", "segmento_cnj", "tribunal_cnj", "sobra_apos_numero"):
                if campos.get(k) not in (None, ""):
                    e[k] = campos[k]
        elif familia == "sumula":
            e["numero_superficie"] = str(campos.get("numero_sumula"))
            e["formato_numero"] = "curto"
            e["palavra_sumula"] = campos.get("palavra_sumula")
        elif familia == "tema":
            e["numero_superficie"] = str(campos.get("numero_tema"))
            e["formato_numero"] = "curto"
            e["numero_tema"] = campos.get("numero_tema")
            e["complemento_tema"] = campos.get("complemento")
        elif familia == "dispositivo":
            e["numero_superficie"] = campos.get("artigo")
            e["formato_numero"] = "artigo"
            e["palavra_artigo"] = campos.get("palavra_artigo")
            e["artigo_ordinal"] = campos.get("artigo_ordinal")
            e["subdivisoes"] = campos.get("subdivisoes")
            e["diploma_superficie"] = campos.get("diploma_superficie")
            e["preposicao_diploma"] = campos.get("preposicao_diploma")
        else:
            e["molde_vaga"] = campos.get("molde")
            e["classe_vaga"] = campos.get("classe_vaga")
            e["relator_caixa_alta"] = campos.get("relator_caixa_alta")
            e["relator_n_palavras"] = campos.get("relator_n_palavras")
            e["relator_quebra_linha"] = campos.get("relator_quebra_linha")
            e["formato_numero"] = "nenhum"
        if campos.get("erro_parse"):
            e["erro_parse"] = True
        e["ruidos"] = rotulos_ruido(trecho, familia, campos, nivel)
        e["contexto_antes"] = texto[max(0, ini - 40):ini]
        e["contexto_depois"] = texto[fim:fim + 40]
        e["char_antes"] = texto[ini - 1] if ini > 0 else ""
        e["char_depois"] = texto[fim] if fim < len(texto) else ""

        # --- base canônica
        dig = e["digitos"]
        if familia == "processo" and dig:
            occ = base.ocorrencias(dig)
            e["base_ocorrencias_token"] = len(occ)          # registros com o número em qualquer lugar
            e["base_posicao_minima"] = occ[0][1] if occ else None
            e["base_registro_posicao_minima"] = occ[0][0] if occ else None
            e["base_ocorrencias_substring"] = base.ocorrencias_substring(dig)
            e["base_registros"] = [i for i, _ in occ][:10]
            # registros em que o número é o número PRÓPRIO (cabeçalho / "autos de ... nº TST-")
            proprios = []
            for id_ in base.proprios.get(dig, []):
                reg = base.registros[id_]
                proprios.append({"id": id_, "tribunal": reg["tribunal"], "ano": reg["ano"],
                                 "classe_propria": reg.get("classe_propria"),
                                 "cadeia_propria": reg.get("cadeia_propria"),
                                 "offset": reg.get("numero_proprio_offset")})
            e["base_registros_proprios"] = proprios
            e["base_n_proprios"] = len(proprios)
            e["base_n_proprios_mesma_cadeia"] = sum(
                1 for p in proprios if p["cadeia_propria"] == campos.get("cadeia_canonica"))
        if familia == "vaga" and e.get("relator"):
            cands = base.por_relator_ano(e["tribunal_explicito"], e["ano"], e["relator"])
            e["base_candidatos_relator_ano"] = len(cands)
            e["base_candidatos_relator_ano_ids"] = cands[:10]
            exatos = base.por_relator_ano(e["tribunal_explicito"], e["ano"], e["relator"], tolerancia=0)
            # comparação preservando acentos (a->ã não some com sem_acento)
            alvo = base.relator_chave(e["relator"], manter_acentos=True)
            com_acentos = [i for i in exatos if base.relator_chave(base.registros[i]["relator"], manter_acentos=True) == alvo]
            e["relator_exato_na_base"] = bool(com_acentos)
            if cands and not com_acentos:
                e["ruidos"].append("ocr_no_nome_do_relator")
            if e.get("classe_vaga"):
                cls_v = CLASSES.get(chave(e["classe_vaga"]))
                e["classe_vaga_canonica"] = cls_v
                e["base_candidatos_relator_ano_classe"] = sum(
                    1 for i in cands if (base.registros[i].get("cadeia_propria") or [None])[-1] == cls_v)
        if e["id_canonico"]:
            reg = base.registros.get(e["id_canonico"])
            if reg:
                e["registro"] = {"tribunal": reg["tribunal"], "ano": reg["ano"], "relator": reg["relator"],
                                 "natureza": reg["natureza"], "tipo": reg["tipo"],
                                 "primeira_linha": reg["texto"].split("\n", 1)[0][:120]}
                if familia == "processo":
                    e["registro"]["classe_propria"] = reg.get("classe_propria")
                    e["registro"]["cadeia_propria"] = reg.get("cadeia_propria")
                    e["registro"]["numero_proprio"] = reg.get("numero_proprio")
                    e["registro"]["posicao_numero_proprio"] = reg.get("numero_proprio_offset")
                    toks = tokens_numericos(reg["texto"])
                    pos = [o for o, s, d in toks if d == dig]
                    e["registro"]["posicao_primeira_ocorrencia"] = pos[0] if pos else None
                    e["registro"]["numero_encontrado_no_registro"] = bool(pos)
                    e["registro"]["numero_e_o_proprio"] = reg.get("numero_proprio") == dig
                    cad_cit = campos.get("cadeia_canonica") or []
                    cad_reg = reg.get("cadeia_propria") or []
                    e["cadeia_citada"] = cad_cit
                    e["classe_principal_igual_propria"] = bool(cad_cit and cad_reg and cad_cit[-1] == cad_reg[-1])
                    e["cadeia_igual_propria"] = bool(cad_cit and cad_cit == cad_reg)
        saida.append(e)
    return saida


# ----------------------------------------------------------------------------------------------
# Resumo estatístico (para docs/03_analise_gabarito.md)
# ----------------------------------------------------------------------------------------------


def resumo(cat: list[dict], textos: dict[str, str], base: Base) -> None:
    P = print
    P("=" * 100)
    P("RESUMO DO CATÁLOGO")
    P("=" * 100)
    P("total", len(cat))
    P("por nivel/classificacao", Counter((e["nivel"], e["classificacao"]) for e in cat))
    P("por tipo", Counter(e["tipo"] for e in cat))
    P("por familia", Counter(e["familia"] for e in cat))
    P("por familia/nivel/classificacao", sorted(Counter((e["familia"], e["nivel"], e["classificacao"]) for e in cat).items()))
    P("erros de parse", [(e["documento_id"], e["citacao_id"]) for e in cat if e.get("erro_parse")])

    P("\n--- fronteira: char antes/depois ---")
    P("char_antes", Counter(repr(e["char_antes"]) for e in cat))
    P("char_depois", Counter(repr(e["char_depois"]) for e in cat))
    P("char_depois por familia", sorted(Counter((e["familia"], repr(e["char_depois"])) for e in cat).items()))
    P("palavra antes do span", Counter(e["contexto_antes"].split()[-1] if e["contexto_antes"].split() else "" for e in cat).most_common(30))
    P("quando char_depois é espaço/quebra: próxima palavra", Counter((e["familia"], e["contexto_depois"].split()[0] if e["contexto_depois"].split() else "") for e in cat if e["char_depois"] in (" ", "\n")).most_common())
    P("posição da quebra de linha dentro do span (familia, entre o quê):")
    c = Counter()
    for e in cat:
        t = e["trecho"]
        for m in re.finditer(r"\n", t):
            dir_ = t[m.end():].split()[0] if t[m.end():].split() else ""
            if e["familia"] == "processo":
                num = e["numero_superficie"] or ""
                ini_num = t.find(num) if num else -1
                if ini_num >= 0 and ini_num <= m.start() < ini_num + len(num):
                    onde = "dentro_do_numero"
                elif e["uf"] and m.start() >= ini_num + len(num):
                    onde = "antes_da_uf"
                elif re.search(r"(n[º°o.]?|N[º°o.]?)$", t[:m.start()]):
                    onde = "entre_conector_e_numero"
                elif ini_num >= 0 and m.start() < ini_num:
                    onde = "dentro_da_cadeia_de_classes"
                else:
                    onde = "outro"
            elif e["familia"] == "vaga":
                rel = e["relator"] or ""
                pos_rel = t.replace("\n", " ").find(rel)
                onde = "dentro_do_nome_do_relator" if pos_rel >= 0 and m.start() >= pos_rel else "antes_do_relator"
            elif e["familia"] == "dispositivo":
                onde = "entre_art_e_numero" if re.search(r"art\.?$", t[:m.start()]) else "dentro_do_diploma"
            elif e["familia"] == "sumula":
                onde = "antes_do_tribunal" if dir_.startswith("do") else "dentro_do_tribunal"
            else:
                onde = "outro"
            c[(e["familia"], onde, e["nivel"])] += 1
    for k, v in sorted(c.items()):
        P("   ", k, v)

    proc = [e for e in cat if e["familia"] == "processo"]
    P("\n--- processo: classes de superfície (superficie, canonica) x nivel ---")
    c = Counter((e["classe_processual"]["superficie"], e["classe_processual"]["canonica"], e["nivel"]) for e in proc)
    for k, v in sorted(c.items(), key=lambda kv: (kv[0][1] or "", kv[0][2], kv[0][0])):
        P(f"  {k[1]!s:10} N{k[2]}  {k[0]!r:45} {v}")
    P("classe canonica x classificacao", sorted(Counter((e["classe_processual"]["canonica"], e["classificacao"]) for e in proc).items(), key=lambda kv: str(kv[0])))
    P("cadeias completas (superficie) x nivel:")
    for k, v in sorted(Counter((e["classe_processual"]["cadeia_superficie"], e["nivel"]) for e in proc).items()):
        P(f"   N{k[1]} {k[0]!r}: {v}")
    P("estilo_cadeia", Counter(e["classe_processual"]["estilo_cadeia"] for e in proc))
    P("prefixos_encadeados (canonicos)", Counter(" ".join(e["prefixos_canonicos"]) for e in proc if e["prefixos_encadeados"]))
    P("n prefixos", Counter(len([p for p in e["prefixos_encadeados"] if p not in CONECTORES_CLASSE and p != "-"]) for e in proc))
    P("palavra_processo", Counter(e["classe_processual"]["palavra_processo"] for e in proc))
    P("tribunal_prefixo", Counter(e["tribunal_explicito"] for e in proc))
    P("conector_numero x nivel", sorted(Counter((repr(e["classe_processual"]["conector_numero"]), e["nivel"]) for e in proc).items()))
    P("conector + espaçamento até o número (forma literal) x nivel:")
    c = Counter()
    for e in proc:
        m = re.search(r"((?:\s|^)(?:n[º°o.]?|N[º°o.]?|n\.º|N\.º))([\s\xa0]*)$", e["trecho"][: e["trecho"].find(e["numero_superficie"])] if e["numero_superficie"] else "")
        if m:
            c[(m.group(1).strip(), repr(m.group(2)), e["nivel"])] += 1
    for k, v in sorted(c.items(), key=str):
        P("   ", k, v)
    P("espaçamento entre cadeia de classes e número quando NÃO há conector:", Counter(repr(e["trecho"][len(e["classe_processual"]["cadeia_superficie"]): e["trecho"].find(e["numero_superficie"])]) for e in proc if not e["classe_processual"]["conector_numero"] and not e["classe_processual"]["palavra_processo"] and not e["tribunal_explicito"]))
    P("formato_numero x nivel", sorted(Counter((e["formato_numero"], e["nivel"]) for e in proc).items()))
    P("formato_numero x classificacao", sorted(Counter((e["formato_numero"], e["classificacao"]) for e in proc).items()))
    P("len(digitos) curto", Counter(len(e["digitos"]) for e in proc if e["formato_numero"] == "curto"))
    P("uf presente x nivel", sorted(Counter((e["uf"] is not None, e["nivel"]) for e in proc).items()))
    P("uf x formato", sorted(Counter((e["uf"] is not None, e["formato_numero"]) for e in proc).items()))
    P("separador_uf x nivel", sorted(Counter((repr(e["separador_uf"]), e["nivel"]) for e in proc).items()))
    P("uf valores", Counter(e["uf"] for e in proc))
    P("segmento_cnj x classificacao", sorted(Counter((e.get("segmento_cnj"), e["classificacao"]) for e in proc if e.get("segmento_cnj")).items()))
    P("sobra_apos_numero", [(e["documento_id"], e["citacao_id"], e["sobra_apos_numero"]) for e in proc if e.get("sobra_apos_numero")])
    P("numero_superficie formas (N2):")
    for e in proc:
        if e["nivel"] == 2:
            P(f"   {e['documento_id']} {e['citacao_id']} {e['classificacao']:10} {e['numero_superficie']!r} -> {e['digitos']}  uf={e['uf']} sep={e['separador_uf']!r}")

    P("\n--- ruídos x nivel ---")
    c = Counter()
    for e in cat:
        for r in e["ruidos"]:
            c[(r, e["nivel"])] += 1
    for k, v in sorted(c.items()):
        P(f"   N{k[1]} {k[0]}: {v}")
    P("citações N2 sem nenhum ruído:", sum(1 for e in cat if e["nivel"] == 2 and not e["ruidos"]))
    P("citações N1 com algum ruído:", [(e["documento_id"], e["citacao_id"], e["ruidos"]) for e in cat if e["nivel"] == 1 and e["ruidos"]])
    P("substituições OCR letra->dígito observadas:")
    c = Counter()
    for e in proc:
        for ch in re.findall(r"[OolISsgGBZz]", e["numero_superficie"] or ""):
            c[(ch, OCR_MAPA[ch], e["nivel"])] += 1
    P("   ", sorted(c.items()))
    P("cobertura do número próprio na base (tribunal, encontrado):", base.cobertura_numero_proprio())
    dup = {d: ids for d, ids in base.proprios.items() if len(ids) > 1}
    iguais = sum(1 for ids in dup.values() if len({tuple(base.registros[i].get("cadeia_propria") or []) for i in ids}) == 1)
    P(f"números próprios DUPLICADOS na base: {len(dup)} (registros envolvidos: {sum(len(v) for v in dup.values())}); "
      f"com cadeia de classes idêntica (indistinguíveis pela classe): {iguais}; por tribunal: "
      f"{Counter(base.registros[ids[0]]['tribunal'] for ids in dup.values())}")
    P("   duplicados com cadeias DIFERENTES (desempate possível pela classe):")
    for d, ids in sorted(dup.items()):
        cads = [tuple(base.registros[i].get("cadeia_propria") or []) for i in ids]
        if len(set(cads)) > 1:
            P("     ", base.registros[ids[0]]["tribunal"], d, [" ".join(c) for c in cads])
    P("garantia dígito->dígito (real, dígitos da citação encontrados no registro):",
      Counter((e["nivel"], e["registro"].get("numero_encontrado_no_registro")) for e in proc if e["classificacao"] == "real"))
    P("real: dígitos == número PRÓPRIO extraído do registro:",
      Counter((e["nivel"], e["registro"].get("numero_e_o_proprio")) for e in proc if e["classificacao"] == "real"))
    P("real com número NÃO igual ao próprio:", [(e["documento_id"], e["citacao_id"], e["digitos"], e["registro"].get("numero_proprio"), e["registro"].get("classe_propria")) for e in proc if e["classificacao"] == "real" and not e["registro"].get("numero_e_o_proprio")])
    P("real: posição do número próprio no registro (tribunal, offset):", sorted((e["registro"]["tribunal"], e["registro"]["posicao_numero_proprio"]) for e in proc if e["classificacao"] == "real"))
    P("real: classe PRINCIPAL citada == própria?", Counter(e.get("classe_principal_igual_propria") for e in proc if e["classificacao"] == "real"))
    P("real: CADEIA citada == própria?", Counter(e.get("cadeia_igual_propria") for e in proc if e["classificacao"] == "real"))
    P("real: cadeia citada != própria (detalhe):")
    for e in proc:
        if e["classificacao"] == "real" and not e.get("cadeia_igual_propria"):
            P(f"   {e['documento_id']} {e['citacao_id']} citada={e['cadeia_citada']} propria={e['registro'].get('cadeia_propria')} ({e['registro'].get('classe_propria')!r}) trib={e['registro']['tribunal']}")
    P("real: nº de registros em que o número é PRÓPRIO:", Counter(e["base_n_proprios"] for e in proc if e["classificacao"] == "real"))
    P("real: nº de registros próprios com a MESMA cadeia:", Counter(e["base_n_proprios_mesma_cadeia"] for e in proc if e["classificacao"] == "real"))
    P("real com número próprio em >1 registro:", [(e["documento_id"], e["citacao_id"], e["cadeia_citada"], [(p["id"], p["cadeia_propria"]) for p in e["base_registros_proprios"]]) for e in proc if e["classificacao"] == "real" and e["base_n_proprios"] > 1])
    P("real: ocorrências do número em qualquer registro (token):", Counter(e["base_ocorrencias_token"] for e in proc if e["classificacao"] == "real"))
    P("real com número em >1 registro (qualquer posição):", [(e["documento_id"], e["citacao_id"], e["base_ocorrencias_token"], e["base_registros"]) for e in proc if e["classificacao"] == "real" and e["base_ocorrencias_token"] > 1])

    P("\n--- inventadas (processo) ---")
    inv = [e for e in proc if e["classificacao"] == "inventada"]
    P("total inventadas processo", len(inv), "| por nivel", Counter(e["nivel"] for e in inv))
    P("existe como token em algum registro:", Counter(e["base_ocorrencias_token"] > 0 for e in inv))
    P("existe como número PRÓPRIO de algum registro:", Counter(e["base_n_proprios"] > 0 for e in inv))
    P("existe como substring de token:", Counter(e["base_ocorrencias_substring"] > 0 for e in inv))
    for e in inv:
        P(f"   {e['documento_id']} {e['citacao_id']} N{e['nivel']} {e['classe_processual']['cadeia_superficie']!r:40} dig={e['digitos']:22} fmt={e['formato_numero']:6} tok={e['base_ocorrencias_token']} sub={e['base_ocorrencias_substring']} posmin={e['base_posicao_minima']} proprios={[(p['id'], p['classe_propria']) for p in e['base_registros_proprios']]}")
    P("inventada classe x formato:", sorted(Counter((e["classe_processual"]["canonica"], e["formato_numero"]) for e in inv).items(), key=str))
    P("inventada: tribunal implícito pela classe/segmento CNJ:", sorted(Counter((e["classe_processual"]["canonica"], e.get("segmento_cnj")) for e in inv).items(), key=str))

    P("\n--- súmulas ---")
    for e in cat:
        if e["familia"] == "sumula":
            P(f"   N{e['nivel']} {e['classificacao']:10} palavra={e['palavra_sumula']!r} vinc={e['vinculante']} num={e['numero_sumula']} trib={e['tribunal_explicito']} ruidos={e['ruidos']} depois={e['char_depois']!r}")
    P("\n--- temas ---")
    for e in cat:
        if e["familia"] == "tema":
            P(f"   N{e['nivel']} {e['classificacao']} {e['trecho']!r} {e['ruidos']}")
    P("\n--- dispositivos ---")
    for e in sorted((e for e in cat if e["familia"] == "dispositivo"), key=lambda e: (e["diploma"] or "", e["artigo"])):
        P(f"   N{e['nivel']} {e['classificacao']:10} art={e['artigo']:5} ord={e['artigo_ordinal']!s:5} sub={e['subdivisoes']!s:14} {e['palavra_artigo']:7} {e['preposicao_diploma']} {e['diploma_superficie']!r:40} -> {e['diploma']} id={e['id_canonico']} ruidos={e['ruidos']}")
    P("dispositivo diploma x classificacao", sorted(Counter((e["diploma"], e["classificacao"]) for e in cat if e["familia"] == "dispositivo").items(), key=str))
    P("dispositivo palavra_artigo x nivel", sorted(Counter((e["palavra_artigo"], e["nivel"]) for e in cat if e["familia"] == "dispositivo").items()))
    P("dispositivo com subdivisões", Counter(len(e["subdivisoes"]) for e in cat if e["familia"] == "dispositivo"))
    P("mesmo artigo sob dois diplomas:")
    porart = defaultdict(list)
    for e in cat:
        if e["familia"] == "dispositivo":
            porart[e["artigo"]].append((e["diploma"], e["classificacao"], e["documento_id"]))
    for a, v in porart.items():
        if len({d for d, _, _ in v}) > 1:
            P("   art", a, v)

    P("\n--- vagas ---")
    vag = [e for e in cat if e["familia"] == "vaga"]
    P("total", len(vag), "| molde x nivel", sorted(Counter((e["molde_vaga"], e["nivel"]) for e in vag).items()))
    P("molde x tribunal", sorted(Counter((e["molde_vaga"], e["tribunal_explicito"]) for e in vag).items(), key=str))
    P("classe_vaga", Counter(e["classe_vaga"] for e in vag))
    P("relator caixa alta", Counter(e["relator_caixa_alta"] for e in vag))
    P("relator n palavras", Counter(e["relator_n_palavras"] for e in vag))
    P("relator com quebra de linha", Counter(e["relator_quebra_linha"] for e in vag))
    P("quebra de linha em algum lugar do span", Counter("\n" in e["trecho"] for e in vag))
    P("char depois do relator", Counter(repr(e["char_depois"]) for e in vag))
    P("texto depois (10 chars)", Counter(e["contexto_depois"][:12] for e in vag).most_common())
    P("candidatos tribunal+ano+relator na base:", Counter(e.get("base_candidatos_relator_ano") for e in vag))
    P("candidatos tribunal+ano+relator+classe (só moldes com classe):", Counter(e.get("base_candidatos_relator_ano_classe") for e in vag if e.get("classe_vaga")))
    P("relator: palavras finais (última palavra) e o que vem depois:", Counter((e["relator"].split()[-1], e["contexto_depois"][:6]) for e in vag).most_common(40))
    for e in vag:
        P(f"   N{e['nivel']} {e['molde_vaga']:22} trib={e['tribunal_explicito']!s:4} ano={e['ano']} rel={e['relator']!r:35} cands={e.get('base_candidatos_relator_ano')} classe={e['classe_vaga']}")
    P("relatores distintos", sorted(Counter(sem_acento(e["relator"]).lower() for e in vag).items()))

    P("\n--- estatísticas por documento ---")
    pordoc = defaultdict(list)
    for e in cat:
        pordoc[e["documento_id"]].append(e)
    dists = []
    adj = []
    for d in sorted(textos):
        es = sorted(pordoc[d], key=lambda e: e["inicio"])
        P(f"   {d}: {len(es)} citações, texto_len={len(textos[d])}, primeira em {es[0]['inicio']}, última em {es[-1]['fim']}, "
          f"classes={Counter(e['classificacao'] for e in es)}")
        for a, b in zip(es, es[1:]):
            dist = b["inicio"] - a["fim"]
            dists.append(dist)
            if dist < 60:
                adj.append((d, a["citacao_id"], b["citacao_id"], dist, textos[d][a["fim"]:b["inicio"]]))
    P("citações por doc: min/med/max", min(len(v) for v in pordoc.values()), statistics.median(len(v) for v in pordoc.values()), max(len(v) for v in pordoc.values()))
    P("distância entre spans consecutivos: min/mediana/max", min(dists), statistics.median(dists), max(dists))
    P("distâncias < 60:", adj)
    P("distâncias histograma (bins de 200):", sorted(Counter(dd // 200 * 200 for dd in dists).items()))
    P("números repetidos no mesmo documento (dígitos):")
    for d, es in sorted(pordoc.items()):
        c = Counter(e["digitos"] for e in es if e["digitos"])
        for k, v in c.items():
            if v > 1:
                P("   ", d, k, v, [(e["citacao_id"], e["classificacao"]) for e in es if e["digitos"] == k])
    P("dígitos repetidos entre documentos:")
    c = Counter((e["digitos"], e["familia"]) for e in cat if e["digitos"])
    for k, v in c.items():
        if v > 1:
            P("   ", k, v, [(e["documento_id"], e["classificacao"]) for e in cat if e["digitos"] == k[0] and e["familia"] == k[1]])

    P("\n--- cabeçalho e distratores por documento ---")
    tot_dist = Counter()
    for d in sorted(textos):
        t = textos[d]
        fim_cab, marcador = fim_do_cabecalho(t)
        spans = sorted((e["inicio"], e["fim"]) for e in pordoc[d])
        primeiro = spans[0][0]
        P(f"\n   {d}: fim_cabecalho={fim_cab} (linha: {marcador!r}); primeiro span={primeiro}")
        for off, sup, dig in tokens_numericos(t):
            if any(s <= off < e for s, e in spans):
                continue
            rot = classificar_distrator(t, off, sup, dig, fim_cab)
            zona = "CAB" if off < fim_cab else ("PRE" if off < primeiro else "CORPO")
            tot_dist[(zona, rot)] += 1
            ctx = t[max(0, off - 30):off + len(sup) + 15].replace("\n", "⏎")
            P(f"      {zona:5} {off:5} {sup!r:35} {rot:32} …{ctx}…")
    P("\n   totais de distratores (zona, rótulo):")
    for k, v in sorted(tot_dist.items()):
        P("     ", k, v)
    P("\n--- armadilhas: sentenças-modelo sem identificador (fora do gabarito) ---")
    c = Counter()
    for d, t in textos.items():
        tl = re.sub(r"\s+", " ", sem_acento(t).lower())
        for frase in ARMADILHAS_SEM_ID:
            n = len(re.findall(re.escape(sem_acento(frase).lower()), tl))
            if n:
                c[frase] += n
    for k, v in c.most_common():
        P(f"   {v:3}  {k}")
    P("OCR: dígitos dentro de palavras (N2) — tokens de 1 dígito colados a letras:")
    for d, t in sorted(textos.items()):
        for m in re.finditer(r"(?<=[A-Za-zÀ-ÿ])[0-9](?=[A-Za-zÀ-ÿ])|(?<=[A-Za-zÀ-ÿ])[0-9]\b|\b[0-9](?=[A-Za-zÀ-ÿ]{2,})", t):
            P(f"   {d} {m.start()} {t[max(0, m.start()-12):m.end()+12]!r}")
    P("lacunas de citacao_id por documento (citações removidas do gabarito):")
    tot = 0
    for d, es in sorted(pordoc.items()):
        ids = sorted(int(e["citacao_id"][1:]) for e in es)
        falt = [i for i in range(1, max(ids) + 1) if i not in ids]
        tot += len(falt)
        if falt:
            P(f"   {d}: faltam {falt}")
    P("   total de lacunas:", tot)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", default="dados")
    ap.add_argument("--saida", default="dados/catalogo_gabarito.json")
    ap.add_argument("--resumo", action="store_true")
    args = ap.parse_args()
    dados = Path(args.dados)
    if not (dados / "goldenset.csv").exists() or not (dados / "txt").is_dir():
        # clone limpo sem o zip do desafio (R3e-05): nada a catalogar, sem traceback e sem falhar o make
        print(f"gabarito ausente em {dados} (goldenset.csv/txt); catálogo não gerado", file=sys.stderr)
        return
    gold, textos = carregar(dados)
    base = Base(dados / "desafio1_bracis.db")
    cat = catalogar(gold, textos, base)
    Path(args.saida).write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(cat)} citações catalogadas em {args.saida}", file=sys.stderr)
    if args.resumo:
        resumo(cat, textos, base)


if __name__ == "__main__":
    main()
