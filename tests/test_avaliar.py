"""Testes de scripts/avaliar.py e scripts/gerar_submissao.py.

Cenários com um gabarito SINTÉTICO (textos e números inventados) e, sob
``skipUnless(TEM_DADOS)``, com o gabarito real — sem imprimir trechos.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "tests"))

from conftest_paths import DADOS, GOLDENSET, TEM_DADOS  # noqa: E402

import avaliar as av  # noqa: E402
import gerar_submissao as gs  # noqa: E402

from caca_alucinacao.contrato import Citacao, SaidaDocumento  # noqa: E402

TEM_FERRAMENTAS = (DADOS / "ferramentas" / "kaggle_metric.py").exists() and \
    (DADOS / "ferramentas" / "json_to_submission.py").exists()
try:
    import numpy  # noqa: F401
    import pandas  # noqa: F401

    TEM_PANDAS = True
except ImportError:  # pragma: no cover
    TEM_PANDAS = False

# ---------------------------------------------------------------------------
# Gabarito sintético
# ---------------------------------------------------------------------------
TEXTOS = {
    "syn_n1_001": ("PARECER\n\nAutos nº 1111111-11.2020.4.05.0001\n\nComo se decidiu no REsp 1.111.222/SP, "
                   "a tese prevalece. Invoca-se o julgado do STF proferido em 2020 pela relatoria de Fulano "
                   "de Tal, e ainda a Rcl 55.555/RJ, que nada acrescenta.\n"),
    "syn_n1_002": ("MEMORIAL\n\nProcesso nº 2222222-22.2021.8.26.0100\n\nAplica-se o art. 11 da Constituição\n"
                   "Federal, bem como a Súmula 999 do STF, ao caso.\n"),
    "syn_n2_001": ("PARECER\n\nAutos nº 3333333-33.2019.5.02.0001\n\nVeja-se o RESP 2222333 - RS, o precedente "
                   "do STJ de 2019, da relatoria de Beltrano Silva, e a Rcl 66.666/PR, que não existe.\n"),
    "syn_n2_002": "ACÓRDÃO\n\nAutos nº 4444444-44.2018.4.01.0001\n\nNada a citar neste documento.\n",
}
# (documento, citacao_id, trecho, tipo, classificacao, id_canonico)
GOLD = [
    ("syn_n1_001", "g1", "REsp 1.111.222/SP", "jurisprudencia", "real", "100"),
    ("syn_n1_001", "g2", "julgado do STF proferido em 2020 pela relatoria de Fulano de Tal", "jurisprudencia",
     "incompleta", ""),
    ("syn_n1_001", "g3", "Rcl 55.555/RJ", "jurisprudencia", "inventada", ""),
    ("syn_n1_002", "g1", "art. 11 da Constituição\nFederal", "lei", "real", "200"),
    ("syn_n1_002", "g2", "Súmula 999 do STF", "jurisprudencia", "inventada", ""),
    ("syn_n2_001", "g1", "RESP 2222333 - RS", "jurisprudencia", "real", "300"),
    ("syn_n2_001", "g2", "precedente do STJ de 2019, da relatoria de Beltrano Silva", "jurisprudencia",
     "incompleta", ""),
    ("syn_n2_001", "g3", "Rcl 66.666/PR", "jurisprudencia", "inventada", ""),
]


def criar_fixture(raiz: Path) -> tuple[Path, Path, Path]:
    """Escreve goldenset.csv (BOM, CRLF, ``\\n`` escapado), sample_submission.csv e txt/."""
    txt = raiz / "txt"
    txt.mkdir(parents=True)
    for doc, texto in TEXTOS.items():
        (txt / f"{doc}.txt").write_bytes(texto.encode("utf-8"))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["nivel", "documento_id", "citacao_id", "inicio", "fim", "trecho", "tipo", "classificacao",
                "id_canonico"])
    for doc, cid, trecho, tipo, classe, idc in GOLD:
        i = TEXTOS[doc].index(trecho)
        w.writerow([av.nivel_do_documento(doc), doc, cid, i, i + len(trecho), trecho.replace("\n", "\\n"),
                    tipo, classe, idc])
    gab = raiz / "goldenset.csv"
    gab.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))
    sample = raiz / "sample_submission.csv"
    sample.write_text("documento_id,citacoes\n" + "".join(f"{d},-\n" for d in sorted(TEXTOS)), encoding="utf-8")
    return gab, sample, txt


def escrever_jsons(pasta: Path, citacoes_por_doc: dict[str, list[Citacao]]) -> None:
    for doc, cits in citacoes_por_doc.items():
        SaidaDocumento.montar(doc, cits).escrever(pasta / f"{doc}.json")


def cit(doc: str, trecho: str, tipo: str, classe: str, idc: str | None, conf: float | None,
        deslocar_fim: int = 0) -> Citacao:
    i = TEXTOS[doc].index(trecho)
    f = i + len(trecho) + deslocar_fim
    return Citacao("c?", i, f, TEXTOS[doc][i:f], tipo, classe, idc, conf)


@unittest.skipUnless(TEM_FERRAMENTAS and TEM_PANDAS, "scripts oficiais e pandas necessários")
class TestCenariosSinteticos(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.gab, cls.sample, cls.txt = criar_fixture(cls.tmp)
        cls.linhas = av.ler_goldenset(cls.gab)
        cls.docs = list(av.documentos_do_gabarito(cls.linhas, av.ler_sample(cls.sample)))

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def pasta(self, nome: str) -> Path:
        p = self.tmp / nome
        if p.exists():
            shutil.rmtree(p)
        p.mkdir()
        return p

    def test_leitura_do_gabarito(self) -> None:
        self.assertEqual(len(self.linhas), 8)
        self.assertEqual(self.linhas[0]["documento_id"], "syn_n1_001")   # BOM removido
        lei = next(r for r in self.linhas if r["tipo"] == "lei")
        self.assertIn("\n", lei["trecho"])                                # "\n" desescapado
        self.assertEqual(TEXTOS["syn_n1_002"][lei["inicio"]:lei["fim"]], lei["trecho"])
        self.assertEqual(self.docs, ["syn_n1_001", "syn_n1_002", "syn_n2_001", "syn_n2_002"])
        self.assertEqual(av.nivel_do_documento("syn_n2_002"), 2)
        self.assertEqual(av.nivel_do_documento("gen_n1_013"), 1)

    def test_formato_da_solution(self) -> None:
        sol = av.montar_solution(self.linhas, av.ler_sample(self.sample))
        self.assertEqual(list(sol.columns), ["documento_id", "nivel", "citacoes"])
        por_doc = dict(zip(sol["documento_id"], sol["citacoes"]))
        niveis = dict(zip(sol["documento_id"], sol["nivel"]))
        self.assertEqual(por_doc["syn_n2_002"], "-")
        self.assertEqual(niveis["syn_n2_002"], 2)
        blocos = por_doc["syn_n1_001"].split("|")
        self.assertEqual(len(blocos), 3)
        campos = blocos[0].split(",")
        self.assertEqual(len(campos), 4)
        self.assertEqual(campos[2:], ["real", "100"])
        self.assertEqual(blocos[1].split(",")[3], "-")
        # a célula passa no parser do oficial
        metrica = av.importar_oficial("kaggle_metric")
        golds = metrica._parse_solution_cell(por_doc["syn_n1_001"], "syn_n1_001")
        self.assertEqual(golds[0]["doc_ids"], frozenset({"100"}))

    def test_perfeita_com_confianca_1_da_1_1(self) -> None:
        pasta = self.pasta("perfeita")
        av.gabarito_para_jsons(self.linhas, pasta, self.docs, confianca=1.0)
        self.assertEqual(len(list(pasta.glob("*.json"))), 4)
        r = av.avaliar_pasta(pasta, self.gab, self.sample, txt=self.txt)
        self.assertAlmostEqual(r["score_final"], 1.1, places=9)
        self.assertEqual(r["ausentes"], [])
        self.assertEqual(r["erros"], [])
        self.assertEqual(r["erros_contrato"], {})
        for n in (1, 2):
            self.assertAlmostEqual(r["niveis"][n]["macro_f1"], 1.0)
            self.assertAlmostEqual(r["niveis"][n]["b"], 0.1)
            self.assertAlmostEqual(r["niveis"][n]["brier"], 0.0)
        texto = av.formatar_relatorio(r)
        self.assertIn("score_final = 1.10000", texto)
        for _, _, trecho, *_ in GOLD:
            self.assertNotIn(trecho, texto)      # nunca imprime trechos

    def test_perfeita_sem_confianca_da_1_0(self) -> None:
        pasta = self.pasta("sem_conf")
        av.gabarito_para_jsons(self.linhas, pasta, self.docs, confianca=None)
        r = av.avaliar_pasta(pasta, self.gab, self.sample)
        self.assertAlmostEqual(r["score_final"], 1.0, places=9)
        self.assertEqual(r["niveis"][1]["n_com_confianca"], 0)

    def test_vazia_da_0(self) -> None:
        pasta = self.pasta("vazia")
        av.gabarito_para_jsons([], pasta, self.docs)
        r = av.avaliar_pasta(pasta, self.gab, self.sample)
        self.assertEqual(r["score_final"], 0.0)
        self.assertEqual(len(r["erros"]), 8)
        self.assertTrue(all(e["tipo"] == "span_nao_detectado" for e in r["erros"]))
        self.assertEqual(r["niveis"][1]["matriz"]["real"][av.SEM_PAR], 2)

    def test_inventada_para_real_conta_em_tau(self) -> None:
        pasta = self.pasta("trocada")
        av.gabarito_para_jsons(self.linhas, pasta, self.docs, confianca=1.0, trocar={"syn_n1_001:g3": "real"})
        r = av.avaliar_pasta(pasta, self.gab, self.sample)
        n1 = r["niveis"][1]
        self.assertAlmostEqual(n1["tau"], 0.5)                 # 1 de 2 inventadas do N1
        self.assertAlmostEqual(n1["tau_diagnostico"], 0.5)
        self.assertEqual(n1["tau_num"], 1)
        f1_real, f1_inv, f1_inc = 4 / 5, 2 / 3, 1.0             # real: tp2 fp1; inventada: tp1 fn1
        macro = (f1_real + f1_inv + f1_inc) / 3
        self.assertAlmostEqual(n1["macro_f1"], macro)
        self.assertAlmostEqual(n1["macro_f1_diagnostico"], macro)
        s = macro * (1 - 0.5 * 0.5)
        brier = 1 / 5                                           # 5 pares com confiança 1,0; 1 errado
        score_n1 = s * (1 + 0.1 * (1 - brier))
        self.assertAlmostEqual(n1["score"], score_n1)
        self.assertAlmostEqual(r["score_final"], (score_n1 + 2 * 1.1) / 3)
        self.assertEqual(len(r["graves"]), 1)
        self.assertEqual(r["graves"][0]["gold_id"], "g3")
        self.assertEqual(r["graves"][0]["tipo"], "classe_errada")
        self.assertIn("inventada→real (erro grave, τ): 1", av.formatar_relatorio(r))

    def test_tipos_de_erro_e_regra_extra(self) -> None:
        pasta = self.pasta("erros")
        escrever_jsons(pasta, {
            "syn_n1_001": [
                cit("syn_n1_001", "REsp 1.111.222/SP", "jurisprudencia", "real", "999", 0.9),      # id errado
                cit("syn_n1_001", "Rcl 55.555/RJ", "jurisprudencia", "inventada", None, 0.9),      # ok
                cit("syn_n1_001", "que nada acrescenta", "jurisprudencia", "inventada", None, 0.7),  # espúrio
                # g2 (vaga) não detectada
            ],
            "syn_n1_002": [
                cit("syn_n1_002", "art. 11 da Constituição\nFederal", "lei", "real", "200", 0.9),
                cit("syn_n1_002", "Federal", "lei", "real", "200", 0.6),   # EXTRA: contida na casada, IoU < 0,5
                cit("syn_n1_002", "Súmula 999 do STF", "jurisprudencia", "incompleta", None, 0.8),  # classe errada
            ],
            "syn_n2_001": [
                cit("syn_n2_001", "RESP 2222333 - RS", "jurisprudencia", "real", "300", 0.95),
                cit("syn_n2_001", "precedente do STJ de 2019, da relatoria de Beltrano Silva", "jurisprudencia",
                    "incompleta", None, 0.95),
                cit("syn_n2_001", "Rcl 66.666/PR", "jurisprudencia", "inventada", None, 0.95),
            ],
            "syn_n2_002": [],
        })
        r = av.avaliar_pasta(pasta, self.gab, self.sample, txt=self.txt)
        tipos = sorted((e["documento_id"], e["tipo"]) for e in r["erros"])
        self.assertEqual(tipos, [
            ("syn_n1_001", "id_errado"), ("syn_n1_001", "span_espurio"), ("syn_n1_001", "span_nao_detectado"),
            ("syn_n1_002", "classe_errada"), ("syn_n1_002", "extra_ignorado"),
        ])
        n1 = r["niveis"][1]
        self.assertEqual(n1["id_errado"], 1)
        self.assertEqual(n1["extra_ignorado"], 1)
        # contagens: real tp1 fp1 (id errado); inventada tp1 fn1 fp1 (espúria); incompleta fn1 (vaga) fn1...
        self.assertEqual(n1["tp"], {"real": 1, "inventada": 1, "incompleta": 0})
        self.assertEqual(n1["fp"], {"real": 1, "inventada": 1, "incompleta": 1})
        self.assertEqual(n1["fn"], {"real": 0, "inventada": 1, "incompleta": 1})
        self.assertAlmostEqual(n1["macro_f1"], n1["macro_f1_diagnostico"])
        self.assertAlmostEqual(r["niveis"][2]["macro_f1"], 1.0)
        self.assertEqual(r["graves"], [])
        id_errado = next(e for e in r["erros"] if e["tipo"] == "id_errado")
        self.assertEqual(id_errado["id_esperado"], ["100"])
        self.assertEqual(id_errado["id_obtido"], "999")
        self.assertEqual(r["niveis"][1]["matriz"]["inventada"]["incompleta"], 1)
        self.assertEqual(r["niveis"][1]["matriz"][av.SEM_PAR]["inventada"], 1)
        self.assertEqual(r["niveis"][1]["matriz"]["incompleta"][av.SEM_PAR], 1)

    def test_por_caminho_com_rastro(self) -> None:
        pasta = self.pasta("rastro")
        av.gabarito_para_jsons(self.linhas, pasta, self.docs, confianca=0.9, trocar={"syn_n1_001:g3": "real"})
        rastro = pasta / "rastro.jsonl"
        with rastro.open("w", encoding="utf-8") as f:
            for r in self.linhas:
                cam = f"{r['tipo']}:{r['classificacao']}"
                f.write(json.dumps({"documento_id": r["documento_id"], "inicio": r["inicio"], "fim": r["fim"],
                                    "caminho": cam, "status": "emitida"}) + "\n")
        r = av.avaliar_pasta(pasta, self.gab, self.sample, rastro=rastro)
        pc = r["por_caminho"]
        self.assertEqual(pc["jurisprudencia:inventada"]["n"], 3)
        self.assertEqual(pc["jurisprudencia:inventada"]["acertos"], 2)
        self.assertAlmostEqual(pc["jurisprudencia:real"]["acuracia"], 1.0)
        self.assertAlmostEqual(pc["jurisprudencia:inventada"]["brier"], (0.01 + 0.01 + 0.81) / 3)

    def test_documento_ausente_e_modo_estrito(self) -> None:
        pasta = self.pasta("ausente")
        av.gabarito_para_jsons(self.linhas, pasta, [], confianca=1.0)
        (pasta / "syn_n1_002.json").unlink()
        r = av.avaliar_pasta(pasta, self.gab, self.sample)
        self.assertEqual(r["ausentes"], ["syn_n1_002", "syn_n2_002"])
        self.assertIn("REJEITARIA", av.formatar_relatorio(r))
        metrica = av.importar_oficial("kaggle_metric")
        with self.assertRaises(metrica.ParticipantVisibleError):
            av.avaliar_pasta(pasta, self.gab, self.sample, preencher_ausentes=False)

    def test_submissao_invalida_levanta_erro_do_oficial(self) -> None:
        pasta = self.pasta("invalida")
        escrever_jsons(pasta, {
            "syn_n1_001": [cit("syn_n1_001", "REsp 1.111.222/SP", "jurisprudencia", "real", "100", 0.9),
                           cit("syn_n1_001", "REsp 1.111.222/SP", "jurisprudencia", "real", "100", 0.9, -1)],
        })
        metrica = av.importar_oficial("kaggle_metric")
        with self.assertRaises(metrica.ParticipantVisibleError):
            av.avaliar_pasta(pasta, self.gab, self.sample)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(av.main(["--saida", str(pasta), "--gabarito", str(self.gab),
                                      "--sample", str(self.sample), "--txt", str(self.txt)]), 1)

    def test_main_imprime_e_grava_json(self) -> None:
        pasta = self.pasta("main")
        av.gabarito_para_jsons(self.linhas, pasta, self.docs, confianca=1.0)
        relatorio = self.tmp / "rel" / "relatorio.json"
        out = io.StringIO()
        with redirect_stdout(out):
            codigo = av.main(["--saida", str(pasta), "--gabarito", str(self.gab), "--sample", str(self.sample),
                              "--txt", str(self.txt), "--json", str(relatorio), "--quieto"])
        self.assertEqual(codigo, 0)
        self.assertIn("score_final = 1.10000", out.getvalue())
        self.assertAlmostEqual(json.loads(relatorio.read_text(encoding="utf-8"))["score_final"], 1.1)

    def test_gerar_submissao(self) -> None:
        pasta = self.pasta("submissao")
        av.gabarito_para_jsons(self.linhas, pasta, self.docs, confianca=0.87)
        destino = self.tmp / "sub" / "submission.csv"
        gs.converter(pasta, destino)
        erros, classes, n = gs.validar_csv(destino, av.ler_sample(self.sample))
        self.assertEqual(erros, [])
        self.assertEqual(n, 4)
        self.assertEqual(dict(classes), {"real": 3, "inventada": 3, "incompleta": 2})
        with destino.open(encoding="utf-8", newline="") as f:
            linhas = list(csv.DictReader(f))
        self.assertEqual(linhas[3]["citacoes"], "-")
        self.assertIn(",real,100,0.8700", linhas[0]["citacoes"])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            codigo = gs.main(["--saida", str(pasta), "--destino", str(destino), "--sample", str(self.sample),
                              "--txt", str(self.txt)])
        self.assertEqual(codigo, 0, err.getvalue())
        self.assertTrue((self.tmp / "sub" / "submission_jsons.zip").exists())
        self.assertIn("submissão válida", out.getvalue())
        # documento faltando → rejeitada
        (pasta / "syn_n2_002.json").unlink()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            codigo = gs.main(["--saida", str(pasta), "--destino", str(destino), "--sample", str(self.sample),
                              "--txt", str(self.txt), "--sem-zip"])
        self.assertEqual(codigo, 1)
        self.assertIn("sem linha", err.getvalue())


@unittest.skipUnless(TEM_DADOS and TEM_FERRAMENTAS and TEM_PANDAS, "dados do desafio ausentes")
class TestGabaritoReal(unittest.TestCase):
    """Usa o gabarito real só para números agregados; nunca imprime trechos."""

    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)
        cls.tmp = Path(tempfile.mkdtemp())
        cls.linhas = av.ler_goldenset(GOLDENSET)
        cls.sample = DADOS / "sample_submission.csv"
        cls.docs = list(av.documentos_do_gabarito(cls.linhas, av.ler_sample(cls.sample)))

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_sanidade_reproduz_o_oficial(self) -> None:
        r = av.sanidade(GOLDENSET, self.sample)
        self.assertAlmostEqual(r["perfeita_conf_1.0"], 1.1, places=9)
        self.assertAlmostEqual(r["perfeita_sem_conf"], 1.0, places=9)
        self.assertEqual(r["vazia"], 0.0)

    def test_offsets_e_diagnostico_batem_com_oficial(self) -> None:
        self.assertEqual(len(self.linhas), 192)
        self.assertEqual(len(self.docs), 26)
        for r in self.linhas:
            texto = (DADOS / "txt" / f"{r['documento_id']}.txt").read_bytes().decode("utf-8")
            self.assertEqual(texto[r["inicio"]:r["fim"]], r["trecho"], f"{r['documento_id']} {r['citacao_id']}")
        inv = next(r for r in self.linhas if r["nivel"] == 1 and r["classificacao"] == "inventada")
        pasta = self.tmp / "trocada"
        av.gabarito_para_jsons(self.linhas, pasta, self.docs, confianca=0.9,
                               trocar={f"{inv['documento_id']}:{inv['citacao_id']}": "real"})
        r = av.avaliar_pasta(pasta, GOLDENSET, self.sample, txt=DADOS / "txt")
        self.assertEqual(r["erros_contrato"], {})
        self.assertAlmostEqual(r["niveis"][1]["tau"], 1 / 32)
        self.assertAlmostEqual(r["niveis"][2]["tau"], 0.0)
        for n in (1, 2):
            self.assertAlmostEqual(r["niveis"][n]["macro_f1"], r["niveis"][n]["macro_f1_diagnostico"])
            self.assertAlmostEqual(r["niveis"][n]["tau"], r["niveis"][n]["tau_diagnostico"])
        self.assertEqual(len(r["graves"]), 1)
        self.assertLess(r["score_final"], 1.1)


if __name__ == "__main__":
    unittest.main()
