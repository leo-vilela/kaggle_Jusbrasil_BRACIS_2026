#!/usr/bin/env python3
"""Gerador de conjuntos ADVERSARIAIS — rodada 5 (revisor 2, generalização para o cego, 4ª revisão).

Reutiliza a infraestrutura de ``gerar_adversarial.py`` (amostrador da base, Doc, frases,
cabeçalhos, escrita do goldenset). Gabarito POR CONSTRUÇÃO a partir de ``dados/indice.json``.
Formas NOVAS em relação a todas as rodadas anteriores (r2_*, r3_*, r4_* e os oito conjuntos
iniciais); nenhum conjunto repete os existentes.

Uso: PYTHONPATH=src python scripts/adversarial/gerar_adversarial_r5.py [--seed N] [--so nome ...]

Conjuntos (12 docs cada):
  r5_vagas_lavra_final     N1/N2: ``da lavra do Ministro X, julgado pelo T em AAAA`` (tribunal e ano
                           DEPOIS do nome), ``julgado de AAAA da relatoria do Ministro X, do T``
                           (tribunal no fim), ``cujo relator, Ministro X,``, ``S. Exa. o Ministro``,
                           ``; Rel. Min. X;``, ``- Rel. Min. X -``, ``da lavra do Min. X (T, AAAA)``,
                           ``voto condutor do Ministro X no T, em AAAA``; N2 com quebras dentro do span
  r5_processos_plural_nos  N1: ``REsps nºs X/UF e Y/UF``, ``Recursos Especiais X/UF e Y/UF``, ``REsps X,
                           Y e Z, todos do STJ`` (sem UF), ``REsp nº X/UF e nº Y/UF``, ``Rcls X e Y``
                           (STF, sem UF), ``Rcl X, de AAAA,`` / ``RHC X, de AAAA,`` (regra negativa
                           ``, de AAAA`` × 5 dígitos), ``Rcl X (AAAA)``
  r5_normativos_ocr        N2/N1: ``Lci nº 13.105/2015`` (e→c em ``Lei``), ``Lei nº l3.105`` (OCR no 1º
                           dígito da lei), ``Dccreto-Lci``, ``art. N, a, da CLT`` (alínea só), ``Novo
                           CPC``, ``art. N, I e II, c/c o art. M da CLT`` (diploma só do 2º),
                           ``Súmulas Vinculantes 10 e N``, ``Súmula de nº N do T``, ``Súmulas N e M do
                           STJ e K do TST``, ``Enunciado nº N da IV Jornada`` (distrator)
  r5_processos_ocr_combo   N2: 2–3 perturbações por citação — OCR em nome por extenso (``Rec1amação``,
                           ``Espec1al``, ``lnterno``), 3 letras no número, letra no 1º dígito + conector,
                           UF com OCR + NBSP + quebra dentro da cadeia, caixa alta com OCR
  r5_distratores_orgaos    N1: ``Enunciado N do CJF``/``da IV Jornada`` com N da tabela, súmulas
                           administrativas (AGU), OJ/SBDI, NUP/SEI/PAD/IP/Precatório/RPV/Empenho/
                           Apólice/Matrícula/Pregão/Edital, EC nº, Tema sem complemento, IRDR/IAC
  r5_layouts               N1: data e local na 1ª linha, seções numeradas (``1.1.``), ``Processo nº <CNJ>.
                           Recorrente:`` numa linha só, 1ª linha curta com citação, ``Excelentíssimo
                           Senhor Ministro,``, notas de rodapé com citações, CRLF, 45 colunas em todo o
                           arquivo, citação no fim do arquivo sem ponto, ementa multilinha em caixa alta
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gerar_adversarial as G  # noqa: E402
from gerar_adversarial import (  # noqa: E402
    Amostra, Doc, cabecalho_padrao, cit_processo_inventada, cit_processo_real, cit_vaga, com_pontos,
    enchimento, escrever, frase_com_citacao, nome_titulo, render_cadeia, TRIB_EXT, OCR_MAP,
)

NOMES_DIP = {"CC": "Código Civil", "CDC": "Código de Defesa do Consumidor", "CE": "Código Eleitoral",
             "CF": "Constituição Federal", "CLT": "Consolidação das Leis do Trabalho", "CPC": "Código de Processo Civil",
             "CPM": "Código Penal Militar", "CPP": "Código de Processo Penal", "LC64": "Lei Complementar nº 64/1990"}
PREP = {"CC": "do", "CDC": "do", "CE": "do", "CF": "da", "CLT": "da", "CPC": "do", "CPM": "do", "CPP": "do", "LC64": "da"}
LEIS = {"CPC": ("Lei", "13.105", "2015"), "CDC": ("Lei", "8.078", "1990"), "CC": ("Lei", "10.406", "2002"),
        "CE": ("Lei", "4.737", "1965"), "CLT": ("Decreto-Lei", "5.452", "1943"), "CPP": ("Decreto-Lei", "3.689", "1941"),
        "CPM": ("Decreto-Lei", "1.001", "1969"), "LC64": ("Lei Complementar", "64", "1990")}


def _vaga(am: Amostra, tribunal: str | None = None, n_palavras=(2, 4)):
    return am.vaga(tribunal, n_palavras=n_palavras)


def _molde_vaga(am: Amostra, doc: Doc, rng: random.Random, molde: str, nota: str, sufixo: str = "",
                pref: str | None = None, artigo: str | None = None) -> None:
    v = _vaga(am)
    if v is None:
        return
    nome = nome_titulo(v["palavras"])
    trecho = molde.format(T=v["tribunal"], TX=TRIB_EXT[v["tribunal"]], A=v["ano"], N=nome)
    if pref is None:
        frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"{nota} mult={v['mult']}", artigo)
    else:
        doc.add(pref)
        doc.cit(trecho, "jurisprudencia", "incompleta", None, f"{nota} mult={v['mult']}")
        doc.add(sufixo)


MOLDES_R5 = [
    # (molde, prefixo | None, sufixo, nota)
    ("precedente da lavra do Ministro {N}, julgado pelo {T} em {A}", None, "", "lavra_tribunal_ano_depois [alta]"),
    ("julgado de {A} da relatoria do Ministro {N}, do {T}", None, "", "tribunal_no_fim [alta]"),
    ("acórdão do {T} de {A}, cujo relator, Ministro {N}", "Como se vê do ", ", assentou a tese. ", "cujo_relator_virgula [media]"),
    ("decisão do {T} de {A} sob a relatoria de S. Exa. o Ministro {N}", None, "", "s_exa [media]"),
    ("acórdão do {T} de {A}; Rel. Min. {N}", "Confira-se o ", "; a tese é idêntica. ", "ponto_e_virgula [baixa]"),
    ("acórdão do {T} de {A} - Rel. Min. {N}", "Confira-se o ", " - no mesmo sentido. ", "travessao [media]"),
    ("decisão da lavra do Min. {N} ({T}, {A})", None, "", "lavra_parenteses [media]"),
    ("voto condutor do Ministro {N} no {T}, em {A}", None, "", "voto_condutor [media]"),
    ("aresto do {TX}, {A}, relator o Ministro {N}", None, "", "extenso_relator_o [controle]"),
    ("julgado do {T}, relator Ministro {N}, julgado em {A}", None, "", "relator_sem_titulo_antes [controle]"),
    ("orientação firmada pelo {T} em {A}, relator o Ministro {N}", None, "", "orientacao_firmada [controle]"),
    ("acórdão da Segunda Turma do {T}, de {A} (Rel.ª Min.ª {N})", None, "", "turma_parenteses_fem [controle]"),
]


def conjunto_vagas_lavra_final(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        nivel = 1 if n < 6 else 2
        doc = Doc(f"adv_r5_vagas_lavra_final_n{nivel}_{n + 1:03d}", nivel)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "eleit", "mil", "trab"])))
        enchimento(doc, rng, 1)
        for molde, pref, suf, nota in rng.sample(MOLDES_R5, 6):
            if nivel == 2:
                molde = molde.replace(" de {A}", rng.choice([" de {A}", " dc {A}"])).replace("Min. ", rng.choice(["Min. ", "Mln. "]))
            _molde_vaga(am, doc, rng, molde, nota, suf, pref)
            enchimento(doc, rng, rng.choice([1, 2]))
        cit_processo_real(am, doc, rng, rng.choice(["STJ", "STF"]), "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        # armadilhas sem as três âncoras
        doc.add(rng.choice([
            "O relator, Ministro Presidente, votou em 2019 pela denegação. ",
            "Da lavra do Ministro relator, o voto de 2021 nada acrescentou. ",
            "O STJ, em 2020, pela voz de seu Presidente, afetou o tema. ",
        ]))
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def _cnj_ou_pontos(i: dict) -> str:
    return G.render_numero(i["digitos"], i["formato"], i["tribunal"])


def conjunto_processos_plural_nos(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        doc = Doc(f"adv_r5_processos_plural_nos_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal"])))
        enchimento(doc, rng, 1)
        def seq7(i):
            return i["formato"] == "sequencial" and len(i["digitos"]) == 7 and i["cadeia"] == ["RESP"]
        # (1) REsps nºs X/UF e Y/UF
        a, b = am.real("STJ", seq7), am.real("STJ", seq7)
        if a and b:
            doc.add("Nesse sentido os ")
            doc.cit(f"REsps nºs {com_pontos(a['digitos'])}/{a['uf']}", "jurisprudencia", "real", a["reg"]["id_canonico"], "REsps nºs [alta]")
            doc.add(" e ")
            doc.cit(f"{com_pontos(b['digitos'])}/{b['uf']}", "jurisprudencia", "real", b["reg"]["id_canonico"], "2º da enumeração nºs [alta]")
            doc.add(". ")
            enchimento(doc, rng, 1)
        # (2) Recursos Especiais X/UF e Y/UF
        a, b = am.real("STJ", seq7), am.real("STJ", seq7)
        if a and b:
            doc.add("Colhe-se orientação no mesmo sentido nos ")
            doc.cit(f"Recursos Especiais {com_pontos(a['digitos'])}/{a['uf']}", "jurisprudencia", "real", a["reg"]["id_canonico"], "plural por extenso [alta]")
            doc.add(" e ")
            doc.cit(f"{com_pontos(b['digitos'])}/{b['uf']}", "jurisprudencia", "real", b["reg"]["id_canonico"], "2º da enumeração extenso [alta]")
            doc.add(", ambos da Corte Especial. ")
            enchimento(doc, rng, 1)
        # (3) REsps X, Y e Z, todos do STJ (sem UF)
        a, b, c = am.real("STJ", seq7), am.real("STJ", seq7), am.real("STJ", seq7)
        if a and b and c:
            doc.add("Confira-se, a propósito, os ")
            doc.cit(f"REsps {com_pontos(a['digitos'])}", "jurisprudencia", "real", a["reg"]["id_canonico"], "REsps sem UF [media]")
            doc.add(", ")
            doc.cit(com_pontos(b["digitos"]), "jurisprudencia", "real", b["reg"]["id_canonico"], "2º sem UF [media]")
            doc.add(" e ")
            doc.cit(com_pontos(c["digitos"]), "jurisprudencia", "real", c["reg"]["id_canonico"], "3º sem UF [media]")
            doc.add(", todos do STJ. ")
            enchimento(doc, rng, 1)
        # (4) REsp nº X/UF e nº Y/UF (o 2º inventado)
        a = am.real("STJ", seq7)
        modelo = am.real("STJ", seq7, unico=False)
        if a and modelo:
            d = am.inventado(modelo)
            doc.add("Invoca-se, ainda, o ")
            doc.cit(f"REsp nº {com_pontos(a['digitos'])}/{a['uf']}", "jurisprudencia", "real", a["reg"]["id_canonico"], "REsp nº X e nº Y [media]")
            doc.add(" e o ")
            doc.cit(f"nº {com_pontos(d)}/{modelo['uf'] or 'SP'}", "jurisprudencia", "inventada", None, "2º com nº repetido, inventado [media]")
            doc.add(". ")
            enchimento(doc, rng, 1)
        # (5) Rcls X e Y (STF, sem UF)
        def rcl(i):
            return i["formato"] == "sequencial" and len(i["digitos"]) == 5 and i["cadeia"][-1] == "RCL" and i["tribunal"] == "STF"
        a, b = am.real("STF", rcl), am.real("STF", rcl)
        if a and b:
            doc.add("A Suprema Corte reafirmou a tese nas ")
            doc.cit(f"Rcls {com_pontos(a['digitos'])}", "jurisprudencia", "real", a["reg"]["id_canonico"], "Rcls plural sem UF [media]")
            doc.add(" e ")
            doc.cit(com_pontos(b["digitos"]), "jurisprudencia", "real", b["reg"]["id_canonico"], "2ª Rcl sem UF [media]")
            doc.add(". ")
            enchimento(doc, rng, 1)
        # (6) Rcl X, de AAAA, / RHC X, de AAAA,
        a = am.real("STF", rcl)
        if a:
            doc.add("Como decidido na ")
            doc.cit(f"Rcl {com_pontos(a['digitos'])}", "jurisprudencia", "real", a["reg"]["id_canonico"], "Rcl 5 dígitos + ', de AAAA' [alta]")
            doc.add(f", de {a['reg']['ano']}, a tese não se sustenta. ")
            enchimento(doc, rng, 1)
        def rhc(i):
            return i["formato"] == "sequencial" and len(i["digitos"]) <= 6 and i["cadeia"][-1] in ("RHC", "RMS", "HC")
        a = am.real("STJ", rhc)
        if a:
            cad = render_cadeia(a["cadeia"], "STJ", "sigla", rng)
            doc.add("Como decidido no ")
            doc.cit(f"{cad} {com_pontos(a['digitos'])}", "jurisprudencia", "real", a["reg"]["id_canonico"], "RHC/RMS/HC + ', de AAAA' [alta]")
            doc.add(f", de {a['reg']['ano']}, a tese não se sustenta. ")
            enchimento(doc, rng, 1)
        # (7) Rcl X (AAAA) — controle
        a = am.real("STF", rcl)
        if a:
            doc.add("Veja-se a ")
            doc.cit(f"Rcl {com_pontos(a['digitos'])}", "jurisprudencia", "real", a["reg"]["id_canonico"], "Rcl (AAAA) [controle]")
            doc.add(f" ({a['reg']['ano']}), em que a Corte assentou o mesmo. ")
            enchimento(doc, rng, 1)
        # inventada com ', de AAAA' (também não pode virar real)
        modelo = am.real("STF", rcl, unico=False)
        if modelo:
            d = am.inventado(modelo)
            doc.add("Diversamente, a ")
            doc.cit(f"Rcl {com_pontos(d)}", "jurisprudencia", "inventada", None, "Rcl inventada + ', de AAAA'")
            doc.add(f", de {rng.randint(2018, 2025)}, tratou de hipótese distinta. ")
            enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_normativos_ocr(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    disp = am.dispositivos_reais()
    for n in range(12):
        nivel = 2 if n % 3 != 2 else 1
        doc = Doc(f"adv_r5_normativos_ocr_n{nivel}_{n + 1:03d}", nivel)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "penal"])))
        enchimento(doc, rng, 1)
        if nivel == 2:
            # (1) Lci nº <lei>/<ano> (e→c em Lei)
            d, a, idc = rng.choice([x for x in disp if x[0] in ("CPC", "CDC", "CC", "CE")])
            tipo, num, ano = LEIS[d]
            G.cit_dispositivo(doc, rng, f"art. {a} da Lci nº {num}/{ano}", True, idc, "Lci (e→c) [alta]")
            enchimento(doc, rng, 1)
            # (2) Lei nº l3.105/2015 (OCR no 1º dígito do número da lei)
            d, a, idc = rng.choice([x for x in disp if x[0] in ("CPC", "CC")])
            tipo, num, ano = LEIS[d]
            num_ocr = OCR_MAP[num[0]] + num[1:] if num[0] in OCR_MAP else num
            G.cit_dispositivo(doc, rng, f"art. {a} da Lei nº {num_ocr}/{ano}", True, idc, "OCR no 1º dígito da lei [media]")
            enchimento(doc, rng, 1)
            # (3) Dccreto-Lci
            d, a, idc = rng.choice([x for x in disp if x[0] in ("CLT", "CPP", "CPM")])
            tipo, num, ano = LEIS[d]
            G.cit_dispositivo(doc, rng, f"art. {a} do Dccreto-Lci nº {num}/{ano}", True, idc, "Dccreto-Lci [media]")
            enchimento(doc, rng, 1)
            # (4) Lci Complementar
            a_lc, idc_lc = G.artigo_k(am, "LC64", 0)
            G.cit_dispositivo(doc, rng, f"art. {a_lc}º da Lci Complementar nº 64/1990", True, idc_lc, "Lci Complementar [media]")
            enchimento(doc, rng, 1)
        else:
            # (5) art. N, a, da CLT (alínea sozinha)
            a, idc = G.artigo_k(am, "CLT", 2)
            G.cit_dispositivo(doc, rng, f"art. {a}, {rng.choice('ac')}, da CLT", True, idc, "alínea solta entre vírgulas [media]")
            enchimento(doc, rng, 1)
            # (6) Novo CPC
            d, a, idc = [x for x in disp if x[0] == "CPC"][0]
            G.cit_dispositivo(doc, rng, f"art. {a} do Novo CPC", True, idc, "Novo CPC [media]")
            enchimento(doc, rng, 1)
            # (7) art. N, I e II, c/c o art. M da CLT — diploma só do 2º (gabarito assumido: só o 2º)
            a, idc = G.artigo_k(am, "CLT", 1)
            doc.add(f"Aplica-se o art. {G.artigo_k(am, 'CPC')[0]}, I e II, c/c o ")
            doc.cit(f"art. {a} da CLT", "lei", "real", idc, "c/c com diploma só no 2º (assumido) [media]")
            doc.add(". ")
            enchimento(doc, rng, 1)
            # (8) Súmula de nº N do T
            s_num, s_id = G.sumula_k(am, "STJ", k=2)
            G.cit_sumula(doc, rng, f"Súmula de nº {s_num} do STJ", True, s_id, "Súmula de nº [baixa]")
            enchimento(doc, rng, 1)
        # (9) Súmulas Vinculantes 10 e N (um span, número do 1º — ADR 0005)
        sv_num, sv_id = G.sumula_k(am, "STF", True)
        G.cit_sumula(doc, rng, f"Súmulas Vinculantes {sv_num} e {rng.choice([37, 45, 56])}", True, sv_id, "Súmulas Vinculantes plural [media]")
        enchimento(doc, rng, 1)
        # (10) Súmulas N e M do STJ e K do TST (um span, id do 1º)
        (n1, id1), (n2, _), (n3, _) = G.sumula_k(am, "STJ", k=2), G.sumula_k(am, "STJ", k=1), G.sumula_k(am, "TST")
        G.cit_sumula(doc, rng, f"Súmulas {n1} e {n2} do STJ e {n3} do TST", True, id1, "enumeração com dois tribunais [media]")
        enchimento(doc, rng, 1)
        # (11) distrator: Enunciado nº N da IV Jornada / Enunciado M do CJF (números da tabela de súmulas)
        doc.add(rng.choice([f"Cf. o Enunciado nº {n3} da IV Jornada de Direito Civil do CJF. ",
                            f"Cf. o Enunciado {n2} do CJF, aprovado na V Jornada de Direito Civil. ",
                            f"Cf. o Enunciado {n1} da I Jornada de Direito Comercial. "]))
        enchimento(doc, rng, 1)
        # controles
        d, a, idc = rng.choice(disp)
        G.cit_dispositivo(doc, rng, f"art. {a} {PREP[d]} {NOMES_DIP[d]}", True, idc)
        enchimento(doc, rng, 1)
        d, a, idc = rng.choice(disp)
        G.cit_dispositivo(doc, rng, f"art. 9{a} {PREP[d]} {NOMES_DIP[d]}", False, None, "inventada controle")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def _ocr_letras(num: str, rng: random.Random, k: int) -> str:
    return G.ocr_no_numero(num, rng, k)


def conjunto_processos_ocr_combo(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        doc = Doc(f"adv_r5_processos_ocr_combo_n2_{n + 1:03d}", 2)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "trab"])))
        enchimento(doc, rng, 1)
        # (1) Rec1amação / Recurso Espec1al (l→1 / i→1) com número limpo
        i = am.real("STF", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["AGR", "RCL"])
        if i:
            frase_com_citacao(doc, f"Rec1amação {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "Rec1amação (l→1) [media]", artigo="a")
            enchimento(doc, rng, 1)
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["RESP"])
        if i:
            frase_com_citacao(doc, f"Recurso Espec1al nº {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "Espec1al (i→1) [media]")
            enchimento(doc, rng, 1)
        # (2) 3 letras de OCR no número (mapa do dev) + sigla com OCR
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["digitos"]) == 7 and sum(c in OCR_MAP for c in i["digitos"][1:]) >= 3)
        if i:
            num = _ocr_letras(com_pontos(i["digitos"]), rng, 3)
            cad = render_cadeia(i["cadeia"], "STJ", "sigla", rng).replace("REsp", "RE5p").replace("AREsp", "ARE5p")
            frase_com_citacao(doc, f"{cad} {num}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "3 letras OCR + sigla OCR [media]")
            enchimento(doc, rng, 1)
        # (3) letra no 1º dígito + conector + UF com OCR
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["digitos"]) == 7 and i["digitos"][0] in OCR_MAP and i["uf"] and any(c in "SO" for c in i["uf"]))
        if i:
            num = OCR_MAP[i["digitos"][0]] + com_pontos(i["digitos"])[1:]
            uf = i["uf"].replace("S", "5").replace("O", "0")
            cad = render_cadeia(i["cadeia"], "STJ", "sigla", rng)
            frase_com_citacao(doc, f"{cad} n.º {num}/{uf}", "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "letra no 1º dígito + UF OCR [media]")
            enchimento(doc, rng, 1)
        # (4) NBSP + quebra dentro da cadeia + espaço duplo
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["cadeia"]) >= 2)
        if i:
            cad = render_cadeia(i["cadeia"], "STJ", "sigla", rng).replace(" no ", "\u00a0no\n", 1).replace(" nos ", "  nos\n", 1)
            frase_com_citacao(doc, f"{cad}\u00a0nº\u00a0{com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "NBSP + quebra + espaço duplo [media]")
            enchimento(doc, rng, 1)
        # (5) caixa alta com OCR no nome por extenso e no número
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] in ("RESP", "ARESP"))
        if i:
            ext = render_cadeia(i["cadeia"], "STJ", "extenso", rng).upper().replace("ESPECIAL", "E5PECIAL").replace("AGRAVO", "AGRAV0")
            num = _ocr_letras(com_pontos(i["digitos"]), rng, 1)
            frase_com_citacao(doc, f"{ext} Nº {num}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "caixa alta + OCR [media]")
            enchimento(doc, rng, 1)
        # (6) CNJ TST com 3 letras + T5T + quebra
        i = am.real("TST", lambda i: i["formato"] == "cnj")
        if i:
            c = _ocr_letras(G.cnj(i["digitos"], "TST"), rng, 3)
            cad = render_cadeia(i["cadeia"], "TST", "sigla", rng)
            frase_com_citacao(doc, f"T5T-{cad}-{c}", "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "CNJ 3 letras + T5T [media]")
            enchimento(doc, rng, 1)
        # (7) inventada com as mesmas perturbações (não pode virar real)
        modelo = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["digitos"]) == 7, unico=False)
        if modelo:
            d = am.inventado(modelo)
            num = _ocr_letras(com_pontos(d), rng, 2)
            frase_com_citacao(doc, f"Recurso Espec1al {num}/{modelo['uf'] or 'SP'}", "jurisprudencia", "inventada", None, rng, "inventada com OCR duplo")
            enchimento(doc, rng, 1)
        # (8) súmula com OCR na palavra + tribunal com OCR
        (n1, id1), (n2, id2), (n3, id3) = G.sumula_k(am, "STJ", k=2), G.sumula_k(am, "STJ", k=1), G.sumula_k(am, "TST")
        s = rng.choice([(f"{G.com_ocr('Súmula', 'l', '1')} {n1} do {G.com_ocr('STJ', 'S', '5')}", id1),
                        (f"{G.com_ocr('SÚMULA', 'S', '5')} {n2} {G.com_ocr('DO', 'O', '0')} STJ", id2),
                        (f"{G.com_ocr('Sumula', 'l', '1')} nº {n3} do {G.com_ocr('TST', 'S', '5')}", id3)])
        frase_com_citacao(doc, s[0], "jurisprudencia", "real", s[1], rng, "súmula OCR combo", artigo="a")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def _distratores(am: Amostra) -> list[str]:
    """Distratores com os números da tabela de súmulas sob órgãos não jurisdicionais (consulta posicional)."""
    (n1, _), (n2, _), (n3, _) = G.sumula_k(am, "STJ", k=2), G.sumula_k(am, "STJ", k=1), G.sumula_k(am, "TST")
    return [
        f"O Enunciado {n3} do CJF, aprovado na IV Jornada de Direito Civil, orienta a interpretação. ",
        f"Cf. o Enunciado nº {n2} da V Jornada de Direito Civil e o Enunciado {n1} da I Jornada de Direito Comercial. ",
    ] + DISTRATORES


DISTRATORES = [
    "A Súmula Administrativa nº 12 da AGU e a Súmula AGU nº 45 vinculam a Administração. ",
    "A OJ 394 da SBDI-1 do TST e a Orientação Jurisprudencial nº 191 da SDI-1 orientam a matéria. ",
    "O NUP 00400.001234/2020-11 e o SEI nº 12345.678901/2020-12 foram autuados em 2020. ",
    "O PAD nº 45/2019, o Inquérito Policial nº 123/2020 e o IP nº 4.567/2019 tramitaram em apenso. ",
    "O Precatório nº 123456 e a RPV nº 2020.12345 foram expedidos; o Empenho nº 2020NE000123 consta. ",
    "A Apólice nº 1234567, a Matrícula nº 12.345 do 1º CRI e a Certidão nº 45.678 constam dos autos. ",
    "O Pregão Eletrônico nº 12/2020, o Edital nº 1/2020 e a Nota Técnica nº 12/2020 regulam o certame. ",
    "A EC nº 45/2004 e a Emenda Constitucional nº 103/2019 alteraram o regime; a EC 20/1998 idem. ",
    "O Tema 1234 e o Tema Repetitivo 988 foram afetados em 2019; a tese é vinculante. ",
    "O IRDR nº 12 do TJSP e o IAC nº 3 do STJ tratam de hipótese diversa. ",
    "A Recomendação CNJ nº 62/2020 e o Provimento CGJ nº 12/2020 aplicam-se aos feitos em curso. ",
    "O Ofício nº 123/2020-GAB, o Parecer PGFN/CRJ nº 1.234/2020 e o Despacho nº 45/2020 foram juntados. ",
    "O réu (CPF 123.456.789-00, RG 12.345.678-9), telefone (11) 98765-4321, foi citado em 20200312. ",
    "A empresa (CNPJ 12.345.678/0001-90), representada pelo advogado OAB 123456, apresentou a NF-e nº 123.456. ",
    "O valor de R$ 1.234.567,89, corrigido pelo IPCA (10,06% em 2021) e pela SELIC (9,25%), consta da Tabela 3. ",
    "Vide o item 2.3.4 do parecer, a cláusula 12.1 do contrato nº 45/2019 e o quesito nº 7 da perícia (fls. 1.234/1.240). ",
    "A Lei nº 8.078/1990, o Decreto nº 9.412/2018 e a MP nº 1.045/2021 tratam da matéria; o art. 5º garante o direito. ",
    "A súmula do STJ sobre o tema é clara; o verbete sumular aplicável à espécie também; a Súmula é antiga. ",
    "A Instrução Normativa RFB nº 1.500/2014 e o Ato Declaratório nº 12/2020 regulam o ponto. ",
    "O documento ID 987654321 (Num. 12345678 - Pág. 3) e o Protocolo nº 2020.1234567 constam. ",
]


def conjunto_distratores_orgaos(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    sums = [s for s in am.sumulas_reais() if not s[1]]
    disp = am.dispositivos_reais()
    for n in range(12):
        doc = Doc(f"adv_r5_distratores_orgaos_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "trab"])))
        enchimento(doc, rng, 1)
        itens = rng.sample(_distratores(am), 7)
        for k, dist in enumerate(itens):
            doc.add(dist)
            if k == 1:
                cit_processo_real(am, doc, rng, "STJ", "sigla")
            if k == 3:
                t, v, num, idc = rng.choice(sums)
                G.cit_sumula(doc, rng, f"Súmula {num} do {t}", True, idc)
            if k == 5:
                d, a, idc = rng.choice(disp)
                G.cit_dispositivo(doc, rng, f"art. {a} {PREP[d]} {NOMES_DIP[d]}", True, idc)
            enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_layouts(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    sums = [s for s in am.sumulas_reais() if not s[1]]
    for n in range(12):
        layout = n % 6
        doc = Doc(f"adv_r5_layouts_n1_{n + 1:03d}", 1)
        cnj_cab = f"{rng.randint(1000000, 9999999)}-{rng.randint(10, 99)}.{rng.randint(2018, 2024)}.8.26.{rng.randint(1, 999):04d}"
        if layout == 0:
            doc.add("São Paulo, 12 de março de 2024.\n\nAo Juízo da 3ª Vara Cível da Comarca de Campinas.\n\n"
                    "EMPRESA ALFA LTDA., nos autos da ação que move contra BANCO BETA S.A., vem expor e requerer o que segue. ")
            doc.notas.append("data e local na 1ª linha")
        elif layout == 1:
            doc.add("1. RELATÓRIO\n\n1.1. Trata-se de recurso interposto contra a sentença que julgou procedente o pedido, pelos fundamentos que se passa a expor. ")
            doc.notas.append("seções numeradas")
        elif layout == 2:
            doc.add(f"MINISTÉRIO PÚBLICO FEDERAL\n\nPARECER\n\nProcesso nº {cnj_cab}. Recorrente: JOÃO DA SILVA. Recorrido: UNIÃO. "
                    "Trata-se de recurso especial interposto contra acórdão que manteve a sentença, pelos fundamentos que se passa a expor. ")
            doc.notas.append("Processo nº <CNJ> + partes + prosa na mesma linha")
        elif layout == 3:
            doc.add("Cuida-se de habeas corpus.\n")
            t, v, num, idc = rng.choice(sums)
            doc.add("Invoca-se a ")
            doc.cit(f"Súmula {num} do {t}", "jurisprudencia", "real", idc, "citação na 2ª linha curta")
            doc.add(".\nA impetração sustenta que a prisão preventiva carece de fundamentação idônea, pelos fundamentos que se passa a expor. ")
            doc.notas.append("1ª linha curta + citação na 2ª linha curta")
        elif layout == 4:
            doc.add("Excelentíssimo Senhor Ministro,\nTrata-se de recurso interposto contra a sentença que julgou procedente o pedido, pelos fundamentos que se passa a expor. ")
            doc.notas.append("vocativo curto + prosa na 2ª linha")
        else:
            doc.add("EMENTA\nPROCESSUAL CIVIL. AGRAVO INTERNO.\nÔNUS DA PROVA. REEXAME DE FATOS.\nAGRAVO DESPROVIDO.\n\nACÓRDÃO\n\n"
                    "Vistos, relatados e discutidos estes autos, acordam os Ministros em negar provimento ao agravo, nos termos do voto do relator. ")
            doc.notas.append("ementa multilinha em caixa alta sem citações + ACÓRDÃO")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, rng.choice(["STF", "TST", "STM", "TSE"]), "misto")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        t, v, num, idc = rng.choice(sums)
        G.cit_sumula(doc, rng, f"Súmula {num} do {t}", True, idc)
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        if n % 2 == 0:
            # notas de rodapé com citações
            doc.add("A tese encontra amparo na jurisprudência¹ e na doutrina².\n\n____________\n¹ ")
            i = am.real("STJ", lambda i: i["formato"] == "sequencial")
            if i:
                doc.cit(f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], "nota de rodapé")
                doc.add(", Rel. Min. Fulano de Tal, DJe 12/03/2019.\n² ")
            t, v, num, idc = rng.choice(sums)
            doc.cit(f"Súmula {num} do {t}", "jurisprudencia", "real", idc, "nota de rodapé 2")
            doc.add(".\n³ Cf. ")
            v_ = am.vaga(None, n_palavras=(2, 4))
            if v_:
                doc.cit(f"acórdão do {v_['tribunal']} de {v_['ano']}, Rel. Min. {nome_titulo(v_['palavras'])}", "jurisprudencia", "incompleta", None, "nota de rodapé 3 (vaga) sem ponto no fim do arquivo")
        else:
            doc.add("Por fim, ampara a pretensão o ")
            i = am.real("STJ", lambda i: i["formato"] == "sequencial")
            if i:
                doc.cit(f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} nº {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], "fim do arquivo sem ponto")
        docs.append(doc)
    return docs


def escrever_layouts(docs: list[Doc], pasta: Path, rng: random.Random) -> None:
    """Escreve com larguras variadas: 45 colunas (n%4==1), CRLF (n%4==2), sem quebra (n%4==3)."""
    import csv
    (pasta / "txt").mkdir(parents=True, exist_ok=True)
    linhas = []
    for k, doc in enumerate(docs):
        texto = doc.texto()
        modo = k % 4
        if modo == 0:
            texto = G.quebrar(texto, 100, doc.protegidos, rng, True)
        elif modo == 1:
            texto = G.quebrar(texto, 45, doc.protegidos, rng, False)
        elif modo == 2:
            texto = G.quebrar(texto, 90, doc.protegidos, rng, True)
            # CRLF: troca cada \n por \r\n e recalcula offsets (cada quebra antes do span soma 1)
            partes = texto.split("\n")
            novo = "\r\n".join(partes)
            desloc = [0]
            pos = 0
            for p in partes[:-1]:
                pos += len(p) + 1
                desloc.append(pos)
            for g in doc.gab:
                n_antes_ini = sum(1 for d in desloc[1:] if d <= g["inicio"])
                n_antes_fim = sum(1 for d in desloc[1:] if d < g["fim"])
                g["inicio"] += n_antes_ini
                g["fim"] += n_antes_fim
            texto = novo
            doc.notas.append("CRLF")
        for g in doc.gab:
            g["trecho"] = texto[g["inicio"]:g["fim"]]
            assert g["trecho"].replace("\r\n", " ").replace("\n", " ") == g["trecho"].replace("\r\n", " ").replace("\n", " ")
        (pasta / "txt" / f"{doc.id}.txt").write_bytes(texto.encode("utf-8"))
        spans = sorted((g["inicio"], g["fim"]) for g in doc.gab)
        for a, b in zip(spans, spans[1:]):
            assert b[0] >= a[1], (doc.id, a, b)
        linhas.extend(doc.gab)
    with open(pasta / "goldenset.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=G.COLUNAS, extrasaction="ignore", lineterminator="\r\n")
        w.writeheader()
        for g in linhas:
            linha = dict(g)
            linha["trecho"] = linha["trecho"].replace("\r", "\\r").replace("\n", "\\n")
            w.writerow(linha)
    with open(pasta / "gabarito_notas.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=G.COLUNAS + ["nota"], lineterminator="\r\n")
        w.writeheader()
        for g in linhas:
            linha = dict(g)
            linha["trecho"] = linha["trecho"].replace("\r", "\\r").replace("\n", "\\n")
            w.writerow(linha)
    notas = [f"{d.id}: {x}" for d in docs for x in d.notas]
    if notas:
        (pasta / "avisos.txt").write_text("\n".join(notas), encoding="utf-8")


CONJUNTOS = {
    "r5_vagas_lavra_final": conjunto_vagas_lavra_final,
    "r5_processos_plural_nos": conjunto_processos_plural_nos,
    "r5_normativos_ocr": conjunto_normativos_ocr,
    "r5_processos_ocr_combo": conjunto_processos_ocr_combo,
    "r5_distratores_orgaos": conjunto_distratores_orgaos,
    "r5_layouts": conjunto_layouts,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", type=Path, default=RAIZ / "dados" / "adversarial")
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--seed", type=int, default=555)
    ap.add_argument("--so", nargs="*", default=None)
    args = ap.parse_args()
    for nome, fn in CONJUNTOS.items():
        if args.so and nome not in args.so:
            continue
        rng = random.Random(f"{args.seed}:{nome}")
        am = Amostra(args.indice, rng)
        docs = fn(am, rng)
        if nome == "r5_layouts":
            escrever_layouts(docs, args.saida / nome, rng)
        else:
            escrever(docs, args.saida / nome, rng, proteger=(nome not in ("r5_processos_ocr_combo",)) and not nome.endswith("lavra_final"))
        print(f"{nome}: {len(docs)} docs, {sum(len(d.gab) for d in docs)} citações")


if __name__ == "__main__":
    main()
