#!/usr/bin/env python3
"""Avalia uma pasta de JSONs (schema 1.2) contra o gabarito com a métrica OFICIAL.

Uso:
    python scripts/avaliar.py --saida saida/ [--gabarito dados/goldenset.csv]
                              [--sample dados/sample_submission.csv] [--txt dados/txt]
                              [--rastro saida/rastro.jsonl] [--json relatorio.json] [--quieto]
    python scripts/avaliar.py --sanidade      # prova que reproduz o oficial (1.1000 / 1.0000 / 0.0)

O ``kaggle_metric.py`` e o ``json_to_submission.py`` da organização são importados
de ``dados/ferramentas/`` (nunca copiados). O score impresso é o do oficial; o
DIAGNÓSTICO (matriz de confusão, lista de erros por documento, inventada→real,
acurácia por caminho de decisão) é uma reimplementação do alinhamento com as
mesmas regras (IoU ≥ 0,5 guloso por maior IoU, regra EXTRA ≥ 90 %) e é conferido
contra o oficial nos testes (``tests/test_avaliar.py``). Nunca imprime trechos.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any

# um documento com milhares de citações gera uma célula ``citacoes`` maior que o limite
# padrão do módulo csv (131072); o conversor oficial escreve e o kaggle_metric (pandas) lê
# sem problema, então a validação local não pode abortar aí (rodada 3, R3e-04)
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.config import DADOS, FERRAMENTAS  # noqa: E402
from caca_alucinacao.contrato import validar_arquivo  # noqa: E402
from caca_alucinacao.tipos import CLASSIFICACOES, iou  # noqa: E402

IOU_MIN = 0.5
FRAC_EXTRA = 0.9
SEM_PAR = "(sem par)"


# ---------------------------------------------------------------------------
# Scripts oficiais
# ---------------------------------------------------------------------------
_MODULOS_OFICIAIS: dict[Path, ModuleType] = {}


def importar_oficial(nome: str, pasta: Path = FERRAMENTAS) -> ModuleType:
    """Importa ``<pasta>/<nome>.py`` pelo caminho (sem copiar o arquivo); uma vez por caminho.

    O cache garante que ``ParticipantVisibleError`` seja a mesma classe em todos
    os pontos que a capturam.
    """
    caminho = (pasta / f"{nome}.py").resolve()
    if caminho in _MODULOS_OFICIAIS:
        return _MODULOS_OFICIAIS[caminho]
    if not caminho.exists():
        raise FileNotFoundError(f"script oficial ausente: {caminho} (rode scripts/preparar_dados.py)")
    spec = importlib.util.spec_from_file_location(f"oficial_{nome}", caminho)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    _MODULOS_OFICIAIS[caminho] = modulo
    return modulo


# ---------------------------------------------------------------------------
# Gabarito e submissão
# ---------------------------------------------------------------------------
def nivel_do_documento(documento_id: str) -> int:
    """``gen_n2_003`` → 2; qualquer outro → 1."""
    partes = documento_id.lower().split("_")
    return 2 if "n2" in partes else 1


def norm_id(v: Any) -> str:
    """Mesma normalização do oficial (``_norm_id``): zeros à esquerda não contam."""
    v = str(v).strip()
    return (v.lstrip("0") or "0") if v.isdigit() else v


def ler_goldenset(caminho: Path) -> list[dict[str, Any]]:
    """Linhas do ``goldenset.csv`` (BOM → ``utf-8-sig``; ``\\n`` literal desescapado no trecho)."""
    with Path(caminho).open(encoding="utf-8-sig", newline="") as f:
        linhas = []
        for r in csv.DictReader(f):
            linhas.append({
                "nivel": int(r["nivel"]),
                "documento_id": r["documento_id"].strip(),
                "citacao_id": r.get("citacao_id", "").strip(),
                "inicio": int(r["inicio"]),
                "fim": int(r["fim"]),
                "trecho": (r.get("trecho") or "").replace("\\n", "\n"),
                "tipo": (r.get("tipo") or "").strip(),
                "classificacao": r["classificacao"].strip().lower(),
                "id_canonico": (r.get("id_canonico") or "").strip(),
            })
    return linhas


def ler_sample(caminho: Path | None) -> list[str]:
    if caminho is None or not Path(caminho).exists():
        return []
    with Path(caminho).open(encoding="utf-8-sig", newline="") as f:
        return [r["documento_id"].strip() for r in csv.DictReader(f) if r.get("documento_id")]


def documentos_do_gabarito(linhas: list[dict[str, Any]], extras: list[str] = ()) -> dict[str, int]:
    """``{documento_id: nivel}`` em ordem determinística (gabarito ∪ sample)."""
    niveis: dict[str, int] = {}
    for r in linhas:
        niveis[r["documento_id"]] = r["nivel"]
    for d in extras:
        niveis.setdefault(d, nivel_do_documento(d))
    return dict(sorted(niveis.items()))


def celula_solution(citacoes: list[dict[str, Any]]) -> str:
    partes = []
    for c in sorted(citacoes, key=lambda x: (x["inicio"], x["fim"])):
        doc_ids = c["id_canonico"] or "-"
        partes.append(f"{c['inicio']},{c['fim']},{c['classificacao']},{doc_ids}")
    return "|".join(partes) if partes else "-"


def montar_solution(linhas: list[dict[str, Any]], extras: list[str] = ()) -> Any:
    """DataFrame ``documento_id, nivel, citacoes`` no formato que a métrica espera."""
    import pandas as pd

    por_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in linhas:
        por_doc[r["documento_id"]].append(r)
    niveis = documentos_do_gabarito(linhas, extras)
    registros = [
        {"documento_id": d, "nivel": n, "citacoes": celula_solution(por_doc.get(d, []))}
        for d, n in niveis.items()
    ]
    return pd.DataFrame(registros, columns=["documento_id", "nivel", "citacoes"])


def montar_submission(pasta: Path, documento_ids: list[str], encode: Any,
                      preencher_ausentes: bool = True) -> tuple[Any, list[str]]:
    """DataFrame ``documento_id, citacoes`` via ``encode()`` oficial; devolve também os ausentes."""
    import pandas as pd

    pasta = Path(pasta)
    registros, ausentes = [], []
    for d in documento_ids:
        arq = pasta / f"{d}.json"
        if arq.exists():
            doc = json.loads(arq.read_text(encoding="utf-8"))
            registros.append({"documento_id": d, "citacoes": encode(doc)})
        else:
            ausentes.append(d)
            if preencher_ausentes:
                registros.append({"documento_id": d, "citacoes": "-"})
    return pd.DataFrame(registros, columns=["documento_id", "citacoes"]), ausentes


def gabarito_para_jsons(linhas: list[dict[str, Any]], pasta: Path, documento_ids: list[str] = (),
                        confianca: float | None = 1.0, trocar: dict[str, str] | None = None) -> list[Path]:
    """Escreve a submissão "perfeita" derivada do gabarito (para sanidade e testes).

    ``trocar`` mapeia ``documento_id:citacao_id`` → nova classificação (uma
    ``inventada`` trocada por ``real`` recebe o id ``"1"``, que não existe).
    """
    from caca_alucinacao.contrato import Citacao, SaidaDocumento

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    por_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in linhas:
        por_doc[r["documento_id"]].append(r)
    escritos = []
    for d in sorted(set(por_doc) | set(documento_ids)):
        cits = []
        for r in por_doc.get(d, []):
            classe = (trocar or {}).get(f"{d}:{r['citacao_id']}", r["classificacao"])
            idc = r["id_canonico"] or None
            if classe == "real" and not idc:
                idc = "1"
            if classe != "real":
                idc = None
            cits.append(Citacao(id="c?", inicio=r["inicio"], fim=r["fim"],
                                trecho=r["trecho"] or "?" * (r["fim"] - r["inicio"]),
                                tipo=r["tipo"] or "jurisprudencia", classificacao=classe,
                                id_canonico=idc, confianca=confianca))
        escritos.append(SaidaDocumento.montar(d, cits).escrever(pasta / f"{d}.json"))
    return escritos


# ---------------------------------------------------------------------------
# Alinhamento (reimplementação com as regras da métrica)
# ---------------------------------------------------------------------------
def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    return iou(a["inicio"], a["fim"], b["inicio"], b["fim"])


def _contida(p: dict[str, Any], g: dict[str, Any], frac: float = FRAC_EXTRA) -> bool:
    largura = p["fim"] - p["inicio"]
    inter = max(0, min(p["fim"], g["fim"]) - max(p["inicio"], g["inicio"]))
    return largura > 0 and inter / largura >= frac


def alinhar(golds: list[dict[str, Any]], preds: list[dict[str, Any]]
            ) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Matching 1-para-1 guloso por maior IoU (IoU ≥ 0,5), desempate por índices."""
    candidatos = []
    for gi, g in enumerate(golds):
        for pi, p in enumerate(preds):
            v = _iou(g, p)
            if v >= IOU_MIN:
                candidatos.append((-v, gi, pi))
    candidatos.sort()
    g_usado: set[int] = set()
    p_usado: set[int] = set()
    pares: list[tuple[int, int, float]] = []
    for nv, gi, pi in candidatos:
        if gi in g_usado or pi in p_usado:
            continue
        g_usado.add(gi)
        p_usado.add(pi)
        pares.append((gi, pi, -nv))
    return (pares, [i for i in range(len(golds)) if i not in g_usado],
            [i for i in range(len(preds)) if i not in p_usado])


