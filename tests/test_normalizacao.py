"""Testes de ``caca_alucinacao.normalizacao`` (implementação única de normalização).

Todos os números, nomes e trechos são SINTÉTICOS: preservam os padrões medidos
em docs/03_analise_gabarito.md (§2, §3, §9.2) e docs/04_analise_base.md (h.2,
h.5–h.7), mas nenhum é do gabarito nem da base. Rodar com::

    PYTHONPATH=src python -m unittest tests.test_normalizacao -v
"""
from __future__ import annotations

import inspect
import sys
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao import normalizacao as N  # noqa: E402
from caca_alucinacao.normalizacao import (  # noqa: E402
    FORMATO_CNJ,
    FORMATO_CNJ20,
    FORMATO_CURTO,
    FORMATO_OUTRO,
    FORMATO_REGISTRO,
    FORMATO_SEQUENCIAL,
    UFS,
    cadeia_da_citacao,
    cadeia_de_classes,
    chave_textual,
    classe_principal,
    classe_processual_canonica,
    classes_compativeis,
    classificar_digitos,
    como_cadeia,
    corrigir_ocr_em_grupo,
    corrigir_ocr_em_numero,
    digitos_canonicos,
    digitos_do_identificador,
    formato_de,
    inferir_tribunal,
    nucleo_principal,
    nucleos,
    numeros_com_posicao,
    numeros_do_texto,
    sem_acento,
    separar_uf,
    tolerante,
    uf_de_estado,
)

# Tabela de referência (repositório público documentado) + a nossa convenção
# para o CNJ do TST (sempre 20 dígitos com o sequencial preenchido a 7).
CASOS: list[tuple[str, str]] = [
    ("REsp 1.234.567/SP", "1234567"),
    ("AgInt no AREsp nº 2.345.678/RJ", "2345678"),
    ("RSE nº 1234567-89.2025.7.00.0000/DF", "12345678920257000000"),
    ("Súmula Vinculante 99", "99"),
    ("AgRg no Rec. Esp. n. 3.456.789 (SC)", "3456789"),
    ("Recurso em Habeas Corpus nº 45678 - SC", "45678"),
    ("Rec. Esp. No 4.567.890\n- SP", "4567890"),
    ("RESP n. 5 678 901/BA", "5678901"),
    ("Reclamação n° 56.- 789 (MA)", "56789"),
    ("APL 1234567-89 2021 7 00 0000/BA", "12345678920217000000"),
    ("AgInt no RESP 34567l9 - SP", "3456719"),
    ("R.Esp. n° 2.34g.567-MA", "2349567"),
    ("EDcl no AgInt no Recurso Especial Nº 345678O (SP)", "3456780"),
    ("AgRg no RESP 2.639.5S6/ RJ", "2639556"),
    # o repositório público documenta "12345620115020251" (17 dígitos); a NOSSA
    # convenção (docs/02 regra 5, docs/04) é 20 dígitos zero-padded, a mesma
    # chave que o índice grava para o cabeçalho do acórdão do TST
    ("TST-ED-E-ED-ARR-1234-56.2011.5.02.\n0251", "00012345620115020251"),
    ("REsp 1.234.567 DO STJ", "1234567"),
]


class TestTexto(unittest.TestCase):
    def test_sem_acento(self):
        self.assertEqual(sem_acento("Constituição Fedéral ÀÉÎÕÜ ç"), "Constituicao Federal AEIOU c")
        self.assertEqual(sem_acento("nº 2º 3ª"), "nº 2º 3ª")  # º/ª não são diacríticos

    def test_chave_textual(self):
        self.assertEqual(chave_textual("Constituição  Federal\n"), "constituicao federal")
        self.assertEqual(chave_textual("Rel.\xa0 Min.\nFULANO"), "rel. min. fulano")
        self.assertEqual(chave_textual("  \n "), "")

    def test_tolerante_regras_do_nivel_2(self):
        self.assertTrue(tolerante("Fcderal", "Federal"))          # 1 troca, ≥ 5 letras
        self.assertTrue(tolerante("proferldo", "proferido"))
        self.assertTrue(tolerante("assirn", "assim"))             # rn ↔ m
        self.assertTrue(tolerante("Fulãno", "FULANO"))      # acento + caixa
        self.assertTrue(tolerante("Sobrlnho", "Sobrinho"))            # l por i
        self.assertTrue(tolerante("Sicrãno", "Sicrano"))
        self.assertTrue(tolerante("Võto", "Voto"))                # só acento (palavra curta)
        self.assertTrue(tolerante("Fulana De Tal", "FULANA DE TAL"))
        self.assertTrue(tolerante("Rel.  Min. Fulano", "Rel. Min. Fulano"))

    def test_tolerante_nao_tolera(self):
        self.assertFalse(tolerante("dc", "de"))                   # < 5 letras: exato
        self.assertFalse(tolerante("Rita Werner", "Elton Farias"))
        self.assertFalse(tolerante("Fcderal", "Federal", max_erros=0))
        self.assertFalse(tolerante("Rita Werner", "Rosa"))         # nº de palavras diferente
        self.assertFalse(tolerante("Fulano", "Fulana Silva"))
        self.assertFalse(tolerante("Federal", "Fedcrxl"))         # 2 trocas
        self.assertFalse(tolerante("", ""))
        self.assertTrue(tolerante("Federal", "Fedcrxl", max_erros=2))


