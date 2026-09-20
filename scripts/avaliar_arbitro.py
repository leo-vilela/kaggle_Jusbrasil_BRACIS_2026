#!/usr/bin/env python3
"""Avalia o árbitro LLM sobre um JSONL de casos sintéticos difíceis.

Uso:
    PYTHONPATH=src python scripts/avaliar_arbitro.py --casos dados/sinteticos/arbitro.jsonl \
        [--arbitro mock|transformers|vllm] [--cache cache/avaliacao.sqlite] [--lote 8] \
        [--saida-json saida/avaliacao_arbitro.json] [-v]

Formato de entrada (uma linha JSON por caso; o gerador de sintéticos é de outro
módulo — este script só define o contrato):

    {"operacao": "normalizar", "trecho": "REsp 1.9SO.OO1/SP", "contexto": "… o REsp 1.9SO.OO1/SP, que …",
     "esperado": {"numero_digitos": "1950001", "classe_cadeia": ["RESP"], "uf": "SP", "tribunal": "STJ", "eh_citacao": true}}

    {"operacao": "escolher", "trecho": "AgInt no REsp 1.777.888/PR", "contexto": "…",
     "candidatos": [{"id_canonico": 11, "cabecalho": "…", "tribunal": "STJ", "ano": 2018, "relator": "…", "cadeia": "AGINT RESP"}, …],
     "esperado": {"indice": 0}}                      # ou {"indice": null} quando o certo é abster-se

    {"operacao": "classificar", "trecho": "n° 2.111.333 (PE)", "contexto": "<janela que contém o trecho>",
     "inicio_rel": 85,                                # opcional: posição do trecho na janela
     "esperado": {"eh_citacao": true, "familia": "processo", "inicio_rel": 78, "fim_rel": 102}}
                                                      # ou {"eh_citacao": false}

``operacao`` pode ser omitida: é inferida (``candidatos`` → escolher; ``esperado.familia``
ou ``esperado.eh_citacao`` sem ``numero_digitos`` → classificar; senão normalizar).
Campos extras (``id``, ``nivel``, ``nota``) são ignorados e devolvidos no relatório.

Métricas por operação: n, respondidos (não-None), abstenções, acertos plenos, acurácia
(acertos/n), precisão (acertos/respondidos), tempo médio por caso e, para
``classificar``, a taxa de IoU ≥ 0,5 (critério de alinhamento da métrica oficial).
Para ``normalizar`` conta-se também o erro crítico "dígitos diferentes do esperado"
(um número errado pode virar ``inventada→real`` na reconsulta).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.normalizacao import classificar_digitos  # noqa: E402
from caca_alucinacao.llm import CacheLLM, ErroDependencia, obter_arbitro  # noqa: E402
from caca_alucinacao.tipos import iou  # noqa: E402

logger = logging.getLogger("avaliar_arbitro")


#: Nomes gravados pelo gerador (``casos_llm.jsonl``) → nomes curtos do laço de avaliação (R3e-03).
OPERACOES = {"classificar_span": "classificar", "normalizar_citacao": "normalizar", "escolher_candidato": "escolher",
             "classificar": "classificar", "normalizar": "normalizar", "escolher": "escolher"}


class OperacaoDesconhecida(ValueError):
    pass


def inferir_operacao(caso: dict[str, Any]) -> str:
    if caso.get("operacao"):
        nome = str(caso["operacao"])
        if nome not in OPERACOES:
            raise OperacaoDesconhecida(f"operação desconhecida no caso: {nome!r} (aceitas: {sorted(OPERACOES)})")
        return OPERACOES[nome]
    if "candidatos" in caso:
        return "escolher"
    esp = caso.get("esperado") or {}
    if "familia" in esp or ("eh_citacao" in esp and "numero_digitos" not in esp):
        return "classificar"
    return "normalizar"


def carregar_casos(caminho: Path) -> list[dict[str, Any]]:
    casos = []
    with caminho.open("r", encoding="utf-8") as f:
        for n, linha in enumerate(f, 1):
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            try:
                caso = json.loads(linha)
            except json.JSONDecodeError as e:
                raise SystemExit(f"{caminho}:{n}: JSON inválido ({e})") from e
            for campo in ("trecho", "contexto", "esperado"):
                if campo not in caso:
                    raise SystemExit(f"{caminho}:{n}: campo obrigatório ausente: {campo}")
            try:
                caso["operacao"] = inferir_operacao(caso)
            except OperacaoDesconhecida as e:
                raise SystemExit(f"{caminho}:{n}: {e}") from e
            caso.setdefault("id", f"linha{n}")
            casos.append(caso)
    return casos


def _canon(digitos: str | None) -> str:
    d = "".join(c for c in str(digitos or "") if c.isdigit())
    return classificar_digitos(d)[0] if d else ""


def avaliar_normalizar(esp: dict[str, Any], obtido: dict[str, Any] | None) -> dict[str, Any]:
    if obtido is None:
        return {"acerto": False, "abstencao": True, "digitos_errados": False}
    ok_digitos = _canon(esp.get("numero_digitos")) == _canon(obtido.get("numero_digitos"))
    ok_eh = ("eh_citacao" not in esp) or bool(esp["eh_citacao"]) == bool(obtido.get("eh_citacao"))
    ok_cadeia = ("classe_cadeia" not in esp) or [s.upper() for s in esp["classe_cadeia"]] == obtido.get("classe_cadeia")
    ok_uf = ("uf" not in esp) or esp["uf"] == obtido.get("uf")
    ok_trib = ("tribunal" not in esp) or esp["tribunal"] == obtido.get("tribunal")
    return {
        "acerto": ok_digitos and ok_eh and ok_cadeia and ok_uf and ok_trib, "abstencao": False,
        "digitos_errados": bool(obtido.get("eh_citacao")) and not ok_digitos,
        "sub": {"digitos": ok_digitos, "eh_citacao": ok_eh, "cadeia": ok_cadeia, "uf": ok_uf, "tribunal": ok_trib},
    }


def avaliar_escolher(esp: dict[str, Any], obtido: int | None) -> dict[str, Any]:
    alvo = esp.get("indice")
    return {"acerto": alvo == obtido, "abstencao": obtido is None,
            "escolha_errada": obtido is not None and alvo is not None and alvo != obtido,
            "chute_indevido": obtido is not None and alvo is None}


def avaliar_classificar(esp: dict[str, Any], obtido: dict[str, Any] | None) -> dict[str, Any]:
    if obtido is None:
        return {"acerto": False, "abstencao": True, "iou_ok": False}
    ok_eh = bool(esp.get("eh_citacao", True)) == bool(obtido["eh_citacao"])
    if not esp.get("eh_citacao", True):
        return {"acerto": ok_eh, "abstencao": False, "iou_ok": ok_eh}
    ok_fam = ("familia" not in esp) or esp["familia"] == obtido["familia"]
    tem_span = "inicio_rel" in esp and "fim_rel" in esp
    ok_span = (not tem_span) or (esp["inicio_rel"], esp["fim_rel"]) == (obtido["inicio_rel"], obtido["fim_rel"])
    v = iou(esp["inicio_rel"], esp["fim_rel"], obtido["inicio_rel"], obtido["fim_rel"]) if tem_span else 1.0
    return {"acerto": ok_eh and ok_fam and ok_span, "abstencao": False,
            "iou_ok": ok_eh and ok_fam and v >= 0.5, "iou": round(v, 3),
            "sub": {"eh_citacao": ok_eh, "familia": ok_fam, "span": ok_span}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--casos", type=Path, required=True, help="JSONL de casos sintéticos")
    ap.add_argument("--arbitro", default="mock", help="mock | transformers | vllm")
    ap.add_argument("--cache", default=None, help="caminho do cache SQLite (padrão: CACA_CACHE_LLM / memória p/ mock)")
    ap.add_argument("--lote", type=int, default=8, help="casos por chamada em lote")
    ap.add_argument("--saida-json", type=Path, default=None, help="relatório detalhado em JSON")
    ap.add_argument("--exportar-cache", type=Path, default=None, help="exporta o cache em JSONL ao final")
    ap.add_argument("-v", "--verbose", action="store_true", help="imprime cada erro/abstenção")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    casos = carregar_casos(args.casos)
    if not casos:
        print("nenhum caso", file=sys.stderr)
        return 2
    cfg: dict[str, Any] = {}
    if args.cache is not None:
        cfg["cache"] = CacheLLM(args.cache)
    try:
        arbitro = obter_arbitro(args.arbitro, **cfg)
    except ErroDependencia as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    if arbitro is None:
        print("--arbitro nenhum não avalia nada", file=sys.stderr)
        return 2

    por_op: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in casos:
        por_op[c["operacao"]].append(c)

    relatorio: dict[str, Any] = {"arbitro": arbitro.estatisticas(), "operacoes": {}, "casos": []}
    t_inicio = time.perf_counter()
    for op in ("normalizar", "escolher", "classificar"):
        lista = por_op.get(op, [])
        if not lista:
            continue
        resultados: list[Any] = []
        tempos: list[float] = []
        for k in range(0, len(lista), max(1, args.lote)):
            bloco = lista[k:k + max(1, args.lote)]
            if op == "normalizar":
                entradas = [(c["trecho"], c["contexto"]) for c in bloco]
            elif op == "escolher":
                entradas = [(c["trecho"], c["contexto"], c["candidatos"]) for c in bloco]
            else:
                entradas = [(c["trecho"], c["contexto"], c.get("inicio_rel")) for c in bloco]
            t0 = time.perf_counter()
            resultados.extend(arbitro.executar_lote(op, entradas))
            dt = (time.perf_counter() - t0) / len(bloco)
            tempos.extend([dt] * len(bloco))
        agreg: dict[str, float] = defaultdict(float)
        for caso, obtido, dt in zip(lista, resultados, tempos):
            esp = caso["esperado"]
            if op == "normalizar":
                aval = avaliar_normalizar(esp, obtido)
            elif op == "escolher":
                aval = avaliar_escolher(esp, obtido)
            else:
                aval = avaliar_classificar(esp, obtido)
            agreg["n"] += 1
            agreg["acertos"] += aval["acerto"]
            agreg["abstencoes"] += aval["abstencao"]
            agreg["respondidos"] += not aval["abstencao"]
            agreg["acertos_respondidos"] += aval["acerto"] and not aval["abstencao"]
            for extra in ("digitos_errados", "escolha_errada", "chute_indevido", "iou_ok"):
                if extra in aval:
                    agreg[extra] += bool(aval[extra])
            agreg["tempo_total"] += dt
            relatorio["casos"].append({"id": caso.get("id"), "operacao": op, "nivel": caso.get("nivel"),
                                       "esperado": esp, "obtido": obtido, "avaliacao": aval, "segundos": round(dt, 3)})
            if args.verbose and not aval["acerto"]:
                print(f"  [{op}] {caso.get('id')}: esperado={json.dumps(esp, ensure_ascii=False)} "
                      f"obtido={json.dumps(obtido, ensure_ascii=False)}")
        n = agreg["n"]
        resumo = {
            "n": int(n), "respondidos": int(agreg["respondidos"]), "abstencoes": int(agreg["abstencoes"]),
            "acertos": int(agreg["acertos"]),
            "acuracia": round(agreg["acertos"] / n, 4),
            "precisao_respondidos": (round(agreg["acertos_respondidos"] / agreg["respondidos"], 4)
                                     if agreg["respondidos"] else None),
            "segundos_por_caso": round(agreg["tempo_total"] / n, 3),
        }
        if op == "normalizar":
            resumo["digitos_errados"] = int(agreg["digitos_errados"])
        if op == "escolher":
            resumo["escolhas_erradas"] = int(agreg["escolha_errada"])
            resumo["chutes_indevidos"] = int(agreg["chute_indevido"])
        if op == "classificar":
            resumo["taxa_iou_ok"] = round(agreg["iou_ok"] / n, 4)
        relatorio["operacoes"][op] = resumo

    relatorio["segundos_total"] = round(time.perf_counter() - t_inicio, 2)
    relatorio["arbitro"] = arbitro.estatisticas()

    print(f"árbitro: {arbitro.nome} (modelo={arbitro.modelo}, rev={arbitro.revisao or '?'}, "
          f"prompt={relatorio['arbitro']['prompt_versao']})")
    print(f"{'operação':<12}{'n':>5}{'resp.':>7}{'abst.':>7}{'acertos':>9}{'acur.':>8}{'prec.':>8}{'s/caso':>8}  extras")
    for op, r in relatorio["operacoes"].items():
        extras = {k: v for k, v in r.items() if k in ("digitos_errados", "escolhas_erradas", "chutes_indevidos", "taxa_iou_ok")}
        prec = "-" if r["precisao_respondidos"] is None else f"{r['precisao_respondidos']:.3f}"
        print(f"{op:<12}{r['n']:>5}{r['respondidos']:>7}{r['abstencoes']:>7}{r['acertos']:>9}"
              f"{r['acuracia']:>8.3f}{prec:>8}{r['segundos_por_caso']:>8.3f}  {extras}")
    print(f"total: {relatorio['segundos_total']} s; chamadas ao modelo: {relatorio['arbitro']['chamadas_ao_modelo']}; "
          f"cache: {relatorio['arbitro']['cache']}")

    if args.saida_json:
        args.saida_json.parent.mkdir(parents=True, exist_ok=True)
        args.saida_json.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"relatório: {args.saida_json}")
    if args.exportar_cache and arbitro.cache is not None:
        n = arbitro.cache.exportar_jsonl(args.exportar_cache)
        print(f"cache exportado: {args.exportar_cache} ({n} respostas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
