"""Blocos de regex reutilizáveis pelos detectores (docs/03 §2, §3, §9.1).

Tudo aqui é *texto de regex* (strings) ou padrões compilados uma única vez na
importação. Convenções:

* **espaço** é sempre ``\\s`` com quantificador limitado (``\\s{1,4}``): cobre
  espaço, espaço duplo, NBSP (``\\xa0``) e quebra de linha, que aparecem em
  qualquer posição do span (docs/03 §3.2), sem permitir que um span engula
  parágrafos inteiros;
* quantificadores ilimitados só sobre classes que não se sobrepõem ao que vem
  depois (evita retrocesso catastrófico; ver ``tests/test_deteccao.py``);
* siglas processuais são casadas com caixa exata (``REsp``, ``RESP``, mas nunca
  ``resp``), pois ``AR``, ``AP``, ``RE``, ``AI`` seriam palavras comuns em
  minúsculas; nomes por extenso exigem inicial maiúscula (``Recurso``,
  ``RECURSO``) e, no resto, toleram caixa, acento, quebra de linha entre
  palavras e o OCR medido (``Fcderal``, ``Espcciãl``);
* nenhum bloco casa o artigo anterior (``o``, ``a``, ``no``, ``na``) nem a
  pontuação final: as fronteiras do span são as de docs/03 §1.
"""
from __future__ import annotations

import re

from ..normalizacao import UFS

# ===========================================================================
# 1. Espaço, conector de número, UF
# ===========================================================================

#: Espaço "interno" do span (1–4 caracteres): `` ``, ``  ``, ``\xa0``, ``\n``, ``\n ``.
S = r"\s{1,4}"
#: Espaço opcional.
S0 = r"\s{0,4}"

#: Conector de número (docs/03 §2.2 + formas ood do gerador): ``nº``, ``n.``, ``n°``,
#: ``Nº``, ``No``, ``n.º``, ``N.º``, ``nº.`` (ponto depois do ordinal; revisão rodada 2,
#: R4-05), ``número``, ``num.``, ``n`` isolado. ``U+FFFD`` no lugar de ``º`` cobre um
#: arquivo que não era UTF-8 (``errors="replace"`` em ``texto.carregar``; R3b-06).
#: Nunca é seguido de letra (``No`` de ``Novembro`` não é conector: exige-se
#: espaço ou dígito depois — garantido pelo bloco que o usa).
#: Plural (``nºs``, ``n.ºs``, ``nos``, ``números``; rodada 4, R6-02) para as enumerações
#: ``REsps nºs X/UF e Y/UF``.
CONECTOR = r"(?:[nN](?:[uú]meros?|[uú]m\.?|\.?\s?[º°ᵒ\ufffd]s?\.?|[oO]s?\.?|\.)?)"

#: UF: lista fechada de 27 siglas (docs/03 §2.4). Só maiúsculas ASCII, com o OCR
#: ``S``→``5`` e ``O``→``0`` medido em caixa alta no nível 2 (``5P``, ``R5``, ``M5``, ``G0``,
#: ``R0``; revisão rodada 3, R3-13): a letra que o OCR troca nunca é a primeira quando ela
#: sozinha identificaria outra coisa — ``5P`` é aceito porque ``5`` não abre nenhuma sigla
#: de classe nem grupo numérico depois de ``/``. :func:`uf_canonica` desfaz a troca.
_UF_OCR = {"S": "[S5]", "O": "[O0]"}
UF = "(?:" + "|".join(
    "".join(_UF_OCR.get(ch, ch) for ch in uf) for uf in sorted(UFS)
) + ")"
#: UF sem OCR: a única forma aceita COLADA ao número (``1234567SP``; ``44974G0`` é número, não ``GO``).
UF_LIMPA = "(?:" + "|".join(sorted(UFS)) + ")"


def uf_canonica(uf: str | None) -> str:
    """``"5P"`` → ``"SP"``, ``"R0"`` → ``"RO"``, ``"SP"`` → ``"SP"``; vazio se não for UF."""
    if not uf:
        return ""
    u = uf.strip().upper().replace("5", "S").replace("0", "O")
    return u if u in UFS else ""

#: UF com separador, para colar ao fim do número. Alternativas medidas (§2.4)
#: e as ood: ``/SP``, ``/ SP``, ``-SP``, `` - SP``, `` – SP``, `` (SP)``, ``\n- SP``,
#: `` / SP``, ``–SP``, `` — SP``, ``(SP)`` colado, `` /SP``, ``/\nSP``, `` SP``.
#: O ``)`` entra no span só quando o ``(`` abriu. A UF nunca é seguida de letra
#: ou dígito (``/SPA`` não é UF).
UF_COM_SEPARADOR = (
    r"(?:"
    rf"{S0}\({S0}(?P<uf_par>{UF}){S0}\)"                   # (SP), ( SP ), \n(SP)
    rf"|(?:{S0}[/\-–—]{S0}|\s{{1,3}})(?P<uf>{UF})(?![A-Za-zÀ-ÿ0-9])"
    rf"|(?<=\d)(?P<uf_colada>{UF_LIMPA})(?![A-Za-zÀ-ÿ0-9])"   # ``1234567SP`` colada (rodada 4, R4-09)
    r")"
)

# ===========================================================================
# 2. Número de processo com ruído (docs/03 §2.3, §3.1, §9.1)
# ===========================================================================

