"""Testes das correções da revisão (rodada 4) — um bloco por achado, todos sintéticos.

Cada classe cita o(s) achado(s) que cobre: R4-xx (correção = revisor 1), R6-xx (generalização =
revisor 2) e R3q-xx (engenharia = revisor 3). Base canônica FALSA (``tests/test_resolucao.INDICE_FALSO``);
nenhum número, nome ou trecho do gabarito ou da base real (números de súmula/artigo são os da base
falsa: 123/456/45, 321/11/240, ou números inexistentes como 999).
"""
from __future__ import annotations

import logging
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

from test_resolucao import INDICE_FALSO  # noqa: E402

from caca_alucinacao import calibracao as cal  # noqa: E402
from caca_alucinacao import texto as T  # noqa: E402
from caca_alucinacao.base_canonica import BaseCanonica  # noqa: E402
from caca_alucinacao.base_canonica.normativos import diploma_canonico  # noqa: E402
from caca_alucinacao.deteccao import detectar  # noqa: E402
from caca_alucinacao.normalizacao import cadeia_de_classes  # noqa: E402
from caca_alucinacao.pipeline import listar_documentos, processar_texto_com_rastro  # noqa: E402
from caca_alucinacao.resolucao import resolver  # noqa: E402
from caca_alucinacao.tipos import Achado, Decisao  # noqa: E402

PROSA = ("Trata-se de peça processual em que a parte examina a tese defendida na origem, "
         "conforme as razões a seguir expostas.\n")
CABECALHO = "EGRÉGIO TRIBUNAL\n\nAutos nº 1234567-89.2021.8.26.0100\nRecorrente: FULANO\n\nMEMORIAL\n\n"
N = "Fulano Beltrano"   # relator fictício
logging.getLogger("caca_alucinacao").setLevel(logging.CRITICAL)


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

    def emitidas(self, frase: str) -> tuple[list, list]:
        """Citações emitidas pelo pipeline (com descarte dos amplos) e o rastro."""
        saida, rastros = processar_texto_com_rastro("doc_n2_001", doc(frase), self.base)
        return list(saida.citacoes), rastros


# ---------------------------------------------------------------------------
# R4-01 — CNJ com branco (espaço, NBSP, quebra, espaço duplo) no lugar do ponto antes do segmento J
# ---------------------------------------------------------------------------
class TestCnjBrancoAntesDoSegmentoJ(Base):
    CNJS = [
        # (cadeia, número limpo, id esperado) — números da base FALSA
        ("RR", "10173-25.2016.5.03.0028", 203),
        ("AIRR", "987-65.2016.5.02.0123", 202),
        ("APL", "7000123-45.2023.7.00.0000", 300),
    ]

    def test_branco_no_lugar_do_ponto_antes_do_j(self) -> None:
        for cadeia, limpo, idc in self.CNJS:
            ano_fim = limpo.index(".", limpo.index(".") + 1)   # ponto entre o ano e o J
            for branco in (" ", "\xa0", "\n", "  ", "\n "):
                ruidoso = limpo[:ano_fim] + branco + limpo[ano_fim + 1:]
                frase = f"Conforme o {cadeia} {ruidoso}, a tese."
                with self.subTest(frase=frase):
                    a, d = self.ponta_a_ponta(frase)
                    self.assertEqual(a.trecho, f"{cadeia} {ruidoso}")
                    self.assertEqual(len(a.dados["digitos"]), 20)
                    self.assertEqual(a.dados["formato"], "cnj20")
                    self.assertEqual((d.classificacao, d.id_canonico), ("real", idc), d)

    def test_a_guarda_anti_data_continua(self) -> None:
        # ``12.03.2022`` depois do número NÃO é grupo do número; a data fica fora do span
        a = um("Ver o REsp 1.234.567 12.03.2022, nada.")
        self.assertEqual(a.trecho, "REsp 1.234.567")


