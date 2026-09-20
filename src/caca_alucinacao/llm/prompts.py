"""Prompts do árbitro LLM (português), versionados.

Cada operação tem um prompt de sistema comum (regras do desafio) e um prompt de
usuário com instruções específicas, exemplos SINTÉTICOS (nenhum trecho, número
ou nome vem do gabarito ou da base) e o pedido de JSON puro.

``PROMPT_VERSAO`` é o rótulo humano da versão; ``PROMPT_HASH`` (sha256 curto de
``SISTEMA`` + os quatro templates de usuário, calculado no import) entra no hash do
cache junto com ele, então **qualquer** mudança de texto invalida o cache
automaticamente — a versão humana deixou de ser o único guarda (revisão rodada 2,
R3b-03). ``tests/test_llm.py`` fixa o hash esperado: mudar o prompt obriga a
atualizar o teste e, por convenção, a versão.

Os esquemas JSON (``ESQUEMAS``) servem para *guided decoding* no vLLM e para
documentar a saída esperada; a validação real é feita em :mod:`.arbitro`,
que nunca confia no modelo.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

PROMPT_VERSAO = "2026-09-20.1"

# Comprimento máximo (codepoints) do contexto enviado ao modelo. A janela é
# recortada em torno do trecho para caber no orçamento de tokens (≈ 1k).
CONTEXTO_MAX = 900

OPERACOES = ("normalizar", "escolher", "classificar", "extrair")

SISTEMA = """Você é um assistente jurídico brasileiro especializado em identificar e normalizar citações de jurisprudência e de lei em pareceres e petições. Você recebe trechos curtos (às vezes com ruído de OCR, abreviações, quebras de linha) e responde SOMENTE com um objeto JSON válido, sem comentários, sem cercas de código e sem texto antes ou depois.

Regras fixas do domínio:
1. Uma citação de PROCESSO é "classe processual + número": REsp 1.234.567/SP, AgInt no AREsp 2.000.111/RJ, Rcl 45.678, RE 987.654/DF, RR-1234-56.2019.5.04.0001, APL 7000123-45.2023.7.00.0000/RS, REspe 0600123-45.2020.6.06.0001. A cadeia de classes inclui os prefixos encadeados (AgInt no, EDcl no, AgRg na, ED-E-, Terceiro AgR no) e termina na classe principal.
2. O número pode vir com pontos de milhar, espaços, quebras de linha, NBSP, hífen no lugar do ponto, sem pontuação, ou com letras trocadas por OCR: O/o→0, l/I/|→1, S/s→5, g/q→9, G→6, B→8, Z/z→2. Um dígito NUNCA vira outro dígito: você não pode alterar, remover nem inserir dígitos; só pode converter letras confundíveis em dígitos.
3. A UF é sempre duas maiúsculas no fim (/SP, - SP, (SP), –SP). A UF NUNCA sofre OCR: o S de /SP não é 5.
4. Tribunal implícito pela classe: REsp, AREsp, RHC, RMS, EREsp → STJ; RE, ARE, ADI, ADPF, Súmula Vinculante → STF; REspe, AREspEl, RO eleitoral → TSE; RR, AIRR, ARR, RRAg, prefixo TST- → TST; APL, RSE, EI → STM. Rcl, HC, MS, AR, AgInt são ambíguos (STF/STJ/STM): tribunal null, a menos que o contexto o diga. No número CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO), J=5 é TST, J=6 é TSE, J=7 é STM.
5. Outras famílias: SÚMULA (Súmula 123 do STJ, Súmula Vinculante 45, Súm. 45 do TSE), DISPOSITIVO de lei (art. 8º, IX, da Constituição Federal; art 321 do CPC; artigo 791 da CLT), TEMA (Tema 1.234 da repercussão geral) e citação VAGA (tribunal + ano + relator, sem número: "julgado do STJ proferido em 2021 pela relatoria de Fulano de Tal", "Rcl de 2022, Rel. Min. Beltrana Silva").
6. NÃO são citações (distratores): número dos autos do cabeçalho (Autos nº, Processo nº do próprio caso), protocolo, OAB, fls. 12/34, valores em R$, percentuais, datas, "Memorial nº", e frases sem identificador ("jurisprudência pacífica desta Corte", "orientação dos tribunais superiores", "verbete sumular aplicável").
7. Fronteiras de um span: começa no primeiro token da cadeia de classes (ou em Súmula/art./Tema/julgado/precedente/acórdão) e termina no último dígito, na UF, no tribunal da súmula, no nome do diploma ou na última palavra do nome do relator. Artigos anteriores (o, a, no, na, do, da) e a pontuação final ficam FORA.
Se não houver critério suficiente, responda com null nos campos incertos. Nunca invente."""

# ---------------------------------------------------------------------------
# normalizar_citacao
# ---------------------------------------------------------------------------
_NORMALIZAR_INSTRUCOES = """Tarefa: normalizar a citação de processo abaixo. Devolva um JSON com exatamente estes campos:
{"classe_cadeia": [lista de siglas canônicas na ordem, ex. ["AGINT","ARESP"]], "numero_digitos": "somente os dígitos do número, na ordem, sem pontuação (letras de OCR já convertidas)", "uf": "duas letras ou null", "tribunal": "STF|STJ|TSE|TST|STM ou null", "eh_citacao": true|false}

