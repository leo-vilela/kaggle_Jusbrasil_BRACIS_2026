#!/usr/bin/env python3
"""Gera ``submission.csv`` com o conversor OFICIAL e valida antes de enviar ao Kaggle.

Uso:
    python scripts/gerar_submissao.py --saida saida/ [--destino submission.csv]
                                      [--sample dados/sample_submission.csv] [--txt dados/txt]
                                      [--zip saida_jsons.zip] [--sem-zip]

Passos:
  1. executa ``dados/ferramentas/json_to_submission.py <saida> <destino>`` (subprocesso,
     exatamente como a organização faria);
  2. valida cada JSON com ``contrato.validar`` (contra o .txt, se disponível);
  3. confere que todo ``documento_id`` do ``sample_submission.csv`` tem linha no CSV
     e que cada célula passa em ``_parse_submission_cell`` do ``kaggle_metric.py``
     oficial (nenhum ``ParticipantVisibleError``);
  4. empacota os JSONs num zip (para o bundle) e imprime o resumo por classe.
Código de saída 1 se a submissão seria rejeitada.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

# um documento com milhares de citações gera uma célula ``citacoes`` maior que o limite
# padrão do módulo csv (131072); o conversor oficial escreve e o kaggle_metric (pandas) lê
# sem problema, então a validação local não pode abortar aí (rodada 3, R3e-04)
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

from avaliar import importar_oficial, ler_sample  # noqa: E402

from caca_alucinacao.config import DADOS, FERRAMENTAS  # noqa: E402
from caca_alucinacao.contrato import validar_arquivo  # noqa: E402


def converter(pasta: Path, destino: Path) -> str:
    """Roda o conversor oficial num subprocesso; devolve o que ele imprimiu."""
    script = FERRAMENTAS / "json_to_submission.py"
    if not script.exists():
        raise FileNotFoundError(f"conversor oficial ausente: {script}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([sys.executable, str(script), str(pasta), str(destino)],
                          check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def validar_csv(destino: Path, sample: list[str]) -> tuple[list[str], Counter[str], int]:
    """Erros (como o Kaggle mostraria), contagem por classe e nº de linhas."""
    metrica = importar_oficial("kaggle_metric")
    erros: list[str] = []
    classes: Counter[str] = Counter()
    with destino.open(encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f))
    vistos: dict[str, int] = {}
    for i, linha in enumerate(linhas, start=2):
        doc = (linha.get("documento_id") or "").strip()
        if not doc:
            erros.append(f"linha {i}: documento_id vazio")
            continue
        if doc in vistos:
            erros.append(f"linha {i}: documento_id {doc!r} repetido (linha {vistos[doc]})")
        vistos[doc] = i
        try:
            preds = metrica._parse_submission_cell(linha.get("citacoes"), doc)
        except metrica.ParticipantVisibleError as exc:
            erros.append(str(exc))
            continue
        for p in preds:
            classes[p["classe"]] += 1
    faltam = [d for d in sample if d not in vistos]
    if faltam:
        erros.append(f"{len(faltam)} documento(s) do sample_submission.csv sem linha: {faltam[:5]}")
    sobra = sorted(set(vistos) - set(sample)) if sample else []
    if sobra:
        erros.append(f"AVISO: {len(sobra)} documento(s) fora do sample_submission.csv: {sobra[:5]}")
    return erros, classes, len(linhas)


def empacotar(pasta: Path, destino_zip: Path) -> int:
    """Zip reprodutível byte a byte: nomes ordenados, data fixa (1980-01-01) e sem atributos
    externos — duas execuções com os mesmos JSONs dão o mesmo hash (revisão R3-09)."""
    arquivos = sorted(pasta.glob("*.json"))
    with zipfile.ZipFile(destino_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for arq in arquivos:
            info = zipfile.ZipInfo(arq.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, arq.read_bytes())
    return len(arquivos)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", type=Path, default=RAIZ / "saida", help="pasta com os JSONs")
    ap.add_argument("--destino", type=Path, default=RAIZ / "submission.csv")
    ap.add_argument("--sample", type=Path, default=DADOS / "sample_submission.csv")
    ap.add_argument("--txt", type=Path, default=DADOS / "txt", help="pasta dos .txt (confere trechos)")
    ap.add_argument("--zip", type=Path, default=None, help="zip dos JSONs (padrão: <destino>_jsons.zip)")
    ap.add_argument("--sem-zip", action="store_true")
    args = ap.parse_args(argv)

    if not args.saida.is_dir() or not any(args.saida.glob("*.json")):
        print(f"nenhum .json em {args.saida}", file=sys.stderr)
        return 2

    erros_contrato = 0
    for arq in sorted(args.saida.glob("*.json")):
        texto = None
        txt = args.txt / f"{arq.stem}.txt"
        if txt.exists():
            texto = txt.read_bytes().decode("utf-8")
        for e in validar_arquivo(arq, texto):
            erros_contrato += 1
            print(f"CONTRATO [{arq.name}] {e}", file=sys.stderr)

    print(converter(args.saida, args.destino))
    sample = ler_sample(args.sample)
    erros, classes, n = validar_csv(args.destino, sample)
    fatais = [e for e in erros if not e.startswith("AVISO")]
    for e in erros:
        print(("ERRO " if not e.startswith("AVISO") else "") + e, file=sys.stderr)

    total = sum(classes.values())
    print(f"{args.destino}: {n} linhas, {total} citações "
          + ", ".join(f"{c}={classes.get(c, 0)}" for c in ("real", "inventada", "incompleta")))
    if not args.sem_zip:
        destino_zip = args.zip or args.destino.with_name(args.destino.stem + "_jsons.zip")
        k = empacotar(args.saida, destino_zip)
        print(f"{destino_zip}: {k} JSONs empacotados")
    if fatais or erros_contrato:
        print(f"SUBMISSÃO REJEITADA: {len(fatais)} erro(s) de CSV, {erros_contrato} violação(ões) do contrato",
              file=sys.stderr)
        return 1
    print("submissão válida (nenhum ParticipantVisibleError)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
