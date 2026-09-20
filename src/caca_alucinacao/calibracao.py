"""Calibração da confiança por caminho de decisão.

A métrica oficial (docs/00 §2, item 5) usa a confiança só nos pares casados
que a trazem: ``brier = média((c − y)²)`` com ``y = 1`` se o acerto foi pleno
(mesma classe e, em ``real``, ``id_canonico`` certo) e ``y = 0`` caso
contrário; o bônus é ``b = clip(0,10·(1 − brier), 0, 0,10)`` e
``score_nível = s·(1 + b)``. Consequências:

* A esperança de ``(c − y)²`` para um caminho cuja acurácia verdadeira é
  ``p`` vale ``c²(1 − p) + (1 − c)²·p``, minimizada em ``c = p`` (valor mínimo
  ``p(1 − p)``). Logo a confiança ótima é a **acurácia empírica do caminho**,
  não um valor "de segurança" nem 1,0.
* Com ``n`` observações e ``a`` acertos, a estimativa de Laplace
  ``(a + 1)/(n + 2)`` é a média a posteriori sob prior uniforme e nunca chega
  a 1,0: mesmo ``n`` acertos em ``n`` deixam probabilidade ``1/(n + 2)`` de
  erro. O custo de ``c = 1,0`` é assimétrico — cada erro futuro contribui 1
  para o Brier, enquanto usar ``c = 0,98`` num acerto custa só ``0,0004``.
  Por isso o **teto é 0,98** (docs/03 §9.4) e o piso 0,05: valores extremos só
  pagam se a acurácia fosse exatamente 0 ou 1, o que não é observável.
* O bônus tem peso pequeno (≤ 10 % do ``s``): a calibração nunca deve mudar a
  **classe** decidida; ela só reporta o quanto o caminho é confiável.

Tabela ``{caminho: confiança}`` com **fallback hierárquico** por prefixo:
``processo:1cand:cadeia_exata`` → ``processo:1cand`` → ``processo`` → padrão
(``config.CONFIANCA_PADRAO``). Um caminho novo herda a estimativa do prefixo
mais específico presente. Achados de padrões amplos (``:amplo``) usam o valor
específico quando a tabela o tem; senão herdam o do caminho estrito
multiplicado pela ``forca`` do achado.

:func:`ajustar` produz a tabela empírica: acurácia suavizada por caminho
**e por todos os seus prefixos** (agregando os filhos), com o prior da
``tabela_inicial`` valendo ``PESO_PRIOR`` observações (Laplace generalizado:
``(a + k·p0)/(n + k)``), de modo que caminhos raros ficam perto do prior e
caminhos frequentes convergem para a acurácia observada. Decisão registrada em
``docs/decisoes/0007-calibracao.md``; treino em ``scripts/treinar_calibracao.py``.
"""
from __future__ import annotations

import json
import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CONFIANCA_PADRAO, CONFIANCA_TETO, CONFIANCA_TETO_CONSOLIDADO, N_MINIMO_CONSOLIDADO
from .tipos import Achado, Decisao

log = logging.getLogger(__name__)

#: Piso da calibração (mais alto que o piso do contrato, 0,02): abaixo disso a
#: confiança não carrega informação útil e só amplia o Brier em acertos raros.
CONFIANCA_PISO = 0.05
#: Peso do prior (em observações equivalentes) na suavização: ``(a + k·p0)/(n + k)``.
#: Com ``p0 = 0,5`` e ``k = 2`` é exatamente Laplace ``(a + 1)/(n + 2)``; usamos o
#: prior hierárquico da tabela inicial como ``p0`` e ``k = 4`` (o conhecimento de
#: domínio — duplicata ≈ 0,5, cadeia exata ≈ 0,98 — vale quatro observações).
PESO_PRIOR = 4.0
#: Sufixo dos caminhos de achados amplos (ver ``resolucao``).
SUFIXO_AMPLO = ":amplo"
#: Caminhos cuja "verdade" nos sintéticos/adversariais é definida pela própria política dos
#: autores (classe divergente ⇒ real por construção, tribunal incompatível ⇒ inventada por
#: construção, OCR ambíguo, chute entre duplicatas): treiná-los seria evidência circular
#: (rodada 3, R5-04). :func:`ajustar` ignora as observações destes prefixos e mantém o prior.
CAMINHOS_SEM_TREINO: tuple[str, ...] = (
    "processo:1cand:classe_divergente", "processo:1cand:tribunal_incompativel",
    "processo:multi:tribunal_incompativel", "processo:multi:curto_classe_divergente",
    "processo:1cand:curto_classe_divergente", "processo:0cand:ocr_ambiguo",
    "processo:duplicata", "processo:ambiguo_chute", "processo:ocr_reparado:1cand:classe_divergente",
    "sumula:fora_da_tabela:vinculante_tribunal_divergente",
)