# ---------------------------------------------------------------------------
# R6-01 / R4-02 — a regra negativa ``, de AAAA`` só elimina sigla de órgão, ≤ 3 dígitos, sem conector
# ---------------------------------------------------------------------------
class TestRegraNegativaDeAtoNormativo(Base):
    def test_citacoes_legitimas_com_de_ano(self) -> None:
        for frase, span in (
            ("Como decidido na Rcl 54.321, de 2023, a tese não se sustenta.", "Rcl 54.321"),      # Rcl nunca é órgão
            ("Como decidido no RHC 12.345, de 2021, Rel. Min. Sicrano, a tese.", "RHC 12.345"),
            ("Conforme a AR 4.321, de 2015, a tese.", "AR 4.321"),                                 # ≥ 4 dígitos
            ("Conforme o MS nº 123, de 2015, a tese.", "MS nº 123"),                              # conector
            ("Conforme o MS 123, de 2015, Rel. Min. Sicrano, a tese.", "MS 123"),                # relatoria depois
            ("Conforme o MS 123/DF, de 2015, a tese.", "MS 123/DF"),                             # UF
        ):
            with self.subTest(frase=frase):
                self.assertEqual(um(frase).trecho, span)

    def test_resolucao_da_rcl_com_de_ano(self) -> None:
        a, d = self.ponta_a_ponta("Como decidido na Rcl 54.321, de 2023, a tese não se sustenta.")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 401))

    def test_atos_continuam_eliminados(self) -> None:
        for frase in (
            "Nos termos da Portaria MS nº 2.048, de 2002, a tese.",   # substantivo antes
            "Nos termos do Ato CC nº 1, de 2015, a tese.",
            "Nos termos da MS nº 2.048/2002, a tese.",               # ``/AAAA`` colado
            "Nos termos do MS 12, de 2015, a tese.",                 # sigla de órgão, ≤ 3 dígitos, sem conector
        ):
            with self.subTest(frase=frase):
                nenhum(frase)


# ---------------------------------------------------------------------------
# R6-02 / R6-07 / R3-12 — enumerações com a classe no plural: um span por número
# ---------------------------------------------------------------------------
class TestEnumeracoesNoPlural(Base):
    def test_plural_com_conector_plural_e_nome_por_extenso(self) -> None:
        for frase, spans in (
            ("Nesse sentido os REsps nºs 1.234.567/SP e 2.345.678/PR.", ["REsps nºs 1.234.567/SP", "2.345.678/PR"]),
            ("Nesse sentido os REsps n.ºs 1.234.567/SP, 2.345.678/PR.", ["REsps n.ºs 1.234.567/SP", "2.345.678/PR"]),
            ("Colhe-se nos Recursos Especiais 1.234.567/SP e 2.345.678/PR, ambos da Corte Especial.",
             ["Recursos Especiais 1.234.567/SP", "2.345.678/PR"]),
            ("Assim nas Reclamações 54.321/RJ e 62.471/SP, nada.", ["Reclamações 54.321/RJ", "62.471/SP"]),
            # sem UF: só com o plural, ≥ 5 dígitos e o mesmo formato (R6-07)
            ("Veja-se os REsps 1.234.567, 2.345.678 e 1.234.567, todos do STJ.", ["REsps 1.234.567", "2.345.678", "1.234.567"]),
            ("Assim nas Rcls 54.321 e 62.471, que decidiram.", ["Rcls 54.321", "62.471"]),
            # conector repetido na continuação (R6-07)
            ("Assim o REsp nº 1.234.567/SP e o nº 2.345.678/PR, que decidiram.", ["REsp nº 1.234.567/SP", "2.345.678/PR"]),
        ):
            with self.subTest(frase=frase):
                self.assertEqual([a.trecho for a in todos(frase)], spans)

    def test_plural_e_alias_da_mesma_cadeia(self) -> None:
        self.assertEqual(cadeia_de_classes("Rcls"), ["RCL"])
        self.assertEqual(cadeia_de_classes("REsps"), ["RESP"])
        self.assertEqual(cadeia_de_classes("Recursos Especiais"), ["RESP"])
        self.assertEqual(cadeia_de_classes("Reclamações"), ["RCL"])
        a, d = self.ponta_a_ponta("Assim na Rcls 54.321, nada.")
        self.assertEqual(d.classificacao, "real")

    def test_sem_plural_a_continuacao_exige_uf_e_nunca_e_ano_ou_data(self) -> None:
        self.assertEqual([a.trecho for a in todos("Veja-se o Habeas Corpus 12.345 e 2020, nada.")], ["Habeas Corpus 12.345"])
        self.assertEqual([a.trecho for a in todos("Veja-se o REsp 1.234.567/SP e 12/03/2020, nada.")], ["REsp 1.234.567/SP"])
        self.assertEqual([a.trecho for a in todos("Veja-se os REsps 1.234.567/SP e 2020, nada.")], ["REsps 1.234.567/SP"])
        self.assertEqual([a.trecho for a in todos("Veja-se os REsps 1.234.567/SP, 2ª Turma, nada.")], ["REsps 1.234.567/SP"])

    def test_cada_numero_resolve_por_si(self) -> None:
        achados = todos("Nesse sentido os REsps nºs 1.234.567/SP e 2.345.678/PR.")
        ids = [resolver(a, self.base).id_canonico for a in achados]
        self.assertEqual(ids, [100, 101])


