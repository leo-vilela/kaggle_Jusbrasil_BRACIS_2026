"""Retreino **completo e reproduzível** de ``dados/calibracao.json`` (ADR 0007, "Teto consolidado").

    python scripts/calibrar_completo.py                 # regenera tudo, retreina em saida_calibracao/calibracao.json
                                                        # e compara com dados/calibracao.json (não sobrescreve)
    python scripts/calibrar_completo.py --gravar        # idem, e grava em dados/calibracao.json
    python scripts/calibrar_completo.py --sem-gerar     # reaproveita dados/sinteticos e dados/adversarial existentes
    python scripts/calibrar_completo.py --cache-llm saida_llm_q35/cache_llm.jsonl   # com o árbitro real, só do cache

O que ele faz, na ordem:

1. gera os sintéticos (``n2_dev`` seed 123, ``n3_ood`` seed 7, ``n2_ag_treino`` seed 321; os mesmos de
   ``make sinteticos``) e os 34 conjuntos adversariais das revisões (``scripts/adversarial/gerar_*.py``,
   seeds padrão dos ``rodar_*.sh``) — tudo determinístico;
2. roda o pipeline com ``--rastro`` em cada conjunto: dev (26 docs) + 3 sintéticos + 34 adversariais =
   38 conjuntos. Sem ``--cache-llm``: núcleo (``--arbitro nenhum``). Com ``--cache-llm <jsonl>`` (o
   ``cache_llm.jsonl`` exportado por ``scripts/rodar_llm_local.py``): ``--arbitro transformers`` **só do
   cache** (``CACA_LLM_SOMENTE_CACHE=1``, zero chamadas, sem GPU; modelo e revisão de
   ``modelos/revisao_fixa.env``) — as extrações do modelo **real** entram no rastro e são a única
   evidência que treina os caminhos ``llm:*`` (decisões do ``mock`` nunca treinam; ADR 0003/0007);
   janela sem resposta no cache é abstenção (o documento fica como o regex deixou);
3. treina a tabela com ``scripts/treinar_calibracao.py`` sobre **37 conjuntos** e mantém ``n3_ood``
   **fora do ajuste**, como validação no nível do pipeline (``--validacao-rastro``); a calibração
   a partir do rastro (e não do catálogo) inclui os erros do detector, como a métrica. Com
   ``--cache-llm`` roda ainda um **diagnóstico fora da amostra dos caminhos ``llm:*``**: metade dos
   documentos de ``r6_extrator_formas`` (índices pares) treina e a outra metade valida
   (``treino_holdout_llm.log``; ``meta.holdout_llm`` na tabela) — a tabela final é a do treino completo;
4. compara a tabela obtida com a versionada (``dados/calibracao.json``): as tabelas têm de ser
   idênticas caminho a caminho e as contagens do ``meta`` também — só ``gerado_em`` pode diferir.
   Uma tabela treinada com ``--cache-llm`` registra o SHA-256 do JSONL em ``meta.cache_llm`` e só se
   reproduz com o mesmo arquivo (que acompanha a submissão, como ``dados/``; nunca é versionado).

Sai com 0 se a tabela reproduzida é idêntica à versionada (ou se ``--gravar``); 1 se difere ou se
alguma etapa falhou. Só biblioteca padrão (o pipeline e o treino também).
"""
from __future__ import annotations

