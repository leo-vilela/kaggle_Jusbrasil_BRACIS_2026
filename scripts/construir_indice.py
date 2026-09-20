#!/usr/bin/env python3
"""Constrói o índice de números próprios: dados/desafio1_bracis.db → dados/indice.json.

Uso: python scripts/construir_indice.py [--db CAMINHO] [--saida CAMINHO]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.base_canonica.indice import (  # noqa: E402
    construir_indice,
    estatisticas,
    salvar_indice,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=RAIZ / "dados" / "desafio1_bracis.db")
    ap.add_argument("--saida", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if not args.db.exists():
        print(f"banco não encontrado: {args.db}", file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    indice = construir_indice(args.db)
    salvar_indice(indice, args.saida)
    dt = time.perf_counter() - t0
    est = estatisticas(indice)
    print(f"índice salvo em {args.saida} ({dt:.1f}s)")
    print(f"registros: {len(indice['registros'])} | chaves numéricas: {est['chaves']} | "
          f"chaves ambíguas (≥2 registros): {est['chaves_ambiguas']} | "
          f"acórdãos sem identificador: {est['sem_identificador']}")
    print("por tribunal:")
    for trib, d in sorted(est["por_tribunal"].items()):
        print(f"  {trib}: registros={d['registros']} sequencial={d['sequencial']} cnj={d['cnj']} "
              f"registro={d['registro']} com_uf={d['com_uf']} sem_identificador={d['sem_identificador']}")
    n = indice["normativos"]
    print(f"súmulas: {len(n['sumulas'])} | dispositivos: {len(n['dispositivos'])} | "
          f"diplomas: {', '.join(n['diplomas_na_base'])} | não derivados: {n['nao_derivados']}")
    if indice["sem_identificador"]:
        print("SEM IDENTIFICADOR:", ", ".join(indice["sem_identificador"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
