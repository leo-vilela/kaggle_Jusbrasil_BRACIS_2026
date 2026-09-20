"""Gerador determinístico de documentos sintéticos com gabarito.

Reproduz o formato do conjunto de desenvolvimento (docs/03): cabeçalho com
distratores, prosa por seções, 4–9 citações em frases próprias, fronteiras de
span por família (§1), formas de superfície (§2), ruído N2 (§3), dispositivos
(§4), súmulas (§5), armadilhas sem identificador (§6.3) e distribuição de
classes ≈ 50 % real / 33 % inventada / 17 % incompleta (§0).

Toda citação ``real`` usa um número **próprio** da base (índice
``por_digitos``), toda ``inventada`` de processo é conferida contra o índice
(nunca é número próprio de ninguém) e toda ``incompleta`` é da família ``vaga``
com tribunal + ano + relator reais e multiplicidade ≥ 2 na base.

Uso::

    base = BaseCanonica.de_arquivo("dados/indice.json")
    docs = gerar_conjunto(base, n_docs=40, nivel=2, seed=123, perfil="dev")
    escrever_conjunto(docs, Path("dados/sinteticos/n2_dev"))

Cada documento é ``(documento_id, texto, gabarito)``; o gabarito tem as colunas
oficiais do goldenset (``nivel, documento_id, citacao_id, inicio, fim, trecho,
tipo, classificacao, id_canonico``) mais colunas de análise (``familia``,
``tribunal``, ``digitos``, ``classe_cadeia``, ``uf``, ``ruidos``, ``forma``,
``ood``). Offsets em codepoints, texto NFC, LF, sem BOM.
"""
from __future__ import annotations

import csv
import json
import random
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..base_canonica import BaseCanonica, Registro, artigo_canonico, diploma_canonico, sumula_canonica
from ..base_canonica.classes import classe_principal as _classe_principal
from ..base_canonica.digitos import FORMATO_CNJ, FORMATO_REGISTRO, FORMATO_SEQUENCIAL, UFS
from ..tipos import iou
from . import cabecalhos as cab
from . import moldes as M
from . import ruido as R

VERSAO = 1
COLUNAS_OFICIAIS = ["nivel", "documento_id", "citacao_id", "inicio", "fim", "trecho", "tipo", "classificacao", "id_canonico"]
COLUNAS_EXTRAS = ["familia", "tribunal", "digitos", "classe_cadeia", "uf", "ruidos", "forma", "ood"]
DISTANCIA_MINIMA = 60
PERFIS = ("dev", "agressivo")


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Perfil:
    """``dev``: só formas observadas no dev (in-distribution). ``agressivo``: formas
    inéditas (siglas nunca citadas, separadores/abreviações plausíveis, moldes de
    vaga novos, armadilhas com tribunal/ano) + ruído combinado quando nível 3."""

    nome: str
    nivel: int
    taxas: R.Taxas

    @property
    def ood(self) -> bool:
        return self.nome == "agressivo"


def perfil_para(nivel: int, nome: str = "dev") -> Perfil:
    if nivel not in (1, 2, 3):
        raise ValueError(f"nível inválido: {nivel}")
    if nome not in PERFIS:
        raise ValueError(f"perfil inválido: {nome}")
    if nivel == 3:
        nome = "agressivo"
    taxas = R.taxas_do_nivel(nivel)
    if nome == "agressivo" and nivel < 3:
        # formas inéditas sem ruído adicional (nível 1) ou com ruído do nível 2
        taxas = R.Taxas(**{**taxas.__dict__, "ood": True, "conector_ood": 0.2, "separador_uf_ood": 0.25,
                          "forma_classe_ood": 0.3, "forma_sumula_ood": 0.3, "forma_art_ood": 0.25})
    return Perfil(nome=nome, nivel=nivel, taxas=taxas)


# ---------------------------------------------------------------------------
# Estruturas
# ---------------------------------------------------------------------------
@dataclass
class Citacao:
    familia: str
    tipo: str
    classificacao: str
    id_canonico: int | None
    partes: R.Partes
    genero: str                      # artigo antes do span: m/f/p
    ruidos: list[str] = field(default_factory=list)
    forma: dict[str, str] = field(default_factory=dict)
    tribunal: str | None = None
    digitos: str = ""
    cadeia: list[str] = field(default_factory=list)
    uf: str | None = None
    ood: bool = False
    origem_id: str | None = None     # documento_id do registro usado (real ou fonte da perturbação)

    @property
    def trecho(self) -> str:
        return R.montar(self.partes)


@dataclass
class Documento:
    documento_id: str
    nivel: int
    perfil: str
    texto: str
    gabarito: list[dict[str, Any]]
    armadilhas: list[tuple[int, int, str]] = field(default_factory=list)   # spans sem citação (negativos)
    meta: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator[Any]:
        yield self.documento_id
        yield self.texto
        yield self.gabarito


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _artigo(genero: str, prefixo: str = "") -> str:
    base = {"m": "o", "f": "a", "p": "os"}[genero]
    return prefixo + base


def _com_pontos(digitos: str) -> str:
    s = digitos.lstrip("0") or "0"
    grupos = []
    while len(s) > 3:
        grupos.insert(0, s[-3:])
        s = s[:-3]
    grupos.insert(0, s)
    return ".".join(grupos)


def _superficie_cnj(d: str, tribunal: str | None) -> str:
    seq, dv, ano, j, tr, o = d[:7], d[7:9], d[9:13], d[13], d[14:16], d[16:20]
    if tribunal == "STM" or (tribunal == "TSE" and int(ano) >= 2019 and seq.startswith("0")):
        seq_s = seq
    else:
        seq_s = seq.lstrip("0") or "0"
    return f"{seq_s}-{dv}.{ano}.{j}.{tr}.{o}"


def _superficie_registro(d: str) -> str:
    return f"{d[:4]}/{d[4:11]}-{d[11]}"


def _genero_diploma(superficie: str) -> str:
    s = superficie
    if s.startswith(("Decreto-Lei", "Código", "CPC", "NCPC", "CC", "CDC", "CPP", "CPM", "CE")):
        return "m"
    return "f"


_RE_RELATOR_LIXO = re.compile(r"\b(DESEMBARGADOR|DESEMBARGADORA|CONVOCAD[OA]).*$", re.I)
_RE_LINHA_ARTIGO = re.compile(r"^Artigo\s+(?P<num>[\d\.]+)[ºo°]?\s+(?P<resto>d[ao]\s+.+)$", re.I)
_PARTICULAS = {"de", "da", "do", "dos", "das", "e"}


def _palavras_relator(relator: str | None) -> list[str]:
    if not relator:
        return []
    t = _RE_RELATOR_LIXO.sub("", relator)
    t = re.sub(r"^\s*(Min\.|Ministro|Ministra|Des\.)\s+", "", t)
    palavras = [p for p in t.split() if p.isalpha()]
    if len(palavras) < 2 or any(len(p) < 2 for p in palavras):
        return []
    return palavras


def _nome_relator(palavras: list[str], rng: random.Random, caixa_alta: bool) -> str:
    n = len(palavras)
    if n > 4:
        k = rng.choice([2, 3, 4])
        if rng.random() < 0.5:
            escolha = palavras[:k]
        else:
            escolha = palavras[n - k:]
        # não começar por partícula
        while escolha and escolha[0].lower() in _PARTICULAS:
            escolha = escolha[1:]
        if len(escolha) < 2:
            escolha = palavras[:2]
    else:
        escolha = list(palavras)
    if caixa_alta:
        return " ".join(p.upper() for p in escolha)
    saida = []
    maiuscula_particula = rng.random() < 0.3
    for i, p in enumerate(escolha):
        if p.lower() in _PARTICULAS and i > 0 and not maiuscula_particula:
            saida.append(p.lower())
        else:
            saida.append(p[0].upper() + p[1:].lower())
    return " ".join(saida)