# ---------------------------------------------------------------------------
# R6-03 — OCR e→c na palavra ``Lei`` (``Lci``, ``Dccreto-Lci``, ``Lci Complementar``)
# ---------------------------------------------------------------------------
class TestOcrNaPalavraLei(Base):
    def test_diploma_canonico_tolera_lci(self) -> None:
        for superficie, esperado in (
            ("Lci nº 13.105/2015", "CPC"), ("Dccreto-Lci nº 1.001/1969", "CPM"), ("Lci Complementar nº 64/1990", "LC64"),
            ("Lci nº 9.504/1997", "LEI-9504"), ("Lci Fcderal nº 8.078/1990", "CDC"), ("Lcis Trabalhistas", "CLT"),
            ("Lei nº 13.105/2015", "CPC"), ("1ei nº 13.105/2015", "CPC"),
        ):
            with self.subTest(superficie=superficie):
                self.assertEqual(diploma_canonico(superficie), esperado)
        self.assertIsNone(diploma_canonico("lei"))
        self.assertIsNone(diploma_canonico("a lei do mais forte"))

    def test_ponta_a_ponta(self) -> None:
        for frase, idc in (
            ("Aplica-se o art. 321 da Lci nº 13.105/2015.", 950),
            ("Aplica-se o art. 240 do Dccreto-Lci nº 1.001/1969.", 952),
            ("Aplica-se o art. 321 da Lci Fcderal nº 13.105/2015.", 950),
        ):
            with self.subTest(frase=frase):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("real", idc, "dispositivo:na_tabela"))


# ---------------------------------------------------------------------------
# R6-04 / R6-09 — enumeração de súmulas com dois tribunais; ``Súmulas Vinculantes``; ``Súmula de nº``
# ---------------------------------------------------------------------------
class TestSumulaEnumeracaoEFormas(Base):
    def test_dois_tribunais_fecha_no_primeiro(self) -> None:
        a, d = self.ponta_a_ponta("Nesse sentido as Súmulas 123 e 999 do STJ e 456 do TST.")
        self.assertEqual(a.trecho, "Súmulas 123 e 999 do STJ")
        self.assertEqual(a.dados["tribunal"], "STJ")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 900))
        a, d = self.ponta_a_ponta("Nesse sentido as Súmulas nº 123, 999 (STJ) e 456 (TST).")
        self.assertEqual(a.trecho, "Súmulas nº 123, 999 (STJ)")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 900))

    def test_vinculantes_no_plural_e_de_no(self) -> None:
        a, d = self.ponta_a_ponta("Nesse sentido as Súmulas Vinculantes 45 e 37.")
        self.assertEqual(a.trecho, "Súmulas Vinculantes 45 e 37")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 901))
        a, d = self.ponta_a_ponta("Nesse sentido a Súmula de nº 123 do STJ.")
        self.assertEqual(a.trecho, "Súmula de nº 123 do STJ")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 900))
        a, d = self.ponta_a_ponta("Veja-se a Súmula 123 dó STJ, que decidiu.")   # R4-07
        self.assertEqual(a.trecho, "Súmula 123 dó STJ")
        self.assertEqual(d.id_canonico, 900)


