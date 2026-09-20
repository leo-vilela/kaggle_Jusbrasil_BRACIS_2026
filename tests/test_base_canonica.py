"""Testes da base canônica (índice de números próprios, consulta, normativos).

Os testes sem dados usam cabeçalhos SINTÉTICOS (números trocados) que
preservam o layout de cada tribunal. Os testes com dados (``skipUnless``)
exigem cobertura 96/96 do gabarito e as propriedades de docs/04_analise_base.md.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from conftest_paths import DB, GOLDENSET, TEM_DADOS  # noqa: E402

from caca_alucinacao.base_canonica import (  # noqa: E402
    BaseCanonica,
    Registro,
    artigo_canonico,
    construir_indice,
    digitos_canonicos,
    diploma_canonico,
    extrair_identificadores_proprios,
    regiao_de_identificacao,
    relator_compativel,
    separar_uf,
    sumula_canonica,
)
from caca_alucinacao.base_canonica.classes import (  # noqa: E402
    cadeia_de_classes,
    classe_principal,
    classes_compativeis,
    uf_de_estado,
)
from caca_alucinacao.base_canonica.digitos import (  # noqa: E402
    FORMATO_CNJ,
    FORMATO_REGISTRO,
    FORMATO_SEQUENCIAL,
    classificar_digitos,
    nucleos,
    numeros_do_texto,
)
from caca_alucinacao.base_canonica.normativos import derivar_normativos  # noqa: E402

# ---------------------------------------------------------------------------
# Cabeçalhos sintéticos (números inventados; layouts reais)
# ---------------------------------------------------------------------------
STF_A = ("03/05/2023 PRIMEIRA TURMA AG.REG. NA RECLAMAÇÃO 12.345 SÃO PAULO RELATOR : MIN. FULANO DE TAL "
         "AGTE.(S) : EMPRESA X LTDA ADV.(A/S) : BELTRANO INTDO.(A/S) : RELATOR DO PROCESSO Nº 5000123-"
         "45.2020.4.03.6100 DA 1a TURMA Ementa: DIREITO PROCESSUAL. AGRAVO REGIMENTAL NA RECLAMAÇÃO.")
STF_B = ("Supremo Tribunal Federal EmentaeAcórdão Inteiro Teor do Acórdão - Página 1 de 20 10/10/2020 "
         "SEGUNDA TURMA SEGUNDO AG.REG. NO RECURSO EXTRAORDINÁRIO COM AGRAVO 1.234.567 MINAS GERAIS "
         "RELATOR : MIN. SICRANO REDATOR DO : MIN. OUTRO ACÓRDÃO AGTE.(S) : ALGUÉM")
STF_C = ("PLENÁRIO REFERENDO NOS DÉCIMOS EMB.DECL. NA AÇÃO PENAL 1.234 DISTRITO FEDERAL RELATOR : MIN. "
         "ALGUÉM EMBTE.(S) : X")
STJ_A = ("AgInt no AGRAVO EM RECURSO ESPECIAL Nº 1.234.567 - RJ (2019/0123456-7) RELATOR : MINISTRO FULANO "
         "AGRAVANTE : A ADVOGADO : B - RJ012345 AGRAVADO : C EMENTA PROCESSUAL CIVIL. AGRAVO INTERNO.")
STJ_B = ("Superior Tribunal de Justiça Revista Eletrônica de Jurisprudência RECURSO EM HABEAS CORPUS Nº "
         "98.765 - PR (2018⁄0111222-3) RELATOR : MINISTRO SICRANO RECORRENTE : X")
STJ_C = ("EDcl no AgInt nos EDcl no RECURSO ESPECIAL Nº 7654321 - SP (2020/0000001-0) RELATORA : MINISTRA "
         "ALGUÉM EMBARGANTE : Y")
STJ_D = "QO na CAUTELAR INOMINADA CRIMINAL Nº 42 - DF (2022/0187654-3) RELATORA : MINISTRA Z"
TSE_A = ("TRIBUNAL SUPERIOR ELEITORAL ACÓRDÃO AGRAVO REGIMENTAL NO RECURSO ESPECIAL ELEITORAL Nº 123-45.2016."
         "6.05.0151 - CLASSE 32— CIDADE - BAHIA Relator: Ministro Fulano Agravante: X Advogados: Y - OAB: "
         "12345/BA e outros Agravado: Ministério Público Eleitoral ELEIÇÕES 2016.")
TSE_B = ("TRIBUNAL SUPERIOR ELEITORAL ACÓRDÃO RECURSO ESPECIAL ELEITORAL Nº 36.123 ( 43210-98.2009.6.00.0000) "
         "-CLASSE 32— CIDADE - ALAGOAS Relator originário: Ministro X Redator para o acórdão: Ministro Y")
TSE_C = ("TRIBUNAL SUPERIOR ELEITORAL ACÓRDÃO AGRAVO EM RECURSO ESPECIAL ELEITORAL Nº 0600123-45.2021.6.06.0121 "
         "- CIDADE - CEARÁ Relator: Ministro Z Agravante: W")
TSE_D = ("05/12/2020 Número: 0601234-56.2018.6.09.0000 Classe: AGRAVO DE INSTRUMENTO Órgão julgador colegiado: "
         "Colegiado do Tribunal Superior Eleitoral Órgão julgador: Ministro X Última distribuição : 17/02/2020")
TSE_E = ("1i1 TRIBUNAL SUPERIOR ELEITORAL ACORDAO EMBARGOS DE DECLARAcA0 NA PREsTAcA0 DE CONTAS N o 984-27. "
         "2010.6.00.0000 - CLASSE 25— BRASILIA - DISTRITO FEDERAL Relator: Ministro X Embargante: Y")
TSE_F = ("rN€ TRIBUNAL SUPERIOR ELEITORAL AC€RD O AGRAVO REGIMENTAL NO RECURSO ESPECIAL ELEITORAL N‚ 374-29. "
         "2012.6.16.0066 - CLASSE 32ƒ CIDADE - PARAN„ Relator: Ministro X Agravante: Y")
STM_A = ("Poder Judiciário STM EXTRATO DE ATA DA SESSÃO VIRTUAL DE 18/09/2023 A 21/09/2023 EMBARGOS INFRINGENTES "
         "E DE NULIDADE Nº 7000123- 45.2023.7.00.0000/DF RELATOR: MINISTRO FULANO REVISOR: MINISTRO X")
STM_B = ("Secretaria do Tribunal Pleno AGRAVO INTERNO Nº 7000456-78.2021.7.00.0000 RELATOR: MINISTRO X AGRAVANTE: "
         "Y Extrato de Ata DECISÃO PROFERIDA o Plenário, por unanimidade, negou provimento ao Agravo Interno nº "
         "7000456- 78.2021.7.00.0000/RS, oposto pela Defesa.")
STM_C = ("J SUPERIOR TRIBUNAL MILITAR. Secretaria Judiciária EXTRATO DA ATA DA 52a SESSÃO DE JULGAMENTO. EM 29 DE "
         "AGOSTO DE 2017 Presidência do Ministro Dr. X. Presentes os Ministros A, B e C. " + "x " * 300 +
         "APELAÇÃO Nº 241-56.2016.7.11.0213 - DF - Relator Ministro Y Revisor Ministro Z")
TST_A = ("A C Ó R D Ã O SbDI-1 GMJRP/in/rb/ac EMBARGOS DE DECLARAÇÃO. " + "blá " * 200 +
         "Vistos, relatados e discutidos estes autos de Embargos de Declaração em Embargos em Embargos de "
         "Declaração em Recurso de Revista nº TST-ED-E-ED-RR-1234-56.2011.5.21.0009, em que é Embargante X. "
         + "blá " * 100 + "JOSÉ RELATOR Ministro Relator fls. PROCESSO Nº TST-ED-E-ED-RR-1234-56.2011.5.21.0009 "
         "Firmado por assinatura digital em 27/03/2017 pelo sistema AssineJus da Justiça do Trabalho.")
TST_B = ("Poder Judiciário Justiça do Trabalho Tribunal Superior do Trabalho PROCESSO Nº TST-Ag-ROT - "
         "1005713-27.2023.5.02.0000 A C Ó R D Ã O Subseção II GMMAR/rhs AGRAVO EM RECURSO ORDINÁRIO. " + "blá " * 50
         + "Vistos, relatados e discutidos estes autos de Agravo em Recurso Ordinário Trabalhista n.º TST-Ag-ROT-"
         "1005713-27.2023.5.02.0000, em que é Agravante X.")
TST_C = ("A C Ó R D Ã O (5ª Turma) GMDAR/ASL AGRAVO DE INSTRUMENTO. " + "blá " * 30 +
         "Vistos, relatados e discutidos estes autos de Agravo de Instrumento em Recurso de Revista n . º "
         "TST-AIRR-88612-31.2008.5.24.0005 , em que é Agravante SINDICATO X. Como se vê no processo n . º "
         "TST-RR-21077-91.2014.5.04.0202, a tese é outra.")


def _ids(texto: str, tribunal: str) -> list[dict]:
    return extrair_identificadores_proprios(texto, tribunal)


class TestDigitos(unittest.TestCase):
    def test_sequencial_com_pontos_e_uf(self):
        self.assertEqual(digitos_canonicos("AgInt no AREsp nº 1.234.567/RJ"), "1234567")
        self.assertEqual(digitos_canonicos("Rcl 12.345/RS"), "12345")
        self.assertEqual(digitos_canonicos("RE nº\xa05. 231.809-DF"), "5231809")
        self.assertEqual(digitos_canonicos("Reclamação n°\xa033.-\n479 (MA)"), "33479")

    def test_ocr_so_dentro_de_grupo_numerico(self):
        self.assertEqual(digitos_canonicos("AgInt no RESP\xa021739l4 - SP"), "2173914")
        self.assertEqual(digitos_canonicos("R.Esp. n°  1.46g.781-MA"), "1469781")
        self.assertEqual(digitos_canonicos("AgRg no RESP 1.529.4S7/ RJ"), "1529457")
        self.assertEqual(digitos_canonicos("EDcl no AgInt no Recurso Especial Nº 170079O (SP)"), "1700790")
        self.assertEqual(digitos_canonicos("Recl. n° 6G.841/ BA"), "66841")
        # "AREspEl" não vira número; "No"/"SP" não viram dígitos
        self.assertEqual(digitos_canonicos("ED no AgR no AREspEl 0601517-93.2020.6.05.0000"), "06015179320206050000")
        self.assertEqual(digitos_canonicos("REspe No  0600319-5120206160182"), "06003195120206160182")

    def test_uf_separada_antes_da_correcao(self):
        self.assertEqual(separar_uf("REsp 1.234.567/SP"), ("REsp 1.234.567", "SP"))
        self.assertEqual(separar_uf("RCL n° 45782 (GO)"), ("RCL n° 45782", "GO"))
        self.assertEqual(separar_uf("Recurso Especial nº 1385702/ SP"), ("Recurso Especial nº 1385702", "SP"))
        self.assertEqual(separar_uf("Súmula 456 do TST"), ("Súmula 456 do TST", None))
        # o "S" de SP nunca vira 5
        self.assertEqual(digitos_canonicos("AgInt no RESP 1234 - SP"), "1234")

    def test_cnj_completa_com_zeros(self):
        self.assertEqual(digitos_canonicos("AgR-REspe 379-12.2016.6.05.0151"), "00003791220166050151")
        self.assertEqual(digitos_canonicos("TST-ED-E-ED-RR-3411-07.2011.5.21.0009"), "00034110720115210009")
        self.assertEqual(digitos_canonicos("APL\n 7000769-81 2021 7 00 0000/BA"), "70007698120217000000")
        self.assertEqual(digitos_canonicos("REspe. n° 0600457-13.2020-\n.6.14.0022"), "06004571320206140022")
        self.assertEqual(digitos_canonicos("EDs no AGR-RESPE n°\xa0537-81. 2012.6.13.0029"), "00005378120126130029")

    def test_registro_stj(self):
        self.assertEqual(classificar_digitos("201801163991"), ("201801163991", FORMATO_REGISTRO))
        self.assertEqual(classificar_digitos("1741799"), ("1741799", FORMATO_SEQUENCIAL))
        self.assertEqual(classificar_digitos("34110720115210009"), ("00034110720115210009", FORMATO_CNJ))
        self.assertEqual(classificar_digitos("0036")[0], "36")

    def test_nucleos_multiplos(self):
        ns = nucleos("Nº 36.123 ( 43210-98.2009.6.00.0000)")
        self.assertEqual([n.digitos for n in ns], ["36123", "00432109820096000000"])
        self.assertEqual(digitos_canonicos("Súmula Vinculante 45"), "45")
        self.assertEqual(digitos_canonicos("julgado do STF de 2024, relatoria de X"), "2024")
        self.assertEqual(digitos_canonicos("sem número"), "")

    def test_numeros_do_texto(self):
        t = "cita o REsp 1.234.567/SP e o processo 0001234-56.2019.5.02.0030, fls. 2.826/2.883e, art. 1.026"
        digs = [d for _, _, d, _ in numeros_do_texto(t)]
        self.assertIn("1234567", digs)
        self.assertIn("00012345620195020030", digs)
        self.assertIn("1026", digs)


class TestClasses(unittest.TestCase):
    def test_cadeias(self):
        self.assertEqual(cadeia_de_classes("EDcl no AgInt no AREsp"), ["ED", "AGINT", "ARESP"])
        self.assertEqual(cadeia_de_classes("AgInt nos EDcl no Rec. Esp."), ["AGINT", "ED", "RESP"])
        self.assertEqual(cadeia_de_classes("Terceiro AG.REG na Rcl"), ["3O", "AGR", "RCL"])
        self.assertEqual(cadeia_de_classes("ED no AgR no AREspEl"), ["ED", "AGR", "ARESPE"])
        self.assertEqual(cadeia_de_classes("TST-ED-E-ED-RR"), ["ED", "E", "ED", "RR"])
        self.assertEqual(cadeia_de_classes("TST-AgARR"), ["AG", "ARR"])
        self.assertEqual(cadeia_de_classes("Ag. Int. No"), ["AGINT"])
        self.assertEqual(cadeia_de_classes("AgRg no H.C."), ["AGR", "HC"])
        self.assertEqual(cadeia_de_classes("R-Rp"), ["RRP"])
        self.assertEqual(cadeia_de_classes("Agravo Interno na Suspensão de Liminar e de Sentença"), ["AGINT", "SLS"])
        self.assertEqual(cadeia_de_classes("PRIMEIRA TURMA AG.REG. NA RECLAMAÇÃO"), ["AGR", "RCL"])
        self.assertEqual(cadeia_de_classes("AgInt nosEMBARGOS DE DIVERGÊNCIA EM RESP"), ["AGINT", "ERESP"])
        self.assertEqual(cadeia_de_classes("EMBARGOS DE DECLARAcA0 NA PREsTAcA0 DE CONTAS"), ["ED", "PC"])
        self.assertEqual(cadeia_de_classes("Súmula 456 do TST"), [])

    def test_principal_e_compatibilidade(self):
        self.assertEqual(classe_principal(["2O", "AGR", "RCL"]), "RCL")
        self.assertEqual(classe_principal(["QO"]), "QO")
        self.assertTrue(classes_compativeis("RESP", "RESPE"))
        self.assertTrue(classes_compativeis("ARR", "AIRR"))
        self.assertFalse(classes_compativeis("RESP", "ARESP"))
        self.assertFalse(classes_compativeis("RCL", "MS"))
        self.assertFalse(classes_compativeis(None, "RCL"))

    def test_uf_de_estado(self):
        self.assertEqual(uf_de_estado("RIO DE JANEIRO"), "RJ")
        self.assertEqual(uf_de_estado("M A R A N H Ã O"), "MA")
        self.assertEqual(uf_de_estado("PARAN„"), "PR")
        self.assertEqual(uf_de_estado("PARÁ"), "PA")
        self.assertEqual(uf_de_estado("DISTRITO FEDE RAL"), "DF")
        self.assertIsNone(uf_de_estado("CIDADE QUALQUER"))


class TestExtracaoSintetica(unittest.TestCase):
    def test_stf(self):
        a = _ids(STF_A, "STF")
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["digitos"], a[0]["formato"], a[0]["classe_propria"], a[0]["uf"]),
                         ("12345", FORMATO_SEQUENCIAL, "AGR RCL", "SP"))
        # o CNJ do "RELATOR DO PROCESSO Nº …" (distrator) NÃO entra
        self.assertNotIn("50001234520204036100", [x["digitos"] for x in a])
        b = _ids(STF_B, "STF")
        self.assertEqual((b[0]["digitos"], b[0]["classe_propria"], b[0]["uf"]), ("1234567", "2O AGR ARE", "MG"))
        c = _ids(STF_C, "STF")
        self.assertEqual((c[0]["digitos"], c[0]["classe_propria"], c[0]["uf"]), ("1234", "REF 10O ED AP", "DF"))

    def test_stj(self):
        a = _ids(STJ_A, "STJ")
        self.assertEqual([(x["digitos"], x["formato"]) for x in a],
                         [("1234567", FORMATO_SEQUENCIAL), ("201901234567", FORMATO_REGISTRO)])
        self.assertEqual(a[0]["classe_propria"], "AGINT ARESP")
        self.assertEqual(a[0]["uf"], "RJ")
        # a OAB "RJ012345" não é identificador
        self.assertNotIn("12345", [x["digitos"] for x in a])
        b = _ids(STJ_B, "STJ")
        self.assertEqual([(x["digitos"], x["classe_propria"], x["uf"]) for x in b],
                         [("98765", "RHC", "PR"), ("201801112223", "RHC", "PR")])
        c = _ids(STJ_C, "STJ")
        self.assertEqual((c[0]["digitos"], c[0]["classe_propria"]), ("7654321", "ED AGINT ED RESP"))
        d = _ids(STJ_D, "STJ")
        self.assertEqual((d[0]["digitos"], d[0]["classe_propria"]), ("42", "QO CAUTINOM"))

    def test_tse(self):
        a = _ids(TSE_A, "TSE")
        self.assertEqual([(x["digitos"], x["classe_propria"], x["uf"]) for x in a],
                         [("00001234520166050151", "AGR RESPE", "BA")])
        b = _ids(TSE_B, "TSE")
        self.assertEqual([(x["digitos"], x["formato"]) for x in b],
                         [("36123", FORMATO_SEQUENCIAL), ("00432109820096000000", FORMATO_CNJ)])
        self.assertEqual(b[0]["uf"], "AL")
        c = _ids(TSE_C, "TSE")
        self.assertEqual((c[0]["digitos"], c[0]["classe_propria"], c[0]["uf"]), ("06001234520216060121", "ARESPE", "CE"))
        d = _ids(TSE_D, "TSE")
        self.assertEqual((d[0]["digitos"], d[0]["classe_propria"]), ("06012345620186090000", "AI"))
        e = _ids(TSE_E, "TSE")
        self.assertEqual((e[0]["digitos"], e[0]["classe_propria"], e[0]["uf"]), ("00009842720106000000", "ED PC", "DF"))
        f = _ids(TSE_F, "TSE")
        self.assertEqual((f[0]["digitos"], f[0]["classe_propria"], f[0]["uf"]), ("00003742920126160066", "AGR RESPE", "PR"))

    def test_stm(self):
        a = _ids(STM_A, "STM")
        self.assertEqual((a[0]["digitos"], a[0]["classe_propria"], a[0]["uf"]), ("70001234520237000000", "EI", "DF"))
        b = _ids(STM_B, "STM")
        self.assertEqual((b[0]["digitos"], b[0]["classe_propria"], b[0]["uf"]), ("70004567820217000000", "AGINT", "RS"))
        c = _ids(STM_C, "STM")
        self.assertEqual((c[0]["digitos"], c[0]["classe_propria"], c[0]["uf"]), ("00002415620167110213", "APL", "DF"))
        self.assertGreater(c[0]["posicao"], 500)

    def test_tst(self):
        a = _ids(TST_A, "TST")
        self.assertEqual(len(a), 1)  # fórmula + rodapé → deduplicado
        self.assertEqual((a[0]["digitos"], a[0]["classe_propria"]), ("00012345620115210009", "ED E ED RR"))
        self.assertEqual(a[0]["classe_principal"], "RR")
        b = _ids(TST_B, "TST")
        self.assertEqual(len(b), 1)
        self.assertEqual((b[0]["digitos"], b[0]["classe_propria"]), ("10057132720235020000", "AG ROT"))
        self.assertLess(b[0]["posicao"], 200)
        c = _ids(TST_C, "TST")
        # só o número dos "autos de …"; o processo citado depois NÃO entra
        self.assertEqual([x["digitos"] for x in c], ["00886123120085240005"])
        self.assertEqual(c[0]["classe_propria"], "AIRR")

    def test_regiao(self):
        self.assertTrue(regiao_de_identificacao(STF_A, "STF").endswith("SÃO PAULO "))
        self.assertIn("autos de", regiao_de_identificacao(TST_A, "TST"))
        self.assertEqual(extrair_identificadores_proprios("texto qualquer", None), [])


class TestNormativos(unittest.TestCase):
    def test_diploma(self):
        self.assertEqual(diploma_canonico("art. 321, I, do CPC"), "CPC")
        self.assertEqual(diploma_canonico("art. 1.144 da Lei nº\n13.105/2015"), "CPC")
        self.assertEqual(diploma_canonico("artigo 9º, XXIX, da Constituição Fcderal"), "CF")
        self.assertEqual(diploma_canonico("art. 97, IX, da Constituição da República"), "CF")
        self.assertEqual(diploma_canonico("art 319 do Código\nde Processo Penal"), "CPP")
        self.assertEqual(diploma_canonico("art. 240 do Código Penal Militar"), "CPM")
        self.assertEqual(diploma_canonico("art. 12 do Código de Defesa do Consumidor"), "CDC")
        self.assertEqual(diploma_canonico("artigo 187 do Código Civil"), "CC")
        self.assertEqual(diploma_canonico("art. 791 da CLT"), "CLT")
        self.assertEqual(diploma_canonico("art 224 do Código Eleitoral"), "CE")
        self.assertEqual(diploma_canonico("art. 22, I, 'g', da Lei Complementar nº 64/1990"), "LC64")
        self.assertEqual(diploma_canonico("art. 60 da Lei nº 13.467/2017"), "LEI-13467")
        self.assertEqual(diploma_canonico("artigo 41 da Lei nº 9.504/1997"), "LEI-9504")
        self.assertEqual(diploma_canonico("Artigo 899 do Decreto-Lei nº 5.452, de 1º de maio de 1943"), "CLT")
        self.assertIsNone(diploma_canonico("art. 5º de algo desconhecido"))

    def test_artigo_e_sumula(self):
        self.assertEqual(artigo_canonico("art. 8º, LV, da CF"), "8")
        self.assertEqual(artigo_canonico("artigo 1.026, § 2º, do CPC"), "1026")
        self.assertEqual(artigo_canonico("art. 3l9 do CPP"), "319")
        self.assertEqual(artigo_canonico("art. 899, § 1º-A, da CLT"), "899")
        self.assertEqual(sumula_canonica("5umula 219 do STJ"), ("STJ", False, 219))
        self.assertEqual(sumula_canonica("Súmula Vinculante 45"), ("STF", True, 45))
        self.assertEqual(sumula_canonica("Súm. 47 do TSE"), ("TSE", False, 47))
        self.assertEqual(sumula_canonica("SÚMULA 123 do STJ"), ("STJ", False, 123))
        self.assertEqual(sumula_canonica("Súmula 614\ndo STF"), ("STF", False, 614))

    def test_derivacao_das_tabelas(self):
        regs = [
            ("s1", "sumula", "STJ", "Súmula n. 123 do STJ\nDIREITO PROCESSUAL CIVIL"),
            ("s2", "sumula", "STF", "Súmula Vinculante n. 45 do STF\nPROCESSUAL CIVIL"),
            ("d1", "dispositivo", None, "Artigo 321 da Lei nº 13.105, de 16 de março de 2015\nArt. 321. O ônus"),
            ("d2", "dispositivo", None, "Artigo 97 da Constituição Federal de 1988\nArt. 97."),
            ("d3", "dispositivo", None, "Artigo 22 da Lei Complementar nº 64, de 18 de maio de 1990\nArt. 22"),
            ("d4", "dispositivo", None, "Artigo 240 do Decreto-Lei nº 1.001, de 21 de outubro de 1969\nArt. 240."),
            ("d5", "dispositivo", None, "Artigo 224 da Lei nº 4.737, de 15 de julho de 1965\nArt. 224."),
        ]
        n = derivar_normativos(regs)
        self.assertEqual(n["sumulas"], {"STF|1|45": "s2", "STJ|0|123": "s1"})
        self.assertEqual(n["dispositivos"], {"CE|224": "d5", "CF|97": "d2", "CPC|321": "d1", "CPM|240": "d4", "LC64|22": "d3"})
        self.assertEqual(n["nao_derivados"], [])


def _indice_sintetico() -> dict:
    """Índice mínimo com um par ambíguo (mesmo número, classes diferentes) e um par de duplicatas."""
    def reg(doc, idc, trib, ano, rel, classe, digitos, formato, uf, natureza="acordao", tipo="jurisprudencia"):
        return {"id_canonico": idc, "tribunal": trib, "ano": ano, "relator": rel, "natureza": natureza, "tipo": tipo,
                "texto_len": 1000, "classe_propria": classe,
                "identificadores": [{"digitos": digitos, "formato": formato, "classe_propria": classe,
                                     "classe_principal": classe_principal(classe.split()) if classe else None,
                                     "uf": uf, "posicao": 10, "bruto": ""}] if digitos else [],
                "cabecalho": f"CABEÇALHO {doc}"}
    registros = {
        "doc_a": reg("doc_a", 101, "STJ", 2018, "Min. FULANO DE TAL", "AGINT RESP", "1597461", "sequencial", "PR"),
        "doc_b": reg("doc_b", 102, "STJ", 2019, "Nádia Andrade", "AGINT ERESP", "1597461", "sequencial", "PR"),
        "doc_c": reg("doc_c", 103, "STF", 2024, "Túlio Brandão", "AGR RCL", "66571", "sequencial", "RJ"),
        "doc_d": reg("doc_d", 104, "TSE", 2016, "Min. HORÁCIO NUNES DA SILVA", "AGR RESPE", "00003791220166050151", "cnj", "BA"),
        "doc_e": reg("doc_e", 105, "TST", 2017, "João Ricardo Freitas Pinto", "AIRR", "00258251820155240091", "cnj", None),
        "doc_f": reg("doc_f", 106, "STM", 2023, "Mario Augusto", "APL", "70000999120227000000", "cnj", "PR"),
        "doc_g": reg("doc_g", 107, "STM", 2023, "Mario Augusto", "APL", "70000999120227000000", "cnj", "PR"),
        "doc_h": reg("doc_h", 108, "STF", 2024, "Túlio Brandão", "AGR RCL", "66572", "sequencial", "SP"),
        "sum1": reg("sum1", 201, "STJ", None, None, None, "", "", None, "sumula"),
        "disp1": reg("disp1", 301, None, None, None, None, "", "", None, "dispositivo", "lei"),
    }
    por_digitos: dict[str, list[str]] = {}
    for d, r in registros.items():
        for it in r["identificadores"]:
            por_digitos.setdefault(it["digitos"], []).append(d)
    return {"versao": 1, "registros": registros, "por_digitos": por_digitos, "sem_identificador": [],
            "normativos": {"sumulas": {"STJ|0|123": "sum1"}, "dispositivos": {"CPC|321": "disp1"},
                           "diplomas_na_base": ["CPC"], "nao_derivados": []}}


class TestConsultaSintetica(unittest.TestCase):
    def setUp(self):
        self.base = BaseCanonica(_indice_sintetico())

    def test_por_numero_e_ordem(self):
        c = self.base.candidatos_por_numero("1597461")
        self.assertEqual([r.documento_id for r in c], ["doc_a", "doc_b"])
        self.assertIsInstance(c[0], Registro)
        self.assertEqual(self.base.candidatos_por_numero("AgInt no REsp 1.597.461/PR")[0].id_canonico, 101)
        self.assertEqual(self.base.candidatos_por_numero("999"), [])
        self.assertEqual(self.base.candidatos_por_numero(""), [])

    def test_desempate_por_cadeia_exata_depois_por_classe_principal(self):
        exato = self.base.candidatos_por_numero_e_classe("1597461", "AgInt no REsp", None)
        self.assertEqual([r.documento_id for r in exato], ["doc_a"])
        frouxo = self.base.candidatos_por_numero_e_classe("1597461", "REsp", None)
        self.assertEqual([r.documento_id for r in frouxo], ["doc_a"])
        eresp = self.base.candidatos_por_numero_e_classe("1597461", "EREsp", "STJ")
        self.assertEqual([r.documento_id for r in eresp], ["doc_b"])
        self.assertEqual(self.base.candidatos_por_numero_e_classe("1597461", "REsp", "STJ", estrito=True), [])
        self.assertEqual(self.base.candidatos_por_numero_e_classe("1597461", "Rcl", None), [])

    def test_filtros_tribunal_e_uf(self):
        self.assertEqual(self.base.candidatos_por_numero_e_classe("66571", None, "STJ"), [])
        self.assertEqual(len(self.base.candidatos_por_numero_e_classe("66571", None, "STF")), 1)
        self.assertEqual(self.base.candidatos_por_numero_e_classe("66571", "Rcl", "STF", uf="SP"), [])
        self.assertEqual(len(self.base.candidatos_por_numero_e_classe("66571", "Rcl", "STF", uf="RJ")), 1)
        # registro sem UF (TST) não é eliminado por UF informada
        self.assertEqual(len(self.base.candidatos_por_numero_e_classe("00258251820155240091", "AgARR", "TST", uf="MS")), 1)

    def test_classe_da_familia_tst_nao_elimina(self):
        c = self.base.candidatos_por_numero_e_classe("TST-AgARR-25825-18.2015.5.24.0091", "TST-AgARR", "TST")
        self.assertEqual([r.documento_id for r in c], ["doc_e"])

    def test_duplicatas_permanecem_ambiguas(self):
        c = self.base.candidatos_por_numero_e_classe("70000999120227000000", "APL", "STM", uf="PR")
        self.assertEqual([r.documento_id for r in c], ["doc_f", "doc_g"])

    def test_sumula_e_dispositivo(self):
        self.assertEqual(self.base.sumula("STJ", False, 123).id_canonico, 201)
        self.assertIsNone(self.base.sumula("STF", False, 123))
        self.assertEqual(self.base.sumula(None, False, 123).id_canonico, 201)
        self.assertIsNone(self.base.sumula("STJ", True, 123))
        self.assertEqual(self.base.dispositivo("CPC", "321").id_canonico, 301)
        self.assertEqual(self.base.dispositivo("CPC", "0321").id_canonico, 301)
        self.assertIsNone(self.base.dispositivo("CPC", "1144"))
        self.assertIsNone(self.base.dispositivo("LEI-9504", "41"))

    def test_por_relator_ano(self):
        self.assertEqual([r.documento_id for r in self.base.por_relator_ano("STF", 2024, "Túlio Brandão")], ["doc_c", "doc_h"])
        self.assertEqual([r.documento_id for r in self.base.por_relator_ano("STJ", 2018, "Fulano de Tal")], ["doc_a"])
        self.assertEqual(self.base.por_relator_ano("STJ", 2018, "Beltrano"), [])
        self.assertEqual([r.documento_id for r in self.base.por_relator_ano(None, 2023, "Mário Augusto")], ["doc_f", "doc_g"])

    def test_relator_compativel_tolerante(self):
        self.assertTrue(relator_compativel("Fulano Reis Sobrlnho", "Fulano Reis Sobrinho"))
        self.assertTrue(relator_compativel("Ana Zefirã", "Ministra ANA ZEFIRA"))
        self.assertTrue(relator_compativel("Mario Augusto", "Mário Augusto de Faria"))
        self.assertTrue(relator_compativel("Cesar De Melo", "Min. CESAR DE MELO"))
        self.assertFalse(relator_compativel("Rita Werner", "Elton Farias"))
        self.assertFalse(relator_compativel("", "Elton Farias"))

    def test_cabecalho_e_ids(self):
        self.assertEqual(self.base.cabecalho("doc_a"), "CABEÇALHO doc_a")
        self.assertEqual(self.base.por_id_canonico(105).documento_id, "doc_e")
        self.assertEqual(self.base.registro("doc_c").classe_principal, "RCL")
        self.assertEqual(len(self.base), 10)


# ---------------------------------------------------------------------------
@unittest.skipUnless(TEM_DADOS, "dados do desafio ausentes")
class TestComDados(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.indice = construir_indice(DB)
        cls.base = BaseCanonica(cls.indice)
        with open(GOLDENSET, encoding="utf-8-sig", newline="") as f:
            cls.gab = list(csv.DictReader(f))
        for x in cls.gab:
            x["trecho"] = x["trecho"].replace("\\n", "\n")

    def test_todos_os_acordaos_tem_identificador(self):
        self.assertEqual(self.indice["sem_identificador"], [])
        for r in self.base.registros():
            if r.natureza == "acordao":
                self.assertTrue(self.base.identificadores(r.documento_id), r.documento_id)
                self.assertTrue(r.classe_propria is not None or r.tribunal == "TSE", r.documento_id)

    def test_determinismo(self):
        a = json.dumps(self.indice, sort_keys=True, ensure_ascii=False)
        b = json.dumps(construir_indice(DB), sort_keys=True, ensure_ascii=False)
        self.assertEqual(a, b)

    def test_cobertura_96_de_96(self):
        reais = [x for x in self.gab if x["classificacao"] == "real"]
        self.assertEqual(len(reais), 96)
        ok = 0
        for x in reais:
            t, gab_id = x["trecho"], int(x["id_canonico"])
            if x["tipo"] == "lei":
                reg = self.base.dispositivo(diploma_canonico(t) or "", artigo_canonico(t) or "")
                ok += reg is not None and reg.id_canonico == gab_id
            elif re.search(r"[s5]\s?[uúü]\s?m", t, re.I):
                trib, vinc, num = sumula_canonica(t)
                reg = self.base.sumula(trib, vinc, num or -1)
                ok += reg is not None and reg.id_canonico == gab_id
            else:
                sem_uf, uf = separar_uf(t)
                cands = self.base.candidatos_por_numero_e_classe(digitos_canonicos(t), sem_uf, None, uf)
                self.assertEqual(len(cands), 1, f"{t!r} → {[c.documento_id for c in cands]}")
                ok += cands[0].id_canonico == gab_id
        self.assertEqual(ok, 96)

    def test_inventadas_nunca_sao_numero_proprio(self):
        for x in self.gab:
            if x["classificacao"] != "inventada" or x["tipo"] != "jurisprudencia":
                continue
            t = x["trecho"]
            if re.search(r"[s5]\s?[uúü]\s?m|tem[aã]", t, re.I):
                continue
            dig = digitos_canonicos(t)
            self.assertTrue(dig, t)
            self.assertEqual(self.base.candidatos_por_numero(dig), [], t)

    def test_lei_e_sumula_coerentes(self):
        for x in self.gab:
            t = x["trecho"]
            if x["tipo"] == "lei":
                d, a = diploma_canonico(t), artigo_canonico(t)
                self.assertIsNotNone(d, t)
                reg = self.base.dispositivo(d, a or "")
            elif re.search(r"[s5]\s?[uúü]\s?m", t, re.I):
                trib, vinc, num = sumula_canonica(t)
                reg = self.base.sumula(trib, vinc, num or -1)
            else:
                continue
            self.assertEqual(reg is not None, x["classificacao"] == "real", t)

    def test_incompletas_sempre_multiplas(self):
        from importlib import import_module
        sys.path.insert(0, str(RAIZ / "scripts" / "analise"))
        validar = import_module("validar_indice")
        for x in self.gab:
            if x["classificacao"] != "incompleta":
                continue
            trib, ano, rel = validar.parse_incompleta(x["trecho"])
            n = len(self.base.por_relator_ano(trib, ano, rel))
            self.assertGreaterEqual(n, 2, x["trecho"])

    def test_normativos_derivados_da_base(self):
        n = self.indice["normativos"]
        self.assertEqual(len(n["sumulas"]), 5)
        self.assertEqual(len(n["dispositivos"]), 13)
        self.assertEqual(n["nao_derivados"], [])
        self.assertEqual(n["diplomas_na_base"], ["CC", "CDC", "CE", "CF", "CLT", "CPC", "CPM", "CPP", "LC64"])

    def test_sem_colisao_entre_tribunais(self):
        for dig, docs in self.indice["por_digitos"].items():
            tribs = {self.base.registro(d).tribunal for d in docs}
            self.assertEqual(len(tribs), 1, dig)


if __name__ == "__main__":
    unittest.main()
