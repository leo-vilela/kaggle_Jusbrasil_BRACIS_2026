#!/usr/bin/env python3
"""Gerador de conjuntos ADVERSARIAIS — rodada 4 (engenheiro da correção, após a revisão da rodada 3).

Cobre as formas que o revisor 1 mediu FORA do repositório (r3_vagas_relator_antes, r3_ocr_duplo,
r3_cabecalhos_novos) e as regras negativas novas com citações legítimas ao lado, para medir FP.
Reutiliza a infraestrutura de ``gerar_adversarial.py``; gabarito POR CONSTRUÇÃO.

Uso: PYTHONPATH=src python scripts/adversarial/gerar_adversarial_r4.py [--seed N] [--so nome ...]

Conjuntos (12 docs cada):
  r4_vagas_relator_antes  N1: relator ANTES do ano sem parênteses (``acórdão do T, Rel. Min. X, j. AAAA``,
                          ``julgado do T, Rel. Min. X, de AAAA``, ``precedente do T, Rel. Min. X, julgado em
                          AAAA``, ``decisão do T, Relator Ministro X, AAAA``, ``acórdão do <T extenso>, Rel.
                          Min. X, DJe AAAA``, ``precedente do T, da relatoria do Ministro X, de AAAA``,
                          ``j. dd/mm/AAAA``) — R5-01
  r4_ocr_duplo            N2: OCR na palavra ``art.`` (``artlgo``, ``ãrt.``, ``Art1go``) + OCR no diploma — R5-02
  r4_cabecalhos_novos     N1: ``Apelação Cível nº <CNJ> da Comarca de …, em que é apelante …`` como linha longa
                          do cabeçalho; ``Processo: <CNJ>`` na 1ª linha; sem cabeçalho — R5-05
  r4_negativas_vizinhas   N1: as regras negativas novas (Portaria MS, Ag. bancária, STJ/REsp, ``, de AAAA``)
                          ao lado de citações legítimas parecidas (``MS 12.345/DF``, ``AgRg no MS``,
                          ``RE N, de AAAA``) — R3-01/R3-02/R3-09 (FP × FN)
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
    enchimento, escrever, render_cadeia,
)

NOMES_DIP = {"CC": "Código Civil", "CDC": "Código de Defesa do Consumidor", "CE": "Código Eleitoral",
             "CF": "Constituição Federal", "CLT": "Consolidação das Leis do Trabalho", "CPC": "Código de Processo Civil",
             "CPM": "Código Penal Militar", "CPP": "Código de Processo Penal", "LC64": "Lei Complementar nº 64/1990"}
PREP = {"CC": "do", "CDC": "do", "CE": "do", "CF": "da", "CLT": "da", "CPC": "do", "CPM": "do", "CPP": "do", "LC64": "da"}
OCR_DIP = {"CF": "Constituição Fcderal", "CPC": "Código de Proccsso Civil", "CC": "Códlgo Civil",
           "CDC": "Código de Defesa do Consumldor", "CLT": "Consolidação das Leis do Trabãlho",
           "CPP": "Código de Processo Penãl", "CPM": "Código Penal Mllitar", "CE": "Código Eleitorãl"}

MOLDES_R4 = [
    ("acórdão do {T}, Rel. Min. {N}, j. {A}", "rel_antes_j [alta]"),
    ("julgado do {T}, Rel. Min. {N}, de {A}", "rel_antes_de [alta]"),
    ("precedente do {T}, Rel. Min. {N}, julgado em {A}", "rel_antes_julgado_em [alta]"),
    ("decisão do {T}, Relator Ministro {N}, {A}", "relator_extenso_antes [alta]"),
    ("acórdão do {TX}, Rel. Min. {N}, DJe {A}", "extenso_rel_antes_dje [alta]"),
    ("precedente do {T}, da relatoria do Ministro {N}, de {A}", "relatoria_antes_de [alta]"),
    ("acórdão do {T}, Rel. Min. {N}, j. 12/03/{A}", "rel_antes_data_completa [media]"),
    ("aresto do {T}, Rel. Min. {N}, DJe de 3 de maio de {A}", "rel_antes_dje_extenso [media]"),
    ("julgado do {T} proferido em {A} pela relatoria de {N}", "A (dev)"),
]


def conjunto_vagas_relator_antes(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        doc = Doc(f"adv_r4_vagas_relator_antes_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "eleit", "mil", "trab"])))
        enchimento(doc, rng, 1)
        for molde, tag in rng.sample(MOLDES_R4, 5):
            cit_vaga(am, doc, rng, molde, nota=f"molde {tag}")
            enchimento(doc, rng, rng.choice([1, 2]))
        cit_processo_real(am, doc, rng, rng.choice(["STJ", "STF"]), "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        # armadilhas: relator + ano sem tribunal; tribunal + ano sem relator
        doc.add(rng.choice([
            "O relator, Ministro Presidente, em 2019, indeferiu a liminar. ",
            "O STJ, em 2020, afetou o tema ao rito dos repetitivos. ",
            "Conforme o voto do Rel. Min. Presidente na sessão de 2021, nada se decidiu. ",
        ]))
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_ocr_duplo(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    disp = [(d, a, idc) for d, a, idc in am.dispositivos_reais()]
    palavras_art = ["artlgo", "ãrt.", "Art1go", "artlgo", "ãrt.", "art1go", "Artlgo", "ãrtigo"]
    for n in range(12):
        doc = Doc(f"adv_r4_ocr_duplo_n2_{n + 1:03d}", 2)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "penal"])))
        enchimento(doc, rng, 1)
        for d, a, idc in rng.sample(disp, 3):
            art = rng.choice(palavras_art)
            nome = OCR_DIP.get(d, NOMES_DIP[d]) if rng.random() < 0.6 else NOMES_DIP[d]
            G.cit_dispositivo(doc, rng, f"{art} {a} {PREP[d]} {nome}", True, idc, f"OCR na palavra art ({art}) [media]")
            enchimento(doc, rng, 1)
        d, a, idc = rng.choice(disp)
        G.cit_dispositivo(doc, rng, f"{rng.choice(palavras_art)} 9{a} {PREP[d]} {NOMES_DIP[d]}", False, None, "inventada com OCR na palavra art")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_cabecalhos_novos(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    sums = [s for s in am.sumulas_reais() if not s[1]]
    for n in range(12):
        doc = Doc(f"adv_r4_cabecalhos_novos_n1_{n + 1:03d}", 1)
        layout = n % 3
        cnj_cab = f"{rng.randint(1000000, 9999999)}-{rng.randint(10, 99)}.{rng.randint(2018, 2024)}.8.26.{rng.randint(1, 999):04d}"
        if layout == 0:
            doc.add("TRIBUNAL DE JUSTIÇA DO ESTADO DE SÃO PAULO\n\n"
                    f"Apelação Cível nº {cnj_cab} da Comarca de Campinas, em que é apelante EMPRESA ALFA LTDA. e apelado "
                    "JOÃO DA SILVA PEREIRA.\nRelator: Des. Sicrano de Tal\n\nVOTO\n\n")
            doc.notas.append("apelacao_linha_longa (cabeçalho assumido)")
        elif layout == 1:
            doc.add(f"Processo: {cnj_cab}\nClasse: Agravo de Instrumento\nRelator: Des. Sicrano de Tal\n\nDECISÃO\n\n")
            doc.notas.append("Processo: CNJ na 1ª linha (cabeçalho assumido)")
        else:
            doc.notas.append("sem cabeçalho")
        doc.add("Trata-se de recurso interposto contra a sentença que julgou procedente o pedido, pelos fundamentos que se passa a expor. ")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, rng.choice(["STF", "TST", "STM"]), "misto")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        t, v, num, idc = rng.choice(sums)
        G.cit_sumula(doc, rng, f"Súmula {num} do {t}", True, idc)
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_negativas_vizinhas(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        doc = Doc(f"adv_r4_negativas_vizinhas_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab"])))
        enchimento(doc, rng, 1)
        # distrator + citação legítima parecida na mesma frase
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] in ("MS", "RMS", "HC", "RHC"), unico=True)
        if i:
            doc.add(f"A Portaria MS nº {rng.randint(100, 2999)}/{rng.randint(2001, 2023)} foi examinada no ")
            doc.cit(f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real",
                    i["reg"]["id_canonico"], "citação legítima ao lado de Portaria MS")
            doc.add(", que a considerou válida. ")
            enchimento(doc, rng, 1)
        i = am.real("STF", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] == "RE" and len(i["digitos"]) >= 6, unico=True)
        if i:
            doc.add("Nesse sentido, o ")
            doc.cit(f"RE {com_pontos(i['digitos'])}", "jurisprudencia", "real", i["reg"]["id_canonico"], "RE N, de AAAA (≥ 6 dígitos não é ato normativo)")
            doc.add(f", de {rng.randint(2015, 2023)}, fixou a tese. ")
            enchimento(doc, rng, 1)
        i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            doc.add(f"O depósito na Ag. {rng.randint(1000, 9999)}, conta {rng.randint(10000, 99999)}-{rng.randint(0, 9)}, foi discutido no STJ/")
            doc.cit(f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real",
                    i["reg"]["id_canonico"], "STJ/<classe> ao lado de Ag. bancária")
            doc.add(". ")
            enchimento(doc, rng, 1)
        i = am.real("TST", lambda i: i["formato"] == "cnj", unico=True)
        if i:
            doc.add(f"A Instrução Normativa IN nº {rng.randint(10, 99)}/{rng.randint(2015, 2023)} do TST foi aplicada no ")
            doc.cit(f"{render_cadeia(i['cadeia'], 'TST', 'hifen', rng)}-{G.cnj(i['digitos'], 'TST')}", "jurisprudencia", "real",
                    i["reg"]["id_canonico"], "TST CNJ ao lado de IN")
            doc.add(". ")
            enchimento(doc, rng, 1)
        modelo = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] in ("MS", "RMS", "HC"), unico=False)
        if modelo:
            d = am.inventado(modelo)
            doc.add("Confira-se ainda o ")
            doc.cit(f"{render_cadeia(modelo['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(d)}/{modelo['uf'] or 'SP'}", "jurisprudencia",
                    "inventada", None, "inventada com sigla ambígua e UF")
            doc.add(f", e a Resolução CC nº {rng.randint(10, 99)}/{rng.randint(2010, 2023)}. ")
            enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


CONJUNTOS = {
    "r4_vagas_relator_antes": conjunto_vagas_relator_antes,
    "r4_ocr_duplo": conjunto_ocr_duplo,
    "r4_cabecalhos_novos": conjunto_cabecalhos_novos,
    "r4_negativas_vizinhas": conjunto_negativas_vizinhas,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", type=Path, default=RAIZ / "dados" / "adversarial")
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--seed", type=int, default=444)
    ap.add_argument("--so", nargs="*", default=None)
    args = ap.parse_args()
    for nome, fn in CONJUNTOS.items():
        if args.so and nome not in args.so:
            continue
        rng = random.Random(f"{args.seed}:{nome}")
        am = Amostra(args.indice, rng)
        docs = fn(am, rng)
        escrever(docs, args.saida / nome, rng, proteger=("vagas" not in nome))
        print(f"{nome}: {len(docs)} docs, {sum(len(d.gab) for d in docs)} citações")


if __name__ == "__main__":
    main()
