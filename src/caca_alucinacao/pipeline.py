"""Pipeline por documento: texto → detecção → resolução → calibração → contrato.

Os componentes são injetáveis (``detector``, ``resolvedor``, ``calibrador``,
``arbitro``); quando ausentes, são importados tardiamente de
``caca_alucinacao.deteccao`` (``detectar(texto) -> list[Achado]``),
``caca_alucinacao.resolucao`` (``resolver(achado, base[, arbitro=…]) -> Decisao``)
e ``caca_alucinacao.calibracao`` (``confianca(decisao, achado, tabela) -> float``).

Garantias:

* a saída de :func:`processar_texto` **sempre** passa em :func:`contrato.validar`
  (citações inválidas são descartadas, nunca emitidas);
* uma exceção numa citação nunca derruba o documento: a citação é **omitida**
  (ver ``docs/decisoes/0002-contrato-e-avaliacao.md`` — omitir custa no máximo
  1 FN; emitir ``incompleta`` às cegas custa em média mais);
* dois achados com IoU ≥ 0,5 (não deveria acontecer: ``deteccao.fusao`` já
  evita) → fica o de maior ``forca`` (desempate: span mais longo, depois o
  primeiro); o outro é descartado com log;
* ordem determinística: citações por ``(inicio, fim)``; arquivos por nome;
* offsets em codepoints do texto lido **sem** tradução de quebras de linha
  (``read_bytes().decode``), sem NFC forçado (só aviso se o texto não for NFC).
"""
from __future__ import annotations

import bisect
import inspect
import logging
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CONFIANCA_PADRAO, ENVELOPE_SEGUNDOS_POR_DOC, IOU_MIN
from .texto import carregar, carregar_com_codificacao
from .contrato import Citacao, SaidaDocumento, validar, validar_citacao
from .tipos import Achado, Decisao, iou

# Janela de contexto (chars antes/depois do span) entregue ao resolvedor/árbitro LLM.
JANELA_CONTEXTO = 300
# Teto defensivo de achados por documento (envelope de 60 s/doc; ver _sanear_achados).
TETO_ACHADOS_POR_DOCUMENTO = 5000

log = logging.getLogger(__name__)

Detector = Callable[[str], list[Achado]]
Resolvedor = Callable[..., Decisao]
Calibrador = Callable[[Decisao, Achado, dict[str, float]], float]


class ErroPipeline(RuntimeError):
    """Falha estrutural (componente ausente, saída irreparável)."""


# ---------------------------------------------------------------------------
# Rastro (diagnóstico / calibração)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Rastro:
    """O caminho de decisão de um achado, emitido ou não.

    ``status``: ``emitida`` | ``omitida:erro_resolucao`` | ``omitida:invalida``
    | ``descartada:sobreposicao`` | ``descartada:span`` | ``descartada:teto``
    | ``descartada:resolucao`` (flag ``descartar`` da resolução; ADR 0006 §8).
    """

    documento_id: str
    achado: Achado
    decisao: Decisao | None
    confianca: float | None
    status: str
    erro: str | None = None

    def para_dicionario(self) -> dict[str, Any]:
        d = self.decisao
        return {
            "documento_id": self.documento_id,
            "inicio": self.achado.inicio,
            "fim": self.achado.fim,
            "familia": self.achado.familia,
            "tipo": self.achado.tipo,
            "origem": self.achado.origem,
            "forca": self.achado.forca,
            "classificacao": d.classificacao if d else None,
            "id_canonico": None if d is None or d.id_canonico is None else str(d.id_canonico),
            "caminho": d.caminho if d else None,
            "candidatos": [str(x) for x in d.candidatos] if d else [],
            "confianca": self.confianca,
            "status": self.status,
            "erro": self.erro,
        }


# ---------------------------------------------------------------------------
# Componentes padrão (imports tardios)
# ---------------------------------------------------------------------------
def _detector_padrao() -> Detector:
    try:
        from .deteccao import detectar
    except ImportError as exc:  # pragma: no cover - depende da integração
        raise ErroPipeline("detector indisponível: caca_alucinacao.deteccao.detectar") from exc
    return detectar


