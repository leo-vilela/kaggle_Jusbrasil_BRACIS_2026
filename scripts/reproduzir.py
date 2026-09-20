"""Reprodução completa em um comando (README §"Como reproduzir passo a passo", condensado).

    python scripts/reproduzir.py                                  # tudo, em saida_reproducao/
    python scripts/reproduzir.py --referencia submission_v1_1.csv  # e compara o CSV gerado com um entregue
    python scripts/reproduzir.py --sem-testes                      # só pipeline + métrica + CSV
    python scripts/reproduzir.py --arbitro transformers --cache-llm saida_llm/cache_llm.jsonl \
        --referencia submission_v1_2.csv                           # com o árbitro LLM, SEM GPU (só o cache)

Etapas, na ordem, cada uma com veredito próprio:

1. **dados**: os arquivos oficiais estão em ``dados/`` e os SHA-256 batem com os documentados
   (``scripts/preparar_dados.py``: distribuição final de 15/09/2026);
2. **derivados**: ``dados/catalogo_gabarito.json`` (exigido pela verificação de vazamento) e os
   sintéticos ``n2_dev``/``n3_ood``/``n2_ag_treino`` (seeds fixas; docs/05) são gerados se faltarem;
3. **testes**: ``python -m unittest discover -s tests`` — falha se algum teste falhar **ou** se
   algum ficar ``skipped`` com os dados presentes;
4. **vazamento**: nenhum trecho/número/nome do gabarito em arquivo versionado ou novo;
5. **pipeline 2×**: o CLI roda duas vezes (a segunda sem ``dados/indice.json``, forçando a
   reconstrução do índice em memória) e as saídas têm de ser byte a byte idênticas (JSONs e rastro);
   com ``--arbitro transformers --cache-llm <jsonl>`` o árbitro LLM roda **só do cache** exportado da
   execução de referência (``CACA_LLM_SOMENTE_CACHE=1``; nem torch é carregado): zero chamadas ao
   modelo, mesma saída em qualquer máquina — é assim que a submissão com o Qwen ligado se reproduz;
6. **métrica oficial**: ``scripts/avaliar.py`` (que importa o ``kaggle_metric.py`` da organização);
7. **submissão**: ``json_to_submission.py`` oficial + validação; SHA-256 do CSV; com ``--referencia``,
   comparação byte a byte.

Sai com código 0 só se todas as etapas passarem. Só biblioteca padrão aqui; ``numpy``/``pandas``
são exigidos apenas pela métrica oficial (etapa 6) — sem eles, a etapa é marcada como PULADA e o
código de saída é 3, para não confundir "não avaliei" com "reproduzi".
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dados"
sys.path.insert(0, str(RAIZ / "scripts"))
from preparar_dados import SHA_ESPERADOS, sha256  # noqa: E402

OBRIGATORIOS = ("desafio1_bracis.db", "goldenset.csv", "sample_submission.csv",
                "ferramentas/kaggle_metric.py", "ferramentas/json_to_submission.py")
SINTETICOS = (  # exatamente os comandos de `make sinteticos`
    ("n2_dev", ["--n-docs", "40", "--nivel", "2", "--seed", "123", "--perfil", "dev"]),
    ("n3_ood", ["--n-docs", "40", "--nivel", "3", "--seed", "7"]),
    ("n2_ag_treino", ["--n-docs", "60", "--nivel", "2", "--seed", "321", "--perfil", "agressivo"]),
)


class Etapa:
    def __init__(self) -> None:
        self.linhas: list[tuple[str, str, str]] = []
        self.falhas = 0
        self.puladas = 0

    def ok(self, nome: str, detalhe: str = "") -> None:
        self.linhas.append((nome, "OK", detalhe))

    def falha(self, nome: str, detalhe: str = "") -> None:
        self.linhas.append((nome, "FALHOU", detalhe))
        self.falhas += 1

    def pulada(self, nome: str, detalhe: str = "") -> None:
        self.linhas.append((nome, "PULADA", detalhe))
        self.puladas += 1


def rodar(cmd: list[str], env: dict[str, str] | None = None, capturar: bool = True) -> subprocess.CompletedProcess:
    ambiente = dict(os.environ)
    ambiente["PYTHONPATH"] = str(RAIZ / "src")
    ambiente["PYTHONDONTWRITEBYTECODE"] = "1"
    ambiente["PYTHONIOENCODING"] = "utf-8"
    if env:
        ambiente.update(env)
    return subprocess.run(cmd, cwd=str(RAIZ), env=ambiente, text=True, encoding="utf-8",
                          errors="replace", capture_output=capturar, check=False)


def arvore(pasta: Path) -> list[Path]:
    return sorted(p.relative_to(pasta) for p in pasta.rglob("*") if p.is_file())


def comparar_pastas(a: Path, b: Path) -> list[str]:
    """Nomes que diferem (ausentes de um lado ou com bytes diferentes)."""
    fa, fb = set(arvore(a)), set(arvore(b))
    # o log de estatísticas do árbitro traz o caminho do cache (um por execução): não é saída
    fa, fb = {x for x in fa if x.name != "arbitro_estatisticas.log"}, {x for x in fb if x.name != "arbitro_estatisticas.log"}
    diferentes = sorted(str(p) for p in fa ^ fb)
    for rel in sorted(fa & fb):
        if not filecmp.cmp(a / rel, b / rel, shallow=False):
            diferentes.append(str(rel))
    return diferentes


def pasta_limpa(pasta: Path) -> Path:
    """``pasta`` vazia e recém-criada; se não puder apagar a existente (montagens sem permissão de
    exclusão, como a VM do Cowork), usa ``<pasta>_2``, ``<pasta>_3``… — nunca reaproveita saída antiga."""
    candidata = pasta
    for n in range(2, 50):
        if candidata.exists():
            try:
                shutil.rmtree(candidata)
            except OSError:
                candidata = pasta.with_name(f"{pasta.name}_{n}")
                continue
        candidata.mkdir(parents=True)
        if candidata != pasta:
            print(f"aviso: não foi possível apagar {pasta}; usando {candidata}")
        return candidata
    raise RuntimeError(f"não foi possível criar uma pasta de saída limpa a partir de {pasta}")


def ambiente_arbitro(arbitro: str, cache_llm: Path | None) -> dict[str, str] | None:
    """Variáveis para o pipeline rodar o árbitro **só do cache** (``{}`` sem árbitro; ``None`` se o
    JSONL não existe): modelo e revisão fixa de ``modelos/revisao_fixa.env`` (a chave do cache inclui
    os dois), ``CACA_LLM_SOMENTE_CACHE=1`` e ``CACA_LLM_CACHE_IMPORTAR=<jsonl>``."""
    if arbitro == "nenhum":
        return {}
    env: dict[str, str] = {}
    fixo = RAIZ / "modelos" / "revisao_fixa.env"
    if fixo.exists():
        for linha in fixo.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*export\s+(CACA_MODELO|CACA_MODELO_REVISAO)="([^"]*)"', linha)
            if m and not os.environ.get(m.group(1)):
                env[m.group(1)] = m.group(2)
    if cache_llm is not None:
        if not cache_llm.exists():
            return None
        env["CACA_LLM_SOMENTE_CACHE"] = "1"
        env["CACA_LLM_CACHE_IMPORTAR"] = str(cache_llm.resolve())
    return env


def estatisticas_arbitro(pasta: Path) -> dict:
    """``arbitro_estatisticas.log`` gravado pelo CLI (``{}`` se ausente ou ilegível)."""
    try:
        return json.loads((pasta / "arbitro_estatisticas.log").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--saida", type=Path, default=RAIZ / "saida_reproducao",
                    help="pasta de trabalho (criada do zero a cada execução)")
    ap.add_argument("--referencia", type=Path, default=None,
                    help="submission.csv entregue para comparar byte a byte com o gerado")
    ap.add_argument("--sem-testes", action="store_true", help="pula a suíte unittest e a verificação de vazamento")
    ap.add_argument("--entrada", type=Path, default=DADOS / "txt", help="pasta dos .txt (padrão: os 26 do dev)")
    ap.add_argument("--calibracao", type=Path, default=DADOS / "calibracao.json")
    ap.add_argument("--arbitro", default="nenhum", choices=("nenhum", "transformers", "vllm", "mock"),
                    help="árbitro LLM do pipeline (padrão: nenhum = só o núcleo)")
    ap.add_argument("--cache-llm", type=Path, default=None,
                    help="JSONL exportado do cache do árbitro (saida_llm/cache_llm.jsonl): o árbitro responde só dele, sem GPU")
    args = ap.parse_args()
    if args.arbitro not in ("nenhum", "mock") and args.cache_llm is None:
        ap.error("--arbitro transformers/vllm exige --cache-llm <jsonl> (a reprodução nunca chama o modelo)")
    for fluxo in (sys.stdout, sys.stderr):  # consoles sem UTF-8 (Windows cp1252) não derrubam o resumo
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    py = sys.executable
    et = Etapa()
    t0 = time.time()
    print(f"raiz: {RAIZ}\npython: {sys.version.split()[0]} ({py})\n")

    # 1. dados oficiais e SHA-256 ----------------------------------------------------------
    ausentes = [r for r in OBRIGATORIOS if not (DADOS / r).exists()]
    if ausentes or not (args.entrada.is_dir() and any(args.entrada.glob("*.txt"))):
        et.falha("1 dados", f"ausentes em dados/: {ausentes or [str(args.entrada)]} — rode `make dados ZIP=<zip da aba Data>`")
        return imprimir(et, t0)
    divergentes = []
    for rel, esperado in SHA_ESPERADOS.items():
        caminho = DADOS / rel
        if caminho.exists() and sha256(caminho) != esperado:
            divergentes.append(rel)
    if divergentes:
        et.falha("1 dados", f"SHA-256 diverge do documentado: {divergentes}")
    else:
        et.ok("1 dados", f"{len(OBRIGATORIOS)} arquivos oficiais com SHA-256 conferido; {len(list(args.entrada.glob('*.txt')))} .txt")

    # 2. derivados -----------------------------------------------------------------------
    gerados = []
    catalogo = DADOS / "catalogo_gabarito.json"
    if not catalogo.exists():
        r = rodar([py, "scripts/analise/catalogar_gabarito.py", "--dados", "dados", "--saida", str(catalogo)])
        if r.returncode != 0:
            et.falha("2 derivados", "catalogar_gabarito.py falhou:\n" + r.stderr[-800:])
            return imprimir(et, t0)
        gerados.append("catalogo_gabarito.json")
    for nome, extra in SINTETICOS:
        pasta = DADOS / "sinteticos" / nome
        if not pasta.is_dir():
            r = rodar([py, "scripts/gerar_sinteticos.py", "--saida", str(pasta), *extra])
            if r.returncode != 0:
                et.falha("2 derivados", f"gerar_sinteticos.py ({nome}) falhou:\n" + r.stderr[-800:])
                return imprimir(et, t0)
            gerados.append(f"sinteticos/{nome}")
    et.ok("2 derivados", ("gerados agora: " + ", ".join(gerados)) if gerados else "já presentes")

    # 3. testes ----------------------------------------------------------------------------
    if args.sem_testes:
        et.pulada("3 testes", "--sem-testes")
        et.pulada("4 vazamento", "--sem-testes")
    else:
        r = rodar([py, "-m", "unittest", "discover", "-s", "tests"])
        saida = r.stdout + r.stderr
        m = re.search(r"Ran (\d+) tests? in ([\d.]+)s", saida)
        n = int(m.group(1)) if m else 0
        pulados = re.search(r"skipped=(\d+)", saida)
        n_pulados = int(pulados.group(1)) if pulados else 0
        if r.returncode != 0 or not m or "\nOK" not in saida:
            et.falha("3 testes", f"{n} testes; código {r.returncode}\n" + saida[-1500:])
        elif n_pulados:
            et.falha("3 testes", f"{n} testes OK mas {n_pulados} skipped com os dados presentes (veja `-v`)")
        else:
            et.ok("3 testes", f"{n} testes OK, 0 skipped ({m.group(2)}s)")
        # 4. vazamento
        r = rodar([py, "scripts/analise/verificar_vazamento.py"])
        ultima = ((r.stdout + r.stderr).strip().splitlines() or [""])[-1]
        if r.returncode == 0:
            et.ok("4 vazamento", ultima)
        else:
            et.falha("4 vazamento", (r.stdout + r.stderr)[-1500:])

    # 5. pipeline 2× --------------------------------------------------------------------------
    args.saida = pasta_limpa(args.saida)
    base = [py, "-m", "caca_alucinacao.cli", "--input", str(args.entrada), "--db", str(DADOS / "desafio1_bracis.db"),
            "--arbitro", args.arbitro, "--calibracao", str(args.calibracao)]
    a, b = args.saida / "execucao_a", args.saida / "execucao_b"
    indice = DADOS / "indice.json"
    cmd_a = base + ["--output", str(a), "--rastro", str(a / "rastro.jsonl")] + (["--indice", str(indice)] if indice.exists() else [])
    cmd_b = base + ["--output", str(b), "--rastro", str(b / "rastro.jsonl")]  # sem --indice: reconstrói em memória
    env_llm = ambiente_arbitro(args.arbitro, args.cache_llm)
    if env_llm is None:
        et.falha("5 pipeline", f"cache do árbitro ausente: {args.cache_llm}")
        return imprimir(et, t0)
    tempos = []
    # cada execução com o seu SQLite (importado do mesmo JSONL), numa pasta temporária local: nada
    # passa de A para B, e o SQLite não depende da pasta de saída (montagens de rede/VM sem
    # travas de arquivo deixam o cache inativo — e aí a reprodução falharia, como deve)
    pasta_tmp = Path(tempfile.mkdtemp(prefix="caca_cache_llm_")) if env_llm else None
    for cmd, pasta in ((cmd_a, a), (cmd_b, b)):
        t = time.time()
        r = rodar(cmd, env=dict(env_llm, CACA_CACHE_LLM=str(pasta_tmp / f"{pasta.name}.sqlite")) if env_llm else None)
        tempos.append(time.time() - t)
        if r.returncode != 0:
            et.falha("5 pipeline", f"CLI falhou (código {r.returncode}):\n" + (r.stdout + r.stderr)[-1500:])
            return imprimir(et, t0)
    n_json = len(list(a.glob("*.json")))
    n_txt = len(list(args.entrada.glob("*.txt")))
    dif = comparar_pastas(a, b)
    if n_json != n_txt:
        et.falha("5 pipeline", f"{n_json} JSONs para {n_txt} .txt")
    elif dif:
        et.falha("5 pipeline", "execuções A e B diferem em: " + ", ".join(dif[:10]))
    else:
        detalhe = (f"{n_json} JSONs; A (com índice) == B (índice em memória), byte a byte, rastro incluído; "
                   f"{tempos[0]:.1f}s / {tempos[1]:.1f}s")
        if args.arbitro != "nenhum":
            stats = estatisticas_arbitro(a)
            chamadas = stats.get("chamadas_ao_modelo")
            abstencoes = stats.get("abstencoes")
            cache = stats.get("cache") or {}
            detalhe += (f"\n      árbitro {args.arbitro}: {stats.get('modelo')}@{str(stats.get('revisao') or '')[:12]} "
                        f"prompt {stats.get('prompt_versao')}; chamadas ao modelo = {chamadas}; "
                        f"abstenções = {abstencoes}; cache: {cache.get('acertos')} acertos, {cache.get('registros')} registros")
            if args.cache_llm is not None:
                # reprodução só do cache: nenhuma chamada ao modelo E nenhuma abstenção (toda janela
                # tem de achar a resposta gravada); cache inativo ou JSONL de outra versão do prompt
                # aparecem aqui como abstenções, nunca como "reproduzido"
                if chamadas not in (0, None):
                    et.falha("5 pipeline", detalhe + "\n      o árbitro chamou o modelo: a reprodução tem de vir só do cache")
                    return imprimir(et, t0)
                if not cache.get("ativo", False) or (abstencoes or 0) > 0:
                    et.falha("5 pipeline", detalhe + "\n      o árbitro NÃO respondeu do cache (cache inativo, JSONL de outro modelo/"
                                                     "prompt ou janelas sem resposta gravada): a saída acima não reproduz a submissão com o árbitro")
                    return imprimir(et, t0)
        et.ok("5 pipeline", detalhe)

    # 6. métrica oficial -----------------------------------------------------------------------
    relatorio = args.saida / "relatorio.json"
    score = None
    try:
        import numpy  # noqa: F401
        import pandas  # noqa: F401
    except ImportError:
        et.pulada("6 métrica", "numpy/pandas ausentes (pip install -r requirements.txt); o kaggle_metric.py oficial precisa deles")
    else:
        r = rodar([py, "scripts/avaliar.py", "--saida", str(a), "--rastro", str(a / "rastro.jsonl"), "--json", str(relatorio)])
        if r.returncode != 0 or not relatorio.exists():
            et.falha("6 métrica", (r.stdout + r.stderr)[-1500:])
        else:
            rel = json.loads(relatorio.read_text(encoding="utf-8"))
            score = float(rel["score_final"])
            linhas_niveis = [ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith("Nível")]
            et.ok("6 métrica", f"score_final = {score:.5f} (exato {score:.7f}; máximo 1.10000)\n"
                               + "\n".join("      " + ln for ln in linhas_niveis))

    # 7. submissão ------------------------------------------------------------------------------
    csv = args.saida / "submission.csv"
    r = rodar([py, "scripts/gerar_submissao.py", "--saida", str(a), "--destino", str(csv)])
    if r.returncode != 0 or not csv.exists():
        et.falha("7 submissão", (r.stdout + r.stderr)[-1500:])
    else:
        h = sha256(csv)
        detalhe = f"{csv.name} válido (conversor oficial); sha256 {h}"
        if args.referencia is not None:
            if not args.referencia.exists():
                et.falha("7 submissão", f"referência ausente: {args.referencia}")
                return imprimir(et, t0)
            if filecmp.cmp(csv, args.referencia, shallow=False):
                detalhe += f"\n      IDÊNTICO byte a byte a {args.referencia}"
                et.ok("7 submissão", detalhe)
            else:
                et.falha("7 submissão", detalhe + f"\n      DIFERE de {args.referencia} (sha256 {sha256(args.referencia)})")
        else:
            et.ok("7 submissão", detalhe)
    return imprimir(et, t0)


def imprimir(et: Etapa, t0: float) -> int:
    print("=" * 78)
    for nome, estado, detalhe in et.linhas:
        print(f"{estado:7} {nome:14} {detalhe}")
    print("=" * 78)
    if et.falhas:
        print(f"REPRODUÇÃO FALHOU: {et.falhas} etapa(s) com problema ({time.time() - t0:.0f}s)")
        return 1
    if et.puladas:
        print(f"REPRODUÇÃO PARCIAL: {et.puladas} etapa(s) pulada(s) ({time.time() - t0:.0f}s)")
        return 3
    print(f"REPRODUÇÃO COMPLETA: todas as etapas conferem ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
