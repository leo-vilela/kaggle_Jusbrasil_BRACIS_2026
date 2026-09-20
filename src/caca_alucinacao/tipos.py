"""Tipos compartilhados entre detecção, resolução, calibração e contrato.

Mantidos num módulo próprio (sem dependências) para que os módulos possam ser
desenvolvidos e testados de forma independente.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FAMILIAS = ("processo", "sumula", "dispositivo", "tema", "vaga")
TIPOS = ("jurisprudencia", "lei")
CLASSIFICACOES = ("real", "inventada", "incompleta")
TRIBUNAIS = ("STF", "STJ", "TSE", "TST", "STM")


@dataclass(frozen=True)
class Achado:
    """Um span candidato a citação, antes de ser resolvido.

    ``inicio``/``fim`` em codepoints, fim exclusivo; ``trecho == texto[inicio:fim]``.
    ``dados`` leva os grupos já isolados pela detecção (chaves em minúsculas):
    ``classe`` (superfície), ``cadeia`` (siglas canônicas separadas por espaço,
    ex. ``"AGINT ARESP"``), ``classe_principal``, ``numero`` (superfície),
    ``digitos`` (canônicos), ``formato`` (``cnj20`` | ``curto`` | ``registro``),
    ``uf``, ``tribunal``, ``ano``, ``relator``, ``artigo``, ``diploma`` (canônico),
    ``numero_sumula``, ``vinculante`` (``"1"``/``"0"``), ``numero_tema``.
    ``origem`` identifica o padrão que produziu o achado (``"regex:processo"``,
    ``"llm:e_citacao"``); ``forca`` é a confiança da própria detecção (1.0 para
    padrões estritos, menor para padrões amplos) e alimenta a calibração.
    """

    inicio: int
    fim: int
    trecho: str
    familia: str
    tipo: str
    dados: dict[str, str] = field(default_factory=dict, compare=False)
    origem: str = "regex"
    forca: float = 1.0

    def __post_init__(self) -> None:
        if self.familia not in FAMILIAS:
            raise ValueError(f"família inválida: {self.familia!r}")
        if self.tipo not in TIPOS:
            raise ValueError(f"tipo inválido: {self.tipo!r}")
        if self.inicio < 0 or self.fim <= self.inicio:
            raise ValueError(f"span inválido: ({self.inicio}, {self.fim})")
        if not 0.0 <= self.forca <= 1.0:
            raise ValueError(f"força fora de [0, 1]: {self.forca}")

    @property
    def tamanho(self) -> int:
        return self.fim - self.inicio


@dataclass(frozen=True)
class Decisao:
    """Resultado da resolução de um achado contra a base canônica.

    ``caminho`` é a chave da calibração de confiança (ex. ``"processo:1candidato:cadeia_exata"``,
    ``"processo:0candidatos"``, ``"sumula:na_tabela"``, ``"vaga:incompleta"``).
    ``candidatos`` lista os ``id_canonico`` considerados (ordem determinística);
    ``detalhes`` guarda o que for útil ao diagnóstico e ao árbitro LLM.
    """

    classificacao: str
    id_canonico: int | None
    caminho: str
    candidatos: tuple[int, ...] = ()
    detalhes: dict[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if self.classificacao not in CLASSIFICACOES:
            raise ValueError(f"classificação inválida: {self.classificacao!r}")
        if self.classificacao == "real" and self.id_canonico is None:
            raise ValueError("classe real exige id_canonico")
        if self.classificacao != "real" and self.id_canonico is not None:
            raise ValueError("id_canonico só existe na classe real")


def iou(a_inicio: int, a_fim: int, b_inicio: int, b_fim: int) -> float:
    """IoU de dois spans em codepoints (mesma fórmula do kaggle_metric.py)."""
    inter = max(0, min(a_fim, b_fim) - max(a_inicio, b_inicio))
    if inter == 0:
        return 0.0
    uniao = (a_fim - a_inicio) + (b_fim - b_inicio) - inter
    return inter / uniao
