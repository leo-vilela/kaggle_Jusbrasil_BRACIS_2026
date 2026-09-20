"""Tabelas de superfície do gerador sintético.

Tudo aqui é *forma*, não conteúdo do gabarito: siglas e nomes por extenso das
classes processuais, conectores, separadores de UF, moldes das citações vagas
(docs/03 §2.6), formas de dispositivo/súmula (§4, §5) e as frases-molde
próprias do gerador (frases de peça jurídica escritas para este projeto; nenhuma
é transcrição do conjunto de desenvolvimento).

Cada forma de superfície é rotulada como ``dev`` (observada no conjunto de
desenvolvimento, docs/03 §2), ``n2`` (só ocorre no nível 2 do dev) ou ``ood``
(existe na base ou é plausível, mas nunca foi citada no dev — só entra no
perfil ``agressivo``).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Classes processuais: sigla canônica → formas de superfície e gênero
# ---------------------------------------------------------------------------
# genero: "m" (o/no/do), "f" (a/na/da), "p" (os/nos/dos — Embargos)
# dev: formas do nível 1; n2: formas que só aparecem no nível 2; ood: nunca citadas no dev.
CLASSES: dict[str, dict[str, object]] = {
    # STJ
    "RESP": {"genero": "m", "dev": ["REsp", "Recurso Especial"], "n2": ["RESP", "Rec. Esp.", "R.Esp."],
             "ood": ["REsp.", "Resp", "Rec. Especial"]},
    "ARESP": {"genero": "m", "dev": ["AREsp", "Agravo em Recurso Especial"], "n2": ["ARESP", "AgREsp", "A.REsp"],
              "ood": ["AREsp.", "AgResp", "Ag. em REsp"]},
    "ERESP": {"genero": "p", "dev": [], "n2": [], "ood": ["EREsp", "Embargos de Divergência em Recurso Especial", "ERESP"]},
    "EARESP": {"genero": "p", "dev": [], "n2": [], "ood": ["EAREsp", "Embargos de Divergência em Agravo em Recurso Especial"]},
    "RHC": {"genero": "m", "dev": ["RHC", "Recurso em Habeas Corpus"], "n2": [],
            "ood": ["Recurso Ordinário em Habeas Corpus", "R.H.C."]},
    "RMS": {"genero": "m", "dev": ["RMS", "Recurso em Mandado de Segurança"], "n2": [],
            "ood": ["Recurso Ordinário em Mandado de Segurança", "R.M.S."]},
    "HC": {"genero": "m", "dev": [], "n2": ["H.C."], "ood": ["HC", "Habeas Corpus"]},
    "MS": {"genero": "m", "dev": [], "n2": [], "ood": ["MS", "Mandado de Segurança"]},
    "AR": {"genero": "f", "dev": ["AR"], "n2": [], "ood": ["Ação Rescisória"]},
    "AP": {"genero": "f", "dev": [], "n2": [], "ood": ["AP", "Ação Penal"]},
    "CC": {"genero": "m", "dev": [], "n2": [], "ood": ["CC", "Conflito de Competência"]},
    "SLS": {"genero": "f", "dev": ["Suspensão de Liminar e de Sentença"], "n2": [], "ood": ["SLS"]},
    "SS": {"genero": "f", "dev": [], "n2": [], "ood": ["SS", "Suspensão de Segurança"]},
    "PET": {"genero": "f", "dev": [], "n2": [], "ood": ["Pet", "Petição"]},
    "CAUTINOM": {"genero": "f", "dev": [], "n2": [], "ood": ["Cautelar Inominada Criminal"]},
    # STF
    "RE": {"genero": "m", "dev": ["RE", "Recurso Extraordinário"], "n2": ["RE."], "ood": ["R.E."]},
    "ARE": {"genero": "m", "dev": [], "n2": [], "ood": ["ARE", "Recurso Extraordinário com Agravo", "ARE."]},
    "RCL": {"genero": "f", "dev": ["Rcl", "Reclamação"], "n2": ["RCL", "Recl."], "ood": ["Rcl.", "RECLAMAÇÃO"]},
    "ADI": {"genero": "f", "dev": [], "n2": [], "ood": ["ADI", "Ação Direta de Inconstitucionalidade"]},
    "ADPF": {"genero": "f", "dev": [], "n2": [], "ood": ["ADPF"]},
    "REF": {"genero": "m", "dev": [], "n2": [], "ood": ["Referendo"]},
    # prefixos
    "AGR": {"genero": "m", "dev": ["AgRg", "Agravo Regimental", "AgR"], "n2": ["AG.REG", "AGR"],
            "ood": ["Ag.Reg.", "AgReg", "Agr. Reg."]},
    "AGINT": {"genero": "m", "dev": ["AgInt", "Agravo Interno"], "n2": ["AGINT", "Ag. Int."], "ood": ["AgInt.", "Ag.Int."]},
    "ED": {"genero": "p", "dev": ["EDcl", "Embargos de Declaração", "ED"], "n2": ["EDs"],
           "ood": ["Emb. Decl.", "EDcl.", "Embargos Declaratórios"]},
    "EDV": {"genero": "p", "dev": [], "n2": [], "ood": ["EDv", "Embargos de Divergência"]},
    "QO": {"genero": "f", "dev": [], "n2": [], "ood": ["QO", "Questão de Ordem"]},
    "PEXT": {"genero": "m", "dev": [], "n2": [], "ood": ["PExt", "Pedido de Extensão"]},
    # TSE
    "RESPE": {"genero": "m", "dev": ["REspe", "Recurso Especial Eleitoral"], "n2": ["REspe.", "RESPE"],
              "ood": ["REspE", "Resp. Eleitoral"]},
    "ARESPE": {"genero": "m", "dev": ["AREspEl"], "n2": [],
               "ood": ["AREspE", "Agravo em Recurso Especial Eleitoral", "ARESPE"]},
    "RO": {"genero": "m", "dev": [], "n2": [], "ood": ["RO", "Recurso Ordinário", "Recurso Ordinário Eleitoral"]},
    "AI": {"genero": "m", "dev": ["AI", "Agravo de Instrumento"], "n2": [], "ood": ["A.I."]},
    "AIJE": {"genero": "f", "dev": [], "n2": [], "ood": ["AIJE", "Ação de Investigação Judicial Eleitoral"]},
    "RP": {"genero": "f", "dev": ["Rp"], "n2": [], "ood": ["Representação"]},
    "RRP": {"genero": "m", "dev": ["R-Rp"], "n2": [], "ood": ["Recurso na Representação"]},
    "PC": {"genero": "f", "dev": [], "n2": [], "ood": ["PC", "Prestação de Contas"]},
    "AC": {"genero": "f", "dev": [], "n2": [], "ood": ["AC", "Ação Cautelar"]},
    "LT": {"genero": "f", "dev": [], "n2": [], "ood": ["LT", "Lista Tríplice"]},
    "TUTCAUT": {"genero": "f", "dev": [], "n2": [], "ood": ["Tutela Cautelar Antecedente"]},
    "RCED": {"genero": "m", "dev": [], "n2": [], "ood": ["RCED", "Recurso contra Expedição de Diploma"]},
    # STM
    "APL": {"genero": "f", "dev": ["APL"], "n2": [], "ood": ["Apelação", "Apelação Criminal", "Ap."]},
    "RSE": {"genero": "m", "dev": ["RSE"], "n2": [], "ood": ["Recurso em Sentido Estrito", "R.S.E."]},
    "EI": {"genero": "p", "dev": [], "n2": [], "ood": ["EI", "Embargos Infringentes e de Nulidade", "Embargos Infringentes"]},
    "CJ": {"genero": "m", "dev": [], "n2": [], "ood": ["CJ", "Conflito de Jurisdição"]},
    "CP": {"genero": "f", "dev": [], "n2": [], "ood": ["CP", "Correição Parcial"]},
    "RDI": {"genero": "f", "dev": [], "n2": [], "ood": ["RDI"]},
    # TST (tokens de prefixo hifenizado e classes)
    "RR": {"genero": "m", "dev": ["RR"], "n2": [], "ood": ["Recurso de Revista", "RR."]},
    "AIRR": {"genero": "m", "dev": [], "n2": [], "ood": ["AIRR", "Agravo de Instrumento em Recurso de Revista"]},
    "ARR": {"genero": "m", "dev": ["ARR"], "n2": [], "ood": ["Recurso de Revista com Agravo"]},
    "RRAG": {"genero": "m", "dev": [], "n2": [], "ood": ["RRAg"]},
    "ROT": {"genero": "m", "dev": [], "n2": [], "ood": ["ROT"]},
    "E": {"genero": "p", "dev": ["E"], "n2": [], "ood": ["Emb"]},
    "AG": {"genero": "m", "dev": ["Ag"], "n2": [], "ood": ["Agravo"]},
    "EDCIV": {"genero": "p", "dev": [], "n2": [], "ood": ["EDCiv"]},
}

# Tokens do prefixo hifenizado do TST (``TST-ED-E-ED-RR-…``)
TOKEN_TST: dict[str, str] = {
    "AG": "Ag", "AGR": "AgR", "ED": "ED", "E": "E", "RR": "RR", "AIRR": "AIRR", "ARR": "ARR",
    "RRAG": "RRAg", "ROT": "ROT", "EDCIV": "EDCiv",
}
# Tokens hifenizados do TSE (``AgR-REspe``, ``ED-AgR-AI``)
TOKEN_TSE: dict[str, str] = {
    "AGR": "AgR", "ED": "ED", "RESPE": "REspe", "ARESPE": "AREspE", "AI": "AI", "RO": "RO",
    "MS": "MS", "AR": "AR", "RP": "Rp", "RRP": "R-Rp", "HC": "HC", "RE": "RE", "PC": "PC",
    "AC": "AC", "PET": "Pet", "AG": "Ag", "RCL": "Rcl", "LT": "LT", "RESP": "REsp", "ARESP": "AREsp",
    "AIJE": "AIJE", "RCED": "RCED", "RHC": "RHC", "TUTCAUT": "TutCautAnt",
}

# Ordinais (tokens ``2O``, ``3O``, ``10O`` da cadeia) por gênero do elemento seguinte
ORDINAIS: dict[str, dict[str, str]] = {
    "2O": {"m": "Segundo", "f": "Segunda", "p": "Segundos"},
    "3O": {"m": "Terceiro", "f": "Terceira", "p": "Terceiros"},
    "4O": {"m": "Quarto", "f": "Quarta", "p": "Quartos"},
    "5O": {"m": "Quinto", "f": "Quinta", "p": "Quintos"},
    "10O": {"m": "Décimo", "f": "Décima", "p": "Décimos"},
}

# Tribunal implícito por classe principal (para o esperado do árbitro LLM)
TRIBUNAL_DA_CLASSE: dict[str, str] = {
    "RESP": "STJ", "ARESP": "STJ", "ERESP": "STJ", "EARESP": "STJ", "RHC": "STJ", "RMS": "STJ",
    "SLS": "STJ", "CAUTINOM": "STJ",
    "RE": "STF", "ARE": "STF", "ADI": "STF", "ADPF": "STF",
    "RESPE": "TSE", "ARESPE": "TSE", "RO": "TSE", "AIJE": "TSE", "RP": "TSE", "RRP": "TSE",
    "PC": "TSE", "LT": "TSE", "RCED": "TSE", "TUTCAUT": "TSE",
    "APL": "STM", "RSE": "STM", "EI": "STM", "CJ": "STM", "CP": "STM", "RDI": "STM",
    "RR": "TST", "AIRR": "TST", "ARR": "TST", "RRAG": "TST", "ROT": "TST",
}

# Conectores de número (docs/03 §2.2): superfície → rótulo
CONECTORES_DEV: list[str] = ["", "nº"]
CONECTORES_N2: list[str] = ["n°", "Nº", "No", "n."]
CONECTORES_OOD: list[str] = ["n.º", "N.º", "número", "num."]

# Separadores de UF (§2.4): (antes, depois)
SEPARADORES_UF_DEV: list[tuple[str, str]] = [("/", "")]
SEPARADORES_UF_N2: list[tuple[str, str]] = [("/ ", ""), ("-", ""), (" - ", ""), (" – ", ""), (" (", ")"), ("\n- ", "")]
SEPARADORES_UF_OOD: list[tuple[str, str]] = [(" / ", ""), ("–", ""), (" — ", ""), ("(", ")"), (" /", ""), ("/\n", "")]

# ---------------------------------------------------------------------------
# Citações vagas (§2.6): moldes A–E. ``{T}`` tribunal, ``{A}`` ano, ``{N}`` nome,
# ``{C}`` classe por extenso, ``{S}`` sigla.
# ---------------------------------------------------------------------------
MOLDES_VAGA: dict[str, dict[str, object]] = {
    "A": {"forma": "julgado do {T} proferido em {A} pela relatoria de {N}", "genero": "m", "tribunal": True},
    "B": {"forma": "precedente do {T} de {A}, da relatoria de {N}", "genero": "m", "tribunal": True},
    "C": {"forma": "{C} do {T}, de {A}, Rel. Min. {N}", "genero": None, "tribunal": True},
    "D": {"forma": "{S} de {A}, Rel. Min. {N}", "genero": None, "tribunal": False},
    "E": {"forma": "acórdão do {T} julgado em {A} sob relatoria de {N}", "genero": "m", "tribunal": True},
}
# moldes fora do dev (perfil agressivo): mesmas âncoras (ano + relatoria + nome)
MOLDES_VAGA_OOD: dict[str, dict[str, object]] = {
    "F": {"forma": "decisão do {T} de {A}, relatada pelo Min. {N}", "genero": "f", "tribunal": True},
    "G": {"forma": "aresto do {T}, {A}, Relator Ministro {N}", "genero": "m", "tribunal": True},
    "H": {"forma": "julgado do {T}, {A}, Rel. Min. {N}", "genero": "m", "tribunal": True},
}
# Classe por extenso/sigla usada nos moldes C e D, por classe principal
CLASSE_VAGA_EXTENSO: dict[str, str] = {
    "RCL": "Reclamação", "ARESP": "Agravo em Recurso Especial", "RHC": "Recurso em Habeas Corpus",
    "RESP": "Recurso Especial", "RE": "Recurso Extraordinário", "APL": "Apelação",
    "RESPE": "Recurso Especial Eleitoral", "RR": "Recurso de Revista", "RMS": "Recurso em Mandado de Segurança",
    "HC": "Habeas Corpus", "ARE": "Recurso Extraordinário com Agravo", "RO": "Recurso Ordinário",
    "AI": "Agravo de Instrumento", "RSE": "Recurso em Sentido Estrito", "EI": "Embargos Infringentes",
    "AIRR": "Agravo de Instrumento em Recurso de Revista", "MS": "Mandado de Segurança",
}
CLASSE_VAGA_SIGLA: dict[str, str] = {
    "RCL": "Rcl", "APL": "APL", "RESP": "REsp", "ARESP": "AREsp", "RHC": "RHC", "RE": "RE",
    "RESPE": "REspe", "RR": "RR", "RSE": "RSE", "HC": "HC", "ARE": "ARE", "RO": "RO", "MS": "MS",
}
GENERO_CLASSE_VAGA: dict[str, str] = {k: str(CLASSES[k]["genero"]) for k in CLASSE_VAGA_EXTENSO}

# ---------------------------------------------------------------------------
# Dispositivos (§4)
# ---------------------------------------------------------------------------
# diploma canônico → gênero, último artigo (para inventar artigo inexistente), formas
DIPLOMAS: dict[str, dict[str, object]] = {
    "CF": {"genero": "f", "ultimo": 250, "dev": ["Constituição Federal", "Constituição da República"],
           "ood": ["CF", "CF/88", "CRFB", "Carta Magna", "Constituição da República Federativa do Brasil"]},
    "CLT": {"genero": "f", "ultimo": 922, "dev": ["CLT", "Consolidação das Leis do Trabalho"],
            "ood": ["Decreto-Lei nº 5.452/1943"]},
    "CDC": {"genero": "m", "ultimo": 119, "dev": ["Código de Defesa do Consumidor"],
            "ood": ["CDC", "Lei nº 8.078/1990", "Código do Consumidor"]},
    "CPC": {"genero": "m", "ultimo": 1072, "dev": ["CPC", "Código de Processo Civil", "Lei nº 13.105/2015"],
            "ood": ["NCPC", "CPC/2015", "Lei 13.105/2015", "Lei nº 13.105, de 16 de março de 2015"]},
    "CE": {"genero": "m", "ultimo": 383, "dev": ["Código Eleitoral"], "ood": ["Lei nº 4.737/1965"]},
    "LC64": {"genero": "f", "ultimo": 28, "dev": ["Lei Complementar nº 64/1990"],
             "ood": ["LC 64/90", "LC nº 64/1990", "Lei das Inelegibilidades"]},
    "CPM": {"genero": "m", "ultimo": 410, "dev": ["Código Penal Militar"], "ood": ["CPM", "Decreto-Lei nº 1.001/1969"]},
    "CPP": {"genero": "m", "ultimo": 811, "dev": ["Código de Processo Penal"], "ood": ["CPP", "Decreto-Lei nº 3.689/1941"]},
    "CC": {"genero": "m", "ultimo": 2046, "dev": ["Código Civil"], "ood": ["CC", "Lei nº 10.406/2002", "CC/2002"]},
}
# Diplomas identificáveis mas FORA da base (sempre inventada). (superfície, gênero, último artigo)
DIPLOMAS_FORA_DA_BASE_DEV: list[tuple[str, str, int]] = [
    ("Lei nº 9.504/1997", "f", 107), ("Lei nº 13.467/2017", "f", 6),
]
DIPLOMAS_FORA_DA_BASE_OOD: list[tuple[str, str, int]] = [
    ("Lei nº 8.429/1992", "f", 25), ("Lei nº 9.099/1995", "f", 97), ("Lei nº 14.133/2021", "f", 194),
    ("Lei nº 8.666/1993", "f", 126), ("Lei nº 11.340/2006", "f", 46), ("Código Penal", "m", 361),
    ("Lei nº 9.784/1999", "f", 70), ("Lei Complementar nº 123/2006", "f", 89),
]
# Diplomas por matéria (coerência do documento)
DIPLOMAS_POR_MATERIA: dict[str, list[str]] = {
    "civel": ["CPC", "CC", "CDC", "CF"],
    "penal": ["CPP", "CF", "CPC"],
    "trabalhista": ["CLT", "CF", "CPC"],
    "eleitoral": ["CE", "LC64", "CF"],
    "militar": ["CPM", "CPP", "CF"],
}
FORMAS_ART_DEV: list[str] = ["art."]
FORMAS_ART_N2: list[str] = ["art", "artigo"]
FORMAS_ART_OOD: list[str] = ["Art.", "Artigo", "art.º"]
INCISOS: list[str] = ["I", "II", "III", "IV", "V", "VI", "IX", "X", "XII", "LV", "XXIX"]
ALINEAS: list[str] = ["'a'", "'b'", "'c'", "'g'"]
PARAGRAFOS: list[str] = ["§ 1º", "§ 2º", "§ 3º", "§ 1º-A", "parágrafo único"]

# ---------------------------------------------------------------------------
# Súmulas (§5)
# ---------------------------------------------------------------------------
FORMAS_SUMULA_DEV: list[str] = ["Súmula"]
FORMAS_SUMULA_N2: list[str] = ["5UMULA", "SÚMULA", "Súm."]
FORMAS_SUMULA_OOD: list[str] = ["Sumula", "Súmula nº", "Enunciado nº", "Súmula n."]
# faixas de números inexistentes por tribunal (acima dos verbetes reais; nunca colidem com a base)
SUMULA_INVENTADA_FAIXA: dict[str, tuple[int, int]] = {
    "STF": (900, 999), "SV": (180, 260), "TSE": (160, 199), "STJ": (700, 799), "TST": (500, 599),
}
# súmulas reais no mundo mas ausentes da base (perfil agressivo): pela base fechada, inventada
SUMULA_MUNDO_REAL_FORA_DA_BASE: list[tuple[str, int]] = [
    ("STJ", 7), ("STJ", 5), ("STF", 279), ("STF", 282), ("TST", 126), ("TSE", 24), ("SV", 11), ("SV", 37),
]

# ---------------------------------------------------------------------------
# Matérias, tribunais e peças
# ---------------------------------------------------------------------------
MATERIAS: list[str] = ["civel", "penal", "trabalhista", "eleitoral", "militar"]
# tribunais amostrados por matéria (com pesos): o principal e os satélites
TRIBUNAIS_POR_MATERIA: dict[str, list[tuple[str, int]]] = {
    "civel": [("STJ", 7), ("STF", 2)],
    "penal": [("STJ", 6), ("STF", 3)],
    "trabalhista": [("TST", 6), ("STJ", 2), ("STF", 1)],
    "eleitoral": [("TSE", 6), ("STF", 2), ("STJ", 1)],
    "militar": [("STM", 6), ("STJ", 2), ("STF", 1)],
}
# pesos das matérias (peças do dev: cível 9, penal 5, trabalhista 4, eleitoral 4, militar 4)
MATERIAS_PESOS: list[int] = [7, 4, 3, 3, 3]
# segmento J do CNJ do cabeçalho: no dev é variado (3–8) e não amarra a matéria
SEGMENTOS_J_CABECALHO: list[str] = ["1", "2", "3", "4", "5", "6", "7", "8"]

# ---------------------------------------------------------------------------
# Frases-molde do gerador (próprias). ``{o}`` = artigo (o/a/os), ``n{o}`` = no/na/nos,
# ``d{o}`` = do/da/dos, ``{cit}`` = citação. O caractere após a citação é sempre
# ``,``, ``.`` ou espaço + palavra minúscula (docs/03 §1).
# ---------------------------------------------------------------------------
FRASES_CITACAO: list[str] = [
    "Nesse sentido, confira-se {o} {cit}, de idêntico teor.",
    "A tese encontra amparo n{o} {cit}, que dirimiu controvérsia semelhante.",
    "Colhe-se orientação idêntica d{o} {cit}.",
    "Merece destaque {o} {cit} para a solução da causa.",
    "Vale lembrar {o} {cit}, cuja fundamentação se aplica integralmente à hipótese.",
    "O mesmo raciocínio foi adotado n{o} {cit}, em situação análoga.",
    "Não destoa desse entendimento {o} {cit}.",
    "Cite-se, por todos, {o} {cit}, que examinou questão idêntica.",
    "A pretensão da parte adversa esbarra n{o} {cit}, de observância obrigatória.",
    "Assim se decidiu n{o} {cit}, sem voto divergente.",
    "Nessa linha, {o} {cit} foi expresso ao rejeitar tese semelhante.",
    "Reforça a conclusão {o} {cit}, invocado pela própria parte contrária.",
    "É o que se extrai d{o} {cit}, cujos fundamentos se adotam como razão de decidir.",
    "Aplica-se à espécie {o} {cit}, como reconhecido nas instâncias ordinárias.",
    "Basta conferir {o} {cit} para constatar a identidade de situações.",
    "Em sentido contrário ao pretendido pelo recorrente, veja-se {o} {cit}.",
]

# Frases de ligação genéricas (sem identificador)
FRASES_LIGACAO: list[str] = [
    "A questão posta nos autos não comporta maior dificuldade.",
    "Impõe-se, de início, delimitar os contornos da controvérsia.",
    "A parte contrária limita-se a reiterar argumentos já enfrentados na origem.",
    "O acórdão recorrido examinou a matéria com a devida profundidade.",
    "Não há, portanto, como acolher a pretensão deduzida.",
    "A conclusão alcançada na origem harmoniza-se com o entendimento das Cortes Superiores.",
    "Sob qualquer ângulo que se examine a questão, a resposta é a mesma.",
    "Ainda que se admitisse tese diversa, o resultado não seria alterado.",
    "Convém recordar, brevemente, o histórico processual.",
    "Trata-se de ponto que já mereceu exame exaustivo nas instâncias ordinárias.",
    "A moldura fática fixada na origem é suficiente para o julgamento.",
    "O argumento, embora engenhoso, não resiste a uma análise mais detida.",
    "Nada há a reparar na decisão impugnada quanto a esse capítulo.",
    "É de rigor, portanto, o acolhimento da tese ora defendida.",
    "Cumpre destacar, ademais, que a matéria é eminentemente de direito.",
    "A doutrina majoritária caminha no mesmo sentido.",
    "Não se pode perder de vista a finalidade da norma aplicável.",
    "Resta evidenciado o desacerto da decisão de primeiro grau.",
]

# Frases-armadilha (docs/03 §6.3): mencionam precedente/súmula/lei SEM identificador — nunca são span
FRASES_ARMADILHA: list[str] = [
    "A jurisprudência dominante das Cortes Superiores converge no ponto.",
    "O verbete sumular pertinente à espécie confirma essa leitura.",
    "O dispositivo legal invocado na petição inicial não socorre a parte.",
    "A norma que rege a prescrição no caso concreto é clara a respeito.",
    "O entendimento sumulado a respeito do tema é de aplicação obrigatória.",
    "Os precedentes das instâncias extraordinárias apontam na mesma direção.",
    "A orientação consolidada do Tribunal Pleno não deixa margem a dúvida.",
    "As normas de regência da matéria foram corretamente aplicadas.",
    "O precedente firmado em sede de recurso repetitivo é vinculante para as instâncias ordinárias.",
    "A jurisprudência pacífica desta Corte afasta a pretensão.",
]
# Armadilhas fora do dev (perfil agressivo): trazem tribunal/ano ou relatoria, mas não os dois
FRASES_ARMADILHA_OOD: list[str] = [
    "A orientação firmada pelo {T} em {A} permanece íntegra.",
    "Como anotou o Ministro relator em seu voto, a tese não prospera.",
    "O Superior Tribunal de Justiça, em {A}, consolidou a orientação contrária.",
    "A repercussão geral da matéria já foi reconhecida pelo Supremo Tribunal Federal.",
    "O Tribunal Superior do Trabalho editou orientação jurisprudencial sobre o tema.",
    "Ainda em {A}, o {T} reafirmou a jurisprudência então dominante.",
]

# Frases factuais por matéria (com marcadores de distrator: {data}, {fls}, {valor}, {pct})
FRASES_MATERIA: dict[str, list[str]] = {
    "civel": [
        "A relação contratual entre as partes teve início em {data}, mediante instrumento particular de prestação de serviços.",
        "A perícia contábil de {fls} apurou prejuízo material no montante de {valor}.",
        "A sentença julgou parcialmente procedentes os pedidos, fixando os honorários em {pct} sobre o valor da condenação.",
        "Ambas as partes recorreram, e os recursos foram recebidos nos efeitos devolutivo e suspensivo.",
        "A parte ré atribui o inadimplemento a fato de terceiro e invoca cláusula de exclusão de responsabilidade.",
        "Os documentos de {fls} comprovam o pagamento das parcelas vencidas até {data}.",
        "A prescrição foi corretamente afastada, pois o termo inicial coincide com a ciência inequívoca da lesão.",
        "O dano moral foi arbitrado em {valor}, valor que se mostra proporcional às circunstâncias do caso.",
    ],
    "penal": [
        "Segundo a denúncia, os fatos ocorreram em {data}, quando o acusado teria subtraído bens da vítima mediante grave ameaça.",
        "A prisão em flagrante foi convertida em preventiva e mantida pelo Tribunal de origem.",
        "O laudo pericial de {fls} concluiu pela materialidade do delito.",
        "A instrução transcorreu com a oitiva de quatro testemunhas de acusação e duas de defesa.",
        "A pena-base foi fixada acima do mínimo legal em razão da valoração negativa das circunstâncias do crime.",
        "A defesa sustenta constrangimento ilegal decorrente do excesso de prazo para a formação da culpa.",
        "O acórdão recorrido manteve a dosimetria, afastando apenas uma das agravantes reconhecidas em primeiro grau.",
        "A fiança foi arbitrada em {valor}, valor que a defesa reputa incompatível com a condição econômica do acusado.",
    ],
    "trabalhista": [
        "O reclamante foi admitido em {data} para exercer a função de operador de máquinas.",
        "A sentença reconheceu o vínculo de emprego e condenou a reclamada ao pagamento das verbas rescisórias.",
        "Os cartões de ponto de {fls} registram jornada superior à contratual em diversos meses.",
        "O acórdão regional manteve a condenação ao pagamento de horas extras com adicional de {pct}.",
        "A reclamada sustenta a licitude da terceirização e a ausência de culpa na fiscalização do contrato.",
        "O valor da condenação foi provisoriamente arbitrado em {valor}.",
        "A responsabilidade subsidiária da tomadora decorre da culpa in vigilando reconhecida na origem.",
        "O contrato de trabalho foi rescindido sem justa causa em {data}.",
    ],
    "eleitoral": [
        "A representação foi ajuizada durante o período eleitoral de {data}, sob a alegação de captação ilícita de sufrágio.",
        "Os fatos foram registrados em áudio e vídeo juntados aos autos às {fls}.",
        "As contas de campanha apontaram inconsistências relativas à origem de recursos no montante de {valor}.",
        "O Tribunal Regional cassou o diploma do representado e aplicou multa no patamar mínimo legal.",
        "A defesa sustenta que as provas foram obtidas por meio ilícito e que não houve potencialidade lesiva.",
        "O parecer conclusivo da unidade técnica opinou pela desaprovação das contas.",
        "O percentual de votos obtido pelo candidato foi de {pct} no município.",
        "O registro de candidatura foi indeferido por incidência de causa de inelegibilidade.",
    ],
    "militar": [
        "O apelante, militar da ativa à época dos fatos, foi denunciado pela prática do delito descrito na denúncia oferecida em {data}.",
        "O Conselho Permanente de Justiça julgou procedente a pretensão punitiva e aplicou pena privativa de liberdade.",
        "A prova testemunhal colhida às {fls} não confirma a autoria atribuída ao acusado.",
        "Discute-se a competência da Justiça Militar da União para processar e julgar o feito.",
        "O Ministério Público Militar defende a manutenção integral da sentença.",
        "A defesa sustenta a atipicidade da conduta e a insuficiência do conjunto probatório.",
        "O delito foi praticado em lugar sujeito à administração militar, conforme apurado no inquérito.",
        "O prejuízo ao erário foi estimado em {valor} pela auditoria interna.",
    ],
}

SECOES: list[list[str]] = [
    ["I — DA CONTROVÉRSIA", "II — DO DIREITO APLICÁVEL", "III — DOS PRECEDENTES INVOCADOS", "IV — DA IMPOSSIBILIDADE DE REEXAME FÁTICO"],
    ["I — DOS FATOS", "II — DA ADMISSIBILIDADE", "III — DO MÉRITO", "IV — DOS PRECEDENTES", "V — DO PEDIDO"],
    ["I — RELATÓRIO", "II — DA CONTROVÉRSIA", "III — DO DIREITO APLICÁVEL", "IV — DA CONCLUSÃO"],
    ["I — SÍNTESE DA DEMANDA", "II — DA TESE RECURSAL", "III — DA JURISPRUDÊNCIA", "IV — DO PEDIDO"],
]

FECHAMENTOS: list[str] = [
    "Ante o exposto, requer-se o provimento do recurso, com a reforma integral do acórdão recorrido.",
    "Requer, por fim, a juntada do presente aos autos, para que produza seus regulares efeitos.",
    "É o parecer, que se submete à consideração superior.",
    "Diante disso, opina-se pelo desprovimento do recurso.",
    "Pelo exposto, nega-se provimento ao recurso.",
    "É o que se tinha a expor, colocando-se esta consultoria à disposição para esclarecimentos.",
]
DESPEDIDAS: list[str] = ["Termos em que pede deferimento.", "Nestes termos, pede deferimento.", "É como voto.", ""]

MESES: list[str] = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                    "setembro", "outubro", "novembro", "dezembro"]
CIDADES: list[str] = ["Brasília", "São Paulo", "Rio de Janeiro", "Porto Alegre", "Curitiba", "Salvador",
                      "Belo Horizonte", "Recife", "Fortaleza", "Florianópolis", "Goiânia", "Belém"]

# Substituições de OCR em palavras (docs/03 §3.1), com pesos observados
OCR_PALAVRA: list[tuple[str, str, int]] = [("e", "c", 36), ("a", "ã", 28), ("c", "e", 15), ("m", "rn", 12), ("i", "l", 11)]
OCR_PALAVRA_OOD: list[tuple[str, str, int]] = [("o", "0", 3), ("s", "5", 3), ("u", "ü", 2), ("n", "ri", 2), ("é", "e", 3)]
# Letra por dígito DENTRO de números (uma por número, nunca dígito por dígito)
OCR_DIGITO: dict[str, str] = {"1": "l", "0": "O", "5": "S", "9": "g", "6": "G"}
OCR_DIGITO_OOD: dict[str, str] = {"1": "I", "0": "o", "2": "Z", "8": "B"}

__all__ = [name for name in dir() if name.isupper()]
