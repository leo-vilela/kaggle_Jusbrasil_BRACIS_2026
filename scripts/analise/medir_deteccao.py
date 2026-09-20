#!/usr/bin/env python3
"""Mede ``deteccao.detectar`` contra um gabarito (dev ou sintético) com as regras da métrica.

Uso:
    PYTHONPATH=src python scripts/analise/medir_deteccao.py                       # dev (dados/txt + goldenset.csv)
    PYTHONPATH=src python scripts/analise/medir_deteccao.py --conjunto dados/sinteticos/n2_dev
    PYTHONPATH=src python scripts/analise/medir_deteccao.py --conjunto dados/sinteticos/n3_ood --erros 80
    PYTHONPATH=src python scripts/analise/medir_deteccao.py --json                # métricas em JSON (para testes)

Alinhamento igual ao de ``kaggle_metric.py``: IoU ≥ 0,5 em codepoints, 1-para-1
guloso por maior IoU; predição sem par que esteja ≥ 90 % contida numa citação já
casada é EXTRA (ignorada); as demais são espúrias (FP). Imprime recall de spans,
precisão, IoU médio, exatidão de fronteira (span idêntico), família e tipo
corretos, cabeçalho (fim_do_cabecalho ≤ primeiro span), tempo por documento e a
lista de erros (documento, offsets, família, motivo — no máximo 40 caracteres de
trecho, nunca a citação inteira do gabarito).

A família do gabarito é inferida do trecho pelo mesmo critério do catálogo
(``dados/catalogo_gabarito.json`` quando existe; senão pela forma). Só biblioteca padrão.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.deteccao import detectar  # noqa: E402
from caca_alucinacao.texto import carregar, fim_do_cabecalho  # noqa: E402
from caca_alucinacao.tipos import iou  # noqa: E402

IOU_MIN = 0.5
FRAC_EXTRA = 0.9

_RE_FAMILIA = [
    ("dispositivo", re.compile(r"^(?:art|Art|ART)", re.S)),
    ("sumula", re.compile(r"^(?:[S5][úuÚU][mM]|[Ee]nunciado)", re.S)),
    ("tema", re.compile(r"^Tem[aã]", re.S)),
    ("vaga", re.compile(r"(?:19|20)\d{2}.{0,80}(?:[Rr]el|relat)", re.S)),
]


def familia_do_trecho(trecho: str, tipo: str) -> str:
    """Família inferida da forma do trecho (o gabarito não a traz)."""
    if tipo == "lei":
        return "dispositivo"
    for fam, rx in _RE_FAMILIA:
        if rx.search(trecho):
            return fam
    return "processo"


def ler_gabarito(caminho: Path) -> dict[str, list[dict]]:
    """``goldenset.csv`` (oficial ou sintético) → citações por documento."""
    por_doc: dict[str, list[dict]] = {}
    with caminho.open(encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f):
            trecho = linha["trecho"].replace("\\n", "\n")
            por_doc.setdefault(linha["documento_id"], []).append({
                "inicio": int(linha["inicio"]), "fim": int(linha["fim"]), "trecho": trecho,
                "tipo": linha["tipo"], "classificacao": linha["classificacao"],
                "familia": linha.get("familia") or familia_do_trecho(trecho, linha["tipo"]),
                "ruidos": linha.get("ruidos", ""), "ood": linha.get("ood", ""),
            })
    return por_doc


def carregar_familias_catalogo(caminho: Path, gab: dict[str, list[dict]]) -> None:
    """Sobrescreve a família inferida pela do catálogo quando ele existe (dev)."""
    if not caminho.exists():
        return
    try:
        cat = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    por_chave = {(e["documento_id"], e["inicio"], e["fim"]): e.get("familia") for e in cat}
    for doc, cits in gab.items():
        for c in cits:
            fam = por_chave.get((doc, c["inicio"], c["fim"]))
            if fam:
                c["familia"] = fam


def casar(golds: list[dict], preds: list) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Réplica de ``kaggle_metric._casar``: guloso por maior IoU, 1-para-1."""
    cands = []
    for gi, g in enumerate(golds):
        for pi, p in enumerate(preds):
            v = iou(g["inicio"], g["fim"], p.inicio, p.fim)
            if v >= IOU_MIN:
                cands.append((-v, gi, pi))
    cands.sort()
    gu, pu, pares = set(), set(), []
    for nv, gi, pi in cands:
        if gi in gu or pi in pu:
            continue
        gu.add(gi)
        pu.add(pi)
        pares.append((gi, pi, -nv))
    return pares, [i for i in range(len(golds)) if i not in gu], [i for i in range(len(preds)) if i not in pu]