def _quebrar_linhas(s: str, largura: int, protegidos: list[tuple[int, int]] | None = None) -> str:
    """Quebra em linhas substituindo espaços por ``\\n`` (mesmo número de codepoints).

    ``protegidos``: intervalos que devem ser tratados como uma única palavra (a
    quebra acontece antes deles, nunca dentro) — usado para controlar a taxa de
    quebras de linha dentro dos spans."""
    out = list(s)
    prot = sorted(protegidos or [])
    col = 0
    i = 0
    n = len(s)

    def fim_da_palavra(k: int) -> int:
        """Fim da 'palavra' que começa em k (um intervalo protegido conta como palavra)."""
        for a, b in prot:
            if a <= k < b:
                k = b
                break
        while k < n and s[k] not in " \n":
            for a, b in prot:
                if a <= k < b:
                    k = b
                    break
            else:
                k += 1
        return k

    while i < n:
        c = s[i]
        if c == "\n":
            col = 0
            i += 1
            continue
        if c == " " and not any(a <= i < b for a, b in prot):
            j = fim_da_palavra(i + 1)
            palavra = j - (i + 1)
            if col > 0 and col + 1 + palavra > largura:
                out[i] = "\n"
                col = palavra
            else:
                col += 1 + palavra
            i = j
            continue
        col += 1
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Amostragem na base
# ---------------------------------------------------------------------------
class _Amostrador:
    """Acesso indexado à base para o gerador (tudo ordenado → determinístico)."""

    def __init__(self, base: BaseCanonica) -> None:
        self.base = base
        self.acordaos: dict[str, list[Registro]] = {t: [] for t in ("STF", "STJ", "STM", "TSE", "TST")}
        for r in base.registros():
            if r.natureza == "acordao" and r.tribunal in self.acordaos and base.identificadores(r.documento_id):
                self.acordaos[r.tribunal].append(r)
        self.sumulas: list[tuple[str, bool, int, Registro]] = []
        self.dispositivos: list[tuple[str, str, Registro]] = []
        for r in base.registros():
            linha = base.cabecalho(r.documento_id, 200).split("\n", 1)[0].strip()
            if r.natureza == "sumula":
                trib, vinc, num = sumula_canonica(linha)
                if num is not None:
                    self.sumulas.append((trib or r.tribunal or "STF", vinc, num, r))
            elif r.natureza == "dispositivo":
                m = _RE_LINHA_ARTIGO.match(linha)
                if not m:
                    continue
                dip = diploma_canonico(m.group("resto"))
                art = artigo_canonico("art. " + m.group("num"))
                if dip and art:
                    self.dispositivos.append((dip, art, r))
        self.por_digitos: dict[str, list[str]] = base._por_digitos  # só leitura

    def existe_numero_proprio(self, digitos_ou_trecho: str) -> bool:
        return bool(self.base.candidatos_por_numero(digitos_ou_trecho))

    def ambiguo(self, digitos: str) -> list[str]:
        return list(self.por_digitos.get(digitos, []))


# ---------------------------------------------------------------------------
# Renderização da cadeia de classes
# ---------------------------------------------------------------------------
def _forma_classe(sigla: str, perfil: Perfil, rng: random.Random, principal: bool) -> tuple[str, bool]:
    """Superfície de uma sigla da cadeia (formas do nível 1; inéditas no perfil agressivo)."""
    tab = M.CLASSES.get(sigla)
    if tab is None:
        return sigla, True
    dev = list(tab["dev"])  # type: ignore[arg-type]
    ood = list(tab["ood"])  # type: ignore[arg-type]
    n2 = list(tab["n2"])  # type: ignore[arg-type]
    if perfil.ood and (not dev or rng.random() < perfil.taxas.forma_classe_ood):
        opcoes = ood + n2 + dev
        return rng.choice(opcoes), True
    if not dev:
        # sigla só existe fora do dev: usa a forma canônica mais simples
        return (ood or n2 or [sigla])[0], True
    # no dev, ~2/3 sigla e 1/3 nome por extenso
    pesos = [3 if i == 0 else 1 for i in range(len(dev))]
    return rng.choices(dev, weights=pesos, k=1)[0], False


def _genero_sigla(sigla: str) -> str:
    tab = M.CLASSES.get(sigla)
    return str(tab["genero"]) if tab else "m"


def _render_cadeia(cadeia: list[str], tribunal: str | None, estilo: str, perfil: Perfil,
                   rng: random.Random) -> tuple[R.Partes, str, bool]:
    """Partes ``classe``/``ligacao`` da cadeia, gênero do primeiro elemento e flag ood."""
    partes: R.Partes = []
    ood = False
    if estilo == "tst":
        tokens = [M.TOKEN_TST.get(s, s) for s in cadeia]
        partes.append(["classe", "-".join(tokens)])
        return partes, "m", ood
    if estilo == "hifen":
        tokens = [M.TOKEN_TSE.get(s, s) for s in cadeia]
        if len(tokens) >= 3 and rng.random() < 0.6:
            # misto: "ED no AgR-REspe"
            primeiro, _ = _forma_classe(cadeia[0], perfil, rng, False)
            partes.append(["classe", primeiro])
            partes.append(["ligacao", f" {_artigo(_genero_sigla(cadeia[1]), 'n')} "])
            partes.append(["classe", "-".join(tokens[1:])])
            return partes, _genero_sigla(cadeia[0]), ood
        partes.append(["classe", "-".join(tokens)])
        return partes, _genero_sigla(cadeia[0]), ood
    # estilo "conector"
    genero_inicial: str | None = None
    i = 0
    while i < len(cadeia):
        s = cadeia[i]
        if s in M.ORDINAIS:
            prox = cadeia[i + 1] if i + 1 < len(cadeia) else "AGR"
            g = _genero_sigla(prox)
            partes.append(["classe", M.ORDINAIS[s][g]])
            partes.append(["ligacao", " "])
            genero_inicial = genero_inicial or g
            i += 1
            continue
        superficie, e_ood = _forma_classe(s, perfil, rng, i == len(cadeia) - 1)
        ood = ood or e_ood
        partes.append(["classe", superficie])
        genero_inicial = genero_inicial or _genero_sigla(s)
        if i + 1 < len(cadeia):
            prox = cadeia[i + 1]
            if prox in M.ORDINAIS:
                partes.append(["ligacao", " "])
            else:
                partes.append(["ligacao", f" {_artigo(_genero_sigla(prox), 'n')} "])
        i += 1
    return partes, genero_inicial or "m", ood


# ---------------------------------------------------------------------------
# Citações de processo
# ---------------------------------------------------------------------------
def _escolher_identificador(reg: Registro, am: _Amostrador, perfil: Perfil, rng: random.Random) -> dict[str, Any] | None:
    idents = am.base.identificadores(reg.documento_id)
    if not idents:
        return None
    cnj = [i for i in idents if i["formato"] == FORMATO_CNJ]
    seq = [i for i in idents if i["formato"] == FORMATO_SEQUENCIAL]
    regs = [i for i in idents if i["formato"] == FORMATO_REGISTRO]
    if reg.tribunal == "STJ":
        if perfil.ood and regs and rng.random() < 0.08:
            return regs[0]
        return seq[0] if seq else idents[0]
    if reg.tribunal == "TSE":
        if perfil.ood and seq and rng.random() < 0.4:
            return seq[0]      # número antigo (nunca citado no dev)
        return cnj[0] if cnj else idents[0]
    return idents[0]


def _numero_superficie(digitos: str, formato: str, tribunal: str | None, nivel: int, rng: random.Random,
                       ruidos: list[str]) -> str:
    if formato == FORMATO_CNJ:
        return _superficie_cnj(digitos, tribunal)
    if formato == FORMATO_REGISTRO:
        return _superficie_registro(digitos)
    if len(digitos) > 3 and rng.random() < 0.17:
        ruidos.append("numero_sem_pontos_de_milhar")
        return digitos
    return _com_pontos(digitos)