#: Letras que o OCR troca por dígitos (docs/03 §3.1 + ood ``I o q B Z z |``).
LETRAS_OCR = "OolI|SsgqGBZz"
#: Ano de 4 dígitos (2016–2026 no dev; aceita 19xx/20xx).
ANO_RE = r"(?:19|20)\d{2}"
#: Um grupo numérico: começa por dígito ASCII; letras confundíveis só coladas a dígitos.
_GRUPO_INICIAL = rf"\d[\d{LETRAS_OCR}]*"
#: Grupo seguinte (depois de pontuação): pode começar por letra confundível (``1.O99``)
#: mas precisa conter ao menos um dígito — assim ``- S`` de ``- SP`` nunca vira grupo.
#: A exceção é um segmento de 1–3 letras confundíveis no lugar de um segmento
#: do CNJ ou de milhar (``2016.S.00``, ``2023.7.OO.0000``, ``1.lOS.567``), aceito
#: quando seguido de separador + dígito (a normalização o trata como núcleo
#: ambíguo; ver ``normalizacao.nucleos`` e ``resolucao.chaves_alternativas``).
_GRUPO = rf"(?:[\d{LETRAS_OCR}]*\d[\d{LETRAS_OCR}]*|[{LETRAS_OCR}]{{1,3}}(?=[.\-–\s]{{1,2}}\d))"
#: Grupo FINAL inteiramente em letras confundíveis (``1.140.OSl``, ``0000-12.2020.8.26.OlOO``;
#: revisão rodada 2, R4-01): só colado a UM sinal de pontuação (nunca depois de
#: branco — ``567. O recurso`` é fim de frase), 1–4 letras, nunca seguido de letra
#: ou dígito e nunca igual a uma UF (``-GO`` é Goiás). O span o consome para que
#: o prefixo numérico nunca vire chave parcial: ``nucleos`` marca o núcleo como
#: ambíguo e a resolução só o lê pela conversão relaxada (``chaves_alternativas``).
_GRUPO_OCR_FINAL = rf"[.\-–](?!{UF}(?![A-Za-zÀ-ÿ0-9]))[{LETRAS_OCR}]{{1,4}}(?![A-Za-zÀ-ÿ0-9])"
#: Grupo depois de 1–2 brancos (``1 234 567``, ``7009999-12 2021 7 00 0000``,
#: ``9.\n999.999``, ``1 o99 999``). Mais restrito que :data:`_GRUPO`, porque o
#: branco também separa o número do que vem depois na frase (docs/03 §2.3;
#: revisão R1-04): um ano de 4 dígitos (``2019``) só entra se o número continua
#: (CNJ com espaços); um caractere sozinho (``7``, ``S``) idem; um grupo com ≥ 2
#: dígitos nunca é seguido de ordinal (``2ª Turma``), de ``/dígito`` (data
#: ``12/03/2022``) nem de ``.dd.dddd`` (data ``12.03.2022``).
_CONTINUA = rf"(?=[.\-–\s]{{1,2}}(?:\d|[{LETRAS_OCR}]{{1,2}}[.\-–\s]{{1,2}}\d))"
#: Segmento J do CNJ depois de um branco no lugar do ponto (``7000123-45.2023 7.00.0000``,
#: ``0000123-45.2016\n5.24.0099``; rodada 4, R4-01): um caractere numérico precedido do ano
#: de 4 dígitos + branco e seguido de ``.TR.OOOO`` — tem exatamente a forma da data
#: ``d.dd.dddd`` que a guarda abaixo rejeita, por isso é reconhecido ANTES dela.
_SEGMENTO_J_APOS_BRANCO = (
    rf"(?:(?<=\d{{4}}\s)|(?<=\d{{4}}\s\s))[\d{LETRAS_OCR}]"
    rf"(?=[.\-–\s]{{1,2}}[\d{LETRAS_OCR}]{{2}}[.\-–\s]{{1,2}}[\d{LETRAS_OCR}]{{4}}(?![\d{LETRAS_OCR}]))"
)
_GRUPO_APOS_BRANCO = (
    r"(?:"
    rf"{_SEGMENTO_J_APOS_BRANCO}"
    r"|(?:"
    rf"{ANO_RE}{_CONTINUA}"
    rf"|(?!{ANO_RE}(?![\d{LETRAS_OCR}]))[\d{LETRAS_OCR}]*\d[\d{LETRAS_OCR}]*\d[\d{LETRAS_OCR}]*"
    rf"|[\d{LETRAS_OCR}]{{1,2}}{_CONTINUA}"
    r")"
    rf"(?![\d{LETRAS_OCR}ºª°]|/\d|\.\d{{1,2}}\.\d{{4}})"
    r")"
)
#: Separador entre grupos: pontuação (``.``, ``-``, ``–``, ``--``, ``-\n.``, ``.-\n``,
#: ``. ``) com no máximo 2 brancos.
_SEP_PONTUADO = r"(?:[.\-–]{1,2}\s{0,2}[.\-–]{0,2}|\s{1,2}[.\-–]{1,2}\s{0,2})"
#: UF colada ao último dígito (``1234567SP``; rodada 4, R4-09): a única letra que pode seguir
#: o número sem separador.
_UF_COLADA = rf"{UF_LIMPA}(?![A-Za-zÀ-ÿ0-9])"
#: Fim do número (rodada 4, R4-09/R6-08): nunca seguido de letra ou dígito — salvo uma UF
#: colada — nem de pontuação + dígito. Assim ``1.234.567 - 5P`` para em ``567`` (o ``5P`` é a
#: UF com OCR, não um grupo) e ``1.234.56A`` (letra fora do mapa de confusões) não casa em
#: parte alguma: chave parcial nunca é emitida (o retrocesso não pode parar antes de um
#: dígito nem de ``.dígito``).
_FIM_NUMERO = rf"(?!(?!{_UF_COLADA})[A-Za-zÀ-ÿ0-9]|[.\-–]\d)"
#: Prefixo opcional de 1–3 letras confundíveis ANTES do primeiro dígito, no lugar
#: do primeiro dígito com OCR (``l.234.567``, ``G2.416``, ``lO.345``; revisão
#: R1-02). Só quando seguido de dígito (ou de um ponto de milhar + dígito) e
#: precedido do que separa a cadeia do número (branco, hífen ou conector), o
#: que a regex que o usa garante. O reparo é da resolução
#: (``chaves_alternativas``, rótulo ``letra_inicial``): a chave padrão continua
#: sendo lida a partir do primeiro dígito ASCII.
PREFIXO_OCR = rf"(?:[{LETRAS_OCR}]{{1,3}}\.?(?=\d))?"
#: Número completo: [prefixo de OCR] grupo inicial + (separador + grupo)*. Não
#: inclui ``/`` (a UF vem depois de ``/``) exceto na forma "registro" do STJ,
#: tratada à parte.
NUMERO = (
    rf"{PREFIXO_OCR}{_GRUPO_INICIAL}"
    rf"(?:{_SEP_PONTUADO}{_GRUPO}(?![A-Za-zÀ-ÿ0-9ºª°])|\s{{1,2}}{_GRUPO_APOS_BRANCO}|{_GRUPO_OCR_FINAL})*"
    rf"{_FIM_NUMERO}"
)
#: Registro do STJ ``AAAA/NNNNNNN-D`` (docs/04 h.4; ood ``registro_stj``).
NUMERO_REGISTRO = r"(?:19|20)\d{2}\s?[/⁄]\s?\d{7}\s?-\s?\d"

#: Ano de 4 dígitos (alias de :data:`ANO_RE`).
ANO = ANO_RE
#: Ano de citação vaga com o OCR letra↔dígito do nível 2 em qualquer posição (``2O21``,
#: ``20l9``, ``2Ol8``; revisão rodada 2, R4-01): ``1``/``2`` (ou ``l``/``I``/``|``/``Z``) +
#: ``9``/``0`` (ou ``g``/``q``/``O``/``o``) + dois caracteres numéricos, nunca seguido de
#: letra ou dígito. O detector exige ≥ 2 dígitos reais e converte pelo mapa inverso
#: (``normalizacao.CONFUSOES``); a resolução não usa o ano para classificar.
ANO_OCR = rf"(?:[12lI|Zz][09OogqQ][\d{LETRAS_OCR}]{{2}})(?![0-9A-Za-zÀ-ÿ])"

# ===========================================================================
# 3. Classes processuais
# ===========================================================================

