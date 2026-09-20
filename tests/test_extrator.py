"""Extrator LLM de segundo estágio (ADR 0003, padrão ouro): o modelo só aponta onde olhar.

Cobre o contrato de validação (``validar_extracao``), a escolha de janelas, a re-detecção pela
forma canônica, a integração no pipeline (classe pela base, caminho ``llm:extrator:…``, sem
sobreposição, byte a byte igual ao núcleo quando o árbitro nada acrescenta) e as propriedades de
segurança: um número que não está no span nunca entra; um span que toca um achado do regex nunca
entra; abstenção/exceção do árbitro deixam o documento como o regex o deixou.
Nenhum trecho, número ou nome vem do gabarito ou da base.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao import calibracao as cal  # noqa: E402
from caca_alucinacao.deteccao import detectar  # noqa: E402
from caca_alucinacao.llm import extrator  # noqa: E402
from caca_alucinacao.llm.arbitro import validar_extracao  # noqa: E402
from caca_alucinacao.llm.backends import MockArbitro  # noqa: E402
from caca_alucinacao.pipeline import processar_texto_com_rastro  # noqa: E402
from caca_alucinacao.tipos import Achado  # noqa: E402

CABECALHO = ("PARECER\n\nAutos nº 0001234-56.2020.8.26.0100\n\nEXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO DA VARA CÍVEL\n\n"
             "Trata-se de parecer sobre a controvérsia instaurada nos autos, conforme se passa a expor.\n\n")
CORPO = ("Nesse sentido, o REsp1.234.567/SP afastou a tese, como também a Súmula 7 do STJ. Conforme decidido no "
         "julgamento do recurso especial de número 2.OO0.111, oriundo do Paraná, a pretensão não prospera.\n\n"
         "Aplica-se a Sún1ula 4l2 do TST e o art. 802 do Código Civil, conforme julgado pela 3ª Turma do STJ em 2020, "
         "relatoria da Ministra Beltrana Souza. Ainda, a Re curso Especial 7.654.321/RJ e a Recla-\nmação 45.678/SP "
         "corroboram.\n\n"
         "Conforme consta às fls. 45/52, o valor de R$ 12.500,00 foi fixado em 10/03/2020, e a jurisprudência pacífica "
         "desta Corte não socorre (Processo nº 0001234-56.2020.8.26.0100).")
TEXTO = CABECALHO + CORPO


class BaseFalsa:
    """Base canônica vazia: toda consulta dá 0 candidatos (classe ``inventada``/``incompleta``)."""

    def __getattr__(self, nome: str) -> Any:
        def _nada(*a: Any, **k: Any) -> Any:
            return []
        return _nada


class ArbitroFixo:
    """Árbitro de teste: devolve uma resposta pré-definida (já validada) por janela, ou falha."""

    nome = "fixo"

    def __init__(self, resposta: Any = None, excecao: bool = False) -> None:
        self.resposta = resposta
        self.excecao = excecao
        self.chamadas = 0

    def extrair_citacoes(self, janela: str, ja_detectadas: list[dict[str, Any]] | None = None) -> Any:
        self.chamadas += 1
        if self.excecao:
            raise RuntimeError("modelo caiu")
        if callable(self.resposta):
            return self.resposta(janela, ja_detectadas or [])
        return self.resposta


class TestValidacao(unittest.TestCase):
    JANELA = "como se vê no REsp1.234.567/SP, que afastou a tese, e na Súmula 7 do STJ. Aplica-se a Sún1ula 4l2 do TST e o art. 8O2 do Código Civil."

    def _ja(self) -> list[dict[str, Any]]:
        i = self.JANELA.index("Súmula 7 do STJ")
        return [{"inicio": i, "fim": i + len("Súmula 7 do STJ"), "trecho": "Súmula 7 do STJ"}]

    def test_forma_invalida_e_abstencao(self) -> None:
        self.assertIsNone(validar_extracao(self.JANELA, None, []))
        self.assertIsNone(validar_extracao(self.JANELA, {"x": 1}, []))
        self.assertIsNone(validar_extracao(self.JANELA, {"citacoes": "não é lista"}, []))
        self.assertEqual(validar_extracao(self.JANELA, {"citacoes": []}, []), [])

    def test_numero_tem_de_estar_no_span(self) -> None:
        certo = {"trecho": "REsp1.234.567/SP", "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "1234567", "uf": "SP"}
        errado = dict(certo, numero_digitos="1234568")
        inventado = dict(certo, numero_digitos="9999999")
        r = validar_extracao(self.JANELA, {"citacoes": [certo, errado, inventado]}, self._ja())
        self.assertEqual([c["digitos"] for c in r], ["1234567"])
        self.assertEqual(r[0]["uf"], "SP")
        self.assertEqual(r[0]["cadeia"], ["RESP"])

    def test_ocr_na_palavra_nao_invalida_o_numero(self) -> None:
        r = validar_extracao(self.JANELA, {"citacoes": [
            {"trecho": "Sún1ula 4l2 do TST", "familia": "sumula", "numero_sumula": "412", "tribunal": "TST"},
            {"trecho": "art. 8O2 do Código Civil", "familia": "dispositivo", "artigo": "802", "diploma": "Código Civil"},
            {"trecho": "art. 8O2 do Código Civil", "familia": "dispositivo", "artigo": "802", "diploma": "Código Penal"},
        ]}, self._ja())
        self.assertEqual([(c["familia"], c.get("numero") or c.get("artigo")) for c in r], [("sumula", "412"), ("dispositivo", "802")])

    def test_span_fora_da_janela_e_sobreposicao_sao_rejeitados(self) -> None:
        r = validar_extracao(self.JANELA, {"citacoes": [
            {"trecho": "texto que não existe", "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "1234567"},
            {"trecho": "Súmula 7 do STJ", "familia": "sumula", "numero_sumula": "7", "tribunal": "STJ"},  # já detectada
            {"trecho": "REsp1.234.567/SP", "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "1234567"},
            {"trecho": "REsp1.234.567/SP", "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "1234567"},  # repetida
        ]}, self._ja())
        self.assertEqual(len(r), 1)

    def test_processo_exige_classe_e_vaga_exige_tribunal_ano_relator(self) -> None:
        janela = "julgado pela 3ª Turma do STJ em 2020, relatoria da Ministra Beltrana Souza, e o acórdão nº 45.678 do STF"
        r = validar_extracao(janela, {"citacoes": [
            {"trecho": "acórdão nº 45.678 do STF", "familia": "processo", "classe_cadeia": [], "numero_digitos": "45678", "tribunal": "STF"},
            {"trecho": "julgado pela 3ª Turma do STJ em 2020, relatoria da Ministra Beltrana Souza", "familia": "vaga", "tribunal": "STJ", "ano": "2020", "relator": "Beltrana Souza"},
            {"trecho": "julgado pela 3ª Turma do STJ em 2020, relatoria da Ministra Beltrana Souza", "familia": "vaga", "tribunal": "STJ", "ano": "2021", "relator": "Beltrana Souza"},
            {"trecho": "julgado pela 3ª Turma do STJ em 2020, relatoria da Ministra Beltrana Souza", "familia": "vaga", "tribunal": "STF", "ano": "2020", "relator": "Beltrana Souza"},
            {"trecho": "julgado pela 3ª Turma do STJ em 2020, relatoria da Ministra Beltrana Souza", "familia": "vaga", "tribunal": "STJ", "ano": "2020", "relator": "Fulana"},
        ]}, [])
        self.assertEqual([c["familia"] for c in r], ["vaga"])
        self.assertEqual(r[0]["relator"], "Beltrana Souza")

    def test_familia_desconhecida_e_span_gigante(self) -> None:
        r = validar_extracao(self.JANELA, {"citacoes": [
            {"trecho": "REsp1.234.567/SP", "familia": "nenhuma", "classe_cadeia": ["RESP"], "numero_digitos": "1234567"},
            {"trecho": self.JANELA, "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "1234567"},
        ]}, [])
        self.assertEqual(r, [])


class TestJanelas(unittest.TestCase):
    def test_cabecalho_fica_fora_e_pistas_cobertas_nao_contam(self) -> None:
        achados = detectar(TEXTO)
        jan = extrator.janelas_candidatas(TEXTO, achados)
        self.assertTrue(jan)
        self.assertTrue(all(ini >= len(CABECALHO) - 2 for ini, _, _ in jan))
        # a janela dos distratores (fls., R$, Processo nº) tem pistas mas nenhuma citação: entra (o
        # modelo decide) — o que prova a precisão é o resultado, não a seleção
        self.assertTrue(any("fls." in TEXTO[i:f] for i, f, _ in jan))

    def test_limite_zero_desliga(self) -> None:
        self.assertEqual(extrator.janelas_candidatas(TEXTO, detectar(TEXTO), limite=0), [])

    def test_janela_nunca_excede_o_maximo(self) -> None:
        longo = CABECALHO + ("Nesse sentido, o REsp1.234.567/SP afastou a tese. " * 60)
        for ini, fim, _ in extrator.janelas_candidatas(longo, [], limite=50):
            self.assertLessEqual(fim - ini, extrator.JANELA_MAX)


class TestRedeteccao(unittest.TestCase):
    def test_forma_canonica_e_redeteccao(self) -> None:
        campos = {"familia": "processo", "cadeia": ["AGINT", "RESP"], "digitos": "1234567", "uf": "SP"}
        self.assertEqual(extrator.forma_canonica(campos), "AGINT no RESP 1234567/SP")
        a = extrator.redetectar(campos)
        self.assertIsNotNone(a)
        self.assertEqual((a.familia, a.dados["cadeia"], a.dados["digitos"], a.dados["uf"]), ("processo", "AGINT RESP", "1234567", "SP"))
        cnj = {"familia": "processo", "cadeia": ["RR"], "digitos": "00012345620195040001"}
        self.assertEqual(extrator.forma_canonica(cnj), "RR-0001234-56.2019.5.04.0001")
        self.assertEqual(extrator.redetectar(cnj).dados["formato"], "cnj20")
        v = {"familia": "vaga", "tribunal": "STJ", "ano": "2020", "relator": "Beltrana Souza"}
        self.assertEqual(extrator.redetectar(v).dados["relator"], "Beltrana Souza")
        s = {"familia": "sumula", "numero": "412", "tribunal": "TST", "vinculante": False}
        self.assertEqual(extrator.redetectar(s).dados["numero_sumula"], "412")
        d = {"familia": "dispositivo", "artigo": "802", "diploma": "Código Civil"}
        self.assertEqual(extrator.redetectar(d).dados["diploma"], "CC")

    def test_achado_de_proposta_confere_offsets(self) -> None:
        ini = TEXTO.index("REsp1.234.567/SP")
        campos = {"familia": "processo", "cadeia": ["RESP"], "digitos": "1234567", "uf": "SP",
                  "inicio_rel": ini, "fim_rel": ini + len("REsp1.234.567/SP"), "trecho": "REsp1.234.567/SP"}
        a = extrator.achado_de_proposta(TEXTO, 0, campos)
        self.assertEqual((a.inicio, a.fim, a.trecho, a.origem), (ini, ini + 16, "REsp1.234.567/SP", "llm:extrator:processo"))
        self.assertEqual(a.dados["llm_extraiu"], "1")
        self.assertIsNone(extrator.achado_de_proposta(TEXTO, 0, dict(campos, trecho="outro texto")))


class TestExtrairComMock(unittest.TestCase):
    def test_mock_encontra_as_formas_forcadas_e_nada_nos_distratores(self) -> None:
        achados = detectar(TEXTO)
        novos, n = extrator.extrair(TEXTO, achados, MockArbitro())
        self.assertGreater(n, 0)
        trechos = [a.trecho for a in novos]
        for esperado in ("REsp1.234.567/SP", "recurso especial de número 2.OO0.111", "Sún1ula 4l2 do TST",
                         "julgado pela 3ª Turma do STJ em 2020, relatoria da Ministra Beltrana Souza",
                         "Re curso Especial 7.654.321/RJ", "Recla-\nmação 45.678/SP"):
            self.assertIn(esperado, trechos)
        self.assertFalse(any("fls." in t or "R$" in t or "Processo" in t or "0001234-56" in t for t in trechos))
        # nenhum novo toca um achado do regex nem outro novo
        spans = sorted([(a.inicio, a.fim) for a in achados] + [(a.inicio, a.fim) for a in novos])
        for (i1, f1), (i2, f2) in zip(spans, spans[1:]):
            self.assertLessEqual(f1, i2)

    def test_abstencao_e_excecao_deixam_o_documento_intacto(self) -> None:
        achados = detectar(TEXTO)
        self.assertEqual(extrator.extrair(TEXTO, achados, ArbitroFixo(None))[0], [])
        self.assertEqual(extrator.extrair(TEXTO, achados, ArbitroFixo([]))[0], [])
        self.assertEqual(extrator.extrair(TEXTO, achados, ArbitroFixo(excecao=True))[0], [])
        self.assertEqual(extrator.extrair(TEXTO, achados, None), ([], 0))

    def test_orcamento_de_tempo_limita_as_janelas(self) -> None:
        import time

        def lento(janela: str, ja: list) -> list:
            time.sleep(0.05)
            return []
        arb = ArbitroFixo(lento)
        _, n = extrator.extrair(TEXTO, detectar(TEXTO), arb, orcamento_s=0.01)
        self.assertEqual(n, 1)  # a primeira janela sempre é consultada; as demais estouram o orçamento


class TestPipeline(unittest.TestCase):
    def test_classe_vem_da_base_e_caminho_e_proprio(self) -> None:
        saida, rastros = processar_texto_com_rastro("doc", TEXTO, BaseFalsa(), arbitro=MockArbitro())
        emitidas = [r for r in rastros if r.status == "emitida" and r.achado.origem.startswith("llm:extrator")]
        self.assertTrue(emitidas)
        for r in emitidas:
            self.assertTrue(r.achado.origem.startswith("llm:extrator:mock:"), r.achado.origem)
            self.assertTrue(r.decisao.caminho.startswith("llm:extrator:"), r.decisao.caminho)
            self.assertIn(r.decisao.classificacao, ("inventada", "incompleta"))  # base vazia: nunca real
            self.assertLessEqual(r.confianca, 0.9)  # priors conservadores dos caminhos llm
        dic = saida.para_dicionario()
        spans = sorted((c["inicio"], c["fim"]) for c in dic["citacoes"])
        for (i1, f1), (i2, f2) in zip(spans, spans[1:]):
            self.assertLessEqual(f1, i2)

    def test_sem_arbitro_ou_com_abstencao_saida_identica_ao_nucleo(self) -> None:
        base = BaseFalsa()
        nucleo, _ = processar_texto_com_rastro("doc", TEXTO, base)
        for arb in (None, ArbitroFixo(None), ArbitroFixo([]), ArbitroFixo(excecao=True)):
            saida, _ = processar_texto_com_rastro("doc", TEXTO, base, arbitro=arb)
            self.assertEqual(saida.para_dicionario(), nucleo.para_dicionario())

    def test_proposta_que_toca_achado_do_regex_nunca_entra(self) -> None:
        base = BaseFalsa()
        nucleo, _ = processar_texto_com_rastro("doc", TEXTO, base)
        alvo = "Súmula 7 do STJ"

        def sobreposta(janela: str, ja: list) -> list:
            if alvo not in janela:
                return []
            i = janela.index(alvo)
            return [{"inicio_rel": i, "fim_rel": i + len(alvo), "trecho": alvo, "familia": "sumula", "tipo": "jurisprudencia",
                     "numero": "7", "tribunal": "STJ", "vinculante": False}]
        saida, rastros = processar_texto_com_rastro("doc", TEXTO, base, arbitro=ArbitroFixo(sobreposta))
        self.assertEqual(saida.para_dicionario(), nucleo.para_dicionario())
        self.assertFalse([r for r in rastros if r.achado.origem.startswith("llm:")])


class TestCalibracaoDosCaminhosLLM(unittest.TestCase):
    def test_priors_e_fallback_nunca_herdam_do_regex(self) -> None:
        v, chave = cal.valor_do_caminho("llm:extrator:processo:1cand:cadeia_exata", cal.TABELA_INICIAL)
        self.assertEqual(chave, "llm:extrator:processo:1cand")
        self.assertLess(v, cal.TABELA_INICIAL["processo:1cand:cadeia_exata"])
        v0, chave0 = cal.valor_do_caminho("llm:extrator:tema:inventada:repercussao", cal.TABELA_INICIAL)
        self.assertEqual(chave0, "llm:extrator:tema")
        self.assertTrue(all(chave.startswith("llm") for chave in cal.chaves_de_consulta("llm:extrator:vaga:incompleta")))

    def test_caminhos_llm_nunca_consolidam(self) -> None:
        avs = [cal.Avaliacao("llm:extrator:processo:1cand:cadeia_exata", 1)] * 500
        tabela = cal.ajustar(None, avs)
        self.assertLessEqual(tabela["llm:extrator:processo:1cand:cadeia_exata"], cal.CONFIANCA_TETO)
        self.assertTrue(cal.sem_consolidacao("llm:extrator:processo"))
        self.assertFalse(cal.sem_consolidacao("processo:1cand"))

    def test_achado_llm_construtor(self) -> None:
        a = Achado(10, 20, "0123456789", "processo", "jurisprudencia", {}, "llm:extrator:processo", 1.0)
        self.assertEqual(a.origem, "llm:extrator:processo")


if __name__ == "__main__":
    unittest.main()


class TestReproducaoSemGPU(unittest.TestCase):
    """O JSONL exportado do cache reproduz as respostas sem modelo (``somente_cache`` + importação)."""

    def test_exportar_importar_somente_cache(self) -> None:
        import os
        import tempfile

        from caca_alucinacao.llm import obter_arbitro
        from caca_alucinacao.llm.cache import CacheLLM

        c1 = CacheLLM(":memory:")
        a1 = MockArbitro(cache=c1)
        achados = detectar(TEXTO)
        novos1, _ = extrator.extrair(TEXTO, achados, a1)
        self.assertTrue(novos1)
        with tempfile.TemporaryDirectory() as d:
            jsonl = Path(d) / "cache.jsonl"
            self.assertEqual(c1.exportar_jsonl(jsonl), len(c1))
            antigo = dict(os.environ)
            os.environ["CACA_LLM_SOMENTE_CACHE"] = "1"
            os.environ["CACA_LLM_CACHE_IMPORTAR"] = str(jsonl)
            try:
                a2 = obter_arbitro("mock", cache=CacheLLM(":memory:"))
            finally:
                os.environ.clear()
                os.environ.update(antigo)
            self.assertTrue(a2.somente_cache)
            novos2, _ = extrator.extrair(TEXTO, achados, a2)
            self.assertEqual([(a.inicio, a.fim, a.familia) for a in novos1], [(a.inicio, a.fim, a.familia) for a in novos2])
            self.assertEqual(a2.chamadas, 0)  # nada chegou ao "modelo": tudo veio do cache importado
            # sem o cache, o mesmo modo abstém-se (documento fica como o regex deixou)
            a3 = MockArbitro(cache=CacheLLM(":memory:"), somente_cache=True)
            self.assertEqual(extrator.extrair(TEXTO, achados, a3)[0], [])
