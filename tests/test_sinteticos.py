"""Testes do gerador de documentos sintéticos (``caca_alucinacao.sinteticos``).

Sem dados: utilidades puras (quebra de linha, ruído em números, superfícies).
Com dados (``skipUnless``): invariantes do conjunto gerado — offsets, sobreposição,
distância, determinismo, distribuição de classes, coerência com o índice
(``real`` resolve; ``inventada`` nunca é número próprio), fronteiras, cabeçalho
sem citação, CSV no formato oficial e casos do árbitro. Nunca imprime trechos.
"""
from __future__ import annotations

import csv
import json
import random
import sys
import tempfile
import unicodedata
import unittest
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from conftest_paths import INDICE, TEM_DADOS  # noqa: E402

from caca_alucinacao.base_canonica import BaseCanonica, digitos_canonicos, separar_uf  # noqa: E402
from caca_alucinacao.sinteticos import (  # noqa: E402
    COLUNAS_OFICIAIS,
    DISTANCIA_MINIMA,
    TAXAS_N2,
    TAXAS_N3,
    Documento,
    escrever_conjunto,
    estatisticas,
    gerar_casos_llm,
    gerar_conjunto,
    ler_goldenset,
    perfil_para,
)
from caca_alucinacao.sinteticos import gerador as G  # noqa: E402
from caca_alucinacao.sinteticos import ruido as R  # noqa: E402
from caca_alucinacao.tipos import iou  # noqa: E402

TEM_INDICE = TEM_DADOS and INDICE.exists()
_ARTIGOS = {"o", "a", "os", "no", "na", "nos", "do", "da", "dos"}
_RUIDOS_SO_N2 = {"nbsp", "conector_numero_nao_padrao", "separador_uf_nao_padrao", "caixa_alta_na_classe",
                 "ocr_letra_em_digito", "espaco_duplo", "art_sem_ponto", "forma_artigo", "ocr_palavra"}

_CACHE: dict[tuple[int, str], list[Documento]] = {}
_BASE: BaseCanonica | None = None


def _base() -> BaseCanonica:
    global _BASE
    if _BASE is None:
        _BASE = BaseCanonica.de_arquivo(INDICE)
    return _BASE


def _docs(nivel: int, perfil: str = "dev", n: int = 12, seed: int = 11) -> list[Documento]:
    chave = (nivel, perfil)
    if chave not in _CACHE:
        _CACHE[chave] = gerar_conjunto(_base(), n, nivel, seed, perfil)
    return _CACHE[chave]


