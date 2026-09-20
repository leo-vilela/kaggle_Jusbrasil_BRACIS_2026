#!/usr/bin/env python3
"""Cruza os erros do avaliar.py com as notas do gabarito adversarial e mostra o trecho + predições vizinhas.

Uso: PYTHONPATH=src python scripts/adversarial/erros.py <conjunto>   (depois de rodar_*.sh; lê saida/adv_<conjunto>/relatorio.json)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
conjunto = sys.argv[1]
pasta = RAIZ / "dados" / "adversarial" / conjunto
saida = RAIZ / "saida" / f"adv_{conjunto}"
rel = json.load(open(saida / "relatorio.json", encoding="utf-8"))
notas = {}
with open(pasta / "gabarito_notas.csv", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        notas[(r["documento_id"], int(r["inicio"]), int(r["fim"]))] = r

erros = rel.get("erros") or rel.get("lista_erros") or []
if not erros:
    # procura em qualquer chave que seja lista de dicts com 'documento_id'
    for k, v in rel.items():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "documento_id" in v[0]:
            erros = v
            break
for e in erros:
    doc = e["documento_id"]
    gs = e.get("gold_span")
    ini, fim = (gs[0], gs[1]) if gs else (None, None)
    n = notas.get((doc, ini, fim), {})
    pred = json.load(open(saida / f"{doc}.json", encoding="utf-8"))["citacoes"]
    texto = (pasta / "txt" / f"{doc}.txt").read_text(encoding="utf-8")
    viz = [(c["inicio"], c["fim"], c["classificacao"], c.get("confianca"), c["trecho"]) for c in pred
           if ini is not None and abs(c["inicio"] - ini) < 120]
    print(f"[{doc}] {e.get('tipo') or e.get('erro')} esperado={e.get('esperado')} obtido={e.get('obtido')} "
          f"gold=({ini},{fim}) nota={n.get('nota', '')!r}")
    if ini is not None:
        print("   gold  :", repr(texto[ini:fim]))
    ps = e.get("pred_span")
    if ps:
        print("   pred  :", repr(texto[ps[0]:ps[1]]), e.get("obtido"), e.get("id_obtido"), "iou=", e.get("iou"))
        if ini is None:
            ini = ps[0]
            viz = [(c["inicio"], c["fim"], c["classificacao"], c.get("confianca"), c["trecho"]) for c in pred if abs(c["inicio"] - ini) < 120]
    for v in viz:
        print("   vizinh:", v)
