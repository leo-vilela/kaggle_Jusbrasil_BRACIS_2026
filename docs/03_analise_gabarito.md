# Análise do gabarito de desenvolvimento — especificação para o detector de spans

Data: 16/09/2026. Fonte: `dados/goldenset.csv` (192 citações, 26 documentos), `dados/txt/*.txt`
e `dados/desafio1_bracis.db`. Todos os números deste documento são gerados por
`scripts/analise/catalogar_gabarito.py --resumo`, que também escreve
`dados/catalogo_gabarito.json` (uma entrada por citação, com todos os campos inferidos).
Os exemplos abaixo são **sintéticos**: preservam o padrão, mas nenhum número, nome ou trecho é o
do gabarito (os dados do desafio não podem ser redistribuídos).

Convenções: N1 = nível 1 (formato padrão, peso 1×); N2 = nível 2 (ruído de OCR/abreviação/pontuação/
quebra de linha, peso 2×). "Span" = `texto[inicio:fim]` em codepoints, fim exclusivo. Todos os 192
spans conferem com `trecho` (0 divergências).

## 0. Visão geral

| | N1 | N2 | total |
|---|---|---|---|
| real | 52 | 44 | 96 |
| inventada | 32 | 32 | 64 |
| incompleta | 15 | 17 | 32 |
| **total** | **99** | **93** | **192** |

Por tipo: 164 `jurisprudencia`, 28 `lei`. Por família (inferida pelo script):

| família | N1 | N2 | total | classes |
|---|---|---|---|---|
| `processo` (classe + número) | 64 | 55 | 119 | 77 real, 42 inventada |
| `vaga` (tribunal + ano + relator, sem número) | 15 | 17 | 32 | 32 incompleta |
| `dispositivo` (art. + diploma) | 14 | 14 | 28 | 14 real, 14 inventada |
| `sumula` | 6 | 6 | 12 | 5 real, 7 inventada |
| `tema` (repercussão geral) | 0 | 1 | 1 | 1 inventada |

Fatos estruturais que condicionam tudo o mais:

1. **Toda `incompleta` é da família `vaga`** e toda `vaga` é `incompleta` (32/32). Nenhuma
   citação com número é `incompleta`.
2. **Toda `real` da família `processo` (77/77) tem dígitos idênticos ao número próprio do
   registro apontado** (após a normalização de OCR). O número próprio está no cabeçalho do
   registro (STJ: offsets 19–76; STF: 48–56; STM: 47–111; TSE: 65–123) ou, no TST, na fórmula
   "autos de … nº TST-…" (offsets 1.017–4.309).
3. **Nenhuma `inventada` da família `processo` (0/42) tem número que seja número próprio de
   algum registro.** Só 1/42 aparece em algum lugar da base — citada no corpo de 2 acórdãos, a
   partir do offset 48.212 — o que confirma a armadilha documentada: "quem cita o número" não é
   "quem é o processo".
4. Os 5 registros de súmula e os 13 registros de dispositivo da base são **todos** citados como
   `real` pelo menos uma vez; toda súmula/dispositivo `inventada` está fora dessas 18 chaves.
5. Não há dois spans a menos de 68 caracteres um do outro; não há spans aninhados nem
   sobrepostos; não há número repetido dentro do mesmo documento.

## 1. Convenção de fronteira do span, por família (item a)

Regras válidas para as 192 citações (com as exceções indicadas):

**Regra geral.** O caractere anterior ao span é sempre um espaço (188) ou quebra de linha (4); a
palavra anterior é sempre um artigo/contração — `o` (86), `a` (32), `no` (32), `na` (21), `do`
(13), `da` (5), `os` (3) — e **nunca entra no span**. O caractere seguinte é sempre `,` (121),
`.` (51), espaço (18) ou `\n` (2); **pontuação final nunca entra**. Quando o que segue é
espaço/quebra, a próxima palavra é minúscula: `foi` (13), `para` (4), `afastou` (2).

### `processo` — do primeiro token da cadeia de classes até o último dígito ou até a UF

`[processo nº] [TST-] <prefixos encadeados> <classe> [conector] <número> [sep UF]`

Entra no span:
- **Prefixos encadeados completos**, inclusive ordinais: `AgInt no`, `EDcl nos EDcl no AgInt no`,
  `Terceiro AG.REG na`, `ED no AgR no`, `ED-E-ED-` (TST/TSE com hífen). 42/119 têm ≥ 1 prefixo
  (1 prefixo: 25; 2: 11; 3: 6).
- A palavra **`processo nº`/`Processo n°`** quando precede um número TST (4 casos, todos com
  `TST-`), ex.: `processo nº TST-E-RR-999-12.2011.5.15.0099`. Fora desse caso a palavra
  "processo" nunca inicia span.
- O prefixo de tribunal **`TST-`** (7 casos; inclusive com espaço depois do hífen, `TST- ED - E-ED-RR-…`).
- O **conector de número** (`nº`, `n.`, `n°`, `Nº`, `No`) e todo o espaço em branco até o número
  (espaço, espaço duplo, NBSP `\xa0`, quebra de linha).
- O número inteiro, com toda a sua pontuação interna, espaços e quebras de linha.
- A **UF com o separador** (`/SP`, `/ SP`, `-SP`, ` - SP`, ` – SP`, ` (SP)`, `\n- SP`), inclusive o
  parêntese de fechamento. 97/119 têm UF; os 22 sem UF são todos CNJ de TST/TSE ou CNJ do STM
  escrito sem pontuação.

Fica de fora: o artigo anterior (`o`, `a`, `no`, `na`), a pontuação seguinte, e qualquer palavra
após a UF. Não há "sobra" depois do número em nenhuma das 119 citações.

Exceções/armadilhas: (i) uma cadeia que começa por sigla mas é seguida de `de <ano>, Rel. Min.`
é `vaga` (5 casos), não `processo`; (ii) o CNJ do cabeçalho (`Autos nº`, `Processo nº`) é
distrator, não citação.

### `sumula` — de `Súmula` até o número ou até o tribunal

`Súmula [Vinculante] <número> [do <STJ|STF|TST|TSE>]`. O **`do STJ` entra no span** sempre que
presente (9/12), inclusive com quebra de linha antes (`999\ndo STF`) ou dentro (`do\nSTF`).
`Vinculante` (3/12) nunca vem com tribunal. A palavra-chave pode vir com OCR (`S`→`5` na inicial), em caixa
alta (`SÚMULA`) ou abreviada (`Súm.`).

