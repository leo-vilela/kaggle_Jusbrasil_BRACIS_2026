"""Família ``vaga``: tribunal + ano + relator, sem número (docs/03 §2.6).

Toda ``vaga`` do dev é ``incompleta`` (32/32). O span vai do substantivo
(``julgado``, ``precedente``, ``acórdão``, ``decisão``, ``aresto``) ou da classe
(``Reclamação``, ``Rcl``, ``APL``, ``Agravo em Recurso Especial``) até a última
palavra do nome do relator; o artigo anterior e a pontuação seguinte ficam fora.

Dois padrões:

* **estrito** (``regex:vaga:<molde>``, força 1,0): os moldes A–E do dev e F–H
  do gerador (docs/05 §5), numa só regex com as âncoras obrigatórias, mais as
  ordens ``min_sem_rel``, ``parenteses_rel``, ``parenteses`` e
  ``relator_antes_ano`` (revisão R2-06) —
  substantivo/classe, tribunal (exceto no molde D, que tem classe), ano de
  4 dígitos, fórmula de relatoria e nome próprio — e tolerância ao OCR medido
  (``proferldo``, ``dc``, ``julgãdo``, ``relatorla``, ``Rel.  Min.``,
  ``Rel.\\nMin.``, quebra antes ou dentro do nome);
* **amplo** (``regex:vaga:amplo``, força 0,6): ancorado em ``<ano> … <fórmula
  de relatoria> <Nome>`` (≤ 60 caracteres entre o ano e a fórmula) com um
  tribunal (sigla ou nome por extenso) até 120 caracteres antes do ano, sem
  ponto final entre eles; começa no substantivo/classe que precede o
  tribunal ou, na falta dele, no próprio tribunal.

Armadilhas (docs/03 §6.3): "orientação dos tribunais superiores é firme no
ponto", "jurisprudência pacífica desta Corte", "entendimento sumulado sobre a
matéria" e as ood "O STJ, em 2019, consolidou…", "Como anotou o Ministro
relator em seu voto" não disparam — falta ano, ou falta relatoria, ou falta
nome próprio. Nenhum padrão dispara sem os três.
"""
from __future__ import annotations

import logging
import re

from ..normalizacao import CONFUSOES, cadeia_de_classes, chave_textual, classe_principal, inferir_tribunal
from ..tipos import Achado
from . import padroes as P

log = logging.getLogger(__name__)

_ESQUERDA = r"(?<![A-Za-zÀ-ÿ0-9])"
#: Substantivos que abrem os moldes A, B, E, F, G, H (e sinônimos plausíveis).
_SUBSTANTIVO = (
    rf"(?:{P.P_JULGADO}|{P.P_PRECEDENTE}|{P.P_ACORDAO}|{P.P_DECISAO}|{P.P_ARESTO}"
    r"|[eE]nt[ec]nd[il]m[ec]nt[o0]|[oO]r[il][ec]nt[aã][çc][ãa][o0]|[jJ]ur[il]spr[uü]d[êe]nc[il][aã]"
    r"|[vV][o0]t[o0](?:\s{1,2}[cC][o0]ndut[o0]r)?|[lL][ec][aã]d[il]ng\s?[cC][aã]s[ec]|[pP][o0]s[il][çc][ãa][o0]|[tT][ec]s[ec])"
)   # ``voto condutor`` (rodada 4, R6-06)
#: Palavras que podem ficar entre o tribunal/classe e o ano.
_ANTES_ANO = (
    rf"(?:{P.P_PROFERIDO}{P.S}{P.P_EM}|{P.P_JULGADO}{P.S}{P.P_EM}|{P.P_DE}|{P.P_EM}"
    rf"|{P.P_DE}{P.S}{P.P_JULGADO}{P.S}{P.P_EM}|{P.P_DE}{P.S}{P.P_PROFERIDO}{P.S}{P.P_EM})"
)

#: ``Min.``/``Ministro`` sem ``Rel.`` logo depois de ``<ano>,`` (molde ``min_sem_rel``,
#: revisão R2-06): ``julgado do TSE de 2023, Min. Fulano``. Só é aceito colado à
#: vírgula que segue o ano — em qualquer outra posição ``Ministro X`` é prosa. Também
#: entre parênteses logo depois do ano: ``decisão do STJ de 2023 (Min. Fulano)`` (rodada 3, R3-05).
_MIN_SEM_REL = rf"(?:{P.P_MIN}|Des\.?){P.S}"

