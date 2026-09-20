"""Família ``processo``: cadeia de classes + conector + número (+ UF).

Dois padrões (docs/03 §2.1–§2.5, §9.1):

* **estrito** (``regex:processo``, força 1,0): a cadeia de classes é uma
  alternância fechada de siglas e nomes por extenso conhecidos
  (:data:`padroes.SIGLAS`, :data:`padroes.EXTENSOS`), com prefixos encadeados
  por ``no/na/nos`` ou hífen, ordinais, ``processo nº`` e ``TST-``; o número
  começa por dígito ASCII e aceita o ruído medido (letras de OCR coladas,
  pontos, hífens, espaços e quebras só quando seguidos de dígito); a UF é da
  lista fechada e entra com o separador (e o ``)`` quando abriu ``(``);
* **amplo** (``regex:processo:amplo``, força 0,5): sigla desconhecida em caixa
  alta/CamelCase (2–8 letras, com pontos opcionais) ou ``Processo``/``Autos``
  + conector + número ≥ 4 dígitos. Existe para recall no conjunto cego; a
  resolução e o árbitro confirmam. Nunca dispara sobre UFs, tribunais ou
  palavras de cabeçalho (``OAB``, ``CNPJ``…), nem sobre ``NNN/AAAA``.

Armadilhas evitadas (uma por regra):

* ``<Classe> do STF, de 2023, Rel. Min.`` é ``vaga``: aqui o número precisa
  seguir a cadeia diretamente (só espaço, hífen ou conector) — ``de 2023`` não
  é número; e a fusão dá precedência à ``vaga``;
* ``- SP`` nunca é engolido pelo número: um grupo depois de espaço só abre com
  dígito, e um grupo depois de pontuação precisa conter dígito;
* ``AR 2019``/``RE 2020`` (sigla de 2 letras + ano sem conector, sem pontos e
  sem UF) é descartado: no dev todo número curto de 4 dígitos vem com pontos ou
  conector; com UF (``AR 2019/SP``) a forma é de processo e fica;
* número de 2–3 dígitos sem conector só fica com UF, nome por extenso (≥ 2
  palavras) ou classe de numeração curta (``ADPF 684``, ``SL 12``);
* ``12/03/2022`` depois do número: o grupo separado por espaço não pode ser
  seguido de ``/dígito``;
* o artigo anterior (``o``, ``no``, ``na``) fica fora porque a cadeia começa
  numa sigla/nome com maiúscula e há guarda de fronteira à esquerda.
"""
from __future__ import annotations

import logging
import re

from ..normalizacao import (
    CONFUSOES,
    UFS,
    cadeia_de_classes,
    chave_textual,
    classe_principal,
    digitos_do_identificador,
    formato_de,
    inferir_tribunal,
)
from ..tipos import Achado
from . import padroes as P

log = logging.getLogger(__name__)