def _resolvedor_padrao() -> Resolvedor:
    try:
        from .resolucao import resolver
    except ImportError as exc:  # pragma: no cover
        raise ErroPipeline("resolvedor indisponível: caca_alucinacao.resolucao.resolver") from exc
    return resolver


def _confianca_fixa(decisao: Decisao, achado: Achado, tabela: dict[str, float]) -> float:
    """Calibrador de reserva: tabela por caminho se houver, senão o padrão."""
    return float(tabela.get(decisao.caminho, CONFIANCA_PADRAO))


def _calibrador_padrao() -> Calibrador:
    try:
        from .calibracao import confianca
    except ImportError:
        log.warning("calibracao.confianca indisponível; usando confiança fixa %.2f", CONFIANCA_PADRAO)
        return _confianca_fixa
    return confianca


def _aceita_parametro(funcao: Callable[..., Any], nome: str) -> bool:
    try:
        params = inspect.signature(funcao).parameters
    except (TypeError, ValueError):
        return False
    if nome in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


# ---------------------------------------------------------------------------
# Saneamento dos achados
# ---------------------------------------------------------------------------
def _sanear_achados(documento_id: str, texto: str, achados: Iterable[Achado],
                    rastros: list[Rastro]) -> list[Achado]:
    """Confere spans contra o texto e remove sobreposições com IoU ≥ 0,5."""
    validos: list[Achado] = []
    for a in achados:
        if a.fim > len(texto) or a.inicio < 0 or a.fim <= a.inicio:
            log.error("[%s] achado fora do texto (%d,%d) len=%d — descartado",
                      documento_id, a.inicio, a.fim, len(texto))
            rastros.append(Rastro(documento_id, a, None, None, "descartada:span", "span fora do texto"))
            continue
        literal = texto[a.inicio:a.fim]
        if a.trecho != literal:
            log.warning("[%s] trecho do achado (%d,%d) difere do texto; usando texto[inicio:fim]",
                        documento_id, a.inicio, a.fim)
            a = Achado(a.inicio, a.fim, literal, a.familia, a.tipo, dict(a.dados), a.origem, a.forca)
        validos.append(a)

    # Prioridade: maior força, depois span mais longo, depois o mais à esquerda.
    # Varredura em O(n log n): os aceitos ficam numa lista ordenada por início e só
    # os vizinhos que podem intersectar o candidato são comparados (revisão R3-04:
    # a busca linear anterior era O(n²) e um documento com 4 000 artigos levava 22 s).
    prioridade = sorted(validos, key=lambda a: (-a.forca, -(a.fim - a.inicio), a.inicio, a.fim))
    inicios: list[int] = []          # inícios dos aceitos, ordenados (bisect)
    aceitos_ord: list[Achado] = []   # aceitos na mesma ordem
    maior_len = 0
    aceitos: list[Achado] = []
    for a in prioridade:
        # candidatos a conflito: aceitos cujo início está em [a.inicio - maior_len, a.fim)
        k0 = bisect.bisect_left(inicios, a.inicio - maior_len)
        k1 = bisect.bisect_left(inicios, a.fim)
        conflito = next((b for b in aceitos_ord[k0:k1] if iou(a.inicio, a.fim, b.inicio, b.fim) >= IOU_MIN), None)
        if conflito is None:
            pos = bisect.bisect_left(inicios, a.inicio)
            inicios.insert(pos, a.inicio)
            aceitos_ord.insert(pos, a)
            maior_len = max(maior_len, a.fim - a.inicio)
            aceitos.append(a)
        else:
            log.warning("[%s] achados sobrepostos (IoU>=%.1f): mantido (%d,%d) forca=%.2f, "
                        "descartado (%d,%d) forca=%.2f", documento_id, IOU_MIN,
                        conflito.inicio, conflito.fim, conflito.forca, a.inicio, a.fim, a.forca)
            rastros.append(Rastro(documento_id, a, None, None, "descartada:sobreposicao",
                                  f"sobrepõe ({conflito.inicio},{conflito.fim})"))
    if len(aceitos) > TETO_ACHADOS_POR_DOCUMENTO:
        # teto defensivo do envelope (60 s/doc): documentos reais têm dezenas de citações
        log.warning("[%s] %d achados; mantidos os %d primeiros (teto defensivo)", documento_id,
                    len(aceitos), TETO_ACHADOS_POR_DOCUMENTO)
        aceitos.sort(key=lambda a: (a.inicio, a.fim))
        for a in aceitos[TETO_ACHADOS_POR_DOCUMENTO:]:
            rastros.append(Rastro(documento_id, a, None, None, "descartada:teto", "teto de achados"))
        aceitos = aceitos[:TETO_ACHADOS_POR_DOCUMENTO]
    return sorted(aceitos, key=lambda a: (a.inicio, a.fim))