class TestSepararUf(unittest.TestCase):
    def test_todos_os_separadores_medidos(self):
        for trecho in [
            "AREsp 1234567/SP", "AREsp 1234567/ SP", "AREsp 1234567-SP", "AREsp 1234567 - SP",
            "AREsp 1234567 – SP", "AREsp 1234567 (SP)", "AREsp 1234567\n- SP", "AREsp 1234567 —SP",
            "AREsp 1234567/SP.", "AREsp 1234567 (SP),", "AREsp 1234567\xa0/\xa0SP", "AREsp 1234567 SP",
        ]:
            sem_uf, uf = separar_uf(trecho)
            self.assertEqual(uf, "SP", trecho)
            self.assertEqual(sem_uf, "AREsp 1234567", trecho)
        self.assertEqual(separar_uf("AREsp 1234567/SP"), ("AREsp 1234567", "SP"))

    def test_so_as_27_siglas_e_so_no_fim(self):
        self.assertEqual(len(UFS), 27)
        self.assertEqual(separar_uf("Súmula 456 do TST"), ("Súmula 456 do TST", None))
        self.assertEqual(separar_uf("REsp 1.234.567 DO STJ"), ("REsp 1.234.567 DO STJ", None))
        self.assertEqual(separar_uf("REsp 1.234.567/XX"), ("REsp 1.234.567/XX", None))
        self.assertEqual(separar_uf("REsp 1.234.567/SP e outro"), ("REsp 1.234.567/SP e outro", None))
        self.assertEqual(separar_uf("julgado do STF de 2024, relatoria de Fulano"),
                         ("julgado do STF de 2024, relatoria de Fulano", None))
        self.assertEqual(separar_uf("RCL n° 45782 (GO)"), ("RCL n° 45782", "GO"))
        self.assertEqual(separar_uf("Recurso Especial nº 1385702/ SP"), ("Recurso Especial nº 1385702", "SP"))

    def test_uf_que_tambem_e_sigla_de_classe(self):
        # com número: é UF
        self.assertEqual(separar_uf("Rcl 12.345/AC"), ("Rcl 12.345", "AC"))
        self.assertEqual(separar_uf("MS 12.345 - RO"), ("MS 12.345", "RO"))
        # sem número não há UF a separar: a classe fica intacta
        self.assertEqual(separar_uf("AgRg no MS"), ("AgRg no MS", None))
        self.assertEqual(separar_uf("AgR-RO"), ("AgR-RO", None))
        self.assertEqual(separar_uf("TST-RR"), ("TST-RR", None))

    def test_ce_no_fim_de_processo_e_uf(self):
        self.assertEqual(separar_uf("REsp 1.234.567/CE"), ("REsp 1.234.567", "CE"))
        # em dispositivo o diploma é lido antes por normativos; aqui só se documenta o comportamento
        self.assertEqual(separar_uf("art. 224 do CE"), ("art. 224 do", "CE"))

    def test_uf_antes_da_correcao_de_ocr(self):
        # o "S" de SP e o "O" de RO nunca viram 5/0
        self.assertEqual(digitos_do_identificador("AgInt no RESP 1234 - SP"), "1234")
        self.assertEqual(digitos_do_identificador("Rcl 1234/RO"), "1234")
        self.assertEqual(digitos_do_identificador("Rcl 1234-SE"), "1234")