# ---------------------------------------------------------------------------
# sem dados
# ---------------------------------------------------------------------------
class TestUtilidades(unittest.TestCase):
    def test_quebra_de_linha_preserva_tamanho_e_largura(self) -> None:
        s = " ".join(f"palavra{i}" for i in range(60))
        q = G._quebrar_linhas(s, 40)
        self.assertEqual(len(q), len(s))
        self.assertEqual(q.replace("\n", " "), s)
        self.assertTrue(all(len(ln) <= 40 for ln in q.split("\n")))

    def test_quebra_de_linha_respeita_intervalo_protegido(self) -> None:
        antes = "x " * 30
        span = "REsp nº 1.234.567 (SP)"
        s = antes + span + " fim da frase."
        ini, fim = len(antes), len(antes) + len(span)
        for largura in range(30, 80):
            q = G._quebrar_linhas(s, largura, [(ini, fim)])
            self.assertEqual(len(q), len(s))
            self.assertNotIn("\n", q[ini:fim], f"largura {largura} partiu o span protegido")

    def test_superficies_numericas(self) -> None:
        self.assertEqual(G._com_pontos("1741799"), "1.741.799")
        self.assertEqual(G._com_pontos("49871"), "49.871")
        self.assertEqual(G._com_pontos("42"), "42")
        self.assertEqual(G._superficie_cnj("00003197620166160006", "TSE"), "319-76.2016.6.16.0006")
        self.assertEqual(G._superficie_cnj("70000781320227000000", "STM"), "7000078-13.2022.7.00.0000")
        self.assertEqual(G._superficie_cnj("06001234520216060121", "TSE"), "0600123-45.2021.6.06.0121")
        self.assertEqual(G._superficie_cnj("00034172520115210009", "TST"), "3417-25.2011.5.21.0009")
        self.assertEqual(G._superficie_registro("201901234567"), "2019/0123456-7")
        for d, t in (("00003197620166160006", "TSE"), ("70000781320227000000", "STM"), ("00034172520115210009", "TST")):
            self.assertEqual(digitos_canonicos("X " + G._superficie_cnj(d, t)), d)

    def test_letra_por_digito_nunca_digito_por_digito(self) -> None:
        rng = random.Random(1)
        for _ in range(200):
            n = str(rng.randint(1000, 9999999))
            novo, ok, inicio = R.letra_por_digito(n, rng)
            if not ok:
                continue
            self.assertEqual(len(novo), len(n))
            self.assertFalse(inicio)
            self.assertEqual(sum(1 for a, b in zip(n, novo) if a != b), 1)
            self.assertTrue(novo[0].isdigit())
            self.assertEqual(digitos_canonicos("Rcl " + novo), n.lstrip("0"))

    def test_ocr_fora_do_processo_so_no_perfil_agressivo(self) -> None:   # R4-01 (rodada 2, revisor 1)
        from caca_alucinacao.deteccao.sumula import numero_com_ocr
        from caca_alucinacao.deteccao.vaga import ano_canonico

        rng = random.Random(3)
        self.assertEqual((TAXAS_N2.ocr_digito_normativo, TAXAS_N2.ocr_digito_ano), (0.0, 0.0))
        self.assertGreater(TAXAS_N3.ocr_digito_normativo, 0)
        vistos: Counter[str] = Counter()
        for _ in range(300):
            partes = [["palavra", "Súmula"], ["vinc", ""], ["numero", " 105"], ["tribunal", " do STJ"]]
            r = R.ruido_sumula(partes, TAXAS_N3, rng)
            if "ood:ocr_fora_do_processo" in r:
                vistos["sumula"] += 1
                self.assertIn("ocr_letra_em_digito", r)
                self.assertEqual(numero_com_ocr(partes[2][1].strip()), ("105", 1))
                self.assertTrue(partes[2][1].strip()[0].isdigit())
            partes = [["art", "art."], ["espaco", " "], ["numero", "1.026"], ["complemento", ""], ["prep", " do "],
                      ["diploma", "CPC"]]
            r = R.ruido_dispositivo(partes, TAXAS_N3, rng)
            if "ood:ocr_fora_do_processo" in r:
                vistos["dispositivo"] += 1
                self.assertEqual(numero_com_ocr(partes[2][1]), ("1026", 1))
            partes = [["texto", "julgado do STF proferido em 2019 pela relatoria de "], ["nome", "Fulana Tal"]]
            r = R.ruido_vaga(partes, TAXAS_N3, rng)
            if "ood:ocr_fora_do_processo" in r:
                vistos["vaga"] += 1
                ano = partes[0][1].split(" em ")[1].split(" ")[0]
                self.assertNotEqual(ano, "2019")
                self.assertEqual(ano_canonico(ano), "2019")
            # perfil dev: nunca
            partes = [["palavra", "Súmula"], ["vinc", ""], ["numero", " 123"], ["tribunal", " do STJ"]]
            self.assertNotIn("ood:ocr_fora_do_processo", R.ruido_sumula(partes, TAXAS_N2, rng))
            self.assertEqual(partes[2][1], " 123")
        self.assertEqual(set(vistos), {"sumula", "dispositivo", "vaga"}, vistos)

    def test_ruido_processo_preserva_digitos(self) -> None:
        rng = random.Random(5)
        for taxa in (TAXAS_N2, TAXAS_N3):
            for _ in range(300):
                digitos = str(rng.randint(10000, 9999999))
                partes = [["prefixo", ""], ["tst", ""], ["classe", "AgInt"], ["ligacao", " no "], ["classe", "REsp"],
                          ["conector", " nº"], ["espaco", " "], ["numero", G._com_pontos(digitos)],
                          ["sep", "/"], ["uf", "SP"], ["fecha", ""]]
                info = R.InfoProcesso(formato="sequencial", tribunal="STJ", classe_principal="RESP", estilo="conector", tem_uf=True)
                rotulos = R.ruido_processo(partes, info, taxa, rng)
                trecho = R.montar(partes)
                if "ood:ocr_primeiro_digito" in rotulos:
                    continue
                self.assertEqual(digitos_canonicos(trecho), digitos, (trecho, rotulos))
                self.assertEqual(separar_uf(trecho)[1], "SP", trecho)
                self.assertLessEqual(trecho.count("\n"), 1, trecho)

    def test_perfil(self) -> None:
        self.assertEqual(perfil_para(3, "dev").nome, "agressivo")
        self.assertFalse(perfil_para(2, "dev").ood)
        self.assertTrue(perfil_para(1, "agressivo").ood)
        self.assertEqual(perfil_para(1, "agressivo").taxas.nbsp, 0.0)
        with self.assertRaises(ValueError):
            perfil_para(4, "dev")

    def test_artigos(self) -> None:
        self.assertEqual(G._artigo("f", "n"), "na")
        self.assertEqual(G._artigo("p", "d"), "dos")
        self.assertEqual(G._artigo("m"), "o")


