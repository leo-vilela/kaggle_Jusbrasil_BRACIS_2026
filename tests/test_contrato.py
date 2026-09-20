"""Testes do contrato (schema 1.2): escrita, carga e validador.

Todos os textos e números são SINTÉTICOS.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao.contrato import (  # noqa: E402
    CHAVES_CITACAO,
    CHAVES_SAIDA,
    Citacao,
    ErroContrato,
    SaidaDocumento,
    carregar,
    carregar_citacoes,
    validar,
    validar_arquivo,
)

TEXTO = (
    "TRIBUNAL DE ALGUM LUGAR\n\nAutos nº 1234567-89.2020.4.05.0001\n\n"
    "Como se decidiu no REsp 1.111.222/SP, a tese prevalece. Invoca-se também o "
    "julgado do STJ proferido em 2021 pela relatoria de Fulano de Tal, e ainda o "
    "art. 11 da Constituição Federal, além da Súmula 999 do STF.\n"
)


def _span(sub: str) -> tuple[int, int]:
    i = TEXTO.index(sub)
    return i, i + len(sub)


def citacoes_validas() -> list[Citacao]:
    a = _span("REsp 1.111.222/SP")
    b = _span("julgado do STJ proferido em 2021 pela relatoria de Fulano de Tal")
    c = _span("art. 11 da Constituição Federal")
    d = _span("Súmula 999 do STF")
    return [
        Citacao("x", d[0], d[1], TEXTO[d[0]:d[1]], "jurisprudencia", "inventada", None, 0.9),
        Citacao("x", a[0], a[1], TEXTO[a[0]:a[1]], "jurisprudencia", "real", "123456789", 0.95),
        Citacao("x", c[0], c[1], TEXTO[c[0]:c[1]], "lei", "real", 987654321, 0.8),
        Citacao("x", b[0], b[1], TEXTO[b[0]:b[1]], "jurisprudencia", "incompleta", None, None),
    ]


def saida_valida() -> dict:
    return SaidaDocumento.montar("doc_teste", citacoes_validas()).para_dicionario()


class TestEscrita(unittest.TestCase):
    def test_ordem_das_chaves_e_ids(self) -> None:
        d = saida_valida()
        self.assertEqual(list(d.keys()), list(CHAVES_SAIDA))
        self.assertEqual(d["schema_version"], "1.2")
        self.assertEqual([c["id"] for c in d["citacoes"]], ["c1", "c2", "c3", "c4"])
        inicios = [c["inicio"] for c in d["citacoes"]]
        self.assertEqual(inicios, sorted(inicios))
        for c in d["citacoes"]:
            self.assertEqual(list(c.keys()), list(CHAVES_CITACAO))

    def test_resolucao_so_em_real_e_id_como_string(self) -> None:
        d = saida_valida()
        por_classe = {c["classificacao"]: c for c in d["citacoes"]}
        self.assertEqual(por_classe["real"]["resolucao"]["fonte"], "jusbrasil")
        self.assertIsInstance(por_classe["real"]["resolucao"]["id_canonico"], str)
        self.assertIsNone(por_classe["inventada"]["resolucao"])
        self.assertIsNone(por_classe["incompleta"]["resolucao"])
        self.assertIsNone(por_classe["incompleta"]["confianca"])
        # inteiro vira string de dígitos
        lei = next(c for c in d["citacoes"] if c["tipo"] == "lei")
        self.assertEqual(lei["resolucao"]["id_canonico"], "987654321")

    def test_escrever_e_carregar(self) -> None:
        saida = SaidaDocumento.montar("doc_teste", citacoes_validas())
        with tempfile.TemporaryDirectory() as tmp:
            arq = saida.escrever(Path(tmp) / "sub" / "doc_teste.json")
            bruto = arq.read_text(encoding="utf-8")
            self.assertIn("Súmula", bruto)              # ensure_ascii=False
            self.assertTrue(bruto.startswith("{\n  \"schema_version\""))  # indent=2
            self.assertEqual(json.loads(bruto), saida.para_dicionario())
            lida = carregar(arq, TEXTO)
            self.assertEqual(lida.para_dicionario(), saida.para_dicionario())
            cits = carregar_citacoes(arq, TEXTO)
            self.assertEqual([c.id for c in cits], ["c1", "c2", "c3", "c4"])
            self.assertIsInstance(cits[0], Citacao)
            self.assertEqual(validar_arquivo(arq, TEXTO), [])

    def test_carregar_invalido_levanta(self) -> None:
        d = saida_valida()
        d["citacoes"][0]["classificacao"] = "talvez"
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / "doc_teste.json"
            arq.write_text(json.dumps(d), encoding="utf-8")
            with self.assertRaises(ErroContrato) as ctx:
                carregar_citacoes(arq)
            self.assertTrue(any("classificacao" in e for e in ctx.exception.erros))
            self.assertEqual(len(carregar(arq, estrito=False).citacoes), 4)


class TestValidador(unittest.TestCase):
    def assertViola(self, saida: dict, fragmento: str, texto: str | None = TEXTO) -> None:
        erros = validar(saida, texto)
        self.assertTrue(erros, "esperava violação")
        self.assertTrue(any(fragmento in e for e in erros), f"{fragmento!r} não está em {erros}")

    def test_valida(self) -> None:
        self.assertEqual(validar(saida_valida(), TEXTO), [])
        self.assertEqual(validar(saida_valida(), None), [])
        vazio = SaidaDocumento("doc_vazio").para_dicionario()
        self.assertEqual(validar(vazio, ""), [])

    def test_raiz(self) -> None:
        self.assertEqual(validar([], TEXTO), ["a saída deve ser um objeto JSON"])
        d = saida_valida()
        d["schema_version"] = "1.1"
        self.assertViola(d, "schema_version")
        d = saida_valida()
        d["schema_version"] = 1.2
        self.assertViola(d, "schema_version")
        d = saida_valida()
        d["documento_id"] = ""
        self.assertViola(d, "documento_id")
        d = saida_valida()
        d["citacoes"] = None
        self.assertViola(d, "'citacoes' deve ser uma lista")
        d = saida_valida()
        d["extra"] = 1
        self.assertViola(d, "campos desconhecidos na raiz")

    def test_campos_ausentes_e_desconhecidos(self) -> None:
        d = saida_valida()
        del d["citacoes"][0]["trecho"]
        self.assertViola(d, "campos ausentes ['trecho']")
        d = saida_valida()
        d["citacoes"][0]["familia"] = "processo"
        self.assertViola(d, "campos desconhecidos ['familia']")
        d = saida_valida()
        d["citacoes"][0] = "texto"
        self.assertViola(d, "deve ser um objeto JSON")

    def test_span(self) -> None:
        d = saida_valida()
        d["citacoes"][0]["inicio"] = d["citacoes"][0]["fim"]
        self.assertViola(d, "span inválido")
        d = saida_valida()
        d["citacoes"][0]["inicio"] = -1
        self.assertViola(d, "span inválido")
        d = saida_valida()
        d["citacoes"][0]["inicio"] = "10"
        self.assertViola(d, "'inicio' deve ser inteiro")
        d = saida_valida()
        d["citacoes"][0]["fim"] = 10.0
        self.assertViola(d, "'fim' deve ser inteiro")
        d = saida_valida()
        d["citacoes"][0]["fim"] = True
        self.assertViola(d, "'fim' deve ser inteiro")
        d = saida_valida()
        d["citacoes"][-1]["fim"] = len(TEXTO) + 5
        d["citacoes"][-1]["trecho"] = d["citacoes"][-1]["trecho"] + "xxxxx"
        self.assertViola(d, "ultrapassa o texto")

    def test_trecho(self) -> None:
        d = saida_valida()
        d["citacoes"][0]["trecho"] = ""
        self.assertViola(d, "'trecho' deve ser string não vazia")
        d = saida_valida()
        c = d["citacoes"][0]
        c["trecho"] = c["trecho"][:-1] + "X"
        self.assertViola(d, "trecho difere de texto")
        self.assertEqual(validar(d, None), [])       # sem texto, só o tamanho é conferido
        c["trecho"] = c["trecho"] + "Y"
        self.assertViola(d, "len(trecho)", texto=None)

    def test_enums(self) -> None:
        d = saida_valida()
        d["citacoes"][0]["tipo"] = "sumula"
        self.assertViola(d, "'tipo'")
        d = saida_valida()
        d["citacoes"][0]["classificacao"] = "Real"
        self.assertViola(d, "'classificacao'")

    def test_resolucao(self) -> None:
        d = saida_valida()
        real = next(c for c in d["citacoes"] if c["classificacao"] == "real")
        real["resolucao"] = None
        self.assertViola(d, "classificacao=real exige 'resolucao'")
        real["resolucao"] = {"fonte": "jusbrasil", "id_canonico": "12a34"}
        self.assertViola(d, "só de dígitos")
        real["resolucao"] = {"fonte": "jusbrasil", "id_canonico": 123}
        self.assertViola(d, "só de dígitos")
        real["resolucao"] = {"fonte": "jusbrasil", "id_canonico": ""}
        self.assertViola(d, "só de dígitos")
        real["resolucao"] = {"fonte": "outra", "id_canonico": "123"}
        self.assertViola(d, "resolucao.fonte")
        real["resolucao"] = {"fonte": "jusbrasil", "id_canonico": "123", "url": "x"}
        self.assertViola(d, "resolucao com campos desconhecidos")
        d = saida_valida()
        inv = next(c for c in d["citacoes"] if c["classificacao"] == "inventada")
        inv["resolucao"] = {"fonte": "jusbrasil", "id_canonico": "123"}
        self.assertViola(d, "deve ser null quando classificacao=inventada")

    def test_confianca(self) -> None:
        for ruim in (1.5, -0.1, "0.9", True, float("nan")):
            d = saida_valida()
            d["citacoes"][0]["confianca"] = ruim
            self.assertViola(d, "'confianca'")
        d = saida_valida()
        d["citacoes"][0]["confianca"] = 1
        self.assertEqual(validar(d, TEXTO), [])
        d["citacoes"][0]["confianca"] = 0
        self.assertEqual(validar(d, TEXTO), [])

    def test_ids_repetidos(self) -> None:
        d = saida_valida()
        d["citacoes"][1]["id"] = d["citacoes"][0]["id"]
        self.assertViola(d, "repetido")
        d = saida_valida()
        d["citacoes"][0]["id"] = ""
        self.assertViola(d, "'id' deve ser string não vazia")

    def test_sobreposicao_e_fatal(self) -> None:
        d = saida_valida()
        c = copy.deepcopy(d["citacoes"][1])
        c["id"] = "c9"
        c["inicio"] += 1
        c["trecho"] = c["trecho"][1:]
        d["citacoes"].append(c)
        self.assertViola(d, "FATAL")
        # IoU abaixo de 0,5 não é fatal: span curto dentro de um longo
        d = saida_valida()
        longa = d["citacoes"][2]                     # a citação "vaga", longa
        curta = copy.deepcopy(longa)
        curta["id"] = "c9"
        curta["fim"] = curta["inicio"] + 4
        curta["trecho"] = TEXTO[curta["inicio"]:curta["fim"]]
        d["citacoes"].append(curta)
        self.assertEqual([e for e in validar(d, TEXTO) if "FATAL" in e], [])


if __name__ == "__main__":
    unittest.main()