def _confianca_segura(valor: Any) -> float:
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return CONFIANCA_PADRAO
    if math.isnan(v):
        return CONFIANCA_PADRAO
    return min(1.0, max(0.0, v))


# ---------------------------------------------------------------------------
# Processamento de um documento
# ---------------------------------------------------------------------------
def processar_texto_com_rastro(
    documento_id: str,
    texto: str,
    base: Any,
    *,
    detector: Detector | None = None,
    resolvedor: Resolvedor | None = None,
    calibrador: Calibrador | None = None,
    arbitro: Any = None,
    tabela_calibracao: dict[str, float] | None = None,
) -> tuple[SaidaDocumento, list[Rastro]]:
    """Como :func:`processar_texto`, devolvendo também o rastro de cada achado."""
    detector = detector or _detector_padrao()
    resolvedor = resolvedor or _resolvedor_padrao()
    calibrador = calibrador or _calibrador_padrao()
    tabela = dict(tabela_calibracao or {})
    passa_arbitro = arbitro is not None and _aceita_parametro(resolvedor, "arbitro")
    if arbitro is not None and not passa_arbitro:
        log.warning("[%s] resolvedor não aceita 'arbitro'; árbitro ignorado", documento_id)
    # O resolvedor (e o árbitro LLM) recebem uma janela de contexto em torno do span
    # (±JANELA_CONTEXTO chars) quando a assinatura permite — só para desempate/diagnóstico.
    passa_contexto = _aceita_parametro(resolvedor, "contexto")

    rastros: list[Rastro] = []
    try:
        brutos = list(detector(texto))
    except Exception as exc:
        log.exception("[%s] detector falhou (%s); documento sem citações", documento_id, exc)
        brutos = []
    achados = _sanear_achados(documento_id, texto, brutos, rastros)

    citacoes: list[Citacao] = []
    for a in achados:
        kwargs: dict[str, Any] = {}
        if passa_arbitro:
            kwargs["arbitro"] = arbitro
        if passa_contexto:
            kwargs["contexto"] = texto[max(0, a.inicio - JANELA_CONTEXTO):a.fim + JANELA_CONTEXTO]
        try:
            decisao = resolvedor(a, base, **kwargs)
        except Exception as exc:
            log.exception("[%s] resolução falhou em (%d,%d) %s: %s — citação omitida",
                          documento_id, a.inicio, a.fim, a.familia, exc)
            rastros.append(Rastro(documento_id, a, None, None, "omitida:erro_resolucao", repr(exc)))
            continue
        # Contrato com resolucao.py: um achado de padrão AMPLO (forca < 1) que a base não
        # confirma vem marcado com detalhes["descartar"] == "1" — provavelmente não é
        # citação; emitir seria 1 FP certo. Omitir custa no máximo 1 FN se fosse citação.
        detalhes = getattr(decisao, "detalhes", None) or {}
        if str(detalhes.get("descartar", "")) == "1":
            log.info("[%s] (%d,%d) %s %s descartado pela resolução (caminho=%s)",
                     documento_id, a.inicio, a.fim, a.familia, a.origem, decisao.caminho)
            rastros.append(Rastro(documento_id, a, decisao, None, "descartada:resolucao",
                                  decisao.caminho))
            continue
        try:
            conf = _confianca_segura(calibrador(decisao, a, tabela))
        except Exception as exc:
            log.warning("[%s] calibração falhou em (%d,%d): %s — confiança padrão %.2f",
                        documento_id, a.inicio, a.fim, exc, CONFIANCA_PADRAO)
            conf = CONFIANCA_PADRAO
        idc = None if decisao.id_canonico is None else str(decisao.id_canonico)
        citacao = Citacao(id="c?", inicio=a.inicio, fim=a.fim, trecho=a.trecho, tipo=a.tipo,
                          classificacao=decisao.classificacao, id_canonico=idc, confianca=conf)
        erros = validar_citacao(len(citacoes), citacao.para_dicionario(), texto)
        if erros:
            log.error("[%s] citação (%d,%d) inválida e omitida: %s", documento_id, a.inicio, a.fim, erros)
            rastros.append(Rastro(documento_id, a, decisao, conf, "omitida:invalida", "; ".join(erros)))
            continue
        citacoes.append(citacao)
        rastros.append(Rastro(documento_id, a, decisao, conf, "emitida"))
        log.info("[%s] (%d,%d) %s/%s %s forca=%.2f -> %s id=%s caminho=%s conf=%.3f",
                 documento_id, a.inicio, a.fim, a.familia, a.tipo, a.origem, a.forca,
                 decisao.classificacao, idc or "-", decisao.caminho, conf)

    saida = SaidaDocumento.montar(documento_id, citacoes)
    erros = validar(saida.para_dicionario(), texto)
    if erros:  # não deveria acontecer: cada citação já foi validada e as sobreposições removidas
        raise ErroPipeline(f"[{documento_id}] saída irreparável: {erros}")
    return saida, rastros


