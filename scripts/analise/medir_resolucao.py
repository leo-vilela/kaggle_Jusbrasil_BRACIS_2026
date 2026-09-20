#!/usr/bin/env python3
"""Mede a resolução (``resolucao.resolver``) isoladamente, com spans do gabarito.

Constrói um ``Achado`` por citação do gabarito — fronteiras, família e tipo do
gabarito; ``dados`` derivados do trecho com ``normalizacao`` (dígitos, cadeia,
UF, formato), como o detector fará — resolve contra a base e compara classe e
``id_canonico`` com o esperado. Isola a resolução da detecção: aqui a meta é
**192/192** no dev sem árbitro (docs/03 §9.3, docs/04 h) e a análise dos erros
nos sintéticos (docs/05).

Uso:
    PYTHONPATH=src python scripts/analise/medir_resolucao.py                       # dev (catálogo)
    PYTHONPATH=src python scripts/analise/medir_resolucao.py --sinteticos dados/sinteticos/n2_dev dados/sinteticos/n3_ood
    PYTHONPATH=src python scripts/analise/medir_resolucao.py --arbitro mock --erros 50 --json medicao.json

Nunca imprime trechos do gabarito (só ids, caminhos, rótulos e contagens).
Somente biblioteca padrão. O módulo também é importado por
``scripts/treinar_calibracao.py`` (``achados_do_catalogo``, ``achados_dos_sinteticos``, ``medir``).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from caca_alucinacao import calibracao  # noqa: E402
from caca_alucinacao.base_canonica import BaseCanonica  # noqa: E402
from caca_alucinacao.base_canonica.normativos import artigo_canonico, diploma_canonico, sumula_canonica  # noqa: E402
from caca_alucinacao.config import DADOS, caminho_db, caminho_indice  # noqa: E402
from caca_alucinacao.normalizacao import (  # noqa: E402
    cadeia_da_citacao,
    digitos_do_identificador,
    formato_de,
    separar_uf,
)
from caca_alucinacao.resolucao import campos_da_vaga, resolver  # noqa: E402
from caca_alucinacao.tipos import Achado, Decisao  # noqa: E402

log = logging.getLogger("medir_resolucao")


# ---------------------------------------------------------------------------
# Achados a partir do gabarito
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Caso:
    """Uma citação do gabarito pronta para resolver, com a resposta esperada."""

    achado: Achado
    documento_id: str
    citacao_id: str
    esperado: str                     # classificação
    id_esperado: int | None
    nivel: int
    rotulos: tuple[str, ...] = ()     # ruídos/ood/forma (diagnóstico)
    digitos_gabarito: str = ""        # chave do gabarito (sintéticos), p/ conferir a normalização
    extra: dict[str, Any] = field(default_factory=dict, compare=False)


def dados_derivados(familia: str, trecho: str) -> dict[str, str]:
    """``Achado.dados`` como o detector os preencheria, usando só ``normalizacao``."""
    d: dict[str, str] = {}
    if familia == "processo":
        _, uf = separar_uf(trecho)
        digitos = digitos_do_identificador(trecho)
        cadeia = cadeia_da_citacao(trecho)
        d["digitos"] = digitos
        d["formato"] = formato_de(digitos) if digitos else "outro"
        d["cadeia"] = " ".join(cadeia)
        if uf:
            d["uf"] = uf
    elif familia == "sumula":
        trib, vinc, num = sumula_canonica(trecho)
        d["vinculante"] = "1" if vinc else "0"
        if num is not None:
            d["numero_sumula"] = str(num)
        if trib and not vinc:
            d["tribunal"] = trib
    elif familia == "dispositivo":
        dip = diploma_canonico(trecho)
        art = artigo_canonico(trecho)
        if dip:
            d["diploma"] = dip
        if art:
            d["artigo"] = art
    elif familia == "vaga":
        trib, ano, rel = campos_da_vaga(trecho)
        if trib:
            d["tribunal"] = trib
        if ano is not None:
            d["ano"] = str(ano)
        if rel:
            d["relator"] = rel
    return d


def _achado(familia: str, tipo: str, inicio: int, fim: int, trecho: str, com_dados: bool,
            forca: float = 1.0) -> Achado:
    dados = dados_derivados(familia, trecho) if com_dados else {}
    return Achado(inicio=inicio, fim=fim, trecho=trecho, familia=familia, tipo=tipo, dados=dados,
                  origem="gabarito", forca=forca)


def achados_do_catalogo(caminho: Path | str = DADOS / "catalogo_gabarito.json", com_dados: bool = True) -> list[Caso]:
    """Casos do dev a partir de ``dados/catalogo_gabarito.json`` (campos ``familia``/``tipo`` inferidos lá)."""
    entradas = json.loads(Path(caminho).read_text(encoding="utf-8"))
    casos: list[Caso] = []
    for e in entradas:
        familia = e["familia"]
        tipo = e["tipo"]
        idc = e.get("id_canonico")
        rotulos = tuple(sorted(e.get("ruidos") or []))
        casos.append(Caso(
            achado=_achado(familia, tipo, int(e["inicio"]), int(e["fim"]), e["trecho"], com_dados),
            documento_id=e["documento_id"], citacao_id=e["citacao_id"], esperado=e["classificacao"],
            id_esperado=int(idc) if idc not in (None, "", "-") else None, nivel=int(e.get("nivel") or 1),
            rotulos=rotulos, digitos_gabarito=str(e.get("digitos") or ""),
            extra={"formato_numero": e.get("formato_numero"), "classe_vaga": e.get("classe_vaga")},
        ))
    return casos


def achados_dos_sinteticos(pasta: Path | str, com_dados: bool = True) -> list[Caso]:
    """Casos de um conjunto sintético (``goldenset_estendido.csv`` de ``gerar_sinteticos.py``)."""
    from caca_alucinacao.sinteticos import ler_goldenset

    linhas = ler_goldenset(Path(pasta) / "goldenset_estendido.csv")
    casos: list[Caso] = []
    for r in linhas:
        familia = r["familia"]
        tipo = r["tipo"]
        idc = (r.get("id_canonico") or "").strip()
        rotulos = tuple(sorted(x for x in (r.get("ruidos") or "").split("|") if x))
        forma = tuple(f"forma:{x}" for x in (r.get("forma") or "").split(";") if x)
        casos.append(Caso(
            achado=_achado(familia, tipo, int(r["inicio"]), int(r["fim"]), r["trecho"], com_dados),
            documento_id=r["documento_id"], citacao_id=r["citacao_id"], esperado=r["classificacao"],
            id_esperado=int(idc) if idc.isdigit() else None, nivel=int(r.get("nivel") or 1),
            rotulos=rotulos + forma, digitos_gabarito=r.get("digitos") or "",
            extra={"tribunal": r.get("tribunal"), "classe_cadeia": r.get("classe_cadeia"), "uf": r.get("uf"),
                   "ood": r.get("ood")},
        ))
    return casos


# ---------------------------------------------------------------------------
# Medição
# ---------------------------------------------------------------------------
@dataclass
class Resultado:
    caso: Caso
    decisao: Decisao
    confianca: float

    @property
    def classe_ok(self) -> bool:
        return self.decisao.classificacao == self.caso.esperado

    @property
    def acerto(self) -> bool:
        if not self.classe_ok:
            return False
        if self.caso.esperado == "real":
            return self.decisao.id_canonico == self.caso.id_esperado
        return True


def medir(base: BaseCanonica, casos: list[Caso], arbitro: Any = None,
          tabela: dict[str, float] | None = None) -> list[Resultado]:
    """Resolve cada caso e devolve os resultados (ordem dos casos)."""
    saida: list[Resultado] = []
    for c in casos:
        d = resolver(c.achado, base, arbitro=arbitro)
        conf = calibracao.confianca(d, c.achado, tabela)
        saida.append(Resultado(c, d, conf))
    return saida


def avaliacoes_de(resultados: list[Resultado]) -> list[calibracao.Avaliacao]:
    """``(caminho, acerto, forca)`` por resultado — entrada de ``calibracao.ajustar``."""
    return [calibracao.Avaliacao(r.decisao.caminho, 1 if r.acerto else 0, r.caso.achado.forca) for r in resultados]


def resumo(resultados: list[Resultado], tabela: dict[str, float] | None = None) -> dict[str, Any]:
    """Acurácia por classe/família/nível, inventada→real, ids certos, caminhos, Brier."""
    por_classe: dict[str, Counter] = defaultdict(Counter)
    por_familia: dict[str, Counter] = defaultdict(Counter)
    por_nivel: dict[int, Counter] = defaultdict(Counter)
    matriz: Counter = Counter()
    caminhos: dict[str, Counter] = defaultdict(Counter)
    inv_real = 0
    reais_total = reais_id_ok = 0
    digitos_diferentes = 0
    for r in resultados:
        c, d = r.caso, r.decisao
        ok = r.acerto
        por_classe[c.esperado]["n"] += 1
        por_classe[c.esperado]["ok"] += ok
        por_familia[c.achado.familia]["n"] += 1
        por_familia[c.achado.familia]["ok"] += ok
        por_nivel[c.nivel]["n"] += 1
        por_nivel[c.nivel]["ok"] += ok
        matriz[(c.esperado, d.classificacao)] += 1
        caminhos[d.caminho]["n"] += 1
        caminhos[d.caminho]["ok"] += ok
        if c.esperado == "inventada" and d.classificacao == "real":
            inv_real += 1
        if c.esperado == "real":
            reais_total += 1
            reais_id_ok += (d.classificacao == "real" and d.id_canonico == c.id_esperado)
        if c.achado.familia == "processo" and c.digitos_gabarito and d.detalhes.get("digitos") != c.digitos_gabarito:
            digitos_diferentes += 1
    avals = avaliacoes_de(resultados)
    n = len(resultados)
    acertos = sum(1 for r in resultados if r.acerto)
    return {
        "n": n, "acertos": acertos, "acuracia": (acertos / n) if n else None,
        "por_classe": {k: {"n": v["n"], "ok": v["ok"], "acuracia": v["ok"] / v["n"]} for k, v in sorted(por_classe.items())},
        "por_familia": {k: {"n": v["n"], "ok": v["ok"], "acuracia": v["ok"] / v["n"]} for k, v in sorted(por_familia.items())},
        "por_nivel": {k: {"n": v["n"], "ok": v["ok"], "acuracia": v["ok"] / v["n"]} for k, v in sorted(por_nivel.items())},
        "matriz": {f"{e}->{o}": v for (e, o), v in sorted(matriz.items())},
        "inventada_para_real": inv_real,
        "reais": {"n": reais_total, "id_correto": reais_id_ok},
        "digitos_diferentes_do_gabarito": digitos_diferentes,
        "caminhos": {k: {"n": v["n"], "ok": v["ok"], "acuracia": v["ok"] / v["n"],
                         "confianca": calibracao.limitar(calibracao.valor_do_caminho(k, tabela or calibracao.TABELA_INICIAL)[0])}
                     for k, v in sorted(caminhos.items())},
        "brier_tabela_inicial": calibracao.brier(avals, None),
        "brier_tabela": calibracao.brier(avals, tabela) if tabela else None,
    }


def erros(resultados: list[Resultado]) -> list[dict[str, Any]]:
    """Lista de erros (sem trechos): ids, esperado × obtido, caminho, rótulos e detalhes."""
    saida = []
    for r in resultados:
        if r.acerto:
            continue
        c, d = r.caso, r.decisao
        saida.append({
            "documento_id": c.documento_id, "citacao_id": c.citacao_id, "familia": c.achado.familia,
            "esperado": c.esperado, "id_esperado": c.id_esperado, "obtido": d.classificacao,
            "id_obtido": d.id_canonico, "caminho": d.caminho, "confianca": round(r.confianca, 3),
            "rotulos": list(c.rotulos), "grave": c.esperado == "inventada" and d.classificacao == "real",
            "detalhes": {k: v for k, v in d.detalhes.items() if k in (
                "digitos", "formato", "cadeia_citada", "cadeia_propria", "uf", "uf_propria", "tribunal",
                "tribunal_fonte", "tribunal_proprio", "filtros", "classe_relacao", "n_candidatos", "restantes",
                "diploma", "artigo", "numero", "vinculante", "multiplicidade", "llm", "letras_confundiveis")},
            "digitos_gabarito": c.digitos_gabarito,
        })
    return saida


def erros_por_rotulo(resultados: list[Resultado]) -> dict[str, dict[str, int]]:
    """Taxa de erro por rótulo de ruído/ood/forma (só rótulos com ≥ 1 erro)."""
    tot: Counter = Counter()
    err: Counter = Counter()
    for r in resultados:
        for rot in r.caso.rotulos:
            tot[rot] += 1
            if not r.acerto:
                err[rot] += 1
    return {k: {"n": tot[k], "erros": err[k]} for k in sorted(tot) if err[k]}


def formatar(nome: str, res: dict[str, Any], lista_erros: list[dict[str, Any]], por_rotulo: dict[str, dict[str, int]],
             max_erros: int) -> str:
    L = [f"== {nome}: {res['acertos']}/{res['n']} corretas (classe + id) = {100 * (res['acuracia'] or 0):.2f}%"]
    L.append("  por classe : " + "  ".join(f"{k}={v['ok']}/{v['n']}" for k, v in res["por_classe"].items()))
    L.append("  por família: " + "  ".join(f"{k}={v['ok']}/{v['n']}" for k, v in res["por_familia"].items()))
    L.append("  por nível  : " + "  ".join(f"N{k}={v['ok']}/{v['n']}" for k, v in res["por_nivel"].items()))
    L.append(f"  inventada→real (τ): {res['inventada_para_real']}   id correto nas real: "
             f"{res['reais']['id_correto']}/{res['reais']['n']}   dígitos ≠ gabarito: {res['digitos_diferentes_do_gabarito']}")
    conf = {k: v for k, v in res["matriz"].items() if k.split("->")[0] != k.split("->")[1]}
    if conf:
        L.append("  confusões  : " + "  ".join(f"{k}={v}" for k, v in conf.items()))
    b0 = res["brier_tabela_inicial"]
    L.append(f"  Brier (tabela inicial): {'-' if b0 is None else f'{b0:.4f}'}"
             + (f"   Brier (tabela dada): {res['brier_tabela']:.4f}" if res.get("brier_tabela") is not None else ""))
    L.append("  caminhos:")
    for k, v in res["caminhos"].items():
        L.append(f"    {k:48s} n={v['n']:4d} acc={100 * v['acuracia']:6.1f}%  conf={v['confianca']:.2f}")
    if por_rotulo:
        L.append("  erros por rótulo: " + ", ".join(f"{k}={v['erros']}/{v['n']}" for k, v in por_rotulo.items()))
    if lista_erros:
        L.append(f"  erros ({len(lista_erros)}; mostrando até {max_erros}):")
        for e in lista_erros[:max_erros]:
            L.append(f"    {'GRAVE ' if e['grave'] else ''}{e['documento_id']}/{e['citacao_id']} {e['familia']}: "
                     f"esperado {e['esperado']}({e['id_esperado'] or '-'}) obtido {e['obtido']}({e['id_obtido'] or '-'}) "
                     f"via {e['caminho']} conf={e['confianca']} rótulos={','.join(e['rotulos']) or '-'} "
                     f"detalhes={e['detalhes']}")
    return "\n".join(L)


def carregar_base(indice: Path | None = None, db: Path | None = None) -> BaseCanonica:
    indice = indice or caminho_indice()
    db = db or caminho_db()
    if Path(indice).exists():
        return BaseCanonica.de_arquivo(indice)
    if Path(db).exists():
        log.warning("índice %s ausente; construindo do banco %s", indice, db)
        return BaseCanonica.de_banco(db)
    raise FileNotFoundError(f"nem índice ({indice}) nem banco ({db}) encontrados")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalogo", type=Path, default=DADOS / "catalogo_gabarito.json")
    ap.add_argument("--sem-dev", action="store_true", help="não mede o dev (só sintéticos)")
    ap.add_argument("--sinteticos", type=Path, nargs="*", default=[], help="pastas geradas por gerar_sinteticos.py")
    ap.add_argument("--indice", type=Path, default=None)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--arbitro", default="nenhum", help="nenhum | mock | transformers | vllm")
    ap.add_argument("--calibracao", type=Path, default=None, help="tabela JSON para o Brier 'depois'")
    ap.add_argument("--sem-dados", action="store_true", help="Achado.dados vazio (a resolução recalcula tudo do trecho)")
    ap.add_argument("--erros", type=int, default=25, help="quantos erros listar por conjunto")
    ap.add_argument("--json", type=Path, default=None, help="grava o resumo (e erros) em JSON")
    ap.add_argument("--log-level", default="WARNING")
    args = ap.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING),
                        format="%(levelname)s %(name)s: %(message)s")

    base = carregar_base(args.indice, args.db)
    arbitro = None
    if args.arbitro and args.arbitro != "nenhum":
        from caca_alucinacao.llm import obter_arbitro

        arbitro = obter_arbitro(args.arbitro)
    tabela = calibracao.carregar(args.calibracao) if args.calibracao else None

    conjuntos: list[tuple[str, list[Caso]]] = []
    if not args.sem_dev and args.catalogo.exists():
        conjuntos.append(("dev (catálogo)", achados_do_catalogo(args.catalogo, com_dados=not args.sem_dados)))
    for pasta in args.sinteticos:
        conjuntos.append((f"sintético {pasta.name}", achados_dos_sinteticos(pasta, com_dados=not args.sem_dados)))
    if not conjuntos:
        print("nada a medir (catálogo ausente e nenhum conjunto sintético)", file=sys.stderr)
        return 2

    saida_json: dict[str, Any] = {}
    falhou = False
    for nome, casos in conjuntos:
        resultados = medir(base, casos, arbitro, tabela)
        res = resumo(resultados, tabela)
        lista = erros(resultados)
        por_rotulo = erros_por_rotulo(resultados)
        print(formatar(nome, res, lista, por_rotulo, args.erros))
        print()
        saida_json[nome] = {"resumo": res, "erros": lista, "erros_por_rotulo": por_rotulo}
        if nome.startswith("dev") and res["acertos"] != res["n"]:
            falhou = True
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(saida_json, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"resumo em {args.json}")
    return 1 if falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
