#!/usr/bin/env python3
"""Gerador de conjuntos ADVERSARIAIS — rodada 6: os que FORÇAM o extrator LLM (ADR 0003, padrão ouro).

Reutiliza a infraestrutura de ``gerar_adversarial.py`` (amostrador da base, Doc, frases, cabeçalhos,
escrita do goldenset). Gabarito POR CONSTRUÇÃO a partir de ``dados/indice.json``; nenhum número da
base é escrito neste arquivo (consultas posicionais).

Uso: PYTHONPATH=src python scripts/adversarial/gerar_adversarial_r6.py [--seed N] [--so nome ...]

Conjuntos (12 docs cada):
  r6_extrator_formas       N1/N2: citações em formas que os detectores por regex NÃO cobrem (medido em
                           20/09: classe colada ao número ``REsp1.234.567/SP``; ``recurso especial de
                           número N``; palavra quebrada ``Re curso Especial``/``Recla-⏎mação``; OCR na
                           palavra ``Sún1ula N do T``; vaga com órgão ``julgado pela 3ª Turma do T em
                           AAAA, relatoria da Ministra X``), reais e inventadas por construção, ao lado
                           de citações normais (controle: nada pode ser duplicado) e de distratores com
                           pistas (fls., R$, ``Processo nº`` do próprio caso).
                           Com ``--arbitro nenhum`` o recall cai (FN por construção); com o extrator
                           ligado o score tem de subir SEM nenhum ``inventada→real`` (τ = 0).
  r6_extrator_distratores  N1: janelas cheias de pistas sem citação nenhuma — ``Processo nº <CNJ>``,
                           ``Ministro X afirmou``, ``art. 5º do contrato``, ``Lei nº 8.078/90`` sem artigo,
                           ``Tema 3: Da prescrição``, ``acórdão nº N`` sem classe, ``REsp.`` sem número,
                           datas/valores/percentuais, ``nº`` de ofício/protocolo — mais poucas citações
                           normais (controle). Mede a PRECISÃO do extrator: qualquer acréscimo é FP.
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
    Amostra, Doc, cabecalho_padrao, cit_processo_real, com_pontos, enchimento, escrever, frase_com_citacao,
    nome_titulo,
)

SIGLA = {"RESP": "REsp", "ARESP": "AREsp", "RE": "RE", "ARE": "ARE", "RCL": "Rcl", "HC": "HC", "RMS": "RMS", "RHC": "RHC"}
EXTENSO = {"RESP": "recurso especial", "ARESP": "agravo em recurso especial", "RE": "recurso extraordinário",
           "RCL": "reclamação", "HC": "habeas corpus", "RMS": "recurso em mandado de segurança"}
QUEBRAVEL = {"RESP": ("Re curso Especial", "Recurso Espe-\ncial"), "RCL": ("Recla-\nmação", "Recla mação"),
             "RE": ("Recurso Extraordi-\nnário", "Re curso Extraordinário"), "HC": ("Habeas Cor-\npus", "Ha beas Corpus")}
UF_EXT = {"SP": "São Paulo", "RJ": "Rio de Janeiro", "MG": "Minas Gerais", "PR": "Paraná", "RS": "Rio Grande do Sul",
          "BA": "Bahia", "DF": "Distrito Federal", "SC": "Santa Catarina", "PE": "Pernambuco"}
SUMULA_OCR = ["Sún1ula", "Sumu1a", "Súmu1a", "Sún1u1a"]


def _um_token(i: dict) -> bool:
    return len(i["cadeia"]) == 1 and i["cadeia"][0] in SIGLA and i["formato"] == "sequencial"


def _real(am: Amostra, tribunal: str, filtro=None) -> dict | None:
    return am.real(tribunal, lambda i: _um_token(i) and (filtro is None or filtro(i)), unico=True)


def _inventado(am: Amostra, tribunal: str) -> dict | None:
    modelo = am.real(tribunal, _um_token, unico=False)
    if modelo is None:
        return None
    d = am.inventado(modelo)
    return {"cadeia": modelo["cadeia"], "digitos": d, "uf": modelo["uf"] or "SP", "tribunal": tribunal, "reg": None}


def _emitir(doc: Doc, rng: random.Random, trecho: str, item: dict, nota: str) -> None:
    classe = "real" if item.get("reg") else "inventada"
    idc = item["reg"]["id_canonico"] if item.get("reg") else None
    frase_com_citacao(doc, trecho, "jurisprudencia", classe, idc, rng, nota)


def _colado(item: dict) -> str:
    uf = item.get("uf")
    return f"{SIGLA[item['cadeia'][0]]}{com_pontos(item['digitos'])}" + (f"/{uf}" if uf and item["tribunal"] != "STF" else "")


def _de_numero(item: dict, rng: random.Random) -> str:
    return f"{EXTENSO[item['cadeia'][0]]} de número {com_pontos(item['digitos'])}"


def _quebrado(item: dict, rng: random.Random, nivel: int) -> str:
    formas = QUEBRAVEL.get(item["cadeia"][0])
    if not formas:
        return _colado(item)
    forma = formas[0] if nivel == 2 or "\n" not in formas[1] else formas[1]
    if nivel == 1 and "\n" in forma:
        forma = formas[1] if "\n" not in formas[1] else forma.replace("-\n", " ")
    uf = item.get("uf")
    return f"{forma} {com_pontos(item['digitos'])}" + (f"/{uf}" if uf and item["tribunal"] != "STF" else "")


def _vaga_orgao(am: Amostra, doc: Doc, rng: random.Random) -> None:
    v = am.vaga(rng.choice(["STJ", "STF", "TST"]), n_palavras=(2, 4))
    if v is None:
        return
    nome = nome_titulo(v["palavras"])
    orgao = rng.choice(["1ª Turma", "2ª Turma", "3ª Turma", "4ª Turma", "5ª Turma", "6ª Turma", "1ª Seção", "2ª Seção"])
    genero = rng.choice([("a", "a"), ("o", "o")])
    trecho = f"julgado pela {orgao} do {v['tribunal']} em {v['ano']}, relatoria d{genero[0]} Ministr{genero[1]} {nome}"
    frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"vaga com órgão [extrator] mult={v['mult']}")


def _distratores_com_pistas(doc: Doc, rng: random.Random, cnj_cab: str) -> None:
    frases = [
        f"Conforme consta às fls. {rng.randint(10, 90)}/{rng.randint(91, 300)} dos autos, o valor da causa foi fixado em R$ {rng.randint(10, 900)}.{rng.randint(100, 999)},00 em {rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(2015, 2024)}. ",
        f"A jurisprudência pacífica desta Corte não socorre o recorrente (Processo nº {cnj_cab}). ",
        f"O Ministro relator afirmou, em {rng.randint(2015, 2024)}, que a orientação dos tribunais superiores é firme no ponto. ",
        f"Nos termos da cláusula {rng.randint(3, 30)}ª e do art. {rng.randint(2, 40)} do contrato firmado entre as partes, o percentual de {rng.randint(5, 40)}% incide sobre o saldo. ",
        f"O ofício nº {rng.randint(100, 999)}/{rng.randint(2018, 2024)} e o protocolo nº {rng.randint(100000, 999999)} instruem o pedido. ",
        "A Lei nº 8.078/90 e o Código de Processo Civil regem a matéria, como registrou o acórdão recorrido. ",
        f"Tema {rng.randint(2, 9)}: Da prescrição e da decadência — ver o item {rng.randint(2, 9)}.{rng.randint(1, 9)} deste parecer. ",
    ]
    rng.shuffle(frases)
    for f in frases[:3]:
        doc.add(f)


def conjunto_extrator_formas(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        nivel = 2 if n % 2 else 1
        doc = Doc(f"adv_r6_extrator_formas_n{nivel}_{n + 1:03d}", nivel)
        cnj_cab = f"{rng.randint(1000000, 9999999):07d}-{rng.randint(10, 99)}.{rng.randint(2015, 2024)}.8.26.{rng.randint(1, 999):04d}"
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "penal"]), cnj_cab))
        enchimento(doc, rng, 1)
        # (1) classe colada ao número — real e inventada
        for trib in ("STJ", "STF"):
            i = _real(am, trib)
            if i:
                _emitir(doc, rng, _colado(i), i, "classe colada [extrator]")
                enchimento(doc, rng, 1)
        j = _inventado(am, "STJ")
        if j:
            _emitir(doc, rng, _colado(j), j, "classe colada inventada [extrator]")
            enchimento(doc, rng, 1)
        # (2) "recurso especial de número N" (+ UF por extenso fora do span)
        i = _real(am, "STJ", lambda x: x["cadeia"][0] in EXTENSO)
        if i:
            trecho = _de_numero(i, rng)
            uf = i.get("uf")
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "de número [extrator]",
                              sem_ponto=True)
            doc.add((f", oriundo de {UF_EXT.get(uf, 'São Paulo')}" if uf else "") + ". ")
            enchimento(doc, rng, 1)
        j = _inventado(am, "STJ")
        if j and j["cadeia"][0] in EXTENSO:
            _emitir(doc, rng, _de_numero(j, rng), j, "de número inventada [extrator]")
            enchimento(doc, rng, 1)
        # (3) palavra quebrada (N2: hífen + quebra de linha; N1: espaço no meio)
        i = _real(am, rng.choice(["STJ", "STF"]), lambda x: x["cadeia"][0] in QUEBRAVEL)
        if i:
            _emitir(doc, rng, _quebrado(i, rng, nivel), i, "palavra quebrada [extrator]")
            enchimento(doc, rng, 1)
        # (4) Súmula com OCR na palavra — real (tabela) e inventada (número fora da tabela)
        disponiveis = sorted({t for t, v, _, _ in am.sumulas_reais() if not v})
        trib = disponiveis[n % len(disponiveis)]
        s_num, s_id = G.sumula_k(am, trib, k=n)
        G.cit_sumula(doc, rng, f"{rng.choice(SUMULA_OCR)} {s_num} do {trib}", True, s_id, "Súmula com OCR na palavra [extrator]")
        enchimento(doc, rng, 1)
        reais = {(t, nn) for t, v, nn, _ in am.sumulas_reais()}
        s_inv = next(x for x in range(900 + n * 7, 1300) if (trib, x) not in reais)
        G.cit_sumula(doc, rng, f"{rng.choice(SUMULA_OCR)} {s_inv} do {trib}", False, None, "Súmula OCR inventada [extrator]")
        enchimento(doc, rng, 1)
        # (5) vaga com órgão julgador
        _vaga_orgao(am, doc, rng)
        enchimento(doc, rng, 1)
        # controles: citações normais (o extrator não pode duplicá-las) e distratores com pistas
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        G.cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        _distratores_com_pistas(doc, rng, cnj_cab)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_extrator_distratores(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        doc = Doc(f"adv_r6_extrator_distratores_n1_{n + 1:03d}", 1)
        cnj_cab = f"{rng.randint(1000000, 9999999):07d}-{rng.randint(10, 99)}.{rng.randint(2015, 2024)}.8.26.{rng.randint(1, 999):04d}"
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "penal"]), cnj_cab))
        enchimento(doc, rng, 1)
        nomes = [nome_titulo(G.palavras_relator(r["relator"])) for r in list(am.regs.values())[n * 5:(n * 5) + 8]
                 if r.get("relator")]
        nome = nomes[0] if nomes else "Fulano de Tal"
        pistas = [
            f"Como assentou o Ministro {nome} em sessão de {rng.randint(2015, 2024)}, a matéria é de ordem pública. ",
            f"O acórdão nº {rng.randint(100000, 999999)} do tribunal de origem foi mantido pelo STJ. ",
            "O REsp. e o AREsp. são os instrumentos adequados, segundo a doutrina, para a impugnação. ",
            f"Nos termos do art. {rng.randint(2, 40)}º do contrato social e da cláusula {rng.randint(2, 20)}ª, a quota é de {rng.randint(5, 60)}%. ",
            "A Lei nº 8.078/90, o Código Civil e a Constituição Federal regem a relação, como registra a sentença. ",
            f"Tema {rng.randint(2, 9)}: Da prescrição — ver o item {rng.randint(2, 9)}.{rng.randint(1, 9)} deste parecer e o Tema {rng.randint(2, 9)} do sumário. ",
            f"Conforme fls. {rng.randint(10, 90)}/{rng.randint(91, 300)}, o débito de R$ {rng.randint(10, 900)}.{rng.randint(100, 999)},{rng.randint(10, 99)} venceu em {rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(2015, 2024)}. ",
            f"O ofício nº {rng.randint(100, 999)}/{rng.randint(2018, 2024)}, o protocolo nº {rng.randint(100000, 999999)} e a matrícula nº {rng.randint(10000, 99999)} instruem o pedido. ",
            f"A jurisprudência pacífica desta Corte não socorre o recorrente (Processo nº {cnj_cab}). ",
            f"Segundo o relator, Ministro {nome}, o precedente firmado no ano de {rng.randint(2015, 2024)} pelo Supremo Tribunal Federal não se aplica. ",
            f"O Tribunal Superior do Trabalho, em {rng.randint(2015, 2024)}, pacificou a questão em súmula própria, sem número indicado no recurso. ",
            f"Súmula de jurisprudência dominante, verbete sem numeração, e enunciado administrativo nº {rng.randint(2, 30)} da Corregedoria. ",
        ]
        rng.shuffle(pistas)
        for f in pistas[:8]:
            doc.add(f)
            if rng.random() < 0.5:
                enchimento(doc, rng, 1)
        # controles: duas citações normais
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        s_num, s_id = G.sumula_k(am, "STJ", k=n)
        G.cit_sumula(doc, rng, f"Súmula {s_num} do STJ", True, s_id)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


CONJUNTOS = {
    "r6_extrator_formas": conjunto_extrator_formas,
    "r6_extrator_distratores": conjunto_extrator_distratores,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", type=Path, default=RAIZ / "dados" / "adversarial")
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--seed", type=int, default=666)
    ap.add_argument("--so", nargs="*", default=None)
    args = ap.parse_args()
    for nome, fn in CONJUNTOS.items():
        if args.so and nome not in args.so:
            continue
        rng = random.Random(f"{args.seed}:{nome}")
        am = Amostra(args.indice, rng)
        docs = fn(am, rng)
        escrever(docs, args.saida / nome, rng, proteger=True)
        print(f"{nome}: {len(docs)} docs, {sum(len(d.gab) for d in docs)} citações")


if __name__ == "__main__":
    main()
