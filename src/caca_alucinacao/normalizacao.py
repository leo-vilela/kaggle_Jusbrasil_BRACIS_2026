"""Normalização de superfície: a implementação ÚNICA usada por detecção, índice e consulta.

Este módulo absorve os protótipos ``base_canonica/digitos.py`` e
``base_canonica/classes.py`` (que hoje são apenas re-exports daqui). A regra de
ouro é que **o mesmo número escrito no cabeçalho de um acórdão e num parecer
com ruído de OCR produza a mesma chave**, e que **a mesma classe processual
escrita por extenso, em sigla, em caixa alta ou com pontos produza a mesma
cadeia canônica**. Toda função aqui é determinística, sem estado, sem ``print``
e sem regex de custo super-linear (ver ``tests/test_normalizacao.py``).

Três famílias de funções:

1. **Texto**: :func:`sem_acento`, :func:`chave_textual`, :func:`tolerante`.
2. **Números**: :func:`separar_uf`, :func:`corrigir_ocr_em_numero`,
   :func:`corrigir_ocr_em_grupo`, :func:`nucleos`, :func:`nucleo_principal`,
   :func:`digitos_do_identificador` (= :func:`digitos_canonicos`),
   :func:`classificar_digitos`, :func:`formato_de`, :func:`numeros_do_texto`,
   :func:`numeros_com_posicao`.
3. **Classes processuais e tribunal**: :func:`cadeia_de_classes`,
   :func:`cadeia_da_citacao`, :func:`classe_processual_canonica`,
   :func:`classe_principal`, :func:`classes_compativeis`,
   :func:`inferir_tribunal`, :func:`uf_de_estado`.

Os normativos (``diploma_canonico``, ``artigo_canonico``, ``sumula_canonica``)
vivem em ``base_canonica/normativos.py``, que importa este módulo — nunca o
contrário (sem ciclo de import; revisão R3-11).

Especificação medida nos dados: ``docs/03_analise_gabarito.md`` (§2, §3, §9.2)
e ``docs/04_analise_base.md`` (h.2, h.5–h.7). Decisão registrada em
``docs/decisoes/0001-normalizacao.md``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

# ===========================================================================
# Constantes compartilhadas
# ===========================================================================

#: As 27 unidades federativas. Lista FECHADA: só estas siglas são aceitas como
#: UF ao fim de um trecho de processo (``do STJ``, ``XX`` etc. nunca são UF).
UFS: frozenset[str] = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

#: Letras que o OCR confunde com dígitos (docs/03 §3.1). Só valem DENTRO de um
#: grupo numérico que começa por dígito ASCII; fora dele nunca são tocadas
#: (``AREspEl`` não vira ``AREsp1``; o ``S`` de ``/SP`` não vira ``5``).
#: Um dígito NUNCA é mapeado para outro dígito (garantia do desafio).
CONFUSOES: dict[str, str] = {
    "O": "0", "o": "0",
    "l": "1", "I": "1", "|": "1",
    "S": "5", "s": "5",
    "g": "9", "q": "9",
    "G": "6",
    "B": "8",
    "Z": "2", "z": "2",
}

# Vocabulário de formato do ÍNDICE (JSON versão 1; docs/04). Não alterar: o
# arquivo ``dados/indice.json`` e ``scripts/construir_indice.py`` dependem dele.
FORMATO_CNJ = "cnj"                # NNNNNNN-DD.AAAA.J.TR.OOOO → 20 dígitos
FORMATO_REGISTRO = "registro"      # STJ: AAAA/NNNNNNN-D → 12 dígitos
FORMATO_SEQUENCIAL = "sequencial"  # 1.234.567 / 12.345 / 42 → sem zeros à esquerda
FORMATO_OUTRO = "outro"            # mais de 20 dígitos ou vazio

# Vocabulário de formato do ``Achado`` (tipos.py: ``cnj20 | curto | registro``),
# usado pela detecção/resolução. :func:`formato_de` devolve este vocabulário.
FORMATO_CNJ20 = "cnj20"
FORMATO_CURTO = "curto"
FORMATO_ACHADO: dict[str, str] = {
    FORMATO_CNJ: FORMATO_CNJ20,
    FORMATO_SEQUENCIAL: FORMATO_CURTO,
    FORMATO_REGISTRO: FORMATO_REGISTRO,
    FORMATO_OUTRO: FORMATO_OUTRO,
}

TRIBUNAIS: tuple[str, ...] = ("STF", "STJ", "TSE", "TST", "STM")

# ===========================================================================
# 1. Texto
# ===========================================================================


def sem_acento(texto: str) -> str:
    """Remove diacríticos (``"Constituição"`` → ``"Constituicao"``).

    Usa decomposição NFD e descarta as marcas combinantes; ``º``/``ª`` não são
    marcas e permanecem (importante para reconhecer ``nº`` e ordinais).
    """
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


_RE_ESPACOS = re.compile(r"\s+")


def chave_textual(texto: str) -> str:
    """Minúsculas, sem acento, espaços (inclusive NBSP e quebras) colapsados.

    ``"Constituição  Federal\\n"`` → ``"constituicao federal"``. Serve de chave
    de comparação para nomes de diploma, palavras-chave e aliases; não remove
    pontuação (para isso a cadeia de classes tem a sua própria normalização).
    """
    return _RE_ESPACOS.sub(" ", sem_acento(texto).lower()).strip()


_RE_NAO_ALFANUM = re.compile(r"[^a-z0-9]+")


def _chave_tolerante(texto: str) -> str:
    """Chave para :func:`tolerante`: ``chave_textual`` + ``rn``→``m`` + só letras/dígitos."""
    t = chave_textual(texto).replace("rn", "m")
    return _RE_ESPACOS.sub(" ", _RE_NAO_ALFANUM.sub(" ", t)).strip()


def distancia_de_edicao(a: str, b: str, limite: int | None = None) -> int:
    """Distância de Levenshtein; com ``limite`` devolve ``limite + 1`` assim que o excede.

    Implementação por linhas (O(len(a)·len(b)) de tempo, O(len(b)) de memória);
    as entradas aqui são palavras curtas.
    """
    if a == b:
        return 0
    if limite is not None and abs(len(a) - len(b)) > limite:
        return limite + 1
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        if limite is not None and min(atual) > limite:
            return limite + 1
        anterior = atual
    return anterior[-1]


def tolerante(a: str, b: str, max_erros: int = 1) -> bool:
    """Igualdade de palavras/nomes tolerante ao ruído do nível 2.

    Regras (docs/03 §3.1, docs/04 f): acentos ignorados (``Fulãno`` =
    ``FULANO``), ``rn`` ≡ ``m`` (``assirn`` = ``assim``), caixa ignorada, e
    até ``max_erros`` edições (troca/inserção/remoção) **por palavra com ≥ 5
    letras** (``Fcderal`` = ``Federal``, ``Sobrlnho`` = ``Júnior``). Palavras
    curtas exigem igualdade exata (``dc`` ≠ ``de``: com 2 letras uma edição
    troca a palavra inteira). Ambos os lados precisam ter o mesmo número de
    palavras — comparação por *contenção* de sobrenomes é responsabilidade de
    ``consulta.relator_compativel``, não daqui.
    """
    ka, kb = _chave_tolerante(a), _chave_tolerante(b)
    if ka == kb:
        return bool(ka)
    pa, pb = ka.split(), kb.split()
    if len(pa) != len(pb) or not pa:
        return False
    for x, y in zip(pa, pb):
        if x == y:
            continue
        if len(x) < 5 or len(y) < 5:
            if max_erros >= 1 and _confusao_conhecida(x, y):
                continue
            return False
        if distancia_de_edicao(x, y, max_erros) > max_erros:
            return False
    return True


#: Pares de caracteres que o OCR confunde (docs/03 §3.1), já sem acento e em
#: minúsculas: ``e``↔``c``, ``i``↔``l``, ``o``↔``0``, ``s``↔``5``, ``b``↔``8``, ``g``↔``9``/``6``.
_CONFUSOES_CURTAS: frozenset[tuple[str, str]] = frozenset({
    ("e", "c"), ("c", "e"), ("i", "l"), ("l", "i"), ("o", "0"), ("0", "o"), ("s", "5"), ("5", "s"),
    ("b", "8"), ("8", "b"), ("g", "9"), ("9", "g"), ("g", "6"), ("6", "g"), ("i", "1"), ("1", "i"),
    ("l", "1"), ("1", "l"), ("z", "2"), ("2", "z"),
})


def _confusao_conhecida(x: str, y: str) -> bool:
    """Palavras curtas (3–4 letras) iguais a menos de UMA troca do mapa de confusões
    (``lcis`` = ``leis``, ``lci`` = ``lei``; revisão R2-04). Com 2 letras uma troca
    seria metade da palavra (``dc`` ≠ ``de``): exige-se igualdade exata."""
    if len(x) != len(y) or len(x) < 3:
        return False
    difs = [(a, b) for a, b in zip(x, y) if a != b]
    return len(difs) == 1 and difs[0] in _CONFUSOES_CURTAS


# ===========================================================================
# 2. Números
# ===========================================================================

_LETRAS_CONFUSAS = "".join(re.escape(c) for c in CONFUSOES)
#: Grupo bruto: dígitos e letras confundíveis colados (``34567l9``, ``No``, ``S``).
_RE_GRUPO = re.compile(rf"[0-9{_LETRAS_CONFUSAS}]+")
#: O que pode existir ENTRE dois grupos do mesmo núcleo: pontuação de milhar,
#: hífen (inclusive duplo), travessões, barra do registro, espaço, NBSP, quebra.
_RE_SEPARADORES = re.compile(r"^[\s\.,\-–—/⁄]+$")
_RE_REGISTRO_STJ = re.compile(r"^(19|20)\d{2}\d{7}\d$")
#: Entre letras confundíveis no lugar do primeiro dígito e o resto do número: nada ou um
#: sinal de pontuação (``l.234.567``, ``G2``); nunca branco (``SS 3.518`` é classe + número).
_RE_PONTO_DE_MILHAR = re.compile(r"^[.\-–]?$")

# UF ao FIM do trecho. Quantificadores limitados (nunca ``\s*``) para que a
# busca seja O(1) por posição; o ``search`` é feito só na cauda do trecho.
# Separadores medidos (docs/03 §2.4): ``/SP``, ``/ SP``, ``-SP``, `` - SP``,
# `` – SP``, `` (SP)``, ``\n- SP``; aceita-se também espaço/quebra simples.
# A UF admite o OCR ``S``→``5`` e ``O``→``0`` do nível 2 (``/5P``, ``- R0``; rodada 4, R6-08 — o
# mesmo mapa de ``deteccao.padroes.UF``): :func:`separar_uf` devolve a sigla canônica.
_UF_OCR = {"S": "[S5]", "O": "[O0]"}
# Colada ao último dígito (``1234567SP``) só a UF limpa: ``44974G0`` é um número com OCR, não ``GO``.
_RE_UF = re.compile(
    r"(?:(?:\s{0,4}[/\-–—]\s{0,4}|\s{0,4}\(\s{0,4}|\s{1,4})"
    r"(?P<uf>" + "|".join("".join(_UF_OCR.get(ch, ch) for ch in uf) for uf in sorted(UFS)) + r")"
    r"|(?<=\d)(?P<uf_colada>" + "|".join(sorted(UFS)) + r"))"
    r"\s{0,4}\)?\s{0,4}[\.,;]?\s{0,4}$"
)
_CAUDA_UF = 32  # tamanho máximo do sufixo em que a UF pode estar


@dataclass(frozen=True)
class Nucleo:
    """Um núcleo numérico encontrado num trecho.

    ``formato`` usa o vocabulário do índice (``cnj``/``sequencial``/``registro``/
    ``outro``); converta com :data:`FORMATO_ACHADO` ou :func:`formato_de` para
    o vocabulário do ``Achado``.

    ``ambiguo`` marca um núcleo que a normalização determinística **se recusa a
    ler** (``digitos == ""``): um grupo com maioria de letras confundíveis no
    meio do número (``1.GO1.157``), um segmento só de letras entre grupos
    numéricos (``2023.7.OO.0000``) ou letras confundíveis no lugar do primeiro
    dígito (``G2.471``). Nunca se emite uma chave parcial nesses casos — uma
    chave montada pulando um grupo cairia na faixa dos sequenciais e poderia
    casar com outro processo (revisão R2-01). A resolução tenta as conversões
    alternativas (``resolucao.chaves_alternativas``).
    """

    digitos: str      # dígitos canônicos (já preenchidos/normalizados); "" se ambíguo
    formato: str      # FORMATO_* (vocabulário do índice)
    inicio: int       # offset (codepoints) do primeiro caractere do núcleo no trecho
    fim: int          # offset exclusivo
    bruto: str        # texto original do núcleo
    n_digitos: int    # quantidade de dígitos ANTES do preenchimento (CNJ → 20); 0 se ambíguo
    ambiguo: bool = False


def separar_uf(trecho: str) -> tuple[str, str | None]:
    """``"REsp 1.234.567/SP"`` → ``("REsp 1.234.567", "SP")``; sem UF → ``(trecho, None)``.

    Regras e armadilhas:

    * **Chamar ANTES de corrigir OCR**: o ``S`` de ``/SP`` e o ``O`` de ``/RO``
      viraram dígitos se ainda estiverem colados ao número.
    * Só as 27 siglas de :data:`UFS`, só no **fim** do trecho (pontuação final
      ``.,;`` tolerada), com os separadores medidos em docs/03 §2.4 — inclusive
      ``\\n- SP`` e ``(SP)`` (o parêntese de fechamento é consumido).
    * O restante precisa conter ao menos um dígito: sem número não há UF a
      separar. Isso evita que ``"AgRg no MS"``/``"AgR-RO"`` percam a própria
      classe (``MS``, ``RO``, ``RR``, ``AC``, ``AP`` são siglas de classe *e* UF).
    * ``"art. 224 do CE"`` devolve ``("art. 224 do", "CE")``: em dispositivos o
      diploma é lido antes, por ``normativos.diploma_canonico``; esta função é
      para trechos da família ``processo``.
    """
    m = _RE_UF.search(trecho, max(0, len(trecho) - _CAUDA_UF))
    if not m:
        return trecho, None
    resto = trecho[: m.start()]
    if not any(c.isdigit() for c in resto):
        return trecho, None
    uf = (m.group("uf") or m.group("uf_colada")).replace("5", "S").replace("0", "O")   # ``5P`` → ``SP`` (R6-08)
    return resto, uf


def corrigir_ocr_em_grupo(grupo: str) -> str | None:
    """Dígitos de um grupo ``[0-9 + letras confundíveis]``; ``None`` se não for numérico.

    Um grupo é numérico quando tem pelo menos um dígito real e as letras
    confundíveis não são maioria (evita ``No``, ``SS``, ``Os`` virarem número).
    Esta é a regra usada dentro de um núcleo já aberto por um dígito (ver
    :func:`nucleos`); ``normativos`` também a usa para números de lei/artigo.
    """
    n_dig = sum(c.isdigit() for c in grupo)
    n_let = len(grupo) - n_dig
    if n_dig == 0 or n_let > n_dig:
        return None
    return "".join(CONFUSOES.get(c, c) for c in grupo)


def corrigir_ocr_em_numero(grupo: str) -> str:
    """``"34567l9"`` → ``"3456719"``; ``"1.46g.781"`` → ``"1.469.781"``; ``"AREspEI"`` → inalterado.

    Aplica :data:`CONFUSOES` apenas quando a cadeia **começa por dígito ASCII**
    (docs/03 §3.1: ``DO5`` e ``C0NTROVÉRSIA`` não podem virar número) e, dentro
    dela, só em grupos que contêm dígitos e não têm maioria de letras.
    Pontuação e espaços são preservados (a função corrige, não extrai: use
    :func:`digitos_do_identificador` para obter a chave). Um dígito nunca é
    alterado. Chame :func:`separar_uf` antes se o trecho puder terminar em UF.
    """
    if not grupo or not grupo[0].isdigit():
        return grupo

    def _troca(m: re.Match[str]) -> str:
        corrigido = corrigir_ocr_em_grupo(m.group(0))
        return corrigido if corrigido is not None else m.group(0)

    return _RE_GRUPO.sub(_troca, grupo)


def classificar_digitos(digitos: str) -> tuple[str, str]:
    """Regras 4–6 de docs/02: ``(digitos_canonicos, formato_do_indice)``.

    * 14–20 dígitos → CNJ, preenchido a 20 com zeros à esquerda (o sequencial
      pode ter 1–7 dígitos: ``12-34.2011.6.05.0099``);
    * 12 dígitos começando por ano → registro do STJ (``2019/0123456-7``);
    * caso contrário, sequencial sem zeros à esquerda (``1.234.567`` → ``1234567``;
      ``0036`` → ``36``); vazio ou > 20 dígitos → ``outro``.
    """
    n = len(digitos)
    if n == 0:
        return "", FORMATO_OUTRO
    if 14 <= n <= 20:
        return digitos.zfill(20), FORMATO_CNJ
    if n == 12 and _RE_REGISTRO_STJ.match(digitos):
        return digitos, FORMATO_REGISTRO
    if n > 20:
        return digitos, FORMATO_OUTRO
    return digitos.lstrip("0") or "0", FORMATO_SEQUENCIAL


def formato_de(digitos: str) -> str:
    """Formato de uma chave de dígitos no vocabulário do ``Achado``.

    ``"12345678920257000000"`` → ``"cnj20"``; ``"1234567"`` → ``"curto"``;
    ``"201901234567"`` → ``"registro"``; ``""``/não numérico/> 20 → ``"outro"``.
    Aceita dígitos ainda não canônicos (17 dígitos de CNJ → ``"cnj20"``).
    ``"curto"`` cobre todo sequencial (na prática 4–7 dígitos; 2–3 só em
    classes raras do STJ como ``Nº 42``).
    """
    if not digitos or not digitos.isdigit():
        return FORMATO_OUTRO
    return FORMATO_ACHADO[classificar_digitos(digitos)[1]]


def _e_letra(c: str) -> bool:
    return bool(c) and c.isalpha() and c not in "ºª°"


def _primeiro_digito(grupo: str) -> int:
    for i, c in enumerate(grupo):
        if c.isdigit():
            return i
    return -1


#: Tamanho máximo de um segmento só de letras confundíveis dentro de um número
#: (``S`` no lugar do dígito J do CNJ, ``OO`` no lugar de ``00``, ``lO``).
_MAX_LETRAS_SEGMENTO = 3
#: Idem para o grupo FINAL do número (``1.140.OSl``, ``.OlOO`` do CNJ; revisão
#: rodada 2, R4-01): só quando colado ao grupo anterior por UM sinal de pontuação.
_MAX_LETRAS_GRUPO_FINAL = 4
_PONTUACAO_DE_GRUPO = ".-–"
#: O que pode preceder letras confundíveis no lugar do primeiro dígito (``nº G2.471``,
#: ``REsp l.234.567``, ``- lO.345``): nunca uma letra (``AI12345``, ``No1234``).
_ANTES_DO_PREFIXO = " \t\n\xa0º°.-–—/("


def _so_confundiveis(grupo: str) -> bool:
    return bool(grupo) and all(c in CONFUSOES for c in grupo)


def nucleos(trecho: str) -> list[Nucleo]:
    """Todos os núcleos numéricos do trecho, na ordem em que aparecem.

    Um núcleo é uma sequência de grupos numéricos unidos apenas por pontuação,
    espaço, NBSP ou quebra de linha (``1.234.567``, ``7000769-81 2021 7 00
    0000``, ``33.-\\n479``, ``0600457-13.2020-\\n.6.14.0022``). Regras:

    * o núcleo **abre num dígito ASCII**: letras confundíveis coladas a uma
      letra comum nunca são tocadas (``No``, ``l`` de ``EDcl``, ``AREspEl``);
    * dentro do núcleo, um grupo é aceito se contém dígito e as letras não são
      maioria (``46g`` → ``469``);
    * um grupo com dígitos mas **maioria de letras** (``GO1``), um segmento só de
      letras confundíveis (≤ 3) entre dois grupos numéricos (``2016.S.00``,
      ``7.OO.0000``), um grupo **final** só de letras confundíveis (≤ 4) colado
      por um sinal de pontuação (``1.140.OSl``; revisão rodada 2, R4-01) ou
      letras confundíveis no lugar do primeiro dígito precedidas de
      branco/conector (``G2.471``, ``l.234.567``) tornam o núcleo **ambíguo**:
      ele é devolvido com ``digitos == ""`` e ``ambiguo=True`` e cobre o número
      inteiro. Nunca se fecha o núcleo no meio para abrir outro no dígito
      seguinte (isso produzia chaves parciais — revisão R2-01);
    * um grupo não numérico ou um separador inesperado (``" D"`` de ``DO STJ``,
      ``" ("``, ``S`` de ``- SP`` sem dígito depois) fecha o núcleo;
    * um núcleo com **menos de 4 dígitos colado a uma letra** é descartado —
      é dígito dentro de palavra (``DO5``, ``5alvador``, ``C0NTROVÉRSIA``), não
      número; ``Nº42`` e ``art.5`` (colados a ``º``/``.``) continuam válidos.

    **Não** separa a UF: chame :func:`separar_uf` antes se o trecho puder
    terminar em UF (``"1234/SP"`` produziria ``12345``).
    """
    saida: list[Nucleo] = []
    atual: list[str] = []
    ambiguo = False
    ini = fim = -1
    ultimo_fim = -1
    grupos = list(_RE_GRUPO.finditer(trecho))

    def fechar() -> None:
        nonlocal atual, ambiguo
        if atual:
            brutos = "".join(atual)
            antes = trecho[ini - 1] if ini > 0 else ""
            depois = trecho[fim] if fim < len(trecho) else ""
            if ambiguo:
                saida.append(Nucleo("", FORMATO_OUTRO, ini, fim, trecho[ini:fim], 0, True))
            elif not (len(brutos) < 4 and (_e_letra(antes) or _e_letra(depois))):
                digitos, formato = classificar_digitos(brutos)
                saida.append(Nucleo(digitos, formato, ini, fim, trecho[ini:fim], len(brutos)))
            atual = []
            ambiguo = False

    def continua_com_digito(j: int, colado: bool = False) -> bool:
        """O grupo ``j+1`` existe, contém dígito e está unido ao grupo ``j`` só por separadores
        (com ``colado``, só por um sinal de pontuação: ``l.234``, nunca ``SS 3.518``)."""
        if j + 1 >= len(grupos):
            return False
        prox = grupos[j + 1]
        entre = trecho[grupos[j].end():prox.start()]
        if colado:
            return bool(_RE_PONTO_DE_MILHAR.match(entre)) and any(c.isdigit() for c in prox.group(0))
        return bool(entre) and bool(_RE_SEPARADORES.match(entre)) and any(c.isdigit() for c in prox.group(0))

    for j, m in enumerate(grupos):
        grupo, g_ini, g_fim = m.group(0), m.start(), m.end()
        entre = trecho[ultimo_fim:g_ini] if ultimo_fim >= 0 else ""
        ultimo_fim = g_fim
        if atual and _RE_SEPARADORES.match(entre):
            dig = corrigir_ocr_em_grupo(grupo)
            if dig is not None:
                atual.append(dig)
                fim = g_fim
                continue
            tem_digito = any(c.isdigit() for c in grupo)
            if tem_digito or (_so_confundiveis(grupo) and len(grupo) <= _MAX_LETRAS_SEGMENTO
                              and continua_com_digito(j)):
                # maioria de letras com dígito, ou segmento só de letras entre grupos numéricos
                ambiguo = True
                atual.append(grupo)
                fim = g_fim
                continue
            if (_so_confundiveis(grupo) and len(grupo) <= _MAX_LETRAS_GRUPO_FINAL
                    and entre in _PONTUACAO_DE_GRUPO):
                # grupo final só de letras confundíveis colado por um sinal de pontuação
                # ("1.140.OSl"): o número continua e o núcleo é ambíguo — fechá-lo antes
                # produziria a chave parcial "1140" (revisão rodada 2, R4-01)
                ambiguo = True
                atual.append(grupo)
                fim = g_fim
                continue
        fechar()
        k = _primeiro_digito(grupo)
        if k < 0:
            # letras confundíveis no lugar do primeiro dígito ("G2" já tem dígito; aqui é "l" de "l.234")
            antes = trecho[g_ini - 1] if g_ini > 0 else ""
            if (_so_confundiveis(grupo) and len(grupo) <= _MAX_LETRAS_SEGMENTO
                    and (g_ini == 0 or antes in _ANTES_DO_PREFIXO) and continua_com_digito(j, colado=True)):
                atual, ambiguo, ini, fim = [grupo], True, g_ini, g_fim
            continue
        antes = trecho[g_ini - 1] if g_ini > 0 else ""
        if k > 0 and len(grupo[:k]) <= _MAX_LETRAS_SEGMENTO and (g_ini == 0 or antes in _ANTES_DO_PREFIXO):
            # "G2.471", "lO345": letras confundíveis coladas ao primeiro dígito, precedidas de branco
            atual, ambiguo, ini, fim = [grupo], True, g_ini, g_fim
            continue
        dig = corrigir_ocr_em_grupo(grupo[k:])
        if dig is None:
            continue
        atual = [dig]
        ini, fim = g_ini + k, g_fim
    fechar()
    return saida


def nucleo_principal(trecho: str) -> Nucleo | None:
    """O núcleo que identifica o processo; ``None`` se não há dígitos.

    Escolhe o **primeiro núcleo com ≥ 4 dígitos** (docs/04 h.4: quando a
    citação traz número e registro do STJ, ``REsp 1.234.567 - PR
    (2019/0123456-7)``, o número vem primeiro e é a chave preferida). Sem
    núcleo de 4 dígitos, o de mais dígitos (empate → o primeiro): cobre
    ``Nº 42`` e ``Súmula 7``. Um núcleo ambíguo (``digitos == ""``, ver
    :class:`Nucleo`) conta como 0 dígitos: ``digitos_do_identificador`` devolve
    ``""`` para ``"REsp nº 1.OO1.140"`` — nunca a chave parcial ``1140``.
    """
    todos = nucleos(trecho)
    if not todos:
        return None
    for n in todos:
        if n.n_digitos >= 4:
            return n
    melhor = todos[0]
    for n in todos[1:]:
        if n.n_digitos > melhor.n_digitos:
            melhor = n
    return melhor


def digitos_do_identificador(trecho: str) -> str:
    """Núcleo numérico canônico do identificador citado (``""`` se não há).

    Pipeline (docs/03 §9.2): :func:`separar_uf` → :func:`nucleos` (correção de
    OCR só dentro do grupo que começa com dígito; remoção de ``.``, ``-``,
    ``–``, espaço, NBSP e ``\\n``) → :func:`nucleo_principal` →
    :func:`classificar_digitos` (CNJ → 20 dígitos; registro → 12; curto como está).

    Exemplos: ``"AgInt no RESP 34567l9 - SP"`` → ``"3456719"``;
    ``"APL 1234567-89 2021 7 00 0000/BA"`` → ``"12345678920217000000"``;
    ``"TST-ED-E-ED-ARR-1234-56.2011.5.02.\\n0251"`` → ``"00012345620115020251"``
    (o prefixo ``TST-…-`` e ``processo nº`` não têm dígitos e ficam fora).
    """
    sem_uf, _ = separar_uf(trecho)
    n = nucleo_principal(sem_uf)
    return n.digitos if n else ""


#: Nome usado pelo índice/consulta (mesma função).
digitos_canonicos = digitos_do_identificador


_RE_NUMERO_CORPO = re.compile(
    r"(?<![\d])"
    r"(?:\d{1,7}\s?-\s?\d{2}\s?\.\s?\d{4}\s?\.\s?\d\s?\.\s?\d{2}\s?\.\s?\d{4}"  # CNJ pontuado
    r"|\d{4}\s?[/⁄]\s?\d{7}\s?-\s?\d"                                         # registro STJ
    r"|\d{1,3}(?:\.\d{3}){1,2}"                                               # 1.234.567 / 12.345
    r"|\d{4,20})"                                                              # dígitos corridos
    r"(?![\d\.]\d)"
)


def numeros_com_posicao(texto: str) -> list[tuple[int, int, str, str]]:
    """Números "limpos" do corpo de um texto: ``(inicio, fim, digitos, formato_do_indice)``.

    Versão conservadora, **sem correção de OCR** (o corpo dos acórdãos da base é
    texto digital, exceto o TSE): CNJ pontuado, registro do STJ, número com
    pontos de milhar ou ≥ 4 dígitos corridos. Serve para medir a armadilha
    "quem cita vs. quem é" (quantos registros mencionam um número no corpo) e
    para indexar; nunca para resolver uma citação — para isso use
    :func:`digitos_do_identificador`.
    """
    saida: list[tuple[int, int, str, str]] = []
    for m in _RE_NUMERO_CORPO.finditer(texto):
        bruto = m.group(0)
        dig = "".join(c for c in bruto if c.isdigit())
        digitos, formato = classificar_digitos(dig)
        if formato == FORMATO_OUTRO:
            continue
        saida.append((m.start(), m.end(), digitos, formato))
    return saida


def numeros_do_texto(texto: str) -> list[str]:
    """Todos os números canônicos do texto, na ordem da primeira ocorrência, sem repetição.

    ``"RECURSO ESPECIAL Nº 1.234.567 - PR (2019/0123456-7)"`` →
    ``["1234567", "201901234567"]``. Projeção de :func:`numeros_com_posicao`.
    """
    vistos: set[str] = set()
    saida: list[str] = []
    for _, _, dig, _ in numeros_com_posicao(texto):
        if dig not in vistos:
            vistos.add(dig)
            saida.append(dig)
    return saida


# ===========================================================================
# 3. Classes processuais
# ===========================================================================

# (alias normalizado, cadeia canônica). Aliases multi-palavra têm precedência
# (casamento pelo mais longo). Normalização: minúsculas, sem acento, pontuação
# e hífens viram espaço, espaços colapsados. As siglas canônicas são as do
# índice (``ED``, ``AGR``, ``AGINT``, ``RESP``, ``ARESP``, ``RESPE`` …) e NÃO
# podem mudar sem reconstruir ``dados/indice.json``.
_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    # órgãos julgadores que precedem a classe no cabeçalho: cadeia vazia
    ("primeira turma", ()), ("segunda turma", ()), ("terceira turma", ()),
    ("quarta turma", ()), ("quinta turma", ()), ("sexta turma", ()),
    ("setima turma", ()), ("oitava turma", ()), ("tribunal pleno", ()),
    ("plenario", ()), ("corte especial", ()), ("primeira secao", ()),
    ("segunda secao", ()), ("terceira secao", ()),
    # prefixos / incidentes
    ("agravo regimental", ("AGR",)), ("agrg", ("AGR",)), ("agr", ("AGR",)),
    ("ag reg", ("AGR",)), ("agreg", ("AGR",)), ("ag regimental", ("AGR",)),
    ("agravo interno", ("AGINT",)), ("agint", ("AGINT",)), ("ag int", ("AGINT",)),
    ("embargos de declaracao", ("ED",)), ("embargos declaratorios", ("ED",)),
    ("embargos de declaracao criminal", ("ED",)), ("edcl", ("ED",)), ("ed", ("ED",)),
    ("eds", ("ED",)), ("emb decl", ("ED",)), ("embdecl", ("ED",)), ("emb de decl", ("ED",)),
    ("embargos de divergencia", ("EDV",)), ("edv", ("EDV",)), ("emb div", ("EDV",)),
    ("embdiv", ("EDV",)),
    ("questao de ordem", ("QO",)), ("qo", ("QO",)),
    ("pedido de extensao", ("PEXT",)), ("pext", ("PEXT",)),
    ("referendo", ("REF",)),
    # STF / STJ
    ("recurso especial", ("RESP",)), ("resp", ("RESP",)), ("r esp", ("RESP",)),
    ("rec esp", ("RESP",)), ("rec especial", ("RESP",)), ("recurso esp", ("RESP",)),
    ("agravo em recurso especial", ("ARESP",)), ("aresp", ("ARESP",)), ("a resp", ("ARESP",)),
    ("agresp", ("ARESP",)), ("ag resp", ("ARESP",)),
    ("embargos de divergencia em recurso especial", ("ERESP",)),
    ("embargos de divergencia em resp", ("ERESP",)), ("eresp", ("ERESP",)),
    ("embargos de divergencia em agravo em recurso especial", ("EARESP",)),
    ("earesp", ("EARESP",)),
    ("recurso extraordinario", ("RE",)), ("re", ("RE",)),
    ("recurso extraordinario com agravo", ("ARE",)), ("are", ("ARE",)),
    ("reclamacao", ("RCL",)), ("rcl", ("RCL",)), ("recl", ("RCL",)),
    ("reclamacao constitucional", ("RCL",)),
    ("habeas corpus", ("HC",)), ("hc", ("HC",)), ("h c", ("HC",)),
    ("habeas corpus criminal", ("HC",)),
    ("recurso em habeas corpus", ("RHC",)), ("rhc", ("RHC",)),
    ("recurso ordinario em habeas corpus", ("RHC",)),
    ("recurso em mandado de seguranca", ("RMS",)), ("rms", ("RMS",)),
    ("recurso ordinario em mandado de seguranca", ("RMS",)),
    ("recurso ord em mandado de seguranca", ("RMS",)),
    ("mandado de seguranca", ("MS",)), ("ms", ("MS",)), ("mandado de seguranca civel", ("MS",)),
    ("acao rescisoria", ("AR",)), ("ar", ("AR",)),
    ("acao penal", ("AP",)), ("ap", ("AP",)),
    ("acao direta de inconstitucionalidade", ("ADI",)), ("adi", ("ADI",)), ("adin", ("ADI",)),
    ("arguicao de descumprimento de preceito fundamental", ("ADPF",)), ("adpf", ("ADPF",)),
    ("acao declaratoria de constitucionalidade", ("ADC",)), ("adc", ("ADC",)),
    ("conflito de competencia", ("CC",)), ("cc", ("CC",)),
    ("suspensao de liminar e de sentenca", ("SLS",)), ("sls", ("SLS",)),
    ("suspensao de seguranca", ("SS",)), ("ss", ("SS",)),
    ("suspensao de liminar", ("SL",)), ("sl", ("SL",)),
    ("peticao", ("PET",)), ("pet", ("PET",)),
    ("cautelar inominada criminal", ("CAUTINOM",)), ("cautelar inominada", ("CAUTINOM",)),
    # TSE
    ("recurso especial eleitoral", ("RESPE",)), ("respe", ("RESPE",)), ("respel", ("RESPE",)),
    ("resp eleitoral", ("RESPE",)), ("recurso esp eleitoral", ("RESPE",)),
    ("agravo em recurso especial eleitoral", ("ARESPE",)), ("arespe", ("ARESPE",)),
    ("arespel", ("ARESPE",)), ("arespei", ("ARESPE",)),  # "AREspEI": OCR l→I na sigla
    ("a respe", ("ARESPE",)),
    ("recurso ordinario", ("RO",)), ("ro", ("RO",)), ("recurso ordinario eleitoral", ("RO",)),
    ("roel", ("RO",)), ("ro el", ("RO",)),
    ("agravo de instrumento", ("AI",)), ("ai", ("AI",)),
    ("acao de investigacao judicial eleitoral", ("AIJE",)), ("aije", ("AIJE",)),
    ("recurso contra expedicao de diploma", ("RCED",)), ("rced", ("RCED",)),
    ("prestacao de contas", ("PC",)), ("pc", ("PC",)),
    ("acao cautelar", ("AC",)), ("ac", ("AC",)),
    ("lista triplice", ("LT",)), ("lt", ("LT",)),
    ("tutela cautelar antecedente", ("TUTCAUT",)),
    ("representacao", ("RP",)), ("rp", ("RP",)),
    ("recurso na representacao", ("RRP",)), ("r rp", ("RRP",)), ("rrp", ("RRP",)),
    # STM
    ("apelacao", ("APL",)), ("apl", ("APL",)), ("apelacao criminal", ("APL",)),
    ("embargos infringentes e de nulidade", ("EI",)), ("embargos infringentes", ("EI",)),
    ("ei", ("EI",)), ("emb infr", ("EI",)), ("embinfr", ("EI",)),
    # 2º grau (fora da base; só para que a cadeia não fique vazia — revisão rodada 2, R4-12)
    ("apelacao civel", ("APC",)), ("agravo de peticao", ("AGPET",)), ("recurso inominado", ("RI",)),
    ("remessa necessaria", ("REMNEC",)),
    ("recurso em sentido estrito", ("RSE",)), ("rse", ("RSE",)),
    ("conflito de jurisdicao", ("CJ",)), ("cj", ("CJ",)),
    ("correicao parcial", ("CP",)), ("correicao parcial militar", ("CP",)),
    ("representacao p declaracao de indignidade incompatibilidade", ("RDI",)),
    ("representacao para declaracao de indignidade incompatibilidade", ("RDI",)),
    ("representacao para declaracao de indignidade", ("RDI",)),
    # TST (nomes por extenso e tokens do prefixo TST-…)
    ("recurso de revista", ("RR",)), ("rr", ("RR",)),
    ("agravo de instrumento em recurso de revista", ("AIRR",)), ("airr", ("AIRR",)),
    ("recurso de revista com agravo", ("ARR",)), ("arr", ("ARR",)), ("rrag", ("RRAG",)),
    ("recurso ordinario trabalhista", ("ROT",)), ("rot", ("ROT",)),
    ("recurso ordinario em acao rescisoria", ("ROT",)),
    ("embargos", ("E",)), ("emb", ("E",)), ("e", ("E",)),
    ("agravo", ("AG",)), ("ag", ("AG",)),
    ("edciv", ("EDCIV",)),
    # cadeias coladas frequentes nos prefixos do TST
    ("agarr", ("AG", "ARR")), ("agairr", ("AG", "AIRR")), ("agrr", ("AG", "RR")),
    ("agrrag", ("AG", "RRAG")), ("edairr", ("ED", "AIRR")), ("edrr", ("ED", "RR")),
]

# Ordinais por extenso → token da cadeia (``"2O"``). Distinguem decisões
# sucessivas no mesmo processo (``SEGUNDO AG.REG.`` × ``AG.REG.``, STF).
_ORDINAIS: dict[str, str] = {
    "segundo": "2O", "segunda": "2O", "segundos": "2O", "segundas": "2O",
    "terceiro": "3O", "terceira": "3O", "terceiros": "3O",
    "quarto": "4O", "quarta": "4O", "quartos": "4O",
    "quinto": "5O", "quinta": "5O", "quintos": "5O",
    "sexto": "6O", "sextos": "6O", "setimo": "7O", "setimos": "7O",
    "oitavo": "8O", "oitavos": "8O", "nono": "9O", "nonos": "9O",
    "decimo": "10O", "decimos": "10O",
}
#: Ordinal numérico (``2º``, ``3ª``, ``10o``) já convertido por ``_normalizar_mantendo_caixa``.
_RE_ORDINAL_NUMERICO = re.compile(r"(\d{1,2})[oa]")

# Classes equivalentes para comparação "frouxa" (a classe principal casa mesmo
# com nomenclatura diferente entre eras/tribunais).
_EQUIVALENTES: list[frozenset[str]] = [
    frozenset({"RESP", "RESPE"}),
    frozenset({"ARESP", "ARESPE"}),
    frozenset({"AGR", "AGINT", "AG"}),
    # TST: o número CNJ identifica o caso; RR → AIRR → ARR/RRAg → Ag-AIRR são
    # etapas do mesmo processo e a citação pode usar qualquer uma delas
    frozenset({"RR", "AIRR", "ARR", "RRAG", "ROT", "E", "EDCIV"}),
]

#: Plurais dos nomes por extenso (``Recursos Especiais 1/SP e 2/RJ``, ``Reclamações``; rodada 4,
#: R6-02) → alias singular. Só citações usam o plural; nenhum cabeçalho da base o traz.
_ALIASES_PLURAL: dict[str, str] = {
    "recursos especiais eleitorais": "recurso especial eleitoral", "recursos especiais": "recurso especial",
    "agravos em recurso especial": "agravo em recurso especial",
    "agravos em recursos especiais": "agravo em recurso especial",
    "embargos de divergencia em recursos especiais": "embargos de divergencia em recurso especial",
    "recursos extraordinarios com agravo": "recurso extraordinario com agravo",
    "recursos extraordinarios": "recurso extraordinario", "reclamacoes constitucionais": "reclamacao",
    "reclamacoes": "reclamacao", "recursos ordinarios em habeas corpus": "recurso ordinario em habeas corpus",
    "recursos em habeas corpus": "recurso em habeas corpus",
    "recursos ordinarios em mandado de seguranca": "recurso ordinario em mandado de seguranca",
    "recursos em mandado de seguranca": "recurso em mandado de seguranca",
    "mandados de seguranca": "mandado de seguranca", "acoes rescisorias": "acao rescisoria",
    "acoes penais": "acao penal", "acoes diretas de inconstitucionalidade": "acao direta de inconstitucionalidade",
    "conflitos de competencia": "conflito de competencia", "agravos regimentais": "agravo regimental",
    "agravos internos": "agravo interno", "recursos ordinarios": "recurso ordinario",
    "agravos de instrumento em recurso de revista": "agravo de instrumento em recurso de revista",
    "agravos de instrumento": "agravo de instrumento", "apelacoes criminais": "apelacao criminal",
    "apelacoes civeis": "apelacao civel", "apelacoes": "apelacao", "recursos de revista": "recurso de revista",
    "agravos": "agravo", "peticoes": "peticao", "representacoes": "representacao",
}

_ALIAS_POR_CHAVE: dict[str, tuple[str, ...]] = {}
_MAX_TOKENS = 1
for _chave, _cadeia in _ALIASES:
    _ALIAS_POR_CHAVE[_chave] = _cadeia
    _MAX_TOKENS = max(_MAX_TOKENS, len(_chave.split()))
for _plural, _singular in _ALIASES_PLURAL.items():
    _ALIAS_POR_CHAVE[_plural] = _ALIAS_POR_CHAVE[_singular]
    _MAX_TOKENS = max(_MAX_TOKENS, len(_plural.split()))

#: Aliases com ≥ 6 letras, por número de palavras, para o casamento tolerante ao OCR
#: (``recurso espccial``, ``rcclamacao``; revisão rodada 2, R4-08). Aliases curtos
#: (``resp``, ``ag int``) ficam de fora: uma edição trocaria a sigla inteira.
_MIN_LETRAS_TOLERANTE = 6
#: ``(inicial, nº de palavras) → aliases``: a inicial nunca sofre OCR (a regex do detector a
#: exige exata) e serve de pré-filtro; ``tolerante`` só corre sobre poucos candidatos.
_ALIASES_TOLERANTES: dict[tuple[str, int], list[str]] = {}
for _chave in _ALIAS_POR_CHAVE:
    if sum(c.isalpha() for c in _chave) >= _MIN_LETRAS_TOLERANTE:
        _ALIASES_TOLERANTES.setdefault((_chave[0], len(_chave.split())), []).append(_chave)
_RE_SO_LETRAS_E_ESPACO = re.compile(r"^[a-z]+(?: [a-z]+)*$")


@lru_cache(maxsize=8192)
def _alias_tolerante(chave: str) -> str | None:
    """Alias que casa com ``chave`` a menos de uma edição por palavra (:func:`tolerante`).

    ``"recurso espccial"`` → ``"recurso especial"``; ``"agravo intcrno"`` → ``"agravo
    interno"``; ``"rcclamacao"`` → ``"reclamacao"``. Só para chaves com ≥ 6 letras, só
    letras/espaços e mesma inicial; devolve ``None`` quando nenhum ou mais de um alias
    casa (ambiguidade nunca é resolvida por chute). Cache: os mesmos tokens repetem-se
    milhares de vezes nos cabeçalhos da base.
    """
    if len(chave) < _MIN_LETRAS_TOLERANTE or not _RE_SO_LETRAS_E_ESPACO.match(chave):
        return None
    candidatos = [al for al in _ALIASES_TOLERANTES.get((chave[0], chave.count(" ") + 1), ())
                  if abs(len(al) - len(chave)) <= 2 and tolerante(chave, al)]
    cadeias = {_ALIAS_POR_CHAVE[al] for al in candidatos}
    return candidatos[0] if len(cadeias) == 1 else None

# siglas "curtas" (sem espaço) para decompor tokens colados como "AgARR"
_SIGLAS_COLAVEIS: dict[str, tuple[str, ...]] = {
    k: v for k, v in _ALIAS_POR_CHAVE.items() if " " not in k and len(k) >= 2
}

SIGLAS_CANONICAS: frozenset[str] = frozenset(s for _, c in _ALIASES for s in c)

_RE_PONTUACAO_CLASSE = re.compile(r"[\.\-–—/,;:()\[\]'\"ºª°]+")
_RE_ORDINAL_SUFIXO = re.compile(r"(?<=\d)[ºª°]")
_RE_MINUSCULA_COLADA_A_SIGLA = re.compile(r"([a-z])([A-Z]{3,})(?![a-z])")
_RE_TOKEN_CANONICO = re.compile(r"\d+O")


def _normalizar(texto: str) -> str:
    t = sem_acento(texto).lower()
    t = _RE_PONTUACAO_CLASSE.sub(" ", t)
    return _RE_ESPACOS.sub(" ", t).strip()


def _decompor_colado(token: str) -> tuple[str, ...] | None:
    """``"agarr"`` → ``("AG", "ARR")`` por programação dinâmica; ``None`` se impossível."""
    n = len(token)
    melhor: list[tuple[str, ...] | None] = [None] * (n + 1)
    melhor[0] = ()
    for i in range(1, n + 1):
        candidatos: list[tuple[str, ...]] = []
        for j in range(0, i):
            if melhor[j] is None:
                continue
            pedaco = token[j:i]
            if pedaco in _SIGLAS_COLAVEIS:
                candidatos.append(melhor[j] + _SIGLAS_COLAVEIS[pedaco])
        if candidatos:
            melhor[i] = min(candidatos, key=len)
    return melhor[n] or None


def _parece_sigla(original: str) -> bool:
    """Sigla colada (``AgARR``, ``EDAIRR``), não uma palavra comum em caixa alta."""
    resto = original[1:]
    if not any(c.isupper() for c in resto):
        return False
    if any(c.islower() for c in original):
        return len(original) <= 8
    return len(original) <= 6


def _parece_sigla_no_plural(stem: str) -> bool:
    """``REsp``/``HC``/``Rcl``/``MS`` (o que precede o ``s`` de plural): sigla colada ou sigla de
    inicial maiúscula com ≥ 3 letras (``Rcls``; rodada 4, R6-07) — nunca ``res``/``ares``."""
    return _parece_sigla(stem) or (len(stem) >= 3 and stem[0].isupper() and stem[1:].islower())


def _desfazer_ocr_em_palavra(token: str) -> str:
    """``DECLARAcA0`` → ``DECLARAcAo``: dígito dentro de palavra (maioria de letras) vira letra.

    Só age quando há ≥ 3 letras e os dígitos não são maioria — um número com uma
    letra de OCR (``34567l9``) passa intacto.
    """
    letras = sum(c.isalpha() for c in token)
    digitos = sum(c.isdigit() for c in token)
    if digitos == 0 or letras < 3 or digitos > letras:
        return token
    return token.translate(str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b"}))


#: Confusões de OCR dentro de siglas, já em minúsculas (revisão R2-02): dígito ou
#: ``l`` no lugar de uma letra. Cada variante troca TODAS as ocorrências de um
#: caractere; siglas têm ≤ 8 letras e uma troca por sigla é o caso medido.
_OCR_SIGLA_INVERSO: tuple[tuple[str, str], ...] = (
    ("5", "s"), ("0", "o"), ("1", "i"), ("1", "l"), ("l", "i"), ("i", "l"), ("8", "b"), ("6", "g"),
    ("9", "g"), ("2", "z"),
)


def _variantes_ocr_sigla(token: str) -> list[str]:
    """``"aglnt"`` → ``["agint", …]``: variantes com uma confusão de OCR desfeita."""
    if len(token) < 3 or (token.isalpha() and not any(c in token for c in "li")):
        return []
    saida: list[str] = []
    for de, para in _OCR_SIGLA_INVERSO:
        if de in token:
            v = token.replace(de, para)
            if v != token and v not in saida:
                saida.append(v)
    return saida


def _normalizar_mantendo_caixa(texto: str) -> list[str]:
    t = sem_acento(texto)
    # "nosEMBARGOS" / "AgARR": palavra minúscula colada a sigla maiúscula
    t = _RE_MINUSCULA_COLADA_A_SIGLA.sub(r"\1 \2", t)
    # "2º"/"3ª" → "2o"/"3a": preserva o ordinal numérico antes de apagar a pontuação
    t = _RE_ORDINAL_SUFIXO.sub("o", t)
    t = _RE_PONTUACAO_CLASSE.sub(" ", t)
    return [_desfazer_ocr_em_palavra(tok) for tok in t.split()]


def cadeia_de_classes(texto: str) -> list[str]:
    """Cadeia canônica de siglas do texto de classe processual.

    ``"EDcl no AgInt no AREsp"`` → ``["ED", "AGINT", "ARESP"]``;
    ``"TST-Ag-ED-AIRR"`` → ``["AG", "ED", "AIRR"]``;
    ``"Terceiro AG.REG na Rcl"`` → ``["3O", "AGR", "RCL"]``;
    ``"2º AgRg no RE"`` → ``["2O", "AGR", "RE"]``.

    Regras:

    * casamento pelo alias mais longo (``"Recurso Especial Eleitoral"`` é
      ``RESPE``, não ``RESP`` + ruído); caixa, acentos, pontos (``Rec. Esp.``,
      ``H.C.``, ``AG.REG``), hífens e quebras de linha (``Recurso\\nEspecial``)
      são indiferentes;
    * tokens desconhecidos (``PRIMEIRA``, ``TURMA``, ``no``, ``na``, ``nos``,
      ``em``, ``nº``, ``processo``, ``TST``) são ignorados; ``E`` só é Embargos
      (TST) quando grafado em maiúscula isolada;
    * siglas coladas (``AgARR``, ``EDAIRR``) são decompostas;
    * ordinais por extenso ou numéricos viram token próprio (``2O``);
    * **depois de um token numérico, siglas que também são UF são ignoradas**:
      em ``"Rcl 12.345/AC"`` o ``AC`` é Acre, não Ação Cautelar (o mesmo vale
      para ``MS``, ``RO``, ``RR``, ``AP``). Ainda assim, para citações completas
      prefira :func:`cadeia_da_citacao`, que separa a UF antes.

    Usada tanto para o cabeçalho dos acórdãos (nomes por extenso, em caixa
    alta) quanto para citações (siglas com ruído) — as siglas canônicas são as
    gravadas em ``dados/indice.json``.
    """
    originais = _normalizar_mantendo_caixa(texto)
    tokens = [t.lower() for t in originais]
    cadeia: list[str] = []
    apos_numero = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if apos_numero and originais[i].upper() in UFS and len(tok) == 2:
            i += 1
            continue
        casou = False
        for k in range(min(_MAX_TOKENS, len(tokens) - i), 0, -1):
            chave = " ".join(tokens[i : i + k])
            if chave not in _ALIAS_POR_CHAVE and k == 1:
                # sigla com OCR ("aglnt", "rc1", "ar3sp"): desfaz as confusões conhecidas
                chave = next((v for v in _variantes_ocr_sigla(chave) if v in _ALIAS_POR_CHAVE), chave)
            if chave not in _ALIAS_POR_CHAVE and k == 1 and len(chave) >= 3 and chave.endswith("s") \
                    and chave[:-1] in _ALIAS_POR_CHAVE and _parece_sigla_no_plural(originais[i][:-1]):
                # plural colado à sigla ("REsps", "HCs", "RRs", "Rcls"; revisão rodada 2, R4-15; rodada 4, R6-07)
                chave = chave[:-1]
            if chave not in _ALIAS_POR_CHAVE:
                # nome por extenso com OCR ("Recurso Espccial", "Agravo Intcrno"; revisão rodada 2, R4-08)
                chave = _alias_tolerante(chave) or chave
            if chave in _ALIAS_POR_CHAVE:
                # "e" só é Embargos (TST) quando grafado "E" maiúsculo isolado
                if chave == "e" and originais[i] != "E":
                    break
                cadeia.extend(_ALIAS_POR_CHAVE[chave])
                i += k
                casou = True
                break
        if casou:
            continue
        if tok in _ORDINAIS:
            cadeia.append(_ORDINAIS[tok])
        elif (m := _RE_ORDINAL_NUMERICO.fullmatch(tok)):
            cadeia.append(f"{int(m.group(1))}O")
        elif tok == "e":
            pass
        elif tok[0].isdigit():
            apos_numero = True
        elif len(tok) >= 4 and tok.isalpha() and _parece_sigla(originais[i]):
            dec = _decompor_colado(tok)
            if dec:
                cadeia.extend(dec)
        i += 1
    return cadeia


def cadeia_da_citacao(trecho: str) -> list[str]:
    """Cadeia canônica de um trecho de citação completo (classe + número + UF).

    Separa a UF antes (:func:`separar_uf`) e então aplica
    :func:`cadeia_de_classes`: ``"AgInt no AREsp nº 2.345.678/RJ"`` →
    ``["AGINT", "ARESP"]``; ``"MS 12.345/RO"`` → ``["MS"]``.
    """
    sem_uf, _ = separar_uf(trecho)
    return cadeia_de_classes(sem_uf)


def como_cadeia(valor: Sequence[str] | str | None) -> list[str]:
    """Aceita cadeia já canônica (lista ou ``"AGINT ARESP"``) ou texto bruto.

    Texto cujos tokens são todos siglas canônicas (ou ordinais ``2O``) é
    devolvido tal qual; qualquer outra coisa passa por :func:`cadeia_da_citacao`.
    """
    if not valor:
        return []
    if not isinstance(valor, str):
        return [str(s) for s in valor]
    tokens = valor.split()
    if all(t in SIGLAS_CANONICAS or _RE_TOKEN_CANONICO.fullmatch(t) for t in tokens):
        return tokens
    return cadeia_da_citacao(valor)


def classe_principal(cadeia: Sequence[str]) -> str | None:
    """Último elemento da cadeia que não seja ordinal (``["2O", "AGR", "RCL"]`` → ``"RCL"``)."""
    for s in reversed(cadeia):
        if not s.endswith("O") or not s[:-1].isdigit():
            return s
    return None


def classe_processual_canonica(trecho: str) -> str | None:
    """Sigla canônica da classe PRINCIPAL de uma citação.

    ``"Rec. Esp. n. 3.456.789 (SC)"`` → ``"RESP"``; ``"AgInt no AREsp nº
    2.345.678/RJ"`` → ``"ARESP"``; ``"Súmula 456 do TST"`` → ``None``.
    A UF é separada antes (``"Rcl 12.345/AC"`` → ``"RCL"``, não ``"AC"``).
    """
    return classe_principal(cadeia_da_citacao(trecho))


def classes_compativeis(a: str | None, b: str | None) -> bool:
    """Classe principal citada × própria: iguais ou equivalentes.

    ``RESP`` ≈ ``RESPE``, ``ARESP`` ≈ ``ARESPE``, ``AGR`` ≈ ``AGINT`` ≈ ``AG`` e
    toda a família do TST (``RR`` ≈ ``AIRR`` ≈ ``ARR`` ≈ ``RRAG`` …). ``None``
    nunca é compatível.
    """
    if a is None or b is None:
        return False
    if a == b:
        return True
    return any(a in grupo and b in grupo for grupo in _EQUIVALENTES)


# ---------------------------------------------------------------------------
# Tribunal implícito (docs/04 h.2)
# ---------------------------------------------------------------------------

#: Segmento J do CNJ (``NNNNNNN-DD.AAAA.J.TR.OOOO``, posição 13 dos 20 dígitos).
#: STF e STJ nunca são citados por CNJ na base (J=1/3 não inferem nada).
_TRIBUNAL_POR_J: dict[str, str] = {"5": "TST", "6": "TSE", "7": "STM"}

#: Classes principais EXCLUSIVAS de um tribunal: listadas em docs/04 h.2 e com
#: um único tribunal entre os números próprios da base. Ficam de fora, por
#: serem ambíguas, ``RCL``, ``HC``, ``MS``, ``AR``, ``AP``, ``PET``, ``RMS``
#: (há um RMS do STF na base), ``AGINT``/``ED`` (principais só no STM, mas
#: prefixos em todos os outros) e os prefixos em geral.
_TRIBUNAL_POR_CLASSE: dict[str, str] = {
    # STJ
    "RESP": "STJ", "ARESP": "STJ", "ERESP": "STJ", "EARESP": "STJ", "RHC": "STJ",
    # STF
    "RE": "STF", "ARE": "STF", "ADI": "STF", "ADPF": "STF", "ADC": "STF",
    # TSE
    "RESPE": "TSE", "ARESPE": "TSE", "RO": "TSE", "AI": "TSE", "AIJE": "TSE",
    "RCED": "TSE", "PC": "TSE", "LT": "TSE", "RP": "TSE", "RRP": "TSE", "TUTCAUT": "TSE",
    # TST
    "RR": "TST", "AIRR": "TST", "ARR": "TST", "RRAG": "TST", "ROT": "TST",
    # STM
    "APL": "STM", "RSE": "STM", "EI": "STM", "RDI": "STM", "CJ": "STM", "CP": "STM",
}


def inferir_tribunal(
    cadeia: Sequence[str] | str | None,
    uf: str | None = None,
    digitos: str = "",
    formato: str | None = None,
) -> str | None:
    """Tribunal implícito na citação, ou ``None`` quando não é seguro inferir.

    Ordem (docs/04 h.2):

    1. **CNJ** (``formato`` ``cnj``/``cnj20`` ou dígitos de 14–20): o segmento
       J decide — 5 → TST, 6 → TSE, 7 → STM. Vence a classe, porque um AREsp
       ou RHC com CNJ ``.6.`` é do TSE (existem na base), não do STJ. STF e
       STJ nunca são inferidos por CNJ (nunca são citados assim).
    2. **Classe principal exclusiva** (:data:`_TRIBUNAL_POR_CLASSE`): ``REsp``,
       ``AREsp``, ``RHC``, ``EREsp`` → STJ; ``RE``, ``ARE``, ``ADI``, ``ADPF`` →
       STF; ``REspe``, ``AREspEl``, ``RO``, ``AI`` → TSE; ``RR``, ``AIRR``,
       ``ARR`` → TST; ``APL``, ``RSE``, ``EI`` → STM.
    3. ``Rcl``, ``HC``, ``MS``, ``AR``, ``RMS`` e prefixos (``AgInt``, ``EDcl``)
       → ``None``: ambíguos entre tribunais.

    ``uf`` não decide nada (STF, STJ, TSE e STM têm UF; TST não) e existe na
    assinatura para regras futuras/registro em ``Achado.dados``. Um tribunal
    inferido errado é caro (descarta o candidato certo ⇒ ``inventada`` = FN +
    FP), por isso a lista é conservadora.
    """
    del uf  # reservado: não há regra segura baseada só na UF
    fmt = formato
    canon = ""
    if digitos and digitos.isdigit():
        canon, fmt_digitos = classificar_digitos(digitos)
        if fmt is None:
            fmt = fmt_digitos
    if fmt in (FORMATO_CNJ, FORMATO_CNJ20) and len(canon) == 20:
        tribunal = _TRIBUNAL_POR_J.get(canon[13])
        if tribunal:
            return tribunal
    principal = classe_principal(como_cadeia(cadeia))
    if principal is None:
        return None
    return _TRIBUNAL_POR_CLASSE.get(principal)


# ---------------------------------------------------------------------------
# Estados → UF (cabeçalhos do STF e do TSE trazem o nome por extenso)
# ---------------------------------------------------------------------------
ESTADOS: dict[str, str] = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distritofederal": "DF", "espiritosanto": "ES", "goias": "GO",
    "maranhao": "MA", "matogrosso": "MT", "matogrossodosul": "MS", "minasgerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
    "riodejaneiro": "RJ", "riograndedonorte": "RN", "riograndedosul": "RS",
    "rondonia": "RO", "roraima": "RR", "santacatarina": "SC", "saopaulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}

_RE_SO_LETRAS = re.compile(r"[^a-z]")


def uf_de_estado(nome: str) -> str | None:
    """``"RIO DE JANEIRO"`` → ``"RJ"``; tolera OCR leve (``"PARAN„"``, ``"M A R A N H Ã O"``).

    Distância de edição contra os 27 nomes (tolerância de 1 erro a cada 5
    letras), com desempate por prefixo (``"paran"`` → Paraná, não Pará).
    """
    chave = _RE_SO_LETRAS.sub("", sem_acento(nome).lower())
    if not chave:
        return None
    if chave in ESTADOS:
        return ESTADOS[chave]
    if chave.upper() in ESTADOS.values() and len(chave) == 2:
        return chave.upper()
    melhor, dist, prefixo = None, 99, False
    for nome_estado, uf in ESTADOS.items():
        d = distancia_de_edicao(chave, nome_estado)
        # empate: prefere o nome de que a chave é prefixo ("paran" → "parana", não "para")
        pref = nome_estado.startswith(chave)
        if d < dist or (d == dist and pref and not prefixo):
            melhor, dist, prefixo = uf, d, pref
    if melhor and dist <= max(1, len(chave) // 5):
        return melhor
    return None


__all__ = [
    # constantes
    "UFS", "CONFUSOES", "TRIBUNAIS", "ESTADOS", "SIGLAS_CANONICAS",
    "FORMATO_CNJ", "FORMATO_REGISTRO", "FORMATO_SEQUENCIAL", "FORMATO_OUTRO",
    "FORMATO_CNJ20", "FORMATO_CURTO", "FORMATO_ACHADO",
    # texto
    "sem_acento", "chave_textual", "tolerante", "distancia_de_edicao",
    # números
    "Nucleo", "separar_uf", "corrigir_ocr_em_grupo", "corrigir_ocr_em_numero",
    "classificar_digitos", "formato_de", "nucleos", "nucleo_principal",
    "digitos_do_identificador", "digitos_canonicos", "numeros_com_posicao", "numeros_do_texto",
    # classes e tribunal
    "cadeia_de_classes", "cadeia_da_citacao", "como_cadeia", "classe_principal",
    "classe_processual_canonica", "classes_compativeis", "inferir_tribunal", "uf_de_estado",

]
