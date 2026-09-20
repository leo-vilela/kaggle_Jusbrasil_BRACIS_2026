"""Testes de ``caca_alucinacao.deteccao`` (spans de citação).

Todos os números, nomes e frases são SINTÉTICOS: preservam os padrões medidos
em docs/03_analise_gabarito.md (§1 fronteiras, §2 formas, §2.6 moldes de vaga,
§3 ruído, §4 dispositivos, §5 súmulas, §6.2 distratores, §6.3 armadilhas) sem
reproduzir nenhuma citação do gabarito. Os testes com dados reais ficam sob
``skipUnless(TEM_DADOS)`` e verificam só métricas agregadas (nunca imprimem
trechos). Rodar com::

    PYTHONPATH=src python -m unittest tests.test_deteccao -v
"""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from conftest_paths import DADOS, GOLDENSET, TEM_DADOS, TXT  # noqa: E402

from caca_alucinacao.deteccao import candidatos, detectar  # noqa: E402
from caca_alucinacao.deteccao import dispositivo as DISP  # noqa: E402
from caca_alucinacao.deteccao import fusao  # noqa: E402
from caca_alucinacao.deteccao import padroes as P  # noqa: E402
from caca_alucinacao.deteccao import processo as PROC  # noqa: E402
from caca_alucinacao.deteccao import vaga as VAGA  # noqa: E402
from caca_alucinacao.texto import fim_do_cabecalho  # noqa: E402
from caca_alucinacao.tipos import Achado, iou  # noqa: E402

logging.getLogger("caca_alucinacao").setLevel(logging.ERROR)

PROSA = ("Trata-se de peça processual em que a parte examina a tese defendida na origem, "
         "conforme as razões a seguir expostas.\n")
CABECALHO = (
    "EGRÉGIO SUPERIOR TRIBUNAL DE JUSTIÇA\n"
    "\n"
    "Autos nº 1234567-89.2021.8.26.0100\n"
    "Recorrente: FULANO DE TAL\n"
    "Recorrido: BELTRANO S.A.\n"
    "Protocolo nº 2024.1234567\n"
    "Memorial nº 123/2024\n"
    "Valor da causa: R$ 123.456,78\n"
    "\n"
    "CONTRARRAZÕES AO RECURSO ESPECIAL\n"
    "\n"
)


def doc(*frases: str) -> str:
    """Documento sintético: cabeçalho + prosa + uma frase por citação."""
    return CABECALHO + PROSA + "\n".join(frases) + "\n"


def um(frase: str, esperado: str, familia: str | None = None, **dados_esperados: str) -> Achado:
    """Detecta num documento com UMA citação e confere trecho, offsets e dados."""
    t = doc(frase)
    achados = detectar(t)
    trechos = [a.trecho for a in achados]
    if len(achados) != 1:
        raise AssertionError(f"esperava 1 achado, veio {len(achados)}: {trechos!r} para {frase!r}")
    a = achados[0]
    if a.trecho != esperado:
        raise AssertionError(f"fronteira: esperado {esperado!r}, veio {a.trecho!r} [{a.origem}]")
    assert t[a.inicio:a.fim] == a.trecho
    if familia is not None and a.familia != familia:
        raise AssertionError(f"família: esperada {familia}, veio {a.familia} para {esperado!r}")
    for k, v in dados_esperados.items():
        if a.dados.get(k) != v:
            raise AssertionError(f"dados[{k}]: esperado {v!r}, veio {a.dados.get(k)!r} em {esperado!r}")
    return a


def nenhum(frase: str) -> None:
    achados = detectar(doc(frase))
    if achados:
        raise AssertionError(f"esperava nenhum achado, veio {[a.trecho for a in achados]!r} para {frase!r}")