### `tema` — de `Tema` até o fim do complemento

`Tema <número> da repercussão geral` — o complemento **`da repercussão geral` entra no span**
(1 caso; palavra-chave com OCR `a`→`ã`).

### `dispositivo` — de `art.` até o fim do nome do diploma

`art.|art|artigo <número>[º][, <inciso>][, <alínea>][, § …] d[ao] <diploma>`. O **diploma entra por
inteiro**, inclusive número e ano de lei: `da Lei nº 13.105/2015`, `da Lei Complementar nº 64/1990`,
`da Consolidação das Leis do Trabalho`, `do Código de Processo Penal`, `da Constituição da
República`. Incisos e alíneas entre o artigo e o diploma entram (7/28). Quebras de linha
aparecem dentro do diploma (6) e entre `art.` e o número (1). Nunca há vírgula/ponto final no
span. Exemplo sintético: `art. 999, IV, 'c', da Lei Complementar nº 64/1990`.

### `vaga` — do substantivo/classe até a última palavra do nome do relator

Começa em `julgado`, `precedente`, `acórdão` ou no nome da classe (`Reclamação`, `Rcl`, `APL`,
`Agravo em Recurso Especial`, `Recurso em Habeas Corpus`) e **termina na última palavra do nome do
relator** (2–4 palavras; caixa alta em 12/32; quebra de linha dentro do nome em 4/32). O artigo
anterior (`o`, `a`, `no`, `na`) fica fora; a vírgula/ponto seguinte fica fora; em 3 casos o nome é
seguido diretamente por ` para`/`\npara`/` foi`.

## 2. Inventário de formas de superfície (item b)

### 2.1 Classes processuais (família `processo`, 119)

Classe principal (último elemento da cadeia), forma de superfície → canônica, com contagens.

| canônica | superfície | N1 | N2 | classificações |
|---|---|---|---|---|
| REsp | `REsp` | 11 | 1 | 25 real / 3 inv (total 28) |
| REsp | `Recurso Especial` | 3 | 4 | |
| REsp | `RESP` | – | 4 | |
| REsp | `Rec. Esp.` | – | 4 | |
| REsp | `R.Esp.` | – | 1 | |
| Rcl | `Rcl` | 13 | 1 | 3 real / 26 inv (total 29) |
| Rcl | `Reclamação` | 5 | 5 | |
| Rcl | `RCL` | – | 3 | |
| Rcl | `Recl.` | – | 2 | |
| AREsp | `AREsp` | 3 | – | 10 real / 4 inv (total 14) |
| AREsp | `Agravo em Recurso Especial` | 3 | 1 | |
| AREsp | `ARESP` | – | 4 | |
| AREsp | `AgREsp` | – | 2 | |
| AREsp | `A.REsp` | – | 1 | |
| RR (TST) | `RR` | 4 | 3 | 7 real |
| RHC | `RHC` | 4 | – | 3 real / 3 inv |
| RHC | `Recurso em Habeas Corpus` | 1 | 1 | |
| REspe (TSE) | `REspe`, `Recurso Especial Eleitoral`, `REspe.`, `RESPE` | 3 | 3 | 6 real |
| APL (STM) | `APL` | 3 | 2 | 4 real / 1 inv |
| RSE (STM) | `RSE` | 3 | 2 | 4 real / 1 inv |
| AgInt (STM, sem classe principal) | `AgInt`, `AGINT`, `Ag. Int.` | 1 | 3 | 3 real / 1 inv |
| RE | `RE`, `RE.` | 1 | 2 | 3 inv |
| RMS | `Recurso em Mandado de Segurança`, `RMS` | 1 | 1 | 2 real |
| AI (TSE) | `Agravo de Instrumento`, `AI` | 1 | 1 | 2 real |
| ARR (TST) | `ARR` | 1 | 1 | 2 real |
| AgARR (TST) | `AgARR` | – | 1 | 1 real |
| AREspEl (TSE) | `AREspEl` | 1 | – | 1 real |
| HC | `H.C.` | – | 1 | 1 real |
| AR | `AR` | – | 1 | 1 real |
| SLS | `Suspensão de Liminar e de Sentença` | 1 | – | 1 real |
| Rp (TSE, em `R-Rp`) | `Rp` | 1 | – | 1 real |

Prefixos encadeados (canônicos, 42 ocorrências): `AgInt no` 13; `AgRg no` 5; `EDcl no AgInt no` 5;
`EDcl-E-EDcl-` (TST `ED-E-ED-RR`/`ED-E-ED-ARR`) 5; `AgRg-` (TSE `AgR-REspe`, `AgR-AI`) 2;
`AgInt na` 2; `AgInt nos EDcl no` 2; `EDcl no AgRg-` (`ED no AgR-REspe`, `EDs no AGR-RESPE`) 2;
`EDcl no AgRg no` 1; `E-` (TST `E-RR`) 1; `EDcl no` 1; `Terceiro AgRg na` 1; `R-` (`R-Rp`) 1;
`EDcl nos EDcl no AgInt no` 1. Formas de superfície dos prefixos: `AgInt`, `Agravo Interno`,
`AgRg`, `AG.REG`, `AgR`, `AGR`, `Agravo Regimental`, `EDcl`, `ED`, `EDs`, `Embargos de Declaração`,
`E`, `R`, `Terceiro`. Conectores: `no`, `na`, `nos` (nunca `nas`) ou hífen (TST/TSE).
Estilos de cadeia: simples 77, com conector `no/na/nos` 31, hifenizada 9, mista 2
(`ED no AgR-REspe`). Nomes por extenso podem quebrar linha no meio (`Recurso\nEspecial`,
`Suspensão\nde Liminar`).

### 2.2 Conector de número e espaçamento