def _montar_processo(cadeia: list[str], digitos: str, formato: str, tribunal: str | None, uf: str | None,
                     perfil: Perfil, rng: random.Random) -> Citacao:
    """Renderiza classe + conector + número + UF; aplica ruído conforme o perfil."""
    ruidos: list[str] = []
    forma: dict[str, str] = {"formato": formato}
    cadeia = list(cadeia)
    principal = _classe_principal(cadeia) or (cadeia[-1] if cadeia else None)
    ood = False
    # omissão de prefixos (docs/03 §7: 2/77)
    if len(cadeia) > 1 and rng.random() < max(0.03, perfil.taxas.omitir_prefixos):
        cadeia = [cadeia[-1]]
        ruidos.append("prefixos_omitidos")
    # estilo
    if tribunal == "TST" and formato == FORMATO_CNJ:
        estilo = "tst" if rng.random() < 0.7 else ("hifen_tst" if len(cadeia) > 1 else "conector")
    elif tribunal == "TSE" and len(cadeia) > 1:
        estilo = "hifen" if rng.random() < 0.5 else "conector"
    else:
        estilo = "conector"
    partes: R.Partes = [["prefixo", ""], ["tst", ""]]
    if estilo == "tst":
        partes[1][1] = "TST-" if rng.random() < 0.9 else "TST- "
        if rng.random() < 0.55:
            partes[0][1] = rng.choice(["processo nº ", "Processo nº ", "processo n.º "] if perfil.ood else ["processo nº ", "Processo nº "])
        cadeia_partes, genero, _ = _render_cadeia(cadeia, tribunal, "tst", perfil, rng)
        partes.extend(cadeia_partes)
        partes.extend([["conector", ""], ["espaco", "-"]])
        estilo_info = "tst"
    elif estilo == "hifen_tst":
        cadeia_partes, genero, _ = _render_cadeia(cadeia, tribunal, "tst", perfil, rng)
        partes.extend(cadeia_partes)
        partes.extend([["conector", ""], ["espaco", "-"]])
        estilo_info = "tst"
        ruidos.append("sem_prefixo_tst")
    else:
        cadeia_partes, genero, e_ood = _render_cadeia(cadeia, tribunal, estilo, perfil, rng)
        ood = ood or e_ood
        partes.extend(cadeia_partes)
        conector = " nº" if rng.random() < 0.47 else ""
        partes.extend([["conector", conector], ["espaco", " "]])
        estilo_info = estilo
    numero = _numero_superficie(digitos, formato, tribunal, perfil.nivel, rng, ruidos)
    partes.append(["numero", numero])
    tem_uf = bool(uf) and uf in UFS and not (formato == FORMATO_CNJ and tribunal in ("TST", "TSE"))
    if tem_uf and formato == FORMATO_CNJ and rng.random() < 0.15:
        tem_uf = False
    if formato == FORMATO_REGISTRO:
        tem_uf = False
    partes.extend([["sep", "/" if tem_uf else ""], ["uf", uf if tem_uf else ""], ["fecha", ""]])
    info = R.InfoProcesso(formato=formato, tribunal=tribunal, classe_principal=principal, estilo=estilo_info,
                          tem_uf=tem_uf)
    ruidos.extend(R.ruido_processo(partes, info, perfil.taxas, rng))
    if any(r.startswith("ood:") for r in ruidos):
        ood = True
    forma.update({"estilo": estilo_info, "conector": partes[[p[0] for p in partes].index("conector")][1].strip() or "-",
                  "sep_uf": repr(partes[[p[0] for p in partes].index("sep")][1]) if tem_uf else "-"})
    return Citacao(familia="processo", tipo="jurisprudencia", classificacao="real", id_canonico=None, partes=partes,
                   genero=genero, ruidos=sorted(set(ruidos)), forma=forma, tribunal=tribunal, digitos=digitos,
                   cadeia=cadeia, uf=uf if tem_uf else None, ood=ood)


def _cadeia_inedita(cadeia: list[str]) -> bool:
    """Cadeia com alguma sigla que a base tem mas o dev nunca citou (ARE, EREsp, MS, RO, RRAg, AIRR, EI, HC…)."""
    for s in cadeia:
        if s in M.ORDINAIS:
            continue
        tab = M.CLASSES.get(s)
        if tab is None or not tab["dev"]:
            return True
    return False


def _sortear_tribunal(materia: str, rng: random.Random) -> str:
    opcoes = M.TRIBUNAIS_POR_MATERIA[materia]
    return rng.choices([t for t, _ in opcoes], weights=[w for _, w in opcoes], k=1)[0]


def _citacao_processo_real(am: _Amostrador, materia: str, perfil: Perfil, rng: random.Random,
                           usados: set[str]) -> Citacao | None:
    for _ in range(40):
        tribunal = _sortear_tribunal(materia, rng)
        reg = rng.choice(am.acordaos[tribunal])
        if reg.documento_id in usados:
            continue
        ident = _escolher_identificador(reg, am, perfil, rng)
        if ident is None:
            continue
        digitos = ident["digitos"]
        if digitos in usados:
            continue
        donos = am.ambiguo(digitos)
        ambiguo = len(donos) > 1
        if ambiguo:
            if not perfil.ood:
                continue
            # só aceita ambiguidade que a cadeia de classes resolva (duplicatas puras não têm resposta)
            cadeias = {am.base.registro(d).classe_propria for d in donos}  # type: ignore[union-attr]
            if len(cadeias) != len(donos):
                continue
        cadeia = (ident["classe_propria"] or "").split()
        if not cadeia:
            continue
        inedita = _cadeia_inedita(cadeia)
        if inedita and not perfil.ood:
            continue
        cit = _montar_processo(cadeia, digitos, ident["formato"], tribunal, ident.get("uf") or reg.uf, perfil, rng)
        cit.classificacao = "real"
        cit.id_canonico = reg.id_canonico
        cit.origem_id = reg.documento_id
        if inedita:
            cit.ruidos = sorted(set(cit.ruidos + ["ood:classe_inedita"]))
            cit.ood = True
        if ambiguo:
            cit.ruidos = sorted(set(cit.ruidos + ["ood:numero_ambiguo"]))
            cit.ood = True
        if ident["formato"] == FORMATO_REGISTRO:
            cit.ruidos = sorted(set(cit.ruidos + ["ood:registro_stj"]))
            cit.ood = True
        if reg.tribunal == "TSE" and ident["formato"] == FORMATO_SEQUENCIAL:
            cit.ruidos = sorted(set(cit.ruidos + ["ood:numero_antigo_tse"]))
            cit.ood = True
        usados.add(reg.documento_id)
        usados.add(digitos)
        return cit
    return None


_INVENTADA_CLASSES_DEV: list[tuple[str, str, int]] = [
    ("RCL", "STF", 26), ("ARESP", "STJ", 4), ("RE", "STF", 3), ("RESP", "STJ", 3), ("RHC", "STJ", 3),
    ("APL", "STM", 1), ("AGINT", "STM", 1), ("RSE", "STM", 1),
]
_INVENTADA_CLASSES_OOD: list[tuple[str, str, int]] = [
    ("ARE", "STF", 3), ("ERESP", "STJ", 2), ("MS", "STF", 2), ("HC", "STJ", 2), ("RO", "TSE", 2),
    ("RRAG", "TST", 2), ("AIRR", "TST", 2), ("EI", "STM", 2), ("RMS", "STJ", 1), ("RESPE", "TSE", 2),
]


def _numero_fora_da_faixa(sigla: str, tribunal: str, rng: random.Random) -> tuple[str, str]:
    """(dígitos canônicos, formato) para número inexistente por construção (conferido depois)."""
    if tribunal == "STM":
        seq = rng.randint(7001500, 7999999)
        ano = rng.randint(2017, 2026)
        return f"{seq:07d}{rng.randint(10, 99):02d}{ano}7000000", FORMATO_CNJ
    if tribunal == "TSE":
        seq = rng.randint(1, 9999) if rng.random() < 0.5 else rng.randint(600000, 609999)
        ano = rng.randint(2012, 2023)
        return f"{seq:07d}{rng.randint(10, 99):02d}{ano}6{rng.randint(1, 27):02d}{rng.randint(1, 9999):04d}", FORMATO_CNJ
    if tribunal == "TST":
        seq = rng.randint(1, 999999)
        ano = rng.randint(2008, 2022)
        return f"{seq:07d}{rng.randint(10, 99):02d}{ano}5{rng.randint(1, 24):02d}{rng.randint(1, 9999):04d}", FORMATO_CNJ
    faixas = {"RCL": (11000, 99999), "RE": (1000000, 1999999), "ARE": (1000000, 1999999), "MS": (30000, 39999),
              "RESP": (1500000, 2199999), "ARESP": (1500000, 2999999), "ERESP": (1500000, 1999999),
              "RHC": (50000, 199999), "HC": (600000, 899999), "RMS": (40000, 79999)}
    a, b = faixas.get(sigla, (10000, 99999))
    return str(rng.randint(a, b)), FORMATO_SEQUENCIAL