# ===========================================================================
# processo — §2.1 classes, §2.2 conectores, §2.3 números, §2.4 UF, §2.5 TST
# ===========================================================================
class TestProcessoClasses(unittest.TestCase):
    CASOS = [
        # (frase, span esperado, cadeia canônica, classe principal, tribunal)
        ("Invoca-se, ainda, o REsp 1.234.567/SP, no ponto.", "REsp 1.234.567/SP", "RESP", "RESP", "STJ"),
        ("Assim decidiu o Recurso Especial nº 1.234.567/SP, sem divergência.", "Recurso Especial nº 1.234.567/SP", "RESP", "RESP", "STJ"),
        ("Assim decidiu o RESP 1234567/RS, sem divergência.", "RESP 1234567/RS", "RESP", "RESP", "STJ"),
        ("Assim decidiu o Rec. Esp. n. 3.456.789 (SC), sem divergência.", "Rec. Esp. n. 3.456.789 (SC)", "RESP", "RESP", "STJ"),
        ("Assim decidiu o R.Esp. n°  9.99g.999-SP, sem divergência.", "R.Esp. n°  9.99g.999-SP", "RESP", "RESP", "STJ"),
        ("Como se reconheceu na Rcl 12.345/SP, a tese não prospera.", "Rcl 12.345/SP", "RCL", "RCL", ""),
        ("Como se reconheceu na Reclamação nº 12.345/RO, a tese não prospera.", "Reclamação nº 12.345/RO", "RCL", "RCL", ""),
        ("Como se reconheceu na RCL 12345/SP, a tese não prospera.", "RCL 12345/SP", "RCL", "RCL", ""),
        ("Como se reconheceu na Recl. n° 9G.999/ SP, a tese não prospera.", "Recl. n° 9G.999/ SP", "RCL", "RCL", ""),
        ("Ampara a pretensão o AREsp 1.234.567/RJ, de idêntico teor.", "AREsp 1.234.567/RJ", "ARESP", "ARESP", "STJ"),
        ("Ampara a pretensão o Agravo em Recurso Especial nº 1.234.567/RJ, de idêntico teor.", "Agravo em Recurso Especial nº 1.234.567/RJ", "ARESP", "ARESP", "STJ"),
        ("Ampara a pretensão o ARESP\xa01234567/RS, de idêntico teor.", "ARESP\xa01234567/RS", "ARESP", "ARESP", "STJ"),
        ("Ampara a pretensão o AgREsp 1234567/PR, de idêntico teor.", "AgREsp 1234567/PR", "ARESP", "ARESP", "STJ"),
        ("Ampara a pretensão o A.REsp\n 12 345 (SP), de idêntico teor.", "A.REsp\n 12 345 (SP)", "ARESP", "ARESP", "STJ"),
        ("Veja-se o RR-999-12.2011.5.15.0099, que examinou questão idêntica.", "RR-999-12.2011.5.15.0099", "RR", "RR", "TST"),
        ("Veja-se o TST-RR-999-12.2011.5.15.0099, que examinou questão idêntica.", "TST-RR-999-12.2011.5.15.0099", "RR", "RR", "TST"),
        ("Veja-se o RHC 12.345/SP, que examinou questão idêntica.", "RHC 12.345/SP", "RHC", "RHC", "STJ"),
        ("Veja-se o Recurso em Habeas Corpus nº 12.345/SP, que examinou questão idêntica.", "Recurso em Habeas Corpus nº 12.345/SP", "RHC", "RHC", "STJ"),
        ("Veja-se o REspe nº 123-45.2016.6.05.0099, que examinou questão idêntica.", "REspe nº 123-45.2016.6.05.0099", "RESPE", "RESPE", "TSE"),
        ("Veja-se o Recurso Especial Eleitoral nº 1234-56.2019.6.06.0099, que examinou questão idêntica.", "Recurso Especial Eleitoral nº 1234-56.2019.6.06.0099", "RESPE", "RESPE", "TSE"),
        ("Veja-se o REspe. nº\xa0123-45.2016.6.05.0099, que examinou questão idêntica.", "REspe. nº\xa0123-45.2016.6.05.0099", "RESPE", "RESPE", "TSE"),
        ("Veja-se o RESPE 123-45.2016.6.05.0099, que examinou questão idêntica.", "RESPE 123-45.2016.6.05.0099", "RESPE", "RESPE", "TSE"),
        ("Cite-se a APL 7009999-12.2021.7.00.0000/RS, por todos.", "APL 7009999-12.2021.7.00.0000/RS", "APL", "APL", "STM"),
        ("Cite-se o RSE nº 7009999-12.2021.7.00.0000/DF, por todos.", "RSE nº 7009999-12.2021.7.00.0000/DF", "RSE", "RSE", "STM"),
        ("Cite-se o AgInt 7009999-12.2021.7.00.0000/DF, por todos.", "AgInt 7009999-12.2021.7.00.0000/DF", "AGINT", "AGINT", "STM"),
        ("Cite-se o AGINT 7009999-1220217000000, por todos.", "AGINT 7009999-1220217000000", "AGINT", "AGINT", "STM"),
        ("Cite-se o Ag. Int. 7009999-12 2021 7 00 0000/BA, por todos.", "Ag. Int. 7009999-12 2021 7 00 0000/BA", "AGINT", "AGINT", "STM"),
        ("Cite-se o RE 1234567/SP, por todos.", "RE 1234567/SP", "RE", "RE", "STF"),
        ("Cite-se o RE. nº\xa01.234.567-SP, por todos.", "RE. nº\xa01.234.567-SP", "RE", "RE", "STF"),
        ("Cite-se o RMS 12.345/SP, por todos.", "RMS 12.345/SP", "RMS", "RMS", ""),
        ("Cite-se o Recurso em Mandado de Segurança nº 12.345/SP, por todos.", "Recurso em Mandado de Segurança nº 12.345/SP", "RMS", "RMS", ""),
        ("Cite-se o AI 123-45.2016.6.05.0099, por todos.", "AI 123-45.2016.6.05.0099", "AI", "AI", "TSE"),
        ("Cite-se o Agravo de Instrumento nº 123-45.2016.6.05.0099, por todos.", "Agravo de Instrumento nº 123-45.2016.6.05.0099", "AI", "AI", "TSE"),
        ("Cite-se o ARR-1234-56.2011.5.02.0099, por todos.", "ARR-1234-56.2011.5.02.0099", "ARR", "ARR", "TST"),
        ("Cite-se o TST-AgARR-12345-67.2015.5.24.0099, por todos.", "TST-AgARR-12345-67.2015.5.24.0099", "AG ARR", "ARR", "TST"),
        ("Cite-se o AREspEl 0600123-45.2021.6.06.0099, por todos.", "AREspEl 0600123-45.2021.6.06.0099", "ARESPE", "ARESPE", "TSE"),
        ("Cite-se o H.C. Nº 123456 (SP), por todos.", "H.C. Nº 123456 (SP)", "HC", "HC", ""),
        ("Cite-se a AR 5.432/PR, por todos.", "AR 5.432/PR", "AR", "AR", ""),
        ("Cite-se a Suspensão de Liminar e de Sentença nº 1.234/SP, por todos.", "Suspensão de Liminar e de Sentença nº 1.234/SP", "SLS", "SLS", ""),
        ("Cite-se o R-Rp nº 999-12.2019.6.00.0000, por todos.", "R-Rp nº 999-12.2019.6.00.0000", "RRP", "RRP", "TSE"),
    ]

    def test_classes_principais(self):
        for frase, esperado, cadeia, principal, tribunal in self.CASOS:
            with self.subTest(esperado=esperado):
                a = um(frase, esperado, "processo", cadeia=cadeia, classe_principal=principal, tribunal=tribunal)
                self.assertEqual(a.tipo, "jurisprudencia")
                self.assertEqual(a.forca, 1.0)
                self.assertEqual(a.origem, "regex:processo")

    def test_prefixos_encadeados(self):
        casos = [
            ("Nesse sentido, o AgInt no REsp 1.234.567/SP, sem voto divergente.", "AgInt no REsp 1.234.567/SP", "AGINT RESP"),
            ("Nesse sentido, os EDcl nos EDcl no AgInt no AREsp 1.234.567/SP, sem voto divergente.", "EDcl nos EDcl no AgInt no AREsp 1.234.567/SP", "ED ED AGINT ARESP"),
            ("Nesse sentido, o Terceiro AG.REG na Rcl nº 12.345/SP, sem voto divergente.", "Terceiro AG.REG na Rcl nº 12.345/SP", "3O AGR RCL"),
            ("Nesse sentido, os ED no AgR no AREspEl 0600123-45.2021.6.06.0099, sem voto divergente.", "ED no AgR no AREspEl 0600123-45.2021.6.06.0099", "ED AGR ARESPE"),
            ("Nesse sentido, o TST-ED-E-ED-RR-1234-56.2011.5.02.\n0099, sem voto divergente.", "TST-ED-E-ED-RR-1234-56.2011.5.02.\n0099", "ED E ED RR"),
            ("Nesse sentido, o AgR-REspe 999-12.2016.6.05.0099, sem voto divergente.", "AgR-REspe 999-12.2016.6.05.0099", "AGR RESPE"),
            ("Nesse sentido, os EDs no AGR-RESPE\xa00600999-1220216160100, sem voto divergente.", "EDs no AGR-RESPE\xa00600999-1220216160100", "ED AGR RESPE"),
            ("Nesse sentido, o Agravo Interno na Suspensão\nde Liminar e de Sentença nº 1.234/SP, sem voto divergente.", "Agravo Interno na Suspensão\nde Liminar e de Sentença nº 1.234/SP", "AGINT SLS"),
            ("Nesse sentido, o ED no AgR-REspe No\xa00600999-1220216160100, sem voto divergente.", "ED no AgR-REspe No\xa00600999-1220216160100", "ED AGR RESPE"),
            ("Nesse sentido, o AGRAVO REGIMENTAL NA RCL\xa012.345 - SP, sem voto divergente.", "AGRAVO REGIMENTAL NA RCL\xa012.345 - SP", "AGR RCL"),
            ("Nesse sentido, o AgInt no Recurso\nEspecial nº 1.234.567/SP, sem voto divergente.", "AgInt no Recurso\nEspecial nº 1.234.567/SP", "AGINT RESP"),
            ("Nesse sentido, o Ag. em REsp n. 1234567-SP, sem voto divergente.", "Ag. em REsp n. 1234567-SP", "AG RESP"),
        ]
        for frase, esperado, cadeia in casos:
            with self.subTest(esperado=esperado):
                um(frase, esperado, "processo", cadeia=cadeia)

    def test_processo_e_tst(self):
        a = um("Confira-se o processo nº TST-E-RR-999-12.2011.5.15.0099, que dirimiu a controvérsia.",
               "processo nº TST-E-RR-999-12.2011.5.15.0099", "processo", tribunal="TST", prefixo_tst="1",
               digitos="00009991220115150099", formato="cnj20", ano="2011")
        self.assertEqual(a.dados["cadeia"], "E RR")
        um("Confira-se o Processo n° TST- ED - E-ED-RR-99999-12.2020.5.03.0099, que dirimiu a controvérsia.",
           "Processo n° TST- ED - E-ED-RR-99999-12.2020.5.03.0099", "processo", tribunal="TST")