| conector | N1 | N2 | espaço até o número |
|---|---|---|---|
| (nenhum) | 34 | 14 | (excluídos os 7 com `TST-`/`processo nº`) espaço 30, NBSP 4, hífen 3 (TST/TSE), `\n ` 2, `\n` 1, espaço duplo 1 |
| `nº` | 30 | 10 | N1: espaço 27, `\n` 3; N2: espaço 4, espaço duplo 3, NBSP 3 |
| `n°` (sinal de grau) | – | 11 | espaço 4, NBSP 4, espaço duplo 2, `\n ` 1 |
| `Nº` | – | 9 | espaço 6, espaço duplo 2, NBSP 1 |
| `No` (letra o) | – | 6 | espaço 2, espaço duplo 2, NBSP 2 |
| `n.` | – | 5 | espaço 1, espaço duplo 2, NBSP 2 |

Não ocorrem `n.º`, `N.º`, `num.`, `número`. O NBSP (`\xa0`) aparece 16 vezes, só no N2, quase
sempre entre o conector e o número (também entre sigla e número: `ARESP\xa01234567`).

### 2.3 Formatos numéricos

| formato | N1 | N2 | real | inventada | observações |
|---|---|---|---|---|---|
| `cnj20` (NNNNNNN-DD.AAAA.J.TR.OOOO) | 18 | 16 | 31 | 3 | J=5 TST 10, J=6 TSE 10, J=7 STM 14 (as 3 inventadas são STM, sequencial 7xxxxxx) |
| `curto` (4–7 dígitos) | 46 | 39 | 46 | 39 | 7 dígitos 43; 5 dígitos 37; 6 dígitos 3; 4 dígitos 2 |
| `registro` (AAAA/NNNNNNN-D, STJ) | 0 | 0 | | | nunca citado; só no cabeçalho dos registros |

Variações do CNJ observadas (todas produzem 20 dígitos com o sequencial à esquerda preenchido a 7):
sequencial curto TSE/TST (`12-34.2011.6.05.0099`, `999-12.2011.5.01.0099`), sequencial de 7 com
zero à esquerda (`0609999-…`), **sem pontuação após o hífen** (`0609999-1220216160100`, 5 casos,
2 deles STM), **espaços no lugar dos pontos** (`7009999-12 2021 7 00 0000`), **quebra de linha
dentro** (`….5.02.\n0099`, `…-\n.6.14.0099`, 7 casos), **hífen duplo** (`7009999--\n12.…`), espaço
após o ponto (`12-34. 2011…`). Variações do número curto: com pontos de milhar (`1.234.567`), sem
pontos (`1234567`, 8 no N1 e 14 no N2), com espaços (`1 234 567`, `1. 234.567`), com hífen e quebra
(`11.-\n222`, `2.111-\n.222`, `11-\n.222`), com letra de OCR (`21999l1`, `199999O`, `1.99g.999`,
`1.999.9S9`, `9G.999`).

### 2.4 UF e separadores

| separador (literal) | N1 | N2 |
|---|---|---|
| `/` | 53 | 4 |
| `/ ` (barra + espaço) | – | 9 |
| `-` (colado) | – | 11 |
| ` - ` | – | 4 |
| ` – ` (travessão U+2013) | – | 3 |
| ` (` … `)` | – | 11 |
| `\n- ` | – | 2 |
| sem UF | 11 | 11 |

UFs observadas: RS 19, SP 18, RJ 14, PR 10, DF 7, BA 7, SC 6, PE 4, MA 3, TO 2, AC/CE/ES/GO/MG/RO/SE 1.
A UF é sempre 2 maiúsculas ASCII; nunca sofre OCR. **Separar a UF antes de corrigir OCR** (o `S`
de `/SP` viraria 5). Em 12 casos a UF segue um CNJ (todos STM); nos números curtos a UF está
sempre presente (85/85).

### 2.5 Prefixos de tribunal

Só `TST-` (7 citações, todas CNJ, 4 delas precedidas de `processo nº`/`Processo n°`). Não ocorrem
`STJ -`, `STF,`, `STJ,` nem `(STJ)`. O tribunal das demais é implícito na classe/UF/segmento CNJ.

### 2.6 Moldes das citações `vaga` (32)

| molde | forma | N1 | N2 | tribunais |
|---|---|---|---|---|
| A | `julgado do <T> proferido em <AAAA> pela relatoria de <Nome>` | 5 | 4 | STF 4, STJ 2, STM 1, TSE 1, TST 1 |
| B | `precedente do <T> de <AAAA>, da relatoria de <Nome>` | 4 | 2 | STF 4, STJ 1, STM 1 |
| C | `<Classe> do <T>, de <AAAA>, Rel. Min. <Nome>` | 2 | 5 | STF 5 (`Reclamação`), STJ 2 (`Agravo em Recurso Especial`, `Recurso em Habeas Corpus`) |
| D | `<Sigla> de <AAAA>, Rel. Min. <Nome>` (**sem tribunal**) | 2 | 3 | `Rcl` 4, `APL` 1 |
| E | `acórdão do <T> julgado em <AAAA> sob relatoria de <Nome>` | 2 | 3 | STJ 2, TSE 2, STM 1 |

Variações: OCR `e`→`c` em `proferido` e em `de`, `Rel.  Min.` (espaço duplo), `Rel.\nMin.`,
`Rel. Min.\nNOME`; quebra de linha antes do nome (14) ou dentro dele (4); ano sempre com 4 dígitos
(2016–2026). Nome do relator: 2 palavras (23), 3 (4), 4 (5); caixa alta em 12; partículas `De`/`DA`
com inicial maiúscula; OCR dentro do nome (3 casos: `ã` por `a`, `l` por `i`). O nome termina
antes de `,` (23), `.` (6), ` para`/`\npara` (2) ou ` foi` (1). Exemplo sintético do molde C com
ruído: `Reclamação\ndo STF, de 2023, Rel.  Min. FULANA DE TAL`.

Na base, tribunal + ano + relator devolve **sempre ≥ 4 registros** (mín. 4, mediana 6, máx. 44;
mesmo filtrando pela classe do molde C/D continua ≥ 4). Ou seja, `vaga` ⇒ `incompleta` sem consulta.

## 3. Ruído do nível 2 (item c)

Rótulos atribuídos pelo script a cada span (um span pode ter vários). N2 = 93 citações; 15 delas
não receberam nenhum rótulo (são idênticas ao padrão N1).