#: Fronteira à esquerda: o span não começa no meio de uma palavra nem depois de
#: ``/`` (``OAB/MG 123456``) — e nunca depois de letra colada (``EAREsp`` ≠ ``AREsp``).
#: Exceção (revisão rodada 3, R3-09): ``/`` precedido de uma sigla de tribunal (``STJ/REsp
#: 1.234.567/SP``, ``STF/Rcl 12.345``) — o prefixo fica FORA do span (como o artigo) e vira
#: tribunal explícito em ``_montar`` (``tribunal_fonte = "explicito"``).
_ESQUERDA = r"(?:(?<![A-Za-zÀ-ÿ0-9/])|(?<=STF/)|(?<=STJ/)|(?<=TSE/)|(?<=TST/)|(?<=STM/))"
_RE_PREFIXO_TRIBUNAL = re.compile(r"(?<![A-Za-zÀ-ÿ])(STF|STJ|TSE|TST|STM)/$")
#: O que pode existir entre a cadeia e o número: hífen (TST/TSE), conector com
#: brancos (``nº\n``, ``n.\xa0``, ``Nº  ``, ``sob o nº``), dois-pontos (``REsp: 1.234.567``,
#: estilo de ementa; revisão rodada 2, R4-05) ou só brancos (``RESP\xa01234567``).
_ANTES_NUMERO = (
    rf"(?:\s{{0,2}}-\s{{0,2}}|\s{{0,3}}(?:sob{P.S}o{P.S})?(?P<conector>{P.CONECTOR})\s{{0,4}}"
    rf"|\s{{0,2}}:\s{{0,3}}|\s{{1,4}})"
)
#: Tribunal entre a cadeia e o conector (``Reclamação do STF nº 12.345``; revisão rodada 2,
#: R4-15): entra no span e é tribunal explícito.
#: Também entre parênteses (``Apelação (STM) nº 7000011-…``; revisão rodada 3, R3-09).
_TRIBUNAL_MEIO = (
    rf"(?:{P.S}{P.P_DO}{P.S}(?P<trib_meio>{P.TRIBUNAL_SIGLA})(?![A-Za-zÀ-ÿ])"
    rf"|\s{{0,2}}\(\s{{0,2}}(?P<trib_par>{P.TRIBUNAL_SIGLA})\s{{0,2}}\))?"
)
#: Registro do STJ depois da UF (``REsp 1.234.567 - PR (2019/0123456-7)``; docs/04 h.4,
#: revisão rodada 2, R4-07): entra no span; a resolução o usa como ``registro_secundario``.
_REGISTRO_APOS_UF = rf"(?:\s{{0,2}}\(\s{{0,2}}(?P<registro>{P.NUMERO_REGISTRO})\s{{0,2}}\))?"
#: UF colada à sigla, antes do conector (``REsp/SP nº 1.234.567``; forma rara, revisão R2-10).
_UF_ANTES = rf"(?:\s{{0,2}}/\s{{0,2}}(?P<uf_antes>{P.UF})(?![A-Za-zÀ-ÿ0-9]))?"

#: Sufixo de incidente no estilo do STF, DEPOIS do número (``RE 123.456 AgR/SP``,
#: ``HC 123456 MC/SP``, ``ADI 1.234 ED``; revisão R1-12-a): entra no span e na cadeia
#: como prefixo (``AGR RE``), que é a forma da base.
_SUFIXO_INCIDENTE = "(?:" + "|".join(
    P.regex_sigla(x, ponto_final=False) for x in ("AgRg", "AgR", "EDcl", "EDv", "ED", "MC", "QO", "Ref", "PExt", "Emb")
) + ")"

RE_PROCESSO = re.compile(
    rf"""
    {_ESQUERDA}
    (?P<prefixo>{P.PREFIXO_PROCESSO})?
    (?P<tst>{P.PREFIXO_TST})?
    (?P<cadeia>{P.CADEIA}){_UF_ANTES}{_TRIBUNAL_MEIO}
    {_ANTES_NUMERO}
    (?P<numero>{P.NUMERO_REGISTRO}|{P.NUMERO})
    (?:(?:\s{{1,2}}|\s{{0,2}}-\s{{0,2}})(?P<sufixo>{_SUFIXO_INCIDENTE})(?![A-Za-zÀ-ÿ0-9]))?
    (?P<ufbloco>{P.UF_COM_SEPARADOR})?{_REGISTRO_APOS_UF}
    """,
    re.VERBOSE,
)

#: Sigla genérica do padrão amplo: 2–8 letras começando por maiúscula, com pontos
#: opcionais (``R.O.M.S.``); validada em código (≥ 2 maiúsculas ou toda em caixa
#: alta com ≤ 6 letras; fora de :data:`_NAO_SIGLAS`).
_SIGLA_GENERICA = r"(?:[A-Z]\.?(?:[A-Za-z]\.?){1,7})"
_PALAVRA_PROCESSO = r"(?:[Pp]rocessos?|PROCESSOS?|[Aa]utos|AUTOS|[Pp]roc\.)"
RE_PROCESSO_AMPLO = re.compile(
    rf"""
    {_ESQUERDA}
    (?P<cadeia>
        (?P<palavra>{_PALAVRA_PROCESSO})(?![A-Za-zÀ-ÿ])
      | (?:(?:{P.ORDINAL}\s{{1,4}})?(?:{P.ELEMENTO}{P.LIGACAO}|{P.SIGLA_HIFEN}\s{{0,2}}-\s{{0,2}}){{0,6}})
        (?P<sigla>{_SIGLA_GENERICA})(?![A-Za-zÀ-ÿ])
    )
    {_ANTES_NUMERO}
    (?P<numero>{P.NUMERO_REGISTRO}|{P.NUMERO})
    (?P<ufbloco>{P.UF_COM_SEPARADOR})?
    """,
    re.VERBOSE,
)