def sem_treino(caminho: str) -> bool:
    """``True`` se o caminho (ou um prefixo dele) está em :data:`CAMINHOS_SEM_TREINO`."""
    return any(caminho == c or caminho.startswith(c + ":") for c in CAMINHOS_SEM_TREINO)

#: Confianças iniciais por caminho (docs/03 §9.4; docs/04 h.11). São *priors*:
#: o treino substitui/encolhe cada uma pela acurácia empírica. Os valores altos
#: (0,98) são os caminhos com 100 % no dev; ≈ 0,5 é reservado a empates entre
#: duplicatas; os caminhos "residuais" (árbitro, OCR pesado, chute) ficam
#: entre 0,4 e 0,7 porque a única evidência é a lógica do custo.
TABELA_INICIAL: dict[str, float] = {
    # processo
    "processo": 0.85,
    "processo:0cand": 0.95,
    "processo:0cand:ocr_sem_dono": 0.90,
    "processo:0cand:ocr_ambiguo": 0.60,
    "processo:0cand:registro_diverge": 0.60,
    "processo:1cand": 0.90,
    "processo:1cand:cadeia_exata": 0.98,
    "processo:1cand:classe_principal": 0.95,
    "processo:1cand:classe_compativel": 0.90,
    "processo:1cand:sem_classe": 0.85,
    "processo:1cand:classe_divergente": 0.75,
    # só o número sustenta a escolha: P(real) ≈ 0,5 < break-even 0,73 ⇒ emite-se ``inventada`` com a
    # mesma incerteza (rodada 3, R5-04; rodada 4, R4-03 — ADR 0006 §3)
    "processo:1cand:classe_divergente:sem_uf": 0.50,
    "processo:1cand:registro": 0.90,
    "processo:1cand:tribunal_incompativel": 0.70,
    "processo:1cand:uf_incompativel": 0.70,
    "processo:1cand:curto_classe_divergente": 0.60,
    "processo:multi": 0.80,
    "processo:multi:cadeia_exata": 0.95,
    "processo:multi:classe_principal": 0.85,
    "processo:multi:classe_compativel": 0.80,
    "processo:multi:tribunal": 0.90,
    "processo:multi:uf": 0.85,
    "processo:multi:registro": 0.90,
    "processo:multi:uf_confirmada": 0.85,
    "processo:multi:tribunal_incompativel": 0.70,
    "processo:multi:uf_incompativel": 0.70,
    "processo:multi:curto_classe_divergente": 0.60,
    # duplicatas textuais: se o gabarito listar todos os ids do grupo (formato ``a:b`` que a métrica
    # oficial documenta como "conjunto aceito") a escolha é sempre certa; se listar um só, 0,5.
    # Sob incerteza q≈0,6 sobre a política, a esperança 0,5 + 0,5·q ≈ 0,8 minimiza o Brier
    # (revisão rodada 2, R4-14; ADR 0007). Nenhuma fonte de treino observa esse caminho.
    "processo:duplicata": 0.80,
    "processo:duplicata:classe_divergente": 0.50,    # grupo duplicado de OUTRA classe → inventada (R3-11; R4-03)
    "processo:llm_escolha": 0.65,
    "processo:ambiguo_chute": 0.40,
    "processo:llm_normalizou": 0.70,
    "processo:llm_normalizou:0cand": 0.75,
    "processo:llm_nao_citacao": 0.50,
    "processo:ocr_reparado": 0.85,          # sub-caminhos (1cand:…, multi:…) herdam daqui
    # súmula
    "sumula": 0.90,
    "sumula:na_tabela": 0.97,
    # ``Súmula N`` sem tribunal só resolve quando N é único na tabela fechada (``base.sumula``):
    # a única incerteza é o gabarito anotar outro tribunal para o mesmo número (rodada 3, R3-14)
    "sumula:na_tabela:sem_tribunal": 0.95,
    "sumula:na_tabela:ocr": 0.90,               # número com letra confundível convertida (rodada 2)
    "sumula:fora_da_tabela": 0.95,
    "sumula:fora_da_tabela:sem_tribunal": 0.85,
    "sumula:fora_da_tabela:ocr": 0.90,
    "sumula:fora_da_tabela:vinculante_tribunal_divergente": 0.70,   # docs/04 h.8 (rodada 3, R5-08)
    "sumula:sem_numero": 0.50,
    # dispositivo
    "dispositivo": 0.90,
    "dispositivo:na_tabela": 0.97,
    "dispositivo:na_tabela:ocr": 0.90,
    "dispositivo:fora_da_tabela": 0.95,
    "dispositivo:fora_da_tabela:ocr": 0.90,
    "dispositivo:fora_da_tabela:diploma_outro": 0.85,
    "dispositivo:diploma_fora_da_base": 0.95,
    "dispositivo:diploma_desconhecido": 0.70,
    "dispositivo:sem_diploma": 0.50,
    "dispositivo:sem_artigo": 0.50,
    # tema e vaga
    "tema": 0.90,
    "tema:inventada": 0.90,
    "tema:inventada:repercussao": 0.95,   # forma do gabarito (``Tema N da repercussão geral``)
    "tema:inventada:repetitivo": 0.85,    # ``Tema Repetitivo N`` / ``Tema N do STJ``: plausível, sem exemplo no dev
    "tema:inventada:solto": 0.60,         # ``Tema N`` com indício na frase: aposta (R6-16)
    "vaga": 0.90,
    "vaga:incompleta": 0.97,
    "vaga:incompleta:sem_correspondencia": 0.75,
    # (tribunal, ano, relator) com 1 registro: 17 % dos acórdãos da base são únicos, mas as 32 vagas do
    # dev têm multiplicidade ≥ 4 — o gerador evita únicos; se ocorrer, a classe emitida continua
    # ``incompleta`` (o gabarito do dev nunca traz ``real`` para vaga) e 0,90 só reduz o Brier (R4-10)
    "vaga:incompleta:unica": 0.90,
}


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def prefixos(caminho: str) -> list[str]:
    """``"a:b:c"`` → ``["a:b:c", "a:b", "a"]`` (do mais específico ao mais geral)."""
    partes = [p for p in caminho.split(":") if p]
    return [":".join(partes[:i]) for i in range(len(partes), 0, -1)]


