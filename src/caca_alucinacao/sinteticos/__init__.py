"""Documentos sintéticos com gabarito (robustez, calibração e casos para o árbitro LLM).

Ver docs/05_sinteticos.md. API pública::

    gerar_conjunto(base, n_docs, nivel, seed, perfil) -> list[Documento]   # (documento_id, texto, gabarito)
    escrever_conjunto(docs, saida, base) -> estatísticas
    validar_documento(doc)                                                # offsets, IoU, distância, NFC
    gerar_casos_llm(docs, base) -> list[dict]                             # JSONL para o árbitro
    ler_goldenset(caminho) -> list[dict]                                  # desfaz o escape de "\\n"
"""
from __future__ import annotations

from .gerador import (
    COLUNAS_EXTRAS,
    COLUNAS_OFICIAIS,
    DISTANCIA_MINIMA,
    PERFIS,
    VERSAO,
    Citacao,
    Documento,
    Perfil,
    escrever_conjunto,
    estatisticas,
    gerar_casos_llm,
    gerar_conjunto,
    gerar_documento,
    ler_goldenset,
    perfil_para,
    validar_documento,
)
from .ruido import TAXAS_N1, TAXAS_N2, TAXAS_N3, Taxas, taxas_do_nivel

__all__ = [
    "COLUNAS_EXTRAS", "COLUNAS_OFICIAIS", "DISTANCIA_MINIMA", "PERFIS", "VERSAO",
    "Citacao", "Documento", "Perfil", "Taxas", "TAXAS_N1", "TAXAS_N2", "TAXAS_N3",
    "escrever_conjunto", "estatisticas", "gerar_casos_llm", "gerar_conjunto", "gerar_documento",
    "ler_goldenset", "perfil_para", "taxas_do_nivel", "validar_documento",
]
