"""Configuração central: constantes do contrato, caminhos padrão e semente.

Tudo o que depende do ambiente é lido de variáveis ``CACA_*`` (com padrão
sensato para o repositório e para o container da organização). Nenhum módulo
do pacote deve ler ``os.environ`` diretamente: use as funções daqui.

Variáveis reconhecidas:

* ``CACA_DB`` — caminho do SQLite ``desafio1_bracis.db``;
* ``CACA_INDICE`` — caminho do índice JSON de números próprios (opcional; se
  não existir, o índice é construído do banco em memória);
* ``CACA_CALIBRACAO`` — tabela JSON ``{caminho: confiança}``;
* ``CACA_MODELO_DIR`` — diretório local com os pesos do árbitro LLM (snapshot
  ou cache do Hugging Face em ``<dir>/hf``); ``CACA_MODELO`` (nome/caminho do
  modelo), ``CACA_MODELO_REVISAO`` (commit), ``CACA_LLM_LOTE``;
* ``CACA_CACHE_LLM`` — arquivo SQLite do cache das respostas do árbitro;
* ``CACA_ARBITRO`` — backend padrão do árbitro (``nenhum`` | ``mock`` |
  ``transformers`` | ``vllm``);
* ``PYTHONHASHSEED`` — fixado em ``0`` no Dockerfile (determinismo).
"""
from __future__ import annotations

import os
import random
from pathlib import Path

# --- contrato -----------------------------------------------------------------
SCHEMA_VERSION = "1.2"
FONTE = "jusbrasil"
IOU_MIN = 0.5                     # limiar de sobreposição da métrica oficial (erro fatal)
CONFIANCA_PADRAO = 0.5            # usada quando a calibração não está disponível
CONFIANCA_TETO = 0.98             # nunca 1,0 (docs/03 §9.4)
# Teto "consolidado": só para caminhos com evidência massiva (≥ N_MINIMO_CONSOLIDADO decisões
# avaliadas, 0 erros, fora de CAMINHOS_SEM_TREINO; a média a posteriori de Laplace com prior 0,98 e
# k = 4 já passa de 0,999 em n = 100). Brier de um acerto a 0,998 = 0,000004; o custo de
# um erro (0,996) é praticamente o mesmo de 0,98 (0,96) — ver ADR 0007 §"teto consolidado".
CONFIANCA_TETO_CONSOLIDADO = 0.998
N_MINIMO_CONSOLIDADO = 100
CONFIANCA_PISO = 0.02
ARBITROS = ("nenhum", "mock", "transformers", "vllm")

# --- determinismo -------------------------------------------------------------
SEED = 0

# --- caminhos -----------------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "dados"
FERRAMENTAS = DADOS / "ferramentas"

# Contrato de execução da organização (docker run ... -v <db>:/data/base/desafio1_bracis.db:ro)
DOCKER_ENTRADA = Path("/data/in")
DOCKER_SAIDA = Path("/data/out")
DOCKER_DB = Path("/data/base/desafio1_bracis.db")

ENVELOPE_SEGUNDOS_POR_DOC = 60.0  # média máxima por documento exigida pelo desafio


def _caminho_env(nome: str, padrao: Path) -> Path:
    valor = os.environ.get(nome)
    return Path(valor).expanduser() if valor else padrao


def caminho_db() -> Path:
    """Banco SQLite: ``CACA_DB`` → ``dados/desafio1_bracis.db`` → ``/data/base/...``."""
    padrao = DADOS / "desafio1_bracis.db"
    if not padrao.exists() and DOCKER_DB.exists():
        padrao = DOCKER_DB
    return _caminho_env("CACA_DB", padrao)


def caminho_indice() -> Path:
    """Índice JSON de números próprios (pode não existir)."""
    return _caminho_env("CACA_INDICE", DADOS / "indice.json")


def caminho_calibracao() -> Path:
    """Tabela de calibração ``{caminho: confiança}`` (pode não existir)."""
    return _caminho_env("CACA_CALIBRACAO", DADOS / "calibracao.json")