Siglas canônicas: RESP, ARESP, ERESP, RE, ARE, RCL, HC, RHC, RMS, MS, AR, ADI, ADPF, AGR (agravo regimental), AGINT (agravo interno), ED (embargos de declaração), EDV (embargos de divergência), RESPE, ARESPE, RO, AI, RR, AIRR, ARR, RRAG, AG, E, APL, RSE, EI, RP, RRP, SLS, AP. Ordinais viram "2O", "3O".
Lembre: converta APENAS letras confundíveis que estão DENTRO do número (coladas a dígitos); não toque nos dígitos existentes; a UF fica fora do número; o prefixo TST- e as siglas não fazem parte do número. Se o trecho não for uma citação de processo, devolva "eh_citacao": false e "numero_digitos": "".

Exemplos:
Trecho: "AgInt no RESP 1.8O5.6l2 - RS"
Resposta: {"classe_cadeia": ["AGINT","RESP"], "numero_digitos": "1805612", "uf": "RS", "tribunal": "STJ", "eh_citacao": true}
Trecho: "Rcl\\n4S.O12/SP"
Resposta: {"classe_cadeia": ["RCL"], "numero_digitos": "45012", "uf": "SP", "tribunal": null, "eh_citacao": true}
Trecho: "processo nº TST-ED-E-RR-77-l2.2013.5.09.0O11"
Resposta: {"classe_cadeia": ["ED","E","RR"], "numero_digitos": "771220135090011", "uf": null, "tribunal": "TST", "eh_citacao": true}
Trecho: "APL 700O321-9S 2022 7 00 0000 (MG)"
Resposta: {"classe_cadeia": ["APL"], "numero_digitos": "70003219520227000000", "uf": "MG", "tribunal": "STM", "eh_citacao": true}
Trecho: "fls. 1O2/1O5"
Resposta: {"classe_cadeia": [], "numero_digitos": "", "uf": null, "tribunal": null, "eh_citacao": false}
"""


def mensagens_normalizar(trecho: str, contexto: str) -> list[dict[str, str]]:
    """Mensagens (chat) para ``normalizar_citacao``."""
    usuario = (
        f"{_NORMALIZAR_INSTRUCOES}\n"
        f"Contexto (janela do documento, só para referência):\n<<<\n{contexto}\n>>>\n\n"
        f"Trecho a normalizar: {json.dumps(trecho, ensure_ascii=False)}\n"
        "Resposta (apenas o JSON):"
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


# ---------------------------------------------------------------------------
# escolher_candidato
# ---------------------------------------------------------------------------
_ESCOLHER_INSTRUCOES = """Tarefa: a citação abaixo tem o mesmo número que VÁRIOS registros da base (decisões sucessivas no mesmo processo, ou exportações diferentes). Escolha o registro a que a citação se refere, usando SOMENTE evidências presentes no trecho e no contexto: cadeia de classes (AgInt no REsp ≠ AgInt no EREsp), tribunal, ano mencionado, nome do relator, órgão julgador, tema da decisão. Se o trecho e o contexto não trazem nenhuma evidência que distinga os candidatos, devolva null: não chute.
Devolva um JSON: {"indice": <inteiro, posição do candidato na lista, começando em 0> ou null, "evidencia": "frase curta com o critério usado"}

