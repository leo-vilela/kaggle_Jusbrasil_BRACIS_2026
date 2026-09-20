"""Linha de comando: ``python -m caca_alucinacao.cli --input <txt/> --output <json/> --db <db>``.

Contrato de execução da organização (container offline)::

    docker run --rm --network none \\
      -v <txt>:/data/in:ro -v <saida>:/data/out \\
      -v <db>:/data/base/desafio1_bracis.db:ro \\
      <imagem> --input /data/in --output /data/out

Fluxo: carrega a base (índice JSON se existir; senão constrói do SQLite em
memória, opcionalmente salvando), o árbitro LLM (``--arbitro``; padrão
``CACA_ARBITRO`` ou ``nenhum``) e a tabela de calibração; processa a pasta e
mede o tempo por documento (envelope: média ≤ 60 s/doc).
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from . import config
from .pipeline import ErroPipeline, listar_documentos, preparar_saida, processar_pasta

log = logging.getLogger("caca_alucinacao.cli")


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m caca_alucinacao.cli",
        description="Verificador de citações jurídicas — gera um JSON (schema 1.2) por .txt.",
    )
    p.add_argument("--input", required=True, type=Path, help="pasta com os .txt (um por documento)")
    p.add_argument("--output", required=True, type=Path, help="pasta de saída dos .json")
    p.add_argument("--db", type=Path, default=None,
                   help=f"SQLite da base canônica (padrão: CACA_DB, {config.DADOS / 'desafio1_bracis.db'} "
                        f"ou {config.DOCKER_DB})")
    p.add_argument("--indice", type=Path, default=None,
                   help="índice JSON de números próprios; se não existir, é construído do banco em memória "
                        "(padrão: CACA_INDICE)")
    p.add_argument("--salvar-indice", action="store_true",
                   help="grava o índice construído no caminho de --indice")
    p.add_argument("--arbitro", choices=config.ARBITROS, default=None,
                   help=f"backend do árbitro LLM (padrão: CACA_ARBITRO ou 'nenhum'; atual: "
                        f"{config.arbitro_padrao()})")
    p.add_argument("--calibracao", type=Path, default=None,
                   help="tabela JSON {caminho: confiança} (padrão: CACA_CALIBRACAO)")
    p.add_argument("--rastro", type=Path, default=None,
                   help="grava um JSONL com o caminho de decisão de cada achado")
    p.add_argument("--limite", type=int, default=None, help="processa só os N primeiros documentos")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="nível de log (stderr)")
    return p


def configurar_logging(nivel: str) -> None:
    logging.basicConfig(
        level=getattr(logging, nivel),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )


def carregar_base(db: Path | None, indice: Path | None, salvar: bool = False) -> Any:
    """Índice JSON se existir e for compatível; senão constrói do banco (em memória)."""
    from .base_canonica import BaseCanonica, carregar_indice, construir_indice, indice_corresponde_ao_banco, salvar_indice

    if indice is not None and indice.exists():
        try:
            dados_indice = carregar_indice(indice)
            # impressão digital do banco (rodada 3, R3e-07): um desafio1_bracis.db redistribuído com
            # outro conteúdo não pode ser lido por um índice antigo em silêncio
            corresponde = indice_corresponde_ao_banco(dados_indice, db) if db is not None and db.exists() else None
            if corresponde is False:
                log.warning("índice %s foi construído de outro banco (SHA-256 diferente de %s); reconstruindo", indice, db)
            else:
                if corresponde is None and db is not None and db.exists():
                    log.info("índice %s sem impressão do banco; não é possível conferir se corresponde a %s", indice, db)
                base = BaseCanonica(dados_indice)
                log.info("índice carregado de %s (%d registros)", indice, len(base))
                return base
        except (ValueError, KeyError, OSError) as exc:
            log.warning("índice %s incompatível/ilegível (%s); reconstruindo do banco", indice, exc)
    if db is None or not db.exists():
        raise ErroPipeline(f"banco não encontrado: {db} (use --db, CACA_DB ou monte em {config.DOCKER_DB})")
    t0 = time.perf_counter()
    try:
        dados = construir_indice(db)
    except sqlite3.Error as exc:
        # banco corrompido / arquivo que não é SQLite: erro claro, código 2 (revisão R3-07)
        raise ErroPipeline(f"banco {db} ilegível como SQLite ({exc}); confira o volume montado "
                           f"em {config.DOCKER_DB}") from exc
    except OSError as exc:
        raise ErroPipeline(f"não foi possível ler o banco {db}: {exc}") from exc
    log.info("índice construído de %s em %.1fs", db, time.perf_counter() - t0)
    if salvar and indice is not None:
        try:
            salvar_indice(dados, indice)
            log.info("índice salvo em %s", indice)
        except OSError as exc:
            log.warning("não foi possível salvar o índice em %s: %s", indice, exc)
    return BaseCanonica(dados)


def carregar_calibracao(caminho: Path | None) -> dict[str, float] | None:
    """``{caminho: confiança}``; aceita também ``{"tabela": {...}}``. ``None`` se ausente."""
    if caminho is None or not caminho.exists():
        log.info("sem tabela de calibração (%s); confiança padrão %.2f", caminho, config.CONFIANCA_PADRAO)
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ErroPipeline(f"tabela de calibração {caminho} ilegível ({exc}); corrija o JSON ou "
                           f"remova o arquivo para usar a confiança padrão") from exc
    tabela = dados.get("tabela", dados) if isinstance(dados, dict) else {}
    tabela = {str(k): float(v) for k, v in tabela.items() if isinstance(v, (int, float))}
    log.info("calibração carregada de %s (%d caminhos)", caminho, len(tabela))
    return tabela


def criar_arbitro(nome: str) -> Any:
    """``nenhum`` → ``None``; senão ``caca_alucinacao.llm.obter_arbitro(nome)`` (import tardio).

    O backend lê a própria configuração do ambiente (``CACA_CACHE_LLM``,
    ``CACA_MODELO``, ``CACA_MODELO_REVISAO`` …); dependência ausente, nome
    desconhecido ou falha na carga dos pesos viram ``None`` com log ERROR
    (a promessa "qualquer falha do árbitro = abstenção" vale também para a carga).
    """
    if nome == "nenhum":
        return None
    try:
        from .llm import obter_arbitro

        return obter_arbitro(nome)
    except Exception as exc:   # ErroDependencia (ImportError), ValueError, OSError (snapshot ausente), RuntimeError (CUDA)…
        # Qualquer falha ao CARREGAR o árbitro recua para o núcleo determinístico (rodada 3, R3e-01):
        # o árbitro é residual e opcional por desenho; abortar aqui deixaria a submissão vazia,
        # enquanto o núcleo sozinho entrega quase todo o resultado. Fica registrado como ERROR.
        log.error("árbitro '%s' indisponível (%s: %s); seguindo com o núcleo determinístico, sem árbitro",
                  nome, type(exc).__name__, exc)
        return None


def registrar_estatisticas_do_arbitro(arbitro: Any, saida: Path) -> None:
    """Loga ``arbitro.estatisticas()`` (chamadas, abstenções, cache) e grava ``arbitro_estatisticas.log``
    (conteúdo JSON) ao lado dos JSONs — necessário para auditar o envelope de 60 s/doc com o LLM
    ligado (R3e-09). Nunca ``.json``: o conversor oficial lê ``*.json`` da pasta como documentos."""
    try:
        stats = arbitro.estatisticas()
    except Exception as exc:   # o árbitro nunca derruba o lote
        log.warning("estatísticas do árbitro indisponíveis: %s", exc)
        return
    log.info("árbitro: %s", json.dumps(stats, ensure_ascii=False, sort_keys=True, default=str))
    try:
        (Path(saida) / "arbitro_estatisticas.log").write_text(
            json.dumps(stats, ensure_ascii=False, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("não foi possível gravar arbitro_estatisticas.log: %s", exc)


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    configurar_logging(args.log_level)
    nome_arbitro = args.arbitro if args.arbitro is not None else config.arbitro_padrao()
    # numpy/torch só são semeados quando o árbitro os usa: importá-los com ``--arbitro nenhum`` custa
    # segundos na imagem com CUDA e não muda nada no núcleo (rodada 3, R3e-09)
    config.fixar_semente(com_bibliotecas=nome_arbitro != "nenhum")

    db = args.db if args.db is not None else config.caminho_db()
    indice = args.indice if args.indice is not None else config.caminho_indice()
    calibracao = args.calibracao if args.calibracao is not None else config.caminho_calibracao()

    t_inicio = time.perf_counter()
    try:
        documentos = listar_documentos(args.input)
        base = carregar_base(db, indice, salvar=args.salvar_indice)
        arbitro = criar_arbitro(nome_arbitro)
        tabela = carregar_calibracao(calibracao)
        preparar_saida(args.output)   # antes de processar: pasta de saída gravável? (R3-02)
    except ErroPipeline as exc:
        log.error("%s", exc)
        return 2
    if not documentos:
        # lote vazio (pasta-mãe montada no lugar da dos .txt, ou pasta errada): rc 2, nunca um
        # "sucesso" com zero JSONs que um harness da organização não perceberia (rodada 4, R3q-08)
        log.error("nenhum documento .txt em %s: nada a processar (código de saída 2)", args.input)
        return 2
    log.info("%d documentos em %s; árbitro=%s; saída em %s", len(documentos), args.input,
             nome_arbitro, args.output)

    try:
        escritos = processar_pasta(
            args.input, args.output, base, arbitro=arbitro, tabela_calibracao=tabela,
            rastro_para=args.rastro, limite=args.limite, arquivos=documentos,
        )
    except ErroPipeline as exc:   # componente ausente (detector/resolvedor) — erro de integração
        log.error("%s", exc)
        return 2
    total = time.perf_counter() - t_inicio
    n = max(1, len(escritos))
    log.info("concluído: %d JSONs em %.1fs (%.2fs/doc incluindo carga da base)", len(escritos), total, total / n)
    if arbitro is not None:
        registrar_estatisticas_do_arbitro(arbitro, args.output)
    if total / n > config.ENVELOPE_SEGUNDOS_POR_DOC:
        log.warning("tempo médio %.1fs/doc acima do envelope de %.0fs/doc", total / n,
                    config.ENVELOPE_SEGUNDOS_POR_DOC)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
