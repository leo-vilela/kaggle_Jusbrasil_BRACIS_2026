#!/usr/bin/env python3
"""Gera documentos sintéticos com gabarito (formato do goldenset) a partir da base canônica.

Uso:
    PYTHONPATH=src python scripts/gerar_sinteticos.py --saida dados/sinteticos/n2_dev \\
        --n-docs 40 --nivel 2 --seed 123 --perfil dev

    --nivel 1  formato padrão, sem ruído          --perfil dev        só formas vistas no dev
    --nivel 2  ruído N2 (docs/03 §3)              --perfil agressivo  formas inéditas (ood) + armadilhas novas
    --nivel 3  ruído combinado (implica agressivo)

Saída: <saida>/txt/<documento_id>.txt, goldenset.csv (colunas oficiais, utf-8-sig, "\\n" escapado),
goldenset_estendido.csv (+ familia, tribunal, digitos, classe_cadeia, uf, ruidos, forma, ood, origem_id),
casos_llm.jsonl (árbitro), estatisticas.json e manifesto.json. Imprime as estatísticas.
Somente biblioteca padrão. Ver docs/05_sinteticos.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.base_canonica import BaseCanonica  # noqa: E402
from caca_alucinacao.sinteticos import VERSAO, escrever_conjunto, gerar_conjunto  # noqa: E402


def _relativo_a_raiz(caminho: Path) -> str:
    try:
        return str(caminho.resolve().relative_to(RAIZ))
    except ValueError:
        return str(caminho)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", type=Path, required=True, help="pasta de saída (criada se não existir)")
    ap.add_argument("--n-docs", type=int, default=40)
    ap.add_argument("--nivel", type=int, choices=(1, 2, 3), default=2)
    ap.add_argument("--seed", type=int, default=123)
    ap.add_argument("--perfil", choices=("dev", "agressivo"), default="dev")
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--db", type=Path, default=RAIZ / "dados" / "desafio1_bracis.db",
                    help="usado só se o índice não existir")
    ap.add_argument("--sem-casos-llm", action="store_true")
    ap.add_argument("--json", action="store_true", help="imprime as estatísticas em JSON")
    args = ap.parse_args()

    if args.indice.exists():
        base = BaseCanonica.de_arquivo(args.indice)
    elif args.db.exists():
        print(f"índice {args.indice} não encontrado; construindo a partir de {args.db}", file=sys.stderr)
        base = BaseCanonica.de_banco(args.db)
    else:
        print("nem índice nem banco encontrados", file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    docs = gerar_conjunto(base, args.n_docs, args.nivel, args.seed, args.perfil)
    manifesto = {"versao_gerador": VERSAO, "n_docs": args.n_docs, "nivel": args.nivel, "seed": args.seed,
                 "perfil": docs[0].perfil if docs else args.perfil,
                 # caminho relativo à raiz do repositório: o artefato fica reprodutível byte a byte entre
                 # máquinas (rodada 3, R3e-06)
                 "indice": _relativo_a_raiz(args.indice)}
    est = escrever_conjunto(docs, args.saida, base, casos_llm=not args.sem_casos_llm, manifesto=manifesto)
    dt = time.perf_counter() - t0
    if args.json:
        print(json.dumps(est, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    print(f"{len(docs)} documentos (nível {args.nivel}, perfil {manifesto['perfil']}, seed {args.seed}) em {args.saida} ({dt:.1f}s)")
    print(f"citações: {est['citacoes']} | por documento: {est['por_documento']} | distância entre spans: {est['distancia_entre_spans']}")
    n = est["citacoes"]

    def _linha(titulo: str, d: dict) -> None:
        partes = [f"{k}={v} ({100 * v / n:.0f}%)" for k, v in sorted(d.items(), key=lambda kv: -kv[1])]
        print(f"{titulo}: " + ", ".join(partes))

    _linha("classes", est["classificacao"])
    _linha("tipos", est["tipo"])
    _linha("famílias", est["familia"])
    _linha("tribunais", est["tribunal"])
    print("família × classe: " + ", ".join(f"{k}={v}" for k, v in est["familia_x_classe"].items()))
    print(f"citações com ruído: {est['citacoes_com_ruido']} | fora da distribuição do dev (ood): {est['ood']} | armadilhas: {est['armadilhas']}")
    if est["ruidos"]:
        print("ruídos: " + ", ".join(f"{k}={v}" for k, v in sorted(est["ruidos"].items(), key=lambda kv: -kv[1])))
    if "casos_llm" in est:
        print("casos LLM: " + ", ".join(f"{k}={v}" for k, v in est["casos_llm"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