#: Palavras em caixa alta/CamelCase que nunca são classe processual.
_NAO_SIGLAS: frozenset[str] = frozenset({
    "STF", "STJ", "TSE", "TST", "STM", "TRF", "TRT", "TRE", "TJ", "TJSP", "TJRJ", "TJMG", "TJRS",
    "OAB", "CNPJ", "CPF", "CEP", "CNJ", "DJE", "DJU", "DJ", "DOU", "DOE", "PARECER", "MEMORIAL",
    "PROTOCOLO", "OFICIO", "PORTARIA", "RESOLUCAO", "DECRETO", "LEI", "ART", "ARTS", "ARTIGO",
    "TEMA", "SUMULA", "ITEM", "ANEXO", "FLS", "FL", "PAG", "PAGS", "VOL", "TOMO", "CAP", "INC",
    "MP", "MPF", "MPE", "MPM", "MPT", "PGR", "DPU", "AGU", "PFN", "INSS", "FGTS", "PIS", "COFINS",
    "ICMS", "IPI", "IRPJ", "ISS", "IPTU", "ITBI", "CDA", "NF", "NFE", "CT", "CTPS", "RG", "CRM",
    "CREA", "CNH", "SUS", "IBGE", "IPCA", "INPC", "IGP", "IGPM", "SELIC", "CDI", "TR", "URV",
    "UFIR", "UPC", "BACEN", "BCB", "CVM", "CADE", "ANS", "ANP", "ANEEL", "ANATEL", "ANVISA",
    "CLT", "CPC", "CPP", "CDC", "CTN", "CTB", "ECA", "LEP", "CRFB", "NCPC", "CPM", "CPPM",
    "SV", "OJ", "PN", "IN", "PGE", "PGM", "SEI", "NUP", "PAD", "TCU", "TCE", "TCM", "CGU",
    "DOC", "DOCS", "ID", "IDS", "REF", "OBS", "PS", "NB", "EX", "EXMO", "EXMA", "DR", "DRA",
    "MM", "MMA", "VV", "VVA", "SA", "SS", "LTDA", "ME", "EPP", "EIRELI", "CIA", "CIAS",
})


def _e_sigla_plausivel(sigla: str) -> bool:
    """Sigla desconhecida aceitável pelo padrão amplo.

    ≥ 2 maiúsculas em CamelCase (``ROMS``, ``RvCr``, ``AgRgAI``) ou toda em caixa
    alta com 2–6 letras; nunca UF, tribunal nem palavra de :data:`_NAO_SIGLAS`.
    """
    letras = sigla.replace(".", "")
    chave = letras.upper()
    if chave in UFS or chave in _NAO_SIGLAS:
        return False
    n_maius = sum(c.isupper() for c in letras)
    if letras.isupper():
        return 2 <= len(letras) <= 6
    return n_maius >= 2 and 3 <= len(letras) <= 8


