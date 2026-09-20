#!/usr/bin/env python3
"""Conjunto cego em um comando: núcleo e núcleo + árbitro, dois CSVs prontos para o Kaggle (README §5).

    python scripts/rodar_cego.py                                   # dados/cego/txt → saida_cego/, saida_cego_llm/
    python scripts/rodar_cego.py --entrada /caminho/txt --sample /caminho/sample_submission.csv
    python scripts/rodar_cego.py --sem-arbitro                     # só o núcleo (sem GPU)
    python scripts/rodar_cego.py --modelo /opt/bracis/models/qwen35_9b   # snapshot local dos pesos (padrão no .cmd)

Etapas (tudo gravado em ``--saida`` = ``saida_cego/`` e ``--saida-llm`` = ``saida_cego_llm/``):

1. **entrada**: os ``.txt`` existem (``dados/cego/txt`` por padrão); com ``--sample`` (o
   ``sample_submission.csv`` publicado com o cego) a validação do CSV confere os ``documento_id``;
2. **núcleo**: ``caca_alucinacao.cli --arbitro nenhum`` → JSONs + rastro → ``submission_cego_nucleo.csv``
   (conversor oficial + validação + zip dos JSONs);
3. **núcleo + árbitro**: o mesmo CLI com ``--arbitro transformers`` (modelo da revisão fixa em NF4;
   ``--modelo`` aponta para um snapshot local e ``--id``/``--revisao`` põem o nome canônico e o commit na
   chave do cache — padrão: ``modelos/revisao_fixa.env``) → ``submission_cego_llm.csv`` + exportação do
   cache (``saida_cego_llm/cache_llm.jsonl``: reprodução sem GPU) + tempo médio por documento (envelope:
   ≤ 60 s/doc) + estatísticas do árbitro;
4. **resumo**: documentos, citações por classe em cada CSV, quantas citações o árbitro acrescentou e em
   quantos documentos os dois CSVs diferem — os dois vão para o Kaggle e os dois ficam selecionados.

Sai com 0 se os dois CSVs foram gerados e validados (1 se algum passo falhou; 2 se não há entrada).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dados"
sys.path.insert(0, str(RAIZ / "src"))


def rodar(cmd: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(RAIZ / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=str(RAIZ), env=env, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, check=False)


def revisao_fixa() -> tuple[str, str, bool]:
    modelo, rev, nf4 = "", "", False
    arq = RAIZ / "modelos" / "revisao_fixa.env"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if linha.startswith('export CACA_MODELO="'):
                modelo = linha.split('"')[1]
            elif linha.startswith('export CACA_MODELO_REVISAO="'):
                rev = linha.split('"')[1]
            elif linha.startswith('export CACA_LLM_4BIT="'):
                nf4 = linha.split('"')[1].strip().lower() in ("1", "true", "sim", "yes", "on")
    return modelo, rev, nf4


def contar_csv(csv_path: Path) -> tuple[int, Counter]:
    """(documentos, citações por classe) de um submission.csv oficial (``documento_id,citacoes`` com
    ``inicio,fim,classe,id,confianca`` separados por ``|``)."""
    docs: set[str] = set()
    classes: Counter = Counter()
    with csv_path.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            docs.add(str(linha.get("documento_id", "")))
            for cit in (linha.get("citacoes") or "").split("|"):
                partes = cit.split(",")
                if len(partes) >= 3 and partes[2].strip():
                    classes[partes[2].strip().lower()] += 1
    return len(docs), classes


def documentos_diferentes(a: Path, b: Path) -> list[str]:
    """Documentos cujos JSONs diferem entre as duas saídas (bytes)."""
    dif = []
    for arq in sorted(a.glob("*.json")):
        outro = b / arq.name
        if not outro.exists() or arq.read_bytes() != outro.read_bytes():
            dif.append(arq.stem)
    return dif


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", type=Path, default=DADOS / "cego" / "txt", help="pasta com os .txt do conjunto cego")
    ap.add_argument("--sample", type=Path, default=None, help="sample_submission.csv do cego (padrão: dados/cego/sample_submission.csv se existir)")
    ap.add_argument("--saida", type=Path, default=RAIZ / "saida_cego")
    ap.add_argument("--saida-llm", type=Path, default=RAIZ / "saida_cego_llm")
    ap.add_argument("--sem-arbitro", action="store_true", help="só o núcleo")
    ap.add_argument("--modelo", default=None, help="id do Hub ou pasta local dos pesos (padrão: modelos/revisao_fixa.env)")
    ap.add_argument("--id", default=None, help="nome canônico dos pesos quando --modelo é pasta local (padrão: o da revisão fixa)")
    ap.add_argument("--revisao", default=None, help="commit dos pesos (padrão: modelos/revisao_fixa.env)")
    ap.add_argument("--janelas", type=int, default=None, help="CACA_LLM_EXTRATOR_JANELAS (padrão do código: 6)")
    args = ap.parse_args()
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.time()

    # 1. entrada ---------------------------------------------------------------------------
    txts = sorted(args.entrada.glob("*.txt")) if args.entrada.is_dir() else []
    if not txts:
        print(f"ERRO: nenhum .txt em {args.entrada} — coloque os documentos do cego lá (ou --entrada <pasta>)", file=sys.stderr)
        return 2
    sample = args.sample or (DADOS / "cego" / "sample_submission.csv")
    if not sample.exists():
        print(f"aviso: {sample} ausente — a validação do CSV usará dados/sample_submission.csv (ids do dev) só para o formato")
        sample = DADOS / "sample_submission.csv"
    db, indice, calib = DADOS / "desafio1_bracis.db", DADOS / "indice.json", DADOS / "calibracao.json"
    for p in (db, calib):
        if not p.exists():
            print(f"ERRO: {p} ausente", file=sys.stderr)
            return 2
    print(f"entrada: {len(txts)} documentos em {args.entrada}; sample: {sample}")

    # 2. núcleo ----------------------------------------------------------------------------
    def pipeline(saida: Path, arbitro: str, env: dict[str, str] | None) -> float | None:
        saida.mkdir(parents=True, exist_ok=True)
        t = time.time()
        r = rodar([sys.executable, "-m", "caca_alucinacao.cli", "--input", str(args.entrada), "--output", str(saida),
                   "--db", str(db), *(["--indice", str(indice)] if indice.exists() else []), "--arbitro", arbitro,
                   "--calibracao", str(calib), "--rastro", str(saida / "rastro.jsonl"), "--log-level", "WARNING"], env)
        (saida / "log_pipeline.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode != 0:
            print(f"ERRO no pipeline ({arbitro}), código {r.returncode}:\n" + (r.stdout + r.stderr)[-1500:], file=sys.stderr)
            return None
        n = len(list(saida.glob("*.json")))
        seg = (time.time() - t) / max(1, len(txts))
        print(f"pipeline {arbitro}: {n} JSONs em {saida} ({seg:.1f} s/doc)")
        return seg

    def submissao(saida: Path, destino: Path) -> bool:
        r = rodar([sys.executable, "scripts/gerar_submissao.py", "--saida", str(saida), "--destino", str(destino),
                   "--sample", str(sample), "--txt", str(args.entrada)])
        (saida / "log_submissao.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
        ok = r.returncode == 0 and "REJEITADA" not in (r.stdout + r.stderr)
        print(("submissão: " if ok else "SUBMISSÃO REJEITADA: ") + (r.stdout.strip().splitlines() or [""])[-1])
        if not ok:
            print((r.stdout + r.stderr)[-1500:], file=sys.stderr)
        return ok

    if pipeline(args.saida, "nenhum", None) is None:
        return 1
    csv_nucleo = RAIZ / "submission_cego_nucleo.csv"
    if not submissao(args.saida, csv_nucleo):
        return 1
    if args.sem_arbitro:
        n, classes = contar_csv(csv_nucleo)
        print(f"\n{csv_nucleo.name}: {n} documentos; " + ", ".join(f"{c}={classes.get(c, 0)}" for c in ("real", "inventada", "incompleta")))
        return 0

    # 3. núcleo + árbitro -------------------------------------------------------------------
    modelo_fixo, rev_fixa, nf4 = revisao_fixa()
    modelo = args.modelo or modelo_fixo
    revisao = args.revisao if args.revisao is not None else rev_fixa
    env = {"CACA_MODELO": modelo, "CACA_MODELO_REVISAO": revisao, "CACA_LLM_4BIT": "1" if nf4 else "",
           "CACA_CACHE_LLM": str(args.saida_llm / "cache_llm.sqlite"), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "TOKENIZERS_PARALLELISM": "false", "CUBLAS_WORKSPACE_CONFIG": ":4096:8"}
    if Path(modelo).is_dir():
        env["CACA_MODELO_ID"] = args.id or modelo_fixo
    if args.janelas is not None:
        env["CACA_LLM_EXTRATOR_JANELAS"] = str(args.janelas)
    args.saida_llm.mkdir(parents=True, exist_ok=True)
    (args.saida_llm / "ambiente_llm.env").write_text("".join(f'export {k}="{v}"\n' for k, v in env.items()), encoding="utf-8")
    print(f"árbitro: {modelo} (id={env.get('CACA_MODELO_ID', modelo)} rev={revisao[:12]} {'nf4' if nf4 else 'bf16'})")
    seg = pipeline(args.saida_llm, "transformers", env)
    if seg is None:
        return 1
    try:
        est = json.loads((args.saida_llm / "arbitro_estatisticas.log").read_text(encoding="utf-8"))
        print(f"árbitro: chamadas={est.get('chamadas_ao_modelo')} abstenções={est.get('abstencoes')} "
              f"cache={json.dumps(est.get('cache'), ensure_ascii=False)[:160]}")
        if est.get("abstencoes"):
            print("aviso: houve abstenções (janela sem resposta válida): o documento ficou como o regex deixou nessas janelas")
    except (OSError, ValueError):
        print("aviso: arbitro_estatisticas.log ausente")
    if seg > 60:
        print(f"AVISO: {seg:.1f} s/doc acima do envelope de 60 s/doc (GPU mais lenta? janelas demais?)")
    csv_llm = RAIZ / "submission_cego_llm.csv"
    if not submissao(args.saida_llm, csv_llm):
        return 1
    from caca_alucinacao.llm.cache import CacheLLM  # noqa: WPS433

    n_cache = CacheLLM(args.saida_llm / "cache_llm.sqlite").exportar_jsonl(args.saida_llm / "cache_llm.jsonl")
    print(f"cache exportado: {n_cache} respostas em {args.saida_llm / 'cache_llm.jsonl'} (reprodução sem GPU)")

    # 4. resumo ------------------------------------------------------------------------------
    n1, c1 = contar_csv(csv_nucleo)
    n2, c2 = contar_csv(csv_llm)
    dif = documentos_diferentes(args.saida, args.saida_llm)
    llm = 0
    try:
        for ln in (args.saida_llm / "rastro.jsonl").read_text(encoding="utf-8").splitlines():
            if ln.strip() and '"llm:' in ln and json.loads(ln).get("status") == "emitida":
                llm += 1
    except OSError:
        pass
    print(f"\n{csv_nucleo.name}: {n1} documentos; " + ", ".join(f"{c}={c1.get(c, 0)}" for c in ("real", "inventada", "incompleta")))
    print(f"{csv_llm.name}:    {n2} documentos; " + ", ".join(f"{c}={c2.get(c, 0)}" for c in ("real", "inventada", "incompleta")))
    print(f"citações com origem no árbitro: {llm}; documentos em que os dois CSVs diferem: {len(dif)}"
          + (f" ({', '.join(dif[:8])}{'…' if len(dif) > 8 else ''})" if dif else " — os dois CSVs são idênticos"))
    print(f"envie os dois ao Kaggle e selecione os dois (README §5). ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
