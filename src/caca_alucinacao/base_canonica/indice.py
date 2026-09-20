"""Índice de números PRÓPRIOS da base canônica.

Cada acórdão identifica o *próprio* processo numa zona previsível do texto
(ver docs/04_analise_base.md):

* **STF** — ``<ÓRGÃO> <CLASSE> <número> <ESTADO POR EXTENSO> RELATOR``
  (``AG.REG. NA RECLAMAÇÃO 12.345 SÃO PAULO RELATOR : MIN. …``);
* **STJ** — ``<CLASSE> Nº <número> - <UF> (<AAAA/NNNNNNN-D>) RELATOR``
  (número + registro: dois identificadores);
* **TSE** — ``TRIBUNAL SUPERIOR ELEITORAL ACÓRDÃO <CLASSE> Nº <CNJ ou
  sequencial ( CNJ )> - CLASSE nn - <MUNICÍPIO> - <ESTADO> Relator``, com
  muito ruído de OCR, ou o layout PJe ``Número: <CNJ> Classe: <CLASSE>``;
* **STM** — ``… <CLASSE> Nº <CNJ>[/UF] RELATOR`` (extrato de ata);
* **TST** — fórmula ``… estes autos de <classe por extenso> nº TST-<PREFIXOS>-<CNJ>``
  (após a ementa, mediana ≈ 4 mil chars), cabeçalho ``PROCESSO Nº TST-…`` (layout
  novo) e rodapé ``PROCESSO Nº TST-…``.

O índice guarda, por registro, todos os identificadores próprios em dígitos
canônicos (:mod:`.digitos`), o formato, a cadeia de classe processual
(:mod:`.classes`), a UF e a posição. Números que só aparecem no **corpo** de
outros acórdãos (citações) **não** entram — essa é a armadilha "quem cita vs.
quem é".
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from .classes import cadeia_de_classes, classe_principal, uf_de_estado
from .digitos import (
    FORMATO_CNJ,
    FORMATO_REGISTRO,
    FORMATO_SEQUENCIAL,
    UFS,
    classificar_digitos,
)

log = logging.getLogger(__name__)

VERSAO_INDICE = 1

# --- expressões auxiliares --------------------------------------------------
_RE_RELATOR = re.compile(
    r"R\s?e\s?[lI1]\s?a\s?t\s?[oôó0]\s?r|RELAT[OÔ]R|REDATOR|REL\.|Redator", re.I
)
_RE_NUM_CONECTOR = r"(?:N\s?[ºo°‚]\s*|N\s+o\s+|N[ºo°]\.?\s*|n\s*\.?\s*[ºo°]\s*|Nº\s*|N\s+)?"
_RE_SPAN_NUMERO = r"(?P<numero>(?:\d[\d\.\-–—/⁄,\s]*\d|\d)(?![A-Za-zÀ-ÿ]))"

# STJ: "<CLASSE> Nº 1.234.567 - PR (2019/0123456-7)"
_RE_STJ = re.compile(
    r"(?P<classe>[A-Za-zÀ-ÿ\.\s]{2,160}?)\s*N[ºo°]\s*(?P<numero>\d[\d\.]*)\s*[-–—]?\s*"
    r"(?P<uf>[A-Z]{2})\s*\(\s*(?P<registro>\d{4}\s*[/⁄]\s*\d{7}\s*[-–]\s*\d)\s*\)"
)
# STF: "<CLASSE> 12.345 RIO DE JANEIRO RELATOR"
_RE_STF = re.compile(
    r"(?P<classe>(?:[A-ZÀ-Ü][A-ZÀ-Ü\.]*\s+){1,20}?)(?P<numero>\d{1,3}(?:\.\d{3}){0,2}|\d{1,7})"
    r"\s+(?P<estado>[A-ZÀ-Ü][A-ZÀ-Ü ]{1,30}?)\s*$"
)
# STM: "<CLASSE> Nº 7000123-45.2023.7.00.0000/DF" (ou "241-56.2016.7.11.0213 - DF")
_RE_STM = re.compile(
    r"(?P<classe>[A-ZÀ-Ü][A-ZÀ-Ü/\.\s]{2,90}?)\s*N[ºo°]\s*(?P<numero>\d{1,7}\s?-\s?\d{2}\.\d{4}\.7\.\d{2}\.\d{4})"
    r"(?:\s*[/\-–]\s*(?P<uf>[A-Z]{2})\b)?"
)
# TST: "TST-ED-E-ED-RR-1234-56.2011.5.21.0009" (prefixos com hífen, espaços tolerados)
_RE_TST_NUMERO = re.compile(
    r"TST\s*-\s*(?P<prefixo>(?:[A-Za-z]{1,12}\s*-\s*){1,8})(?P<numero>\d{1,7}\s?-\s?\d{2}\.\d{4}\.5\.\d{2}\.\d{4})"
)
_RE_TST_AUTOS = re.compile(r"autos\s+d[eoa]s?\s+(?P<classe>.{0,220}?)\s*n\s*\.?\s*[ºo°]?\s*TST\s*-", re.I | re.S)
_RE_TST_PROCESSO = re.compile(r"PROCESSO\s+N[ºo°]\s*TST\s*-", re.I)
# TSE: classe + conector + número; UF = último " - ESTADO" antes de Relator
_RE_TSE = re.compile(
    r"(?P<classe>[A-ZÀ-Üa-zà-ÿ][A-ZÀ-Üa-zà-ÿ0-9\.\s]{2,140}?)\s+" + _RE_NUM_CONECTOR + _RE_SPAN_NUMERO
    + r"(?P<paren>\s*\(\s*(?P<cnj2>\d{1,7}\s?-\s?\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\s*\))?"
)
_RE_TSE_PJE = re.compile(
    r"N[úu]mero:\s*(?P<numero>\d{1,7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\s*Classe:\s*(?P<classe>[A-ZÀ-Ü][A-ZÀ-Ü\s]{2,80}?)\s*(?=[A-ZÀ-Ü][a-zà-ÿ]|$)"
)
_RUIDO_TSE = re.compile(
    r"^.*?(?:AC[ÓO€]?R?D?[ÃA]?[OÕ]?\b|ACÓ\b|TRIBUNAL\s+SUPERIOR\s+ELEITORAL|PUBLICADO EM SESSÃO)\s*",
    re.S,
)
_RUIDO_STJ = re.compile(
    r"^(?:Superior Tribunal de Justiça|Revista Eletrônica de Jurisprudência|"
    r"Exportação de Auto Texto do Word para o Editor de Documentos do STJ)\s*"
)
_RUIDO_STM = re.compile(
    r"^.*?(?:Secretaria do Tribunal Pleno|EXTRATO DE ATA DA SESSÃO\s+\S+(?:\s+DE\s+[\d/]+(?:\s+A\s+[\d/]+)?)?|"
    r"SUPERIOR TRIBUNAL MILITAR|Poder Judiciário STM)\s*",
    re.S,
)


def regiao_de_identificacao(texto: str, tribunal: str | None) -> str:
    """Zona do texto onde o acórdão declara o PRÓPRIO número.

    STF/STJ/TSE/STM: do início até o primeiro ``RELATOR`` (teto 1.500 chars;
    no STM, se a classe + CNJ não aparece antes do ``RELATOR``, estende até o
    primeiro ``<CLASSE> Nº <CNJ>`` dentro de 3.000 chars — layout "extrato de
    ata" de 2017). TST: janela em torno da primeira fórmula ``autos de … nº
    TST-`` (ou do cabeçalho ``PROCESSO Nº TST-``); o rodapé é tratado à parte
    em :func:`extrair_identificadores_proprios`.
    """
    regioes = _regioes(texto, tribunal)
    ini, fim = regioes[0]
    return texto[ini:fim]


def _regioes(texto: str, tribunal: str | None) -> list[tuple[int, int]]:
    if tribunal == "TST":
        saida: list[tuple[int, int]] = []
        m = _RE_TST_AUTOS.search(texto)
        if m:
            saida.append((m.start(), min(len(texto), m.end() + 80)))
        m2 = _RE_TST_PROCESSO.search(texto, 0, 400)
        if m2:
            saida.append((m2.start(), min(len(texto), m2.end() + 80)))
        m3 = None
        for m3 in _RE_TST_PROCESSO.finditer(texto, max(0, len(texto) - 1200)):
            pass
        if m3:
            saida.append((m3.start(), min(len(texto), m3.end() + 80)))
        if not saida:
            saida.append((0, min(len(texto), 1500)))
        return sorted(saida)
    teto = 1500
    m = _RE_RELATOR.search(texto, 0, teto)
    fim = m.start() if m else min(len(texto), teto)
    if tribunal == "STM" and not _RE_STM.search(texto, 0, fim):
        # extrato de ata longo antes do número (layout 2017): procura classe + CNJ
        m_stm = _RE_STM.search(texto, 0, 3000)
        if m_stm:
            fim = m_stm.end() + 10
    return [(0, max(fim, 1))]


# ---------------------------------------------------------------------------
def extrair_identificadores_proprios(texto: str, tribunal: str | None) -> list[dict[str, Any]]:
    """Identificadores PRÓPRIOS do acórdão.

    Cada item: ``{"digitos", "formato", "classe_propria" (cadeia canônica
    separada por espaço), "classe_principal", "uf", "posicao", "bruto"}``,
    ordenados por posição e sem duplicatas de ``(digitos, classe_propria)``.
    Lista vazia quando o layout não é reconhecido (o chamador registra).
    """
    extrator = _EXTRATORES.get(tribunal or "")
    if extrator is None:
        return []
    itens = extrator(texto)
    vistos: set[tuple[str, str]] = set()
    saida: list[dict[str, Any]] = []
    for it in sorted(itens, key=lambda d: (d["posicao"], d["digitos"])):
        chave = (it["digitos"], it["classe_propria"])
        if chave in vistos or not it["digitos"]:
            continue
        vistos.add(chave)
        saida.append(it)
    return saida


def _item(digitos: str, formato: str, cadeia: list[str], uf: str | None, pos: int, bruto: str) -> dict[str, Any]:
    return {
        "digitos": digitos,
        "formato": formato,
        "classe_propria": " ".join(cadeia),
        "classe_principal": classe_principal(cadeia),
        "uf": uf,
        "posicao": pos,
        "bruto": bruto.strip(),
    }


def _digitos_de_span(span: str) -> tuple[str, str, int]:
    """Dígitos canônicos de um span numérico já isolado (sem UF)."""
    dig = "".join(c for c in span if c.isdigit())
    canon, formato = classificar_digitos(dig)
    return canon, formato, len(dig)


def _extrair_stf(texto: str) -> list[dict[str, Any]]:
    regiao = regiao_de_identificacao(texto, "STF")
    saida = []
    for m in _RE_STF.finditer(regiao):
        classe = m.group("classe")
        cadeia = cadeia_de_classes(classe)
        if not cadeia:
            continue
        canon, formato, _ = _digitos_de_span(m.group("numero"))
        uf = uf_de_estado(m.group("estado"))
        saida.append(_item(canon, formato, cadeia, uf, m.start("numero"), m.group(0)))
        break  # só a primeira linha de classe
    return saida


def _extrair_stj(texto: str) -> list[dict[str, Any]]:
    regiao = regiao_de_identificacao(texto, "STJ")
    m = _RE_STJ.search(regiao)
    if not m:
        return []
    classe = _RUIDO_STJ.sub("", m.group("classe").strip())
    cadeia = cadeia_de_classes(classe)
    uf = m.group("uf") if m.group("uf") in UFS else None
    canon, formato, _ = _digitos_de_span(m.group("numero"))
    itens = [_item(canon, formato, cadeia, uf, m.start("numero"), m.group(0))]
    reg = "".join(c for c in m.group("registro") if c.isdigit())
    if len(reg) == 12:
        itens.append(_item(reg, FORMATO_REGISTRO, cadeia, uf, m.start("registro"), m.group("registro")))
    return itens


def _extrair_stm(texto: str) -> list[dict[str, Any]]:
    regiao = regiao_de_identificacao(texto, "STM")
    saida = []
    for m in _RE_STM.finditer(regiao):
        classe = _RUIDO_STM.sub("", m.group("classe").strip())
        cadeia = cadeia_de_classes(classe)
        if not cadeia:
            continue
        canon, formato, _ = _digitos_de_span(m.group("numero"))
        uf = m.group("uf") if m.group("uf") in UFS else None
        if uf is None:
            # layout "Secretaria do Tribunal Pleno": a UF só aparece na 1ª menção
            # do número no corpo ("… Agravo Interno nº 7000456-78.2021.7.00.0000/DF")
            seq = re.escape(m.group("numero")[:7].split("-")[0])
            m_uf = re.search(seq + r"\s?-\s?\d{2}\.\d{4}\.7\.\d{2}\.\d{4}\s*/\s*([A-Z]{2})\b", texto)
            if m_uf and m_uf.group(1) in UFS:
                uf = m_uf.group(1)
        saida.append(_item(canon, formato, cadeia, uf, m.start("numero"), m.group(0)))
        break
    return saida


def _extrair_tst(texto: str) -> list[dict[str, Any]]:
    saida = []
    for ini, fim in _regioes(texto, "TST"):
        regiao = texto[ini:fim]
        for m in _RE_TST_NUMERO.finditer(regiao):
            cadeia = cadeia_de_classes("TST-" + m.group("prefixo"))
            canon, formato, _ = _digitos_de_span(m.group("numero"))
            saida.append(_item(canon, formato, cadeia, None, ini + m.start("numero"), m.group(0)))
            break
    return saida


def _extrair_tse(texto: str) -> list[dict[str, Any]]:
    regiao = regiao_de_identificacao(texto, "TSE")
    m_pje = _RE_TSE_PJE.search(regiao)
    if m_pje:
        cadeia = cadeia_de_classes(m_pje.group("classe"))
        canon, formato, _ = _digitos_de_span(m_pje.group("numero"))
        return [_item(canon, formato, cadeia, None, m_pje.start("numero"), m_pje.group(0))]
    saida: list[dict[str, Any]] = []
    for m in _RE_TSE.finditer(regiao):
        classe_txt = _RUIDO_TSE.sub("", m.group("classe"))
        cadeia = cadeia_de_classes(classe_txt)
        span = m.group("numero")
        canon, formato, n = _digitos_de_span(span)
        if n < 2:
            continue
        if not cadeia and formato != FORMATO_CNJ:
            continue  # "CLASSE 32" e afins: número sem classe só vale se for CNJ
        uf = _uf_tse(regiao[m.end():])
        saida.append(_item(canon, formato, cadeia, uf, m.start("numero"), m.group(0)))
        if formato == FORMATO_CNJ and n < 16:
            # OCR engoliu os dígitos verificadores ("612- 2012 6 08 0021"): o corpo
            # repete o número completo dezenas de vezes → acrescenta a forma íntegra
            reparo = _reparar_cnj_curto(texto, canon)
            if reparo:
                saida.append(_item(reparo[0], FORMATO_CNJ, cadeia, uf, reparo[1], "reparado pelo corpo"))
        if m.group("cnj2"):
            canon2, formato2, _ = _digitos_de_span(m.group("cnj2"))
            saida.append(_item(canon2, formato2, cadeia, uf, m.start("cnj2"), m.group("cnj2")))
        break
    return saida


_RE_CNJ_CORPO = re.compile(r"(\d{1,7})\s?-\s?(\d{2})\.\s?(\d{4})\.(\d)\.(\d{2})\.(\d{4})")


def _reparar_cnj_curto(texto: str, canon: str) -> tuple[str, int] | None:
    """CNJ com < 16 dígitos no cabeçalho (OCR): procura no corpo o CNJ bem formado
    com o mesmo sufixo AAAA.J.TR.OOOO e o mesmo início; exige ≥ 3 ocorrências."""
    sufixo = canon[-11:]
    inicio = canon.lstrip("0")[:3]
    contagem: dict[str, int] = {}
    posicao: dict[str, int] = {}
    for m in _RE_CNJ_CORPO.finditer(texto):
        completo = "".join(m.groups()).zfill(20)
        if completo[-11:] == sufixo and completo != canon and completo.lstrip("0").startswith(inicio):
            contagem[completo] = contagem.get(completo, 0) + 1
            posicao.setdefault(completo, m.start())
    if not contagem:
        return None
    melhor = sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if melhor[1] < 3:
        return None
    return melhor[0], posicao[melhor[0]]


def _uf_tse(resto: str) -> str | None:
    """UF do TSE: último segmento " - ESTADO" entre o número e o fim da região."""
    resto = re.sub(r"CLASSE\s*\d*[A-Z]{0,3}", " ", resto)
    partes = [p.strip(" .") for p in re.split(r"[-–—]", resto) if p.strip(" .")]
    for parte in reversed(partes):
        uf = uf_de_estado(parte)
        if uf:
            return uf
    # sem travessão entre município e estado ("RIBEIRÃO PRETO SÃO PAULO"): sufixos de 1 a 4 palavras
    if partes:
        palavras = partes[-1].split()
        for k in range(1, min(4, len(palavras)) + 1):
            uf = uf_de_estado(" ".join(palavras[-k:]))
            if uf:
                return uf
    return None


_EXTRATORES = {
    "STF": _extrair_stf,
    "STJ": _extrair_stj,
    "STM": _extrair_stm,
    "TSE": _extrair_tse,
    "TST": _extrair_tst,
}


# ---------------------------------------------------------------------------
def construir_indice(caminho_db: Path | str) -> dict[str, Any]:
    """Lê o SQLite e devolve o índice serializável em JSON.

    Estrutura::

        {"versao": 1,
         "registros": {documento_id: {"id_canonico", "tribunal", "ano", "relator",
                                      "natureza", "tipo", "texto_len",
                                      "classe_propria", "identificadores": [...],
                                      "cabecalho"}},
         "por_digitos": {digitos: [documento_id, ...]},   # só números PRÓPRIOS
         "sem_identificador": [documento_id, ...]}
    """
    from .normativos import derivar_normativos  # import tardio: evita ciclo

    con = sqlite3.connect(str(caminho_db))
    try:
        linhas = con.execute(
            "SELECT documento_id, id, tribunal, ano, relator, natureza, tipo, texto, texto_len "
            "FROM documentos ORDER BY documento_id"
        ).fetchall()
    finally:
        con.close()

    registros: dict[str, dict[str, Any]] = {}
    por_digitos: dict[str, list[str]] = {}
    sem_identificador: list[str] = []
    for documento_id, id_canonico, tribunal, ano, relator, natureza, tipo, texto, texto_len in linhas:
        idents: list[dict[str, Any]] = []
        if natureza == "acordao":
            idents = extrair_identificadores_proprios(texto, tribunal)
            if not idents:
                sem_identificador.append(documento_id)
                log.warning("sem identificador próprio: %s (%s)", documento_id, tribunal)
        registros[documento_id] = {
            "id_canonico": int(id_canonico),
            "tribunal": tribunal,
            "ano": ano,
            "relator": relator,
            "natureza": natureza,
            "tipo": tipo,
            "texto_len": int(texto_len),
            "classe_propria": idents[0]["classe_propria"] if idents else None,
            "identificadores": idents,
            "cabecalho": texto[:600],
        }
        for it in idents:
            por_digitos.setdefault(it["digitos"], [])
            if documento_id not in por_digitos[it["digitos"]]:
                por_digitos[it["digitos"]].append(documento_id)
    for lista in por_digitos.values():
        lista.sort()
    normativos = derivar_normativos(
        [(d, r["natureza"], r["tribunal"], r["cabecalho"]) for d, r in registros.items() if r["natureza"] != "acordao"]
    )
    return {
        "versao": VERSAO_INDICE,
        "banco": impressao_do_banco(caminho_db),
        "registros": registros,
        "por_digitos": dict(sorted(por_digitos.items())),
        "sem_identificador": sorted(sem_identificador),
        "normativos": normativos,
    }


def impressao_do_banco(caminho_db: Path | str) -> dict[str, Any]:
    """``{"sha256", "bytes"}`` do arquivo SQLite: gravada no índice para detectar um banco
    redistribuído com outro conteúdo (rodada 3, R3e-07). Vazio se o arquivo não existir."""
    p = Path(caminho_db)
    try:
        bruto = p.read_bytes()
    except OSError:
        return {}
    return {"sha256": hashlib.sha256(bruto).hexdigest(), "bytes": len(bruto)}


def indice_corresponde_ao_banco(indice: dict[str, Any], caminho_db: Path | str) -> bool | None:
    """``True``/``False`` se o índice traz a impressão do banco e ela bate/não bate; ``None`` se
    o índice (versão antiga) ou o banco não permitem comparar."""
    gravada = indice.get("banco") or {}
    if not gravada.get("sha256"):
        return None
    atual = impressao_do_banco(caminho_db)
    if not atual:
        return None
    return atual["sha256"] == gravada["sha256"]


def salvar_indice(indice: dict[str, Any], caminho: Path | str) -> None:
    Path(caminho).write_text(
        json.dumps(indice, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )


def carregar_indice(caminho: Path | str) -> dict[str, Any]:
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if dados.get("versao") != VERSAO_INDICE:
        raise ValueError(f"índice em versão {dados.get('versao')}; esperado {VERSAO_INDICE}")
    return dados


def estatisticas(indice: dict[str, Any]) -> dict[str, Any]:
    """Contagens para o script de construção (por tribunal e formato)."""
    por_tribunal: dict[str, dict[str, int]] = {}
    for r in indice["registros"].values():
        if r["natureza"] != "acordao":
            continue
        t = por_tribunal.setdefault(r["tribunal"], {"registros": 0, "sem_identificador": 0,
                                                    FORMATO_SEQUENCIAL: 0, FORMATO_CNJ: 0,
                                                    FORMATO_REGISTRO: 0, "com_uf": 0})
        t["registros"] += 1
        if not r["identificadores"]:
            t["sem_identificador"] += 1
        for it in r["identificadores"]:
            t[it["formato"]] = t.get(it["formato"], 0) + 1
        if any(it["uf"] for it in r["identificadores"]):
            t["com_uf"] += 1
    ambiguos = {d: docs for d, docs in indice["por_digitos"].items() if len(docs) > 1}
    return {
        "por_tribunal": por_tribunal,
        "chaves": len(indice["por_digitos"]),
        "chaves_ambiguas": len(ambiguos),
        "sem_identificador": len(indice["sem_identificador"]),
    }


__all__ = [
    "VERSAO_INDICE",
    "regiao_de_identificacao",
    "extrair_identificadores_proprios",
    "construir_indice",
    "salvar_indice",
    "carregar_indice",
    "estatisticas",
]