class TestProcessoConectoresENumeros(unittest.TestCase):
    def test_conectores_e_espacamentos(self):
        for conector in ("", "nº", "n°", "Nº", "No", "n.", "n.º", "N.º", "número", "num."):
            for espaco in (" ", "  ", "\xa0", "\n", "\n "):
                if conector == "" and espaco == "":
                    continue
                cit = f"REsp{(' ' + conector) if conector else ''}{espaco}1.234.567/SP"
                with self.subTest(cit=cit):
                    um(f"Invoca-se o {cit}, no ponto.", cit, "processo", digitos="1234567")

    def test_formatos_de_numero(self):
        casos = [
            ("APL 7009999-12.2021.7.00.0000/RS", "70099991220217000000", "cnj20"),
            ("REspe 12-34.2011.6.05.0099", "00000123420116050099", "cnj20"),
            ("RR-999-12.2011.5.01.0099", "00009991220115010099", "cnj20"),
            ("APL 0609999-12.2021.7.00.0000/SP", "06099991220217000000", "cnj20"),
            ("APL 0609999-1220217000000", "06099991220217000000", "cnj20"),
            ("APL 7009999-12 2021 7 00 0000", "70099991220217000000", "cnj20"),
            ("APL 7009999-12.2021.7.00.\n0000/SP", "70099991220217000000", "cnj20"),
            ("REspe 0600457-13.2020-\n.6.14.0022", "06004571320206140022", "cnj20"),
            ("APL 7009999--\n12.2021.7.00.0000/SP", "70099991220217000000", "cnj20"),
            ("REspe 12-34. 2011.6.05.0099", "00000123420116050099", "cnj20"),
            ("REsp 1.234.567/SP", "1234567", "curto"),
            ("REsp 1234567/SP", "1234567", "curto"),
            ("REsp 1 234 567/SP", "1234567", "curto"),
            ("REsp 1. 234.567/SP", "1234567", "curto"),
            ("Rcl 11.-\n222/SP", "11222", "curto"),
            ("REsp 2.111-\n.222/SP", "2111222", "curto"),
            ("Rcl 11-\n.222/SP", "11222", "curto"),
            ("REsp 21999l1/SP", "2199911", "curto"),
            ("REsp 199999O/SP", "1999990", "curto"),
            ("REsp 1.99g.999/SP", "1999999", "curto"),
            ("REsp 1.999.9S9/SP", "1999959", "curto"),
            ("Rcl 9G.999/SP", "96999", "curto"),
            ("REsp 1 o99 999-MA", "1099999", "curto"),
            ("RR n.\xa024290-50 2016 S 00 0000", "00242905020165000000", "cnj20"),
            ("AREsp nº 2019/0123456-7", "201901234567", "registro"),
            ("AR 544G - PR", "5446", "curto"),
        ]
        for cit, digitos, formato in casos:
            with self.subTest(cit=cit):
                a = um(f"Invoca-se o {cit}, no ponto.", cit, "processo", digitos=digitos, formato=formato)
                self.assertTrue(cit.endswith(a.dados["numero"]) or a.dados["numero"] in cit)

    def test_separadores_de_uf(self):
        for sep_antes, sep_depois in (("/", ""), ("/ ", ""), ("-", ""), (" - ", ""), (" – ", ""), (" (", ")"),
                                      ("\n- ", ""), (" / ", ""), ("–", ""), (" — ", ""), ("(", ")"),
                                      (" /", ""), ("/\n", ""), (" ", "")):
            cit = f"REsp 1.234.567{sep_antes}SP{sep_depois}"
            with self.subTest(cit=repr(cit)):
                um(f"Invoca-se o {cit}, no ponto.", cit, "processo", uf="SP", digitos="1234567")

    def test_sem_uf(self):
        a = um("Invoca-se o REsp 1.234.567, no ponto.", "REsp 1.234.567", "processo", uf="")
        self.assertEqual(a.dados["digitos"], "1234567")

    def test_uf_nunca_e_engolida_pelo_numero(self):
        # "S" de SP não pode virar 5: grupo depois de espaço/hífen precisa de dígito
        for cit in ("RESP 1234567 - SP", "RESP 1234567 -SP", "Rcl 12.345\n- SP", "REsp 1.234.567 – SP"):
            a = um(f"Invoca-se o {cit}, no ponto.", cit, "processo", uf="SP")
            self.assertIn(a.dados["digitos"], ("1234567", "12345"))
            self.assertNotIn("S", a.dados["numero"])

    def test_uf_seguida_de_letra_nao_e_uf(self):
        a = um("Invoca-se o REsp 1.234.567/SPA, no ponto.", "REsp 1.234.567", "processo", uf="")
        self.assertEqual(a.dados["uf"], "")


