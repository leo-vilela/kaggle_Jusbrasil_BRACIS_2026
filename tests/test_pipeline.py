"""Testes do pipeline com detector/resolvedor/calibrador FALSOS (textos sintéticos)."""
from __future__ import annotations

import json
import logging
import math
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from conftest_paths import DB, INDICE, TEM_DADOS  # noqa: E402

from caca_alucinacao.config import CONFIANCA_PADRAO  # noqa: E402
from caca_alucinacao.contrato import SaidaDocumento, validar  # noqa: E402
from caca_alucinacao.pipeline import (  # noqa: E402
    ErroPipeline,
    Rastro,
    carregar_texto,
    listar_documentos,
    processar_pasta,
    processar_texto,
    processar_texto_com_rastro,
)
from caca_alucinacao.tipos import Achado, Decisao  # noqa: E402

TEXTO = (
    "TRIBUNAL DE ALGUM LUGAR\n\nAutos nº 1234567-89.2020.4.05.0001\n\n"
    "Como se decidiu no REsp 1.111.222/SP, a tese prevalece. Invoca-se também o "
    "julgado do STJ proferido em 2021 pela relatoria de Fulano de Tal, e ainda o "
    "art. 11 da Constituição Federal, além da Súmula 999 do STF e da Rcl 77.777/RJ.\n"
)
BASE = {"1111222": 555000111, "CF|11": 777000222}   # "base canônica" falsa: dígitos → id_canonico

ESPECIFICACOES = [
    ("REsp 1.111.222/SP", "processo", "jurisprudencia", {"digitos": "1111222"}, 1.0),
    ("julgado do STJ proferido em 2021 pela relatoria de Fulano de Tal", "vaga", "jurisprudencia", {}, 0.8),
    ("art. 11 da Constituição Federal", "dispositivo", "lei", {"diploma": "CF", "artigo": "11"}, 1.0),
    ("Súmula 999 do STF", "sumula", "jurisprudencia", {"numero_sumula": "999"}, 1.0),
    ("Rcl 77.777/RJ", "processo", "jurisprudencia", {"digitos": "77777"}, 1.0),
]


def achado_de(texto: str, sub: str, familia: str, tipo: str, dados: dict, forca: float = 1.0,
              origem: str = "regex:falso", deslocar: int = 0, trecho: str | None = None) -> Achado:
    i = texto.index(sub) + deslocar
    f = i + len(sub)
    return Achado(i, f, texto[i:f] if trecho is None else trecho, familia, tipo, dict(dados), origem, forca)


def detector_padrao(texto: str) -> list[Achado]:
    achados = [achado_de(texto, *spec) for spec in ESPECIFICACOES if spec[0] in texto]
    return list(reversed(achados))   # desordenado de propósito


def resolvedor_falso(achado: Achado, base: dict) -> Decisao:
    if achado.familia == "vaga":
        return Decisao("incompleta", None, "vaga:incompleta")
    if achado.familia == "dispositivo":
        chave = f"{achado.dados.get('diploma')}|{achado.dados.get('artigo')}"
    else:
        chave = achado.dados.get("digitos", "")
    if chave in base:
        return Decisao("real", base[chave], f"{achado.familia}:1candidato", (base[chave],))
    return Decisao("inventada", None, f"{achado.familia}:0candidatos")


def calibrador_falso(decisao: Decisao, achado: Achado, tabela: dict) -> float:
    return tabela.get(decisao.caminho, 0.75) * achado.forca


