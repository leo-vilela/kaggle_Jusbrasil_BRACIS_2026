#!/usr/bin/env python3
"""Mede, de ponta a ponta e com a métrica oficial, o efeito de LIGAR o árbitro LLM (ADR 0003).

    python scripts/comparar_arbitro.py                       # mock, todos os conjuntos (dev, sintéticos, adversariais)
    python scripts/comparar_arbitro.py --arbitro transformers --cache cache_llm/avaliacao.sqlite   # na GPU
    python scripts/comparar_arbitro.py --so dev r6_extrator_formas r6_extrator_distratores

Para cada conjunto, roda o pipeline duas vezes — ``--arbitro nenhum`` (núcleo) e ``--arbitro X`` —
com ``--rastro``, avalia as duas saídas com ``scripts/avaliar.py`` (que importa o ``kaggle_metric.py``
da organização) e compara: Δscore, τ (fração ``inventada→real``), número de citações acrescentadas
pelo extrator e quantas delas acertaram (alinhamento IoU ≥ 0,5 com o gabarito, classe e id, como a
métrica), chamadas ao modelo e tempo. Sai com o veredito do CRITÉRIO DE DECISÃO (ADR 0003):

  o árbitro fica ligado na submissão se, e só se,
  (a) em nenhum conjunto o score caiu mais que ``--tolerancia`` (padrão 0,0005);
  (b) em nenhum conjunto a contagem ``inventada→real`` aumentou;
  (c) nos conjuntos que forçam os gatilhos (``r6_extrator_*``, ou ``--gatilhos``) o score subiu;
  (d) o dev continua byte a byte idêntico OU melhor.

Código de saída: 0 = critério satisfeito; 1 = não satisfeito; 2 = erro de execução. Relatório JSON em
``--saida-json`` (padrão ``<saida>/comparacao_arbitro.json``) — é o artefato que documenta a decisão.
"""
from __future__ import annotations

import argparse
import csv
import filecmp
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dados"
sys.path.insert(0, str(RAIZ / "src"))
from caca_alucinacao.tipos import iou  # noqa: E402

IOU_MIN = 0.5
GATILHOS_PADRAO = ("r6_extrator_formas", "r6_extrator_distratores")


