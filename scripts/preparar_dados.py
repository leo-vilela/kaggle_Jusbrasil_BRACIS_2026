#!/usr/bin/env python3
"""Prepara ``dados/`` a partir do zip da aba Data do Kaggle e confere integridade.

Uso:
    python scripts/preparar_dados.py [--zip desafio-jusbrasil-bracis-2026.zip] [--dados dados/] [--estrito]

Com o zip: extrai para ``dados/`` (``desafio1_bracis.db``, ``sample_submission.csv``,
``txt/*.txt``), renomeia ``goldenset_offsets.csv`` → ``goldenset.csv`` (mantendo o
original) e move os ``.py`` oficiais para ``dados/ferramentas/``. Sem o zip: só
verifica o que já está em ``dados/``.

Sempre: imprime o SHA-256 de cada arquivo conhecido, compara com o esperado
(distribuição de 15/09/2026), e valida os offsets do gabarito
(``trecho == texto[inicio:fim]``, desescapando ``\\n``). Divergências são AVISOS
(a organização pode redistribuir os dados); com ``--estrito`` viram erro (código 1).
Somente biblioteca padrão.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

SHA_ESPERADOS = {
    "zip": "b5ea998b301459be4769084f0dc00b7758650697e71bf9843257b21870239c52",
    "desafio1_bracis.db": "78f0708b0a21c11655dfdd882382fea75c62a75415d8d3b118888c0a340bef4c",
    "goldenset.csv": "562e4ee5d0e8cb299ccb99b4c6dd758b195fbb5668617ce4c2ead465ea27211d",
    "sample_submission.csv": "c299ddb54b94d6375de4e58ecad8fec55a68f4cced667e19b3f4f9f60af4ffdc",
    "ferramentas/kaggle_metric.py": "3c4d30e70971144afbd0ae73c6d4ac887faf0f5926de986170de32f72544fc3f",
    "ferramentas/json_to_submission.py": "c6ec4963e884c7fc19939816d7398e512cc8f7d60af472fb1a3bd723f1fee05c",
}


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _copiar(origem: Path, destino: Path, avisos: list[str]) -> bool:
    """Copia se o destino não existir ou diferir (tolera destino somente-leitura)."""
    if destino.exists() and sha256(destino) == sha256(origem):
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destino.exists():
            destino.chmod(0o644)
        shutil.copy2(origem, destino)
    except OSError as exc:
        avisos.append(f"não foi possível gravar {destino}: {exc}")
        return False
    return True


def extrair(zip_path: Path, dados: Path, avisos: list[str]) -> dict[str, int]:
    """Extrai e distribui os arquivos por nome; devolve contagens por categoria."""
    contagem = {"db": 0, "csv": 0, "py": 0, "txt": 0, "outros": 0}
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        for arq in sorted(Path(tmp).rglob("*")):
            if not arq.is_file() or arq.name.startswith("._") or "__MACOSX" in arq.parts:
                continue
            nome = arq.name
            if nome.endswith(".db"):
                _copiar(arq, dados / nome, avisos)
                contagem["db"] += 1
            elif nome == "goldenset_offsets.csv":
                _copiar(arq, dados / nome, avisos)               # original preservado
                _copiar(arq, dados / "goldenset.csv", avisos)    # nome usado pelo repositório
                contagem["csv"] += 1
            elif nome.endswith(".csv"):
                _copiar(arq, dados / nome, avisos)
                contagem["csv"] += 1
            elif nome.endswith(".py"):
                _copiar(arq, dados / "ferramentas" / nome, avisos)
                contagem["py"] += 1
            elif nome.endswith(".txt"):
                _copiar(arq, dados / "txt" / nome, avisos)
                contagem["txt"] += 1
            else:
                rel = arq.relative_to(tmp)
                _copiar(arq, dados / rel, avisos)
                contagem["outros"] += 1
                avisos.append(f"arquivo inesperado no zip: {rel}")
    return contagem


def conferir_hashes(dados: Path, zip_path: Path | None) -> list[tuple[str, str, str]]:
    """``[(nome, sha_obtido, estado)]`` com estado OK | DIVERGE | AUSENTE."""
    linhas = []
    if zip_path is not None and zip_path.exists():
        h = sha256(zip_path)
        linhas.append((zip_path.name, h, "OK" if h == SHA_ESPERADOS["zip"] else "DIVERGE"))
    for rel, esperado in SHA_ESPERADOS.items():
        if rel == "zip":
            continue
        caminho = dados / rel
        if not caminho.exists():
            linhas.append((rel, "-", "AUSENTE"))
            continue
        h = sha256(caminho)
        linhas.append((rel, h, "OK" if h == esperado else "DIVERGE"))
    return linhas


def validar_offsets(dados: Path) -> tuple[int, int, list[str]]:
    """``(ok, divergentes, mensagens)`` — sem imprimir trechos do gabarito."""
    gabarito = dados / "goldenset.csv"
    txt = dados / "txt"
    if not gabarito.exists():
        return 0, 0, ["goldenset.csv ausente; offsets não validados"]
    ok = ruim = 0
    msgs: list[str] = []
    textos: dict[str, str | None] = {}
    with gabarito.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            doc = r["documento_id"].strip()
            if doc not in textos:
                arq = txt / f"{doc}.txt"
                textos[doc] = arq.read_bytes().decode("utf-8") if arq.exists() else None
            texto = textos[doc]
            if texto is None:
                ruim += 1
                msgs.append(f"{doc}: .txt ausente")
                continue
            inicio, fim = int(r["inicio"]), int(r["fim"])
            esperado = (r.get("trecho") or "").replace("\\n", "\n")
            if texto[inicio:fim] == esperado:
                ok += 1
            else:
                ruim += 1
                msgs.append(f"{doc} {r.get('citacao_id', '?')}: texto[{inicio}:{fim}] difere do trecho "
                            f"(len {fim - inicio} vs {len(esperado)})")
    return ok, ruim, msgs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", type=Path, default=RAIZ / "desafio-jusbrasil-bracis-2026.zip")
    ap.add_argument("--dados", type=Path, default=RAIZ / "dados")
    ap.add_argument("--estrito", action="store_true", help="divergência de hash/offset = erro")
    args = ap.parse_args(argv)

    avisos: list[str] = []
    args.dados.mkdir(parents=True, exist_ok=True)
    if args.zip.exists():
        print(f"zip: {args.zip} sha256={sha256(args.zip)}")
        contagem = extrair(args.zip, args.dados, avisos)
        print("extraído: " + ", ".join(f"{k}={v}" for k, v in contagem.items()))
    else:
        print(f"zip não encontrado ({args.zip}); modo verificação de {args.dados}")

    print("\nSHA-256:")
    divergentes = 0
    ausentes = 0
    for nome, h, estado in conferir_hashes(args.dados, args.zip if args.zip.exists() else None):
        print(f"  {estado:8} {h:64} {nome}")
        if estado == "AUSENTE":
            ausentes += 1
        elif estado != "OK":
            divergentes += 1

    n_txt = len(list((args.dados / "txt").glob("*.txt"))) if (args.dados / "txt").is_dir() else 0
    print(f"\n.txt em {args.dados / 'txt'}: {n_txt}")
    ok, ruim, msgs = validar_offsets(args.dados)
    print(f"offsets do gabarito: {ok} conferem, {ruim} divergem")
    for m in msgs[:20]:
        print(f"  AVISO {m}")
    for a in avisos:
        print(f"AVISO: {a}")

    problemas = divergentes + ruim
    if ausentes and not problemas:
        # clone limpo sem o zip: os arquivos do desafio ainda não estão em dados/ — não é divergência (R3q-09)
        print(f"\n{ausentes} arquivo(s) AUSENTE(s) em {args.dados}: passe o zip da aba Data "
              f"(make dados ZIP=~/Downloads/desafio-jusbrasil-bracis-2026.zip)")
        return 1 if args.estrito else 0
    if problemas:
        print(f"\n{problemas} divergência(s) — {'ERRO (--estrito)' if args.estrito else 'confira antes de prosseguir'}"
              + (f"; {ausentes} ausente(s)" if ausentes else ""))
        return 1 if args.estrito else 0
    print("\ntudo confere com a distribuição de 15/09/2026")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
