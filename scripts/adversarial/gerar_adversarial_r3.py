#!/usr/bin/env python3
"""Gerador de conjuntos ADVERSARIAIS — rodada 3 (revisor 2, generalização para o cego).

Reutiliza a infraestrutura de ``gerar_adversarial.py`` (amostrador da base, Doc, frases,
cabeçalhos, escrita do goldenset). Gabarito POR CONSTRUÇÃO a partir de ``dados/indice.json``.
Formas NOVAS em relação às rodadas 1 e 2 (nenhum conjunto repete os anteriores).

Uso: PYTHONPATH=src python scripts/adversarial/gerar_adversarial_r3.py [--seed N] [--so nome ...]

Conjuntos (>= 10 docs cada):
  r3_atos_normativos   N1: distratores com sigla de órgão igual a classe processual
                       (``Portaria MS nº``, ``Resolução CC nº``, ``Ofício AR nº``, ``Ag. 1234``
                       de agência bancária, ``Resolução SS``, ``Deliberação CP``) — ataque de FP
  r3_enumeracoes       N1: ``Súmulas N e M do T``, ``Súmulas N/T e M/T``, ``arts. X e Y do D``,
                       ``artigos X, Y e Z do D``, ``art. X c/c art. Y, ambos do D``,
                       ``REsp X e Y/UF`` (sem plural) — gabarito assumido (ver notas)
  r3_vagas_redacao     N1/N2: ``da lavra do Ministro X``, ``(Min. X)`` após o ano, tribunal
                       antes do substantivo, ``relatado por X`` sem título, ``Rel. p/ acórdão``,
                       ``Ministro X relator`` posposto, vaga toda em CAIXA ALTA, ``5TJ``/``T5T``
                       (OCR no tribunal), ``0`` no nome
  r3_sumulas_forma     N1/N2: ``Súmula STJ 443``, ``Súmula vinculante nº`` (v minúsculo),
                       ``(Superior Tribunal de Justiça)``, ``do S.T.J.``, ``do 5TJ``,
                       ``Verbete Sumular``, ``-STJ`` colado, ``Súmula n.º N do E. STJ``
  r3_dispositivos_forma N1/N2: ``Lei Federal nº``, ``art. N, IX, CF`` (sem preposição),
                       ``CF/88`` sem preposição, ``art N IX CF``, ``art. N, caput, CPC``,
                       ``do C.P.C.``, ``do CP0`` (OCR), ``do CDC (Lei 8.078/90)``
  r3_caps_corpo        N2: primeiro parágrafo do corpo inteiramente em CAIXA ALTA com citações
                       (processo, súmula, dispositivo, vaga); ``EMENTA`` em caixa alta longa
                       com citações antes da prosa (não anotadas: cabeçalho assumido)
  r3_prefixo_tribunal  N1: ``STJ/RHC N/UF``, ``STF/Rcl N/UF``, ``STJ-REsp``, ``Apelação (STM)
                       nº CNJ``, ``TSE - REspe nº``, ``STM, APL nº``; ``Rcl N-AgR/UF``
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
    Amostra, Doc, cabecalho_padrao, cit_processo_inventada, cit_processo_real, cit_vaga, cnj,
    com_pontos, enchimento, escrever, frase_com_citacao, montar_processo, nome_titulo,
    render_cadeia, TRIB_EXT,
)

NOMES_DIP = {"CC": "Código Civil", "CDC": "Código de Defesa do Consumidor", "CE": "Código Eleitoral",
             "CF": "Constituição Federal", "CLT": "CLT", "CPC": "CPC", "CPM": "Código Penal Militar",
             "CPP": "Código de Processo Penal", "LC64": "Lei Complementar nº 64/1990"}
SIGLA_DIP = {"CC": "CC", "CDC": "CDC", "CE": "CE", "CF": "CF", "CLT": "CLT", "CPC": "CPC", "CPM": "CPM",
             "CPP": "CPP", "LC64": "LC 64/90"}
PREP = {"CC": "do", "CDC": "do", "CE": "do", "CF": "da", "CLT": "da", "CPC": "do", "CPM": "do", "CPP": "do", "LC64": "da"}
OCR_TRIB = {"STJ": "5TJ", "STF": "5TF", "TST": "T5T", "TSE": "T5E", "STM": "5TM"}


# ---------------------------------------------------------------------------
def conjunto_atos_normativos(am: Amostra, rng: random.Random) -> list[Doc]:
    """Distratores: sigla de órgão/ato igual a uma classe processual, seguida de número."""
    distratores = [
        lambda: f"A Portaria MS nº {rng.randint(100, 2999)}/{rng.randint(2001, 2023)} do Ministério da Saúde regula o atendimento. ",
        lambda: f"A Portaria MS {rng.randint(100, 2999)}, de {rng.randint(2001, 2023)}, regula o atendimento. ",
        lambda: f"A Resolução CC nº {rng.randint(10, 99)}/{rng.randint(2010, 2023)} da Casa Civil disciplina a matéria. ",
        lambda: f"O Ofício AR nº {com_pontos(str(rng.randint(1000, 9999)))}/{rng.randint(2015, 2023)} comunicou a decisão à parte. ",
        lambda: f"A Resolução SS nº {rng.randint(100, 999)}/{rng.randint(2015, 2023)} da Secretaria de Saúde dispõe sobre o tema. ",
        lambda: f"A Deliberação CP nº {rng.randint(10, 99)}/{rng.randint(2015, 2023)} do Conselho Pleno dispõe sobre o tema. ",
        lambda: f"O depósito foi feito na conta {rng.randint(10000, 99999)}-{rng.randint(0, 9)}, Ag. {rng.randint(1000, 9999)}, do Banco Beta. ",
        lambda: f"O valor foi transferido para a Ag. {rng.randint(1000, 9999)}-{rng.randint(0, 9)}, conta corrente {rng.randint(10000, 99999)}-{rng.randint(0, 9)}. ",
        lambda: f"A Instrução Normativa RE nº {rng.randint(10, 99)}/{rng.randint(2015, 2023)} da Receita Estadual dispõe sobre o tema. ",
        lambda: f"A Circular AP nº {rng.randint(100, 999)}/{rng.randint(2015, 2023)} da Agência de Previdência orienta o cálculo. ",
        lambda: f"A Ordem de Serviço PC nº {rng.randint(10, 99)}/{rng.randint(2015, 2023)} da Polícia Civil instaurou o procedimento. ",
        lambda: f"O Memorando HC nº {rng.randint(10, 99)}/{rng.randint(2015, 2023)} do Hospital das Clínicas informou o prontuário. ",
        lambda: f"A Portaria MS/GM nº {com_pontos(str(rng.randint(1000, 4999)))}/{rng.randint(2001, 2023)} regula o atendimento. ",
        lambda: f"O Ato CC nº {rng.randint(1, 99)}, de {rng.randint(2015, 2023)}, da Corregedoria disciplina o ponto. ",
    ]
    docs = []
    sum_reais = [s for s in am.sumulas_reais() if not s[1]]
    for n in range(12):
        doc = Doc(f"adv_r3_atos_normativos_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab"])))
        enchimento(doc, rng, 1)
        for fn in rng.sample(distratores, 4):
            doc.add(fn())
            enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, rng.choice(["STF", "TST", "TSE", "STM"]), "misto")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        t, v, num, idc = rng.choice(sum_reais)
        G.cit_sumula(doc, rng, f"Súmula {num} do {t}", True, idc)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def conjunto_enumeracoes(am: Amostra, rng: random.Random) -> list[Doc]:
    """Enumerações de súmulas, artigos e processos. Gabarito ASSUMIDO: um span por enumeração
    de súmulas/artigos (id do primeiro elemento); processos: um span por número (rodada 2)."""
    docs = []
    sums = [s for s in am.sumulas_reais() if not s[1]]
    disp = {(d, a): idc for d, a, idc in am.dispositivos_reais()}
    por_trib: dict[str, list] = {}
    for s in sums:
        por_trib.setdefault(s[0], []).append(s)
    for n in range(12):
        doc = Doc(f"adv_r3_enumeracoes_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "eleit"])))
        enchimento(doc, rng, 1)
        # (1) Súmulas N e M do T (mesmo tribunal)
        trib = rng.choice([t for t, v in por_trib.items() if len(v) >= 2])
        a, b = rng.sample(por_trib[trib], 2)
        forma = n % 3
        if forma == 0:
            trecho = f"Súmulas {a[2]} e {b[2]} do {trib}"
        elif forma == 1:
            trecho = f"Súmulas nºs {a[2]} e {b[2]} do {trib}"
        else:
            trecho = f"Súmulas {a[2]}/{trib} e {b[2]}/{trib}"
        doc.add("Aplicam-se as ")
        doc.cit(trecho, "jurisprudencia", "real", a[3], f"enumeração de súmulas ({forma}) — gabarito assumido: 1 span, id da 1ª [alta]")
        doc.add(" ao caso, como reconhece a doutrina. ")
        enchimento(doc, rng, 1)
        # (2) Súmulas de tribunais distintos: N/T e M/U
        a, b = rng.sample(sums, 2)
        while a[0] == b[0]:
            a, b = rng.sample(sums, 2)
        doc.add("Incidem as ")
        doc.cit(f"Súmulas {a[2]}/{a[0]} e {b[2]}/{b[0]}", "jurisprudencia", "real", a[3], "Súmulas N/T e M/U — gabarito assumido [alta]")
        doc.add(", que afastam a pretensão. ")
        enchimento(doc, rng, 1)
        # (3) arts. X e Y do D (mesmo diploma)
        dips = sorted({d for d, _ in disp})
        dip = rng.choice([d for d in dips if len([1 for dd, _ in disp if dd == d]) >= 2])
        arts = [a for d, a in disp if d == dip]
        x, y = rng.sample(arts, 2)
        forma = n % 3
        if forma == 0:
            trecho = f"arts. {x} e {y} {PREP[dip]} {NOMES_DIP[dip]}"
        elif forma == 1:
            trecho = f"artigos {x} e {y} {PREP[dip]} {NOMES_DIP[dip]}"
        else:
            trecho = f"arts. {x} e {y}, ambos {PREP[dip]} {NOMES_DIP[dip]}"
        doc.add("Aplicam-se os ")
        doc.cit(trecho, "lei", "real", disp[(dip, x)], f"enumeração de artigos ({forma}) — gabarito assumido: 1 span, id do 1º [alta]")
        doc.add(" ao caso. ")
        enchimento(doc, rng, 1)
        # (4) art. X c/c art. Y, ambos do D
        x, y = rng.sample(arts, 2)
        doc.add("Aplica-se o ")
        doc.cit(f"art. {x} c/c o art. {y}, ambos {PREP[dip]} {NOMES_DIP[dip]}", "lei", "real", disp[(dip, x)], "c/c com diploma no fim — gabarito assumido: 1 span [alta]")
        doc.add(" ao caso. ")
        enchimento(doc, rng, 1)
        # (5) artigos X, Y e Z do CPC (3 elementos) — só se houver 3 artigos
        if len(arts) >= 3:
            x, y, z = rng.sample(arts, 3)
            doc.add("Veja-se o disposto nos ")
            doc.cit(f"artigos {x}, {y} e {z} {PREP[dip]} {NOMES_DIP[dip]}", "lei", "real", disp[(dip, x)], "3 artigos — gabarito assumido [media]")
            doc.add(". ")
            enchimento(doc, rng, 1)
        # (6) REsp X e Y/UF sem plural (dois spans; conhecido na ADR 0005 como pendência)
        i1 = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["RESP"], unico=True)
        i2 = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["RESP"], unico=True)
        if i1 and i2:
            doc.add("Nesse sentido, o ")
            doc.cit(f"REsp {com_pontos(i1['digitos'])}/{i1['uf']}", "jurisprudencia", "real", i1["reg"]["id_canonico"], "REsp X e Y/UF (1)")
            doc.add(" e ")
            doc.cit(f"{com_pontos(i2['digitos'])}/{i2['uf']}", "jurisprudencia", "real", i2["reg"]["id_canonico"], "REsp X e Y/UF (2) sem plural [media]")
            doc.add(", ambos da Terceira Turma. ")
            enchimento(doc, rng, 1)
        # (7) súmula inventada em enumeração (número fora da base do mesmo tribunal)
        t = rng.choice(list(por_trib))
        n_inv = rng.choice([7, 279, 126, 568, 5])
        while any(s[2] == n_inv and s[0] == t for s in sums):
            n_inv += 1
        doc.add("Incidem ainda as ")
        doc.cit(f"Súmulas {n_inv} e {rng.choice(por_trib[t])[2]} do {t}", "jurisprudencia", "inventada", None, "enumeração com 1ª inventada — gabarito assumido: classe do 1º [media]")
        doc.add(". ")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STF", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
MOLDES_R3 = [
    ("julgado do {T}, de {A}, da lavra do Ministro {N}", "da_lavra_do [alta]"),
    ("acórdão da lavra do Ministro {N}, {T}, {A}", "lavra_nome_antes [media]"),
    ("decisão do {T} de {A} (Min. {N})", "parenteses_min_sem_rel [media]"),
    ("decisão do {T} de {A} (Ministro {N})", "parenteses_ministro [media]"),
    ("julgado do {T} de {A} relatado por {N}", "relatado_por_sem_titulo [media]"),
    ("julgado do {T} de {A}, Rel. p/ acórdão Min. {N}", "rel_p_acordao [media]"),
    ("acórdão do {T} de {A}, Redator Ministro {N}", "redator [baixa]"),
    ("julgado do {T} de {A}, Ministro {N} relator", "relator_posposto [media]"),
    ("acórdão do {T}, Rel. Min. {N}, j. {A}", "rel_antes_ano_sem_parenteses [alta]"),
    ("acórdão do {T}, Rel. Min. {N}, julgado em {A}", "rel_antes_julgado_em [alta]"),
    ("{T}, {A}, Rel. Min. {N}", "tribunal_primeiro [media]"),
    ("{TX}, julgado de {A}, Rel. Min. {N}", "tribunal_extenso_primeiro [media]"),
    ("precedente do {T} de {A}, cuja relatoria coube ao Ministro {N}", "coube_ao [baixa]"),
    ("julgado do {T} proferido em {A} pela relatoria de {N}", "A (dev)"),
    ("acórdão do {T} julgado em {A} sob relatoria de {N}", "E (dev)"),
]


def conjunto_vagas_redacao(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        nivel = 1 if n < 6 else 2
        doc = Doc(f"adv_r3_vagas_redacao_n{nivel}_{n + 1:03d}", nivel)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "eleit", "mil", "trab"])))
        enchimento(doc, rng, 1)
        if nivel == 1:
            for molde, tag in rng.sample(MOLDES_R3, 6):
                cit_vaga(am, doc, rng, molde, nota=f"molde {tag}")
                enchimento(doc, rng, rng.choice([1, 2]))
        else:
            # N2: vaga toda em CAIXA ALTA (molde do dev)
            v = am.vaga()
            if v:
                trecho = f"julgado do {v['tribunal']} proferido em {v['ano']} pela relatoria de {nome_titulo(v['palavras'])}".upper()
                frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"vaga toda em CAIXA ALTA mult={v['mult']} [media]")
                enchimento(doc, rng, 1)
            # N2: OCR S→5 no tribunal (molde do dev)
            v = am.vaga()
            if v:
                trecho = f"precedente do {OCR_TRIB[v['tribunal']]} de {v['ano']}, da relatoria de {nome_titulo(v['palavras'])}"
                frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"OCR S→5 no tribunal ({OCR_TRIB[v['tribunal']]}) mult={v['mult']} [alta]")
                enchimento(doc, rng, 1)
            # N2: OCR no tribunal + caixa alta no nome (molde C-like com Rel. Min.)
            v = am.vaga()
            if v:
                trecho = f"acórdão do {OCR_TRIB[v['tribunal']]} de {v['ano']}, Rel. Min. {' '.join(v['palavras']).upper()}"
                frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"OCR no tribunal + nome em caixa alta mult={v['mult']} [alta]")
                enchimento(doc, rng, 1)
            # N2: 0 no lugar de o dentro do nome (o→0, ood)
            v = am.vaga()
            if v:
                nome = nome_titulo(v["palavras"])
                k = nome.find("o", 1)
                nome_ocr = nome[:k] + "0" + nome[k + 1:] if k > 0 else nome
                trecho = f"julgado do {v['tribunal']} de {v['ano']}, Rel. Min. {nome_ocr}"
                frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"0 no nome ({nome_ocr}) mult={v['mult']} [media]")
                enchimento(doc, rng, 1)
            # N2: REL. MIN. em caixa alta com o resto normal
            v = am.vaga()
            if v:
                trecho = f"decisão do {v['tribunal']} de {v['ano']}, REL. MIN. {' '.join(v['palavras']).upper()}"
                frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"REL. MIN. em caixa alta mult={v['mult']} [alta]")
                enchimento(doc, rng, 1)
            # N2: quebra de linha dentro de "Rel.\nMin." + NBSP antes do nome + molde novo
            v = am.vaga()
            if v:
                trecho = f"julgado do {v['tribunal']}, de {v['ano']}, da lavra do\nMinistro\xa0{nome_titulo(v['palavras'])}"
                frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"da lavra + quebra + NBSP mult={v['mult']} [media]")
                enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, rng.choice(["STJ", "STF"]), "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        # armadilhas sem os três elementos
        doc.add(rng.choice([
            "O parecer da lavra do Subprocurador-Geral, de 2019, opinou pelo desprovimento. ",
            "O voto do Ministro relator, proferido em sessão de 2021, foi acompanhado pela maioria. ",
            "A Corte Especial, em 2020, sob a presidência do Ministro Presidente, afetou o tema. ",
        ]))
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def conjunto_sumulas_forma(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    sums = [s for s in am.sumulas_reais() if not s[1]]
    sv = next(s for s in am.sumulas_reais() if s[1])
    formas = [
        (lambda t, n: f"Súmula {t} {n}", "Súmula T N [media]"),
        (lambda t, n: f"Súmula {t} nº {n}", "Súmula T nº N [media]"),
        (lambda t, n: f"Súmula {n} ({TRIB_EXT[t]})", "tribunal por extenso entre parênteses [media]"),
        (lambda t, n: f"Súmula {n} do {'.'.join(t)}.", "do S.T.J. [media]"),
        (lambda t, n: f"Verbete Sumular {n} do {t}", "Verbete Sumular [baixa]"),
        (lambda t, n: f"Súmula n.º {n}-{t}", "-STJ colado [media]"),
        (lambda t, n: f"Súmula {n} do E. {t}", "do E. STJ [media]"),
        (lambda t, n: f"Súmula {n} do {TRIB_EXT[t]} ({t})", "extenso + sigla entre parênteses [media]"),
        (lambda t, n: f"Súmula {n}, {t}", "vírgula + sigla [media]"),
        (lambda t, n: f"Súmula {t}/{n}", "Súmula T/N [baixa]"),
    ]
    formas_sv = [
        (lambda n: f"Súmula vinculante nº {n}", "vinculante minúsculo + nº [alta]"),
        (lambda n: f"súmula vinculante {n}", "tudo minúsculo [media]"),
        (lambda n: f"Súmula vinculante {n} do STF", "vinculante minúsculo + STF [alta]"),
        (lambda n: f"Súmula Vinculante {n}/STF", "SV N/STF [media]"),
        (lambda n: f"SÚMULA VINCULANTE Nº {n} DO STF", "caixa alta + STF [media]"),
        (lambda n: f"Enunciado {n} da Súmula Vinculante do STF", "Enunciado N da SV [baixa]"),
    ]
    inventadas = [("STJ", 7), ("STF", 279), ("TST", 126), ("STJ", 5), ("TSE", 31)]
    for n in range(12):
        nivel = 1 if n < 8 else 2
        doc = Doc(f"adv_r3_sumulas_forma_n{nivel}_{n + 1:03d}", nivel)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab"])))
        enchimento(doc, rng, 1)
        if nivel == 1:
            for f, nota in rng.sample(formas, 4):
                t, v, num, idc = rng.choice(sums)
                G.cit_sumula(doc, rng, f(t, num), True, idc, nota)
                enchimento(doc, rng, 1)
            f, nota = rng.choice(formas_sv)
            G.cit_sumula(doc, rng, f(sv[2]), True, sv[3], nota)
            enchimento(doc, rng, 1)
            # inventada nas mesmas formas
            f, nota = rng.choice(formas)
            t, num = rng.choice(inventadas)
            G.cit_sumula(doc, rng, f(t, num), False, None, "inventada: " + nota)
            enchimento(doc, rng, 1)
        else:
            t, v, num, idc = rng.choice(sums)
            G.cit_sumula(doc, rng, f"Súmula {num} do {OCR_TRIB[t]}", True, idc, f"OCR S→5 no tribunal ({OCR_TRIB[t]}) [alta]")
            enchimento(doc, rng, 1)
            t, v, num, idc = rng.choice(sums)
            G.cit_sumula(doc, rng, f"SÚMULA {num} DO {OCR_TRIB[t]}", True, idc, "caixa alta + OCR no tribunal [alta]")
            enchimento(doc, rng, 1)
            t, v, num, idc = rng.choice(sums)
            G.cit_sumula(doc, rng, f"Súmula {num}/{OCR_TRIB[t]}", True, idc, "N/5TJ [media]")
            enchimento(doc, rng, 1)
            G.cit_sumula(doc, rng, f"{G.com_ocr('SÚMULA', 'S', '5')} VINCULANTE {sv[2]}", True, sv[3], "SÚMULA com S→5 em caixa alta [media]")
            enchimento(doc, rng, 1)
            t, num = rng.choice(inventadas)
            G.cit_sumula(doc, rng, f"Súmula {num} do {OCR_TRIB[t]}", False, None, "inventada com OCR no tribunal")
            enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def conjunto_dispositivos_forma(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    disp = {(d, a): idc for d, a, idc in am.dispositivos_reais()}
    LEI = {"CDC": "8.078/1990", "CPC": "13.105/2015", "CC": "10.406/2002", "CE": "4.737/1965"}
    formas = [
        (lambda d, a: f"art. {a} da Lei Federal nº {LEI[d]}", ("CDC", "CPC", "CC", "CE"), "Lei Federal nº [alta]"),
        (lambda d, a: f"art. {a}, caput, {SIGLA_DIP[d]}", ("CPC", "CF", "CLT", "CDC", "CC", "CPP"), "sem preposição, sigla [alta]"),
        (lambda d, a: f"art. {a}, {SIGLA_DIP[d]}/88" if d == "CF" else f"art. {a}, {SIGLA_DIP[d]}", ("CF", "CPC", "CLT"), "sem preposição, CF/88 [alta]"),
        (lambda d, a: f"art {a} {SIGLA_DIP[d]}", ("CPC", "CF", "CLT"), "sem ponto nem preposição [media]"),
        (lambda d, a: f"art. {a} do {'.'.join(SIGLA_DIP[d])}.", ("CPC", "CPP", "CPM", "CDC", "CLT"), "sigla com pontos (C.P.C.) [media]"),
        (lambda d, a: f"art. {a} do CDC (Lei 8.078/90)", ("CDC",), "diploma + lei entre parênteses — fronteira assumida até CDC [media]"),
        (lambda d, a: f"art. {a} da Lei nº {LEI[d]} ({SIGLA_DIP[d]})", ("CDC", "CPC", "CC"), "lei + sigla entre parênteses — fronteira assumida até a lei [media]"),
        (lambda d, a: f"art. {a} da Carta Magna", ("CF",), "Carta Magna [baixa]"),
        (lambda d, a: f"art. {a} da CRFB", ("CF",), "CRFB [alta]"),
        (lambda d, a: f"art. {a} do Código de Processo Civil de 2015 (Lei nº 13.105)", ("CPC",), "de 2015 (Lei nº 13.105) — fronteira assumida até 2015 [media]"),
        (lambda d, a: f"artigo {a} da Consolidação das Leis Trabalhistas", ("CLT",), "Leis Trabalhistas [baixa]"),
        (lambda d, a: f"art. {a} do Código Civil de 2002", ("CC",), "CC de 2002 [alta]"),
        (lambda d, a: f"art. {a} da Lei de Inelegibilidade", ("LC64",), "Lei de Inelegibilidade [media]"),
        (lambda d, a: f"art. {a} do Código Eleitoral brasileiro", ("CE",), "CE + adjetivo — fronteira assumida sem o adjetivo [baixa]"),
    ]
    inventadas = [
        "art. 927 da Lei Federal nº 10.406/2002", "art. 1.500, caput, CPC", "art. 37, CF/88", "art 121 CP",
        "art. 6º do C.D.C.", "art. 400 do CDC (Lei 8.078/90)", "art. 5º da Lei nº 9.099/1995 (Lei dos Juizados)",
    ]
    for n in range(12):
        nivel = 1 if n < 8 else 2
        doc = Doc(f"adv_r3_dispositivos_forma_n{nivel}_{n + 1:03d}", nivel)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "eleit", "penal"])))
        enchimento(doc, rng, 1)
        if nivel == 1:
            for f, dips, nota in rng.sample(formas, 5):
                cands = [(d, a) for (d, a) in disp if d in dips]
                d, a = rng.choice(cands)
                trecho = f(d, a)
                # fronteiras assumidas: o span termina antes do parêntese / do adjetivo
                if " (" in trecho and "fronteira" in nota:
                    trecho_gab = trecho[:trecho.index(" (")]
                    doc.add("Aplica-se o ")
                    doc.cit(trecho_gab, "lei", "real", disp[(d, a)], nota)
                    doc.add(trecho[len(trecho_gab):] + " ao caso. ")
                elif nota.startswith("CE + adjetivo"):
                    trecho_gab = trecho[:trecho.rindex(" ")]
                    doc.add("Aplica-se o ")
                    doc.cit(trecho_gab, "lei", "real", disp[(d, a)], nota)
                    doc.add(trecho[len(trecho_gab):] + " ao caso. ")
                else:
                    G.cit_dispositivo(doc, rng, trecho, True, disp[(d, a)], nota)
                enchimento(doc, rng, 1)
            for trecho in rng.sample(inventadas, 2):
                trecho_gab = trecho[:trecho.index(" (")] if " (" in trecho else trecho
                doc.add("Aplica-se o ")
                doc.cit(trecho_gab, "lei", "inventada", None, "inventada nas formas novas")
                doc.add(trecho[len(trecho_gab):] + " ao caso. ")
                enchimento(doc, rng, 1)
        else:
            # N2: OCR nas siglas do diploma (C→0? não: O→0 e S→5 não existem em CPC; usamos CP0 (C↔0 não), então
            # aplicamos as trocas documentadas: I→l/1 não há; usamos 0 por O na CONSTITUIÇÃO e 5 em CLT→CL7? não.
            # Trocas plausíveis do gerador (letra→dígito em palavras caixa alta): O→0 e S→5, I→1.
            d, a = ("CF", rng.choice([a for (dd, a) in disp if dd == "CF"]))
            G.cit_dispositivo(doc, rng, f"art. {a} da C0NSTITUIÇÃO FEDERAL", True, disp[(d, a)], "C0NSTITUIÇÃO (O→0, caixa alta) [alta]")
            enchimento(doc, rng, 1)
            d, a = ("CPC", rng.choice([a for (dd, a) in disp if dd == "CPC"]))
            G.cit_dispositivo(doc, rng, f"ART. {a} D0 CPC", True, disp[(d, a)], "ART. D0 CPC [alta]")
            enchimento(doc, rng, 1)
            d, a = ("CLT", rng.choice([a for (dd, a) in disp if dd == "CLT"]))
            G.cit_dispositivo(doc, rng, f"art. {a} da CONSOLIDAÇÃO DA5 LEIS DO TRABALHO", True, disp[(d, a)], "DA5 (S→5) [alta]")
            enchimento(doc, rng, 1)
            d, a = ("CDC", rng.choice([a for (dd, a) in disp if dd == "CDC"]))
            G.cit_dispositivo(doc, rng, f"art. {a} do CÓDIGO DE DEFE5A DO C0NSUMIDOR", True, disp[(d, a)], "DEFE5A C0NSUMIDOR [alta]")
            enchimento(doc, rng, 1)
            d, a = ("CPP", rng.choice([a for (dd, a) in disp if dd == "CPP"]))
            G.cit_dispositivo(doc, rng, f"art. {a}, caput, CPP", True, disp[(d, a)], "sem preposição N2 [alta]")
            enchimento(doc, rng, 1)
            G.cit_dispositivo(doc, rng, "art. 121 D0 CÓDIGO PENAL", False, None, "inventada com OCR")
            enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def conjunto_caps_corpo(am: Amostra, rng: random.Random) -> list[Doc]:
    """N2: primeiro parágrafo do corpo em CAIXA ALTA com citações; ementa em caixa alta com
    citações (não anotadas — assumidas cabeçalho)."""
    docs = []
    sums = [s for s in am.sumulas_reais() if not s[1]]
    disp = [(d, a, idc) for d, a, idc in am.dispositivos_reais()]
    for n in range(12):
        doc = Doc(f"adv_r3_caps_corpo_n2_{n + 1:03d}", 2)
        layout = n % 3
        cab = cabecalho_padrao(rng, rng.choice(["civel", "penal", "trab"]))
        if layout == 2:
            # ementa em caixa alta com citações ANTES do cabeçalho padrão (cabeçalho assumido)
            i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
            t, v, num, idc = rng.choice(sums)
            ementa = (f"EMENTA: PROCESSUAL CIVIL. AGRAVO INTERNO. ÔNUS DA PROVA. INCIDÊNCIA DA SÚMULA {num} DO {t}. "
                      f"PRECEDENTE: {render_cadeia(i['cadeia'], 'STJ', 'sigla', rng).upper()} {com_pontos(i['digitos'])}/{i['uf']}. AGRAVO DESPROVIDO.\n\n")
            partes = [p for p in cab.split("\n") if not p.startswith("Trata-se")]
            doc.add("\n".join(partes).rstrip("\n") + "\n\n")
            doc.add(ementa)
            doc.add("ACÓRDÃO\n\nTrata-se de recurso interposto contra acórdão que manteve a decisão de origem, pelos fundamentos que se passa a expor. ")
            doc.notas.append("ementa com citações não anotadas (cabeçalho assumido)")
        else:
            # cabeçalho padrão SEM a primeira frase de prosa: o primeiro parágrafo do corpo é todo em caixa alta
            partes = cab.split("\n")
            partes = [p for p in partes if not p.startswith("Trata-se")]
            doc.add("\n".join(partes))
        # parágrafo em caixa alta com citações
        doc.add("TRATA-SE DE RECURSO INTERPOSTO CONTRA ACÓRDÃO QUE MANTEVE A DECISÃO DE ORIGEM, PELOS FUNDAMENTOS QUE SE PASSA A EXPOR. " if layout != 2
                else "A ORIENTAÇÃO DOS TRIBUNAIS SUPERIORES É FIRME NO PONTO, COMO SE PASSA A DEMONSTRAR. ")
        i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            doc.add("NESSE SENTIDO É O ")
            doc.cit(f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng).upper()} Nº {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], "processo em parágrafo todo em caixa alta [media]")
            doc.add(", QUE ENFRENTOU HIPÓTESE IDÊNTICA. ")
        t, v, num, idc = rng.choice(sums)
        doc.add("APLICA-SE A ")
        doc.cit(f"SÚMULA {num} DO {t}", "jurisprudencia", "real", idc, "súmula em parágrafo todo em caixa alta [media]")
        doc.add(" AO CASO. ")
        d, a, idd = rng.choice(disp)
        doc.add("INCIDE O ")
        doc.cit(f"ART. {a} {PREP[d].upper()} {NOMES_DIP[d].upper()}", "lei", "real", idd, "dispositivo em parágrafo todo em caixa alta [media]")
        doc.add(". ")
        v_ = am.vaga()
        if v_:
            doc.add("CONFIRA-SE O ")
            doc.cit(f"JULGADO DO {v_['tribunal']} PROFERIDO EM {v_['ano']} PELA RELATORIA DE {' '.join(v_['palavras']).upper()}", "jurisprudencia", "incompleta", None, f"vaga em parágrafo todo em caixa alta mult={v_['mult']} [media]")
            doc.add(". ")
        modelo = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=False)
        dinv = am.inventado(modelo)
        doc.add("VEJA-SE AINDA O ")
        doc.cit(f"{render_cadeia(modelo['cadeia'], 'STJ', 'sigla', rng).upper()} {com_pontos(dinv)}/{modelo['uf'] or 'SP'}", "jurisprudencia", "inventada", None, "inventada em caixa alta")
        doc.add(".\n")
        # depois, prosa normal com citações normais
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, rng.choice(["STF", "TST", "STM", "TSE"]), "misto")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        t, v, num, idc = rng.choice(sums)
        G.cit_sumula(doc, rng, f"Súmula {num} do {t}", True, idc)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def conjunto_prefixo_tribunal(am: Amostra, rng: random.Random) -> list[Doc]:
    """Tribunal como prefixo colado à classe. Gabarito ASSUMIDO: o span começa na classe
    (o prefixo ``STJ/``/``STJ-`` fica fora, como o artigo), exceto ``Apelação (STM) nº`` (tudo)."""
    docs = []
    for n in range(12):
        doc = Doc(f"adv_r3_prefixo_tribunal_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "mil", "eleit"])))
        enchimento(doc, rng, 1)
        # (1) STJ/RHC N/UF
        i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}"
            doc.add("Nesse sentido o STJ/")
            doc.cit(trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], "STJ/<classe> — gabarito assumido a partir da classe [media]")
            doc.add(", que enfrentou a questão. ")
            enchimento(doc, rng, 1)
        # (2) STF/Rcl
        i = am.real("STF", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            trecho = f"{render_cadeia(i['cadeia'], 'STF', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf'] or 'DF'}"
            doc.add("Confira-se STF/")
            doc.cit(trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], "STF/<classe> [media]")
            doc.add(". ")
            enchimento(doc, rng, 1)
        # (3) STJ-REsp (hífen)
        i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}"
            doc.add("Nesse sentido o STJ-")
            doc.cit(trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], "STJ-<classe> [media]")
            doc.add(", que enfrentou a questão. ")
            enchimento(doc, rng, 1)
        # (4) Apelação (STM) nº CNJ
        i = am.real("STM", lambda i: i["formato"] == "cnj" and i["cadeia"] == ["APL"], unico=True)
        if i:
            trecho = f"Apelação (STM) nº {cnj(i['digitos'], 'STM')}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "Apelação (STM) nº [media]", artigo="a")
            enchimento(doc, rng, 1)
        # (5) TSE - REspe nº
        i = am.real("TSE", lambda i: i["formato"] in ("cnj", "sequencial"), unico=True)
        if i:
            num = cnj(i["digitos"], "TSE") if i["formato"] == "cnj" else com_pontos(i["digitos"])
            trecho = f"{render_cadeia(i['cadeia'], 'TSE', 'hifen', rng)} nº {num}"
            doc.add("Veja-se TSE - ")
            doc.cit(trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], "TSE - <classe> [media]")
            doc.add(". ")
            enchimento(doc, rng, 1)
        # (6) STM, APL nº CNJ/UF
        i = am.real("STM", lambda i: i["formato"] == "cnj", unico=True)
        if i:
            trecho = montar_processo(i["cadeia"], i["digitos"], "cnj", "STM", i["uf"], "sigla", rng, conector=" nº")
            doc.add("Veja-se STM, ")
            doc.cit(trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], "STM, <classe> [media]")
            doc.add(". ")
            enchimento(doc, rng, 1)
        # (7) Rcl N-AgR/UF (sufixo com hífen)
        i = am.real("STF", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["AGR", "RCL"], unico=True)
        if i:
            trecho = f"Rcl {com_pontos(i['digitos'])}-AgR/{i['uf'] or 'DF'}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "Rcl N-AgR/UF [media]", artigo="a")
            enchimento(doc, rng, 1)
        # (8) STJ/REsp inventada (número fora da base)
        modelo = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=False)
        d = am.inventado(modelo)
        doc.add("Ainda, STJ/")
        doc.cit(f"{render_cadeia(modelo['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(d)}/{modelo['uf'] or 'SP'}", "jurisprudencia", "inventada", None, "STJ/<classe> inventada")
        doc.add(". ")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


CONJUNTOS = {
    "r3_atos_normativos": conjunto_atos_normativos,
    "r3_enumeracoes": conjunto_enumeracoes,
    "r3_vagas_redacao": conjunto_vagas_redacao,
    "r3_sumulas_forma": conjunto_sumulas_forma,
    "r3_dispositivos_forma": conjunto_dispositivos_forma,
    "r3_caps_corpo": conjunto_caps_corpo,
    "r3_prefixo_tribunal": conjunto_prefixo_tribunal,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", type=Path, default=RAIZ / "dados" / "adversarial")
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--seed", type=int, default=333)
    ap.add_argument("--so", nargs="*", default=None)
    args = ap.parse_args()
    for nome, fn in CONJUNTOS.items():
        if args.so and nome not in args.so:
            continue
        rng = random.Random(f"{args.seed}:{nome}")
        am = Amostra(args.indice, rng)
        docs = fn(am, rng)
        escrever(docs, args.saida / nome, rng, proteger=("caps" not in nome and "vagas" not in nome))
        print(f"{nome}: {len(docs)} docs, {sum(len(d.gab) for d in docs)} citações")


if __name__ == "__main__":
    main()