def _perturbar(digitos: str, formato: str, tribunal: str | None, rng: random.Random) -> str:
    d = list(digitos)
    if formato == FORMATO_CNJ:
        posicoes = list(range(1 if tribunal == "STM" else 0, 9)) + list(range(16, 20))
        if tribunal == "STM":
            posicoes = list(range(1, 9))
        # sequenciais curtos (zeros à esquerda): perturba só dígitos significativos
        primeiro = next((i for i, c in enumerate(digitos[:7]) if c != "0"), 0)
        posicoes = [p for p in posicoes if p >= primeiro or p >= 7]
    else:
        posicoes = list(range(len(d)))
    k = 1 if rng.random() < 0.7 else 2
    for p in rng.sample(posicoes, min(k, len(posicoes))):
        atual = d[p]
        opcoes = [c for c in "0123456789" if c != atual]
        if p == 0 and formato != FORMATO_CNJ:
            opcoes = [c for c in opcoes if c != "0"]
        d[p] = rng.choice(opcoes)
    return "".join(d)


def _citacao_processo_inventada(am: _Amostrador, materia: str, perfil: Perfil, rng: random.Random,
                                usados: set[str]) -> Citacao | None:
    for _ in range(60):
        if rng.random() < 0.5:
            # perturbação de 1–2 dígitos de um número real (docs/04 §c: vizinhos a 1 dígito)
            tribunal = _sortear_tribunal(materia, rng)
            reg = rng.choice(am.acordaos[tribunal])
            ident = _escolher_identificador(reg, am, perfil, rng)
            if ident is None or ident["formato"] == FORMATO_REGISTRO:
                continue
            digitos = _perturbar(ident["digitos"], ident["formato"], tribunal, rng)
            formato = ident["formato"]
            cadeia = (ident["classe_propria"] or "").split()
            if not cadeia or (_cadeia_inedita(cadeia) and not perfil.ood):
                continue
            uf = rng.choice(sorted(UFS - {reg.uf})) if reg.uf else (rng.choice(sorted(UFS)) if tribunal == "STM" else None)
            origem = reg.documento_id
            modo = "perturbacao"
        else:
            pool = list(_INVENTADA_CLASSES_DEV) + (list(_INVENTADA_CLASSES_OOD) if perfil.ood else [])
            permitidos = {t for t, _ in M.TRIBUNAIS_POR_MATERIA[materia]}
            pool = [p for p in pool if p[1] in permitidos]
            sigla, tribunal, _ = rng.choices(pool, weights=[w for _, _, w in pool], k=1)[0]
            digitos, formato = _numero_fora_da_faixa(sigla, tribunal, rng)
            cadeia = [sigla]
            if sigla in ("RESP", "ARESP", "RCL", "RE") and rng.random() < 0.3:
                cadeia = [rng.choice(["AGINT", "AGR"]), sigla]
            uf = rng.choice(sorted(UFS)) if tribunal in ("STF", "STJ") or (tribunal == "STM" and rng.random() < 0.7) else None
            origem = None
            modo = "fora_da_faixa"
        if digitos in usados or am.existe_numero_proprio(digitos):
            continue
        cit = _montar_processo(cadeia, digitos, formato, tribunal, uf, perfil, rng)
        cit.classificacao = "inventada"
        cit.id_canonico = None
        cit.origem_id = origem
        cit.forma["inventada"] = modo
        if _cadeia_inedita(cadeia):
            cit.ood = True
            cit.ruidos = sorted(set(cit.ruidos + ["ood:classe_inedita"]))
        usados.add(digitos)
        return cit
    return None


# ---------------------------------------------------------------------------
# Súmulas, dispositivos, tema
# ---------------------------------------------------------------------------
def _montar_sumula(tribunal: str, vinculante: bool, numero: int, perfil: Perfil, rng: random.Random) -> Citacao:
    partes: R.Partes = [["palavra", "Súmula"], ["vinc", " Vinculante" if vinculante else ""],
                        ["numero", f" {numero}"], ["tribunal", "" if vinculante else f" do {tribunal}"]]
    ruidos = R.ruido_sumula(partes, perfil.taxas, rng)
    ood = any(r.startswith("ood:") for r in ruidos)
    return Citacao(familia="sumula", tipo="jurisprudencia", classificacao="inventada", id_canonico=None,
                   partes=partes, genero="f", ruidos=ruidos, forma={"vinculante": str(int(vinculante))},
                   tribunal="STF" if vinculante else tribunal, digitos=str(numero), ood=ood)


def _citacao_sumula(am: _Amostrador, perfil: Perfil, rng: random.Random, usados: set[str], real: bool) -> Citacao | None:
    if real:
        for _ in range(10):
            trib, vinc, num, reg = rng.choice(am.sumulas)
            chave = f"sumula:{trib}:{int(vinc)}:{num}"
            if chave in usados:
                continue
            usados.add(chave)
            cit = _montar_sumula(trib, vinc, num, perfil, rng)
            cit.classificacao, cit.id_canonico, cit.origem_id = "real", reg.id_canonico, reg.documento_id
            return cit
        return None
    for _ in range(20):
        sorteio = rng.random()
        ood = False
        if perfil.ood and sorteio < 0.25:
            trib, num = rng.choice(M.SUMULA_MUNDO_REAL_FORA_DA_BASE)
            ood = True
            modo = "mundo_real_fora_da_base"
        elif sorteio < 0.4:
            # tribunal errado para um número que existe na base sob outro tribunal
            trib_real, vinc_real, num, _ = rng.choice(am.sumulas)
            if vinc_real:
                continue
            trib = rng.choice([t for t in ("STF", "STJ", "TST", "TSE") if t != trib_real])
            modo = "tribunal_errado"
        else:
            trib = rng.choice(["STF", "SV", "TSE", "STJ", "TST"])
            a, b = M.SUMULA_INVENTADA_FAIXA[trib]
            num = rng.randint(a, b)
            modo = "numero_inexistente"
        vinc = trib == "SV"
        tribunal = "STF" if vinc else trib
        if am.base.sumula(tribunal, vinc, num) is not None:
            continue
        chave = f"sumula:{tribunal}:{int(vinc)}:{num}"
        if chave in usados:
            continue
        usados.add(chave)
        cit = _montar_sumula(tribunal, vinc, num, perfil, rng)
        cit.forma["inventada"] = modo
        cit.ood = cit.ood or ood
        if ood:
            cit.ruidos = sorted(set(cit.ruidos + ["ood:sumula_fora_da_base"]))
        return cit
    return None


def _montar_dispositivo(artigo: str, diploma_sup: str, perfil: Perfil, rng: random.Random, complemento: bool) -> Citacao:
    num = artigo
    if int(artigo) <= 9:
        num = f"{artigo}º"
    comp = ""
    if complemento:
        sorteio = rng.random()
        if sorteio < 0.5:
            comp = f", {rng.choice(M.INCISOS)}"
        elif sorteio < 0.7:
            comp = f", {rng.choice(M.INCISOS)}, {rng.choice(M.ALINEAS)}"
        else:
            comp = f", {rng.choice(M.PARAGRAFOS)}"
    genero_d = _genero_diploma(diploma_sup)
    partes: R.Partes = [["art", "art."], ["espaco", " "], ["numero", num], ["complemento", comp],
                        ["prep", f"{',' if comp else ''} {_artigo(genero_d, 'd')} "], ["diploma", diploma_sup]]
    ruidos = R.ruido_dispositivo(partes, perfil.taxas, rng)
    ood = any(r.startswith("ood:") for r in ruidos)
    return Citacao(familia="dispositivo", tipo="lei", classificacao="inventada", id_canonico=None, partes=partes,
                   genero="m", ruidos=ruidos, forma={"diploma_superficie": diploma_sup}, digitos=artigo, ood=ood)


def _superficie_diploma(diploma: str, perfil: Perfil, rng: random.Random) -> tuple[str, bool]:
    tab = M.DIPLOMAS[diploma]
    if perfil.ood and rng.random() < perfil.taxas.forma_art_ood:
        return rng.choice(list(tab["ood"])), True  # type: ignore[arg-type]
    return rng.choice(list(tab["dev"])), False  # type: ignore[arg-type]