# Siglas em CamelCase canônico. Cada uma gera as formas: exata, toda em caixa
# alta, com ponto opcional entre os segmentos (``R.Esp.``, ``A.REsp``, ``H.C.``,
# ``Ag. Int.``, ``AG.REG``, ``Rec. Esp.``, ``Emb. Decl.``) e ponto final opcional
# (``REspe.``, ``RE.``, ``Rcl.``). Um espaço entre segmentos só é aceito depois
# de um ponto (``Ag. Int.`` sim, ``A REsp`` não — seria o artigo ``A`` + ``REsp``).
SIGLAS: tuple[str, ...] = (
    # STJ / STF
    "REsp", "Resp", "RecEsp", "AREsp", "AgREsp", "AgResp", "EREsp", "EAREsp", "RHC", "RMS",
    "HC", "MS", "AR", "AP", "CC", "SLS", "SS", "SL", "STA", "Pet", "Rcl", "Recl", "RE", "ARE",
    "ADI", "ADIn", "ADPF", "ADC", "ADO", "Ext", "Inq", "ACO", "AC", "AI",
    # prefixos / incidentes
    "AgRg", "AgR", "AgReg", "AgrReg", "AgInt", "Ag", "EDcl", "EDs", "ED", "EmbDecl", "EDv",
    "EDiv", "EmbDiv", "EmbInfr", "QO", "PExt", "Emb", "Ref",
    # TSE
    "REspe", "REspE", "AREspEl", "AREspE", "AREspe", "RO", "AIJE", "Rp", "PC", "LT", "RCED",
    "Cta", "TutCautAnt",
    # STM
    "APL", "Ap", "RSE", "EI", "CJ", "CP", "RDI",
    # TST
    "RR", "AIRR", "ARR", "RRAg", "ROT", "AIRO", "EDCiv", "AgARR", "AgAIRR", "AgRR",
    "EDAIRR", "EDRR", "AgRRAg",
)

#: Siglas de uma só letra que só existem em cadeias hifenizadas do TST/TSE
#: (``ED-E-ED-RR``, ``R-Rp``): nunca casam sozinhas.
SIGLAS_SO_EM_HIFEN: tuple[str, ...] = ("E", "R")

# Nomes por extenso (chave sem acento, minúscula). Casados sem distinção de caixa,
# com tolerância a acento e a ``\s`` (inclusive quebra) entre as palavras.
EXTENSOS: tuple[str, ...] = (
    "recurso especial eleitoral", "recurso especial", "agravo em recurso especial eleitoral",
    "agravo em recurso especial", "embargos de divergencia em recurso especial",
    "embargos de divergencia em agravo em recurso especial", "embargos de divergencia",
    "recurso extraordinario com agravo", "recurso extraordinario",
    "reclamacao constitucional", "reclamacao",
    "recurso ordinario em habeas corpus", "recurso em habeas corpus", "habeas corpus",
    "recurso ordinario em mandado de seguranca", "recurso em mandado de seguranca",
    "mandado de seguranca", "acao rescisoria", "acao penal",
    "acao direta de inconstitucionalidade", "arguicao de descumprimento de preceito fundamental",
    "acao declaratoria de constitucionalidade", "conflito de competencia",
    "suspensao de liminar e de sentenca", "suspensao de seguranca", "suspensao de liminar",
    "peticao", "cautelar inominada criminal", "cautelar inominada",
    "agravo regimental", "agravo interno", "embargos de declaracao", "embargos declaratorios",
    "questao de ordem", "pedido de extensao", "referendo",
    "recurso ordinario eleitoral", "recurso ordinario", "agravo de instrumento em recurso de revista",
    "agravo de instrumento", "acao de investigacao judicial eleitoral",
    "recurso contra expedicao de diploma", "prestacao de contas", "acao cautelar", "lista triplice",
    "tutela cautelar antecedente", "recurso na representacao", "representacao",
    "apelacao criminal", "apelacao civel", "apelacao", "embargos infringentes e de nulidade",
    "embargos infringentes", "agravo de peticao", "recurso inominado", "remessa necessaria",
    "embargos de declaracao civel", "mandado de seguranca civel",
    "recurso em sentido estrito", "conflito de jurisdicao", "correicao parcial",
    "recurso de revista com agravo", "recurso de revista", "recurso ordinario trabalhista",
    "recurso ordinario em acao rescisoria", "agravo", "embargos",
    # abreviações mistas (ood): o ponto é opcional
    "rec. especial", "rec. esp. eleitoral", "resp. eleitoral", "rec. especial eleitoral",
    "ag. regimental", "ag. interno", "emb. de declaracao", "emb. declaratorios",
    "rec. extraordinario", "rec. ordinario", "rec. de revista", "ag. de instrumento",
)
#: Plurais dos nomes por extenso (``Recursos Especiais 1.234.567/SP e 2.345.678/RJ``,
#: ``Reclamações``, ``Agravos Internos``; rodada 4, R6-02): abrem uma enumeração como as
#: siglas com ``s`` (``REsps``). ``normalizacao`` os conhece como aliases da mesma cadeia.
EXTENSOS_PLURAL: tuple[str, ...] = (
    "recursos especiais eleitorais", "recursos especiais", "agravos em recurso especial",
    "agravos em recursos especiais", "embargos de divergencia em recursos especiais",
    "recursos extraordinarios com agravo", "recursos extraordinarios", "reclamacoes constitucionais",
    "reclamacoes", "recursos ordinarios em habeas corpus", "recursos em habeas corpus",
    "recursos ordinarios em mandado de seguranca", "recursos em mandado de seguranca",
    "mandados de seguranca", "acoes rescisorias", "acoes penais", "acoes diretas de inconstitucionalidade",
    "conflitos de competencia", "agravos regimentais", "agravos internos", "recursos ordinarios",
    "agravos de instrumento em recurso de revista", "agravos de instrumento", "apelacoes criminais",
    "apelacoes civeis", "apelacoes", "recursos de revista", "agravos", "peticoes", "representacoes",
)

#: Ordinais que antecedem a cadeia (``Terceiro AG.REG na Rcl``, ``2º AgRg no RE``).
ORDINAL = (
    r"(?:(?:Segund|Terceir|Quart|Quint|Sext|S[ée]tim|Oitav|Non|D[ée]cim)[oa]s?"
    r"|(?:SEGUND|TERCEIR|QUART|QUINT|SEXT|S[ÉE]TIM|OITAV|NON|D[ÉE]CIM)[OA]S?"
    r"|\d{1,2}[ºªo°])"
)

