"""Testes de ``caca_alucinacao.texto`` (leitura, cabeçalho, linhas).

Casos sintéticos que preservam a anatomia dos documentos (docs/03 §6.1) sem
nenhum trecho, número ou nome do gabarito. Testes com dados reais ficam sob
``skipUnless(TEM_DADOS)`` e nunca imprimem trechos. Rodar com::

    PYTHONPATH=src python -m unittest tests.test_texto -v
"""
from __future__ import annotations

import csv
import re
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from conftest_paths import GOLDENSET, TEM_DADOS, TXT  # noqa: E402

from caca_alucinacao import texto as T  # noqa: E402

PROSA = ("Trata-se de peça processual em que a parte examina a tese defendida na origem, "
         "conforme as razões a seguir expostas.")

CABECALHO_MEMORIAL = (
    "DEFENSORIA PÚBLICA DA UNIÃO\n"
    "OFÍCIO JUNTO AO SUPERIOR TRIBUNAL MILITAR\n"
    "\n"
    "Processo nº 1234567-89.2021.7.00.0000\n"
    "Assunto: TRÁFICO MARÍTIMO EIRELI\n"
    "Memorial nº 123/2024\n"
    "\n"
    "MEMORIAL\n"
    "\n"
)
CABECALHO_PARECER = (
    "PARECER JURÍDICO Nº 123/2024\n"
    "\n"
    "Interessado: COMERCIAL VERDE LTDA\n"
    "Assunto: viabilidade da tese defendida à luz da orientação dos tribunais superiores\n"
    "Referência: autos nº 1234567-89.2021.8.26.0100\n"
    "Elaborado por: FULANO DE TAL\n"
    "\n"
    "I — RELATÓRIO\n"
    "\n"
)
CABECALHO_HC = (
    "EXCELENTÍSSIMO SENHOR MINISTRO RELATOR\n"
    "SUPERIOR TRIBUNAL DE JUSTIÇA\n"
    "\n"
    "Autos nº 1234567-89.2021.3.00.0000\n"
    "Impetrante: FULANO DE TAL\n"
    "Paciente: BELTRANO LTDA\n"
    "Autoridade coatora: Tribunal de Justiça DO RIO GRANDE DO SUL\n"
    "Valor da causa: R$ 123.456,78\n"
    "\n"
    "AGRAVO REGIMENTAL EM HABEAS CORPUS\n"
    "\n"
)


class TestCarregar(unittest.TestCase):
    def _escrever(self, conteudo: bytes, nome: str = "gen_n2_001.txt") -> Path:
        pasta = Path(tempfile.mkdtemp())
        p = pasta / nome
        p.write_bytes(conteudo)
        return p

    def test_le_utf8_sem_traduzir_quebras(self):
        p = self._escrever("a\r\nb\nç".encode("utf-8"))
        t = T.carregar(p)
        self.assertEqual(t, "a\r\nb\nç")
        self.assertEqual(len(t), 6)

    def test_nunca_normaliza(self):
        # "e" + acento combinante: NFC reduziria o tamanho → mantém como lido
        bruto = "cafe\u0301 x".encode("utf-8")
        p = self._escrever(bruto)
        self.assertEqual(T.carregar(p), "cafe\u0301 x")
        # singleton (U+212B → U+00C5) manteria o tamanho, mas o trecho emitido tem de ser
        # texto[inicio:fim] do ARQUIVO: também não normaliza (revisão R1-10)
        p2 = self._escrever("\u212b b".encode("utf-8"))
        self.assertEqual(T.carregar(p2), "\u212b b")

    def test_pipeline_usa_o_mesmo_carregador(self):
        from caca_alucinacao import pipeline
        p = self._escrever("a\r\nb \u212b".encode("utf-8"))
        self.assertEqual(pipeline.carregar_texto(p), T.carregar(p))
        self.assertEqual(pipeline.carregar_texto(p), "a\r\nb \u212b")

    def test_bytes_invalidos_nao_derrubam(self):
        p = self._escrever(b"ok \xff fim")
        t = T.carregar(p)
        self.assertIn("ok", t)
        self.assertIn("fim", t)

    def test_documento_id_e_nivel(self):
        self.assertEqual(T.documento_id("dados/txt/gen_n2_003.txt"), "gen_n2_003")
        self.assertEqual(T.nivel_do_documento("gen_n2_003"), 2)
        self.assertEqual(T.nivel_do_documento("gen_n1_013"), 1)
        self.assertEqual(T.nivel_do_documento("sin_n3_agressivo_007"), 3)
        self.assertEqual(T.nivel_do_documento("qualquer_coisa"), 1)