def contida(p, g: dict) -> bool:
    largura = p.fim - p.inicio
    inter = max(0, min(p.fim, g["fim"]) - max(p.inicio, g["inicio"]))
    return largura > 0 and inter / largura >= FRAC_EXTRA


def resumo(s: str, n: int = 40) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 1] + "…"


def medir(txt_dir: Path, gabarito: Path, catalogo: Path | None, max_erros: int, verboso: bool) -> dict:
    gab = ler_gabarito(gabarito)
    if catalogo is not None:
        carregar_familias_catalogo(catalogo, gab)
    docs = sorted(p for p in txt_dir.glob("*.txt"))
    total = casados = exatos = fam_ok = tipo_ok = espurios = extras = 0
    ious: list[float] = []
    tempos: list[float] = []
    cab_ok = 0
    erros: list[str] = []
    por_familia: Counter = Counter()
    perdidos_por_familia: Counter = Counter()
    perdidos_por_ruido: Counter = Counter()
    espurios_por_origem: Counter = Counter()
    n_preds = 0
    for arq in docs:
        doc = arq.stem
        texto = carregar(arq)
        golds = sorted(gab.get(doc, []), key=lambda g: (g["inicio"], g["fim"]))
        t0 = time.perf_counter()
        preds = detectar(texto)
        tempos.append(time.perf_counter() - t0)
        n_preds += len(preds)
        limite = fim_do_cabecalho(texto)
        if golds and limite <= golds[0]["inicio"]:
            cab_ok += 1
        elif golds:
            erros.append(f"{doc} cabecalho fim={limite} > 1o span={golds[0]['inicio']}")
        for g in golds:
            if texto[g["inicio"]:g["fim"]] != g["trecho"]:
                erros.append(f"{doc} gabarito ({g['inicio']},{g['fim']}) trecho != texto[inicio:fim]")
        pares, g_sem, p_sem = casar(golds, preds)
        total += len(golds)
        for gi, pi, v in pares:
            g, p = golds[gi], preds[pi]
            casados += 1
            ious.append(v)
            por_familia[g["familia"]] += 1
            if (p.inicio, p.fim) == (g["inicio"], g["fim"]):
                exatos += 1
            else:
                erros.append(f"{doc} fronteira gab=({g['inicio']},{g['fim']}) pred=({p.inicio},{p.fim}) "
                             f"{g['familia']} IoU={v:.2f} pred={resumo(p.trecho)!r} [{p.origem}]")
            if p.familia == g["familia"]:
                fam_ok += 1
            else:
                erros.append(f"{doc} familia gab={g['familia']} pred={p.familia} ({g['inicio']},{g['fim']}) [{p.origem}]")
            if p.tipo == g["tipo"]:
                tipo_ok += 1
            else:
                erros.append(f"{doc} tipo gab={g['tipo']} pred={p.tipo} ({g['inicio']},{g['fim']})")
        for gi in g_sem:
            g = golds[gi]
            perdidos_por_familia[g["familia"]] += 1
            for r in (g.get("ruidos") or "").split("|"):
                if r:
                    perdidos_por_ruido[r] += 1
            vizinhos = [p for p in preds if p.inicio < g["fim"] and g["inicio"] < p.fim]
            viz = f" sobrepoe pred=({vizinhos[0].inicio},{vizinhos[0].fim}) [{vizinhos[0].origem}]" if vizinhos else ""
            erros.append(f"{doc} PERDIDO ({g['inicio']},{g['fim']}) {g['familia']} {g['classificacao']} "
                         f"forma={resumo(g['trecho'])!r}{viz} ruidos={g.get('ruidos','')}")
        for pi in p_sem:
            p = preds[pi]
            if any(contida(p, golds[gi]) for gi, _, _ in pares):
                extras += 1
                continue
            espurios += 1
            espurios_por_origem[p.origem] += 1
            erros.append(f"{doc} ESPURIO ({p.inicio},{p.fim}) {p.familia} forca={p.forca} "
                         f"{resumo(p.trecho)!r} [{p.origem}]")
    metricas = {
        "documentos": len(docs), "citacoes": total, "predicoes": n_preds, "casados": casados,
        "recall": casados / total if total else 0.0,
        "precisao": (casados / (casados + espurios)) if (casados + espurios) else 0.0,
        "espurios": espurios, "extras": extras,
        "iou_medio": statistics.mean(ious) if ious else 0.0,
        "fronteira_exata": exatos, "familia_ok": fam_ok, "tipo_ok": tipo_ok,
        "cabecalho_ok": cab_ok,
        "tempo_medio_ms": 1000 * statistics.mean(tempos) if tempos else 0.0,
        "tempo_max_ms": 1000 * max(tempos) if tempos else 0.0,
        "por_familia": dict(sorted(por_familia.items())),
        "perdidos_por_familia": dict(sorted(perdidos_por_familia.items())),
        "perdidos_por_ruido": dict(perdidos_por_ruido.most_common(15)),
        "espurios_por_origem": dict(sorted(espurios_por_origem.items())),
        "erros": erros if verboso else erros[:max_erros],
        "n_erros": len(erros),
    }
    return metricas


