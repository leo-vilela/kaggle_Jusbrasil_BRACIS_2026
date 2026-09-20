"""Detecção de spans de citação: ``detectar(texto) -> list[Achado]``.

Ordem dos padrões (docs/03 §9.1): ``vaga`` → ``dispositivo`` → ``sumula`` →
``tema`` → ``processo``; cada família produz candidatos estritos (força 1,0) e
amplos (força < 1), :mod:`.distratores` remove o que está antes do fim do
cabeçalho ou em contexto de folhas/valor/OAB/data, e :mod:`.fusao` escolhe um
span por citação sem interseção alguma (logo, IoU < 0,5 garantido).

Determinismo: só regex compilados uma vez e ordenações explícitas; a saída é
ordenada por ``(inicio, fim)``. Nunca levanta exceção por causa do conteúdo do
texto — um documento sem citações devolve ``[]``.
"""
from __future__ import annotations

import logging
import re

from ..texto import fim_do_cabecalho
from ..tipos import Achado
from . import dispositivo, distratores, fusao, processo, sumula, tema, vaga

log = logging.getLogger(__name__)


def candidatos(texto: str) -> list[Achado]:
    """Todos os candidatos, antes das regras negativas e da fusão (diagnóstico)."""
    saida: list[Achado] = []
    saida.extend(vaga.detectar(texto))
    saida.extend(dispositivo.detectar(texto))
    saida.extend(sumula.detectar(texto))
    saida.extend(tema.detectar(texto))
    saida.extend(processo.detectar(texto))
    return saida


_RE_SEPARADOR_DE_FRASE = re.compile(r"[.;:!?]")
_GAP_CAUDA = 40
#: Entre o fim de uma ``vaga:amplo`` e o início do processo/súmula que ela "apresenta": só brancos
#: e um parêntese (``… Ministro X (REsp 1.234.567/PR)``; rodada 4, R4-05).
_RE_SO_ABRE_PARENTESE = re.compile(r"^\s{0,3}\(?\s{0,2}$")
_GAP_CABECA = 5


def _sem_cauda_de_citacao(texto: str, achados: list[Achado]) -> list[Achado]:
    """Remove ``vaga:amplo`` (ou o molde ``tribunal_primeiro``) que é só a cauda — ou a cabeça — de uma
    citação com número.

    ``AgRg no RE 1234567/SP, 2ª Turma, STF, j. 2021, Rel. Min. X``: o processo já
    é o span; ``STF, j. 2021, Rel. Min. X`` (amplo, sem substantivo) a menos de
    40 caracteres, sem ``.``/``;`` no meio, não é uma segunda citação. Simetricamente
    (rodada 4, R4-05), ``O acórdão do STJ firmou a tese em 2019, sob a relatoria do Ministro X
    (REsp 1.234.567/PR)``: a ``vaga:amplo`` cujo fim está a ≤ 5 caracteres (só brancos e ``(``)
    do início de um processo/súmula é a mesma citação — o número é o span.
    """
    saida: list[Achado] = []
    numerados = [b for b in achados if b.familia in ("processo", "sumula", "tema")]
    for a in achados:
        if a.origem == "regex:vaga:amplo":
            seguinte = next((b for b in numerados if b.inicio >= a.fim), None)
            if seguinte is not None:
                entre = texto[a.fim:seguinte.inicio]
                if len(entre) <= _GAP_CABECA and _RE_SO_ABRE_PARENTESE.match(entre):
                    log.debug("vaga amplo (%d,%d) descartada: cabeça de (%d,%d)", a.inicio, a.fim,
                              seguinte.inicio, seguinte.fim)
                    continue
        if (a.origem in ("regex:vaga:amplo", "regex:vaga:tribunal_primeiro")
                and not a.dados.get("substantivo") and not a.dados.get("classe")):
            anterior = next((b for b in reversed(saida) if b.familia in ("processo", "sumula", "tema")), None)
            if anterior is not None:
                entre = texto[anterior.fim:a.inicio]
                if len(entre) <= _GAP_CAUDA and not _RE_SEPARADOR_DE_FRASE.search(entre):
                    log.debug("vaga amplo (%d,%d) descartada: cauda de (%d,%d)", a.inicio, a.fim,
                              anterior.inicio, anterior.fim)
                    continue
        saida.append(a)
    return saida


def detectar(texto: str) -> list[Achado]:
    """Spans candidatos a citação, ordenados por posição e sem sobreposição."""
    if not texto:
        return []
    limite = fim_do_cabecalho(texto)
    brutos = candidatos(texto)
    filtrados = distratores.filtrar(texto, brutos, limite)
    achados = _sem_cauda_de_citacao(texto, fusao.fundir(filtrados))
    log.debug("detectar: %d candidatos, %d após distratores, %d após fusão (cabeçalho até %d)",
              len(brutos), len(filtrados), len(achados), limite)
    return achados


__all__ = ["Achado", "detectar", "candidatos"]
