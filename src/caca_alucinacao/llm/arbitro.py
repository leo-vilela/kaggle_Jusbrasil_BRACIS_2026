"""Árbitro LLM: interface, parsing tolerante de JSON, validação e classe base.

O árbitro é chamado **só em casos residuais** (docs/02_arquitetura.md, seção
``llm/``; docs/04_analise_base.md, h.3) e nunca decide sozinho:

* :meth:`Arbitro.normalizar_citacao` devolve dígitos que o pipeline **reconsulta**
  no índice; os dígitos só podem diferir do trecho por trocas letra→dígito
  (:func:`digitos_compativeis`) — um dígito ASCII do trecho nunca muda.
* :meth:`Arbitro.escolher_candidato` devolve um índice numa lista que o índice
  já devolveu (nunca inventa ``id_canonico``); sem critério → ``None``.
* :meth:`Arbitro.classificar_span` confirma/descarta um candidato fraco e ajusta
  as fronteiras dentro da janela dada; o span devolvido tem de ser substring
  literal da janela e sobrepor o candidato original.

Qualquer falha (dependência ausente, exceção do modelo, JSON inválido, campo
fora do domínio) resulta em **abstenção** (``None``), nunca em exceção que
derrube o documento. A classe base :class:`ArbitroBase` implementa cache,
parsing e validação; os backends só implementam :meth:`ArbitroBase._gerar`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..normalizacao import (
    CONFUSOES,
    SIGLAS_CANONICAS,
    UFS,
    cadeia_de_classes,
    classificar_digitos,
    separar_uf,
)
from ..tipos import FAMILIAS, TIPOS, TRIBUNAIS
from . import prompts
from .cache import CacheLLM, chave_cache

logger = logging.getLogger(__name__)

FAMILIAS_ARBITRO = FAMILIAS + ("nenhuma",)
_ARTIGOS_INICIAIS = ("o ", "a ", "no ", "na ", "do ", "da ", "os ", "as ", "nos ", "nas ", "dos ", "das ")
_PONTUACAO_FINAL = ",.;:!?)\"'"
_RE_ORDINAL = re.compile(r"^\d+O$")


def _e_snapshot_local(modelo: str) -> bool:
    """``CACA_MODELO`` aponta para uma pasta com ``config.json`` (pesos já no disco)."""
    try:
        return Path(modelo).is_dir() and (Path(modelo) / "config.json").is_file()
    except (OSError, ValueError):
        return False


def _hash_snapshot_local(modelo: str) -> str:
    """``local-<sha256 curto de config.json + nomes/tamanhos dos safetensors>``: identidade dos pesos."""
    h = hashlib.sha256()
    pasta = Path(modelo)
    try:
        h.update((pasta / "config.json").read_bytes())
        for arq in sorted(pasta.glob("*.safetensors")):
            h.update(f"{arq.name}:{arq.stat().st_size}".encode())
    except OSError:
        return "local-desconhecido"
    return "local-" + h.hexdigest()[:16]


class ErroDependencia(ImportError):
    """Dependência opcional (torch/transformers/vllm) ausente ao instanciar um backend."""


@runtime_checkable
class Arbitro(Protocol):
    """Interface do árbitro. Toda operação devolve ``None`` em qualquer falha."""

    def normalizar_citacao(self, trecho: str, contexto: str) -> dict[str, Any] | None:
        """``{"classe_cadeia": [...], "numero_digitos": "…", "digitos_canonicos": "…",
        "uf": "SP"|None, "tribunal": "STJ"|None, "eh_citacao": bool}`` ou ``None``.

        ``numero_digitos`` são os dígitos brutos validados (só trocas
        letra→dígito em relação ao trecho); ``digitos_canonicos`` é a mesma
        chave já no formato do índice (CNJ preenchido a 20 dígitos). O
        pipeline **reconsulta** o índice com ``digitos_canonicos``; nunca
        aceita o resultado como resolução.
        """

    def escolher_candidato(self, trecho: str, contexto: str, candidatos: list[dict[str, Any]]) -> int | None:
        """Índice (0-based) em ``candidatos`` ou ``None`` quando não há critério.

        Cada candidato: ``{"id_canonico", "cabecalho" (≤ 600 chars), "tribunal",
        "ano", "relator", "cadeia"}``. Só chamar com ≥ 2 candidatos de cabeçalhos
        **diferentes** (duplicatas idênticas são indecidíveis por definição).
        """

    def classificar_span(self, trecho: str, contexto: str, inicio_rel: int | None = None) -> dict[str, Any] | None:
        """``{"eh_citacao": bool, "familia": …, "tipo": …, "inicio_rel": int, "fim_rel": int,
        "trecho": str}`` (offsets relativos a ``contexto``) ou ``None``.

        ``contexto`` é a janela que contém ``trecho``; ``inicio_rel`` (opcional)
        desambigua ocorrências repetidas. ``eh_citacao=False`` vem com
        ``familia="nenhuma"`` e os offsets do candidato original.
        """


@dataclass(frozen=True)
class Pedido:
    """Uma pergunta ao modelo (a operação e a entrada permitem ao Mock responder sem prompt)."""

    operacao: str
    entrada: dict[str, Any]
    mensagens: list[dict[str, str]] = field(compare=False)


# ---------------------------------------------------------------------------
# Parsing tolerante de JSON
# ---------------------------------------------------------------------------
_RE_CERCA = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
_RE_VIRGULA_SOBRANDO = re.compile(r",\s*([}\]])")
_RE_PY_LITERAIS = [(re.compile(r"\bTrue\b"), "true"), (re.compile(r"\bFalse\b"), "false"),
                   (re.compile(r"\bNone\b"), "null")]


def _tentar_json(texto: str) -> dict[str, Any] | None:
    candidatos = [texto, _RE_VIRGULA_SOBRANDO.sub(r"\1", texto)]
    t2 = texto
    for rx, sub in _RE_PY_LITERAIS:
        t2 = rx.sub(sub, t2)
    candidatos.append(_RE_VIRGULA_SOBRANDO.sub(r"\1", t2))
    for c in candidatos:
        try:
            obj = json.loads(c)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _objetos_balanceados(texto: str) -> list[str]:
    """Substrings ``{…}`` com chaves balanceadas (ignorando chaves dentro de strings)."""
    saida: list[str] = []
    for ini, ch in enumerate(texto):
        if ch != "{":
            continue
        prof, em_str, esc = 0, False, False
        for j in range(ini, len(texto)):
            c = texto[j]
            if em_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    em_str = False
                continue
            if c == '"':
                em_str = True
            elif c == "{":
                prof += 1
            elif c == "}":
                prof -= 1
                if prof == 0:
                    saida.append(texto[ini : j + 1])
                    break
    return saida


def extrair_json(texto: str | None) -> dict[str, Any] | None:
    """Primeiro objeto JSON válido no texto (com/sem cercas, texto antes/depois).

    Tolera vírgula sobrando antes de ``}``/``]`` e literais Python
    (``True``/``False``/``None``). Devolve ``None`` se nada parseia.
    """
    if not texto or not isinstance(texto, str):
        return None
    texto = texto.strip()
    obj = _tentar_json(texto)
    if obj is not None:
        return obj
    for m in _RE_CERCA.finditer(texto):
        obj = _tentar_json(m.group(1).strip())
        if obj is not None:
            return obj
    for cand in _objetos_balanceados(texto):
        obj = _tentar_json(cand)
        if obj is not None:
            return obj
    return None


# ---------------------------------------------------------------------------
# Validações (a garantia do desafio: um dígito nunca vira outro dígito)
# ---------------------------------------------------------------------------
def digitos_compativeis(trecho: str, resposta: str, mapa: dict[str, str] | None = None) -> bool:
    """``resposta`` é obtível de ``trecho`` só por trocas letra→dígito?

    Percorre o trecho (já sem UF) da esquerda para a direita: todo dígito ASCII
    do trecho tem de aparecer em ``resposta`` na mesma ordem (nenhum dígito
    alterado, removido ou inserido); uma letra confundível pode, opcionalmente,
    virar o dígito que o mapa de OCR lhe atribui; os demais caracteres são
    ignorados. Vazio nunca é compatível.
    """
    if not resposta or not resposta.isdigit():
        return False
    mapa = CONFUSOES if mapa is None else mapa
    estados = {0}
    n = len(resposta)
    for c in trecho:
        if c.isdigit():
            estados = {i + 1 for i in estados if i < n and resposta[i] == c}
            if not estados:
                return False
        elif c in mapa:
            d = mapa[c]
            estados = estados | {i + 1 for i in estados if i < n and resposta[i] == d}
    return n in estados


def _limpar_uf(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    uf = valor.strip().upper().strip("/()-– ")
    return uf if uf in UFS else None


def _limpar_tribunal(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    t = valor.strip().upper()
    return t if t in TRIBUNAIS else None


def _limpar_cadeia(valor: Any) -> list[str]:
    """Lista de siglas canônicas; tokens desconhecidos passam por :func:`cadeia_de_classes`."""
    if isinstance(valor, str):
        valor = re.split(r"[\s,;/]+", valor)
    if not isinstance(valor, list):
        return []
    saida: list[str] = []
    for tok in valor:
        if not isinstance(tok, str) or not tok.strip():
            continue
        t = tok.strip().upper()
        if t in SIGLAS_CANONICAS or _RE_ORDINAL.match(t):
            saida.append(t)
        else:
            saida.extend(cadeia_de_classes(tok))
    return saida


def validar_normalizacao(trecho: str, saida: dict[str, Any] | None) -> dict[str, Any] | None:
    """Valida a resposta de ``normalizar_citacao``; ``None`` se inaceitável."""
    if not isinstance(saida, dict):
        return None
    eh = saida.get("eh_citacao")
    if isinstance(eh, str):
        eh = eh.strip().lower() in ("true", "sim", "1")
    if not isinstance(eh, bool):
        return None
    sem_uf, uf_trecho = separar_uf(trecho)
    uf = _limpar_uf(saida.get("uf")) or uf_trecho
    if uf_trecho and uf and uf != uf_trecho:
        logger.debug("árbitro trocou a UF (%s → %s); mantendo a do trecho", uf_trecho, uf)
        uf = uf_trecho
    tribunal = _limpar_tribunal(saida.get("tribunal"))
    cadeia = _limpar_cadeia(saida.get("classe_cadeia"))
    if not eh:
        return {"classe_cadeia": cadeia, "numero_digitos": "", "digitos_canonicos": "",
                "uf": uf, "tribunal": tribunal, "eh_citacao": False}
    bruto = saida.get("numero_digitos")
    if isinstance(bruto, (int, float)) and not isinstance(bruto, bool):
        bruto = str(int(bruto))
    if not isinstance(bruto, str):
        return None
    digitos = re.sub(r"[^0-9]", "", bruto)
    if not digitos or not digitos_compativeis(sem_uf, digitos):
        logger.info("normalização rejeitada: dígitos %r incompatíveis com o trecho", digitos)
        return None
    canonicos, _formato = classificar_digitos(digitos)
    return {"classe_cadeia": cadeia, "numero_digitos": digitos, "digitos_canonicos": canonicos,
            "uf": uf, "tribunal": tribunal, "eh_citacao": True}


def validar_escolha(saida: dict[str, Any] | None, n_candidatos: int) -> int | None:
    """Índice válido em ``[0, n)`` ou ``None``."""
    if not isinstance(saida, dict) or n_candidatos <= 0:
        return None
    idx = saida.get("indice")
    if isinstance(idx, bool):
        return None
    if isinstance(idx, str):
        idx = idx.strip()
        if not re.fullmatch(r"-?\d+", idx):
            return None
        idx = int(idx)
    if isinstance(idx, float) and idx.is_integer():
        idx = int(idx)
    if not isinstance(idx, int) or not 0 <= idx < n_candidatos:
        return None
    return idx


def _localizar(janela: str, alvo: str, perto_de: int | None = None) -> tuple[int, int] | None:
    """Offsets de ``alvo`` em ``janela``; tolera espaços/quebras diferentes; escolhe a ocorrência
    mais próxima de ``perto_de``."""
    if not alvo:
        return None
    posicoes = [m.start() for m in re.finditer(re.escape(alvo), janela)]
    if posicoes:
        if perto_de is None:
            return posicoes[0], posicoes[0] + len(alvo)
        p = min(posicoes, key=lambda x: (abs(x - perto_de), x))
        return p, p + len(alvo)
    # tolerância: qualquer sequência de espaço em branco casa com qualquer outra
    partes = [re.escape(p) for p in alvo.split()]
    if not partes:
        return None
    rx = re.compile(r"\s+".join(partes))
    ocorr = [(m.start(), m.end()) for m in rx.finditer(janela)]
    if not ocorr:
        return None
    if perto_de is None:
        return ocorr[0]
    return min(ocorr, key=lambda x: (abs(x[0] - perto_de), x[0]))


def aparar_fronteiras(janela: str, ini: int, fim: int) -> tuple[int, int]:
    """Remove artigo inicial, espaços e pontuação final (regra geral do gabarito)."""
    while ini < fim and janela[ini].isspace():
        ini += 1
    while fim > ini and (janela[fim - 1].isspace() or janela[fim - 1] in _PONTUACAO_FINAL):
        # ")" só sai se não houver "(" aberto dentro do span
        if janela[fim - 1] == ")" and "(" in janela[ini:fim]:
            break
        fim -= 1
    mudou = True
    while mudou and ini < fim:
        mudou = False
        for art in _ARTIGOS_INICIAIS:
            if janela[ini:fim].lower().startswith(art) and fim - ini > len(art):
                ini += len(art)
                mudou = True
                break
        while ini < fim and janela[ini].isspace():
            ini += 1
    return ini, fim


def validar_classificacao(
    trecho: str, contexto: str, saida: dict[str, Any] | None, inicio_rel: int | None = None
) -> dict[str, Any] | None:
    """Valida a resposta de ``classificar_span``; ``None`` se inaceitável."""
    if not isinstance(saida, dict):
        return None
    orig = _localizar(contexto, trecho, inicio_rel)
    if orig is None:
        logger.warning("classificar_span: trecho não está na janela; abstendo")
        return None
    eh = saida.get("eh_citacao")
    if isinstance(eh, str):
        eh = eh.strip().lower() in ("true", "sim", "1")
    familia = str(saida.get("familia") or "").strip().lower()
    if familia not in FAMILIAS_ARBITRO:
        if eh is False:
            familia = "nenhuma"
        else:
            return None
    if not isinstance(eh, bool):
        eh = familia != "nenhuma"
    if not eh or familia == "nenhuma":
        return {"eh_citacao": False, "familia": "nenhuma", "tipo": "jurisprudencia",
                "inicio_rel": orig[0], "fim_rel": orig[1], "trecho": contexto[orig[0]:orig[1]]}
    tipo = "lei" if familia == "dispositivo" else "jurisprudencia"
    if str(saida.get("tipo") or "").strip().lower() not in TIPOS + ("",):
        return None
    novo = saida.get("trecho")
    span: tuple[int, int] | None = None
    if isinstance(novo, str) and novo.strip():
        span = _localizar(contexto, novo, orig[0])
        if span is None:
            logger.info("classificar_span: span devolvido não é substring da janela; usando o original")
    if span is None:
        ir, fr = saida.get("inicio_rel"), saida.get("fim_rel")
        if isinstance(ir, int) and isinstance(fr, int) and 0 <= ir < fr <= len(contexto):
            span = (ir, fr)
    if span is None:
        span = orig
    ini, fim = aparar_fronteiras(contexto, span[0], span[1])
    if ini >= fim or fim - ini > 300:
        return None
    if min(fim, orig[1]) - max(ini, orig[0]) <= 0:
        logger.info("classificar_span: span devolvido não sobrepõe o candidato; abstendo")
        return None
    return {"eh_citacao": True, "familia": familia, "tipo": tipo,
            "inicio_rel": ini, "fim_rel": fim, "trecho": contexto[ini:fim]}


# ---------------------------------------------------------------------------
# Classe base
# ---------------------------------------------------------------------------
class ArbitroBase:
    """Implementa as três operações sobre um único método abstrato, :meth:`_gerar`.

    Subclasses definem ``nome`` (backend), ``modelo``, ``revisao`` e
    ``assinatura`` (parâmetros que afetam a saída: dtype, quantização, tokens),
    e implementam ``_gerar(pedidos) -> list[str]`` (uma resposta bruta por
    pedido, na mesma ordem). Cache, parsing, validação e abstenção ficam aqui.
    """

    nome: str = "base"

    def __init__(self, modelo: str, revisao: str, cache: CacheLLM | None = None,
                 assinatura: str = "", somente_cache: bool = False) -> None:
        self.modelo = modelo
        self.revisao = revisao or ""
        self.assinatura = assinatura
        self.cache = cache
        self.somente_cache = somente_cache
        self.chamadas = 0          # pedidos que chegaram ao modelo (após o cache)
        self.abstencoes = 0
        if not self.revisao and self.nome not in ("mock",) and not _e_snapshot_local(modelo):
            # "pesos abertos com revisão fixa" é regra do desafio: sem o commit dos pesos a
            # execução não é reproduzível — erro, não aviso (revisão rodada 2, R3b-02). Um caminho
            # local (snapshot já baixado) é aceito; o hash do config.json vai para o log.
            raise ErroDependencia(
                "revisão do modelo vazia: defina CACA_MODELO_REVISAO (commit do Hugging Face, ver "
                "MANIFESTO_MODELO.md) ou aponte CACA_MODELO para um snapshot local")
        if not self.revisao and self.nome not in ("mock",):
            self.revisao = _hash_snapshot_local(modelo)
            logger.warning("revisão do modelo vazia; snapshot local %s identificado pelo hash %s", modelo, self.revisao)

    # -- a ser implementado pelos backends -----------------------------------
    def _gerar(self, pedidos: list[Pedido]) -> list[str]:  # pragma: no cover - abstrato
        raise NotImplementedError

    # -- infraestrutura -------------------------------------------------------
    def _chave(self, pedido: Pedido) -> str:
        return chave_cache(self.modelo, self.revisao, prompts.PROMPT_ID, pedido.operacao,
                           pedido.entrada, self.assinatura)

    def _responder_lote(self, pedidos: list[Pedido]) -> list[str | None]:
        """Resposta bruta de cada pedido (cache → modelo). ``None`` se o modelo falhar."""
        respostas: list[str | None] = [None] * len(pedidos)
        chaves = [self._chave(p) for p in pedidos]
        faltam: list[int] = []
        for i, (p, k) in enumerate(zip(pedidos, chaves)):
            bruto = self.cache.obter(k) if self.cache is not None else None
            if bruto is not None:
                respostas[i] = bruto
            else:
                faltam.append(i)
        if faltam and not self.somente_cache:
            try:
                geradas = self._gerar([pedidos[i] for i in faltam])
                if len(geradas) != len(faltam):
                    raise RuntimeError(f"backend devolveu {len(geradas)} respostas para {len(faltam)} pedidos")
            except Exception:
                logger.exception("árbitro %s falhou ao gerar %d resposta(s); abstendo", self.nome, len(faltam))
                geradas = [None] * len(faltam)  # type: ignore[list-item]
            self.chamadas += len(faltam)
            for i, bruto in zip(faltam, geradas):
                if not bruto or not isinstance(bruto, str):
                    bruto = None  # resposta vazia = falha transitória: abstém e não grava no cache
                respostas[i] = bruto
                if bruto is not None and self.cache is not None:
                    self.cache.guardar(chaves[i], modelo=self.modelo, revisao=self.revisao,
                                       prompt_versao=prompts.PROMPT_ID, operacao=pedidos[i].operacao,
                                       entrada=pedidos[i].entrada, resposta_bruta=bruto,
                                       assinatura=self.assinatura)
        elif faltam:
            logger.info("árbitro em modo somente_cache: %d pedido(s) sem resposta", len(faltam))
        return respostas

    def _registrar_resultado(self, pedido: Pedido, resultado: Any) -> None:
        if self.cache is not None:
            self.cache.atualizar_resultado(self._chave(pedido), resultado)
        if resultado is None:
            self.abstencoes += 1

    # -- construção de pedidos ------------------------------------------------
    @staticmethod
    def pedido_normalizar(trecho: str, contexto: str) -> Pedido:
        ctx = prompts.recortar_contexto(contexto or "", trecho)
        entrada = {"trecho": trecho, "contexto": ctx}
        return Pedido("normalizar", entrada, prompts.mensagens_normalizar(trecho, ctx))

    @staticmethod
    def pedido_escolher(trecho: str, contexto: str, candidatos: list[dict[str, Any]]) -> Pedido:
        ctx = prompts.recortar_contexto(contexto or "", trecho)
        cands = [
            {"id_canonico": c.get("id_canonico"), "cabecalho": str(c.get("cabecalho") or "")[:600],
             "tribunal": c.get("tribunal"), "ano": c.get("ano"), "relator": c.get("relator"),
             "cadeia": c.get("cadeia")}
            for c in candidatos
        ]
        entrada = {"trecho": trecho, "contexto": ctx, "candidatos": cands}
        return Pedido("escolher", entrada, prompts.mensagens_escolher(trecho, ctx, cands))

    @staticmethod
    def pedido_classificar(trecho: str, contexto: str, inicio_rel: int | None = None) -> Pedido:
        contexto = contexto or ""
        ctx = prompts.recortar_contexto(contexto, trecho)
        entrada: dict[str, Any] = {"trecho": trecho, "contexto": ctx}
        if inicio_rel is not None:
            # o recorte pode ter deslocado a janela: converte o offset (ou descarta)
            desloc = contexto.find(ctx) if ctx != contexto else 0
            novo = inicio_rel - max(desloc, 0)
            if 0 <= novo < len(ctx):
                entrada["inicio_rel"] = novo
        return Pedido("classificar", entrada, prompts.mensagens_classificar(trecho, ctx))

    # -- operações públicas ---------------------------------------------------
    def normalizar_citacao(self, trecho: str, contexto: str) -> dict[str, Any] | None:
        try:
            return self.executar_lote("normalizar", [(trecho, contexto)])[0]
        except Exception:  # última linha de defesa
            logger.exception("normalizar_citacao: erro inesperado; abstendo")
            return None

    def escolher_candidato(self, trecho: str, contexto: str, candidatos: list[dict[str, Any]]) -> int | None:
        try:
            if not candidatos or len(candidatos) < 2:
                return None
            return self.executar_lote("escolher", [(trecho, contexto, candidatos)])[0]
        except Exception:
            logger.exception("escolher_candidato: erro inesperado; abstendo")
            return None

    def classificar_span(self, trecho: str, contexto: str, inicio_rel: int | None = None) -> dict[str, Any] | None:
        try:
            return self.executar_lote("classificar", [(trecho, contexto, inicio_rel)])[0]
        except Exception:
            logger.exception("classificar_span: erro inesperado; abstendo")
            return None

    def executar_lote(self, operacao: str, entradas: list[tuple[Any, ...]]) -> list[Any]:
        """Versão em lote: ``entradas`` são as tuplas de argumentos da operação.

        Agrupa os *misses* do cache numa única chamada ao backend (que pode
        fazer *batching* na GPU). A ordem da saída segue a da entrada.
        """
        if operacao not in prompts.OPERACOES:
            raise ValueError(f"operação desconhecida: {operacao!r}")
        pedidos: list[Pedido] = []
        for args in entradas:
            if operacao == "normalizar":
                pedidos.append(self.pedido_normalizar(*args))
            elif operacao == "escolher":
                pedidos.append(self.pedido_escolher(*args))
            else:
                pedidos.append(self.pedido_classificar(*args))
        brutos = self._responder_lote(pedidos)
        saida: list[Any] = []
        for pedido, bruto in zip(pedidos, brutos):
            resultado: Any = None
            if bruto is not None:
                obj = extrair_json(bruto)
                if obj is None:
                    logger.info("árbitro %s: resposta sem JSON válido (%s)", self.nome, pedido.operacao)
                try:
                    if pedido.operacao == "normalizar":
                        resultado = validar_normalizacao(pedido.entrada["trecho"], obj)
                    elif pedido.operacao == "escolher":
                        resultado = validar_escolha(obj, len(pedido.entrada["candidatos"]))
                    else:
                        resultado = validar_classificacao(pedido.entrada["trecho"], pedido.entrada["contexto"],
                                                          obj, pedido.entrada.get("inicio_rel"))
                except Exception:
                    logger.exception("validação da resposta falhou (%s); abstendo", pedido.operacao)
                    resultado = None
            self._registrar_resultado(pedido, resultado)
            saida.append(resultado)
        return saida

    def estatisticas(self) -> dict[str, Any]:
        return {"backend": self.nome, "modelo": self.modelo, "revisao": self.revisao,
                "prompt_versao": prompts.PROMPT_VERSAO, "assinatura": self.assinatura,
                "chamadas_ao_modelo": self.chamadas, "abstencoes": self.abstencoes,
                "cache": self.cache.estatisticas() if self.cache is not None else None}


def candidato_de_registro(registro: Any, cabecalho: str) -> dict[str, Any]:
    """Monta o dicionário de candidato a partir de um ``Registro`` da base e do seu cabeçalho."""
    return {
        "id_canonico": int(registro.id_canonico),
        "cabecalho": (cabecalho or "")[:600],
        "tribunal": registro.tribunal,
        "ano": registro.ano,
        "relator": registro.relator,
        "cadeia": registro.classe_propria,
    }


__all__ = [
    "Arbitro", "ArbitroBase", "Pedido", "ErroDependencia", "FAMILIAS_ARBITRO",
    "extrair_json", "digitos_compativeis", "validar_normalizacao", "validar_escolha",
    "validar_classificacao", "aparar_fronteiras", "candidato_de_registro",
]
