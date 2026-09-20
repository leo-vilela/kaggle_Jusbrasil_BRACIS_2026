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


class TestPromptMascarado(unittest.TestCase):
    def test_spans_ja_detectados_sao_mascarados_e_o_original_fica_para_validar(self) -> None:
        from caca_alucinacao.llm import prompts
        from caca_alucinacao.llm.arbitro import ArbitroBase

        janela = "como se vê no REsp1.234.567/SP, que afastou a tese, e na Súmula 7 do STJ."
        i = janela.index("Súmula 7 do STJ")
        ja = [{"inicio": i, "fim": i + 15, "trecho": "Súmula 7 do STJ"}]
        self.assertEqual(prompts.mascarar(janela, ja), "como se vê no REsp1.234.567/SP, que afastou a tese, e na " + prompts.MASCARA + ".")
        pedido = ArbitroBase.pedido_extrair(janela, ja)
        self.assertEqual(pedido.entrada["janela"], janela)  # a validação e a chave do cache usam o original
        self.assertIn(prompts.MASCARA, pedido.mensagens[1]["content"])
        self.assertNotIn("Súmula 7 do STJ", pedido.mensagens[1]["content"])

    def test_classe_tem_de_estar_escrita_no_span(self) -> None:
        janela = "A Apólice nº 1234567, a Matrícula nº 12.345 e a Certidão nº 123456 instruem; ver REsp1.234.567/SP."
        r = validar_extracao(janela, {"citacoes": [
            {"trecho": "Apólice nº 1234567", "familia": "processo", "classe_cadeia": ["AP"], "numero_digitos": "1234567"},
            {"trecho": "Matrícula nº 12.345", "familia": "processo", "classe_cadeia": ["MS"], "numero_digitos": "12345"},
            {"trecho": "Certidão nº 123456", "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "123456"},
            {"trecho": "REsp1.234.567/SP", "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "1234567", "uf": "SP"},
        ]}, [])
        self.assertEqual([c["trecho"] for c in r], ["REsp1.234.567/SP"])

    def test_distratores_com_cara_de_sumula_ou_artigo_sao_rejeitados(self) -> None:
        janela = ("A Súmula Administrativa nº 12 da AGU, a Súmula AGU nº 45, a OJ 394 da SBDI-1 do TST, a Orientação "
                  "Jurisprudencial nº 191 da SDI-1, o Enunciado 33 da IV Jornada e o art. 5º do contrato não entram; "
                  "a Sún1ula 4l2 do TST e o art. 802 do Código Civil entram.")
        r = validar_extracao(janela, {"citacoes": [
            {"trecho": "Súmula Administrativa nº 12 da AGU", "familia": "sumula", "numero_sumula": "12"},
            {"trecho": "Súmula AGU nº 45", "familia": "sumula", "numero_sumula": "45"},
            {"trecho": "OJ 394 da SBDI-1 do TST", "familia": "sumula", "numero_sumula": "394", "tribunal": "TST"},
            {"trecho": "Orientação Jurisprudencial nº 191 da SDI-1", "familia": "sumula", "numero_sumula": "191"},
            {"trecho": "Enunciado 33 da IV Jornada", "familia": "sumula", "numero_sumula": "33"},
            {"trecho": "art. 5º do contrato", "familia": "dispositivo", "artigo": "5", "diploma": "contrato"},
            {"trecho": "Sún1ula 4l2 do TST", "familia": "sumula", "numero_sumula": "412", "tribunal": "TST"},
            {"trecho": "art. 802 do Código Civil", "familia": "dispositivo", "artigo": "802", "diploma": "Código Civil"},
        ]}, [])
        self.assertEqual([c["trecho"] for c in r], ["Sún1ula 4l2 do TST", "art. 802 do Código Civil"])

    def test_texto_corrige_cadeia_uf_por_extenso_e_tribunal_da_sumula(self) -> None:
        """Medição com o Qwen real (20/09): o modelo devolveu ``RESP`` para ``agravo em recurso
        especial``, ``RESE`` para ``Re curso Especial`` e ``TST`` para ``Sún1ula 211 do STJ``; o
        validador corrige pelo texto quando o texto escreve UMA cadeia/um tribunal, e lê a UF do
        nome do estado (``oriundo de Rio Grande do Sul`` → ``RS``)."""
        janela = ("Nesse sentido é o agravo em recurso especial de número 7.777.001, oriundo de Rio Grande do Sul. "
                  "Ampara a pretensão o Re curso Especial 7.777.002/MG. Decorre da Sún1ula 211 do STJ. Ver o "
                  "recurso especial de número 7.777.003, que enfrentou hipótese idêntica à dos autos; e o "
                  "Processo nº 7777005-46.2022.8.26.0886 e o acórdão nº 777004 do tribunal de origem.")
        r = validar_extracao(janela, {"citacoes": [
            {"trecho": "agravo em recurso especial de número 7.777.001, oriundo de Rio Grande do Sul", "familia": "processo",
             "classe_cadeia": ["RESP"], "numero_digitos": "7777001", "uf": None, "tribunal": "STJ"},
            {"trecho": "Re curso Especial 7.777.002/MG", "familia": "processo", "classe_cadeia": ["RESE"],
             "numero_digitos": "7777002", "uf": "MG"},
            {"trecho": "Sún1ula 211 do STJ", "familia": "sumula", "numero_sumula": "211", "tribunal": "TST"},
            {"trecho": "recurso especial de número 7.777.003, que enfrentou hipótese idêntica à dos autos",
             "familia": "processo", "classe_cadeia": ["RESPE"], "numero_digitos": "7777003"},
            {"trecho": "Processo nº 7777005-46.2022.8.26.0886", "familia": "processo", "classe_cadeia": ["APL"],
             "numero_digitos": "77770054620228260886"},
            {"trecho": "acórdão nº 777004 do tribunal de origem", "familia": "processo", "classe_cadeia": ["RRAG"],
             "numero_digitos": "777004"},
        ]}, [])
        self.assertEqual([(c["trecho"], c.get("cadeia"), c.get("uf"), c.get("tribunal")) for c in r], [
            ("agravo em recurso especial de número 7.777.001, oriundo de Rio Grande do Sul", ["ARESP"], "RS", "STJ"),
            ("Re curso Especial 7.777.002/MG", ["RESP"], "MG", None),
            ("Sún1ula 211 do STJ", None, None, "STJ"),
        ])
        # sem tribunal escrito no span, a súmula fica sem tribunal (o modelo não pode inventá-lo)
        r = validar_extracao("ver a Súmula 7, como se sabe.", {"citacoes": [
            {"trecho": "Súmula 7", "familia": "sumula", "numero_sumula": "7", "tribunal": "STJ"}]}, [])
        self.assertEqual([(c["trecho"], c["tribunal"]) for c in r], [("Súmula 7", None)])

    def test_lista_truncada_aproveita_as_propostas_completas(self) -> None:
        """19 de 455 respostas da medição 1 estouraram o limite de tokens no meio da lista: as
        propostas completas antes do corte valem (cada uma é validada sozinha); o resto cai."""
        from caca_alucinacao.llm.arbitro import extrair_json_citacoes

        janela = "ver o REsp1.234.567/SP e a Sún1ula 4l2 do TST e o art. 802 do Código Civil."
        bruto = ('{"citacoes": [{"trecho": "REsp1.234.567/SP", "familia": "processo", "classe_cadeia": ["RESP"], '
                 '"numero_digitos": "1234567", "uf": "SP"}, {"trecho": "Sún1ula 4l2 do TST", "familia": "sumula", '
                 '"numero_sumula": "412", "tribunal": "TST"}, {"trecho": "art. 802 do Códi')
        obj = extrair_json_citacoes(bruto)
        self.assertTrue(obj.get("truncada"))
        r = validar_extracao(janela, obj, [])
        self.assertEqual([c["trecho"] for c in r], ["REsp1.234.567/SP", "Sún1ula 4l2 do TST"])
        self.assertIsNone(extrair_json_citacoes("nada de JSON aqui"))
        self.assertIsNone(extrair_json_citacoes('{"citacoes": [{"familia": "processo", "cla'))

    def test_relator_precisa_de_pista_e_nao_pode_ser_um_orgao(self) -> None:
        """Medição 1: o modelo devolveu ``Supremo Tribunal Federal`` como relator de ``precedente
        firmado no ano de 2022 pelo Supremo Tribunal Federal``; o nome tem de vir depois de
        ``Rel.``/``relator``/``relatoria`` e não pode ser um órgão."""
        janela = ("Segundo o relator, Ministro Fulano Sicrano, o precedente firmado no ano de 2022 pelo Supremo Tribunal "
                  "Federal não se aplica; ver o julgado do STJ proferido em 2021 pela relatoria de Beltrana Souza.")
        r = validar_extracao(janela, {"citacoes": [
            {"trecho": "precedente firmado no ano de 2022 pelo Supremo Tribunal Federal", "familia": "vaga",
             "tribunal": "STF", "ano": "2022", "relator": "Supremo Tribunal Federal"},
            {"trecho": "precedente firmado no ano de 2022 pelo Supremo Tribunal Federal", "familia": "vaga",
             "tribunal": "STF", "ano": "2022", "relator": "Fulano Sicrano"},
            {"trecho": "julgado do STJ proferido em 2021 pela relatoria de Beltrana Souza", "familia": "vaga",
             "tribunal": "STJ", "ano": "2021", "relator": "Beltrana Souza"},
        ]}, [])
        self.assertEqual([c["trecho"] for c in r], ["julgado do STJ proferido em 2021 pela relatoria de Beltrana Souza"])