# ---------------------------------------------------------------------------
# R6-05 / R6-06 / R4-06 — moldes de vaga com tribunal/ano DEPOIS do nome e redações novas
# ---------------------------------------------------------------------------
class TestVagaTribunalDepoisDoNome(unittest.TestCase):
    CASOS = [
        # (frase, span, tribunal, ano, molde)
        (f"Ampara a pretensão o precedente da lavra do Ministro {N}, julgado pelo STF em 2024, que fixou.",
         f"precedente da lavra do Ministro {N}, julgado pelo STF em 2024", "STF", "2024", "nome_tribunal_ano"),
        (f"Nesse sentido é o julgado de 2021 da relatoria do Ministro {N}, do STM, que fixou.",
         f"julgado de 2021 da relatoria do Ministro {N}, do STM", "STM", "2021", "ano_nome_tribunal"),
        (f"Confira-se o voto condutor do Ministro {N} no STF, em 2025, que assentou.",
         f"voto condutor do Ministro {N} no STF, em 2025", "STF", "2025", "nome_tribunal_ano"),
        (f"Confira-se a decisão da lavra do Min. {N} (STF, 2025), que assentou.",
         f"decisão da lavra do Min. {N} (STF, 2025)", "STF", "2025", "parenteses"),
        (f"Como se vê do acórdão do TSE de 2013, cujo relator, Ministro {N}, assentou a tese.",
         f"acórdão do TSE de 2013, cujo relator, Ministro {N}", "TSE", "2013", "E"),
        (f"Confira-se a decisão do STF de 2026 sob a relatoria de S. Exa. o Ministro {N}, que assentou.",
         f"decisão do STF de 2026 sob a relatoria de S. Exa. o Ministro {N}", "STF", "2026", "F"),
        (f"Confira-se o acórdão do STJ de 2019; Rel. Min. {N}; que assentou.",
         f"acórdão do STJ de 2019; Rel. Min. {N}", "STJ", "2019", "E"),
        (f"Confira-se o acórdão do STJ de 2019 - Rel. Min. {N} - que assentou.",
         f"acórdão do STJ de 2019 - Rel. Min. {N}", "STJ", "2019", "E"),
        # R4-06: data completa antes da fórmula; ``Relator(a): Ministro(a)``; inicial abreviada
        (f"Veja-se o acórdão do STJ julgado em 12/03/2015, Rel. Min. {N}, que decidiu.",
         f"acórdão do STJ julgado em 12/03/2015, Rel. Min. {N}", "STJ", "2015", "E"),
        (f"Veja-se o acórdão do STJ de 12 de março de 2015, Rel. Min. {N}, que decidiu.",
         f"acórdão do STJ de 12 de março de 2015, Rel. Min. {N}", "STJ", "2015", "E"),
        (f"Veja-se o acórdão do STJ de 2015, Relator(a): Ministro(a) {N}, que decidiu.",
         f"acórdão do STJ de 2015, Relator(a): Ministro(a) {N}", "STJ", "2015", "E"),
        ("Veja-se o acórdão do STJ de 2015, Rel. Min. F. Beltrano, que decidiu.",
         "acórdão do STJ de 2015, Rel. Min. F. Beltrano", "STJ", "2015", "E"),
    ]

    def test_moldes(self) -> None:
        for frase, span, trib, ano, molde in self.CASOS:
            with self.subTest(frase=frase):
                a = um(frase)
                self.assertEqual(a.trecho, span)
                self.assertEqual(a.familia, "vaga")
                self.assertEqual(a.forca, 1.0)
                self.assertEqual((a.dados["tribunal"], a.dados["ano"], a.dados["molde"]), (trib, ano, molde))
                self.assertTrue(a.dados["relator"].endswith("Beltrano"), a.dados["relator"])

    def test_sem_as_tres_ancoras_nao_dispara(self) -> None:
        nenhum(f"O voto condutor do Ministro {N} foi acompanhado à unanimidade.")          # sem tribunal nem ano
        nenhum("O precedente da lavra do Ministro relator, julgado pelo STF em 2024, é claro.")   # sem nome próprio
        nenhum(f"A decisão da lavra do Min. {N} (fls. 12) foi mantida.")


# ---------------------------------------------------------------------------
# R6-08 / R4-09 — UF com OCR e separador `` - ``; letra fora do mapa nunca gera chave parcial
# ---------------------------------------------------------------------------
class TestUfComOcr(Base):
    def test_uf_com_ocr_com_hifen_e_com_letra_inicial(self) -> None:
        for frase, span, caminho in (
            ("Nesse sentido, o REsp 1.234.567 - 5P fixou a orientação.", "REsp 1.234.567 - 5P", "processo:1cand:cadeia_exata"),
            ("Nesse sentido, o REsp l.234.567/5P fixou a orientação.", "REsp l.234.567/5P", "processo:ocr_reparado:1cand:cadeia_exata"),
            ("Nesse sentido, o REsp 1.234.567/5P fixou.", "REsp 1.234.567/5P", "processo:1cand:cadeia_exata"),
            ("Nesse sentido, o REsp 1234567SP, que assentou.", "REsp 1234567SP", "processo:1cand:cadeia_exata"),
        ):
            with self.subTest(frase=frase):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual(a.trecho, span)
                self.assertEqual(a.dados["uf"], "SP")
                self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("real", 100, caminho))

    def test_letra_fora_do_mapa_nao_gera_chave_parcial(self) -> None:   # R4-09
        nenhum("Nesse sentido, o REsp 1.234.56A/SP, que assentou a tese.")
        nenhum("Nesse sentido, o REsp 1.234.567X, que assentou a tese.")