class TestCorrecaoOcr(unittest.TestCase):
    def test_corrigir_ocr_em_numero(self):
        self.assertEqual(corrigir_ocr_em_numero("34567l9"), "3456719")
        self.assertEqual(corrigir_ocr_em_numero("1.46g.781"), "1.469.781")
        self.assertEqual(corrigir_ocr_em_numero("199999O"), "1999990")
        self.assertEqual(corrigir_ocr_em_numero("9G.999"), "96.999")
        self.assertEqual(corrigir_ocr_em_numero("1.999.9S9"), "1.999.959")
        self.assertEqual(corrigir_ocr_em_numero("0601517-93.2020.6.05.0000"), "0601517-93.2020.6.05.0000")

    def test_letra_so_dentro_de_grupo_que_comeca_com_digito(self):
        for fora in ["AREspEI", "AREspEl", "DO5", "C0NTROVÉRSIA", "No", "SP", "S", "l", ""]:
            self.assertEqual(corrigir_ocr_em_numero(fora), fora)
        # a UF já separada não seria tocada; mas mesmo colada, fora do grupo numérico fica intacta
        self.assertEqual(corrigir_ocr_em_numero("34567l9 - SP"), "3456719 - SP")

    def test_mapa_completo_e_digito_nunca_vira_digito(self):
        self.assertEqual(corrigir_ocr_em_numero("1O1o1l1I1|1S1s1g1q1G1B1Z1z"), "10101111111515191916181212")
        self.assertEqual(corrigir_ocr_em_numero("0123456789"), "0123456789")

    def test_corrigir_ocr_em_grupo(self):
        self.assertEqual(corrigir_ocr_em_grupo("46g"), "469")
        self.assertIsNone(corrigir_ocr_em_grupo("No"))
        self.assertIsNone(corrigir_ocr_em_grupo("SS"))
        self.assertIsNone(corrigir_ocr_em_grupo("OO6"))  # maioria de letras: nunca duas no mesmo número
        self.assertEqual(corrigir_ocr_em_grupo("6G"), "66")