#: Entre o substantivo e o tribunal (revisão rodada 2, R4-04/R4-11): ``do``/``da``/``pelo``,
#: com verbo opcional antes (``proferido pelo STJ``, ``firmado pelo TST``) e, depois,
#: adjetivo (``do Eg. STJ``, ``do Colendo STF``) e/ou órgão fracionário (``da Corte
#: Especial do STJ``, ``da Primeira Turma do STF``) — tudo entra no span.
_VERBO = (rf"(?:{P._regex_palavra('proferid')}|firmad|exarad|prolatad|adotad|consolidad"
          r"|assentad|emanad|oriund|lavrad)[oa0ã]s?")
_ADJ_TRIBUNAL = r"(?:[Ee]gr[ée]gi[oa]|[Cc]olend[oa]|[Ee]g\.|[Ee]\.|[Cc]\.|[Ee]xcels[oa])"
_LIGA_TRIBUNAL = (
    rf"(?:{_VERBO}{P.S})?(?:{P.P_DO}|{P.P_DA}|p[ec][l1][oa]|{P.P_DE}){P.S}"
    rf"(?:{_ADJ_TRIBUNAL}{P.S})?(?:{P.ORGAO_FRACIONARIO}{P.S}{P.P_DO}{P.S}(?:{_ADJ_TRIBUNAL}{P.S})?)?"
)
#: Data completa opcional antes do ano (``julgado em 12/03/2015``, ``de 12 de março de 2015``; revisão
#: rodada 3, R5-01; no molde principal desde a rodada 4, R4-06).
_DATA_ANTES_DO_ANO = r"(?:\d{1,2}[/.\-]\d{1,2}[/.\-]|\d{1,2}{S}de{S}[a-zç]+{S}de{S}|\d{1,2}\.\d{1,2}\.)?".replace("{S}", P.S)
#: Ano entre parênteses logo depois do tribunal (``decisão do STF (2023), Rel. Min. X``).
_ANO_PARENTESES = rf"\s{{0,2}}\(\s{{0,2}}(?P<ano_par>{P.ANO_OCR})\s{{0,2}}\)"
#: Separador entre o ano e a fórmula de relatoria: vírgula, ponto-e-vírgula ou travessão
#: (``de 2019; Rel. Min. X``, ``de 2019 - Rel. Min. X``; rodada 4, R6-06).
_SEP_REL = r"(?:[,;]|\s{0,2}[-–—])?"
_RELATORIA_E_NOME = (
    rf"(?:{_SEP_REL}{P.S}(?P<rel>{P.RELATORIA})|[,;]{P.S0}(?P<rel_min>{_MIN_SEM_REL})"
    rf"|\s{{0,2}}\(\s{{0,2}}(?P<rel_par>{_MIN_SEM_REL}))"
    rf"(?P<nome>{P.NOME_RELATOR})(?(rel_par)\s{{0,2}}\))"
)

RE_VAGA = re.compile(
    rf"""
    {_ESQUERDA}
    (?:
        (?P<sub>{_SUBSTANTIVO}){P.S}{_LIGA_TRIBUNAL}(?P<trib>{P.TRIBUNAL})
      | (?P<classe>{P.CADEIA})(?:{P.S}{P.P_DO}{P.S}(?P<trib2>{P.TRIBUNAL}))?
    )
    (?![A-Za-zÀ-ÿ])
    (?:
        ,?{P.S}(?:{_ANTES_ANO}{P.S})?{_DATA_ANTES_DO_ANO}(?P<ano>{P.ANO_OCR})
      | {_ANO_PARENTESES}
    )
    {_RELATORIA_E_NOME}
    """,
    re.VERBOSE,
)