# ---------------------------------------------------------------------------
# R6-09 / R6-10 / R4-07 / R4-08 — formas de dispositivo
# ---------------------------------------------------------------------------
class TestDispositivoFormas(Base):
    def test_formas_reais(self) -> None:
        for frase, span, idc in (
            ("Aplica-se o art. 321 da Lei nº l3.105/2015.", "art. 321 da Lei nº l3.105/2015", 950),   # OCR no 1º dígito da lei
            ("Aplica-se o art. 321, a, do CPC.", "art. 321, a, do CPC", 950),                       # alínea solta
            ("Aplica-se o art. 321, c, CPC.", "art. 321, c, CPC", 950),
            ("Aplica-se o art. 321 do Novo CPC.", "art. 321 do Novo CPC", 950),
            ("Viola o art. 11, LV, da CF de 1988, portanto.", "art. 11, LV, da CF de 1988", 951),   # R4-07
            ("Viola o art. 321 do Código de Processo Civil (Lei nº 13.105/2015), portanto.",
             "art. 321 do Código de Processo Civil (Lei nº 13.105/2015)", 950),
        ):
            with self.subTest(frase=frase):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual(a.trecho, span)
                self.assertEqual((d.classificacao, d.id_canonico), ("real", idc), d)

    def test_alinea_solta_nao_engole_prosa(self) -> None:
        # ``art. 321, a`` seguido de prosa: ``a`` é artigo definido, não alínea → só o amplo (descartado)
        citacoes, _ = self.emitidas("Aplica-se o art. 321, a nosso ver, sem ressalvas.")
        self.assertEqual(citacoes, [])

    def test_art_repetido_sem_diploma_comum(self) -> None:   # R6-10
        citacoes, _ = self.emitidas("Aplica-se o art. 999, I e II, c/c o art. 321 do CPC.")
        self.assertEqual([(c.trecho, c.classificacao) for c in citacoes], [("art. 321 do CPC", "real")])
        # o 1º artigo (sem diploma) fica só como amplo, que a fusão/resolução não emite
        self.assertEqual([a.trecho for a in todos("Aplica-se o art. 999, I e II, c/c o art. 321 do CPC.")], ["art. 321 do CPC"])
        citacoes, _ = self.emitidas("Aplica-se o art. 999 do CPC c/c o art. 321 do CPC.")
        self.assertEqual([(c.trecho, c.classificacao) for c in citacoes],
                         [("art. 999 do CPC", "inventada"), ("art. 321 do CPC", "real")])
        # com a marca de diploma comum continua UM span (R3-04)
        a = um("Aplica-se o art. 999 c/c o art. 321, ambos do CPC.")
        self.assertEqual(a.trecho, "art. 999 c/c o art. 321, ambos do CPC")

    def test_leis_trabalhistas_e_diploma_no_detector(self) -> None:   # R4-08 (c)
        a = um("Viola o art. 999 das Leis Trabalhistas, portanto.")
        self.assertEqual((a.trecho, a.forca, a.dados["diploma"]), ("art. 999 das Leis Trabalhistas", 1.0, "CLT"))

    def test_registro_do_stj_manda_mesmo_com_classe_divergente(self) -> None:   # R4-08 (b)
        a, d = self.ponta_a_ponta("Conforme o AgInt 2019/0123456-7, a tese.")
        self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("real", 100, "processo:1cand:registro"))


# ---------------------------------------------------------------------------
# R6-11 — ``Enunciado N`` de órgão não jurisdicional nunca é súmula, mesmo com o número na tabela
# ---------------------------------------------------------------------------
class TestEnunciadoDeOrgaoExterno(Base):
    def test_descartado_mesmo_com_numero_na_tabela(self) -> None:
        for frase in (
            "O Enunciado 123 do CJF, aprovado na IV Jornada de Direito Civil, orienta a interpretação.",
            "O Enunciado nº 456 da V Jornada de Direito Civil orienta a interpretação.",
            "O Enunciado 45 da I Jornada de Direito Comercial orienta.",
            "O Enunciado 7 do FONAJE orienta a interpretação.",
        ):
            with self.subTest(frase=frase):
                citacoes, rastros = self.emitidas(frase)
                self.assertEqual(citacoes, [])
                self.assertTrue(any(r.achado.origem == "regex:sumula:orgao_externo" and r.status == "descartada:resolucao"
                                    for r in rastros), [(r.status, r.achado.origem) for r in rastros])

    def test_enunciado_da_sumula_de_tribunal_continua(self) -> None:
        citacoes, _ = self.emitidas("O Enunciado 123 da Súmula do STJ orienta.")
        self.assertEqual([(c.trecho, c.classificacao, c.id_canonico) for c in citacoes], [("Enunciado 123 da Súmula do STJ", "real", "900")])


# ---------------------------------------------------------------------------
# R6-12 — OCR l/i→1 dentro do nome da classe por extenso
# ---------------------------------------------------------------------------
class TestOcrNoNomeDaClasse(Base):
    def test_um_no_lugar_de_l_ou_i(self) -> None:
        for frase, span, idc in (
            ("Nesse sentido, a Rec1amação 54.321/RJ fixou a orientação.", "Rec1amação 54.321/RJ", 401),
            ("Nesse sentido, o Recurso Espec1al nº 1.234.567/SP fixou.", "Recurso Espec1al nº 1.234.567/SP", 100),
            ("Nesse sentido, o Agravo 1nterno no REsp 2.345.678/PR fixou.", "Agravo 1nterno no REsp 2.345.678/PR", 101),
            ("Nesse sentido, o Recurso Espec|al nº 1.234.567/SP fixou.", "Recurso Espec|al nº 1.234.567/SP", 100),
        ):
            with self.subTest(frase=frase):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual(a.trecho, span)
                self.assertEqual((d.classificacao, d.id_canonico), ("real", idc), d)

    def test_a_inicial_continua_literal(self) -> None:
        nenhum("Nesse sentido, a 1eclamação 54.321/RJ fixou a orientação.")   # inicial nunca sofre OCR


