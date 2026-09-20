"""Cabeçalhos e distratores dos documentos sintéticos (docs/03 §6).

O cabeçalho reproduz a anatomia observada: endereçamento em caixa alta (1–2
linhas), linha em branco, ``Autos nº``/``Processo nº`` + CNJ distrator (segmento
J variado), partes, campos opcionais (``Protocolo nº``, ``Memorial nº``, ``Valor
da causa``, ``Relator``, ``Autoridade coatora``), título da peça em caixa alta e
um parágrafo de abertura (possivelmente com OAB). A variante "parecer jurídico"
começa por ``PARECER JURÍDICO Nº NNN/AAAA`` e traz ``Referência: autos nº``.

Nenhum número gerado aqui entra no gabarito; todos são distratores. O CNJ do
cabeçalho é conferido contra o índice para nunca coincidir com número próprio.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .moldes import CIDADES, MESES, SEGMENTOS_J_CABECALHO

_NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gustavo", "Helena", "Igor", "Juliana",
          "Leandro", "Marina", "Nelson", "Olívia", "Paulo", "Renata", "Sérgio", "Tatiana", "Vitor", "Yasmin"]
_SOBRENOMES = ["Almeida", "Barbosa", "Cardoso", "Duarte", "Esteves", "Ferreira", "Gonçalves", "Henriques",
               "Lacerda", "Macedo", "Nogueira", "Pacheco", "Queiroz", "Ribeiro", "Salgado", "Tavares",
               "Vasconcelos", "Xavier", "Zanetti", "Moreira"]
_EMPRESAS_A = ["Comercial", "Transportes", "Indústria", "Agropecuária", "Construtora", "Distribuidora",
               "Cooperativa", "Serviços", "Metalúrgica", "Logística"]
_EMPRESAS_B = ["Horizonte", "Vale Verde", "Três Rios", "Santa Clara", "Pontal", "Aurora", "Serra Azul",
               "Planalto", "Boa Vista", "Novo Norte"]
_EMPRESAS_C = ["LTDA", "S.A.", "EIRELI", "ME"]

_UFS_NOME = {
    "SP": "SÃO PAULO", "RJ": "RIO DE JANEIRO", "RS": "RIO GRANDE DO SUL", "PR": "PARANÁ", "BA": "BAHIA",
    "SC": "SANTA CATARINA", "MG": "MINAS GERAIS", "PE": "PERNAMBUCO", "CE": "CEARÁ", "GO": "GOIÁS",
    "DF": "DISTRITO FEDERAL", "MA": "MARANHÃO", "PA": "PARÁ", "ES": "ESPÍRITO SANTO",
}
_UFS = sorted(_UFS_NOME)

_TRIBUNAIS_ENDERECO: dict[str, list[list[str]]] = {
    "civel": [
        ["EXCELENTÍSSIMO SENHOR MINISTRO RELATOR", "SUPERIOR TRIBUNAL DE JUSTIÇA"],
        ["EXCELENTÍSSIMO SENHOR DESEMBARGADOR PRESIDENTE DO TRIBUNAL DE JUSTIÇA DO ESTADO DE {UFN}"],
        ["PODER JUDICIÁRIO", "TRIBUNAL REGIONAL FEDERAL DA {REGIAO} REGIÃO"],
        ["EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA {VARA}ª VARA CÍVEL DA COMARCA DE {CIDADE}"],
    ],
    "penal": [
        ["EXCELENTÍSSIMO SENHOR MINISTRO RELATOR", "SUPERIOR TRIBUNAL DE JUSTIÇA"],
        ["MINISTÉRIO PÚBLICO FEDERAL", "PROCURADORIA-GERAL DA REPÚBLICA"],
        ["EXCELENTÍSSIMO SENHOR MINISTRO PRESIDENTE DO SUPREMO TRIBUNAL FEDERAL"],
        ["PODER JUDICIÁRIO", "TRIBUNAL DE JUSTIÇA DO ESTADO DE {UFN}"],
    ],
    "trabalhista": [
        ["PODER JUDICIÁRIO", "TRIBUNAL REGIONAL DO TRABALHO DA {REGIAO} REGIÃO"],
        ["EXCELENTÍSSIMO SENHOR MINISTRO RELATOR", "TRIBUNAL SUPERIOR DO TRABALHO"],
        ["EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DA {VARA}ª VARA DO TRABALHO DE {CIDADE}"],
    ],
    "eleitoral": [
        ["EXCELENTÍSSIMO SENHOR MINISTRO RELATOR", "TRIBUNAL SUPERIOR ELEITORAL"],
        ["MINISTÉRIO PÚBLICO ELEITORAL", "PROCURADORIA REGIONAL ELEITORAL EM {UFN}"],
        ["PODER JUDICIÁRIO", "TRIBUNAL REGIONAL ELEITORAL DE {UFN}"],
    ],
    "militar": [
        ["DEFENSORIA PÚBLICA DA UNIÃO", "OFÍCIO JUNTO AO SUPERIOR TRIBUNAL MILITAR"],
        ["MINISTÉRIO PÚBLICO MILITAR", "PROCURADORIA-GERAL DE JUSTIÇA MILITAR"],
        ["EXCELENTÍSSIMO SENHOR MINISTRO RELATOR", "SUPERIOR TRIBUNAL MILITAR"],
    ],
}
_PECAS: dict[str, list[tuple[str, str]]] = {
    # (título, papel das partes) — papel define os rótulos das partes
    "civel": [("CONTRARRAZÕES AO RECURSO ESPECIAL", "recorrente"), ("AGRAVO INTERNO", "agravante"),
              ("MEMORIAL", "recorrente"), ("PARECER", "recorrente"), ("ACÓRDÃO", "apelante"),
              ("DECISÃO MONOCRÁTICA", "agravante"), ("PARECER JURÍDICO", "interessado")],
    "penal": [("AGRAVO REGIMENTAL EM HABEAS CORPUS", "impetrante"), ("PARECER", "recorrente"),
              ("MEMORIAL", "recorrente"), ("CONTRARRAZÕES AO RECURSO ESPECIAL", "recorrente"),
              ("DECISÃO MONOCRÁTICA", "agravante")],
    "trabalhista": [("ACÓRDÃO", "reclamante"), ("RECURSO DE REVISTA", "reclamante"), ("MEMORIAL", "recorrente"),
                    ("AGRAVO DE INSTRUMENTO", "agravante")],
    "eleitoral": [("RECURSO ESPECIAL ELEITORAL", "recorrente"), ("PARECER", "recorrente"),
                  ("AGRAVO INTERNO", "agravante"), ("MEMORIAL", "recorrente")],
    "militar": [("MEMORIAL", "assistido"), ("PARECER", "apelante"), ("RAZÕES DE APELAÇÃO", "apelante"),
                ("CONTRARRAZÕES DE APELAÇÃO", "apelante")],
}
_PARTES: dict[str, list[str]] = {
    "recorrente": ["Recorrente: {A}", "Recorrido: {B}"],
    "agravante": ["Agravante: {A}", "Agravado: {B}"],
    "apelante": ["Apelante: {A}", "Apelado: {B}"],
    "impetrante": ["Impetrante: {A}", "Paciente: {B}", "Autoridade coatora: Tribunal de Justiça DO {UFN}"],
    "reclamante": ["Reclamante: {A}", "Reclamada: {B}"],
    "assistido": ["Assistido: {A}"],
    "interessado": ["Interessado: {A}"],
}
_ABERTURAS: dict[str, list[str]] = {
    "recorrente": [
        "{A}, por seu advogado{OAB}, vem apresentar as razões que seguem, demonstrando o desacerto do acórdão recorrido.",
        "Trata-se de recurso interposto por {A} contra acórdão que manteve a decisão de primeiro grau.",
    ],
    "agravante": [
        "{A}, inconformado com a decisão monocrática que negou seguimento ao recurso, interpõe o presente agravo.",
        "Trata-se de agravo interposto contra decisão que inadmitiu o recurso, pelas razões a seguir expostas.",
    ],
    "apelante": [
        "Trata-se de apelação interposta contra sentença que julgou procedente a pretensão deduzida na inicial.",
        "{A}, por seu defensor{OAB}, apresenta razões de apelação contra a sentença condenatória.",
    ],
    "impetrante": [
        "A defesa do paciente, inconformada com a decisão que indeferiu liminarmente a ordem, interpõe o presente recurso.",
        "Trata-se de habeas corpus impetrado em favor de {B}, apontando constrangimento ilegal na manutenção da custódia.",
    ],
    "reclamante": [
        "Trata-se de recurso ordinário interposto contra sentença que julgou parcialmente procedentes os pedidos da reclamação trabalhista.",
        "{A}, por seu advogado{OAB}, interpõe recurso contra o acórdão regional, pelas razões que passa a expor.",
    ],
    "assistido": [
        "A Defensoria Pública da União apresenta o presente memorial em favor do assistido, sintetizando as teses já deduzidas.",
    ],
    "interessado": [
        "Submete-se a exame desta consultoria a questão relativa ao cabimento da tese sustentada nos autos em referência.",
    ],
}


@dataclass(frozen=True)
class Cabecalho:
    texto: str            # bloco completo, terminado em "\n\n"
    materia: str
    peca: str
    papel: str
    parte_a: str
    parte_b: str
    uf: str
    cnj_distrator: str    # o CNJ dos autos (nunca é citação)
    ano: int


def nome_pessoa(rng: random.Random, caixa_alta: bool = True) -> str:
    n = f"{rng.choice(_NOMES)} {rng.choice(_SOBRENOMES)} {rng.choice(_SOBRENOMES)}"
    return n.upper() if caixa_alta else n


def nome_empresa(rng: random.Random) -> str:
    return f"{rng.choice(_EMPRESAS_A)} {rng.choice(_EMPRESAS_B)} {rng.choice(_EMPRESAS_C)}".upper()


def cnj_distrator(rng: random.Random, ano: int | None = None, j: str | None = None) -> str:
    """CNJ ``NNNNNNN-DD.AAAA.J.TR.OOOO`` com segmento J variado (docs/03 §6.2)."""
    seq = rng.randint(1000000, 9999999)
    dv = rng.randint(10, 99)
    ano = ano or rng.randint(2014, 2026)
    j = j or rng.choice(SEGMENTOS_J_CABECALHO)
    tr = rng.randint(1, 27)
    orig = rng.randint(1, 9999)
    return f"{seq:07d}-{dv:02d}.{ano}.{j}.{tr:02d}.{orig:04d}"


def data_extenso(rng: random.Random, ano: int | None = None) -> str:
    dia = rng.randint(1, 28)
    mes = rng.choice(MESES)
    ano = ano or rng.randint(2015, 2026)
    return f"{dia} de {mes} de {ano}"


def folhas(rng: random.Random) -> str:
    a = rng.randint(12, 900)
    return f"fls. {a}/{a + rng.randint(1, 400)}"


def valor_reais(rng: random.Random) -> str:
    inteiro = rng.randint(1000, 999999)
    cent = rng.randint(0, 99)
    return f"R$ {inteiro:,}".replace(",", ".") + f",{cent:02d}"


def percentual(rng: random.Random) -> str:
    return f"{rng.randint(5, 60)}%"


def oab(rng: random.Random) -> str:
    return f" (OAB/{rng.choice(_UFS)} {rng.randint(100000, 999999)})"


def preencher_distratores(frase: str, rng: random.Random, ano: int | None = None) -> str:
    """Substitui ``{data}``, ``{fls}``, ``{valor}``, ``{pct}`` por distratores numéricos."""
    return (frase.replace("{data}", data_extenso(rng, ano)).replace("{fls}", folhas(rng))
            .replace("{valor}", valor_reais(rng)).replace("{pct}", percentual(rng)))


def gerar_cabecalho(rng: random.Random, materia: str, existe_numero_proprio) -> Cabecalho:
    """Cabeçalho completo. ``existe_numero_proprio(cnj) -> bool`` evita colisão com a base."""
    uf = rng.choice(_UFS)
    ufn = _UFS_NOME[uf]
    ano = rng.randint(2018, 2026)
    peca, papel = rng.choice(_PECAS[materia])
    parte_a = nome_empresa(rng) if rng.random() < 0.5 else nome_pessoa(rng)
    parte_b = nome_empresa(rng) if rng.random() < 0.4 else nome_pessoa(rng)
    if papel == "recorrente" and materia == "eleitoral" and rng.random() < 0.5:
        parte_b = "Ministério Público Eleitoral"
    if materia == "militar" and rng.random() < 0.5:
        parte_b = "Ministério Público Militar"
    cnj = cnj_distrator(rng, ano=rng.randint(2015, ano))
    tentativas = 0
    while existe_numero_proprio(cnj) and tentativas < 20:
        cnj = cnj_distrator(rng, ano=rng.randint(2015, ano))
        tentativas += 1
    subst = {"{UFN}": ufn, "{REGIAO}": rng.choice(["PRIMEIRA", "SEGUNDA", "TERCEIRA", "QUARTA", "QUINTA"]),
             "{VARA}": str(rng.randint(1, 12)), "{CIDADE}": rng.choice(CIDADES).upper()}

    def _s(texto: str) -> str:
        for k, v in subst.items():
            texto = texto.replace(k, v)
        return texto.replace("{A}", parte_a).replace("{B}", parte_b).replace("{UFN}", ufn)

    linhas: list[str] = []
    if peca == "PARECER JURÍDICO":
        linhas.append(f"PARECER JURÍDICO Nº {rng.randint(10, 400)}/{ano}")
        linhas.append("")
        linhas.append(f"Interessado: {parte_a}")
        linhas.append(f"Assunto: {rng.choice(['viabilidade da tese defensiva', 'cabimento de recurso às instâncias superiores', 'riscos da demanda em curso'])}")
        linhas.append(f"Referência: autos nº {cnj}")
        linhas.append(f"Elaborado por: {nome_pessoa(rng)}")
        linhas.append("")
        linhas.append("I — RELATÓRIO")
    else:
        for linha in rng.choice(_TRIBUNAIS_ENDERECO[materia]):
            linhas.append(_s(linha))
        linhas.append("")
        rotulo = rng.choice(["Autos nº", "Processo nº", "Autos n.º"]) if rng.random() < 0.15 else rng.choice(["Autos nº", "Processo nº"])
        linhas.append(f"{rotulo} {cnj}")
        for p in _PARTES[papel]:
            linhas.append(_s(p))
        opcionais = []
        if rng.random() < 0.3:
            opcionais.append(f"Protocolo nº {ano}.{rng.randint(1000000, 9999999)}")
        if peca == "MEMORIAL" and rng.random() < 0.7:
            opcionais.append(f"Memorial nº {rng.randint(10, 999)}/{ano}")
        if rng.random() < 0.25:
            opcionais.append(f"Valor da causa: {valor_reais(rng)}")
        if peca in ("ACÓRDÃO", "DECISÃO MONOCRÁTICA") or rng.random() < 0.2:
            titulo = "Desembargador" if materia in ("civel", "trabalhista") else rng.choice(["Ministro", "Desembargador"])
            opcionais.append(f"Relator: {titulo} {nome_pessoa(rng)}")
        if peca == "ACÓRDÃO" and rng.random() < 0.4:
            opcionais.append(f"Sessão de julgamento de {data_extenso(rng, ano)}")
        linhas.extend(opcionais)
        linhas.append("")
        linhas.append(peca)
    linhas.append("")
    abertura = rng.choice(_ABERTURAS[papel])
    abertura = _s(abertura).replace("{OAB}", oab(rng) if rng.random() < 0.6 else "")
    linhas.append(abertura)
    linhas.append("")
    texto = "\n".join(linhas) + "\n"
    return Cabecalho(texto=texto, materia=materia, peca=peca, papel=papel, parte_a=parte_a, parte_b=parte_b,
                     uf=uf, cnj_distrator=cnj, ano=ano)


__all__ = [
    "Cabecalho", "gerar_cabecalho", "cnj_distrator", "data_extenso", "folhas", "valor_reais",
    "percentual", "oab", "nome_pessoa", "nome_empresa", "preencher_distratores",
]