def imprimir(m: dict) -> None:
    print(f"documentos: {m['documentos']}  citações: {m['citacoes']}  predições: {m['predicoes']}")
    print(f"recall de spans (IoU≥0,5): {m['casados']}/{m['citacoes']} = {m['recall']:.4f}")
    print(f"precisão: {m['precisao']:.4f}  (espúrios: {m['espurios']}, extras ignorados: {m['extras']})")
    print(f"IoU médio dos casados: {m['iou_medio']:.4f}")
    print(f"fronteira exata: {m['fronteira_exata']}/{m['casados']}")
    print(f"família correta: {m['familia_ok']}/{m['casados']}   tipo correto: {m['tipo_ok']}/{m['casados']}")
    print(f"cabeçalho ≤ 1º span: {m['cabecalho_ok']}/{m['documentos']}")
    print(f"tempo: média {m['tempo_medio_ms']:.1f} ms/doc, máx {m['tempo_max_ms']:.1f} ms")
    print(f"casados por família: {m['por_familia']}")
    if m["perdidos_por_familia"]:
        print(f"perdidos por família: {m['perdidos_por_familia']}")
        print(f"perdidos por ruído: {m['perdidos_por_ruido']}")
    if m["espurios_por_origem"]:
        print(f"espúrios por origem: {m['espurios_por_origem']}")
    print(f"erros ({m['n_erros']}):")
    for e in m["erros"]:
        print("  -", e)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conjunto", type=Path, default=None,
                    help="pasta com txt/ e goldenset.csv (sintéticos); padrão: dev em dados/")
    ap.add_argument("--txt", type=Path, default=None)
    ap.add_argument("--gabarito", type=Path, default=None)
    ap.add_argument("--erros", type=int, default=60, help="máximo de erros listados")
    ap.add_argument("--verboso", action="store_true", help="lista todos os erros")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.conjunto is not None:
        txt, gab = args.conjunto / "txt", args.conjunto / "goldenset_estendido.csv"
        if not gab.exists():
            gab = args.conjunto / "goldenset.csv"
        catalogo = None
    else:
        txt = args.txt or RAIZ / "dados" / "txt"
        gab = args.gabarito or RAIZ / "dados" / "goldenset.csv"
        catalogo = RAIZ / "dados" / "catalogo_gabarito.json"
    if not txt.is_dir() or not gab.exists():
        print(f"faltam {txt} ou {gab}", file=sys.stderr)
        return 2
    m = medir(txt, gab, catalogo, args.erros, args.verboso)
    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=1))
    else:
        imprimir(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