# ---------------------------------------------------------------------------
# R6-13 / R4-04 — cabeçalho: arquivo todo em linhas curtas; ementa longa; parte com travessão
# ---------------------------------------------------------------------------
class TestCabecalho(unittest.TestCase):
    def test_arquivo_em_45_colunas_com_citacao_na_segunda_linha(self) -> None:   # R6-13
        texto = ("Cuida-se de habeas corpus.\nInvoca-se a Súmula 123 do STJ.\n"
                 "A impetração sustenta que a prisão preventiva\ncarece de fundamentação idônea, pois o\n"
                 "decreto não indica fatos concretos que a\njustifiquem, como exige a jurisprudência.\n")
        self.assertEqual(T.fim_do_cabecalho(texto), 0)
        self.assertEqual([a.trecho for a in detectar(texto)], ["Súmula 123 do STJ"])

    def test_ementa_longa_antes_do_acordao_e_cabecalho(self) -> None:   # R4-04
        ementa = ("EMENTA: AGRAVO INTERNO NO RECURSO ESPECIAL. PROCESSUAL CIVIL. AUSÊNCIA DE PREQUESTIONAMENTO. "
                  "SÚMULA 123/STJ. REEXAME DE PROVAS. SÚMULA 456/TST. DISSÍDIO NÃO DEMONSTRADO. AGRAVO DESPROVIDO. ") * 8
        texto = ("TRIBUNAL DE JUSTIÇA\n\nApelação Cível nº 1234567-89.2021.8.26.0114\nApelante: Fulano\nApelada: Empresa X\n\n"
                 + ementa + "\n\nACÓRDÃO\n\n" + PROSA + "Aplica-se a Súmula 123 do STJ ao caso.\n")
        fim = T.fim_do_cabecalho(texto)
        self.assertGreater(fim, texto.index("ACÓRDÃO"))
        self.assertEqual([a.trecho for a in detectar(texto)], ["Súmula 123 do STJ"])

    def test_parte_com_travessao_e_cabecalho(self) -> None:   # R4-04
        texto = ("Recorrente – Fulano de Tal, brasileiro, casado, advogado, inscrito na OAB sob o nº 123.456\n"
                 "Apelação Cível nº 1234567-89.2021.8.26.0114\nRelator: Des. Fulano\n\n" + PROSA
                 + "Aplica-se a Súmula 123 do STJ ao caso.\n")
        self.assertGreaterEqual(T.fim_do_cabecalho(texto), texto.index("Trata-se"))
        self.assertEqual([a.trecho for a in detectar(texto)], ["Súmula 123 do STJ"])

    def test_ementa_em_caixa_mista_com_rotulo_tambem_e_cabecalho(self) -> None:   # R4-04 (uma só política)
        for rotulo in ("EMENTA: ", "Ementa: "):
            texto = ("TRIBUNAL\n\nAutos nº 1234567-89.2021.8.26.0100\n\n" + rotulo
                     + "Apelação. Estelionato. Materialidade comprovada. Súmula 123 do STJ. Recurso conhecido e desprovido.\n\n"
                     + PROSA + "Aplica-se a Súmula 456 do TST ao caso.\n")
            with self.subTest(rotulo=rotulo):
                self.assertEqual([a.trecho for a in detectar(texto)], ["Súmula 456 do TST"])


# ---------------------------------------------------------------------------
# R6-14 — o nome do relator para em inícios de frase depois da quebra, em ``Palavra:`` e em ``e Outros``
# ---------------------------------------------------------------------------
class TestFronteiraDoNomeDoRelator(unittest.TestCase):
    def test_paradas(self) -> None:
        for frase, relator in (
            (f"Confira-se o acórdão do STJ de 2019, Rel. Min. {N}\nImportante notar que a Corte decidiu.", N),
            (f"Confira-se o acórdão do STJ de 2019, Rel. Min. {N}\nHouve, ainda, outra decisão.", N),
            (f"Confira-se o acórdão do STJ de 2019, Rel. Min. {N}\nBrasília, 12 de março de 2019.", N),
            (f"Confira-se o acórdão do STJ de 2019, Rel. Min. {N} Julgamento: 12/03/2019, que decidiu.", N),
            (f"Confira-se o acórdão do STJ de 2019, Rel. Min. {N} e Outros, que decidiu.", N),
            (f"Confira-se o acórdão do STJ de 2019, Rel. Min. {N}\nUnânime. Nada mais.", N),
            # quebra DENTRO do nome continua aceita (mutação medida no dev)
            ("Confira-se o acórdão do STJ de 2019, Rel. Min. Fulano\nBeltrano, que decidiu.", "Fulano Beltrano"),
        ):
            with self.subTest(frase=frase):
                a = um(frase)
                self.assertEqual(a.dados["relator"], relator)
                self.assertTrue(a.trecho.endswith("Beltrano"), a.trecho)