import argparse
import hashlib
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
#: Conjunto cujo rastro é dividido por documento no diagnóstico fora da amostra dos caminhos ``llm:*``.
HOLDOUT_LLM = "r6_extrator_formas"
SINTETICOS = (  # = make sinteticos
    ("n2_dev", ["--n-docs", "40", "--nivel", "2", "--seed", "123", "--perfil", "dev"]),
    ("n3_ood", ["--n-docs", "40", "--nivel", "3", "--seed", "7"]),
    ("n2_ag_treino", ["--n-docs", "60", "--nivel", "2", "--seed", "321", "--perfil", "agressivo"]),
)
#: (gerador, seed padrão do rodar_*.sh, conjuntos que ele produz)
ADVERSARIAIS = (
    ("gerar_adversarial.py", 2026, ["siglas", "conectores", "ruido_n2", "vagas", "distratores", "frases", "cabecalhos", "normativos"]),
    ("gerar_adversarial_r2.py", 7777, ["r2_chave_parcial", "r2_normativos_ruido", "r2_vagas_ordem", "r2_processos_forma",
                                       "r2_duplicatas", "r2_listas", "r2_fora_da_base"]),
    ("gerar_adversarial_r3.py", 333, ["r3_atos_normativos", "r3_enumeracoes", "r3_vagas_redacao", "r3_sumulas_forma",
                                      "r3_dispositivos_forma", "r3_caps_corpo", "r3_prefixo_tribunal"]),
    ("gerar_adversarial_r4.py", 444, ["r4_vagas_relator_antes", "r4_ocr_duplo", "r4_cabecalhos_novos", "r4_negativas_vizinhas"]),
    ("gerar_adversarial_r5.py", 555, ["r5_vagas_lavra_final", "r5_processos_plural_nos", "r5_normativos_ocr",
                                      "r5_processos_ocr_combo", "r5_distratores_orgaos", "r5_layouts"]),
    ("gerar_adversarial_r6.py", 666, ["r6_extrator_formas", "r6_extrator_distratores"]),
)
VALIDACAO = ("n3_ood",)  # nunca entra no ajuste (ADR 0007 §6)


def rodar(cmd: list[str], env_extra: dict[str, str] | None = None, **kw) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(RAIZ / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=str(RAIZ), env=env, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, check=False, **kw)


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def ambiente_cache_llm(cache_llm: Path, pasta_cache: Path) -> dict[str, str]:
    """Variáveis para o pipeline rodar o árbitro **só do cache** (como ``scripts/reproduzir.py``): modelo,
    revisão fixa e quantização de ``modelos/revisao_fixa.env`` (a chave do cache inclui os três),
    ``CACA_LLM_SOMENTE_CACHE=1``, ``CACA_LLM_CACHE_IMPORTAR=<jsonl>`` e um SQLite próprio por execução (fora do
    repositório)."""
    env: dict[str, str] = {}
    fixo = RAIZ / "modelos" / "revisao_fixa.env"
    if fixo.exists():
        for linha in fixo.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*export\s+(CACA_MODELO|CACA_MODELO_REVISAO|CACA_LLM_4BIT)="([^"]*)"', linha)
            if m and os.environ.get(m.group(1)) is None:
                env[m.group(1)] = m.group(2)
    env["CACA_LLM_SOMENTE_CACHE"] = "1"
    env["CACA_LLM_CACHE_IMPORTAR"] = str(cache_llm.resolve())
    env["CACA_CACHE_LLM"] = str(pasta_cache / "cache_llm.sqlite")
    return env


def dividir_rastro_por_documento(rastro: Path, destino: Path) -> tuple[Path, Path, int, int]:
    """Divide o rastro em dois arquivos pelos documentos (ordenados): índices pares → treino, ímpares →
    validação. Devolve ``(treino, validacao, n_docs_treino, n_docs_validacao)``."""
    linhas = [ln for ln in rastro.read_text(encoding="utf-8").splitlines() if ln.strip()]
    docs = sorted({json.loads(ln)["documento_id"] for ln in linhas})
    treino_docs, val_docs = set(docs[0::2]), set(docs[1::2])
    treino, val = destino / "rastro_treino.jsonl", destino / "rastro_validacao.jsonl"
    with treino.open("w", encoding="utf-8") as ft, val.open("w", encoding="utf-8") as fv:
        for ln in linhas:
            (ft if json.loads(ln)["documento_id"] in treino_docs else fv).write(ln + "\n")
    return treino, val, len(treino_docs), len(val_docs)