| rótulo | N1 | N2 | descrição |
|---|---|---|---|
| quebra_linha_no_span | 18 | 29 | ver §3.2 |
| separador_uf_nao_padrao | – | 40 | tudo que não é `/UF` |
| conector_numero_nao_padrao | – | 17 | `n°`, `Nº`, `No`, `n.` |
| nbsp | – | 16 | `\xa0` dentro do span |
| espaco_no_numero | – | 16 | espaço/quebra dentro do número |
| caixa_alta_na_classe | – | 15 | `RESP`, `ARESP`, `RCL`, `AGINT`, `SÚMULA`… |
| numero_sem_pontos_de_milhar | 8 | 14 | `1234567` em vez de `1.234.567` |
| espaco_duplo | – | 13 | dois espaços consecutivos |
| classe_com_pontos | 1 | 12 | `Rec. Esp.`, `R.Esp.`, `H.C.`, `Ag. Int.`, `A.REsp`, `RE.`, `Recl.`, `REspe.` (N1: `AG.REG`) |
| abreviacao_nao_padrao | – | 11 | `Rec. Esp.`, `R.Esp.`, `Recl.`, `AgREsp`, `Súm.` |
| quebra_linha_no_numero | – | 7 | |
| ocr_palavra | – | 4 | `e`→`c` em `proferido`, `de` e `Federal`; `a`→`ã` em `Tema` |
| ocr_no_nome_do_relator | – | 3 | nome que só casa com a base com tolerância de 1 edição (`ã` por `a` ×2, `l` por `i` ×1) |
| ocr_letra_em_digito | – | 5 | ver §3.1 |
| pontuacao_irregular_no_numero | – | 5 | `--`, `-\n.`, `.-`, `. ` |
| cnj_sem_pontuacao_padrao | – | 5 | CNJ com só o primeiro hífen ou com espaços |
| art_sem_ponto | – | 5 | `art <n>` sem o ponto da abreviatura |
| ocr_letra_em_palavra | – | 1 | `S`→`5` na inicial de `Súmula` |
| caixa_alta (súmula) | – | 1 | `SÚMULA` |

### 3.1 Substituições de OCR observadas

Letra → dígito **dentro de números** (5 ocorrências, uma por número, nunca duas no mesmo número):
`l`→1, `O`→0, `S`→5, `g`→9, `G`→6. Não ocorreram `I`, `o`, `B`, `Z`, `q`, `|`. Sempre em número
curto (4 vezes em números de 7 dígitos do STJ, 1 vez numa `Rcl` de 5 dígitos), em qualquer posição
(início, meio ou fim do grupo), inclusive imediatamente após um ponto de milhar.

Dígito → letra / letra → letra **em palavras** (no texto todo dos 13 documentos N2, 3,8% das
palavras estão fora do vocabulário N1): `e`→`c` 36 (`dc`, `quc`, `dcstacar`, também dentro de `Federal`),
`a`→`ã` 28 (`defesã`, `tribunãis`, também na palavra `Tema`), `c`→`e` 15 (`eomporta`, `reelamante`), `m`→`rn` 12
(`assirn`, `cornporta`), `i`→`l` 11 (`dellto`, `matérla`, também num sobrenome de relator), acento
removido 3, acento extra 1; **dígito dentro de palavra** 7 (`S`→`5` na inicial de `Súmula`, `DO5`, `5alvador`, um nome
de parte terminado em `5`, `C0NTROVÉRSIA`, mais os dois casos dentro de números). Consequência: um regex de número deve exigir que o grupo comece
por dígito ASCII e que letras confundíveis só apareçam **coladas a dígitos**; `DO5` e `C0NTROVÉRSIA`
não podem virar tokens numéricos.

**Garantia "dígito nunca vira outro dígito"** — confirmada: para as 77 citações `real` da família
`processo` (41 N1 + 36 N2), os dígitos após a correção de OCR (`O/o→0, l/I→1, S/s→5, g→9, G→6,
B→8, Z→2`, só dentro do grupo numérico, UF separada antes) são **idênticos** ao número próprio
extraído do cabeçalho do registro `id_canonico` (77/77). Nenhum caso exigiu tolerância a dígito
trocado.

### 3.2 Quebras de linha dentro do span (47: N1 18, N2 29)

| família | onde | N1 | N2 |
|---|---|---|---|
| processo | dentro da cadeia de classes (`AgInt no Recurso\nEspecial`, `Rcl\n99.…`) | 4 | 3 |
| processo | entre conector e número (`nº\n7009…`) | 3 | 1 |
| processo | dentro do número | – | 7 |
| processo | antes da UF (`1.999.888\n- PR`) | – | 2 |
| vaga | antes do nome do relator / no meio da frase | 8 | 6 |
| vaga | dentro do nome do relator | 1 | 3 |
| dispositivo | dentro do nome do diploma (`Constituição\nFederal`, `Lei nº\n13.105/2015`) | 1 | 5 |
| dispositivo | entre `art.` e o número | 1 | – |
| sumula | antes de `do <T>` / dentro (`do\nSTF`) | – | 2 |

**A quebra de linha ocorre em qualquer posição do identificador, também no N1** (18 casos). Todo
`\s` dos regex deve aceitar `\n` e `\xa0`; nunca usar `[ ]`.

### 3.3 Espaços, pontuação e abreviações

- Espaço duplo após conector (11) e dentro de `Rel.  Min.` (1); NBSP após conector (12) e após
  sigla (4).
- Pontuação irregular no número: `--`, `-\n.`, `.-`, `. ` (espaço após ponto de milhar).
- Abreviações fora do padrão: `Rec. Esp.` (4), `R.Esp.` (1), `Recl.` (2), `AgREsp` (2), `Súm.` (1),
  `Ag. Int.` (1), `H.C.` (1), `A.REsp` (1), `RE.` (1), `REspe.` (1); `EDs` (por `EDcl`); `AGR-RESPE`.
- Caixa: `RESP`, `ARESP`, `RCL`, `AGINT`, `AGR-RESPE`, `RESPE`, `SÚMULA`; conector `No`/`Nº`.

## 4. Dispositivos (tipo `lei`, 28) (item d)

| forma | contagem |
|---|---|
| `art.` | 17 (N1 14, N2 3) |
| `art` (sem ponto) | 5 (N2) |
| `artigo` | 6 (N2) |
| número ordinal (`1º`, `5º`, `7º`) | 3 |
| com inciso/alínea/parágrafo | 7 (`I`; `LV`; `IX` ×2; `XXIX`; `§ 1º-A`; `I, 'g'`) |
| preposição | `da` 18, `do` 10 |

