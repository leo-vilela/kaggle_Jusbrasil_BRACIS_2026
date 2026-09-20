"""Testes das correções da revisão (rodada 1) — um bloco por achado, todos sintéticos.

Cada classe cita o(s) achado(s) que cobre (R1-xx correção, R2-xx generalização,
R3-xx engenharia). Base canônica FALSA (``tests/test_resolucao.INDICE_FALSO``);
nenhum número, nome ou trecho do gabarito ou da base.
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from test_resolucao import INDICE_FALSO, achado  # noqa: E402

from caca_alucinacao import texto as T  # noqa: E402
from caca_alucinacao.base_canonica import BaseCanonica  # noqa: E402
from caca_alucinacao.base_canonica.normativos import diploma_canonico  # noqa: E402
from caca_alucinacao.deteccao import detectar  # noqa: E402
from caca_alucinacao.deteccao.distratores import motivo_distrator  # noqa: E402
from caca_alucinacao.normalizacao import (  # noqa: E402
    cadeia_de_classes,
    digitos_do_identificador,
    nucleos,
    tolerante,
)
from caca_alucinacao.pipeline import (  # noqa: E402
    ErroPipeline,
    listar_documentos,
    preparar_saida,
    processar_texto,
    processar_texto_com_rastro,
)
from caca_alucinacao.resolucao import chaves_alternativas, resolver  # noqa: E402
from caca_alucinacao.tipos import Achado, Decisao  # noqa: E402

PROSA = ("Trata-se de peça processual em que a parte examina a tese defendida na origem, "
         "conforme as razões a seguir expostas.\n")
CABECALHO = "EGRÉGIO TRIBUNAL\n\nAutos nº 1234567-89.2021.8.26.0100\nRecorrente: FULANO\n\nMEMORIAL\n\n"


def doc(*frases: str) -> str:
    return CABECALHO + PROSA + "\n".join(frases) + "\n"


def um(frase: str) -> Achado:
    achados = detectar(doc(frase))
    assert len(achados) == 1, [a.trecho for a in achados]
    return achados[0]


def nenhum(frase: str) -> None:
    achados = detectar(doc(frase))
    assert achados == [], [a.trecho for a in achados]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = BaseCanonica(INDICE_FALSO)

    def resolver(self, trecho: str, **kw: Any) -> Decisao:
        return resolver(achado(trecho, **kw), self.base)

    def ponta_a_ponta(self, frase: str) -> tuple[Achado, Decisao]:
        a = um(frase)
        return a, resolver(a, self.base)


# ---------------------------------------------------------------------------
# R2-01 — núcleo ambíguo nunca vira chave parcial; conversão relaxada na resolução
# ---------------------------------------------------------------------------
class TestChaveParcial(Base):
    CASOS = ["1.GO1.157", "1.S9g.905", "2.051.gS0", "7000383-08.2023.7.OO.0000", "REsp nº 1.OO1.140"]

    def test_duas_letras_no_grupo_nao_produzem_chave(self) -> None:
        for t in self.CASOS:
            with self.subTest(t=t):
                self.assertEqual(digitos_do_identificador(t), "")
                ns = nucleos(t)
                self.assertEqual(len(ns), 1)
                self.assertTrue(ns[0].ambiguo)
                self.assertEqual(ns[0].n_digitos, 0)

    def test_tamanho_da_chave_relaxada_bate_com_o_formato(self) -> None:
        # a conversão relaxada troca letra por dígito na posição: 7 dígitos com pontos de milhar → 7
        for t, n in (("1.GO1.157", 7), ("1.S9g.905", 7), ("7000383-08.2023.7.OO.0000", 20)):
            alt = dict(chaves_alternativas(t))
            self.assertEqual(len(alt["relaxado"]), n, t)

    def test_relaxado_resolve_para_o_dono_ou_inventada(self) -> None:
        # 1.234.567 (stj_a) escrito com duas letras no mesmo grupo → real pelo reparo relaxado
        d = self.resolver("REsp nº 1.Z3A.567/SP".replace("A", "4"))
        self.assertEqual(d.classificacao, "real")
        d = self.resolver("REsp nº l.Z34.567/SP")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 100))
        self.assertEqual(d.detalhes["ocr_reparo"], "relaxado")
        self.assertTrue(d.caminho.startswith("processo:ocr_reparado:"))
        # sem dono → inventada com o caminho de OCR ambíguo (confiança baixa), nunca chave parcial
        d = self.resolver("REsp nº 1.OO1.140/DF")
        self.assertEqual((d.classificacao, d.caminho), ("inventada", "processo:0cand:ocr_sem_dono"))
        self.assertEqual(d.detalhes["ocr_reparo"], "sem_dono")
        # sem dígito algum não há chave a converter: continua o caminho ambíguo (confiança baixa)
        d = self.resolver("REsp OOO.OOO/SP")
        self.assertEqual((d.classificacao, d.caminho), ("inventada", "processo:0cand:ocr_ambiguo"))

    def test_uma_letra_continua_convertida_como_antes(self) -> None:
        self.assertEqual(digitos_do_identificador("AgInt no RESP 34567l9"), "3456719")
        self.assertEqual(digitos_do_identificador("Recl. n° 6G.841"), "66841")

    def test_prefixo_so_conta_colado_ao_numero(self) -> None:
        # "SS 3.518" é classe + número, não letras no lugar do primeiro dígito
        self.assertEqual(digitos_do_identificador("AgInt na SS 3.518"), "3518")
        self.assertEqual(digitos_do_identificador("SL 1234"), "1234")


# ---------------------------------------------------------------------------
# R1-02 — OCR no primeiro dígito é detectado e reparado ponta a ponta
# ---------------------------------------------------------------------------
class TestPrimeiroDigito(Base):
    def test_detecta_e_repara(self) -> None:
        a, d = self.ponta_a_ponta("Como decidido no REsp l.234.567/SP, a matéria está superada.")
        self.assertEqual(a.trecho, "REsp l.234.567/SP")
        self.assertEqual(a.dados["digitos"], "")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 100))
        self.assertEqual(d.detalhes["ocr_reparo"], "letra_inicial")
        a, d = self.ponta_a_ponta("Como decidido na AgRg na Rcl G2.471/SP, a matéria está superada.")
        self.assertEqual(a.trecho, "AgRg na Rcl G2.471/SP")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 402))

    def test_sem_dono_vira_inventada(self) -> None:
        a, d = self.ponta_a_ponta("Como decidido na Rcl G8.267/SC, a matéria está superada.")
        self.assertEqual((d.classificacao, d.caminho), ("inventada", "processo:0cand:ocr_sem_dono"))

    def test_sigla_colada_nao_e_prefixo(self) -> None:
        # "AI" + número: o "I" é precedido de letra → não é OCR do primeiro dígito
        self.assertEqual(digitos_do_identificador("AI12345"), "12345")


# ---------------------------------------------------------------------------
# R1-03 / R1-07 / R2-08 — ano solto com UF; números de 2–3 dígitos
# ---------------------------------------------------------------------------
class TestNumerosCurtos(unittest.TestCase):
    def test_ano_com_uf_e_processo(self) -> None:
        for t in ("AR 2019/SP", "RE 2020/SP", "MS 2019/DF"):
            with self.subTest(t=t):
                self.assertEqual(um(f"Como decidido na {t}, a matéria.").trecho, t)
        nenhum("Como decidido na AR 2019, a matéria.")
        nenhum("Como decidido no RE 2020, a matéria.")

    def test_classes_de_numeracao_curta_e_uf(self) -> None:
        for t in ("ADPF 684", "ADI 583", "Cautelar Inominada Criminal 87/DF", "REsp 12/SP", "ADPF nº 684"):
            with self.subTest(t=t):
                self.assertEqual(um(f"Como decidido na {t}, a matéria.").trecho, t)
        nenhum("Como decidido no REsp 12, a matéria.")
        nenhum("Como decidido no HC 123, a matéria.")


# ---------------------------------------------------------------------------
# R1-04 — grupo depois de branco não absorve ordinal, ano solto nem data
# ---------------------------------------------------------------------------
class TestGrupoAposBranco(unittest.TestCase):
    def test_nao_absorve(self) -> None:
        for frase, esperado in (
            ("Como decidido no REsp 1.234.567 2ª Turma, a matéria.", "REsp 1.234.567"),
            ("Como decidido no REsp 1234567 2019/SP, a matéria.", "REsp 1234567"),
            ("Como decidido no REsp 1.234.567 12.03.2022, a matéria.", "REsp 1.234.567"),
            ("Como decidido no REsp 1.234.567, j. 12/03/2022, a matéria.", "REsp 1.234.567"),
        ):
            with self.subTest(frase=frase):
                a = um(frase)
                self.assertEqual(a.trecho, esperado)
                self.assertEqual(a.dados["digitos"], "1234567")

    def test_continua_aceitando_espacos_no_numero(self) -> None:
        a = um("Como decidido no REsp 1 234 567/SP, a matéria.")
        self.assertEqual((a.trecho, a.dados["digitos"]), ("REsp 1 234 567/SP", "1234567"))
        a = um("Como decidido na APL 7009999-12 2021 7 00 0000/BA, a matéria.")
        self.assertEqual(a.dados["digitos"], "70099991220217000000")
        a = um("Invoca-se o RR n.\xa024290-50 2016 S 00 0000, no ponto.")
        self.assertEqual(a.trecho, "RR n.\xa024290-50 2016 S 00 0000")


# ---------------------------------------------------------------------------
# R1-05 — ordinal no meio da cadeia
# ---------------------------------------------------------------------------
class TestOrdinalNoMeio(unittest.TestCase):
    def test_cadeia_canonica(self) -> None:
        for frase, trecho, cadeia in (
            ("A tese encontra amparo no EDcl no 2º AgRg na Rcl 12.345/SP, que dirimiu.", "EDcl no 2º AgRg na Rcl 12.345/SP", "ED 2O AGR RCL"),
            ("A tese encontra amparo no AgRg no Segundo AgRg na Rcl 12.345/SP, que dirimiu.", "AgRg no Segundo AgRg na Rcl 12.345/SP", "AGR 2O AGR RCL"),
            ("A tese encontra amparo no Terceiro AG.REG na Rcl 12.345/SP, que dirimiu.", "Terceiro AG.REG na Rcl 12.345/SP", "3O AGR RCL"),
            # ordinal como ligação, sem "no/na" (forma do gerador agressivo)
            ("Extrai-se do AG.REG. SEGUNDOS EMBARGOS DE DIVERGÊNCIA nos EDCL SEGUNDO AGR no RE 12.345/SP, que dirimiu.",
             "AG.REG. SEGUNDOS EMBARGOS DE DIVERGÊNCIA nos EDCL SEGUNDO AGR no RE 12.345/SP", "AGR 2O EDV ED 2O AGR RE"),
        ):
            with self.subTest(trecho=trecho):
                a = um(frase)
                self.assertEqual((a.trecho, a.dados["cadeia"]), (trecho, cadeia))


# ---------------------------------------------------------------------------
# R1-06 / R2-05 — ``art. N`` sem diploma não é emitido
# ---------------------------------------------------------------------------
class TestArtigoSolto(Base):
    def test_descartado_no_pipeline(self) -> None:
        t = doc("Conforme o art. 321 do Código de Processo Civil, e ainda o art. 927 do mesmo diploma, cabe.",
                "O art. 8º é claro ao respeito, como reconhece a doutrina.")
        saida, rastros = processar_texto_com_rastro("t", t, self.base)
        self.assertEqual([(c.trecho, c.classificacao) for c in saida.citacoes],
                         [("art. 321 do Código de Processo Civil", "real")])
        descartados = [r for r in rastros if r.status == "descartada:resolucao"]
        self.assertEqual(sorted(r.achado.trecho for r in descartados), ["art. 8º", "art. 927"])
        self.assertTrue(all(r.decisao.detalhes["descartar"] == "1" for r in descartados))


# ---------------------------------------------------------------------------
# R1-08 — Súmula Vinculante: tribunal implícito, não explícito
# ---------------------------------------------------------------------------
class TestSumulaVinculanteImplicita(Base):
    def test_caminho_implicito(self) -> None:
        for frase in ("Incide a Súmula Vinculante 45 no caso.", "Incide a SV 45 no caso.", "Incide a SV nº 45 no caso."):
            with self.subTest(frase=frase):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual(a.dados["tribunal"], "")
                self.assertEqual(a.dados["vinculante"], "1")
                self.assertEqual((d.classificacao, d.id_canonico, d.caminho),
                                 ("real", 901, "sumula:na_tabela:tribunal_implicito"))
                self.assertEqual(d.detalhes["tribunal_fonte"], "implicito")

    def test_explicito_continua_explicito(self) -> None:
        a, d = self.ponta_a_ponta("Incide a Súmula 123 do STJ no caso.")
        self.assertEqual(a.dados["tribunal"], "STJ")
        self.assertEqual(d.caminho, "sumula:na_tabela")


# ---------------------------------------------------------------------------
# R2-02 — OCR na sigla da classe
# ---------------------------------------------------------------------------
class TestOcrNaSigla(Base):
    def test_deteccao_e_cadeia(self) -> None:
        for frase, trecho, cadeia in (
            ("Nesse sentido, o RE5P 1.234.567/SP, que resolve.", "RE5P 1.234.567/SP", "RESP"),
            ("Nesse sentido, o ARE5P 2.345.678/PR, que resolve.", "ARE5P 2.345.678/PR", "ARESP"),
            ("Nesse sentido, o Aglnt no ARE5P 2.345.678/PR, que resolve.", "Aglnt no ARE5P 2.345.678/PR", "AGINT ARESP"),
            ("Nesse sentido, o EDcl no Aglnt no RE5P 1.234.567/SP, que resolve.", "EDcl no Aglnt no RE5P 1.234.567/SP", "ED AGINT RESP"),
        ):
            with self.subTest(trecho=trecho):
                a = um(frase)
                self.assertEqual((a.trecho, a.dados["cadeia"], a.origem), (trecho, cadeia, "regex:processo"))
        self.assertEqual(cadeia_de_classes("Rc1"), ["RCL"])

    def test_resolve_como_real(self) -> None:
        _, d = self.ponta_a_ponta("Nesse sentido, o RE5P 1.234.567/SP, que resolve.")
        self.assertEqual((d.classificacao, d.id_canonico, d.caminho), ("real", 100, "processo:1cand:cadeia_exata"))

    def test_rel_min_nao_vira_rcl(self) -> None:
        nenhum("Como anotou o Rel. Min. 1234 em seu voto.")
        # a primeira letra da sigla nunca sofre OCR: "5S 1234" não é "SS 1234"
        nenhum("Como decidido na 5S 1234/SP, a matéria.")


# ---------------------------------------------------------------------------
# R2-03 / R2-07 — Súmula com OCR na palavra; fronteiras novas; SV
# ---------------------------------------------------------------------------
class TestSumulaOcrEFronteiras(unittest.TestCase):
    def test_ocr_na_palavra(self) -> None:
        for frase, trecho, num in (
            ("Incide a Súmulã 456 do TST no caso.", "Súmulã 456 do TST", "456"),
            ("Incide a Súmulã 77\ndo STJ no caso.", "Súmulã 77\ndo STJ", "77"),
            ("Incide a Súrnula 123 do STJ no caso.", "Súrnula 123 do STJ", "123"),
            ("Incide a 5umula Vinculãnte 45 no caso.", "5umula Vinculãnte 45", "45"),
        ):
            with self.subTest(trecho=trecho):
                a = um(frase)
                self.assertEqual((a.trecho, a.dados["numero_sumula"], a.familia), (trecho, num, "sumula"))

    def test_fronteira_ate_o_tribunal(self) -> None:
        for frase, trecho, trib in (
            ("Incide a Súmula 456 da jurisprudência do TST no caso.", "Súmula 456 da jurisprudência do TST", "TST"),
            ("Incide o Enunciado 123 da Súmula do STJ no caso.", "Enunciado 123 da Súmula do STJ", "STJ"),
            ("Incide o verbete nº 123 da Súmula do STJ no caso.", "verbete nº 123 da Súmula do STJ", "STJ"),
            ("Incide a Súmula 123 do Egrégio STJ no caso.", "Súmula 123 do Egrégio STJ", "STJ"),
        ):
            with self.subTest(trecho=trecho):
                a = um(frase)
                self.assertEqual((a.trecho, a.dados["tribunal"]), (trecho, trib))
        nenhum("O enunciado 3 da petição é claro.")   # minúscula sem nº/tribunal: prosa

    def test_sv_e_vinculante(self) -> None:
        a = um("Incide a SV 45 no caso.")
        self.assertEqual((a.trecho, a.dados["vinculante"], a.familia), ("SV 45", "1", "sumula"))


# ---------------------------------------------------------------------------
# R2-04 — OCR em palavra curta do diploma
# ---------------------------------------------------------------------------
class TestDiplomaOcrCurto(Base):
    def test_tolerante_curto(self) -> None:
        self.assertTrue(tolerante("lcis", "leis"))
        self.assertTrue(tolerante("lci", "lei"))
        self.assertTrue(tolerante("quc", "que"))
        self.assertFalse(tolerante("dc", "de"))
        self.assertFalse(tolerante("das", "dos"))
        self.assertEqual(diploma_canonico("Consolidação das Lcis do Trabalho"), "CLT")
        self.assertEqual(diploma_canonico("Códlgo Civil"), "CC")

    def test_ponta_a_ponta(self) -> None:
        a, d = self.ponta_a_ponta("Aplica-se o art 899 da Consolidãção das Lcis do Trabalho ao caso.")
        self.assertEqual(a.dados["diploma"], "CLT")
        self.assertEqual((d.classificacao, d.caminho), ("inventada", "dispositivo:fora_da_tabela"))

    def test_diploma_nao_canonizado_tem_caminho_proprio(self) -> None:
        d = self.resolver("art. 12 da Resolução nº 23.610/2019", familia="dispositivo", tipo="lei",
                          dados={"diploma": "OUTRO", "artigo": "12"})
        self.assertEqual((d.classificacao, d.caminho), ("inventada", "dispositivo:fora_da_tabela:diploma_outro"))


# ---------------------------------------------------------------------------
# R2-06 / R1-11 — moldes de citação vaga com outra ordem; partícula com OCR
# ---------------------------------------------------------------------------
class TestVagaOutrasOrdens(Base):
    def test_moldes(self) -> None:
        for frase, trecho, molde, rel in (
            ("Invoca-se o voto do relator Ministro FULANO DE TAL (STF, 2026), que resolve.",
             "voto do relator Ministro FULANO DE TAL (STF, 2026)", "parenteses", "FULANO DE TAL"),
            ("Invoca-se o acórdão relatado pela Ministra Fulana Quintela Zorobabel em 2018 no STJ, que resolve.",
             "acórdão relatado pela Ministra Fulana Quintela Zorobabel em 2018 no STJ", "relator_antes_ano", "Fulana Quintela Zorobabel"),
            ("Invoca-se o julgado do TSE de 2023, Min. Fulano Silveira Beltrano, que resolve.",
             "julgado do TSE de 2023, Min. Fulano Silveira Beltrano", "min_sem_rel", "Fulano Silveira Beltrano"),
            ("Invoca-se o precedente do TSE (Rel. Min. FULANA ZÉFIRA, 2022), que resolve.",
             "precedente do TSE (Rel. Min. FULANA ZÉFIRA, 2022)", "parenteses_rel", "FULANA ZÉFIRA"),
        ):
            with self.subTest(molde=molde):
                a, d = self.ponta_a_ponta(frase)
                self.assertEqual((a.trecho, a.origem, a.dados["relator"]), (trecho, f"regex:vaga:{molde}", rel))
                self.assertEqual(d.classificacao, "incompleta")

    def test_ministro_sem_virgula_e_prosa(self) -> None:
        nenhum("Como decidiu o STF em 2020 o Ministro Fulano votou pela tese.")

    def test_particula_com_ocr(self) -> None:
        a = um("Como já se reconheceu no julgado do STF proferldo em 2021 pela relatoria dc Fulana dc Tal, a tese.")
        self.assertEqual(a.dados["relator"], "Fulana dc Tal")


# ---------------------------------------------------------------------------
# R2-09 / R1-12-c — cabeçalho: frases curtas antes da prosa; ementa sem prefixo; número do próprio processo
# ---------------------------------------------------------------------------
class TestCabecalho(Base):
    def test_frase_curta_antes_da_prosa_longa(self) -> None:
        t = "DEFENSORIA\n\nAutos nº 1234567-89.2021.5.11.0646\n\nMEMORIAL\n\nCuida-se de habeas corpus.\nInvoca-se o RHC 64.123/RS.\n" + PROSA
        self.assertEqual(t[T.fim_do_cabecalho(t):].startswith("Cuida-se"), True)
        self.assertEqual([a.trecho for a in detectar(t)], ["RHC 64.123/RS"])

    def test_ementa_sem_prefixo_antes_dos_autos(self) -> None:
        t = ("SUPERIOR TRIBUNAL\n\nAPELAÇÃO. Estelionato. Materialidade e autoria comprovadas. Recurso conhecido e desprovido.\n\n"
             "Autos nº 7000123-45.2023.7.00.0000\nApelante: FULANO\n\n" + PROSA)
        self.assertGreater(T.fim_do_cabecalho(t), t.index("Autos"))
        self.assertEqual(detectar(t), [])

    def test_numero_do_cabecalho_no_corpo_e_distrator(self) -> None:
        t = CABECALHO + PROSA + "Nestes autos nº 1234567-89.2021.8.26.0100 a defesa sustenta a tese.\n"
        self.assertEqual(detectar(t), [])
        ini = t.index("autos nº")
        a = Achado(ini, t.index("0100", ini) + 4, "x", "processo", "jurisprudencia",
                   {"digitos": "12345678920218260100"}, "regex:processo:amplo", 0.5)
        self.assertEqual(motivo_distrator(t, a, T.fim_do_cabecalho(t)), "numero_do_cabecalho")


# ---------------------------------------------------------------------------
# R2-11 — tribunal inferido pela classe não é eliminatório
# ---------------------------------------------------------------------------
class TestTribunalFonte(Base):
    def test_detector_marca_a_fonte(self) -> None:
        self.assertEqual(um("Como decidido no REsp 1.234.567/SP, a matéria.").dados["tribunal_fonte"], "classe")
        self.assertEqual(um("Invoca-se o TST-RR-123-45.2015.5.15.0099, no ponto.").dados["tribunal_fonte"], "explicito")
        self.assertEqual(um("Invoca-se a APL 7000123-45.2023.7.00.0000/RS, no ponto.").dados["tribunal_fonte"], "cnj")

    def test_recurso_especial_com_numero_de_respe(self) -> None:
        # 36.123 é um REspe do TSE (tse_a): "Recurso Especial" (STJ pela classe) continua real
        _, d = self.ponta_a_ponta("Como decidido no Recurso Especial nº 36.123, a matéria.")
        self.assertEqual((d.classificacao, d.id_canonico), ("real", 500))
        self.assertEqual(d.detalhes["tribunal_fonte"], "classe")

    def test_prefixo_tst_continua_eliminatorio(self) -> None:
        # número do STJ (1.234.567) com prefixo TST- → tribunal explícito diverge → inventada
        _, d = self.ponta_a_ponta("Invoca-se o TST-RR-1234567, no ponto.")
        self.assertEqual(d.classificacao, "inventada")


# ---------------------------------------------------------------------------
# R1-12-a / R2-10 — sufixo de incidente do STF; ``sob o nº``; UF antes do número
# ---------------------------------------------------------------------------
class TestFormasRaras(unittest.TestCase):
    def test_sufixo_incidente(self) -> None:
        a = um("Como decidido no RE 123.456 AgR/SP, a matéria.")
        self.assertEqual((a.trecho, a.dados["cadeia"], a.dados["uf"]), ("RE 123.456 AgR/SP", "AGR RE", "SP"))

    def test_sob_o_numero_e_uf_antes(self) -> None:
        a = um("Nesse sentido, o AgInt no REsp sob o nº 1.234.567/SC, que resolve.")
        self.assertEqual((a.trecho, a.dados["digitos"]), ("AgInt no REsp sob o nº 1.234.567/SC", "1234567"))
        a = um("Nesse sentido, o REsp/AP nº 1.234.567, que resolve.")
        self.assertEqual((a.trecho, a.dados["cadeia"], a.dados["uf"]), ("REsp/AP nº 1.234.567", "RESP", "AP"))


# ---------------------------------------------------------------------------
# R3-02 / R3-04 / R3-08 / R1-09 — engenharia do pipeline
# ---------------------------------------------------------------------------
class TestPipeline(Base):
    def test_saneamento_linear(self) -> None:
        t = "PARECER\n\n" + PROSA + "art. 8º da CF, " * 3000 + "da CF."
        t0 = time.perf_counter()
        saida = processar_texto("x", t, self.base)
        self.assertLess(time.perf_counter() - t0, 10.0)
        self.assertGreater(len(saida.citacoes), 2000)

    def test_saida_precisa_ser_pasta_gravavel(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "arquivo"
            arq.write_text("x", encoding="utf-8")
            with self.assertRaises(ErroPipeline):
                preparar_saida(arq)
            self.assertTrue(preparar_saida(Path(d) / "nova" / "pasta").is_dir())

    def test_lista_txt_maiusculo_e_ignora_outros(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for nome in ("b.TXT", "a.txt", "c.md"):
                (Path(d) / nome).write_text("x", encoding="utf-8")
            (Path(d) / "sub").mkdir()
            with self.assertLogs("caca_alucinacao.pipeline", level="WARNING") as cm:
                nomes = [p.name for p in listar_documentos(d)]
            self.assertEqual(nomes, ["a.txt", "b.TXT"])
            self.assertIn("c.md", cm.output[0])

    def test_descartar_da_resolucao_omite_a_citacao(self) -> None:
        def resolvedor(a: Achado, base: Any, **_: Any) -> Decisao:
            return Decisao("inventada", None, "processo:0cand:amplo", (), {"descartar": "1"})
        t = doc("Como decidido no REsp 1.234.567/SP, a matéria.")
        saida, rastros = processar_texto_com_rastro("x", t, self.base, resolvedor=resolvedor)
        self.assertEqual(saida.citacoes, [])
        self.assertEqual([r.status for r in rastros], ["descartada:resolucao"])


if __name__ == "__main__":
    unittest.main()
