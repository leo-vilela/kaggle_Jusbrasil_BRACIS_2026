"""Leitura dos ``.txt`` e anatomia mínima do documento (cabeçalho × prosa).

Contrato (docs/02 §texto.py):

* :func:`carregar` lê os bytes como UTF-8 **sem** traduzir ``\\r\\n`` e **sem**
  normalizar (nem NFC): os offsets e o ``trecho`` emitido são sempre relativos
  ao arquivo original, e ``trecho == texto[inicio:fim]`` tem de valer contra o
  arquivo; texto fora de NFC só gera aviso. É o único carregador do pacote
  (``pipeline.carregar_texto`` delega aqui);
* :func:`documento_id` é o ``stem`` do arquivo;
* :func:`nivel_do_documento` lê o nível do ``documento_id`` (``gen_n2_003`` →
  2, ``sin_n3_agressivo_007`` → 3, senão 1);
* :func:`linhas_com_offsets` devolve ``(inicio, fim, linha)`` por linha;
* :func:`fim_do_cabecalho` devolve o offset onde começa a prosa (docs/03 §6.1):
  tudo antes dele é zona de distratores (``Autos nº``, ``Protocolo``, ``Valor
  da causa``, ``PARECER JURÍDICO Nº``) e nenhum span pode começar ali.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger(__name__)

#: Linha ``Chave: valor`` do cabeçalho (``Autoridade coatora: …``, ``Assunto: …``,
#: ``Referência: autos nº …``, ``Elaborado por: …``). Mesmo longa e em minúsculas
#: não é prosa. A chave começa em maiúscula e tem até 40 caracteres.
_RE_CHAVE_VALOR = re.compile(r"^[A-ZÀ-Ú][\wÀ-ÿ .()/\-]{0,40}:\s")
#: ``Recorrente – Fulano de Tal, brasileiro, casado…``: parte do cabeçalho com travessão no lugar dos
#: dois-pontos (rodada 4, R4-04). Só o travessão (nunca o hífen) e chave de ≤ 3 palavras: uma frase de
#: prosa com aposto (``Cuida-se de habeas corpus – o paciente…``) tem mais palavras antes dele.
_RE_CHAVE_TRAVESSAO = re.compile(r"^[A-ZÀ-Ú][\wÀ-ÿ]*(?:\s[\wÀ-ÿ().]+){0,2}\s[–—]\s")
#: ``Relatório: trata-se de…``/``Ementa: …``/``Voto: …``: a "chave" é um título de seção da
#: peça e o que segue é prosa (com ≥ 60 caracteres) — não é ``Chave: valor`` do cabeçalho
#: (revisão rodada 2, R4-09-a).
_RE_TITULO_DE_SECAO = re.compile(
    r"^(?:Relat[óo]rio|Ementa|Voto|Fundamenta[çc][ãa]o|M[ée]rito|Preliminar(?:es)?|Dos?\s+fatos|Dos?\s+direito"
    r"|Dispositivo|Conclus[ãa]o|Decis[ãa]o|Raz[õo]es|S[íi]ntese|Resumo|Hist[óo]rico|Introdu[çc][ãa]o)\s*:\s", re.I)
#: Duas palavras minúsculas consecutivas: o sinal mais barato de prosa corrente. O lookbehind ancora
#: o início da palavra — sem ele a busca é quadrática numa corrida longa de minúsculas (100 KB → 134 s;
#: rodada 4, R3q-04) — e a busca é limitada aos primeiros :data:`JANELA_PROSA` caracteres da linha.
_RE_PROSA = re.compile(r"(?<![a-zà-ú])[a-zà-ú]{3,}\s+[a-zà-ú]{2,}")
JANELA_PROSA = 2000
#: Nível do documento no id (``_n2_``, ``gen_n1_003``, ``sin_n3_agressivo_001``).
_RE_NIVEL = re.compile(r"(?:^|_)n([1-9])(?:_|$)")

#: Tamanho mínimo da primeira linha de prosa (docs/03 §6.1: ≥ 60 caracteres).
TAMANHO_MINIMO_PROSA = 60
#: Teto de segurança: o cabeçalho das peças tem 171–281 caracteres no dev; se a
#: heurística passar deste ponto, algo está errado (documento de parágrafos
#: curtos) e é melhor não perder citações do que eliminar distratores.
LIMITE_CABECALHO = 1500
#: Limiar relaxado usado só quando o teto é ultrapassado.
TAMANHO_MINIMO_PROSA_RELAXADO = 30


#: Uma sequência UTF-8 multibyte válida (2–4 bytes): sinal de que o arquivo é UTF-8 com bytes espúrios,
#: não cp1252 (R3q-05).
_RE_UTF8_MULTIBYTE = re.compile(rb"[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3}")


def carregar(caminho: Path | str) -> str:
    """Texto do arquivo (ver :func:`carregar_com_codificacao`)."""
    return carregar_com_codificacao(caminho)[0]


def carregar_com_codificacao(caminho: Path | str) -> tuple[str, str]:
    """``(texto, codificação usada)`` — ``"utf-8"``, ``"cp1252"`` ou ``"utf-8-replace"``.

    Texto do arquivo em codepoints, UTF-8, tal como está no disco (sem normalização).

    ``read_bytes().decode("utf-8")`` (nunca ``open(..., "r")``: a tradução de
    ``\\r\\n`` deslocaria os offsets). Bytes inválidos são substituídos por
    U+FFFD com aviso — o documento continua processável. O BOM, se existir,
    é mantido (offset 0 = BOM). Nenhuma normalização Unicode é aplicada.
    """
    caminho = Path(caminho)
    bruto = caminho.read_bytes()
    codificacao = "utf-8"
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        # ERROR (não WARNING): o desafio garante UTF-8. Antes da substituição por U+FFFD, tenta
        # cp1252 (latin-1 estendido): nele cada byte é um codepoint, então os offsets de quem
        # produziu o gabarito nessa codificação coincidem com os do texto decodificado (rodada 3,
        # R3e-08). Mas só quando o arquivo é INTEIRAMENTE cp1252 — sem nenhuma sequência UTF-8
        # multibyte válida (rodada 4, R3q-05): um UTF-8 com um único byte espúrio decodificado como
        # cp1252 deslocaria TODOS os offsets (cada acento viraria 2 codepoints); nele ``replace``
        # troca só o byte inválido por U+FFFD e preserva os demais offsets.
        if _RE_UTF8_MULTIBYTE.search(bruto) is None:
            try:
                texto = bruto.decode("cp1252")
                codificacao = "cp1252"
                log.error("%s não é UTF-8 válido; decodificado como cp1252 (%d byte(s) fora do ASCII): "
                          "confira a codificação do lote", caminho, sum(1 for b in bruto if b >= 0x80))
            except UnicodeDecodeError:
                texto = ""
        if codificacao == "utf-8":
            texto = bruto.decode("utf-8", errors="replace")
            codificacao = "utf-8-replace"
            log.error("%s não é UTF-8 válido; decodificado com substituição (%d caractere(s) U+FFFD): "
                      "citações podem ser perdidas", caminho, texto.count("\ufffd"))
    if texto.startswith("﻿"):
        log.warning("%s começa com BOM; mantido (offset 0 = BOM)", caminho)
    if unicodedata.normalize("NFC", texto) != texto:
        # nunca normaliza: o ``trecho`` emitido tem de ser texto[inicio:fim] do arquivo original
        log.warning("%s não está em NFC; offsets e trechos seguem o arquivo tal como lido", caminho)
    return texto, codificacao


def documento_id(caminho: Path | str) -> str:
    """``dados/txt/gen_n2_003.txt`` → ``"gen_n2_003"``."""
    return Path(caminho).stem


def nivel_do_documento(doc_id: str) -> int:
    """``"gen_n2_003"`` → 2; ``"sin_n3_agressivo_001"`` → 3; sem marca → 1."""
    m = _RE_NIVEL.search(doc_id)
    return int(m.group(1)) if m else 1


def linhas_com_offsets(texto: str) -> list[tuple[int, int, str]]:
    """``(inicio, fim, linha)`` por linha, fim exclusivo e sem o ``\\n``.

    ``"ab\\ncd"`` → ``[(0, 2, "ab"), (3, 5, "cd")]``. A soma ``fim - inicio``
    mais as quebras reconstrói o texto; nunca há tradução de ``\\r``.
    """
    saida: list[tuple[int, int, str]] = []
    pos = 0
    for linha in texto.split("\n"):
        saida.append((pos, pos + len(linha), linha))
        pos += len(linha) + 1
    return saida


#: Palavras gramaticais que a prosa corrente tem em abundância e uma ementa nominal quase não tem.
_FUNCIONAIS_CAIXA_ALTA = frozenset(
    "DE DA DO DAS DOS QUE A O E EM NO NA NOS NAS COM POR PARA SE AO AOS À ÀS OS AS PELO PELA PELOS PELAS UM UMA "
    "NÃO É FOI FORAM SER SEU SUA SEUS SUAS ESTE ESTA ESSE ESSA COMO MAS OU QUANDO ONDE JÁ AINDA".split()
)
#: Sinais de oração (pronome relativo, negação, verbo de ligação, pronominal ``-SE``): um endereçamento
#: (``EXCELENTÍSSIMO SENHOR JUIZ DE DIREITO DA VARA CÍVEL DA COMARCA DE …``) tem muitas preposições e
#: nenhum deles; a prosa tem ao menos um.
_SINAIS_DE_ORACAO = frozenset("QUE SE NÃO É FOI FORAM ERA ERAM ESTÁ ESTÃO HÁ COMO MAS OU QUANDO ONDE JÁ".split())
_RE_PALAVRA_CAIXA_ALTA = re.compile(r"[A-ZÀ-Ú]+(?:-[A-ZÀ-Ú]+)?")
_RE_FRASES_CAIXA_ALTA = re.compile(r"\.\s+(?=[A-ZÀ-Ú])")
MINIMO_PALAVRAS_CAIXA_ALTA = 10
RAZAO_FUNCIONAIS_CAIXA_ALTA = 0.30
MINIMO_PALAVRAS_POR_FRASE_CAIXA_ALTA = 7.0


def _e_prosa_em_caixa_alta(s: str) -> bool:
    """Parágrafo de prosa inteiramente em CAIXA ALTA (revisão rodada 3, R3-10).

    Uma ementa em caixa alta (``PROCESSUAL CIVIL. AGRAVO INTERNO. ÔNUS DA PROVA.``) é feita
    de fragmentos nominais curtos; a prosa (``TRATA-SE DE RECURSO INTERPOSTO CONTRA ACÓRDÃO
    QUE MANTEVE A DECISÃO DE ORIGEM``) tem frases longas e ≥ 30 % de palavras gramaticais
    (``DE``, ``QUE``, ``A``, ``PELOS``…). Exige ≥ 10 palavras, razão ≥ 0,30, ≥ 7 palavras
    por frase em média e ao menos um sinal de oração (``QUE``, ``SE``, ``NÃO``, ``É``, ``-SE``),
    que um endereçamento cheio de ``DE``/``DA`` não tem; ``Chave: valor`` (``EMENTA: …``) nunca
    entra aqui.
    """
    palavras = _RE_PALAVRA_CAIXA_ALTA.findall(s)
    if len(palavras) < MINIMO_PALAVRAS_CAIXA_ALTA:
        return False
    funcionais = sum(1 for w in palavras if w in _FUNCIONAIS_CAIXA_ALTA)
    if funcionais / len(palavras) < RAZAO_FUNCIONAIS_CAIXA_ALTA:
        return False
    if not any(w in _SINAIS_DE_ORACAO or w.endswith("-SE") for w in palavras):
        return False
    frases = len(_RE_FRASES_CAIXA_ALTA.findall(s)) + 1
    return len(palavras) / frases >= MINIMO_PALAVRAS_POR_FRASE_CAIXA_ALTA


def e_linha_de_prosa(linha: str, minimo: int = TAMANHO_MINIMO_PROSA) -> bool:
    """Primeira linha de prosa segundo docs/03 §6.1.

    ≥ 60 caracteres, com duas palavras minúsculas consecutivas, não toda em
    caixa alta e que **não** seja ``Chave: valor`` (``Assunto: viabilidade da
    tese…`` tem 80 caracteres em minúsculas e ainda é cabeçalho). Exceção (rodada 3):
    um parágrafo de prosa todo em caixa alta (:func:`_e_prosa_em_caixa_alta`).
    """
    s = linha.strip()
    if len(s) < minimo:
        return False
    if _RE_TITULO_DE_SECAO.match(s):
        # ``Relatório: trata-se de…``/``Ementa: …`` com ≥ 60 caracteres: título de seção seguido de
        # prosa (R4-09-a, rodada 2) — salvo quando o que segue tem a FORMA de ementa (fragmentos
        # nominais: ``Ementa: Apelação. Estelionato. Recurso desprovido.``), que é cabeçalho em qualquer
        # caixa, com ou sem rótulo (uma só política para ementas; rodada 4, R4-04)
        if _tem_forma_de_ementa(s):
            return False
        if s != s.upper():
            return bool(_RE_PROSA.search(s[:JANELA_PROSA]))
    elif _RE_CHAVE_VALOR.match(s):
        return False
    if _RE_CHAVE_TRAVESSAO.match(s):
        return False   # ``Recorrente – Fulano de Tal, brasileiro…`` (rodada 4, R4-04)
    if s == s.upper():   # toda em caixa alta (``Nº``/``2ª`` não contam como minúsculas)
        return _e_prosa_em_caixa_alta(s)
    return bool(_RE_PROSA.search(s[:JANELA_PROSA]))


#: Frase curta de prosa (``Cuida-se de habeas corpus.``): termina em pontuação de fim
#: de frase e tem ≥ 15 caracteres.
_RE_FIM_DE_FRASE = re.compile(r"[.;!?]\s*$")
TAMANHO_MINIMO_FRASE_CURTA = 15


_RE_PALAVRA_MINUSCULA = re.compile(r"(?<![\wÀ-ÿ])[a-zà-ú]+(?![\wÀ-ÿ])")


def _e_frase_curta_de_prosa(linha: str) -> bool:
    """``Cuida-se de habeas corpus.``/``Invoca-se o RHC 64.123/RS.``: ≥ 15 caracteres,
    termina em pontuação de frase, tem ≥ 2 palavras minúsculas, não é caixa alta
    nem ``Chave: valor``."""
    s = linha.strip()
    if len(s) < TAMANHO_MINIMO_FRASE_CURTA or not _RE_FIM_DE_FRASE.search(s) or s.isupper():
        return False
    if _RE_CHAVE_VALOR.match(s) or _RE_CHAVE_TRAVESSAO.match(s):
        return False
    return len(_RE_PALAVRA_MINUSCULA.findall(s[:JANELA_PROSA])) >= 2


#: Linha do cabeçalho que identifica os autos (``Autos nº …``, ``Processo: …``,
#: ``Referência: …``) ou qualquer ``Chave: valor``.
_RE_LINHA_DE_AUTOS = re.compile(r"^(?:Autos|Processo|Proc\.?|Refer[êe]ncia|Ref\.?)\b", re.I)
_RE_FRASES = re.compile(r"[.;]\s+")
LINHAS_ATE_OS_AUTOS = 6
#: Linha de identificação dos autos que começa por classe processual (por extenso ou sigla) +
#: conector + número CNJ (``Apelação Cível nº 1234567-89.2021.8.26.0114 da Comarca de …, em que
#: é apelante …``): mesmo longa e em caixa mista, nas primeiras linhas é cabeçalho (rodada 3, R5-05).
_RE_LINHA_DE_IDENTIFICACAO = re.compile(
    r"^[A-ZÀ-Ú][A-Za-zÀ-ÿ. ]{1,40}?\s(?:n\.?\s?[º°o]\.?\s*|n\.\s*|N\.?\s?[º°o]\.?\s*)?\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}"
)
LINHAS_DE_IDENTIFICACAO = 8
#: ``Autos nº <CNJ>``/``Processo: <CNJ>``/``Referência: autos nº <CNJ>`` com o número CNJ na linha.
_RE_AUTOS_COM_CNJ = re.compile(
    r"^(?:Autos|Processo|Proc\.?|Refer[êe]ncia|Ref\.?)\b.{0,60}?\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", re.I)


def _e_linha_de_identificacao(linha: str) -> bool:
    """``Apelação Cível nº <CNJ> …`` ou ``Autos nº <CNJ>``: identificação dos autos."""
    s = linha.strip()
    return bool(_RE_LINHA_DE_IDENTIFICACAO.match(s) or _RE_AUTOS_COM_CNJ.match(s))


def _fim_das_linhas_de_identificacao(linhas: list[tuple[int, int, str]]) -> int:
    """Início da linha seguinte à ÚLTIMA linha de identificação/``Chave: valor``/autos entre as
    primeiras 8 (0 se nenhuma): fallback quando a prosa está além do teto (rodada 4, R4-04) — a zona
    de distratores cobre ao menos o bloco de identificação, em vez de nada."""
    fim = 0
    for inicio, fim_linha, linha in linhas[:LINHAS_DE_IDENTIFICACAO]:
        s = linha.strip()
        if s and (_e_linha_de_identificacao(s) or _RE_LINHA_DE_AUTOS.match(s) or _RE_CHAVE_VALOR.match(s)
                  or _RE_CHAVE_TRAVESSAO.match(s)):
            fim = min(fim_linha + 1, linhas[-1][1])
    return fim


def _recuar_frases_curtas(linhas: list[tuple[int, int, str]], k: int) -> int:
    """Offset da primeira das frases curtas de prosa imediatamente antes da linha ``k``."""
    j = k
    while j > 0 and _e_frase_curta_de_prosa(linhas[j - 1][2]):
        j -= 1
    return linhas[j][0]


def _tem_forma_de_ementa(linha: str) -> bool:
    """Ementa = ≥ 3 frases curtas (≤ 80 caracteres) todas iniciadas por maiúscula, ≥ 60 caracteres."""
    s = linha.strip()
    if len(s) < TAMANHO_MINIMO_PROSA:
        return False
    frases = [f for f in _RE_FRASES.split(s) if f]
    return len(frases) >= 3 and all(f[0].isupper() for f in frases) and max(len(f) for f in frases) <= 80


def _e_ementa_antes_dos_autos(linhas: list[tuple[int, int, str]], k: int) -> bool:
    """Ementa em caixa mista sem prefixo (``APELAÇÃO. Estelionato. Materialidade…
    Recurso conhecido e desprovido.``) seguida, em até 6 linhas, de ``Autos nº``/
    ``Chave: valor``: ainda é cabeçalho (revisão R2-09-i)."""
    if not _tem_forma_de_ementa(linhas[k][2]):
        return False
    for _ini, _fim, prox in linhas[k + 1:k + 1 + LINHAS_ATE_OS_AUTOS]:
        s = prox.strip()
        if s and (_RE_LINHA_DE_AUTOS.match(s) or _RE_CHAVE_VALOR.match(s)):
            return True
    return False


#: Além do teto, a primeira linha de prosa ainda vale como fim do cabeçalho até aqui (ementa longa
#: em caixa alta antes do ``ACÓRDÃO``; rodada 4, R4-04) — depois disso só o bloco de identificação.
LIMITE_CABECALHO_ESTENDIDO = 4000


def fim_do_cabecalho(texto: str) -> int:
    """Offset (codepoints) do início da primeira linha de prosa; 0 se não houver.

    Política para ementas (rodada 4, R4-04): uma linha com a forma de ementa (≥ 3 frases curtas
    nominais, com ou sem o rótulo ``EMENTA:``, em qualquer caixa) situada ANTES da primeira linha
    de prosa é cabeçalho — as citações que ela contém não são emitidas — mesmo que a prosa só
    comece além de :data:`LIMITE_CABECALHO` (até :data:`LIMITE_CABECALHO_ESTENDIDO`).

    O cabeçalho das peças tem 3–8 linhas (endereçamento em caixa alta, ``Autos
    nº``/``Processo nº`` + CNJ, partes ``Recorrente:``, ``Protocolo nº``,
    ``Valor da causa: R$``, título da peça em caixa alta) e, na variante
    "parecer jurídico", ``PARECER JURÍDICO Nº NNN/AAAA`` na 1ª linha com
    ``Referência: autos nº <CNJ>`` mais abaixo. A prosa começa na primeira
    linha longa com minúsculas que não é ``Chave: valor`` — ou nas frases
    curtas de prosa (terminadas em pontuação) imediatamente antes dela. Nos 26
    documentos do dev o resultado fica entre 171 e 281 e sempre antes do
    primeiro span.
    """
    linhas = linhas_com_offsets(texto)
    for k, (inicio, _fim, linha) in enumerate(linhas):
        if inicio > LIMITE_CABECALHO:
            break   # antes da regex: nenhuma linha além do teto é avaliada (R3q-04)
        if e_linha_de_prosa(linha):
            if _e_ementa_antes_dos_autos(linhas, k):
                continue
            if k < LINHAS_DE_IDENTIFICACAO and _e_linha_de_identificacao(linha):
                continue   # ``Apelação Cível nº <CNJ> da Comarca de …`` (identificação dos autos)
            # frase curta de prosa imediatamente antes da 1ª linha longa ("Cuida-se de
            # habeas corpus.\nInvoca-se o RHC …\n<linha longa>"): a prosa começa nela
            # (revisão R2-09/R1-12-c). Só frases terminadas em pontuação, com duas
            # palavras minúsculas, que não sejam ``Chave: valor`` nem caixa alta.
            return _recuar_frases_curtas(linhas, k)
    # teto ultrapassado (ou nada encontrado): limiar relaxado com o mesmo recuo de frases curtas
    # (rodada 4, R6-13); senão a primeira linha de prosa até o teto estendido (ementa longa antes do
    # ``ACÓRDÃO``; R4-04); senão o fim do bloco de identificação (R4-04); senão 0
    identificacao = _fim_das_linhas_de_identificacao(linhas)
    for k, (inicio, _fim, linha) in enumerate(linhas):
        if inicio > LIMITE_CABECALHO:
            break
        if inicio >= identificacao and e_linha_de_prosa(linha, TAMANHO_MINIMO_PROSA_RELAXADO):
            resultado = max(identificacao, _recuar_frases_curtas(linhas, k))
            log.warning("fim do cabeçalho pelo limiar relaxado (%d chars) em %d", TAMANHO_MINIMO_PROSA_RELAXADO, resultado)
            return resultado
    for k, (inicio, _fim, linha) in enumerate(linhas):
        if inicio > LIMITE_CABECALHO_ESTENDIDO:
            break
        if inicio > LIMITE_CABECALHO and e_linha_de_prosa(linha):
            resultado = max(identificacao, _recuar_frases_curtas(linhas, k))
            log.warning("fim do cabeçalho além do teto (%d chars) em %d", LIMITE_CABECALHO, resultado)
            return resultado
    if identificacao:
        log.warning("nenhuma linha de prosa até %d chars; cabeçalho = bloco de identificação (até %d)",
                    LIMITE_CABECALHO, identificacao)
        return identificacao
    log.warning("nenhuma linha de prosa até %d chars; cabeçalho considerado vazio", LIMITE_CABECALHO)
    return 0


__all__ = [
    "TAMANHO_MINIMO_PROSA",
    "TAMANHO_MINIMO_PROSA_RELAXADO",
    "LIMITE_CABECALHO",
    "LIMITE_CABECALHO_ESTENDIDO",
    "carregar",
    "carregar_com_codificacao",
    "documento_id",
    "nivel_do_documento",
    "linhas_com_offsets",
    "e_linha_de_prosa",
    "fim_do_cabecalho",
]