class TestLinhas(unittest.TestCase):
    def test_offsets_por_linha(self):
        t = "ab\ncd\n\nef"
        linhas = T.linhas_com_offsets(t)
        self.assertEqual(linhas, [(0, 2, "ab"), (3, 5, "cd"), (6, 6, ""), (7, 9, "ef")])
        for i, f, linha in linhas:
            self.assertEqual(t[i:f], linha)

    def test_texto_vazio(self):
        self.assertEqual(T.linhas_com_offsets(""), [(0, 0, "")])


class TestFimDoCabecalho(unittest.TestCase):
    def test_memorial(self):
        t = CABECALHO_MEMORIAL + PROSA + "\n" + PROSA
        fim = T.fim_do_cabecalho(t)
        self.assertEqual(fim, len(CABECALHO_MEMORIAL))
        self.assertTrue(t[fim:].startswith("Trata-se"))

    def test_parecer_juridico_com_chave_valor_longa(self):
        # "Assunto: …" tem > 60 chars em minúsculas e NÃO é prosa; "Referência: autos nº" também não
        t = CABECALHO_PARECER + "Submete-se a exame desta consultoria a questão relativa ao cabimento da tese sustentada nos\nautos."
        fim = T.fim_do_cabecalho(t)
        self.assertEqual(fim, len(CABECALHO_PARECER))
        self.assertGreater(fim, t.index("1234567-89.2021.8.26.0100"))

    def test_hc_com_valor_da_causa(self):
        t = CABECALHO_HC + "A defesa do paciente, inconformada com a decisão que indeferiu liminarmente a ordem, vem interpor\no presente agravo."
        fim = T.fim_do_cabecalho(t)
        self.assertEqual(fim, len(CABECALHO_HC))
        self.assertGreater(fim, t.index("123.456,78") + 10)

    def test_linha_toda_em_caixa_alta_nao_e_prosa(self):
        caps = "EXCELENTÍSSIMO SENHOR DOUTOR DESEMBARGADOR RELATOR DA TERCEIRA CÂMARA CÍVEL DO TRIBUNAL"
        t = caps + "\n\n" + PROSA
        self.assertEqual(T.fim_do_cabecalho(t), len(caps) + 2)

    def test_sem_prosa_devolve_o_fim_da_identificacao(self):
        # rodada 4 (R4-04): sem prosa, o cabeçalho é o bloco de identificação (antes: 0)
        self.assertEqual(T.fim_do_cabecalho("MEMORIAL\n\nAutos nº 1\n"), len("MEMORIAL\n\nAutos nº 1\n"))
        self.assertEqual(T.fim_do_cabecalho("MEMORIAL\n\nTÍTULO\n"), 0)
        self.assertEqual(T.fim_do_cabecalho(""), 0)

    def test_teto_de_seguranca(self):
        # parágrafos curtos: a 1ª linha ≥ 60 chars viria depois do teto; usa o limiar relaxado
        curtas = "\n".join(["Trata-se de recurso da parte autora."] * 60)
        t = "TRIBUNAL\n\n" + curtas + "\n" + PROSA
        fim = T.fim_do_cabecalho(t)
        self.assertEqual(fim, len("TRIBUNAL\n\n"))
        self.assertLessEqual(fim, T.LIMITE_CABECALHO)

    def test_e_linha_de_prosa(self):
        self.assertTrue(T.e_linha_de_prosa(PROSA))
        self.assertFalse(T.e_linha_de_prosa("Assunto: viabilidade da tese defendida à luz da orientação dos tribunais superiores"))
        self.assertFalse(T.e_linha_de_prosa("curta demais para ser prosa"))
        # rodada 3 (R3-10): prosa toda em caixa alta é prosa quando tem frases longas, ≥ 30 % de
        # palavras gramaticais e um sinal de oração; ementas e endereçamentos em caixa alta não
        self.assertTrue(T.e_linha_de_prosa(PROSA.upper()))
        self.assertFalse(T.e_linha_de_prosa(
            "PROCESSUAL CIVIL. AGRAVO INTERNO. ÔNUS DA PROVA. REEXAME DE FATOS. AGRAVO A QUE SE NEGA PROVIMENTO."))
        self.assertFalse(T.e_linha_de_prosa(
            "EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA VARA CÍVEL DA COMARCA DE CAMPINAS DO ESTADO DE SÃO PAULO"))
        # rodada 4 (R4-04): a forma de ementa decide em qualquer caixa (``Ementa: Processual civil. …`` idem)
        self.assertFalse(T.e_linha_de_prosa(
            "EMENTA: PROCESSUAL CIVIL. AGRAVO INTERNO. ÔNUS DA PROVA. REEXAME DE FATOS. AGRAVO A QUE SE NEGA PROVIMENTO."))
        self.assertFalse(T.e_linha_de_prosa(
            "Ementa: Processual civil. Agravo interno. Ônus da prova. Reexame de fatos. Agravo a que se nega provimento."))

    def test_linha_de_identificacao_dos_autos(self):
        # R5-05: linha longa em caixa mista que identifica os autos (classe + nº + CNJ) ainda é cabeçalho
        t = ("TRIBUNAL DE JUSTIÇA\n\nApelação Cível nº 1234567-89.2021.8.26.0114 da Comarca de Campinas, "
             "em que é apelante FULANO DE TAL e apelado BELTRANO S.A.\nRelator: Des. Sicrano\n\nVOTO\n\n" + PROSA + "\n")
        self.assertEqual(T.fim_do_cabecalho(t), t.index("Trata-se"))


