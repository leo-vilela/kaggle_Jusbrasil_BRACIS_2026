"""Testes das correções da revisão (rodada 2) — um bloco por achado, todos sintéticos.

Cada classe cita o(s) achado(s) que cobre: R4-xx (correção = revisor 1; generalização =
revisor 2) e R3b-xx (engenharia). Base canônica FALSA (``tests/test_resolucao.INDICE_FALSO``);
nenhum número, nome ou trecho do gabarito ou da base real.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from test_resolucao import INDICE_FALSO  # noqa: E402

from caca_alucinacao.base_canonica import BaseCanonica  # noqa: E402
from caca_alucinacao.deteccao import detectar  # noqa: E402
from caca_alucinacao.deteccao import padroes as P  # noqa: E402
from caca_alucinacao.deteccao.sumula import numero_com_ocr  # noqa: E402
from caca_alucinacao.deteccao.vaga import ano_canonico  # noqa: E402
from caca_alucinacao.normalizacao import cadeia_de_classes, digitos_do_identificador, nucleos  # noqa: E402
from caca_alucinacao.resolucao import chaves_alternativas, resolver  # noqa: E402
from caca_alucinacao.texto import fim_do_cabecalho  # noqa: E402
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

    def assertReal(self, d: Decisao, idc: int, caminho: str | None = None) -> None:
        self.assertEqual(d.classificacao, "real", d)
        self.assertEqual(d.id_canonico, idc, d)
        if caminho:
            self.assertEqual(d.caminho, caminho, d)

    def assertInventada(self, d: Decisao, prefixo: str = "") -> None:
        self.assertEqual(d.classificacao, "inventada", d)
        self.assertIsNone(d.id_canonico)
        self.assertTrue(d.caminho.startswith(prefixo), d)


# ---------------------------------------------------------------------------
# R4-01 (crítica, generalização) — grupo final todo em letras de OCR: nunca chave parcial
# ---------------------------------------------------------------------------
class TestGrupoFinalTodoOcr(Base):
    def test_span_consome_o_grupo_e_a_chave_fica_vazia(self) -> None:
        a = um("Invoca-se a Rcl 12.345.OSl/SP, julgada.")
        self.assertEqual(a.trecho, "Rcl 12.345.OSl/SP")
        self.assertEqual(a.dados["digitos"], "")      # nunca "12345"
        self.assertEqual(a.dados["uf"], "SP")

    def test_nucleos_marca_ambiguo(self) -> None:
        n = nucleos("Rcl 12.345.OSl")
        self.assertEqual(len(n), 1)
        self.assertTrue(n[0].ambiguo)
        self.assertEqual(n[0].bruto, "12.345.OSl")
        self.assertEqual(digitos_do_identificador("Rcl 12.345.OSl/SP"), "")
        self.assertEqual(chaves_alternativas("Rcl 12.345.OSl"), [("relaxado", "12345051")])

    def test_inventada_com_prefixo_real_nao_vira_real(self) -> None:
        # 12345 é número próprio de dois registros da base falsa: com "1.234.OSl" nunca se
        # consulta o prefixo; a conversão relaxada (1234051) não tem dono → inventada
        for frase in ("Invoca-se a Rcl 12.345.OSl/SP, julgada.", "Invoca-se o RHC 12.345.gOS/RJ, julgado.",
                      "Invoca-se o REsp 1.234.lSG/SP, julgado."):
            with self.subTest(frase=frase):
                _a, d = self.ponta_a_ponta(frase)
                self.assertInventada(d, "processo:0cand:ocr_")

    def test_real_com_grupo_final_todo_ocr_e_reparada(self) -> None:
        _a, d = self.ponta_a_ponta("Invoca-se o REsp 1.234.SG7/SP, julgado.")   # 567 → SG7
        self.assertReal(d, 100, "processo:ocr_reparado:1cand:cadeia_exata")

    def test_grupo_do_meio_com_tres_letras(self) -> None:
        a = um("Invoca-se o REsp 1.OSl.567/SP, julgado.")
        self.assertEqual((a.trecho, a.dados["digitos"]), ("REsp 1.OSl.567/SP", ""))
        self.assertEqual(chaves_alternativas("REsp 1.OSl.567"), [("relaxado", "1051567")])
        self.assertInventada(resolver(a, self.base), "processo:0cand:ocr_")

    def test_fim_de_frase_e_uf_nao_sao_grupo(self) -> None:
        self.assertEqual(um("Invoca-se o REsp 1.234.567. O recurso foi provido.").trecho, "REsp 1.234.567")
        a = um("Invoca-se o REsp 1.234.567-GO, julgado.")
        self.assertEqual((a.trecho, a.dados["uf"], a.dados["digitos"]), ("REsp 1.234.567-GO", "GO", "1234567"))
        a = um("Invoca-se o REsp 1.234.567 - SE, julgado.")
        self.assertEqual((a.dados["uf"], a.dados["digitos"]), ("SE", "1234567"))

    def test_cnj_com_ultimo_segmento_todo_ocr(self) -> None:
        a = um("Invoca-se o RR 123-45.2015.5.15.OOgg, julgado.")
        self.assertEqual(a.trecho, "RR 123-45.2015.5.15.OOgg")
        self.assertEqual(a.dados["digitos"], "")
        self.assertEqual(chaves_alternativas("RR 123-45.2015.5.15.OOgg"), [("relaxado", "00001234520155150099")])


# ---------------------------------------------------------------------------
# R4-02 (crítica) / R4-01 (correção) — OCR no número da súmula, do tema, do artigo e do ano
# ---------------------------------------------------------------------------
class TestOcrEmSumula(Base):
    def test_numero_com_ocr(self) -> None:
        self.assertEqual(numero_com_ocr("8l"), ("81", 1))
        self.assertEqual(numero_com_ocr("l0"), ("10", 1))
        self.assertEqual(numero_com_ocr("1.234"), ("1234", 0))
        self.assertEqual(numero_com_ocr("lO"), ("", 2))

    def test_span_nunca_para_no_prefixo(self) -> None:
        a = um("Aplica-se a Súmula 12S do STJ ao caso.")
        self.assertEqual((a.trecho, a.dados["numero_sumula"], a.dados["letras_ocr"]), ("Súmula 12S do STJ", "125", "1"))
        a = um("Aplica-se a Súmula Vinculante l2, que foi assim.")
        self.assertEqual((a.trecho, a.dados["numero_sumula"]), ("Súmula Vinculante l2", "12"))
        self.assertEqual(um("Aplica-se a SV 4S, assim.").dados["numero_sumula"], "45")

    def test_inventada_com_prefixo_na_tabela_continua_inventada(self) -> None:
        # Súmula 12 do STJ não existe na base falsa, mas 123 existe: "12S" (125) e "123l" (1231) nunca casam 12/123
        for frase in ("Aplica-se a Súmula 12S do STJ.", "Aplica-se a Súmula 123l do STJ."):
            with self.subTest(frase=frase):
                _a, d = self.ponta_a_ponta(frase)
                self.assertInventada(d, "sumula:fora_da_tabela")
                self.assertTrue(d.caminho.endswith(":ocr"), d)

    def test_real_com_ocr_e_real_com_caminho_ocr(self) -> None:
        _a, d = self.ponta_a_ponta("Aplica-se a Súmula l23 do STJ.")
        self.assertReal(d, 900, "sumula:na_tabela:ocr")
        _a, d = self.ponta_a_ponta("Aplica-se a Súmula Vinculante 4S.")
        self.assertReal(d, 901, "sumula:na_tabela:tribunal_implicito:ocr")
        _a, d = self.ponta_a_ponta("Aplica-se a Súmula 45G do TST.")
        self.assertReal(d, 902, "sumula:na_tabela:ocr")
        _a, d = self.ponta_a_ponta("Aplica-se a Súmula 123 do STJ.")
        self.assertReal(d, 900, "sumula:na_tabela")   # sem OCR não há sufixo


class TestFallbackDoResolvedorNuncaTrunca(Base):
    """O resolvedor lê o número do trecho quando o achado chega SEM dados do detector (span
    devolvido pelo árbitro, medição a partir do gabarito): ``normativos.sumula_canonica`` e
    ``artigo_canonico`` também precisam ler o número inteiro ou nada (R4-02, revisor 2)."""

    def test_parsers(self) -> None:
        from caca_alucinacao.base_canonica.normativos import artigo_canonico, sumula_canonica
        self.assertEqual(sumula_canonica("Súmula 8l do STJ"), ("STJ", False, 81))
        self.assertEqual(sumula_canonica("Súmula\nVinculante 1O"), ("STF", True, 10))
        self.assertEqual(sumula_canonica("Súmula 12S do STJ"), ("STJ", False, 125))
        self.assertEqual(sumula_canonica("Súmula l2 do STJ"), ("STJ", False, 12))
        self.assertEqual(sumula_canonica("Súmula lS do STJ"), ("STJ", False, None))   # sem dígito: nada
        self.assertEqual(sumula_canonica("Súmula Impeditiva 3"), (None, False, None))
        self.assertEqual(artigo_canonico("art. 12G da CLT"), "126")
        self.assertEqual(artigo_canonico("art. 5o do CPC"), "5")      # ordinal, não OCR
        self.assertEqual(artigo_canonico("art. l40 do CC"), "140")
        self.assertEqual(artigo_canonico("ART. 240 DO CPM"), "240")

    def test_achado_sem_dados_do_detector(self) -> None:
        # Súmula 12 do STJ não existe na base falsa, mas 123 existe; SV 4 não, SV 45 sim
        for trecho, esperado in (("Súmula 12S do STJ", "inventada"), ("Súmula 123l do STJ", "inventada"),
                                 ("Súmula l23 do STJ", "real"), ("Súmula Vinculante 4S", "real"),
                                 ("Súmula Vinculante 4l", "inventada")):
            with self.subTest(trecho=trecho):
                a = Achado(inicio=0, fim=len(trecho), trecho=trecho, familia="sumula", tipo="jurisprudencia",
                           dados={}, origem="llm:classificar_span", forca=0.9)
                d = resolver(a, self.base)
                self.assertEqual(d.classificacao, esperado, d)
                if esperado == "real":
                    self.assertIn(d.id_canonico, (900, 901))
        a = Achado(inicio=0, fim=16, trecho="art. 32l do CPC", familia="dispositivo", tipo="lei", dados={},
                   origem="llm:classificar_span", forca=0.9)
        self.assertReal(resolver(a, self.base), 950)


class TestOcrEmTemaEArtigo(Base):
    def test_tema(self) -> None:
        a = um("Aplica-se o Tema l.234 da repercussão geral.")
        self.assertEqual((a.trecho, a.dados["numero_tema"], a.forca), ("Tema l.234 da repercussão geral", "1234", 1.0))
        a = um("Aplica-se o Tema 1.234 da repercüssão geral, que foi assim.")   # R4-03 (correção)
        self.assertEqual(a.trecho, "Tema 1.234 da repercüssão geral")
        self.assertEqual(um("Aplica-se o Tema 987 d0 STF.").trecho, "Tema 987 d0 STF")

    def test_artigo_com_ocr_no_fim_inicio_e_meio(self) -> None:
        _a, d = self.ponta_a_ponta("Nos termos do art. 32l do CPC, decidiu-se.")
        self.assertReal(d, 950, "dispositivo:na_tabela:ocr")
        _a, d = self.ponta_a_ponta("Nos termos do art. l1 da CF, decidiu-se.")
        self.assertReal(d, 951, "dispositivo:na_tabela:ocr")
        _a, d = self.ponta_a_ponta("Nos termos do art. 24O do Código Penal Militar, decidiu-se.")
        self.assertReal(d, 952, "dispositivo:na_tabela:ocr")
        a, d = self.ponta_a_ponta("Nos termos do art. 11G da CF, decidiu-se.")   # 116: prefixo 11 está na tabela
        self.assertEqual(a.dados["artigo"], "116")
        self.assertInventada(d, "dispositivo:fora_da_tabela")

    def test_ordinal_o_nao_e_ocr(self) -> None:
        self.assertEqual(um("O art. 5o do CPC se aplica.").dados["artigo"], "5")
        self.assertEqual(um("O art. 5.º do CPC se aplica.").dados["artigo"], "5")
        self.assertEqual(um("O art. 1O26 do CPC se aplica.").dados["artigo"], "1026")

    def test_artigo_so_de_letras_com_diploma(self) -> None:
        self.assertEqual(um("O art. g do Código Penal Militar.").dados["artigo"], "9")
        nenhum("Nos termos do art. l, o autor decaiu.")   # sem diploma: amplo, descartado


class TestAnoComOcrNaVaga(Base):
    def test_ano_canonico(self) -> None:
        self.assertEqual(ano_canonico("2O21"), "2021")
        self.assertEqual(ano_canonico("20l9"), "2019")
        self.assertIsNone(ano_canonico("lOgO"))   # menos de 2 dígitos reais

    def test_vaga_com_ano_ocr(self) -> None:
        a = um("Como decidido no julgado do STF proferido em 2O21 pela relatoria de Fulana Tal, foi assim.")
        self.assertEqual((a.trecho, a.dados["ano"], a.forca),
                         ("julgado do STF proferido em 2O21 pela relatoria de Fulana Tal", "2021", 1.0))
        d = resolver(a, self.base)
        self.assertEqual(d.classificacao, "incompleta")


# ---------------------------------------------------------------------------
# R4-03 (correção) / R4-07 — palavras de ligação com OCR e caixa alta
# ---------------------------------------------------------------------------
class TestPreposicaoOcrECaixaAlta(Base):
    def test_dispositivo(self) -> None:
        self.assertEqual(um("Nos termos do art. 321 d0 CPC, decidiu-se.").trecho, "art. 321 d0 CPC")
        self.assertEqual(um("Nos termos do art. 11 dã Constituição Federal, decidiu-se.").trecho,
                         "art. 11 dã Constituição Federal")
        a, d = self.ponta_a_ponta("O ART. 11 DA CONSTITUIÇÃO FEDERAL se aplica.")
        self.assertEqual(a.trecho, "ART. 11 DA CONSTITUIÇÃO FEDERAL")
        self.assertReal(d, 951, "dispositivo:na_tabela")
        self.assertEqual(um("ART. 240 DO CÓDIGO PENAL MILITAR se aplica.").trecho, "ART. 240 DO CÓDIGO PENAL MILITAR")

    def test_sumula(self) -> None:
        a, d = self.ponta_a_ponta("SÚMULA Nº 123 DO STJ impede.")
        self.assertEqual(a.trecho, "SÚMULA Nº 123 DO STJ")
        self.assertReal(d, 900, "sumula:na_tabela")


# ---------------------------------------------------------------------------
# R4-04 (correção) — vaga:amplo em prosa sem substantivo; parêntese fechado
# ---------------------------------------------------------------------------
class TestVagaAmploSemSubstantivo(Base):
    def test_prosa_sobre_o_tribunal_e_descartada(self) -> None:
        for frase in ("O Superior Tribunal de Justiça, já em 2019, pela relatoria do Ministro Fulano Tal, assentou a tese.",
                      "Como assentado pelo STJ em 2019 (Rel. Min. Fulano Tal), a tese não prospera."):
            with self.subTest(frase=frase):
                a = um(frase)
                self.assertEqual((a.origem, a.forca, a.dados["sem_substantivo"]), ("regex:vaga:amplo", 0.4, "1"))
                d = resolver(a, self.base)
                self.assertEqual(d.detalhes.get("descartar"), "1")

    def test_com_substantivo_fecha_o_parentese(self) -> None:
        a = um("A decisão do STJ em 2020 (Rel. Min. Fulano de Tal), a tese.")   # relator/ano da base falsa
        self.assertEqual((a.trecho, a.forca), ("decisão do STJ em 2020 (Rel. Min. Fulano de Tal)", 0.6))
        d = resolver(a, self.base)
        self.assertEqual((d.classificacao, d.detalhes.get("descartar")), ("incompleta", None))


# ---------------------------------------------------------------------------
# R4-04 / R4-11 (generalização) — moldes de vaga com outra redação
# ---------------------------------------------------------------------------
class TestMoldesDeVaga(Base):
    N = "Fulana Zéfira"
    CASOS = [
        (f"julgado de 2023 do TST, Rel. Min. {N}", "ano_antes_tribunal"),
        (f"precedente de 2017 do TST, da relatoria de {N}", "ano_antes_tribunal"),
        (f"julgado do TST de 2023, Rel.ª Min.ª {N}", "H"),
        (f"julgado do TST de 2023, Relª. Minª. {N}", "H"),
        (f"julgado do TST de 2023 cujo relator foi o Ministro {N}", "H"),
        (f"julgado do TST proferido em 2023 pela relatoria do e. Min. {N}", "A"),
        (f"julgado do TST proferido em 2023 pela relatoria do Exmo. Min. {N}", "A"),
        (f"decisão do TST (Rel. Min. {N}, j. 2023)", "parenteses_rel"),
        (f"acórdão da Corte Especial do STJ, de 2023, Rel. Min. {N}", "E"),
        (f"acórdão da Primeira Turma do STF, de 2023, Rel. Min. {N}", "E"),
        (f"acórdão da 2ª Turma do STF, de 2023, Rel. Min. {N}", "E"),
        (f"julgado do TST de 2023 tendo como relator o Ministro {N}", "H"),
        (f"decisão do STJ (2023), Rel. Min. {N}", "F"),
        (f"entendimento firmado pelo TST em 2023, sob a relatoria do Min. {N}", "outro"),
        (f"acórdão proferido pelo TST em 2023, da relatoria do Ministro {N}", "E"),
        (f"decisão proferida pelo STM em 2023, de relatoria do Ministro {N}", "F"),
        (f"julgado do Eg. STJ de 2023, Rel. Min. {N}", "H"),
    ]

    def test_moldes(self) -> None:
        for trecho, molde in self.CASOS:
            with self.subTest(trecho=trecho):
                a = um(f"Invoca-se o {trecho}, que decidiu igual.")
                self.assertEqual(a.trecho, trecho)
                self.assertEqual(a.origem, f"regex:vaga:{molde}")
                self.assertEqual(a.forca, 1.0)
                self.assertEqual(a.dados["relator"], self.N)
                self.assertEqual(a.dados["ano"], "2023" if "2023" in trecho else "2017")
                self.assertEqual(resolver(a, self.base).classificacao, "incompleta")

    def test_honorifico_fica_fora_do_nome(self) -> None:
        a = um(f"O julgado do TST proferido em 2023 pela relatoria do Exmo. Min. {self.N}, assim.")
        self.assertEqual(a.dados["relator"], self.N)

    def test_nome_seguido_de_inicio_de_frase_apos_quebra(self) -> None:
        a = um(f"Confira-se o julgado do TST proferido em 2023 pela relatoria de {self.N}\nQuanto ao mais, nada.")
        self.assertEqual(a.dados["relator"], self.N)
        a = um("Confira-se o julgado do TST proferido em 2023 pela relatoria de Fulana\nZéfira, que decidiu.")
        self.assertEqual(a.dados["relator"], "Fulana Zéfira")

    def test_armadilhas_continuam_fora(self) -> None:
        nenhum("Como destacou o Ministro relator, a controvérsia é de direito.")
        nenhum("Em 2019 o STJ consolidou a tese em diversos julgados.")
        nenhum("A Primeira Turma do STF, em 2022, reafirmou a orientação.")


# ---------------------------------------------------------------------------
# R4-05 / R4-15 (generalização) — dois-pontos, nº., estilo de ementa, plural, tribunal no meio
# ---------------------------------------------------------------------------
class TestFormasDeProcesso(Base):
    def test_dois_pontos_e_ponto_apos_ordinal(self) -> None:
        for frase, esperado in (("Invoca-se o REsp: 1.234.567/SP, julgado.", "REsp: 1.234.567/SP"),
                                ("Invoca-se o REsp nº. 1.234.567/SP, julgado.", "REsp nº. 1.234.567/SP"),
                                ("Invoca-se o AgInt no REsp: 2.345.678/PR, julgado.", "AgInt no REsp: 2.345.678/PR")):
            with self.subTest(frase=frase):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual(a.trecho, esperado)
                self.assertEqual(d.classificacao, "real")

    def test_estilo_de_ementa(self) -> None:
        achados = todos("Nesse sentido: STJ - REsp: 1234567 SP, Relator: Ministro Fulano Tal, "
                        "Data de Julgamento: 12/03/2020, T3 - TERCEIRA TURMA.")
        self.assertEqual([a.trecho for a in achados], ["REsp: 1234567 SP"])
        self.assertReal(resolver(achados[0], self.base), 100)

    def test_plural_com_enumeracao(self) -> None:
        achados = todos("Nesse sentido, os REsps 1.234.567/SP e 2.345.678/PR, ambos da Turma.")
        self.assertEqual([a.trecho for a in achados], ["REsps 1.234.567/SP", "2.345.678/PR"])
        self.assertEqual([a.dados["cadeia"] for a in achados], ["RESP", "RESP"])
        self.assertEqual(achados[1].origem, "regex:processo:enumeracao")
        self.assertEqual(resolver(achados[0], self.base).classificacao, "real")
        # sem plural o segundo número não é emitido (fronteira não medida no dev)
        # rodada 3 (R3-12): sem plural, o segundo número com o MESMO formato e UF também abre a enumeração
        self.assertEqual([a.trecho for a in todos("Invoca-se o REsp 1.234.567/SP e 2.345.678/PR.")],
                         ["REsp 1.234.567/SP", "2.345.678/PR"])

    def test_tribunal_entre_a_classe_e_o_numero(self) -> None:
        a, d = self.ponta_a_ponta("Invoca-se a Reclamação do STF nº 12.345, de 2022, Rel. Min. Fulana Tal, assim.")
        self.assertEqual(a.trecho, "Reclamação do STF nº 12.345")
        self.assertEqual((a.dados["tribunal"], a.dados["tribunal_fonte"]), ("STF", "explicito"))
        self.assertReal(d, 400)   # o tribunal explícito elimina o RHC 12.345 do STJ

    def test_prefixo_tst_com_ocr(self) -> None:
        a = um("Invoca-se o T5T-RR-123-45.2015.5.15.0099, julgado.")
        self.assertEqual(a.trecho, "T5T-RR-123-45.2015.5.15.0099")
        self.assertEqual(a.dados["tribunal_fonte"], "explicito")

    def test_emb_div_e_emb_infr(self) -> None:   # R4-05 (correção)
        a = um("Invoca-se o AG.REG. NOS EMB.DIV. NOS EMB.DECL. NO SEGUNDO AG.REG. NO RECURSO EXTRAORDINÁRIO "
               "COM AGRAVO 1.234.567/SP, que foi assim.")
        self.assertEqual(a.dados["cadeia"], "AGR EDV ED 2O AGR ARE")
        self.assertEqual(cadeia_de_classes("Emb.Infr. na APL"), ["EI", "APL"])

    def test_registro_depois_da_uf(self) -> None:   # R4-07 (correção)
        a, d = self.ponta_a_ponta("Invoca-se o REsp 1.234.567 - SP (2019/0123456-7), que foi assim.")
        self.assertEqual(a.trecho, "REsp 1.234.567 - SP (2019/0123456-7)")
        self.assertEqual(a.dados["registro"], "201901234567")
        self.assertReal(d, 100)
        a, d = self.ponta_a_ponta("Invoca-se o REsp 9.876.543 - SP (2019/0123456-7), que foi assim.")
        self.assertInventada(d, "processo:0cand:registro_diverge")   # número inventado, registro real


# ---------------------------------------------------------------------------
# R4-08 / R4-12 (generalização) — OCR no nome por extenso; classes de 2º grau
# ---------------------------------------------------------------------------
class TestNomePorExtensoComOcr(Base):
    def test_cadeia_tolerante(self) -> None:
        self.assertEqual(cadeia_de_classes("Recurso Espccial"), ["RESP"])
        self.assertEqual(cadeia_de_classes("Rccurso Especial"), ["RESP"])
        self.assertEqual(cadeia_de_classes("Agravo Intcrno no Recurso Especlal"), ["AGINT", "RESP"])
        self.assertEqual(cadeia_de_classes("Rcclamação"), ["RCL"])
        self.assertEqual(cadeia_de_classes("REsps"), ["RESP"])
        self.assertEqual(cadeia_de_classes("recursos especiais"), ["RESP"])   # plural é alias desde a rodada 4 (R6-02)

    def test_forca_um_e_cadeia_exata(self) -> None:
        a, d = self.ponta_a_ponta("Invoca-se o Recurso Espccial nº 1.234.567/SP, julgado.")
        self.assertEqual((a.origem, a.forca, a.dados["cadeia"]), ("regex:processo", 1.0, "RESP"))
        self.assertReal(d, 100, "processo:1cand:cadeia_exata")

    def test_apelacao_civel_e_detectada_como_inventada(self) -> None:
        a, d = self.ponta_a_ponta("A Apelação Cível nº 1001234-56.2020.8.26.0100 do TJSP decidiu.")
        self.assertEqual(a.trecho, "Apelação Cível nº 1001234-56.2020.8.26.0100")
        self.assertEqual(a.dados["cadeia"], "APC")
        self.assertInventada(d, "processo:0cand")


# ---------------------------------------------------------------------------
# R4-09 / R4-10 / R4-13 / R4-16 (generalização) — súmula minúscula, item, separadores, órgão externo
# ---------------------------------------------------------------------------
class TestFormasDeSumula(Base):
    def test_minuscula_so_com_conector_ou_tribunal(self) -> None:
        self.assertEqual(um("A súmula 123 do STJ impede.").trecho, "súmula 123 do STJ")
        self.assertEqual(um("A súmula nº 123 do STJ impede.").trecho, "súmula nº 123 do STJ")
        nenhum("A súmula 123 impede o recurso.")

    def test_item_e_separadores_entram_no_span(self) -> None:
        for frase, esperado in (("A Súmula 123, IV, do STJ impede.", "Súmula 123, IV, do STJ"),
                                ("A Súmula 123, item IV, do STJ impede.", "Súmula 123, item IV, do STJ"),
                                ("A Súmula 123 (STJ) impede.", "Súmula 123 (STJ)"),
                                ("A Súmula 123 - STJ impede.", "Súmula 123 - STJ"),
                                ("A Súmula 123, do STJ impede.", "Súmula 123, do STJ"),
                                ("A Súmula 123 do Eg. STJ impede.", "Súmula 123 do Eg. STJ")):
            with self.subTest(frase=frase):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual(a.trecho, esperado)
                self.assertEqual(a.dados["tribunal"], "STJ")
                self.assertReal(d, 900, "sumula:na_tabela")   # nunca ":sem_tribunal"

    def test_enunciado_de_orgao_externo_e_descartado(self) -> None:
        achados = todos("O Enunciado nº 12 do FONAJE e o Enunciado 45 da I Jornada de Direito Civil se aplicam.")
        self.assertEqual([a.forca for a in achados], [0.5, 0.5])
        for a in achados:
            self.assertEqual(resolver(a, self.base).detalhes.get("descartar"), "1")
        # "Súmula N do <órgão>" e "Enunciado N da Súmula do STJ" não são afetados
        self.assertEqual(um("Aplica-se a Súmula 123 do STJ.").forca, 1.0)


# ---------------------------------------------------------------------------
# R4-06 (generalização) — itens: inc., alínea sem aspas, caput e §, § 8.º, parte final
# ---------------------------------------------------------------------------
class TestItensDoDispositivo(Base):
    CASOS = [
        "art. 11, inc. LV, da CF", "art. 11, incs. IX e X, da Constituição Federal", "art. 11, I, g, da CF",
        "art. 321, caput e § 1º, do CPC", "art. 321, § 1.º, do CPC", "art. 11, LV, parte final, da CF",
        "art. 11, inciso LV, da CF/88", "art. 321, parágrafo único, do CPC", "art. 11, IV, in fine, da CF",
    ]

    def test_itens(self) -> None:
        for trecho in self.CASOS:
            with self.subTest(trecho=trecho):
                a, d = self.ponta_a_ponta(f"Nos termos do {trecho}, decidiu-se.")
                self.assertEqual(a.trecho, trecho)
                self.assertEqual(d.classificacao, "real")

    def test_letra_solta_nao_e_alinea(self) -> None:
        # "o" depois da vírgula é artigo da prosa, não alínea: o estrito falha e o amplo é descartado
        a = um("O art. 5º, o qual dispõe sobre direitos, é claro.")
        self.assertEqual((a.trecho, a.origem), ("art. 5º", "regex:dispositivo:amplo"))
        self.assertEqual(resolver(a, self.base).detalhes.get("descartar"), "1")


# ---------------------------------------------------------------------------
# R4-09-a (correção) — "Relatório: …" na primeira linha de prosa
# ---------------------------------------------------------------------------
class TestTituloDeSecao(unittest.TestCase):
    def test_relatorio_dois_pontos_e_prosa(self) -> None:
        t = ("TRIBUNAL X\nAutos nº 0001234-56.2020.8.26.0100\n\nRelatório: trata-se de agravo interno contra "
             "decisão que aplicou o REsp 1.234.567/PR ao caso concreto dos autos.\nÉ o relatório. Decido conforme "
             "a jurisprudência dominante desta Corte sobre a matéria em debate.\n")
        self.assertLess(fim_do_cabecalho(t), t.index("Relatório") + 1)
        self.assertEqual([a.trecho for a in detectar(t)], ["REsp 1.234.567/PR"])

    def test_chave_valor_do_cabecalho_continua_cabecalho(self) -> None:
        t = ("TRIBUNAL X\nAutos nº 0001234-56.2020.8.26.0100\nAssunto: viabilidade da tese defendida na origem "
             "quanto ao recurso especial e seus fundamentos\n\n" + PROSA)
        self.assertGreaterEqual(fim_do_cabecalho(t), t.index("Trata-se"))


# ---------------------------------------------------------------------------
# R3b-02 (engenharia) — revisão dos pesos vazia é erro, salvo snapshot local
# ---------------------------------------------------------------------------
class TestRevisaoDoModelo(unittest.TestCase):
    def test_revisao_vazia_e_erro(self) -> None:
        import tempfile

        from caca_alucinacao.llm.arbitro import ArbitroBase, ErroDependencia

        class _Falso(ArbitroBase):
            nome = "falso"

        with self.assertRaises(ErroDependencia):
            _Falso(modelo="Org/Modelo", revisao="")
        self.assertEqual(_Falso(modelo="Org/Modelo", revisao="abc123").revisao, "abc123")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.json").write_text("{}", encoding="utf-8")
            a = _Falso(modelo=d, revisao="")
            self.assertTrue(a.revisao.startswith("local-"), a.revisao)

    def test_dockerfile_llm_exige_o_commit(self) -> None:
        texto = (RAIZ / "Dockerfile.llm").read_text(encoding="utf-8")
        self.assertIn("ARG CACA_MODELO_REVISAO", texto)
        self.assertIn("ENV CACA_MODELO_REVISAO=$CACA_MODELO_REVISAO", texto)
        self.assertIn('test -n "$CACA_MODELO_REVISAO"', texto)

    def test_revisao_fixa_e_a_mesma_em_todo_lugar(self) -> None:
        """MANIFESTO, Dockerfile.llm e modelos/revisao_fixa.env apontam para o MESMO commit de 40 hex;
        nenhum placeholder sobra (R3b-02)."""
        import re

        manifesto = (RAIZ / "MANIFESTO_MODELO.md").read_text(encoding="utf-8")
        dockerfile = (RAIZ / "Dockerfile.llm").read_text(encoding="utf-8")
        env = (RAIZ / "modelos" / "revisao_fixa.env").read_text(encoding="utf-8")
        self.assertNotIn("<PREENCHER", manifesto)
        m_env = re.search(r'^export CACA_MODELO_REVISAO="([0-9a-f]{40})"', env, re.M)
        m_doc = re.search(r'^ARG CACA_MODELO_REVISAO="([0-9a-f]{40})"', dockerfile, re.M)
        m_man = re.search(r"\| Revisão \(commit\) \| `([0-9a-f]{40})`", manifesto)
        self.assertTrue(m_env and m_doc and m_man, (m_env, m_doc, m_man))
        self.assertEqual(m_env.group(1), m_doc.group(1))
        self.assertEqual(m_env.group(1), m_man.group(1))
        self.assertIn("Qwen/Qwen2.5-7B-Instruct", env)
        self.assertIn("Qwen/Qwen2.5-7B-Instruct-AWQ", manifesto)   # alternativa também com revisão fixa
        self.assertRegex(manifesto, r"Qwen2\.5-7B-Instruct-AWQ`, revisão `[0-9a-f]{40}`")


# ---------------------------------------------------------------------------
# Regex compilam e os blocos novos existem (sanidade dos padrões)
# ---------------------------------------------------------------------------
class TestPadroes(unittest.TestCase):
    def test_blocos_novos(self) -> None:
        import re
        for bloco in (P.ANO_OCR, P.HONORIFICO, P.ORGAO_FRACIONARIO, P.RELATORIA, P.NUMERO):
            re.compile(bloco)
        self.assertTrue(re.fullmatch(P.ANO_OCR, "2O21"))
        self.assertIsNone(re.fullmatch(P.ANO_OCR, "2021a"))
        self.assertIn("EmbDiv", P.SIGLAS)
        self.assertIn("apelacao civel", P.EXTENSOS)


if __name__ == "__main__":
    unittest.main()