class TestDigitos(unittest.TestCase):
    def test_tabela_casos(self):
        for trecho, esperado in CASOS:
            self.assertEqual(digitos_do_identificador(trecho), esperado, repr(trecho))

    def test_digitos_canonicos_e_o_mesmo_objeto(self):
        self.assertIs(digitos_canonicos, digitos_do_identificador)

    def test_convencao_cnj_20_digitos(self):
        # sequencial de 1–7 dígitos, com/sem pontuação, espaços, quebras, hífen duplo, ".-", "-\n."
        self.assertEqual(digitos_do_identificador("AgR-REspe 379-12.2016.6.05.0151"), "00003791220166050151")
        self.assertEqual(digitos_do_identificador("AgR-REspe 12-34.2011.6.05.0099"), "00000123420116050099")
        self.assertEqual(digitos_do_identificador("AgR-REspe 12-34. 2011.6.05.0099"), "00000123420116050099")
        self.assertEqual(digitos_do_identificador("REspe No  0600319-5120206160182"), "06003195120206160182")
        self.assertEqual(digitos_do_identificador("REspe. n° 0600457-13.2020-\n.6.14.0022"), "06004571320206140022")
        self.assertEqual(digitos_do_identificador("APL 7009999--\n12.2021.7.00.0000/DF"), "70099991220217000000")
        self.assertEqual(digitos_do_identificador("processo nº TST-E-RR-999-12.2011.5.15.0099"), "00009991220115150099")
        self.assertEqual(digitos_do_identificador("TST- ED - E-ED-RR-1-27.2017.5.02.0001"), "00000012720175020001")
        self.assertEqual(digitos_do_identificador("ED no AgR no AREspEI 0601517-93.2020.6.05.0000"), "06015179320206050000")
        self.assertEqual(classificar_digitos("34110720115210009"), ("00034110720115210009", FORMATO_CNJ))

    def test_numeros_curtos_ficam_como_estao(self):
        self.assertEqual(digitos_do_identificador("REsp 1 234 567/SP"), "1234567")
        self.assertEqual(digitos_do_identificador("REsp 1. 234.567/SP"), "1234567")
        self.assertEqual(digitos_do_identificador("Rcl 11.-\n222/SP"), "11222")
        self.assertEqual(digitos_do_identificador("Rcl 2.111-\n.222/SP"), "2111222")
        self.assertEqual(digitos_do_identificador("Rcl 11-\n.222/SP"), "11222")
        self.assertEqual(digitos_do_identificador("RE nº\xa05. 231.809-DF"), "5231809")
        self.assertEqual(digitos_do_identificador("ARESP\xa01234567 - SP"), "1234567")
        self.assertEqual(digitos_do_identificador("Rcl 0036/SP"), "36")
        self.assertEqual(classificar_digitos("1741799"), ("1741799", FORMATO_SEQUENCIAL))

    def test_ocr_em_qualquer_posicao_do_numero(self):
        self.assertEqual(digitos_do_identificador("REsp 21999l1/SP"), "2199911")
        self.assertEqual(digitos_do_identificador("REsp 199999O/SP"), "1999990")
        self.assertEqual(digitos_do_identificador("REsp 1.99g.999/SP"), "1999999")
        self.assertEqual(digitos_do_identificador("REsp 1.999.9S9/SP"), "1999959")
        self.assertEqual(digitos_do_identificador("Rcl 9G.999/SP"), "96999")
        self.assertEqual(digitos_do_identificador("Recl. n° 6G.841/ BA"), "66841")

    def test_registro_stj(self):
        self.assertEqual(digitos_do_identificador("(2019/0123456-7)"), "201901234567")
        self.assertEqual(classificar_digitos("201901234567"), ("201901234567", FORMATO_REGISTRO))
        # número + registro: o número (primeiro núcleo com ≥ 4 dígitos) é a chave
        self.assertEqual(digitos_do_identificador("RECURSO ESPECIAL Nº 1.234.567 - PR (2019/0123456-7)"), "1234567")

    def test_digito_dentro_de_palavra_nao_e_numero(self):
        for t in ["DO5", "C0NTROVÉRSIA", "5alvador", "AREspEI", "AREspEl", "No", "sem número", ""]:
            self.assertEqual(digitos_do_identificador(t), "", repr(t))
            self.assertEqual(nucleos(t), [], repr(t))
        # colado a "º"/"." continua número
        self.assertEqual(digitos_do_identificador("Nº42"), "42")
        self.assertEqual(digitos_do_identificador("art.5"), "5")
        self.assertEqual(digitos_do_identificador("QO na CAUTELAR INOMINADA CRIMINAL Nº 42"), "42")

    def test_nucleos_e_principal(self):
        ns = nucleos("Nº 36.123 ( 43210-98.2009.6.00.0000)")
        self.assertEqual([n.digitos for n in ns], ["36123", "00432109820096000000"])
        self.assertEqual([n.formato for n in ns], [FORMATO_SEQUENCIAL, FORMATO_CNJ])
        self.assertEqual(ns[0].bruto, "36.123")
        self.assertEqual((ns[0].inicio, ns[0].fim), (3, 9))
        self.assertEqual(nucleo_principal("Nº 36.123 ( 43210-98.2009.6.00.0000)").digitos, "36123")
        self.assertEqual(nucleo_principal("Rcl 12.345 (2021)").digitos, "12345")   # primeiro com ≥ 4
        self.assertEqual(nucleo_principal("Rcl 2021 12.345").digitos, "202112345")  # espaço é separador interno
        self.assertEqual(nucleo_principal("Súmula 7 do STJ").digitos, "7")
        self.assertIsNone(nucleo_principal("sem número"))
        self.assertEqual(digitos_do_identificador("julgado do STF de 2024, relatoria de Fulano"), "2024")

    def test_formato_de(self):
        self.assertEqual(formato_de("12345678920257000000"), FORMATO_CNJ20)
        self.assertEqual(formato_de("34110720115210009"), FORMATO_CNJ20)   # ainda não canônico
        self.assertEqual(formato_de("1234567"), FORMATO_CURTO)
        self.assertEqual(formato_de("42"), FORMATO_CURTO)
        self.assertEqual(formato_de("201901234567"), FORMATO_REGISTRO)
        self.assertEqual(formato_de(""), FORMATO_OUTRO)
        self.assertEqual(formato_de("1" * 21), FORMATO_OUTRO)
        self.assertEqual(formato_de("1.234.567"), FORMATO_OUTRO)
        self.assertEqual({FORMATO_CNJ20, FORMATO_CURTO, FORMATO_REGISTRO, FORMATO_OUTRO},
                         {"cnj20", "curto", "registro", "outro"})

    def test_numeros_do_texto(self):
        t = "RECURSO ESPECIAL Nº 1.234.567 - PR (2019/0123456-7)"
        self.assertIn("1234567", numeros_do_texto(t))
        self.assertEqual(numeros_do_texto(t), ["1234567", "201901234567"])
        t2 = "cita o REsp 1.234.567/SP e o processo 0001234-56.2019.5.02.0030, fls. 2.826/2.883e, art. 1.026 e o REsp 1.234.567"
        digs = numeros_do_texto(t2)
        self.assertEqual(digs.count("1234567"), 1)   # sem repetição
        self.assertIn("00012345620195020030", digs)
        self.assertIn("1026", digs)
        pos = numeros_com_posicao(t2)
        self.assertEqual(pos[0][2], "1234567")
        self.assertEqual(t2[pos[0][0]:pos[0][1]], "1.234.567")
        self.assertEqual(numeros_do_texto("nada aqui, 12 e 123"), [])


