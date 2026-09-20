"""Resolução: de um ``Achado`` a uma ``Decisao`` pela consulta à base canônica.

A classe de uma citação é **consequência da cardinalidade da consulta por
identificador** à base fechada (docs/00 §1): 1 registro → ``real``; 0 →
``inventada``; identificador insuficiente → ``incompleta``. Este módulo não
faz busca semântica nem casamento aproximado de dígitos — a chave primária é
sempre o número canônico e a consulta devolve só *donos* do número
(``BaseCanonica.candidatos_por_numero``), nunca quem o cita no corpo.

Especificação medida: ``docs/04_analise_base.md`` (h.1–h.11) e
``docs/03_analise_gabarito.md`` (§9.3). Decisão registrada em
``docs/decisoes/0006-resolucao.md``.

Custos da métrica que justificam cada regra (docs/00 §2):

* ``real`` com ``id`` errado custa 1 FP; ``incompleta`` num gabarito ``real``
  custa 1 FN + 1 FP. Logo, entre candidatos indistinguíveis **chuta-se** um
  (``processo:duplicata``/``processo:ambiguo_chute``) com confiança baixa em
  vez de emitir ``incompleta``.
* ``inventada`` predita como ``real`` custa 1 FN + 1 FP **e** entra em τ
  (multiplica o macro-F1 por ``1 − 0,5·τ``). Por isso nunca se corrige um
  dígito por outro, nunca se usa FTS/BM25 e o tribunal/UF são filtros
  eliminatórios quando são inferíveis com certeza.
* A classe processual **não** é eliminatória (docs/04 d: 2/77 ``real`` do dev
  têm cadeia diferente da própria); ela só desempata e rebaixa a confiança.

Contrato com o pipeline (``pipeline.processar_texto_com_rastro``)::

    resolver(achado, base, arbitro=None, contexto=None) -> Decisao

``arbitro`` (``llm.Arbitro``) é opcional e só é consultado nos gatilhos de
``docs/decisoes/0003-arbitro-llm.md`` ("Integração"). ``contexto`` é a janela
de texto em torno do trecho para o árbitro; se o pipeline não a passar, usa-se
``achado.dados["contexto"]`` e, na falta, o próprio trecho.

**Achados de padrões amplos** (``achado.forca < 1``): mesma lógica, mas o
``caminho`` recebe o sufixo ``:amplo`` (a calibração dá confiança menor) e,
quando a base **não confirma** o achado (0 candidatos / fora da tabela /
citação vaga sem nenhum registro compatível / ``art. N`` sem diploma) e
``forca < FORCA_MINIMA_SEM_CANDIDATO``, a decisão sai com
``detalhes["descartar"] == "1"``: o pipeline **omite** essa citação (um span
amplo sem respaldo na base é, mais provavelmente, um distrator — emiti-lo
custaria 1 FP; omiti-lo custa no máximo 1 FN, e só se fosse citação de fato).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .base_canonica.consulta import BaseCanonica, Registro
from .base_canonica.normativos import artigo_canonico, diploma_canonico, sumula_canonica
from .normalizacao import (
    CONFUSOES,
    FORMATO_CNJ20,
    FORMATO_REGISTRO,
    TRIBUNAIS,
    cadeia_de_classes,
    classe_principal,
    classes_compativeis,
    como_cadeia,
    formato_de,
    inferir_tribunal,
    nucleos,
    separar_uf,
)
from .tipos import Achado, Decisao

log = logging.getLogger(__name__)

#: Abaixo desta força, um achado amplo que a base não confirma é marcado para descarte.
FORCA_MINIMA_SEM_CANDIDATO = 0.7
#: Chaves com até este número de dígitos são "curtas" (``Nº 42``, ``MS 1662``): exigem classe
#: compatível (era 3; 4 desde a rodada 3, R3-11/R5-04 — ver ADR 0006 §3).
DIGITOS_CURTOS = 4
#: Mínimo de letras confundíveis coladas ao número para acionar ``normalizar_citacao``.
LETRAS_OCR_PARA_ARBITRO = 2
#: Tamanho do cabeçalho comparado para detectar duplicatas (docs/04 h.3-c).
CABECALHO_DUPLICATA = 600

_RE_TRIBUNAL = re.compile(r"\b(STF|STJ|TST|TSE|STM)\b")
_RE_PREFIXO_TST = re.compile(r"\bTST\s*-", re.I)
_RE_ANO = re.compile(r"\b((?:19|20)\d{2})\b")
# Tolera OCR nas palavras de ligação ("relatoria dc", "Rcl. Min." por "Rel. Min.").
_RE_RELATORIA = re.compile(
    r"(?:relatoria\s+[a-zç]{2,3}\b|r[ec]l\.?\s*min\.?|relator[a]?\s*(?:min\.?|ministr[oa])?|"
    r"relatad[oa]\s+pel[oa]\s+(?:min\.?|ministr[oa])?|ministr[oa]\s+relator[a]?)\s*",
    re.I,
)
_RE_DIPLOMA_TAIL = re.compile(r"\b(?:d[ao]s?|de|da|do)\s+\S", re.I)
_RE_ESPACOS = re.compile(r"\s+")
_LETRAS_CONFUSAS = "".join(re.escape(c) for c in CONFUSOES)


# ---------------------------------------------------------------------------
# Dados normalizados de uma citação de processo
# ---------------------------------------------------------------------------
@dataclass
class CitacaoProcesso:
    """Campos de uma citação da família ``processo`` já normalizados.

    Vêm de ``achado.dados`` quando o detector os preencheu (as mesmas funções
    de ``normalizacao`` são usadas por detector, índice e resolução) e são
    recalculados do trecho quando faltam.
    """

    trecho: str
    sem_uf: str
    digitos: str
    formato: str
    cadeia: list[str]
    uf: str | None
    tribunal_explicito: str | None
    tribunal_cnj: str | None
    tribunal_classe: str | None
    registro_secundario: str | None = None
    letras_confundiveis: int = 0
    inicio_numero: int | None = None      # offset do núcleo principal em ``sem_uf``
    origem_dados: dict[str, str] = field(default_factory=dict)

    @property
    def principal(self) -> str | None:
        return classe_principal(self.cadeia)

    @property
    def tribunal_certo(self) -> str | None:
        """Tribunal inferível com certeza (explícito ou pelo segmento J do CNJ)."""
        return self.tribunal_explicito or self.tribunal_cnj

    @property
    def tribunal(self) -> str | None:
        return self.tribunal_certo or self.tribunal_classe


_RE_ORDINAL_TOKEN = re.compile(r"^\d+O$")


def _sem_ordinais_finais(cadeia: Sequence[str]) -> list[str]:
    """Remove ordinais **depois** da classe principal (``[…, "ARE", "44O"]`` → ``[…, "ARE"]``).

    Um ordinal só tem sentido antes do que qualifica (``SEGUNDO AG.REG.``); um
    token ordinal ao fim da cadeia é um número com OCR (``44O``) lido como
    ordinal pela normalização e só atrapalharia a comparação com a cadeia própria.
    """
    saida = list(cadeia)
    while saida and _RE_ORDINAL_TOKEN.match(saida[-1]):
        saida.pop()
    return saida


def _tribunal_valido(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    t = valor.strip().upper()
    return t if t in TRIBUNAIS else None


_RE_GRUPO_OCR = re.compile(rf"[0-9{_LETRAS_CONFUSAS}]+")
_RE_SEPARADOR_NUMERO = re.compile(r"^[\s\.,\-–—/⁄]+$")
_ANTES_DE_LETRA_INICIAL = " \t\n\xa0º°.-–—/("


def _regiao_numerica(sem_uf: str, inicio: int | None = None) -> tuple[int, int, list[re.Match[str]]]:
    """``(inicio, fim, grupos)`` do número citado: do 1º caractere do núcleo até o seu último grupo.

    ``inicio`` é o offset do núcleo principal (``Nucleo.inicio``; num núcleo
    ambíguo pode apontar para uma letra confundível — ``G2.471``); sem ele, o
    primeiro dígito do trecho. Um grupo entra se contém dígito, ou se é um
    segmento só de letras confundíveis (≤ 3) entre separadores e seguido de
    outro grupo com dígito (``2016.S.18``, ``7.OO.0000``); qualquer outra coisa
    (``SP`` de uma UF no meio do trecho, ``(``) fecha a região. Base comum de
    :func:`_letras_confundiveis_no_numero` e :func:`chaves_alternativas`.
    """
    if inicio is not None and 0 <= inicio < len(sem_uf) and (sem_uf[inicio].isdigit() or sem_uf[inicio] in CONFUSOES):
        k = inicio
    else:
        k = next((i for i, c in enumerate(sem_uf) if c.isdigit()), -1)
    if k < 0:
        return -1, -1, []
    grupos = list(_RE_GRUPO_OCR.finditer(sem_uf, k))
    aceitos: list[re.Match[str]] = []
    fim = k
    for j, g in enumerate(grupos):
        entre = sem_uf[fim:g.start()]
        if entre and not _RE_SEPARADOR_NUMERO.match(entre):
            break
        texto = g.group(0)
        if any(c.isdigit() for c in texto):
            aceitos.append(g)
            fim = g.end()
            continue
        proximo = grupos[j + 1] if j + 1 < len(grupos) else None
        if (len(texto) <= _MAX_LETRAS_INICIAIS and proximo is not None
                and any(c.isdigit() for c in proximo.group(0))
                and _RE_SEPARADOR_NUMERO.match(sem_uf[g.end():proximo.start()] or "x")):
            aceitos.append(g)
            fim = g.end()
            continue
        if len(texto) <= _MAX_LETRAS_GRUPO_FINAL and entre in _PONTUACAO_DE_GRUPO and aceitos:
            # grupo final só de letras colado por um sinal de pontuação ("1.140.OSl"): faz parte
            # do número (revisão rodada 2, R4-01) — a conversão relaxada lê "1140051", nunca "1140"
            aceitos.append(g)
            fim = g.end()
            break
        break
    return k, fim, aceitos


def _letras_confundiveis_no_numero(sem_uf: str, inicio: int | None = None) -> int:
    """Quantas letras do mapa de OCR estão dentro do número citado."""
    ini, fim, _ = _regiao_numerica(sem_uf, inicio)
    if ini < 0:
        return 0
    return sum(1 for c in sem_uf[ini:fim] if c in CONFUSOES)


_MAX_LETRAS_INICIAIS = 3
#: Grupo final só de letras confundíveis colado por pontuação (``1.140.OSl``): ver ``normalizacao.nucleos``.
_MAX_LETRAS_GRUPO_FINAL = 4
_PONTUACAO_DE_GRUPO = ".-–"
_SEPARADOR_MILHAR = ".-–—/"


def _letra_inicial_colada(sem_uf: str, inicio_regiao: int) -> str | None:
    """Letras confundíveis logo antes do 1º dígito, precedidas de espaço/conector/início.

    Cobre o OCR no **primeiro** dígito (``G2.471`` por ``62.471``; ``l.234.567``
    por ``1.234.567``, com o ponto de milhar entre a letra e o resto), que a
    normalização determinística recusa por construção (o núcleo abre num
    dígito ASCII). Aceita uma sequência de 1 a 3 letras confundíveis (``lO``)
    colada ao número ou separada dele por **um** sinal de pontuação. A
    exigência de espaço/conector antes da sequência evita tocar siglas
    coladas ao número (``AI12345``: o ``I`` é precedido de ``A``; ``No1234``:
    o ``o`` é precedido de ``N``). ``inicio_regiao`` pode apontar para a
    própria letra (núcleo ambíguo) ou para o primeiro dígito.
    """
    i = inicio_regiao
    while i < len(sem_uf) and not sem_uf[i].isdigit():
        i += 1
    i -= 1
    if i >= 0 and sem_uf[i] in _SEPARADOR_MILHAR:
        i -= 1
    fim = i + 1
    while i >= 0 and sem_uf[i] in CONFUSOES and fim - i <= _MAX_LETRAS_INICIAIS:
        i -= 1
    run = sem_uf[i + 1:fim]
    if not run or len(run) > _MAX_LETRAS_INICIAIS:
        return None
    if i < 0 or sem_uf[i] in _ANTES_DE_LETRA_INICIAL:
        return run
    return None


def chaves_alternativas(sem_uf: str, inicio: int | None = None) -> list[tuple[str, str]]:
    """Chaves canônicas alternativas para OCR que a normalização não converte.

    Só letras viram dígitos (nunca um dígito vira outro) — o mapa
    :data:`normalizacao.CONFUSOES` é a inversa das trocas do gerador de ruído
    (``l``→1, ``O``→0, ``S``→5, ``g``→9, ``G``→6 …), então converter uma letra
    recupera exatamente o dígito original. Alternativas, em ordem:

    * ``letra_no_meio``: grupo de **uma** letra confundível entre dois grupos
      numéricos (``2016.S.18`` — o segmento J do CNJ);
    * ``letra_inicial``: letra(s) confundível(is) coladas **antes** do primeiro
      dígito (:func:`_letra_inicial_colada`), e combinada com a anterior;
    * ``relaxado``: **todas** as letras confundíveis da região numérica
      convertidas — cobre o núcleo ambíguo (``1.OO1.140``, ``1.GO1.157``,
      ``7.OO.0000``), em que a chave padrão é vazia (revisão R2-01).

    Devolve ``[(rótulo, chave), …]`` sem repetições e sem a chave padrão; vazio
    se nada se aplica. Só deve ser consultado quando a chave padrão tem 0
    candidatos (ou é vazia).
    """
    from .normalizacao import classificar_digitos, corrigir_ocr_em_grupo, digitos_do_identificador

    ini, fim, grupos = _regiao_numerica(sem_uf, inicio)
    if ini < 0 or not grupos:
        return []
    if not sem_uf[ini].isdigit():
        # núcleo ambíguo que começa em letra ("G2.471", "l.234.567"): a leitura padrão é vazia
        # e a única alternativa coerente é converter tudo
        tudo = "".join(CONFUSOES.get(c, c) for c in sem_uf[ini:fim] if c.isdigit() or c in CONFUSOES)
        chave = classificar_digitos(tudo)[0] if tudo else ""
        letras = _letra_inicial_colada(sem_uf, ini) or ""
        so_no_inicio = sum(1 for c in sem_uf[ini:fim] if c in CONFUSOES) == len(letras)
        return [("letra_inicial" if so_no_inicio else "relaxado", chave)] if chave else []
    padrao = digitos_do_identificador(sem_uf[ini:fim])
    partes_padrao: list[str] = []      # o que a normalização padrão lê (para na 1ª letra isolada)
    partes_relaxado: list[str] = []    # idem, convertendo letras isoladas entre grupos numéricos
    relaxou = False
    interrompido = False
    for g in grupos:
        texto = g.group(0)
        dig = corrigir_ocr_em_grupo(texto)
        if dig is None:
            if len(texto) == 1 and texto in CONFUSOES and partes_relaxado:
                partes_relaxado.append(CONFUSOES[texto])
                relaxou = True
                continue
            interrompido = True
            break
        if not relaxou:
            partes_padrao.append(dig)
        partes_relaxado.append(dig)
    bruto_padrao = "".join(partes_padrao)
    bruto_relaxado = "".join(partes_relaxado)
    saida: list[tuple[str, str]] = []
    vistos = {padrao} if padrao else set()

    def _add(rotulo: str, bruto: str) -> None:
        if not bruto:
            return
        chave = classificar_digitos(bruto)[0]
        if chave and chave not in vistos:
            vistos.add(chave)
            saida.append((rotulo, chave))

    letras = _letra_inicial_colada(sem_uf, ini)
    prefixo = "".join(CONFUSOES[c] for c in letras) if letras else ""
    if relaxou and not interrompido:
        _add("letra_no_meio", bruto_relaxado)
    if prefixo and not interrompido:
        _add("letra_inicial", prefixo + bruto_padrao)
        if relaxou:
            _add("letra_inicial+meio", prefixo + bruto_relaxado)
    # conversão relaxada de toda a região (inclui o prefixo e grupos com maioria de letras)
    tudo = "".join(CONFUSOES.get(c, c) for c in sem_uf[ini:fim] if c.isdigit() or c in CONFUSOES)
    _add("relaxado", tudo)
    return saida


def _letras_nao_convertidas(sem_uf: str, inicio: int | None = None) -> int:
    """Letras confundíveis do número que a normalização determinística **não** converteu."""
    from .normalizacao import corrigir_ocr_em_grupo

    ini, _fim, grupos = _regiao_numerica(sem_uf, inicio)
    if ini < 0:
        return 0
    n = len(_letra_inicial_colada(sem_uf, ini) or "")
    for g in grupos:
        if corrigir_ocr_em_grupo(g.group(0)) is None:
            n += sum(1 for c in g.group(0) if c in CONFUSOES)
    return n


def _tribunal_explicito_do_trecho(sem_uf: str) -> str | None:
    """``TST-…`` ou sigla de tribunal escrita no próprio span (já sem a UF)."""
    if _RE_PREFIXO_TST.search(sem_uf):
        return "TST"
    m = _RE_TRIBUNAL.search(sem_uf)
    return m.group(1) if m else None


def extrair_processo(achado: Achado) -> CitacaoProcesso:
    """Normaliza os campos de um achado ``processo`` (usa ``dados`` quando presentes)."""
    d = achado.dados or {}
    trecho = achado.trecho
    sem_uf, uf_trecho = separar_uf(trecho)
    uf = d.get("uf") or uf_trecho
    uf = uf.strip().upper() if isinstance(uf, str) and uf.strip() else None

    digitos = d.get("digitos") or ""
    if not (isinstance(digitos, str) and digitos.isdigit()):
        digitos = ""
    todos = nucleos(sem_uf)
    principal = next((n for n in todos if n.n_digitos >= 4), None)
    if principal is None and todos:
        principal = max(todos, key=lambda n: (n.n_digitos, -n.inicio))
    if digitos:
        # dados do detector: localiza o núcleo correspondente (para o reparo de OCR)
        principal = next((n for n in todos if n.digitos == digitos), principal)
    else:
        digitos = principal.digitos if principal else ""
    inicio_numero = principal.inicio if principal else None
    formato = formato_de(digitos) if digitos else "outro"
    registro_secundario = None
    for n in todos:
        if n.formato == FORMATO_REGISTRO and n.digitos != digitos:
            registro_secundario = n.digitos
            break

    cadeia = como_cadeia(d.get("cadeia")) if d.get("cadeia") else []
    if not cadeia:
        cadeia = cadeia_de_classes(sem_uf)
    cadeia = _sem_ordinais_finais(cadeia)

    # ``dados["tribunal"]`` do detector é INFERIDO (classe/CNJ) salvo quando o detector marca
    # ``tribunal_fonte == "explicito"`` (prefixo TST-); a inferência pela classe nunca é
    # eliminatória (ADR 0006 §2: "Recurso Especial" com número de um REspe continua real)
    fonte = d.get("tribunal_fonte")
    tribunal_explicito = _tribunal_explicito_do_trecho(sem_uf)
    if fonte == "explicito" or (fonte is None and d.get("prefixo_tst") == "1"):
        tribunal_explicito = _tribunal_valido(d.get("tribunal")) or tribunal_explicito
    tribunal_cnj = None
    if formato == FORMATO_CNJ20 and len(digitos) == 20:
        tribunal_cnj = inferir_tribunal([], None, digitos, FORMATO_CNJ20)
    tribunal_classe = inferir_tribunal(cadeia, uf, "", None) if cadeia else None

    return CitacaoProcesso(
        trecho=trecho, sem_uf=sem_uf, digitos=digitos, formato=formato, cadeia=cadeia, uf=uf,
        tribunal_explicito=tribunal_explicito, tribunal_cnj=tribunal_cnj, tribunal_classe=tribunal_classe,
        registro_secundario=registro_secundario,
        letras_confundiveis=_letras_confundiveis_no_numero(sem_uf, inicio_numero),
        inicio_numero=inicio_numero,
        origem_dados={k: str(v) for k, v in d.items() if k != "contexto"},
    )


# ---------------------------------------------------------------------------
# Predicados de compatibilidade (docs/04 h.2)
# ---------------------------------------------------------------------------
def relacao_de_classe(cit: CitacaoProcesso, registro: Registro) -> str:
    """Relação entre a cadeia citada e a cadeia própria do registro.

    ``cadeia_exata`` (``ED AGINT ARESP`` = ``ED AGINT ARESP``) → ``classe_principal``
    (mesma classe principal, prefixos diferentes: ``Rcl`` × ``AgRg na Rcl``) →
    ``classe_compativel`` (equivalentes: ``RESP``≈``RESPE``, família TST
    ``AgARR``≈``AIRR``) → ``sem_classe`` (citação sem cadeia reconhecida) →
    ``classe_divergente``.
    """
    if not cit.cadeia:
        return "sem_classe"
    if " ".join(cit.cadeia) == (registro.classe_propria or ""):
        return "cadeia_exata"
    propria = registro.classe_principal
    citada = cit.principal
    if citada is not None and citada == propria:
        return "classe_principal"
    if classes_compativeis(citada, propria):
        return "classe_compativel"
    return "classe_divergente"


def tribunal_incompativel(cit: CitacaoProcesso, registro: Registro) -> bool:
    """O registro pertence a um tribunal que a citação exclui com certeza.

    Tribunal explícito (``TST-``, sigla no span) ou segmento J do CNJ decidem
    sempre. A inferência **pela classe** (``REsp`` → STJ) só elimina quando a
    classe própria do registro não é sequer compatível com a citada: um
    ``Recurso Especial`` cujo número é de um ``REspe`` do TSE é a mesma classe
    em nomenclatura de outra era (docs/04 h.2 declara ``RESP≈RESPE``), mas 5
    dígitos do STF citados como ``REsp`` são outro processo (``RCL`` ≠ ``RESP``).
    """
    if registro.tribunal is None:
        return False
    certo = cit.tribunal_certo
    if certo:
        return registro.tribunal != certo
    if cit.tribunal_classe and registro.tribunal != cit.tribunal_classe:
        return not classes_compativeis(cit.principal, registro.classe_principal)
    return False


def uf_incompativel(cit: CitacaoProcesso, registro: Registro) -> bool:
    """UF citada e UF própria conhecidas e diferentes (registros sem UF são mantidos)."""
    return bool(cit.uf) and registro.uf is not None and registro.uf != cit.uf


# ---------------------------------------------------------------------------
# Utilidades de decisão
# ---------------------------------------------------------------------------
def _ids(regs: Sequence[Registro]) -> tuple[int, ...]:
    return tuple(r.id_canonico for r in regs)


def _menor_documento(regs: Sequence[Registro]) -> Registro:
    return min(regs, key=lambda r: r.documento_id)


def _cabecalho_normalizado(base: BaseCanonica, registro: Registro) -> str:
    try:
        cab = base.cabecalho(registro.documento_id, CABECALHO_DUPLICATA)
    except (KeyError, AttributeError):
        cab = ""
    return _RE_ESPACOS.sub(" ", cab).strip()


def sao_duplicatas(base: BaseCanonica, regs: Sequence[Registro]) -> bool:
    """Candidatos indistinguíveis: cabeçalhos (600 chars) idênticos **ou** mesmos
    tribunal/ano/relator/cadeia (versões da mesma decisão que diferem só no
    prefixo de exportação — 10 dos 77 grupos ambíguos da base)."""
    if len(regs) < 2:
        return True
    cabs = {_cabecalho_normalizado(base, r) for r in regs}
    if len(cabs) == 1:
        return True
    metas = {(r.tribunal, r.ano, r.relator, r.classe_propria) for r in regs}
    return len(metas) == 1


def _contexto_para_arbitro(achado: Achado, contexto: str | None) -> str:
    if contexto:
        return contexto
    ctx = (achado.dados or {}).get("contexto")
    return ctx if isinstance(ctx, str) and ctx else achado.trecho


def _decisao(classificacao: str, id_canonico: int | None, caminho: str,
             candidatos: Sequence[Registro] | tuple[int, ...], detalhes: dict[str, str]) -> Decisao:
    cands = candidatos if isinstance(candidatos, tuple) else _ids(candidatos)
    return Decisao(classificacao, id_canonico, caminho, cands, detalhes)


# ---------------------------------------------------------------------------
# Família processo
# ---------------------------------------------------------------------------
def _filtrar(cands: list[Registro], predicado, nome: str, detalhes: dict[str, str],
             filtros: list[str]) -> list[Registro]:
    """Aplica um filtro eliminatório (tribunal/UF): registra o nome e o que sobrou."""
    restantes = [r for r in cands if not predicado(r)]
    if len(restantes) != len(cands):
        filtros.append(nome)
        detalhes[f"filtro_{nome}"] = f"{len(cands)}>{len(restantes)}"
    return restantes


def _desempatar_por_classe(cit: CitacaoProcesso, cands: list[Registro], detalhes: dict[str, str],
                           filtros: list[str]) -> tuple[list[Registro], str | None]:
    """Cadeia exata → classe principal → classe compatível; **nunca** elimina todos."""
    if not cit.cadeia or len(cands) < 2:
        return cands, None
    for relacao in ("cadeia_exata", "classe_principal", "classe_compativel"):
        sub = [r for r in cands if relacao_de_classe(cit, r) == relacao]
        if sub:
            if len(sub) < len(cands):
                filtros.append(relacao)
                detalhes[f"filtro_{relacao}"] = f"{len(cands)}>{len(sub)}"
            return sub, relacao
    return cands, None


def _desempatar_por_registro(base: BaseCanonica, cit: CitacaoProcesso, cands: list[Registro],
                             detalhes: dict[str, str], filtros: list[str]) -> list[Registro]:
    """Citação com número **e** registro do STJ: fica quem tem os dois (docs/04 h.4)."""
    if not cit.registro_secundario or len(cands) < 2:
        return cands
    sub = []
    for r in cands:
        try:
            ids = base.identificadores(r.documento_id)
        except (KeyError, AttributeError):
            ids = []
        if any(i.get("digitos") == cit.registro_secundario for i in ids):
            sub.append(r)
    if sub and len(sub) < len(cands):
        filtros.append("registro")
        detalhes["filtro_registro"] = f"{len(cands)}>{len(sub)}"
        return sub
    return cands


def _decidir_entre_candidatos(
    achado: Achado, cit: CitacaoProcesso, cands: list[Registro], base: BaseCanonica,
    arbitro: Any, contexto: str | None, prefixo: str, detalhes: dict[str, str],
) -> Decisao:
    """≥ 1 candidato pelo número: filtros eliminatórios, desempates e escolha final."""
    iniciais = list(cands)
    filtros: list[str] = []
    detalhes["n_candidatos"] = str(len(iniciais))

    # --- 1 candidato -------------------------------------------------------
    if len(iniciais) == 1:
        r = iniciais[0]
        detalhes["cadeia_propria"] = r.classe_propria or ""
        detalhes["tribunal_proprio"] = r.tribunal or ""
        detalhes["uf_propria"] = r.uf or ""
        if tribunal_incompativel(cit, r):
            log.info("processo %r: número único mas tribunal %s ≠ %s (%s) → inventada",
                     cit.digitos, cit.tribunal, r.tribunal, cit.trecho[:40])
            return _decisao("inventada", None, f"{prefixo}:1cand:tribunal_incompativel", iniciais, detalhes)
        if uf_incompativel(cit, r):
            log.info("processo %r: número único mas UF %s ≠ %s → inventada", cit.digitos, cit.uf, r.uf)
            return _decisao("inventada", None, f"{prefixo}:1cand:uf_incompativel", iniciais, detalhes)
        relacao = relacao_de_classe(cit, r)
        detalhes["classe_relacao"] = relacao
        if relacao == "classe_divergente" and len(cit.digitos) <= DIGITOS_CURTOS:
            # "Nº 42": chave fraca demais para sustentar uma classe diferente (docs/04 c)
            return _decisao("inventada", None, f"{prefixo}:1cand:curto_classe_divergente", iniciais, detalhes)
        if cit.formato == FORMATO_REGISTRO:
            # registro ``AAAA/NNNNNNN-D`` do STJ com dígito verificador: uma colisão por perturbação é
            # praticamente impossível — o registro manda, qualquer que seja a classe (rodada 4, R4-08)
            return _decisao("real", r.id_canonico, f"{prefixo}:1cand:registro", iniciais, detalhes)
        if relacao == "classe_divergente" and not cit.uf and not cit.tribunal_certo:
            # ``Rcl 12345``/``HC 12345``/``MS 12345`` sem UF nem tribunal certo com o número de OUTRA
            # classe: nada além do número sustenta a escolha. Pela assimetria da métrica (inventada→real
            # custa ≈ 2,6× real→inventada; break-even P(real) ≈ 0,73) e pelo prior ≈ 0,5–0,6 deste
            # caminho, a decisão de menor custo esperado é ``inventada`` (rodada 4, R4-03; ADR 0006 §3)
            log.info("processo %r: classe citada %s ≠ própria %s sem UF/tribunal → inventada",
                     cit.digitos, " ".join(cit.cadeia), r.classe_propria)
            return _decisao("inventada", None, f"{prefixo}:1cand:classe_divergente:sem_uf", iniciais, detalhes)
        if relacao == "classe_divergente":
            log.info("processo %r: classe citada %s ≠ própria %s; UF/tribunal confirmam — número manda "
                     "(confiança rebaixada)", cit.digitos, " ".join(cit.cadeia), r.classe_propria)
        return _decisao("real", r.id_canonico, f"{prefixo}:1cand:{relacao}", iniciais, detalhes)

    # --- ≥ 2 candidatos: tribunal → UF (eliminatórios) ----------------------
    cands = _filtrar(iniciais, lambda r: tribunal_incompativel(cit, r), "tribunal", detalhes, filtros)
    if not cands:
        return _decisao("inventada", None, f"{prefixo}:multi:tribunal_incompativel", iniciais, detalhes)
    cands = _filtrar(cands, lambda r: uf_incompativel(cit, r), "uf", detalhes, filtros)
    if not cands:
        return _decisao("inventada", None, f"{prefixo}:multi:uf_incompativel", iniciais, detalhes)

    # --- chave curta com classe divergente de TODOS os candidatos (``HC nº 87`` num grupo de
    # ``QO CautInom``; ``MS 1662`` num grupo de ``RO``): mesma proteção do caso de 1 candidato,
    # aplicada ANTES do atalho de duplicatas (rodada 3, R3-11)
    if (cit.cadeia and len(cit.digitos) <= DIGITOS_CURTOS
            and all(relacao_de_classe(cit, r) == "classe_divergente" for r in cands)):
        detalhes["classe_relacao"] = "classe_divergente"
        return _decisao("inventada", None, f"{prefixo}:multi:curto_classe_divergente", iniciais, detalhes)

    # --- desempates não eliminatórios: cadeia/classe → registro do STJ → UF confirmada
    cands, relacao = _desempatar_por_classe(cit, cands, detalhes, filtros)
    cands = _desempatar_por_registro(base, cit, cands, detalhes, filtros)
    if cit.uf and len(cands) > 1:
        # evidência positiva vence ausência: entre um registro com a UF citada e
        # outro sem UF no cabeçalho, fica o primeiro
        com_uf = [r for r in cands if r.uf == cit.uf]
        if com_uf and len(com_uf) < len(cands):
            filtros.append("uf_confirmada")
            detalhes["filtro_uf_confirmada"] = f"{len(cands)}>{len(com_uf)}"
            cands = com_uf
    detalhes["filtros"] = ",".join(filtros)
    if relacao:
        detalhes["classe_relacao"] = relacao

    if len(cands) == 1:
        r = cands[0]
        detalhes["cadeia_propria"] = r.classe_propria or ""
        ultimo = filtros[-1] if filtros else "unico"
        return _decisao("real", r.id_canonico, f"{prefixo}:multi:{ultimo}", iniciais, detalhes)

    # --- ainda ≥ 2: duplicatas → escolha determinística; senão árbitro ------
    detalhes["restantes"] = ",".join(str(r.id_canonico) for r in cands)
    if sao_duplicatas(base, cands):
        r = _menor_documento(cands)
        detalhes["cadeia_propria"] = r.classe_propria or ""
        log.info("processo %r: %d duplicatas indistinguíveis; escolhido documento_id mínimo (%s)",
                 cit.digitos, len(cands), r.documento_id)
        if cit.cadeia and all(relacao_de_classe(cit, x) == "classe_divergente" for x in cands):
            # grupo duplicado de OUTRA classe: prior ≈ 0,5 < break-even 0,73 → inventada (R3-11; rodada 4, R4-03)
            return _decisao("inventada", None, f"{prefixo}:duplicata:classe_divergente", iniciais, detalhes)
        return _decisao("real", r.id_canonico, f"{prefixo}:duplicata", iniciais, detalhes)

    if arbitro is not None:
        escolha = _escolher_com_arbitro(achado, cit, cands, base, arbitro, contexto)
        if escolha is not None:
            detalhes["llm"] = "escolheu"
            detalhes["cadeia_propria"] = escolha.classe_propria or ""
            return _decisao("real", escolha.id_canonico, f"{prefixo}:llm_escolha", iniciais, detalhes)
        detalhes["llm"] = "absteve"
    r = _menor_documento(cands)
    detalhes["cadeia_propria"] = r.classe_propria or ""
    log.info("processo %r: %d candidatos distintos sem desempate; chute determinístico (%s)",
             cit.digitos, len(cands), r.documento_id)
    return _decisao("real", r.id_canonico, f"{prefixo}:ambiguo_chute", iniciais, detalhes)


def _escolher_com_arbitro(achado: Achado, cit: CitacaoProcesso, cands: list[Registro],
                          base: BaseCanonica, arbitro: Any, contexto: str | None) -> Registro | None:
    """``escolher_candidato`` só com cabeçalhos diferentes (ADR 0003); ``None`` = abstenção."""
    try:
        from .llm.arbitro import candidato_de_registro
    except ImportError:  # pragma: no cover - llm/ ausente
        return None
    lista = [candidato_de_registro(r, base.cabecalho(r.documento_id, CABECALHO_DUPLICATA)) for r in cands]
    try:
        idx = arbitro.escolher_candidato(achado.trecho, _contexto_para_arbitro(achado, contexto), lista)
    except Exception:
        log.exception("árbitro falhou em escolher_candidato; seguindo sem ele")
        return None
    if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(cands):
        return None
    return cands[idx]


def _normalizar_com_arbitro(achado: Achado, cit: CitacaoProcesso, arbitro: Any,
                            contexto: str | None) -> dict[str, Any] | None:
    try:
        r = arbitro.normalizar_citacao(achado.trecho, _contexto_para_arbitro(achado, contexto))
    except Exception:
        log.exception("árbitro falhou em normalizar_citacao; seguindo sem ele")
        return None
    return r if isinstance(r, dict) else None


def _aplicar_normalizacao(cit: CitacaoProcesso, r: dict[str, Any]) -> CitacaoProcesso:
    """Nova ``CitacaoProcesso`` com os dígitos/cadeia/UF/tribunal devolvidos pelo árbitro."""
    digitos = str(r.get("digitos_canonicos") or "")
    digitos = digitos if digitos.isdigit() else ""
    cadeia = _sem_ordinais_finais([str(s) for s in (r.get("classe_cadeia") or [])]) or cit.cadeia
    uf = _uf_valida(r.get("uf")) or cit.uf
    tribunal_explicito = cit.tribunal_explicito or _tribunal_valido(r.get("tribunal"))
    formato = formato_de(digitos) if digitos else "outro"
    tribunal_cnj = inferir_tribunal([], None, digitos, FORMATO_CNJ20) if formato == FORMATO_CNJ20 else None
    return CitacaoProcesso(
        trecho=cit.trecho, sem_uf=cit.sem_uf, digitos=digitos, formato=formato, cadeia=cadeia, uf=uf,
        tribunal_explicito=tribunal_explicito, tribunal_cnj=tribunal_cnj,
        tribunal_classe=inferir_tribunal(cadeia, uf, "", None) if cadeia else None,
        registro_secundario=cit.registro_secundario, letras_confundiveis=cit.letras_confundiveis,
        inicio_numero=cit.inicio_numero, origem_dados=cit.origem_dados,
    )


def _com_digitos(cit: CitacaoProcesso, digitos: str) -> CitacaoProcesso:
    """Cópia da citação com outra chave (reparo de OCR); tribunal do CNJ recalculado."""
    formato = formato_de(digitos) if digitos else "outro"
    tribunal_cnj = inferir_tribunal([], None, digitos, FORMATO_CNJ20) if formato == FORMATO_CNJ20 else None
    return CitacaoProcesso(
        trecho=cit.trecho, sem_uf=cit.sem_uf, digitos=digitos, formato=formato, cadeia=cit.cadeia, uf=cit.uf,
        tribunal_explicito=cit.tribunal_explicito, tribunal_cnj=tribunal_cnj, tribunal_classe=cit.tribunal_classe,
        registro_secundario=cit.registro_secundario, letras_confundiveis=cit.letras_confundiveis,
        inicio_numero=cit.inicio_numero, origem_dados=cit.origem_dados,
    )


def _uf_valida(valor: Any) -> str | None:
    from .normalizacao import UFS

    if not isinstance(valor, str):
        return None
    v = valor.strip().upper()
    return v if v in UFS else None


def _resolver_processo(achado: Achado, base: BaseCanonica, arbitro: Any, contexto: str | None) -> Decisao:
    cit = extrair_processo(achado)
    detalhes: dict[str, str] = {
        "digitos": cit.digitos, "formato": cit.formato, "cadeia_citada": " ".join(cit.cadeia),
        "uf": cit.uf or "", "tribunal": cit.tribunal or "",
        "tribunal_fonte": ("explicito" if cit.tribunal_explicito else "cnj" if cit.tribunal_cnj
                           else "classe" if cit.tribunal_classe else ""),
    }
    if cit.registro_secundario:
        detalhes["registro_secundario"] = cit.registro_secundario
    prefixo = "processo"

    cands = base.candidatos_por_numero(cit.digitos) if cit.digitos else []

    # --- reparo determinístico de OCR que a normalização recusa (letra inicial,
    # letra isolada no meio de um CNJ): só letras viram dígitos, e só se a chave
    # padrão não tem dono. Uma única alternativa com dono resolve; várias → ambíguo.
    if not cands:
        alternativas = [(rot, ch) for rot, ch in chaves_alternativas(cit.sem_uf, cit.inicio_numero) if ch != cit.digitos]
        com_dono = [(rot, ch, base.candidatos_por_numero(ch)) for rot, ch in alternativas]
        com_dono = [x for x in com_dono if x[2]]
        if alternativas:
            detalhes["ocr_alternativas"] = ",".join(rot for rot, _ in alternativas)
        if len(com_dono) == 1:
            rot, chave, cands = com_dono[0]
            log.info("processo: chave %r sem dono; reparo de OCR (%s) → %r com %d candidato(s)",
                     cit.digitos, rot, chave, len(cands))
            cit = _com_digitos(cit, chave)
            detalhes.update({"digitos": cit.digitos, "formato": cit.formato, "tribunal": cit.tribunal or "",
                             "ocr_reparo": rot})
            return _decidir_entre_candidatos(achado, cit, cands, base, arbitro, contexto, "processo:ocr_reparado", detalhes)
        if len(com_dono) > 1:
            detalhes["ocr_reparo"] = "ambiguo"
        elif alternativas:
            detalhes["ocr_reparo"] = "sem_dono"

    # --- gatilhos do árbitro (ADR 0003): sem dígitos, ou 0 candidatos com OCR que
    # a normalização não converteu (letra inicial/isolada) ou com ≥ 2 letras convertidas
    nao_convertidas = _letras_nao_convertidas(cit.sem_uf, cit.inicio_numero)
    ocr_ambiguo = cit.letras_confundiveis >= LETRAS_OCR_PARA_ARBITRO or nao_convertidas >= 1
    if not cands and (not cit.digitos or ocr_ambiguo):
        detalhes["letras_confundiveis"] = str(cit.letras_confundiveis)
        detalhes["letras_nao_convertidas"] = str(nao_convertidas)
        if arbitro is not None:
            r = _normalizar_com_arbitro(achado, cit, arbitro, contexto)
            if r is None:
                detalhes["llm"] = "absteve"
            elif not r.get("eh_citacao", True):
                detalhes["llm"] = "nao_citacao"
                return _decisao("inventada", None, "processo:llm_nao_citacao", (), detalhes)
            else:
                nova = _aplicar_normalizacao(cit, r)
                detalhes["llm"] = "normalizou"
                detalhes["digitos_llm"] = nova.digitos
                prefixo = "processo:llm_normalizou"
                cands = base.candidatos_por_numero(nova.digitos) if nova.digitos else []
                if not cands:
                    return _decisao("inventada", None, f"{prefixo}:0cand", (), detalhes)
                cit = nova
                detalhes.update({"digitos": cit.digitos, "formato": cit.formato,
                                 "cadeia_citada": " ".join(cit.cadeia), "uf": cit.uf or "",
                                 "tribunal": cit.tribunal or ""})
                return _decidir_entre_candidatos(achado, cit, cands, base, arbitro, contexto, prefixo, detalhes)
        if detalhes.get("ocr_reparo") == "sem_dono":
            # todas as letras foram convertidas (mapa inverso do gerador) e a chave não tem dono:
            # tão inventada quanto um 0cand limpo, com uma chave calibrada própria
            return _decisao("inventada", None, "processo:0cand:ocr_sem_dono", (), detalhes)
        return _decisao("inventada", None, "processo:0cand:ocr_ambiguo", (), detalhes)

    if not cands:
        if cit.registro_secundario and base.candidatos_por_numero(cit.registro_secundario):
            # número inventado mas registro real (ou vice-versa): o número manda (docs/04 h.4)
            detalhes["registro_resolve"] = "1"
            return _decisao("inventada", None, "processo:0cand:registro_diverge", (), detalhes)
        return _decisao("inventada", None, "processo:0cand", (), detalhes)

    return _decidir_entre_candidatos(achado, cit, cands, base, arbitro, contexto, prefixo, detalhes)


# ---------------------------------------------------------------------------
# Súmula, dispositivo, tema, vaga
# ---------------------------------------------------------------------------
def _com_ocr(caminho: str, dados: dict[str, Any], detalhes: dict[str, str]) -> str:
    """Sufixo ``:ocr`` quando o número da súmula/artigo tinha letras confundíveis convertidas
    (``Súmula 8l``, ``art. 12G``; revisão rodada 2): mesma classe, confiança calibrada à parte."""
    letras = str(dados.get("letras_ocr") or "0")
    if letras not in ("", "0"):
        detalhes["letras_ocr"] = letras
        return caminho + ":ocr"
    return caminho


def _resolver_sumula(achado: Achado, base: BaseCanonica) -> Decisao:
    d = achado.dados or {}
    trib_t, vinc_t, num_t = sumula_canonica(achado.trecho)
    numero: int | None = None
    bruto = d.get("numero_sumula")
    if isinstance(bruto, str) and bruto.strip().isdigit():
        numero = int(bruto.strip())
    elif isinstance(bruto, int):
        numero = bruto
    else:
        numero = num_t
    vinculante = (d.get("vinculante") == "1") if "vinculante" in d else bool(vinc_t)
    m_trib = _RE_TRIBUNAL.search(achado.trecho)
    explicito = _tribunal_valido(d.get("tribunal")) or (m_trib.group(1) if m_trib else None)
    del trib_t  # ``sumula_canonica`` já embute "Vinculante ⇒ STF"; aqui a fonte é registrada à parte
    if vinculante and explicito and explicito != "STF":
        # ``Súmula Vinculante N do STJ``: docs/04 h.8 — tribunal explícito diferente do da tabela é
        # inventada (rodada 3, R5-08; antes a exceção "Vinculante implica STF" ignorava o tribunal:
        # um inventada→real custa FN + FP + τ, um real→inventada só FN + FP)
        log.info("súmula vinculante com tribunal explícito %s ≠ STF → inventada", explicito)
        detalhes = {"numero": "" if numero is None else str(numero), "vinculante": "1",
                    "tribunal": explicito, "tribunal_fonte": "explicito"}
        if numero is None:
            return _decisao("incompleta", None, "sumula:sem_numero", (), detalhes)
        return _decisao("inventada", None, _com_ocr("sumula:fora_da_tabela:vinculante_tribunal_divergente", d, detalhes),
                        (), detalhes)
    tribunal = "STF" if vinculante else explicito
    detalhes = {"numero": "" if numero is None else str(numero), "vinculante": "1" if vinculante else "0",
                "tribunal": tribunal or "", "tribunal_fonte": ("implicito" if vinculante and not explicito
                                                               else "explicito" if explicito else "")}
    if numero is None:
        return _decisao("incompleta", None, "sumula:sem_numero", (), detalhes)
    reg = base.sumula(tribunal, vinculante, numero)
    if reg is not None:
        sub = "sumula:na_tabela"
        if tribunal is None:
            sub += ":sem_tribunal"
        elif vinculante and not explicito:
            sub += ":tribunal_implicito"
        return _decisao("real", reg.id_canonico, _com_ocr(sub, d, detalhes), (reg,), detalhes)
    sub = "sumula:fora_da_tabela"
    if tribunal is None:
        sub += ":sem_tribunal"
    elif base.sumula(None, vinculante, numero) is not None:
        sub += ":tribunal_divergente"   # o número existe sob outro tribunal: ainda inventada (base fechada)
    return _decisao("inventada", None, _com_ocr(sub, d, detalhes), (), detalhes)


def _resolver_dispositivo(achado: Achado, base: BaseCanonica) -> Decisao:
    d = achado.dados or {}
    diploma = d.get("diploma") or diploma_canonico(achado.trecho)
    artigo = d.get("artigo") or artigo_canonico(achado.trecho)
    artigo = str(artigo).replace(".", "").lstrip("0") if artigo else None
    detalhes = {"diploma": diploma or "", "artigo": artigo or ""}
    if not artigo:
        return _decisao("incompleta", None, "dispositivo:sem_artigo", (), detalhes)
    if not diploma:
        # há um nome de diploma no span que não reconhecemos? Então é identificável
        # (e fora da base fechada) → inventada; sem diploma algum → incompleta.
        m = re.search(r"\d", achado.trecho)
        cauda = achado.trecho[m.end():] if m else achado.trecho
        if _RE_DIPLOMA_TAIL.search(cauda):
            return _decisao("inventada", None, "dispositivo:diploma_desconhecido", (), detalhes)
        return _decisao("incompleta", None, "dispositivo:sem_diploma", (), detalhes)
    if diploma.startswith(("LEI-", "DL-", "LC-")):
        return _decisao("inventada", None, "dispositivo:diploma_fora_da_base", (), detalhes)
    reg = base.dispositivo(diploma, artigo)
    if reg is not None:
        return _decisao("real", reg.id_canonico, _com_ocr("dispositivo:na_tabela", d, detalhes), (reg,), detalhes)
    if diploma == "OUTRO":
        # o detector reconheceu um nome de diploma, mas ninguém o canonizou: ou é um diploma
        # fora da base (Resolução, Portaria…) ou um diploma coberto com OCR que a tolerância
        # não alcançou — inventada, mas com confiança própria (revisão R2-04)
        return _decisao("inventada", None, "dispositivo:fora_da_tabela:diploma_outro", (), detalhes)
    return _decisao("inventada", None, _com_ocr("dispositivo:fora_da_tabela", d, detalhes), (), detalhes)


def _resolver_tema(achado: Achado) -> Decisao:
    """``tema`` → ``inventada`` (a base não tem temas).

    Sub-caminhos para a calibração (a evidência é muito diferente entre eles): ``:repercussao``
    para a forma confirmada pelo gabarito (``Tema N da repercussão geral``), ``:repetitivo`` para
    ``Tema Repetitivo N``/``Tema N do STJ`` (forma plausível, sem exemplo no dev) e ``:solto`` para
    ``Tema N`` sem complemento (aposta condicionada a indício; ver deteccao.tema).
    """
    dados = achado.dados or {}
    numero = dados.get("numero_tema") or ""
    origem = achado.origem or ""
    if origem.endswith(":sem_complemento"):
        sub = "solto"
    elif dados.get("tribunal") == "STJ":
        sub = "repetitivo"
    else:
        sub = "repercussao"
    return _decisao("inventada", None, f"tema:inventada:{sub}", (), {"numero": str(numero)})


def campos_da_vaga(trecho: str) -> tuple[str | None, int | None, str | None]:
    """``(tribunal, ano, relator)`` lidos do span de uma citação vaga (só diagnóstico)."""
    m_t = _RE_TRIBUNAL.search(trecho)
    m_a = _RE_ANO.search(trecho)
    relator = None
    ultimo = None
    for m in _RE_RELATORIA.finditer(trecho):
        ultimo = m
    if ultimo is not None:
        relator = _RE_ESPACOS.sub(" ", trecho[ultimo.end():]).strip(" ,.;:") or None
    return (m_t.group(1) if m_t else None, int(m_a.group(1)) if m_a else None, relator)


def _resolver_vaga(achado: Achado, base: BaseCanonica) -> Decisao:
    d = achado.dados or {}
    trib_t, ano_t, rel_t = campos_da_vaga(achado.trecho)
    tribunal = _tribunal_valido(d.get("tribunal")) or trib_t
    ano: int | None = None
    if isinstance(d.get("ano"), str) and d["ano"].strip().isdigit():
        ano = int(d["ano"].strip())
    elif isinstance(d.get("ano"), int):
        ano = d["ano"]
    else:
        ano = ano_t
    relator = d.get("relator") or rel_t
    detalhes = {"tribunal": tribunal or "", "ano": "" if ano is None else str(ano), "relator": relator or ""}
    regs: list[Registro] = []
    if ano is not None or relator:
        try:
            regs = base.por_relator_ano(tribunal, ano, relator)
        except Exception:
            log.exception("por_relator_ano falhou; multiplicidade desconhecida")
            regs = []
        detalhes["multiplicidade"] = str(len(regs))
    else:
        detalhes["multiplicidade"] = "?"
    caminho = "vaga:incompleta"
    if ano is not None or relator:
        if not regs:
            caminho += ":sem_correspondencia"
        elif len(regs) == 1:
            caminho += ":unica"
    return _decisao("incompleta", None, caminho, regs, detalhes)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
def _marcar_amplo(achado: Achado, decisao: Decisao) -> Decisao:
    """Sufixo ``:amplo`` e flag ``descartar`` para achados de padrões amplos."""
    if achado.forca >= 1.0:
        return decisao
    detalhes = dict(decisao.detalhes)
    detalhes["forca"] = f"{achado.forca:.2f}"
    nao_confirmada = decisao.classificacao == "inventada" or (
        achado.familia == "vaga" and detalhes.get("multiplicidade") == "0"
    ) or (
        # ``Enunciado 12 do CJF``/``da V Jornada``: órgão não jurisdicional depois do número — nunca é
        # súmula de tribunal superior, mesmo que o número exista na tabela (rodada 4, R6-11)
        achado.familia == "sumula" and (achado.dados or {}).get("orgao_externo") == "1"
    ) or (
        # tribunal + ano + relatoria sem substantivo de citação nem classe antes do tribunal
        # ("O STJ, em 2019, pela relatoria do Min. X, assentou…") é prosa sobre o tribunal
        # (revisão rodada 2, R4-04; ADR 0005)
        achado.familia == "vaga" and (achado.dados or {}).get("sem_substantivo") == "1"
    ) or (
        # ``art. N`` solto (sem diploma reconhecível): a base não confirma nada e o dev não
        # anota artigo sem diploma — emitir ``incompleta`` custaria 1 FP numa classe de
        # suporte pequeno (revisões R1-06/R2-05; ADR 0006 §8)
        achado.familia == "dispositivo" and decisao.classificacao == "incompleta"
    )
    if nao_confirmada and achado.forca < FORCA_MINIMA_SEM_CANDIDATO:
        detalhes["descartar"] = "1"
        log.info("achado amplo (forca=%.2f) sem respaldo na base: marcado para descarte (%s)",
                 achado.forca, decisao.caminho)
    return Decisao(decisao.classificacao, decisao.id_canonico, decisao.caminho + ":amplo",
                   decisao.candidatos, detalhes)


def resolver(achado: Achado, base: BaseCanonica, arbitro: Any = None, contexto: str | None = None) -> Decisao:
    """Resolve um achado contra a base canônica.

    Caminhos (chave da calibração; hierárquicos por ``:``):

    * ``processo:0cand`` (inventada), ``processo:0cand:ocr_sem_dono`` (letras
      convertidas pelo mapa inverso do gerador, chave sem dono),
      ``processo:0cand:ocr_ambiguo`` (sem dígitos, OCR sem alternativa ou com ≥ 2
      alternativas com dono, sem árbitro/abstenção), ``processo:0cand:registro_diverge``;
    * ``processo:1cand:{cadeia_exata|classe_principal|classe_compativel|sem_classe|
      classe_divergente|registro}`` (real) e ``processo:1cand:{tribunal_incompativel|
      uf_incompativel|curto_classe_divergente|classe_divergente:sem_uf}`` (inventada);
    * ``processo:multi:<último filtro>`` (real após tribunal → UF → cadeia exata →
      classe principal → classe compatível → registro → UF confirmada),
      ``processo:multi:{tribunal|uf}_incompativel``, ``processo:multi:curto_classe_divergente``,
      ``processo:duplicata:classe_divergente`` (inventada), ``processo:duplicata`` (real, menor
      ``documento_id``), ``processo:llm_escolha``, ``processo:ambiguo_chute``;
    * ``processo:ocr_reparado:…`` (mesmos sub-caminhos após o reparo determinístico
      de OCR — letra inicial ou letra isolada no CNJ — quando a chave padrão não
      tem dono; ver :func:`chaves_alternativas`);
    * ``processo:llm_normalizou:…`` (mesmos sub-caminhos após ``normalizar_citacao``),
      ``processo:llm_nao_citacao``;
    * ``sumula:na_tabela[:tribunal_implicito|:sem_tribunal]``, ``sumula:fora_da_tabela
      [:sem_tribunal|:tribunal_divergente|:vinculante_tribunal_divergente]``, ``sumula:sem_numero``
      (incompleta);
    * ``dispositivo:na_tabela``, ``dispositivo:fora_da_tabela[:diploma_outro]``,
      ``dispositivo:diploma_fora_da_base``, ``dispositivo:diploma_desconhecido`` (inventada),
      ``dispositivo:sem_artigo``/``sem_diploma`` (incompleta);
    * ``tema:inventada:{repercussao|repetitivo|solto}``; ``vaga:incompleta[:sem_correspondencia|:unica]``.

    Todo caminho ganha o sufixo ``:amplo`` quando ``achado.forca < 1``; ver
    :func:`_marcar_amplo` e o docstring do módulo para ``detalhes["descartar"]``.
    ``Decisao.candidatos`` traz os ``id_canonico`` considerados (ordem de
    ``documento_id``); ``detalhes`` traz tribunal inferido, filtros aplicados,
    cadeia citada × própria e o que o árbitro fez.
    """
    familia = achado.familia
    if familia == "processo":
        decisao = _resolver_processo(achado, base, arbitro, contexto)
    elif familia == "sumula":
        decisao = _resolver_sumula(achado, base)
    elif familia == "dispositivo":
        decisao = _resolver_dispositivo(achado, base)
    elif familia == "tema":
        decisao = _resolver_tema(achado)
    elif familia == "vaga":
        decisao = _resolver_vaga(achado, base)
    else:  # tipos.Achado já validou a família; defesa contra enums futuros
        raise ValueError(f"família desconhecida: {familia!r}")
    decisao = _marcar_amplo(achado, decisao)
    log.debug("(%d,%d) %s → %s id=%s caminho=%s", achado.inicio, achado.fim, familia,
              decisao.classificacao, decisao.id_canonico, decisao.caminho)
    return decisao


__all__ = [
    "resolver", "extrair_processo", "CitacaoProcesso", "relacao_de_classe", "tribunal_incompativel",
    "uf_incompativel", "sao_duplicatas", "campos_da_vaga",
    "FORCA_MINIMA_SEM_CANDIDATO", "DIGITOS_CURTOS", "LETRAS_OCR_PARA_ARBITRO", "CABECALHO_DUPLICATA",
]
