#!/usr/bin/env python3
"""Ajusta ``dados/calibracao.json`` pela acurácia empírica por caminho de decisão.

Fontes de avaliação (``(caminho, acerto)`` por citação), combináveis:

* ``--relatorio relatorio.json``  — saída de ``scripts/avaliar.py --json`` (campo
  ``por_caminho: {caminho: {n, acertos}}``, calculado sobre o pipeline completo);
* ``--rastro rastro.jsonl --gabarito goldenset.csv`` — rastro do pipeline
  (``--rastro`` do CLI) alinhado aqui com o gabarito (IoU ≥ 0,5, guloso, como
  a métrica; espúrios contam como erro; pares de ``rastro``/``gabarito`` na ordem);
* ``--catalogo dados/catalogo_gabarito.json`` — resolução direta dos spans do dev
  (mede só a resolução; padrão se o arquivo existir);
* ``--sinteticos dados/sinteticos/n2_dev …`` — resolução direta dos sintéticos
  (``goldenset_estendido.csv``); ``--validacao`` recebe pastas sintéticas usadas
  **só** para medir o Brier fora da amostra (nunca reaproveite o seed de treino);
* ``--validacao-rastro r.jsonl --validacao-gabarito g.csv`` — o mesmo, no nível do
  pipeline completo (rastro alinhado ao gabarito), **nunca** entra no ajuste. O
  ``meta.validacao`` gravado registra n, acurácia e Brier antes/depois de cada
  conjunto de validação; ``scripts/calibrar_completo.py`` é o caminho oficial.

Saída: ``{"tabela": {caminho: confiança}, "meta": {...}}`` — formato que
``cli.carregar_calibracao`` e ``calibracao.carregar`` leem. Imprime o Brier
antes (tabela inicial) e depois (tabela ajustada) por fonte, in-sample e na
validação. Determinístico (semente fixa; sem aleatoriedade no ajuste).

Uso:
    PYTHONPATH=src python scripts/treinar_calibracao.py \\
        --sinteticos dados/sinteticos/n2_dev --validacao dados/sinteticos/n3_ood \\
        --saida dados/calibracao.json
    PYTHONPATH=src python scripts/treinar_calibracao.py --relatorio relatorio.json \\
        --rastro saida/rastro.jsonl --gabarito dados/goldenset.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts" / "analise"))

from caca_alucinacao import calibracao as cal  # noqa: E402
from caca_alucinacao.config import DADOS, SEED, caminho_calibracao, fixar_semente  # noqa: E402
from caca_alucinacao.tipos import iou  # noqa: E402

log = logging.getLogger("treinar_calibracao")
IOU_MIN = 0.5
GOLDENSET = DADOS / "goldenset.csv"


# ---------------------------------------------------------------------------
# Fontes
# ---------------------------------------------------------------------------
def avaliacoes_de_relatorio(caminho: Path) -> list[cal.Avaliacao]:
    """Expande ``por_caminho`` de um relatório do ``avaliar.py`` em avaliações unitárias."""
    r = json.loads(Path(caminho).read_text(encoding="utf-8"))
    por = r.get("por_caminho") or {}
    saida: list[cal.Avaliacao] = []
    for cam, e in sorted(por.items()):
        n, a = int(e.get("n", 0)), int(e.get("acertos", 0))
        saida.extend(cal.Avaliacao(cam, 1) for _ in range(a))
        saida.extend(cal.Avaliacao(cam, 0) for _ in range(max(0, n - a)))
    return saida


def _norm_id(v: Any) -> str:
    s = str(v or "").strip()
    return (s.lstrip("0") or "0") if s.isdigit() else s


def avaliacoes_de_rastro(rastro: Path, gabarito: Path) -> list[cal.Avaliacao]:
    """Alinha as citações emitidas no rastro com o gabarito (mesmas regras da métrica)."""
    from caca_alucinacao.sinteticos import ler_goldenset

    golds: dict[str, list[dict[str, Any]]] = {}
    for g in ler_goldenset(gabarito):
        golds.setdefault(g["documento_id"], []).append({
            "inicio": int(g["inicio"]), "fim": int(g["fim"]), "classe": g["classificacao"].strip().lower(),
            "ids": {_norm_id(x) for x in str(g.get("id_canonico") or "").split(":") if x.strip() not in ("", "-")},
        })
    preds: dict[str, list[dict[str, Any]]] = {}
    with Path(rastro).open(encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            r = json.loads(linha)
            if r.get("status") != "emitida" or not r.get("caminho"):
                continue
            if str(r.get("origem") or "").startswith("llm:extrator:mock"):
                # o mock exercita o caminho, mas a sua precisão não é a do modelo real: essas
                # decisões nunca treinam os caminhos ``llm:*`` (ADR 0003/0007)
                continue
            preds.setdefault(r["documento_id"], []).append(r)
    saida: list[cal.Avaliacao] = []
    for doc in sorted(preds):
        ps, gs = preds[doc], golds.get(doc, [])
        pares = sorted(((-iou(g["inicio"], g["fim"], int(p["inicio"]), int(p["fim"])), gi, pi)
                        for gi, g in enumerate(gs) for pi, p in enumerate(ps)
                        if iou(g["inicio"], g["fim"], int(p["inicio"]), int(p["fim"])) >= IOU_MIN))
        g_usado: set[int] = set()
        p_usado: set[int] = set()
        casado: dict[int, int] = {}
        for _, gi, pi in pares:
            if gi in g_usado or pi in p_usado:
                continue
            g_usado.add(gi)
            p_usado.add(pi)
            casado[pi] = gi
        for pi, p in enumerate(ps):
            forca = float(p.get("forca", 1.0) or 1.0)
            if pi not in casado:
                saida.append(cal.Avaliacao(str(p["caminho"]), 0, forca))
                continue
            g = gs[casado[pi]]
            ok = p.get("classificacao") == g["classe"]
            if ok and g["classe"] == "real":
                ok = _norm_id(p.get("id_canonico")) in g["ids"]
            saida.append(cal.Avaliacao(str(p["caminho"]), 1 if ok else 0, forca))
    return saida


def avaliacoes_de_resolucao(base: Any, casos: list[Any]) -> list[cal.Avaliacao]:
    import medir_resolucao as mr

    return mr.avaliacoes_de(mr.medir(base, casos))


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------
def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.4f}"


def imprimir_comparacao(nome: str, avs: list[cal.Avaliacao], inicial: dict[str, float], final: dict[str, float]) -> None:
    antes, depois = cal.brier(avs, inicial), cal.brier(avs, final)
    acc = sum(a.acerto for a in avs) / len(avs) if avs else None
    print(f"  {nome:40s} n={len(avs):5d}  acurácia={_fmt(acc)}  Brier antes={_fmt(antes)}  depois={_fmt(depois)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--relatorio", type=Path, nargs="*", default=[], help="relatorio.json do avaliar.py")
    ap.add_argument("--rastro", type=Path, nargs="*", default=[], help="rastro.jsonl do pipeline")
    ap.add_argument("--gabarito", type=Path, nargs="*", default=[],
                    help="goldenset.csv de cada rastro (mesma ordem; padrão dados/goldenset.csv)")
    ap.add_argument("--catalogo", type=Path, default=DADOS / "catalogo_gabarito.json")
    ap.add_argument("--sem-catalogo", action="store_true")
    ap.add_argument("--sinteticos", type=Path, nargs="*", default=[], help="pastas sintéticas de TREINO")
    ap.add_argument("--validacao", type=Path, nargs="*", default=[], help="pastas sintéticas só para o Brier")
    ap.add_argument("--validacao-rastro", type=Path, nargs="*", default=[],
                    help="rastro.jsonl de conjuntos de VALIDAÇÃO (fora do ajuste; Brier no nível do pipeline)")
    ap.add_argument("--validacao-gabarito", type=Path, nargs="*", default=[],
                    help="goldenset.csv de cada --validacao-rastro (mesma ordem; padrão dados/goldenset.csv)")
    ap.add_argument("--tabela-inicial", type=Path, default=None, help="JSON com priors (padrão: TABELA_INICIAL)")
    ap.add_argument("--peso-prior", type=float, default=cal.PESO_PRIOR,
                    help="peso do prior em observações equivalentes (2 = Laplace puro)")
    ap.add_argument("--saida", type=Path, default=None, help="padrão: CACA_CALIBRACAO ou dados/calibracao.json")
    ap.add_argument("--indice", type=Path, default=None)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--log-level", default="WARNING")
    args = ap.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING),
                        format="%(levelname)s %(name)s: %(message)s")
    fixar_semente(SEED)

    inicial = cal.carregar(args.tabela_inicial) if args.tabela_inicial else dict(cal.TABELA_INICIAL)
    if not inicial:
        inicial = dict(cal.TABELA_INICIAL)

    fontes: list[tuple[str, list[cal.Avaliacao]]] = []
    for r in args.relatorio:
        if not r.exists():
            log.warning("relatório %s ausente; ignorado", r)
            continue
        fontes.append((f"relatorio:{r.name}", avaliacoes_de_relatorio(r)))
    if len(args.gabarito) > len(args.rastro):
        print("--gabarito em excesso: informe um por --rastro (ou nenhum, para usar dados/goldenset.csv)", file=sys.stderr)
        return 2
    gabaritos = list(args.gabarito) + [GOLDENSET] * (len(args.rastro) - len(args.gabarito))
    for r, g in zip(args.rastro, gabaritos):
        if not r.exists() or not g.exists():
            log.warning("rastro %s ou gabarito %s ausente; ignorado", r, g)
            continue
        fontes.append((f"rastro:{r.parent.name}/{r.name}", avaliacoes_de_rastro(r, g)))

    base = None
    precisa_base = (not args.sem_catalogo and args.catalogo.exists()) or args.sinteticos or args.validacao
    if precisa_base:
        import medir_resolucao as mr

        base = mr.carregar_base(args.indice, args.db)
        if not args.sem_catalogo and args.catalogo.exists():
            fontes.append(("catalogo:dev", avaliacoes_de_resolucao(base, mr.achados_do_catalogo(args.catalogo))))
        for pasta in args.sinteticos:
            fontes.append((f"sintetico:{pasta.name}", avaliacoes_de_resolucao(base, mr.achados_dos_sinteticos(pasta))))
    validacao: list[tuple[str, list[cal.Avaliacao]]] = []
    for pasta in args.validacao:
        import medir_resolucao as mr

        validacao.append((f"validacao:{pasta.name}", avaliacoes_de_resolucao(base, mr.achados_dos_sinteticos(pasta))))
    if len(args.validacao_gabarito) > len(args.validacao_rastro):
        print("--validacao-gabarito em excesso: informe um por --validacao-rastro", file=sys.stderr)
        return 2
    gabaritos_val = list(args.validacao_gabarito) + [GOLDENSET] * (len(args.validacao_rastro) - len(args.validacao_gabarito))
    for r, g in zip(args.validacao_rastro, gabaritos_val):
        if not r.exists() or not g.exists():
            print(f"validação: rastro {r} ou gabarito {g} ausente", file=sys.stderr)
            return 2
        if any(r.resolve() == t.resolve() for t in args.rastro):
            print(f"validação: {r} também está no treino — um conjunto não pode estar nos dois", file=sys.stderr)
            return 2
        validacao.append((f"validacao-rastro:{r.parent.name}/{r.name}", avaliacoes_de_rastro(r, g)))

    treino = [a for _, avs in fontes for a in avs]
    if not treino:
        print("nenhuma avaliação de treino (informe --relatorio, --rastro/--gabarito, --catalogo ou --sinteticos)",
              file=sys.stderr)
        return 2
    final = cal.ajustar(inicial, treino, peso_prior=args.peso_prior)

    print("Treino (in-sample):")
    for nome, avs in fontes:
        imprimir_comparacao(nome, avs, inicial, final)
    imprimir_comparacao("TOTAL treino", treino, inicial, final)
    if validacao:
        print("Validação (fora da amostra):")
        for nome, avs in validacao:
            imprimir_comparacao(nome, avs, inicial, final)
        imprimir_comparacao("TOTAL validação", [a for _, avs in validacao for a in avs], inicial, final)

    contagens = cal.contagens(treino)
    print("\nTabela ajustada (caminho: inicial → final [n, acertos]):")
    for cam in sorted(final):
        v0, chave0 = cal.valor_do_caminho(cam, inicial)
        n, a = contagens.get(cam, (0.0, 0.0))
        marca = "" if chave0 == cam else f" (prior de {chave0 or 'padrão'})"
        print(f"  {cam:48s} {v0:.3f} → {final[cam]:.3f}   [n={n:.0f}, acertos={a:.0f}]{marca}")

    saida = args.saida or caminho_calibracao()
    meta = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "fontes": [{"nome": n, "n": len(avs), "acertos": sum(a.acerto for a in avs)} for n, avs in fontes],
        "validacao": [{"nome": n, "n": len(avs), "acertos": sum(a.acerto for a in avs),
                       "brier_antes": cal.brier(avs, inicial), "brier_depois": cal.brier(avs, final)}
                      for n, avs in validacao],
        "brier_treino_antes": cal.brier(treino, inicial),
        "brier_treino_depois": cal.brier(treino, final),
        "peso_prior": args.peso_prior, "teto": cal.CONFIANCA_TETO, "piso": cal.CONFIANCA_PISO, "seed": SEED,
        "teto_consolidado": cal.CONFIANCA_TETO_CONSOLIDADO, "n_minimo_consolidado": cal.N_MINIMO_CONSOLIDADO,
        "caminhos_consolidados": sorted(c for c, v in final.items() if v > cal.CONFIANCA_TETO),
        "contagens": {k: {"n": v[0], "acertos": v[1]} for k, v in contagens.items()},
        "suavizacao": "(a + k*p0)/(n + k): Laplace generalizado, p0 = prior hierárquico da tabela inicial, k = peso_prior",
    }
    cal.salvar(final, saida, meta)
    print(f"\ntabela com {len(final)} caminhos gravada em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