def processar_texto(
    documento_id: str,
    texto: str,
    base: Any,
    *,
    detector: Detector | None = None,
    resolvedor: Resolvedor | None = None,
    calibrador: Calibrador | None = None,
    arbitro: Any = None,
    tabela_calibracao: dict[str, float] | None = None,
) -> SaidaDocumento:
    """Processa um documento e devolve a saída válida (schema 1.2).

    ``base`` é a :class:`~caca_alucinacao.base_canonica.BaseCanonica` (ou
    qualquer objeto que o ``resolvedor`` aceite).
    """
    saida, _ = processar_texto_com_rastro(
        documento_id, texto, base, detector=detector, resolvedor=resolvedor,
        calibrador=calibrador, arbitro=arbitro, tabela_calibracao=tabela_calibracao,
    )
    return saida


# ---------------------------------------------------------------------------
# Pasta
# ---------------------------------------------------------------------------
def carregar_texto(caminho: Path | str) -> str:
    """Lê o ``.txt`` como UTF-8 **sem** traduzir ``\\r\\n`` nem normalizar (offsets em codepoints).

    Delegação a :func:`caca_alucinacao.texto.carregar` — implementação única do
    contrato de leitura (revisão R1-10).
    """
    return carregar(caminho)


def documento_id_de(caminho: Path | str) -> str:
    """``documento_id`` = nome do arquivo sem extensão."""
    return Path(caminho).stem