def falhar(msg: str, r: subprocess.CompletedProcess | None = None) -> int:
    print("FALHOU:", msg)
    if r is not None:
        print((r.stdout + r.stderr)[-2000:])
    return 1


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", type=Path, default=RAIZ / "saida_calibracao", help="pasta de trabalho (recriada)")
    ap.add_argument("--gravar", action="store_true", help="grava a tabela em dados/calibracao.json (senão só compara)")
    ap.add_argument("--sem-gerar", action="store_true", help="não regenera sintéticos/adversariais existentes")
    ap.add_argument("--referencia", type=Path, default=DADOS / "calibracao.json")
    ap.add_argument("--cache-llm", type=Path, default=None,
                    help="cache_llm.jsonl exportado da medição com o modelo real: roda cada conjunto com --arbitro "
                         "transformers só do cache (sem GPU) e treina os caminhos llm:* com as extrações reais")
    args = ap.parse_args()
    if args.cache_llm is not None and not args.cache_llm.is_file():
        return falhar(f"--cache-llm: {args.cache_llm} não existe (exporte com scripts/rodar_llm_local.py)")
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    py = sys.executable
    t0 = time.time()
    db, indice = DADOS / "desafio1_bracis.db", DADOS / "indice.json"
    if not db.exists() or not (DADOS / "txt").is_dir() or not (DADOS / "goldenset.csv").exists():
        return falhar("dados/ incompleto (db, txt/, goldenset.csv) — rode `make dados ZIP=...`")
    if not indice.exists():
        r = rodar([py, "scripts/construir_indice.py", "--db", str(db), "--saida", str(indice)])
        if r.returncode != 0:
            return falhar("construir_indice.py", r)

    # 1. conjuntos ---------------------------------------------------------------------------
    for nome, extra in SINTETICOS:
        pasta = DADOS / "sinteticos" / nome
        if args.sem_gerar and pasta.is_dir():
            continue
        r = rodar([py, "scripts/gerar_sinteticos.py", "--saida", str(pasta), *extra])
        if r.returncode != 0:
            return falhar(f"gerar_sinteticos.py ({nome})", r)
    for gerador, seed, conjuntos in ADVERSARIAIS:
        if args.sem_gerar and all((DADOS / "adversarial" / c / "goldenset.csv").exists() for c in conjuntos):
            continue
        r = rodar([py, f"scripts/adversarial/{gerador}", "--seed", str(seed), "--indice", str(indice)])
        if r.returncode != 0:
            return falhar(gerador, r)
    conjuntos: list[tuple[str, Path, Path]] = [("dev", DADOS / "txt", DADOS / "goldenset.csv")]
    conjuntos += [(n, DADOS / "sinteticos" / n / "txt", DADOS / "sinteticos" / n / "goldenset.csv") for n, _ in SINTETICOS]
    conjuntos += [(c, DADOS / "adversarial" / c / "txt", DADOS / "adversarial" / c / "goldenset.csv")
                  for _, _, cs in ADVERSARIAIS for c in cs]
    for nome, txt, gab in conjuntos:
        if not txt.is_dir() or not gab.exists():
            return falhar(f"conjunto {nome} sem txt/ ou goldenset.csv ({txt}, {gab})")
    print(f"{len(conjuntos)} conjuntos ({time.time() - t0:.0f}s)")

    # 2. pipeline com rastro em cada conjunto --------------------------------------------------
    args.saida = pasta_limpa(args.saida)
    arbitro, env_llm = "nenhum", None
    if args.cache_llm is not None:
        arbitro = "transformers"
        env_llm = ambiente_cache_llm(args.cache_llm, Path(tempfile.mkdtemp(prefix="caca_cal_cache_llm_")))
        print(f"árbitro só do cache: {args.cache_llm} (sha256 {sha256(args.cache_llm)[:16]}…; modelo "
              f"{env_llm.get('CACA_MODELO', os.environ.get('CACA_MODELO', '?'))})")
    rastros: dict[str, tuple[Path, Path]] = {}
    llm_emitidas: dict[str, int] = {}
    for nome, txt, gab in conjuntos:
        pasta = args.saida / f"cal_{nome}"
        r = rodar([py, "-m", "caca_alucinacao.cli", "--input", str(txt), "--output", str(pasta), "--db", str(db),
                   "--indice", str(indice), "--arbitro", arbitro, "--calibracao", str(args.referencia),
                   "--rastro", str(pasta / "rastro.jsonl"), "--log-level", "ERROR"], env_llm)
        if r.returncode != 0:
            return falhar(f"pipeline em {nome}", r)
        rastros[nome] = (pasta / "rastro.jsonl", gab)
        if env_llm is not None:
            est = {}
            try:
                est = json.loads((pasta / "arbitro_estatisticas.log").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if est.get("chamadas_ao_modelo", 0) != 0 or not (est.get("cache") or {}).get("ativo"):
                return falhar(f"{nome}: o árbitro deveria responder só do cache (chamadas={est.get('chamadas_ao_modelo')}, "
                              f"cache ativo={(est.get('cache') or {}).get('ativo')})")
            n_llm = sum(1 for ln in (pasta / "rastro.jsonl").read_text(encoding="utf-8").splitlines()
                        if ln.strip() and '"llm:extrator:' in ln and json.loads(ln).get("status") == "emitida")
            if n_llm:
                llm_emitidas[nome] = n_llm
    print(f"pipeline rodado em {len(rastros)} conjuntos ({time.time() - t0:.0f}s)"
          + (f"; extrações do modelo real no rastro: {llm_emitidas or 'nenhuma'}" if env_llm is not None else ""))

    # 3. treino (todos menos n3_ood) + validação (n3_ood) ------------------------------------------------------
    treino = [n for n in rastros if n not in VALIDACAO]
    destino = args.referencia if args.gravar else args.saida / "calibracao.json"
    cmd = [py, "scripts/treinar_calibracao.py", "--sem-catalogo", "--saida", str(destino),
           "--rastro", *[str(rastros[n][0]) for n in treino], "--gabarito", *[str(rastros[n][1]) for n in treino],
           "--validacao-rastro", *[str(rastros[n][0]) for n in VALIDACAO],
           "--validacao-gabarito", *[str(rastros[n][1]) for n in VALIDACAO]]
    r = rodar(cmd)
    if r.returncode != 0:
        return falhar("treinar_calibracao.py", r)
    (args.saida / "treino.log").write_text(r.stdout, encoding="utf-8")
    resumo = [ln for ln in r.stdout.splitlines() if ln.startswith(("  TOTAL", "  validacao", "Treino", "Validação", "tabela com"))]
    print("\n".join(resumo))

    # 3b. diagnóstico fora da amostra dos caminhos llm:* (metade dos documentos de r6_extrator_formas) ---------
    holdout: dict | None = None
    if env_llm is not None and HOLDOUT_LLM in rastros and HOLDOUT_LLM in llm_emitidas:
        pasta_h = args.saida / "holdout_llm"
        pasta_h.mkdir(exist_ok=True)
        r_tr, r_val, n_tr, n_val = dividir_rastro_por_documento(rastros[HOLDOUT_LLM][0], pasta_h)
        gab_h = rastros[HOLDOUT_LLM][1]
        tr_h = [n for n in treino if n != HOLDOUT_LLM]
        cmd_h = [py, "scripts/treinar_calibracao.py", "--sem-catalogo", "--saida", str(pasta_h / "calibracao_holdout.json"),
                 "--rastro", *[str(rastros[n][0]) for n in tr_h], str(r_tr),
                 "--gabarito", *[str(rastros[n][1]) for n in tr_h], str(gab_h),
                 "--validacao-rastro", str(r_val), *[str(rastros[n][0]) for n in VALIDACAO],
                 "--validacao-gabarito", str(gab_h), *[str(rastros[n][1]) for n in VALIDACAO]]
        rh = rodar(cmd_h)
        if rh.returncode != 0:
            return falhar("treinar_calibracao.py (holdout llm)", rh)
        (args.saida / "treino_holdout_llm.log").write_text(rh.stdout, encoding="utf-8")
        meta_h = json.loads((pasta_h / "calibracao_holdout.json").read_text(encoding="utf-8"))["meta"]
        val_h = next((v for v in meta_h["validacao"] if v["nome"].endswith(r_val.name)), None)
        if val_h is None:
            return falhar("holdout llm: validação ausente no meta")
        holdout = {"conjunto": HOLDOUT_LLM, "documentos_treino": n_tr, "documentos_validacao": n_val,
                   "validacao": {k: val_h[k] for k in ("n", "acertos", "brier_antes", "brier_depois")}}
        print(f"holdout llm ({HOLDOUT_LLM}: {n_tr} docs treinam, {n_val} validam): n={val_h['n']} acertos={val_h['acertos']} "
              f"Brier {val_h['brier_antes']:.4f} → {val_h['brier_depois']:.4f}")
        if val_h["brier_depois"] > val_h["brier_antes"]:
            return falhar("holdout llm: o Brier fora da amostra piorou com o ajuste")

    # 3c. proveniência do cache no meta (a tabela só se reproduz com o mesmo JSONL) ----------------
    if env_llm is not None:
        conteudo = json.loads(destino.read_text(encoding="utf-8"))
        conteudo["meta"]["cache_llm"] = {"arquivo": args.cache_llm.name, "sha256": sha256(args.cache_llm),
                                         "modelo": env_llm.get("CACA_MODELO", os.environ.get("CACA_MODELO", "")),
                                         "revisao": env_llm.get("CACA_MODELO_REVISAO", os.environ.get("CACA_MODELO_REVISAO", "")),
                                         "quatro_bits": env_llm.get("CACA_LLM_4BIT", os.environ.get("CACA_LLM_4BIT", "")) in ("1", "true", "sim", "yes", "on"),
                                         "extracoes_por_conjunto": llm_emitidas}
        if holdout is not None:
            conteudo["meta"]["holdout_llm"] = holdout
        destino.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    # 4. comparação com a tabela versionada ----------------------------------------------------
    novo = json.loads(destino.read_text(encoding="utf-8"))
    print(f"\ntabela: {len(novo['tabela'])} caminhos; consolidados (> teto 0,98): {len(novo['meta'].get('caminhos_consolidados', []))}; "
          f"validação: {[(v['nome'], v['n'], v['acertos'], round(v['brier_depois'], 5)) for v in novo['meta']['validacao']]}")
    if args.gravar:
        print(f"gravada em {destino} ({time.time() - t0:.0f}s)")
        return 0
    if not args.referencia.exists():
        return falhar(f"referência ausente: {args.referencia}")
    ref = json.loads(args.referencia.read_text(encoding="utf-8"))
    dif_tabela = sorted(k for k in set(ref["tabela"]) | set(novo["tabela"]) if ref["tabela"].get(k) != novo["tabela"].get(k))
    campos = ("fontes", "validacao", "contagens", "brier_treino_antes", "brier_treino_depois", "caminhos_consolidados",
              "cache_llm", "holdout_llm")
    dif_meta = [c for c in campos if ref["meta"].get(c) != novo["meta"].get(c)]
    if dif_tabela or dif_meta:
        print(f"DIFERE da tabela versionada — caminhos: {dif_tabela[:15]}; meta: {dif_meta} ({time.time() - t0:.0f}s)")
        ref_cache = (ref["meta"].get("cache_llm") or {})
        if ref_cache and env_llm is None:
            print(f"  a tabela versionada foi treinada com --cache-llm ({ref_cache.get('arquivo')}, sha256 "
                  f"{str(ref_cache.get('sha256', ''))[:16]}…): passe o mesmo JSONL para reproduzi-la")
        elif env_llm is not None and not ref_cache:
            print("  a tabela versionada foi treinada sem --cache-llm (caminhos llm:* nos priors)")
        elif env_llm is not None and ref_cache.get("sha256") != novo["meta"]["cache_llm"]["sha256"]:
            print("  o JSONL do cache difere do que treinou a tabela versionada (sha256)")
        return 1
    print(f"REPRODUZIDA: tabela e meta idênticos a {args.referencia.name} (só gerado_em difere) ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
