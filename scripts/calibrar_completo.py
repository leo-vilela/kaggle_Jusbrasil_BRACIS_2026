"""Retreino **completo e reproduzível** de ``dados/calibracao.json`` (ADR 0007, "Teto consolidado").

    python scripts/calibrar_completo.py                 # regenera tudo, retreina em saida_calibracao/calibracao.json
                                                        # e compara com dados/calibracao.json (não sobrescreve)
    python scripts/calibrar_completo.py --gravar        # idem, e grava em dados/calibracao.json
    python scripts/calibrar_completo.py --sem-gerar     # reaproveita dados/sinteticos e dados/adversarial existentes

O que ele faz, na ordem:

1. gera os sintéticos (``n2_dev`` seed 123, ``n3_ood`` seed 7, ``n2_ag_treino`` seed 321; os mesmos de
   ``make sinteticos``) e os 34 conjuntos adversariais das revisões (``scripts/adversarial/gerar_*.py``,
   seeds padrão dos ``rodar_*.sh``) — tudo determinístico;
2. roda o pipeline (núcleo, ``--arbitro nenhum``) com ``--rastro`` em cada conjunto: dev (26 docs) +
   3 sintéticos + 34 adversariais = 38 conjuntos;
3. treina a tabela com ``scripts/treinar_calibracao.py`` sobre **37 conjuntos** e mantém ``n3_ood``
   **fora do ajuste**, como validação no nível do pipeline (``--validacao-rastro``); a calibração
   a partir do rastro (e não do catálogo) inclui os erros do detector, como a métrica;
4. compara a tabela obtida com a versionada (``dados/calibracao.json``): as tabelas têm de ser
   idênticas caminho a caminho e as contagens do ``meta`` também — só ``gerado_em`` pode diferir.

Sai com 0 se a tabela reproduzida é idêntica à versionada (ou se ``--gravar``); 1 se difere ou se
alguma etapa falhou. Só biblioteca padrão (o pipeline e o treino também).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dados"
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


def rodar(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ, PYTHONPATH=str(RAIZ / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, cwd=str(RAIZ), env=env, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, check=False, **kw)


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
    args = ap.parse_args()
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
    rastros: dict[str, tuple[Path, Path]] = {}
    for nome, txt, gab in conjuntos:
        pasta = args.saida / f"cal_{nome}"
        r = rodar([py, "-m", "caca_alucinacao.cli", "--input", str(txt), "--output", str(pasta), "--db", str(db),
                   "--indice", str(indice), "--arbitro", "nenhum", "--calibracao", str(args.referencia),
                   "--rastro", str(pasta / "rastro.jsonl"), "--log-level", "ERROR"])
        if r.returncode != 0:
            return falhar(f"pipeline em {nome}", r)
        rastros[nome] = (pasta / "rastro.jsonl", gab)
    print(f"pipeline rodado em {len(rastros)} conjuntos ({time.time() - t0:.0f}s)")

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
    campos = ("fontes", "validacao", "contagens", "brier_treino_antes", "brier_treino_depois", "caminhos_consolidados")
    dif_meta = [c for c in campos if ref["meta"].get(c) != novo["meta"].get(c)]
    if dif_tabela or dif_meta:
        print(f"DIFERE da tabela versionada — caminhos: {dif_tabela[:15]}; meta: {dif_meta} ({time.time() - t0:.0f}s)")
        return 1
    print(f"REPRODUZIDA: tabela e meta idênticos a {args.referencia.name} (só gerado_em difere) ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
