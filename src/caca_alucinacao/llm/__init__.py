"""Árbitro LLM de pesos abertos para os casos residuais do verificador.

Uso mínimo::

    from caca_alucinacao.llm import obter_arbitro

    arbitro = obter_arbitro("mock")                  # ou "transformers", "vllm", "nenhum" → None
    r = arbitro.normalizar_citacao(trecho, contexto) # dict | None (abstenção)
    i = arbitro.escolher_candidato(trecho, contexto, candidatos)   # int | None
    c = arbitro.classificar_span(trecho, janela)     # dict | None

Ver docs/decisoes/0003-arbitro-llm.md e MANIFESTO_MODELO.md.
"""
from __future__ import annotations

from .arbitro import (
    Arbitro,
    ArbitroBase,
    ErroDependencia,
    Pedido,
    aparar_fronteiras,
    candidato_de_registro,
    digitos_compativeis,
    extrair_json,
    validar_classificacao,
    validar_escolha,
    validar_normalizacao,
)
from .backends import (
    BACKENDS,
    MODELO_AWQ,
    MODELO_PADRAO,
    MockArbitro,
    TransformersArbitro,
    VLLMArbitro,
    obter_arbitro,
)
from .cache import CacheLLM, chave_cache
from .prompts import PROMPT_VERSAO

__all__ = [
    "Arbitro", "ArbitroBase", "ErroDependencia", "Pedido",
    "MockArbitro", "TransformersArbitro", "VLLMArbitro", "obter_arbitro", "BACKENDS",
    "MODELO_PADRAO", "MODELO_AWQ", "CacheLLM", "chave_cache", "PROMPT_VERSAO",
    "extrair_json", "digitos_compativeis", "validar_normalizacao", "validar_escolha",
    "validar_classificacao", "aparar_fronteiras", "candidato_de_registro",
]
