"""Backends do árbitro: ``mock`` (heurístico), ``transformers`` e ``vllm``.

* :class:`MockArbitro` responde sem modelo, com heurísticas determinísticas,
  passando pelo **mesmo** caminho de parsing/validação/cache dos backends reais
  (as respostas são JSON em texto). Serve aos testes e como fallback.
* :class:`TransformersArbitro` carrega ``Qwen/Qwen2.5-7B-Instruct`` (ou o
  modelo de ``CACA_MODELO``) com ``transformers`` em bf16 — ou NF4 (bitsandbytes)
  com ``CACA_LLM_4BIT=1`` —, decodificação **greedy** (``do_sample=False``),
  ``max_new_tokens`` pequeno, *chat template* oficial, semente fixa e limite de
  VRAM por processo (``torch.cuda.set_per_process_memory_fraction``) para nunca
  ultrapassar 24 GB numa GPU maior (RTX 5090 = 32 GB). A família do modelo vem
  de ``architectures`` no ``config.json``: ``*ForCausalLM`` (Qwen2.5) segue o
  caminho medido na ADR 0003; ``*ForConditionalGeneration`` (Qwen3.5, multimodal)
  é carregada pela classe homônima do ``transformers``, com ``visual`` e ``lm_head``
  fora da quantização NF4 e o *chat template* com ``enable_thinking=False`` — os
  mesmos prompts, o mesmo validador. Nada disso entra na assinatura: a família é
  função do modelo, que já está na chave do cache.
* :class:`VLLMArbitro` (opcional): ``gpu_memory_utilization`` calculado para o
  teto de 24 GB, ``temperature=0``, *guided decoding* JSON quando disponível.

Imports de ``torch``/``transformers``/``vllm`` são tardios: a ausência só gera
:class:`~.arbitro.ErroDependencia` (subclasse de ``ImportError``) ao instanciar.
A fábrica :func:`obter_arbitro` lê os padrões do ambiente.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from ..base_canonica.consulta import relator_compativel
from ..normalizacao import (
    CONFUSOES,
    UFS,
    cadeia_da_citacao,
    cadeia_de_classes,
    inferir_tribunal,
    sem_acento,
    separar_uf,
)
from .. import config
from . import prompts
from .arbitro import ArbitroBase, ErroDependencia, Pedido, aparar_fronteiras
from .cache import CacheLLM

try:  # vocabulário dos nomes de classe por extenso (só o Mock usa; degrada sem ele)
    from ..normalizacao import _ALIASES
except ImportError:  # pragma: no cover
    _ALIASES = []

logger = logging.getLogger(__name__)

MODELO_PADRAO = "Qwen/Qwen2.5-7B-Instruct"
MODELO_AWQ = "Qwen/Qwen2.5-7B-Instruct-AWQ"
LIMITE_VRAM_GB_PADRAO = 24.0
SEMENTE_PADRAO = 1234


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------
_LETRAS = "".join(re.escape(c) for c in CONFUSOES)
_RE_GRUPO = re.compile(rf"[0-9{_LETRAS}]+")
_RE_SEP = re.compile(r"^[ \t\r\n \.,\-–—/⁄]+$")
_RE_DISTRATOR = re.compile(
    r"\bfls?\.\s*\d|R\$\s*\d|\bOAB\b|\d\s*%|\bProtocolo\b|\bMemorial\s+n|\bAutos\s+n|"
    r"\bValor\s+da\s+causa|\b\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}\b|"
    r"jurisprud[êe]ncia\s+(?:pac[íi]fica|consolidada)|orienta[çc][ãa]o\s+dos\s+tribunais|"
    r"verbete\s+sumular|entendimento\s+sumulado|normas\s+de\s+reg[êe]ncia|dispositivo\s+constitucional",
    re.I,
)
_RE_SUMULA = re.compile(
    r"(?:S[úu]m(?:ula|\.)|5[úu]mula|SÚMULA)\s+(?:Vinculante\s+)?\d{1,4}(?:\s+do\s+(?:STJ|STF|TST|TSE))?"
)
_RE_TEMA = re.compile(r"T[ec]m[aã]\s+\d[\d.]*(?:\s+da\s+repercuss[ãa]o\s+geral)?")
_RE_DISPOSITIVO = re.compile(
    r"\b(?:art\.?|artigo)\s*\d[\dOolISsgGBZz.]*[ºo°]?(?:\s*,\s*[^,\n]{1,14})*?\s*,?\s*d[ao]\s+"
    r"(?:Lei(?:\s+Complementar)?\s+n[º°.]?\s*[\d.]+/\d{4}|Constitui[çc][ãa]o\s+(?:Fed[ce]ral|da\s+Rep[úu]blica)|"
    r"C[óo]digo\s+(?:de\s+Processo\s+(?:Civil|Penal)|Penal\s+Militar|Civil|Eleitoral|de\s+Defesa\s+do\s+Consumidor)|"
    r"Consolida[çc][ãa]o\s+das\s+Leis\s+do\s+Trabalho|CPC|CLT|CF(?:/88)?|CDC|CPP|CPM|CC)",
    re.I,
)
_RE_VAGA = re.compile(
    r"(?:julgado|precedente|ac[óo]rd[ãa]o|Reclama[çc][ãa]o|Rcl|APL|Agravo\s+em\s+Recurso\s+Especial|"
    r"Recurso\s+em\s+Habeas\s+Corpus|REsp|AREsp|RE)\b[^\n.;]{0,80}?\b(?:19|20)\d{2}\b[^.;]{0,40}?"
    r"(?:relatoria\s+d[eo]|Rel\.?\s*Min\.?|Relator[a]?\s*(?:Min\.?|Ministr[oa])?)\s*((?:[A-ZÀ-Ú][\wÀ-ú'.-]*|d[aeo]s?|DE|DA|DO)(?:[ \n]+(?:[A-ZÀ-Ú][\wÀ-ú'.-]*|d[aeo]s?|DE|DA|DO))*)",
)
_RE_NUMERO = re.compile(rf"\d(?:[0-9{_LETRAS}]|[.\-–]|[ \n\xa0](?=[0-9{_LETRAS}.\-–]))*")
_RE_UF_APOS = re.compile(r"\s*[/\-–(]?\s*(" + "|".join(sorted(UFS)) + r")\)?")
_CONECTORES = {"no", "na", "nos", "em", "de"}


def _digitos_relaxados(trecho_sem_uf: str) -> tuple[str, int, int] | None:
    """Cadeia de grupos ``[dígitos+letras confundíveis]`` que começa por dígito; letras podem
    ser maioria (o que a normalização determinística recusa). Devolve ``(digitos, ini, fim)``
    da cadeia mais longa, ou ``None``."""
    cadeias: list[tuple[str, int, int]] = []
    atual: list[str] = []
    ini = fim = ultimo_fim = -1
    for m in _RE_GRUPO.finditer(trecho_sem_uf):
        g = m.group(0)
        entre = trecho_sem_uf[ultimo_fim:m.start()] if ultimo_fim >= 0 else ""
        if atual and not _RE_SEP.match(entre):
            cadeias.append(("".join(atual), ini, fim))
            atual = []
        if not atual:
            if not g[0].isdigit():
                ultimo_fim = m.end()
                continue
            ini = m.start()
        atual.append("".join(CONFUSOES.get(c, c) for c in g))
        fim = m.end()
        ultimo_fim = m.end()
    if atual:
        cadeias.append(("".join(atual), ini, fim))
    if not cadeias:
        return None
    return max(cadeias, key=lambda c: (len(c[0]), -c[1]))


def _mock_normalizar(entrada: dict[str, Any]) -> dict[str, Any]:
    trecho = entrada["trecho"]
    if _RE_DISTRATOR.search(trecho):
        return {"classe_cadeia": [], "numero_digitos": "", "uf": None, "tribunal": None, "eh_citacao": False}
    sem_uf, uf = separar_uf(trecho)
    achado = _digitos_relaxados(sem_uf)
    if achado is None:
        return {"classe_cadeia": [], "numero_digitos": "", "uf": uf, "tribunal": None, "eh_citacao": False}
    digitos, ini, _fim = achado
    antes = re.sub(r"\bprocesso\s+n[º°.o]?\s*", " ", sem_uf[:ini], flags=re.I)
    antes = re.sub(r"\bTST\s*-\s*", " ", antes)
    antes = re.sub(r"\bn[º°.]?\s*$", " ", antes)
    cadeia = cadeia_de_classes(antes)
    return {"classe_cadeia": cadeia, "numero_digitos": digitos, "uf": uf,
            "tribunal": inferir_tribunal(cadeia, uf, digitos), "eh_citacao": True}


def _mock_escolher(entrada: dict[str, Any]) -> dict[str, Any]:
    trecho, contexto, cands = entrada["trecho"], entrada.get("contexto") or "", entrada["candidatos"]
    texto = f"{trecho}\n{contexto}"
    anos = set(re.findall(r"\b(?:19|20)\d{2}\b", texto))
    cadeia_citada = " ".join(cadeia_da_citacao(trecho))
    # cadeia de classes exata em um único candidato decide (docs/04, h.3-a)
    if cadeia_citada:
        exatos = [i for i, c in enumerate(cands) if c.get("cadeia") == cadeia_citada]
        if len(exatos) == 1:
            return {"indice": exatos[0], "evidencia": f"cadeia de classes {cadeia_citada} só casa com um candidato"}
    pontos: list[int] = []
    for c in cands:
        p = 0
        if c.get("ano") is not None and str(c["ano"]) in anos:
            p += 2
        rel = c.get("relator")
        if rel and relator_compativel(_nomes_proprios(contexto), rel):
            p += 2
        pontos.append(p)
    melhor = max(pontos) if pontos else 0
    if melhor <= 0 or pontos.count(melhor) != 1:
        return {"indice": None, "evidencia": "sem critério distintivo no contexto"}
    return {"indice": pontos.index(melhor), "evidencia": f"pontuação {melhor} (ano/relator/cadeia)"}


def _nomes_proprios(texto: str) -> str:
    """Palavras capitalizadas (≥ 5 letras) do contexto — sobrenomes candidatos a relator."""
    toks = re.findall(r"\b[A-ZÀ-Ú][a-zà-ú]{4,}\b|\b[A-ZÀ-Ú]{5,}\b", texto)
    return " ".join(toks)


_RE_TOKEN_ESQ = re.compile(r"[A-Za-zÀ-ú][A-Za-zÀ-ú.]*|[º°]|-|\S")
_EXPLICITOS = {"no", "na", "nos", "em", "de", "-", "n", "nº", "n°", "tst", "processo",
               "primeiro", "segundo", "terceiro", "quarto"}
# palavras que compõem nomes de classe por extenso ("Recurso" de "Recurso Especial"): tentativas
_VOCAB_CLASSES: frozenset[str] = frozenset(
    w for chave, _ in _ALIASES for w in chave.split() if len(w) >= 2
)


def _estender_esquerda(janela: str, ini_numero: int, max_tokens: int = 12) -> int:
    """Recua do número sobre o conector (``nº``) e a cadeia de classes (``EDcl no AgInt no AREsp``).

    Caminha token a token para trás; um token vira parte do span quando faz a
    cadeia canônica crescer (``Recurso`` fecha ``Recurso Especial``) ou é um
    conector/explicitamente permitido (``no``, ``-``, ``nº``, ``TST``); tokens
    "tentativos" só entram se um token de classe vier antes deles.
    """
    esquerda = janela[max(0, ini_numero - 90):ini_numero]
    base = ini_numero - len(esquerda)
    toks = list(_RE_TOKEN_ESQ.finditer(esquerda))[-max_tokens:]
    inicio = ini_numero
    cadeia_atual: list[str] = []
    acumulado = ""
    tem_classe = False
    for m in reversed(toks):
        tok = m.group(0)
        chave = sem_acento(tok).lower().strip(".")
        acumulado = tok + " " + acumulado
        cadeia = cadeia_de_classes(acumulado)
        if cadeia and cadeia != cadeia_atual:
            cadeia_atual = cadeia
            tem_classe = True
            inicio = base + m.start()
        elif tok in ("º", "°") or chave in _EXPLICITOS or chave in _VOCAB_CLASSES:
            continue  # tentativo: só entra se um token de classe vier antes
        else:
            break
    if not tem_classe:
        return ini_numero
    # inclui os tentativos entre o último token de classe aceito e o número, e
    # ``processo nº``/``TST-`` à esquerda dele quando presentes
    prefixo = janela[max(0, inicio - 20):inicio]
    m_pref = re.search(r"(?:processo\s+n[º°.o]?\s*)?(?:TST\s*-\s*)?$", prefixo, re.I)
    if m_pref and m_pref.group(0).strip() and "tst" in m_pref.group(0).lower():
        inicio = max(0, inicio - 20) + m_pref.start()
    return inicio


def _mock_classificar(entrada: dict[str, Any]) -> dict[str, Any]:
    trecho, janela = entrada["trecho"], entrada["contexto"]
    pos = janela.find(trecho) if entrada.get("inicio_rel") is None else int(entrada["inicio_rel"])
    if pos < 0 or janela[pos:pos + len(trecho)] != trecho:
        pos = max(janela.find(trecho), 0)
    fim_c = pos + len(trecho)
    nao = {"eh_citacao": False, "familia": "nenhuma", "tipo": "jurisprudencia", "trecho": ""}
    if _RE_DISTRATOR.search(trecho) and "TST-" not in trecho:
        return nao
    # janela local: 120 chars antes e depois do candidato
    lo, hi = max(0, pos - 120), min(len(janela), fim_c + 120)

    def sobrepoe(m: re.Match[str]) -> bool:
        return min(lo + m.end(), fim_c) - max(lo + m.start(), pos) > 0

    for familia, rx, tipo in (("sumula", _RE_SUMULA, "jurisprudencia"), ("tema", _RE_TEMA, "jurisprudencia"),
                              ("dispositivo", _RE_DISPOSITIVO, "lei")):
        for m in rx.finditer(janela[lo:hi]):
            if sobrepoe(m):
                return {"eh_citacao": True, "familia": familia, "tipo": tipo, "trecho": m.group(0)}
    for m in _RE_VAGA.finditer(janela[lo:hi]):
        if sobrepoe(m):
            ini, fim = aparar_fronteiras(janela, lo + m.start(), lo + m.end())
            return {"eh_citacao": True, "familia": "vaga", "tipo": "jurisprudencia", "trecho": janela[ini:fim]}
    m_num = None
    for m in _RE_NUMERO.finditer(janela[lo:hi]):
        if sobrepoe(m) and sum(ch.isdigit() for ch in m.group(0)) >= 4:
            m_num = m
            break
    if m_num is None:
        return nao
    ini_n, fim_n = lo + m_num.start(), lo + m_num.end()
    inicio = _estender_esquerda(janela, ini_n)
    fim = fim_n
    m_uf = _RE_UF_APOS.match(janela, fim_n)
    if m_uf and m_uf.end() <= len(janela):
        fim = m_uf.end()
    ini_a, fim_a = aparar_fronteiras(janela, inicio, fim)
    if not cadeia_de_classes(janela[ini_a:ini_n]) and "TST-" not in janela[ini_a:fim_a]:
        return nao
    return {"eh_citacao": True, "familia": "processo", "tipo": "jurisprudencia", "trecho": janela[ini_a:fim_a]}


# --- extrair_citacoes (mock): formas que os detectores por regex NÃO cobrem --------------------
# O mock só serve para exercitar o caminho completo (janelas → validação → re-detecção → resolução)
# e os testes; o modelo real generaliza para formas que nenhuma heurística prevê.
_OCR = "OoIl|SsgqGBZz"
#: Número com pontuação e letras de OCR; SEM espaços dentro e com pelo menos um dígito real à vista
#: (lookahead) — quantificadores limitados e sem grupos opcionais aninhados, para nunca degenerar em
#: retrocesso exponencial (o mock roda em todo conjunto adversarial; um regex patológico travava
#: minutos em ``siglas``).
_NUM_OCR = rf"(?=[0-9{_OCR}.\-]{{0,30}}[0-9])[0-9{_OCR}][0-9{_OCR}.\-]{{2,28}}[0-9{_OCR}]"
_CLASSES_EXTENSO = {
    "recurso especial": ["RESP"], "recurso extraordinario": ["RE"], "reclamacao": ["RCL"],
    "habeas corpus": ["HC"], "agravo em recurso especial": ["ARESP"], "mandado de seguranca": ["MS"],
    "recurso de revista": ["RR"], "agravo interno no recurso especial": ["AGINT", "RESP"],
    "agravo regimental no recurso especial": ["AGR", "RESP"], "agravo regimental no recurso extraordinario": ["AGR", "RE"],
}
_CLASSES_SIGLA = {"REsp": ["RESP"], "RE5p": ["RESP"], "AREsp": ["ARESP"], "RE": ["RE"], "ARE": ["ARE"], "Rcl": ["RCL"], "RHC": ["RHC"],
                  "HC": ["HC"], "RMS": ["RMS"], "MS": ["MS"], "ADI": ["ADI"], "RR": ["RR"], "AIRR": ["AIRR"],
                  "APL": ["APL"], "REspe": ["RESPE"]}


def _palavra_quebravel(palavra: str) -> str:
    """Regex de ``palavra`` tolerando uma quebra curta (espaço, hífen+quebra de linha: ``[-\\s]{0,2}``)
    entre letras e OCR leve nas letras confundíveis (``Re curso``, ``Recla-\nmação``, ``Sún1ula``).
    Só classes de caracteres e quantificadores limitados — nada de grupos opcionais aninhados."""
    partes = []
    alt = {"a": "[aãA4]", "e": "[eéE3c]", "o": "[oóO0]", "u": "[uúU]", "c": "[cçC]", "i": "[iI1l]", "m": "[mM]", "l": "[lL1I]"}
    for ch in palavra:
        if ch == " ":
            partes.append(r"[-\s]{1,3}")
        else:
            classe = alt.get(ch.lower()) or (f"[{ch.lower()}{ch.upper()}]" if ch.isalpha() else re.escape(ch))
            partes.append(classe + r"[-\s]{0,2}")
    return "".join(partes)


_RE_EXTENSO_UF = re.compile(r"(?:oriund[oa]\s+d[oe]\s+|d[oa]\s+Estado\s+d[oe]\s+)([A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+)*)")
_UF_POR_EXTENSO = {"Sao Paulo": "SP", "Rio de Janeiro": "RJ", "Minas Gerais": "MG", "Parana": "PR", "Rio Grande do Sul": "RS",
                   "Bahia": "BA", "Distrito Federal": "DF", "Santa Catarina": "SC", "Pernambuco": "PE", "Ceara": "CE", "Goias": "GO"}
_RE_MOCK_PROCESSO_EXTENSO = [
    (re.compile(_palavra_quebravel(nome) + rf"\s*(?:de\s+)?(?:n[º°.o]?\s*|n[uú]mero\s+)?(?P<num>{_NUM_OCR})(?P<uf>\s*[/(–\-]\s*[A-Z]{{2}}\)?)?", re.I), cadeia)
    for nome, cadeia in sorted(_CLASSES_EXTENSO.items(), key=lambda kv: -len(kv[0]))
]
_RE_MOCK_PROCESSO_COLADO = re.compile(
    rf"(?<![A-Za-z])(?P<classe>{'|'.join(re.escape(k) for k in _CLASSES_SIGLA)})(?P<num>\d[\d.\-]{{3,30}}\d)(?P<uf>\s*/\s*[A-Z]{{2}})?")
_RE_MOCK_SUMULA_OCR = re.compile(rf"(?<![A-Za-z])(?P<palavra>S[úu]?[nm]?[1l]?u?[l1]a)\s+(?:n[º°.o]?\s*)?(?P<num>[0-9{_OCR}]{{1,4}})(?:\s+d[oa]\s+(?P<trib>STJ|STF|TST|TSE|STM))?")
_RE_MOCK_VAGA_ORGAO = re.compile(
    r"julgad[oa]s?\s+pel[oa]\s+\d+[ªa]\s+(?:Turma|Se[çc][ãa]o|C[âa]mara)\s+d[oa]\s+(?P<trib>STJ|STF|TST|TSE|STM)\s+em\s+(?P<ano>(?:19|20)\d{2}),?\s+(?:sob\s+a\s+)?relatoria\s+d[oa]\s+(?:Ministr[oa]\s+)?"
    r"(?P<rel>[A-ZÀ-Ý][\wÀ-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][\wÀ-ÿ]+){1,4})")


def _mock_extrair(entrada: dict[str, Any]) -> dict[str, Any]:
    janela: str = entrada["janela"]
    ocupados = [(int(d["inicio"]), int(d["fim"])) for d in entrada.get("ja_detectadas") or []]
    saida: list[dict[str, Any]] = []

    def livre(ini: int, fim: int) -> bool:
        return not any(min(fim, f) - max(ini, i) > 0 for i, f in ocupados)

    def aceitar(ini: int, fim: int, item: dict[str, Any]) -> None:
        ini, fim = aparar_fronteiras(janela, ini, fim)
        if fim > ini and livre(ini, fim):
            ocupados.append((ini, fim))
            saida.append({"trecho": janela[ini:fim], "classe_cadeia": [], "numero_digitos": None, "uf": None,
                          "tribunal": None, "numero_sumula": None, "vinculante": False, "artigo": None,
                          "diploma": None, "ano": None, "relator": None, **item})

    def digitos(bruto: str) -> str:
        return "".join(CONFUSOES.get(c, c) for c in bruto if c.isdigit() or c in CONFUSOES)

    for m in _RE_MOCK_PROCESSO_COLADO.finditer(janela):
        cadeia = _CLASSES_SIGLA[m.group("classe")]
        uf = (m.group("uf") or "").strip(" /").upper() or None
        aceitar(m.start(), m.end(), {"familia": "processo", "classe_cadeia": cadeia, "numero_digitos": digitos(m.group("num")),
                                     "uf": uf if uf in UFS else None, "tribunal": inferir_tribunal(cadeia[-1]) if cadeia else None})
    for rx, cadeia in _RE_MOCK_PROCESSO_EXTENSO:
        for m in rx.finditer(janela):
            if sum(ch.isdigit() for ch in m.group("num")) < 3:
                continue
            uf = (m.group("uf") or "").strip(" /()–-").upper() or None
            fim = m.end()
            aceitar(m.start(), fim, {"familia": "processo", "classe_cadeia": cadeia, "numero_digitos": digitos(m.group("num")),
                                     "uf": uf if uf in UFS else None, "tribunal": inferir_tribunal(cadeia[-1])})
    for m in _RE_MOCK_SUMULA_OCR.finditer(janela):
        if m.group("palavra").lower() in ("súmula", "sumula"):
            continue  # o regex do núcleo já cobre a forma limpa
        aceitar(m.start(), m.end(), {"familia": "sumula", "numero_sumula": digitos(m.group("num")), "tribunal": m.group("trib")})
    for m in _RE_MOCK_VAGA_ORGAO.finditer(janela):
        aceitar(m.start(), m.end(), {"familia": "vaga", "tribunal": m.group("trib"), "ano": m.group("ano"), "relator": m.group("rel")})
    return {"citacoes": saida}


class MockArbitro(ArbitroBase):
    """Árbitro heurístico determinístico (sem modelo). Para testes e fallback."""

    nome = "mock"

    def __init__(self, cache: CacheLLM | None = None, somente_cache: bool = False, **_: Any) -> None:
        super().__init__(modelo="mock", revisao="0", cache=cache, assinatura="heuristico-v1", somente_cache=somente_cache)

    def _gerar(self, pedidos: list[Pedido]) -> list[str]:
        saida: list[str] = []
        for p in pedidos:
            if p.operacao == "normalizar":
                obj = _mock_normalizar(p.entrada)
            elif p.operacao == "escolher":
                obj = _mock_escolher(p.entrada)
            elif p.operacao == "extrair":
                obj = _mock_extrair(p.entrada)
            else:
                obj = _mock_classificar(p.entrada)
            saida.append(json.dumps(obj, ensure_ascii=False))
        return saida


# ---------------------------------------------------------------------------
# Utilidades de GPU
# ---------------------------------------------------------------------------
def _limitar_vram(torch: Any, limite_gb: float, indice: int = 0) -> float | None:
    """Limita a alocação deste processo a ``limite_gb`` (fração da VRAM total). Devolve a fração."""
    if not torch.cuda.is_available():
        return None
    total = torch.cuda.get_device_properties(indice).total_memory
    fracao = min(1.0, (limite_gb * 1024 ** 3) / float(total))
    if fracao < 1.0:
        torch.cuda.set_per_process_memory_fraction(fracao, indice)
        logger.info("VRAM limitada a %.1f GB (%.0f%% de %.1f GB)", limite_gb, fracao * 100, total / 1024 ** 3)
    return fracao


def _offline() -> bool:
    return os.environ.get("HF_HUB_OFFLINE", "") == "1" or os.environ.get("TRANSFORMERS_OFFLINE", "") == "1"


def _bool_env(nome: str, padrao: bool = False) -> bool:
    v = os.environ.get(nome)
    if v is None:
        return padrao
    return v.strip().lower() in ("1", "true", "sim", "yes", "on")


def _versao_maior(modulo: Any) -> int:
    """Componente maior de ``modulo.__version__`` (0 quando ausente ou ilegível)."""
    try:
        return int(str(getattr(modulo, "__version__", "0")).split(".")[0])
    except (TypeError, ValueError):
        return 0


def _kw_dtype(transformers_mod: Any) -> str:
    """Nome do argumento de precisão em ``from_pretrained``: ``dtype`` (transformers ≥ 5) ou ``torch_dtype``."""
    return "dtype" if _versao_maior(transformers_mod) >= 5 else "torch_dtype"


def _arquitetura(modelo: str, revisao: str | None, offline: bool) -> str:
    """Primeira entrada de ``architectures`` no ``config.json`` do modelo (``""`` quando não dá para ler).

    Pasta local: lê o arquivo; id do Hub: ``AutoConfig`` (sem baixar pesos). Um erro aqui não derruba
    o árbitro — a família cai no caminho clássico (``AutoModelForCausalLM``), que é o padrão.
    """
    p = Path(modelo)
    try:
        if p.is_dir() and (p / "config.json").is_file():
            cfg = json.loads((p / "config.json").read_text(encoding="utf-8"))
            return str((cfg.get("architectures") or [""])[0] or "")
    except (OSError, ValueError) as exc:
        logger.warning("config.json ilegível em %s: %s", modelo, exc)
        return ""
    try:
        import transformers
        AutoConfig = getattr(transformers, "AutoConfig", None)
        if AutoConfig is None:
            return ""
        cfg = AutoConfig.from_pretrained(modelo, revision=revisao or None, local_files_only=offline)
        return str((getattr(cfg, "architectures", None) or [""])[0] or "")
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/cache cai no caminho clássico
        logger.warning("não foi possível ler a arquitetura de %s (%s); assumindo *ForCausalLM", modelo, exc)
        return ""


def _familia(arquitetura: str) -> str:
    """``"causal"`` (``*ForCausalLM`` ou desconhecida) ou ``"condicional"`` (``*ForConditionalGeneration``)."""
    return "condicional" if arquitetura.endswith("ForConditionalGeneration") else "causal"


# ---------------------------------------------------------------------------
# transformers
# ---------------------------------------------------------------------------
class TransformersArbitro(ArbitroBase):
    """Qwen2.5-7B-Instruct (ou outro Qwen, ver ``_familia``) via ``transformers`` (bf16 ou NF4), greedy, com lote."""

    nome = "transformers"

    @staticmethod
    def verificar_dependencias() -> None:
        """``ErroDependencia`` se torch/transformers não estão instalados (sem efeitos colaterais)."""
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError as e:  # pragma: no cover - depende do ambiente
            raise ErroDependencia(
                "backend 'transformers' exige torch, transformers e accelerate "
                "(pip install -r requirements-llm.txt); use --arbitro mock ou nenhum"
            ) from e

    def __init__(
        self,
        modelo: str = MODELO_PADRAO,
        revisao: str = "",
        cache: CacheLLM | None = None,
        dispositivo: str = "cuda",
        quatro_bits: bool | None = None,
        limite_vram_gb: float = LIMITE_VRAM_GB_PADRAO,
        seed: int = SEMENTE_PADRAO,
        lote: int = 1,
        max_new_tokens: dict[str, int] | None = None,
        somente_cache: bool = False,
        modelo_id: str = "",
        **_: Any,
    ) -> None:
        # lote=1 por padrão (revisão rodada 2, R3b-08): a resolução consulta o árbitro um achado
        # por vez, e a decodificação greedy em lote com padding pode diferir numericamente da de
        # prompt único — a chave do cache não inclui a composição do lote. ``CACA_LLM_LOTE`` > 1
        # continua possível para medição, mas a assinatura do backend passa a registrá-lo.
        if not somente_cache:
            self.verificar_dependencias()
            import torch
            import transformers
            from transformers import AutoModelForCausalLM, AutoTokenizer
        else:
            torch = transformers = AutoModelForCausalLM = AutoTokenizer = None  # reprodução sem GPU: só o cache
        self.quatro_bits = _bool_env("CACA_LLM_4BIT") if quatro_bits is None else quatro_bits
        self.seed = int(seed)
        self.lote = max(1, int(lote))
        self.max_new_tokens = dict(prompts.MAX_TOKENS_NOVOS, **(max_new_tokens or {}))
        # A assinatura NÃO muda com a família do modelo (Qwen2.5 → mesma string da ADR 0003, chaves do
        # cache preservadas); a família é função do modelo, que já está na chave.
        assinatura = f"transformers|{'nf4' if self.quatro_bits else 'bf16'}|greedy|lote={self.lote}|" + \
            ",".join(f"{k}={v}" for k, v in sorted(self.max_new_tokens.items()))
        super().__init__(modelo=modelo, revisao=revisao, cache=cache, assinatura=assinatura,
                         somente_cache=somente_cache, modelo_id=modelo_id)
        self._torch = torch
        self._sem_pensar = False
        self.arquitetura = ""
        self.familia = "causal"
        if somente_cache:
            self._model = self._tok = None
            logger.info("árbitro transformers em modo somente_cache: modelo não carregado")
            return
        self.dispositivo = dispositivo if torch.cuda.is_available() or dispositivo != "cuda" else "cpu"
        if self.dispositivo == "cpu":
            logger.warning("CUDA indisponível: o árbitro rodará em CPU (lento)")
        _limitar_vram(torch, limite_vram_gb)
        torch.manual_seed(self.seed)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        # determinismo bit a bit dos kernels (é o que dá efeito ao CUBLAS_WORKSPACE_CONFIG=:4096:8
        # exportado no Dockerfile.llm; ``warn_only`` para um kernel sem variante determinística
        # não derrubar o árbitro — ele só avisa; revisão R3-03)
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
        except (AttributeError, RuntimeError, TypeError) as exc:  # pragma: no cover - versões antigas
            logger.warning("torch.use_deterministic_algorithms indisponível: %s", exc)
        kwargs: dict[str, Any] = {"local_files_only": _offline()}
        if revisao and not Path(modelo).exists():
            kwargs["revision"] = revisao
        self.arquitetura = _arquitetura(modelo, kwargs.get("revision"), kwargs["local_files_only"])
        self.familia = _familia(self.arquitetura)
        if self.familia == "causal":
            classe = AutoModelForCausalLM
            pular: list[str] | None = None
        else:
            # Qwen3.5 e afins (multimodais, ``Qwen3_5ForConditionalGeneration``): a classe homônima do
            # transformers, SDPA, sem kernels baixados do Hub; o encoder visual e a cabeça ficam fora da
            # quantização NF4 — o mesmo carregamento validado no decisor da v2 (ADR 0008).
            classe = getattr(transformers, self.arquitetura, None)
            if classe is None:
                raise ErroDependencia(
                    f"transformers {getattr(transformers, '__version__', '?')} não conhece {self.arquitetura}; "
                    "a família Qwen3.5 exige transformers >= 5 (ver requirements-llm.txt)")
            pular = ["lm_head", "visual"]
            kwargs.update(attn_implementation="sdpa", use_kernels=False, low_cpu_mem_usage=True)
        if self.quatro_bits:
            from transformers import BitsAndBytesConfig
            try:
                import bitsandbytes  # noqa: F401
            except ImportError as exc:  # pragma: no cover - depende do ambiente
                raise ErroDependencia("CACA_LLM_4BIT=1 exige o pacote bitsandbytes (pip install bitsandbytes)") from exc
            extra = {"llm_int8_skip_modules": pular} if pular else {}
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16, **extra)
        else:
            kwargs[_kw_dtype(transformers)] = torch.bfloat16
        logger.info("carregando %s (rev=%s, %s, %s) em %s", modelo, revisao or "?",
                    "nf4" if self.quatro_bits else "bf16", self.arquitetura or "AutoModelForCausalLM", self.dispositivo)
        self._tok = AutoTokenizer.from_pretrained(modelo, revision=kwargs.get("revision"),
                                                  local_files_only=kwargs["local_files_only"])
        self._tok.padding_side = "left"
        if self._tok.pad_token is None:
            self._tok.pad_token = self._tok.eos_token
        # Modelos com modo de raciocínio (Qwen3.x): o template aceita ``enable_thinking`` — desligado, o
        # modelo responde o JSON direto (sem bloco <think>, que estouraria ``max_new_tokens``).
        self._sem_pensar = "enable_thinking" in (getattr(self._tok, "chat_template", None) or "")
        self._model = classe.from_pretrained(modelo, device_map=self.dispositivo, **kwargs)
        self._model.eval()
        self._model.generation_config.do_sample = False
        if torch.cuda.is_available():
            usado = torch.cuda.memory_allocated() / 1024 ** 3
            logger.info("modelo carregado (%s, pensar=%s); VRAM alocada: %.1f GB", self.familia,
                        "off" if self._sem_pensar else "n/a", usado)

    def _texto_prompt(self, mensagens: list[dict[str, str]]) -> str:
        extra: dict[str, Any] = {"enable_thinking": False} if self._sem_pensar else {}
        return self._tok.apply_chat_template(mensagens, tokenize=False, add_generation_prompt=True, **extra)

    def _gerar(self, pedidos: list[Pedido]) -> list[str]:
        if self._model is None or self._tok is None:
            raise RuntimeError("modelo não carregado (somente_cache)")
        torch = self._torch
        textos = [self._texto_prompt(p.mensagens) for p in pedidos]
        # ordena por comprimento (menos padding) mas devolve na ordem original
        ordem = sorted(range(len(pedidos)), key=lambda i: (len(textos[i]), i))
        saida: list[str] = [""] * len(pedidos)
        for k in range(0, len(ordem), self.lote):
            idx = ordem[k:k + self.lote]
            max_novos = max(self.max_new_tokens.get(pedidos[i].operacao, 128) for i in idx)
            entradas = self._tok([textos[i] for i in idx], return_tensors="pt", padding=True)
            entradas = {n: t.to(self._model.device) for n, t in entradas.items()}
            torch.manual_seed(self.seed)
            with torch.inference_mode():
                gerado = self._model.generate(
                    **entradas, do_sample=False, num_beams=1, max_new_tokens=max_novos,
                    temperature=None, top_p=None, top_k=None, repetition_penalty=1.0,
                    pad_token_id=self._tok.pad_token_id,
                )
            n_prompt = entradas["input_ids"].shape[1]
            for j, i in enumerate(idx):
                saida[i] = self._tok.decode(gerado[j, n_prompt:], skip_special_tokens=True).strip()
        return saida


# ---------------------------------------------------------------------------
# vLLM
# ---------------------------------------------------------------------------
class VLLMArbitro(ArbitroBase):
    """Qwen2.5-7B-Instruct via vLLM (opcional), ``temperature=0``, JSON guiado quando possível."""

    nome = "vllm"

    @staticmethod
    def verificar_dependencias() -> None:
        try:
            import vllm  # noqa: F401
        except ImportError as e:  # pragma: no cover - depende do ambiente
            raise ErroDependencia("backend 'vllm' exige o pacote vllm (opcional); "
                                  "use --arbitro transformers, mock ou nenhum") from e

    def __init__(
        self,
        modelo: str = MODELO_PADRAO,
        revisao: str = "",
        cache: CacheLLM | None = None,
        limite_vram_gb: float = LIMITE_VRAM_GB_PADRAO,
        gpu_memory_utilization: float | None = None,
        max_model_len: int = 4096,
        seed: int = SEMENTE_PADRAO,
        max_new_tokens: dict[str, int] | None = None,
        guiado: bool = True,
        somente_cache: bool = False,
        **_: Any,
    ) -> None:
        if not somente_cache:
            self.verificar_dependencias()
            from vllm import LLM, SamplingParams
        else:
            LLM = SamplingParams = None
        self.seed = int(seed)
        self.max_new_tokens = dict(prompts.MAX_TOKENS_NOVOS, **(max_new_tokens or {}))
        self.guiado = guiado
        assinatura = "vllm|bf16|greedy|" + ("json|" if guiado else "") + \
            ",".join(f"{k}={v}" for k, v in sorted(self.max_new_tokens.items()))
        super().__init__(modelo=modelo, revisao=revisao, cache=cache, assinatura=assinatura,
                         somente_cache=somente_cache)
        self._SamplingParams = SamplingParams
        if somente_cache:
            self._llm = None
            return
        if gpu_memory_utilization is None:
            gpu_memory_utilization = self._utilizacao_para(limite_vram_gb)
        kwargs: dict[str, Any] = dict(model=modelo, dtype="bfloat16", seed=self.seed,
                                      gpu_memory_utilization=gpu_memory_utilization,
                                      max_model_len=max_model_len, enable_prefix_caching=True)
        if revisao and not Path(modelo).exists():
            kwargs["revision"] = revisao
        logger.info("carregando %s no vLLM (rev=%s, util=%.2f)", modelo, revisao or "?", gpu_memory_utilization)
        self._llm = LLM(**kwargs)
        self._tok = self._llm.get_tokenizer()

    @staticmethod
    def _utilizacao_para(limite_gb: float, total_gb: float | None = None) -> float:
        """Fração da VRAM total que cabe em ``limite_gb`` (folga de 8% para contexto CUDA/driver).

        ``total_gb`` vem da GPU quando omitido; sem GPU detectável devolve 0,85.
        """
        if total_gb is None:
            try:
                import torch
                if torch.cuda.is_available():
                    total_gb = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
            except Exception:  # pragma: no cover
                total_gb = None
        if not total_gb:
            return 0.85
        return round(min(0.90, (limite_gb * 0.92) / float(total_gb)), 3)

    def _parametros(self, operacao: str) -> Any:
        kw: dict[str, Any] = dict(temperature=0.0, top_p=1.0, top_k=-1, seed=self.seed,
                                  max_tokens=self.max_new_tokens.get(operacao, 128), n=1)
        if self.guiado:
            esquema = prompts.ESQUEMAS[operacao]
            try:  # vLLM ≥ 0.10
                from vllm.sampling_params import StructuredOutputsParams
                kw["structured_outputs"] = StructuredOutputsParams(json=esquema)
            except ImportError:
                try:  # vLLM 0.6–0.9
                    from vllm.sampling_params import GuidedDecodingParams
                    kw["guided_decoding"] = GuidedDecodingParams(json=esquema)
                except ImportError:
                    logger.warning("vLLM sem decodificação guiada; seguindo sem esquema")
                    self.guiado = False
        return self._SamplingParams(**kw)

    def _gerar(self, pedidos: list[Pedido]) -> list[str]:
        if self._llm is None:
            raise RuntimeError("modelo não carregado (somente_cache)")
        saida: list[str] = [""] * len(pedidos)
        por_op: dict[str, list[int]] = {}
        for i, p in enumerate(pedidos):
            por_op.setdefault(p.operacao, []).append(i)
        for op in sorted(por_op):
            idx = por_op[op]
            textos = [self._tok.apply_chat_template(pedidos[i].mensagens, tokenize=False,
                                                    add_generation_prompt=True) for i in idx]
            resultados = self._llm.generate(textos, self._parametros(op), use_tqdm=False)
            for i, r in zip(idx, resultados):
                saida[i] = r.outputs[0].text.strip() if r.outputs else ""
        return saida


# ---------------------------------------------------------------------------
# Fábrica
# ---------------------------------------------------------------------------
BACKENDS: dict[str, type[ArbitroBase]] = {
    "mock": MockArbitro,
    "transformers": TransformersArbitro,
    "vllm": VLLMArbitro,
}


def obter_arbitro(nome: str | None, **cfg: Any) -> ArbitroBase | None:
    """Instancia o árbitro pelo nome: ``nenhum``/``None`` → ``None``; ``mock``; ``transformers``; ``vllm``.

    ``cfg`` sobrepõe os padrões lidos do ambiente: ``modelo`` (``CACA_MODELO``),
    ``revisao`` (``CACA_MODELO_REVISAO``), ``modelo_id`` (``CACA_MODELO_ID``: nome canônico dos pesos
    para a chave do cache quando ``modelo`` é uma pasta local), ``cache`` (:class:`CacheLLM`, caminho,
    ``":memory:"`` ou ``None`` para desligar; padrão ``CACA_CACHE_LLM``),
    ``quatro_bits`` (``CACA_LLM_4BIT``), ``lote`` (``CACA_LLM_LOTE``),
    ``limite_vram_gb``, ``seed``, ``somente_cache`` (também ``CACA_LLM_SOMENTE_CACHE=1``: o modelo não é
    carregado e só o cache responde; ``CACA_LLM_CACHE_IMPORTAR=<jsonl>`` importa antes). Nome desconhecido →
    ``ValueError``; dependência ausente → :class:`ErroDependencia`.
    """
    if nome is None or str(nome).strip().lower() in ("", "nenhum", "none", "no", "off"):
        return None
    chave = str(nome).strip().lower()
    if chave not in BACKENDS:
        raise ValueError(f"árbitro desconhecido: {nome!r} (opções: nenhum, {', '.join(sorted(BACKENDS))})")
    somente_cache = bool(cfg.get("somente_cache")) or _bool_env("CACA_LLM_SOMENTE_CACHE")
    cfg["somente_cache"] = somente_cache
    if chave != "mock" and not somente_cache:
        # dependências primeiro: sem torch/transformers não se cria cache nenhum em disco
        # (revisão R3-06) e o HF_HOME aponta para os pesos montados (revisão R3-03)
        BACKENDS[chave].verificar_dependencias()
        hf = config.preparar_ambiente_hf()
        if hf is not None:
            logger.info("HF_HOME=%s", hf)
    cache_cfg = cfg.pop("cache", "__ambiente__")
    if cache_cfg == "__ambiente__":
        cache: CacheLLM | None = CacheLLM.do_ambiente() if chave != "mock" else CacheLLM(":memory:")
    elif cache_cfg is None or isinstance(cache_cfg, CacheLLM):
        cache = cache_cfg
    else:
        cache = CacheLLM(cache_cfg)
    cfg.setdefault("modelo", config.modelo_llm(MODELO_PADRAO))
    cfg.setdefault("revisao", config.revisao_llm())
    cfg.setdefault("modelo_id", os.environ.get("CACA_MODELO_ID", "").strip())
    if "lote" not in cfg and config.lote_llm():
        cfg["lote"] = config.lote_llm()
    importar = os.environ.get("CACA_LLM_CACHE_IMPORTAR", "").strip()
    if importar and cache is not None:
        # reprodução sem GPU (ADR 0003): o JSONL exportado da execução de referência entra no cache
        # antes da primeira consulta; com CACA_LLM_SOMENTE_CACHE=1 o modelo nem é carregado
        try:
            n = cache.importar_jsonl(importar)
            logger.info("cache do árbitro: %d resposta(s) importada(s) de %s", n, importar)
        except OSError as exc:
            logger.error("não foi possível importar %s no cache do árbitro: %s", importar, exc)
    arb = BACKENDS[chave](cache=cache, **cfg)
    logger.info("árbitro %s pronto (modelo=%s, rev=%s%s)", arb.nome, arb.modelo, arb.revisao or "?",
                ", somente cache" if somente_cache else "")
    return arb


__all__ = [
    "MockArbitro", "TransformersArbitro", "VLLMArbitro", "obter_arbitro", "BACKENDS",
    "MODELO_PADRAO", "MODELO_AWQ", "LIMITE_VRAM_GB_PADRAO", "SEMENTE_PADRAO",
]