#: Moldes com outra ordem dos campos (revisão R2-06 e rodada 2, R4-04), todos com as
#: três âncoras (tribunal, ano, nome próprio) e força 1,0:
#:
#: * ``ano_antes_tribunal``: ``julgado de 2024 do TST, Rel. Min. Nome``, ``precedente de
#:   2017 do TST, da relatoria de Nome``;
#: * ``parenteses_rel``: ``precedente do TSE (Rel. Min. Nome, 2022)`` e ``decisão do STF
#:   (Rel. Min. Nome, j. 2023)`` — o ``)`` entra;
#: * ``parenteses``: ``voto do relator Ministro Nome (STF, 2020)`` — idem;
#: * ``relator_antes_ano``: ``acórdão relatado pela Ministra Nome em 2021 no STJ``.
_ABRE = r"\s{0,2}\(\s{0,2}"
_FECHA = r"\s{0,2}\)"
#: O que pode preceder o ano quando o relator vem antes dele: ``j.``, ``julg.``, ``julgado em``,
#: ``DJe``/``DJe de``/``DJ``, ``sessão de``, ``publicado em``, ``em``, ``de`` — com a data completa
#: opcional (``j. 12/03/2021``, ``DJe de 3 de maio de 2021``; revisão rodada 3, R5-01).
_J = (
    r"(?:(?:j|julg|jul)\.?{S0}(?:em{S})?|julgad[oa]{S}em{S}|DJ[eEuU]?{S}(?:de{S})?|DJE{S}(?:de{S})?"
    r"|sess[ãa]o{S}de{S}|publicad[oa]{S}em{S}|em{S}|de{S})?"
).replace("{S0}", P.S0).replace("{S}", P.S) + _DATA_ANTES_DO_ANO
RE_VAGA_OUTRAS_ORDENS: list[tuple[str, re.Pattern[str]]] = [
    ("ano_antes_tribunal", re.compile(
        rf"""
        {_ESQUERDA}
        (?P<sub>{_SUBSTANTIVO}){P.S}{_ANTES_ANO}{P.S}(?P<ano>{P.ANO_OCR})
        ,?{P.S}{_LIGA_TRIBUNAL}(?P<trib>{P.TRIBUNAL})(?![A-Za-zÀ-ÿ])
        {_RELATORIA_E_NOME}
        """, re.VERBOSE)),
    ("parenteses_rel", re.compile(
        rf"""
        {_ESQUERDA}
        (?P<sub>{_SUBSTANTIVO}){P.S}{_LIGA_TRIBUNAL}(?P<trib>{P.TRIBUNAL})(?![A-Za-zÀ-ÿ])
        {_ABRE}(?P<rel>{P.REL_MIN}{P.S}(?:{P.HONORIFICO}{P.S})?)(?P<nome>{P.NOME_RELATOR})
        ,{P.S0}{_J}(?P<ano>{P.ANO_OCR}){_FECHA}
        """, re.VERBOSE)),
    ("parenteses", re.compile(
        rf"""
        {_ESQUERDA}
        (?P<sub>{_SUBSTANTIVO}){P.S}
        (?P<rel>{P.P_DO}{P.S}(?:{P.P_RELATOR}{P.S}(?:{P.P_MIN}{P.S})?|{P.P_MINISTRO}{P.S}{P.P_RELATOR}{P.S}|{P.REL_MIN}{P.S})
                |{P.RELATORIA})
        (?P<nome>{P.NOME_RELATOR})
        {_ABRE}(?P<trib>{P.TRIBUNAL}),{P.S0}{_J}(?P<ano>{P.ANO_OCR}){_FECHA}
        """, re.VERBOSE)),
    # ``acórdão do STJ, Rel. Min. Nome, j. 2021`` / ``julgado do T, Relator Ministro Nome, de 2021`` /
    # ``precedente do T, da relatoria do Ministro Nome, 2021`` / ``acórdão do STJ, Rel. Min. Nome, DJe 2021``:
    # relator antes do ano, SEM parênteses — a ordem mais comum na prática forense (revisão rodada 3,
    # R5-01/R3-05). Exige as três âncoras; o ano tem de vir logo depois do nome (vírgula + marca opcional).
    ("relator_antes_ano_virgula", re.compile(
        rf"""
        {_ESQUERDA}
        (?P<sub>{_SUBSTANTIVO}){P.S}{_LIGA_TRIBUNAL}(?P<trib>{P.TRIBUNAL})(?![A-Za-zÀ-ÿ])
        ,?{P.S}(?P<rel>{P.RELATORIA})(?P<nome>{P.NOME_RELATOR})
        ,{P.S0}{_J}(?P<ano>{P.ANO_OCR})
        """, re.VERBOSE)),
    # ``STF, 2024, Rel. Min. Nome`` / ``Supremo Tribunal Federal, julgado de 2022, Rel. Min. Nome``: o
    # tribunal abre a citação (sem substantivo), mas a fórmula ``Rel. Min.``/``Relator Ministro`` separada
    # por vírgulas é de citação, não de prosa (revisão rodada 3, R3-05). O span começa no tribunal.
    ("tribunal_primeiro", re.compile(
        rf"""
        (?<![A-Za-zÀ-ÿ0-9/])
        (?P<trib>{P.TRIBUNAL})(?![A-Za-zÀ-ÿ])
        ,{P.S0}(?:{_ANTES_ANO}{P.S}|{P.P_JULGADO}{P.S}{P.P_DE}{P.S}|{_J})?(?P<ano>{P.ANO_OCR})
        ,{P.S0}(?P<rel>{P.REL_MIN}{P.S}(?:{P.HONORIFICO}{P.S})?)(?P<nome>{P.NOME_RELATOR})
        """, re.VERBOSE)),
    # ``acórdão da lavra do Ministro Nome, STF, 2026`` (revisão rodada 3, R3-05).
    ("lavra_nome_antes", re.compile(
        rf"""
        {_ESQUERDA}
        (?P<sub>{_SUBSTANTIVO}){P.S}(?P<rel>{P.RELATORIA})(?P<nome>{P.NOME_RELATOR})
        ,{P.S0}(?P<trib>{P.TRIBUNAL})(?![A-Za-zÀ-ÿ]),{P.S0}{_J}(?P<ano>{P.ANO_OCR})
        """, re.VERBOSE)),
    # ``precedente da lavra do Ministro X, julgado pelo STF em 2024`` / ``decisão do Ministro X no STF, em
    # 2019`` / ``voto condutor do Ministro X no STF, em 2019``: tribunal e ano DEPOIS do nome (rodada 4,
    # R6-05). Exige as três âncoras; o ano vem logo depois do tribunal.
    ("nome_tribunal_ano", re.compile(
        rf"""
        {_ESQUERDA}
        (?P<sub>{_SUBSTANTIVO}){P.S}
        (?P<rel>{P.RELATORIA}|(?:{P.P_DO}|{P.P_DA}){P.S}(?:{P.HONORIFICO}{P.S})?{P.P_MIN}{P.S})
        (?P<nome>{P.NOME_RELATOR})
        ,?{P.S}(?:{P.P_JULGADO}{P.S}p[ec][l1][oa]|{P.P_PROFERIDO}{P.S}p[ec][l1][oa]|{P.P_DO}|{P.P_DA}|n[oa]|N[OA]|p[ec][l1][oa]){P.S}
        (?:{_ADJ_TRIBUNAL}{P.S})?(?P<trib>{P.TRIBUNAL})(?![A-Za-zÀ-ÿ])
        ,?{P.S}(?:{P.P_EM}|{P.P_DE}|{_J}){P.S0}{_DATA_ANTES_DO_ANO}(?P<ano>{P.ANO_OCR})
        """, re.VERBOSE)),
    # ``julgado de 2021 da relatoria do Ministro X, do STM`` (rodada 4, R6-05): ano antes, tribunal no fim.
    ("ano_nome_tribunal", re.compile(
        rf"""
        {_ESQUERDA}
        (?P<sub>{_SUBSTANTIVO}){P.S}{_ANTES_ANO}{P.S}(?P<ano>{P.ANO_OCR})
        ,?{P.S}(?P<rel>{P.RELATORIA})(?P<nome>{P.NOME_RELATOR})
        ,?{P.S}(?:{P.P_DO}|{P.P_DA}|n[oa]|N[OA]|p[ec][l1][oa]){P.S}(?:{_ADJ_TRIBUNAL}{P.S})?(?P<trib>{P.TRIBUNAL})(?![A-Za-zÀ-ÿ])
        """, re.VERBOSE)),
    ("relator_antes_ano", re.compile(
        rf"""
        {_ESQUERDA}
        (?P<sub>{_SUBSTANTIVO}){P.S}
        (?P<rel>{P.P_RELATADO}{P.S}p[ec][l1][oa]{P.S}(?:{P.HONORIFICO}{P.S})?(?:{P.P_MIN}|Des\.?){P.S}|{P.P_DE}{P.S}{P.P_RELATORIA}{P.S}(?:{P.P_DO}|{P.P_DA}|{P.P_DE}){P.S}(?:{P.HONORIFICO}{P.S})?(?:{P.P_MIN}{P.S})?)
        (?P<nome>{P.NOME_RELATOR})
        ,?{P.S}(?:{P.P_EM}|{P.P_DE}){P.S}(?P<ano>{P.ANO_OCR})
        ,?{P.S}(?:no|na|do|da|pelo|pela|NO|NA|DO|DA){P.S}(?P<trib>{P.TRIBUNAL})(?![A-Za-zÀ-ÿ])
        """, re.VERBOSE)),
]

