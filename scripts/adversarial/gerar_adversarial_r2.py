#!/usr/bin/env python3
"""Gerador de conjuntos ADVERSARIAIS — rodada 2 (revisor 2, generalização para o cego).

Reutiliza a infraestrutura de ``gerar_adversarial.py`` (amostrador da base, Doc, frases,
cabeçalhos, escrita do goldenset) e acrescenta formas que a rodada 1 não cobriu.
Gabarito POR CONSTRUÇÃO a partir de ``dados/indice.json``.

Uso: PYTHONPATH=src python scripts/adversarial/gerar_adversarial_r2.py [--seed N] [--so nome ...]

Conjuntos (>= 10 docs cada):
  r2_normativos_ruido  N2: OCR em número de súmula/artigo (início/meio/fim), caixa alta em DA/DO,
                       `inc.`, alínea sem aspas, `caput e §`, `§ 8.º`, `súmula` minúscula,
                       `Súmula N, IV, do T`, `(STJ)`, `- STJ`
  r2_vagas_ordem       N1/N2: ano antes do tribunal, `cujo relator foi`, `Rel.ª Min.ª`,
                       `(Rel. Min. X, j. A)`, `e. Min.`, `Exmo. Min.`, órgão fracionário, nome
                       seguido de palavra capitalizada, `tendo como relator`
  r2_processos_forma   N2: `REsp: N`, `nº.`, OCR no nome por extenso, 3 letras de OCR,
                       estilo Jusbrasil, `T5T-`, `RCl`, `-STJ` depois da UF, plural `REsps`
  r2_duplicatas        N1: números próprios de >= 2 registros (política docs/04 b / ADR 0006 §4)
  r2_listas            N1: enumerações `Precedentes:` com `;`, listas com `-` por linha, `c/c`,
                       `arts. X e Y`, fim de arquivo sem ponto, citação logo após o título
  r2_fora_da_base      N1: tribunais/classes fora da base (TJ/TRF CNJ, Apelação Cível, ADPF,
                       OJ, Tema), distratores (Lei sem artigo, Resolução, MP, FONAJE, IRDR)
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
    palavras_relator, render_cadeia, SUP, ORDINAIS,
)

OCR_MAP = {"1": "l", "0": "O", "5": "S", "9": "g", "6": "G"}
NOMES_DIP = {"CC": "Código Civil", "CDC": "Código de Defesa do Consumidor", "CE": "Código Eleitoral",
             "CF": "Constituição Federal", "CLT": "CLT", "CPC": "CPC", "CPM": "Código Penal Militar",
             "CPP": "Código de Processo Penal", "LC64": "Lei Complementar nº 64/1990"}
PREP = {"CC": "do", "CDC": "do", "CE": "do", "CF": "da", "CLT": "da", "CPC": "do", "CPM": "do", "CPP": "do", "LC64": "da"}


def ocr_pos(num: str, onde: str) -> str:
    """Troca um dígito por letra confundível: ``onde`` = 'inicio' | 'meio' | 'fim'."""
    pos = [k for k, c in enumerate(num) if c in OCR_MAP]
    if not pos:
        return num
    if onde == "inicio":
        p = pos[0]
    elif onde == "fim":
        p = pos[-1]
    else:
        p = pos[len(pos) // 2]
    return num[:p] + OCR_MAP[num[p]] + num[p + 1:]


# ---------------------------------------------------------------------------
def conjunto_normativos_ruido(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    sum_reais = [(t, v, n, idc) for t, v, n, idc in am.sumulas_reais()]
    disp = am.dispositivos_reais()
    sum_inv = [("STJ", False, 7), ("STF", False, 279), ("TST", False, 126), ("TSE", False, 31), ("STF", True, 11), ("STJ", False, 568)]
    disp_inv = [("CF", "37"), ("CPC", "1022"), ("CC", "927"), ("CDC", "6"), ("CLT", "467"), ("CPP", "313"), ("CE", "22"), ("CPM", "9")]
    for n in range(12):
        doc = Doc(f"adv_r2_normativos_ruido_n2_{n + 1:03d}", 2)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "eleit", "penal"])))
        enchimento(doc, rng, 1)
        # (1) OCR no número da súmula (real) — fim, meio
        t, v, num, idc = rng.choice(sum_reais)
        s = str(num)
        onde = rng.choice(["fim", "meio", "inicio"]) if len(s) >= 3 else rng.choice(["fim", "inicio"])
        s_ocr = ocr_pos(s, onde)
        if s_ocr == s:
            s_ocr = s[:-1] + OCR_MAP.get(s[-1], s[-1])
        trecho = f"Súmula Vinculante {s_ocr}" if v else f"Súmula {s_ocr} do {t}"
        G.cit_sumula(doc, rng, trecho, True, idc, f"OCR no nº da súmula ({onde}: {s}->{s_ocr}) [alta]")
        enchimento(doc, rng, 1)
        # (2) OCR no número da súmula (inventada): não pode virar real
        t2, v2, num2 = rng.choice(sum_inv)
        s2 = ocr_pos(str(num2), rng.choice(["fim", "meio"]))
        trecho = f"Súmula Vinculante {s2}" if v2 else f"Súmula {s2} do {t2}"
        G.cit_sumula(doc, rng, trecho, False, None, "OCR no nº da súmula inventada")
        enchimento(doc, rng, 1)
        # (3) OCR no número do artigo (real) — início/fim
        dip, art, idd = rng.choice([d for d in disp if len(d[1]) >= 2])
        onde = rng.choice(["inicio", "fim"])
        a_ocr = ocr_pos(art, onde)
        if a_ocr == art:
            a_ocr = art[:-1] + OCR_MAP.get(art[-1], art[-1])
        G.cit_dispositivo(doc, rng, f"art. {a_ocr} {PREP[dip]} {NOMES_DIP[dip]}", True, idd, f"OCR no nº do artigo ({onde}: {art}->{a_ocr}) [alta]")
        enchimento(doc, rng, 1)
        # (4) OCR no artigo inventado
        dip2, art2 = rng.choice(disp_inv)
        a2 = ocr_pos(art2, "fim")
        G.cit_dispositivo(doc, rng, f"art. {a2} {PREP[dip2]} {NOMES_DIP[dip2]}", False, None, "OCR no artigo inventado")
        enchimento(doc, rng, 1)
        # (5) caixa alta total: ART. N DA CF / SÚMULA N DO STJ
        dip, art, idd = rng.choice(disp)
        if n % 2 == 0:
            G.cit_dispositivo(doc, rng, f"ART. {art} {PREP[dip].upper()} {NOMES_DIP[dip].upper()}", True, idd, "caixa alta total no dispositivo [media]")
        else:
            t, v, num, idc = rng.choice([s for s in sum_reais if not s[1]])
            G.cit_sumula(doc, rng, f"SÚMULA {num} DO {t}", True, idc, "caixa alta total na súmula [media]")
        enchimento(doc, rng, 1)
        # (6) formas de complemento: inc., alínea sem aspas, caput e §, § 8.º, parágrafo
        forma = n % 6
        if forma == 0:
            dip = "CF"
            art, idd = G.artigo_k(am, dip, 0)
            G.cit_dispositivo(doc, rng, f"art. {art}º, inc. LV, {PREP[dip]} {NOMES_DIP[dip]}", True, idd, "inc. abreviado [alta]")
        elif forma == 1:
            art, idd = G.artigo_k(am, "LC64", 0)
            G.cit_dispositivo(doc, rng, f"art. {art}º, I, g, da Lei Complementar nº 64/1990", True, idd, "alínea sem aspas [media]")
        elif forma == 2:
            art, idd = G.artigo_k(am, "CLT", 0)
            G.cit_dispositivo(doc, rng, f"art. {art}, caput e § 8º, da CLT", True, idd, "caput e § [media]")
        elif forma == 3:
            art, idd = G.artigo_k(am, "CLT", 0)
            G.cit_dispositivo(doc, rng, f"art. {art}, § 8.º, da CLT", True, idd, "§ 8.º [media]")
        elif forma == 4:
            art, idd = G.artigo_k(am, "CF", 2)
            G.cit_dispositivo(doc, rng, f"art. {art}, incs. IX e X, da Constituição Federal", True, idd, "incs. [media]")
        else:
            art, idd = G.artigo_k(am, "CF", 0)
            G.cit_dispositivo(doc, rng, f"art. {art}º, LV, parte final, da Constituição Federal", True, idd, "parte final [baixa]")
        enchimento(doc, rng, 1)
        # (7) súmula minúscula com tribunal; súmula com item; (STJ); - STJ
        t, v, num, idc = rng.choice([s for s in sum_reais if not s[1]])
        forma = n % 4
        if forma == 0:
            G.cit_sumula(doc, rng, f"súmula {num} do {t}", True, idc, "súmula minúscula com tribunal [media]")
        elif forma == 1:
            G.cit_sumula(doc, rng, f"Súmula {num}, IV, do {t}", True, idc, "súmula com item (fronteira ambígua) [media]")
        elif forma == 2:
            G.cit_sumula(doc, rng, f"Súmula {num} ({t})", True, idc, "tribunal entre parênteses [media]")
        else:
            G.cit_sumula(doc, rng, f"Súmula {num} - {t}", True, idc, "tribunal com hífen [media]")
        enchimento(doc, rng, 1)
        # (8) processo N2 para manter classes
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STF", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
MOLDES_R2 = [
    ("julgado de {A} do {T}, Rel. Min. {N}", "ano_antes_tribunal [media]"),
    ("precedente de {A} do {T}, da relatoria de {N}", "ano_antes_tribunal_relatoria [media]"),
    ("julgado do {T} de {A} cujo relator foi o Ministro {N}", "cujo_relator [media]"),
    ("julgado do {T} de {A}, Rel.ª Min.ª {N}", "rel_feminino_abreviado [media]"),
    ("decisão do {T} (Rel. Min. {N}, j. {A})", "parenteses_j [baixa]"),
    ("julgado do {T} proferido em {A} pela relatoria do e. Min. {N}", "e_min [media]"),
    ("julgado do {T} proferido em {A} pela relatoria do Exmo. Min. {N}", "exmo_min [media]"),
    ("acórdão da Corte Especial do {T}, de {A}, Rel. Min. {N}", "orgao_fracionario [media]"),
    ("acórdão da Primeira Turma do {T}, de {A}, Rel. Min. {N}", "orgao_fracionario_turma [media]"),
    ("julgado do {T} de {A} tendo como relator o Ministro {N}", "tendo_como_relator [media]"),
    ("decisão do {T} ({A}), Rel. Min. {N}", "ano_parenteses [media]"),
    ("entendimento firmado pelo {T} em {A}, sob a relatoria do Min. {N}", "firmado_pelo [media]"),
    ("acórdão proferido pelo {T} em {A}, da relatoria do Ministro {N}", "proferido_pelo [media]"),
    ("decisão do {T} de {A}, relatada pelo Ministro {N}", "F (dev-like)"),
    ("julgado do {T} proferido em {A} pela relatoria de {N}", "A (dev)"),
]


def conjunto_vagas_ordem(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        nivel = 1 if n < 6 else 2
        doc = Doc(f"adv_r2_vagas_ordem_n{nivel}_{n + 1:03d}", nivel)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "eleit", "mil", "trab"])))
        enchimento(doc, rng, 1)
        for molde, tag in rng.sample(MOLDES_R2, 6):
            cit_vaga(am, doc, rng, molde, nota=f"molde {tag}", caixa_alta=(nivel == 2 and rng.random() < 0.3))
            enchimento(doc, rng, rng.choice([1, 2]))
        # nome seguido de palavra capitalizada (quebra de linha e frase seguinte com maiúscula)
        v = am.vaga(n_palavras=(2, 3))
        if v:
            nome = nome_titulo(v["palavras"])
            trecho = f"julgado do {v['tribunal']} proferido em {v['ano']} pela relatoria de {nome}"
            doc.add("Confira-se o ")
            doc.cit(trecho, "jurisprudencia", "incompleta", None, f"nome seguido de \\nMaiúscula mult={v['mult']} [media]")
            doc.add("\nQuanto ao mais, a orientação é pacífica. ")
            enchimento(doc, rng, 1)
        # real + inventada
        cit_processo_real(am, doc, rng, rng.choice(["STJ", "STF", "TSE"]), "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        # armadilhas: relator sem ano; ano sem relator; ministro em prosa
        doc.add(rng.choice([
            "Como destacou o Ministro relator, a controvérsia é de direito. ",
            "Em 2019 o STJ consolidou a tese em diversos julgados. ",
            "O Ministro Presidente, em 2021, determinou a afetação do tema. ",
            "A Primeira Turma do STF, em 2022, reafirmou a orientação. ",
        ]))
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def ocr_extenso(nome: str, rng: random.Random) -> str:
    """Uma troca de OCR medida (e→c, a→ã, i→l, m→rn) numa palavra do nome por extenso, nunca na inicial."""
    palavras = nome.split()
    for _ in range(20):
        k = rng.randrange(len(palavras))
        p = palavras[k]
        for a, b in rng.sample([("e", "c"), ("a", "ã"), ("i", "l"), ("m", "rn")], 4):
            idx = p.find(a, 1)
            if idx > 0:
                palavras[k] = p[:idx] + b + p[idx + 1:]
                return " ".join(palavras)
    return nome


def conjunto_processos_forma(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        doc = Doc(f"adv_r2_processos_forma_n2_{n + 1:03d}", 2)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "trab"])))
        enchimento(doc, rng, 1)
        # (1) dois-pontos depois da sigla
        i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)}: {com_pontos(i['digitos'])}/{i['uf']}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "dois-pontos após a sigla [media]")
            enchimento(doc, rng, 1)
        # (2) nº. (ponto depois do º)
        i = am.real("STF", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            trecho = f"{render_cadeia(i['cadeia'], 'STF', 'sigla', rng)} nº. {com_pontos(i['digitos'])}/{i['uf'] or 'DF'}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "nº. com ponto [baixa]")
            enchimento(doc, rng, 1)
        # (3) OCR no nome por extenso da classe (real e inventada)
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] in ("RESP", "ARESP", "RHC", "RMS"), unico=True)
        if i:
            cad = ocr_extenso(render_cadeia(i["cadeia"], "STJ", "extenso", rng), rng)
            trecho = f"{cad} nº {com_pontos(i['digitos'])}/{i['uf']}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, f"OCR no nome por extenso ({cad}) [alta]")
            enchimento(doc, rng, 1)
        modelo = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] in ("RESP", "ARESP"), unico=False)
        d = am.inventado(modelo)
        cad = ocr_extenso(render_cadeia(modelo["cadeia"], "STJ", "extenso", rng), rng)
        frase_com_citacao(doc, f"{cad} nº {com_pontos(d)}/{modelo['uf'] or 'SP'}", "jurisprudencia", "inventada", None, rng, "OCR no nome por extenso (inventada)")
        enchimento(doc, rng, 1)
        # (4) três letras de OCR no número (real) — o desafio não limita a 1
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["digitos"]) == 7, unico=True)
        if i:
            num = G.ocr_no_numero(com_pontos(i["digitos"]), rng, 3)
            trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {num}/{i['uf']}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "3 letras OCR [media]")
            enchimento(doc, rng, 1)
        # (5) -STJ / (STJ) depois da UF: span até a UF
        i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}"
            doc.add("Confira-se o ")
            doc.cit(trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], "tribunal depois da UF [alta]")
            doc.add(rng.choice(["-STJ", " (STJ)", " - STJ", "/STJ"]) + ", no mesmo sentido. ")
            enchimento(doc, rng, 1)
        # (6) T5T- (OCR no prefixo) — fronteira
        i = am.real("TST", lambda i: i["formato"] == "cnj", unico=True)
        if i:
            trecho = f"T5T-{render_cadeia(i['cadeia'], 'TST', 'sigla', rng)}-{cnj(i['digitos'], 'TST')}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "OCR no prefixo TST- [media]")
            enchimento(doc, rng, 1)
        # (7) RCl (caixa mista com OCR l) / REsp com S→5 e p→p
        i = am.real("STF", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] == "RCL", unico=True)
        if i:
            trecho = f"RCl {com_pontos(i['digitos'])}/{i['uf'] or 'SP'}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "RCl caixa mista [baixa]", artigo="a")
            enchimento(doc, rng, 1)
        # (8) estilo Jusbrasil (STJ - REsp: N UF, Relator: ...) — real
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["RESP"], unico=True)
        if i:
            doc.add("Nesse sentido: STJ - ")
            doc.cit(f"REsp: {i['digitos']} {i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], "estilo Jusbrasil [media]")
            doc.add(f", Relator: Ministro {nome_titulo(palavras_relator(i['reg']['relator']) or ['Fulano', 'Tal'])}, Data de Julgamento: 12/03/{i['reg']['ano']}, T3 - TERCEIRA TURMA. ")
            enchimento(doc, rng, 1)
        # (9) plural REsps X/UF e Y/UF (conhecido; cada um anotado)
        if n % 3 == 0:
            a = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["RESP"], unico=True)
            b = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["RESP"], unico=True)
            if a and b:
                doc.add("Nesse sentido, os ")
                doc.cit(f"REsps {com_pontos(a['digitos'])}/{a['uf']}", "jurisprudencia", "real", a["reg"]["id_canonico"], "plural REsps (1) [baixa]")
                doc.add(" e ")
                doc.cit(f"{com_pontos(b['digitos'])}/{b['uf']}", "jurisprudencia", "real", b["reg"]["id_canonico"], "plural REsps (2) [baixa]")
                doc.add(", ambos da Terceira Turma. ")
                enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def conjunto_duplicatas(am: Amostra, rng: random.Random) -> list[Doc]:
    regs = am.regs
    grupos = [(k, v) for k, v in am.pd.items() if len(v) > 1 and all(regs[d]["natureza"] == "acordao" for d in v)
              and all(any(i["digitos"] == k and i["formato"] in ("sequencial", "cnj") for i in regs[d]["identificadores"]) for d in v)]
    same = [(k, v) for k, v in grupos if len({regs[d]["classe_propria"] for d in v}) == 1]
    diff = [(k, v) for k, v in grupos if len({regs[d]["classe_propria"] for d in v}) > 1]
    rng.shuffle(same)
    rng.shuffle(diff)
    docs = []
    for n in range(12):
        doc = Doc(f"adv_r2_duplicatas_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "eleit", "mil"])))
        enchimento(doc, rng, 1)
        # (1) duplicata idêntica: gold aceita qualquer dos ids (a:b)
        for _ in range(2):
            if not same:
                break
            k, v = same.pop()
            r = regs[v[0]]
            it = next(i for i in r["identificadores"] if i["digitos"] == k)
            cad = (r["classe_propria"] or "").split()
            if not cad or not all(t in SUP or t in ORDINAIS for t in cad):
                continue
            am.usados.add(k)
            trecho = montar_processo(cad, k, it["formato"], r["tribunal"], it.get("uf"), "sigla", rng)
            ids = ":".join(str(regs[d]["id_canonico"]) for d in v)
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", ids, rng, f"duplicata idêntica ({len(v)} regs) — gold aceita qualquer")
            enchimento(doc, rng, 1)
        # (2) grupo com cadeia distinta: cita com a cadeia completa de um deles (id único esperado)
        if diff:
            k, v = diff.pop()
            d_alvo = rng.choice(v)
            r = regs[d_alvo]
            it = next(i for i in r["identificadores"] if i["digitos"] == k)
            cad = (r["classe_propria"] or "").split()
            if cad and all(t in SUP or t in ORDINAIS for t in cad):
                am.usados.add(k)
                trecho = montar_processo(cad, k, it["formato"], r["tribunal"], it.get("uf"), "sigla", rng)
                frase_com_citacao(doc, trecho, "jurisprudencia", "real", r["id_canonico"], rng, f"cadeia distinta ({len(v)} regs): cadeia exata")
                enchimento(doc, rng, 1)
                # (3) o mesmo número só com a classe principal: gold aceita qualquer registro cuja classe principal bate
                principais = [d for d in v if (regs[d]["classe_propria"] or "").split()[-1:] == cad[-1:]]
                if principais and n % 2 == 0:
                    trecho2 = montar_processo(cad[-1:], k, it["formato"], r["tribunal"], it.get("uf"), "sigla", rng)
                    ids = ":".join(str(regs[d]["id_canonico"]) for d in principais)
                    doc.add("Também o ")
                    doc.cit(trecho2, "jurisprudencia", "real", ids, f"só classe principal ({len(principais)} compatíveis)")
                    doc.add(" caminha no mesmo sentido. ")
                    enchimento(doc, rng, 1)
        # (4) número real de outro tribunal citado com classe incompatível (docs/04 h.2) → inventada
        i = am.real("STF", lambda i: i["cadeia"][-1] == "RCL" and i["formato"] == "sequencial", unico=True)
        if i:
            trecho = f"AREsp {com_pontos(i['digitos'])}/{i['uf'] or 'SP'}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "inventada", None, rng, "número de Rcl do STF citado como AREsp (h.2)")
            enchimento(doc, rng, 1)
        # (5) número de REspe do TSE citado como Recurso Especial (mesma classe, outra nomenclatura) → real
        i = am.real("TSE", lambda i: i["cadeia"] == ["RESPE"] and i["formato"] == "cnj", unico=True)
        if i:
            trecho = f"Recurso Especial nº {cnj(i['digitos'], 'TSE')}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "REspe citado como Recurso Especial (RESP≈RESPE)")
            enchimento(doc, rng, 1)
        # reais/inventadas comuns
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def conjunto_listas(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    disp = {(d, a): idc for d, a, idc in am.dispositivos_reais()}
    sums = [s for s in am.sumulas_reais() if not s[1]]
    for n in range(12):
        doc = Doc(f"adv_r2_listas_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "penal"])))
        # citação logo após o cabeçalho (primeira frase do corpo)
        i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            doc.add("A controvérsia, tal como decidida no ")
            doc.cit(f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], "1ª frase do corpo")
            doc.add(", diz respeito ao prazo prescricional. ")
        enchimento(doc, rng, 1)
        # Precedentes com ponto-e-vírgula e relator entre
        doc.add("Precedentes: ")
        itens = [am.real(rng.choice(["STJ", "STF"]), lambda i: i["formato"] == "sequencial", unico=True) for _ in range(3)]
        itens = [x for x in itens if x]
        for k, it in enumerate(itens):
            doc.cit(montar_processo(it["cadeia"], it["digitos"], "sequencial", it["tribunal"], it["uf"], "sigla", rng), "jurisprudencia", "real", it["reg"]["id_canonico"], "lista com ; e relator")
            doc.add(f", Rel. Min. Fulano de Tal, DJe 1º/2/{2015 + k}" + ("; " if k < len(itens) - 1 else ". "))
        enchimento(doc, rng, 1)
        # lista com hífen por linha
        doc.add("Nesse sentido, os seguintes julgados:\n")
        for k in range(3):
            it = am.real(rng.choice(["STJ", "TST", "STM", "TSE"]), lambda i: True, unico=True)
            if not it:
                continue
            doc.add("- ")
            doc.cit(montar_processo(it["cadeia"], it["digitos"], it["formato"], it["tribunal"], it["uf"], "sigla", rng), "jurisprudencia", "real", it["reg"]["id_canonico"], "lista com hífen por linha")
            doc.add(";\n" if k < 2 else ".\n")
        enchimento(doc, rng, 1)
        # c/c: dois dispositivos na mesma frase
        (d1, a1), (d2, a2) = rng.sample(list(disp), 2)
        doc.add("Aplicam-se o ")
        doc.cit(f"art. {a1} {PREP[d1]} {NOMES_DIP[d1]}", "lei", "real", disp[(d1, a1)], "c/c (1)")
        doc.add(" c/c o ")
        doc.cit(f"art. {a2} {PREP[d2]} {NOMES_DIP[d2]}", "lei", "real", disp[(d2, a2)], "c/c (2)")
        doc.add(". ")
        enchimento(doc, rng, 1)
        # súmula + inventada na mesma frase, separadas por 'e'
        t, v, num, idc = rng.choice(sums)
        doc.add("Incidem a ")
        doc.cit(f"Súmula {num} do {t}", "jurisprudencia", "real", idc, "súmula + inventada na frase")
        doc.add(" e a ")
        modelo = am.real("STF", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] == "RCL", unico=False)
        dinv = am.inventado(modelo)
        doc.cit(f"Rcl {com_pontos(dinv)}/{modelo['uf'] or 'SP'}", "jurisprudencia", "inventada", None, "súmula + inventada na frase")
        doc.add(". ")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        # fim de arquivo: vaga sem ponto (n par) ou processo sem ponto (n ímpar)
        if n % 2 == 0:
            v_ = am.vaga(n_palavras=(2, 4))
            if v_:
                doc.add("Por fim, o ")
                doc.cit(f"precedente do {v_['tribunal']} de {v_['ano']}, da relatoria de {nome_titulo(v_['palavras'])}", "jurisprudencia", "incompleta", None, f"vaga no fim do arquivo sem ponto mult={v_['mult']}")
        else:
            it = am.real("TST", lambda i: i["formato"] == "cnj", unico=True)
            if it:
                doc.add("Por fim, o ")
                doc.cit(montar_processo(it["cadeia"], it["digitos"], "cnj", "TST", None, "sigla", rng, prefixo_tst="TST-"), "jurisprudencia", "real", it["reg"]["id_canonico"], "TST no fim do arquivo sem ponto")
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
def conjunto_fora_da_base(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    fora = [
        (lambda: f"Apelação Cível nº {rng.randint(1000000, 1999999)}-{rng.randint(10, 99)}.{rng.randint(2018, 2023)}.8.26.{rng.randint(1, 999):04d}", "TJSP apelação cível [media]"),
        (lambda: f"Agravo de Instrumento nº {rng.randint(2000000, 2999999)}-{rng.randint(10, 99)}.{rng.randint(2018, 2023)}.8.26.0000", "TJSP AI [media]"),
        (lambda: f"Apelação nº {rng.randint(1, 9999999):07d}-{rng.randint(10, 99)}.{rng.randint(2015, 2023)}.4.03.6100", "TRF3 apelação [media]"),
        (lambda: f"Recurso Ordinário nº {rng.randint(1000, 9999)}-{rng.randint(10, 99)}.{rng.randint(2015, 2023)}.5.02.{rng.randint(1, 99):04d}", "TRT2 RO (J=5, TRT) [media]"),
        (lambda: f"ADPF {rng.randint(100, 999)}", "ADPF [alta]"),
        (lambda: f"ADC {rng.randint(10, 99)}", "ADC [media]"),
        (lambda: f"Inq {com_pontos(str(rng.randint(3000, 4999)))}/DF", "Inq [media]"),
        (lambda: f"MS {com_pontos(str(rng.randint(30000, 39999)))}/DF", "MS STF fora [alta]"),
        (lambda: f"HC {com_pontos(str(rng.randint(600000, 799999)))}/SP", "HC STJ fora [alta]"),
        (lambda: f"RE {com_pontos(str(rng.randint(1000000, 1400000)))}/RS", "RE fora [alta]"),
        (lambda: f"AgRg no HC {com_pontos(str(rng.randint(600000, 799999)))}/SP", "AgRg no HC fora [alta]"),
        (lambda: f"EREsp {com_pontos(str(rng.randint(1000000, 1999999)))}/SP", "EREsp fora [alta]"),
        (lambda: f"CC {com_pontos(str(rng.randint(150000, 199999)))}/SP", "CC fora [alta]"),
        (lambda: f"RMS {com_pontos(str(rng.randint(50000, 69999)))}/MG", "RMS fora [alta]"),
        (lambda: f"Súmula {rng.randint(1, 50)} do STJ", "súmula real no mundo fora da base [alta]"),
        (lambda: f"Súmula {rng.randint(300, 400)} do TST", "súmula TST fora [alta]"),
        (lambda: f"Súmula Vinculante {rng.randint(20, 50)}", "SV fora [alta]"),
        (lambda: f"Tema {com_pontos(str(rng.randint(500, 1300)))} da repercussão geral", "tema [alta]"),
        (lambda: f"art. {rng.randint(900, 1000)} do Código Civil", "art CC fora [alta]"),
        (lambda: f"art. {rng.randint(1, 60)} da Lei nº 9.099/1995", "lei fora [alta]"),
        (lambda: f"art. {rng.randint(1, 30)} da Lei nº 8.429/1992", "lei fora [alta]"),
        (lambda: f"art. {rng.randint(100, 300)} do Código Penal", "CP fora [alta]"),
        (lambda: f"art. {rng.randint(1, 100)} do Código Tributário Nacional", "CTN fora [media]"),
        (lambda: f"art. {rng.randint(100, 400)} do Código de Processo Penal Militar", "CPPM fora [media]"),
    ]
    distratores = [
        "A pretensão funda-se na Lei nº 8.078/1990 e na Lei nº 13.105/2015, que regem a matéria. ",
        "A Resolução CNJ nº 123/2010 e a Portaria nº 1.234/2019 disciplinam o ponto. ",
        "A Medida Provisória nº 1.045/2021 e o Decreto nº 10.282/2020 tratam do tema. ",
        "O Enunciado 12 do FONAJE orienta a prática. ",
        "O IRDR nº 12 do TJSP fixou a tese. ",
        "A Orientação Jurisprudencial nº 394 da SBDI-1 do TST se aplica. ",
        "O Provimento nº 12/2019 da Corregedoria regula a matéria. ",
        "Aplica-se a súmula do STJ sobre o tema, cujo enunciado dispensa comentários. ",
        f"Nos termos do art. {G.artigo_k(am, 'CPC')[0]}, a prova incumbe a quem alega, e o art. 1.022 trata dos embargos. ",
        "Como decidiu a 3ª Turma em 12/03/2021, no valor de R$ 12.345,67, com juros de 1% ao mês. ",
    ]
    for n in range(12):
        doc = Doc(f"adv_r2_fora_da_base_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "trab", "eleit"])))
        enchimento(doc, rng, 1)
        for fn, nota in rng.sample(fora, 5):
            trecho = fn()
            tipo = "lei" if trecho.startswith("art.") else "jurisprudencia"
            frase_com_citacao(doc, trecho, tipo, "inventada", None, rng, nota)
            enchimento(doc, rng, 1)
        for d in rng.sample(distratores, 3):
            doc.add(d)
            enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, rng.choice(["STJ", "STF", "TST", "TSE", "STM"]), "misto")
        enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_chave_parcial(am: Amostra, rng: random.Random) -> list[Doc]:
    """N2: grupo final do número inteiramente em letras de OCR (3 letras no mesmo grupo).

    Inventadas construídas para que o PREFIXO de 4–5 dígitos seja número próprio real de outra
    classe (mecanismo de inventada→real por chave parcial, ADR 0006 'chave parcial nunca'); reais
    com o último grupo todo em OCR (devem continuar real via reparo).
    """
    regs = am.regs
    curtos = [k for k in am.pd if k.isdigit() and 4 <= len(k) <= 5 and len(am.pd[k]) == 1
              and regs[am.pd[k][0]]["natureza"] == "acordao" and k[0] != "0"]
    rng.shuffle(curtos)
    docs = []
    for n in range(10):
        doc = Doc(f"adv_r2_chave_parcial_n2_{n + 1:03d}", 2)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal"])))
        enchimento(doc, rng, 1)
        # (1) inventada: prefixo real + grupo final todo OCR (3 letras)
        for _ in range(2):
            if not curtos:
                break
            k = curtos.pop()
            r = regs[am.pd[k][0]]
            resto = "".join(rng.choice("lOSgG") for _ in range(3))
            if len(k) == 4:
                num = f"{k[0]}.{k[1:]}.{resto}"
            else:
                num = f"{k[:2]}.{k[2:]}.{resto}"
            cls = rng.choice(["Rcl", "REsp", "AREsp", "RE", "HC"])
            uf = rng.choice(["SP", "RJ", "MG", "DF"])
            am.usados.add(k)
            frase_com_citacao(doc, f"{cls} {num}/{uf}", "jurisprudencia", "inventada", None, rng,
                              f"grupo final todo OCR; prefixo {k} é {r['tribunal']} {r['classe_propria']} [crítica se virar real]",
                              artigo="a" if cls == "Rcl" else "o")
            enchimento(doc, rng, 1)
        # (2) real com o último grupo todo em OCR
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["digitos"]) == 7, unico=True)
        if i:
            d = i["digitos"]
            mapa = {"1": "l", "0": "O", "5": "S", "9": "g", "6": "G"}
            if all(c in mapa for c in d[4:]):
                num = f"{d[0]}.{d[1:4]}.{''.join(mapa[c] for c in d[4:])}"
                trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {num}/{i['uf']}"
                frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "real com grupo final todo OCR [media]")
                enchimento(doc, rng, 1)
        # (3) real com grupo do meio todo em OCR
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["digitos"]) == 7
                    and all(c in "10596" for c in i["digitos"][1:4]), unico=True)
        if i:
            d = i["digitos"]
            mapa = {"1": "l", "0": "O", "5": "S", "9": "g", "6": "G"}
            num = f"{d[0]}.{''.join(mapa[c] for c in d[1:4])}.{d[4:]}"
            trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {num}/{i['uf']}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "real com grupo do meio todo OCR [media]")
            enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STF", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


CONJUNTOS = {
    "r2_chave_parcial": conjunto_chave_parcial,
    "r2_normativos_ruido": conjunto_normativos_ruido,
    "r2_vagas_ordem": conjunto_vagas_ordem,
    "r2_processos_forma": conjunto_processos_forma,
    "r2_duplicatas": conjunto_duplicatas,
    "r2_listas": conjunto_listas,
    "r2_fora_da_base": conjunto_fora_da_base,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", type=Path, default=RAIZ / "dados" / "adversarial")
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--seed", type=int, default=7777)
    ap.add_argument("--so", nargs="*", default=None)
    args = ap.parse_args()
    for nome, fn in CONJUNTOS.items():
        if args.so and nome not in args.so:
            continue
        rng = random.Random(f"{args.seed}:{nome}")
        am = Amostra(args.indice, rng)
        docs = fn(am, rng)
        escrever(docs, args.saida / nome, rng, proteger=("ruido" not in nome and "forma" not in nome and "parcial" not in nome))
        print(f"{nome}: {len(docs)} docs, {sum(len(d.gab) for d in docs)} citações")


if __name__ == "__main__":
    main()