_RE_ANO_SOLTO = re.compile(r"^(?:19|20)\d{2}$")
#: Sigla no plural ao fim da cadeia (``REsps``, ``AREsps``, ``RRs``): abre uma enumeração.
_RE_SIGLA_PLURAL = re.compile(r"[A-Z][A-Za-z]*[A-Za-z]s$")
#: Nomes por extenso que terminam em ``s`` no SINGULAR (``Habeas Corpus``, ``Embargos``): não abrem
#: enumeração (rodada 4, R6-07 — a continuação sem UF exige um plural verdadeiro).
_EXTENSOS_SINGULAR_EM_S = frozenset(n for n in P.EXTENSOS if n.endswith("s"))
#: Cadeia com nome por extenso (≥ 2 palavras com ≥ 3 minúsculas): ``Cautelar Inominada Criminal``.
#: O lookbehind ancora o início da palavra: sem ele a busca é quadrática numa corrida longa de
#: minúsculas (rodada 4, R3q-04).
_RE_NOME_EXTENSO = re.compile(r"(?<![a-zà-ú])[a-zà-ú]{3,}\S*\s+\S*[a-zà-ú]{3,}")


def _e_plural(cadeia_sup: str) -> bool:
    """``REsps``/``Rcls``/``Recursos Especiais``/``Reclamações`` → ``True``; ``Habeas Corpus``/``REsp`` → ``False``."""
    if not _RE_SIGLA_PLURAL.search(cadeia_sup):
        return False
    chave = re.sub(r"[.\-]", " ", chave_textual(cadeia_sup))
    chave = " ".join(chave.split())
    ultimo = chave.split()[-1] if chave else ""
    return not any(chave.endswith(n) and (chave == n or chave.endswith(" " + n)) for n in _EXTENSOS_SINGULAR_EM_S
                   if n.split()[-1] == ultimo)
#: Classes cuja numeração corrente tem 2–4 dígitos: um número de 2–3 dígitos sem conector
#: (``ADPF 684``, ``ADI 583``, ``SL 1.234``) ainda é processo (revisão R2-08).
CLASSES_NUMERACAO_CURTA: frozenset[str] = frozenset({
    "ADPF", "ADC", "ADI", "ADO", "SL", "SS", "SLS", "STA", "PET", "RP", "AC", "MS", "CAUTINOM", "PC", "LT",
    "AIJE", "RCED", "CJ", "CP", "RDI", "EI", "RSE", "INQ", "EXT", "ACO",
})
#: Letra de OCR sozinha entre separadores (``2016 S 00``, ``2016.S.00``): o segmento J
#: do CNJ tem 1 dígito e ``normalizacao.nucleos`` fecha o núcleo num grupo sem dígito.
_RE_SEGMENTO_DE_UMA_LETRA = re.compile(rf"(?<=[\s.\-–])([{P.LETRAS_OCR}])(?=[\s.\-–])")


def _segmentos_de_uma_letra(numero: str) -> str:
    """``"24290-50 2016 S 00 0000"`` → ``"24290-50 2016 5 00 0000"`` (só segmentos de 1 letra)."""
    return _RE_SEGMENTO_DE_UMA_LETRA.sub(lambda m: CONFUSOES.get(m.group(1), m.group(1)), numero)


#: Substantivo de ato normativo/administrativo imediatamente antes de uma sigla de 2–3 letras
#: (``Portaria MS nº 2.048/2002``, ``Resolução CC nº 12/2019``, ``Ofício AR nº 1.234/2020``,
#: ``Instrução Normativa RE nº 10/2016``, ``Ato CC nº 1, de 2015``; revisão rodada 3, R3-01): a
#: sigla é do órgão emissor, não classe processual.
_RE_ATO_ANTES = re.compile(
    r"(?<![A-Za-zÀ-ÿ])(?:[Pp]ortarias?|[Rr]esolu[çc](?:[ãa]o|[õo]es)|[Oo]f[íi]cios?|[Dd]elibera[çc](?:[ãa]o|[õo]es)|[Cc]ircular(?:es)?"
    r"|[Ii]nstru[çc][ãa]o\s{1,2}[Nn]ormativa|[Ii]nstru[çc][õo]es\s{1,2}[Nn]ormativas|IN|[Oo]rdem\s{1,2}de\s{1,2}[Ss]ervi[çc]o|OS"
    r"|[Mm]emorandos?|[Aa]tos?|[Pp]rovimentos?|[Cc]omunicados?|[Aa]visos?|[Ee]ditais|[Ee]dital|[Dd]espachos?|[Nn]otas?\s{1,2}[Tt][ée]cnicas?"
    r"|[Rr]ecomenda[çc](?:[ãa]o|[õo]es)|[Oo]rienta[çc](?:[ãa]o|[õo]es)|[Dd]ecretos?|[Nn]ormas?|[Rr]egulamentos?|[Cc]onsultas?"
    r"|PORTARIAS?|RESOLU[ÇC](?:[ÃA]O|[ÕO]ES)|OF[ÍI]CIOS?|CIRCULAR(?:ES)?|INSTRU[ÇC][ÃA]O\s{1,2}NORMATIVA|MEMORANDOS?|ATOS?|PROVIMENTOS?)"
    r"\s{1,3}$")
