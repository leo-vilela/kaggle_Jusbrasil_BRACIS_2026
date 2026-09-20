"""Testes do árbitro LLM: parsing tolerante, regra "dígito nunca muda", abstenção,
cache, Mock em casos sintéticos e fábrica.

Nenhum trecho, número ou nome vem do gabarito: todos os exemplos são sintéticos.
Nenhum teste exige torch/transformers/vllm (só verifica o erro claro na ausência).
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.llm import (  # noqa: E402
    Arbitro,
    ArbitroBase,
    CacheLLM,
    ErroDependencia,
    MockArbitro,
    Pedido,
    PROMPT_VERSAO,
    aparar_fronteiras,
    candidato_de_registro,
    chave_cache,
    digitos_compativeis,
    extrair_json,
    obter_arbitro,
    validar_classificacao,
    validar_escolha,
    validar_normalizacao,
)
from caca_alucinacao.llm import backends, prompts  # noqa: E402

logging.getLogger("caca_alucinacao").setLevel(logging.CRITICAL)


# ---------------------------------------------------------------------------
# Backends falsos para exercitar a classe base
# ---------------------------------------------------------------------------
class _Roteirizado(ArbitroBase):
    """Devolve respostas fixas (texto bruto), na ordem; registra os pedidos recebidos."""

    nome = "roteirizado"

    def __init__(self, respostas: list[str], cache: CacheLLM | None = None) -> None:
        super().__init__(modelo="fake", revisao="abc123", cache=cache, assinatura="t")
        self.respostas = list(respostas)
        self.pedidos: list[Pedido] = []

    def _gerar(self, pedidos: list[Pedido]) -> list[str]:
        self.pedidos.extend(pedidos)
        saida = []
        for _ in pedidos:
            saida.append(self.respostas.pop(0) if self.respostas else "")
        return saida


class _Explosivo(ArbitroBase):
    nome = "explosivo"

    def __init__(self) -> None:
        super().__init__(modelo="fake", revisao="x", cache=None)

    def _gerar(self, pedidos: list[Pedido]) -> list[str]:
        raise RuntimeError("CUDA out of memory (simulado)")


CANDIDATOS = [
    {"id_canonico": 11, "cabecalho": "AgInt no RECURSO ESPECIAL Nº 1.777.888 - PR (2018/0011111-2) RELATOR : MINISTRO FULANO PEREIRA",
     "tribunal": "STJ", "ano": 2018, "relator": "Fulano Pereira", "cadeia": "AGINT RESP"},
    {"id_canonico": 22, "cabecalho": "AgInt nos EMBARGOS DE DIVERGÊNCIA EM RESP Nº 1.777.888 - PR (2019/0022222-3) RELATORA : MINISTRA BELTRANA SOUZA",
     "tribunal": "STJ", "ano": 2019, "relator": "Beltrana Souza", "cadeia": "AGINT ERESP"},
]


# ---------------------------------------------------------------------------
# Parsing tolerante
# ---------------------------------------------------------------------------
class TestExtrairJson(unittest.TestCase):
    def test_json_puro(self) -> None:
        self.assertEqual(extrair_json('{"a": 1, "b": null}'), {"a": 1, "b": None})

    def test_com_cerca_de_codigo(self) -> None:
        txt = 'Claro! Segue:\n```json\n{"indice": 0, "evidencia": "ano"}\n```\nEspero ter ajudado.'
        self.assertEqual(extrair_json(txt), {"indice": 0, "evidencia": "ano"})

    def test_texto_antes_e_depois_sem_cerca(self) -> None:
        txt = 'Resposta: {"eh_citacao": true, "familia": "processo"} — fim.'
        self.assertEqual(extrair_json(txt), {"eh_citacao": True, "familia": "processo"})

    def test_chaves_dentro_de_string_e_virgula_sobrando(self) -> None:
        txt = '{"trecho": "art. 5º, {inciso}", "x": [1, 2,], }'
        obj = extrair_json(txt)
        self.assertIsNotNone(obj)
        self.assertEqual(obj["trecho"], "art. 5º, {inciso}")
        self.assertEqual(obj["x"], [1, 2])

    def test_literais_python(self) -> None:
        self.assertEqual(extrair_json("{'a': True}".replace("'", '"')), {"a": True})
        self.assertEqual(extrair_json('{"a": None, "b": False}'), {"a": None, "b": False})

    def test_primeiro_objeto_valido_vence(self) -> None:
        txt = 'lixo { não json } {"ok": 1} {"depois": 2}'
        self.assertEqual(extrair_json(txt), {"ok": 1})

    def test_invalido_ou_vazio(self) -> None:
        self.assertIsNone(extrair_json(""))
        self.assertIsNone(extrair_json(None))
        self.assertIsNone(extrair_json("sem json nenhum"))
        self.assertIsNone(extrair_json("[1, 2, 3]"))  # lista não é objeto

    def test_campos_faltando_nao_quebram_validacao(self) -> None:
        self.assertIsNone(validar_normalizacao("REsp 1.234.567/SP", {"numero_digitos": "1234567"}))  # sem eh_citacao
        self.assertIsNone(validar_escolha({"evidencia": "x"}, 2))
        self.assertIsNone(validar_classificacao("REsp 1", "o REsp 1, x", {"trecho": "REsp 1"}))  # sem familia/eh


# ---------------------------------------------------------------------------
# Regra "dígito nunca vira outro dígito"
# ---------------------------------------------------------------------------
class TestDigitosCompativeis(unittest.TestCase):
    def test_troca_letra_por_digito_aceita(self) -> None:
        self.assertTrue(digitos_compativeis("REsp 1.9SO.OO1", "1950001"))
        self.assertTrue(digitos_compativeis("AgInt no RESP 21739l4", "2173914"))
        self.assertTrue(digitos_compativeis("Rcl\n4S.O12", "45012"))
        self.assertTrue(digitos_compativeis("APL 700O321-9S 2022 7 00 0000", "70003219520227000000"))

    def test_digito_alterado_rejeitado(self) -> None:
        self.assertFalse(digitos_compativeis("REsp 1.234.567", "1234568"))
        self.assertFalse(digitos_compativeis("REsp 1.234.567", "1234567".replace("2", "3")))

    def test_digito_removido_ou_inserido_rejeitado(self) -> None:
        self.assertFalse(digitos_compativeis("REsp 1.234.567", "123456"))
        self.assertFalse(digitos_compativeis("REsp 1.234.567", "12345678"))
        self.assertFalse(digitos_compativeis("REsp 1.234.567", "01234567"))

    def test_letra_nao_confundivel_nao_vira_digito(self) -> None:
        # "E" não é confundível: não pode virar 3; "T" não vira 7
        self.assertFalse(digitos_compativeis("RE 1.234", "31234"))
        self.assertFalse(digitos_compativeis("TST-RR-12", "712"))

    def test_letra_so_vira_o_digito_do_mapa(self) -> None:
        self.assertFalse(digitos_compativeis("Rcl 4S.012", "47012"))   # S → 5, nunca 7
        self.assertTrue(digitos_compativeis("Rcl 4S.012", "45012"))

    def test_vazio_ou_nao_numerico(self) -> None:
        self.assertFalse(digitos_compativeis("REsp 1.234.567", ""))
        self.assertFalse(digitos_compativeis("REsp 1.234.567", "12a34"))

    def test_uf_nao_e_convertida_na_validacao(self) -> None:
        # validar_normalizacao separa a UF antes: o S de /SP não pode virar 5
        r = validar_normalizacao("REsp 1.234.567/SP", {"classe_cadeia": ["RESP"], "numero_digitos": "12345675",
                                                        "uf": "SP", "tribunal": "STJ", "eh_citacao": True})
        self.assertIsNone(r)
        r = validar_normalizacao("REsp 1.234.567/SP", {"classe_cadeia": ["RESP"], "numero_digitos": "1234567",
                                                        "uf": "SP", "tribunal": "STJ", "eh_citacao": True})
        self.assertIsNotNone(r)
        self.assertEqual(r["numero_digitos"], "1234567")
        self.assertEqual(r["uf"], "SP")


class TestValidacoes(unittest.TestCase):
    def test_normalizacao_completa_e_canonizacao(self) -> None:
        r = validar_normalizacao("processo nº TST-ED-E-RR-77-l2.2013.5.09.0O11",
                                 {"classe_cadeia": ["edcl", "E", "rr"], "numero_digitos": "771220135090011",
                                  "uf": None, "tribunal": "tst", "eh_citacao": True})
        self.assertEqual(r["classe_cadeia"], ["ED", "E", "RR"])
        self.assertEqual(r["numero_digitos"], "771220135090011")
        self.assertEqual(r["digitos_canonicos"], "00000771220135090011")   # CNJ preenchido a 20
        self.assertEqual(r["tribunal"], "TST")
        self.assertIsNone(r["uf"])

    def test_normalizacao_pontuacao_no_numero_e_cadeia_bruta(self) -> None:
        r = validar_normalizacao("AgInt no AREsp 1.234.567 - RS",
                                 {"classe_cadeia": "AgInt no AREsp", "numero_digitos": "1.234.567",
                                  "uf": "rs", "tribunal": "STJ", "eh_citacao": "true"})
        self.assertEqual(r["classe_cadeia"], ["AGINT", "ARESP"])
        self.assertEqual(r["numero_digitos"], "1234567")
        self.assertEqual(r["uf"], "RS")

    def test_normalizacao_uf_invalida_e_tribunal_invalido_sao_descartados(self) -> None:
        r = validar_normalizacao("Rcl 12.345", {"classe_cadeia": ["RCL"], "numero_digitos": "12345",
                                                "uf": "XX", "tribunal": "TJSP", "eh_citacao": True})
        self.assertIsNone(r["uf"])
        self.assertIsNone(r["tribunal"])

    def test_normalizacao_uf_do_trecho_prevalece(self) -> None:
        r = validar_normalizacao("Rcl 12.345/SP", {"classe_cadeia": ["RCL"], "numero_digitos": "12345",
                                                   "uf": "RJ", "tribunal": None, "eh_citacao": True})
        self.assertEqual(r["uf"], "SP")

    def test_normalizacao_nao_citacao(self) -> None:
        r = validar_normalizacao("fls. 1O2/1O5", {"classe_cadeia": [], "numero_digitos": "",
                                                  "uf": None, "tribunal": None, "eh_citacao": False})
        self.assertEqual(r, {"classe_cadeia": [], "numero_digitos": "", "digitos_canonicos": "",
                             "uf": None, "tribunal": None, "eh_citacao": False})

    def test_normalizacao_sem_digitos_abstem(self) -> None:
        self.assertIsNone(validar_normalizacao("REsp 1.234.567", {"classe_cadeia": ["RESP"], "numero_digitos": "",
                                                                  "uf": None, "tribunal": None, "eh_citacao": True}))
        self.assertIsNone(validar_normalizacao("REsp 1.234.567", None))
        self.assertIsNone(validar_normalizacao("REsp 1.234.567", "não é dict"))  # type: ignore[arg-type]

    def test_escolha(self) -> None:
        self.assertEqual(validar_escolha({"indice": 1}, 2), 1)
        self.assertEqual(validar_escolha({"indice": "0"}, 2), 0)
        self.assertEqual(validar_escolha({"indice": 1.0}, 2), 1)
        self.assertIsNone(validar_escolha({"indice": 2}, 2))
        self.assertIsNone(validar_escolha({"indice": -1}, 2))
        self.assertIsNone(validar_escolha({"indice": None}, 2))
        self.assertIsNone(validar_escolha({"indice": True}, 2))
        self.assertIsNone(validar_escolha({"indice": "um"}, 2))
        self.assertIsNone(validar_escolha(None, 2))

    def test_classificacao_offsets_a_partir_do_trecho_literal(self) -> None:
        jan = "Invoca-se, ainda, o AgInt no AREsp 1.234.567/RS, que"
        r = validar_classificacao("AREsp 1.234.567", jan,
                                  {"eh_citacao": True, "familia": "processo", "tipo": "jurisprudencia",
                                   "trecho": "o AgInt no AREsp 1.234.567/RS,"})
        self.assertEqual(jan[r["inicio_rel"]:r["fim_rel"]], "AgInt no AREsp 1.234.567/RS")   # artigo e vírgula fora
        self.assertEqual(r["trecho"], "AgInt no AREsp 1.234.567/RS")
        self.assertEqual(r["tipo"], "jurisprudencia")

    def test_classificacao_dispositivo_forca_tipo_lei(self) -> None:
        jan = "viola o art. 321 do CPC, razão"
        r = validar_classificacao("art. 321", jan, {"eh_citacao": True, "familia": "dispositivo",
                                                    "tipo": "jurisprudencia", "trecho": "art. 321 do CPC"})
        self.assertEqual(r["tipo"], "lei")
        self.assertEqual(jan[r["inicio_rel"]:r["fim_rel"]], "art. 321 do CPC")

    def test_classificacao_trecho_com_espacos_diferentes(self) -> None:
        jan = "conforme a Súmula 77\ndo STJ, segundo"
        r = validar_classificacao("Súmula 77", jan, {"eh_citacao": True, "familia": "sumula",
                                                      "tipo": "jurisprudencia", "trecho": "Súmula 77 do STJ"})
        self.assertEqual(jan[r["inicio_rel"]:r["fim_rel"]], "Súmula 77\ndo STJ")

    def test_classificacao_span_fora_da_janela_usa_o_original(self) -> None:
        jan = "o REsp 1.234.567/SP, que"
        r = validar_classificacao("REsp 1.234.567/SP", jan, {"eh_citacao": True, "familia": "processo",
                                                             "tipo": "jurisprudencia", "trecho": "REsp 9.999.999/SP"})
        self.assertEqual(jan[r["inicio_rel"]:r["fim_rel"]], "REsp 1.234.567/SP")

    def test_classificacao_span_sem_sobreposicao_abstem(self) -> None:
        jan = "o REsp 1.234.567/SP e, adiante, a Súmula 7 do STJ"
        r = validar_classificacao("REsp 1.234.567/SP", jan, {"eh_citacao": True, "familia": "sumula",
                                                             "tipo": "jurisprudencia", "trecho": "Súmula 7 do STJ"})
        self.assertIsNone(r)

    def test_classificacao_nao_citacao_mantem_offsets_originais(self) -> None:
        jan = "às fls. 45/52 dos autos"
        r = validar_classificacao("fls. 45/52", jan, {"eh_citacao": False, "familia": "nenhuma",
                                                      "tipo": "jurisprudencia", "trecho": ""})
        self.assertEqual(r["eh_citacao"], False)
        self.assertEqual((r["inicio_rel"], r["fim_rel"]), (3, 13))

    def test_classificacao_familia_invalida_abstem(self) -> None:
        self.assertIsNone(validar_classificacao("x 1", "o x 1", {"eh_citacao": True, "familia": "acordao", "trecho": "x 1"}))

    def test_classificacao_trecho_ausente_da_janela_abstem(self) -> None:
        self.assertIsNone(validar_classificacao("REsp 1", "janela sem o candidato",
                                                {"eh_citacao": True, "familia": "processo", "trecho": "REsp 1"}))

    def test_classificacao_inicio_rel_desambigua(self) -> None:
        jan = "Rcl 1.111/SP ... Rcl 1.111/SP"
        r = validar_classificacao("Rcl 1.111/SP", jan, {"eh_citacao": True, "familia": "processo",
                                                        "trecho": "Rcl 1.111/SP"}, inicio_rel=17)
        self.assertEqual(r["inicio_rel"], 17)

    def test_aparar_fronteiras(self) -> None:
        jan = " no AgInt no REsp 1/SP, "
        self.assertEqual(jan[slice(*aparar_fronteiras(jan, 0, len(jan)))], "AgInt no REsp 1/SP")
        jan2 = "a Rcl 1 (SP)."
        self.assertEqual(jan2[slice(*aparar_fronteiras(jan2, 0, len(jan2)))], "Rcl 1 (SP)")   # ")" fica


# ---------------------------------------------------------------------------
# Abstenção
# ---------------------------------------------------------------------------
class TestAbstencao(unittest.TestCase):
    def test_backend_que_lanca_excecao_abstem(self) -> None:
        a = _Explosivo()
        self.assertIsNone(a.normalizar_citacao("REsp 1.2S4.567/SP", "ctx"))
        self.assertIsNone(a.escolher_candidato("REsp 1", "ctx", CANDIDATOS))
        self.assertIsNone(a.classificar_span("REsp 1", "o REsp 1, x"))
        self.assertEqual(a.abstencoes, 3)

    def test_resposta_sem_json_abstem(self) -> None:
        a = _Roteirizado(["Desculpe, não consigo ajudar.", "```\nnada\n```", ""])
        self.assertIsNone(a.normalizar_citacao("REsp 1.2S4.567/SP", "ctx"))
        self.assertIsNone(a.escolher_candidato("REsp 1", "ctx", CANDIDATOS))
        self.assertIsNone(a.classificar_span("REsp 1", "o REsp 1, x"))

    def test_json_com_digito_alterado_abstem(self) -> None:
        a = _Roteirizado([json.dumps({"classe_cadeia": ["RESP"], "numero_digitos": "1264567",
                                      "uf": "SP", "tribunal": "STJ", "eh_citacao": True})])
        self.assertIsNone(a.normalizar_citacao("REsp 1.2S4.567/SP", "ctx"))

    def test_escolha_com_menos_de_dois_candidatos_nem_chama_o_modelo(self) -> None:
        a = _Roteirizado(['{"indice": 0}'])
        self.assertIsNone(a.escolher_candidato("REsp 1", "ctx", CANDIDATOS[:1]))
        self.assertIsNone(a.escolher_candidato("REsp 1", "ctx", []))
        self.assertEqual(a.chamadas, 0)

    def test_lote_com_tamanho_errado_abstem(self) -> None:
        class _Curto(ArbitroBase):
            nome = "curto"

            def __init__(self) -> None:
                super().__init__("f", "r", None)

            def _gerar(self, pedidos: list[Pedido]) -> list[str]:
                return []

        a = _Curto()
        self.assertEqual(a.executar_lote("normalizar", [("REsp 1S", "c"), ("Rcl 2O", "c")]), [None, None])

    def test_operacao_desconhecida(self) -> None:
        with self.assertRaises(ValueError):
            _Roteirizado([]).executar_lote("inventar", [("x", "y")])


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
class TestCache(unittest.TestCase):
    def test_chave_deterministica_e_sensivel_a_cada_componente(self) -> None:
        base = dict(modelo="m", revisao="r", prompt_versao="p", operacao="normalizar", entrada={"a": 1, "b": "x"})
        k1 = chave_cache(**base)
        k2 = chave_cache(**{**base, "entrada": {"b": "x", "a": 1}})   # ordem das chaves não importa
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 64)
        for campo, valor in (("modelo", "m2"), ("revisao", "r2"), ("prompt_versao", "p2"),
                             ("operacao", "escolher"), ("entrada", {"a": 2, "b": "x"})):
            self.assertNotEqual(k1, chave_cache(**{**base, campo: valor}), campo)
        self.assertNotEqual(k1, chave_cache(**base, assinatura="bf16"))

    def test_hit_e_miss(self) -> None:
        cache = CacheLLM(":memory:")
        a = _Roteirizado([json.dumps({"indice": 1, "evidencia": "ano"})], cache=cache)
        self.assertEqual(a.escolher_candidato("AgInt no REsp 1.777.888/PR", "em 2019", CANDIDATOS), 1)
        self.assertEqual((cache.acertos, cache.erros), (0, 1))
        self.assertEqual(a.chamadas, 1)
        # segunda chamada idêntica: vem do cache; o backend (sem respostas restantes) não é chamado
        self.assertEqual(a.escolher_candidato("AgInt no REsp 1.777.888/PR", "em 2019", CANDIDATOS), 1)
        self.assertEqual((cache.acertos, cache.erros), (1, 1))
        self.assertEqual(a.chamadas, 1)
        # entrada diferente: miss; o backend devolve "" (sem roteiro) → abstém e NÃO grava no cache
        self.assertIsNone(a.escolher_candidato("AgInt no REsp 1.777.888/PR", "em 2018", CANDIDATOS))
        self.assertEqual(cache.erros, 2)
        self.assertEqual(len(cache), 1)
        reg = next(iter(cache.iterar()))
        self.assertEqual(reg["operacao"], "escolher")
        self.assertEqual(reg["prompt_versao"], prompts.PROMPT_ID)   # rótulo + hash do texto (R3b-03)
        self.assertTrue(reg["prompt_versao"].startswith(PROMPT_VERSAO + "+"))
        self.assertEqual(reg["resultado"], 1)
        self.assertEqual(reg["entrada"]["contexto"], "em 2019")

    def test_hash_do_prompt_fixado(self) -> None:
        """Mudar o texto de qualquer prompt muda ``PROMPT_HASH`` e, por consequência, a chave do
        cache; este teste obriga a atualizar o hash esperado (e, por convenção, PROMPT_VERSAO)
        junto com o texto (R3b-03)."""
        self.assertEqual(prompts.PROMPT_HASH, "5d503edc6854c3b4")
        self.assertEqual(prompts.PROMPT_ID, f"{PROMPT_VERSAO}+{prompts.PROMPT_HASH}")
        self.assertEqual(len(prompts.PROMPT_HASH), 16)

    def test_persistencia_exportacao_e_somente_cache(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            caminho = Path(d) / "sub" / "c.sqlite"
            cache = CacheLLM(caminho)
            a = _Roteirizado([json.dumps({"classe_cadeia": ["RCL"], "numero_digitos": "45012", "uf": "SP",
                                          "tribunal": None, "eh_citacao": True})], cache=cache)
            r1 = a.normalizar_citacao("Rcl\n4S.O12/SP", "ctx")
            self.assertEqual(r1["numero_digitos"], "45012")
            n = cache.exportar_jsonl(Path(d) / "export.jsonl")
            self.assertEqual(n, 1)
            cache.fechar()
            # reabre: mesma chave → hit, sem backend (somente_cache=True)
            cache2 = CacheLLM(caminho)
            b = _Roteirizado([], cache=cache2)
            b.somente_cache = True
            self.assertEqual(b.normalizar_citacao("Rcl\n4S.O12/SP", "ctx"), r1)
            self.assertEqual(b.chamadas, 0)
            self.assertIsNone(b.normalizar_citacao("Rcl\n4S.O13/SP", "ctx"))   # miss em somente_cache → None
            # importa o JSONL num cache novo
            cache3 = CacheLLM(":memory:")
            self.assertEqual(cache3.importar_jsonl(Path(d) / "export.jsonl"), 1)
            self.assertEqual(len(cache3), 1)

    def test_cache_do_ambiente(self) -> None:
        import os
        with tempfile.TemporaryDirectory() as d:
            antigo = os.environ.get("CACA_CACHE_LLM")
            os.environ["CACA_CACHE_LLM"] = str(Path(d) / "x.sqlite")
            try:
                c = CacheLLM.do_ambiente()
                self.assertTrue(c.ativo)
                self.assertTrue(Path(d, "x.sqlite").exists())
            finally:
                if antigo is None:
                    del os.environ["CACA_CACHE_LLM"]
                else:
                    os.environ["CACA_CACHE_LLM"] = antigo

    def test_cache_em_diretorio(self) -> None:
        # CACA_CACHE_LLM pode ser um diretório (config.caminho_cache_llm): o arquivo vai dentro
        with tempfile.TemporaryDirectory() as d:
            c = CacheLLM(Path(d) / "cache_llm")
            self.assertTrue(c.ativo)
            self.assertTrue(Path(d, "cache_llm", "arbitro_llm.sqlite").exists())
            c2 = CacheLLM(d)   # diretório existente
            self.assertEqual(Path(c2.caminho).name, "arbitro_llm.sqlite")

    def test_cache_quebrado_nao_derruba(self) -> None:
        c = CacheLLM("/dev/null/impossivel/c.sqlite")
        self.assertFalse(c.ativo)
        self.assertIsNone(c.obter("x"))
        c.guardar("x", modelo="m", revisao="r", prompt_versao="p", operacao="o", entrada={}, resposta_bruta="{}")
        a = _Roteirizado(['{"indice": 0}'], cache=c)
        self.assertEqual(a.escolher_candidato("t", "c", CANDIDATOS), 0)


# ---------------------------------------------------------------------------
# Mock em casos sintéticos
# ---------------------------------------------------------------------------
class TestMock(unittest.TestCase):
    def setUp(self) -> None:
        self.a = MockArbitro()

    def test_protocolo(self) -> None:
        self.assertIsInstance(self.a, Arbitro)

    def test_normalizar_ocr_pesado(self) -> None:
        r = self.a.normalizar_citacao("REsp 1.9SO.OO1/SP", "... o REsp 1.9SO.OO1/SP, que ...")
        self.assertEqual(r["numero_digitos"], "1950001")
        self.assertEqual(r["classe_cadeia"], ["RESP"])
        self.assertEqual((r["uf"], r["tribunal"], r["eh_citacao"]), ("SP", "STJ", True))

    def test_normalizar_tst_e_stm(self) -> None:
        r = self.a.normalizar_citacao("processo nº TST-ED-E-RR-77-l2.2013.5.09.0O11", "")
        self.assertEqual(r["classe_cadeia"], ["ED", "E", "RR"])
        self.assertEqual(r["digitos_canonicos"], "00000771220135090011")
        self.assertEqual(r["tribunal"], "TST")
        r = self.a.normalizar_citacao("APL 700O321-9S 2022 7 00 0000 (MG)", "")
        self.assertEqual(r["digitos_canonicos"], "70003219520227000000")
        self.assertEqual((r["uf"], r["tribunal"]), ("MG", "STM"))

    def test_normalizar_distrator(self) -> None:
        r = self.a.normalizar_citacao("fls. 1O2/1O5", "")
        self.assertFalse(r["eh_citacao"])
        self.assertEqual(r["numero_digitos"], "")

    def test_normalizar_tribunal_ambiguo(self) -> None:
        r = self.a.normalizar_citacao("Rcl\n4S.O12/SP", "")
        self.assertEqual(r["numero_digitos"], "45012")
        self.assertIsNone(r["tribunal"])

    def test_escolher_por_cadeia_exata(self) -> None:
        i = self.a.escolher_candidato("AgInt no REsp 1.777.888/PR", "como decidiu em 2019, Rel. Min. Beltrana Souza", CANDIDATOS)
        self.assertEqual(i, 0)

    def test_escolher_por_ano_e_relator(self) -> None:
        cands = [{"id_canonico": 3, "cabecalho": "x", "tribunal": "TST", "ano": 2018, "relator": "Fulano Lima", "cadeia": "RR"},
                 {"id_canonico": 4, "cabecalho": "y", "tribunal": "TST", "ano": 2021, "relator": "Sicrana Moreira", "cadeia": "RR"}]
        self.assertEqual(self.a.escolher_candidato("RR-1234-56.2015.5.04.0001",
                                                   "acolhida em 2021 no RR-1234-56.2015.5.04.0001, Rel. Min. Sicrana Moreira", cands), 1)
        self.assertEqual(self.a.escolher_candidato("RR-1234-56.2015.5.04.0001",
                                                   "acolhida no RR-1234-56.2015.5.04.0001, Rel. Min. Fulano Lima", cands), 0)

    def test_escolher_sem_criterio_devolve_none(self) -> None:
        cands = [{"id_canonico": 3, "cabecalho": "x", "tribunal": "TST", "ano": 2018, "relator": "Fulano Lima", "cadeia": "RR"},
                 {"id_canonico": 4, "cabecalho": "y", "tribunal": "TST", "ano": 2018, "relator": "Fulano Lima", "cadeia": "RR"}]
        self.assertIsNone(self.a.escolher_candidato("RR-1234-56.2015.5.04.0001", "acolhida no RR-1234-56.2015.5.04.0001", cands))

    def test_classificar_processo_ajusta_fronteiras(self) -> None:
        jan = "Nesse sentido, como se vê no A.REsp n° 2.111.333 (PE), que afastou a tese."
        r = self.a.classificar_span("n° 2.111.333 (PE)", jan)
        self.assertEqual(r["familia"], "processo")
        self.assertEqual(jan[r["inicio_rel"]:r["fim_rel"]], "A.REsp n° 2.111.333 (PE)")
        jan = "conforme o EDcl no AgInt no AREsp 1.234.567/RS, foi"
        r = self.a.classificar_span("AREsp 1.234.567", jan)
        self.assertEqual(r["trecho"], "EDcl no AgInt no AREsp 1.234.567/RS")
        jan = "como decidido no processo nº TST-E-RR-999-12.2011.5.15.0099, em que"
        r = self.a.classificar_span("999-12.2011.5.15.0099", jan)
        self.assertEqual(r["trecho"], "processo nº TST-E-RR-999-12.2011.5.15.0099")
        jan = "Invoca-se, ainda, o Agravo em Recurso\nEspecial nº 2.000.111/RJ, que"
        r = self.a.classificar_span("2.000.111/RJ", jan)
        self.assertEqual(r["trecho"], "Agravo em Recurso\nEspecial nº 2.000.111/RJ")

    def test_classificar_outras_familias(self) -> None:
        jan = "Ampara a pretensão o julgado do TSE proferido em 2020 pela relatoria de\nSICRANA DE OLIVEIRA, para o qual"
        r = self.a.classificar_span("2020 pela relatoria de\nSICRANA", jan)
        self.assertEqual(r["familia"], "vaga")
        self.assertEqual(r["trecho"], "julgado do TSE proferido em 2020 pela relatoria de\nSICRANA DE OLIVEIRA")
        jan = "viola o art 9O5, I, do Código de Defesa\ndo Consumidor, razão pela qual"
        r = self.a.classificar_span("art 9O5, I, do Código", jan)
        self.assertEqual((r["familia"], r["tipo"]), ("dispositivo", "lei"))
        self.assertEqual(r["trecho"], "art 9O5, I, do Código de Defesa\ndo Consumidor")
        jan = "Invoca-se, ainda, a Súmula 77\ndo STJ, segundo a qual"
        r = self.a.classificar_span("Súmula 77", jan)
        self.assertEqual((r["familia"], r["trecho"]), ("sumula", "Súmula 77\ndo STJ"))
        jan = "conforme o Tcma 1.234 da repercussão geral, a"
        r = self.a.classificar_span("Tcma 1.234", jan)
        self.assertEqual((r["familia"], r["trecho"]), ("tema", "Tcma 1.234 da repercussão geral"))

    def test_classificar_distratores(self) -> None:
        casos = [
            ("conforme consta às fls. 45/52 dos autos, o valor", "fls. 45/52"),
            ("a jurisprudência pacífica desta Corte, firmada em 2019, não socorre", "jurisprudência pacífica desta Corte, firmada em 2019"),
            ("Autos nº 0001234-56.2020.8.26.0100\nRecorrente: Fulano", "0001234-56.2020.8.26.0100"),
            ("o valor de R$ 12.345,00 foi", "12.345"),
            ("no ano de 2019 o tribunal", "2019"),
            ("advogado (OAB/SP 123456) requer", "123456"),
        ]
        for jan, cand in casos:
            r = self.a.classificar_span(cand, jan)
            self.assertIsNotNone(r, cand)
            self.assertFalse(r["eh_citacao"], cand)
            self.assertEqual(r["familia"], "nenhuma")

    def test_lote_preserva_ordem(self) -> None:
        saida = self.a.executar_lote("normalizar", [("REsp 1.9SO.OO1/SP", ""), ("fls. 1O2", ""), ("Rcl 4S.O12/SP", "")])
        self.assertEqual([s["numero_digitos"] for s in saida], ["1950001", "", "45012"])

    def test_determinismo(self) -> None:
        a1, a2 = MockArbitro(), MockArbitro()
        jan = "conforme o EDcl no AgInt no AREsp 1.234.567/RS, foi"
        self.assertEqual(a1.classificar_span("AREsp 1.234.567", jan), a2.classificar_span("AREsp 1.234.567", jan))

    def test_candidato_de_registro(self) -> None:
        class _Reg:
            id_canonico = "77"
            tribunal, ano, relator, classe_propria = "STJ", 2019, "Fulano", "AGINT RESP"

        c = candidato_de_registro(_Reg(), "cab " * 300)
        self.assertEqual(c["id_canonico"], 77)
        self.assertEqual(len(c["cabecalho"]), 600)
        self.assertEqual(c["cadeia"], "AGINT RESP")


# ---------------------------------------------------------------------------
# Prompts e fábrica
# ---------------------------------------------------------------------------
class TestPromptsEFabrica(unittest.TestCase):
    def test_mensagens_tem_sistema_e_usuario_e_sao_deterministicas(self) -> None:
        m1 = prompts.mensagens_normalizar("REsp 1S/SP", "ctx")
        m2 = prompts.mensagens_normalizar("REsp 1S/SP", "ctx")
        self.assertEqual(m1, m2)
        self.assertEqual([m["role"] for m in m1], ["system", "user"])
        self.assertIn("REsp 1S/SP", m1[1]["content"])
        m = prompts.mensagens_escolher("t", "c", CANDIDATOS)
        self.assertIn("[1]", m[1]["content"])
        self.assertIn("AGINT ERESP", m[1]["content"])
        m = prompts.mensagens_classificar("t", "janela t")
        self.assertIn("janela t", m[1]["content"])

    def test_recortar_contexto_mantem_trecho(self) -> None:
        ctx = "a" * 2000 + " REsp 1.234.567/SP " + "b" * 2000
        rec = prompts.recortar_contexto(ctx, "REsp 1.234.567/SP", 300)
        self.assertEqual(len(rec), 300)
        self.assertIn("REsp 1.234.567/SP", rec)
        self.assertEqual(prompts.recortar_contexto("curto", "x", 300), "curto")

    def test_esquemas_cobrem_operacoes(self) -> None:
        self.assertEqual(set(prompts.ESQUEMAS), set(prompts.OPERACOES))
        self.assertEqual(set(prompts.MAX_TOKENS_NOVOS), set(prompts.OPERACOES))

    def test_fabrica(self) -> None:
        self.assertIsNone(obter_arbitro("nenhum"))
        self.assertIsNone(obter_arbitro(None))
        self.assertIsInstance(obter_arbitro("mock"), MockArbitro)
        self.assertIsInstance(obter_arbitro("MOCK", cache=None), MockArbitro)
        with self.assertRaises(ValueError):
            obter_arbitro("gpt4")

    def test_fabrica_backends_reais_sem_dependencia(self) -> None:
        for nome in ("transformers", "vllm"):
            try:
                arb = obter_arbitro(nome, cache=None, revisao="deadbeef", somente_cache=True)
            except ErroDependencia as e:
                self.assertIsInstance(e, ImportError)
                self.assertIn(nome, str(e))
            else:  # dependência instalada: em somente_cache nada é carregado e a operação abstém
                self.assertEqual(arb.nome, nome)
                self.assertIsNone(arb.normalizar_citacao("REsp 1S/SP", "ctx"))

    def test_utilizacao_vllm_para_24gb(self) -> None:
        # 24 GB × 0,92 / 32 GB ≈ 0,69 (RTX 5090); numa GPU de 24 GB o teto é 0,90
        self.assertAlmostEqual(backends.VLLMArbitro._utilizacao_para(24.0, 32.0), 0.69)
        self.assertAlmostEqual(backends.VLLMArbitro._utilizacao_para(24.0, 24.0), 0.90)
        self.assertAlmostEqual(backends.VLLMArbitro._utilizacao_para(24.0, 0), 0.85)

    def test_limitar_vram_fracao(self) -> None:
        class _Props:
            total_memory = 32 * 1024 ** 3

        class _Cuda:
            chamadas: list[tuple[float, int]] = []

            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def get_device_properties(i: int) -> _Props:
                return _Props()

            @classmethod
            def set_per_process_memory_fraction(cls, f: float, i: int) -> None:
                cls.chamadas.append((f, i))

        class _Torch:
            cuda = _Cuda

        fr = backends._limitar_vram(_Torch, 24.0)
        self.assertAlmostEqual(fr, 0.75)
        self.assertEqual(_Cuda.chamadas, [(0.75, 0)])


# ---------------------------------------------------------------------------
# Backends reais com dependências FALSAS (exercita o código sem GPU/torch)
# ---------------------------------------------------------------------------
def _torch_falso(total_gb: float = 32.0) -> types.ModuleType:
    torch = types.ModuleType("torch")

    class _Cuda:
        fracoes: list[float] = []

        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def get_device_properties(i: int) -> Any:
            return types.SimpleNamespace(total_memory=int(total_gb * 1024 ** 3))

        @classmethod
        def set_per_process_memory_fraction(cls, f: float, i: int) -> None:
            cls.fracoes.append(f)

        @staticmethod
        def memory_allocated() -> int:
            return 15 * 1024 ** 3

    class _Ctx:
        def __enter__(self) -> "_Ctx":
            return self

        def __exit__(self, *a: object) -> bool:
            return False

    torch.cuda = _Cuda
    torch.manual_seed = lambda s: None
    torch.bfloat16 = "bf16"
    torch.backends = types.SimpleNamespace(
        cuda=types.SimpleNamespace(matmul=types.SimpleNamespace(allow_tf32=True)),
        cudnn=types.SimpleNamespace(allow_tf32=True))
    torch.inference_mode = lambda: _Ctx()
    return torch


class _TensorFalso:
    def __init__(self, dados: list[list[int]]) -> None:
        self.dados = dados

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.dados), len(self.dados[0]))

    def to(self, dev: str) -> "_TensorFalso":
        return self

    def __getitem__(self, idx: tuple[int, slice]) -> list[int]:
        j, sl = idx
        return self.dados[j][sl]


class _TokenizadorFalso:
    pad_token = None
    eos_token = "<eos>"
    pad_token_id = 0
    padding_side = "right"

    def apply_chat_template(self, msgs: list[dict[str, str]], tokenize: bool = False,
                            add_generation_prompt: bool = True) -> str:
        return msgs[1]["content"]

    def __call__(self, textos: list[str], return_tensors: str = "pt", padding: bool = True) -> dict[str, Any]:
        n = max(len(t) for t in textos)
        return {"input_ids": _TensorFalso([[1] * n for _ in textos]),
                "attention_mask": _TensorFalso([[1] * n for _ in textos])}

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        return "".join(chr(i) for i in ids)


class _ModeloFalso:
    device = "cuda"
    generation_config = types.SimpleNamespace(do_sample=True)
    kwargs_vistos: list[dict[str, Any]] = []

    def eval(self) -> "_ModeloFalso":
        return self

    def generate(self, input_ids: _TensorFalso, attention_mask: _TensorFalso, **kw: Any) -> _TensorFalso:
        self.kwargs_vistos.append(kw)
        n = input_ids.shape[1]
        resp = json.dumps({"classe_cadeia": ["RESP"], "numero_digitos": "1950001", "uf": "SP",
                           "tribunal": "STJ", "eh_citacao": True})
        return _TensorFalso([[1] * n + [ord(c) for c in resp] for _ in range(input_ids.shape[0])])


class TestBackendsComDependenciasFalsas(unittest.TestCase):
    def setUp(self) -> None:
        self._salvos = {k: sys.modules.get(k) for k in ("torch", "transformers", "vllm", "vllm.sampling_params")}
        self.chamadas: dict[str, Any] = {}
        torch = _torch_falso()
        tr = types.ModuleType("transformers")
        chamadas = self.chamadas

        class AutoTokenizer:
            @staticmethod
            def from_pretrained(m: str, revision: str | None = None, local_files_only: bool = False) -> Any:
                chamadas["tok"] = (m, revision, local_files_only)
                return _TokenizadorFalso()

        class AutoModelForCausalLM:
            @staticmethod
            def from_pretrained(m: str, device_map: str | None = None, **kw: Any) -> Any:
                chamadas["model"] = (m, device_map, kw)
                return _ModeloFalso()

        tr.AutoTokenizer = AutoTokenizer
        tr.AutoModelForCausalLM = AutoModelForCausalLM
        sys.modules["torch"] = torch
        sys.modules["transformers"] = tr
        self.torch = torch

    def tearDown(self) -> None:
        for k, v in self._salvos.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def test_transformers_limita_vram_repassa_revisao_e_gera_em_lote(self) -> None:
        _ModeloFalso.kwargs_vistos.clear()
        a = obter_arbitro("transformers", cache=":memory:", revisao="deadbeef", lote=2)
        self.assertEqual(a.nome, "transformers")
        self.assertAlmostEqual(self.torch.cuda.fracoes[-1], 0.75)                 # 24 GB de 32 GB
        self.assertEqual(self.chamadas["tok"][1], "deadbeef")
        self.assertEqual(self.chamadas["model"][2]["revision"], "deadbeef")
        self.assertEqual(self.chamadas["model"][2]["torch_dtype"], "bf16")
        self.assertIn("bf16", a.assinatura)
        r = a.normalizar_citacao("REsp 1.9SO.OO1/SP", "no REsp 1.9SO.OO1/SP, que")
        self.assertEqual(r["numero_digitos"], "1950001")
        kw = _ModeloFalso.kwargs_vistos[-1]
        self.assertFalse(kw["do_sample"])
        self.assertEqual(kw["num_beams"], 1)
        self.assertIsNone(kw["temperature"])
        self.assertLessEqual(kw["max_new_tokens"], prompts.MAX_TOKENS_NOVOS["normalizar"])
        saida = a.executar_lote("normalizar", [("REsp 1.9SO.OO1/SP", "a"), ("REsp 1.9SO.OO1/SP", "b"),
                                               ("REsp 1.9SO.OO1/SP", "c")])
        self.assertEqual(len(saida), 3)
        self.assertEqual(len(_ModeloFalso.kwargs_vistos), 1 + 2)                 # 3 misses em lotes de 2
        self.assertEqual(a.chamadas, 4)

    def test_transformers_4bit_por_ambiente(self) -> None:
        import os
        tr = sys.modules["transformers"]

        class BitsAndBytesConfig:
            def __init__(self, **kw: Any) -> None:
                self.kw = kw

        tr.BitsAndBytesConfig = BitsAndBytesConfig
        os.environ["CACA_LLM_4BIT"] = "1"
        try:
            a = obter_arbitro("transformers", cache=None, revisao="r")
        finally:
            del os.environ["CACA_LLM_4BIT"]
        self.assertIn("nf4", a.assinatura)
        self.assertTrue(self.chamadas["model"][2]["quantization_config"].kw["load_in_4bit"])

    def test_vllm_utilizacao_e_geracao(self) -> None:
        vllm = types.ModuleType("vllm")
        sp = types.ModuleType("vllm.sampling_params")
        registro: dict[str, Any] = {}

        class SamplingParams:
            def __init__(self, **kw: Any) -> None:
                self.kw = kw

        class GuidedDecodingParams:
            def __init__(self, json: Any = None) -> None:
                self.json = json

        class LLM:
            def __init__(self, **kw: Any) -> None:
                registro["llm"] = kw

            def get_tokenizer(self) -> Any:
                return _TokenizadorFalso()

            def generate(self, textos: list[str], params: Any, use_tqdm: bool = False) -> list[Any]:
                registro["params"] = params.kw
                resp = json.dumps({"indice": 1, "evidencia": "ano"})
                return [types.SimpleNamespace(outputs=[types.SimpleNamespace(text=resp)]) for _ in textos]

        vllm.LLM, vllm.SamplingParams = LLM, SamplingParams
        sp.GuidedDecodingParams = GuidedDecodingParams
        sys.modules["vllm"], sys.modules["vllm.sampling_params"] = vllm, sp
        a = obter_arbitro("vllm", cache=":memory:", revisao="cafe")
        self.assertAlmostEqual(registro["llm"]["gpu_memory_utilization"], 0.69)   # 24·0,92/32
        self.assertEqual(registro["llm"]["revision"], "cafe")
        self.assertEqual(registro["llm"]["dtype"], "bfloat16")
        self.assertEqual(a.escolher_candidato("AgInt no REsp 1.777.888/PR", "em 2019", CANDIDATOS), 1)
        self.assertEqual(registro["params"]["temperature"], 0.0)
        self.assertIsInstance(registro["params"]["guided_decoding"], GuidedDecodingParams)
        self.assertEqual(registro["params"]["guided_decoding"].json, prompts.ESQUEMAS["escolher"])


if __name__ == "__main__":
    unittest.main()
