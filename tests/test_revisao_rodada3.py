"""Testes das correções da revisão (rodada 3) — um bloco por achado, todos sintéticos.

Cada classe cita o(s) achado(s) que cobre: R5-xx (correção = revisor 1), R3-xx (generalização =
revisor 2) e R3e-xx (engenharia = revisor 3). Base canônica FALSA (``tests/test_resolucao.INDICE_FALSO``);
nenhum número, nome ou trecho do gabarito ou da base real (números de súmula/artigo são os da base
falsa: 123/456/45, 321/11/240, ou números inexistentes como 999).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from test_resolucao import INDICE_FALSO, _reg  # noqa: E402

from caca_alucinacao import calibracao as cal  # noqa: E402
from caca_alucinacao import texto as T  # noqa: E402
from caca_alucinacao.base_canonica import BaseCanonica  # noqa: E402
from caca_alucinacao.deteccao import detectar  # noqa: E402
from caca_alucinacao.deteccao import padroes as P  # noqa: E402
from caca_alucinacao.resolucao import resolver  # noqa: E402
from caca_alucinacao.tipos import Achado, Decisao  # noqa: E402

PROSA = ("Trata-se de peça processual em que a parte examina a tese defendida na origem, "
         "conforme as razões a seguir expostas.\n")
CABECALHO = "EGRÉGIO TRIBUNAL\n\nAutos nº 1234567-89.2021.8.26.0100\nRecorrente: FULANO\n\nMEMORIAL\n\n"


def doc(*frases: str) -> str:
    return CABECALHO + PROSA + "\n".join(frases) + "\n"


def todos(frase: str) -> list[Achado]:
    return detectar(doc(frase))


def um(frase: str) -> Achado:
    achados = todos(frase)
    assert len(achados) == 1, [a.trecho for a in achados]
    return achados[0]


def nenhum(frase: str) -> None:
    achados = todos(frase)
    assert achados == [], [a.trecho for a in achados]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = BaseCanonica(INDICE_FALSO)

    def ponta_a_ponta(self, frase: str) -> tuple[Achado, Decisao]:
        a = um(frase)
        return a, resolver(a, self.base)


# ---------------------------------------------------------------------------
# R5-01 / R3-05 — citação vaga com o relator ANTES do ano (sem parênteses) e redações novas
# ---------------------------------------------------------------------------
class TestVagaRelatorAntesDoAno(unittest.TestCase):
    CASOS = [
        # (frase, span, tribunal, ano, relator, molde)
        ("Invoca-se o acórdão do STJ, Rel. Min. Fulano Beltrano, j. 2021, como se vê.",
         "acórdão do STJ, Rel. Min. Fulano Beltrano, j. 2021", "STJ", "2021", "Fulano Beltrano", "relator_antes_ano_virgula"),
        ("Ver o julgado do TST, Rel. Min. Fulano Beltrano, de 2021, que tudo.",
         "julgado do TST, Rel. Min. Fulano Beltrano, de 2021", "TST", "2021", "Fulano Beltrano", "relator_antes_ano_virgula"),
        ("O precedente do STF, Rel. Min. Fulano Beltrano, julgado em 2021, nada.",
         "precedente do STF, Rel. Min. Fulano Beltrano, julgado em 2021", "STF", "2021", "Fulano Beltrano", "relator_antes_ano_virgula"),
        ("A decisão do STM, Relator Ministro Fulano Beltrano, 2021, nada.",
         "decisão do STM, Relator Ministro Fulano Beltrano, 2021", "STM", "2021", "Fulano Beltrano", "relator_antes_ano_virgula"),
        ("O acórdão do Superior Tribunal de Justiça, Rel. Min. Fulano Beltrano, DJe 2021, nada.",
         "acórdão do Superior Tribunal de Justiça, Rel. Min. Fulano Beltrano, DJe 2021", "STJ", "2021", "Fulano Beltrano", "relator_antes_ano_virgula"),
        ("O precedente do TSE, da relatoria do Ministro Fulano Beltrano, de 2021, nada.",
         "precedente do TSE, da relatoria do Ministro Fulano Beltrano, de 2021", "TSE", "2021", "Fulano Beltrano", "relator_antes_ano_virgula"),
        ("O acórdão do STJ, Rel. Min. Fulano Beltrano, j. 12/03/2021, nada.",
         "acórdão do STJ, Rel. Min. Fulano Beltrano, j. 12/03/2021", "STJ", "2021", "Fulano Beltrano", "relator_antes_ano_virgula"),
        # R3-05: da lavra do, (Min. X), Rel. p/ acórdão, Redator, tribunal primeiro, coube ao, lavra + tribunal + ano
        ("Nesse sentido é o julgado do STF, de 2024, da lavra do Ministro Fulano Beltrano, que enfrentou.",
         "julgado do STF, de 2024, da lavra do Ministro Fulano Beltrano", "STF", "2024", "Fulano Beltrano", "H"),
        ("Ver o julgado do STJ, de 2021, da lavra do\nMinistro\xa0Fulano Beltrano, que.",
         "julgado do STJ, de 2021, da lavra do\nMinistro\xa0Fulano Beltrano", "STJ", "2021", "Fulano Beltrano", "H"),
        ("Ver a decisão do STJ de 2023 (Min. Fulano Beltrano) e mais.",
         "decisão do STJ de 2023 (Min. Fulano Beltrano)", "STJ", "2023", "Fulano Beltrano", "min_sem_rel"),
        ("Ver a decisão do STJ de 2023 (Ministro Fulano Beltrano), e mais.",
         "decisão do STJ de 2023 (Ministro Fulano Beltrano)", "STJ", "2023", "Fulano Beltrano", "min_sem_rel"),
        ("Ver o julgado do STF de 2024, Rel. p/ acórdão Min. Fulano Beltrano, que.",
         "julgado do STF de 2024, Rel. p/ acórdão Min. Fulano Beltrano", "STF", "2024", "Fulano Beltrano", "H"),
        ("O acórdão do STF de 2019, Redator Ministro Fulano Beltrano, que.",
         "acórdão do STF de 2019, Redator Ministro Fulano Beltrano", "STF", "2019", "Fulano Beltrano", "E"),
        ("Ver STF, 2024, Rel. Min. Fulano Beltrano, que.",
         "STF, 2024, Rel. Min. Fulano Beltrano", "STF", "2024", "Fulano Beltrano", "tribunal_primeiro"),
        ("Ver o Supremo Tribunal Federal, julgado de 2022, Rel. Min. Fulano Beltrano, que.",
         "Supremo Tribunal Federal, julgado de 2022, Rel. Min. Fulano Beltrano", "STF", "2022", "Fulano Beltrano", "tribunal_primeiro"),
        ("O precedente do STF de 2019, cuja relatoria coube ao Ministro Fulano Beltrano, nada.",
         "precedente do STF de 2019, cuja relatoria coube ao Ministro Fulano Beltrano", "STF", "2019", "Fulano Beltrano", "B"),
        ("O acórdão da lavra do Ministro Fulano Beltrano, STF, 2026, nada.",
         "acórdão da lavra do Ministro Fulano Beltrano, STF, 2026", "STF", "2026", "Fulano Beltrano", "lavra_nome_antes"),
        ("O julgado do STF de 2024 relatado por Fulano Beltrano, nada.",
         "julgado do STF de 2024 relatado por Fulano Beltrano", "STF", "2024", "Fulano Beltrano", "H"),
        ("Ver o julgado do STJ de 2024, Rel. a Min. Fulana Beltrana, nada.",
         "julgado do STJ de 2024, Rel. a Min. Fulana Beltrana", "STJ", "2024", "Fulana Beltrana", "H"),
    ]

    def test_moldes(self) -> None:
        for frase, span, trib, ano, relator, molde in self.CASOS:
            with self.subTest(frase=frase):
                a = um(frase)
                self.assertEqual(a.trecho, span)
                self.assertEqual(a.familia, "vaga")
                self.assertEqual(a.forca, 1.0)
                self.assertEqual((a.dados["tribunal"], a.dados["ano"], a.dados["relator"]), (trib, ano, relator))
                self.assertEqual(a.dados["molde"], molde)

    def test_substantivo_depois_do_tribunal_no_amplo(self) -> None:
        a = um("O STJ, em acórdão de 2019 relatado pelo Ministro Fulano Beltrano, decidiu.")
        self.assertEqual(a.trecho, "STJ, em acórdão de 2019 relatado pelo Ministro Fulano Beltrano")
        self.assertEqual((a.origem, a.forca), ("regex:vaga:amplo", 0.6))

    def test_armadilhas_continuam_sem_disparar(self) -> None:
        nenhum("O parecer da lavra do Subprocurador-Geral, de 2019, opinou pelo desprovimento.")
        nenhum("O voto do Ministro relator, proferido em sessão de 2021, foi acompanhado pela maioria.")
        nenhum("A Corte Especial, em 2020, sob a presidência do Ministro Presidente, afetou o tema.")
        # prosa sobre o tribunal sem substantivo continua com força 0,4 (descartada pela resolução)
        a = um("O STJ, em 2019, pela relatoria do Min. Fulano Beltrano, assentou a tese.")
        self.assertEqual((a.forca, a.dados.get("sem_substantivo")), (0.4, "1"))

    def test_cauda_de_citacao_completa_nao_vira_vaga(self) -> None:
        # ``tribunal_primeiro`` é só a cauda de um processo com número (mesma regra do amplo)
        achados = todos("Cite-se o AgRg no RE 1234567/SP, 2ª Turma, STF, j. 2021, Rel. Min. Rosa Exemplo.")
        self.assertEqual([a.trecho for a in achados], ["AgRg no RE 1234567/SP"])


# ---------------------------------------------------------------------------
# R3-06 — OCR no tribunal (5TJ/T5T), fórmula em caixa alta, vaga inteira em CAIXA ALTA, 0 no nome
# ---------------------------------------------------------------------------
class TestVagaCaixaAltaEOcrNoTribunal(unittest.TestCase):
    def test_ocr_no_tribunal(self) -> None:
        for sigla, canon in (("5TJ", "STJ"), ("5TF", "STF"), ("T5T", "TST"), ("T5E", "TSE"), ("5TM", "STM")):
            with self.subTest(sigla=sigla):
                a = um(f"Nesse sentido é o acórdão do {sigla} de 2016, Rel. Min. Fulano Beltrano, que enfrentou.")
                self.assertEqual(a.trecho, f"acórdão do {sigla} de 2016, Rel. Min. Fulano Beltrano")
                self.assertEqual(a.dados["tribunal"], canon)
        self.assertEqual(P.sigla_tribunal_canonica("S.T.J."), "STJ")
        self.assertEqual(P.sigla_tribunal_canonica("T5E"), "TSE")
        self.assertEqual(P.sigla_tribunal_canonica("TJSP"), "")

    def test_formula_em_caixa_alta(self) -> None:
        a = um("Ver a decisão do STJ de 2019, REL. MIN. FULANO BELTRANO FILHO, que.")
        self.assertEqual(a.trecho, "decisão do STJ de 2019, REL. MIN. FULANO BELTRANO FILHO")
        self.assertEqual(a.dados["relator"], "FULANO BELTRANO FILHO")

    def test_vaga_inteira_em_caixa_alta(self) -> None:
        a = um("CONFIRA-SE O JULGADO DO STM PROFERIDO EM 2021 PELA RELATORIA DE FULANO BELTRANO. Nada mais.")
        self.assertEqual(a.trecho, "JULGADO DO STM PROFERIDO EM 2021 PELA RELATORIA DE FULANO BELTRANO")
        self.assertEqual((a.dados["tribunal"], a.dados["ano"], a.dados["molde"]), ("STM", "2021", "A"))
        a = um("JULGAD0 D0 5TJ DE 2O19, REL. MIN. J0EL BELTRAN0 SILVA, que.")
        self.assertEqual((a.dados["tribunal"], a.dados["ano"], a.dados["relator"]), ("STJ", "2019", "J0EL BELTRAN0 SILVA"))

    def test_zero_dentro_do_nome(self) -> None:
        a = um("Ver o julgado do STJ de 2021, Rel. Min. J0se Coelho, que.")
        self.assertEqual(a.dados["relator"], "J0se Coelho")


# ---------------------------------------------------------------------------
# R5-07 — fim do nome do relator; R5-09 — amplo não atravessa fim de frase
# ---------------------------------------------------------------------------
class TestFronteiraDoNome(unittest.TestCase):
    def test_ordinal_e_inicio_de_frase_param_o_nome(self) -> None:
        a = um("Ver o julgado do STJ de 2019 pela relatoria de Fulano Beltrano Terceira Turma, nada.")
        self.assertEqual(a.trecho, "julgado do STJ de 2019 pela relatoria de Fulano Beltrano")
        a = um("Ver o julgado do STJ de 2019 pela relatoria de Fulano Beltrano\nNão obstante isso, nada.")
        self.assertEqual(a.trecho, "julgado do STJ de 2019 pela relatoria de Fulano Beltrano")
        a = um("Ver o julgado do STJ de 2019 pela relatoria de Fulano Beltrano\nEm seguida, nada.")
        self.assertEqual(a.dados["relator"], "Fulano Beltrano")

    def test_particulas_continuam_no_nome(self) -> None:
        a = um("Ver o julgado do STJ de 2019 pela relatoria de Fulano De Tal e Silva, nada.")
        self.assertEqual(a.dados["relator"], "Fulano De Tal e Silva")

    def test_amplo_nao_atravessa_ponto_final(self) -> None:
        achados = todos("Consta em decisão do STJ em 2021. Veja-se acórdão do STJ, Rel. Min. Fulano Beltrano, j. 2020, nada.")
        self.assertEqual([a.trecho for a in achados], ["acórdão do STJ, Rel. Min. Fulano Beltrano, j. 2020"])
        for a in achados:
            self.assertNotIn(". Veja-se", a.trecho)


# ---------------------------------------------------------------------------
# R5-02 — OCR na palavra ``art.``; R3-04 — enumeração de artigos; R3-07 — formas de dispositivo
# ---------------------------------------------------------------------------
class TestDispositivoFormas(unittest.TestCase):
    CASOS = [
        # (frase, span, artigo, diploma)
        ("Invoca-se o artlgo 321 do Código de Processo Civil, como se vê.", "artlgo 321 do Código de Processo Civil", "321", "CPC"),
        ("Invoca-se o ãrt. 11 da Constituição Fcderal, como se vê.", "ãrt. 11 da Constituição Fcderal", "11", "CF"),
        ("Invoca-se o Art1go 11 da CF, como se vê.", "Art1go 11 da CF", "11", "CF"),
        ("Aplicam-se os arts. 11 e 12, ambos da Constituição Federal ao caso.", "arts. 11 e 12, ambos da Constituição Federal", "11", "CF"),
        ("Aplica-se o art. 321 c/c o art. 1.022, ambos do CPC ao caso.", "art. 321 c/c o art. 1.022, ambos do CPC", "321", "CPC"),
        ("Veja-se o disposto nos artigos 11, 12 e 13 da Constituição Federal.", "artigos 11, 12 e 13 da Constituição Federal", "11", "CF"),
        ("Aplicam-se os arts. 321 e 1.022 do CPC ao caso.", "arts. 321 e 1.022 do CPC", "321", "CPC"),
        ("Aplica-se o art. 99 da Lei Federal nº 8.078/1990 ao caso.", "art. 99 da Lei Federal nº 8.078/1990", "99", "CDC"),
        ("Nesse sentido é o art. 321, caput, CPC, que dispõe.", "art. 321, caput, CPC", "321", "CPC"),
        ("Aplica-se o art. 6º do C.D.C. ao caso.", "art. 6º do C.D.C.", "6", "CDC"),
        ("Veja o art 11 CF que dispõe.", "art 11 CF", "11", "CF"),
        ("Aplica-se o art. 11, CF/88 ao caso.", "art. 11, CF/88", "11", "CF"),
        ("Ver art. 11, IX, CF/88 e outros.", "art. 11, IX, CF/88", "11", "CF"),
        ("Ver o artigo 999 da Consolidação das Leis Trabalhistas, ok.", "artigo 999 da Consolidação das Leis Trabalhistas", "999", "CLT"),
    ]

    def test_formas(self) -> None:
        for frase, span, artigo, diploma in self.CASOS:
            with self.subTest(frase=frase):
                a = um(frase)
                self.assertEqual(a.trecho, span)
                self.assertEqual((a.familia, a.forca), ("dispositivo", 1.0))
                self.assertEqual((a.dados["artigo"], a.dados["diploma"]), (artigo, diploma))

    def test_amplo_consome_o_ponto_de_milhar_e_continua_descartado(self) -> None:
        achados = todos("Aplicam-se os arts. 321 e 1.022 ao caso.")
        self.assertEqual([(a.trecho, a.origem) for a in achados], [("arts. 321 e 1.022", "regex:dispositivo:amplo")])

    def test_dois_dispositivos_na_mesma_frase_nao_se_fundem(self) -> None:
        achados = todos("Nos termos do art. 11, LV, da CF, e do art. 321, I, do CPC, cabe.")
        self.assertEqual([a.trecho for a in achados], ["art. 11, LV, da CF", "art. 321, I, do CPC"])


# ---------------------------------------------------------------------------
# R3-03 / R5-06 — súmulas no plural (enumeração); R3-08 — formas de súmula
# ---------------------------------------------------------------------------
class TestSumulaFormas(unittest.TestCase):
    CASOS = [
        # (frase, span, numero, tribunal, vinculante, enumeracao)
        ("Aplicam-se as Súmulas 123 e 456 do STJ ao caso.", "Súmulas 123 e 456 do STJ", "123", "STJ", "0", "456"),
        ("Aplicam-se as Súmulas nºs 123 e 456 do STF ao caso.", "Súmulas nºs 123 e 456 do STF", "123", "STF", "0", "456"),
        ("Incidem as Súmulas 456/TST e 123/STJ, que afastam.", "Súmulas 456/TST e 123/STJ", "456", "TST", "0", "123"),
        ("Ver as Súmulas 12, 34 e 56 do STJ, nada.", "Súmulas 12, 34 e 56 do STJ", "12", "STJ", "0", "34,56"),
        ("Ver o verbete 456 da súmula do TST.", "verbete 456 da súmula do TST", "456", "TST", "0", None),
        ("Ampara a pretensão a Súmula STJ 123, no ponto.", "Súmula STJ 123", "123", "STJ", "0", None),
        ("Ver a Súmula STJ nº 123 no ponto.", "Súmula STJ nº 123", "123", "STJ", "0", None),
        ("Ver a Súmula STJ/123 nada.", "Súmula STJ/123", "123", "STJ", "0", None),
        ("Decorre da Súmula vinculante nº 45, e.", "Súmula vinculante nº 45", "45", "", "1", None),
        ("Ver a Súmula vinculante 45 do STF e.", "Súmula vinculante 45 do STF", "45", "STF", "1", None),
        ("Ver a súmula vinculante 45 e.", "súmula vinculante 45", "45", "", "1", None),
        ("Como se reconheceu na Súmula 123 (Superior Tribunal de Justiça), nada.", "Súmula 123 (Superior Tribunal de Justiça)", "123", "STJ", "0", None),
        ("Ver a Súmula 123 do S.T.J. e.", "Súmula 123 do S.T.J.", "123", "STJ", "0", None),
        ("Ampara a pretensão a Verbete Sumular 456 do TST, ok.", "Verbete Sumular 456 do TST", "456", "TST", "0", None),
        ("Ver a Súmula 123, STJ, nada.", "Súmula 123, STJ", "123", "STJ", "0", None),
        ("Ver o Enunciado 45 da Súmula Vinculante do STF.", "Enunciado 45 da Súmula Vinculante do STF", "45", "STF", "1", None),
        ("Aplica-se a Súmula 123 do 5TJ ao caso.", "Súmula 123 do 5TJ", "123", "STJ", "0", None),
    ]

    def test_formas(self) -> None:
        for frase, span, numero, trib, vinc, enum in self.CASOS:
            with self.subTest(frase=frase):
                a = um(frase)
                self.assertEqual(a.trecho, span)
                self.assertEqual((a.familia, a.forca), ("sumula", 1.0))
                self.assertEqual((a.dados["numero_sumula"], a.dados["tribunal"], a.dados["vinculante"]), (numero, trib, vinc))
                self.assertEqual(a.dados.get("enumeracao"), enum)

    def test_singular_nao_abre_enumeracao(self) -> None:
        self.assertEqual(um("Ver a Súmula 123 do STJ, 2 vezes.").trecho, "Súmula 123 do STJ")
        self.assertEqual(um("Ver a Súmula 123 e 8 anos.").trecho, "Súmula 123")
        self.assertEqual(um("Súmula 123, 1ª Turma do STJ.").trecho, "Súmula 123")


class TestSumulaResolucao(Base):
    def test_enumeracao_resolve_pelo_primeiro(self) -> None:
        a, d = self.ponta_a_ponta("Aplicam-se as Súmulas 123 e 999 do STJ ao caso.")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 900))
        a, d = self.ponta_a_ponta("Aplicam-se as Súmulas 999 e 123 do STJ ao caso.")
        self.assertEqual(d.classificacao, "inventada")

    def test_vinculante_com_tribunal_divergente_e_inventada(self) -> None:   # R5-08
        a, d = self.ponta_a_ponta("Ver a Súmula Vinculante 45 do STJ, nada.")
        self.assertEqual((d.classificacao, d.id_canonico), ("inventada", None))
        self.assertEqual(d.caminho, "sumula:fora_da_tabela:vinculante_tribunal_divergente")
        a, d = self.ponta_a_ponta("Ver a Súmula Vinculante 45 do STF, nada.")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 901))
        a, d = self.ponta_a_ponta("Ver a Súmula Vinculante 45, nada.")
        self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("real", 901, "sumula:na_tabela:tribunal_implicito"))


# ---------------------------------------------------------------------------
# R3-01 / R3-02 — siglas de ato normativo e agência bancária não são processo
# ---------------------------------------------------------------------------
class TestAtosNormativos(unittest.TestCase):
    DISTRATORES = [
        "A Portaria MS nº 2.048/2002 do Ministério da Saúde regula o atendimento.",
        "A Portaria MS 2048, de 2002, regula o atendimento.",
        "A Resolução CC nº 12/2019 da Casa Civil disciplina a matéria.",
        "O Ofício AR nº 1.234/2020 comunicou a decisão à parte.",
        "A Resolução SS nº 123/2021 da Secretaria de Saúde dispõe sobre o tema.",
        "A Deliberação CP nº 45/2020 do Conselho Pleno dispõe sobre o tema.",
        "A Circular AP nº 289/2020 da Agência de Previdência orienta o cálculo.",
        "O Memorando HC nº 94/2021 do Hospital das Clínicas informou o prontuário.",
        "A Instrução Normativa RE nº 10/2016 da Receita Estadual dispõe sobre o tema.",
        "O Ato CC nº 1, de 2015, da Corregedoria disciplina o ponto.",
        "O depósito foi feito na conta 12345-6, Ag. 1234, do Banco Beta.",
        "O valor foi transferido para a Ag. 4370-5, conta corrente 12345-6.",
        "Veja-se o AIRR 1234, que nada diz.",           # família TST sem CNJ
    ]

    def test_distratores(self) -> None:
        for frase in self.DISTRATORES:
            with self.subTest(frase=frase):
                nenhum(frase)

    def test_citacoes_legitimas_continuam(self) -> None:
        for frase, span in (
            ("Ver o MS 12.345/DF, tudo.", "MS 12.345/DF"),                       # com UF
            ("Ver o AgRg no MS 12.345, tudo.", "AgRg no MS 12.345"),               # com prefixo
            ("Ver o Mandado de Segurança nº 12.345, tudo.", "Mandado de Segurança nº 12.345"),
            ("Veja-se o RE 123456, de 2019, que.", "RE 123456"),                    # ≥ 6 dígitos: ", de AAAA" não elimina
            ("Veja-se o RR-999-12.2011.5.15.0099, que examinou.", "RR-999-12.2011.5.15.0099"),
            ("Veja-se o TST-Ag-AIRR-999-12.2011.5.15.0099, que examinou.", "TST-Ag-AIRR-999-12.2011.5.15.0099"),
        ):
            with self.subTest(frase=frase):
                self.assertEqual(um(frase).trecho, span)


# ---------------------------------------------------------------------------
# R3-09 — tribunal como prefixo; R3-12 — enumeração sem plural; R3-13 — fronteiras
# ---------------------------------------------------------------------------
class TestProcessoFormas(unittest.TestCase):
    def test_prefixo_de_tribunal_fica_fora_e_vira_tribunal_explicito(self) -> None:
        for frase, span, trib in (
            ("Nesse sentido o STJ/RHC 12.345/PR, que enfrentou a questão.", "RHC 12.345/PR", "STJ"),
            ("Confira-se STF/Rcl 12.345/RJ.", "Rcl 12.345/RJ", "STF"),
            ("Ainda, STJ/REsp 1.846.332/PA.", "REsp 1.846.332/PA", "STJ"),
            ("Ver STJ/AgInt no AREsp 1.234.567/SP.", "AgInt no AREsp 1.234.567/SP", "STJ"),
            ("Como já se reconheceu na Apelação (STM) nº 7000123-45.2023.7.00.0000, tudo.",
             "Apelação (STM) nº 7000123-45.2023.7.00.0000", "STM"),
        ):
            with self.subTest(frase=frase):
                a = um(frase)
                self.assertEqual(a.trecho, span)
                self.assertEqual((a.dados["tribunal"], a.dados["tribunal_fonte"]), (trib, "explicito"))
        nenhum("Inscrito na OAB/AC 12345, o advogado.")   # ``/`` depois de outra sigla continua barrando

    def test_enumeracao_sem_plural(self) -> None:
        achados = todos("Nesse sentido, o REsp 1.234.567/SP e 2.345.678/RS, ambos da Terceira Turma.")
        self.assertEqual([a.trecho for a in achados], ["REsp 1.234.567/SP", "2.345.678/RS"])
        self.assertEqual(achados[1].dados["cadeia"], "RESP")
        self.assertEqual(achados[1].origem, "regex:processo:enumeracao")
        # sem UF, formato diferente ou número curto: não abre
        self.assertEqual([a.trecho for a in todos("Ver o REsp 1.234.567/SP e 12/03/2020, nada.")], ["REsp 1.234.567/SP"])
        self.assertEqual([a.trecho for a in todos("Ver o REsp 1.234.567/SP e 2020/SP, nada.")], ["REsp 1.234.567/SP"])

    def test_fronteiras(self) -> None:
        a = um("Como decidido na Rcl 12.345-AgR/RJ, nada.")
        self.assertEqual((a.trecho, a.dados["cadeia"], a.dados["uf"]), ("Rcl 12.345-AgR/RJ", "AGR RCL", "RJ"))
        a = um("Ver o AgInt n0 AREsp 1.234.567/MG, tudo.")
        self.assertEqual((a.trecho, a.dados["cadeia"]), ("AgInt n0 AREsp 1.234.567/MG", "AGINT ARESP"))
        a = um("Ver o REsp nº 1.234.567/5P, tudo.")
        self.assertEqual((a.trecho, a.dados["uf"]), ("REsp nº 1.234.567/5P", "SP"))
        a = um("Ver o REsp nº 1.234.567/R0, tudo.")
        self.assertEqual((a.trecho, a.dados["uf"]), ("REsp nº 1.234.567/R0", "RO"))
        self.assertEqual(P.uf_canonica("M5"), "MS")
        self.assertEqual(P.uf_canonica("XX"), "")


# ---------------------------------------------------------------------------
# R3-11 / R5-04 — chave curta com classe divergente antes do atalho de duplicatas; sub-caminhos
# ---------------------------------------------------------------------------
class TestChaveCurtaEClasseDivergente(Base):
    @classmethod
    def setUpClass(cls) -> None:
        indice = json.loads(json.dumps(INDICE_FALSO))
        # grupo duplicado de 3 registros ``QO CAUTINOM`` com número 87 (cabeçalho idêntico) e um par
        # ``RO`` do TSE com número 1662
        for k in ("dup_a", "dup_b", "dup_c"):
            indice["registros"][k] = _reg(k, 700 + int(k[-1] == "b") + 2 * int(k[-1] == "c"), "STJ", 2020,
                                          "MINISTRO SICRANO", "QO CAUTINOM",
                                          "QUESTÃO DE ORDEM NA CAUTELAR INOMINADA Nº 87 - DF RELATOR : MINISTRO SICRANO",
                                          [("87", "sequencial", "DF")])
        for k, idc in (("ro_a", 800), ("ro_b", 801)):
            indice["registros"][k] = _reg(k, idc, "TSE", 2010, "Ministro Epsilon", "RO",
                                          "TRIBUNAL SUPERIOR ELEITORAL RECURSO ORDINÁRIO Nº 1662 - CLASSE 27 - CIDADE - GOIÁS Relator",
                                          [("1662", "sequencial", "GO")])
        indice["registros"]["stf_x"] = _reg("stf_x", 403, "STF", 2021, "Min. Fulana", "ADI",
                                            "TRIBUNAL PLENO AÇÃO DIRETA DE INCONSTITUCIONALIDADE 4.815 DISTRITO FEDERAL RELATOR : MIN. FULANA",
                                            [("4815", "sequencial", "DF")])
        m: dict[str, list[str]] = {}
        for docid in sorted(indice["registros"]):
            for it in indice["registros"][docid]["identificadores"]:
                m.setdefault(it["digitos"], []).append(docid)
        indice["por_digitos"] = {k: sorted(v) for k, v in m.items()}
        cls.base = BaseCanonica(indice)

    def test_chave_curta_divergente_em_grupo_duplicado_e_inventada(self) -> None:
        for frase in ("Nesse sentido o HC nº 87, que enfrentou a questão.", "Nesse sentido o MS 1662, que enfrentou.",
                      "Ver o HC nº 1.662/GO, que enfrentou."):
            with self.subTest(frase=frase):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual(d.classificacao, "inventada", d)
                self.assertEqual(d.caminho, "processo:multi:curto_classe_divergente")

    def test_classe_compativel_em_grupo_duplicado_continua_real(self) -> None:
        a, d = self.ponta_a_ponta("Ver a Cautelar Inominada nº 87/DF, que enfrentou.")
        self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("real", 700, "processo:duplicata"))
        a, d = self.ponta_a_ponta("Ver o RO 1662/GO, que enfrentou.")
        self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("real", 800, "processo:duplicata"))

    def test_um_candidato_4_digitos_divergente_e_inventada(self) -> None:
        a, d = self.ponta_a_ponta("Ver a Rcl 4.815/DF, que enfrentou.")
        self.assertEqual((d.classificacao, d.caminho), ("inventada", "processo:1cand:curto_classe_divergente"))
        a, d = self.ponta_a_ponta("Ver a ADI 4.815/DF, que enfrentou.")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 403))

    def test_cinco_digitos_divergente_sem_uf_e_inventada(self) -> None:
        # número de 5 dígitos de um ``AGR RCL`` citado como HC sem UF nem tribunal certo: nada além do
        # número sustenta a escolha — rodada 3 (R5-04) emitia ``real`` com prior 0,6; desde a rodada 4
        # (R4-03) a decisão é ``inventada`` (break-even da métrica P(real) ≈ 0,73 > prior), prior 0,5
        a, d = self.ponta_a_ponta("Ver o HC 62.471, que enfrentou.")
        self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("inventada", None, "processo:1cand:classe_divergente:sem_uf"))
        # com a UF confirmada o número manda (real, confiança rebaixada)
        a, d = self.ponta_a_ponta("Ver o HC 62.471/SP, que enfrentou.")
        self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("real", 402, "processo:1cand:classe_divergente"))
        conf_sem_uf = cal.confianca(Decisao("inventada", None, "processo:1cand:classe_divergente:sem_uf", (402,), {}), a, None)
        conf_com_uf = cal.confianca(Decisao("real", 402, "processo:1cand:classe_divergente", (402,), {}), a, None)
        self.assertLess(conf_sem_uf, conf_com_uf)


class TestCalibracaoSemTreinoCircular(unittest.TestCase):
    def test_caminhos_por_politica_mantem_o_prior(self) -> None:   # R5-04 (a)
        avs = [("processo:1cand:classe_divergente", 1)] * 50 + [("processo:1cand:cadeia_exata", 1)] * 50
        tabela = cal.ajustar(None, avs)
        self.assertEqual(tabela["processo:1cand:classe_divergente"], cal.TABELA_INICIAL["processo:1cand:classe_divergente"])
        self.assertGreater(tabela["processo:1cand:cadeia_exata"], 0.97)
        # o prefixo agregado não recebe as observações excluídas
        n, a = cal.contagens([av for av in cal.normalizar_avaliacoes(avs) if not cal.sem_treino(av.caminho)])["processo:1cand"]
        self.assertEqual(n, 50)
        self.assertTrue(cal.sem_treino("processo:duplicata:classe_divergente"))
        self.assertFalse(cal.sem_treino("processo:1cand:cadeia_exata"))

    def test_tabela_versionada_tem_os_priors(self) -> None:
        tabela = cal.carregar(RAIZ / "dados" / "calibracao.json")
        if not tabela:
            self.skipTest("dados/calibracao.json ausente")
        for cam in ("processo:1cand:classe_divergente", "processo:1cand:tribunal_incompativel", "processo:0cand:ocr_ambiguo"):
            self.assertEqual(tabela[cam], cal.TABELA_INICIAL[cam], cam)
        self.assertGreaterEqual(tabela["sumula:na_tabela:sem_tribunal"], 0.95)   # R3-14


# ---------------------------------------------------------------------------
# R5-05 / R3-10 — cabeçalho: linha longa de identificação dos autos; parágrafo em CAIXA ALTA
# ---------------------------------------------------------------------------
class TestCabecalho(unittest.TestCase):
    def test_linha_longa_de_identificacao_e_cabecalho(self) -> None:
        t = ("TRIBUNAL DE JUSTIÇA\n\nApelação Cível nº 1234567-89.2021.8.26.0114 da Comarca de Campinas, em que é "
             "apelante FULANO DE TAL e apelado BELTRANO S.A.\nRelator: Des. Sicrano\n\nVOTO\n\n" + PROSA
             + "Invoca-se o REsp 1.234.567/SP, que tudo.\n")
        self.assertEqual(T.fim_do_cabecalho(t), t.index("Trata-se"))
        self.assertEqual([a.trecho for a in detectar(t)], ["REsp 1.234.567/SP"])

    def test_primeiro_paragrafo_em_caixa_alta_e_prosa(self) -> None:
        t = (CABECALHO + "TRATA-SE DE RECURSO INTERPOSTO CONTRA ACÓRDÃO QUE MANTEVE A DECISÃO DE ORIGEM, PELOS "
             "FUNDAMENTOS QUE SE PASSA A EXPOR. NESSE SENTIDO É O RESP Nº 1.234.567/SP, QUE ENFRENTOU HIPÓTESE "
             "IDÊNTICA. APLICA-SE A SÚMULA 123 DO STJ AO CASO.\n" + PROSA)
        self.assertEqual(T.fim_do_cabecalho(t), t.index("TRATA-SE"))
        self.assertEqual([a.trecho for a in detectar(t)], ["RESP Nº 1.234.567/SP", "SÚMULA 123 DO STJ"])

    def test_ementa_antes_da_prosa_e_cabecalho_em_qualquer_caixa(self) -> None:
        # rodada 3 (R3-10): ementa em caixa alta é cabeçalho; rodada 4 (R4-04): a MESMA política vale
        # sem rótulo e com ``Ementa:`` em caixa mista (a forma de ementa decide, não a caixa)
        t = ("MINISTÉRIO PÚBLICO\n\nAutos nº 1234567-89.2021.8.26.0100\n\nPARECER\n\nEMENTA: PROCESSUAL CIVIL. "
             "AGRAVO INTERNO. ÔNUS DA PROVA. INCIDÊNCIA DA SÚMULA 123 DO STJ. PRECEDENTE: RESP 1.234.567/SP. "
             "AGRAVO A QUE SE NEGA PROVIMENTO.\n\nACÓRDÃO\n\n" + PROSA + "Invoca-se o RHC 12.345/RJ, que tudo.\n")
        mista = t.replace("EMENTA: PROCESSUAL CIVIL. AGRAVO INTERNO. ÔNUS DA PROVA. INCIDÊNCIA DA SÚMULA 123 DO STJ.",
                          "Ementa: Processual civil. Agravo interno. Ônus da prova. Incidência da Súmula 123 do STJ.")
        for t_k in (t, t.replace("EMENTA: ", ""), mista):
            with self.subTest(inicio=t_k[:80]):
                self.assertEqual(T.fim_do_cabecalho(t_k), t_k.index("Trata-se"))
                self.assertEqual([a.trecho for a in detectar(t_k)], ["RHC 12.345/RJ"])
        # ``Relatório: trata-se de …`` continua a ser prosa (R4-09-a)
        self.assertTrue(T.e_linha_de_prosa("Relatório: trata-se de recurso interposto contra a sentença que julgou o pedido."))


# ---------------------------------------------------------------------------
# Engenharia — R3e-01 (carga do árbitro), R3e-04 (csv), R3e-08 (cp1252), R3e-11 (subpastas)
# ---------------------------------------------------------------------------
class TestEngenharia(unittest.TestCase):
    def test_falha_ao_carregar_o_arbitro_recua_para_o_nucleo(self) -> None:   # R3e-01
        from caca_alucinacao import cli

        class Quebrado(Exception):
            pass

        def falha(nome: str):
            raise OSError("Can't load tokenizer (offline)")

        import caca_alucinacao.llm as llm
        original = llm.obter_arbitro
        llm.obter_arbitro = falha
        try:
            self.assertIsNone(cli.criar_arbitro("transformers"))
        finally:
            llm.obter_arbitro = original
        self.assertIsNone(cli.criar_arbitro("nenhum"))

    def test_latin1_e_decodificado_como_cp1252(self) -> None:   # R3e-08
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "latin1.txt"
            conteudo = "Súmula 123 do STJ e art. 11 da CF, ação.\n"
            p.write_bytes(conteudo.encode("cp1252"))
            texto = T.carregar(p)
            self.assertEqual(texto, conteudo)
            self.assertNotIn("�", texto)
            p.write_bytes(conteudo.encode("utf-8"))
            self.assertEqual(T.carregar(p), conteudo)

    def test_csv_com_celula_grande(self) -> None:   # R3e-04
        import csv
        import io
        sys.path.insert(0, str(RAIZ / "scripts"))
        import gerar_submissao  # noqa: F401  (ajusta o limite ao ser importado)
        celula = "|".join(f"{i},{i + 5},inventada,-,0.9" for i in range(0, 60000, 10))
        self.assertGreater(len(celula), 131072)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["documento_id", "citacoes"])
        w.writerow(["doc", celula])
        linhas = list(csv.DictReader(io.StringIO(buf.getvalue())))
        self.assertEqual(len(linhas[0]["citacoes"]), len(celula))

    def test_pasta_so_com_subpastas_avisa(self) -> None:   # R3e-11
        from caca_alucinacao.pipeline import listar_documentos
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "txt").mkdir()
            (Path(d) / "txt" / "a.txt").write_text("x", encoding="utf-8")
            with self.assertLogs("caca_alucinacao.pipeline", level="ERROR") as cm:
                self.assertEqual(listar_documentos(Path(d)), [])
            self.assertTrue(any("txt" in m for m in cm.output))


if __name__ == "__main__":
    unittest.main()