#: Marca de ato normativo DEPOIS do número: ``/AAAA`` colado (``2.048/2002``) ou ``, de AAAA``.
_RE_ATO_DEPOIS = re.compile(r"^\s{0,2}/\s{0,2}(?:19|20)\d{2}(?![\d])|^,\s{1,2}de\s{1,2}(?:19|20)\d{2}(?![\d])")
#: Fórmula de relatoria logo depois de ``, de AAAA`` (``Rcl 12.345, de 2026, Rel. Min. X``): é a versão
#: numerada do molde D das vagas — citação, nunca ato normativo (rodada 4, R4-02/R6-01).
_RE_RELATORIA_APOS_ANO = re.compile(
    rf"^,\s{{1,2}}de\s{{1,2}}(?:19|20)\d{{2}}\s{{0,2}}[,;(]\s{{0,3}}(?:{P.RELATORIA}|{P.P_MIN}\s)")
#: Siglas de 2–3 letras que também nomeiam órgãos emissores de atos (``MS`` = Ministério da Saúde,
#: ``CC`` = Casa Civil, ``AR``, ``RE``, ``SS``, ``CP``, ``AI``, ``PC``, ``AC``…): só nelas ``, de AAAA``
#: sozinho é indício de ato normativo; ``Rcl``/``RHC``/``HC``/``RMS`` nunca são órgão (R6-01).
_SIGLAS_DE_ORGAO: frozenset[str] = frozenset({
    "MS", "CC", "AR", "RE", "SS", "SL", "CP", "AI", "PC", "AC", "AP", "RO", "EI", "CJ", "LT", "RP", "STA", "SLS",
})
#: Dígitos a partir dos quais um número seguido de ``, de AAAA`` é sempre processo (``AR 1.234, de
#: 2015``, ``MS 12.345, de 2019``): atos numerados têm ≤ 3 dígitos na prática (R4-02).
_MAX_DIGITOS_ATO = 3
#: Contexto bancário para ``Ag.`` (agência): ``conta``, ``agência``, ``Banco``, ``c/c`` a ≤ 40 chars.
_RE_BANCO = re.compile(r"(?:\bconta\b|\bag[êe]ncia\b|\bbanco\b|\bc/c\b|\bcorrente\b|\bdep[óo]sito\b)", re.I)
_RE_SIGLA_NUA = re.compile(r"^[A-Za-z]{2,3}\.?$")
#: Classes cuja numeração na base é exclusivamente CNJ (TST: 198/198 identificadores).
_SO_CNJ: frozenset[str] = frozenset({"RR", "AIRR", "ARR", "RRAG", "ROT", "AG"})
_MIN_DIGITOS_CNJ = 13


