"""Extrator LLM de segundo estágio (ADR 0003, "padrão ouro"): o modelo só aponta onde olhar.

Depois da detecção por regex, o texto (fora do cabeçalho) é dividido em janelas; as que têm
**pistas de citação não cobertas** por um achado (``nº``, ``Rel.``, ``Súm``, ``art.``, sigla de
tribunal, classe processual…) vão ao árbitro (:meth:`ArbitroBase.extrair_citacoes`), que devolve
propostas já validadas contra o texto (:func:`caca_alucinacao.llm.arbitro.validar_extracao`).

Cada proposta aceita é **re-detectada**: os campos que o modelo devolveu (e que o validador
conferiu literalmente no span) são renderizados na forma canônica que os detectores por regex
entendem (``AGINT no RESP 1234567/SP``, ``Súmula 412 do TST``, ``art. 802 do Código Civil``,
``julgado do STJ proferido em 2020 pela relatoria de X``, ``Tema 1234 da repercussão geral``) e
passados por :func:`caca_alucinacao.deteccao.detectar`; o ``Achado`` resultante herda os ``dados``
exatamente como um achado de regex teria, mas com os offsets do span original e ``origem``
``llm:extrator:<família>``. A **classe** vem depois, da resolução contra a base — nunca do modelo.

Garantias: (1) nenhum span extraído toca um achado existente; (2) número, UF, artigo, diploma,
ano e relator estão literalmente no span (validador); (3) o que a re-detecção não entende é
descartado (nenhum ``dados`` inventado); (4) no máximo :data:`MAX_JANELAS_POR_DOCUMENTO` chamadas por
documento, por ordem de pistas descobertas (envelope de 60 s/doc); (5) qualquer exceção ou
abstenção do árbitro deixa o documento exatamente como o regex o deixou.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from ..config import ENVELOPE_SEGUNDOS_POR_DOC
from ..texto import fim_do_cabecalho
from ..tipos import Achado

log = logging.getLogger(__name__)

JANELA_MAX = 900
#: Chamadas ao modelo por documento (``CACA_LLM_EXTRATOR_JANELAS``; 0 desliga o extrator).
MAX_JANELAS_POR_DOCUMENTO = 6
#: Orçamento de tempo do extrator por documento: metade do envelope da organização (60 s/doc, em
#: média). As janelas são consultadas por ordem de pistas; estourado o orçamento, as restantes
#: ficam sem consulta (o documento sai como o regex o deixou naquelas janelas).
ORCAMENTO_SEGUNDOS = ENVELOPE_SEGUNDOS_POR_DOC * 0.5
ORIGEM = "llm:extrator"

#: Pistas de citação. Só palavras ligadas a citações; a prosa forense comum não conta.
RE_PISTA = re.compile(
    r"(?<![A-Za-zÀ-ÿ])(?:"
    r"n[º°\.o]|Rel\.|Min\.|Ministr[oa]|Desembargador|S[úu]m(?:ula|\.)?|S[úu]n[1l]ula|enunciado|verbete|art(?:igo|s?\.)|"
    r"Tema|[S5]T[JF]|T[S5][TE]|[S5]TM|Supremo|Superior\s+Tribunal|Tribunal\s+Superior|"
    r"REsp|RE5p|AREsp|Rcl|Recl|HC|RMS|RHC|ADI|ADPF|AgInt|AgRg|EDcl|RR|AIRR|APL|REspe|"
    r"Recurso|Re\s?curso|Reclama|Habeas|Mandado|A[çc][ãa]o\s+Direta|ac[óo]rd[ãa]o|julgad[oa]|precedente|relatoria|"
    r"C[óo]digo|Lei\s+n|Constitui[çc][ãa]o|CPC|CLT|CF/?88|CDC|CTN"
    r")(?![A-Za-zÀ-ÿ])",
    re.I,
)
_RE_PARAGRAFO = re.compile(r"\n\s*\n")
_RE_FRASE = re.compile(r"(?<=[.;!?])\s+")


def janelas_por_documento() -> int:
    """Limite de chamadas por documento (``CACA_LLM_EXTRATOR_JANELAS``; padrão 8; 0 desliga)."""
    bruto = os.environ.get("CACA_LLM_EXTRATOR_JANELAS", "").strip()
    if bruto.isdigit():
        return int(bruto)
    return MAX_JANELAS_POR_DOCUMENTO


def _blocos(texto: str, inicio: int) -> list[tuple[int, int]]:
    """Janelas ``(ini, fim)`` de até :data:`JANELA_MAX` codepoints a partir de ``inicio``:
    parágrafos, quebrados por frase quando longos."""
    saida: list[tuple[int, int]] = []
    pos = inicio
    for m in list(_RE_PARAGRAFO.finditer(texto, inicio)) + [None]:
        fim_par = m.start() if m is not None else len(texto)
        if fim_par > pos:
            saida.extend(_quebrar(texto, pos, fim_par))
        pos = m.end() if m is not None else len(texto)
    return saida


def _quebrar(texto: str, ini: int, fim: int) -> list[tuple[int, int]]:
    if fim - ini <= JANELA_MAX:
        return [(ini, fim)]
    saida: list[tuple[int, int]] = []
    cursor = ini
    while fim - cursor > JANELA_MAX:
        corte = None
        for m in _RE_FRASE.finditer(texto, cursor, min(fim, cursor + JANELA_MAX)):
            corte = m.end()
        if corte is None or corte <= cursor:
            corte = cursor + JANELA_MAX
        saida.append((cursor, corte))
        cursor = corte
    if fim > cursor:
        saida.append((cursor, fim))
    return saida


def janelas_candidatas(texto: str, achados: list[Achado], limite: int | None = None) -> list[tuple[int, int, int]]:
    """``(ini, fim, n_pistas_descobertas)`` das janelas com pelo menos uma pista fora de todo achado e um
    dígito, fora do cabeçalho; as ``limite`` com mais pistas, em ordem de posição."""
    if not texto:
        return []
    cabecalho = fim_do_cabecalho(texto)
    ocupados = sorted((a.inicio, a.fim) for a in achados)
    saida: list[tuple[int, int, int]] = []
    for ini, fim in _blocos(texto, cabecalho):
        janela = texto[ini:fim]
        if not any(c.isdigit() for c in janela):
            continue
        n = 0
        for m in RE_PISTA.finditer(janela):
            p = ini + m.start()
            if not any(i <= p < f for i, f in ocupados):
                n += 1
        if n:
            saida.append((ini, fim, n))
    if limite is None:
        limite = janelas_por_documento()
    if limite <= 0:
        return []
    escolhidas = sorted(sorted(saida, key=lambda x: (-x[2], x[0]))[:limite])
    return escolhidas


# ---------------------------------------------------------------------------
# Re-detecção pela forma canônica
# ---------------------------------------------------------------------------
_TST = "5"


def _formatar_numero(digitos: str) -> str:
    n = len(digitos)
    if 14 <= n <= 20:
        d = digitos.zfill(20)
        return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"
    if n == 12 and digitos[:2] in ("19", "20"):
        return f"{digitos[:4]}/{digitos[4:11]}-{digitos[11]}"
    return digitos.lstrip("0") or "0"


def forma_canonica(campos: dict[str, Any]) -> str:
    """Superfície canônica que os detectores por regex entendem (ver módulo)."""
    fam = campos.get("familia")
    if fam == "processo":
        cadeia = [str(c).upper() for c in campos.get("cadeia") or []]
        numero = _formatar_numero(str(campos.get("digitos") or ""))
        uf = campos.get("uf")
        if len(str(campos.get("digitos") or "")) >= 14 and str(campos.get("digitos") or "").zfill(20)[13] == _TST:
            corpo = "-".join(cadeia + [numero])
        else:
            corpo = " no ".join(cadeia) + " " + numero
        return corpo + (f"/{uf}" if uf else "")
    if fam == "sumula":
        base = "Súmula Vinculante " if campos.get("vinculante") else "Súmula "
        trib = campos.get("tribunal")
        return base + str(campos.get("numero") or "") + (f" do {trib}" if trib and not campos.get("vinculante") else "")
    if fam == "dispositivo":
        diploma = str(campos.get("diploma") or "").strip()
        conector = "do" if re.match(r"(?i)(c[óo]digo|decreto|estatuto|regimento|cpc|cp\b|cdc|cc\b|ctn|adct|cpp)", diploma) else "da"
        return f"art. {campos.get('artigo')} {conector} {diploma}"
    if fam == "vaga":
        return f"julgado do {campos.get('tribunal')} proferido em {campos.get('ano')} pela relatoria de {campos.get('relator')}"
    if fam == "tema":
        if campos.get("tribunal") == "STJ":
            return f"Tema Repetitivo {campos.get('numero')}"
        return f"Tema {campos.get('numero')} da repercussão geral"
    return ""


_PREFIXO_REDETECCAO = "PARECER\n\nTrata-se de parecer sobre a controvérsia, conforme se passa a expor.\n\nNo "


def redetectar(campos: dict[str, Any]) -> Achado | None:
    """Passa a forma canônica pelos detectores e devolve o achado (com ``dados``) ou ``None``."""
    from ..deteccao import detectar

    canon = forma_canonica(campos)
    if not canon:
        return None
    texto = _PREFIXO_REDETECCAO + canon + ", decidiu-se."
    ini_canon = len(_PREFIXO_REDETECCAO)
    for a in detectar(texto):
        if a.familia == campos.get("familia") and a.inicio >= ini_canon and a.fim <= ini_canon + len(canon):
            return a
    log.info("extrator: forma canônica %r não re-detectada; proposta descartada", canon)
    return None


def achado_de_proposta(texto: str, ini_janela: int, campos: dict[str, Any]) -> Achado | None:
    """``Achado`` com os offsets do span original e os ``dados`` da re-detecção; ``None`` se inválido."""
    base = redetectar(campos)
    if base is None:
        return None
    ini = ini_janela + int(campos["inicio_rel"])
    fim = ini_janela + int(campos["fim_rel"])
    if not (0 <= ini < fim <= len(texto)) or texto[ini:fim] != campos["trecho"]:
        return None
    dados = dict(base.dados)
    dados["numero"] = campos["trecho"] if campos.get("familia") in ("processo", "sumula", "tema") else dados.get("numero", "")
    dados["llm_extraiu"] = "1"
    return Achado(ini, fim, campos["trecho"], base.familia, base.tipo, dados,
                  f"{ORIGEM}:{base.familia}", 1.0)


def extrair(texto: str, achados: list[Achado], arbitro: Any, limite: int | None = None,
            orcamento_s: float = ORCAMENTO_SEGUNDOS) -> tuple[list[Achado], int]:
    """Achados novos propostos pelo árbitro e validados; ``(achados_novos, n_janelas_consultadas)``.

    Nunca lança: qualquer falha devolve ``([], n)``. Os achados novos não se sobrepõem entre si nem
    aos existentes (o validador já garante; aqui se confere de novo com os offsets absolutos).
    As janelas são consultadas uma a uma, por ordem de prioridade (mais pistas primeiro), e a
    consulta para quando ``orcamento_s`` se esgota — o cache do árbitro torna a repetição gratuita.
    """
    if arbitro is None or not hasattr(arbitro, "extrair_citacoes"):
        return [], 0
    try:
        janelas = janelas_candidatas(texto, achados, limite)
    except Exception:  # pragma: no cover - defensivo
        log.exception("extrator: falha ao escolher janelas; ignorando")
        return [], 0
    if not janelas:
        return [], 0
    # prioridade: mais pistas descobertas primeiro (o orçamento pode não alcançar todas)
    ordem = sorted(janelas, key=lambda x: (-x[2], x[0]))
    inicio_t = time.monotonic()
    respostas: list[tuple[int, list[dict[str, Any]] | None]] = []
    consultadas = 0
    for ini, fim, _ in ordem:
        if consultadas and time.monotonic() - inicio_t > orcamento_s:
            log.warning("extrator: orçamento de %.0f s esgotado após %d janela(s); %d sem consulta",
                        orcamento_s, consultadas, len(ordem) - consultadas)
            break
        ja = [{"inicio": a.inicio - ini, "fim": a.fim - ini, "trecho": a.trecho}
              for a in achados if a.inicio < fim and a.fim > ini]
        try:
            resposta = arbitro.extrair_citacoes(texto[ini:fim], ja)
        except Exception:
            log.exception("extrator: árbitro falhou na janela (%d,%d); ignorada", ini, fim)
            resposta = None
        consultadas += 1
        respostas.append((ini, resposta))
    novos: list[Achado] = []
    ocupados = [(a.inicio, a.fim) for a in achados]
    for ini, resposta in sorted(respostas, key=lambda x: x[0]):
        if not resposta:
            continue
        for campos in resposta:
            try:
                a = achado_de_proposta(texto, ini, campos)
            except Exception:
                log.exception("extrator: proposta inválida; ignorada")
                a = None
            if a is None:
                continue
            if any(min(a.fim, f) - max(a.inicio, i) > 0 for i, f in ocupados):
                continue
            ocupados.append((a.inicio, a.fim))
            novos.append(a)
    novos.sort(key=lambda a: (a.inicio, a.fim))
    if novos:
        log.info("extrator: %d citação(ões) nova(s) em %d janela(s)", len(novos), consultadas)
    return novos, consultadas


__all__ = ["JANELA_MAX", "MAX_JANELAS_POR_DOCUMENTO", "ORCAMENTO_SEGUNDOS", "ORIGEM", "RE_PISTA", "janelas_candidatas",
           "forma_canonica", "redetectar", "achado_de_proposta", "extrair", "janelas_por_documento"]
