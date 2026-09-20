# ADR 0002 — Contrato de saída, pipeline, avaliação local e empacotamento

Data: 16/09/2026. Estado: aceita. Escopo: `contrato.py`, `pipeline.py`, `cli.py`, `config.py`,
`scripts/avaliar.py`, `scripts/gerar_submissao.py`, `scripts/preparar_dados.py`, `Makefile`,
`Dockerfile*`.

## Contexto

O desafio pontua com `kaggle_metric.py` sobre um `submission.csv` gerado por
`json_to_submission.py` a partir de um JSON por documento (schema 1.2). Erros de formato são
fatais para a submissão inteira (sobreposição de spans, `real` sem id numérico, documento sem
linha). Os módulos de detecção/resolução/calibração são desenvolvidos em paralelo e ainda não
existem; o contrato e a avaliação precisam ficar prontos antes deles e não podem depender deles.

## Decisões

1. **`id_canonico` é emitido como string de dígitos** (o exemplo oficial usa string; conversor e
   métrica aceitam string ou inteiro e normalizam zeros à esquerda). `Citacao` converte `int`
   automaticamente; `validar()` exige `str.isdigit()`.
2. **`validar()` é mais estrito que a métrica**: além do que ela rejeita (enum, `inicio < fim`,
   `real` sem id, IoU ≥ 0,5, confiança fora de [0, 1]) confere `schema_version`, campos exatos
   (sem chaves extras), `trecho == texto[inicio:fim]`, `resolucao == null` fora de `real`,
   `resolucao.fonte == "jusbrasil"` e ids únicos. Motivo: o validador local da organização
   ("conferido pelo validador local", docstring do conversor) pode checar `trecho`/`tipo`.
3. **`confianca` sempre presente** na saída do pipeline (nunca `null`), com teto/piso definidos
   pela calibração; `null` continua aceito pelo validador porque a métrica aceita "-".
4. **Exceção numa citação ⇒ citação omitida** (não `incompleta`). Custo esperado: omitir custa
   ≤ 1 FN; emitir `incompleta` às cegas custa TP só se o gabarito for `incompleta` (~17 % das
   citações), senão 1 FN + 1 FP, e 1 FP se o span for espúrio. Esperança: 1,0 vs ≈ 1,7. Além
   disso, omitir nunca gera erro fatal. A calibração falhar não omite: usa a confiança padrão 0,5.
5. **Exceção no detector ⇒ documento sem citações; exceção no documento ⇒ JSON vazio.** A
   submissão exige uma linha por documento; um JSON vazio vale 0 nesse documento, uma linha ausente
   invalida tudo.
6. **Sobreposição entre achados (IoU ≥ 0,5)** — não deveria ocorrer (`deteccao.fusao`), mas o
   pipeline é a última barreira: fica o de maior `forca`, desempate pelo span mais longo, depois o
   mais à esquerda; o descarte vai para o log e para o rastro.
7. **Texto lido com `read_bytes().decode("utf-8")`**, nunca `read_text()`: o modo texto traduz
   `\r\n` → `\n` e deslocaria offsets. Não forçamos NFC (os dados são NFC; se não fossem, os offsets
   do avaliador seguiriam o arquivo original) — só avisamos.
8. **Injeção de dependência + imports tardios.** `processar_texto(..., detector=, resolvedor=,
   calibrador=, arbitro=)`; sem argumento, importa `deteccao.detectar`, `resolucao.resolver`,
   `calibracao.confianca`. O árbitro é repassado ao resolvedor como `arbitro=` **somente se a
   assinatura o aceitar** (`inspect.signature`), senão é ignorado com aviso. `cli.py` cria o
   árbitro via `llm.obter_arbitro(nome)` (o backend lê `CACA_CACHE_LLM`, `CACA_MODELO`, `CACA_MODELO_REVISAO` do ambiente).
9. **Rastro** (`--rastro rastro.jsonl`): uma linha por achado com `caminho`, `candidatos`,
   `confianca`, `status`. É a ponte para `calibracao.ajustar` (acurácia por caminho) e para o
   diagnóstico de `scripts/avaliar.py --rastro`.
10. **Avaliação = script oficial importado por caminho** (`importlib`, com cache para que
    `ParticipantVisibleError` seja uma única classe). A `solution` é construída do
    `goldenset.csv` (`utf-8-sig`, `\n` literal desescapado) no formato
    `inicio,fim,classe,doc_ids|…`; a `submission` usa `encode()` do conversor oficial. O
    diagnóstico reimplementa o alinhamento (guloso por maior IoU, desempate por índices, regra
    EXTRA ≥ 90 %) e é conferido contra o oficial (macro-F1 e τ idênticos) nos testes. Documento sem
    JSON é preenchido com `-` e avisado (o oficial rejeitaria); `--estrito` reproduz a rejeição.
11. **Imagem Docker sem dados nem índice**: o índice é construído do banco montado em ~0,2 s. A
    única coisa que viaja além do código é `dados/calibracao.json` (artefato nosso, versionado).
    `PYTHONHASHSEED=0`, usuário não-root, `ENTRYPOINT` no CLI com `CMD` padrão igual ao comando da
    organização.
12. **`preparar_dados.py` só avisa** em divergência de SHA-256 (a organização já redistribuiu os
    dados duas vezes); `--estrito` transforma em erro.

## Consequências

- Qualquer módulo novo que devolva `Achado`/`Decisao` conforme `tipos.py` entra sem alteração no
  pipeline; o que ele quebrar aparece no log e no rastro, nunca na submissão.
- A pontuação local é a do Kaggle no dev set (referencial); o ranking real é no conjunto cego.
- Pendente para a integração: nomes exatos `deteccao.detectar`, `resolucao.resolver`,
  `calibracao.confianca`, `llm.obter_arbitro`; formato de `dados/calibracao.json`
  (`{caminho: confiança}` ou `{"tabela": {...}}`); `scripts/gerar_sinteticos.py` e
  `scripts/treinar_calibracao.py` (alvos `sinteticos`/`calibrar` do Makefile já apontam para eles).
