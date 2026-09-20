#!/usr/bin/env python3
"""Verifica que nenhum dado do desafio (gabarito/base) vazou para os arquivos versionados.

Regra do projeto: os dados do desafio (``dados/``) não podem ser redistribuídos,
logo **nenhum trecho, número ou nome do gabarito** pode aparecer em código,
testes, scripts ou docs. Este script deriva a lista proibida **dinamicamente**
do catálogo local (``dados/catalogo_gabarito.json``, ignorado pelo git) e do
índice (``dados/indice.json``) — ele próprio não contém nenhum literal — e faz
uma varredura dos arquivos versionados (``git ls-files``; sem git, tudo fora de
``dados/``, ``saida/`` e caches).

O que é proibido (cada item vira um "motivo" no relatório):

* ``trecho``: o span literal de qualquer citação do gabarito (brancos e
  ``\\n``/``\\xa0`` escapados de strings Python colapsados);
* ``numero``: os dígitos canônicos ou de superfície (≥ 5) de qualquer número de
  processo do gabarito, procurados nos tokens numéricos do arquivo (com
  pontuação/quebras removidas e letras de OCR convertidas) — inclusive uma
  forma parcial de um CNJ (≥ 13 dígitos);
* ``numero_base``: idem para os números próprios do índice da base (também são
  dados do desafio);
* ``sumula``: ``Súmula [Vinculante] N`` para todo número de súmula do gabarito;
* ``artigo``: ``art. N`` para artigos do gabarito com ≥ 3 dígitos, e ``art. N …
  <diploma>`` (até 60 caracteres) para os curtos;
* ``relator``: nome completo (≥ 2 palavras) de um relator do gabarito, sem
  distinção de caixa/acento, e as grafias com OCR dos nomes;
* ``relator_parcial``: dois sobrenomes consecutivos (sem partículas/títulos) de um
  mesmo relator do gabarito ou da base — um nome "disfarçado" que preserva o par
  ainda é o nome (revisão rodada 2, R4-06);
* ``ocr``: palavras que só existem no gabarito na forma com ruído de OCR
  (derivadas por comparação com as formas limpas do próprio gabarito e com os
  relatores da base).

Uso::

    python scripts/analise/verificar_vazamento.py [--raiz .] [--catalogo dados/catalogo_gabarito.json]

Saída: uma linha por ocorrência (``arquivo:linha: motivo: <o que casou>``) e
código de saída 1 se houver qualquer vazamento; 0 se limpo. Sem o catálogo
(clone sem ``dados/``) o script avisa e sai com 0 — a checagem só é possível
onde os dados existem. É chamado por ``tests/test_vazamento.py``.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

RAIZ_PADRAO = Path(__file__).resolve().parents[2]
EXTENSOES = {".py", ".md", ".txt", ".json", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".sh", ".ps1",
             ".csv", ".jsonl", ".rst", ""}
PASTAS_IGNORADAS = {"dados", "saida", ".git", "__pycache__", ".ruff_cache", ".venv", "modelos",
                    "cache_llm", "legado"}
CONFUSOES = {"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5", "s": "5", "g": "9", "q": "9",
             "G": "6", "B": "8", "Z": "2", "z": "2"}
#: Token numérico: dígitos e letras de OCR colados; pontuação (com um branco opcional depois)
#: ou branco só quando seguidos de dígito (``12.345 no S…`` → ``12.345``, nunca ``1234505``;
#: revisão rodada 2, R4-02). Além do token inteiro, cada segmento de ≥ 5 dígitos é testado à parte.
_RE_TOKEN_NUM = re.compile(
    r"\d(?:[\dOolI|SsgqGBZz]|[.\-–—/]\s?(?=\d)|(?:\s|\\n)+(?=\d))*"
)
_RE_SEGMENTO_DIGITOS = re.compile(r"\d{5,}")
_RE_PALAVRA_RX = re.compile(r"\w{2,}")
#: Partículas e títulos que não contam como sobrenome (pares de sobrenomes de relator, R4-06).
_PARTICULAS_NOME = frozenset(
    "de da do das dos e y von van ministro ministra min rel relator relatora des desembargador "
    "desembargadora dr dra sr sra exmo exma juiz juiza convocado convocada".split()
)


def _palavras(t: str) -> list[str]:
    return [w for w in _RE_PALAVRA_RX.findall(t) if any(ch.isalpha() for ch in w)]
_RE_ESCAPES = re.compile(r"\\(?:n|xa0|t|u00a0)")
_RE_BRANCOS = re.compile(r"\s+")

ALIASES_DIPLOMA = {
    "CF": r"(?:CF|CRFB|Constitui|Carta\s+Magna|Lei\s+Maior)",
    "CPC": r"(?:CPC|Processo\s+Civil|13\.?105)",
    "CPP": r"(?:CPP|Processo\s+Penal|3\.?689)",
    "CPM": r"(?:CPM|Penal\s+Militar|1\.?001)",
    "CC": r"(?:CC\b|C[óo]digo\s+Civil|10\.?406)",
    "CDC": r"(?:CDC|Consumidor|8\.?078)",
    "CE": r"(?:CE\b|C[óo]digo\s+Eleitoral|4\.?737)",
    "CLT": r"(?:CLT|Consolida|5\.?452)",
    "LC64": r"(?:LC\s*n?[º°.]?\s*64|Lei\s+Complementar\s+n?[º°.]?\s*64|Inelegib)",
}


#: Vocabulário genérico (palavras-chave dos detectores): só serve de referência
#: para reconhecer a forma com OCR de uma palavra comum; não é dado do desafio.
VOCABULARIO = frozenset("""
sumula súmula tema enunciado artigo constituicao constituição federal codigo código processo civil
penal lei recurso especial extraordinario extraordinário agravo reclamacao reclamação proferido julgado
precedente acordao acórdão decisao decisão relatoria ministro ministra vinculante regimental interno
embargos declaracao declaração divergencia divergência repercussao repercussão geral habeas corpus
mandado seguranca segurança apelacao apelação revista consolidacao consolidação leis trabalho
consumidor defesa eleitoral militar complementar decreto tribunal superior justica justiça supremo
""".split())
_DOBRAS = {"c": "e", "ã": "a", "l": "i", "0": "o", "5": "s", "ü": "u", "1": "i", "|": "i"}


def dobrar(t: str) -> str:
    """Forma "dobrada" em que as confusões de OCR conhecidas ficam indistinguíveis."""
    t = t.lower().replace("rn", "m")
    return "".join(_DOBRAS.get(ch, ch) for ch in t)


def sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def normalizar_brancos(t: str) -> str:
    return _RE_BRANCOS.sub(" ", _RE_ESCAPES.sub(" ", t)).strip()


def distancia(a: str, b: str, limite: int = 2) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limite:
        return limite + 1
    ant = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(ant[j] + 1, atual[j - 1] + 1, ant[j - 1] + (ca != cb)))
        if min(atual) > limite:
            return limite + 1
        ant = atual
    return ant[-1]


def arquivos_versionados(raiz: Path) -> list[Path]:
    """Arquivos rastreados **e** os novos ainda não adicionados (``--others``): um arquivo
    recém-criado com dados do gabarito tem de falhar no lint antes do ``git add`` (R3b-01)."""
    try:
        saida = subprocess.run(["git", "-C", str(raiz), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                               capture_output=True, check=True)
        nomes = [n for n in saida.stdout.decode("utf-8", "replace").split("\0") if n]
        arquivos = [raiz / n for n in nomes]
    except (OSError, subprocess.CalledProcessError):
        arquivos = [p for p in raiz.rglob("*") if p.is_file()]
    saida_lista: list[Path] = []
    for p in arquivos:
        rel = p.relative_to(raiz)
        if rel.parts and rel.parts[0] in PASTAS_IGNORADAS:
            continue
        if any(parte in PASTAS_IGNORADAS for parte in rel.parts[:-1]):
            continue
        if p.suffix.lower() not in EXTENSOES:
            continue
        if p.exists():
            saida_lista.append(p)
    return sorted(saida_lista)


class Proibidos:
    """Lista proibida derivada do catálogo (nunca escrita à mão)."""

    def __init__(self, catalogo: list[dict], indice: dict | None) -> None:
        self.trechos: list[str] = []
        self.numeros: set[str] = set()
        self.sumulas: list[re.Pattern[str]] = []
        self.artigos: list[re.Pattern[str]] = []
        self.relatores: list[re.Pattern[str]] = []
        self.pares_relator: set[tuple[str, str]] = set()
        self.ocr: set[str] = set()
        self._derivar(catalogo, indice or {})

    def _pares_de(self, nome: str) -> None:
        nomes = [sem_acento(w).lower() for w in _palavras(nome)]
        nomes = [w for w in nomes if w not in _PARTICULAS_NOME and len(w) >= 3]
        for a, b in zip(nomes, nomes[1:]):
            self.pares_relator.add((a, b))

    @staticmethod
    def _digitos(texto: str) -> str:
        return "".join(CONFUSOES.get(c, c) for c in texto if c.isdigit() or c in CONFUSOES)

    @staticmethod
    def _num_com_ocr(n: str) -> str:
        """``"896"`` → regex que casa ``896``, ``89G``, ``8g6``…: cada dígito admite as letras que o OCR
        põe no lugar dele (mapa inverso de ``CONFUSOES``; rodada 3, R5-03) e um ponto de milhar."""
        if len(n) < 2:
            return n   # um só caractere: só o dígito (``s``/``l`` soltos seriam prosa)
        inverso: dict[str, str] = {}
        for letra, dig in CONFUSOES.items():
            inverso[dig] = inverso.get(dig, "") + re.escape(letra)
        classes = [f"[{d}{inverso.get(d, '')}]" for d in n]
        corpo = "".join(classes[:-3]) + r"\.?" + "".join(classes[-3:]) if len(n) > 3 else "".join(classes)
        letras = "".join(re.escape(c) for c in sorted(set(CONFUSOES)))
        # caixa EXATA nas letras (``(?-i:…)``) e ao menos um dígito real dentro do número
        return rf"(?-i:(?=[\d.{letras}]*\d){corpo})"

    def _derivar(self, catalogo: list[dict], indice: dict) -> None:
        registros = indice.get("registros", {}) if isinstance(indice, dict) else {}
        relatores_base: set[str] = set()
        for r in registros.values():
            rel = r.get("relator") or ""
            relatores_base.update(w.lower() for w in _palavras(rel))
            self._pares_de(rel)
        # pares de sobrenomes consecutivos de QUALQUER relator do catálogo (vaga ou relator do
        # acórdão citado): um nome "disfarçado" que preserva dois sobrenomes seguidos ainda é o
        # nome do gabarito/da base (revisão rodada 2, R4-06)
        for c in catalogo:
            for chave, valor in c.items():
                if "relator" in chave and isinstance(valor, str):
                    self._pares_de(valor)
        # números próprios da base (índice): também são dados do desafio
        self.numeros_base: set[str] = set()
        for chave in (indice.get("por_digitos") or {}):
            if len(chave) >= 5:
                self.numeros_base.add(chave)
                self.numeros_base.add(chave.lstrip("0"))
        limpos: set[str] = set()
        ruidosos: list[dict] = []
        for c in catalogo:
            trecho = normalizar_brancos(c["trecho"])
            if trecho:
                self.trechos.append(trecho)
            fam = c.get("familia")
            if fam == "processo":
                for d in (c.get("digitos") or "", self._digitos(c.get("numero_superficie") or "")):
                    if len(d) >= 5:
                        self.numeros.add(d)
                        self.numeros.add(d.lstrip("0"))
            elif fam == "sumula" and c.get("numero_sumula"):
                n = str(c["numero_sumula"])
                num = self._num_com_ocr(n)
                self.sumulas.append(re.compile(
                    rf"(?i)(?:s[úu5]m\w*\.?|enunciado|verbete)\s*(?:n[º°.o]*\s*)?(?:vinculante\s*)?(?:n[º°.o]*\s*)?"
                    rf"{num}(?![\dA-Za-z])"))
                # ``<TRIBUNAL> <n>``/``SV <n>``/``<TRIBUNAL>/<n>``: a chave (tribunal, número) escrita sem a
                # palavra "Súmula" — forma de tabela que escapava (rodada 3, R5-03)
                trib = "SV" if c.get("vinculante") in ("1", 1, True) else str(c.get("tribunal") or "")
                if trib and trib not in ("", "None"):
                    self.sumulas.append(re.compile(rf"(?<![A-Za-z]){trib}\s{{0,2}}[/\-]?\s{{0,2}}{num}(?![\dA-Za-z])"))
            elif fam == "dispositivo" and c.get("artigo"):
                art = str(c["artigo"])
                num = self._num_com_ocr(art)
                alias = ALIASES_DIPLOMA.get(str(c.get("diploma") or ""))
                if len(art) >= 3:
                    self.artigos.append(re.compile(rf"(?i)art\w*\.?\s*(?:[º°]\s*)?{num}(?![\dA-Za-z])"))
                elif alias:
                    self.artigos.append(re.compile(
                        rf"(?i)art\w*\.?\s*(?:[º°]\s*)?{num}(?![\dA-Za-z.]).{{0,60}}?{alias}", re.S))
                # ``<DIPLOMA> <n>``/``<DIPLOMA> <n>, <m>``: par (diploma, artigo) sem a palavra "art." (R5-03)
                sigla = str(c.get("diploma") or "")
                if sigla and sigla.isupper():
                    self.artigos.append(re.compile(
                        rf"(?<![A-Za-z]){re.escape(sigla)}\s{{1,2}}(?:\d{{1,4}},\s{{0,2}}){{0,4}}{num}(?![\dA-Za-z.])"))
            elif fam == "vaga":
                rel = c.get("relator") or ""
                palavras = _palavras(rel)
                if len(palavras) >= 2:
                    padrao = r"\b" + r"\s+(?:d[aeo]s?\s+)?".join(
                        re.escape(sem_acento(w).lower()) for w in palavras) + r"\b"
                    self.relatores.append(re.compile(padrao))
            if any("ocr" in str(r) for r in c.get("ruidos", [])):
                ruidosos.append(c)
            else:
                limpos.update(w.lower() for w in _palavras(c["trecho"]))
                limpos.update(w.lower() for w in _palavras(c.get("relator") or ""))
        # palavras que só existem no gabarito com OCR: a mesma palavra limpa (do próprio
        # gabarito, dos relatores da base ou do vocabulário jurídico genérico) depois de
        # dobrar as confusões conhecidas (e↔c, a↔ã, i↔l, m↔rn, o↔0, s↔5, u↔ü)
        referencia = {dobrar(u): u for u in limpos | relatores_base | VOCABULARIO}
        for c in ruidosos:
            for w in _palavras(c["trecho"]) + _palavras(c.get("relator") or ""):
                wl = w.lower()
                if len(wl) < 3 or wl in limpos or wl in relatores_base or wl in VOCABULARIO:
                    continue
                u = referencia.get(dobrar(wl))
                if u is not None and u != wl:
                    self.ocr.add(wl)
        self.trechos = sorted(set(self.trechos), key=len, reverse=True)


def verificar_arquivo(caminho: Path, p: Proibidos) -> list[tuple[int, str, str]]:
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return _verificar_texto(texto, p)


def _verificar_texto(texto: str, p: Proibidos) -> list[tuple[int, str, str]]:
    achados: list[tuple[int, str, str]] = []
    linhas = texto.split("\n")
    # 1. trechos literais (janela de 3 linhas, brancos colapsados)
    for i in range(len(linhas)):
        bloco = normalizar_brancos("\n".join(linhas[i:i + 3]))
        for t in p.trechos:
            if t in bloco and (i == 0 or t not in normalizar_brancos("\n".join(linhas[i - 1:i + 2]))):
                achados.append((i + 1, "trecho", t))
    for i, linha in enumerate(linhas, 1):
        # 2. números de processo: o token inteiro e cada segmento de ≥ 5 dígitos
        for m in _RE_TOKEN_NUM.finditer(linha):
            bruto = m.group(0).strip()
            tok = p._digitos(bruto)
            if len(tok) < 5:
                continue
            candidatos = [tok] + [seg for seg in _RE_SEGMENTO_DIGITOS.findall(bruto) if seg != tok]
            motivo = None
            for cand in candidatos:
                if any(cand == n or (len(n) >= 7 and n in cand) or (len(cand) >= 13 and cand in n) for n in p.numeros):
                    motivo = "numero"
                    break
                if cand in p.numeros_base or (len(cand) >= 9 and any(
                        (n in cand or (len(cand) >= 13 and cand in n)) for n in p.numeros_base if len(n) >= 9)):
                    motivo = "numero_base"
                    break
            if motivo:
                achados.append((i, motivo, bruto))
        # 3./4. súmulas e artigos
        for rx in p.sumulas:
            m = rx.search(linha)
            if m:
                achados.append((i, "sumula", m.group(0)))
        for rx in p.artigos:
            m = rx.search(linha)
            if m:
                achados.append((i, "artigo", m.group(0)[:60]))
        # 5. relatores: nome completo (sem acento/caixa) e pares de sobrenomes consecutivos
        plana = sem_acento(linha).lower()
        for rx in p.relatores:
            m = rx.search(plana)
            if m:
                achados.append((i, "relator", m.group(0)))
        if p.pares_relator:
            nomes = [w for w in _RE_PALAVRA_RX.findall(plana)
                     if w.isalpha() and len(w) >= 3 and w not in _PARTICULAS_NOME]
            for a, b in zip(nomes, nomes[1:]):
                if (a, b) in p.pares_relator:
                    achados.append((i, "relator_parcial", f"{a} {b}"))
        # 6. formas com OCR
        for w in _palavras(linha):
            if w.lower() in p.ocr:
                achados.append((i, "ocr", w))
    return achados


def carregar_catalogo(caminho: Path) -> list[dict]:
    return json.loads(caminho.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    ap.add_argument("--catalogo", type=Path, default=None)
    ap.add_argument("--indice", type=Path, default=None)
    ap.add_argument("--quieto", action="store_true")
    ap.add_argument("--historico", action="store_true",
                    help="varre também o histórico do git (git log -p --all): o repositório publicado "
                         "não pode ter dados do desafio em NENHUM commit (R3b-01)")
    args = ap.parse_args(argv)
    raiz = args.raiz.resolve()
    catalogo = args.catalogo or raiz / "dados" / "catalogo_gabarito.json"
    indice = args.indice or raiz / "dados" / "indice.json"
    if not catalogo.exists():
        if (raiz / "dados" / "goldenset.csv").exists():
            print(f"catálogo ausente ({catalogo}) mas dados/goldenset.csv existe: gere-o com\n"
                  "  PYTHONPATH=src python scripts/analise/catalogar_gabarito.py --resumo\n"
                  "(make dados já faz isso). A verificação de vazamento NÃO foi executada.", file=sys.stderr)
            return 1
        print(f"catálogo ausente ({catalogo}); verificação de vazamento não executada", file=sys.stderr)
        return 0
    idx = json.loads(indice.read_text(encoding="utf-8")) if indice.exists() else None
    proibidos = Proibidos(carregar_catalogo(catalogo), idx)
    total = 0
    for arq in arquivos_versionados(raiz):
        for linha, motivo, casou in verificar_arquivo(arq, proibidos):
            total += 1
            if not args.quieto:
                print(f"{arq.relative_to(raiz)}:{linha}: {motivo}: {casou!r}")
    print(f"{total} ocorrência(s) de dados do desafio em arquivos versionados", file=sys.stderr)
    if args.historico:
        n_hist = verificar_historico(raiz, proibidos, quieto=args.quieto)
        print(f"{n_hist} ocorrência(s) de dados do desafio no histórico do git", file=sys.stderr)
        total += n_hist
    return 1 if total else 0


def verificar_historico(raiz: Path, p: Proibidos, quieto: bool = False) -> int:
    """Conta ocorrências nas linhas ADICIONADAS por qualquer commit de qualquer ramo.

    Só o conteúdo (``git log -p --all``, linhas ``+``) é analisado: um vazamento em
    commit antigo continua redistribuído por ``git clone`` mesmo depois de removido
    da árvore de trabalho — a correção é reescrever o histórico (README, "Dados").
    """
    try:
        saida = subprocess.run(["git", "-C", str(raiz), "log", "-p", "--all", "--no-color", "--format=commit %H"],
                               capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print("sem git: histórico não verificado", file=sys.stderr)
        return 0
    commit = "?"
    arquivo = "?"
    adicionadas: list[str] = []
    total = 0

    def _flush() -> int:
        if not adicionadas:
            return 0
        tmp = "\n".join(adicionadas)
        n = 0
        for _linha, motivo, casou in _verificar_texto(tmp, p):
            n += 1
            if not quieto:
                print(f"historico {commit[:12]} {arquivo}: {motivo}: {casou!r}")
        adicionadas.clear()
        return n

    for linha in saida.stdout.decode("utf-8", "replace").split("\n"):
        if linha.startswith("commit "):
            total += _flush()
            commit = linha[7:].strip()
        elif linha.startswith("+++ "):
            total += _flush()
            arquivo = linha[4:].strip()
        elif linha.startswith("+") and not linha.startswith("+++"):
            adicionadas.append(linha[1:])
    total += _flush()
    return total


if __name__ == "__main__":
    raise SystemExit(main())