def _novo_nivel() -> dict[str, Any]:
    return {
        "tp": {c: 0 for c in CLASSIFICACOES},
        "fp": {c: 0 for c in CLASSIFICACOES},
        "fn": {c: 0 for c in CLASSIFICACOES},
        "suporte": {c: 0 for c in CLASSIFICACOES},
        "matriz": {e: {o: 0 for o in (*CLASSIFICACOES, SEM_PAR)} for e in (*CLASSIFICACOES, SEM_PAR)},
        "id_errado": 0, "extra_ignorado": 0, "tau_num": 0, "tau_den": 0,
        "brier_termos": [], "conf_acertos": [], "conf_erros": [],
    }


def diagnosticar(golds_por_doc: dict[str, list[dict[str, Any]]],
                 preds_por_doc: dict[str, list[dict[str, Any]]],
                 niveis: dict[str, int],
                 caminhos: dict[tuple[str, int, int], str] | None = None) -> dict[str, Any]:
    """Matriz de confusão, erros por documento e estatísticas por caminho."""
    por_nivel: dict[int, dict[str, Any]] = {}
    erros: list[dict[str, Any]] = []
    por_caminho: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "acertos": 0, "brier_termos": []})

    def registrar_caminho(doc: str, p: dict[str, Any], y: int) -> None:
        if caminhos is None:
            return
        cam = caminhos.get((doc, p["inicio"], p["fim"]))
        if cam is None:
            return
        e = por_caminho[cam]
        e["n"] += 1
        e["acertos"] += y
        if p.get("confianca") is not None:
            e["brier_termos"].append((p["confianca"] - y) ** 2)

    for doc in sorted(niveis):
        nivel = niveis[doc]
        acc = por_nivel.setdefault(nivel, _novo_nivel())
        golds = golds_por_doc.get(doc, [])
        preds = preds_por_doc.get(doc, [])
        pares, g_sem, p_sem = alinhar(golds, preds)
        for g in golds:
            acc["suporte"][g["classe"]] += 1
            if g["classe"] == "inventada":
                acc["tau_den"] += 1

        def erro(tipo: str, g: dict[str, Any] | None, p: dict[str, Any] | None, v: float | None,
                 grave: bool = False) -> None:
            erros.append({
                "documento_id": doc, "nivel": nivel, "tipo": tipo,
                "gold_id": g.get("citacao_id") if g else None,
                "gold_span": [g["inicio"], g["fim"]] if g else None,
                "pred_span": [p["inicio"], p["fim"]] if p else None,
                "iou": None if v is None else round(v, 3),
                "esperado": g["classe"] if g else None,
                "obtido": p["classe"] if p else None,
                "id_esperado": sorted(g["doc_ids"]) if g else None,
                "id_obtido": p.get("id_canonico") if p else None,
                "confianca": p.get("confianca") if p else None,
                "grave": grave,
            })

        for gi, pi, v in pares:
            g, p = golds[gi], preds[pi]
            cg, cp = g["classe"], p["classe"]
            acc["matriz"][cg][cp] += 1
            if cg == cp:
                if cg == "real" and p["id_canonico"] not in g["doc_ids"]:
                    acc["fp"]["real"] += 1
                    acc["id_errado"] += 1
                    y = 0
                    erro("id_errado", g, p, v)
                else:
                    acc["tp"][cg] += 1
                    y = 1
            else:
                acc["fn"][cg] += 1
                acc["fp"][cp] += 1
                y = 0
                grave = cg == "inventada" and cp == "real"
                if grave:
                    acc["tau_num"] += 1
                erro("classe_errada", g, p, v, grave)
            if p.get("confianca") is not None:
                acc["brier_termos"].append((p["confianca"] - y) ** 2)
                (acc["conf_acertos"] if y else acc["conf_erros"]).append(p["confianca"])
            registrar_caminho(doc, p, y)

        for gi in g_sem:
            g = golds[gi]
            acc["fn"][g["classe"]] += 1
            acc["matriz"][g["classe"]][SEM_PAR] += 1
            erro("span_nao_detectado", g, None, None)

        casados = [golds[gi] for gi, _, _ in pares]
        for pi in p_sem:
            p = preds[pi]
            if any(_contida(p, g) for g in casados):
                acc["extra_ignorado"] += 1
                erro("extra_ignorado", None, p, None)
                continue
            acc["fp"][p["classe"]] += 1
            acc["matriz"][SEM_PAR][p["classe"]] += 1
            erro("span_espurio", None, p, None)
            registrar_caminho(doc, p, 0)

    resumo_niveis: dict[int, dict[str, Any]] = {}
    for nivel, acc in sorted(por_nivel.items()):
        f1s = {}
        for c in CLASSIFICACOES:
            if acc["suporte"][c] == 0:
                continue
            tp, fp, fn = acc["tp"][c], acc["fp"][c], acc["fn"][c]
            denom = 2 * tp + fp + fn
            f1s[c] = (2 * tp / denom) if denom > 0 else 0.0
        macro = sum(f1s.values()) / len(f1s) if f1s else None
        tau = acc["tau_num"] / acc["tau_den"] if acc["tau_den"] else 0.0
        brier = (sum(acc["brier_termos"]) / len(acc["brier_termos"])) if acc["brier_termos"] else None
        resumo_niveis[nivel] = {
            "tp": acc["tp"], "fp": acc["fp"], "fn": acc["fn"], "suporte": acc["suporte"],
            "f1_por_classe": f1s, "macro_f1": macro, "tau": tau,
            "tau_num": acc["tau_num"], "tau_den": acc["tau_den"],
            "brier": brier, "n_com_confianca": len(acc["brier_termos"]),
            "conf_media_acertos": (sum(acc["conf_acertos"]) / len(acc["conf_acertos"])) if acc["conf_acertos"] else None,
            "conf_media_erros": (sum(acc["conf_erros"]) / len(acc["conf_erros"])) if acc["conf_erros"] else None,
            "id_errado": acc["id_errado"], "extra_ignorado": acc["extra_ignorado"],
            "matriz": acc["matriz"],
        }
    for cam, e in por_caminho.items():
        e["acuracia"] = e["acertos"] / e["n"] if e["n"] else None
        e["brier"] = (sum(e["brier_termos"]) / len(e["brier_termos"])) if e["brier_termos"] else None
        del e["brier_termos"]
    return {
        "niveis": resumo_niveis,
        "erros": erros,
        "graves": [e for e in erros if e["grave"]],
        "por_caminho": dict(sorted(por_caminho.items())),
    }


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def ler_rastro(caminho: Path | None) -> dict[tuple[str, int, int], str] | None:
    if caminho is None or not Path(caminho).exists():
        return None
    mapa: dict[tuple[str, int, int], str] = {}
    with Path(caminho).open(encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            r = json.loads(linha)
            if r.get("status") == "emitida" and r.get("caminho"):
                mapa[(r["documento_id"], int(r["inicio"]), int(r["fim"]))] = str(r["caminho"])
    return mapa


def avaliar_pasta(pasta: Path, gabarito: Path, sample: Path | None = None,
                  rastro: Path | None = None, txt: Path | None = None,
                  preencher_ausentes: bool = True) -> dict[str, Any]:
    """Score oficial + diagnóstico. Levanta ``ParticipantVisibleError`` se a submissão for inválida."""
    metrica = importar_oficial("kaggle_metric")
    conversor = importar_oficial("json_to_submission")
    linhas = ler_goldenset(gabarito)
    extras = ler_sample(sample)
    solution = montar_solution(linhas, extras)
    documentos = list(solution["documento_id"])
    submission, ausentes = montar_submission(pasta, documentos, conversor.encode, preencher_ausentes)

    oficial = metrica.avaliar(solution, submission, row_id="documento_id")

    niveis = documentos_do_gabarito(linhas, extras)
    golds_por_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in linhas:
        golds_por_doc[r["documento_id"]].append({
            "inicio": r["inicio"], "fim": r["fim"], "classe": r["classificacao"],
            "doc_ids": frozenset(norm_id(x) for x in r["id_canonico"].split(":") if x.strip() not in ("", "-")),
            "citacao_id": r["citacao_id"],
        })
    preds_por_doc: dict[str, list[dict[str, Any]]] = {}
    for _, linha in submission.iterrows():
        preds_por_doc[linha["documento_id"]] = metrica._parse_submission_cell(linha["citacoes"], linha["documento_id"])
    diag = diagnosticar(golds_por_doc, preds_por_doc, niveis, ler_rastro(rastro))

    contrato: dict[str, list[str]] = {}
    for d in documentos:
        arq = Path(pasta) / f"{d}.json"
        if not arq.exists():
            continue
        texto = None
        if txt is not None and (Path(txt) / f"{d}.txt").exists():
            texto = (Path(txt) / f"{d}.txt").read_bytes().decode("utf-8")
        e = validar_arquivo(arq, texto)
        if e:
            contrato[d] = e

    niveis_saida: dict[int, dict[str, Any]] = {}
    for n, r in oficial["niveis"].items():  # valores oficiais prevalecem; o diagnóstico só acrescenta
        d = diag["niveis"].get(int(n), {})
        niveis_saida[int(n)] = {**d, **r, "macro_f1_diagnostico": d.get("macro_f1"), "tau_diagnostico": d.get("tau")}
    return {
        "score_final": oficial["score_final"],
        "niveis": niveis_saida,
        "ausentes": ausentes,
        "erros": diag["erros"],
        "graves": diag["graves"],
        "por_caminho": diag["por_caminho"],
        "erros_contrato": contrato,
        "n_documentos": len(documentos),
        "n_gabarito": len(linhas),
    }


def formatar_relatorio(r: dict[str, Any], detalhar_erros: bool = True) -> str:
    linhas = [f"score_final = {r['score_final']:.5f}   (máximo 1.10000; {r['n_documentos']} docs, "
              f"{r['n_gabarito']} citações no gabarito)"]
    if r["ausentes"]:
        linhas.append(f"AVISO: {len(r['ausentes'])} documento(s) sem JSON, preenchidos com '-' "
                      f"(a métrica oficial REJEITARIA a submissão): {', '.join(r['ausentes'][:5])}")
    for n, d in sorted(r["niveis"].items()):
        f1 = "  ".join(f"{c}={v:.4f}" for c, v in d["f1_por_classe"].items())
        brier = "-" if d.get("brier") is None else f"{d['brier']:.4f}"
        linhas.append(f"\nNível {n}: score={d['score']:.5f}  macroF1={d['macro_f1']:.4f}  "
                      f"tau={d['tau']:.4f} ({d.get('tau_num', 0)}/{d.get('tau_den', 0)})  "
                      f"s={d['s']:.4f}  brier={brier} (n={d.get('n_com_confianca', 0)})  bônus={d['b']:.4f}")
        linhas.append(f"  F1 por classe: {f1}")
        linhas.append("  " + "  ".join(f"{c}: tp={d['tp'][c]} fp={d['fp'][c]} fn={d['fn'][c]} "
                                        f"sup={d['suporte'][c]}" for c in CLASSIFICACOES))
        if d.get("conf_media_acertos") is not None or d.get("conf_media_erros") is not None:
            ca = d.get("conf_media_acertos")
            ce = d.get("conf_media_erros")
            linhas.append(f"  confiança média: acertos={'-' if ca is None else f'{ca:.3f}'}  "
                          f"erros={'-' if ce is None else f'{ce:.3f}'}  "
                          f"id_errado={d.get('id_errado', 0)}  extra_ignorado={d.get('extra_ignorado', 0)}")
        m = d.get("matriz")
        if m:
            cols = (*CLASSIFICACOES, SEM_PAR)
            linhas.append("  matriz (linha=esperado, coluna=obtido):")
            linhas.append("    " + f"{'':12}" + "".join(f"{c:>12}" for c in cols))
            for e in cols:
                linhas.append("    " + f"{e:12}" + "".join(f"{m[e][o]:>12}" for o in cols))
    if r["por_caminho"]:
        linhas.append("\nPor caminho de decisão (citações emitidas):")
        for cam, e in r["por_caminho"].items():
            acc = "-" if e["acuracia"] is None else f"{e['acuracia']:.3f}"
            br = "-" if e["brier"] is None else f"{e['brier']:.3f}"
            linhas.append(f"  {cam:45} n={e['n']:4d} acurácia={acc} brier={br}")
    graves = r["graves"]
    linhas.append(f"\ninventada→real (erro grave, τ): {len(graves)}")
    for e in graves:
        linhas.append(f"  {e['documento_id']} {e['gold_id']} span={e['gold_span']} id_obtido={e['id_obtido']} "
                      f"conf={e['confianca']}")
    erros = [e for e in r["erros"] if e["tipo"] != "extra_ignorado"]
    linhas.append(f"\nErros: {len(erros)} (extra ignorados: {len(r['erros']) - len(erros)})")
    if detalhar_erros:
        por_tipo: dict[str, int] = defaultdict(int)
        for e in erros:
            por_tipo[e["tipo"]] += 1
        linhas.append("  por tipo: " + ", ".join(f"{k}={v}" for k, v in sorted(por_tipo.items())))
        for e in erros:
            g = f"gold={e['gold_id']}{e['gold_span']}" if e["gold_span"] else "gold=-"
            p = f"pred={e['pred_span']}" if e["pred_span"] else "pred=-"
            ids = ""
            if e["tipo"] == "id_errado":
                ids = f" id_esperado={e['id_esperado']} id_obtido={e['id_obtido']}"
            linhas.append(f"  [{e['documento_id']}] {e['tipo']:18} {g} {p} esperado={e['esperado']} "
                          f"obtido={e['obtido']}{ids} conf={e['confianca']}")
    if r["erros_contrato"]:
        linhas.append(f"\nViolações do contrato em {len(r['erros_contrato'])} documento(s):")
        for d, es in r["erros_contrato"].items():
            for e in es[:5]:
                linhas.append(f"  [{d}] {e}")
    return "\n".join(linhas)


def sanidade(gabarito: Path, sample: Path | None) -> dict[str, float]:
    """Submissões derivadas do gabarito: perfeita c/ conf 1.0 → 1.1; sem conf → 1.0; vazia → 0.0."""
    linhas = ler_goldenset(gabarito)
    extras = ler_sample(sample)
    docs = list(documentos_do_gabarito(linhas, extras))
    resultados = {}
    with tempfile.TemporaryDirectory() as tmp:
        for nome, conf, vazia in (("perfeita_conf_1.0", 1.0, False), ("perfeita_sem_conf", None, False),
                                  ("vazia", None, True)):
            pasta = Path(tmp) / nome
            gabarito_para_jsons([] if vazia else linhas, pasta, docs, confianca=conf)
            resultados[nome] = avaliar_pasta(pasta, gabarito, sample)["score_final"]
    return resultados


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", type=Path, default=RAIZ / "saida", help="pasta com os JSONs")
    ap.add_argument("--gabarito", type=Path, default=DADOS / "goldenset.csv")
    ap.add_argument("--sample", type=Path, default=None,
                    help="sample_submission.csv cujos ids entram na contagem de documentos; por padrão só "
                         "quando o gabarito é o oficial (dados/goldenset.csv) — revisão R3-10")
    ap.add_argument("--txt", type=Path, default=DADOS / "txt", help="pasta dos .txt (confere trechos)")
    ap.add_argument("--rastro", type=Path, default=None, help="rastro.jsonl do pipeline (estatísticas por caminho)")
    ap.add_argument("--json", type=Path, default=None, help="grava o relatório completo em JSON")
    ap.add_argument("--quieto", action="store_true", help="não lista os erros um a um")
    ap.add_argument("--estrito", action="store_true", help="documento sem JSON = erro (como o oficial)")
    ap.add_argument("--sanidade", action="store_true", help="só confere que a avaliação reproduz o oficial")
    args = ap.parse_args(argv)
    if args.sample is None and args.gabarito.resolve() == (DADOS / "goldenset.csv").resolve():
        args.sample = DADOS / "sample_submission.csv"

    if args.sanidade:
        r = sanidade(args.gabarito, args.sample)
        for k, v in r.items():
            print(f"{k:22} score_final = {v:.5f}")
        ok = abs(r["perfeita_conf_1.0"] - 1.1) < 1e-9 and abs(r["perfeita_sem_conf"] - 1.0) < 1e-9 and r["vazia"] == 0.0
        print("OK: reproduz o oficial" if ok else "FALHA: valores inesperados")
        return 0 if ok else 1

    if not args.saida.is_dir():
        print(f"pasta de saída inexistente: {args.saida}", file=sys.stderr)
        return 2
    try:
        r = avaliar_pasta(args.saida, args.gabarito, args.sample, args.rastro,
                          args.txt if args.txt.is_dir() else None, preencher_ausentes=not args.estrito)
    except Exception as exc:
        print(f"SUBMISSÃO INVÁLIDA ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    print(formatar_relatorio(r, detalhar_erros=not args.quieto))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nrelatório JSON em {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
