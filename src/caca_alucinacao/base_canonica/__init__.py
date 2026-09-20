"""Base canônica: índice de números PRÓPRIOS, consulta e normativos.

Ver docs/02_arquitetura.md (seção ``base_canonica``) e docs/04_analise_base.md.
"""
from __future__ import annotations

from .consulta import BaseCanonica, Registro, relator_compativel
from .digitos import digitos_canonicos, separar_uf
from .indice import (
    carregar_indice,
    construir_indice,
    extrair_identificadores_proprios,
    impressao_do_banco,
    indice_corresponde_ao_banco,
    regiao_de_identificacao,
    salvar_indice,
)
from .normativos import artigo_canonico, diploma_canonico, sumula_canonica

__all__ = [
    "BaseCanonica",
    "Registro",
    "relator_compativel",
    "digitos_canonicos",
    "separar_uf",
    "carregar_indice",
    "construir_indice",
    "extrair_identificadores_proprios",
    "impressao_do_banco",
    "indice_corresponde_ao_banco",
    "regiao_de_identificacao",
    "salvar_indice",
    "artigo_canonico",
    "diploma_canonico",
    "sumula_canonica",
]