@unittest.skipUnless(TEM_DADOS, "dados do desafio ausentes")
class TestDadosReais(unittest.TestCase):
    """Metas de docs/03 §6.1 nos 26 documentos (sem imprimir trechos)."""

    @classmethod
    def setUpClass(cls):
        cls.primeiro_span: dict[str, int] = {}
        with GOLDENSET.open(encoding="utf-8-sig", newline="") as f:
            for linha in csv.DictReader(f):
                doc = linha["documento_id"]
                cls.primeiro_span[doc] = min(cls.primeiro_span.get(doc, 10**9), int(linha["inicio"]))
        cls.docs = sorted(TXT.glob("*.txt"))

    def test_carregar_nao_altera_offsets(self):
        for p in self.docs:
            t = T.carregar(p)
            self.assertEqual(len(t), len(p.read_bytes().decode("utf-8")))

    def test_fim_do_cabecalho_antes_do_primeiro_span_e_depois_do_ultimo_numero(self):
        rx_cnj = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
        faixa = []
        for p in self.docs:
            t = T.carregar(p)
            fim = T.fim_do_cabecalho(t)
            faixa.append(fim)
            self.assertLessEqual(fim, self.primeiro_span[p.stem], p.stem)
            m = rx_cnj.search(t)
            self.assertIsNotNone(m, p.stem)
            self.assertGreater(fim, m.end(), p.stem)
            self.assertTrue(150 <= fim <= 300, (p.stem, fim))
        self.assertEqual(len(faixa), 26)

    def test_nivel_por_documento(self):
        niveis = {T.nivel_do_documento(p.stem) for p in self.docs}
        self.assertEqual(niveis, {1, 2})


if __name__ == "__main__":
    unittest.main()