#: Letra → classe tolerante a acento, caixa e ao OCR medido em docs/03 §3.1
#: (``e``→``c``, ``a``→``ã``, ``c``→``e``, ``m``→``rn``, ``i``→``l``; ood ``o``→``0``,
#: ``s``→``5``, ``u``→``ü``, ``n``→``ri``). Só é usada DENTRO de nomes multi-palavra
#: (classes, diplomas, tribunais), sempre presos a outra âncora do padrão.
#: ``i``/``l`` também aceitam ``1`` e ``|`` (``Rec1amação``, ``Recurso Espec1al``, ``Agravo
#: 1nterno``; rodada 4, R6-12 — o enunciado do desafio lista ``Sumu1a`` como ruído esperado).
_ACENTOS: dict[str, str] = {
    "a": "[aáàâãäAÁÀÂÃÄ]", "c": "[cçeCÇE]", "e": "[eéèêëcEÉÈÊËC]", "i": "[iíìîïlIÍÌÎÏ1|]",
    "l": "[lL1I|]", "o": "[oóòôõöOÓÒÔÕÖ0]", "u": "[uúùûüUÚÙÛÜ]", "s": "[sS5]",
    "m": "(?:[mM]|rn|RN)", "n": "(?:[nN]|ri)",
}


_MAIUSCULAS: dict[str, str] = {
    "a": "[AÁÀÂÃÄ]", "c": "[CÇ]", "e": "[EÉÈÊË]", "i": "[IÍÌÎÏ]", "o": "[OÓÒÔÕÖ]", "u": "[UÚÙÛÜ]",
}


def _regex_palavra(palavra: str, inicial_maiuscula: bool = False) -> str:
    """``"reclamacao"`` → regex tolerante a acento/caixa e ao OCR de :data:`_ACENTOS`.

    ``"Constituição Fcderal"`` e ``"Recurso Espcciãl"`` casam; a inicial maiúscula
    (quando exigida) nunca sofre OCR.

    Com ``inicial_maiuscula`` a primeira letra só casa em maiúscula: um nome de
    classe por extenso começa sempre por maiúscula no gabarito (``Recurso``,
    ``RECURSO``), e ``recurso especial`` em minúsculas na prosa não é citação.
    """
    partes = []
    for k, ch in enumerate(palavra):
        if k == 0 and inicial_maiuscula:
            partes.append(_MAIUSCULAS.get(ch, ch.upper()))
        elif ch == ".":
            partes.append(r"\.?")
        elif ch in _ACENTOS:
            partes.append(_ACENTOS[ch])
        else:
            partes.append(f"[{ch}{ch.upper()}]")
    return "".join(partes)


def regex_extenso(nome: str, inicial_maiuscula: bool = True) -> str:
    """``"recurso especial"`` → ``[R][eE]...[oO]\\s{1,4}[eE]...`` com quebra entre palavras."""
    palavras = nome.split()
    return S.join(
        _regex_palavra(p, inicial_maiuscula=(inicial_maiuscula and k == 0))
        for k, p in enumerate(palavras)
    )


_RE_SEGMENTOS = re.compile(r"[A-Z][a-z]*|[a-z]+")

#: Letra de sigla → classe com o dígito que o OCR põe no lugar (docs/03 §3.1:
#: ``DO5``, ``C0NTROVÉRSIA`` e ``S``→``5`` em ``Súmula`` mostram ``S``→``5``, ``O``→``0``,
#: ``I``→``1`` em caixa alta; ``i``→``l`` em minúsculas). Só dentro de siglas com
#: ≥ 2 caracteres e nunca na primeira letra (``5S`` não é ``SS``); ``e``↔``c`` fica
#: de fora de propósito: ``Rel.`` (relator) não pode virar ``Rcl``.
_OCR_SIGLA: dict[str, str] = {
    "S": "[S5]", "O": "[O0]", "I": "[I1l]", "B": "[B8]", "Z": "[Z2]", "G": "[G6]",
    "s": "[s5]", "o": "[o0]", "i": "[il1]", "l": "[l1I]", "g": "[g9]",
}


def _classe_sigla(seg: str, primeira: bool) -> str:
    """``"Esp"`` → ``E[s5]p`` (a 1ª letra da sigla nunca sofre OCR)."""
    partes = []
    for k, ch in enumerate(seg):
        if primeira and k == 0:
            partes.append(re.escape(ch))
        else:
            partes.append(_OCR_SIGLA.get(ch, re.escape(ch)))
    return "".join(partes)


def regex_sigla(sigla: str, ponto_final: bool = True) -> str:
    """Regex de uma sigla CamelCase com as variações de pontuação e caixa observadas.

    ``"AgInt"`` → ``(?:Ag|AG)(?:\\.\\s?)?(?:[I1l]nt|[I1l]NT)\\.?`` — casa ``AgInt``,
    ``AGINT``, ``Ag. Int.``, ``Ag.Int``, ``AgInt.`` e o OCR ``Aglnt``/``RE5P``
    (revisão R2-02); não casa ``Ag Int`` (sem ponto) nem ``agint``. Segmentos =
    corridas iniciadas por maiúscula. A primeira letra é sempre literal, então
    uma sigla nunca começa por dígito.
    """
    segmentos = _RE_SEGMENTOS.findall(sigla)
    partes = []
    for i, seg in enumerate(segmentos):
        if len(sigla) < 2:
            partes.append(re.escape(seg))
        elif seg.upper() == seg:
            partes.append(_classe_sigla(seg, i == 0))
        else:
            partes.append(f"(?:{_classe_sigla(seg, i == 0)}|{_classe_sigla(seg.upper(), i == 0)})")
    corpo = r"(?:\.\s?)?".join(partes)
    return corpo + (r"\.?" if ponto_final else "")


def _alternancia(itens: list[str]) -> str:
    return "(?:" + "|".join(itens) + ")"


#: Sigla (sem as de uma letra), maior primeiro. Fronteira à esquerda: não pode
#: vir colada a letra (``nosEMBARGOS`` é tratado pelo nome por extenso).
SIGLA = _alternancia([regex_sigla(s) for s in sorted(SIGLAS, key=len, reverse=True)])
#: Sigla que pode participar de cadeia hifenizada (inclui ``E`` e ``R``).
SIGLA_HIFEN = _alternancia(
    [regex_sigla(s, ponto_final=False) for s in sorted(SIGLAS, key=len, reverse=True)]
    + list(SIGLAS_SO_EM_HIFEN)
)
#: Nome por extenso, maior primeiro (``Recurso Especial Eleitoral`` antes de ``Recurso Especial``).
EXTENSO = _alternancia([regex_extenso(n) for n in sorted(EXTENSOS + EXTENSOS_PLURAL, key=len, reverse=True)])