# ---------------------------------------------------------------------------
# R6-15 / R4-10 / R4-03 — calibração: caminho-irmão sem ``ocr_reparado``; prior de ``:unica``
# ---------------------------------------------------------------------------
class TestCalibracaoCaminhoIrmao(Base):
    def test_chaves_de_consulta_tentam_o_irmao_antes_do_prefixo(self) -> None:
        chaves = cal.chaves_de_consulta("processo:ocr_reparado:1cand:uf_incompativel")
        self.assertEqual(chaves[:2], ["processo:ocr_reparado:1cand:uf_incompativel", "processo:1cand:uf_incompativel"])
        self.assertLess(chaves.index("processo:1cand:uf_incompativel"), chaves.index("processo:ocr_reparado:1cand"))
        self.assertEqual(cal.chaves_de_consulta("processo:1cand:cadeia_exata"),
                         ["processo:1cand:cadeia_exata", "processo:1cand", "processo"])

    def test_uf_incompativel_apos_reparo_herda_do_irmao(self) -> None:
        a, d = self.ponta_a_ponta("Veja-se o REsp l.234.567/RJ, que decidiu.")
        self.assertEqual((d.classificacao, d.caminho), ("inventada", "processo:ocr_reparado:1cand:uf_incompativel"))
        tabela = {"processo:ocr_reparado:1cand": 0.978, "processo:1cand:uf_incompativel": 0.70, "processo": 0.85}
        self.assertAlmostEqual(cal.confianca(d, a, tabela), 0.70)
        # com a tabela versionada o valor também é o do irmão
        versionada = cal.carregar(RAIZ / "dados" / "calibracao.json")
        if versionada:
            self.assertLess(cal.confianca(d, a, versionada), 0.8)

    def test_prior_de_vaga_unica(self) -> None:   # R4-10
        self.assertGreaterEqual(cal.TABELA_INICIAL["vaga:incompleta:unica"], 0.9)
        self.assertEqual(cal.TABELA_INICIAL["processo:1cand:classe_divergente:sem_uf"], 0.5)   # R4-03


# ---------------------------------------------------------------------------
# R6-16 — ``Tema N`` solto: só com indício jurisprudencial na mesma frase
# ---------------------------------------------------------------------------
class TestTemaSolto(Base):
    def test_com_indicio_emite_e_sem_indicio_descarta(self) -> None:
        citacoes, _ = self.emitidas("Como fixado no Tema 999, a tese vincula os demais órgãos.")
        self.assertEqual([(c.trecho, c.classificacao) for c in citacoes], [("Tema 999", "inventada")])
        citacoes, _ = self.emitidas("O Tema 999 e o Tema Repetitivo 998 foram afetados em 2019.")
        self.assertEqual([(c.trecho, c.classificacao) for c in citacoes], [("Tema 999", "inventada"), ("Tema Repetitivo 998", "inventada")])
        for frase in ("Passa-se ao Tema 999: Da prescrição da pretensão, conforme exposto.",
                      "Veja-se o item 3 do sumário. Tema 999. A prescrição corre em dobro."):
            with self.subTest(frase=frase):
                citacoes, rastros = self.emitidas(frase)
                self.assertEqual(citacoes, [])
                self.assertTrue(any(r.achado.familia == "tema" and r.status == "descartada:resolucao" for r in rastros))

    def test_tema_repetitivo_tem_complemento(self) -> None:
        a = um("O Tema Repetitivo 999 foi afetado.")
        self.assertEqual((a.trecho, a.forca, a.dados["tribunal"]), ("Tema Repetitivo 999", 1.0, "STJ"))
        a = um("Veja-se o Tema 999 de repercussão geral, que decidiu.")   # R4-07: ``de`` no complemento
        self.assertEqual((a.trecho, a.forca), ("Tema 999 de repercussão geral", 1.0))


# ---------------------------------------------------------------------------
# R4-05 — ``vaga:amplo`` como cabeça de uma citação numerada
# ---------------------------------------------------------------------------
class TestVagaCabecaDeCitacaoNumerada(Base):
    def test_amplo_seguido_do_numero_entre_parenteses_e_a_mesma_citacao(self) -> None:
        citacoes, rastros = self.emitidas(
            f"O acórdão do STJ firmou a tese em 2019, sob a relatoria do Ministro {N} (REsp 1.234.567/SP), e assim se decidiu.")
        self.assertEqual([(c.trecho, c.classificacao) for c in citacoes], [("REsp 1.234.567/SP", "real")])
        # o molde estrito (sem parêntese e sem número) continua a valer como citação vaga
        citacoes, _ = self.emitidas(f"O acórdão do STJ de 2019, sob a relatoria do Ministro {N}, firmou a tese.")
        self.assertEqual([c.classificacao for c in citacoes], ["incompleta"])