#: Âncora do padrão amplo: ano … fórmula de relatoria + nome (janela ≤ 60).
#: O ``<meio>`` nunca atravessa um fim de frase (``. Veja-se``; revisão rodada 3, R5-09).
RE_VAGA_ANCORA = re.compile(
    rf"""
    (?:(?<![\d/.\-])|(?<=\d\d/))(?P<ano>{P.ANO_OCR})
    (?P<meio>(?:(?![.;!?]\s+[A-ZÀ-Ú]).){{0,60}}?)
    (?P<rel>{P.RELATORIA})
    (?P<nome>{P.NOME_RELATOR})
    """,
    re.VERBOSE | re.DOTALL,
)
#: Ordem inversa do amplo (revisão rodada 3, R5-01): ``<fórmula de relatoria> <Nome>, … <ano>`` com
#: janela ≤ 40 entre o nome e o ano; o tribunal continua a ser procurado antes da fórmula.
RE_VAGA_ANCORA_INVERSA = re.compile(
    rf"""
    (?<![A-Za-zÀ-ÿ])(?P<rel>{P.RELATORIA})
    (?P<nome>{P.NOME_RELATOR})
    (?P<meio>(?:(?![.;!?]\s+[A-ZÀ-Ú]).){{0,40}}?)
    (?:(?<![\d/.\-])|(?<=\d\d/))(?P<ano>{P.ANO_OCR})
    """,
    re.VERBOSE | re.DOTALL,
)
RE_TRIBUNAL = re.compile(rf"(?<![A-Za-zÀ-ÿ]){P.TRIBUNAL}(?![A-Za-zÀ-ÿ])")
RE_SUBSTANTIVO_OU_CLASSE = re.compile(
    rf"{_ESQUERDA}(?:{_SUBSTANTIVO}|{P.CADEIA})(?![A-Za-zÀ-ÿ])"
)
_RE_LIGA_TRIBUNAL = re.compile(rf"\s{{1,4}}{_LIGA_TRIBUNAL}")
_RE_FECHA_PARENTESE = re.compile(r"\s{0,2}\)")
#: Fim de frase: ponto/ponto-e-vírgula seguido de branco e maiúscula.
_RE_FIM_DE_FRASE = re.compile(r"[.;!?]\s+[A-ZÀ-Ú]")
JANELA_TRIBUNAL = 120
JANELA_SUBSTANTIVO = 60