#: Um elemento da cadeia: cadeia hifenizada (≥ 2 tokens, ``ED-E-ED-RR``, ``AgR-REspe``),
#: nome por extenso ou sigla. Depois do elemento não pode vir letra (``REsp`` não
#: casa em ``REspe``… a alternância maior-primeiro já cuida disso, mas a guarda
#: impede ``AR`` em ``ARE``-like desconhecidos).
#: As repetições são limitadas (≤ 7 tokens hifenizados, ≤ 6 ligações): cadeias
#: reais têm até 5 elementos e o limite mantém a busca linear em textos patológicos.
#: Um ``s`` de plural colado à sigla (``REsps``, ``HCs``, ``RRs``; revisão rodada 2, R4-15)
#: entra no elemento; ``normalizacao.cadeia_de_classes`` o descarta.
ELEMENTO = (
    r"(?:"
    rf"{SIGLA_HIFEN}(?:\s{{0,2}}-\s{{0,2}}{SIGLA_HIFEN}){{1,7}}"
    rf"|{EXTENSO}"
    rf"|{SIGLA}"
    r")(?:s(?![A-Za-zÀ-ÿ]))?(?![A-Za-zÀ-ÿ])"
)
#: Conector entre elementos da cadeia (``no``, ``na``, ``nos``; caixa alta no N2; ``em`` ood).
#: ``n0``/``N0``/``nã`` cobrem o OCR ``o``→``0``/``a``→``ã`` na ligação (``AgInt n0 AREsp``; rodada 3, R3-13).
LIGACAO = rf"(?:{S}(?:no|na|nos|NO|NA|NOS|em|EM|n[0ã]|N[0Ã]|n[0ã]s|N[0Ã]S){S})"
#: Cadeia completa: ``[ordinal] elemento (ligação [ordinal] elemento)*`` — o ordinal
#: pode vir no meio (``EDcl no 2º AgRg na Rcl``, ``AgRg nos EDv nos EDcl no Segundo
#: AgRg no ARE``; revisão R1-05).
#: Um ordinal também pode seguir o elemento anterior sem ``no/na`` (``AG.REG. SEGUNDOS
#: EMBARGOS DE DIVERGÊNCIA``, ``EDCL SEGUNDO AGR``): o ordinal é inequívoco como ligação.
CADEIA = (
    rf"(?:{ORDINAL}{S})?{ELEMENTO}"
    rf"(?:(?:{LIGACAO}(?:{ORDINAL}{S})?|{S}{ORDINAL}{S}){ELEMENTO}){{0,6}}"
)

#: Prefixo de tribunal (docs/03 §2.5): só ``TST-`` (com espaço opcional depois do hífen;
#: ``T5T-`` com o OCR ``S``→``5`` — revisão rodada 2, R4-15).
PREFIXO_TST = r"(?:T[S5]T\s{0,2}-\s{0,2})"
#: ``processo nº``/``Processo n°``/``processo n.º`` antes de ``TST-`` (4 casos no dev).
PREFIXO_PROCESSO = rf"(?:[Pp]rocesso{S}{CONECTOR}{S0})"

# ===========================================================================
# 4. Tribunais e relatoria (vaga, súmula)
# ===========================================================================

#: Sigla do tribunal com o OCR ``S``→``5`` medido em caixa alta (``5TJ``, ``T5T``, ``5TM``;
#: docs/03 §3.1 mede ``S``→``5`` em caixa alta; revisão rodada 3, R3-06) e a forma pontuada ``S.T.J.``
#: (``T.S.E.``; o ponto final só entra quando os internos existem — ``do STJ.`` fecha a
#: frase). :func:`sigla_tribunal_canonica` desfaz as duas coisas.
TRIBUNAL_SIGLA = r"(?:[S5]T[JF]|T[S5][TE]|[S5]TM|S\.T\.[JF]\.?|T\.S\.[TE]\.?|S\.T\.M\.?)"
#: Só as cinco siglas limpas (para lookbehinds e listas de exclusão).
TRIBUNAIS_SIGLA_LIMPA: tuple[str, ...] = ("STF", "STJ", "TSE", "TST", "STM")


def sigla_tribunal_canonica(texto: str | None) -> str:
    """``"5TJ"``/``"S.T.J."``/``"stj"`` → ``"STJ"``; vazio se não for uma das cinco siglas."""
    if not texto:
        return ""
    t = texto.strip().upper().replace(".", "").replace("5", "S")
    return t if t in TRIBUNAIS_SIGLA_LIMPA else ""


TRIBUNAL_EXTENSO = _alternancia([
    regex_extenso("supremo tribunal federal", inicial_maiuscula=False),
    regex_extenso("superior tribunal de justica", inicial_maiuscula=False),
    regex_extenso("tribunal superior eleitoral", inicial_maiuscula=False),
    regex_extenso("tribunal superior do trabalho", inicial_maiuscula=False),
    regex_extenso("superior tribunal militar", inicial_maiuscula=False),
])
TRIBUNAL = rf"(?:{TRIBUNAL_SIGLA}|{TRIBUNAL_EXTENSO})"
#: Órgão fracionário entre o substantivo e o tribunal (``acórdão da Corte Especial do STJ``,
#: ``da Primeira Turma do STF``, ``da 2ª Turma do STJ``, ``da SBDI-1 do TST``; revisão
#: rodada 2, R4-11): entra no span da citação vaga.
ORGAO_FRACIONARIO = (
    r"(?:(?:(?:[Pp]rimeira|[Ss]egunda|[Tt]erceira|[Qq]uarta|[Qq]uinta|[Ss]exta|[Ss][ée]tima|[Oo]itava"
    r"|PRIMEIRA|SEGUNDA|TERCEIRA|QUARTA|QUINTA|SEXTA|S[ÉE]TIMA|OITAVA|\d{1,2}[ªa°º])\s{1,2})?"
    r"(?:[Tt]urma|TURMA|[Ss]e[çc][ãa]o|SE[ÇC][ÃA]O|[Cc][âa]mara|C[ÂA]MARA)"
    r"|[Cc]orte\s{1,2}[Ee]special|CORTE\s{1,2}ESPECIAL|[Pp]len[áa]rio|PLEN[ÁA]RIO|[Tt]ribunal\s{1,2}[Pp]leno"
    r"|TRIBUNAL\s{1,2}PLENO|[ÓO]rg[ãa]o\s{1,2}[Ee]special|[ÓO]RG[ÃA]O\s{1,2}ESPECIAL|SBDI-?\s?[12I]{0,2}|SDI-?\s?[12I]{0,2}"
    r"|SDC|[Ss]e[çc][ãa]o\s{1,2}[Ee]specializada)"
)