# ---------------------------------------------------------------------------
# Engenharia — R3q-04 (regex linear), R3q-05 (cp1252 × UTF-8 com byte espúrio), R3q-07, R3q-08
# ---------------------------------------------------------------------------
class TestEngenharia(unittest.TestCase):
    def test_linha_gigante_de_minusculas_e_linear(self) -> None:   # R3q-04
        texto = "x" * 100_000 + " " + doc("Aplica-se a Súmula 123 do STJ.")
        t0 = time.perf_counter()
        achados = detectar(texto)
        self.assertLess(time.perf_counter() - t0, 2.0)
        self.assertIn("Súmula 123 do STJ", [a.trecho for a in achados])
        t0 = time.perf_counter()
        T.e_linha_de_prosa("a" * 200_000 + "!")
        self.assertLess(time.perf_counter() - t0, 1.0)

    def test_utf8_com_um_byte_espurio_nao_desloca_offsets(self) -> None:   # R3q-05
        conteudo = "Súmula 123 do STJ e art. 11 da CF, ação.\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "misto.txt"
            p.write_bytes(conteudo.encode("utf-8") + b"Observa\xe7\xe3o final.\n")
            texto, codificacao = T.carregar_com_codificacao(p)
            self.assertEqual(codificacao, "utf-8-replace")
            self.assertTrue(texto.startswith(conteudo))          # nenhum offset deslocado
            self.assertEqual(texto.count("�"), 2)
            # arquivo INTEIRAMENTE em cp1252 continua a ser lido como cp1252 (R3e-08)
            p.write_bytes(conteudo.encode("cp1252"))
            texto, codificacao = T.carregar_com_codificacao(p)
            self.assertEqual((texto, codificacao), (conteudo, "cp1252"))

    def test_dockerignore_cobre_subpastas(self) -> None:   # R3q-07
        linhas = (RAIZ / ".dockerignore").read_text(encoding="utf-8").split("\n")
        self.assertIn("**/__pycache__/", linhas)
        self.assertIn("**/*.pyc", linhas)

    def test_arquivos_ocultos_sao_ignorados_e_lote_vazio_da_codigo_2(self) -> None:   # R3q-08
        from caca_alucinacao.cli import main
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d) / "in"
            pasta.mkdir()
            (pasta / "doc.txt").write_text("x", encoding="utf-8")
            (pasta / ".oculto.txt").write_text("x", encoding="utf-8")
            (pasta / "._doc.txt").write_text("x", encoding="utf-8")
            with self.assertLogs("caca_alucinacao.pipeline", level="WARNING"):
                self.assertEqual([p.name for p in listar_documentos(pasta)], ["doc.txt"])
            vazia = Path(d) / "vazia"
            vazia.mkdir()
            (vazia / "txt").mkdir()
            (vazia / "txt" / "a.txt").write_text("x", encoding="utf-8")
            with self.assertLogs("caca_alucinacao", level="ERROR"):
                codigo = main(["--input", str(vazia), "--output", str(Path(d) / "out"), "--db", str(Path(d) / "nao.db"),
                               "--indice", str(Path(d) / "nao.json"), "--arbitro", "nenhum", "--log-level", "ERROR"])
            self.assertEqual(codigo, 2)

    def test_geradores_adversariais_versionados(self) -> None:   # R3q-06
        pasta = RAIZ / "scripts" / "adversarial"
        for nome in ("gerar_adversarial.py", "gerar_adversarial_r2.py", "gerar_adversarial_r3.py",
                     "gerar_adversarial_r4.py", "gerar_adversarial_r5.py", "erros.py", "rodar_todos.sh"):
            self.assertTrue((pasta / nome).exists(), nome)
        fonte = (pasta / "gerar_adversarial.py").read_text(encoding="utf-8")
        self.assertIn("def artigo_k", fonte)
        self.assertIn("def sumula_k", fonte)


if __name__ == "__main__":
    unittest.main()


class TestSondaDeEscritaSemUnlink(unittest.TestCase):
    """Pasta que permite criar mas não apagar (mount sincronizado/sandbox) ainda é gravável."""

    def test_falha_ao_apagar_a_sonda_nao_impede_o_pipeline(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from caca_alucinacao.pipeline import preparar_saida

        with tempfile.TemporaryDirectory() as d:
            alvo = Path(d) / "saida"
            with mock.patch.object(Path, "unlink", side_effect=PermissionError(1, "Operation not permitted")):
                with self.assertLogs("caca_alucinacao.pipeline", level="WARNING") as cm:
                    self.assertTrue(preparar_saida(alvo).is_dir())
            self.assertTrue(any("permite escrever mas não apagar" in m for m in cm.output))
            self.assertTrue((alvo / ".caca_escrita_ok").exists())