class TestClasses(unittest.TestCase):
    def test_superficies_de_docs03_para_classe_principal(self):
        casos = {
            "RESP": ["REsp 1234567/SP", "RESP 1234567/SP", "Rec. Esp. 1234567/SP", "R.Esp. 1234567/SP",
                     "Recurso Especial 1234567/SP", "Recurso\nEspecial nº 1234567/SP"],
            "RCL": ["Rcl 12345/SP", "RCL 12345/SP", "Recl. 12345/SP", "Reclamação 12345/SP", "Rcl\n12.345/SP"],
            "ARESP": ["AREsp 1234567/SP", "ARESP\xa01234567/SP", "AgREsp 1234567/SP", "A.REsp 1234567/SP",
                      "Agravo em Recurso Especial 1234567/SP"],
            "RR": ["RR 1234-56.2011.5.02.0251", "TST-RR-1234-56.2011.5.02.0251"],
            "AIRR": ["AIRR 1234-56.2011.5.02.0251"], "ARR": ["ARR 1234-56.2011.5.02.0251", "AgARR 1234-56.2011.5.02.0251"],
            "RRAG": ["RRAg 1234-56.2011.5.02.0251"],
            "RHC": ["RHC 12345/SP", "Recurso em Habeas Corpus nº 12345 - SP"],
            "RESPE": ["REspe 12-34.2016.6.05.0099", "RESPE 12-34.2016.6.05.0099", "REspe. 12-34.2016.6.05.0099",
                      "Recurso Especial Eleitoral 12-34.2016.6.05.0099"],
            "ARESPE": ["AREspEl 12-34.2016.6.05.0099", "AREspEI 12-34.2016.6.05.0099"],
            "APL": ["APL 7000123-45.2023.7.00.0000/RS", "Apelação 7000123-45.2023.7.00.0000"],
            "RSE": ["RSE 7000123-45.2023.7.00.0000"],
            "AGINT": ["AgInt 7000123-45.2023.7.00.0000", "AGINT 7000123-45.2023.7.00.0000", "Ag. Int. No 7000123-45.2023.7.00.0000"],
            "RE": ["RE 1234567/SP", "RE. 1234567/SP", "Recurso Extraordinário 1234567/SP"],
            "ARE": ["ARE 1234567/SP"],
            "RMS": ["RMS 12345/SP", "Recurso em Mandado de Segurança 12345/SP"],
            "AI": ["AI 12-34.2016.6.05.0099", "Agravo de Instrumento 12-34.2016.6.05.0099"],
            "HC": ["HC 123456/SP", "H.C. 123456/SP", "Habeas Corpus 123456/SP"],
            "MS": ["MS 12345/DF"], "AR": ["AR 1234/SP"],
            "SLS": ["SLS 1234/SP", "Suspensão de Liminar e de Sentença 1234/SP", "Suspensão\nde Liminar e de Sentença 1234/SP"],
            "RP": ["Rp 1234/SP"], "RRP": ["R-Rp 1234/SP"],
            "ERESP": ["EREsp 1234567/SP", "Embargos de Divergência em REsp 1234567/SP",
                      "Embargos de Divergência em Recurso Especial 1234567/SP"],
        }
        for esperado, trechos in casos.items():
            for t in trechos:
                self.assertEqual(classe_processual_canonica(t), esperado, repr(t))

    def test_prefixos_conectores_ordinais_e_hifen(self):
        self.assertEqual(cadeia_da_citacao("AgInt no AREsp nº 2.345.678/RJ"), ["AGINT", "ARESP"])
        self.assertEqual(cadeia_da_citacao("AgRg no REsp 1234567/SP"), ["AGR", "RESP"])
        self.assertEqual(cadeia_da_citacao("AGR na Rcl 12345/SP"), ["AGR", "RCL"])
        self.assertEqual(cadeia_da_citacao("AG.REG na Rcl 12345/SP"), ["AGR", "RCL"])
        self.assertEqual(cadeia_da_citacao("Agravo Regimental na Reclamação 12345/SP"), ["AGR", "RCL"])
        self.assertEqual(cadeia_da_citacao("Agravo Interno no Recurso Especial 1234567/SP"), ["AGINT", "RESP"])
        self.assertEqual(cadeia_da_citacao("EDcl no AgInt no REsp 1234567/SP"), ["ED", "AGINT", "RESP"])
        self.assertEqual(cadeia_da_citacao("ED no AgR no AREspEl 12-34.2016.6.05.0099"), ["ED", "AGR", "ARESPE"])
        self.assertEqual(cadeia_da_citacao("EDs no AGR-RESPE n°\xa0537-81. 2012.6.13.0029"), ["ED", "AGR", "RESPE"])
        self.assertEqual(cadeia_da_citacao("Embargos de Declaração no Agravo Interno no REsp 1234567/SP"), ["ED", "AGINT", "RESP"])
        self.assertEqual(cadeia_da_citacao("EDcl nos EDcl no AgInt no REsp 1234567/SP"), ["ED", "ED", "AGINT", "RESP"])
        self.assertEqual(cadeia_da_citacao("AgInt nos EDcl no Rec. Esp. 1234567/SP"), ["AGINT", "ED", "RESP"])
        self.assertEqual(cadeia_da_citacao("Terceiro AG.REG na Rcl 12345/SP"), ["3O", "AGR", "RCL"])
        self.assertEqual(cadeia_da_citacao("Segundo AgRg no RE 1234567/SP"), ["2O", "AGR", "RE"])
        self.assertEqual(cadeia_da_citacao("2º AgRg no RE 1234567/SP"), ["2O", "AGR", "RE"])
        self.assertEqual(cadeia_da_citacao("processo nº TST-ED-E-ED-ARR-1234-56.2011.5.02.\n0251"), ["ED", "E", "ED", "ARR"])
        self.assertEqual(cadeia_da_citacao("TST- ED - E-ED-RR-1234-56.2011.5.02.0251"), ["ED", "E", "ED", "RR"])
        self.assertEqual(cadeia_da_citacao("AgR-REspe 379-12.2016.6.05.0151"), ["AGR", "RESPE"])
        self.assertEqual(cadeia_da_citacao("AgR-AI 379-12.2016.6.05.0151"), ["AGR", "AI"])
        self.assertEqual(cadeia_da_citacao("Agravo Interno na Suspensão\nde Liminar e de Sentença 1234/SP"), ["AGINT", "SLS"])
        self.assertEqual(cadeia_da_citacao("Súmula 456 do TST"), [])
        self.assertIsNone(classe_processual_canonica("Súmula 456 do TST"))
        self.assertIsNone(classe_processual_canonica("julgado do STF de 2024, relatoria de Fulano"))

    def test_uf_nunca_vira_classe(self):
        # AC/AP/MS/RO/RR são siglas de classe E de UF: depois do número são UF
        self.assertEqual(classe_processual_canonica("Rcl 12.345/AC"), "RCL")
        self.assertEqual(classe_processual_canonica("MS 12.345/RO"), "MS")
        self.assertEqual(classe_processual_canonica("REsp 1.234.567 - RR"), "RESP")
        self.assertEqual(cadeia_de_classes("Rcl 12.345/AC"), ["RCL"])
        self.assertEqual(cadeia_de_classes("Rcl 12.345 AP"), ["RCL"])
        # sem número a sigla continua classe
        self.assertEqual(cadeia_de_classes("AgRg no MS"), ["AGR", "MS"])
        self.assertEqual(cadeia_de_classes("AgR-RO"), ["AGR", "RO"])

    def test_cadeias_do_indice_inalteradas(self):
        # mesmas siglas canônicas do protótipo (o índice em JSON depende delas)
        self.assertEqual(cadeia_de_classes("EDcl no AgInt no AREsp"), ["ED", "AGINT", "ARESP"])
        self.assertEqual(cadeia_de_classes("TST-ED-E-ED-RR"), ["ED", "E", "ED", "RR"])
        self.assertEqual(cadeia_de_classes("TST-AgARR"), ["AG", "ARR"])
        self.assertEqual(cadeia_de_classes("TST-Ag-ROT - "), ["AG", "ROT"])
        self.assertEqual(cadeia_de_classes("Ag. Int. No"), ["AGINT"])
        self.assertEqual(cadeia_de_classes("AgRg no H.C."), ["AGR", "HC"])
        self.assertEqual(cadeia_de_classes("R-Rp"), ["RRP"])
        self.assertEqual(cadeia_de_classes("PRIMEIRA TURMA AG.REG. NA RECLAMAÇÃO"), ["AGR", "RCL"])
        self.assertEqual(cadeia_de_classes("SEGUNDA TURMA SEGUNDO AG.REG. NO RECURSO EXTRAORDINÁRIO COM AGRAVO"), ["2O", "AGR", "ARE"])
        self.assertEqual(cadeia_de_classes("PLENÁRIO REFERENDO NOS DÉCIMOS EMB.DECL. NA AÇÃO PENAL"), ["REF", "10O", "ED", "AP"])
        self.assertEqual(cadeia_de_classes("AgInt nosEMBARGOS DE DIVERGÊNCIA EM RESP"), ["AGINT", "ERESP"])
        self.assertEqual(cadeia_de_classes("EMBARGOS DE DECLARAcA0 NA PREsTAcA0 DE CONTAS"), ["ED", "PC"])
        self.assertEqual(cadeia_de_classes("QO na CAUTELAR INOMINADA CRIMINAL"), ["QO", "CAUTINOM"])
        self.assertEqual(cadeia_de_classes("EMBARGOS INFRINGENTES E DE NULIDADE"), ["EI"])
        self.assertEqual(cadeia_de_classes("AGRAVO EM RECURSO ESPECIAL ELEITORAL"), ["ARESPE"])
        self.assertEqual(cadeia_de_classes("Agravo de Instrumento em Recurso de Revista"), ["AIRR"])
        self.assertEqual(cadeia_de_classes("e"), [])  # "e" minúsculo é conjunção, não Embargos

    def test_principal_compatibilidade_e_como_cadeia(self):
        self.assertEqual(classe_principal(["2O", "AGR", "RCL"]), "RCL")
        self.assertEqual(classe_principal(["QO"]), "QO")
        self.assertIsNone(classe_principal([]))
        self.assertIsNone(classe_principal(["2O"]))
        self.assertTrue(classes_compativeis("RESP", "RESPE"))
        self.assertTrue(classes_compativeis("ARESP", "ARESPE"))
        self.assertTrue(classes_compativeis("ARR", "AIRR"))
        self.assertTrue(classes_compativeis("AGR", "AGINT"))
        self.assertFalse(classes_compativeis("RESP", "ARESP"))
        self.assertFalse(classes_compativeis("RCL", "MS"))
        self.assertFalse(classes_compativeis(None, "RCL"))
        self.assertEqual(como_cadeia("AGINT ARESP"), ["AGINT", "ARESP"])
        self.assertEqual(como_cadeia("2O AGR RCL"), ["2O", "AGR", "RCL"])
        self.assertEqual(como_cadeia(("ED", "RESP")), ["ED", "RESP"])
        self.assertEqual(como_cadeia("AgInt no AREsp nº 2.345.678/RJ"), ["AGINT", "ARESP"])
        self.assertEqual(como_cadeia(None), [])
        self.assertEqual(como_cadeia(""), [])

    def test_uf_de_estado(self):
        self.assertEqual(uf_de_estado("RIO DE JANEIRO"), "RJ")
        self.assertEqual(uf_de_estado("M A R A N H Ã O"), "MA")
        self.assertEqual(uf_de_estado("PARAN„"), "PR")
        self.assertEqual(uf_de_estado("PARÁ"), "PA")
        self.assertIsNone(uf_de_estado("CIDADE QUALQUER"))