#: Palavras com OCR tolerado (docs/03 §3.1: e→c, a→ã, c→e, m→rn, i→l; ood o→0,
#: s→5, u→ü, n→ri), via :func:`_regex_palavra`. ``proferldo``, ``dc``, ``julgãdo``,
#: ``preeedente``, ``aeórdão``, ``rclatoria``, ``relatorla`` casam.
P_JULGADO = _regex_palavra("julgado")
P_PRECEDENTE = _regex_palavra("precedente")
P_ACORDAO = _regex_palavra("acordao")
P_DECISAO = _regex_palavra("decisao")
P_ARESTO = _regex_palavra("aresto")
P_PROFERIDO = _regex_palavra("proferido")
P_RELATORIA = _regex_palavra("relatoria")
P_RELATADO = _regex_palavra("relatad") + "[aão0]"
P_RELATOR = _regex_palavra("relator") + "[aãAÃ]?"
#: Palavras de ligação da citação vaga em QUALQUER caixa (``DO``, ``EM``, ``PELA`` no ruído
#: de caixa alta do nível 2; revisão rodada 3, R3-06) e com o OCR medido (``d0``, ``dc``,
#: ``pe1a``, ``crn``).
P_MINISTRO = r"[mM][il1I][nN][il1I][sS5][tT][rR][oaOA0]"
P_DE = r"[dD][ceêCEÊ]"
P_DA = r"[dD][aãAÃ]"
P_DO = r"[dD][o0O]"
P_EM = r"(?:[eEcC][mM]|[ecEC]rn)"
P_PELA = r"[pP][ecEC][l1L][aãAÃ]"
P_SOB = r"[sS][o0O][bB]"
#: ``Rel``/``Rel.``/``Relator``/``Relatora`` (abreviado ou por extenso) e as abreviações
#: femininas ``Rel.ª``/``Relª.``/``Rela.`` (revisão rodada 2, R4-04).
_FEM = r"(?:\.?\s?[ªᵃ]\.?|\(a\))?"   # ``Rel.ª``, ``Relator(a)``, ``Ministro(a)`` (rodada 4, R4-06)
P_REL = _regex_palavra("rel") + "(?:" + _regex_palavra("ator") + "[aãAÃ]?)?" + _FEM
#: ``Min.``/``MIN.``/``Ministro``/``MINISTRA`` (caixa alta e OCR ``i``→``l``/``1``).
P_MIN = rf"(?:M[il1I][nN]\.?{_FEM}|{P_MINISTRO}{_FEM})"
#: ``Rel. p/ acórdão``/``Relator para o acórdão``/``Redator``/``Redatora`` (revisão rodada 3, R3-05).
P_REL_ACORDAO = (
    rf"(?:{P_REL}\.?{S}(?:p/|p\.|para){S0}(?:o{S})?{P_ACORDAO}|{_regex_palavra('redator')}[aãAÃ]?)"
)

#: ``Rel. Min.`` e variantes: ``Rel.  Min.``, ``Rel.\nMin.``, ``Relator Ministro``,
#: ``Relatora Ministra``, ``Rel. Ministro``, ``Relator: Min.``, ``Min.`` só depois de ``Rel``,
#: ``Rel. o Min.``/``Rel. a Min.``, ``Rel. p/ acórdão Min.``, ``Redator Ministro``.
REL_MIN = (
    rf"(?:(?:{P_REL}|{P_REL_ACORDAO})\.?:?{S}(?:[oa]{S})?(?:{P_MIN}|Des\.?|Desembargador[a]?)\.?:?)"
)
#: Honorífico opcional entre a fórmula de relatoria e o nome (``do e. Min. X``, ``do
#: Exmo. Min. X``, ``da Eminente Ministra X``; revisão rodada 2, R4-04): entra no span,
#: não no nome do relator.
HONORIFICO = (
    r"(?:[eEiI]\.|[Ee]xm[oa]\.?|[Ee]m\.|[Ee]minente|[Ii]lustre|[Ii]l\.|[Ss]r[a]?\.?|[Dd]r[a]?\.?|"
    r"[Dd]out[oa]|[Ee]xcelent[íi]ssim[oa]|[Ii]lustr[íi]ssim[oa]"
    # ``S. Exa.``, ``Sua Excelência``, ``V. Exa.`` (rodada 4, R6-06)
    r"|[SV]\.\s?Exa\.?|[Ss]ua\s{1,2}[Ee]xcel[êe]ncia|[Vv]ossa\s{1,2}[Ee]xcel[êe]ncia)"
)
#: Fórmulas de relatoria dos moldes A/B/E/F e variantes ood: ``pela relatoria de``,
#: ``da relatoria de``, ``sob relatoria de``, ``sob a relatoria do Ministro``,
#: ``relatada pelo Min.``, ``de relatoria do Min.``, ``relator o Ministro``, ``cujo
#: relator foi o Ministro``, ``tendo como relator o Ministro`` (revisão rodada 2, R4-04).
#: Novas na rodada 3 (R3-05): ``da lavra do Ministro``, ``de lavra da Ministra``, ``cuja
#: relatoria coube ao Ministro``, ``relatado por Nome`` (sem título; só com o nome próprio
#: logo depois), ``Rel. p/ acórdão Min.``, ``Redator Ministro`` (via ``REL_MIN``). Todas em
#: qualquer caixa (``PELA RELATORIA DE``).
_O_A = r"[oaOA]"
_PELO = r"[pP][ecEC][l1L][oaOA]"
_LAVRA = rf"(?:{P_DA}|{P_DE}){S}[lL][aãAÃ][vV][rR][aãAÃ]{S}(?:{P_DO}|{P_DA}){S}"
RELATORIA = (
    r"(?:"
    rf"(?:{P_PELA}|{P_DA}|{P_SOB}(?:{S}[aA])?|{P_DE}|[cC][oO][mM]{S}[aA]){S}{P_RELATORIA}{S}"
    rf"(?:{P_DE}|{P_DO}|{P_DA}){S}(?:{HONORIFICO}{S}(?:{_O_A}{S})?)?(?:(?:{P_MIN}|Des\.?){S})?"
    rf"|{P_RELATADO}{S}{_PELO}{S}(?:{HONORIFICO}{S})?(?:{P_MIN}|Des\.?){S}"
    rf"|{P_RELATADO}{S}[pP][oO][rR]{S}(?:{HONORIFICO}{S})?(?:(?:{P_MIN}|Des\.?){S})?"
    rf"|{REL_MIN}{S}(?:{HONORIFICO}{S})?"
    rf"|{P_RELATOR}{S}{_O_A}{S}(?:{HONORIFICO}{S})?{P_MIN}{S}"
    rf"|[cC][uU][jJ]{_O_A}{S}{P_RELATOR}{S}(?:[fF][oO][iI]|[eE][rR][aA]|[éÉeE]){S}{_O_A}{S}(?:{HONORIFICO}{S})?{P_MIN}{S}"
    # ``cujo relator, Ministro X,`` / ``cuja relatora, a Ministra X,`` (rodada 4, R6-06)
    rf"|[cC][uU][jJ]{_O_A}{S}{P_RELATOR},?{S}(?:{_O_A}{S})?(?:{HONORIFICO}{S})?{P_MIN}{S}"
    rf"|[cC][uU][jJ][aA]{S}{P_RELATORIA}{S}[cC][oO][uU][bB][eE]{S}(?:[aA][oO]|[àÀaA]){S}(?:{HONORIFICO}{S})?(?:{P_MIN}{S})?"
    rf"|[tT][eE][nN][dD][oO]{S}(?:[cC][oO][mM][oO]|[pP][oO][rR]){S}{P_RELATOR}{S}{_O_A}{S}(?:{HONORIFICO}{S})?{P_MIN}{S}"
    rf"|{_LAVRA}(?:{HONORIFICO}{S})?(?:{P_MIN}{S})?"
    r")"
)