def _e_distrator_estrito(texto: str, m: re.Match[str], cadeia_sup: str, principal: str,
                         digitos: str, uf: str, conector: str | None) -> bool:
    """Regras negativas do padrão ESTRITO (revisão rodada 3, R3-01/R3-02).

    Só para uma sigla NUA de 2–3 letras (sem prefixo, ligação, nome por extenso nem UF):

    * precedida imediatamente por substantivo de ato normativo (``Portaria MS nº``);
    * número seguido de ``/AAAA`` (``MS nº 2.048/2002``) ou, SEM conector, com ≤ 3 dígitos, sigla
      de órgão (:data:`_SIGLAS_DE_ORGAO`) e sem fórmula de relatoria depois, de ``, de AAAA``
      (rodada 4, R4-02/R6-01: ``Rcl 12.345, de 2024, Rel. Min. X``, ``AR 1.234, de 2015`` e
      ``MS nº 123, de 2015`` são processos; ``Ato CC nº 1, de 2015`` cai pelo substantivo);
    * classe só citada por CNJ na base (família TST e ``Ag``) com número de < 13 dígitos e sem
      ``TST-``/``processo nº`` (``Ag. 1234`` de agência bancária), ou ``Ag`` em contexto bancário.

    Cadeias com prefixo (``AgRg no MS``), UF (``MS 12.345/DF``) ou nome por extenso nunca caem aqui.
    """
    if uf or m.groupdict().get("tst") or m.groupdict().get("prefixo"):
        return False
    inicio, fim = m.start(), m.end()
    if principal in _SO_CNJ and digitos and len(digitos) < _MIN_DIGITOS_CNJ:
        return True
    if principal == "AG" and _RE_BANCO.search(texto[max(0, inicio - 40):fim + 40]):
        return True
    if not _RE_SIGLA_NUA.match(cadeia_sup):
        return False
    if _RE_ATO_ANTES.search(texto[max(0, inicio - 30):inicio]):
        return True
    depois = texto[fim:fim + 12]
    if _RE_ATO_DEPOIS.match(depois):
        if depois.lstrip().startswith("/"):
            return True
        if (len(digitos) <= _MAX_DIGITOS_ATO and principal in _SIGLAS_DE_ORGAO and not conector
                and not _RE_RELATORIA_APOS_ANO.match(texto[fim:fim + 60])):
            return True
    return False


