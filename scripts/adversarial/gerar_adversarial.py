#!/usr/bin/env python3
"""Gerador de conjuntos ADVERSARIAIS (revisão 2 — generalização para o conjunto cego).

Constrói documentos com gabarito POR CONSTRUÇÃO a partir da base (dados/indice.json):
números próprios reais (real), perturbados/fora da base (inventada), tribunal+ano+relator
(incompleta), súmulas e dispositivos das tabelas derivadas.

Uso: PYTHONPATH=src python scripts/adversarial/gerar_adversarial.py [--saida dados/adversarial]

Conjuntos (cada um com >= 10 docs):
  siglas       (a) siglas nunca citadas no dev, prefixos encadeados inéditos, nomes por extenso
  conectores   (b) separadores/conectores inéditos
  ruido_n2     (c) ruído N2 combinado (2 letras OCR, OCR na sigla, NBSP+quebra+espaço duplo)
  vagas        (d) moldes de incompleta com redação nova
  distratores  (e) distratores novos + enumeração de precedentes
  frases       (f) duas citações na mesma frase; citação no fim do arquivo sem ponto
  cabecalhos   (g) cabeçalhos de layout diferente
  normativos   súmulas/dispositivos com formas novas
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.base_canonica import BaseCanonica  # noqa: E402

COLUNAS = ["nivel", "documento_id", "citacao_id", "inicio", "fim", "trecho", "tipo", "classificacao", "id_canonico"]

# ---------------------------------------------------------------------------
# superfícies de classe
# ---------------------------------------------------------------------------
SUP: dict[str, list[str]] = {
    "RESP": ["REsp", "Recurso Especial", "RESP"],
    "ARESP": ["AREsp", "Agravo em Recurso Especial"],
    "ERESP": ["EREsp", "Embargos de Divergência em Recurso Especial"],
    "EARESP": ["EAREsp", "Embargos de Divergência em Agravo em Recurso Especial"],
    "RHC": ["RHC", "Recurso em Habeas Corpus", "Recurso Ordinário em Habeas Corpus"],
    "RMS": ["RMS", "Recurso em Mandado de Segurança", "Recurso Ordinário em Mandado de Segurança"],
    "HC": ["HC", "Habeas Corpus"],
    "MS": ["MS", "Mandado de Segurança"],
    "AR": ["AR", "Ação Rescisória"],
    "AP": ["AP", "Ação Penal"],
    "CC": ["CC", "Conflito de Competência"],
    "RCL": ["Rcl", "Reclamação"],
    "RE": ["RE", "Recurso Extraordinário"],
    "ARE": ["ARE", "Recurso Extraordinário com Agravo"],
    "ADI": ["ADI", "Ação Direta de Inconstitucionalidade"],
    "AGR": ["AgRg", "AgR", "Agravo Regimental"],
    "AGINT": ["AgInt", "Agravo Interno"],
    "ED": ["EDcl", "ED", "Embargos de Declaração"],
    "EDV": ["EDv", "Embargos de Divergência"],
    "QO": ["QO", "Questão de Ordem"],
    "PEXT": ["PExt", "Pedido de Extensão"],
    "RESPE": ["REspe", "Recurso Especial Eleitoral"],
    "ARESPE": ["AREspE", "AREspEl", "Agravo em Recurso Especial Eleitoral"],
    "RO": ["RO", "Recurso Ordinário"],
    "AI": ["AI", "Agravo de Instrumento"],
    "AIJE": ["AIJE", "Ação de Investigação Judicial Eleitoral"],
    "PC": ["PC", "Prestação de Contas"],
    "LT": ["LT", "Lista Tríplice"],
    "PET": ["Pet", "Petição"],
    "AC": ["AC", "Ação Cautelar"],
    "RCED": ["RCED", "Recurso contra Expedição de Diploma"],
    "TUTCAUT": ["TutCautAnt", "Tutela Cautelar Antecedente"],
    "APL": ["APL", "Apelação", "Apelação Criminal"],
    "RSE": ["RSE", "Recurso em Sentido Estrito"],
    "EI": ["EI", "Embargos Infringentes e de Nulidade"],
    "CJ": ["CJ", "Conflito de Jurisdição"],
    "CP": ["CP", "Correição Parcial"],
    "RDI": ["RDI"],
    "RR": ["RR", "Recurso de Revista"],
    "AIRR": ["AIRR", "Agravo de Instrumento em Recurso de Revista"],
    "ARR": ["ARR", "Recurso de Revista com Agravo"],
    "RRAG": ["RRAg"],
    "ROT": ["ROT", "Recurso Ordinário Trabalhista"],
    "AG": ["Ag"],
    "E": ["E"],
    "EDCIV": ["EDCiv"],
    "SLS": ["SLS", "Suspensão de Liminar e de Sentença"],
    "SS": ["SS", "Suspensão de Segurança"],
}
GEN: dict[str, str] = {
    "RESP": "m", "ARESP": "m", "ERESP": "p", "EARESP": "p", "RHC": "m", "RMS": "m", "HC": "m", "MS": "m",
    "AR": "f", "AP": "f", "CC": "m", "RCL": "f", "RE": "m", "ARE": "m", "ADI": "f", "AGR": "m", "AGINT": "m",
    "ED": "p", "EDV": "p", "QO": "f", "PEXT": "m", "RESPE": "m", "ARESPE": "m", "RO": "m", "AI": "m",
    "AIJE": "f", "PC": "f", "LT": "f", "PET": "f", "AC": "f", "RCED": "m", "TUTCAUT": "f", "APL": "f",
    "RSE": "m", "EI": "p", "CJ": "m", "CP": "f", "RDI": "m", "RR": "m", "AIRR": "m", "ARR": "m", "RRAG": "m",
    "ROT": "m", "AG": "m", "E": "p", "EDCIV": "p", "SLS": "f", "SS": "f",
}
ORDINAIS = {"2O": "Segundo", "3O": "Terceiro", "10O": "Décimos"}
CONECT = {"m": "no", "f": "na", "p": "nos"}
CLASSES_VISTAS_NO_DEV = {"RESP", "RCL", "ARESP", "RR", "RHC", "RESPE", "APL", "RSE", "AGINT", "RE", "RMS", "AI",
                         "ARR", "ARESPE", "HC", "AR", "SLS", "RP"}

UFS_NOMES = {
    "AC": "ACRE", "AL": "ALAGOAS", "AM": "AMAZONAS", "AP": "AMAPÁ", "BA": "BAHIA", "CE": "CEARÁ",
    "DF": "DISTRITO FEDERAL", "ES": "ESPÍRITO SANTO", "GO": "GOIÁS", "MA": "MARANHÃO", "MG": "MINAS GERAIS",
    "MS": "MATO GROSSO DO SUL", "MT": "MATO GROSSO", "PA": "PARÁ", "PB": "PARAÍBA", "PE": "PERNAMBUCO",
    "PI": "PIAUÍ", "PR": "PARANÁ", "RJ": "RIO DE JANEIRO", "RN": "RIO GRANDE DO NORTE", "RO": "RONDÔNIA",
    "RR": "RORAIMA", "RS": "RIO GRANDE DO SUL", "SC": "SANTA CATARINA", "SE": "SERGIPE", "SP": "SÃO PAULO",
    "TO": "TOCANTINS",
}


def com_pontos(d: str) -> str:
    s = d.lstrip("0") or "0"
    g = []
    while len(s) > 3:
        g.insert(0, s[-3:])
        s = s[:-3]
    g.insert(0, s)
    return ".".join(g)


def cnj(d: str, tribunal: str | None, seq_cheio: bool = False) -> str:
    seq, dv, ano, j, tr, o = d[:7], d[7:9], d[9:13], d[13], d[14:16], d[16:20]
    if not (tribunal == "STM" or seq_cheio or (tribunal == "TSE" and int(ano) >= 2019 and seq.startswith("0"))):
        seq = seq.lstrip("0") or "0"
    return f"{seq}-{dv}.{ano}.{j}.{tr}.{o}"


# ---------------------------------------------------------------------------
# amostrador da base
# ---------------------------------------------------------------------------
class Amostra:
    def __init__(self, indice_json: Path, rng: random.Random) -> None:
        self.ind = json.load(open(indice_json, encoding="utf-8"))
        self.base = BaseCanonica(self.ind)
        self.regs = self.ind["registros"]
        self.pd = self.ind["por_digitos"]
        self.rng = rng
        self.usados: set[str] = set()
        self.itens: list[dict] = []
        for doc_id, r in self.regs.items():
            if r["natureza"] != "acordao":
                continue
            for it in r["identificadores"]:
                if it["formato"] not in ("sequencial", "cnj"):
                    continue
                self.itens.append({"doc": doc_id, "reg": r, "digitos": it["digitos"], "formato": it["formato"],
                                   "uf": it.get("uf"), "cadeia": (r["classe_propria"] or "").split(),
                                   "tribunal": r["tribunal"], "unico": len(self.pd[it["digitos"]]) == 1})

    def existe(self, digitos: str) -> bool:
        return digitos in self.pd

    def real(self, tribunal: str | None = None, filtro=None, unico: bool = True, min_digitos: int = 4) -> dict | None:
        cands = [i for i in self.itens if i["digitos"] not in self.usados and (not unico or i["unico"])
                 and (tribunal is None or i["tribunal"] == tribunal)
                 and all(t in SUP or t in ORDINAIS for t in i["cadeia"]) and i["cadeia"]
                 and (i["formato"] == "cnj" or len(i["digitos"]) >= min_digitos)
                 and (filtro is None or filtro(i))]
        if not cands:
            return None
        i = self.rng.choice(cands)
        self.usados.add(i["digitos"])
        return i

    def inventado(self, modelo: dict) -> str:
        """Perturba 1–2 dígitos (nunca o primeiro) até não existir na base."""
        d = modelo["digitos"]
        for _ in range(200):
            lst = list(d)
            k = self.rng.choice([1, 2])
            posicoes = list(range(1, len(d)))
            if modelo["formato"] == "cnj":
                posicoes = list(range(1, 7)) + [7, 8]   # sequencial e DV
            for p in self.rng.sample(posicoes, k):
                lst[p] = self.rng.choice([c for c in "0123456789" if c != lst[p]])
            novo = "".join(lst)
            if novo not in self.pd and novo not in self.usados and novo.lstrip("0"):
                self.usados.add(novo)
                return novo
        raise RuntimeError("não conseguiu perturbar")

    def numero_fora(self, tribunal: str, formato: str) -> str:
        for _ in range(500):
            if formato == "cnj":
                j = {"TST": "5", "TSE": "6", "STM": "7"}[tribunal]
                seq = self.rng.randint(7002000, 7999999) if tribunal == "STM" else self.rng.randint(100, 9999999)
                tr = "00" if tribunal == "STM" else f"{self.rng.randint(1, 24):02d}"
                o = "0000" if tribunal == "STM" else f"{self.rng.randint(1, 999):04d}"
                d = f"{seq:07d}{self.rng.randint(10, 99)}{self.rng.randint(2010, 2024)}{j}{tr}{o}"
            else:
                d = str(self.rng.randint(1000000, 2999999)) if tribunal == "STJ" else str(self.rng.randint(10000, 99999))
            if d not in self.pd and d not in self.usados:
                self.usados.add(d)
                return d
        raise RuntimeError

    def vaga(self, tribunal: str | None = None, min_mult: int = 2, n_palavras: tuple[int, int] = (2, 4)) -> dict | None:
        cands = [r for r in self.regs.values() if r["natureza"] == "acordao" and r["relator"] and r["ano"]
                 and (tribunal is None or r["tribunal"] == tribunal)]
        self.rng.shuffle(cands)
        for r in cands[:60]:
            palavras = palavras_relator(r["relator"])
            if not (n_palavras[0] <= len(palavras) <= n_palavras[1]):
                continue
            chave = f"{r['tribunal']}|{r['ano']}|{' '.join(palavras)}"
            if chave in self.usados:
                continue
            mult = len(self.base.por_relator_ano(r["tribunal"], r["ano"], " ".join(palavras)))
            if mult >= min_mult:
                self.usados.add(chave)
                return {"tribunal": r["tribunal"], "ano": r["ano"], "palavras": palavras, "mult": mult}
        return None

    def sumulas_reais(self) -> list[tuple[str, bool, int, str]]:
        out = []
        for k, doc in self.ind["normativos"]["sumulas"].items():
            t, v, n = k.split("|")
            out.append((t, v == "1", int(n), self.regs[doc]["id_canonico"]))
        return out

    def dispositivos_reais(self) -> list[tuple[str, str, str]]:
        return [(k.split("|")[0], k.split("|")[1], self.regs[doc]["id_canonico"])
                for k, doc in self.ind["normativos"]["dispositivos"].items()]


# ---------------------------------------------------------------------------
# consultas POSICIONAIS às tabelas normativas do índice (política de dados: nenhum número de
# artigo/súmula da base é escrito neste arquivo — ``artigo_k("CLT", 1)`` é "o 2º artigo da CLT
# na ordem do índice", o que quer que ele seja; a saída é determinística porque o índice é)
# ---------------------------------------------------------------------------
def artigo_k(am: "Amostra", diploma: str, k: int = 0) -> tuple[str, str]:
    """``(artigo, id_canonico)`` do k-ésimo artigo do diploma na tabela ``normativos.dispositivos``."""
    itens = [(a, i) for d, a, i in am.dispositivos_reais() if d == diploma]
    return itens[k % len(itens)]


def sumula_k(am: "Amostra", tribunal: str, vinculante: bool = False, k: int = 0) -> tuple[int, str]:
    """``(numero, id_canonico)`` da k-ésima súmula do tribunal na tabela ``normativos.sumulas``."""
    itens = [(n, i) for t, v, n, i in am.sumulas_reais() if t == tribunal and v == vinculante]
    return itens[k % len(itens)]


def com_ocr(palavra: str, de: str, para: str, n: int = 1) -> str:
    """``com_ocr("Súmula", "S", "5")`` → a forma com ruído, montada em tempo de execução."""
    return palavra.replace(de, para, n)


_RE_LIXO = re.compile(r"\b(DESEMBARGADOR|DESEMBARGADORA|CONVOCAD[OA]).*$", re.I)
PARTICULAS = {"de", "da", "do", "dos", "das", "e"}


def palavras_relator(relator: str) -> list[str]:
    t = _RE_LIXO.sub("", relator)
    t = re.sub(r"^\s*(Min\.|Ministro|Ministra|Des\.)\s+", "", t)
    return [p for p in t.split() if p.isalpha() and len(p) >= 2]


def nome_titulo(palavras: list[str]) -> str:
    return " ".join(p.lower() if p.lower() in PARTICULAS and i > 0 else p[0].upper() + p[1:].lower()
                    for i, p in enumerate(palavras))


# ---------------------------------------------------------------------------
# renderização de processo
# ---------------------------------------------------------------------------
def render_cadeia(cadeia: list[str], tribunal: str, estilo: str, rng: random.Random) -> str:
    """estilo: 'sigla' | 'extenso' | 'misto' | 'hifen' (TST/TSE)."""
    toks = list(cadeia)
    if tribunal == "TST":
        return "-".join(SUP[t][0] for t in toks)
    if estilo == "hifen" and tribunal == "TSE":
        return "-".join(SUP[t][0] for t in toks)
    partes: list[str] = []
    prefixo_ordinal = ""
    for k, t in enumerate(toks):
        if t in ORDINAIS:
            prefixo_ordinal = ORDINAIS[t] + " "
            continue
        formas = SUP[t]
        if estilo == "sigla":
            f = formas[0]
        elif estilo == "extenso":
            f = formas[1] if len(formas) > 1 else formas[0]
        else:
            f = rng.choice(formas)
        f = prefixo_ordinal + f
        prefixo_ordinal = ""
        if partes:
            partes.append(CONECT[GEN[t]])
        partes.append(f)
    return " ".join(partes)


def render_numero(digitos: str, formato: str, tribunal: str, pontos: bool = True) -> str:
    if formato == "cnj":
        return cnj(digitos, tribunal)
    return com_pontos(digitos) if pontos else digitos.lstrip("0")


# ---------------------------------------------------------------------------
# documento
# ---------------------------------------------------------------------------
class Doc:
    def __init__(self, doc_id: str, nivel: int) -> None:
        self.id = doc_id
        self.nivel = nivel
        self.partes: list[str] = []
        self.pos = 0
        self.gab: list[dict] = []
        self.protegidos: list[tuple[int, int]] = []
        self.notas: list[str] = []

    def add(self, s: str) -> None:
        self.partes.append(s)
        self.pos += len(s)

    def cit(self, trecho: str, tipo: str, classificacao: str, id_canonico: str | int | None = None, nota: str = "") -> None:
        ini = self.pos
        self.add(trecho)
        self.gab.append({"nivel": self.nivel, "documento_id": self.id, "citacao_id": f"g{len(self.gab) + 1}",
                         "inicio": ini, "fim": self.pos, "trecho": trecho, "tipo": tipo,
                         "classificacao": classificacao, "id_canonico": "" if id_canonico is None else str(id_canonico),
                         "nota": nota})
        self.protegidos.append((ini, self.pos))

    def texto(self) -> str:
        return "".join(self.partes)


ENCH = [
    "A leitura conjunta dos dispositivos invocados conduz à mesma conclusão, sem que se possa cogitar de interpretação diversa.",
    "Não se trata, aqui, de revolver matéria fática, mas de aplicar o direito à moldura já delineada nas instâncias ordinárias.",
    "O ponto nodal da discussão reside na qualificação jurídica dos fatos incontroversos, como bem apontou a parte recorrida.",
    "Registre-se, por oportuno, que a questão foi devidamente prequestionada, o que afasta o óbice apontado na decisão agravada.",
    "Ainda que assim não fosse, subsiste fundamento autônomo a amparar a pretensão deduzida na peça recursal.",
    "A orientação dos tribunais superiores é firme no ponto, e não há razão para dela se afastar no caso concreto.",
    "Cumpre destacar que a parte adversa não impugnou especificamente os fundamentos da decisão recorrida.",
    "Nesse contexto, a pretensão deduzida encontra amparo na jurisprudência consolidada, como se passa a demonstrar.",
    "Os fatos foram registrados nos autos e não há controvérsia sobre a sua ocorrência, restando apenas a questão de direito.",
    "A tese defensiva não merece acolhida, pois desconsidera a moldura fática fixada pelas instâncias ordinárias.",
]
PREF = [
    ("Invoca-se, ainda, ", ", cuja fundamentação se pede vênia para transcrever."),
    ("Como já se reconheceu n", ", a matéria não comporta maior digressão."),
    ("Ampara a pretensão ", ", no ponto em que afasta a exigência combatida."),
    ("Nesse sentido é ", ", que enfrentou hipótese idêntica à dos autos."),
    ("A tese ora sustentada decorre diretamente d", ", como se vê da leitura do inteiro teor."),
    ("Confira-se, a propósito, ", ", em que a Corte fixou a orientação aplicável."),
    ("Colhe-se orientação no mesmo sentido em ", ", cujo teor se aplica integralmente ao caso."),
]


def artigo_para(trecho: str, genero: str | None = None) -> str:
    """Artigo definido antes da citação: o/a/os."""
    if genero is None:
        primeira = trecho.split()[0]
        chave = re.sub(r"[^A-Za-zÀ-ÿ]", "", primeira).upper()
        if chave.startswith(("EMBARGOS", "EDCL", "ED", "EDV", "EAR", "ERESP", "EI")):
            genero = "p"
        elif chave.startswith(("RCL", "RECLAMA", "ADI", "AR", "AP", "APL", "APELA", "ACAO", "AÇÃO", "PET", "PC", "LT", "QO", "TUT", "SLS", "SS", "SÚMULA", "SUMULA", "SUM", "ENUNCIADO", "DECISAO", "DECISÃO", "ACÓRDÃO", "CORREI", "CP", "LISTA", "PRESTA", "TUTELA", "SUSPENS", "QUEST", "PETI")):
            genero = "f" if not chave.startswith(("ACÓRDÃO", "ENUNCIADO")) else "m"
        else:
            genero = "m"
    return {"m": "o", "f": "a", "p": "os"}[genero]


def frase_com_citacao(doc: Doc, trecho: str, tipo: str, classe: str, idc, rng: random.Random, nota: str = "",
                      artigo: str | None = None, sem_ponto: bool = False) -> None:
    pref, suf = rng.choice(PREF)
    art = artigo if artigo is not None else artigo_para(trecho)
    if pref.endswith("n") or pref.endswith("d"):
        doc.add(pref + art + " ")
    else:
        doc.add(pref + art + " ")
    doc.cit(trecho, tipo, classe, idc, nota)
    doc.add(("" if sem_ponto else suf) + ("" if sem_ponto else " "))


def enchimento(doc: Doc, rng: random.Random, n: int = 1) -> None:
    for _ in range(n):
        doc.add(rng.choice(ENCH) + " ")


def quebrar(texto: str, largura: int, protegidos: list[tuple[int, int]], rng: random.Random,
            proteger: bool = True) -> str:
    """Troca espaços por '\\n' (mesmo número de codepoints) a cada ~largura colunas."""
    out = list(texto)
    col = 0
    ultimo_espaco = -1
    i = 0
    while i < len(out):
        ch = out[i]
        if ch == "\n":
            col = 0
            ultimo_espaco = -1
        else:
            col += 1
            if ch == " " and not (proteger and any(a < i < b for a, b in protegidos)):
                ultimo_espaco = i
            if col > largura and ultimo_espaco > 0:
                out[ultimo_espaco] = "\n"
                col = i - ultimo_espaco
                ultimo_espaco = -1
        i += 1
    return "".join(out)


def cabecalho_padrao(rng: random.Random, materia: str = "civel", cnj_cab: str | None = None) -> str:
    end = {
        "civel": "EXCELENTÍSSIMO SENHOR MINISTRO PRESIDENTE DO SUPERIOR TRIBUNAL DE JUSTIÇA",
        "penal": "MINISTÉRIO PÚBLICO FEDERAL\nPROCURADORIA-GERAL DA REPÚBLICA",
        "trab": "TRIBUNAL REGIONAL DO TRABALHO DA 2ª REGIÃO\nGABINETE DO DESEMBARGADOR",
        "eleit": "MINISTÉRIO PÚBLICO ELEITORAL\nPROCURADORIA REGIONAL ELEITORAL DE MINAS GERAIS",
        "mil": "MINISTÉRIO PÚBLICO MILITAR\nPROCURADORIA DE JUSTIÇA MILITAR",
    }[materia]
    cnj_cab = cnj_cab or f"{rng.randint(1000000, 9999999)}-{rng.randint(10, 99)}.{rng.randint(2018, 2024)}.{rng.choice('3458')}.{rng.randint(1, 26):02d}.{rng.randint(1, 9999):04d}"
    partes = [end, "", f"Autos nº {cnj_cab}", f"Recorrente: {rng.choice(['JOÃO DA SILVA PEREIRA', 'EMPRESA ALFA LTDA.', 'MARIA APARECIDA COSTA'])}",
              f"Recorrido: {rng.choice(['ESTADO DE SÃO PAULO', 'BANCO BETA S.A.', 'UNIÃO'])}"]
    if rng.random() < 0.5:
        partes.append(f"Protocolo nº {rng.randint(2019, 2024)}.{rng.randint(1000000, 9999999)}")
    if rng.random() < 0.3:
        partes.append(f"Valor da causa: R$ {rng.randint(10, 900)}.{rng.randint(100, 999)},{rng.randint(10, 99)}")
    partes += ["", rng.choice(["MEMORIAL", "PARECER", "CONTRARRAZÕES", "AGRAVO INTERNO"]), "",
               "Trata-se de recurso interposto contra acórdão que manteve a decisão de origem, pelos fundamentos que se passa a expor. "
               f"O patrono da parte (OAB/SP {rng.randint(100000, 399999)}) requer o processamento do apelo às fls. {rng.randint(10, 300)}/{rng.randint(301, 900)}.", ""]
    return "\n".join(partes) + "\n"


# ---------------------------------------------------------------------------
# citações-padrão
# ---------------------------------------------------------------------------
def cit_processo_real(am: Amostra, doc: Doc, rng: random.Random, tribunal: str | None = None, estilo: str = "misto",
                      filtro=None, sep_uf: str = "/", conector: str | None = None, nota: str = "", pontos: bool = True,
                      artigo: str | None = None, sem_ponto: bool = False, unico: bool = True) -> dict | None:
    i = am.real(tribunal, filtro, unico=unico)
    if i is None:
        return None
    trecho = montar_processo(i["cadeia"], i["digitos"], i["formato"], i["tribunal"], i["uf"], estilo, rng, sep_uf,
                             conector, pontos)
    frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, nota, artigo, sem_ponto)
    return i


def montar_processo(cadeia, digitos, formato, tribunal, uf, estilo, rng, sep_uf="/", conector=None, pontos=True,
                    prefixo_tst: str | None = None) -> str:
    cad = render_cadeia(cadeia, tribunal, estilo, rng)
    num = render_numero(digitos, formato, tribunal, pontos)
    if tribunal == "TST":
        p = prefixo_tst if prefixo_tst is not None else rng.choice(["TST-", "TST-", "", "processo nº TST-"])
        return f"{p}{cad}-{num}"
    if tribunal == "TSE" and estilo == "hifen":
        con = conector if conector is not None else rng.choice(["", " nº"])
        return f"{cad}{con} {num}"
    con = conector if conector is not None else rng.choice(["", " nº", " n."])
    s = f"{cad}{con} {num}"
    if uf and tribunal in ("STF", "STJ", "STM"):
        s += sep_uf + uf if sep_uf.startswith(" ") or sep_uf in ("/", "-", "–") else sep_uf + uf
    return s


def cit_processo_inventada(am: Amostra, doc: Doc, rng: random.Random, tribunal: str, estilo: str = "misto",
                           filtro=None, sep_uf: str = "/", conector: str | None = None, nota: str = "",
                           fora_da_faixa: bool = False, pontos: bool = True, cadeia: list[str] | None = None,
                           uf: str | None = None) -> str:
    modelo = am.real(tribunal, filtro, unico=False)
    if modelo is None:
        raise RuntimeError(f"sem modelo para {tribunal}")
    if fora_da_faixa:
        d = am.numero_fora(tribunal, modelo["formato"])
    else:
        d = am.inventado(modelo)
    cad = cadeia or modelo["cadeia"]
    uf_ = uf or modelo["uf"] or rng.choice(["SP", "RJ", "MG", "RS", "PR", "BA"])
    trecho = montar_processo(cad, d, modelo["formato"], tribunal, uf_, estilo, rng, sep_uf, conector, pontos)
    frase_com_citacao(doc, trecho, "jurisprudencia", "inventada", None, rng, nota)
    return trecho


MOLDES_VAGA_DEV = [
    "julgado do {T} proferido em {A} pela relatoria de {N}",
    "precedente do {T} de {A}, da relatoria de {N}",
    "acórdão do {T} julgado em {A} sob relatoria de {N}",
]
MOLDES_VAGA_NOVOS = [
    ("decisão do {T} de {A}, relatada pelo Ministro {N}", "F"),
    ("acórdão relatado pela Ministra {N} em {A} no {T}", "relator_antes_ano"),
    ("voto do relator Ministro {N} ({T}, {A})", "parenteses"),
    ("julgado do {T} de {A}, Min. {N}", "min_sem_rel"),
    ("aresto do {T}, {A}, Relator Ministro {N}", "G"),
    ("julgado do {T}, {A}, Rel. Min. {N}", "H"),
    ("precedente do {T} (Rel. Min. {N}, {A})", "parenteses_rel"),
    ("decisão proferida pelo {T} em {A}, de relatoria do Ministro {N}", "de_relatoria"),
    ("entendimento do {T} firmado em {A} sob a relatoria do Min. {N}", "entendimento"),
    ("acórdão do {TX} de {A}, Rel. Min. {N}", "tribunal_extenso"),
]
TRIB_EXT = {"STF": "Supremo Tribunal Federal", "STJ": "Superior Tribunal de Justiça", "TSE": "Tribunal Superior Eleitoral",
            "TST": "Tribunal Superior do Trabalho", "STM": "Superior Tribunal Militar"}


def cit_vaga(am: Amostra, doc: Doc, rng: random.Random, molde: str | None = None, nota: str = "", caixa_alta: bool = False,
             minusculas: bool = False, n_palavras=(2, 4), tribunal: str | None = None) -> None:
    v = am.vaga(tribunal, n_palavras=n_palavras)
    if v is None:
        return
    nome = " ".join(v["palavras"]).upper() if caixa_alta else nome_titulo(v["palavras"])
    if minusculas:
        nome = nome.lower()
    m = molde or rng.choice(MOLDES_VAGA_DEV)
    trecho = m.format(T=v["tribunal"], TX=TRIB_EXT[v["tribunal"]], A=v["ano"], N=nome)
    frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, nota + f" mult={v['mult']}")


def cit_sumula(doc: Doc, rng: random.Random, trecho: str, real: bool, idc=None, nota: str = "") -> None:
    frase_com_citacao(doc, trecho, "jurisprudencia", "real" if real else "inventada", idc, rng, nota, artigo="a")


def cit_dispositivo(doc: Doc, rng: random.Random, trecho: str, real: bool, idc=None, nota: str = "") -> None:
    frase_com_citacao(doc, trecho, "lei", "real" if real else "inventada", idc, rng, nota, artigo="o")


# ---------------------------------------------------------------------------
# conjuntos
# ---------------------------------------------------------------------------
def conjunto_siglas(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    sum_reais = am.sumulas_reais()
    disp_reais = am.dispositivos_reais()
    planos = [
        # (tribunal, filtro de cadeia, estilo, nota)
        ("STJ", lambda i: i["cadeia"][-1] in ("ERESP", "EARESP"), "sigla", "ERESP/EARESP sigla"),
        ("STJ", lambda i: i["cadeia"][-1] in ("ERESP", "EARESP"), "extenso", "ERESP extenso"),
        ("STJ", lambda i: i["cadeia"][-1] in ("RMS", "HC", "MS", "AR", "CC", "AP"), "sigla", "RMS/HC/MS/AR/CC"),
        ("STJ", lambda i: i["cadeia"][-1] in ("RMS", "HC", "MS", "AR", "CC"), "extenso", "extenso STJ"),
        ("STF", lambda i: i["cadeia"][-1] in ("ARE", "RE", "HC", "AR", "ADI", "MS"), "sigla", "STF ARE/RE/ADI"),
        ("STF", lambda i: i["cadeia"][-1] in ("ARE", "RE", "ADI"), "extenso", "STF extenso"),
        ("STF", lambda i: any(t in ORDINAIS for t in i["cadeia"]), "misto", "ordinal STF"),
        ("TSE", lambda i: i["cadeia"][-1] in ("RO", "AI", "MS", "AC", "PET", "AIJE", "PC", "LT", "AR", "RCED", "TUTCAUT"), "hifen", "TSE hifen"),
        ("TSE", lambda i: i["cadeia"][-1] in ("RO", "AI", "MS", "AC", "AIJE", "PC"), "extenso", "TSE extenso"),
        ("TSE", lambda i: i["cadeia"][-1] in ("RESPE", "ARESPE") and len(i["cadeia"]) >= 2, "hifen", "TSE ED-AgR-REspe"),
        ("TST", lambda i: i["cadeia"][-1] in ("AIRR", "RRAG", "ROT") or "AG" in i["cadeia"] or "AGR" in i["cadeia"], "sigla", "TST Ag-AIRR/RRAg"),
        ("TST", lambda i: "E" in i["cadeia"] or "EDCIV" in i["cadeia"], "sigla", "TST E-/EDCiv"),
        ("STM", lambda i: i["cadeia"][-1] in ("EI", "HC", "ED", "CJ", "CP", "RDI"), "sigla", "STM EI/HC/ED/CJ/RDI"),
        ("STM", lambda i: i["cadeia"][-1] in ("EI", "HC", "ED", "CJ", "CP"), "extenso", "STM extenso"),
        ("STJ", lambda i: len(i["cadeia"]) >= 3, "misto", "STJ cadeia longa"),
        ("STF", lambda i: len(i["cadeia"]) >= 3, "misto", "STF cadeia longa"),
    ]
    for n in range(12):
        doc = Doc(f"adv_siglas_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "trab", "eleit", "mil"])))
        enchimento(doc, rng, 1)
        meus = rng.sample(planos, 4)
        for trib, filtro, estilo, nota in meus:
            r = cit_processo_real(am, doc, rng, trib, estilo, filtro, nota=nota)
            if r is None:
                doc.notas.append(f"sem candidato: {nota}")
            enchimento(doc, rng, rng.choice([1, 2]))
        # inventadas com siglas inéditas
        trib, filtro, estilo, nota = rng.choice(planos)
        cit_processo_inventada(am, doc, rng, trib, estilo, filtro, nota="inventada " + nota)
        enchimento(doc, rng, 1)
        # inventadas por classe fora da base (ADPF, ADC) e por sigla inédita
        if n % 3 == 0:
            trecho = rng.choice([f"ADPF {rng.randint(100, 999)}", f"ADC nº {rng.randint(10, 99)}", f"Inq {com_pontos(str(rng.randint(3000, 4999)))}/DF"])
            frase_com_citacao(doc, trecho, "jurisprudencia", "inventada", None, rng, "classe sem registro na base", artigo="a")
            enchimento(doc, rng, 1)
        if n % 3 == 1:
            # número real do STF (Rcl) citado como REsp: tribunal incompatível pela classe → inventada (docs/04 h.2)
            i = am.real("STF", lambda i: i["cadeia"][-1] == "RCL" and i["formato"] == "sequencial", unico=True)
            if i:
                trecho = f"REsp nº {com_pontos(i['digitos'])}/{i['uf'] or 'SP'}"
                frase_com_citacao(doc, trecho, "jurisprudencia", "inventada", None, rng, "numero real STF citado como REsp (spec h.2)")
                enchimento(doc, rng, 1)
        if n % 3 == 2:
            # chave ambígua distinguível pela cadeia (docs/04 b)
            amb = [k for k, v in am.pd.items() if len(v) > 1 and len({am.regs[d]["classe_propria"] for d in v}) > 1
                   and k not in am.usados and all(am.regs[d]["natureza"] == "acordao" for d in v)]
            if amb:
                k = rng.choice(amb)
                docs_k = am.pd[k]
                d_alvo = rng.choice(docs_k)
                r = am.regs[d_alvo]
                it = next(i for i in r["identificadores"] if i["digitos"] == k)
                cad = (r["classe_propria"] or "").split()
                if cad and all(t in SUP or t in ORDINAIS for t in cad):
                    am.usados.add(k)
                    trecho = montar_processo(cad, k, it["formato"], r["tribunal"], it.get("uf"), "sigla", rng)
                    frase_com_citacao(doc, trecho, "jurisprudencia", "real", r["id_canonico"], rng, f"ambiguo por cadeia ({len(docs_k)} regs)")
                    enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        t, v, num, idc = rng.choice(sum_reais)
        cit_sumula(doc, rng, f"Súmula Vinculante {num}" if v else f"Súmula {num} do {t}", True, idc)
        enchimento(doc, rng, 1)
        dip, art, idc = rng.choice(disp_reais)
        nomes = {"CC": "Código Civil", "CDC": "Código de Defesa do Consumidor", "CE": "Código Eleitoral", "CF": "Constituição Federal",
                 "CLT": "CLT", "CPC": "CPC", "CPM": "Código Penal Militar", "CPP": "Código de Processo Penal", "LC64": "Lei Complementar nº 64/1990"}
        cit_dispositivo(doc, rng, f"art. {art} d{'a' if nomes[dip].startswith(('Constituição', 'CLT', 'Lei')) else 'o'} {nomes[dip]}", True, idc)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_conectores(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    formas = [
        # (conector, sep_uf, nota, plausibilidade)
        (" n.º", "/", "n.º", "alta"),
        (" número", "/", "número", "media"),
        (" N.º", "/", "N.º", "media"),
        (" num.", "/", "num.", "baixa"),
        (" nº", " ( ", "UF entre parênteses com espaço", "media"),
        (" nº", " — ", "travessão longo", "media"),
        ("", " – ", "en dash", "alta"),
        (" nº", "/ ", "barra espaço", "alta"),
        ("", " ", "UF só com espaço", "media"),
        (" n.", "-", "n. + hifen colado", "alta"),
        (" nº", "/", "/UF. fim de frase", "alta"),
        (" sob o nº", "/", "sob o nº", "baixa"),
        (" n°", "/", "sinal de grau", "alta"),
        (" Nº", " (", "Nº + (UF)", "alta"),
    ]
    for n in range(12):
        doc = Doc(f"adv_conectores_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal"])))
        enchimento(doc, rng, 1)
        for con, sep, nota, plaus in rng.sample(formas, 5):
            trib = rng.choice(["STJ", "STF", "STJ"])
            real = rng.random() < 0.6
            if real:
                i = am.real(trib, lambda i: i["formato"] == "sequencial", unico=True)
                if i is None:
                    continue
                uf = i["uf"] or "SP"
                cad = render_cadeia(i["cadeia"], trib, rng.choice(["sigla", "misto"]), rng)
                num = com_pontos(i["digitos"])
                idc, cls = i["reg"]["id_canonico"], "real"
            else:
                modelo = am.real(trib, lambda i: i["formato"] == "sequencial", unico=False)
                d = am.inventado(modelo)
                uf = modelo["uf"] or "RJ"
                cad = render_cadeia(modelo["cadeia"], trib, rng.choice(["sigla", "misto"]), rng)
                num = com_pontos(d)
                idc, cls = None, "inventada"
            if sep == " ( ":
                trecho = f"{cad}{con} {num} ( {uf} )"
            elif sep == " (":
                trecho = f"{cad}{con} {num} ({uf})"
            else:
                trecho = f"{cad}{con} {num}{sep}{uf}"
            if nota == "/UF. fim de frase":
                doc.add("Como se decidiu n" + artigo_para(trecho) + " ")
                doc.cit(trecho, "jurisprudencia", cls, idc, f"{nota} [{plaus}]")
                doc.add(". ")
            else:
                frase_com_citacao(doc, trecho, "jurisprudencia", cls, idc, rng, f"{nota} [{plaus}]")
            enchimento(doc, rng, rng.choice([1, 2]))
        # UF antes do número
        if n % 2 == 0:
            i = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"] == ["RESP"], unico=True)
            if i:
                trecho = f"REsp/{i['uf']} nº {com_pontos(i['digitos'])}"
                frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "UF antes do número [baixa]")
                enchimento(doc, rng, 1)
        else:
            # "autos do REsp nº X/UF": span só a citação
            i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
            if i:
                trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} nº {com_pontos(i['digitos'])}/{i['uf']}"
                doc.add("Extrai-se dos autos do ")
                doc.cit(trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], "autos do <cit> [alta]")
                doc.add(" a mesma orientação, que aqui se adota. ")
                enchimento(doc, rng, 1)
        # CNJ com separadores inéditos (TSE/STM)
        i = am.real(rng.choice(["STM", "TSE"]), lambda i: i["formato"] == "cnj", unico=True)
        if i:
            forma = rng.choice(["normal", "so_hifen", "espacos"])
            d = i["digitos"]
            c = cnj(d, i["tribunal"])
            if forma == "so_hifen":
                c = c.replace(".", "")
            elif forma == "espacos":
                c = c.replace(".", " ")
            cad = render_cadeia(i["cadeia"], i["tribunal"], "hifen" if i["tribunal"] == "TSE" else "sigla", rng)
            trecho = f"{cad} nº {c}" + (f"/{i['uf']}" if i["tribunal"] == "STM" and i["uf"] else "")
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, f"cnj {forma}")
            enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


OCR_MAP = {"1": "l", "0": "O", "5": "S", "9": "g", "6": "G"}   # só as trocas observadas no dev (docs/03 §3.1)


def ocr_no_numero(num: str, rng: random.Random, n_letras: int = 2) -> str:
    """Troca n dígitos (nunca o 1º) por letras confundíveis."""
    pos = [k for k, c in enumerate(num) if c in OCR_MAP and k > 0]
    if len(pos) < n_letras:
        return num
    out = list(num)
    for p in rng.sample(pos, n_letras):
        out[p] = OCR_MAP[out[p]]
    return "".join(out)


def conjunto_ruido_n2(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    sum_reais = am.sumulas_reais()
    disp_reais = am.dispositivos_reais()
    for n in range(12):
        doc = Doc(f"adv_ruido_n2_{n + 1:03d}", 2)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "trab"])))
        enchimento(doc, rng, 1)
        # (1) duas letras OCR no mesmo número curto (real)
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["digitos"]) == 7, unico=True)
        if i:
            num = ocr_no_numero(com_pontos(i["digitos"]), rng, 2)
            trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} nº {num}/{i['uf']}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "2 letras OCR no número")
            enchimento(doc, rng, 1)
        # (2) 2 letras OCR num número inventado (não pode virar real)
        modelo = am.real("STJ", lambda i: i["formato"] == "sequencial" and len(i["digitos"]) == 7, unico=False)
        d = am.inventado(modelo)
        num = ocr_no_numero(com_pontos(d), rng, 2)
        trecho = f"{render_cadeia(modelo['cadeia'], 'STJ', 'sigla', rng)} n° {num}/{modelo['uf'] or 'SP'}"
        frase_com_citacao(doc, trecho, "jurisprudencia", "inventada", None, rng, "2 letras OCR em inventada")
        enchimento(doc, rng, 1)
        # (3) OCR na sigla: RE5P, Aglnt, ARE5P, RCl
        i = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] in ("RESP", "ARESP"), unico=True)
        if i:
            cad = render_cadeia(i["cadeia"], "STJ", "sigla", rng)
            # S→5 e O→0 em caixa alta e I→l (docs/03 §3.1)
            cad_ocr = cad.replace("REsp", "RE5P").replace("AREsp", "ARE5P").replace("AgInt", "Aglnt").replace("EDcl", "EDcl")
            if cad_ocr == cad:
                cad_ocr = cad.replace("S", "5", 1)
            trecho = f"{cad_ocr} {com_pontos(i['digitos'])}/{i['uf']}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, f"OCR na sigla ({cad_ocr})")
            enchimento(doc, rng, 1)
        # (4) quebra de linha + NBSP + espaço duplo
        i = am.real("STF", lambda i: i["formato"] == "sequencial", unico=True)
        if i:
            cad = render_cadeia(i["cadeia"], "STF", "misto", rng)
            trecho = f"{cad}\xa0nº\n  {com_pontos(i['digitos'])} -\xa0{i['uf']}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "NBSP+quebra+espaço duplo")
            enchimento(doc, rng, 1)
        # (5) CNJ com letra OCR + quebra dentro
        i = am.real(rng.choice(["TST", "STM", "TSE"]), lambda i: i["formato"] == "cnj", unico=True)
        if i:
            c = cnj(i["digitos"], i["tribunal"])
            c = ocr_no_numero(c, rng, 1)
            k = c.find(".", 5)
            c = c[:k + 1] + "\n" + c[k + 1:]
            trecho = montar_processo(i["cadeia"], i["digitos"], "cnj", i["tribunal"], i["uf"], "sigla", rng)
            trecho = trecho.replace(cnj(i["digitos"], i["tribunal"]), c)
            frase_com_citacao(doc, trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], rng, "CNJ com OCR e quebra")
            enchimento(doc, rng, 1)
        # (6) súmula com OCR e vaga com OCR
        t, v, num, idc = rng.choice(sum_reais)
        s = rng.choice(["Sumula", com_ocr("Súmula", "S", "5"), "SÚMULA", "Súmulã", "Súrnula"])
        vinc = rng.choice(["Vinculante", "Vinculãnte", "Vineulante"])
        cit_sumula(doc, rng, f"{s} {vinc} {num}" if v else f"{s} {num} do {t}", True, idc, f"súmula OCR ({s} {vinc if v else ''})")
        enchimento(doc, rng, 1)
        v_ = am.vaga(n_palavras=(2, 3))
        if v_:
            nome = nome_titulo(v_["palavras"])
            nome_ocr = nome.replace("a", "ã", 1) if "a" in nome[1:] else nome.replace("i", "l", 1)
            trecho = f"julgãdo do {v_['tribunal']} {com_ocr('proferido', 'e', 'c')} em {v_['ano']} pelã relatoria dc {nome_ocr}"
            frase_com_citacao(doc, trecho, "jurisprudencia", "incompleta", None, rng, f"vaga OCR pesado mult={v_['mult']}")
            enchimento(doc, rng, 1)
        # (7) dispositivo com OCR no diploma e no artigo
        dip, art, idc = rng.choice(disp_reais)
        nomes = {"CC": "Códlgo Civil", "CDC": "Códlgo de Defesa do Consurnidor", "CE": "Código Eleitorãl", "CF": rng.choice(["C0nstituição Federal", "Constituição Fcderal", "Constituiçã0 Federal"]),
                 "CLT": "Consolidãção das Lcis do Trabalho", "CPC": "Código dc Processo Civil", "CPM": "Códlgo Penal Mllitar",
                 "CPP": "Código de Proccsso Penal", "LC64": "Lei Complcmentar nº 64/1990"}
        prep = "da" if dip in ("CF", "CLT", "LC64") else "do"
        art_ocr = art if len(art) < 3 else art[0] + OCR_MAP.get(art[1], art[1]) + art[2:]
        cit_dispositivo(doc, rng, f"art {art_ocr} {prep} {nomes[dip]}", True, idc, "dispositivo OCR")
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_vagas(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        nivel = 1 if n < 6 else 2
        doc = Doc(f"adv_vagas_n{nivel}_{n + 1:03d}", nivel)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "penal", "eleit", "mil"])))
        enchimento(doc, rng, 1)
        for molde, tag in rng.sample(MOLDES_VAGA_NOVOS, 5):
            cit_vaga(am, doc, rng, molde, nota=f"molde {tag}", caixa_alta=rng.random() < 0.3)
            enchimento(doc, rng, rng.choice([1, 2]))
        # nome com 5 palavras (título) — só se existir relator assim
        cit_vaga(am, doc, rng, MOLDES_VAGA_DEV[0], nota="nome 5 palavras", n_palavras=(5, 6))
        enchimento(doc, rng, 1)
        if n % 2 == 0:
            cit_vaga(am, doc, rng, "precedente do {T} de {A}, da relatoria de {N}", nota="nome minúsculas", minusculas=True)
            enchimento(doc, rng, 1)
        # uma real e uma inventada para manter classes
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_processo_inventada(am, doc, rng, "STF", "sigla")
        enchimento(doc, rng, 1)
        # armadilhas sem relator / sem ano (não são citação)
        doc.add(rng.choice(["O STJ, em 2019, consolidou o entendimento sobre a matéria em diversos julgados. ",
                            "Como anotou o Ministro relator em seu voto, a questão é de ordem pública. ",
                            "A Ministra relatora do caso paradigmático destacou a natureza da controvérsia. "]))
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_distratores(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        doc = Doc(f"adv_distratores_n1_{n + 1:03d}", 1)
        cnj_cab = f"{rng.randint(1000000, 9999999)}-{rng.randint(10, 99)}.{rng.randint(2018, 2024)}.8.26.{rng.randint(1, 999):04d}"
        doc.add(cabecalho_padrao(rng, "civel", cnj_cab))
        enchimento(doc, rng, 1)
        # lei sem artigo
        doc.add(rng.choice(["A pretensão funda-se na Lei nº 8.078/1990 e na Lei nº 13.105/2015, que regem a matéria. ",
                            "Aplica-se ao caso a Lei Complementar nº 64/1990, com as alterações posteriores. ",
                            "O Decreto-Lei nº 5.452/1943 disciplina integralmente a relação de emprego. "]))
        enchimento(doc, rng, 1)
        # súmula genérica sem número
        doc.add(rng.choice(["Aplica-se a súmula do STJ sobre o tema, cujo enunciado dispensa maiores comentários. ",
                            "O verbete sumular aplicável à espécie afasta a pretensão. ",
                            "A Súmula do Tribunal Superior do Trabalho sobre a matéria é clara. "]))
        enchimento(doc, rng, 1)
        # CNJ do próprio processo no corpo
        doc.add(f"Nestes autos nº {cnj_cab}, a parte autora requereu a produção de prova pericial. ")
        enchimento(doc, rng, 1)
        # números diversos
        doc.add(f"O contrato foi firmado em {rng.randint(1, 28):02d}{rng.randint(1, 12):02d}{rng.randint(2015, 2023)} e o pagamento de R$ {rng.randint(1, 99)}.{rng.randint(100, 999)},{rng.randint(10, 99)} ocorreu em {rng.randint(1, 28)}/{rng.randint(1, 12):02d}/{rng.randint(2016, 2024)}. ")
        doc.add(f"O réu, inscrito no CPF sob o nº {rng.randint(100, 999)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}-{rng.randint(10, 99)}, e a empresa, CNPJ {rng.randint(10, 99)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}/0001-{rng.randint(10, 99)}, foram citados. ")
        doc.add(f"O advogado, OAB {rng.randint(100000, 399999)}, informou o telefone (11) {rng.randint(90000, 99999)}-{rng.randint(1000, 9999)} para contato, conforme certidão de fls. {rng.randint(10, 99)}. ")
        enchimento(doc, rng, 1)
        # enumeração de precedentes: cada um anotado
        doc.add("Precedentes: ")
        itens = []
        for k in range(3):
            i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
            if i is None:
                break
            itens.append(i)
        for k, i in enumerate(itens):
            trecho = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}"
            doc.cit(trecho, "jurisprudencia", "real", i["reg"]["id_canonico"], "enumeração de precedentes")
            doc.add(", " if k < len(itens) - 2 else (" e " if k == len(itens) - 2 else ". "))
        enchimento(doc, rng, 1)
        # artigo sem diploma no corpo (ambíguo: gabarito NÃO anota — reportar como ambiguidade)
        doc.add(f"O art. {rng.choice(['5º', '37', '93, IX', '186'])} é claro ao respeito, como reconhece a doutrina. ")
        enchimento(doc, rng, 1)
        # citação normal para manter classes
        cit_processo_inventada(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        # tema sem "repercussão geral" / com
        if n % 2 == 0:
            frase_com_citacao(doc, f"Tema {com_pontos(str(rng.randint(1000, 1400)))} da repercussão geral", "jurisprudencia", "inventada", None, rng, "tema", artigo="o")
            enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


def conjunto_frases(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    for n in range(12):
        doc = Doc(f"adv_frases_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "mil"])))
        enchimento(doc, rng, 1)
        # duas citações na mesma frase (real + inventada)
        i = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        modelo = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=False)
        d = am.inventado(modelo)
        t1 = f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}"
        t2 = f"{render_cadeia(modelo['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(d)}/{modelo['uf'] or 'RJ'}"
        doc.add("Nesse sentido, " + artigo_para(t1) + " ")
        doc.cit(t1, "jurisprudencia", "real", i["reg"]["id_canonico"], "2 na frase (1)")
        doc.add(" e " + artigo_para(t2) + " ")
        doc.cit(t2, "jurisprudencia", "inventada", None, "2 na frase (2)")
        doc.add(" apontam para a mesma solução. ")
        enchimento(doc, rng, 1)
        # súmula e processo na mesma frase
        sr = rng.choice(am.sumulas_reais())
        t, v, num, idc = sr
        doc.add("Aplicam-se a ")
        doc.cit(f"Súmula Vinculante {num}" if v else f"Súmula {num} do {t}", "jurisprudencia", "real", idc, "súmula + processo na frase")
        doc.add(" e o ")
        i2 = am.real("STF", lambda i: i["formato"] == "sequencial", unico=True)
        doc.cit(f"{render_cadeia(i2['cadeia'], 'STF', 'sigla', rng)} {com_pontos(i2['digitos'])}/{i2['uf']}", "jurisprudencia", "real", i2["reg"]["id_canonico"], "súmula + processo na frase")
        doc.add(", sem espaço para dúvida. ")
        enchimento(doc, rng, 1)
        # dispositivo + processo, separados por ponto e vírgula
        dip, art, idd = rng.choice([x for x in am.dispositivos_reais() if x[0] in ("CPC", "CF", "CLT")])
        nomes = {"CPC": "do CPC", "CF": "da Constituição Federal", "CLT": "da CLT"}
        doc.add("Veja-se o ")
        doc.cit(f"art. {art} {nomes[dip]}", "lei", "real", idd, "disp+proc")
        doc.add("; no mesmo sentido, o ")
        i3 = am.real("TST", lambda i: i["formato"] == "cnj", unico=True)
        if i3:
            doc.cit(montar_processo(i3["cadeia"], i3["digitos"], "cnj", "TST", None, "sigla", rng, prefixo_tst="TST-"), "jurisprudencia", "real", i3["reg"]["id_canonico"], "disp+proc")
        doc.add(". ")
        enchimento(doc, rng, 2)
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        # citação entre parênteses
        i4 = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        if i4:
            doc.add("A matéria já foi enfrentada por esta Corte (")
            doc.cit(f"{render_cadeia(i4['cadeia'], 'STJ', 'sigla', rng)} nº {com_pontos(i4['digitos'])}/{i4['uf']}", "jurisprudencia", "real", i4["reg"]["id_canonico"], "entre parênteses")
            doc.add("), sem divergência. ")
            enchimento(doc, rng, 1)
        # citação no fim do arquivo, sem ponto
        i5 = am.real("STJ", lambda i: i["formato"] == "sequencial", unico=True)
        modelo5 = am.real("STF", lambda i: i["formato"] == "sequencial", unico=False)
        if n % 2 == 0 and i5:
            doc.add("Por fim, tudo conforme decidido no ")
            doc.cit(f"{render_cadeia(i5['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i5['digitos'])}/{i5['uf']}", "jurisprudencia", "real", i5["reg"]["id_canonico"], "fim de arquivo sem ponto")
        else:
            d5 = am.inventado(modelo5)
            doc.add("Por fim, tudo conforme decidido na ")
            doc.cit(f"Rcl {com_pontos(d5)}/{modelo5['uf'] or 'SP'}", "jurisprudencia", "inventada", None, "fim de arquivo sem ponto (inventada)")
        docs.append(doc)
    return docs


def conjunto_cabecalhos(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    layouts = ["sem_linha_em_branco", "ementa_caixa_alta", "prosa_na_2a_linha", "processo_no_corpo", "ementa_mista",
               "primeira_prosa_curta", "cabecalho_com_classe_real", "parecer_numerado", "referencia_no_fim", "sem_cabecalho",
               "duas_colunas_chave", "so_titulo"]
    for n in range(12):
        layout = layouts[n % len(layouts)]
        doc = Doc(f"adv_cabecalhos_n1_{n + 1:03d}", 1)
        cnj_cab = f"{rng.randint(1000000, 9999999)}-{rng.randint(10, 99)}.{rng.randint(2018, 2024)}.{rng.choice('4578')}.{rng.randint(1, 26):02d}.{rng.randint(1, 9999):04d}"
        abertura = ("Trata-se de recurso interposto contra acórdão que manteve a decisão de origem, pelos fundamentos "
                    "que se passa a expor, conforme razões de fls. 12/45.")
        if layout == "sem_linha_em_branco":
            doc.add(f"TRIBUNAL DE JUSTIÇA DO ESTADO DE SÃO PAULO\nAutos nº {cnj_cab}\nApelante: JOÃO DA SILVA\nApelada: EMPRESA ALFA LTDA.\nRAZÕES DE APELAÇÃO\n{abertura}\n")
        elif layout == "ementa_caixa_alta":
            doc.add(f"SUPERIOR TRIBUNAL DE JUSTIÇA\n\nProcesso nº {cnj_cab}\nRelator: Ministro Fulano\n\nEMENTA: RECURSO ESPECIAL. DIREITO CIVIL. RESPONSABILIDADE CIVIL. DANO MORAL. QUANTUM INDENIZATÓRIO. REVISÃO. SÚMULA 7/STJ. RECURSO NÃO CONHECIDO.\n\nACÓRDÃO\n\n{abertura}\n")
        elif layout == "prosa_na_2a_linha":
            doc.add(f"PARECER\n{abertura}\n")
        elif layout == "processo_no_corpo":
            doc.add(f"MINISTÉRIO PÚBLICO FEDERAL\n\nMemorial nº {rng.randint(10, 99)}/2024\n\n{abertura}\nO Processo nº {cnj_cab} teve origem na comarca de Campinas, sendo distribuído por dependência. ")
        elif layout == "ementa_mista":
            # ementa em caixa mista antes do 'Autos nº': prosa cai cedo
            doc.add(f"Ementa: Recurso especial. Responsabilidade civil por dano ambiental. Prescrição. Inocorrência. Precedentes desta Corte. Recurso provido.\n\nAutos nº {cnj_cab}\nRecorrente: FULANO\nProtocolo nº 2023.{rng.randint(1000000, 9999999)}\n\n{abertura}\n")
        elif layout == "primeira_prosa_curta":
            doc.add(f"DEFENSORIA PÚBLICA DA UNIÃO\n\nAutos nº {cnj_cab}\n\nMEMORIAL\n\nCuida-se de habeas corpus.\n")
            i = am.real("STJ", lambda i: i["formato"] == "sequencial" and i["cadeia"][-1] in ("HC", "RHC"), unico=True)
            if i:
                doc.add("Invoca-se o ")
                doc.cit(f"{render_cadeia(i['cadeia'], 'STJ', 'sigla', rng)} {com_pontos(i['digitos'])}/{i['uf']}", "jurisprudencia", "real", i["reg"]["id_canonico"], "citação em linha curta antes da 1ª prosa longa [media]")
                doc.add(".\n")
            doc.add(abertura + "\n")
        elif layout == "cabecalho_com_classe_real":
            i = am.real("STM", lambda i: i["formato"] == "cnj", unico=True)
            c = cnj(i["digitos"], "STM") if i else cnj_cab
            doc.add(f"SUPERIOR TRIBUNAL MILITAR\n\nAPELAÇÃO Nº {c}/{(i or {}).get('uf') or 'DF'}\nApelante: MINISTÉRIO PÚBLICO MILITAR\nApelado: SOLDADO FULANO\n\nPARECER\n\n{abertura}\n")
        elif layout == "parecer_numerado":
            doc.add(f"PARECER JURÍDICO Nº {rng.randint(100, 999)}/2024\n\nInteressado: Secretaria de Administração\nAssunto: viabilidade jurídica da contratação direta por inexigibilidade de licitação para serviços técnicos especializados\nReferência: autos nº {cnj_cab}\n\n{abertura}\n")
        elif layout == "referencia_no_fim":
            doc.add(f"CONTRARRAZÕES\n\n{abertura}\n")
        elif layout == "sem_cabecalho":
            doc.add(f"{abertura}\n")
        elif layout == "duas_colunas_chave":
            doc.add(f"Processo: {cnj_cab}    Classe: Apelação Cível    Origem: 3ª Vara Cível\nRelator: Des. Fulano de Tal    Sessão: 12/03/2024\n\n{abertura}\n")
        else:
            doc.add(f"AGRAVO INTERNO\n\n{abertura}\n")
        enchimento(doc, rng, 1)
        for _ in range(3):
            if rng.random() < 0.6:
                cit_processo_real(am, doc, rng, rng.choice(["STJ", "STF", "STM", "TST", "TSE"]), "misto")
            else:
                cit_processo_inventada(am, doc, rng, rng.choice(["STJ", "STF"]), "sigla")
            enchimento(doc, rng, rng.choice([1, 2]))
        cit_vaga(am, doc, rng)
        enchimento(doc, rng, 1)
        t, v, num, idc = rng.choice(am.sumulas_reais())
        cit_sumula(doc, rng, f"Súmula Vinculante {num}" if v else f"Súmula {num} do {t}", True, idc)
        enchimento(doc, rng, 1)
        if layout == "referencia_no_fim":
            doc.add(f"\nReferência: autos nº {cnj_cab}\nProtocolo nº 2024.{rng.randint(1000000, 9999999)}\n")
        if layout == "processo_no_corpo":
            doc.add(f"Registre-se que o processo nº {cnj_cab} encontra-se concluso para julgamento. ")
        docs.append(doc)
    return docs


def conjunto_normativos(am: Amostra, rng: random.Random) -> list[Doc]:
    docs = []
    sum_reais = {(t, v, n): idc for t, v, n, idc in am.sumulas_reais()}
    disp = {(d, a): idc for d, a, idc in am.dispositivos_reais()}
    formas_sumula = [
        (lambda t, n: f"Súmula nº {n} do {t}", "Súmula nº", "alta"),
        (lambda t, n: f"Súmula {n}/{t}", "Súmula N/T", "alta"),
        (lambda t, n: f"Súmula n. {n} do {t}", "Súmula n.", "alta"),
        (lambda t, n: f"Enunciado {n} da Súmula do {t}", "Enunciado N da Súmula do T", "media"),
        (lambda t, n: f"verbete nº {n} da Súmula do {t}", "verbete nº N da Súmula", "baixa"),
        (lambda t, n: f"Súmula {n} do {TRIB_EXT[t]}", "tribunal por extenso", "alta"),
        (lambda t, n: f"Súmula {n}, do {t}", "vírgula antes de do", "media"),
        (lambda t, n: f"Súmula {n} da jurisprudência do {t}", "da jurisprudência do", "media"),
        (lambda t, n: f"enunciado nº {n} da Súmula do {t}", "enunciado minúsculo", "baixa"),
    ]
    formas_sv = [
        (lambda n: f"Súmula Vinculante nº {n}", "SV nº", "alta"),
        (lambda n: f"SV {n}", "SV sigla", "media"),
        (lambda n: f"Súmula Vinculante {n} do STF", "SV do STF", "alta"),
        (lambda n: f"Súmula Vinculante n. {n}", "SV n.", "alta"),
    ]
    formas_disp = [
        (lambda a, d: f"art. {a} do CPC/2015", "CPC", "CPC/2015", "alta"),
        (lambda a, d: f"artigo {a}, LV, da CF/88", "CF", "CF/88", "alta"),
        (lambda a, d: f"art. {a} da CRFB", "CF", "CRFB", "media"),
        (lambda a, d: f"art. {a}, § 1º, da Constituição da República Federativa do Brasil", "CF", "CRFB extenso", "alta"),
        (lambda a, d: f"art. {a} do Código Civil de 2002", "CC", "CC de 2002", "media"),
        (lambda a, d: f"art. {a} da Lei nº 10.406/2002", "CC", "Lei 10.406", "alta"),
        (lambda a, d: f"art. {a} do Decreto-Lei nº 5.452/1943", "CLT", "DL 5.452", "alta"),
        (lambda a, d: f"art. {a}, caput, da Lei nº 8.078/90", "CDC", "Lei 8.078/90", "alta"),
        (lambda a, d: f"art. {a} da Lei nº 4.737/1965", "CE", "Lei 4.737", "alta"),
        (lambda a, d: f"art. {a}, I, \"g\", da LC 64/90", "LC64", "LC 64/90", "alta"),
        (lambda a, d: f"art. {a} do Decreto-Lei nº 1.001/1969", "CPM", "DL 1.001", "alta"),
        (lambda a, d: f"art. {a} do Decreto-Lei 3.689/41", "CPP", "DL 3.689/41", "media"),
        (lambda a, d: f"Art. {a} do Novo Código de Processo Civil", "CPC", "NCPC extenso", "media"),
        (lambda a, d: f"art. {a}, inciso IX, da Constituição", "CF", "Constituição só", "alta"),
        (lambda a, d: f"art. {a}º da Lei Maior", "CF", "Lei Maior", "baixa"),
        (lambda a, d: f"art. {a}, §§ 1º e 2º, da Consolidação das Leis do Trabalho", "CLT", "§§", "alta"),
        (lambda a, d: f"art. {a} do Código de Proteção e Defesa do Consumidor", "CDC", "CPDC", "media"),
        (lambda a, d: f"art. {a} da Lei Complementar 64, de 18 de maio de 1990", "LC64", "LC data extenso", "media"),
    ]
    inventadas_disp = [
        ("art. 1.500 do CPC", "artigo inexistente"), ("art. 400 do CDC", "artigo inexistente"),
        ("art. 37 da Constituição Federal", "artigo real fora da base"), ("art. 121 do Código Penal", "diploma fora da base"),
        ("art. 5º da Lei nº 9.099/1995", "lei fora da base"), ("art. 927 do Código Civil", "artigo real fora da base"),
        ("art. 10 da Lei nº 8.429/1992", "lei fora da base"),
        (f"art. {artigo_k(am, 'CPC')[0]} da Lei nº 13.467/2017", "artigo do CPC sob lei errada"),
        (f"art. {artigo_k(am, 'CPM')[0]} da Constituição da República", "artigo do CPM sob CF"),
        (f"art. {artigo_k(am, 'CPP')[0]} do Código Penal Militar", "artigo do CPP sob CPM"),
        (f"art. {artigo_k(am, 'CF', 1)[0]}º da CLT", "artigo da CF sob CLT"),
        (f"art. {artigo_k(am, 'CC')[0]} do Código de Defesa do Consumidor", "artigo do CC sob CDC"),
    ]
    inventadas_sum = [
        ("Súmula 7 do STJ", "real no mundo, fora da base"), ("Súmula 279 do STF", "real no mundo"), ("Súmula Vinculante 11", "SV real no mundo"),
        (f"Súmula {sumula_k(am, 'STJ', k=2)[0]} do STF", "número da base sob outro tribunal"),
        (f"Súmula {sumula_k(am, 'TST')[0]} do TSE", "tribunal trocado"),
        (f"Súmula {sumula_k(am, 'STJ', k=1)[0]} do TST", "tribunal trocado"),
        (f"Súmula {sumula_k(am, 'STF', True)[0]} do STF", "SV citada sem Vinculante"),
        (f"Súmula Vinculante {sumula_k(am, 'STJ', k=2)[0]}", "súmula do STJ como SV"),
        ("Súmula 1.200 do STJ", "fora da faixa"),
    ]
    for n in range(12):
        doc = Doc(f"adv_normativos_n1_{n + 1:03d}", 1)
        doc.add(cabecalho_padrao(rng, rng.choice(["civel", "trab", "eleit"])))
        enchimento(doc, rng, 1)
        for f, nota, pl in rng.sample(formas_sumula, 3):
            t, v, num = rng.choice([k for k in sum_reais if not k[1]])
            cit_sumula(doc, rng, f(t, num), True, sum_reais[(t, v, num)], f"{nota} [{pl}]")
            enchimento(doc, rng, 1)
        f, nota, pl = rng.choice(formas_sv)
        sv_num, sv_id = sumula_k(am, "STF", True)
        cit_sumula(doc, rng, f(sv_num), True, sv_id, f"{nota} [{pl}]")
        enchimento(doc, rng, 1)
        for f, dip, nota, pl in rng.sample(formas_disp, 3):
            arts = [a for (d, a) in disp if d == dip]
            a = rng.choice(arts)
            cit_dispositivo(doc, rng, f(a, dip), True, disp[(dip, a)], f"{nota} [{pl}]")
            enchimento(doc, rng, 1)
        for trecho, nota in rng.sample(inventadas_disp, 2):
            cit_dispositivo(doc, rng, trecho, False, None, nota)
            enchimento(doc, rng, 1)
        for trecho, nota in rng.sample(inventadas_sum, 2):
            cit_sumula(doc, rng, trecho, False, None, nota)
            enchimento(doc, rng, 1)
        cit_processo_real(am, doc, rng, "STJ", "sigla")
        enchimento(doc, rng, 1)
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
# escrita
# ---------------------------------------------------------------------------
def escrever(docs: list[Doc], pasta: Path, rng: random.Random, largura: int = 100, proteger: bool = True) -> None:
    (pasta / "txt").mkdir(parents=True, exist_ok=True)
    linhas = []
    for doc in docs:
        texto = doc.texto()
        texto = quebrar(texto, largura, doc.protegidos, rng, proteger)
        # confere/atualiza trechos após a quebra (mesmo número de codepoints)
        for g in doc.gab:
            g["trecho"] = texto[g["inicio"]:g["fim"]]
        (pasta / "txt" / f"{doc.id}.txt").write_bytes(texto.encode("utf-8"))
        # validação: distância entre spans e ausência de sobreposição
        spans = sorted((g["inicio"], g["fim"]) for g in doc.gab)
        for a, b in zip(spans, spans[1:]):
            assert b[0] >= a[1], (doc.id, a, b)
        linhas.extend(doc.gab)
    with open(pasta / "goldenset.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore", lineterminator="\r\n")
        w.writeheader()
        for g in linhas:
            linha = dict(g)
            linha["trecho"] = linha["trecho"].replace("\n", "\\n")
            w.writerow(linha)
    with open(pasta / "gabarito_notas.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS + ["nota"], lineterminator="\r\n")
        w.writeheader()
        for g in linhas:
            linha = dict(g)
            linha["trecho"] = linha["trecho"].replace("\n", "\\n")
            w.writerow(linha)
    notas = [f"{d.id}: {x}" for d in docs for x in d.notas]
    if notas:
        (pasta / "avisos.txt").write_text("\n".join(notas), encoding="utf-8")


CONJUNTOS = {
    "siglas": conjunto_siglas,
    "conectores": conjunto_conectores,
    "ruido_n2": conjunto_ruido_n2,
    "vagas": conjunto_vagas,
    "distratores": conjunto_distratores,
    "frases": conjunto_frases,
    "cabecalhos": conjunto_cabecalhos,
    "normativos": conjunto_normativos,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", type=Path, default=RAIZ / "dados" / "adversarial")
    ap.add_argument("--indice", type=Path, default=RAIZ / "dados" / "indice.json")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--so", nargs="*", default=None)
    args = ap.parse_args()
    for nome, fn in CONJUNTOS.items():
        if args.so and nome not in args.so:
            continue
        rng = random.Random(f"{args.seed}:{nome}")
        am = Amostra(args.indice, rng)
        docs = fn(am, rng)
        escrever(docs, args.saida / nome, rng, proteger=(nome != "ruido_n2"))
        n = sum(len(d.gab) for d in docs)
        print(f"{nome}: {len(docs)} docs, {n} citações")


if __name__ == "__main__":
    main()