def _citacao_dispositivo(am: _Amostrador, materia: str, perfil: Perfil, rng: random.Random, usados: set[str],
                         real: bool) -> Citacao | None:
    preferidos = M.DIPLOMAS_POR_MATERIA[materia]
    if real:
        opcoes = [(d, a, r) for d, a, r in am.dispositivos if d in preferidos] or list(am.dispositivos)
        for _ in range(10):
            dip, art, reg = rng.choice(opcoes)
            chave = f"disp:{dip}:{art}"
            if chave in usados:
                continue
            usados.add(chave)
            sup, ood = _superficie_diploma(dip, perfil, rng)
            cit = _montar_dispositivo(art, sup, perfil, rng, complemento=rng.random() < 0.25)
            cit.classificacao, cit.id_canonico, cit.origem_id = "real", reg.id_canonico, reg.documento_id
            cit.forma["diploma"] = dip
            cit.ood = cit.ood or ood
            if ood:
                cit.ruidos = sorted(set(cit.ruidos + ["ood:forma_diploma"]))
            return cit
        return None
    for _ in range(20):
        sorteio = rng.random()
        ood = False
        if sorteio < 0.22:
            fora = list(M.DIPLOMAS_FORA_DA_BASE_DEV) + (list(M.DIPLOMAS_FORA_DA_BASE_OOD) if perfil.ood else [])
            sup, _g, ultimo = rng.choice(fora)
            if perfil.ood and rng.random() < 0.4:
                art = str(rng.randint(1, ultimo))       # artigo que existe no mundo, diploma fora da base
                ood = True
                modo = "diploma_fora_da_base_artigo_existente"
            else:
                art = str(rng.randint(ultimo + 10, ultimo + 120))
                modo = "diploma_fora_da_base"
            dip = "FORA"
        elif sorteio < 0.37:
            # artigo que existe na base sob OUTRO diploma
            dip_real, art, _ = rng.choice(am.dispositivos)
            candidatos = [d for d in preferidos if d != dip_real] or [d for d in M.DIPLOMAS if d != dip_real]
            dip = rng.choice(candidatos)
            modo = "artigo_sob_outro_diploma"
        else:
            dip = rng.choice(preferidos)
            ultimo = int(M.DIPLOMAS[dip]["ultimo"])  # type: ignore[arg-type]
            art = str(rng.randint(ultimo + 5, int(ultimo * 1.3) + 60))
            modo = "artigo_inexistente"
        if dip != "FORA":
            if am.base.dispositivo(dip, art) is not None:
                continue
            sup, sup_ood = _superficie_diploma(dip, perfil, rng)
            ood = ood or sup_ood
        chave = f"disp:{dip}:{sup}:{art}"
        if chave in usados:
            continue
        usados.add(chave)
        cit = _montar_dispositivo(art, sup, perfil, rng, complemento=rng.random() < 0.2)
        cit.forma["inventada"] = modo
        cit.forma["diploma"] = dip
        cit.ood = cit.ood or ood
        if ood:
            cit.ruidos = sorted(set(cit.ruidos + ["ood:dispositivo"]))
        return cit
    return None


def _citacao_tema(perfil: Perfil, rng: random.Random) -> Citacao:
    numero = rng.randint(1000, 2999)
    palavra = "Tema"
    ruidos: list[str] = []
    if rng.random() < perfil.taxas.ocr_palavra_vaga:
        palavra = "Tcma"
        ruidos.append("ocr_palavra")
    partes: R.Partes = [["palavra", palavra], ["numero", f" {_com_pontos(str(numero))}"], ["complemento", " da repercussão geral"]]
    if perfil.taxas.ood:
        R._ocr_digito_fora_do_processo(partes[1], perfil.taxas, rng, ruidos, perfil.taxas.ocr_digito_normativo)
    return Citacao(familia="tema", tipo="jurisprudencia", classificacao="inventada", id_canonico=None, partes=partes,
                   genero="m", ruidos=sorted(set(ruidos)), forma={}, tribunal="STF", digitos=str(numero),
                   ood=any(r.startswith("ood:") for r in ruidos))


# ---------------------------------------------------------------------------
# Citações vagas (incompleta)
# ---------------------------------------------------------------------------
_PESOS_MOLDE = {1: {"A": 5, "B": 4, "C": 2, "D": 2, "E": 2}, 2: {"A": 4, "B": 2, "C": 5, "D": 3, "E": 3}}


def _citacao_vaga(am: _Amostrador, materia: str, perfil: Perfil, rng: random.Random, usados: set[str]) -> Citacao | None:
    pesos = dict(_PESOS_MOLDE[1 if perfil.nivel == 1 else 2])
    moldes: dict[str, dict[str, object]] = dict(M.MOLDES_VAGA)
    if perfil.ood:
        moldes.update(M.MOLDES_VAGA_OOD)
        for k in M.MOLDES_VAGA_OOD:
            pesos[k] = 2
    for _ in range(60):
        molde_id = rng.choices(list(pesos), weights=list(pesos.values()), k=1)[0]
        molde = moldes[molde_id]
        tribunal = _sortear_tribunal(materia, rng)
        reg = rng.choice(am.acordaos[tribunal])
        palavras = _palavras_relator(reg.relator)
        if not palavras or reg.ano is None:
            continue
        principal = reg.classe_principal
        classe_ext = sigla = None
        if molde_id == "C":
            if principal not in M.CLASSE_VAGA_EXTENSO:
                continue
            if not perfil.ood and principal not in ("RCL", "ARESP", "RHC", "RESP", "RE"):
                continue   # no dev o molde C só ocorre com Reclamação (STF) e AREsp/RHC (STJ)
            classe_ext = M.CLASSE_VAGA_EXTENSO[principal]
        if molde_id == "D":
            if principal not in M.CLASSE_VAGA_SIGLA:
                continue
            if not perfil.ood and principal not in ("RCL", "APL"):
                continue
            sigla = M.CLASSE_VAGA_SIGLA[principal]
        caixa_alta = rng.random() < 0.37
        nome = _nome_relator(palavras, rng, caixa_alta)
        chave = f"vaga:{tribunal}:{reg.ano}:{nome.lower()}"
        if chave in usados:
            continue
        candidatos = am.base.por_relator_ano(tribunal if molde["tribunal"] else None, reg.ano, nome)
        if len(candidatos) < 2:
            continue
        forma = str(molde["forma"])
        antes = forma.split("{N}")[0].format(T=tribunal, A=reg.ano, C=classe_ext or "", S=sigla or "")
        partes: R.Partes = [["texto", antes], ["nome", nome]]
        ruidos = R.ruido_vaga(partes, perfil.taxas, rng)
        if caixa_alta:
            ruidos = sorted(set(ruidos + ["relator_caixa_alta"]))
        genero = str(molde["genero"]) if molde["genero"] else _genero_sigla(principal or "RCL")
        usados.add(chave)
        cit = Citacao(familia="vaga", tipo="jurisprudencia", classificacao="incompleta", id_canonico=None,
                      partes=partes, genero=genero, ruidos=ruidos,
                      forma={"molde": molde_id, "relator_palavras": str(len(nome.split())), "candidatos": str(len(candidatos))},
                      tribunal=tribunal, cadeia=[principal] if principal and molde_id in ("C", "D") else [],
                      ood=molde_id in M.MOLDES_VAGA_OOD, origem_id=reg.documento_id)
        cit.forma["ano"] = str(reg.ano)
        cit.forma["relator"] = nome
        if cit.ood:
            cit.ruidos = sorted(set(cit.ruidos + ["ood:molde_vaga"]))
        return cit
    return None


# ---------------------------------------------------------------------------
# Plano de citações de um documento
# ---------------------------------------------------------------------------
# docs/03 §0: processo 119, vaga 32, dispositivo 28, súmula 12, tema 1 (de 192)
_FAMILIAS_PESOS = [("processo", 60), ("vaga", 18), ("dispositivo", 15), ("sumula", 6.5), ("tema", 0.5)]