class TestProcessoNegativos(unittest.TestCase):
    def test_sigla_de_duas_letras_com_ano_nao_e_processo(self):
        nenhum("A AR 2019 foi julgada em sessão.")
        nenhum("O RE 2020 foi um ano difícil para a Corte.")

    def test_numero_curto_demais(self):
        nenhum("O REsp 12 não existe.")
        nenhum("O HC 123 tampouco.")

    def test_data_apos_numero_nao_entra(self):
        a = um("Cite-se a APL 7009999-12.2021.7.00.0000 12/03/2022, por todos.",
               "APL 7009999-12.2021.7.00.0000", "processo")
        self.assertEqual(a.dados["digitos"], "70099991220217000000")

    def test_fronteiras_artigo_anterior_e_pontuacao(self):
        for frase, esperado in (
            ("Invoca-se, ainda, o REsp 1.234.567/SP, no ponto.", "REsp 1.234.567/SP"),
            ("Invoca-se, ainda, a Rcl 12.345/SP.", "Rcl 12.345/SP"),
            ("Invoca-se, ainda, no AgInt no AREsp 1.234.567/SP foi decidido.", "AgInt no AREsp 1.234.567/SP"),
            ("Invoca-se, ainda, o\nREsp 1.234.567/SP\npara tanto.", "REsp 1.234.567/SP"),
        ):
            with self.subTest(esperado=esperado):
                um(frase, esperado, "processo")


class TestProcessoAmplo(unittest.TestCase):
    def test_sigla_desconhecida(self):
        a = um("Cite-se o RvCr 1234/SP, por todos.", "RvCr 1234/SP", "processo")
        self.assertEqual(a.origem, "regex:processo:amplo")
        self.assertEqual(a.forca, 0.5)
        self.assertEqual(a.dados["uf"], "SP")
        a = um("Cite-se o ROMS nº 12.345/SP, por todos.", "ROMS nº 12.345/SP", "processo")
        self.assertEqual(a.forca, 0.5)

    def test_processo_ou_autos_no_corpo(self):
        a = um("Consta do Processo nº 1234567-89.2020.8.26.0100 que a parte recorreu.",
               "Processo nº 1234567-89.2020.8.26.0100", "processo")
        self.assertEqual(a.origem, "regex:processo:amplo")
        self.assertEqual(a.forca, 0.5)

    def test_amplo_nao_dispara_em_siglas_conhecidas_de_outra_natureza(self):
        nenhum("O advogado (OAB/SP 123456) juntou o CNPJ 12.345.678/0001-90.")
        nenhum("A Portaria nº 1234/2020 e o ITEM 1234 e o DJe 12345 não são processos.")
        nenhum("Os honorários foram fixados em 10% sobre R$ 1.234,56 às fls. 123/125.")
        nenhum("O contrato foi assinado em 12 de março de 2024 e a MG 123456 não é nada.")

    def test_prefixo_conhecido_com_sigla_desconhecida(self):
        a = um("Cite-se o AgRg no ROMS 12.345/SP, por todos.", "AgRg no ROMS 12.345/SP", "processo")
        self.assertEqual(a.forca, 0.5)