def listar_documentos(entrada: Path | str, sufixo: str = ".txt") -> list[Path]:
    """Arquivos ``*.txt`` da pasta (extensão sem distinção de caixa), em ordem de nome.

    Arquivos com outra extensão e subpastas são ignorados **com aviso** no log
    (revisão R3-08): a submissão exige uma linha por documento. Arquivos ocultos
    (``.r3_oculto.txt``, forks AppleDouble ``._doc.txt``) também são ignorados com aviso
    (rodada 4, R3q-08): virariam linhas espúrias na submissão.
    """
    pasta = Path(entrada)
    if not pasta.is_dir():
        raise ErroPipeline(f"pasta de entrada inexistente: {pasta}")
    aceitos: list[Path] = []
    ignorados: list[str] = []
    ocultos: list[str] = []
    for p in sorted(pasta.iterdir()):
        if p.name.startswith("."):
            if p.is_file() and p.suffix.lower() == sufixo:
                ocultos.append(p.name)
        elif p.is_file() and p.suffix.lower() == sufixo:
            aceitos.append(p)
        else:
            ignorados.append(p.name)
    if ignorados:
        log.warning("%d entrada(s) ignorada(s) em %s (não são %s): %s", len(ignorados), pasta, sufixo,
                    ", ".join(ignorados[:10]) + (" …" if len(ignorados) > 10 else ""))
    if ocultos:
        log.warning("%d arquivo(s) oculto(s) %s ignorado(s) em %s (nome começa por '.'): %s", len(ocultos),
                    sufixo, pasta, ", ".join(ocultos[:10]) + (" …" if len(ocultos) > 10 else ""))
    if not aceitos:
        # a pasta-mãe foi montada no lugar da pasta dos .txt (``/data/in/txt/*.txt``): ERROR explícito
        # listando as subpastas de 1º nível que têm .txt, em vez de um lote vazio silencioso (R3e-11)
        com_txt = [p.name for p in sorted(pasta.iterdir())
                   if p.is_dir() and any(q.is_file() and q.suffix.lower() == sufixo for q in p.iterdir())]
        if com_txt:
            log.error("nenhum %s em %s, mas há %s em subpasta(s): %s — monte a subpasta como entrada",
                      sufixo, pasta, sufixo, ", ".join(com_txt[:10]))
        else:
            log.error("nenhum %s em %s: lote vazio", sufixo, pasta)
    return aceitos


def processar_pasta(
    entrada: Path | str,
    saida: Path | str,
    base: Any,
    *,
    detector: Detector | None = None,
    resolvedor: Resolvedor | None = None,
    calibrador: Calibrador | None = None,
    arbitro: Any = None,
    tabela_calibracao: dict[str, float] | None = None,
    rastro_para: Path | str | None = None,
    limite: int | None = None,
    arquivos: list[Path] | None = None,
) -> list[Path]:
    """Um JSON por ``.txt`` (mesmo nome), em ordem de nome. Devolve os caminhos escritos.

    Um documento que falhe por completo gera um JSON com ``citacoes: []`` (a
    submissão exige uma linha por documento); o erro fica no log.
    ``rastro_para`` grava um JSONL com o caminho de decisão de cada achado.
    ``arquivos`` é a lista já obtida por :func:`listar_documentos` (o CLI a passa
    para não varrer a pasta duas vezes nem duplicar o aviso de entradas ignoradas; R3b-05).
    """
    detector = detector or _detector_padrao()
    resolvedor = resolvedor or _resolvedor_padrao()
    calibrador = calibrador or _calibrador_padrao()
    destino = preparar_saida(saida)
    if arquivos is None:
        arquivos = listar_documentos(entrada)
    if limite is not None:
        arquivos = arquivos[:limite]
    if not arquivos:
        log.warning("nenhum .txt em %s", entrada)

    escritos: list[Path] = []
    duracoes: list[float] = []
    rastros_todos: list[Rastro] = []
    falhas = 0
    degradados = 0   # documentos que não eram UTF-8 válido (U+FFFD no texto; R3b-06)
    for arq in arquivos:
        doc = documento_id_de(arq)
        t0 = time.perf_counter()
        try:
            texto, codificacao = carregar_com_codificacao(arq)
            if codificacao != "utf-8":
                degradados += 1
            resultado, rastros = processar_texto_com_rastro(
                doc, texto, base, detector=detector, resolvedor=resolvedor,
                calibrador=calibrador, arbitro=arbitro, tabela_calibracao=tabela_calibracao,
            )
        except Exception as exc:
            falhas += 1
            log.exception("[%s] documento falhou (%s); gravando JSON vazio", doc, exc)
            resultado, rastros = SaidaDocumento(documento_id=doc), []
        try:
            caminho = resultado.escrever(destino / f"{doc}.json")
        except OSError as exc:
            # falha de E/S na escrita (permissão, disco cheio): registra e segue — o lote
            # nunca é derrubado por um documento (revisões R3-02/R3-07)
            falhas += 1
            log.error("[%s] não foi possível escrever %s: %s", doc, destino / f"{doc}.json", exc)
            continue
        dt = time.perf_counter() - t0
        duracoes.append(dt)
        rastros_todos.extend(rastros)
        escritos.append(caminho)
        n_cls = {}
        for c in resultado.citacoes:
            n_cls[c.classificacao] = n_cls.get(c.classificacao, 0) + 1
        log.info("[%s] %d citações %s em %.2fs", doc, len(resultado.citacoes),
                 dict(sorted(n_cls.items())), dt)

    if rastro_para is not None:
        _gravar_rastro(Path(rastro_para), rastros_todos)
    if duracoes:
        media = sum(duracoes) / len(duracoes)
        log.info("%d documentos em %.1fs (média %.2fs/doc, máx %.2fs; envelope %.0fs/doc)%s%s",
                 len(duracoes), sum(duracoes), media, max(duracoes), ENVELOPE_SEGUNDOS_POR_DOC,
                 f"; {falhas} falha(s)" if falhas else "",
                 f"; {degradados} documento(s) com decodificação degradada (não UTF-8)" if degradados else "")
        if degradados:
            log.error("%d documento(s) não eram UTF-8 válido: citações com º/ç podem ter sido perdidas", degradados)
        if media > ENVELOPE_SEGUNDOS_POR_DOC:
            log.warning("média de %.1fs/doc EXCEDE o envelope de %.0fs/doc", media,
                        ENVELOPE_SEGUNDOS_POR_DOC)
    return escritos