# ---------------------------------------------------------------------------
# com dados
# ---------------------------------------------------------------------------
@unittest.skipUnless(TEM_INDICE, "requer dados/indice.json")
class TestConjunto(unittest.TestCase):
    def test_offsets_validos_e_texto_limpo(self) -> None:
        for nivel, perfil in ((1, "dev"), (2, "dev"), (3, "agressivo")):
            for doc in _docs(nivel, perfil):
                t = doc.texto
                self.assertEqual(unicodedata.normalize("NFC", t), t)
                self.assertNotIn("\r", t)
                self.assertFalse(t.startswith("﻿"))
                self.assertTrue(t.endswith("\n"))
                self.assertGreaterEqual(len(doc.gabarito), 4)
                self.assertLessEqual(len(doc.gabarito), 9)
                for g in doc.gabarito:
                    self.assertEqual(t[g["inicio"]:g["fim"]], g["trecho"])
                    self.assertEqual(set(COLUNAS_OFICIAIS) - set(g), set())

    def test_sem_sobreposicao_e_distancia_minima(self) -> None:
        for nivel, perfil in ((1, "dev"), (2, "dev"), (3, "agressivo")):
            for doc in _docs(nivel, perfil):
                spans = sorted((g["inicio"], g["fim"]) for g in doc.gabarito)
                for i in range(len(spans)):
                    for j in range(i + 1, len(spans)):
                        self.assertLess(iou(*spans[i], *spans[j]), 0.5)
                for (_, fa), (ib, _) in zip(spans, spans[1:]):
                    self.assertGreaterEqual(ib - fa, DISTANCIA_MINIMA)

    def test_determinismo_por_seed(self) -> None:
        a = gerar_conjunto(_base(), 3, 2, 42, "dev")
        b = gerar_conjunto(_base(), 3, 2, 42, "dev")
        self.assertEqual([d.texto for d in a], [d.texto for d in b])
        self.assertEqual([d.gabarito for d in a], [d.gabarito for d in b])
        c = gerar_conjunto(_base(), 3, 2, 43, "dev")
        self.assertNotEqual([d.texto for d in a], [d.texto for d in c])
        self.assertEqual([d.documento_id for d in a], ["sin_n2_dev_001", "sin_n2_dev_002", "sin_n2_dev_003"])

    def test_distribuicao_de_classes_e_familias(self) -> None:
        docs = gerar_conjunto(_base(), 30, 2, 7, "dev")
        est = estatisticas(docs)
        n = est["citacoes"]
        cls = est["classificacao"]
        self.assertTrue(0.40 <= cls["real"] / n <= 0.60, cls)
        self.assertTrue(0.23 <= cls["inventada"] / n <= 0.43, cls)
        self.assertTrue(0.09 <= cls["incompleta"] / n <= 0.26, cls)
        self.assertTrue(0.08 <= est["tipo"]["lei"] / n <= 0.25, est["tipo"])
        for fam in ("processo", "vaga", "dispositivo", "sumula"):
            self.assertIn(fam, est["familia"])
        self.assertEqual(est["familia_x_classe"].get("vaga/incompleta"), est["familia"]["vaga"])
        self.assertNotIn("processo/incompleta", est["familia_x_classe"])
        self.assertNotIn("dispositivo/incompleta", est["familia_x_classe"])
        self.assertEqual(est["por_documento"]["min"], 4)
        self.assertEqual(est["por_documento"]["max"], 9)

    def test_real_resolve_pelo_indice(self) -> None:
        base = _base()
        for nivel, perfil in ((1, "dev"), (2, "dev"), (3, "agressivo")):
            for doc in _docs(nivel, perfil):
                for g in doc.gabarito:
                    if g["classificacao"] != "real":
                        continue
                    self.assertTrue(str(g["id_canonico"]).isdigit())
                    if g["familia"] == "processo":
                        if "ood:ocr_primeiro_digito" in g["ruidos"]:
                            continue
                        dig = digitos_canonicos(g["trecho"])
                        self.assertEqual(dig, g["digitos"], g["ruidos"])
                        ids = {r.id_canonico for r in base.candidatos_por_numero(dig)}
                        self.assertIn(int(g["id_canonico"]), ids)
                        if g["uf"]:
                            self.assertEqual(separar_uf(g["trecho"])[1], g["uf"])
                    elif g["familia"] == "sumula":
                        vinc = "vinculante=1" in g["forma"]
                        reg = base.sumula(g["tribunal"], vinc, int(g["digitos"]))
                        self.assertIsNotNone(reg)
                        self.assertEqual(reg.id_canonico, int(g["id_canonico"]))  # type: ignore[union-attr]
                    elif g["familia"] == "dispositivo":
                        diploma = dict(kv.split("=", 1) for kv in g["forma"].split(";"))["diploma"]
                        reg = base.dispositivo(diploma, g["digitos"])
                        self.assertIsNotNone(reg)
                        self.assertEqual(reg.id_canonico, int(g["id_canonico"]))  # type: ignore[union-attr]

    def test_inventada_nunca_e_numero_proprio(self) -> None:
        base = _base()
        n_proc = 0
        for nivel, perfil in ((1, "dev"), (2, "dev"), (3, "agressivo")):
            for doc in _docs(nivel, perfil):
                for g in doc.gabarito:
                    if g["classificacao"] != "inventada":
                        continue
                    self.assertEqual(g["id_canonico"], "")
                    if g["familia"] == "processo":
                        n_proc += 1
                        self.assertEqual(base.candidatos_por_numero(g["digitos"]), [])
                        if "ood:ocr_primeiro_digito" not in g["ruidos"]:
                            self.assertEqual(base.candidatos_por_numero(digitos_canonicos(g["trecho"])), [])
                    elif g["familia"] == "sumula":
                        vinc = "vinculante=1" in g["forma"]
                        self.assertIsNone(base.sumula(g["tribunal"], vinc, int(g["digitos"])))
                    elif g["familia"] == "dispositivo":
                        diploma = dict(kv.split("=", 1) for kv in g["forma"].split(";"))["diploma"]
                        if diploma != "FORA":
                            self.assertIsNone(base.dispositivo(diploma, g["digitos"]))
                    elif g["familia"] == "tema":
                        self.assertIn("repercussão geral", g["trecho"])
        self.assertGreater(n_proc, 10)

    def test_incompleta_e_vaga_com_multiplicidade(self) -> None:
        base = _base()
        n = 0
        for doc in _docs(2) + _docs(1):
            for g in doc.gabarito:
                if g["classificacao"] == "incompleta":
                    n += 1
                    self.assertEqual(g["familia"], "vaga")
                    forma = dict(kv.split("=", 1) for kv in g["forma"].split(";"))
                    self.assertIn(forma["ano"], g["trecho"])
                    self.assertTrue(2 <= int(forma["relator_palavras"]) <= 4)
                    trib = g["tribunal"] if forma["molde"] != "D" else None
                    self.assertGreaterEqual(len(base.por_relator_ano(trib, int(forma["ano"]), forma["relator"])), 2)
        self.assertGreater(n, 5)

    def test_fronteiras_dos_spans(self) -> None:
        for nivel, perfil in ((1, "dev"), (2, "dev"), (3, "agressivo")):
            for doc in _docs(nivel, perfil):
                t = doc.texto
                for g in doc.gabarito:
                    ini, fim, tr = g["inicio"], g["fim"], g["trecho"]
                    self.assertFalse(tr[0].isspace() or tr[-1].isspace())
                    self.assertNotIn(tr[-1], ",.;:")
                    self.assertIn(t[ini - 1], (" ", "\n"))
                    palavra_anterior = t[:ini].split()[-1]
                    self.assertIn(palavra_anterior, _ARTIGOS, palavra_anterior)
                    self.assertIn(t[fim], (",", ".", " ", "\n"))
                    if t[fim] in (" ", "\n"):
                        self.assertTrue(t[fim + 1].islower())

    def test_cabecalho_sem_citacao_e_distratores_fora_do_gabarito(self) -> None:
        for doc in _docs(2) + _docs(1):
            fim_cab = doc.meta["fim_cabecalho"]
            cnj = doc.meta["cnj_cabecalho"]
            self.assertIn(cnj, doc.texto[:fim_cab])
            for g in doc.gabarito:
                self.assertGreater(g["inicio"], fim_cab)
                self.assertNotIn(cnj, g["trecho"])
                self.assertNotIn("fls.", g["trecho"])
                self.assertNotIn("R$", g["trecho"])
            trechos = [g["trecho"] for g in doc.gabarito]
            for ini, fim, rotulo in doc.armadilhas:
                self.assertNotIn(doc.texto[ini:fim], trechos)
            # citacao_id com lacunas (armadilhas numeradas mas ausentes), como no dev
            ids = [int(g["citacao_id"][1:]) for g in doc.gabarito]
            self.assertEqual(ids, sorted(ids))

    def test_ruido_por_nivel(self) -> None:
        r1 = Counter(r for d in _docs(1) for g in d.gabarito for r in g["ruidos"].split("|") if r)
        r2 = Counter(r for d in _docs(2) for g in d.gabarito for r in g["ruidos"].split("|") if r)
        r3 = Counter(r for d in _docs(3, "agressivo") for g in d.gabarito for r in g["ruidos"].split("|") if r)
        self.assertEqual(set(r1) & _RUIDOS_SO_N2, set())
        self.assertGreaterEqual(len(set(r2) & _RUIDOS_SO_N2), 6)
        self.assertFalse(any(k.startswith("ood:") for k in r1))
        self.assertFalse(any(k.startswith("ood:") for k in r2))
        self.assertTrue(any(k.startswith("ood:") for k in r3))
        self.assertEqual(sum(1 for d in _docs(2) for g in d.gabarito if g["ood"] == "1"), 0)
        self.assertGreater(sum(1 for d in _docs(3, "agressivo") for g in d.gabarito if g["ood"] == "1"), 0)
        # letra por dígito: no máximo uma letra por número e nunca no primeiro caractere (N2)
        for d in _docs(2):
            for g in d.gabarito:
                if "ocr_letra_em_digito" in g["ruidos"]:
                    numero = separar_uf(g["trecho"])[0]
                    letras = sum(1 for c in numero if c in "lOSgGIoZB" and any(ch.isdigit() for ch in numero))
                    self.assertGreaterEqual(letras, 1)
        # um span do N2 nunca tem mais de uma quebra de linha vinda do ruído + uma da diagramação
        for d in _docs(2):
            for g in d.gabarito:
                self.assertLessEqual(g["trecho"].count("\n"), 2, g["ruidos"])

    def test_ocr_fora_do_processo_e_detectado_com_fronteira_exata(self) -> None:   # R4-01 (rodada 2)
        from caca_alucinacao.deteccao import detectar
        from caca_alucinacao.resolucao import resolver

        vistos: Counter[str] = Counter()
        for doc in _docs(3, "agressivo"):
            achados = {(a.inicio, a.fim): a for a in detectar(doc.texto)}
            for g in doc.gabarito:
                if "ood:ocr_fora_do_processo" not in g["ruidos"]:
                    continue
                vistos[g["familia"]] += 1
                a = achados.get((g["inicio"], g["fim"]))
                self.assertIsNotNone(a, (g["familia"], g["ruidos"]))
                d = resolver(a, _base())
                self.assertEqual(d.classificacao, g["classificacao"], (g["familia"], d.caminho))
                if g["classificacao"] == "real":
                    self.assertEqual(str(d.id_canonico), str(g["id_canonico"]))
        self.assertGreaterEqual(sum(vistos.values()), 3, vistos)

    def test_escrita_e_leitura_no_formato_oficial(self) -> None:
        docs = _docs(2)[:4]
        with tempfile.TemporaryDirectory() as tmp:
            est = escrever_conjunto(docs, tmp, _base(), manifesto={"seed": 11})
            raiz = Path(tmp)
            bruto = (raiz / "goldenset.csv").read_bytes()
            self.assertTrue(bruto.startswith(b"\xef\xbb\xbf"))
            with open(raiz / "goldenset.csv", encoding="utf-8-sig", newline="") as f:
                r = csv.DictReader(f)
                self.assertEqual(r.fieldnames, COLUNAS_OFICIAIS)
            linhas = ler_goldenset(raiz / "goldenset.csv")
            self.assertEqual(len(linhas), sum(len(d.gabarito) for d in docs))
            for ln in linhas:
                txt = (raiz / "txt" / f"{ln['documento_id']}.txt").read_bytes()
                self.assertFalse(txt.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r", txt)
                t = txt.decode("utf-8")
                self.assertEqual(t[int(ln["inicio"]):int(ln["fim"])], ln["trecho"])
                if ln["classificacao"] == "real":
                    self.assertTrue(ln["id_canonico"].isdigit())
                else:
                    self.assertEqual(ln["id_canonico"], "")
            ext = ler_goldenset(raiz / "goldenset_estendido.csv")
            self.assertIn("ruidos", ext[0])
            self.assertTrue((raiz / "casos_llm.jsonl").exists())
            self.assertTrue((raiz / "estatisticas.json").exists())
            self.assertEqual(json.loads((raiz / "manifesto.json").read_text(encoding="utf-8"))["seed"], 11)
            self.assertIn("casos_llm", est)
            # o "\n" do trecho é escapado literalmente no CSV, como no goldenset oficial
            com_quebra = [ln for ln in linhas if "\n" in ln["trecho"]]
            if com_quebra:
                self.assertIn(b"\\n", bruto)

    def test_casos_llm(self) -> None:
        docs = _docs(2)[:5]
        casos = gerar_casos_llm(docs, _base())
        ops = Counter(c["operacao"] for c in casos)
        for op in ("normalizar_citacao", "classificar_span", "escolher_candidato"):
            self.assertGreater(ops[op], 0)
        negativos = 0
        for c in casos:
            if c["operacao"] == "normalizar_citacao":
                e = c["esperado"]
                self.assertTrue(e["eh_citacao"])
                self.assertTrue(e["numero_digitos"].isdigit())
                self.assertIsInstance(e["classe_cadeia"], list)
            elif c["operacao"] == "classificar_span":
                e = c["esperado"]
                if e["eh_citacao"]:
                    self.assertIn(e["familia"], ("processo", "sumula", "dispositivo", "tema", "vaga"))
                    self.assertIn(e["tipo"], ("jurisprudencia", "lei"))
                    self.assertTrue(0 <= e["inicio_rel"] < e["fim_rel"] <= len(c["trecho"]))
                    self.assertIn(c["trecho"][e["inicio_rel"]:e["fim_rel"]], c["contexto"])
                else:
                    negativos += 1
                    self.assertIsNone(e["familia"])
            else:
                e = c["esperado"]
                self.assertGreaterEqual(len(c["candidatos"]), 2)
                if e["indice"] is not None:
                    self.assertTrue(0 <= e["indice"] < len(c["candidatos"]))
                    self.assertIn("cabecalho", c["candidatos"][e["indice"]])
        self.assertGreater(negativos, 0)
        self.assertTrue(any(c["operacao"] == "escolher_candidato" and c["esperado"]["indice"] is None for c in casos))


if __name__ == "__main__":
    unittest.main()