def _planejar_citacoes(am: _Amostrador, materia: str, n: int, perfil: Perfil, rng: random.Random) -> list[Citacao]:
    """Sorteia primeiro o plano (família e classe de cada uma das ``n`` citações) e só
    depois tenta realizá-lo, para que falhas de amostragem (súmulas esgotadas, relator
    sem multiplicidade) não desloquem a distribuição para ``processo``."""
    usados: set[str] = set()
    citacoes: list[Citacao] = []
    plano = rng.choices([f for f, _ in _FAMILIAS_PESOS], weights=[w for _, w in _FAMILIAS_PESOS], k=n)
    if plano.count("tema") > 1:
        plano = [f if f != "tema" or i == plano.index("tema") else "processo" for i, f in enumerate(plano)]
    # docs/03 §0: processo 77 real / 42 inv; dispositivo 14 / 14; súmula 5 / 7
    for familia in plano:
        cit: Citacao | None = None
        for tentativa in range(4):
            if familia == "processo":
                real = rng.random() < 0.65
                cit = (_citacao_processo_real if real else _citacao_processo_inventada)(am, materia, perfil, rng, usados)
            elif familia == "vaga":
                cit = _citacao_vaga(am, materia, perfil, rng, usados)
            elif familia == "dispositivo":
                cit = _citacao_dispositivo(am, materia, perfil, rng, usados, real=rng.random() < 0.5)
            elif familia == "sumula":
                cit = _citacao_sumula(am, perfil, rng, usados, real=rng.random() < 0.45)
            elif familia == "tema":
                cit = _citacao_tema(perfil, rng)
            if cit is not None:
                break
        if cit is None:
            cit = _citacao_processo_real(am, materia, perfil, rng, usados)
        if cit is not None:
            citacoes.append(cit)
    return citacoes


# ---------------------------------------------------------------------------
# Montagem do documento
# ---------------------------------------------------------------------------
class _Montador:
    """Acumula pedaços de texto e registra offsets globais de spans e armadilhas."""

    def __init__(self, largura: int, rng: random.Random, p_proteger: float) -> None:
        self.pecas: list[str] = []
        self.tamanho = 0
        self.largura = largura
        self.rng = rng
        self.p_proteger = p_proteger   # probabilidade de um span NÃO ser partido pela quebra de linha
        self.spans: list[tuple[int, int, Citacao]] = []
        self.armadilhas: list[tuple[int, int, str]] = []

    def bruto(self, texto: str) -> None:
        self.pecas.append(texto)
        self.tamanho += len(texto)

    def paragrafo(self, pedacos: list[tuple[str, Citacao | None, str | None]]) -> None:
        """``pedacos``: (texto, citação-ou-None, rótulo-de-armadilha-ou-None). Quebra o parágrafo
        em linhas de ``largura`` e registra offsets (a quebra só troca espaços por ``\\n``)."""
        local = ""
        marcas: list[tuple[int, int, Citacao | None, str | None]] = []
        protegidos: list[tuple[int, int]] = []
        for texto, cit, rotulo in pedacos:
            ini = len(local)
            local += texto
            if cit is not None or rotulo is not None:
                marcas.append((ini, len(local), cit, rotulo))
            if cit is not None and self.rng.random() < self.p_proteger:
                protegidos.append((ini, len(local)))
        quebrado = _quebrar_linhas(local, self.largura, protegidos)
        assert len(quebrado) == len(local)
        base = self.tamanho
        for ini, fim, cit, rotulo in marcas:
            if cit is not None:
                self.spans.append((base + ini, base + fim, cit))
            else:
                self.armadilhas.append((base + ini, base + fim, rotulo or ""))
        self.bruto(quebrado + "\n\n")

    def texto(self) -> str:
        return "".join(self.pecas)


def _frase_citacao(cit: Citacao, rng: random.Random, taxas: R.Taxas) -> list[tuple[str, Citacao | None, str | None]]:
    molde = rng.choice(M.FRASES_CITACAO)
    antes, depois = molde.split("{cit}")
    art = _artigo(cit.genero)
    antes = antes.replace("n{o}", _artigo(cit.genero, "n")).replace("d{o}", _artigo(cit.genero, "d")).replace("{o}", art)
    # OCR só no texto de moldura; o artigo imediatamente anterior ao span fica intacto
    if " " in antes.rstrip():
        corpo, artigo = antes.rstrip().rsplit(" ", 1)
        antes = R.ocr_em_texto(corpo, taxas, rng) + " " + artigo + " "
    depois = R.ocr_em_texto(depois, taxas, rng)
    return [(antes, None, None), (cit.trecho, cit, None), (depois, None, None)]


def _escolher_inedita(opcoes: list[str], usadas: set[str], rng: random.Random) -> str:
    """Sorteia evitando frases já usadas no documento (quando ainda há inéditas)."""
    livres = [o for o in opcoes if o not in usadas]
    escolha = rng.choice(livres or opcoes)
    usadas.add(escolha)
    return escolha


def _frase_ligacao(materia: str, rng: random.Random, taxas: R.Taxas, ano: int, perfil: Perfil,
                   usadas: set[str]) -> tuple[str, str | None]:
    """Uma frase de enchimento; devolve (texto, rótulo de armadilha ou None)."""
    sorteio = rng.random()
    if sorteio < 0.45:
        frase = cab.preencher_distratores(_escolher_inedita(M.FRASES_MATERIA[materia], usadas, rng), rng, ano)
        rotulo = "distrator_numerico" if any(c.isdigit() for c in frase) else None
    elif sorteio < 0.62:
        frase = _escolher_inedita(M.FRASES_ARMADILHA, usadas, rng)
        rotulo = "armadilha_sem_identificador"
    elif perfil.ood and sorteio < 0.70:
        frase = _escolher_inedita(M.FRASES_ARMADILHA_OOD, usadas, rng)
        frase = frase.replace("{T}", rng.choice(["STF", "STJ", "TST", "TSE", "STM"])).replace("{A}", str(rng.randint(2016, 2026)))
        rotulo = "armadilha_ood"
    else:
        frase = _escolher_inedita(M.FRASES_LIGACAO, usadas, rng)
        rotulo = None
    return R.ocr_em_texto(frase, taxas, rng), rotulo