Exemplo:
Trecho: "AgInt no REsp 1.777.888/PR"
Contexto: "... como decidiu a Segunda Turma em 2019, no AgInt no REsp 1.777.888/PR, Rel. Min. Beltrana Souza, ..."
Candidatos:
[0] tribunal=STJ ano=2018 relator=Fulano Pereira cadeia=AGINT RESP | cabeçalho: "AgInt no RECURSO ESPECIAL Nº 1.777.888 - PR (2018/0011111-2) RELATOR : MINISTRO FULANO PEREIRA ..."
[1] tribunal=STJ ano=2019 relator=Beltrana Souza cadeia=AGINT RESP | cabeçalho: "AgInt no RECURSO ESPECIAL Nº 1.777.888 - PR (2019/0022222-3) RELATORA : MINISTRA BELTRANA SOUZA ..."
Resposta: {"indice": 1, "evidencia": "o contexto menciona 2019 e a relatora Beltrana Souza, que só casam com o candidato 1"}

Exemplo sem critério:
Trecho: "RR-1234-56.2015.5.04.0001"
Contexto: "... a tese foi acolhida no RR-1234-56.2015.5.04.0001, para reformar a decisão regional."
Candidatos:
[0] tribunal=TST ano=2018 relator=Fulano Lima cadeia=RR | cabeçalho: "... Recurso de Revista nº TST-RR-1234-56.2015.5.04.0001 ..."
[1] tribunal=TST ano=2019 relator=Fulano Lima cadeia=AG RR | cabeçalho: "... Agravo em Recurso de Revista nº TST-Ag-RR-1234-56.2015.5.04.0001 ..."
Resposta: {"indice": null, "evidencia": "nem ano nem relator nem classe distinguem os candidatos"}
"""


def _formatar_candidato(i: int, c: dict[str, Any]) -> str:
    cab = str(c.get("cabecalho") or "").replace("\n", " ").strip()
    return (
        f"[{i}] tribunal={c.get('tribunal') or '?'} ano={c.get('ano') or '?'} "
        f"relator={c.get('relator') or '?'} cadeia={c.get('cadeia') or '?'} | "
        f"cabeçalho: {json.dumps(cab, ensure_ascii=False)}"
    )


def mensagens_escolher(trecho: str, contexto: str, candidatos: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Mensagens (chat) para ``escolher_candidato``."""
    lista = "\n".join(_formatar_candidato(i, c) for i, c in enumerate(candidatos))
    usuario = (
        f"{_ESCOLHER_INSTRUCOES}\n"
        f"Trecho: {json.dumps(trecho, ensure_ascii=False)}\n"
        f"Contexto:\n<<<\n{contexto}\n>>>\n"
        f"Candidatos:\n{lista}\n"
        "Resposta (apenas o JSON):"
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


# ---------------------------------------------------------------------------
# classificar_span
# ---------------------------------------------------------------------------
_CLASSIFICAR_INSTRUCOES = """Tarefa: um detector automático marcou um trecho candidato dentro da janela abaixo. Decida se ele é uma citação de jurisprudência ou de lei e, se for, copie o span EXATO (caractere a caractere, inclusive quebras de linha) com as fronteiras corretas, dentro da janela. Devolva um JSON:
{"eh_citacao": true|false, "familia": "processo|sumula|dispositivo|tema|vaga|nenhuma", "tipo": "jurisprudencia|lei", "trecho": "texto literal do span corrigido, copiado da janela (ou \\"\\" se não for citação)"}

Regras de fronteira: começa na cadeia de classes (com prefixos como AgInt no), em Súmula/Súm., em art./artigo, em Tema, ou em julgado/precedente/acórdão/nome da classe (citação vaga); termina no último dígito, na UF, em "do STJ" da súmula, no nome completo do diploma ("da Constituição Federal", "da Lei nº 13.105/2015") ou na última palavra do nome do relator. Nunca inclua o artigo anterior (o, a, no, na, do, da) nem vírgula/ponto final. "familia" = dispositivo implica "tipo" = lei; as demais são jurisprudencia. Não é citação: número dos autos do cabeçalho, protocolo, OAB, fls., R$, datas, percentuais, e frases sem identificador (sem número e sem relator+ano).

Exemplos:
Janela: "Nesse sentido, a orientação dos tribunais superiores é firme no ponto, como se vê no A.REsp n° 2.111.333 (PE), que afastou a tese."
Candidato: "n° 2.111.333 (PE)"
Resposta: {"eh_citacao": true, "familia": "processo", "tipo": "jurisprudencia", "trecho": "A.REsp n° 2.111.333 (PE)"}
Janela: "conforme consta às fls. 45/52 dos autos, o valor da causa foi fixado em R$ 12.500,00, e a"
Candidato: "fls. 45/52"
Resposta: {"eh_citacao": false, "familia": "nenhuma", "tipo": "jurisprudencia", "trecho": ""}
Janela: "Ampara a pretensão o julgado do TSE proferido em 2020 pela relatoria de\\nSICRANA DE OLIVEIRA, para o qual"
Candidato: "2020 pela relatoria de\\nSICRANA"
Resposta: {"eh_citacao": true, "familia": "vaga", "tipo": "jurisprudencia", "trecho": "julgado do TSE proferido em 2020 pela relatoria de\\nSICRANA DE OLIVEIRA"}
Janela: "viola o art 9O5, I, do Código de Defesa\\ndo Consumidor, razão pela qual"
Candidato: "art 9O5, I, do Código"
Resposta: {"eh_citacao": true, "familia": "dispositivo", "tipo": "lei", "trecho": "art 9O5, I, do Código de Defesa\\ndo Consumidor"}
Janela: "a jurisprudência pacífica desta Corte, firmada em 2019, não socorre o recorrente"
Candidato: "jurisprudência pacífica desta Corte, firmada em 2019"
Resposta: {"eh_citacao": false, "familia": "nenhuma", "tipo": "jurisprudencia", "trecho": ""}
"""


def mensagens_classificar(trecho: str, contexto: str) -> list[dict[str, str]]:
    """Mensagens (chat) para ``classificar_span``."""
    usuario = (
        f"{_CLASSIFICAR_INSTRUCOES}\n"
        f"Janela: {json.dumps(contexto, ensure_ascii=False)}\n"
        f"Candidato: {json.dumps(trecho, ensure_ascii=False)}\n"
        "Resposta (apenas o JSON):"
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


# ---------------------------------------------------------------------------
# extrair_citacoes (extrator de segundo estágio — padrão ouro: o modelo só aponta
# onde olhar; número, classe, UF, artigo, diploma, ano e relator têm de estar
# literalmente no span, e a classe (real/inventada/incompleta) vem da base)
# ---------------------------------------------------------------------------
_EXTRAIR_INSTRUCOES = """Tarefa: um detector automático já marcou as citações mais comuns da janela abaixo (lista "já detectadas", com offsets relativos à janela). Encontre citações de jurisprudência ou de lei que ele NÃO marcou — formas incomuns, abreviações, palavras quebradas por hífen ou espaço, OCR na palavra (Sún1ula, RE5p, Re curso), número escrito depois de "de número", classe e número colados, citações vagas com órgão julgador. Toda citação de processo precisa de uma classe processual reconhecível (REsp, Rcl, RE, HC, RR…); "acórdão nº" ou "processo nº" sem classe não entram. Não repita nem estenda as já detectadas. Não marque: número dos autos do cabeçalho, protocolo, OAB, fls., R$, datas, percentuais, "jurisprudência pacífica", "esta Corte", leis citadas sem artigo.
Devolva um JSON: {"citacoes": [ {"trecho": "texto EXATO copiado da janela (caractere a caractere, inclusive quebras)", "familia": "processo|sumula|dispositivo|tema|vaga", "classe_cadeia": [siglas canônicas, só para processo], "numero_digitos": "dígitos do número na ordem, letras de OCR convertidas (processo)", "uf": "duas letras ou null", "tribunal": "STF|STJ|TSE|TST|STM ou null", "numero_sumula": "dígitos ou null", "vinculante": true|false, "artigo": "número do artigo ou null", "diploma": "nome do diploma como está no trecho ou null", "ano": "AAAA ou null", "relator": "nome do relator como está no trecho ou null"} ] }
Sem nada novo: {"citacoes": []}. Fronteiras: começa na classe/Súmula/art./Tema/julgado/acórdão e termina no último dígito, na UF, no tribunal, no diploma ou no nome do relator; artigo anterior (o, a, no, na, do, da) e pontuação final ficam fora. Cada número, UF, artigo, diploma, ano e nome que você devolver TEM de aparecer literalmente no trecho; nunca complete de memória.

Exemplos:
Janela: "como se vê no REsp1.234.567/SP, que afastou a tese, e na Súmula 7 do STJ."
Já detectadas: [{"inicio": 55, "fim": 71, "trecho": "Súmula 7 do STJ"}]
Resposta: {"citacoes": [{"trecho": "REsp1.234.567/SP", "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "1234567", "uf": "SP", "tribunal": "STJ", "numero_sumula": null, "vinculante": false, "artigo": null, "diploma": null, "ano": null, "relator": null}]}
Janela: "conforme decidido no julgamento do recurso especial de número 2.OO0.111, oriundo do Paraná, e na Recla-\nmação 45.678/SP"
Já detectadas: []
Resposta: {"citacoes": [{"trecho": "recurso especial de número 2.OO0.111", "familia": "processo", "classe_cadeia": ["RESP"], "numero_digitos": "2000111", "uf": null, "tribunal": "STJ", "numero_sumula": null, "vinculante": false, "artigo": null, "diploma": null, "ano": null, "relator": null}, {"trecho": "Recla-\nmação 45.678/SP", "familia": "processo", "classe_cadeia": ["RCL"], "numero_digitos": "45678", "uf": "SP", "tribunal": null, "numero_sumula": null, "vinculante": false, "artigo": null, "diploma": null, "ano": null, "relator": null}]}
Janela: "Aplica-se a Sún1ula 4l2 do TST e o art. 8O2 do Código Civil, conforme julgado pela 3ª Turma do STJ em 2020, relatoria da Ministra Beltrana Souza."
Já detectadas: []
Resposta: {"citacoes": [{"trecho": "Sún1ula 4l2 do TST", "familia": "sumula", "classe_cadeia": [], "numero_digitos": null, "uf": null, "tribunal": "TST", "numero_sumula": "412", "vinculante": false, "artigo": null, "diploma": null, "ano": null, "relator": null}, {"trecho": "art. 8O2 do Código Civil", "familia": "dispositivo", "classe_cadeia": [], "numero_digitos": null, "uf": null, "tribunal": null, "numero_sumula": null, "vinculante": false, "artigo": "802", "diploma": "Código Civil", "ano": null, "relator": null}, {"trecho": "julgado pela 3ª Turma do STJ em 2020, relatoria da Ministra Beltrana Souza", "familia": "vaga", "classe_cadeia": [], "numero_digitos": null, "uf": null, "tribunal": "STJ", "numero_sumula": null, "vinculante": false, "artigo": null, "diploma": null, "ano": "2020", "relator": "Beltrana Souza"}]}
Janela: "conforme consta às fls. 45/52 dos autos, a jurisprudência pacífica desta Corte não socorre o recorrente (Processo nº 0001234-56.2020.8.26.0100)."
Já detectadas: []
Resposta: {"citacoes": []}
"""


def mensagens_extrair(contexto: str, ja_detectadas: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Mensagens (chat) para ``extrair_citacoes``."""
    usuario = (
        f"{_EXTRAIR_INSTRUCOES}\n"
        f"Janela: {json.dumps(contexto, ensure_ascii=False)}\n"
        f"Já detectadas: {json.dumps(ja_detectadas, ensure_ascii=False)}\n"
        "Resposta (apenas o JSON):"
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]


# ---------------------------------------------------------------------------
# Esquemas JSON (guided decoding no vLLM; documentação da saída)
# ---------------------------------------------------------------------------
ESQUEMAS: dict[str, dict[str, Any]] = {
    "normalizar": {
        "type": "object",
        "properties": {
            "classe_cadeia": {"type": "array", "items": {"type": "string"}},
            "numero_digitos": {"type": "string"},
            "uf": {"type": ["string", "null"]},
            "tribunal": {"type": ["string", "null"]},
            "eh_citacao": {"type": "boolean"},
        },
        "required": ["classe_cadeia", "numero_digitos", "uf", "tribunal", "eh_citacao"],
    },
    "escolher": {
        "type": "object",
        "properties": {
            "indice": {"type": ["integer", "null"]},
            "evidencia": {"type": "string"},
        },
        "required": ["indice"],
    },
    "classificar": {
        "type": "object",
        "properties": {
            "eh_citacao": {"type": "boolean"},
            "familia": {"type": "string",
                        "enum": ["processo", "sumula", "dispositivo", "tema", "vaga", "nenhuma"]},
            "tipo": {"type": "string", "enum": ["jurisprudencia", "lei"]},
            "trecho": {"type": "string"},
        },
        "required": ["eh_citacao", "familia", "tipo", "trecho"],
    },
    "extrair": {
        "type": "object",
        "properties": {
            "citacoes": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "trecho": {"type": "string"},
                        "familia": {"type": "string", "enum": ["processo", "sumula", "dispositivo", "tema", "vaga"]},
                        "classe_cadeia": {"type": "array", "items": {"type": "string"}},
                        "numero_digitos": {"type": ["string", "null"]},
                        "uf": {"type": ["string", "null"]},
                        "tribunal": {"type": ["string", "null"]},
                        "numero_sumula": {"type": ["string", "null"]},
                        "vinculante": {"type": "boolean"},
                        "artigo": {"type": ["string", "null"]},
                        "diploma": {"type": ["string", "null"]},
                        "ano": {"type": ["string", "null"]},
                        "relator": {"type": ["string", "null"]},
                    },
                    "required": ["trecho", "familia"],
                },
            },
        },
        "required": ["citacoes"],
    },
}

# Orçamento de geração por operação (tokens novos). Pequeno de propósito: a
# resposta é um JSON curto e o custo de decodificação domina a latência.
MAX_TOKENS_NOVOS: dict[str, int] = {"normalizar": 96, "escolher": 64, "classificar": 160, "extrair": 480}


def _hash_dos_prompts() -> str:
    """sha256 curto de todo o texto que o modelo vê (sistema + instruções das 3 operações)."""
    h = hashlib.sha256()
    for parte in (SISTEMA, _NORMALIZAR_INSTRUCOES, _ESCOLHER_INSTRUCOES, _CLASSIFICAR_INSTRUCOES, _EXTRAIR_INSTRUCOES):
        h.update(parte.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


#: Identidade efetiva do prompt na chave do cache: rótulo humano + hash do texto.
PROMPT_HASH = _hash_dos_prompts()
PROMPT_ID = f"{PROMPT_VERSAO}+{PROMPT_HASH}"


def recortar_contexto(contexto: str, trecho: str, maximo: int = CONTEXTO_MAX) -> str:
    """Recorta ``contexto`` a ``maximo`` codepoints mantendo ``trecho`` no centro.

    Se o trecho não estiver no contexto, corta simplesmente o início. Nunca
    lança exceção. Idempotente quando o contexto já cabe.
    """
    if len(contexto) <= maximo:
        return contexto
    pos = contexto.find(trecho) if trecho else -1
    if pos < 0:
        return contexto[:maximo]
    folga = max(0, (maximo - len(trecho)) // 2)
    ini = max(0, pos - folga)
    fim = min(len(contexto), ini + maximo)
    ini = max(0, fim - maximo)
    return contexto[ini:fim]


__all__ = [
    "PROMPT_VERSAO", "PROMPT_HASH", "PROMPT_ID", "CONTEXTO_MAX", "OPERACOES", "SISTEMA", "ESQUEMAS", "MAX_TOKENS_NOVOS",
    "mensagens_normalizar", "mensagens_escolher", "mensagens_classificar", "mensagens_extrair", "recortar_contexto",
]