#: Segmentos "modificadores" de um caminho (``processo:ocr_reparado:1cand:uf_incompativel``): antes de
#: subir ao prefixo, tenta-se o caminho-irmão sem o modificador (``processo:1cand:uf_incompativel``,
#: 0,70), para que uma inventada por UF divergente após reparo de OCR não herde a confiança de
#: ``processo:ocr_reparado:1cand`` ≈ cadeia exata (rodada 4, R6-15).
MODIFICADORES: tuple[str, ...] = ("ocr_reparado", "llm_normalizou")


def chaves_de_consulta(caminho: str) -> list[str]:
    """``prefixos`` intercalados com o irmão sem modificador: ``a:ocr_reparado:b:c`` → ``[a:ocr_reparado:b:c,
    a:b:c, a:ocr_reparado:b, a:b, a:ocr_reparado, a]``."""
    saida: list[str] = []
    for chave in prefixos(caminho):
        saida.append(chave)
        partes = [p for p in chave.split(":") if p not in MODIFICADORES]
        irmao = ":".join(partes)
        if irmao and irmao != chave and irmao not in saida:
            saida.append(irmao)
    return saida


def valor_do_caminho(caminho: str, tabela: Mapping[str, float] | None,
                     padrao: float = CONFIANCA_PADRAO) -> tuple[float, str | None]:
    """Fallback hierárquico: ``(valor, chave usada)``; chave ``None`` = padrão."""
    if tabela:
        for chave in chaves_de_consulta(caminho):
            v = tabela.get(chave)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v), chave
    return float(padrao), None