def gerar_documento(base: BaseCanonica, documento_id: str, nivel: int, perfil: Perfil, rng: random.Random,
                    am: _Amostrador | None = None) -> Documento:
    am = am or _Amostrador(base)
    materia = rng.choices(M.MATERIAS, weights=M.MATERIAS_PESOS, k=1)[0]
    cabecalho = cab.gerar_cabecalho(rng, materia, am.existe_numero_proprio)
    largura = rng.randint(92, 106)
    n_cit = rng.choice([4, 5, 6, 7, 8, 8, 8, 9, 9])
    citacoes = _planejar_citacoes(am, materia, n_cit, perfil, rng)
    rng.shuffle(citacoes)
    # dev: 18/99 spans N1 e 29/93 N2 com quebra de linha → protege ~70 % (N1) / ~45 % (N2/N3) dos spans
    mont = _Montador(largura, rng, 0.55 if perfil.nivel == 1 else 0.60)
    usadas: set[str] = set()
    # cabeçalho (sem spans): quebra linha a linha
    cab_texto = "\n".join(_quebrar_linhas(linha, largura) for linha in cabecalho.texto.split("\n"))
    mont.bruto(cab_texto)
    if rng.random() < 0.7:
        mont.bruto("\n")
    secoes = rng.choice(M.SECOES)
    # distribuição das citações: pré-seção 0–2, depois 1–3 por seção
    fila = list(citacoes)
    blocos: list[list[Citacao]] = []
    k = min(len(fila), rng.choice([0, 1, 1, 2]))
    blocos.append(fila[:k])
    fila = fila[k:]
    for i in range(len(secoes)):
        restantes_secoes = len(secoes) - i
        if not fila:
            blocos.append([])
            continue
        k = max(1, min(len(fila), round(len(fila) / restantes_secoes)))
        blocos.append(fila[:k])
        fila = fila[k:]
    if fila:
        blocos[-1].extend(fila)
    taxas = perfil.taxas
    for i, bloco in enumerate(blocos):
        if i > 0:
            mont.bruto(secoes[i - 1] + "\n\n")
        pedacos: list[tuple[str, Citacao | None, str | None]] = []
        n_lig = rng.randint(1, 3)
        for _ in range(n_lig):
            frase, rotulo = _frase_ligacao(materia, rng, taxas, cabecalho.ano, perfil, usadas)
            pedacos.append((frase, None, rotulo))
            pedacos.append((" ", None, None))
        for j, cit in enumerate(bloco):
            if j > 0:
                for _ in range(rng.randint(1, 2)):
                    frase, rotulo = _frase_ligacao(materia, rng, taxas, cabecalho.ano, perfil, usadas)
                    pedacos.append((frase, None, rotulo))
                    pedacos.append((" ", None, None))
            pedacos.extend(_frase_citacao(cit, rng, taxas))
            pedacos.append((" ", None, None))
        if not bloco or rng.random() < 0.6:
            frase, rotulo = _frase_ligacao(materia, rng, taxas, cabecalho.ano, perfil, usadas)
            pedacos.append((frase, None, rotulo))
            pedacos.append((" ", None, None))
        # remove o espaço final
        if pedacos and pedacos[-1][0] == " ":
            pedacos.pop()
        mont.paragrafo(pedacos)
    fechamento = rng.choice(M.FECHAMENTOS)
    despedida = rng.choice(M.DESPEDIDAS)
    mont.bruto(_quebrar_linhas(fechamento, largura) + "\n\n")
    if despedida:
        mont.bruto(despedida + "\n\n")
    mont.bruto(f"{rng.choice(M.CIDADES)}, {cab.data_extenso(rng, cabecalho.ano)}.\n")
    texto = mont.texto()
    if _nfc(texto) != texto:
        raise AssertionError("texto gerado não está em NFC")
    # gabarito com numeração que inclui as armadilhas (como no dev, os ids das armadilhas ficam ausentes)
    eventos: list[tuple[int, int, Any]] = [(i, f, c) for i, f, c in mont.spans] + [(i, f, None) for i, f, _ in mont.armadilhas if _ == "armadilha_sem_identificador"]
    eventos.sort(key=lambda e: e[0])
    gabarito: list[dict[str, Any]] = []
    for idx, (ini, fim, cit) in enumerate(eventos, start=1):
        if cit is None:
            continue
        trecho = texto[ini:fim]
        ruidos = list(cit.ruidos)
        if "\n" in trecho and "quebra_linha_no_span" not in ruidos:
            ruidos.append("quebra_linha_no_span")
        if cit.familia == "processo":
            partes_num = [p for p in cit.partes if p[0] == "numero"]
            pos = sum(len(p[1]) for p in cit.partes[: [p[0] for p in cit.partes].index("numero")])
            if partes_num and "\n" in trecho[pos: pos + len(partes_num[0][1])] and "quebra_linha_no_numero" not in ruidos:
                ruidos.append("quebra_linha_no_numero")
        gabarito.append({
            "nivel": nivel, "documento_id": documento_id, "citacao_id": f"g{idx}", "inicio": ini, "fim": fim,
            "trecho": trecho, "tipo": cit.tipo, "classificacao": cit.classificacao,
            "id_canonico": cit.id_canonico if cit.id_canonico is not None else "",
            "familia": cit.familia, "tribunal": cit.tribunal or "", "digitos": cit.digitos,
            "classe_cadeia": " ".join(cit.cadeia), "uf": cit.uf or "", "ruidos": "|".join(sorted(set(ruidos))),
            "forma": ";".join(f"{k}={v}" for k, v in sorted(cit.forma.items())), "ood": "1" if cit.ood else "0",
            "origem_id": cit.origem_id or "",
        })
    meta = {"materia": materia, "peca": cabecalho.peca, "cnj_cabecalho": cabecalho.cnj_distrator, "largura": largura,
            "fim_cabecalho": len(cab_texto)}
    return Documento(documento_id=documento_id, nivel=nivel, perfil=perfil.nome, texto=texto, gabarito=gabarito,
                     armadilhas=sorted(mont.armadilhas), meta=meta)


# ---------------------------------------------------------------------------
# Conjunto, validação, escrita
# ---------------------------------------------------------------------------
def validar_documento(doc: Documento) -> None:
    """Levanta ``AssertionError`` se algum invariante falhar (offsets, IoU, distância, NFC, LF)."""
    t = doc.texto
    if "\r" in t or t.startswith("﻿"):
        raise AssertionError(f"{doc.documento_id}: CR ou BOM no texto")
    if _nfc(t) != t:
        raise AssertionError(f"{doc.documento_id}: texto não NFC")
    spans = []
    for g in doc.gabarito:
        ini, fim = int(g["inicio"]), int(g["fim"])
        if not 0 <= ini < fim <= len(t):
            raise AssertionError(f"{doc.documento_id} {g['citacao_id']}: span fora do texto")
        if t[ini:fim] != g["trecho"]:
            raise AssertionError(f"{doc.documento_id} {g['citacao_id']}: trecho != texto[inicio:fim]")
        if t[ini].isspace() or t[fim - 1].isspace() or g["trecho"][-1] in ",.;:":
            raise AssertionError(f"{doc.documento_id} {g['citacao_id']}: fronteira com espaço/pontuação")
        if g["classificacao"] == "real" and not str(g["id_canonico"]).strip():
            raise AssertionError(f"{doc.documento_id} {g['citacao_id']}: real sem id_canonico")
        if g["classificacao"] != "real" and str(g["id_canonico"]).strip():
            raise AssertionError(f"{doc.documento_id} {g['citacao_id']}: id_canonico em classe não real")
        spans.append((ini, fim))
    spans.sort()
    for a in range(len(spans)):
        for b in range(a + 1, len(spans)):
            if iou(*spans[a], *spans[b]) >= 0.5:
                raise AssertionError(f"{doc.documento_id}: spans com IoU >= 0,5")
    for (ia, fa), (ib, fb) in zip(spans, spans[1:]):
        if ib - fa < DISTANCIA_MINIMA:
            raise AssertionError(f"{doc.documento_id}: spans a {ib - fa} chars (< {DISTANCIA_MINIMA})")
    if len(doc.gabarito) < 1:
        raise AssertionError(f"{doc.documento_id}: documento sem citações")


def gerar_conjunto(base: BaseCanonica, n_docs: int, nivel: int, seed: int, perfil: str = "dev") -> list[Documento]:
    """``n_docs`` documentos do nível/perfil, determinísticos por ``seed``. Cada item é
    ``Documento`` (desempacotável como ``(documento_id, texto, gabarito)``)."""
    p = perfil_para(nivel, perfil)
    am = _Amostrador(base)
    docs: list[Documento] = []
    for i in range(1, n_docs + 1):
        documento_id = f"sin_n{p.nivel}_{p.nome}_{i:03d}"
        rng = random.Random(f"caca-alucinacao:{VERSAO}:{seed}:{p.nivel}:{p.nome}:{i}")
        doc = gerar_documento(base, documento_id, p.nivel, p, rng, am)
        validar_documento(doc)
        docs.append(doc)
    return docs


