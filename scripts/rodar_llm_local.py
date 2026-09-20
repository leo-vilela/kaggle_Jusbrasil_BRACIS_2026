#!/usr/bin/env python3
"""Medição do árbitro LLM com o modelo REAL, na GPU local, em um comando (ADR 0003, padrão ouro).

    python scripts/rodar_llm_local.py                       # Qwen2.5-7B-Instruct na revisão fixa (baixa se faltar)
    python scripts/rodar_llm_local.py --modelo /opt/bracis/models/<snapshot>   # snapshot local (teste de fumaça)
    python scripts/rodar_llm_local.py --rapido              # só os conjuntos-chave (≈ 500 chamadas)
    python scripts/rodar_llm_local.py --completo            # todos os conjuntos (≈ 2.000 chamadas; horas)
    # outro modelo, quantizado em NF4, com o nome canônico e o commit nas chaves do cache:
    python scripts/rodar_llm_local.py --modelo /opt/bracis/models/qwen35_9b --id Qwen/Qwen3.5-9B \\
        --revisao <commit> --quatro-bits --saida saida_llm_q35

Etapas (cada uma grava o que produz em ``--saida``, padrão ``saida_llm/``):

1. **ambiente**: Python, torch, transformers, GPU (nome, VRAM), CUDA; grava ``ambiente.json``;
   falha cedo (código 2) sem torch com CUDA — não faz sentido medir na CPU;
2. **pesos**: ``--modelo`` como pasta local (``config.json`` + safetensors) ou id do Hugging Face
   com ``--revisao`` (padrão: ``modelos/revisao_fixa.env``); sem snapshot no cache, baixa com
   ``huggingface_hub.snapshot_download`` (rede necessária só aqui); grava ``modelo.json`` com o
   caminho, o commit e o hash de ``config.json`` + shards (identidade dos pesos). Para uma pasta
   local, ``--revisao`` só vale se dado explicitamente (a revisão fixa do .env é do modelo padrão) e
   ``--id`` (exige ``--revisao``) põe o nome canônico dos pesos na chave do cache, no lugar do caminho
   — assim o ``cache_llm.jsonl`` reproduz depois com ``CACA_MODELO=<id>``; ``--quatro-bits`` carrega
   em NF4 (``CACA_LLM_4BIT=1``, bitsandbytes);
3. **fumaça**: uma chamada de cada operação do árbitro (``normalizar``, ``escolher``, ``classificar``,
   ``extrair``) com entradas sintéticas; imprime resposta bruta, resultado validado e latência;
4. **medição**: ``scripts/comparar_arbitro.py --arbitro transformers`` nos conjuntos escolhidos, com
   cache SQLite em ``--saida/cache_llm.sqlite`` (repetir é grátis); relatório ``comparacao_arbitro.json``
   e VEREDITO pelo critério da ADR 0003;
5. **dev com árbitro** → JSONs, ``submission_llm.csv`` (conversor oficial) e score;
6. **exportação**: ``cache_llm.jsonl`` com todas as respostas do modelo — com ele qualquer pessoa
   reproduz a mesma saída SEM GPU (``CACA_LLM_SOMENTE_CACHE=1`` + ``CacheLLM.importar_jsonl``).

Reprodutibilidade: decodificação greedy, semente fixa, TF32 desligado, 1 prompt por ``generate``
(MANIFESTO_MODELO.md); o limite de VRAM por processo reproduz o envelope de 24 GB numa GPU maior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dados"
sys.path.insert(0, str(RAIZ / "src"))

RAPIDO = ["dev", "n3_ood", "r6_extrator_formas", "r6_extrator_distratores", "r5_distratores_orgaos",
          "r2_chave_parcial", "ruido_n2", "r5_processos_ocr_combo", "vagas"]


def rodar(cmd: list[str], env_extra: dict[str, str] | None = None, capturar: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(RAIZ / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=str(RAIZ), env=env, text=True, encoding="utf-8", errors="replace",
                          capture_output=capturar, check=False)


def revisao_fixa() -> tuple[str, str]:
    modelo, rev = "Qwen/Qwen2.5-7B-Instruct", ""
    arq = RAIZ / "modelos" / "revisao_fixa.env"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if linha.startswith('export CACA_MODELO="'):
                modelo = linha.split('"')[1]
            if linha.startswith('export CACA_MODELO_REVISAO="'):
                rev = linha.split('"')[1]
    return modelo, rev


def hf_home_padrao() -> Path:
    """Onde guardar os pesos: ``modelos/hf`` no repositório, EXCETO quando o repositório está num disco
    do Windows montado no WSL (``/mnt/<letra>/…``, drvfs): carregar 15 GB de safetensors por 9p é
    lento demais — aí os pesos vão para ``~/.cache/huggingface`` (sistema de arquivos do WSL)."""
    raiz = str(RAIZ)
    if platform.system() == "Linux" and (raiz.startswith("/mnt/") and len(raiz) > 5 and raiz[5].isalpha() and raiz[6:7] in ("/", "")):
        return Path.home() / ".cache" / "huggingface"
    return RAIZ / "modelos" / "hf"


def hash_snapshot(pasta: Path) -> str:
    h = hashlib.sha256()
    h.update((pasta / "config.json").read_bytes())
    for arq in sorted(pasta.glob("*.safetensors")):
        h.update(f"{arq.name}:{arq.stat().st_size}".encode())
    return h.hexdigest()[:16]


def etapa_ambiente(saida: Path) -> dict:
    info: dict = {"python": sys.version.split()[0], "plataforma": platform.platform(), "executavel": sys.executable}
    try:
        import torch  # noqa: WPS433
        info["torch"] = torch.__version__
        info["cuda_disponivel"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            info["gpu"] = p.name
            info["vram_gb"] = round(p.total_memory / 2**30, 1)
            info["cuda"] = torch.version.cuda
            info["capacidade"] = f"{p.major}.{p.minor}"
    except Exception as exc:
        info["torch_erro"] = repr(exc)
    try:
        import transformers
        info["transformers"] = transformers.__version__
    except Exception as exc:
        info["transformers_erro"] = repr(exc)
    try:
        import huggingface_hub
        info["huggingface_hub"] = huggingface_hub.__version__
    except Exception:
        pass
    (saida / "ambiente.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ambiente:", json.dumps(info, ensure_ascii=False))
    return info


def etapa_pesos(modelo: str, revisao: str, saida: Path, revisao_local: str = "", modelo_id: str = "",
                quatro_bits: bool = False) -> tuple[str, str, Path]:
    """Devolve ``(CACA_MODELO, CACA_MODELO_REVISAO, pasta_do_snapshot)``.

    ``revisao`` é a do id do Hub; para uma pasta local vale ``revisao_local`` (só a explícita) e
    ``modelo_id`` (nome canônico que vai para a chave do cache).
    """
    p = Path(modelo)
    if p.is_dir() and (p / "config.json").is_file():
        cfg = json.loads((p / "config.json").read_text(encoding="utf-8"))
        texto = cfg.get("text_config") or {}
        info = {"modelo": str(p), "origem": "snapshot local", "id": modelo_id, "revisao": revisao_local,
                "quatro_bits": quatro_bits, "hash": hash_snapshot(p),
                "config": {k: cfg.get(k, texto.get(k)) for k in ("_name_or_path", "model_type", "architectures",
                                                                 "num_hidden_layers", "hidden_size", "torch_dtype",
                                                                 "dtype", "vocab_size")}}
        (saida / "modelo.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print("pesos:", json.dumps(info, ensure_ascii=False))
        return str(p), revisao_local, p
    hf_home = Path(os.environ.get("HF_HOME") or hf_home_padrao())
    hf_home.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf_home)
    from huggingface_hub import snapshot_download  # noqa: WPS433
    print(f"pesos: {modelo}@{revisao or 'main'} em {hf_home} (baixando se faltar; ≈ 15 GB)…", flush=True)
    t = time.time()
    pasta = Path(snapshot_download(modelo, revision=revisao or None))
    commit = pasta.name
    info = {"modelo": modelo, "origem": "huggingface", "revisao": commit, "quatro_bits": quatro_bits,
            "hash": hash_snapshot(pasta), "snapshot": str(pasta), "segundos": round(time.time() - t)}
    if revisao and commit != revisao:
        print(f"ERRO: commit baixado {commit} ≠ revisão fixa {revisao}", file=sys.stderr)
        sys.exit(2)
    (saida / "modelo.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print("pesos:", json.dumps(info, ensure_ascii=False))
    return modelo, commit, pasta


def etapa_fumaca(env: dict[str, str]) -> None:
    for k, v in env.items():
        os.environ[k] = v
    from caca_alucinacao.llm import obter_arbitro  # noqa: WPS433
    t = time.time()
    arb = obter_arbitro("transformers", cache=None)
    print(f"fumaça: modelo carregado em {time.time() - t:.0f}s ({arb.modelo} id={arb.modelo_id or '-'} rev={arb.revisao} "
          f"família={getattr(arb, 'familia', '?')} arquitetura={getattr(arb, 'arquitetura', '') or '-'} "
          f"assinatura={arb.assinatura})")
    janela = ("Nesse sentido, o REsp1.234.567/SP afastou a tese, como também a Súmula 7 do STJ. Conforme decidido no "
              "julgamento do recurso especial de número 2.OO0.111, oriundo do Paraná, a pretensão não prospera. "
              "Conforme consta às fls. 45/52, o valor de R$ 12.500,00 foi fixado em 10/03/2020.")
    ja = [{"inicio": janela.index("Súmula 7"), "fim": janela.index("Súmula 7") + 15, "trecho": "Súmula 7 do STJ"}]
    chamadas = (
        ("extrair", lambda a: a.extrair_citacoes(janela, ja)),
        ("normalizar", lambda a: a.normalizar_citacao("REsp 1.9SO.OO1/SP", "… como decidido no REsp 1.9SO.OO1/SP, que …")),
        ("classificar", lambda a: a.classificar_span("n° 2.111.333 (PE)", "como se vê no A.REsp n° 2.111.333 (PE), que afastou a tese.")),
    )
    for nome, fn in chamadas:
        t = time.time()
        r = fn(arb)
        print(f"fumaça {nome}: {time.time() - t:.1f}s → {json.dumps(r, ensure_ascii=False)[:300]}")
    print("fumaça: estatísticas", json.dumps(arb.estatisticas(), ensure_ascii=False)[:300])
    del arb


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", default=None, help="id do Hugging Face ou pasta local (padrão: modelos/revisao_fixa.env)")
    ap.add_argument("--revisao", default=None, help="commit dos pesos (padrão: modelos/revisao_fixa.env; para pasta local, só se dado)")
    ap.add_argument("--id", default=None, help="nome canônico dos pesos de uma pasta local (ex.: Qwen/Qwen3.5-9B) para a chave do cache; exige --revisao")
    ap.add_argument("--quatro-bits", action="store_true", help="carrega em NF4 (bitsandbytes; CACA_LLM_4BIT=1)")
    ap.add_argument("--saida", type=Path, default=RAIZ / "saida_llm")
    ap.add_argument("--rapido", action="store_true", help="só os conjuntos-chave (padrão)")
    ap.add_argument("--completo", action="store_true", help="todos os conjuntos")
    ap.add_argument("--so", nargs="*", default=None, help="conjuntos explícitos")
    ap.add_argument("--sem-fumaca", action="store_true")
    ap.add_argument("--sem-medicao", action="store_true")
    ap.add_argument("--janelas", type=int, default=None, help="CACA_LLM_EXTRATOR_JANELAS")
    args = ap.parse_args()
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    args.saida.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    info = etapa_ambiente(args.saida)
    if not info.get("cuda_disponivel"):
        print("ERRO: torch com CUDA indisponível neste Python; use o venv com GPU (ver README §LLM)", file=sys.stderr)
        return 2
    modelo_fixo, rev_fixa = revisao_fixa()
    if args.id and not args.revisao:
        print("ERRO: --id exige --revisao (o commit dos pesos é o que torna a chave do cache reproduzível)", file=sys.stderr)
        return 2
    modelo, revisao, _pasta = etapa_pesos(args.modelo or modelo_fixo, args.revisao if args.revisao is not None else rev_fixa,
                                          args.saida, revisao_local=args.revisao or "", modelo_id=args.id or "",
                                          quatro_bits=args.quatro_bits)

    cache = args.saida / "cache_llm.sqlite"
    env = {"CACA_MODELO": modelo, "CACA_MODELO_REVISAO": revisao, "CACA_CACHE_LLM": str(cache),
           "HF_HOME": os.environ.get("HF_HOME", str(hf_home_padrao())), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "TOKENIZERS_PARALLELISM": "false", "CUBLAS_WORKSPACE_CONFIG": ":4096:8"}
    if args.id:
        env["CACA_MODELO_ID"] = args.id
    if args.quatro_bits:
        env["CACA_LLM_4BIT"] = "1"
    if args.janelas is not None:
        env["CACA_LLM_EXTRATOR_JANELAS"] = str(args.janelas)
    (args.saida / "ambiente_llm.env").write_text("".join(f'export {k}="{v}"\n' for k, v in env.items()), encoding="utf-8")

    if not args.sem_fumaca:
        r = rodar([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import rodar_llm_local as m; "
                   f"m.etapa_fumaca({json.dumps(env)})"], env, capturar=False)
        if r.returncode != 0:
            print("ERRO na fumaça: o modelo não carregou ou não respondeu; veja acima", file=sys.stderr)
            return 2

    if not args.sem_medicao:
        conjuntos = args.so or (None if args.completo else RAPIDO)
        cmd = [sys.executable, "scripts/comparar_arbitro.py", "--arbitro", "transformers", "--cache", str(cache),
               "--saida", str(args.saida / "comparacao")]
        if conjuntos:
            cmd += ["--so", *conjuntos]
        print("medição:", " ".join(cmd), flush=True)
        r = rodar(cmd, env, capturar=False)
        print(f"medição: código {r.returncode} (0 = LIGAR, 1 = MANTER DESLIGADO) ({time.time() - t0:.0f}s)")

    # dev com árbitro + submissão
    dev = args.saida / "dev_arbitro"
    r = rodar([sys.executable, "-m", "caca_alucinacao.cli", "--input", str(DADOS / "txt"), "--output", str(dev),
               "--db", str(DADOS / "desafio1_bracis.db"), "--indice", str(DADOS / "indice.json"), "--arbitro", "transformers",
               "--calibracao", str(DADOS / "calibracao.json"), "--rastro", str(dev / "rastro.jsonl"), "--log-level", "WARNING"], env)
    if r.returncode != 0:
        print("ERRO no dev com árbitro:\n" + (r.stdout + r.stderr)[-1500:], file=sys.stderr)
        return 2
    r = rodar([sys.executable, "scripts/avaliar.py", "--saida", str(dev), "--rastro", str(dev / "rastro.jsonl"),
               "--json", str(args.saida / "dev_arbitro.json")])
    print("\n".join(ln for ln in r.stdout.splitlines() if ln.startswith(("score_final", "Nível"))))
    r = rodar([sys.executable, "scripts/gerar_submissao.py", "--saida", str(dev), "--destino", str(args.saida / "submission_llm.csv")])
    print((r.stdout.strip().splitlines() or [""])[-1])

    # exportação do cache (reprodução sem GPU)
    from caca_alucinacao.llm.cache import CacheLLM  # noqa: WPS433
    n = CacheLLM(cache).exportar_jsonl(args.saida / "cache_llm.jsonl")
    print(f"cache exportado: {n} respostas em {args.saida / 'cache_llm.jsonl'} ({time.time() - t0:.0f}s no total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
