# ADR 0001 — Normalização de superfície: implementação única em `normalizacao.py`

Data: 16/09/2026. Estado: aceita. Escopo: `src/caca_alucinacao/normalizacao.py`,
`base_canonica/digitos.py`, `base_canonica/classes.py` (re-exports), `tests/test_normalizacao.py`.

## Contexto

O índice de números próprios (`base_canonica`) já nasceu com dois protótipos validados
(`digitos.py`, `classes.py`; cobertura 96/96 no gabarito), e o detector, o árbitro LLM e os
sintéticos precisam das mesmas funções. Duas implementações de "dígitos canônicos" ou de "cadeia
de classes" divergiriam cedo ou tarde — e o custo é exatamente o erro caro do desafio: um número
do cabeçalho do acórdão e o mesmo número citado com ruído de OCR gerando chaves diferentes
(`real` → `inventada`, FN + FP) ou iguais quando não deveriam (`inventada` → `real`, penalidade τ).

## Decisões

1. **Uma implementação, dois pontos de importação.** Todo o código dos protótipos foi movido
   para `normalizacao.py`; `base_canonica/digitos.py` e `classes.py` viram re-exports puros
   (teste garante que não há `def` neles e que os objetos são os mesmos). As siglas canônicas
   (`ED`, `AGR`, `AGINT`, `RESP`, `ARESP`, `RESPE`…) e `classificar_digitos` **não mudaram**:
   o índice reconstruído é byte a byte igual a `dados/indice.json`.
2. **Dois vocabulários de formato, documentados.** O índice (JSON v1, `estatisticas`,
   `scripts/construir_indice.py`) usa `cnj | sequencial | registro | outro` (constantes
   `FORMATO_*`, devolvidas por `classificar_digitos` e em `Nucleo.formato`). O `Achado`
   (`tipos.py`) usa `cnj20 | curto | registro | outro`, devolvido por `formato_de(digitos)`;
   `FORMATO_ACHADO` converte um no outro. `curto` = qualquer sequencial (na prática 4–7 dígitos).
3. **CNJ é sempre 20 dígitos zero-padded** (`00012345620115020251`), também para o TST cujo
   sequencial pode ter 1–7 dígitos. O repositório público de referência grava 17 dígitos; a nossa
   chave é a do índice. `processo nº` e `TST-…-` nunca entram nos dígitos (não têm dígito).
4. **Núcleo numérico abre só em dígito ASCII.** Letras confundíveis (`O l I | S s g q G B Z z`)
   só viram dígito dentro de um núcleo já aberto por dígito e nunca com maioria de letras num
   grupo. Um núcleo com < 4 dígitos colado a uma letra é descartado (`DO5`, `5alvador`,
   `C0NTROVÉRSIA` não são números; `Nº42` e `art.5` são). Um dígito nunca vira outro dígito.
5. **UF antes do OCR, com guarda de dígito.** `separar_uf` só age no fim do trecho, só para as
   27 siglas, com os separadores medidos (`/`, `/ `, `-`, ` - `, ` – `, ` (…)`, `\n- `, espaço)
   e só se o restante contém dígito — assim `AgRg no MS`/`AgR-RO` não perdem a classe (`MS`,
   `RO`, `RR`, `AC`, `AP` são classe e UF). A busca é feita só na cauda (32 chars) com
   quantificadores limitados: O(1) por chamada, sem regex catastrófico.
6. **`cadeia_de_classes` ignora siglas de UF depois de um token numérico** e reconhece ordinais
   numéricos (`2º AgRg` → `2O AGR`). Para citações completas, `cadeia_da_citacao` (separa a UF
   antes) e `classe_processual_canonica` (classe principal) são a porta de entrada.
7. **`nucleo_principal` = primeiro núcleo com ≥ 4 dígitos** (antes: o mais longo). Motivo:
   docs/04 h.4 — numa citação com número e registro do STJ (`REsp 1.234.567 - PR
   (2019/0123456-7)`) a chave preferida é o número. Sem núcleo de 4 dígitos, o mais longo.
8. **`inferir_tribunal`: CNJ decide antes da classe.** Segmento J 5/6/7 → TST/TSE/STM (vence a
   classe: há `AREsp` e `RHC` com CNJ `.6.` no TSE). Sem CNJ, só classes exclusivas de um
   tribunal **na base e em docs/04 h.2**: `RESP/ARESP/ERESP/EARESP/RHC` → STJ; `RE/ARE/ADI/ADPF/ADC`
   → STF; `RESPE/ARESPE/RO/AI/…` → TSE; `RR/AIRR/ARR/RRAG/ROT` → TST; `APL/RSE/EI/RDI/CJ/CP` →
   STM. `Rcl`, `HC`, `MS`, `AR`, `AP`, `PET`, `RMS` (há um RMS do STF na base) e os prefixos
   (`AgInt`, `ED`) → `None`. STF/STJ nunca por CNJ. `uf` não decide (reservado).
