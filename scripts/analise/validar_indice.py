#!/usr/bin/env python3
"""Valida o índice de números próprios contra o gabarito de desenvolvimento.

Verificações (docs/04_analise_base.md, seções d–g):

* d. toda citação ``real`` de jurisprudência resolve pelo índice para o
  ``id_canonico`` do gabarito (cobertura obrigatória 96/96, contando súmulas)
  e quantos registros apenas *citam* o mesmo número no corpo (armadilha);
* e. nenhuma citação ``inventada`` com número casa com número próprio; quantos
  registros citam o número no corpo;
* f. multiplicidade das ``incompleta`` (tribunal + ano + relator);
* g. dispositivos e súmulas resolvem pela tabela derivada.

Uso: python scripts/analise/validar_indice.py [--indice dados/indice.json]
Termina com ``COBERTURA 96/96`` (código de saída 0) ou ``COBERTURA n/96`` (1).
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.base_canonica import (  # noqa: E402
    BaseCanonica,
    artigo_canonico,
    digitos_canonicos,
    diploma_canonico,
    separar_uf,
    sumula_canonica,
)
from caca_alucinacao.base_canonica.classes import cadeia_de_classes  # noqa: E402
from caca_alucinacao.base_canonica.digitos import numeros_do_texto  # noqa: E402

_RE_TRIB = re.compile(r"\b(STF|STJ|TST|TSE|STM)\b")
_RE_ANO = re.compile(r"\b(20\d{2}|19\d{2})\b")
_RE_REL = re.compile(r"(?:relatoria\s+\w{1,2}|Rel\.?\s*(?:Min\.?|Ministr[oa])?\.?)\s*(?P<nome>.+)$", re.I | re.S)


def ler_gabarito(caminho: Path) -> list[dict[str, str]]:
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f))
    for x in linhas:
        x["trecho"] = x["trecho"].replace("\\n", "\n")
    return linhas


def e_sumula(trecho: str) -> bool:
    return bool(re.search(r"[s5]\s?[uúü]\s?m", trecho, re.I))


def corpo_por_numero(caminho_db: Path) -> dict[str, set[str]]:
    """digitos → conjunto de documento_id cujo TEXTO contém o número (em qualquer posição)."""
    con = sqlite3.connect(str(caminho_db))
    try:
        linhas = con.execute("SELECT documento_id, texto FROM documentos WHERE natureza='acordao'").fetchall()
    finally:
        con.close()
    mapa: dict[str, set[str]] = collections.defaultdict(set)
    for documento_id, texto in linhas:
        for _, _, dig, _ in numeros_do_texto(texto):
            mapa[dig].add(documento_id)
    return mapa


def parse_incompleta(trecho: str) -> tuple[str | None, int | None, str | None]:
    t = trecho.replace("\n", " ")
    trib = _RE_TRIB.search(t)
    ano = _RE_ANO.search(t)
    rel = _RE_REL.search(t)
    nome = rel.group("nome").strip(" .,") if rel else None
    return (trib.group(1) if trib else None), (int(ano.group(1)) if ano else None), nome


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--db", type=Path, default=RAIZ / "dados" / "desafio1_bracis.db")
    ap.add_argument("--gabarito", type=Path, default=RAIZ / "dados" / "goldenset.csv")
    args = ap.parse_args()

    base = BaseCanonica.de_arquivo(args.indice)
    gab = ler_gabarito(args.gabarito)
    corpo = corpo_por_numero(args.db)

    reais = [x for x in gab if x["classificacao"] == "real"]
    inventadas = [x for x in gab if x["classificacao"] == "inventada"]
    incompletas = [x for x in gab if x["classificacao"] == "incompleta"]
    print(f"gabarito: {len(gab)} citações | real={len(reais)} inventada={len(inventadas)} incompleta={len(incompletas)}")

    # ---------------------------------------------------------------- d
    print("\n== d. REAL: índice devolve o id do gabarito? (quem é) × quantos só citam (quem cita) ==")
    ok = 0
    linhas_d: list[tuple] = []
    armadilha = collections.Counter()
    for x in reais:
        t, gab_id = x["trecho"], int(x["id_canonico"])
        if x["tipo"] == "lei":
            d, a = diploma_canonico(t), artigo_canonico(t)
            reg = base.dispositivo(d, a) if d and a else None
            acertou = reg is not None and reg.id_canonico == gab_id
            linhas_d.append(("lei", f"{d}|{a}", 1 if reg else 0, 1 if reg else 0, 0, acertou))
        elif e_sumula(t):
            trib, vinc, num = sumula_canonica(t)
            reg = base.sumula(trib, vinc, num) if num is not None else None
            acertou = reg is not None and reg.id_canonico == gab_id
            linhas_d.append(("sumula", f"{trib}|{int(vinc)}|{num}", 1 if reg else 0, 1 if reg else 0, 0, acertou))
        else:
            sem_uf, uf = separar_uf(t)
            dig = digitos_canonicos(t)
            cands = base.candidatos_por_numero(dig)
            cadeia = " ".join(cadeia_de_classes(sem_uf))
            filtrados = base.candidatos_por_numero_e_classe(dig, cadeia, None, uf)
            acertou = any(c.id_canonico == gab_id for c in cands)
            donos = {c.documento_id for c in cands}
            citam = len(corpo.get(dig, set()) - donos)
            armadilha[min(citam, 10)] += 1
            so_filtro = any(c.id_canonico == gab_id for c in filtrados)
            linhas_d.append(("processo", dig, len(cands), len(filtrados), citam, acertou and (so_filtro or len(filtrados) == 0)))
            if not so_filtro and acertou:
                print(f"  AVISO filtro por classe/UF removeria o gabarito: {dig} cadeia={cadeia!r} uf={uf} "
                      f"(registro: {[c.classe_propria for c in cands]})")
        if linhas_d[-1][-1]:
            ok += 1
        else:
            print(f"  FALHA {x['documento_id']} {x['citacao_id']} {t!r} → {linhas_d[-1]}")
    n_proc = sum(1 for ln in linhas_d if ln[0] == "processo")
    print(f"  processos: {n_proc} | com ≥2 candidatos pelo número: "
          f"{sum(1 for ln in linhas_d if ln[0] == 'processo' and ln[2] >= 2)} | "
          f"após classe/UF ainda ≥2: {sum(1 for ln in linhas_d if ln[0] == 'processo' and ln[3] >= 2)}")
    print("  registros que só CITAM o número no corpo (por citação real): "
          + ", ".join(f"{k}{'+' if k == 10 else ''}:{v}" for k, v in sorted(armadilha.items())))
    print(f"  total de 'falsos donos' que BM25/FTS devolveria: {sum(ln[4] for ln in linhas_d if ln[0] == 'processo')}")

    # ---------------------------------------------------------------- e
    print("\n== e. INVENTADA com número: existe como número PRÓPRIO? (esperado: nunca) ==")
    colisoes = 0
    cit_corpo = collections.Counter()
    for x in inventadas:
        t = x["trecho"]
        if x["tipo"] == "lei" or e_sumula(t) or "Tema" in t or "Tcma" in t:
            continue
        sem_uf, uf = separar_uf(t)
        dig = digitos_canonicos(t)
        cands = base.candidatos_por_numero(dig)
        citam = len(corpo.get(dig, set()))
        cit_corpo[min(citam, 5)] += 1
        if cands:
            colisoes += 1
            cadeia = cadeia_de_classes(sem_uf)
            print(f"  COLISÃO {dig} citada como {cadeia}/{uf} ← próprio de "
                  f"{[(c.documento_id, c.tribunal, c.classe_propria, c.uf) for c in cands]}")
    print(f"  inventadas de processo: {sum(cit_corpo.values())} | com número próprio na base: {colisoes}")
    print("  aparecem no CORPO de n registros: " + ", ".join(f"{k}{'+' if k == 5 else ''}:{v}" for k, v in sorted(cit_corpo.items())))

    # ---------------------------------------------------------------- f
    print("\n== f. INCOMPLETA (tribunal + ano + relator): quantos registros casam ==")
    dist = collections.Counter()
    for x in incompletas:
        trib, ano, rel = parse_incompleta(x["trecho"])
        regs = base.por_relator_ano(trib, ano, rel)
        dist[min(len(regs), 6)] += 1
        marca = "  ARMADILHA(=1)" if len(regs) == 1 else ("  SEM_CASAMENTO" if not regs else "")
        print(f"  n={len(regs):2d} trib={trib} ano={ano} rel={rel!r}{marca}")
    print("  distribuição (n registros → citações): " + ", ".join(f"{k}{'+' if k == 6 else ''}:{v}" for k, v in sorted(dist.items())))

    # ---------------------------------------------------------------- g
    print("\n== g. LEI e SÚMULA: real ↔ existe, inventada ↔ não existe ==")
    g_ok = g_tot = 0
    for x in gab:
        t = x["trecho"]
        if x["tipo"] == "lei":
            d, a = diploma_canonico(t), artigo_canonico(t)
            reg = base.dispositivo(d, a) if d and a else None
            chave = f"{d}|{a}"
        elif e_sumula(t):
            trib, vinc, num = sumula_canonica(t)
            reg = base.sumula(trib, vinc, num) if num is not None else None
            chave = f"{trib}|{int(vinc)}|{num}"
        else:
            continue
        g_tot += 1
        esperado = x["classificacao"] == "real"
        coerente = (reg is not None) == esperado and (not esperado or reg.id_canonico == int(x["id_canonico"]))
        g_ok += coerente
        if not coerente:
            print(f"  FALHA {x['classificacao']} {chave} → {reg}")
    print(f"  coerentes: {g_ok}/{g_tot}")

    print(f"\nCOBERTURA {ok}/{len(reais)}")
    return 0 if ok == len(reais) else 1


if __name__ == "__main__":
    raise SystemExit(main())