def caminho_modelo() -> Path:
    """Diretório local dos pesos do árbitro LLM (``CACA_MODELO_DIR``; padrão ``modelos/``).

    Duas formas são aceitas por :func:`modelo_llm`/:func:`preparar_ambiente_hf`:
    um *snapshot* (a pasta contém ``config.json``) — usado diretamente como nome
    do modelo — ou um cache do Hugging Face em ``<dir>/hf`` (o que
    ``scripts/baixar_modelo.sh`` produz) — vira ``HF_HOME`` quando ``HF_HOME``
    não está definido.
    """
    return _caminho_env("CACA_MODELO_DIR", RAIZ / "modelos")


def modelo_llm(padrao: str) -> str:
    """Nome ou caminho do modelo: ``CACA_MODELO``, senão o snapshot em ``CACA_MODELO_DIR``, senão ``padrao``."""
    valor = os.environ.get("CACA_MODELO")
    if valor:
        return valor
    d = caminho_modelo()
    if (d / "config.json").exists():
        return str(d)
    return padrao


def revisao_llm() -> str:
    """Commit dos pesos (``CACA_MODELO_REVISAO``; vazio = não fixado)."""
    return os.environ.get("CACA_MODELO_REVISAO", "").strip()


def lote_llm() -> int | None:
    """Tamanho do lote do árbitro (``CACA_LLM_LOTE``), ou ``None`` para o padrão do backend."""
    valor = os.environ.get("CACA_LLM_LOTE", "").strip()
    return int(valor) if valor.isdigit() else None


def preparar_ambiente_hf() -> Path | None:
    """Aponta ``HF_HOME`` para ``<CACA_MODELO_DIR>/hf`` quando existe e ``HF_HOME`` não está definido.

    É o que faz ``docker run -v <pesos>:/modelos:ro`` funcionar offline sem exportar
    ``HF_HOME`` à mão (revisão R3-03). Devolve o caminho usado, ou ``None``.
    """
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"])
    hf = caminho_modelo() / "hf"
    if hf.is_dir():
        os.environ["HF_HOME"] = str(hf)
        return hf
    return None


def caminho_cache_llm() -> Path:
    """Cache em disco das respostas do árbitro (hash do prompt → resposta): ``CACA_CACHE_LLM``
    ou ``<raiz>/cache_llm/arbitro_llm.sqlite``."""
    return _caminho_env("CACA_CACHE_LLM", RAIZ / "cache_llm" / "arbitro_llm.sqlite")


def arbitro_padrao() -> str:
    """Backend padrão do árbitro (``CACA_ARBITRO``; ``nenhum`` se ausente/inválido)."""
    valor = os.environ.get("CACA_ARBITRO", "nenhum").strip().lower()
    return valor if valor in ARBITROS else "nenhum"


def fixar_semente(seed: int = SEED, com_bibliotecas: bool = True) -> None:
    """Fixa as sementes disponíveis (``random``; ``numpy``/``torch`` se instalados e ``com_bibliotecas``).

    O núcleo determinístico não usa numpy nem torch: com ``com_bibliotecas=False`` (CLI com
    ``--arbitro nenhum``) nada é importado — importar torch numa imagem com CUDA custa segundos
    e inicializa o que não será usado (rodada 3, R3e-09)."""
    random.seed(seed)
    if not com_bibliotecas:
        return
    try:  # opcionais — nunca obrigatórios no núcleo
        import numpy  # type: ignore

        numpy.random.seed(seed)
    except Exception:
        pass
    try:
        import torch  # type: ignore

        torch.manual_seed(seed)
    except Exception:
        pass


__all__ = [
    "SCHEMA_VERSION", "FONTE", "IOU_MIN", "CONFIANCA_PADRAO", "CONFIANCA_TETO",
    "CONFIANCA_TETO_CONSOLIDADO", "N_MINIMO_CONSOLIDADO",
    "CONFIANCA_PISO", "ARBITROS", "SEED", "RAIZ", "DADOS", "FERRAMENTAS",
    "DOCKER_ENTRADA", "DOCKER_SAIDA", "DOCKER_DB", "ENVELOPE_SEGUNDOS_POR_DOC",
    "caminho_db", "caminho_indice", "caminho_calibracao", "caminho_modelo", "modelo_llm",
    "revisao_llm", "lote_llm", "preparar_ambiente_hf", "caminho_cache_llm", "arbitro_padrao",
    "fixar_semente",
]
