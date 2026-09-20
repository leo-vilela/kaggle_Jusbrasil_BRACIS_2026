"""Testes de ``calibracao``: fallback hierárquico, teto/piso, força, Laplace, prior, Brier, persistência."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao import calibracao as cal  # noqa: E402
from caca_alucinacao.config import (  # noqa: E402
    CONFIANCA_PADRAO, CONFIANCA_TETO, CONFIANCA_TETO_CONSOLIDADO, N_MINIMO_CONSOLIDADO,
)
from caca_alucinacao.tipos import Achado, Decisao  # noqa: E402


def dec(caminho: str, classificacao: str = "inventada", idc: int | None = None) -> Decisao:
    return Decisao(classificacao, idc, caminho)


def ach(forca: float = 1.0) -> Achado:
    return Achado(0, 5, "x y z", "processo", "jurisprudencia", {}, "regex", forca)


class TestConsulta(unittest.TestCase):
    def test_prefixos(self) -> None:
        self.assertEqual(cal.prefixos("a:b:c"), ["a:b:c", "a:b", "a"])
        self.assertEqual(cal.prefixos("a"), ["a"])
        self.assertEqual(cal.prefixos(""), [])

    def test_fallback_hierarquico(self) -> None:
        tabela = {"processo": 0.8, "processo:1cand": 0.9, "processo:1cand:cadeia_exata": 0.98}
        self.assertEqual(cal.valor_do_caminho("processo:1cand:cadeia_exata", tabela), (0.98, "processo:1cand:cadeia_exata"))
        self.assertEqual(cal.valor_do_caminho("processo:1cand:classe_divergente", tabela), (0.9, "processo:1cand"))
        self.assertEqual(cal.valor_do_caminho("processo:duplicata", tabela), (0.8, "processo"))
        self.assertEqual(cal.valor_do_caminho("sumula:na_tabela", tabela), (CONFIANCA_PADRAO, None))
        self.assertEqual(cal.valor_do_caminho("x", None), (CONFIANCA_PADRAO, None))

    def test_valores_invalidos_na_tabela_sao_ignorados(self) -> None:
        tabela = {"processo:1cand": "alto", "processo": 0.7}
        self.assertEqual(cal.valor_do_caminho("processo:1cand", tabela), (0.7, "processo"))

    def test_confianca_usa_tabela_inicial_sem_tabela(self) -> None:
        c = cal.confianca(dec("processo:1cand:cadeia_exata", "real", 1), ach(), None)
        self.assertEqual(c, cal.TABELA_INICIAL["processo:1cand:cadeia_exata"])
        self.assertEqual(cal.confianca(dec("processo:1cand:cadeia_exata", "real", 1), ach(), {}), c)

    def test_teto_e_piso(self) -> None:
        # a tabela treinada pode carregar até o teto consolidado (0,995); nunca 1,0
        self.assertEqual(cal.confianca(dec("a"), ach(), {"a": 1.0}), CONFIANCA_TETO_CONSOLIDADO)
        self.assertEqual(cal.confianca(dec("a"), ach(), {"a": 5.0}), CONFIANCA_TETO_CONSOLIDADO)
        self.assertEqual(cal.confianca(dec("a"), ach(), {"a": 0.98}), CONFIANCA_TETO)
        self.assertLess(CONFIANCA_TETO_CONSOLIDADO, 1.0)
        self.assertEqual(cal.confianca(dec("a"), ach(), {"a": 0.0}), cal.CONFIANCA_PISO)
        self.assertEqual(cal.confianca(dec("a"), ach(), {"a": -1.0}), cal.CONFIANCA_PISO)
        self.assertEqual(cal.limitar(float("nan")), CONFIANCA_PADRAO)
        self.assertLess(CONFIANCA_TETO, 1.0)

    def test_forca_multiplica_quando_nao_ha_valor_amplo(self) -> None:
        tabela = {"processo:0cand": 0.9}
        self.assertAlmostEqual(cal.confianca(dec("processo:0cand:amplo"), ach(0.5), tabela), 0.45)
        self.assertAlmostEqual(cal.confianca(dec("processo:0cand"), ach(1.0), tabela), 0.9)

    def test_valor_amplo_especifico_nao_multiplica(self) -> None:
        tabela = {"processo:0cand": 0.9, "processo:0cand:amplo": 0.6}
        self.assertAlmostEqual(cal.confianca(dec("processo:0cand:amplo"), ach(0.5), tabela), 0.6)

    def test_tabela_parcial_cai_na_inicial_para_caminhos_ausentes(self) -> None:
        tabela = {"sumula:na_tabela": 0.9}
        c = cal.confianca(dec("processo:duplicata", "real", 1), ach(), tabela)
        self.assertEqual(c, cal.TABELA_INICIAL["processo:duplicata"])

    def test_tabela_inicial_dentro_dos_limites(self) -> None:
        for k, v in cal.TABELA_INICIAL.items():
            self.assertTrue(cal.CONFIANCA_PISO <= v <= CONFIANCA_TETO_CONSOLIDADO, k)
        # 0,5 + 0,5·q com q ≈ 0,6 (gabarito com conjunto de ids aceitos; ADR 0007, rodada 2 R4-14)
        self.assertAlmostEqual(cal.TABELA_INICIAL["processo:duplicata"], 0.8)


class TestAjuste(unittest.TestCase):
    def test_normalizar_avaliacoes(self) -> None:
        avs = cal.normalizar_avaliacoes([("a", 1), ("a", 0, 0.5), {"caminho": "b", "acerto": True},
                                         {"caminho": "b", "y": 0}, cal.Avaliacao("c", 1), ("sem_acerto",), None, {"x": 1}])
        self.assertEqual([(a.caminho, a.acerto, a.forca) for a in avs],
                         [("a", 1, 1.0), ("a", 0, 0.5), ("b", 1, 1.0), ("b", 0, 1.0), ("c", 1, 1.0)])

    def test_contagens_agregam_prefixos(self) -> None:
        c = cal.contagens([("p:a:x", 1), ("p:a:x", 0), ("p:b", 1)])
        self.assertEqual(c["p:a:x"], (2.0, 1.0))
        self.assertEqual(c["p:a"], (2.0, 1.0))
        self.assertEqual(c["p"], (3.0, 2.0))
        self.assertEqual(cal.contagens([("p:a", 1)], com_prefixos=False), {"p:a": (1.0, 1.0)})

    def test_laplace(self) -> None:
        self.assertAlmostEqual(cal.laplace(0, 0), 0.5)
        self.assertAlmostEqual(cal.laplace(10, 10), 11 / 12)
        self.assertAlmostEqual(cal.laplace(98, 98), 0.99)
        self.assertLess(cal.laplace(1000, 1000), 1.0)
        self.assertGreater(cal.laplace(1000, 0), 0.0)
        # generalizado: prior p0 com peso k
        self.assertAlmostEqual(cal.laplace(0, 0, 0.9, 4), 0.9)
        self.assertAlmostEqual(cal.laplace(6, 6, 0.9, 4), (6 + 3.6) / 10)

    def test_ajustar_com_n_grande_converge_para_a_empirica(self) -> None:
        avs = [("p:x", 1)] * 180 + [("p:x", 0)] * 20
        t = cal.ajustar({"p:x": 0.5}, avs, peso_prior=2.0)
        self.assertAlmostEqual(t["p:x"], 181 / 202)  # Laplace puro com p0 = 0,5 e k = 2
        self.assertAlmostEqual(t["p"], 181 / 202)    # prefixo agregado (prior padrão 0,5)

    def test_ajustar_com_n_pequeno_fica_perto_do_prior(self) -> None:
        t = cal.ajustar({"p:x": 0.9}, [("p:x", 1)] * 5)
        self.assertAlmostEqual(t["p:x"], (5 + cal.PESO_PRIOR * 0.9) / (5 + cal.PESO_PRIOR))
        self.assertGreaterEqual(t["p:x"], 0.9)       # acertos nunca puxam abaixo do prior
        t0 = cal.ajustar({"p:x": 0.9}, [])
        self.assertAlmostEqual(t0["p:x"], 0.9)       # sem observação: fica o prior
        t1 = cal.ajustar({"p:x": 0.9}, [("p:x", 0)])
        self.assertLess(t1["p:x"], 0.9)              # um erro puxa para baixo

    def test_prior_por_familia_quando_caminho_novo(self) -> None:
        t = cal.ajustar({"p": 0.8}, [("p:novo", 1)] * 2)
        self.assertAlmostEqual(t["p:novo"], (2 + cal.PESO_PRIOR * 0.8) / (2 + cal.PESO_PRIOR))
        t2 = cal.ajustar({}, [("q:novo", 1)] * 2)   # sem prior algum: Laplace com 0,5
        self.assertAlmostEqual(t2["q:novo"], (2 + cal.PESO_PRIOR * 0.5) / (2 + cal.PESO_PRIOR))

    def test_teto_nunca_ultrapassado(self) -> None:
        # evidência massiva sem erro → teto consolidado (0,995), nunca 1,0
        t = cal.ajustar({}, [("p:x", 1)] * 10000)
        self.assertEqual(t["p:x"], CONFIANCA_TETO_CONSOLIDADO)
        self.assertEqual(t["p"], CONFIANCA_TETO_CONSOLIDADO)
        self.assertLess(t["p:x"], 1.0)

    def test_teto_consolidado_exige_volume_e_zero_erros(self) -> None:
        n = N_MINIMO_CONSOLIDADO
        prior = {"p": 0.98, "p:x": 0.98, "p:a": 0.98, "p:b": 0.98}
        # abaixo do mínimo: teto comum (o teto é um limite, não um piso)
        self.assertEqual(cal.ajustar(prior, [("p:x", 1)] * (n - 1))["p:x"], CONFIANCA_TETO)
        # no mínimo, sem erro e com prior alto: consolidado
        self.assertEqual(cal.ajustar(prior, [("p:x", 1)] * n)["p:x"], CONFIANCA_TETO_CONSOLIDADO)
        # sem prior (Laplace com 0,5) a acurácia a posteriori ainda fica abaixo do teto consolidado
        self.assertLess(cal.ajustar({}, [("p:x", 1)] * n)["p:x"], CONFIANCA_TETO_CONSOLIDADO)
        # um único erro em muitos: nunca consolida
        t = cal.ajustar(prior, [("p:x", 1)] * 5000 + [("p:x", 0)])
        self.assertEqual(t["p:x"], CONFIANCA_TETO)
        # o prefixo só consolida se TODOS os filhos acertaram
        t = cal.ajustar(prior, [("p:a", 1)] * n + [("p:b", 1)] * 50 + [("p:b", 0)])
        self.assertEqual(t["p:a"], CONFIANCA_TETO_CONSOLIDADO)
        self.assertEqual(t["p"], CONFIANCA_TETO)
        # caminhos sem treino nunca consolidam (ficam no prior)
        t = cal.ajustar({}, [("processo:duplicata", 1)] * 1000)
        self.assertEqual(t["processo:duplicata"], cal.TABELA_INICIAL["processo:duplicata"])

    def test_piso(self) -> None:
        t = cal.ajustar({}, [("p:x", 0)] * 10000)
        self.assertEqual(t["p:x"], cal.CONFIANCA_PISO)

    def test_caminhos_nao_observados_permanecem(self) -> None:
        t = cal.ajustar({"a:b": 0.7, "c": 0.6}, [("a:b", 1)] * 20)
        self.assertEqual(t["c"], 0.6)
        self.assertIn("a", t)

    def test_amplo_e_calibrado_como_caminho_proprio(self) -> None:
        avs = [("p:x:amplo", 0, 0.5)] * 10 + [("p:x", 1)] * 10
        t = cal.ajustar({}, avs)
        self.assertLess(t["p:x:amplo"], t["p:x"])
        self.assertAlmostEqual(t["p:x:amplo"], cal.laplace(10, 0, 0.5, cal.PESO_PRIOR))

    def test_determinismo_e_ordenacao(self) -> None:
        avs = [("b", 1), ("a:x", 0), ("a:y", 1)]
        t1, t2 = cal.ajustar({}, avs), cal.ajustar({}, list(reversed(avs)))
        self.assertEqual(t1, t2)
        self.assertEqual(list(t1), sorted(t1))


class TestBrier(unittest.TestCase):
    def test_brier_basico(self) -> None:
        avs = [("a", 1), ("a", 0)]
        self.assertAlmostEqual(cal.brier(avs, {"a": 0.5}), 0.25)
        self.assertAlmostEqual(cal.brier([("a", 1)] * 4, {"a": 0.9}), 0.01)
        self.assertIsNone(cal.brier([], {"a": 0.9}))

    def test_brier_respeita_limites_e_forca(self) -> None:
        # 1,0 na tabela vira 0,995 (teto consolidado): um acerto custa (0,005)²
        self.assertAlmostEqual(cal.brier([("a", 1)], {"a": 1.0}), (1 - CONFIANCA_TETO_CONSOLIDADO) ** 2)
        # força multiplica quando não há valor amplo específico
        self.assertAlmostEqual(cal.brier([("a:amplo", 1, 0.5)], {"a": 0.8}), (1 - 0.4) ** 2)

    def test_calibrar_reduz_o_brier(self) -> None:
        avs = [("p:x", 1)] * 70 + [("p:x", 0)] * 30
        antes = cal.brier(avs, {"p:x": 0.98})
        depois = cal.brier(avs, cal.ajustar({"p:x": 0.98}, avs))
        self.assertLess(depois, antes)
        # ótimo teórico em c = p: p(1-p) = 0,21; a estimativa suavizada fica perto
        self.assertAlmostEqual(depois, 0.21, delta=0.005)

    def test_um_ponto_zero_e_pior_que_o_teto_com_um_erro(self) -> None:
        avs = [("p", 1)] * 99 + [("p", 0)]
        com_teto = cal.brier(avs, {"p": 0.98})
        # sem teto seria (0)*99 + 1 = 0,01 de Brier; com o teto: 99·0,0004 + 0,9604 → 0,0100
        self.assertLess(com_teto, 0.0101)
        self.assertGreater(cal.brier([("p", 1)] * 99, {"p": 0.98}), 0.0)


class TestPersistencia(unittest.TestCase):
    def test_salvar_e_carregar(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "calibracao.json"
            cal.salvar({"b": 0.5, "a": 0.98765}, p, meta={"fontes": ["x"]})
            dados = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(list(dados["tabela"]), ["a", "b"])
            self.assertEqual(dados["tabela"]["a"], 0.9877)
            self.assertEqual(dados["meta"]["fontes"], ["x"])
            self.assertEqual(cal.carregar(p), {"a": 0.9877, "b": 0.5})

    def test_carregar_formato_plano_e_ausente(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"a": 0.5, "b": "x", "c": True}), encoding="utf-8")
            self.assertEqual(cal.carregar(p), {"a": 0.5})
            self.assertEqual(cal.carregar(Path(d) / "nada.json"), {})

    def test_calibracao_json_do_repositorio_e_valida(self) -> None:
        p = RAIZ / "dados" / "calibracao.json"
        if not p.exists():
            self.skipTest("dados/calibracao.json ausente")
        tabela = cal.carregar(p)
        if not tabela:
            self.skipTest("tabela vazia")
        for k, v in tabela.items():
            self.assertTrue(cal.CONFIANCA_PISO <= v <= CONFIANCA_TETO_CONSOLIDADO, k)
        self.assertIn("processo", tabela)
        # nunca 0,98: a política do gabarito para duplicatas é incerta (ADR 0007)
        self.assertLessEqual(tabela.get("processo:duplicata", 0.5), 0.85)
        self.assertGreaterEqual(tabela.get("processo:duplicata", 0.5), 0.5)

    def test_calibracao_json_do_repositorio_tem_validacao_fora_da_amostra(self) -> None:
        """ADR 0007 §6: a tabela entregue foi treinada com um conjunto MANTIDO FORA do ajuste
        (``scripts/calibrar_completo.py``: ``n3_ood``), e o meta prova isso: validação não vazia,
        nenhum conjunto de validação entre as fontes de treino, Brier de validação não pior
        após o ajuste, e um caminho só consolida (> 0,98) com ≥ N_MINIMO decisões sem erro."""
        p = RAIZ / "dados" / "calibracao.json"
        if not p.exists():
            self.skipTest("dados/calibracao.json ausente")
        meta = json.loads(p.read_text(encoding="utf-8")).get("meta") or {}
        validacao = meta.get("validacao") or []
        self.assertTrue(validacao, "meta.validacao vazio: tabela treinada sem conjunto fora da amostra")
        fontes = {f["nome"].split(":", 1)[-1] for f in meta.get("fontes", [])}
        for v in validacao:
            self.assertGreater(v["n"], 0, v["nome"])
            self.assertNotIn(v["nome"].split(":", 1)[-1], fontes, "conjunto de validação também está no treino")
            self.assertLessEqual(v["brier_depois"], v["brier_antes"] + 1e-9, v["nome"])
        contagens = meta.get("contagens") or {}
        tabela = cal.carregar(p)
        for cam in meta.get("caminhos_consolidados", []):
            c = contagens.get(cam) or {}
            self.assertGreaterEqual(c.get("n", 0), cal.N_MINIMO_CONSOLIDADO, cam)
            self.assertEqual(c.get("acertos"), c.get("n"), cam)
            self.assertGreater(tabela[cam], CONFIANCA_TETO, cam)
        for cam, v in tabela.items():
            if v > CONFIANCA_TETO:
                self.assertIn(cam, meta.get("caminhos_consolidados", []), cam)

    def test_caminhos_llm_so_saem_do_prior_com_evidencia_do_modelo_real(self) -> None:
        """ADR 0003/0007: um caminho ``llm:*`` só se afasta do prior da TABELA_INICIAL com decisões do
        modelo REAL (``calibrar_completo.py --cache-llm``: ``meta.cache_llm`` com o SHA-256 do JSONL, o
        modelo e a revisão; ``meta.holdout_llm`` com o Brier fora da amostra, não pior após o ajuste);
        nunca recebe o teto consolidado."""
        p = RAIZ / "dados" / "calibracao.json"
        if not p.exists():
            self.skipTest("dados/calibracao.json ausente")
        conteudo = json.loads(p.read_text(encoding="utf-8"))
        tabela, meta = cal.carregar(p), conteudo.get("meta") or {}
        movidos = [cam for cam, v in tabela.items() if cal.sem_consolidacao(cam)
                   and abs(v - cal.valor_do_caminho(cam, cal.TABELA_INICIAL)[0]) > 1e-9]
        for cam in movidos:
            self.assertLessEqual(tabela[cam], CONFIANCA_TETO, cam)
            self.assertNotIn(cam, meta.get("caminhos_consolidados", []), cam)
        if not movidos:
            return
        cache = meta.get("cache_llm") or {}
        self.assertTrue(cache.get("sha256") and cache.get("modelo") and cache.get("revisao"),
                        "caminhos llm:* treinados sem meta.cache_llm (evidência do modelo real)")
        self.assertNotIn("mock", str(cache.get("modelo")))
        hold = meta.get("holdout_llm") or {}
        val = hold.get("validacao") or {}
        self.assertGreater(val.get("n", 0), 0, "holdout dos caminhos llm:* ausente")
        self.assertLessEqual(val["brier_depois"], val["brier_antes"] + 1e-9)
        self.assertGreater(hold.get("documentos_validacao", 0), 0)


if __name__ == "__main__":
    unittest.main()