def rodar(cmd: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(RAIZ / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=str(RAIZ), env=env, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, check=False)


def conjuntos_disponiveis() -> list[tuple[str, Path, Path]]:
    saida = [("dev", DADOS / "txt", DADOS / "goldenset.csv")]
    for n in ("n2_dev", "n3_ood", "n2_ag_treino"):
        p = DADOS / "sinteticos" / n
        if (p / "goldenset.csv").exists():
            saida.append((n, p / "txt", p / "goldenset.csv"))
    adv = DADOS / "adversarial"
    if adv.is_dir():
        for p in sorted(adv.iterdir()):
            if (p / "goldenset.csv").exists() and (p / "txt").is_dir():
                saida.append((p.name, p / "txt", p / "goldenset.csv"))
    return saida


def _norm_id(v) -> str:
    s = str(v or "").strip()
    return (s.lstrip("0") or "0") if s.isdigit() else s


def ler_gabarito(caminho: Path) -> dict[str, list[dict]]:
    golds: dict[str, list[dict]] = {}
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            golds.setdefault(r["documento_id"], []).append({
                "inicio": int(r["inicio"]), "fim": int(r["fim"]), "classe": r["classificacao"].strip().lower(),
                "ids": {_norm_id(x) for x in str(r.get("id_canonico") or "").split(":") if x.strip() not in ("", "-")}})
    return golds


def analisar_rastro(rastro: Path, golds: dict[str, list[dict]]) -> dict:
    """Citações emitidas pelo extrator LLM: quantas, quantas certas, e ``inventada→real`` totais."""
    preds: dict[str, list[dict]] = {}
    with open(rastro, encoding="utf-8") as f:
        for linha in f:
            if not linha.strip():
                continue
            r = json.loads(linha)
            if r.get("status") != "emitida":
                continue
            preds.setdefault(r["documento_id"], []).append(r)
    llm_total = llm_certas = inv_para_real = 0
    chamadas = 0
    for doc, ps in preds.items():
        gs = golds.get(doc, [])
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
            eh_llm = str(p.get("origem") or "").startswith("llm:extrator")
            g = gs[casado[pi]] if pi in casado else None
            ok = g is not None and p.get("classificacao") == g["classe"] and \
                (g["classe"] != "real" or _norm_id(p.get("id_canonico")) in g["ids"])
            if g is not None and g["classe"] == "inventada" and p.get("classificacao") == "real":
                inv_para_real += 1
            if eh_llm:
                llm_total += 1
                llm_certas += int(bool(ok))
    return {"llm_emitidas": llm_total, "llm_certas": llm_certas, "inventada_para_real": inv_para_real, "chamadas": chamadas}


def chamadas_do_log(pasta: Path) -> int | None:
    arq = pasta / "arbitro_estatisticas.log"
    if not arq.exists():
        return None
    try:
        obj = json.loads(arq.read_text(encoding="utf-8"))
        return int(obj.get("chamadas_ao_modelo", 0))
    except (ValueError, TypeError, OSError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arbitro", default="mock", help="mock | transformers | vllm")
    ap.add_argument("--saida", type=Path, default=RAIZ / "saida_arbitro")
    ap.add_argument("--saida-json", type=Path, default=None)
    ap.add_argument("--so", nargs="*", default=None, help="nomes de conjuntos (padrão: todos)")
    ap.add_argument("--gatilhos", nargs="*", default=list(GATILHOS_PADRAO), help="conjuntos em que o score TEM de subir")
    ap.add_argument("--tolerancia", type=float, default=0.0005)
    ap.add_argument("--cache", default=None, help="cache SQLite do árbitro (CACA_CACHE_LLM)")
    ap.add_argument("--calibracao", type=Path, default=DADOS / "calibracao.json")
    ap.add_argument("--janelas", type=int, default=None, help="CACA_LLM_EXTRATOR_JANELAS (padrão do código: 6)")
    args = ap.parse_args()
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    py = sys.executable
    conjuntos = [c for c in conjuntos_disponiveis() if not args.so or c[0] in args.so]
    if not conjuntos:
        print("nenhum conjunto encontrado (rode make sinteticos / make adversarial)", file=sys.stderr)
        return 2
    args.saida.mkdir(parents=True, exist_ok=True)
    env_llm: dict[str, str] = {}
    if args.cache:
        env_llm["CACA_CACHE_LLM"] = str(args.cache)
    if args.janelas is not None:
        env_llm["CACA_LLM_EXTRATOR_JANELAS"] = str(args.janelas)
    linhas: list[dict] = []
    t0 = time.time()
    for nome, txt, gab in conjuntos:
        golds = ler_gabarito(gab)
        res: dict[str, dict] = {}
        for rot, arb in (("nucleo", "nenhum"), ("arbitro", args.arbitro)):
            pasta = args.saida / f"{rot}_{nome}"
            t = time.time()
            r = rodar([py, "-m", "caca_alucinacao.cli", "--input", str(txt), "--output", str(pasta), "--db", str(DADOS / "desafio1_bracis.db"),
                       "--indice", str(DADOS / "indice.json"), "--arbitro", arb, "--calibracao", str(args.calibracao),
                       "--rastro", str(pasta / "rastro.jsonl"), "--log-level", "ERROR"], env_llm if rot == "arbitro" else None)
            dt = time.time() - t
            if r.returncode != 0:
                print(f"ERRO no pipeline ({nome}, {arb}):\n{(r.stdout + r.stderr)[-1500:]}", file=sys.stderr)
                return 2
            extra = [] if nome == "dev" else ["--gabarito", str(gab), "--txt", str(txt), "--sample", "/nonexistent"]
            r2 = rodar([py, "scripts/avaliar.py", "--saida", str(pasta), *extra, "--json", str(pasta) + ".json", "--quieto"])
            if r2.returncode != 0 or not Path(str(pasta) + ".json").exists():
                print(f"ERRO na avaliação ({nome}, {arb}):\n{(r2.stdout + r2.stderr)[-1500:]}", file=sys.stderr)
                return 2
            rel = json.loads(Path(str(pasta) + ".json").read_text(encoding="utf-8"))
            an = analisar_rastro(pasta / "rastro.jsonl", golds)
            an["chamadas"] = chamadas_do_log(pasta) if rot == "arbitro" else 0
            n_docs = len(list(txt.glob("*.txt"))) or 1
            res[rot] = {"score": float(rel["score_final"]), "segundos": dt, "seg_por_doc": dt / n_docs, **an}
        identico = filecmp.dircmp(args.saida / f"nucleo_{nome}", args.saida / f"arbitro_{nome}",
                                  ignore=["rastro.jsonl", "arbitro_estatisticas.log"])
        jsons_iguais = not identico.diff_files and not identico.left_only and not identico.right_only
        linha = {"conjunto": nome, "score_nucleo": res["nucleo"]["score"], "score_arbitro": res["arbitro"]["score"],
                 "delta": res["arbitro"]["score"] - res["nucleo"]["score"],
                 "inv_real_nucleo": res["nucleo"]["inventada_para_real"], "inv_real_arbitro": res["arbitro"]["inventada_para_real"],
                 "llm_emitidas": res["arbitro"]["llm_emitidas"], "llm_certas": res["arbitro"]["llm_certas"],
                 "chamadas": res["arbitro"]["chamadas"], "seg_por_doc_arbitro": res["arbitro"]["seg_por_doc"],
                 "jsons_identicos": jsons_iguais}
        linhas.append(linha)
        print(f"{nome:26s} núcleo={linha['score_nucleo']:.5f} árbitro={linha['score_arbitro']:.5f} Δ={linha['delta']:+.5f} "
              f"inv→real {linha['inv_real_nucleo']}→{linha['inv_real_arbitro']}  LLM emitiu {linha['llm_emitidas']} (certas {linha['llm_certas']})  "
              f"chamadas={linha['chamadas']}  {linha['seg_por_doc_arbitro']:.1f}s/doc{'  =' if jsons_iguais else ''}", flush=True)

    # critério de decisão ------------------------------------------------------------------------
    falhas: list[str] = []
    for ln in linhas:
        if ln["delta"] < -args.tolerancia:
            falhas.append(f"(a) {ln['conjunto']}: score caiu {ln['delta']:+.5f}")
        if ln["inv_real_arbitro"] > ln["inv_real_nucleo"]:
            falhas.append(f"(b) {ln['conjunto']}: inventada→real subiu {ln['inv_real_nucleo']}→{ln['inv_real_arbitro']}")
    for g in args.gatilhos:
        ln = next((x for x in linhas if x["conjunto"] == g), None)
        if ln is None:
            continue
        if g.endswith("distratores"):
            if ln["llm_emitidas"] > 0:
                falhas.append(f"(c) {g}: o extrator emitiu {ln['llm_emitidas']} citação(ões) onde não há nenhuma (precisão)")
        elif ln["delta"] <= 0:
            falhas.append(f"(c) {g}: score não subiu ({ln['delta']:+.5f})")
    dev = next((x for x in linhas if x["conjunto"] == "dev"), None)
    if dev is not None and not dev["jsons_identicos"] and dev["delta"] < 0:
        falhas.append(f"(d) dev mudou e piorou ({dev['delta']:+.5f})")
    total_emitidas = sum(x["llm_emitidas"] for x in linhas)
    total_certas = sum(x["llm_certas"] for x in linhas)
    veredito = "LIGAR" if not falhas else "MANTER DESLIGADO"
    print("=" * 100)
    print(f"árbitro={args.arbitro}  conjuntos={len(linhas)}  extrator emitiu {total_emitidas} citações, {total_certas} certas "
          f"(precisão {total_certas / total_emitidas:.3f})" if total_emitidas else
          f"árbitro={args.arbitro}  conjuntos={len(linhas)}  extrator não emitiu nenhuma citação")
    for f in falhas:
        print("  FALHA", f)
    print(f"VEREDITO: {veredito}  ({time.time() - t0:.0f}s)")
    saida_json = args.saida_json or (args.saida / "comparacao_arbitro.json")
    saida_json.write_text(json.dumps({"arbitro": args.arbitro, "tolerancia": args.tolerancia, "gatilhos": args.gatilhos,
                                      "conjuntos": linhas, "falhas": falhas, "veredito": veredito,
                                      "precisao_extrator": (total_certas / total_emitidas) if total_emitidas else None},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not falhas else 1


if __name__ == "__main__":
    sys.exit(main())