_RE_MOLDE = [
    ("A", re.compile(rf"^{P.P_JULGADO}\b.*{P.P_PROFERIDO}", re.S)),
    ("B", re.compile(rf"^{P.P_PRECEDENTE}\b", re.S)),
    ("E", re.compile(rf"^{P.P_ACORDAO}\b", re.S)),
    ("F", re.compile(rf"^{P.P_DECISAO}\b", re.S)),
    ("G", re.compile(rf"^{P.P_ARESTO}\b", re.S)),
    ("H", re.compile(rf"^{P.P_JULGADO}\b", re.S)),
]


_SIGLAS_TRIBUNAL = frozenset({"STF", "STJ", "TSE", "TST", "STM"})


def sigla_do_tribunal(texto: str | None) -> str:
    """``"Superior Tribunal de Justiça"`` → ``"STJ"``; ``"STF"`` → ``"STF"``; vazio se nada."""
    if not texto:
        return ""
    sigla = P.sigla_tribunal_canonica(texto)   # ``5TJ``, ``S.T.J.`` (rodada 3, R3-06)
    if sigla:
        return sigla
    t = chave_textual(texto)
    if t.upper() in _SIGLAS_TRIBUNAL:
        return t.upper()
    if "supremo" in t:
        return "STF"
    if "justica" in t:
        return "STJ"
    if "eleitoral" in t:
        return "TSE"
    if "trabalho" in t:
        return "TST"
    if "militar" in t:
        return "STM"
    return ""