def _montar(texto: str, m: re.Match[str], origem: str, forca: float) -> Achado | None:
    """Valida o casamento e monta o ``Achado`` com todos os campos de ``dados``."""
    numero = m.group("numero")
    digitos = digitos_do_identificador(_segmentos_de_uma_letra(numero))
    n_digitos = len(digitos)
    conector = m.groupdict().get("conector")
    uf = P.uf_canonica(m.group("uf") or m.group("uf_par") or m.groupdict().get("uf_colada")
                       or (m.groupdict().get("uf_antes") or ""))
    cadeia_sup = m.group("cadeia")
    sufixo = m.groupdict().get("sufixo")
    cadeia = cadeia_de_classes(f"{sufixo} no {cadeia_sup}" if sufixo else cadeia_sup)
    principal = classe_principal(cadeia) or ""
    if not digitos:
        # núcleo ambíguo (letras confundíveis que a normalização se recusa a converter:
        # ``1.OO1.140``, ``G2.416``, ``7.OO.0000``): o achado vale se há ≥ 4 caracteres
        # numéricos; a chave fica vazia e a resolução tenta as conversões alternativas
        # (``chaves_alternativas``) — nunca uma chave parcial (revisão R2-01/R1-02).
        if sum(c.isdigit() or c in CONFUSOES for c in numero) < 4 or not any(c.isdigit() for c in numero):
            return None
    elif n_digitos < 4 and not (conector and n_digitos >= 2):
        # 2–3 dígitos só com conector ("Nº 42"), UF explícita ("ADPF 684/DF" não existe, mas
        # "Cautelar Inominada Criminal 87/DF" sim) ou classe de numeração curta (ADPF, ADC…)
        # — revisões R1-07/R2-08. A resolução protege chaves curtas (``curto_classe_divergente``).
        if not (n_digitos >= 2 and (uf or principal in CLASSES_NUMERACAO_CURTA
                                    or _RE_NOME_EXTENSO.search(cadeia_sup))):
            return None
    # sigla de 2–3 letras + ano de 4 dígitos sem conector, sem pontos e SEM UF: "AR 2019" é data;
    # "AR 2019/SP" é processo (revisão R1-03)
    if (_RE_ANO_SOLTO.match(numero) and not conector and not uf
            and len(cadeia_sup.replace(".", "")) <= 3):
        return None
    inicio, fim = m.start(), m.end()
    trecho = texto[inicio:fim]
    formato = formato_de(digitos) if digitos else "outro"
    tst = bool(m.groupdict().get("tst"))
    trib_meio = P.sigla_tribunal_canonica(m.groupdict().get("trib_meio") or m.groupdict().get("trib_par") or "")
    if not trib_meio and not tst:
        # ``STJ/REsp …``: prefixo de tribunal colado por ``/`` logo antes do span (fora dele; R3-09)
        antes = _RE_PREFIXO_TRIBUNAL.search(texto[max(0, m.start() - 4):m.start()])
        if antes:
            trib_meio = antes.group(1)
    tribunal = "TST" if tst else trib_meio or (inferir_tribunal(cadeia, uf or None, digitos, formato) or "")
    if not tst and not trib_meio and _e_distrator_estrito(texto, m, cadeia_sup, principal, digitos, uf, conector):
        return None
    # de onde veio o tribunal: só ``explicito`` (prefixo TST-, ``Reclamação do STF nº``) é
    # eliminatório na resolução; ``cnj`` (segmento J) também decide; ``classe`` (REsp → STJ)
    # apenas desempata (revisão R2-11; ADR 0006 §2)
    if tst or trib_meio:
        tribunal_fonte = "explicito"
    elif tribunal and formato == "cnj20" and inferir_tribunal([], None, digitos, formato) == tribunal:
        tribunal_fonte = "cnj"
    else:
        tribunal_fonte = "classe" if tribunal else ""
    ano = ""
    if formato == "cnj20" and len(digitos) == 20:
        ano = digitos[9:13]
    elif formato == "registro":
        ano = digitos[:4]
    dados = {
        "classe": cadeia_sup,
        "cadeia": " ".join(cadeia),
        "classe_principal": principal,
        "numero": numero,
        "digitos": digitos,
        "formato": formato,
        "uf": uf,
        "tribunal": tribunal,
        "ano": ano,
        "relator": "",
        "artigo": "",
        "diploma": "",
        "numero_sumula": "",
        "vinculante": "",
        "numero_tema": "",
        "conector": conector or "",
        "prefixo_tst": "1" if tst else "0",
        "tribunal_fonte": tribunal_fonte,
        "registro": digitos_do_identificador(m.groupdict().get("registro") or ""),
        "plural": "1" if _e_plural(cadeia_sup) else "0",
    }
    return Achado(inicio, fim, trecho, "processo", "jurisprudencia", dados, origem, forca)


#: Segundo número de uma enumeração com a classe no plural (``REsps 1.234.567/SP e
#: 1.234.568/RS``; revisão rodada 2, R4-15): ``e``/``,``/``;`` + [artigo + conector: ``e o nº``]
#: + número + UF, colado ao span anterior. Herda a cadeia do primeiro e vira span próprio.
#: A UF é obrigatória salvo com a classe no plural (rodada 4, R6-07: ``REsps X, Y e Z, todos do
#: STJ``, ``Rcls X e Y``), quando o código exige ≥ 5 dígitos e o mesmo formato do primeiro.
RE_ENUMERACAO = re.compile(
    rf"\s{{0,2}}(?:,|;|e|E)\s{{1,2}}(?:[oa]s?\s{{1,2}})?(?:{P.CONECTOR}\s{{0,2}})?"
    rf"(?P<numero>{P.NUMERO})(?P<ufbloco>{P.UF_COM_SEPARADOR})?"
)
_MIN_DIGITOS_ENUMERACAO_SEM_UF = 5


