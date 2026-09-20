"""Testes de ``resolucao.resolver`` com uma BaseCanonica FALSA em memória.

O índice sintético abaixo preserva o formato de ``dados/indice.json`` mas usa
números, ids e nomes inventados: números próprios únicos, duplicatas idênticas,
pares distinguíveis pela cadeia, colisão STF×STJ de 5 dígitos, registro do
STJ, chave curta (``Nº 42``), OCR reparável, súmulas e dispositivos. Cada
caminho de decisão tem ao menos um teste. Os testes com dados reais
(``skipUnless``) exigem 192/192 no dev e nunca imprimem trechos do gabarito.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))
sys.path.insert(0, str(RAIZ / "scripts" / "analise"))

from conftest_paths import DADOS, DB, INDICE, TEM_DADOS  # noqa: E402

from caca_alucinacao.base_canonica import BaseCanonica  # noqa: E402
from caca_alucinacao.base_canonica.normativos import artigo_canonico, diploma_canonico, sumula_canonica  # noqa: E402
from caca_alucinacao.resolucao import (  # noqa: E402
    campos_da_vaga,
    chaves_alternativas,
    extrair_processo,
    relacao_de_classe,
    resolver,
    sao_duplicatas,
    tribunal_incompativel,
)
from caca_alucinacao.normalizacao import digitos_do_identificador  # noqa: E402
from caca_alucinacao.tipos import Achado, Decisao  # noqa: E402

CATALOGO = DADOS / "catalogo_gabarito.json"
SINTETICOS = DADOS / "sinteticos"
TEM_CATALOGO = CATALOGO.exists() and (INDICE.exists() or DB.exists())


# ---------------------------------------------------------------------------
# Índice sintético (números inventados; layout real)
# ---------------------------------------------------------------------------
def _reg(doc: str, idc: int, tribunal: str | None, ano: int | None, relator: str | None, classe: str | None,
         cabecalho: str, ids: list[tuple[str, str, str | None]], natureza: str = "acordao",
         tipo: str = "jurisprudencia", texto_len: int = 30000) -> dict[str, Any]:
    return {
        "id_canonico": idc, "tribunal": tribunal, "ano": ano, "relator": relator, "natureza": natureza,
        "texto_len": texto_len, "classe_propria": classe, "cabecalho": cabecalho, "tipo": tipo,
        "identificadores": [{"digitos": d, "formato": f, "uf": uf, "bruto": d, "posicao": 0,
                             "classe_propria": classe, "classe_principal": (classe or "").split()[-1] if classe else None}
                            for d, f, uf in ids],
    }


# Chaves canônicas calculadas pela MESMA função do índice/detector (docs/02: implementação única).
CNJ_TST_DUP = digitos_do_identificador("123-45.2015.5.15.0099")       # RR duplicado (2 registros idênticos)
CNJ_TST_AIRR = digitos_do_identificador("987-65.2016.5.02.0123")      # AIRR citado como AgARR
CNJ_TST_OCR = digitos_do_identificador("10173-25.2016.5.03.0028")     # citado com letra isolada no segmento J
CNJ_STM_PAR = digitos_do_identificador("7000123-45.2023.7.00.0000")   # APL: dois registros distintos
REG_STJ = digitos_do_identificador("2019/0123456-7")                  # registro AAAA/NNNNNNN-D do stj_a

REGISTROS: dict[str, dict[str, Any]] = {
    "stj_a": _reg("stj_a", 100, "STJ", 2020, "MINISTRO FULANO DE TAL", "RESP",
                  "RECURSO ESPECIAL Nº 1.234.567 - SP (2019/0123456-7) RELATOR : MINISTRO FULANO DE TAL",
                  [("1234567", "sequencial", "SP"), (REG_STJ, "registro", "SP")]),
    "stj_b": _reg("stj_b", 101, "STJ", 2018, "MINISTRA BELTRANA", "AGINT RESP",
                  "AgInt no RECURSO ESPECIAL Nº 2.345.678 - PR (2018/0000001-1) RELATORA : MINISTRA BELTRANA",
                  [("2345678", "sequencial", "PR")], texto_len=38000),
    "stj_c": _reg("stj_c", 102, "STJ", 2019, "MINISTRA BELTRANA", "AGINT ERESP",
                  "AgInt nos EMBARGOS DE DIVERGÊNCIA EM RESP Nº 2.345.678 - PR (2019/0000002-2) RELATORA : MINISTRA BELTRANA",
                  [("2345678", "sequencial", "PR")], texto_len=16000),
    "stj_d": _reg("stj_d", 103, "STJ", 2021, "MINISTRO SICRANO", "RHC",
                  "RECURSO EM HABEAS CORPUS Nº 12.345 - RJ (2021/0000003-3) RELATOR : MINISTRO SICRANO",
                  [("12345", "sequencial", "RJ")]),
    "stj_e": _reg("stj_e", 104, "STJ", 2017, "MINISTRO SICRANO", "CAUTINOM",
                  "CAUTELAR INOMINADA CRIMINAL Nº 42 - DF (2017/0000004-4) RELATOR : MINISTRO SICRANO",
                  [("42", "sequencial", "DF")]),
    "stf_a": _reg("stf_a", 400, "STF", 2022, "Min. Fulana", "AGR RCL",
                  "01/02/2022 PRIMEIRA TURMA AG.REG. NA RECLAMAÇÃO 12.345 SÃO PAULO RELATOR : MIN. FULANA",
                  [("12345", "sequencial", "SP")]),
    "stf_b": _reg("stf_b", 401, "STF", 2023, "Min. Fulana", "ED RCL",
                  "03/04/2023 SEGUNDA TURMA EMB.DECL. NA RECLAMAÇÃO 54.321 RIO DE JANEIRO RELATOR : MIN. FULANA",
                  [("54321", "sequencial", "RJ")]),
    "stf_c": _reg("stf_c", 402, "STF", 2024, "Min. Fulana", "AGR RCL",
                  "05/06/2024 PRIMEIRA TURMA AG.REG. NA RECLAMAÇÃO 62.471 SÃO PAULO RELATOR : MIN. FULANA",
                  [("62471", "sequencial", "SP")]),
    "tst_a": _reg("tst_a", 200, "TST", 2015, "Ministro Alfa", "RR",
                  "A C Ó R D Ã O (5ª Turma) GMXXX/abc RECURSO DE REVISTA. TEMA. autos de Recurso de Revista nº TST-RR-123-45.2015.5.15.0099",
                  [(CNJ_TST_DUP, "cnj", None)]),
    "tst_b": _reg("tst_b", 201, "TST", 2015, "Ministro Alfa", "RR",
                  "A C Ó R D Ã O (5ª Turma) GMXXX/abc RECURSO DE REVISTA. TEMA. autos de Recurso de Revista nº TST-RR-123-45.2015.5.15.0099",
                  [(CNJ_TST_DUP, "cnj", None)]),
    "tst_c": _reg("tst_c", 202, "TST", 2016, "Ministro Beta", "AIRR",
                  "A C Ó R D Ã O (3ª Turma) AGRAVO DE INSTRUMENTO. autos de Agravo de Instrumento em Recurso de Revista nº TST-AIRR-987-65.2016.5.02.0123",
                  [(CNJ_TST_AIRR, "cnj", None)]),
    "tst_d": _reg("tst_d", 203, "TST", 2016, "Ministro Beta", "RR",
                  "A C Ó R D Ã O (3ª Turma) RECURSO DE REVISTA. autos de Recurso de Revista nº TST-RR-10173-25.2016.5.03.0028",
                  [(CNJ_TST_OCR, "cnj", None)]),
    "stm_a": _reg("stm_a", 300, "STM", 2023, "MINISTRO GAMA", "APL",
                  "Poder Judiciário STM EXTRATO DE ATA APELAÇÃO Nº 7000123-45.2023.7.00.0000/RS RELATOR: MINISTRO GAMA",
                  [(CNJ_STM_PAR, "cnj", "RS")]),
    "stm_b": _reg("stm_b", 301, "STM", 2024, "MINISTRO DELTA", "APL",
                  "Secretaria do Tribunal Pleno APELAÇÃO Nº 7000123-45.2023.7.00.0000 RELATOR: MINISTRO DELTA",
                  [(CNJ_STM_PAR, "cnj", None)]),
    "tse_a": _reg("tse_a", 500, "TSE", 2011, "Ministro Epsilon", "RESPE",
                  "TRIBUNAL SUPERIOR ELEITORAL ACÓRDÃO RECURSO ESPECIAL ELEITORAL Nº 36.123 - CLASSE 32 - CIDADE - BAHIA Relator",
                  [("36123", "sequencial", "BA")]),
    "sum_stj_123": _reg("sum_stj_123", 900, "STJ", None, None, None, "Súmula n. 123 do STJ", [], "sumula"),
    "sum_sv_45": _reg("sum_sv_45", 901, "STF", None, None, None, "Súmula Vinculante n. 45 do STF", [], "sumula"),
    "sum_tst_456": _reg("sum_tst_456", 902, "TST", None, None, None, "Súmula n. 456 do TST", [], "sumula"),
    "disp_cpc_321": _reg("disp_cpc_321", 950, None, None, None, None, "Artigo 321 da Lei nº 13.105, de 16 de março de 2015", [], "dispositivo", "lei"),
    "disp_cf_11": _reg("disp_cf_11", 951, None, None, None, None, "Artigo 11 da Constituição Federal de 1988", [], "dispositivo", "lei"),
    "disp_cpm_240": _reg("disp_cpm_240", 952, None, None, None, None, "Artigo 240 do Decreto-Lei nº 1.001, de 21 de outubro de 1969", [], "dispositivo", "lei"),
}


def _por_digitos() -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    for doc in sorted(REGISTROS):
        for it in REGISTROS[doc]["identificadores"]:
            m.setdefault(it["digitos"], []).append(doc)
    return {k: sorted(v) for k, v in m.items()}


INDICE_FALSO: dict[str, Any] = {
    "versao": 1,
    "registros": REGISTROS,
    "por_digitos": _por_digitos(),
    "sem_identificador": [],
    "normativos": {
        "sumulas": {"STJ|0|123": "sum_stj_123", "STF|1|45": "sum_sv_45", "TST|0|456": "sum_tst_456"},
        "dispositivos": {"CPC|321": "disp_cpc_321", "CF|11": "disp_cf_11", "CPM|240": "disp_cpm_240"},
        "diplomas_na_base": ["CF", "CPC", "CPM"],
        "nao_derivados": [],
    },
}


def achado(trecho: str, familia: str = "processo", tipo: str = "jurisprudencia", forca: float = 1.0,
           dados: dict[str, str] | None = None, origem: str = "regex") -> Achado:
    return Achado(10, 10 + len(trecho), trecho, familia, tipo, dict(dados or {}), origem, forca)


class ArbitroFalso:
    """Árbitro controlável: registra as chamadas e devolve o que for configurado."""

    def __init__(self, normalizacao: dict[str, Any] | None = None, escolha: int | None = None) -> None:
        self.normalizacao = normalizacao
        self.escolha = escolha
        self.chamadas: list[tuple[str, Any]] = []

    def normalizar_citacao(self, trecho: str, contexto: str) -> dict[str, Any] | None:
        self.chamadas.append(("normalizar", trecho))
        return self.normalizacao

    def escolher_candidato(self, trecho: str, contexto: str, candidatos: list[dict[str, Any]]) -> int | None:
        self.chamadas.append(("escolher", [c["id_canonico"] for c in candidatos]))
        return self.escolha

    def classificar_span(self, trecho: str, contexto: str, inicio_rel: int | None = None) -> dict[str, Any] | None:
        return None


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = BaseCanonica(INDICE_FALSO)

    def resolver(self, trecho: str, **kw: Any) -> Decisao:
        arbitro = kw.pop("arbitro", None)
        return resolver(achado(trecho, **kw), self.base, arbitro=arbitro)

    def assertReal(self, d: Decisao, idc: int, caminho: str) -> None:
        self.assertEqual(d.classificacao, "real", d)
        self.assertEqual(d.id_canonico, idc, d)
        self.assertEqual(d.caminho, caminho, d)

    def assertInventada(self, d: Decisao, caminho: str) -> None:
        self.assertEqual(d.classificacao, "inventada", d)
        self.assertIsNone(d.id_canonico)
        self.assertEqual(d.caminho, caminho, d)


# ---------------------------------------------------------------------------
# processo: 0 e 1 candidato
# ---------------------------------------------------------------------------
class TestProcessoUmCandidato(Base):
    def test_cadeia_exata(self) -> None:
        d = self.resolver("REsp 1.234.567/SP")
        self.assertReal(d, 100, "processo:1cand:cadeia_exata")
        self.assertEqual(d.candidatos, (100,))
        self.assertEqual(d.detalhes["tribunal"], "STJ")
        self.assertEqual(d.detalhes["tribunal_fonte"], "classe")

    def test_ruido_n2_nao_muda_a_chave(self) -> None:
        for t in ("RESP\xa012345G7 - SP", "Rec. Esp. n°  1.234.\n567 (SP)", "R.Esp. No 1 234 567/ SP",
                  "Recurso\nEspecial nº 1.234.5G7 – SP", "REsp 1.Z34.567/SP"):
            with self.subTest(t=t):
                self.assertReal(self.resolver(t), 100, "processo:1cand:cadeia_exata")

    def test_ocr_no_primeiro_digito_e_reparado(self) -> None:
        # a normalização recusa a letra inicial (núcleo abre em dígito); o reparo só converte letra
        self.assertReal(self.resolver("RESP\xa0l234567 - SP"), 100, "processo:ocr_reparado:1cand:cadeia_exata")

    def test_classe_principal_prefixo_omitido(self) -> None:
        d = self.resolver("Rcl 54.321/RJ")  # registro é "ED RCL"
        self.assertReal(d, 401, "processo:1cand:classe_principal")

    def test_classe_compativel_familia_tst(self) -> None:
        d = self.resolver("TST-AgARR-987-65.2016.5.02.0123")  # registro é AIRR
        self.assertReal(d, 202, "processo:1cand:classe_compativel")
        self.assertEqual(d.detalhes["tribunal_fonte"], "explicito")

    def test_classe_compativel_entre_eras_resp_respe(self) -> None:
        # "Recurso Especial" → STJ pela classe, mas o número é de um REspe do TSE:
        # RESP≈RESPE, logo o tribunal inferido pela classe não elimina.
        d = self.resolver("Recurso Especial nº 36.123/BA")
        self.assertReal(d, 500, "processo:1cand:classe_compativel")

    def test_classe_divergente_numero_manda(self) -> None:
        d = self.resolver("Ag. Int. nº 62.471/SP")  # registro é AGR RCL; AgInt≈AgR mas RCL ≠ AGINT
        self.assertReal(d, 402, "processo:1cand:classe_divergente")

    def test_sem_classe(self) -> None:
        d = self.resolver("nº 62.471/SP")
        self.assertReal(d, 402, "processo:1cand:sem_classe")

    def test_tribunal_incompativel_pela_classe(self) -> None:
        d = self.resolver("REsp 54.321/RJ")  # 54321 é Rcl do STF; RESP não é compatível com RCL
        self.assertInventada(d, "processo:1cand:tribunal_incompativel")
        self.assertEqual(d.candidatos, (401,))

    def test_tribunal_explicito_incompativel(self) -> None:
        # prefixo TST- é certeza de tribunal; o número é de um REsp do STJ → inventada
        d = self.resolver("TST-RR-1234567")
        self.assertInventada(d, "processo:1cand:tribunal_incompativel")
        self.assertEqual(d.detalhes["tribunal_fonte"], "explicito")

    def test_tribunal_pelo_cnj_incompativel_elimina_todos(self) -> None:
        d = self.resolver("TST-RR-7000123-45.2023.7.00.0000")  # CNJ .7. = STM, TST- diz TST
        self.assertInventada(d, "processo:multi:tribunal_incompativel")
        self.assertEqual(d.candidatos, (300, 301))

    def test_classe_do_cnj_vence_a_classe(self) -> None:
        # "AREsp" diz STJ, mas o CNJ .7. diz STM e o registro é STM: o CNJ manda (classe só rebaixa)
        d = self.resolver("APL 7000123-45.2023.7.00.0000/RS")
        self.assertEqual(d.detalhes["tribunal_fonte"], "cnj")

    def test_uf_incompativel(self) -> None:
        d = self.resolver("REsp 1.234.567/MG")
        self.assertInventada(d, "processo:1cand:uf_incompativel")

    def test_uf_ausente_no_registro_nao_elimina(self) -> None:
        d = self.resolver("AIRR 987-65.2016.5.02.0123/SP")  # TST não tem UF
        self.assertReal(d, 202, "processo:1cand:cadeia_exata")

    def test_registro_stj_resolve_sozinho(self) -> None:
        d = self.resolver("REsp (2019/0123456-7)")
        self.assertReal(d, 100, "processo:1cand:registro")

    def test_numero_e_registro_juntos(self) -> None:
        d = self.resolver("REsp 1.234.567 - SP (2019/0123456-7)")
        self.assertReal(d, 100, "processo:1cand:cadeia_exata")
        self.assertEqual(d.detalhes["registro_secundario"], REG_STJ)

    def test_zero_candidatos(self) -> None:
        d = self.resolver("REsp 7.654.321/SP")
        self.assertInventada(d, "processo:0cand")
        self.assertEqual(d.candidatos, ())

    def test_vizinho_a_um_digito_nao_casa(self) -> None:
        d = self.resolver("REsp 1.234.568/SP")
        self.assertInventada(d, "processo:0cand")

    def test_numero_inventado_com_registro_real(self) -> None:
        d = self.resolver("REsp 9.999.999 - SP (2019/0123456-7)")
        self.assertInventada(d, "processo:0cand:registro_diverge")

    def test_chave_curta_exige_classe_compativel(self) -> None:
        self.assertInventada(self.resolver("Rcl 42/DF"), "processo:1cand:curto_classe_divergente")
        self.assertReal(self.resolver("Cautelar Inominada Criminal nº 42/DF"), 104, "processo:1cand:cadeia_exata")

    def test_dados_do_detector_sao_usados(self) -> None:
        dados = {"digitos": "1234567", "cadeia": "RESP", "uf": "SP", "formato": "curto"}
        d = self.resolver("texto irrelevante", dados=dados)
        self.assertReal(d, 100, "processo:1cand:cadeia_exata")

    def test_dados_invalidos_sao_recalculados(self) -> None:
        d = self.resolver("REsp 1.234.567/SP", dados={"digitos": "abc", "cadeia": ""})
        self.assertReal(d, 100, "processo:1cand:cadeia_exata")


# ---------------------------------------------------------------------------
# processo: ≥ 2 candidatos
# ---------------------------------------------------------------------------
class TestProcessoMultiplos(Base):
    def test_desempate_por_cadeia_exata(self) -> None:
        d = self.resolver("AgInt no REsp 2.345.678/PR")
        self.assertReal(d, 101, "processo:multi:cadeia_exata")
        self.assertEqual(d.candidatos, (101, 102))
        d2 = self.resolver("AgInt nos EREsp 2.345.678/PR")
        self.assertReal(d2, 102, "processo:multi:cadeia_exata")

    def test_desempate_por_classe_principal(self) -> None:
        d = self.resolver("EDcl no AgInt no EREsp 2.345.678/PR")
        self.assertReal(d, 102, "processo:multi:classe_principal")

    def test_colisao_stf_stj_tribunal_pela_classe(self) -> None:
        d = self.resolver("RHC 12.345/RJ")
        self.assertReal(d, 103, "processo:multi:tribunal")
        self.assertEqual(d.candidatos, (400, 103))  # ordem de documento_id (stf_a < stj_d)

    def test_colisao_stf_stj_rcl_ambigua_uf_decide(self) -> None:
        d = self.resolver("Rcl 12.345/SP")  # Rcl não infere tribunal; UF SP → STF
        self.assertReal(d, 400, "processo:multi:uf")

    def test_colisao_uf_elimina_todos(self) -> None:
        d = self.resolver("Rcl 12.345/MG")
        self.assertInventada(d, "processo:multi:uf_incompativel")

    def test_colisao_tribunal_elimina_todos(self) -> None:
        d = self.resolver("APL 12.345/SP")  # APL → STM; nenhum candidato do STM
        self.assertInventada(d, "processo:multi:tribunal_incompativel")

    def test_duplicatas_identicas_menor_documento_id(self) -> None:
        d = self.resolver("RR 123-45.2015.5.15.0099")
        self.assertReal(d, 200, "processo:duplicata")
        self.assertEqual(d.candidatos, (200, 201))
        self.assertEqual(d.detalhes["restantes"], "200,201")

    def test_duplicatas_nunca_chamam_o_arbitro(self) -> None:
        arb = ArbitroFalso(escolha=1)
        d = self.resolver("RR 123-45.2015.5.15.0099", arbitro=arb)
        self.assertReal(d, 200, "processo:duplicata")
        self.assertEqual(arb.chamadas, [])

    def test_cabecalhos_diferentes_sem_arbitro_chute(self) -> None:
        d = self.resolver("APL 7000123-45.2023.7.00.0000")
        self.assertReal(d, 300, "processo:ambiguo_chute")

    def test_cabecalhos_diferentes_uf_confirmada_desempata(self) -> None:
        # stm_a tem UF RS, stm_b não tem UF: a UF citada não elimina stm_b (docs/04 h.2),
        # mas a evidência positiva desempata a favor de stm_a
        d = self.resolver("APL 7000123-45.2023.7.00.0000/RS")
        self.assertReal(d, 300, "processo:multi:uf_confirmada")

    def test_cabecalhos_diferentes_arbitro_escolhe(self) -> None:
        arb = ArbitroFalso(escolha=1)
        d = self.resolver("APL 7000123-45.2023.7.00.0000", arbitro=arb)
        self.assertReal(d, 301, "processo:llm_escolha")
        self.assertEqual(arb.chamadas, [("escolher", [300, 301])])
        self.assertEqual(d.detalhes["llm"], "escolheu")

    def test_arbitro_abstem_chute(self) -> None:
        arb = ArbitroFalso(escolha=None)
        d = self.resolver("APL 7000123-45.2023.7.00.0000", arbitro=arb)
        self.assertReal(d, 300, "processo:ambiguo_chute")
        self.assertEqual(d.detalhes["llm"], "absteve")

    def test_arbitro_indice_invalido_e_ignorado(self) -> None:
        arb = ArbitroFalso(escolha=7)
        d = self.resolver("APL 7000123-45.2023.7.00.0000", arbitro=arb)
        self.assertReal(d, 300, "processo:ambiguo_chute")

    def test_arbitro_que_explode_nao_derruba(self) -> None:
        class Explosivo(ArbitroFalso):
            def escolher_candidato(self, *a: Any, **k: Any) -> int | None:
                raise RuntimeError("boom")

        d = self.resolver("APL 7000123-45.2023.7.00.0000", arbitro=Explosivo())
        self.assertReal(d, 300, "processo:ambiguo_chute")

    def test_sao_duplicatas(self) -> None:
        a, b = self.base.registro("tst_a"), self.base.registro("tst_b")
        c, e = self.base.registro("stm_a"), self.base.registro("stm_b")
        self.assertTrue(sao_duplicatas(self.base, [a, b]))
        self.assertFalse(sao_duplicatas(self.base, [c, e]))


# ---------------------------------------------------------------------------
# processo: OCR — reparo determinístico e árbitro
# ---------------------------------------------------------------------------
class TestProcessoOCR(Base):
    def test_letra_inicial_reparada(self) -> None:
        d = self.resolver("AgRg na Rcl G2.471/SP")
        self.assertReal(d, 402, "processo:ocr_reparado:1cand:cadeia_exata")
        self.assertEqual(d.detalhes["ocr_reparo"], "letra_inicial")

    def test_letra_isolada_no_cnj_reparada(self) -> None:
        d = self.resolver("RR n°\xa010173-25.2016.S.\n03.0028")
        self.assertReal(d, 203, "processo:ocr_reparado:1cand:cadeia_exata")
        self.assertEqual(d.detalhes["ocr_reparo"], "letra_no_meio")

    def test_reparo_nunca_troca_digito_por_digito(self) -> None:
        # 62.417 não existe; nenhuma letra → nada a reparar → inventada
        self.assertInventada(self.resolver("AgRg na Rcl 62.417/SP"), "processo:0cand")

    def test_sigla_colada_nao_e_tratada_como_ocr(self) -> None:
        # "I" de "AI" colado ao número não pode virar 1 (precedido de letra)
        self.assertEqual(chaves_alternativas("AI2416"), [])
        self.assertEqual([r for r, _ in chaves_alternativas("Rcl G2.471")], ["letra_inicial"])

    def test_reparo_sem_dono_vira_inventada_ocr_sem_dono(self) -> None:
        d = self.resolver("Rcl G8.267/SC")
        self.assertInventada(d, "processo:0cand:ocr_sem_dono")
        self.assertEqual(d.detalhes["letras_nao_convertidas"], "1")
        self.assertEqual(d.detalhes["ocr_reparo"], "sem_dono")

    def test_sem_digitos_sem_arbitro(self) -> None:
        d = self.resolver("REsp OOO.OOO/SP")
        self.assertInventada(d, "processo:0cand:ocr_ambiguo")

    def test_sem_digitos_arbitro_normaliza_e_reconsulta(self) -> None:
        arb = ArbitroFalso(normalizacao={"classe_cadeia": ["RESP"], "numero_digitos": "1234567",
                                         "digitos_canonicos": "1234567", "uf": "SP", "tribunal": "STJ",
                                         "eh_citacao": True})
        # a conversão determinística (l→1, Z→2, S→5) daria 1234568, que não tem dono → árbitro
        d = self.resolver("REsp l.Z34.S68/SP", arbitro=arb)
        self.assertReal(d, 100, "processo:llm_normalizou:1cand:cadeia_exata")
        self.assertEqual(d.detalhes["llm"], "normalizou")
        self.assertEqual(arb.chamadas[0][0], "normalizar")

    def test_arbitro_normaliza_para_numero_inexistente(self) -> None:
        arb = ArbitroFalso(normalizacao={"classe_cadeia": ["RESP"], "numero_digitos": "9999999",
                                         "digitos_canonicos": "9999999", "uf": None, "tribunal": None,
                                         "eh_citacao": True})
        d = self.resolver("REsp l.Z34.S68/SP", arbitro=arb)
        self.assertInventada(d, "processo:0cand:ocr_sem_dono")  # chave nova sem dono: vale o núcleo (20/09)
        self.assertEqual(d.detalhes.get("llm"), "normalizou_sem_dono")

    def test_arbitro_diz_que_nao_e_citacao(self) -> None:
        arb = ArbitroFalso(normalizacao={"classe_cadeia": [], "numero_digitos": "", "digitos_canonicos": "",
                                         "uf": None, "tribunal": None, "eh_citacao": False})
        d = self.resolver("REsp OOO.OOO/SP", arbitro=arb)
        self.assertInventada(d, "processo:llm_nao_citacao")

    def test_arbitro_abstem_na_normalizacao(self) -> None:
        arb = ArbitroFalso(normalizacao=None)
        d = self.resolver("REsp OOO.OOO/SP", arbitro=arb)
        self.assertInventada(d, "processo:0cand:ocr_ambiguo")
        self.assertEqual(d.detalhes["llm"], "absteve")

    def test_arbitro_nao_e_chamado_com_numero_limpo(self) -> None:
        arb = ArbitroFalso(normalizacao={"eh_citacao": True, "digitos_canonicos": "1234567", "classe_cadeia": ["RESP"]})
        self.assertInventada(self.resolver("REsp 7.654.321/SP", arbitro=arb), "processo:0cand")
        self.assertEqual(arb.chamadas, [])

    def test_gatilho_duas_letras_convertidas(self) -> None:
        arb = ArbitroFalso(normalizacao=None)
        d = self.resolver("REsp 7.6S4.3Z1/SP", arbitro=arb)  # 2 letras convertidas, 0 candidatos
        self.assertInventada(d, "processo:0cand:ocr_ambiguo")
        self.assertEqual(arb.chamadas[0][0], "normalizar")


# ---------------------------------------------------------------------------
# achados amplos
# ---------------------------------------------------------------------------
class TestAmplo(Base):
    def test_sufixo_amplo_e_descartar(self) -> None:
        d = self.resolver("REsp 7.654.321/SP", forca=0.5)
        self.assertEqual(d.caminho, "processo:0cand:amplo")
        self.assertEqual(d.detalhes["descartar"], "1")

    def test_amplo_confirmado_nao_descarta(self) -> None:
        d = self.resolver("REsp 1.234.567/SP", forca=0.5)
        self.assertReal(d, 100, "processo:1cand:cadeia_exata:amplo")
        self.assertNotIn("descartar", d.detalhes)

    def test_amplo_acima_do_limiar_nao_descarta(self) -> None:
        d = self.resolver("REsp 7.654.321/SP", forca=0.8)
        self.assertEqual(d.caminho, "processo:0cand:amplo")
        self.assertNotIn("descartar", d.detalhes)

    def test_vaga_ampla_sem_correspondencia_descarta(self) -> None:
        d = self.resolver("julgado do STJ proferido em 2020 pela relatoria de Ninguem Conhecido",
                          familia="vaga", forca=0.5)
        self.assertEqual(d.classificacao, "incompleta")
        self.assertEqual(d.caminho, "vaga:incompleta:sem_correspondencia:amplo")
        self.assertEqual(d.detalhes["descartar"], "1")

    def test_estrito_nunca_tem_sufixo(self) -> None:
        self.assertFalse(self.resolver("REsp 7.654.321/SP").caminho.endswith(":amplo"))


# ---------------------------------------------------------------------------
# súmula, dispositivo, tema, vaga
# ---------------------------------------------------------------------------
class TestNormativos(Base):
    def test_sumula_na_tabela(self) -> None:
        self.assertReal(self.resolver("Súmula 123 do STJ", familia="sumula"), 900, "sumula:na_tabela")
        self.assertReal(self.resolver("5umula 123 do STJ", familia="sumula"), 900, "sumula:na_tabela")
        self.assertReal(self.resolver("SÚMULA 456\ndo TST", familia="sumula"), 902, "sumula:na_tabela")

    def test_sumula_vinculante_implica_stf(self) -> None:
        d = self.resolver("Súmula Vinculante 45", familia="sumula")
        self.assertReal(d, 901, "sumula:na_tabela:tribunal_implicito")

    def test_sumula_sem_tribunal_unica(self) -> None:
        self.assertReal(self.resolver("Súm. 123", familia="sumula"), 900, "sumula:na_tabela:sem_tribunal")

    def test_sumula_fora_da_tabela(self) -> None:
        self.assertInventada(self.resolver("Súmula 612 do STF", familia="sumula"), "sumula:fora_da_tabela")
        self.assertInventada(self.resolver("Súmula Vinculante 173", familia="sumula"), "sumula:fora_da_tabela")
        self.assertInventada(self.resolver("Súmula 123 do STF", familia="sumula"), "sumula:fora_da_tabela:tribunal_divergente")
        self.assertInventada(self.resolver("Súmula 612", familia="sumula"), "sumula:fora_da_tabela:sem_tribunal")

    def test_sumula_sem_numero_incompleta(self) -> None:
        d = self.resolver("Súmula do STJ", familia="sumula")
        self.assertEqual((d.classificacao, d.caminho), ("incompleta", "sumula:sem_numero"))

    def test_sumula_dados_do_detector(self) -> None:
        d = self.resolver("x", familia="sumula", dados={"numero_sumula": "45", "vinculante": "1"})
        self.assertReal(d, 901, "sumula:na_tabela:tribunal_implicito")

    def test_dispositivo_na_tabela(self) -> None:
        self.assertReal(self.resolver("art. 321, I, do CPC", familia="dispositivo", tipo="lei"), 950, "dispositivo:na_tabela")
        self.assertReal(self.resolver("art. 321 da Lei nº 13.105/2015", familia="dispositivo", tipo="lei"), 950, "dispositivo:na_tabela")
        self.assertReal(self.resolver("art 11, LV, da Constituição\nFcderal", familia="dispositivo", tipo="lei"), 951, "dispositivo:na_tabela")
        self.assertReal(self.resolver("art.º 240 do Decreto-Lei\nnº 1.001/1969", familia="dispositivo", tipo="lei"), 952, "dispositivo:na_tabela")
        self.assertReal(self.resolver("artigo 11 da Constltuição da República", familia="dispositivo", tipo="lei"), 951, "dispositivo:na_tabela")

    def test_dispositivo_mesmo_artigo_outro_diploma(self) -> None:
        self.assertInventada(self.resolver("art 240 da Constituição Federal", familia="dispositivo", tipo="lei"), "dispositivo:fora_da_tabela")

    def test_dispositivo_fora_da_tabela_e_da_base(self) -> None:
        self.assertInventada(self.resolver("art. 1.144 da Lei 13.105/2015", familia="dispositivo", tipo="lei"), "dispositivo:fora_da_tabela")
        self.assertInventada(self.resolver("art. 175 da Lei nº 9.504/1997", familia="dispositivo", tipo="lei"), "dispositivo:diploma_fora_da_base")
        self.assertInventada(self.resolver("art. 121 do Código Penal", familia="dispositivo", tipo="lei"), "dispositivo:diploma_desconhecido")

    def test_dispositivo_incompleto(self) -> None:
        d = self.resolver("art. 321", familia="dispositivo", tipo="lei")
        self.assertEqual((d.classificacao, d.caminho), ("incompleta", "dispositivo:sem_diploma"))
        d = self.resolver("artigo do CPC", familia="dispositivo", tipo="lei")
        self.assertEqual((d.classificacao, d.caminho), ("incompleta", "dispositivo:sem_artigo"))

    def test_tema(self) -> None:
        d = self.resolver("Tcma 2.680 da repercussão geral", familia="tema")
        self.assertInventada(d, "tema:inventada:repercussao")
        d = self.resolver("Tema Repetitivo 988", familia="tema", dados={"tribunal": "STJ", "numero_tema": "988"})
        self.assertInventada(d, "tema:inventada:repetitivo")
        d = self.resolver("Tema 1234", familia="tema", origem="regex:tema:sem_complemento", forca=0.7)
        self.assertInventada(d, "tema:inventada:solto:amplo")   # forca < 1 ⇒ sufixo :amplo

    def test_vaga(self) -> None:
        d = self.resolver("precedente do STJ, da relatoria de Beltrana", familia="vaga")
        self.assertEqual((d.classificacao, d.caminho), ("incompleta", "vaga:incompleta"))
        self.assertEqual(d.detalhes["multiplicidade"], "2")  # stj_b e stj_c: só diagnóstico
        self.assertEqual(d.candidatos, (101, 102))

    def test_vaga_multiplicidade_unica_tem_caminho_proprio(self) -> None:
        # um único registro casa, mas a família vaga NUNCA vira real (docs/04 f)
        d = self.resolver("julgado do STJ proferido em 2020 pela relatoria de Fulano de Tal", familia="vaga")
        self.assertEqual((d.classificacao, d.caminho), ("incompleta", "vaga:incompleta:unica"))
        self.assertEqual(d.candidatos, (100,))

    def test_vaga_dados_do_detector(self) -> None:
        d = self.resolver("x", familia="vaga", dados={"tribunal": "STJ", "ano": "2020", "relator": "Fulano de Tal"})
        self.assertEqual(d.detalhes["multiplicidade"], "1")

    def test_campos_da_vaga(self) -> None:
        self.assertEqual(campos_da_vaga("Reclamação\ndo STF, de 2023, Rel.  Min. FULANA DE TAL"),
                         ("STF", 2023, "FULANA DE TAL"))
        self.assertEqual(campos_da_vaga("julgado do TSE proferldo em 2019 pela relatoria dc Fulano Beltrano"),
                         ("TSE", 2019, "Fulano Beltrano"))
        self.assertEqual(campos_da_vaga("APL de 2023, Rel. Min. LEONILDO EXEMPLAR"), (None, 2023, "LEONILDO EXEMPLAR"))


# ---------------------------------------------------------------------------
# unidades auxiliares
# ---------------------------------------------------------------------------
class TestAuxiliares(Base):
    def test_extrair_processo(self) -> None:
        c = extrair_processo(achado("processo nº TST-ED-E-ED-RR-1234-56.2011.5.02.\n0251"))
        self.assertEqual(c.digitos, "00012345620115020251")
        self.assertEqual(c.cadeia, ["ED", "E", "ED", "RR"])
        self.assertEqual(c.tribunal_explicito, "TST")
        self.assertEqual(c.tribunal_cnj, "TST")
        self.assertEqual(c.formato, "cnj20")

    def test_ordinal_final_e_removido(self) -> None:
        c = extrair_processo(achado("AgR no ARE 44O.123/SP"))
        self.assertEqual(c.cadeia, ["AGR", "ARE"])

    def test_relacao_de_classe(self) -> None:
        r = self.base.registro("stj_b")  # AGINT RESP
        self.assertEqual(relacao_de_classe(extrair_processo(achado("AgInt no REsp 1/PR")), r), "cadeia_exata")
        self.assertEqual(relacao_de_classe(extrair_processo(achado("REsp 1/PR")), r), "classe_principal")
        self.assertEqual(relacao_de_classe(extrair_processo(achado("REspe 1/PR")), r), "classe_compativel")
        self.assertEqual(relacao_de_classe(extrair_processo(achado("nº 1/PR")), r), "sem_classe")
        self.assertEqual(relacao_de_classe(extrair_processo(achado("Rcl 1/PR")), r), "classe_divergente")

    def test_tribunal_incompativel(self) -> None:
        stf = self.base.registro("stf_a")
        self.assertTrue(tribunal_incompativel(extrair_processo(achado("REsp 12.345/SP")), stf))
        self.assertFalse(tribunal_incompativel(extrair_processo(achado("Rcl 12.345/SP")), stf))
        self.assertFalse(tribunal_incompativel(extrair_processo(achado("HC 12.345/SP")), stf))
        tse = self.base.registro("tse_a")
        self.assertFalse(tribunal_incompativel(extrair_processo(achado("REsp 36.123/BA")), tse))

    def test_familia_invalida(self) -> None:
        with self.assertRaises(ValueError):
            Achado(0, 1, "x", "outra", "lei")

    def test_decisao_coerente(self) -> None:
        with self.assertRaises(ValueError):
            Decisao("real", None, "x")

    def test_determinismo(self) -> None:
        a = achado("APL 7000123-45.2023.7.00.0000")
        r1 = resolver(a, self.base)
        r2 = resolver(a, self.base)
        self.assertEqual((r1.classificacao, r1.id_canonico, r1.caminho, r1.candidatos),
                         (r2.classificacao, r2.id_canonico, r2.caminho, r2.candidatos))


# ---------------------------------------------------------------------------
# normativos: generalizações de parsing que a resolução exige
# ---------------------------------------------------------------------------
class TestParsingNormativos(unittest.TestCase):
    def test_artigo_com_ordinal_apos_ponto(self) -> None:
        self.assertEqual(artigo_canonico("art.º 266 da CF"), "266")
        self.assertEqual(artigo_canonico("art.º\n14, IV, da Lei nº 8.078/1990"), "14")

    def test_enunciado_e_sinonimo_de_sumula(self) -> None:
        self.assertEqual(sumula_canonica("Enunciado nº 456 do TST"), ("TST", False, 456))
        self.assertEqual(sumula_canonica("Enunciado nº Vinculante 45"), ("STF", True, 45))
        self.assertEqual(sumula_canonica("Sumula nº 279\ndo STF"), ("STF", False, 279))

    def test_diploma_com_ocr_nas_palavras(self) -> None:
        self.assertEqual(diploma_canonico("da Constltuição da República"), "CF")
        self.assertEqual(diploma_canonico("da C0nstituição Federal"), "CF")
        self.assertEqual(diploma_canonico("do Deereto-Lei nº 5.452/1943"), "CLT")
        self.assertEqual(diploma_canonico("da Lei Complcmentar nº 64/1990"), "LC64")
        self.assertEqual(diploma_canonico("do Código de Defesa do Consurnidor"), "CDC")
        self.assertIsNone(diploma_canonico("do Código Penal"))


# ---------------------------------------------------------------------------
# dados reais
# ---------------------------------------------------------------------------
@unittest.skipUnless(TEM_CATALOGO, "catálogo do gabarito/índice ausentes")
class TestDadosReais(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import medir_resolucao as mr

        cls.mr = mr
        cls.base = mr.carregar_base()

    def _checar(self, nome: str, casos: list[Any]) -> dict[str, Any]:
        resultados = self.mr.medir(self.base, casos)
        res = self.mr.resumo(resultados)
        self.assertEqual(res["inventada_para_real"], 0, f"{nome}: inventada→real")
        self.assertEqual(res["reais"]["id_correto"], res["reais"]["n"], f"{nome}: id errado em real")
        return res

    def test_dev_192_de_192(self) -> None:
        casos = self.mr.achados_do_catalogo()
        self.assertEqual(len(casos), 192)
        res = self._checar("dev", casos)
        self.assertEqual(res["acertos"], 192, {k: v for k, v in res["por_familia"].items()})
        self.assertLess(res["brier_tabela_inicial"], 0.01)

    def test_dev_sem_dados_do_detector(self) -> None:
        casos = self.mr.achados_do_catalogo(com_dados=False)
        res = self._checar("dev sem dados", casos)
        self.assertEqual(res["acertos"], 192)

    @unittest.skipUnless(TEM_DADOS, "dados reais ausentes")
    def test_sinteticos_se_existirem(self) -> None:
        pastas = sorted(p for p in SINTETICOS.glob("*") if (p / "goldenset_estendido.csv").exists()) if SINTETICOS.exists() else []
        if not pastas:
            self.skipTest("nenhum conjunto sintético gerado")
        for pasta in pastas:
            with self.subTest(pasta=pasta.name):
                res = self._checar(pasta.name, self.mr.achados_dos_sinteticos(pasta))
                self.assertGreaterEqual(res["acuracia"], 0.99, res["matriz"])


if __name__ == "__main__":
    unittest.main()