def escrever_conjunto(docs: list[Documento], saida: Path | str, base: BaseCanonica | None = None,
                      casos_llm: bool = True, manifesto: dict[str, Any] | None = None) -> dict[str, Any]:
    """Escreve ``txt/``, ``goldenset.csv`` (colunas oficiais, utf-8-sig, ``\\n`` escapado no
    trecho), ``goldenset_estendido.csv``, ``casos_llm.jsonl`` (``escolher_candidato`` só com
    ``base``), ``estatisticas.json`` e ``manifesto.json``. Devolve as estatísticas."""
    saida = Path(saida)
    (saida / "txt").mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (saida / "txt" / f"{doc.documento_id}.txt").write_bytes(doc.texto.encode("utf-8"))
    for nome, colunas in (("goldenset.csv", COLUNAS_OFICIAIS), ("goldenset_estendido.csv", COLUNAS_OFICIAIS + COLUNAS_EXTRAS + ["origem_id"])):
        with open(saida / nome, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=colunas, extrasaction="ignore")
            w.writeheader()
            for doc in docs:
                for g in doc.gabarito:
                    linha = dict(g)
                    linha["trecho"] = linha["trecho"].replace("\n", "\\n")
                    w.writerow(linha)
    est = estatisticas(docs)
    if casos_llm:
        casos = gerar_casos_llm(docs, base)
        with open(saida / "casos_llm.jsonl", "w", encoding="utf-8") as f:
            for c in casos:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        est["casos_llm"] = dict(sorted(Counter(c["operacao"] for c in casos).items()))
    (saida / "estatisticas.json").write_text(json.dumps(est, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    if manifesto is not None:
        (saida / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return est


def ler_goldenset(caminho: Path | str) -> list[dict[str, str]]:
    """Lê um goldenset (oficial ou sintético) desfazendo o escape de ``\\n``."""
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f))
    for ln in linhas:
        ln["trecho"] = ln["trecho"].replace("\\n", "\n")
    return linhas


def estatisticas(docs: list[Documento]) -> dict[str, Any]:
    cits = [g for d in docs for g in d.gabarito]
    por_doc = [len(d.gabarito) for d in docs]
    distancias: list[int] = []
    for d in docs:
        spans = sorted((int(g["inicio"]), int(g["fim"])) for g in d.gabarito)
        distancias.extend(b[0] - a[1] for a, b in zip(spans, spans[1:]))
    ruidos = Counter(r for g in cits for r in g["ruidos"].split("|") if r)
    return {
        "documentos": len(docs),
        "citacoes": len(cits),
        "por_documento": {"min": min(por_doc), "mediana": statistics.median(por_doc), "max": max(por_doc)},
        "classificacao": dict(Counter(g["classificacao"] for g in cits)),
        "tipo": dict(Counter(g["tipo"] for g in cits)),
        "familia": dict(Counter(g["familia"] for g in cits)),
        "familia_x_classe": {f"{fam}/{cls}": n for (fam, cls), n in
                             sorted(Counter((g["familia"], g["classificacao"]) for g in cits).items())},
        "tribunal": dict(Counter(g["tribunal"] for g in cits if g["tribunal"])),
        "ruidos": dict(sorted(ruidos.items())),
        "citacoes_com_ruido": sum(1 for g in cits if g["ruidos"]),
        "ood": sum(1 for g in cits if g["ood"] == "1"),
        "distancia_entre_spans": {"min": min(distancias) if distancias else None,
                                  "mediana": statistics.median(distancias) if distancias else None},
        "tamanho_texto": {"min": min(len(d.texto) for d in docs), "max": max(len(d.texto) for d in docs)},
        "materias": dict(Counter(d.meta.get("materia", "") for d in docs)),
        "armadilhas": sum(len(d.armadilhas) for d in docs),
    }


# ---------------------------------------------------------------------------
# Casos para o árbitro LLM
# ---------------------------------------------------------------------------
def _janela(texto: str, ini: int, fim: int, antes: int = 90, depois: int = 90) -> tuple[int, int]:
    a = max(0, ini - antes)
    b = min(len(texto), fim + depois)
    while a > 0 and not texto[a - 1].isspace():
        a -= 1
    while b < len(texto) and not texto[b].isspace():
        b += 1
    return a, b


def gerar_casos_llm(docs: list[Documento], base: BaseCanonica | None = None) -> list[dict[str, Any]]:
    """JSONL para o árbitro: ``normalizar_citacao`` (processo), ``classificar_span``
    (todas as famílias + negativos) e ``escolher_candidato`` (real com candidatos ×
    inventada com vizinhos)."""
    casos: list[dict[str, Any]] = []
    for doc in docs:
        t = doc.texto
        for g in doc.gabarito:
            ini, fim = int(g["inicio"]), int(g["fim"])
            a, b = _janela(t, ini, fim)
            contexto = t[a:b]
            if g["familia"] == "processo":
                cadeia = g["classe_cadeia"].split()
                principal = _classe_principal(cadeia) if cadeia else None
                tribunal = g["tribunal"] or (M.TRIBUNAL_DA_CLASSE.get(principal or "") if principal else None)
                casos.append({"operacao": "normalizar_citacao", "documento_id": doc.documento_id, "citacao_id": g["citacao_id"],
                              "trecho": g["trecho"], "contexto": contexto,
                              "esperado": {"classe_cadeia": cadeia, "numero_digitos": g["digitos"], "uf": g["uf"] or None,
                                           "tribunal": tribunal, "eh_citacao": True}})
            casos.append({"operacao": "classificar_span", "documento_id": doc.documento_id, "citacao_id": g["citacao_id"],
                          "trecho": contexto, "contexto": t[max(0, a - 200): min(len(t), b + 200)],
                          "esperado": {"eh_citacao": True, "familia": g["familia"], "tipo": g["tipo"],
                                       "inicio_rel": ini - a, "fim_rel": fim - a}})
        for ini, fim, rotulo in doc.armadilhas:
            a, b = _janela(t, ini, fim, 40, 40)
            casos.append({"operacao": "classificar_span", "documento_id": doc.documento_id, "citacao_id": None,
                          "trecho": t[a:b], "contexto": t[max(0, a - 200): min(len(t), b + 200)], "rotulo": rotulo,
                          "esperado": {"eh_citacao": False, "familia": None, "tipo": None, "inicio_rel": None, "fim_rel": None}})
        cnj = doc.meta.get("cnj_cabecalho")
        if cnj and cnj in t:
            p = t.index(cnj)
            a, b = _janela(t, p, p + len(cnj), 30, 30)
            casos.append({"operacao": "classificar_span", "documento_id": doc.documento_id, "citacao_id": None,
                          "trecho": t[a:b], "contexto": t[: min(len(t), b + 200)], "rotulo": "cnj_cabecalho",
                          "esperado": {"eh_citacao": False, "familia": None, "tipo": None, "inicio_rel": None, "fim_rel": None}})
    if base is not None:
        casos.extend(_casos_escolher_candidato(docs, base))
    return casos


def _resumo_registro(base: BaseCanonica, documento_id: str) -> dict[str, Any]:
    r = base.registro(documento_id)
    assert r is not None
    return {"id_canonico": r.id_canonico, "documento_id": r.documento_id, "tribunal": r.tribunal, "ano": r.ano,
            "relator": r.relator, "classe_propria": r.classe_propria, "uf": r.uf,
            "cabecalho": base.cabecalho(r.documento_id, 160).replace("\n", " ")}


def _casos_escolher_candidato(docs: list[Documento], base: BaseCanonica) -> list[dict[str, Any]]:
    casos: list[dict[str, Any]] = []
    for doc in docs:
        t = doc.texto
        rng = random.Random(f"casos_llm:{doc.documento_id}")
        for g in doc.gabarito:
            if g["familia"] != "processo":
                continue
            ini, fim = int(g["inicio"]), int(g["fim"])
            a, b = _janela(t, ini, fim)
            contexto = t[a:b]
            if g["classificacao"] == "real":
                donos = base.candidatos_por_numero(g["digitos"])
                ids = [r.documento_id for r in donos]
                if len(ids) < 2:
                    # acrescenta 2–3 registros do mesmo tribunal/classe como distratores
                    alvo = base.registro(g["origem_id"])
                    if alvo is None:
                        continue
                    pool = [r for r in base.registros() if r.natureza == "acordao" and r.tribunal == alvo.tribunal
                            and r.documento_id != alvo.documento_id and r.classe_principal == alvo.classe_principal]
                    ids = [alvo.documento_id] + [r.documento_id for r in rng.sample(pool, min(3, len(pool)))]
                    rng.shuffle(ids)
                esperado = ids.index(g["origem_id"]) if g["origem_id"] in ids else None
                if esperado is None:
                    continue
                casos.append({"operacao": "escolher_candidato", "documento_id": doc.documento_id, "citacao_id": g["citacao_id"],
                              "trecho": g["trecho"], "contexto": contexto,
                              "candidatos": [_resumo_registro(base, d) for d in ids], "esperado": {"indice": esperado}})
            elif g["origem_id"]:
                # inventada por perturbação: o vizinho a 1–2 dígitos NÃO deve ser escolhido
                alvo = base.registro(g["origem_id"])
                if alvo is None:
                    continue
                pool = [r for r in base.registros() if r.natureza == "acordao" and r.tribunal == alvo.tribunal
                        and r.documento_id != alvo.documento_id]
                ids = [alvo.documento_id] + [r.documento_id for r in rng.sample(pool, min(2, len(pool)))]
                rng.shuffle(ids)
                casos.append({"operacao": "escolher_candidato", "documento_id": doc.documento_id, "citacao_id": g["citacao_id"],
                              "trecho": g["trecho"], "contexto": contexto,
                              "candidatos": [_resumo_registro(base, d) for d in ids], "esperado": {"indice": None}})
    return casos


__all__ = [
    "VERSAO", "COLUNAS_OFICIAIS", "COLUNAS_EXTRAS", "DISTANCIA_MINIMA", "PERFIS", "Perfil", "perfil_para",
    "Citacao", "Documento", "gerar_documento", "gerar_conjunto", "validar_documento", "escrever_conjunto",
    "ler_goldenset", "estatisticas", "gerar_casos_llm",
]