def _molde(trecho: str, classe: str | None, trib: str) -> str:
    """Letra do molde (docs/03 §2.6 A–E; docs/05 F–H) para diagnóstico e origem."""
    if classe:
        return "C" if trib else "D"
    for nome, rx in _RE_MOLDE:
        if rx.match(trecho):
            return nome
    return "outro"


def ano_canonico(ano: str) -> str | None:
    """``"2O21"`` → ``"2021"`` (mapa inverso do gerador); ``None`` com menos de 2 dígitos reais."""
    if sum(c.isdigit() for c in ano) < 2:
        return None
    dig = "".join(CONFUSOES.get(c, c) for c in ano)
    return dig if dig.isdigit() and len(dig) == 4 else None


def _montar(texto: str, inicio: int, fim: int, *, sub: str | None, classe: str | None,
            trib: str | None, ano: str, nome: str, origem: str, forca: float) -> Achado | None:
    ano_dig = ano_canonico(ano)
    if ano_dig is None:
        return None
    cadeia = cadeia_de_classes(classe) if classe else []
    principal = classe_principal(cadeia) or ""
    tribunal = sigla_do_tribunal(trib)
    if not tribunal and cadeia:
        tribunal = inferir_tribunal(cadeia) or ""
    dados = {
        "classe": classe or "",
        "cadeia": " ".join(cadeia),
        "classe_principal": principal,
        "numero": "",
        "digitos": "",
        "formato": "",
        "uf": "",
        "tribunal": tribunal,
        "ano": ano_dig,
        "relator": " ".join(nome.split()),
        "artigo": "",
        "diploma": "",
        "numero_sumula": "",
        "vinculante": "",
        "numero_tema": "",
        "substantivo": sub or "",
        "molde": _molde(texto[inicio:fim], classe, sigla_do_tribunal(trib)),
    }
    return Achado(inicio, fim, texto[inicio:fim], "vaga", "jurisprudencia", dados, origem, forca)


def detectar_estrito(texto: str) -> list[Achado]:
    """Moldes A–H e as outras ordens (força 1,0). Origem ``regex:vaga:<molde>``."""
    saida: list[Achado] = []
    for m in RE_VAGA.finditer(texto):
        trib = m.group("trib") or m.group("trib2")
        a = _montar(texto, m.start(), m.end(), sub=m.group("sub"), classe=m.group("classe"),
                    trib=trib, ano=m.group("ano") or m.group("ano_par"), nome=m.group("nome"),
                    origem="regex:vaga", forca=1.0)
        if a is None:
            continue
        molde = a.dados["molde"] if not (m.group("rel_min") or m.group("rel_par")) else "min_sem_rel"
        a.dados["molde"] = molde
        a = Achado(a.inicio, a.fim, a.trecho, a.familia, a.tipo, a.dados, f"regex:vaga:{molde}", 1.0)
        saida.append(a)
    for molde, rx in RE_VAGA_OUTRAS_ORDENS:
        for m in rx.finditer(texto):
            a = _montar(texto, m.start(), m.end(), sub=m.groupdict().get("sub"), classe=None,
                        trib=m.group("trib"), ano=m.group("ano"), nome=m.group("nome"),
                        origem="regex:vaga", forca=1.0)
            if a is None:
                continue
            a.dados["molde"] = molde
            saida.append(Achado(a.inicio, a.fim, a.trecho, a.familia, a.tipo, a.dados,
                                f"regex:vaga:{molde}", 1.0))
    saida.sort(key=lambda a: (a.inicio, -a.fim))
    return saida


