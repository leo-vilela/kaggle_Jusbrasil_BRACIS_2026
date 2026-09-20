"""Re-export de compatibilidade: a implementação vive em :mod:`caca_alucinacao.normalizacao`.

Mantido para que o índice, a consulta, os scripts de análise e os testes
continuem importando ``base_canonica.digitos``; **nenhuma lógica** mora aqui
(ver docs/decisoes/0001-normalizacao.md). Diferenças de nome:

* ``numeros_do_texto`` aqui é :func:`normalizacao.numeros_com_posicao`
  (devolve ``(inicio, fim, digitos, formato)``), como os scripts esperam;
  :func:`normalizacao.numeros_do_texto` devolve só a lista de dígitos.
* ``digitos_canonicos`` é o mesmo objeto que :func:`normalizacao.digitos_do_identificador`.
"""
from __future__ import annotations

from ..normalizacao import (
    CONFUSOES,
    FORMATO_CNJ,
    FORMATO_OUTRO,
    FORMATO_REGISTRO,
    FORMATO_SEQUENCIAL,
    UFS,
    Nucleo,
    classificar_digitos,
    corrigir_ocr_em_grupo,
    corrigir_ocr_em_numero,
    digitos_canonicos,
    digitos_do_identificador,
    formato_de,
    nucleo_principal,
    nucleos,
    separar_uf,
)
from ..normalizacao import numeros_com_posicao as numeros_do_texto

__all__ = [
    "CONFUSOES",
    "FORMATO_CNJ",
    "FORMATO_OUTRO",
    "FORMATO_REGISTRO",
    "FORMATO_SEQUENCIAL",
    "UFS",
    "Nucleo",
    "classificar_digitos",
    "corrigir_ocr_em_grupo",
    "corrigir_ocr_em_numero",
    "digitos_canonicos",
    "digitos_do_identificador",
    "formato_de",
    "nucleo_principal",
    "nucleos",
    "numeros_do_texto",
    "separar_uf",
]