def _enumerados(texto: str, primeiro: Achado) -> list[Achado]:
    """Spans dos números seguintes de ``REsps X/UF e Y/UF`` e de ``REsp X/UF e Y/UF``.

    Com a classe no plural, qualquer número com UF continua a enumeração; sem plural
    (revisão rodada 3, R3-12) o número seguinte precisa ter o MESMO formato do primeiro, UF
    e ≥ 4 dígitos — ``e 12/03/2020`` ou ``, 2ª Turma`` nunca casam (a UF é obrigatória).
    """
    saida: list[Achado] = []
    plural = primeiro.dados.get("plural") == "1"
    if not plural and len(primeiro.dados.get("digitos") or "") < 4:
        return saida
    pos = primeiro.fim
    anterior = primeiro
    while True:
        m = RE_ENUMERACAO.match(texto, pos)
        if m is None:
            break
        numero = m.group("numero")
        digitos = digitos_do_identificador(_segmentos_de_uma_letra(numero))
        if not digitos or formato_de(digitos) != anterior.dados["formato"]:
            break
        if not plural and (len(digitos) < 4 or _RE_ANO_SOLTO.match(digitos)):
            break   # ``e 2020/SP`` não é o segundo número de uma enumeração
        if not m.group("ufbloco") and (
                not plural or len(digitos) < _MIN_DIGITOS_ENUMERACAO_SEM_UF or _RE_ANO_SOLTO.match(digitos)):
            break   # sem UF só com a classe no plural, ≥ 5 dígitos e nunca um ano (rodada 4, R6-07)
        uf = P.uf_canonica(m.group("uf") or m.group("uf_par") or m.group("uf_colada") or "")
        dados = dict(anterior.dados)
        dados.update({"numero": numero, "digitos": digitos, "formato": formato_de(digitos), "uf": uf,
                      "conector": "", "registro": "", "plural": "0",
                      "tribunal": inferir_tribunal(anterior.dados["cadeia"].split(), uf or None, digitos,
                                                   formato_de(digitos)) or ""})
        dados["tribunal_fonte"] = "classe" if dados["tribunal"] else ""
        a = Achado(m.start("numero"), m.end(), texto[m.start("numero"):m.end()], "processo", "jurisprudencia",
                   dados, "regex:processo:enumeracao", 1.0)
        saida.append(a)
        anterior, pos = a, m.end()
    return saida


def detectar_estrito(texto: str) -> list[Achado]:
    """Padrão estrito. Cadeia sem sigla canônica conhecida por ``normalizacao``
    (ex.: ``Inq``, ``ADO``) sai com força 0,8 e origem ``regex:processo:sigla_rara``."""
    saida: list[Achado] = []
    for m in RE_PROCESSO.finditer(texto):
        a = _montar(texto, m, "regex:processo", 1.0)
        if a is None:
            continue
        if not a.dados["cadeia"]:
            a = Achado(a.inicio, a.fim, a.trecho, a.familia, a.tipo, a.dados,
                       "regex:processo:sigla_rara", 0.8)
        saida.append(a)
        saida.extend(_enumerados(texto, a))
    return saida


def detectar_amplo(texto: str) -> list[Achado]:
    """Padrão amplo (força 0,5): sigla desconhecida ou ``Processo/Autos`` + número."""
    saida: list[Achado] = []
    for m in RE_PROCESSO_AMPLO.finditer(texto):
        sigla = m.group("sigla")
        if sigla is not None and not _e_sigla_plausivel(sigla):
            continue
        # "NNN/AAAA" (Memorial nº 123/2024, Ofício nº 45/2023) não é processo
        if re.match(r"/\d{2,4}\b", texto[m.end("numero"):m.end("numero") + 6]):
            continue
        a = _montar(texto, m, "regex:processo:amplo", 0.5)
        if a is not None:
            saida.append(a)
    return saida


def detectar(texto: str) -> list[Achado]:
    """Estrito + amplo, na ordem do texto (a fusão remove as sobreposições)."""
    achados = detectar_estrito(texto) + detectar_amplo(texto)
    achados.sort(key=lambda a: (a.inicio, -a.fim))
    log.debug("processo: %d achados", len(achados))
    return achados


__all__ = ["RE_PROCESSO", "RE_PROCESSO_AMPLO", "detectar", "detectar_estrito", "detectar_amplo"]
