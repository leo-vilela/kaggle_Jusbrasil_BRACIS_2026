"""Fusão dos candidatos: um span por citação, sem sobreposição (docs/02, docs/03 §9.1.2).

Regras, na ordem:

1. prioridade = maior ``forca`` (estrito 1,0 antes de amplo), depois **span mais
   longo** (``AgInt no AREsp nº …`` vence ``AREsp nº …``; ``Súmula 7 do STJ``
   vence ``Súmula 7``), depois a ordem das famílias de §9.1 (vaga → dispositivo
   → sumula → tema → processo), depois o mais à esquerda;
2. um candidato que **interseca** qualquer achado já aceito é descartado — não
   só quando IoU ≥ 0,5: o gabarito não tem spans aninhados nem sobrepostos, e
   dois achados com interseção seriam ou o mesmo identificador (prefixo
   encadeado + classe principal) ou um erro;
3. saída ordenada por ``(inicio, fim)``.

A garantia exigida pelo pipeline (nenhum par com IoU ≥ 0,5) decorre de 2.
"""
from __future__ import annotations

import bisect
import logging

from ..tipos import Achado, iou

log = logging.getLogger(__name__)

_ORDEM_FAMILIA = {"vaga": 0, "dispositivo": 1, "sumula": 2, "tema": 3, "processo": 4}


def _prioridade(a: Achado) -> tuple[float, int, int, int, int]:
    return (-a.forca, -(a.fim - a.inicio), _ORDEM_FAMILIA.get(a.familia, 9), a.inicio, a.fim)


def _interseca(a: Achado, b: Achado) -> bool:
    return a.inicio < b.fim and b.inicio < a.fim


def fundir(candidatos: list[Achado]) -> list[Achado]:
    """Seleção gulosa por prioridade; descarta qualquer candidato que interseque um aceito.

    Os aceitos ficam numa lista ordenada por início e só os vizinhos que podem
    intersectar o candidato são comparados (O(n log n); a busca linear anterior
    era O(n²) — 30 000 candidatos levavam 2 minutos; revisão R3-04).
    """
    inicios: list[int] = []
    aceitos: list[Achado] = []
    maior_len = 0
    for a in sorted(candidatos, key=_prioridade):
        k0 = bisect.bisect_left(inicios, a.inicio - maior_len)
        k1 = bisect.bisect_left(inicios, a.fim)
        conflito = next((b for b in aceitos[k0:k1] if _interseca(a, b)), None)
        if conflito is None:
            pos = bisect.bisect_left(inicios, a.inicio)
            inicios.insert(pos, a.inicio)
            aceitos.insert(pos, a)
            maior_len = max(maior_len, a.fim - a.inicio)
        else:
            log.debug("fusão: descartado (%d,%d) %s/%s forca=%.2f por (%d,%d) %s/%s IoU=%.2f",
                      a.inicio, a.fim, a.familia, a.origem, a.forca, conflito.inicio, conflito.fim,
                      conflito.familia, conflito.origem,
                      iou(a.inicio, a.fim, conflito.inicio, conflito.fim))
    aceitos.sort(key=lambda x: (x.inicio, x.fim))
    return aceitos


def sem_sobreposicao(achados: list[Achado]) -> bool:
    """``True`` se nenhum par tem interseção (verificação usada pelos testes)."""
    for i, a in enumerate(achados):
        for b in achados[i + 1:]:
            if _interseca(a, b):
                return False
    return True


__all__ = ["fundir", "sem_sobreposicao"]