class TestProcessarTexto(unittest.TestCase):
    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    def processar(self, **kw):
        kw.setdefault("detector", detector_padrao)
        kw.setdefault("resolvedor", resolvedor_falso)
        kw.setdefault("calibrador", calibrador_falso)
        return processar_texto_com_rastro("doc_x", TEXTO, BASE, **kw)

    def test_saida_valida_ordenada_e_tipada(self) -> None:
        saida, rastros = self.processar(tabela_calibracao={"vaga:incompleta": 0.9})
        self.assertIsInstance(saida, SaidaDocumento)
        d = saida.para_dicionario()
        self.assertEqual(validar(d, TEXTO), [])
        self.assertEqual([c["id"] for c in d["citacoes"]], ["c1", "c2", "c3", "c4", "c5"])
        self.assertEqual([c["classificacao"] for c in d["citacoes"]],
                         ["real", "incompleta", "real", "inventada", "inventada"])
        self.assertEqual(d["citacoes"][0]["resolucao"], {"fonte": "jusbrasil", "id_canonico": "555000111"})
        self.assertEqual(d["citacoes"][2]["resolucao"]["id_canonico"], "777000222")
        self.assertEqual(d["citacoes"][2]["tipo"], "lei")
        self.assertIsNone(d["citacoes"][1]["resolucao"])
        self.assertAlmostEqual(d["citacoes"][1]["confianca"], 0.9 * 0.8)   # tabela × força
        self.assertAlmostEqual(d["citacoes"][0]["confianca"], 0.75)
        self.assertEqual([r.status for r in rastros], ["emitida"] * 5)
        self.assertEqual(rastros[0].decisao.caminho, "processo:1candidato")
        self.assertEqual(json.loads(saida.para_json())["documento_id"], "doc_x")
        # processar_texto (sem rastro) devolve o mesmo
        so_saida = processar_texto("doc_x", TEXTO, BASE, detector=detector_padrao,
                                   resolvedor=resolvedor_falso, calibrador=calibrador_falso,
                                   tabela_calibracao={"vaga:incompleta": 0.9})
        self.assertEqual(so_saida.para_dicionario(), d)

    def test_documento_sem_citacao(self) -> None:
        saida, rastros = self.processar(detector=lambda t: [])
        self.assertEqual(saida.citacoes, [])
        self.assertEqual(rastros, [])
        self.assertEqual(validar(saida.para_dicionario(), TEXTO), [])
        self.assertEqual(saida.para_dicionario()["citacoes"], [])

    def test_detector_que_falha_nao_derruba(self) -> None:
        def detector_ruim(texto: str) -> list[Achado]:
            raise RuntimeError("bum")

        saida, _ = self.processar(detector=detector_ruim)
        self.assertEqual(saida.citacoes, [])

    def test_trecho_errado_e_corrigido_e_span_fora_descartado(self) -> None:
        def detector(texto: str) -> list[Achado]:
            a = achado_de(texto, "REsp 1.111.222/SP", "processo", "jurisprudencia", {"digitos": "1111222"},
                          trecho="REsp 1.111.222/XX")
            fora = Achado(len(texto) - 3, len(texto) + 10, "x" * 13, "processo", "jurisprudencia")
            return [a, fora]

        saida, rastros = self.processar(detector=detector)
        self.assertEqual(len(saida.citacoes), 1)
        self.assertEqual(saida.citacoes[0].trecho, "REsp 1.111.222/SP")
        self.assertEqual(validar(saida.para_dicionario(), TEXTO), [])
        self.assertEqual([r.status for r in rastros if r.status != "emitida"], ["descartada:span"])

    def test_sobreposicao_mantem_maior_forca(self) -> None:
        def detector(texto: str) -> list[Achado]:
            forte = achado_de(texto, "REsp 1.111.222/SP", "processo", "jurisprudencia", {"digitos": "1111222"}, 1.0)
            # mesmo span deslocado 1 à direita e 1 mais curto (IoU alto), força menor
            fraco = Achado(forte.inicio + 1, forte.fim - 1, texto[forte.inicio + 1:forte.fim - 1], "processo",
                           "jurisprudencia", {"digitos": "9"}, "regex:amplo", 0.6)
            return [fraco, forte]

        saida, rastros = self.processar(detector=detector)
        self.assertEqual(len(saida.citacoes), 1)
        self.assertEqual(saida.citacoes[0].classificacao, "real")
        descartados = [r for r in rastros if r.status == "descartada:sobreposicao"]
        self.assertEqual(len(descartados), 1)
        self.assertEqual(descartados[0].achado.forca, 0.6)

    def test_sobreposicao_empate_mantem_mais_longo(self) -> None:
        def detector(texto: str) -> list[Achado]:
            longo = achado_de(texto, "REsp 1.111.222/SP", "processo", "jurisprudencia", {"digitos": "1111222"})
            curto = Achado(longo.inicio, longo.fim - 3, texto[longo.inicio:longo.fim - 3], "processo",
                           "jurisprudencia", {"digitos": "9"})
            return [curto, longo]

        saida, _ = self.processar(detector=detector)
        self.assertEqual(saida.citacoes[0].trecho, "REsp 1.111.222/SP")

    def test_excecao_na_resolucao_omite_so_a_citacao(self) -> None:
        def resolvedor(achado: Achado, base: dict) -> Decisao:
            if achado.familia == "sumula":
                raise KeyError("sem tabela")
            return resolvedor_falso(achado, base)

        saida, rastros = self.processar(resolvedor=resolvedor)
        self.assertEqual(len(saida.citacoes), 4)
        self.assertNotIn("sumula", [r.achado.familia for r in rastros if r.status == "emitida"])
        omitidos = [r for r in rastros if r.status == "omitida:erro_resolucao"]
        self.assertEqual(len(omitidos), 1)
        self.assertIn("KeyError", omitidos[0].erro)
        self.assertEqual(validar(saida.para_dicionario(), TEXTO), [])

    def test_calibrador_defeituoso(self) -> None:
        def calibrador(decisao: Decisao, achado: Achado, tabela: dict) -> float:
            if achado.familia == "vaga":
                raise ValueError("x")
            if achado.familia == "sumula":
                return 1.7
            if achado.familia == "dispositivo":
                return float("nan")
            return -2.0

        saida, _ = self.processar(calibrador=calibrador)
        # ordem de posição: processo, vaga, dispositivo, sumula, processo
        por_familia = dict(zip(["processo", "vaga", "dispositivo", "sumula", "processo2"],
                               [c.confianca for c in saida.citacoes]))
        self.assertEqual(por_familia["vaga"], CONFIANCA_PADRAO)      # exceção → padrão
        self.assertEqual(por_familia["sumula"], 1.0)                 # 1.7 → teto 1.0
        self.assertEqual(por_familia["dispositivo"], CONFIANCA_PADRAO)  # NaN → padrão
        self.assertEqual(por_familia["processo"], 0.0)               # -2.0 → piso 0.0
        self.assertEqual(validar(saida.para_dicionario(), TEXTO), [])
        self.assertFalse(any(c.confianca is None or math.isnan(c.confianca) for c in saida.citacoes))

    def test_calibrador_de_reserva_usa_tabela(self) -> None:
        from caca_alucinacao.pipeline import _confianca_fixa

        d = Decisao("inventada", None, "processo:0candidatos")
        a = achado_de(TEXTO, "Rcl 77.777/RJ", "processo", "jurisprudencia", {})
        self.assertEqual(_confianca_fixa(d, a, {"processo:0candidatos": 0.93}), 0.93)
        self.assertEqual(_confianca_fixa(d, a, {}), CONFIANCA_PADRAO)

    def test_arbitro_repassado_quando_aceito(self) -> None:
        recebidos: list = []

        def resolvedor_com_arbitro(achado: Achado, base: dict, arbitro=None) -> Decisao:
            recebidos.append(arbitro)
            return resolvedor_falso(achado, base)

        sentinela = object()
        self.processar(resolvedor=resolvedor_com_arbitro, arbitro=sentinela)
        self.assertTrue(recebidos and all(r is sentinela for r in recebidos))
        # resolvedor sem o parâmetro: árbitro ignorado, sem erro
        saida, _ = self.processar(arbitro=sentinela)
        self.assertEqual(len(saida.citacoes), 5)

    def test_decisao_invalida_e_omitida(self) -> None:
        class DecisaoTorta:
            classificacao = "real"
            id_canonico = "abc"      # não é dígito
            caminho = "x"
            candidatos = ()

        def resolvedor(achado: Achado, base: dict) -> Decisao:
            return DecisaoTorta() if achado.familia == "sumula" else resolvedor_falso(achado, base)

        saida, rastros = self.processar(resolvedor=resolvedor)
        self.assertEqual(len(saida.citacoes), 4)
        self.assertEqual([r.status for r in rastros if r.status.startswith("omitida")], ["omitida:invalida"])

    def test_rastro_serializavel(self) -> None:
        _, rastros = self.processar()
        for r in rastros:
            self.assertIsInstance(r, Rastro)
            d = r.para_dicionario()
            json.dumps(d)
            self.assertEqual(d["status"], "emitida")
            self.assertIn("caminho", d)