class TestInferirTribunal(unittest.TestCase):
    def test_classes_exclusivas(self):
        for cadeia, trib in [
            (["RESP"], "STJ"), (["AGINT", "ARESP"], "STJ"), (["RHC"], "STJ"), (["ERESP"], "STJ"),
            (["RE"], "STF"), (["2O", "AGR", "ARE"], "STF"), (["ADI"], "STF"), (["ADPF"], "STF"),
            (["RESPE"], "TSE"), (["ARESPE"], "TSE"), (["RO"], "TSE"), (["AI"], "TSE"), (["RRP"], "TSE"),
            (["RR"], "TST"), (["AIRR"], "TST"), (["AG", "ARR"], "TST"), (["RRAG"], "TST"),
            (["APL"], "STM"), (["RSE"], "STM"), (["EI"], "STM"),
        ]:
            self.assertEqual(inferir_tribunal(cadeia, None, "1234567", "curto"), trib, cadeia)
        self.assertEqual(inferir_tribunal("AGINT ARESP"), "STJ")
        self.assertEqual(inferir_tribunal("AgInt no AREsp nº 2.345.678/RJ"), "STJ")

    def test_ambiguas_devolvem_none(self):
        for cadeia in [["RCL"], ["AGR", "RCL"], ["HC"], ["MS"], ["AR"], ["RMS"], ["AGINT"], ["ED"], ["PET"], ["AP"], [], None]:
            self.assertIsNone(inferir_tribunal(cadeia, "SP", "12345", "curto"), cadeia)
        self.assertIsNone(inferir_tribunal("Súmula 456 do TST"))

    def test_segmento_j_do_cnj(self):
        self.assertEqual(inferir_tribunal([], None, "00012345620115020251", "cnj20"), "TST")
        self.assertEqual(inferir_tribunal([], None, "00003791220166050151", "cnj"), "TSE")
        self.assertEqual(inferir_tribunal([], None, "70001234520237000000", None), "STM")
        self.assertEqual(inferir_tribunal(["AGINT"], None, "70001234520237000000", None), "STM")
        self.assertEqual(inferir_tribunal(["RCL"], "DF", "70001234520237000000", "cnj20"), "STM")
        # ainda não canônico (17 dígitos) também funciona
        self.assertEqual(inferir_tribunal([], None, "34110720115210009", None), "TST")
        # CNJ vence a classe: AREsp/RHC com ".6." existem no TSE
        self.assertEqual(inferir_tribunal(["ARESP"], None, "00001234520166050151", "cnj20"), "TSE")
        self.assertEqual(inferir_tribunal(["RHC"], None, "00001234520166050151", None), "TSE")

    def test_stf_e_stj_nunca_por_cnj(self):
        # J=1/3/4/8: nenhum tribunal pelo CNJ; cai na classe
        self.assertIsNone(inferir_tribunal(["RCL"], None, "00012345620191000000", "cnj20"))
        self.assertIsNone(inferir_tribunal([], None, "00012345620193000000", "cnj20"))
        self.assertEqual(inferir_tribunal(["RESP"], None, "00012345620198260100", "cnj20"), "STJ")
        self.assertIsNone(inferir_tribunal(["HC"], None, "00012345620194036100", None))