# ===========================================================================
# vaga — §2.6 moldes A–E (e F–H), com e sem quebra de linha
# ===========================================================================
class TestVaga(unittest.TestCase):
    MOLDES = [
        ("A", "julgado do STF proferido em 2024 pela relatoria de Fulano de Tal", "STF", "2024", "Fulano de Tal"),
        ("B", "precedente do STJ de 2021, da relatoria de Beltrano Silva", "STJ", "2021", "Beltrano Silva"),
        ("C", "Reclamação do STF, de 2023, Rel. Min. FULANA DE TAL", "STF", "2023", "FULANA DE TAL"),
        ("C", "Agravo em Recurso Especial do STJ, de 2020, Rel. Min. Sicrano Souza Lima", "STJ", "2020", "Sicrano Souza Lima"),
        ("D", "Rcl de 2021, Rel. Min. Fulana Tal", "", "2021", "Fulana Tal"),
        ("D", "APL de 2023, Rel. Min. LEONILDO EXEMPLAR", "STM", "2023", "LEONILDO EXEMPLAR"),
        ("E", "acórdão do TSE julgado em 2022 sob relatoria de Beltrano de Souza Lima", "TSE", "2022", "Beltrano de Souza Lima"),
        ("F", "decisão do STJ de 2021, relatada pelo Min. Fulano Tal", "STJ", "2021", "Fulano Tal"),
        ("G", "aresto do TSE, 2019, Relator Ministro Beltrano Silva", "TSE", "2019", "Beltrano Silva"),
        ("H", "julgado do STF, 2023, Rel. Min. Fulana de Tal", "STF", "2023", "Fulana de Tal"),
    ]

    def test_moldes_sem_quebra(self):
        for molde, cit, trib, ano, relator in self.MOLDES:
            with self.subTest(molde=molde):
                a = um(f"Invoca-se, ainda, o {cit}, no ponto em que afasta a exigência.", cit, "vaga",
                       tribunal=trib, ano=ano, relator=relator)
                self.assertEqual(a.origem, f"regex:vaga:{molde}")
                self.assertEqual(a.forca, 1.0)
                self.assertEqual(a.dados["numero"], "")

    def test_moldes_com_quebra(self):
        for molde, cit, trib, ano, relator in self.MOLDES:
            palavras = cit.split(" ")
            # quebra antes do nome (última palavra) e no meio da frase
            for k in (1, len(palavras) - 1, len(palavras) // 2):
                quebrado = " ".join(palavras[:k]) + "\n" + " ".join(palavras[k:])
                with self.subTest(molde=molde, k=k):
                    um(f"Invoca-se, ainda, o {quebrado}, no ponto em que afasta a exigência.", quebrado, "vaga",
                       tribunal=trib, ano=ano, relator=relator)

    def test_variacoes_de_ocr_e_espaco(self):
        casos = [
            "julgado do STF proferldo em 2024 pela relatoria dc Fulano de Tal",
            "julgãdo do STJ proferido em 2024 pela rclatoria de Fulano Tal",
            "preeedente do STF de 2022, da relatoria de ROSA EXEMPLO",
            "aeórdão do TSE julgado em 2021 sob relatoria de Sicrano Tal",
            "Reclamação\ndo STF, de 2023, Rel.  Min. FULANA DE TAL",
            "Rcl de 2021, Rel.\nMin. Fulana Tal",
            "APL de 2023, Rel. Min.\nLEONILDO EXEMPLAR",
            "julgado do STM proferido em 2023\npela relatoria de CARLINDO EXEMPLAR AMARILDO SILVEIRA",
            "precedente do STF de 2021, da relatoria de Fulano\nTal",
            "acórdão do STJ julgado em 2022 sob relatoria de FULANO TAL\nDE SOUZA",
        ]
        for cit in casos:
            with self.subTest(cit=cit):
                a = um(f"Invoca-se, ainda, o {cit}, no ponto.", cit, "vaga")
                self.assertEqual(a.forca, 1.0)

    def test_nome_termina_antes_de_minuscula_ponto_ou_virgula(self):
        cit = "julgado do STF proferido em 2024 pela relatoria de Fulano de Tal"
        for depois in (", no ponto.", ".", " para tanto.", "\npara tanto.", " foi decisivo."):
            with self.subTest(depois=repr(depois)):
                um(f"Invoca-se o {cit}{depois}", cit, "vaga", relator="Fulano de Tal")
        um("Confira-se o julgado do STF, 2023, Rel. Min. Rosa Exemplo, DJe 12/03/2023.",
           "julgado do STF, 2023, Rel. Min. Rosa Exemplo", "vaga")

    def test_nomes_de_2_a_4_palavras(self):
        for nome in ("Fulano Tal", "Fulano de Tal", "Fulano Beltrano Tal", "FULANO BELTRANO DA SILVA"):
            cit = f"precedente do STJ de 2021, da relatoria de {nome}"
            um(f"Invoca-se o {cit}, no ponto.", cit, "vaga", relator=nome)

    def test_classe_com_ano_nao_e_processo(self):
        a = um("Invoca-se a Reclamação do STF, de 2023, Rel. Min. Fulana de Tal, para tanto.",
               "Reclamação do STF, de 2023, Rel. Min. Fulana de Tal", "vaga")
        self.assertEqual(a.dados["cadeia"], "RCL")
        self.assertEqual(a.dados["classe_principal"], "RCL")
        self.assertEqual(a.dados["digitos"], "")

    def test_frases_armadilha_nao_disparam(self):
        for frase in (
            "A orientação dos tribunais superiores é firme no ponto.",
            "O dispositivo constitucional invocado na origem não socorre a parte.",
            "A jurisprudência pacífica desta Corte afasta a pretensão.",
            "O verbete sumular aplicável à espécie confirma essa leitura.",
            "A lei que disciplina a prescrição no caso é clara.",
            "O entendimento sumulado sobre a matéria é de aplicação obrigatória.",
            "As normas de regência da matéria foram corretamente aplicadas.",
            "A jurisprudência consolidada dos tribunais superiores aponta na mesma direção.",
            "A orientação firmada pelo STF em 2021 permanece íntegra.",
            "Como anotou o Ministro relator em seu voto, a tese não prospera.",
            "O Superior Tribunal de Justiça, em 2019, consolidou a orientação contrária.",
            "Ainda em 2020, o STJ reafirmou a jurisprudência então dominante.",
            "O precedente firmado em sede de recurso repetitivo é vinculante.",
        ):
            with self.subTest(frase=frase):
                nenhum(frase)

    def test_amplo(self):
        a = um("Invoca-se o julgado do STF, publicado em 2021, da relatoria de Fulano de Tal, no ponto.",
               "julgado do STF, publicado em 2021, da relatoria de Fulano de Tal", "vaga",
               tribunal="STF", ano="2021", relator="Fulano de Tal")
        self.assertEqual(a.origem, "regex:vaga:amplo")
        self.assertEqual(a.forca, 0.6)
        a = um("Invoca-se a decisão do Superior Tribunal de Justiça, em 2019, pela relatoria do Ministro Og Exemplo, no ponto.",
               "decisão do Superior Tribunal de Justiça, em 2019, pela relatoria do Ministro Og Exemplo", "vaga",
               tribunal="STJ")

    def test_cauda_de_citacao_com_numero_nao_vira_vaga(self):
        t = doc("Nesse sentido: AgRg no RE 1234567/SP, 2ª Turma, STF, j. 2021, Rel. Min. Rosa Exemplo, DJe 12/03/2021.")
        achados = detectar(t)
        self.assertEqual([a.trecho for a in achados], ["AgRg no RE 1234567/SP"])


# ===========================================================================
# dispositivo — §4
# ===========================================================================
class TestDispositivo(unittest.TestCase):
    CASOS = [
        ("art. 321, I, do CPC", "321", "CPC"),
        ("art. 8º, LV, da Constituição Federal", "8", "CF"),
        ("art. 97, IX, da Constituição da República", "97", "CF"),
        ("art. 240 da Constituição Fcderal", "240", "CF"),
        ("artigo 97, IX, da Constituição\nda República", "97", "CF"),
        ("art 468 da CLT", "468", "CLT"),
        ("art. 899, § 1º-A, da CLT", "899", "CLT"),
        ("art. 791 da Consolidação das Leis do Trabalho", "791", "CLT"),
        ("art. 12 do Código de Defesa do Consumidor", "12", "CDC"),
        ("art. 1.115 do Código de Processo Civil", "1115", "CPC"),
        ("art. 321 da Lei nº 13.105/2015", "321", "CPC"),
        ("art. 321 da Lei nº\n13.105/2015", "321", "CPC"),
        ("art. 224 do Código Eleitoral", "224", "CE"),
        ("art. 22, I, 'g', da Lei Complementar nº 64/1990", "22", "LC64"),
        ("art. 240 do Código Penal Militar", "240", "CPM"),
        ("art.\n319 do Código de Processo Penal", "319", "CPP"),
        ("art. 187 do Código Civil", "187", "CC"),
        ("art. 175 da Lei nº 9.504/1997", "175", "LEI-9504"),
        ("art 55 da Lei nº 13.467/2017", "55", "LEI-13467"),
        ("artigo 9º, XXIX, da Constituição Federal", "9", "CF"),
        ("Art. 14 da\nCLT", "14", "CLT"),
        ("art 319 do CPC/2015", "319", "CPC"),
        ("art.º 99 do Código de Defesa do Consumidor", "99", "CDC"),
        ("art 999 do Decreto-Lei nº 5.452/1943", "999", "CLT"),
        ("art. 81 da Lei Complemcntar\nnº 64/1990", "81", "LC64"),
        ("art. 8º da CF/88", "8", "CF"),
        ("art. 121 do Código Penal", "121", "CP"),
        ("art. 10 da Lei nº 8.429/1992", "10", "LEI-8429"),
        ("art. 3l9 do Código de Processo Penal", "319", "CPP"),
        ("art. 1.026, § 2º, do Código de Processo Civil", "1026", "CPC"),
        ("arts. 8º e 9º da Constituição Federal", "8", "CF"),
        ("art. 321 da Lei nº 13.105, de 16 de março de 2015", "321", "CPC"),
        ("art. 8o, I, da Constituição Federal", "8", "CF"),
        ("art. 3º, I e II, da Lei nº 9.504/1997", "3", "LEI-9504"),
        ("art. 37, caput, da Constituição Federal", "37", "CF"),
        ("art. 8º, inciso II, da Constituição Federal", "8", "CF"),
    ]

    def test_casos(self):
        for cit, artigo, diploma in self.CASOS:
            with self.subTest(cit=cit):
                a = um(f"Aplica-se à espécie o {cit}, como reconhecido nas instâncias ordinárias.", cit,
                       "dispositivo", artigo=artigo, diploma=diploma)
                self.assertEqual(a.tipo, "lei")
                self.assertEqual(a.forca, 1.0)

    def test_pontuacao_final_fora(self):
        um("Viola o art. 321, I, do CPC.", "art. 321, I, do CPC", "dispositivo")
        um("Viola o art. 11 da Constituição Federal, sem dúvida.", "art. 11 da Constituição Federal", "dispositivo")

    def test_amplo_sem_diploma(self):
        a = um("Nos termos do art. 5º, a parte tem razão.", "art. 5º", "dispositivo", artigo="5", diploma="")
        self.assertEqual(a.origem, "regex:dispositivo:amplo")
        self.assertEqual(a.forca, 0.4)

    def test_lei_sem_artigo_nao_e_span(self):
        nenhum("A Lei nº 8.429/1992 disciplina a matéria.")

    def test_diploma_canonico_da_superficie(self):
        self.assertEqual(DISP.diploma_canonico_da_superficie("Código de Processo Penal Militar"), "CPPM")
        self.assertEqual(DISP.diploma_canonico_da_superficie("Resolução nº 23.610/2019"), "OUTRO")
        self.assertEqual(DISP.diploma_canonico_da_superficie("Lei nº 9.504/1997"), "LEI-9504")


# ===========================================================================
# súmula e tema — §5
# ===========================================================================
class TestSumulaETema(unittest.TestCase):
    def test_sumulas(self):
        casos = [
            ("Súmula 77 do STJ", "77", "STJ", "0"),
            ("Súmula 456 do TST", "456", "TST", "0"),
            ("Súmula 999 do STF", "999", "STF", "0"),
            ("Súmula Vinculante 45", "45", "", "1"),
            ("Súmula Vinculante 199", "199", "", "1"),
            ("5umula 219 do STJ", "219", "STJ", "0"),
            ("SÚMULA 123 do STJ", "123", "STJ", "0"),
            ("Súm. 49 do TSE", "49", "TSE", "0"),
            ("Súmula 999\ndo STF", "999", "STF", "0"),
            ("Súmula 999 do\nSTF", "999", "STF", "0"),
            ("Sumula 7 do STJ", "7", "STJ", "0"),
            ("Súmula nº 7 do STJ", "7", "STJ", "0"),
            ("Súmula n. 123\ndo STJ", "123", "STJ", "0"),
            ("Enunciado nº 456 do TST", "456", "TST", "0"),
            ("Súmula nº Vinculante 45", "45", "", "1"),
            ("Súmula 7/STJ", "7", "STJ", "0"),
            ("Súmula 7", "7", "", "0"),
        ]
        for cit, numero, trib, vinc in casos:
            with self.subTest(cit=cit):
                a = um(f"Ampara a pretensão a {cit}, de observância obrigatória.", cit, "sumula",
                       numero_sumula=numero, tribunal=trib, vinculante=vinc)
                self.assertEqual(a.tipo, "jurisprudencia")

    def test_sumula_sem_numero_nao_dispara(self):
        nenhum("A Súmula do STJ aplicável à espécie confirma essa leitura.")

    def test_tema(self):
        a = um("Basta conferir o Tema 1.234 da repercussão geral para constatar.", "Tema 1.234 da repercussão geral",
               "tema", numero_tema="1234", tribunal="STF")
        self.assertEqual(a.forca, 1.0)
        um("Basta conferir o Tcma 2.345 da repercussão geral para constatar.", "Tcma 2.345 da repercussão geral", "tema")
        # sem complemento: força 0,7 só com indício jurisprudencial na mesma frase (rodada 4, R6-16);
        # sem indício (``Tema 1.234 para constatar``) 0,4 — a resolução descarta
        a = um("Basta conferir o Tema 1.234, afetado pelo STF, para constatar.", "Tema 1.234", "tema")
        self.assertEqual(a.forca, 0.7)
        a = um("Basta conferir o Tema 1.234 para constatar.", "Tema 1.234", "tema")
        self.assertEqual(a.forca, 0.4)


# ===========================================================================
# distratores — §6.2 e cabeçalho — §6.1
# ===========================================================================
class TestDistratores(unittest.TestCase):
    def test_cabecalho_inteiro_e_zona_proibida(self):
        t = doc("Nada a citar aqui.")
        self.assertEqual(detectar(t), [])
        # os números do cabeçalho existem, mas ficam antes de fim_do_cabecalho
        self.assertGreater(fim_do_cabecalho(t), t.index("123.456,78"))

    def test_distratores_do_corpo(self):
        for frase in (
            "O advogado (OAB/MG 123456) apresentou contrarrazões.",
            "Os documentos de fls. 123/125 comprovam o pagamento.",
            "A sentença fixou honorários em 15% sobre a condenação.",
            "A relação teve início em 12 de março de 2024, mediante instrumento particular.",
            "O dano moral foi arbitrado em R$ 12.345,67, valor proporcional.",
            "A questão foi debatida em Salvador e a C0NTROVÉRSIA persiste, conforme DO5 autos.",
            "O Protocolo nº 2024.1234567 e o Memorial nº 123/2024 foram juntados.",
            "O PARECER JURÍDICO Nº 123/2024 opinou pela improcedência.",
            "Referência: autos nº 1234567-89.2021.8.26.0100 (linha de cabeçalho no corpo).",
        ):
            with self.subTest(frase=frase):
                nenhum(frase)

    def test_cnj_do_cabecalho_nao_e_citacao_mesmo_com_j_de_tribunal_superior(self):
        t = CABECALHO.replace("8.26.0100", "5.02.0100") + PROSA + "Nada a citar.\n"
        self.assertEqual(detectar(t), [])


# ===========================================================================
# propriedades: sobreposição, determinismo, desempenho
# ===========================================================================
class TestPropriedades(unittest.TestCase):
    TEXTO = doc(
        "Invoca-se, ainda, o julgado do STF proferido em 2024 pela relatoria de Fulano de Tal, no ponto.",
        "Como já se reconheceu no AgInt no AREsp nº 1.234.567/SP, a tese não prospera.",
        "Aplica-se o art. 321, I, do CPC, como reconhecido.",
        "Ampara a pretensão a Súmula 7 do STJ, bem como o Tema 1.234 da repercussão geral.",
        "Veja-se a Reclamação do STF, de 2023, Rel. Min. FULANA DE TAL, para tanto.",
        "Também o processo nº TST-E-RR-999-12.2011.5.15.0099 e a Rcl 12.345/RO foram citados às fls. 12/13.",
        "Cite-se o RvCr 1234/SP e o art. 5º, bem como a APL de 2023, Rel. Min. LEONILDO EXEMPLAR.",
    )

    def test_ordenado_e_sem_sobreposicao(self):
        achados = detectar(self.TEXTO)
        self.assertGreaterEqual(len(achados), 10)
        self.assertEqual(achados, sorted(achados, key=lambda a: (a.inicio, a.fim)))
        self.assertTrue(fusao.sem_sobreposicao(achados))
        for i, a in enumerate(achados):
            self.assertEqual(self.TEXTO[a.inicio:a.fim], a.trecho)
            for b in achados[i + 1:]:
                self.assertLess(iou(a.inicio, a.fim, b.inicio, b.fim), 0.5)

    def test_fusao_mantem_o_maior_span(self):
        a = Achado(10, 20, "x" * 10, "processo", "jurisprudencia", {}, "regex:processo", 1.0)
        b = Achado(13, 20, "x" * 7, "processo", "jurisprudencia", {}, "regex:processo", 1.0)
        c = Achado(30, 40, "y" * 10, "vaga", "jurisprudencia", {}, "regex:vaga:amplo", 0.6)
        d = Achado(35, 42, "z" * 7, "sumula", "jurisprudencia", {}, "regex:sumula", 1.0)
        self.assertEqual(fusao.fundir([b, a, c, d]), [a, d])

    def test_todas_as_chaves_de_dados(self):
        chaves = {"classe", "cadeia", "classe_principal", "numero", "digitos", "formato", "uf", "tribunal",
                  "ano", "relator", "artigo", "diploma", "numero_sumula", "vinculante", "numero_tema"}
        for a in detectar(self.TEXTO):
            self.assertTrue(chaves <= set(a.dados), (a.familia, set(a.dados)))
            self.assertTrue(all(isinstance(v, str) for v in a.dados.values()))

    def test_determinismo(self):
        r1 = detectar(self.TEXTO)
        r2 = detectar(self.TEXTO)
        self.assertEqual([(a.inicio, a.fim, a.familia, a.origem, a.dados) for a in r1],
                         [(a.inicio, a.fim, a.familia, a.origem, a.dados) for a in r2])

    def test_texto_vazio_e_sem_citacoes(self):
        self.assertEqual(detectar(""), [])
        self.assertEqual(detectar(PROSA), [])

    def test_candidatos_inclui_amplos_descartados(self):
        self.assertGreaterEqual(len(candidatos(self.TEXTO)), len(detectar(self.TEXTO)))

    def test_tempo_por_documento(self):
        texto = (self.TEXTO * 3)[:4000]
        detectar(texto)  # aquecimento
        t0 = time.perf_counter()
        for _ in range(5):
            detectar(texto)
        dt = (time.perf_counter() - t0) / 5
        # limite folgado (×10 do medido) para não depender do relógio da máquina (R4-08)
        self.assertLess(dt, 1.0, f"{dt * 1000:.1f} ms por documento de 4.000 chars")

    def test_sem_retrocesso_catastrofico(self):
        patologicos = [
            "REsp " + "1." * 10000,
            "REsp " + "1" * 20000 + "/SP",
            "AgInt no AREsp nº " + "1.-\n" * 5000 + "2",
            "APL " + "7009999-12 " * 2000,
            "art. " + "1." * 10000 + " do CPC",
            "Súmula " + "9" * 20000,
            "julgado do STF proferido em 2024 pela relatoria de " + "Fulano " * 3000,
            "Rcl " + "12.345 " * 3000 + "/SP",
            "\xa0" * 20000 + "REsp 1.234.567/SP",
            "TST-" + "ED-" * 6000 + "RR-999-12.2011.5.15.0099",
        ]
        for texto in patologicos:
            with self.subTest(texto=texto[:20]):
                t0 = time.perf_counter()
                detectar(PROSA + texto)
                self.assertLess(time.perf_counter() - t0, 10.0)  # retrocesso catastrófico levaria minutos

    def test_regex_compilados_uma_vez(self):
        self.assertIsInstance(PROC.RE_PROCESSO, re.Pattern)
        self.assertIsInstance(VAGA.RE_VAGA, re.Pattern)
        self.assertIsInstance(DISP.RE_DISPOSITIVO, re.Pattern)
        self.assertIsInstance(P.regex_sigla("AgInt"), str)


# ===========================================================================
# dados reais (metas de docs/03) — sem imprimir trechos
# ===========================================================================
def _carregar_medidor():
    caminho = RAIZ / "scripts" / "analise" / "medir_deteccao.py"
    spec = importlib.util.spec_from_file_location("medir_deteccao", caminho)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(TEM_DADOS, "dados do desafio ausentes")
class TestDadosReais(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.medidor = _carregar_medidor()
        cls.m = cls.medidor.medir(TXT, GOLDENSET, DADOS / "catalogo_gabarito.json", 0, False)

    def test_metas_do_dev(self):
        m = self.m
        self.assertEqual(m["citacoes"], 192)
        self.assertEqual(m["casados"], 192, m["perdidos_por_familia"])
        self.assertEqual(m["espurios"], 0, m["espurios_por_origem"])
        self.assertEqual(m["fronteira_exata"], 192)   # ADR 0005: 192/192 (sem folga; R4-08)
        self.assertEqual(m["tipo_ok"], 192)
        self.assertEqual(m["familia_ok"], 192)
        self.assertEqual(m["cabecalho_ok"], 26)
        self.assertLess(m["tempo_medio_ms"], 1000)

    def test_sem_sobreposicao_nos_26_documentos(self):
        for p in sorted(TXT.glob("*.txt")):
            achados = detectar(p.read_bytes().decode("utf-8"))
            self.assertTrue(fusao.sem_sobreposicao(achados), p.stem)


_N2_DEV = DADOS / "sinteticos" / "n2_dev"
_N3_OOD = DADOS / "sinteticos" / "n3_ood"


@unittest.skipUnless((_N2_DEV / "goldenset.csv").exists(), "sintéticos n2_dev ausentes")
class TestSinteticosN2(unittest.TestCase):
    def test_recall_e_precisao(self):
        m = _carregar_medidor().medir(_N2_DEV / "txt", _N2_DEV / "goldenset_estendido.csv", None, 0, False)
        self.assertGreaterEqual(m["recall"], 0.99, m["perdidos_por_ruido"])
        self.assertGreaterEqual(m["precisao"], 0.99, m["espurios_por_origem"])


@unittest.skipUnless((_N3_OOD / "goldenset.csv").exists(), "sintéticos n3_ood ausentes")
class TestSinteticosN3(unittest.TestCase):
    def test_recall_e_precisao(self):
        m = _carregar_medidor().medir(_N3_OOD / "txt", _N3_OOD / "goldenset_estendido.csv", None, 0, False)
        self.assertGreaterEqual(m["recall"], 0.95, m["perdidos_por_ruido"])
        self.assertGreaterEqual(m["precisao"], 0.99, m["espurios_por_origem"])


if __name__ == "__main__":
    unittest.main()