9. **`tolerante`**: comparação palavra a palavra (mesmo número de palavras), sem acento e caixa,
   `rn` ≡ `m`, até `max_erros` edições por palavra com ≥ 5 letras; palavras curtas exigem
   igualdade. Contenção de sobrenomes continua em `consulta.relator_compativel`.
10. **`numeros_do_texto(texto) -> list[str]`** (docs/02) é uma projeção sem repetição de
    `numeros_com_posicao` (a função dos protótipos, que `base_canonica.digitos.numeros_do_texto`
    continua a re-exportar com esse nome porque os scripts de análise dependem das posições).
    Ambas são conservadoras (sem OCR): servem para indexar/medir, não para resolver citações.
11. Normativos (`diploma_canonico`, `artigo_canonico`, `sumula_canonica`) ficam em
    `base_canonica/normativos.py`; `normalizacao` expõe aliases com import tardio (evita ciclo).

## Revisão da rodada 1 (16/09)

- `nucleos` devolve um **núcleo ambíguo** (`Nucleo.ambiguo`, `digitos == ""`) quando um grupo
  do número tem maioria de letras confundíveis, quando um segmento só de letras (≤ 3) fica entre
  grupos numéricos, ou quando letras confundíveis estão coladas no lugar do primeiro dígito
  (precedidas de branco/conector). Antes, o núcleo era fechado e outro aberto no dígito seguinte,
  o que produzia **chaves parciais** (`1.GO1.157` → `1157`) na faixa dos sequenciais do STF/STJ —
  um mecanismo de `inventada → real` (revisão R2-01). A conversão relaxada fica na resolução
  (`chaves_alternativas`), nunca aqui: o índice da base é construído a partir dos cabeçalhos por
  regex própria e não muda.
- `tolerante` admite uma troca do mapa de confusões em palavras de 3–4 letras (`Lcis`=`Leis`).
- `cadeia_de_classes` desfaz uma confusão de OCR numa sigla desconhecida (`aglnt` → `agint`,
  `re5p` → `resp`).
- Os aliases `diploma_canonico`/`artigo_canonico`/`sumula_canonica` saíram deste módulo:
  `base_canonica.normativos` importa `normalizacao`, nunca o inverso.

## Revisão da rodada 2 (17/09)

- `nucleos`: um grupo **final** só de letras confundíveis (≤ 4) colado ao grupo anterior por um
  sinal de pontuação (`1.140.OSl`, `.OlOO` do CNJ) torna o núcleo ambíguo (`digitos == ""`) em
  vez de fechá-lo antes — fechar produzia a chave parcial `1140` (R4-01 crítica). Grupos do
  meio já eram tratados assim; a regex do detector foi alinhada (1–3 letras no meio, 1–4 no
  fim, nunca depois de branco, nunca uma UF). O índice reconstruído do SQLite continua
  byte a byte igual a `dados/indice.json`.
- `cadeia_de_classes`: casamento **tolerante** de aliases com ≥ 6 letras (`tolerante()`: uma
  edição por palavra ≥ 5 letras, confusão conhecida em 3–4) quando a chave exata falha
  (`Recurso Espccial` → `RESP`, `Rcclamação` → `RCL`; R4-08), com pré-filtro pela inicial e
  cache; ambiguidade entre cadeias distintas → nenhum casamento. Plural colado à sigla
  (`REsps`, `HCs`) é descartado. Aliases novos para classes de 2º grau (`APC`, `AGPET`, `RI`,
  `REMNEC`) e `emb infr` → `EI`. Índice inalterado.

## Consequências

- Detecção, índice, consulta, árbitro e sintéticos chamam as mesmas funções; um caso novo de
  ruído é corrigido num só lugar e coberto por `tests/test_normalizacao.py` (38 testes, sintéticos).
- `base_canonica.digitos.formato_de` passou a devolver o vocabulário do `Achado` (ninguém a usava).
- Desempenho: qualquer função em < 50 ms para 5.000 chars patológicos (testado), sem `print`.

## Quando revisitar

- Se o conjunto cego trouxer OCR **antes** do primeiro dígito (`l.234.567`): hoje o núcleo abre
  no `2` (regra 4); seria preciso permitir letra inicial quando seguida de ≥ 3 dígitos e pontuação
  de milhar — medir antes, porque `AI1234`/`MS1234` (sigla colada) virariam `11234`/`51234`.
- Se aparecer classe nova como principal (`AGINT`/`ED` fora do STM, `RMS` no STF citado) ou
  colisão de número entre tribunais na base: rever `_TRIBUNAL_POR_CLASSE` (regra 8).
- Se o índice mudar de versão (novas siglas ou formato), atualizar `FORMATO_ACHADO`/aliases aqui
  e reconstruir `dados/indice.json` no mesmo commit.
