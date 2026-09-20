"""Nenhum dado do desafio nos arquivos versionados (regra do projeto).

Executa ``scripts/analise/verificar_vazamento.py`` contra o catálogo local
(``dados/catalogo_gabarito.json``, ignorado pelo git) e o índice. Sem o
catálogo (clone sem ``dados/``) o teste é pulado; as funções de derivação são
testadas à parte com um catálogo sintético mínimo.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts" / "analise"))
sys.path.insert(0, str(RAIZ / "tests"))

from conftest_paths import DADOS, INDICE  # noqa: E402

import verificar_vazamento as V  # noqa: E402

CATALOGO = DADOS / "catalogo_gabarito.json"

# Catálogo sintético: números, nomes e formas que NÃO existem no gabarito real.
_CATALOGO_FALSO = [
    {"documento_id": "x", "familia": "processo", "trecho": "REsp 9.876.543/SP", "digitos": "9876543",
     "numero_superficie": "9.876.543", "ruidos": []},
    {"documento_id": "x", "familia": "processo", "trecho": "REspe 4321-09.2019.6.26.0001",
     "digitos": "00043210920196260001", "numero_superficie": "4321-09.2019.6.26.0001", "ruidos": []},
    {"documento_id": "x", "familia": "sumula", "trecho": "Súmula 4.321 do STJ", "numero_sumula": 4321, "ruidos": []},
    {"documento_id": "x", "familia": "dispositivo", "trecho": "art. 9.999 do CPC", "artigo": "9999", "diploma": "CPC",
     "ruidos": []},
    {"documento_id": "x", "familia": "dispositivo", "trecho": "art. 4 da CLT", "artigo": "4", "diploma": "CLT",
     "ruidos": []},
    {"documento_id": "x", "familia": "vaga", "trecho": "julgado do STF proferido em 2020 pela relatoria de Zenóbia Quaresma",
     "relator": "Zenóbia Quaresma", "ruidos": []},
    {"documento_id": "x", "familia": "vaga", "trecho": "julgado do STF proferldo em 2021 pela relatoria de Zenóbia Quãresma",
     "relator": "Zenóbia Quãresma", "ruidos": ["ocr_palavra", "ocr_no_nome_do_relator"]},
]
_INDICE_FALSO = {"registros": {"r1": {"relator": "MINISTRA ZENÓBIA QUARESMA"},
                               "r2": {"relator": "MINISTRO ABDENAGO VILARINHO DE QUEVEDO"}},
                 "por_digitos": {"7654321": ["r1"], "00012345620195020030": ["r1"]}}


class TestDerivacao(unittest.TestCase):
    def setUp(self) -> None:
        self.p = V.Proibidos(_CATALOGO_FALSO, _INDICE_FALSO)

    def _verificar(self, conteudo: str) -> set[str]:
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "a.py"
            arq.write_text(conteudo, encoding="utf-8")
            return {motivo for _, motivo, _ in V.verificar_arquivo(arq, self.p)}

    def test_trecho_literal_e_com_escape(self) -> None:
        self.assertIn("trecho", self._verificar('x = "REsp 9.876.543/SP"'))
        self.assertIn("trecho", self._verificar('x = "REspe 4321-09.2019.6.26.0001"'))
        self.assertIn("trecho", self._verificar('x = "julgado do STF proferido em 2020 pela\\nrelatoria de Zenóbia Quaresma"'))

    def test_numero_com_pontuacao_ocr_e_parcial(self) -> None:
        self.assertIn("numero", self._verificar("n = '9876543'"))
        self.assertIn("numero", self._verificar("n = 'Rec 9.876.543 - RJ'"))
        self.assertIn("numero", self._verificar("n = 'REsp 9.87G.543'"))
        self.assertIn("numero", self._verificar("n = '4321-09.2019.6.26.0001'"))
        self.assertIn("numero", self._verificar("n = '43210920196260001'"))
        self.assertIn("numero_base", self._verificar("n = '7.654.321'"))
        self.assertIn("numero_base", self._verificar("n = '0001234-56.2019.5.02.0030'"))
        self.assertEqual(self._verificar("n = '1234567'"), set())
        self.assertEqual(self._verificar("ano = 2019; art = 9999"), set())

    def test_numero_seguido_de_palavra_com_letras_confundiveis(self) -> None:
        # R4-02 (rodada 2): "9876543 no STJ" era lido como "987654305" e escapava
        self.assertIn("numero", self._verificar('t = "o exemplo 9876543 no STJ e no TSE"'))
        self.assertIn("numero", self._verificar('t = "9.876.543 ou outro"'))
        self.assertIn("numero_base", self._verificar('t = "7.654.321/SP"'))
        self.assertIn("numero", self._verificar('t = "9876543-SP"'))
        self.assertEqual([m.group(0) for m in V._RE_TOKEN_NUM.finditer("9876543 no STJ")], ["9876543"])

    def test_catalogo_ausente_com_goldenset_falha(self) -> None:
        # R3b-04: num clone com dados/goldenset.csv mas sem catálogo, o lint não pode passar em silêncio
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "dados").mkdir()
            (Path(d) / "dados" / "goldenset.csv").write_text("documento_id\n", encoding="utf-8")
            saida = io.StringIO()
            with redirect_stderr(saida), redirect_stdout(io.StringIO()):
                rc = V.main(["--raiz", d])
            self.assertEqual(rc, 1)
            self.assertIn("catalogar_gabarito", saida.getvalue())

    def test_sumula_artigo_relator_ocr(self) -> None:
        self.assertIn("sumula", self._verificar("s = 'Súmula nº 4321'"))
        self.assertIn("sumula", self._verificar("s = 'SÚMULA 4.321'"))
        self.assertIn("artigo", self._verificar("s = 'art. 9.999'"))
        self.assertIn("artigo", self._verificar("s = 'art. 4º, I, da Consolidação das Leis do Trabalho'"))
        self.assertEqual(self._verificar("s = 'art. 4º da CF'"), set())
        self.assertIn("relator", self._verificar("s = 'ZENOBIA QUARESMA'"))
        self.assertIn("ocr", self._verificar("s = 'Quãresma'"))
        self.assertIn("ocr", self._verificar("s = 'proferldo'"))
        self.assertEqual(self._verificar("s = 'proferido Quaresma'"), set())

    def test_par_de_sobrenomes_do_mesmo_relator(self) -> None:   # R4-06 (rodada 2)
        # nome "disfarçado" que preserva dois sobrenomes consecutivos do relator da base
        self.assertIn("relator_parcial", self._verificar("n = 'Fulano Vilarinho Quevedo'"))
        self.assertIn("relator_parcial", self._verificar("n = 'ABDENAGO VILARINHO'"))
        self.assertIn("relator_parcial", self._verificar("n = 'Zenobia Quaresma Neta'"))
        # um sobrenome sozinho, ou dois de relatores diferentes, não acusam
        self.assertEqual(self._verificar("n = 'Fulano Quevedo'"), set())
        self.assertEqual(self._verificar("n = 'Quaresma Vilarinho'"), set())
        self.assertEqual(self._verificar("n = 'Ministro Vilarinho de Tal'"), set())

    def test_sem_catalogo_sai_limpo(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            saida = io.StringIO()
            with redirect_stderr(saida), redirect_stdout(io.StringIO()):
                rc = V.main(["--raiz", d, "--catalogo", str(Path(d) / "nao_existe.json")])
            self.assertEqual(rc, 0)
            self.assertIn("catálogo ausente", saida.getvalue())


@unittest.skipUnless(CATALOGO.exists(), "dados/catalogo_gabarito.json ausente")
class TestRepositorioLimpo(unittest.TestCase):
    def test_nenhum_dado_do_desafio_versionado(self) -> None:
        proibidos = V.Proibidos(json.loads(CATALOGO.read_text(encoding="utf-8")),
                                json.loads(INDICE.read_text(encoding="utf-8")) if INDICE.exists() else None)
        ocorrencias: list[str] = []
        for arq in V.arquivos_versionados(RAIZ):
            for linha, motivo, _casou in V.verificar_arquivo(arq, proibidos):
                # nunca imprime o que casou: só arquivo, linha e motivo
                ocorrencias.append(f"{arq.relative_to(RAIZ)}:{linha}: {motivo}")
        self.assertEqual(ocorrencias, [], "dados do desafio em arquivos versionados:\n" + "\n".join(ocorrencias))


if __name__ == "__main__":
    unittest.main()