class TestRobustez(unittest.TestCase):
    def test_desempenho_em_strings_patologicas(self):
        entradas = [
            "1" * 5000, "." * 5000, "1.234." * 834, "1234567-89.2025.7.00.0000 " * 200,
            " " * 5000, "1" + " " * 5000 + "SP", "AgInt no AREsp " * 350, "REsp 1.234.567/SP, " * 250,
        ]
        funcoes = [separar_uf, corrigir_ocr_em_numero, digitos_do_identificador, numeros_do_texto,
                   cadeia_de_classes, classe_processual_canonica, chave_textual, lambda s: tolerante(s, s)]
        for s in entradas:
            for f in funcoes:
                t0 = time.perf_counter()
                f(s)
                dt = (time.perf_counter() - t0) * 1000
                self.assertLess(dt, 50, f"{getattr(f, '__name__', 'tolerante')} em {len(s)} chars: {dt:.1f} ms")

    def test_determinismo(self):
        for trecho, esperado in CASOS:
            self.assertEqual([digitos_do_identificador(trecho) for _ in range(3)], [esperado] * 3)
            self.assertEqual(cadeia_da_citacao(trecho), cadeia_da_citacao(trecho))

    def test_sem_print_no_modulo(self):
        fonte = inspect.getsource(N)
        self.assertNotIn("print(", fonte)

    def test_reexports_sao_a_mesma_implementacao(self):
        from caca_alucinacao.base_canonica import classes, digitos
        self.assertIs(digitos.separar_uf, N.separar_uf)
        self.assertIs(digitos.digitos_canonicos, N.digitos_do_identificador)
        self.assertIs(digitos.classificar_digitos, N.classificar_digitos)
        self.assertIs(digitos.nucleos, N.nucleos)
        self.assertIs(digitos.corrigir_ocr_em_grupo, N.corrigir_ocr_em_grupo)
        self.assertIs(digitos.numeros_do_texto, N.numeros_com_posicao)   # scripts esperam as posições
        self.assertIs(classes.cadeia_de_classes, N.cadeia_de_classes)
        self.assertIs(classes.classe_principal, N.classe_principal)
        self.assertIs(classes.classes_compativeis, N.classes_compativeis)
        self.assertIs(classes.uf_de_estado, N.uf_de_estado)
        self.assertIs(classes.sem_acento, N.sem_acento)
        for mod in (digitos, classes):
            fonte = inspect.getsource(mod)
            self.assertNotIn("def ", fonte, f"{mod.__name__} deve ser só re-export")

    def test_aliases_de_normativos(self):
        from caca_alucinacao.base_canonica import normativos as NV
        self.assertEqual(NV.diploma_canonico("art. 321, I, do CPC"), "CPC")
        self.assertEqual(NV.artigo_canonico("art. 3l9 do CPP"), "319")
        self.assertEqual(NV.sumula_canonica("5umula 219 do STJ"), ("STJ", False, 219))
        self.assertFalse(hasattr(N, "sumula_canonica"))   # sem aliases: normativos importa normalizacao, nunca o inverso


if __name__ == "__main__":
    unittest.main()