class TestProcessarPasta(unittest.TestCase):
    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    def test_um_json_por_txt_em_ordem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entrada, saida = Path(tmp) / "in", Path(tmp) / "out"
            entrada.mkdir()
            (entrada / "b_doc.txt").write_bytes(TEXTO.encode("utf-8"))
            (entrada / "a_doc.txt").write_bytes("Sem nenhuma citação aqui.\n".encode("utf-8"))
            (entrada / "c_doc.txt").write_bytes(TEXTO.replace("\n", "\r\n").encode("utf-8"))
            (entrada / "ignorar.md").write_text("x", encoding="utf-8")
            escritos = processar_pasta(entrada, saida, BASE, detector=detector_padrao,
                                       resolvedor=resolvedor_falso, calibrador=calibrador_falso,
                                       rastro_para=saida / "rastro.jsonl")
            self.assertEqual([p.name for p in escritos], ["a_doc.json", "b_doc.json", "c_doc.json"])
            self.assertEqual(sorted(p.name for p in saida.glob("*.json")), ["a_doc.json", "b_doc.json", "c_doc.json"])
            for p in escritos:
                d = json.loads(p.read_text(encoding="utf-8"))
                texto = carregar_texto(entrada / f"{p.stem}.txt")
                self.assertEqual(validar(d, texto), [], p.name)
                self.assertEqual(d["documento_id"], p.stem)
            a = json.loads((saida / "a_doc.json").read_text(encoding="utf-8"))
            self.assertEqual(a["citacoes"], [])
            c = json.loads((saida / "c_doc.json").read_text(encoding="utf-8"))
            self.assertEqual(len(c["citacoes"]), 5)          # CRLF não desloca offsets
            self.assertIn("\r\n", carregar_texto(entrada / "c_doc.txt"))
            linhas = (saida / "rastro.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(linhas), 10)
            self.assertEqual(json.loads(linhas[0])["documento_id"], "b_doc")
            self.assertEqual(listar_documentos(entrada)[0].name, "a_doc.txt")

    def test_documento_que_falha_gera_json_vazio(self) -> None:
        def resolvedor_explosivo(achado: Achado, base: dict) -> Decisao:
            raise RuntimeError("sempre")

        with tempfile.TemporaryDirectory() as tmp:
            entrada, saida = Path(tmp) / "in", Path(tmp) / "out"
            entrada.mkdir()
            (entrada / "doc.txt").write_bytes(TEXTO.encode("utf-8"))
            escritos = processar_pasta(entrada, saida, BASE, detector=detector_padrao,
                                       resolvedor=resolvedor_explosivo, calibrador=calibrador_falso, limite=5)
            d = json.loads(escritos[0].read_text(encoding="utf-8"))
            self.assertEqual(d["citacoes"], [])
            self.assertEqual(validar(d, TEXTO), [])

    def test_pasta_inexistente(self) -> None:
        with self.assertRaises(ErroPipeline):
            listar_documentos(Path("/nao/existe/mesmo"))

    def test_documento_nao_utf8_e_contado_no_resumo(self) -> None:   # R3b-06 (rodada 2)
        logging.disable(logging.NOTSET)
        with tempfile.TemporaryDirectory() as tmp:
            entrada, saida = Path(tmp) / "in", Path(tmp) / "out"
            entrada.mkdir()
            (entrada / "latin.txt").write_bytes(TEXTO.encode("latin-1"))
            (entrada / "utf8.txt").write_bytes(TEXTO.encode("utf-8"))
            with self.assertLogs("caca_alucinacao", level="ERROR") as cm:
                escritos = processar_pasta(entrada, saida, BASE, detector=detector_padrao,
                                           resolvedor=resolvedor_falso, calibrador=calibrador_falso)
            self.assertEqual(len(escritos), 2)   # o lote nunca é derrubado
            self.assertTrue(any("1 documento(s) não eram UTF-8" in m for m in cm.output), cm.output)
            self.assertTrue(any("latin.txt não é UTF-8" in m for m in cm.output), cm.output)


class TestCli(unittest.TestCase):
    """Exercita os imports tardios injetando módulos falsos em ``sys.modules``."""

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "in").mkdir()
        (self.tmp / "in" / "doc_1.txt").write_bytes(TEXTO.encode("utf-8"))
        (self.tmp / "in" / "doc_2.txt").write_bytes(b"Nada.\n")
        self._salvos = {n: sys.modules.get(n) for n in ("caca_alucinacao.deteccao", "caca_alucinacao.resolucao",
                                                        "caca_alucinacao.calibracao")}
        deteccao = types.ModuleType("caca_alucinacao.deteccao")
        deteccao.detectar = detector_padrao
        resolucao = types.ModuleType("caca_alucinacao.resolucao")
        resolucao.resolver = lambda achado, base: resolvedor_falso(achado, BASE)
        calibracao = types.ModuleType("caca_alucinacao.calibracao")
        calibracao.confianca = calibrador_falso
        sys.modules["caca_alucinacao.deteccao"] = deteccao
        sys.modules["caca_alucinacao.resolucao"] = resolucao
        sys.modules["caca_alucinacao.calibracao"] = calibracao

    def tearDown(self) -> None:
        for nome, mod in self._salvos.items():
            if mod is None:
                sys.modules.pop(nome, None)
            else:
                sys.modules[nome] = mod
        logging.disable(logging.NOTSET)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sem_banco_retorna_2(self) -> None:
        from caca_alucinacao.cli import main

        codigo = main(["--input", str(self.tmp / "in"), "--output", str(self.tmp / "out"),
                       "--db", str(self.tmp / "nao_existe.db"), "--indice", str(self.tmp / "nao_existe.json"),
                       "--log-level", "ERROR"])
        self.assertEqual(codigo, 2)
        self.assertFalse((self.tmp / "out").exists())

    @unittest.skipUnless(TEM_DADOS, "dados do desafio ausentes")
    def test_ponta_a_ponta_com_indice(self) -> None:
        from caca_alucinacao.cli import main

        (self.tmp / "calib.json").write_text(json.dumps({"vaga:incompleta": 0.9}), encoding="utf-8")
        codigo = main(["--input", str(self.tmp / "in"), "--output", str(self.tmp / "out"),
                       "--db", str(DB), "--indice", str(INDICE), "--calibracao", str(self.tmp / "calib.json"),
                       "--rastro", str(self.tmp / "rastro.jsonl"), "--arbitro", "nenhum", "--log-level", "ERROR"])
        self.assertEqual(codigo, 0)
        d1 = json.loads((self.tmp / "out" / "doc_1.json").read_text(encoding="utf-8"))
        d2 = json.loads((self.tmp / "out" / "doc_2.json").read_text(encoding="utf-8"))
        self.assertEqual(validar(d1, TEXTO), [])
        self.assertEqual(len(d1["citacoes"]), 5)
        self.assertAlmostEqual(d1["citacoes"][1]["confianca"], 0.9 * 0.8)   # tabela de calibração aplicada
        self.assertEqual(d2["citacoes"], [])
        self.assertTrue((self.tmp / "rastro.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