def _amplo_de(texto: str, m: re.Match[str], ancora: int, inverso: bool) -> Achado | None:
    """Monta o achado amplo a partir de um casamento da âncora (``ancora`` = onde procurar o tribunal antes)."""
    janela_ini = max(0, ancora - JANELA_TRIBUNAL)
    janela = texto[janela_ini:ancora]
    tribs = list(RE_TRIBUNAL.finditer(janela))
    if not tribs:
        return None
    t = tribs[-1]
    if _RE_FIM_DE_FRASE.search(janela, t.start()):
        return None  # o tribunal está numa frase anterior
    inicio = janela_ini + t.start()
    # substantivo/classe logo antes do tribunal: "julgado do STF", "Reclamação do STF"
    antes = texto[max(0, inicio - JANELA_SUBSTANTIVO):inicio]
    sub_txt: str | None = None
    classe_txt: str | None = None
    for s in RE_SUBSTANTIVO_OU_CLASSE.finditer(antes):
        resto = antes[s.end():]
        if _RE_LIGA_TRIBUNAL.fullmatch(resto) or re.fullmatch(r"\s{1,4}", resto):
            inicio = max(0, inicio - JANELA_SUBSTANTIVO) + s.start()
            if re.match(_SUBSTANTIVO, s.group(0)):
                sub_txt = s.group(0)
            else:
                classe_txt = s.group(0)
            break
    if sub_txt is None and classe_txt is None:
        # substantivo DEPOIS do tribunal ("o STJ, em acórdão de 2019 relatado pelo Ministro X";
        # revisão rodada 3, R3-05): âncora igualmente válida; o span continua a começar no tribunal
        depois = texto[janela_ini + t.end():ancora]
        s2 = RE_SUBSTANTIVO_OU_CLASSE.search(depois)
        if s2 and re.match(_SUBSTANTIVO, s2.group(0)) and not _RE_FIM_DE_FRASE.search(depois[:s2.start()]):
            sub_txt = s2.group(0)
    fim = m.end()
    if texto[inicio:fim].count("(") > texto[inicio:fim].count(")"):
        fecha = _RE_FECHA_PARENTESE.match(texto, fim)
        if fecha:
            fim = fecha.end()  # ``decisão do STJ em 2019 (Rel. Min. X)``: o ``)`` entra
    # sem substantivo nem classe antes do tribunal ("O STJ, em 2019, pela relatoria do Min. X,
    # assentou…") é prosa sobre o tribunal, não citação: força 0,4 e a resolução descarta
    # (revisão rodada 2, R4-04). O achado fica no rastro para diagnóstico.
    forca = 0.6 if (sub_txt or classe_txt) else 0.4
    a = _montar(texto, inicio, fim, sub=sub_txt, classe=classe_txt, trib=t.group(0),
                ano=m.group("ano"), nome=m.group("nome"),
                origem="regex:vaga:amplo", forca=forca)
    if a is not None:
        if forca < 0.6:
            a.dados["sem_substantivo"] = "1"
        if inverso:
            a.dados["ordem"] = "relator_antes_ano"
    return a


def detectar_amplo(texto: str) -> list[Achado]:
    """Ancorado em ``ano … relatoria Nome`` (ou ``relatoria Nome … ano``; rodada 3) com tribunal
    até 120 chars antes (força 0,6; 0,4 sem substantivo/classe)."""
    saida: list[Achado] = []
    for m in RE_VAGA_ANCORA.finditer(texto):
        a = _amplo_de(texto, m, m.start("ano"), inverso=False)
        if a is not None:
            saida.append(a)
    for m in RE_VAGA_ANCORA_INVERSA.finditer(texto):
        a = _amplo_de(texto, m, m.start("rel"), inverso=True)
        if a is not None and not any(b.inicio == a.inicio and b.fim == a.fim for b in saida):
            saida.append(a)
    return saida


def detectar(texto: str) -> list[Achado]:
    """Estrito + amplo, na ordem do texto (a fusão remove as sobreposições)."""
    achados = detectar_estrito(texto) + detectar_amplo(texto)
    achados.sort(key=lambda a: (a.inicio, -a.fim))
    log.debug("vaga: %d achados", len(achados))
    return achados


__all__ = ["RE_VAGA", "RE_VAGA_ANCORA", "detectar", "detectar_estrito", "detectar_amplo",
           "sigla_do_tribunal", "ano_canonico"]