Diplomas (superfície → canônico) e classificação:

| diploma canônico | superfícies | real | inventada |
|---|---|---|---|
| CF | `Constituição Federal` (6, uma com OCR `e`→`c`), `Constituição da República` (2) | 4 (três artigos distintos; um deles citado em dois documentos) | 4 (artigos acima do último artigo da CF, que tem 250) |
| CLT | `CLT` (3), `Consolidação das Leis do Trabalho` (1) | 3 | 1 (artigo acima do último da CLT, que vai até o 922) |
| CDC | `Código de Defesa do Consumidor` (3) | 1 | 2 (artigos acima do último do CDC, que tem 119) |
| CPC | `CPC` (1), `Código de Processo Civil` (1), `Lei nº 13.105/2015` (1) | 1 | 2 (artigos acima do último do CPC, que vai até o 1.072) |
| CE | `Código Eleitoral` (2) | 1 | 1 (artigo acima do último do CE, que tem 383) |
| LC 64/1990 | `Lei Complementar nº 64/1990` (2) | 1 | 1 (artigo acima do último da LC 64, que tem 28) |
| CPM | `Código Penal Militar` | 1 | – |
| CPP | `Código de Processo Penal` | 1 | – |
| CC | `Código Civil` | 1 | – |
| Lei 9.504/1997 | `Lei nº 9.504/1997` (2) | – | 2 (artigos acima do último; a lei tem 107) — diploma **fora da base** |
| Lei 13.467/2017 | `Lei nº 13.467/2017` | – | 1 (artigo acima do último; a lei tem 6) — diploma **fora da base** |

Observações:
- Não há forma `Lei nº X, art. Y` (lei antes do artigo); o artigo vem sempre primeiro.
- Não há dispositivo `incompleta` (0/28).
- **Mesmo artigo sob dois diplomas**: o número do único artigo do Código Penal Militar presente na
  base é citado, em outro documento, como se fosse `da Constituição Federal` — e aí é
  `inventada`. Um mesmo artigo da CF é citado em dois documentos (ambos real).
  Logo a chave da resolução é o par (diploma canônico, artigo), nunca o artigo sozinho.