#: Nome próprio do relator: 1–6 palavras iniciadas por maiúscula (ou partículas
#: ``de/da/do/dos/das/e`` em qualquer caixa entre elas), com ``\n`` permitido
#: entre palavras. Termina antes de ``,``, ``.``, palavra minúscula ou fim.
#: Palavras de parada evitam engolir ``DJe``, ``Turma`` etc. que possam seguir.
#: Palavras de parada do nome: rótulos que podem seguir o nome (``DJe``, ``Turma``), títulos
#: (``Min``, ``Des``, ``Exmo``) e inícios de frase comuns depois de uma quebra de linha
#: (``Quanto ao mais``, ``Nesse sentido``; revisão rodada 2): nenhuma é sobrenome corrente.
_PARADAS_NOME = (
    r"DJ[eEuU]?|DJE|Turma|TURMA|Se[çc][ãa]o|SE[ÇC][ÃA]O|Plen[áa]rio|PLEN[ÁA]RIO|Rel|REL|Min|MIN"
    r"|Exm[oa]|EXM[OA]|Sra?|Dra?|Des|DES|Eminente|Ilustre"
    r"|Quanto|Como|Assim|Ness[ea]|Nest[ea]|Dess[ea]|Ademais|Outrossim|Portanto|Logo|Ante|Diante"
    r"|Isso|Isto|Ora|Cumpre|Trata-se|Segundo|Conforme|Nos|Nas|Pelo|Pela|Tamb[ée]m|Todavia|Contudo"
    r"|Entretanto|Al[ée]m|Ap[óo]s|Sobre|Observe-se|Ressalte-se|Destaque-se|Frise-se|Note-se|Saliente-se"
    r"|Registre-se|Veja-se|Confira-se|Sendo|Para|Nada|Ainda|Ent[ãa]o|Aplica-se|Incide|Impende|Import[ae]"
    # ordinais de órgão fracionário e mais inícios de frase (revisão rodada 3, R5-07)
    r"|Primeir[oa]|Segund[oa]|Terceir[oa]|Quart[oa]|Quint[oa]|Sext[oa]|S[ée]tim[oa]|Oitav[oa]|Non[oa]|D[ée]cim[oa]"
    r"|N[ãa]o|Em|No|Na|Este|Esta|Esse|Essa|Cabe|H[áa]|[ÉE]|De|Os|As|Ali[áa]s|Com|Sem|Por|Se|Ao|Mas"
    r"|Ou|Que|Da|Do|Dos|Das|Aos|Um|Uma|Nem|Onde|Quando|Enquanto|Embora|Caso|Vide|Cf|Ver|Op|Apud|Idem"
    r"|Ibidem|Cfr|Ementa|EMENTA|Ac[óo]rd[ãa]o|AC[ÓO]RD[ÃA]O|Julgado|JULGADO|Publicado|PUBLICADO|Data|DATA"
    r"|Voto|VOTO|Relator[a]?|RELATOR[A]?|Tema|TEMA|S[úu]mula|S[ÚU]MULA|Processo|PROCESSO|Autos|AUTOS"
    r"|Outros|Outras|OUTROS|OUTRAS"   # ``Fulano e Outros`` é rol de partes, não relator (rodada 4, R6-14)
)
#: Depois da inicial, o nome admite os dígitos que o OCR põe no lugar de ``o``/``l``/``s``
#: (``J0se``, ``PACI0RNIK``; revisão rodada 3, R3-06) — nunca na inicial, que segue maiúscula.
#: Uma palavra do nome nunca é pronominal (``Ressalta-se``) nem seguida de ``:`` (``Julgamento:``;
#: rodada 4, R6-14).
_PALAVRA_NOME = (
    rf"(?!(?:{_PARADAS_NOME})(?![A-Za-zÀ-ÿ'’\-]))(?![A-Za-zÀ-ÿ]+-[sS][eE](?![A-Za-zÀ-ÿ]))"
    r"(?![A-Za-zÀ-ÿ015'’\-]+\s{0,2}:)[A-ZÀ-Ú][A-Za-zÀ-ÿ015'’\-]+"
)
#: Inicial abreviada antes de uma palavra do nome (``J. Paciornik``, ``Fulano A. Beltrano``; R4-06).
_INICIAL_NOME = r"(?:[A-ZÀ-Ú]\.\s{1,2}){0,2}"
#: Partículas do nome; ``dc``/``Dc`` é ``de`` com o OCR ``e``→``c`` (revisão R1-11).
_PARTICULA = r"(?:[dD][aeoAEOc]s?|[eE]|[yY]|[vV]on|[vV]an)"
#: Depois de uma QUEBRA DE LINHA o nome só continua se a palavra seguinte não abre frase
#: (``\nImportante``, ``\nHouve``, ``\nBrasília``, ``\nJulgamento``; rodada 4, R6-14). Nenhuma delas
#: é sobrenome corrente — ``Vale``/``Tal`` ficam de fora de propósito: a quebra dentro do nome é
#: mutação medida no dev (``Fulano de\nTal``).
_PARADAS_APOS_QUEBRA = (
    r"Import[ae]nte|Relevante|J[áa]|Mais|Houve|Un[âa]nime|Julgamento|Sess[ãa]o|Outros|Outras"
    r"|Bras[íi]lia|Vistos|Verifica|Cumpre|Foi|Feita|Fica|Fim|Deste|Desta|Assim|Pelo|Pela|Nesse|Nessa"
)
_SEPARADOR_NOME = (
    rf"(?:[ \t\xa0]{{1,2}}|\s{{0,2}}\n\s{{0,2}}(?!(?:{_PARADAS_APOS_QUEBRA})(?![A-Za-zÀ-ÿ'’\-])))"
)
NOME_RELATOR = (
    rf"{_INICIAL_NOME}{_PALAVRA_NOME}"
    rf"(?:(?:\s{{1,2}}{_PARTICULA})?{_SEPARADOR_NOME}{_INICIAL_NOME}{_PALAVRA_NOME}){{0,5}}"
)

# ===========================================================================
# 5. Diplomas (dispositivo)
# ===========================================================================

