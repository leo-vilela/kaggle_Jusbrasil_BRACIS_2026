"""Ruído do nível 2 (docs/03 §3) e do perfil agressivo, aplicado por partes.

Cada citação é representada por uma lista de **partes** ``(nome, texto)`` que,
concatenadas, formam o span. As funções deste módulo mutam as partes e devolvem
a lista de rótulos de ruído aplicados (mesmos nomes da tabela de §3:
``separador_uf_nao_padrao``, ``conector_numero_nao_padrao``, ``nbsp``,
``espaco_duplo``, ``numero_sem_pontos_de_milhar``, ``espaco_no_numero``,
``caixa_alta_na_classe``, ``classe_com_pontos``, ``abreviacao_nao_padrao``,
``ocr_letra_em_digito``, ``pontuacao_irregular_no_numero``,
``cnj_sem_pontuacao_padrao``, ``quebra_linha_no_numero``, ``quebra_linha_no_span``,
``ocr_palavra``, ``ocr_no_nome_do_relator``, ``ocr_letra_em_palavra``,
``caixa_alta``, ``art_sem_ponto``, ``forma_artigo``).

Garantias (as mesmas do desafio): um dígito **nunca** vira outro dígito; letra
por dígito ocorre no máximo uma vez por número e só com o mapa observado
(``l O S g G``; no perfil agressivo também ``I o Z B``, todas recuperáveis
pela normalização); a UF nunca sofre OCR; o ruído nunca altera os dígitos
canônicos do identificador.

As taxas são as de §3 (contagens sobre as 93 citações N2), por família; o
perfil agressivo combina ruídos e usa formas inéditas (rotuladas ``ood:*``).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .moldes import (
    CLASSES,
    CONECTORES_N2,
    CONECTORES_OOD,
    FORMAS_ART_N2,
    FORMAS_ART_OOD,
    FORMAS_SUMULA_N2,
    FORMAS_SUMULA_OOD,
    OCR_DIGITO,
    OCR_DIGITO_OOD,
    OCR_PALAVRA,
    OCR_PALAVRA_OOD,
    SEPARADORES_UF_N2,
    SEPARADORES_UF_OOD,
)

Partes = list[list[str]]  # [[nome, texto], ...] — listas mutáveis


@dataclass(frozen=True)
class Taxas:
    """Probabilidades por ruído. Nível 1 = tudo zero; nível 2 = §3; nível 3 = agressivo."""

    # processo
    conector_alternativo: float = 0.0     # troca o conector por n°/Nº/No/n. (ou acrescenta um)
    nbsp: float = 0.0                     # NBSP entre conector/sigla e número
    espaco_duplo: float = 0.0
    quebra_antes_numero: float = 0.0
    separador_uf: float = 0.0             # separador ≠ "/"
    caixa_alta_classe: float = 0.0
    forma_classe_n2: float = 0.0          # Rec. Esp., R.Esp., Recl., AgREsp, Ag. Int., H.C., A.REsp, RE., REspe.
    numero_sem_pontos: float = 0.0        # números curtos
    espaco_no_numero: float = 0.0
    cnj_sem_pontuacao: float = 0.0
    quebra_no_numero: float = 0.0
    pontuacao_irregular: float = 0.0
    letra_por_digito: float = 0.0
    letra_por_digito_em_cnj: float = 0.0
    omitir_prefixos: float = 0.0
    # vaga
    ocr_palavra_vaga: float = 0.0
    espaco_duplo_rel_min: float = 0.0
    quebra_rel_min: float = 0.0
    quebra_antes_nome: float = 0.0
    quebra_no_nome: float = 0.0
    ocr_nome_relator: float = 0.0
    # súmula
    forma_sumula_n2: float = 0.0
    quebra_sumula_tribunal: float = 0.0
    # dispositivo
    forma_art_n2: float = 0.0
    quebra_no_diploma: float = 0.0
    ocr_diploma: float = 0.0
    quebra_art_numero: float = 0.0
    # corpo
    ocr_corpo: float = 0.0
    digito_em_palavra_corpo: float = 0.0
    # formas inéditas (só perfil agressivo)
    ood: bool = False
    conector_ood: float = 0.0
    separador_uf_ood: float = 0.0
    forma_classe_ood: float = 0.0
    forma_sumula_ood: float = 0.0
    forma_art_ood: float = 0.0
    ocr_ood: float = 0.0
    # letra por dígito FORA do número de processo (número de súmula/tema/artigo e ano da citação
    # vaga): o dev só mostrou o fenômeno em números de processo (5/5 eventos, p ≈ 0,09 sob
    # amostragem uniforme), então fica fora do perfil dev e entra no agressivo como ``ood``
    # (revisão rodada 2, R4-01 do revisor 1).
    ocr_digito_normativo: float = 0.0
    ocr_digito_ano: float = 0.0


TAXAS_N1 = Taxas()
TAXAS_N2 = Taxas(
    conector_alternativo=0.45, nbsp=0.30, espaco_duplo=0.25, quebra_antes_numero=0.05,
    separador_uf=0.90, caixa_alta_classe=0.27, forma_classe_n2=0.45,
    numero_sem_pontos=0.23, espaco_no_numero=0.30, cnj_sem_pontuacao=0.30, quebra_no_numero=0.13,
    pontuacao_irregular=0.10, letra_por_digito=0.12, letra_por_digito_em_cnj=0.0, omitir_prefixos=0.03,
    ocr_palavra_vaga=0.25, espaco_duplo_rel_min=0.10, quebra_rel_min=0.10, quebra_antes_nome=0.30,
    quebra_no_nome=0.15, ocr_nome_relator=0.18,
    forma_sumula_n2=0.50, quebra_sumula_tribunal=0.33,
    forma_art_n2=0.79, quebra_no_diploma=0.30, ocr_diploma=0.10, quebra_art_numero=0.0,
    ocr_corpo=0.038, digito_em_palavra_corpo=0.002,
)
TAXAS_N3 = Taxas(
    conector_alternativo=0.60, nbsp=0.40, espaco_duplo=0.35, quebra_antes_numero=0.12,
    separador_uf=0.90, caixa_alta_classe=0.35, forma_classe_n2=0.35,
    numero_sem_pontos=0.50, espaco_no_numero=0.30, cnj_sem_pontuacao=0.40, quebra_no_numero=0.25,
    pontuacao_irregular=0.20, letra_por_digito=0.25, letra_por_digito_em_cnj=0.15, omitir_prefixos=0.08,
    ocr_palavra_vaga=0.40, espaco_duplo_rel_min=0.20, quebra_rel_min=0.20, quebra_antes_nome=0.35,
    quebra_no_nome=0.25, ocr_nome_relator=0.30,
    forma_sumula_n2=0.50, quebra_sumula_tribunal=0.40,
    forma_art_n2=0.70, quebra_no_diploma=0.40, ocr_diploma=0.20, quebra_art_numero=0.10,
    ocr_corpo=0.06, digito_em_palavra_corpo=0.005,
    ood=True, conector_ood=0.20, separador_uf_ood=0.25, forma_classe_ood=0.30, forma_sumula_ood=0.30,
    forma_art_ood=0.25, ocr_ood=0.15, ocr_digito_normativo=0.20, ocr_digito_ano=0.20,
)


def taxas_do_nivel(nivel: int) -> Taxas:
    return {1: TAXAS_N1, 2: TAXAS_N2, 3: TAXAS_N3}[nivel]


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------
def _parte(partes: Partes, nome: str) -> list[str] | None:
    for p in partes:
        if p[0] == nome:
            return p
    return None


def montar(partes: Partes) -> str:
    return "".join(p[1] for p in partes)


def ocr_em_palavra(palavra: str, rng: random.Random, ood: bool = False) -> str | None:
    """Uma substituição de OCR na palavra (§3.1); ``None`` se nenhuma se aplica."""
    tabela = list(OCR_PALAVRA) + (list(OCR_PALAVRA_OOD) if ood else [])
    opcoes = [(a, b, w) for a, b, w in tabela if a in palavra]
    if not opcoes:
        return None
    pesos = [w for _, _, w in opcoes]
    a, b, _ = rng.choices(opcoes, weights=pesos, k=1)[0]
    posicoes = [i for i in range(len(palavra)) if palavra.startswith(a, i)]
    i = rng.choice(posicoes)
    return palavra[:i] + b + palavra[i + len(a):]


def letra_por_digito(numero: str, rng: random.Random, ood: bool = False,
                     permitir_inicio: bool = False) -> tuple[str, bool, bool]:
    """Troca UM dígito por letra confundível (nunca dígito por dígito).

    Devolve ``(novo, aplicou, no_inicio)``. O primeiro caractere do número só é
    trocado com ``permitir_inicio`` (o dev nunca tem letra no início e a
    normalização exige dígito ASCII inicial — docs/03 §3.1)."""
    mapa = dict(OCR_DIGITO)
    if ood:
        mapa.update(OCR_DIGITO_OOD)
    posicoes = [i for i, c in enumerate(numero) if c in mapa and (i > 0 or permitir_inicio)]
    if not posicoes:
        return numero, False, False
    i = rng.choice(posicoes)
    return numero[:i] + mapa[numero[i]] + numero[i + 1:], True, i == 0


_RE_PALAVRA = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
_RE_ANO = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def _ocr_digito_fora_do_processo(parte: list[str], taxa: Taxas, rng: random.Random, r: list[str],
                                 probabilidade: float, so_ano: bool = False) -> None:
    """Uma letra por dígito no número de súmula/tema/artigo (ou no ano de uma citação vaga).

    Nunca no primeiro dígito (a normalização exige dígito inicial — como no processo); só com o
    mapa do dev (``l O S g G``). Rótulos: ``ocr_letra_em_digito`` + ``ood:ocr_fora_do_processo``.
    """
    if probabilidade <= 0 or rng.random() >= probabilidade:
        return
    texto = parte[1]
    if so_ano:
        anos = list(_RE_ANO.finditer(texto))
        if not anos:
            return
        m = rng.choice(anos)
        novo, ok, _ = letra_por_digito(m.group(0), rng)
        if not ok:
            return
        parte[1] = texto[:m.start()] + novo + texto[m.end():]
    else:
        miolo = texto.strip()
        novo, ok, _ = letra_por_digito(miolo, rng)
        if not ok:
            return
        ini = texto.index(miolo)
        parte[1] = texto[:ini] + novo + texto[ini + len(miolo):]
    r.extend(["ocr_letra_em_digito", "ood:ocr_fora_do_processo"])


def ocr_em_texto(texto: str, taxa: Taxas, rng: random.Random) -> str:
    """OCR nas palavras de um trecho de prosa (fora dos spans). Não toca em siglas
    nem em palavras com dígitos; ``de`` → ``dc`` entra pela tabela geral."""
    if taxa.ocr_corpo <= 0:
        return texto
    saida: list[str] = []
    ultimo = 0
    for m in _RE_PALAVRA.finditer(texto):
        saida.append(texto[ultimo:m.start()])
        palavra = m.group(0)
        nova = palavra
        if palavra.isupper():
            if rng.random() < taxa.digito_em_palavra_corpo:
                nova = _digito_em_palavra(palavra, rng)
        elif palavra[0].islower() and rng.random() < taxa.ocr_corpo:
            nova = ocr_em_palavra(palavra, rng, taxa.ood and rng.random() < taxa.ocr_ood) or palavra
        saida.append(nova)
        ultimo = m.end()
    saida.append(texto[ultimo:])
    return "".join(saida)


def _digito_em_palavra(palavra: str, rng: random.Random) -> str:
    mapa = {"S": "5", "O": "0", "I": "1"}
    posicoes = [i for i, c in enumerate(palavra) if c in mapa]
    if not posicoes:
        return palavra
    i = rng.choice(posicoes)
    return palavra[:i] + mapa[palavra[i]] + palavra[i + 1:]


# ---------------------------------------------------------------------------
# processo
# ---------------------------------------------------------------------------
@dataclass
class InfoProcesso:
    """Metadados que o ruído precisa conhecer (nunca alterados pelo ruído)."""

    formato: str                 # "sequencial" | "cnj" | "registro"
    tribunal: str | None
    classe_principal: str | None
    estilo: str                  # "conector" | "hifen" | "tst"
    tem_uf: bool
    rotulos: list[str] = field(default_factory=list)


def ruido_processo(partes: Partes, info: InfoProcesso, taxa: Taxas, rng: random.Random) -> list[str]:
    """Aplica ruído às partes de uma citação de processo. Partes esperadas (em ordem):
    ``prefixo``, ``tst``, ``classe`` (pode repetir: um ``classe`` por elemento da cadeia,
    intercalado com ``ligacao``), ``conector``, ``espaco``, ``numero``, ``sep``, ``uf``, ``fecha``."""
    r: list[str] = []
    ood = taxa.ood

    # 1. formas da classe principal (abreviações não padrão / com pontos / inéditas)
    classes = [p for p in partes if p[0] == "classe"]
    if classes and info.estilo == "conector":
        principal = classes[-1]
        sigla = info.classe_principal or ""
        formas_n2 = list(CLASSES.get(sigla, {}).get("n2", []))
        formas_ood = list(CLASSES.get(sigla, {}).get("ood", []))
        if ood and formas_ood and rng.random() < taxa.forma_classe_ood:
            principal[1] = rng.choice(formas_ood)
            r.append("ood:forma_classe")
        elif formas_n2 and rng.random() < taxa.forma_classe_n2:
            principal[1] = rng.choice(formas_n2)
        if "." in principal[1]:
            r.append("classe_com_pontos")
        if principal[1] in ("Rec. Esp.", "R.Esp.", "Recl.", "AgREsp", "Ag. Int.", "H.C.", "A.REsp", "EDs"):
            r.append("abreviacao_nao_padrao")
    # 2. caixa alta na classe (tokens da cadeia; ligações ficam minúsculas)
    if classes and rng.random() < taxa.caixa_alta_classe:
        alvo = classes if rng.random() < 0.5 else classes[-1:]
        mudou = False
        for p in alvo:
            if not p[1].isupper():
                p[1] = p[1].upper()
                mudou = True
        if mudou:
            r.append("caixa_alta_na_classe")
    # 3. conector e espaçamento
    conector = _parte(partes, "conector")
    espaco = _parte(partes, "espaco")
    if conector is not None and espaco is not None and info.estilo != "tst" and espaco[1] != "-":
        if ood and rng.random() < taxa.conector_ood:
            conector[1] = " " + rng.choice(CONECTORES_OOD)
            r.append("ood:conector")
        elif rng.random() < taxa.conector_alternativo:
            conector[1] = " " + rng.choice(CONECTORES_N2)
            r.append("conector_numero_nao_padrao")
        sorteio = rng.random()
        if sorteio < taxa.nbsp:
            espaco[1] = " "
            r.append("nbsp")
        elif sorteio < taxa.nbsp + taxa.espaco_duplo:
            espaco[1] = "  "
            r.append("espaco_duplo")
        elif sorteio < taxa.nbsp + taxa.espaco_duplo + taxa.quebra_antes_numero:
            espaco[1] = rng.choice(["\n", "\n "])
            r.append("quebra_linha_no_span")
    # 4. número (sem quebra de linha se o espaço antes do número já quebrou)
    numero = _parte(partes, "numero")
    if numero is not None:
        taxa_num = taxa
        if "quebra_linha_no_span" in r:
            taxa_num = Taxas(**{**taxa.__dict__, "quebra_no_numero": 0.0, "pontuacao_irregular": 0.0})
        r.extend(_ruido_numero(numero, info, taxa_num, rng))
    # 5. UF e separador (no máximo UMA quebra de linha vinda do ruído por span, como no dev)
    sep = _parte(partes, "sep")
    fecha = _parte(partes, "fecha")
    ja_quebrou = "quebra_linha_no_span" in r
    if info.tem_uf and sep is not None and fecha is not None:
        if ood and rng.random() < taxa.separador_uf_ood:
            opcoes = [o for o in SEPARADORES_UF_OOD if not (ja_quebrou and "\n" in o[0])]
            sep[1], fecha[1] = rng.choice(opcoes)
            r.append("ood:separador_uf")
            r.append("separador_uf_nao_padrao")
        elif rng.random() < taxa.separador_uf:
            opcoes = [o for o in SEPARADORES_UF_N2 if not (ja_quebrou and "\n" in o[0])]
            sep[1], fecha[1] = rng.choice(opcoes)
            r.append("separador_uf_nao_padrao")
        if "\n" in sep[1]:
            r.append("quebra_linha_no_span")
    return sorted(set(r))


def _ruido_numero(numero: list[str], info: InfoProcesso, taxa: Taxas, rng: random.Random) -> list[str]:
    r: list[str] = []
    n = numero[1]
    if info.formato == "sequencial":
        if "." in n and rng.random() < taxa.numero_sem_pontos:
            n = n.replace(".", "")
            r.append("numero_sem_pontos_de_milhar")
        elif "." in n and rng.random() < taxa.espaco_no_numero:
            if rng.random() < 0.5:
                n = n.replace(".", " ")
            else:
                pontos = [i for i, c in enumerate(n) if c == "."]
                i = rng.choice(pontos)
                n = n[:i + 1] + " " + n[i + 1:]
            r.append("espaco_no_numero")
        elif "." in n and rng.random() < taxa.pontuacao_irregular:
            pontos = [i for i, c in enumerate(n) if c == "."]
            i = rng.choice(pontos)
            forma = rng.choice([".-\n", "-\n.", "-\n", "--"])
            n = n[:i] + forma + n[i + 1:]
            r.append("pontuacao_irregular_no_numero")
            r.append("quebra_linha_no_numero")
            r.append("quebra_linha_no_span")
        elif "." in n and rng.random() < taxa.quebra_no_numero:
            pontos = [i for i, c in enumerate(n) if c == "."]
            i = rng.choice(pontos)
            n = n[:i + 1] + "\n" + n[i + 1:]
            r.append("quebra_linha_no_numero")
            r.append("quebra_linha_no_span")
        if rng.random() < taxa.letra_por_digito:
            n, ok, inicio = letra_por_digito(n, rng, taxa.ood, permitir_inicio=taxa.ood and rng.random() < 0.1)
            if ok:
                r.append("ocr_letra_em_digito")
                if inicio:
                    r.append("ood:ocr_primeiro_digito")
    elif info.formato == "cnj":
        sorteio = rng.random()
        if sorteio < taxa.cnj_sem_pontuacao:
            if rng.random() < 0.5:
                # só o primeiro hífen: 0609999-1220216160100
                seq, resto = n.split("-", 1)
                n = seq + "-" + resto.replace(".", "").replace("-", "")
            else:
                n = n.replace(".", " ")
                r.append("espaco_no_numero")
            r.append("cnj_sem_pontuacao_padrao")
        elif sorteio < taxa.cnj_sem_pontuacao + taxa.quebra_no_numero:
            posicoes = [i for i, c in enumerate(n) if c in ".-"]
            i = rng.choice(posicoes)
            if n[i] == "-" and rng.random() < 0.3:
                n = n[:i] + "-\n" + n[i + 1:]
            else:
                n = n[:i + 1] + "\n" + n[i + 1:]
            r.append("quebra_linha_no_numero")
            r.append("quebra_linha_no_span")
        elif sorteio < taxa.cnj_sem_pontuacao + taxa.quebra_no_numero + taxa.pontuacao_irregular:
            i = n.index("-")
            forma = rng.choice(["--\n", "-\n.", ". "])
            if forma == ". ":
                pontos = [k for k, c in enumerate(n) if c == "."]
                k = rng.choice(pontos)
                n = n[:k + 1] + " " + n[k + 1:]
                r.append("espaco_no_numero")
            else:
                n = n[:i] + forma + n[i + 1:]
                r.append("quebra_linha_no_numero")
                r.append("quebra_linha_no_span")
            r.append("pontuacao_irregular_no_numero")
        if rng.random() < taxa.letra_por_digito_em_cnj:
            n, ok, inicio = letra_por_digito(n, rng, taxa.ood, permitir_inicio=taxa.ood and rng.random() < 0.1)
            if ok:
                r.append("ocr_letra_em_digito")
                r.append("ood:ocr_em_cnj")
                if inicio:
                    r.append("ood:ocr_primeiro_digito")
    numero[1] = n
    return r


# ---------------------------------------------------------------------------
# vaga
# ---------------------------------------------------------------------------
_PALAVRAS_OCR_VAGA = ("proferido", "julgado", "precedente", "relatoria", "sob", "pela", "de", "acórdão", "da")


def ruido_vaga(partes: Partes, taxa: Taxas, rng: random.Random) -> list[str]:
    """Partes: ``texto`` (molde até o espaço antes do nome, inclusive) e ``nome``."""
    r: list[str] = []
    texto = _parte(partes, "texto")
    nome = _parte(partes, "nome")
    if texto is None or nome is None:
        return r
    t = texto[1]
    if rng.random() < taxa.ocr_palavra_vaga:
        candidatos = [w for w in _PALAVRAS_OCR_VAGA if re.search(rf"\b{w}\b", t)]
        if candidatos:
            w = rng.choice(candidatos)
            novo = ocr_em_palavra(w, rng, taxa.ood and rng.random() < taxa.ocr_ood)
            if novo:
                t = re.sub(rf"\b{w}\b", novo, t, count=1)
                r.append("ocr_palavra")
    if taxa.ood:
        _ocr_digito_fora_do_processo(texto, taxa, rng, r, taxa.ocr_digito_ano, so_ano=True)
        t = texto[1]
    if "Rel. Min. " in t:
        sorteio = rng.random()
        if sorteio < taxa.espaco_duplo_rel_min:
            t = t.replace("Rel. Min. ", "Rel.  Min. ")
            r.append("espaco_duplo")
        elif sorteio < taxa.espaco_duplo_rel_min + taxa.quebra_rel_min:
            t = t.replace("Rel. Min. ", "Rel.\nMin. ")
            r.append("quebra_linha_no_span")
    quebrou_antes = False
    if t.endswith(" ") and "\n" not in t and rng.random() < taxa.quebra_antes_nome:
        t = t[:-1] + "\n"
        r.append("quebra_linha_no_span")
        quebrou_antes = True
    texto[1] = t
    n = nome[1]
    if " " in n and not quebrou_antes and "\n" not in t and rng.random() < taxa.quebra_no_nome:
        espacos = [i for i, c in enumerate(n) if c == " "]
        i = rng.choice(espacos)
        n = n[:i] + "\n" + n[i + 1:]
        r.append("quebra_linha_no_span")
    if rng.random() < taxa.ocr_nome_relator:
        palavras = n.split(" ")
        idx = [i for i, w in enumerate(palavras) if len(w.replace("\n", "")) >= 5]
        if idx:
            i = rng.choice(idx)
            alvo = palavras[i]
            # só troca letra por letra (ã por a, l por i): preserva a caixa
            if alvo.isupper():
                novo = None
                for a, b in (("A", "Ã"), ("I", "L")):
                    if a in alvo:
                        k = alvo.index(a)
                        novo = alvo[:k] + b + alvo[k + 1:]
                        break
            else:
                novo = None
                for a, b in (("a", "ã"), ("i", "l")):
                    if a in alvo[1:]:
                        k = alvo.index(a, 1)
                        novo = alvo[:k] + b + alvo[k + 1:]
                        break
            if novo and novo != alvo:
                palavras[i] = novo
                n = " ".join(palavras)
                r.append("ocr_no_nome_do_relator")
    nome[1] = n
    return sorted(set(r))


# ---------------------------------------------------------------------------
# súmula
# ---------------------------------------------------------------------------
def ruido_sumula(partes: Partes, taxa: Taxas, rng: random.Random) -> list[str]:
    """Partes: ``palavra`` (Súmula), ``vinc`` (`` Vinculante``/vazio), ``numero``, ``tribunal`` (`` do STJ``/vazio)."""
    r: list[str] = []
    palavra = _parte(partes, "palavra")
    tribunal = _parte(partes, "tribunal")
    if palavra is not None:
        if taxa.ood and rng.random() < taxa.forma_sumula_ood:
            palavra[1] = rng.choice(FORMAS_SUMULA_OOD)
            r.append("ood:forma_sumula")
        elif rng.random() < taxa.forma_sumula_n2:
            palavra[1] = rng.choice(FORMAS_SUMULA_N2)
        if palavra[1].startswith("5"):
            r.append("ocr_letra_em_palavra")
        elif palavra[1].isupper():
            r.append("caixa_alta")
        elif palavra[1].endswith("."):
            r.append("abreviacao_nao_padrao")
    numero = _parte(partes, "numero")
    if numero is not None and taxa.ood:
        _ocr_digito_fora_do_processo(numero, taxa, rng, r, taxa.ocr_digito_normativo)
    if tribunal is not None and tribunal[1] and rng.random() < taxa.quebra_sumula_tribunal:
        tribunal[1] = "\ndo " + tribunal[1][4:] if rng.random() < 0.5 else " do\n" + tribunal[1][4:]
        r.append("quebra_linha_no_span")
    return sorted(set(r))


# ---------------------------------------------------------------------------
# dispositivo
# ---------------------------------------------------------------------------
def ruido_dispositivo(partes: Partes, taxa: Taxas, rng: random.Random) -> list[str]:
    """Partes: ``art``, ``espaco``, ``numero``, ``complemento``, ``prep``, ``diploma``."""
    r: list[str] = []
    art = _parte(partes, "art")
    espaco = _parte(partes, "espaco")
    diploma = _parte(partes, "diploma")
    if art is not None:
        if taxa.ood and rng.random() < taxa.forma_art_ood:
            art[1] = rng.choice(FORMAS_ART_OOD)
            r.append("ood:forma_art")
        elif rng.random() < taxa.forma_art_n2:
            art[1] = rng.choice(FORMAS_ART_N2)
        if art[1] == "art":
            r.append("art_sem_ponto")
        elif art[1].lower().startswith("artigo"):
            r.append("forma_artigo")
    numero = _parte(partes, "numero")
    if numero is not None and taxa.ood:
        _ocr_digito_fora_do_processo(numero, taxa, rng, r, taxa.ocr_digito_normativo)
    if espaco is not None and rng.random() < taxa.quebra_art_numero:
        espaco[1] = "\n"
        r.append("quebra_linha_no_span")
    if diploma is not None:
        d = diploma[1]
        if " " in d and rng.random() < taxa.quebra_no_diploma:
            espacos = [i for i, c in enumerate(d) if c == " "]
            i = rng.choice(espacos)
            d = d[:i] + "\n" + d[i + 1:]
            r.append("quebra_linha_no_span")
        if rng.random() < taxa.ocr_diploma:
            palavras = re.findall(r"[A-Za-zÀ-ÿ]{5,}", d)
            palavras = [w for w in palavras if not w.isupper()]
            if palavras:
                w = rng.choice(palavras)
                novo = ocr_em_palavra(w, rng, taxa.ood and rng.random() < taxa.ocr_ood)
                if novo:
                    d = d.replace(w, novo, 1)
                    r.append("ocr_palavra")
        diploma[1] = d
    return sorted(set(r))


__all__ = [
    "Taxas", "TAXAS_N1", "TAXAS_N2", "TAXAS_N3", "taxas_do_nivel", "Partes", "InfoProcesso",
    "montar", "ruido_processo", "ruido_vaga", "ruido_sumula", "ruido_dispositivo",
    "ocr_em_texto", "ocr_em_palavra", "letra_por_digito",
]