def preparar_saida(saida: Path | str) -> Path:
    """Cria a pasta de saída e **prova** que consegue escrever nela.

    A imagem roda como ``root`` (Dockerfile), mas quem passa ``--user`` no ``docker run`` pode
    receber um ``/data/out`` com dono ``root`` e modo 755, que daria ``PermissionError`` só na
    escrita do primeiro JSON; aqui a falha vira :class:`ErroPipeline` com a orientação
    (revisão R3-02; mensagem coerente com root/``--user`` desde a rodada 4, R3q-09).
    """
    destino = Path(saida)
    if destino.exists() and not destino.is_dir():
        raise ErroPipeline(f"--output aponta para um arquivo, não para uma pasta: {destino}")
    try:
        destino.mkdir(parents=True, exist_ok=True)
        sonda = destino / ".caca_escrita_ok"
        sonda.write_text("", encoding="utf-8")
    except OSError as exc:
        raise ErroPipeline(
            f"sem permissão de escrita em {destino} ({exc}); no container, a pasta de saída montada em "
            f"/data/out precisa ser gravável pelo usuário do processo (root por padrão; com "
            f"--user $(id -u):$(id -g), pelo seu usuário — confira dono/modo da pasta no host)"
        ) from exc
    # A sonda só prova a ESCRITA. Alguns sistemas de arquivos montados (ex.: pastas
    # sincronizadas, sandboxes) permitem criar mas não apagar: isso não impede o pipeline
    # (os JSONs só são criados/sobrescritos), então a falha ao remover a sonda é apenas avisada.
    try:
        sonda.unlink()
    except OSError as exc:
        log.warning("pasta de saída %s permite escrever mas não apagar (%s); a sonda "
                    "%s ficou para trás e pode ser removida à mão", destino, exc, sonda.name)
    return destino


def _gravar_rastro(caminho: Path, rastros: list[Rastro]) -> None:
    import json

    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as f:
        for r in rastros:
            f.write(json.dumps(r.para_dicionario(), ensure_ascii=False) + "\n")
    log.info("rastro com %d achados em %s", len(rastros), caminho)


__all__ = [
    "Detector", "Resolvedor", "Calibrador", "Rastro", "ErroPipeline",
    "processar_texto", "processar_texto_com_rastro", "processar_pasta", "preparar_saida",
    "carregar_texto", "documento_id_de", "listar_documentos", "TETO_ACHADOS_POR_DOCUMENTO",
]
