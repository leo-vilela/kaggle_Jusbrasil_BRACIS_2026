"""Re-export de compatibilidade: a implementação vive em :mod:`caca_alucinacao.normalizacao`.

Mantido para que o índice, a consulta, os scripts de análise e os testes
continuem importando ``base_canonica.classes``; **nenhuma lógica** mora aqui
(ver docs/decisoes/0001-normalizacao.md). As siglas canônicas (``ED``,
``AGR``, ``AGINT``, ``RESP``, ``ARESP``, ``RESPE`` …) são as gravadas em
``dados/indice.json`` e não mudam.
"""
from __future__ import annotations

from ..normalizacao import (
    ESTADOS,
    SIGLAS_CANONICAS,
    cadeia_da_citacao,
    cadeia_de_classes,
    classe_principal,
    classe_processual_canonica,
    classes_compativeis,
    sem_acento,
    uf_de_estado,
)

__all__ = [
    "ESTADOS",
    "SIGLAS_CANONICAS",
    "cadeia_da_citacao",
    "cadeia_de_classes",
    "classe_principal",
    "classe_processual_canonica",
    "classes_compativeis",
    "sem_acento",
    "uf_de_estado",
]
