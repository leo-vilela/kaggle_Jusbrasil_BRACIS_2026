#!/usr/bin/env python3
"""Medições da base canônica para docs/04_analise_base.md (seções a, b, c).

a. anatomia do cabeçalho por tribunal (posição do número próprio, formatos,
   quantidade de identificadores, classes, UF, layouts);
b. ambiguidades: números próprios compartilhados por ≥2 registros (com o
   veredito do gabarito quando houver);
c. colisões: números próprios curtos que aparecem no corpo de outros registros
   e números próprios iguais em tribunais diferentes.

Uso: python scripts/analise/anatomia_base.py [--indice dados/indice.json]
Imprime só contagens e documento_id; NÃO imprime números de processo.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import re
import sqlite3
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.base_canonica import BaseCanonica, digitos_canonicos  # noqa: E402
from caca_alucinacao.base_canonica.digitos import numeros_do_texto  # noqa: E402
from caca_alucinacao.base_canonica.indice import regiao_de_identificacao  # noqa: E402


def mascara(texto: str) -> str:
    return re.sub(r"\d", "#", texto)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--db", type=Path, default=RAIZ / "dados" / "desafio1_bracis.db")
    ap.add_argument("--gabarito", type=Path, default=RAIZ / "dados" / "goldenset.csv")
    args = ap.parse_args()

    base = BaseCanonica.de_arquivo(args.indice)
    con = sqlite3.connect(str(args.db))
    textos = dict(con.execute("SELECT documento_id, texto FROM documentos").fetchall())
    con.close()
    with open(args.gabarito, encoding="utf-8-sig", newline="") as f:
        gab = list(csv.DictReader(f))
    ids_gab = {int(x["id_canonico"]) for x in gab if x["id_canonico"]}
    digitos_gab = {digitos_canonicos(x["trecho"].replace("\\n", "\n")): x["classificacao"]
                   for x in gab if x["tipo"] == "jurisprudencia" and x["classificacao"] != "incompleta"}

    # ------------------------------------------------------------------ a
    print("== a. ANATOMIA POR TRIBUNAL ==")
    for trib in ["STF", "STJ", "TSE", "TST", "STM"]:
        regs = [r for r in base.registros() if r.tribunal == trib and r.natureza == "acordao"]
        pos, fmt, n_ids, classes, ufs, layouts, relatores, anos = [], collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
        tam_regiao = []
        for r in regs:
            idents = base.identificadores(r.documento_id)
            n_ids[len(idents)] += 1
            for it in idents:
                fmt[it["formato"]] += 1
            if idents:
                pos.append(idents[0]["posicao"])
            classes[r.classe_propria or "?"] += 1
            ufs["com UF" if r.uf else "sem UF"] += 1
            anos[r.ano] += 1
            relatores[mascara_relator(r.relator)] += 1
            t = textos[r.documento_id]
            tam_regiao.append(len(regiao_de_identificacao(t, trib)))
            layouts[layout(t, trib)] += 1
        print(f"\n-- {trib}: {len(regs)} acórdãos | anos {min(anos)}–{max(anos)}")
        print(f"   posição do 1º número próprio: min={min(pos)} mediana={int(statistics.median(pos))} "
              f"p90={sorted(pos)[int(len(pos) * 0.9)]} max={max(pos)}")
        print(f"   tamanho da região de identificação: mediana={int(statistics.median(tam_regiao))} max={max(tam_regiao)}")
        print(f"   identificadores por registro: {dict(sorted(n_ids.items()))} | formatos: {dict(sorted(fmt.items()))}")
        print(f"   UF: {dict(ufs)}")
        print("   layouts do início do texto (top): ")
        for k, v in layouts.most_common(8):
            print(f"      {v:3d}  {k}")
        print(f"   classes próprias (top 12 de {len(classes)}): " + ", ".join(f"{k}={v}" for k, v in classes.most_common(12)))
        print("   formatos de relator: " + ", ".join(f"{k}={v}" for k, v in relatores.most_common(6)))

    # ------------------------------------------------------------------ b
    print("\n== b. AMBIGUIDADES: número próprio compartilhado por ≥2 registros ==")
    grupos = {d: docs for d, docs in base._por_digitos.items() if len(docs) >= 2}
    tipos = collections.Counter()
    print(f"   chaves ambíguas: {len(grupos)} (de {len(base._por_digitos)})")
    for dig, docs in sorted(grupos.items(), key=lambda kv: (base.registro(kv[1][0]).tribunal, kv[0])):
        regs = [base.registro(d) for d in docs]
        hashes = {hashlib.sha1(textos[d].encode()).hexdigest()[:8] for d in docs}
        cab = {hashlib.sha1(textos[d][:600].encode()).hexdigest()[:8] for d in docs}
        classes = {r.classe_propria for r in regs}
        tribs = {r.tribunal for r in regs}
        if len(tribs) > 1:
            tipo = "TRIBUNAIS DIFERENTES"
        elif len(hashes) == 1:
            tipo = "texto idêntico"
        elif len(cab) == 1:
            tipo = "cabeçalho idêntico, corpo diferente"
        elif len(classes) > 1:
            tipo = "classes diferentes (decisões sucessivas)"
        else:
            tipo = "mesma classe, texto diferente"
        tipos[tipo] += 1
        no_gab = [r.documento_id for r in regs if r.id_canonico in ids_gab]
        marca = f"  GABARITO→{no_gab}" if no_gab else ""
        print(f"   [{tipo}] {len(dig)} dígitos: " + " | ".join(
            f"{r.documento_id} {r.tribunal} {r.classe_propria} {r.ano} len={r.texto_len} uf={r.uf} rel={r.relator!r}" for r in regs) + marca)
    print("   resumo: " + ", ".join(f"{k}={v}" for k, v in tipos.most_common()))

    # ------------------------------------------------------------------ c
    print("\n== c. COLISÕES ==")
    corpo: dict[str, set[str]] = collections.defaultdict(set)
    for d, t in textos.items():
        for _, _, dig, _ in numeros_do_texto(t):
            corpo[dig].add(d)
    print("   c1. números próprios curtos (sequenciais) e em quantos OUTROS registros o mesmo número aparece no corpo:")
    por_tamanho = collections.defaultdict(list)
    for dig, docs in base._por_digitos.items():
        r = base.registro(docs[0])
        if len(dig) <= 8:
            outros = len(corpo.get(dig, set()) - set(docs))
            por_tamanho[len(dig)].append(outros)
    for n in sorted(por_tamanho):
        vals = por_tamanho[n]
        print(f"      {n} dígitos: {len(vals)} chaves | aparecem no corpo de outros registros: "
              f"média={statistics.mean(vals):.1f} max={max(vals)} | ≥1: {sum(v >= 1 for v in vals)} | ≥5: {sum(v >= 5 for v in vals)}")
    print("   c2. chaves CNJ (20 dígitos) citadas no corpo de outros registros:")
    vals = [len(corpo.get(dig, set()) - set(docs)) for dig, docs in base._por_digitos.items() if len(dig) == 20]
    print(f"      {len(vals)} chaves | ≥1: {sum(v >= 1 for v in vals)} | max={max(vals)}")
    print("   c3. números próprios iguais em tribunais diferentes:")
    cross = 0
    for dig, docs in sorted(base._por_digitos.items()):
        tribs = sorted({base.registro(d).tribunal for d in docs})
        if len(tribs) > 1:
            cross += 1
            print(f"      {len(dig)} dígitos: " + " | ".join(f"{base.registro(d).documento_id} {base.registro(d).tribunal} {base.registro(d).classe_propria}" for d in docs))
    print(f"      total: {cross}")
    print("   c4. números próprios sequenciais que coincidem com anos (1900–2030) ou com números de leis conhecidas:")
    leis = {"13105", "10406", "5452", "3689", "1001", "8078", "4737", "64", "8429", "9504", "13467", "8666", "14133", "9099", "11419"}
    coinc = [dig for dig in base._por_digitos if (len(dig) == 4 and 1900 <= int(dig) <= 2030) or dig in leis]
    print(f"      {len(coinc)} chaves: " + ", ".join(f"{base.registro(base._por_digitos[d][0]).tribunal}/{base.registro(base._por_digitos[d][0]).classe_propria}" for d in coinc))
    print("   c5. números do gabarito (real/inventada) e quantos registros os citam no corpo sem serem donos:")
    for dig, cls in sorted(digitos_gab.items(), key=lambda kv: (kv[1], -len(corpo.get(kv[0], set())))):
        donos = set(base._por_digitos.get(dig, []))
        n = len(corpo.get(dig, set()) - donos)
        if n:
            print(f"      {cls:9s} {len(dig):2d} dígitos: donos={len(donos)} citam={n}")
    return 0


def mascara_relator(rel: str | None) -> str:
    if not rel:
        return "<vazio>"
    r = re.sub(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,}", "MAIÚSC", rel)
    r = re.sub(r"[A-Za-zÁ-ú][a-záéíóúâêôãõç]+", "Nome", r)
    return r


def layout(texto: str, tribunal: str) -> str:
    t = texto[:120]
    if tribunal == "TST":
        m = re.match(r"(A C Ó R D Ã O\s*\(?[^)]{0,40}\)?|Poder Judiciário[^A]{0,60})", t)
        return mascara(m.group(1)[:50]) if m else mascara(t[:40])
    m = re.match(r"(.{0,60}?)(?=\b(?:AG\.REG|EMB|RECURSO|AGRAVO|RECLAMA|HABEAS|APELA|EMBARGOS|A[CÇ][ÃA]O|MANDADO|CONFLITO|QO|PExt|Ag|ED|SUSPENS|PETI|LISTA|PRESTA|REPRESENTA|CORREI|N[úu]mero|CAUTELAR|REFERENDO|TUTELA|SEGUNDO|TERCEIRO|PLEN|PRIMEIRA|SEGUNDA))", t)
    return mascara((m.group(1) if m else t[:40]).strip())[:70] or "<classe no início>"


if __name__ == "__main__":
    raise SystemExit(main())