- Toda `inventada` de diploma coberto usa **artigo inexistente no diploma** (número maior que o
  último artigo); as 3 de diploma não coberto (Leis 9.504 e 13.467) também usam artigos inexistentes.
  Para a resolução isso é irrelevante: (diploma, artigo) ∉ base ⇒ `inventada` acerta 14/14 e
  (diploma, artigo) ∈ base ⇒ `real` acerta 14/14. Risco no conjunto cego: um artigo real de diploma
  coberto mas ausente da base (ex.: um art. 37 da CF) — pela definição oficial ("consequência da
  consulta à base fechada") deve ser `inventada`.
- A primeira linha dos 13 registros (`Artigo <n> da Lei nº 13.105, de 16 de março de 2015`) permite
  derivar a tabela de aliases: CPC = Lei 13.105/2015; CC = Lei 10.406/2002; CLT = DL 5.452/1943;
  CF = "Constituição Federal de 1988"; CPP = DL 3.689/1941; CPM = DL 1.001/1969; CDC = Lei
  8.078/1990; Código Eleitoral = Lei 4.737/1965; LC 64/1990.

## 5. Súmulas e temas (item e)

| forma | N1 | N2 | classificação |
|---|---|---|---|
| `Súmula <n> do <T>` | 4 | – | STJ real; TST real; STF inventada; TSE inventada (números muito acima dos verbetes existentes) |
| `Súmula Vinculante <n>` | 2 | 1 | uma SV real; duas SV inventadas (números muito acima dos verbetes existentes) |
| `Súmula <n> do STJ` com OCR `S`→`5` | – | 1 | real |
| `SÚMULA <n> do STJ` (caixa alta) | – | 1 | real |
| `Súm. <n> do TSE` (abreviada) | – | 1 | inventada (número muito acima dos verbetes existentes) |
| `Súmula <n>\ndo STF`, `Súmula <n> do\nSTF` (quebra de linha) | – | 2 | inventadas (números muito acima dos verbetes existentes) |

Total 12: 5 real = exatamente os 5 registros de súmula da base (3 do STJ, 1 do TST, 1 SV);
7 inventadas, todas com número muito acima dos verbetes existentes (as faixas exatas não são reproduzidas aqui: são dados do desafio).
Número: sempre inteiro sem ponto de milhar; nunca `nº` entre `Súmula` e o número; nunca `do STJ`
com Vinculante. Tema: 1 caso, `Tema <n.nnn> da repercussão geral` (N2, com OCR na palavra), inventado; não há
registro de tema na base ⇒ `tema` ⇒ `inventada`.

## 6. Distratores (item f)

### 6.1 Fim do cabeçalho

Heurística usada (`fim_do_cabecalho`): primeira linha com ≥ 60 caracteres, palavras minúsculas,
não toda em caixa alta e que **não** seja `Chave: valor` (ex.: `Autoridade coatora: …`,
`Assunto: …`, `Referência: autos nº …`). Resultado nos 26 documentos (offsets em codepoints):

| doc | len | fim cab. | 1º span | cit. | tokens numéricos fora de span: CAB / PRÉ / CORPO | peça |
|---|---|---|---|---|---|---|
| gen_n1_001 | 3498 | 178 | 589 | 8 | 2 / 0 / 5 | memorial (DPU) |
| gen_n1_002 | 3563 | 252 | 651 | 8 | 1 / 2 / 5 | decisão monocrática (TRF) |
| gen_n1_003 | 3420 | 185 | 577 | 7 | 1 / 1 / 5 | contrarrazões a REsp |
| gen_n1_004 | 2880 | 209 | 460 | 6 | 2 / 0 / 5 | parecer (MPM) |
| gen_n1_005 | 3375 | 178 | 848 | 5 | 1 / 1 / 5 | contrarrazões a REsp |
| gen_n1_006 | 3322 | 236 | 505 | 9 | 2 / 0 / 7 | parecer (MPE) |
| gen_n1_007 | 3270 | 177 | 531 | 9 | 1 / 0 / 5 | memorial |
| gen_n1_008 | 3466 | 226 | 558 | 7 | 1 / 0 / 5 | acórdão (TRT) |
| gen_n1_009 | 3887 | 258 | 616 | 9 | 3 / 2 / 5 | agravo interno (TJ) |
| gen_n1_010 | 3494 | 171 | 477 | 9 | 1 / 0 / 5 | memorial |
| gen_n1_011 | 3109 | 275 | 502 | 7 | 1 / 0 / 5 | AgRg em HC (STJ) |
| gen_n1_012 | 3523 | 234 | 574 | 9 | 1 / 0 / 5 | acórdão (TRT) |
| gen_n1_013 | 3300 | 214 | 1041 | 6 | 1 / 1 / 7 | REspe (TSE) |
| gen_n2_001 | 3284 | 281 | 544 | 8 | 1 / 0 / 5 | AgRg em HC (STJ) |
| gen_n2_002 | 3377 | 259 | 670 | 7 | 1 / 2 / 7 | decisão monocrática (TRF) |
| gen_n2_003 | 3223 | 242 | 613 | 7 | 1 / 0 / 5 | acórdão (TRT) |
| gen_n2_004 | 3052 | 231 | 1014 | 5 | 2 / 0 / 7 | parecer (MPE) |
| gen_n2_005 | 3364 | 235 | 574 | 8 | 1 / 0 / 5 | acórdão (TRT) |
| gen_n2_006 | 3244 | 226 | 494 | 8 | 2 / 0 / 7 | parecer (MPE) |
| gen_n2_007 | 3126 | 206 | 514 | 8 | 3 / 0 / 5 | parecer (MPM) |
| gen_n2_008 | 3265 | 247 | 1206 | 4 | 1 / 4 / 3 | decisão monocrática (TRF) |
| gen_n2_009 | 3432 | 223 | 539 | 8 | 2 / 0 / 6 | parecer (MPF) |
| gen_n2_010 | 3167 | 252 | 579 | 7 | 2 / 0 / 5 | parecer jurídico (consultoria) |
| gen_n2_011 | 3712 | 262 | 671 | 9 | 3 / 2 / 5 | agravo interno (TJ) |
| gen_n2_012 | 3382 | 171 | 481 | 8 | 1 / 0 / 5 | memorial |
| gen_n2_013 | 2977 | 191 | 516 | 6 | 1 / 0 / 5 | razões de apelação (STM) |

O cabeçalho tem 3–8 linhas: endereçamento em caixa alta (1–2 linhas), linha em branco, `Autos nº`
ou `Processo nº` + CNJ, partes (`Recorrente:`, `Apelante:`, `Impetrante:`, `Reclamante:`…),
opcionalmente `Protocolo nº AAAA.NNNNNNN`, `Memorial nº NNN/AAAA`, `Valor da causa: R$ …`,
`Relator: …`, `Autoridade coatora: …`, `Sessão de julgamento …`; depois o título da peça em caixa
alta (`MEMORIAL`, `PARECER`, `ACÓRDÃO`, `AGRAVO INTERNO`…) ou, na variante "parecer jurídico",
`PARECER JURÍDICO Nº NNN/AAAA` na 1ª linha e `Referência: autos nº <CNJ>` mais abaixo. A prosa
começa em 171–281 (mediana 231); o primeiro span vem 227–959 caracteres depois disso (mín. 460,
máx. 1.206 do início do texto).

### 6.2 Números fora do gabarito (193 tokens numéricos) e o que um regex ganancioso pegaria

| zona | rótulo | n | forma | seria falso positivo de… |
|---|---|---|---|---|
| CAB | `Autos nº`/`Processo nº`/`Referência: autos nº` + CNJ | 26 | `NNNNNNN-DD.AAAA.J.TR.OOOO`, J ∈ {3,4,5,6,7,8}, TR e origem aleatórios | qualquer regex de CNJ sem ancoragem à classe |
| CAB | `Protocolo nº` / `Memorial nº` / `PARECER JURÍDICO Nº` | 8 | `AAAA.NNNNNNN` (5), `NNN/AAAA` (3) | regex de número solto |
| CAB | `Valor da causa: R$` | 4 (2 valores × 2 grupos) | `NNN.NNN,NN` | número curto com pontos |
| CAB | dígito de OCR em nome de parte | 1 | nome terminado em `5` (por `S`) | — |
| PRÉ (entre fim do cabeçalho e 1º span) | `(OAB/UF NNNNNN)` | 5 | 6 dígitos sem pontos | número curto tipo STJ sem pontos |
| PRÉ | `fls. NNN/NNN` | 5 | | par de números |
| PRÉ | `NN%` | 3 | | — |
| PRÉ | data por extenso | 2 | `D de <mês> de AAAA` | — |
| CORPO | data por extenso (dia + ano) | 51 + 51 | idem | ano isolado (4 dígitos) |
| CORPO | `fls. NNN/NNN` (referência interna a folhas) | 26 | | |
| CORPO | `R$ NNN.NNN,NN` | 8 | | |
| CORPO | dígito de OCR dentro de palavra | 3 | `DO5`, `5alvador`, `C0NTROVÉRSIA` | token de 1 dígito |

Não há, fora do gabarito: números de processo citados no corpo, nem "citação do mesmo processo
repetida", nem artigos de lei soltos (todo `art.` do corpo está no gabarito), nem números de
súmula soltos. Ou seja: **todo identificador de jurisprudência/lei que aparece na prosa está
anotado**; os únicos números não anotados são os do cabeçalho, folhas, datas, valores, OAB e
percentuais. Os CNJ do cabeçalho têm segmento J variado (3, 4, 5, 6, 7, 8) e tribunal/origem
aleatórios; os CNJ citados no corpo têm J ∈ {5, 6, 7} e, no STM, sempre `7.00.0000`. Isso **não**
deve ser usado como critério (o conjunto cego pode ter cabeçalhos com CNJ "legítimos"); a regra
robusta é posicional: antes do fim do cabeçalho não há citação (26/26 documentos).

### 6.3 Frases-armadilha sem identificador (fora do gabarito)

28 `citacao_id` faltam na numeração do gabarito (ex.: g1 e g7 ausentes em um documento com g2–g10):
são citações "vagas sem identificador" que **saíram** do gabarito em 01/09 e 15/09. Frases-modelo
presentes nos textos e que **não** devem gerar span (contagem nos 26 documentos): "orientação dos
tribunais superiores é firme no ponto" 13; "dispositivo constitucional invocado na origem" 3;
"jurisprudência pacífica desta Corte" 3; "verbete sumular aplicável à espécie" 3; "lei que
disciplina a prescrição no caso" 3; "entendimento sumulado sobre a matéria" 2; "normas de regência
da matéria" 1; "jurisprudência consolidada dos tribunais superiores" 1. Um padrão `vaga` só pode
disparar quando há **ano de 4 dígitos + palavra de relatoria (`relatoria`/`Rel. Min.`) + nome
próprio**; "precedente"/"jurisprudência"/"entendimento" sozinhos não bastam.

## 7. Estatísticas (item g)

- Citações por documento: mín. 4, mediana 8, máx. 9 (N1: 5–9; N2: 4–9).
- Distância entre spans consecutivos (fim → início): mín. 68, mediana 404, máx. 1.014 caracteres;
  70 pares abaixo de 200, 71 pares entre 400 e 600. Nenhum par a menos de 60 caracteres ⇒ não há
  enumerações do tipo `REsp X e AREsp Y` nem spans aninhados; cada citação está numa frase própria
  (`Invoca-se, ainda, o …`, `Como já se reconheceu no …`, `Ampara a pretensão o …`).
- Número repetido no mesmo documento: 0 casos. Entre documentos: um artigo da CF (2 docs, ambos real);
  o artigo do CPM citado também como CF (real / inventada). Relator + ano se repete entre documentos (ex.: o mesmo
  ministro/ano em três `vaga`), sempre `incompleta`.
- A cada `real` corresponde 1 registro próprio (76/77) — o único número próprio de 2 registros
  (`AgInt no REsp` × `AgInt no EREsp`) foi resolvido pela cadeia de classes. Em 10/77 o número
  também aparece **no corpo** de 1–4 outros acórdãos (citado), sempre a partir do offset 2.575 —
  jamais deve contar como candidato.
- Classe citada × classe própria do registro (77 real): cadeia idêntica em 75; classe principal
  idêntica em 76; divergências: `Rcl` citado para registro `AgRg na Rcl` (prefixo omitido) e
  `AgARR` citado para registro `AIRR` (sigla diferente). Logo **a classe não é condição de
  `real`**; só serve de desempate.

## 8. As `inventada` (64) (item h)

| família | n | número existe na base? |
|---|---|---|
| processo | 42 (N1 23, N2 19) | como número **próprio**: 0/42. Em qualquer lugar (citado no corpo): 1/42 (2 registros, offset mín. 48.212). Como substring de um número maior: 11/42 (irrelevante). Em lugar nenhum: 31/42 |
| sumula | 7 | 0 (números > verbetes existentes; a base só tem 5 súmulas) |
| dispositivo | 14 | 0 (11 artigos inexistentes em diplomas cobertos + 3 em diplomas fora da base) |
| tema | 1 | 0 (não há temas na base) |

Classes das 42 `inventada` de processo: `Rcl` 26 (5 dígitos, 11.xxx–99.xxx, com `Rcl`/`Reclamação`/
`RCL`/`Recl.`), `AREsp` 4, `RE` 3 (7 dígitos), `REsp` 3, `RHC` 3, e 3 CNJ do STM (`AgInt`, `APL`,
`RSE`, sequencial 7xxxxxx fora da faixa de sequenciais 7000001–7001432 da base). **Classe "errada" para número
existente com outra classe: 0 casos** — não há na base número próprio igual ao de uma inventada.
Também não há colisão de número próprio entre tribunais na base (0), então a UF/tribunal não é
necessária para desambiguar no dev; é útil apenas como filtro de segurança.

## 9. Recomendações (item i)

### 9.1 Detector

1. **Cabeçalho primeiro.** Calcular `fim_do_cabecalho` (primeira linha de prosa; tratar
   `Chave: valor` como cabeçalho). Nenhum span antes dele. Isso elimina 39 distratores/26 docs
   (todos os `Autos nº`, `Protocolo`, `Valor da causa`, `PARECER Nº`).
2. **Ordem dos padrões** (cada um consome o texto e é seguido da fusão que descarta sobreposições,
   mantendo o span mais longo):
   1. `vaga` (moldes A–E). Precisa vir antes de `processo` porque os moldes C/D começam por
      classe (`Reclamação do STF, de …`, `Rcl de 2021, Rel. Min. …`) e um regex de classe+número
      não deve tentar casar `de 2021` como número.
   2. `dispositivo`: `\b(art\.?|artigo)\s*\d[\d.]*[ºo°]?(?:\s*,\s*[^,]{1,12})*\s*,?\s*d[ao]\s+<diploma>`,
      com `<diploma>` = alternância dos nomes conhecidos (com `\s+` entre palavras, tolerando
      `e`→`c` em `Federal`) incluindo `Lei (Complementar )?n[º°.]?\s*\d[\d.]*/\d{4}`. Terminar no diploma;
      não consumir vírgula/ponto.
   3. `sumula`: `(S[úu]m(?:ula|\.)|5[úu]mula|SÚMULA)\s+(Vinculante\s+)?\d{1,4}(\s+do\s+(STJ|STF|TST|TSE))?`.
   4. `tema`: `Tem[aã]\s+\d[\d.]*\s+da\s+repercuss[ãa]o\s+geral`.
   5. `processo`: `(processo\s+n[º°]\s+)?(TST\s*-\s*)?<cadeia>\s*<conector>?\s*<número>(<sep>\s*<UF>\)?)?`
      onde `<cadeia>` = `(<ordinal>\s+)?<classe>((\s+(no|na|nos)\s+|\s*-\s*)<classe>)*` e
      `<classe>` = alternância de siglas/nomes (§2.1), aceitando pontos internos, caixa alta e
      quebra de linha entre palavras do nome por extenso. `<conector>` = `[nN][º°o.]?`.
      `<número>` = `\d(?:[\dOolISsgGBZz]|[.\-–]|[ \n\xa0](?=[\dOolISsgGBZz.\-–]))*` — começa por
      dígito ASCII, letras confundíveis só coladas a dígitos, e espaço/quebra só quando seguido de
      dígito ou pontuação (evita engolir a próxima palavra). `<sep>` = `\s*[/\-–(]\s*|\s+`;
      UF só de uma lista fechada de 27 siglas; incluir `)` se abriu `(`.
3. **Regras negativas** (não disparar): `fls.\s*\d+/\d+`; `\d{1,2} de <mês> de \d{4}`;
   `R\$\s*[\d.]+,\d{2}`; `OAB/[A-Z]{2}\s*\d+`; `\d+%`; `Protocolo|Memorial|PARECER JURÍDICO\s+nº`;
   tokens de 1 dígito colados a letras; as frases-armadilha de §6.3.
4. **Fronteiras**: nunca incluir o artigo anterior nem a pontuação final; incluir `)` de `(UF)`;
   incluir `do <T>` da súmula, `da repercussão geral` do tema, o diploma inteiro do dispositivo, o
   `processo nº`/`TST-` do TST e o nome completo do relator na `vaga` (parar em `,`, `.`, ou
   palavra minúscula; aceitar `\n` dentro do nome).
5. **Testes sintéticos**: um caso por linha das tabelas de §2–§3 (cada conector × cada
   espaçamento, cada separador de UF, cada variação de CNJ, cada molde de `vaga` com e sem
   quebra de linha, cada abreviação), mais os 12 tipos de distrator de §6.2 como negativos.

### 9.2 Normalização

Separar UF → corrigir OCR só dentro de grupos que começam com dígito → remover `.`, `-`, `–`,
espaço, NBSP e `\n` → se o padrão for CNJ (sequencial 1–7 dígitos + 13 fixos = 14–20 dígitos),
preencher o sequencial a 7 e produzir 20 dígitos; senão manter os 4–7 dígitos como estão.
Classe: `chave_textual` (minúsculas, sem acento, sem pontos/espaços) → tabela de aliases
(`recesp`/`resp`/`recursoespecial` → `REsp`; `agresp`/`aresp`/`agravoemrecursoespecial` → `AREsp`;
`agr`/`agrg`/`agreg`/`agravoregimental` → `AgRg`; `ed`/`eds`/`edcl` → `EDcl`; `recl`/`rcl`/
`reclamacao` → `Rcl`; …). Cadeia canônica = lista de siglas na ordem, sem conectores.

### 9.3 Resolução

- `processo`: dígitos → índice de **números próprios** (nunca o corpo dos acórdãos; nunca a FTS).
  0 candidatos ⇒ `inventada` (42/42 no dev). 1 ⇒ `real` (76/77). ≥ 2 ⇒ desempate na ordem:
  tribunal explícito/segmento J do CNJ e UF (eliminatórios) → cadeia canônica idêntica → classe
  principal idêntica → classe compatível → registro do STJ → UF confirmada (docs/04 h.3, ADR 0006);
  se ainda empatado, duplicatas → menor `documento_id`; senão escolher deterministicamente e
  emitir `real` com confiança baixa. Justificativa: a métrica cobra 1 FP por `real` com id errado, mas
  `incompleta` num gabarito `real` custa 1 FN + 1 FP; e o dev não tem nenhuma `incompleta` com
  número. **Atenção**: a base tem 77 números próprios duplicados (161 registros; TSE 36, STJ 15,
  STM 14, TST 11, STF 1), 69 deles com cadeia de classes idêntica — em geral o mesmo acórdão
  indexado duas vezes (mesmo ano, relator e texto). Só 8 são distinguíveis pela cadeia (4 pela
  classe principal). Esse empate não ocorreu no dev além do caso resolvido pela cadeia, mas
  ocorrerá no conjunto cego.
- Classe divergente com número existente: no dev **nunca** houve número próprio existente com
  classe "errada"; e 2/77 `real` têm cadeia diferente da própria. Portanto: **número manda;
  classe só desempata**. Não rebaixar a `inventada` por divergência de classe.
- `sumula`: (tribunal, vinculante, número) na tabela derivada da 1ª linha dos 5 registros; ausente
  ⇒ `inventada`. `Vinculante` ⇒ tribunal STF implícito.
- `dispositivo`: (diploma canônico, artigo) na tabela derivada dos 13 registros; ausente ⇒
  `inventada` (inclusive diploma desconhecido). Incisos/alíneas não entram na chave.
- `tema` ⇒ `inventada`. `vaga` ⇒ `incompleta` sem consulta (32/32; a base sempre devolve ≥ 4).
- Índice de números próprios: extrair por tribunal (STJ `<classe> Nº <n> - UF (registro)`; STF
  `<data> <órgão> <classe> <n> <cidade>`; STM `<classe> Nº <CNJ>/UF`; TSE `ACÓRDÃO <classe> Nº <n>`
  com formas antigas `Nº 99.999 (CNJ)`; TST `autos de <classe> nº TST-<sigla>-<CNJ>` ou
  `PROCESSO Nº TST-…`). Cobertura obtida pelas heurísticas do script: STF 200/200, STJ 199/199,
  STM 199/200, TSE 195/199, TST 197/198 (990/996). A base também tem ruído de OCR nos cabeçalhos
  (`N o 999-99`, `9999-9920146070000`, `TRE3UNAL`), então o extrator do índice deve usar a mesma
  normalização tolerante do detector.

### 9.4 Confiança

Caminhos com acurácia 100% no dev: `vaga→incompleta` (32), `processo 0 candidatos→inventada` (42),
`processo 1 candidato→real` (76), `sumula/dispositivo na tabela→real` (19), `fora da tabela→inventada`
(22). Usar teto 0,98 e reservar valores baixos (≈0,5) para o empate ≥ 2 com cadeia idêntica e para
spans produzidos por padrões amplos (`vaga` com nome de 1 palavra, número com ≥ 2 letras de OCR).

## 10. Limitações desta análise

- As heurísticas do script (parsing de cadeias, extração de número próprio, fim do cabeçalho,
  rótulos de distrator) foram ajustadas ao dev set; a cobertura fora dele não foi medida.
- O gabarito do dev cobre 26 documentos de 13 "moldes" de peça e um gerador de frases fixo; o
  conjunto cego pode trazer classes, diplomas e moldes de `vaga` ausentes aqui (ex.: `ARE`, `EREsp`,
  `MS`, `RO`, `RRAg`, `Ag-AIRR`, que existem na base mas nunca são citados no dev).
- "Número existe na base" foi medido sobre tokens numéricos normalizados (dígitos), não sobre
  substrings arbitrárias do texto; a medida frouxa (substring de token) está no JSON para conferência.