def limitar(valor: float, teto: float = CONFIANCA_TETO, piso: float = CONFIANCA_PISO) -> float:
    """Aplica piso e teto (e trata NaN/valores absurdos como o padrão)."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        v = CONFIANCA_PADRAO
    if math.isnan(v):
        v = CONFIANCA_PADRAO
    return max(piso, min(teto, v))


def confianca(decisao: Decisao, achado: Achado, tabela: Mapping[str, float] | None) -> float:
    """Confiança em [piso, teto] para a decisão, pela tabela por caminho.

    1. procura ``decisao.caminho`` e depois os seus prefixos na ``tabela``
       (``TABELA_INICIAL`` é usada quando ``tabela`` está vazia/``None``);
    2. se o achado é amplo (``forca < 1``) e a chave encontrada **não** é
       específica de ``:amplo``, multiplica pela ``forca`` — a acurácia do
       caminho estrito superestima a de um padrão amplo;
    3. aplica piso 0,05 e teto 0,98 (0,995 só para valores que a tabela treinada
       marcou como consolidados — ver :func:`ajustar`).
    """
    fonte = tabela if tabela else TABELA_INICIAL
    valor, chave = valor_do_caminho(decisao.caminho, fonte)
    if chave is None and fonte is not TABELA_INICIAL:
        valor, chave = valor_do_caminho(decisao.caminho, TABELA_INICIAL)
    forca = float(getattr(achado, "forca", 1.0))
    if forca < 1.0 and not (chave or "").endswith(SUFIXO_AMPLO):
        valor *= max(0.0, forca)
    # O teto consolidado (0,995) só entra pela tabela treinada (``ajustar`` o concede a caminhos
    # com ≥ N_MINIMO_CONSOLIDADO decisões e 0 erros); priors e caminhos comuns param em 0,98.
    return limitar(valor, teto=CONFIANCA_TETO_CONSOLIDADO)


# ---------------------------------------------------------------------------
# Ajuste empírico
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Avaliacao:
    """Uma decisão avaliada: ``caminho`` e ``acerto`` (1 = classe e id certos)."""

    caminho: str
    acerto: int
    forca: float = 1.0
    peso: float = 1.0


def _como_avaliacao(item: Any) -> Avaliacao | None:
    if isinstance(item, Avaliacao):
        return item
    if isinstance(item, Mapping):
        cam = item.get("caminho")
        y = item.get("acerto", item.get("y"))
        if not cam or y is None:
            return None
        return Avaliacao(str(cam), 1 if int(y) else 0, float(item.get("forca", 1.0)), float(item.get("peso", 1.0)))
    if isinstance(item, (tuple, list)) and len(item) >= 2:
        return Avaliacao(str(item[0]), 1 if int(item[1]) else 0,
                         float(item[2]) if len(item) > 2 else 1.0, float(item[3]) if len(item) > 3 else 1.0)
    return None


def normalizar_avaliacoes(avaliacoes: Iterable[Any]) -> list[Avaliacao]:
    """Aceita ``Avaliacao``, ``(caminho, acerto[, forca[, peso]])`` ou dicts; ignora inválidos."""
    saida: list[Avaliacao] = []
    for item in avaliacoes:
        a = _como_avaliacao(item)
        if a is not None:
            saida.append(a)
    return saida


def contagens(avaliacoes: Iterable[Any], com_prefixos: bool = True) -> dict[str, tuple[float, float]]:
    """``{caminho: (n, acertos)}`` (ponderados por ``peso``), agregando também nos prefixos."""
    acc: dict[str, list[float]] = {}
    for a in normalizar_avaliacoes(avaliacoes):
        chaves = prefixos(a.caminho) if com_prefixos else [a.caminho]
        for k in chaves:
            e = acc.setdefault(k, [0.0, 0.0])
            e[0] += a.peso
            e[1] += a.peso * a.acerto
    return {k: (v[0], v[1]) for k, v in sorted(acc.items())}


def laplace(n: float, acertos: float, p0: float = 0.5, peso: float = 2.0) -> float:
    """``(a + k·p0)/(n + k)``: média a posteriori da acurácia sob prior Beta centrado em ``p0``.

    Com os padrões (``p0 = 0,5``, ``k = 2``) é a regra de sucessão de Laplace
    ``(a + 1)/(n + 2)``: nunca chega a 1,0 (``n`` acertos em ``n`` deixam
    ``1/(n + 2)`` de erro) e nunca a 0,0. Com ``p0`` = prior do caminho e ``k``
    maior, o prior vale ``k`` observações e domina enquanto ``n`` é pequeno.
    """
    return (acertos + peso * p0) / (n + peso)


def ajustar(
    tabela_inicial: Mapping[str, float] | None,
    avaliacoes: Iterable[Any],
    peso_prior: float = PESO_PRIOR,
    teto: float = CONFIANCA_TETO,
    piso: float = CONFIANCA_PISO,
) -> dict[str, float]:
    """Tabela ajustada pela acurácia empírica por caminho (e prefixos).

    Para cada caminho observado (e cada prefixo dele, agregando os filhos):

    * prior ``p0`` = valor da ``tabela_inicial`` para o caminho (fallback
      hierárquico; ``TABELA_INICIAL`` se ela for ``None``; 0,5 se nada casa);
    * ``p = (a + k·p0)/(n + k)`` com ``k = peso_prior`` (:func:`laplace`):
      ``n = 0`` devolve o prior; ``n ≫ k`` devolve a acurácia empírica; ``n``
      acertos em ``n`` nunca chegam a 1,0;
    * piso/teto.

    Caminhos da ``tabela_inicial`` sem observação são mantidos como estão
    (continuam a servir de fallback), assim como os de :data:`CAMINHOS_SEM_TREINO`
    (observações ignoradas, inclusive na agregação dos prefixos). A saída inclui as chaves de prefixo para
    que caminhos novos herdem a acurácia agregada da família (prior por família).
    """
    inicial = dict(tabela_inicial) if tabela_inicial else dict(TABELA_INICIAL)
    saida: dict[str, float] = {k: limitar(v, teto, piso) for k, v in inicial.items()}
    treinaveis = [a for a in normalizar_avaliacoes(avaliacoes) if not sem_treino(a.caminho)]
    for caminho, (n, a) in contagens(treinaveis).items():
        p0, _ = valor_do_caminho(caminho, inicial)
        p = laplace(n, a, p0, peso_prior)
        # Teto consolidado: ≥ N_MINIMO_CONSOLIDADO decisões avaliadas sem nenhum erro (o
        # prefixo agrega os filhos, então um prefixo só consolida se TODOS os filhos acertaram).
        teto_caminho = teto
        if n >= N_MINIMO_CONSOLIDADO and a >= n and teto < CONFIANCA_TETO_CONSOLIDADO:
            teto_caminho = CONFIANCA_TETO_CONSOLIDADO
        saida[caminho] = limitar(p, teto_caminho, piso)
        log.debug("calibração %s: n=%.0f a=%.0f p0=%.3f → %.3f (teto %.3f)",
                  caminho, n, a, p0, saida[caminho], teto_caminho)
    return dict(sorted(saida.items()))


def brier(avaliacoes: Iterable[Any], tabela: Mapping[str, float] | None) -> float | None:
    """Brier médio das avaliações com a tabela (``None`` sem avaliações).

    Reproduz o que a métrica faria para pares casados: ``c`` é a confiança
    que :func:`confianca` daria (fallback + força + limites) e ``y`` o acerto.
    """
    soma = 0.0
    n = 0.0
    for a in normalizar_avaliacoes(avaliacoes):
        fonte = tabela if tabela else TABELA_INICIAL
        c, chave = valor_do_caminho(a.caminho, fonte)
        if a.forca < 1.0 and not (chave or "").endswith(SUFIXO_AMPLO):
            c *= max(0.0, a.forca)
        c = limitar(c, teto=CONFIANCA_TETO_CONSOLIDADO)
        soma += a.peso * (c - a.acerto) ** 2
        n += a.peso
    return (soma / n) if n else None


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------
def carregar(caminho: Path | str) -> dict[str, float]:
    """Lê ``{caminho: confiança}`` ou ``{"tabela": {...}, "meta": {...}}``; ``{}`` se ausente."""
    p = Path(caminho)
    if not p.exists():
        log.info("tabela de calibração ausente (%s); usando TABELA_INICIAL", p)
        return {}
    dados = json.loads(p.read_text(encoding="utf-8"))
    tabela = dados.get("tabela", dados) if isinstance(dados, dict) else {}
    return {str(k): float(v) for k, v in tabela.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def salvar(tabela: Mapping[str, float], caminho: Path | str, meta: Mapping[str, Any] | None = None) -> Path:
    """Grava ``{"tabela": {...}, "meta": {...}}`` (chaves ordenadas, UTF-8)."""
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {"tabela": dict(sorted((str(k), round(float(v), 4)) for k, v in tabela.items())),
                "meta": dict(meta or {})}
    p.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return p


__all__ = [
    "TABELA_INICIAL", "CONFIANCA_PISO", "PESO_PRIOR", "SUFIXO_AMPLO", "CAMINHOS_SEM_TREINO", "sem_treino", "Avaliacao",
    "prefixos", "chaves_de_consulta", "MODIFICADORES", "valor_do_caminho", "limitar", "confianca", "normalizar_avaliacoes", "contagens",
    "laplace", "ajustar", "brier", "carregar", "salvar",
]