#: Número de lei com ano: ``13.105/2015``, ``8.078/90``, ``64/1990``, ``13.105, de 16
#: de março de 2015``, com OCR nos dígitos e quebra de linha antes do número.
_NUM_LEI = rf"{PREFIXO_OCR}\d[\d{LETRAS_OCR}]{{0,5}}(?:\.\s?[\d{LETRAS_OCR}]{{3}})*"   # ``l3.105`` (rodada 4, R6-09)
_ANO_LEI = r"(?:\d{4}|\d{2})"
_DATA_LEI = rf",?{S}{P_DE}{S}\d{{1,2}}{S}{P_DE}{S}[a-zç]+{S}{P_DE}{S}\d{{4}}"
#: ``Lei Federal nº``/``Lei Estadual``/``Lei Ordinária`` (revisão rodada 3, R3-07): o
#: adjetivo entra no span e ``normativos.diploma_canonico`` o ignora (lê o número da lei).
_TIPO_LEI = _alternancia([
    regex_extenso("lei complementar", inicial_maiuscula=False),
    regex_extenso("lei federal", inicial_maiuscula=False),
    regex_extenso("lei estadual", inicial_maiuscula=False),
    regex_extenso("lei municipal", inicial_maiuscula=False),
    regex_extenso("lei ordinaria", inicial_maiuscula=False),
    regex_extenso("decreto lei", inicial_maiuscula=False).replace(S, r"[\s\-]{1,2}", 1),
    regex_extenso("medida provisoria", inicial_maiuscula=False),
    regex_extenso("resolucao", inicial_maiuscula=False),
    regex_extenso("decreto", inicial_maiuscula=False),
    regex_extenso("lei", inicial_maiuscula=False),
    "LC", "DL", "MP",
])
LEI_NUMERADA = (
    r"(?:"
    rf"{_TIPO_LEI}"
    rf"{S0}(?:{CONECTOR}{S0})?{_NUM_LEI}"
    rf"(?:{S0}/{S0}{_ANO_LEI}|{_DATA_LEI}|,?{S}{P_DE}{S}\d{{4}})?"
    r")"
)

#: Nomes de diplomas (chave sem acento). Casados como os nomes por extenso das classes.
DIPLOMAS_EXTENSO: tuple[str, ...] = (
    "constituicao da republica federativa do brasil", "constituicao da republica",
    "constituicao federal", "constituicao", "carta magna", "lei maior", "lei fundamental",
    "texto constitucional",
    "codigo de processo civil", "novo codigo de processo civil", "novo cpc", "codigo de processo penal",
    "codigo de processo penal militar", "codigo penal militar", "codigo penal",
    "codigo de defesa do consumidor", "codigo de protecao e defesa do consumidor",
    "codigo do consumidor", "codigo civil", "codigo eleitoral", "codigo tributario nacional",
    "codigo de transito brasileiro", "codigo florestal", "codigo de aguas", "codigo brasileiro de aeronautica",
    "consolidacao das leis do trabalho", "consolidacao das leis trabalhistas", "leis trabalhistas", "lei das inelegibilidades", "lei de inelegibilidade",
    "lei de inelegibilidades", "lei de execucao penal", "lei de execucoes penais",
    "estatuto da crianca e do adolescente", "estatuto do idoso", "estatuto da cidade",
    "lei maria da penha", "lei de improbidade administrativa", "lei de licitacoes",
    "lei dos juizados especiais", "lei das eleicoes", "lei dos partidos politicos",
    "lei organica da magistratura nacional", "lei de drogas", "lei de falencias",
    "lei do inquilinato", "lei de introducao as normas do direito brasileiro",
    "regimento interno do supremo tribunal federal", "regimento interno do superior tribunal de justica",
    "regimento interno do tribunal superior eleitoral", "regimento interno do tribunal superior do trabalho",
    "regimento interno do superior tribunal militar",
)
#: Siglas de diplomas, com sufixo de ano opcional (``CF/88``, ``CPC/2015``, ``CC/02``).
DIPLOMAS_SIGLA: tuple[str, ...] = (
    "CRFB", "CF", "CPC", "NCPC", "CPP", "CPM", "CPPM", "CDC", "CLT", "CTN", "CTB", "ECA", "LEP",
    "CC", "CE", "CP", "LC", "LOMAN", "LINDB", "RISTF", "RISTJ", "RITSE", "RITST", "RISTM",
)
DIPLOMA_EXTENSO = _alternancia(
    [regex_extenso(n, inicial_maiuscula=False) for n in sorted(DIPLOMAS_EXTENSO, key=len, reverse=True)]
)
#: Sigla pontuada (``C.P.C.``, ``C.D.C.``, ``C.F.``; revisão rodada 3, R3-07): todos os pontos
#: internos são obrigatórios e o final é opcional (entra no span quando existe — ``do C.P.C.``).
def _sigla_pontuada(sigla: str) -> str:
    return r"\.".join(sigla) + r"\.?"


DIPLOMA_SIGLA = (
    _alternancia(sorted(DIPLOMAS_SIGLA, key=len, reverse=True) + [_sigla_pontuada(s) for s in DIPLOMAS_SIGLA])
    + rf"(?:/\d{{2,4}}|{S}{P_DE}{S}\d{{4}})?(?![A-Za-zÀ-ÿ])"   # ``CF/88``, ``CF de 1988`` (rodada 4, R4-07)
)
#: Diploma: lei numerada (vence: ``Lei Complementar nº 64/1990``), nome por extenso
#: (inclusive ``Constituição Fcderal``), sigla. Um nome por extenso pode ser
#: seguido de ``de 1988`` (``Constituição Federal de 1988``).
DIPLOMA = (
    r"(?:"
    rf"{LEI_NUMERADA}"
    rf"|{DIPLOMA_EXTENSO}(?:{S}{P_DE}{S}\d{{4}}|/\d{{2,4}})?(?![A-Za-zÀ-ÿ])"
    rf"(?:\s{{0,2}}\(\s{{0,2}}{LEI_NUMERADA}\s{{0,2}}\))?"   # ``Código de Processo Civil (Lei nº 13.105/2015)`` (R4-07)
    rf"|{DIPLOMA_SIGLA}"
    r")"
)

__all__ = [
    "S", "S0", "CONECTOR", "UF", "UF_LIMPA", "UF_COM_SEPARADOR", "LETRAS_OCR", "PREFIXO_OCR", "NUMERO", "NUMERO_REGISTRO",
    "ANO", "SIGLAS", "SIGLAS_SO_EM_HIFEN", "EXTENSOS", "EXTENSOS_PLURAL", "ORDINAL", "SIGLA", "SIGLA_HIFEN",
    "EXTENSO", "ELEMENTO", "LIGACAO", "CADEIA", "PREFIXO_TST", "PREFIXO_PROCESSO",
    "TRIBUNAL_SIGLA", "TRIBUNAL_EXTENSO", "TRIBUNAL", "P_REL", "P_MIN", "REL_MIN", "RELATORIA",
    "NOME_RELATOR", "ANO_OCR", "HONORIFICO", "ORGAO_FRACIONARIO",
    "LEI_NUMERADA", "DIPLOMAS_EXTENSO", "DIPLOMAS_SIGLA", "DIPLOMA_EXTENSO", "DIPLOMA_SIGLA",
    "DIPLOMA", "regex_sigla", "regex_extenso",
]
