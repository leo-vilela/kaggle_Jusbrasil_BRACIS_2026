"""Cache determinístico das respostas do árbitro LLM (SQLite).

Chave = ``sha256(modelo | revisão | versão do prompt | assinatura do backend |
operação | entrada canônica)``. O cache guarda a **resposta bruta** do modelo
(texto) e o resultado validado (JSON), de modo que:

* uma mesma pergunta nunca é feita duas vezes ao modelo (latência e
  determinismo entre execuções);
* as respostas usadas na submissão ficam registradas para auditoria e podem ser
  exportadas (:meth:`CacheLLM.exportar_jsonl`) e reproduzidas sem GPU
  (``obter_arbitro("transformers", somente_cache=True)`` responde só do cache);
* melhorias no *parsing*/validação não exigem rodar o modelo de novo: o texto
  bruto é reparseado na leitura.

O caminho padrão vem de ``CACA_CACHE_LLM``; ``":memory:"`` cria um cache
efêmero (testes). Toda operação é tolerante a falhas de E/S (um cache quebrado
nunca derruba o documento: registra em log e segue sem cache).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator

from .. import config

logger = logging.getLogger(__name__)

VARIAVEL_AMBIENTE = "CACA_CACHE_LLM"
#: Caminho padrão (``<raiz do repositório>/cache_llm/arbitro_llm.sqlite``; ver ``config``).
CAMINHO_PADRAO = config.caminho_cache_llm()

_DDL = """
CREATE TABLE IF NOT EXISTS respostas (
    chave          TEXT PRIMARY KEY,
    modelo         TEXT NOT NULL,
    revisao        TEXT NOT NULL,
    prompt_versao  TEXT NOT NULL,
    assinatura     TEXT NOT NULL,
    operacao       TEXT NOT NULL,
    entrada        TEXT NOT NULL,
    resposta_bruta TEXT NOT NULL,
    resultado      TEXT,
    criado_em      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_respostas_operacao ON respostas (operacao);
"""


def entrada_canonica(entrada: dict[str, Any]) -> str:
    """Serialização canônica (chaves ordenadas, sem espaços, UTF-8 literal)."""
    return json.dumps(entrada, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def chave_cache(
    modelo: str,
    revisao: str,
    prompt_versao: str,
    operacao: str,
    entrada: dict[str, Any],
    assinatura: str = "",
) -> str:
    """SHA-256 hexadecimal da identidade completa da pergunta."""
    partes = [modelo, revisao, prompt_versao, assinatura, operacao, entrada_canonica(entrada)]
    h = hashlib.sha256()
    for p in partes:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")  # separador de unidade: evita colisão por concatenação
    return h.hexdigest()


NOME_ARQUIVO = "arbitro_llm.sqlite"


def _resolver_caminho(caminho: str | Path) -> str:
    """``":memory:"`` fica como está; um diretório (existente ou sem extensão, como
    ``cache_llm/`` de ``config.caminho_cache_llm``) recebe ``arbitro_llm.sqlite`` dentro."""
    if str(caminho) == ":memory:":
        return ":memory:"
    p = Path(caminho)
    if p.is_dir() or (not p.exists() and p.suffix == ""):
        p = p / NOME_ARQUIVO
    return str(p)


class CacheLLM:
    """Cache em SQLite com contadores de acerto/erro.

    Uso típico::

        cache = CacheLLM.do_ambiente()          # CACA_CACHE_LLM ou cache/arbitro_llm.sqlite
        bruto = cache.obter(chave)              # None = miss
        cache.guardar(chave, ..., resposta_bruta=texto, resultado=dicionario)
    """

    def __init__(self, caminho: str | Path = ":memory:", somente_leitura: bool = False) -> None:
        self.caminho = _resolver_caminho(caminho)
        self.somente_leitura = somente_leitura
        self.acertos = 0
        self.erros = 0
        self._conn: sqlite3.Connection | None = None
        try:
            if self.caminho != ":memory:":
                Path(self.caminho).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.caminho, check_same_thread=False)
            self._conn.executescript(_DDL)
            self._conn.commit()
        except (sqlite3.Error, OSError):
            logger.exception("cache LLM indisponível em %s; seguindo sem cache", self.caminho)
            self._conn = None

    # -- construção ---------------------------------------------------------
    @classmethod
    def do_ambiente(cls, padrao: str | Path | None = None) -> CacheLLM:
        """Cache no caminho de ``CACA_CACHE_LLM`` (ou ``padrao``/``CAMINHO_PADRAO``)."""
        # toda leitura de CACA_* passa por ``config`` (revisão R3-06)
        caminho = padrao if padrao is not None else config.caminho_cache_llm()
        return cls(caminho)

    @property
    def ativo(self) -> bool:
        return self._conn is not None

    # -- leitura / escrita --------------------------------------------------
    def obter(self, chave: str) -> str | None:
        """Resposta bruta gravada para a chave, ou ``None`` (miss)."""
        if self._conn is None:
            self.erros += 1
            return None
        try:
            cur = self._conn.execute("SELECT resposta_bruta FROM respostas WHERE chave = ?", (chave,))
            linha = cur.fetchone()
        except sqlite3.Error:
            logger.exception("falha ao ler o cache LLM")
            linha = None
        if linha is None:
            self.erros += 1
            return None
        self.acertos += 1
        return str(linha[0])

    def obter_registro(self, chave: str) -> dict[str, Any] | None:
        """Registro completo (entrada, resposta, resultado) ou ``None``."""
        if self._conn is None:
            return None
        try:
            cur = self._conn.execute(
                "SELECT modelo, revisao, prompt_versao, assinatura, operacao, entrada, "
                "resposta_bruta, resultado, criado_em FROM respostas WHERE chave = ?",
                (chave,),
            )
            linha = cur.fetchone()
        except sqlite3.Error:
            logger.exception("falha ao ler o cache LLM")
            return None
        if linha is None:
            return None
        return _linha_para_dict(chave, linha)

    def guardar(
        self,
        chave: str,
        *,
        modelo: str,
        revisao: str,
        prompt_versao: str,
        operacao: str,
        entrada: dict[str, Any],
        resposta_bruta: str,
        resultado: Any = None,
        assinatura: str = "",
    ) -> None:
        """Grava (ou substitui) a resposta bruta e o resultado validado."""
        if self._conn is None or self.somente_leitura:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO respostas (chave, modelo, revisao, prompt_versao, assinatura, "
                "operacao, entrada, resposta_bruta, resultado, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    chave, modelo, revisao, prompt_versao, assinatura, operacao,
                    entrada_canonica(entrada), resposta_bruta,
                    None if resultado is None else json.dumps(resultado, ensure_ascii=False, sort_keys=True),
                    time.time(),
                ),
            )
            self._conn.commit()
        except sqlite3.Error:
            logger.exception("falha ao gravar no cache LLM")

    def atualizar_resultado(self, chave: str, resultado: Any) -> None:
        """Atualiza só o resultado validado (quando o parsing foi refeito)."""
        if self._conn is None or self.somente_leitura:
            return
        try:
            self._conn.execute(
                "UPDATE respostas SET resultado = ? WHERE chave = ?",
                (None if resultado is None else json.dumps(resultado, ensure_ascii=False, sort_keys=True), chave),
            )
            self._conn.commit()
        except sqlite3.Error:
            logger.exception("falha ao atualizar o cache LLM")

    # -- diagnóstico / auditoria -------------------------------------------
    def __len__(self) -> int:
        if self._conn is None:
            return 0
        try:
            return int(self._conn.execute("SELECT COUNT(*) FROM respostas").fetchone()[0])
        except sqlite3.Error:
            return 0

    def estatisticas(self) -> dict[str, Any]:
        por_op: dict[str, int] = {}
        if self._conn is not None:
            try:
                for op, n in self._conn.execute("SELECT operacao, COUNT(*) FROM respostas GROUP BY operacao"):
                    por_op[str(op)] = int(n)
            except sqlite3.Error:
                pass
        return {
            "caminho": self.caminho, "ativo": self.ativo, "acertos": self.acertos,
            "erros": self.erros, "registros": len(self), "por_operacao": por_op,
        }

    def iterar(self) -> Iterator[dict[str, Any]]:
        """Todos os registros, em ordem de chave (determinística)."""
        if self._conn is None:
            return iter(())
        try:
            linhas = self._conn.execute(
                "SELECT chave, modelo, revisao, prompt_versao, assinatura, operacao, entrada, "
                "resposta_bruta, resultado, criado_em FROM respostas ORDER BY chave"
            ).fetchall()
        except sqlite3.Error:
            logger.exception("falha ao iterar o cache LLM")
            return iter(())
        return (_linha_para_dict(ln[0], ln[1:]) for ln in linhas)

    def exportar_jsonl(self, destino: str | Path) -> int:
        """Exporta o cache inteiro para JSONL (uma linha por resposta). Devolve o total."""
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with destino.open("w", encoding="utf-8") as f:
            for reg in self.iterar():
                f.write(json.dumps(reg, ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
        return n

    def importar_jsonl(self, origem: str | Path) -> int:
        """Importa registros de um JSONL exportado (reprodução sem GPU). Devolve o total."""
        n = 0
        with Path(origem).open("r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                reg = json.loads(linha)
                self.guardar(
                    reg["chave"], modelo=reg["modelo"], revisao=reg["revisao"],
                    prompt_versao=reg["prompt_versao"], operacao=reg["operacao"],
                    entrada=reg["entrada"], resposta_bruta=reg["resposta_bruta"],
                    resultado=reg.get("resultado"), assinatura=reg.get("assinatura", ""),
                )
                n += 1
        return n

    def fechar(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    def __enter__(self) -> CacheLLM:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()


def _linha_para_dict(chave: str, linha: tuple[Any, ...]) -> dict[str, Any]:
    modelo, revisao, prompt_versao, assinatura, operacao, entrada, bruta, resultado, criado = linha
    return {
        "chave": chave, "modelo": modelo, "revisao": revisao, "prompt_versao": prompt_versao,
        "assinatura": assinatura, "operacao": operacao, "entrada": json.loads(entrada),
        "resposta_bruta": bruta, "resultado": None if resultado is None else json.loads(resultado),
        "criado_em": criado,
    }


__all__ = ["CacheLLM", "chave_cache", "entrada_canonica", "VARIAVEL_AMBIENTE", "CAMINHO_PADRAO"]
