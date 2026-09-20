# Análise da base canônica: números próprios, ambiguidades e colisões

Data: 16/09/2026. Fonte: `dados/desafio1_bracis.db` (distribuição de 15/09,
1.014 registros: 996 acórdãos, 5 súmulas, 13 dispositivos) e
`dados/goldenset.csv` (192 citações). Todas as contagens abaixo são
reproduzíveis com `scripts/construir_indice.py`,
`scripts/analise/anatomia_base.py` e `scripts/analise/validar_indice.py`.
**Os exemplos usam números trocados** (mesmo layout, dígitos inventados);
nenhum número real de processo aparece neste documento.

Vocabulário: *número próprio* = o número que o acórdão declara como o
**seu** processo no cabeçalho (ou na fórmula "autos de …", no TST); *citação
no corpo* = qualquer outro número mencionado no inteiro teor. O índice guarda
só o primeiro. *Dígitos canônicos* = chave numérica normalizada
(`base_canonica/digitos.py`): CNJ → 20 dígitos com zeros à esquerda;
registro do STJ → 12 dígitos; sequencial → dígitos sem zeros à esquerda.
*Cadeia de classe* = siglas canônicas na ordem do cabeçalho
(`EDcl no AgInt no AREsp` → `ED AGINT ARESP`; o último elemento é a classe
principal).

Resultado central: **cobertura 96/96** das citações `real` do gabarito pelo
índice de números próprios; **0/42** citações `inventada` com número
coincidem com um número próprio; **40/40** citações de lei/súmula coerentes
com as tabelas derivadas.

## a. Anatomia do cabeçalho por tribunal

Resumo (posição = offset em codepoints do primeiro dígito do número próprio):

| Tribunal | Acórdãos | Anos | Posição do nº próprio (min / mediana / p90 / máx) | Ids por registro | Formato | UF |
|---|---|---|---|---|---|---|
| STF | 200 | 2014–2026 | 37 / 48 / 129 / 146 | 1 | sequencial (4–7 dígitos) | 200/200 (estado por extenso) |
| STJ | 199 | 2010–2026 | 11 / 35 / 54 / 163 | **2** (número + registro) | sequencial (2–7) + registro `AAAA/NNNNNNN-D` | 199/199 (sigla) |
| TSE | 199 | 2009–2023 | 19 / 83 / 103 / 123 | 1 (186), 2 (13) | CNJ (199, 1 reparado pelo corpo) + sequencial antigo (13) | 196/199 (estado por extenso) |
| TST | 198 | 2011–2026 | 88 / **3.800** / 7.101 / 12.547 | 1 (repetido em rodapé/cabeçalho) | CNJ com prefixo `TST-<CLASSES>-` | 0/198 |
| STM | 200 | 2017–2026 | 41 / 99 / 111 / 837 | 1 | CNJ (`…7.00.0000`) | 138/200 (sigla `/UF`) |

Chaves numéricas no índice: 1.105 (200 STF + 398 STJ + 212 TSE + 198 TST +
200 STM = 1.208 identificadores, menos os compartilhados); 0 acórdãos sem
identificador.

### STF

Layout único, 200/200: `[dd/mm/aaaa] <ÓRGÃO> <CLASSE COM PREFIXOS> <número>
<ESTADO POR EXTENSO> RELATOR : MIN. …`. Em 157 registros o texto começa pela
data; em 43 há um prefixo de exportação (`Supremo Tribunal Federal
EmentaeAcórdão Inteiro Teor do Acórdão - Página 1 de 42 dd/mm/aaaa …`).
Exemplo sintético:

```
03/05/2023 PRIMEIRA TURMA AG.REG. NA RECLAMAÇÃO 12.345 SÃO PAULO RELATOR : MIN. FULANO
AGTE.(S) : … INTDO.(A/S) : RELATOR DO PROCESSO Nº 5000123-45.2020.4.03.6100 DA 1a TURMA …
```

* Número: 5 dígitos em 177 registros (`12.345`), 7 em 16 (`1.234.567`), 4 em
  4, 6 em 3. Sempre com pontos de milhar. Nunca há "Nº".
* Classe: 27 cadeias distintas; `AGR RCL` = 156, `ED RCL` = 7, `2O AGR RCL`
  = 6, `2O AGR ARE` = 3, `AGR RE` = 3, …, com encadeamentos longos
  (`AG.REG. NOS EMB.DIV. NOS EMB.DECL. NO SEGUNDO AG.REG. NO RECURSO
  EXTRAORDINÁRIO COM AGRAVO`) e ordinais (`SEGUNDO`, `TERCEIRO`, `DÉCIMOS`),
  que o índice preserva como tokens (`2O`, `3O`, `10O`) porque distinguem
  decisões sucessivas no mesmo processo.
* UF: nome do estado por extenso (`RIO GRANDE DO SUL`) → sigla.
* Distratores no cabeçalho: em 6 registros a lista de interessados traz um
  CNJ de outro processo (`RELATOR DO PROCESSO Nº …`). A região de
  identificação termina no primeiro `RELATOR`, o que os exclui.
* Relator: `Nome Sobrenome` (128), `Min. MAIÚSCULAS` (47), 3+ palavras (25).

### STJ

Layout único, 199/199: `<CLASSE COM PREFIXOS> Nº <número> - <UF>
(<AAAA/NNNNNNN-D>) RELATOR : MINISTRO …`. Em 18 registros há prefixo de
exportação (`Superior Tribunal de Justiça [Revista Eletrônica de
Jurisprudência [Exportação de Auto Texto do Word …]]`). Exemplo sintético:

```
EDcl no AgInt no AGRAVO EM RECURSO ESPECIAL Nº 1.234.567 - RJ (2019/0123456-7) RELATOR : MINISTRO FULANO
AGRAVANTE : … ADVOGADO : BELTRANO - RJ012345 …
```

* **Dois identificadores** por registro: o número (7 dígitos em 143, 5 em 36,
  6 em 12, 4 em 5, 2 em 3 — `QO na CAUTELAR INOMINADA CRIMINAL Nº 42`) e o
  registro (12 dígitos). Número com pontos em 120 e sem pontos em 79
  (`Nº 1234567`). O separador do registro é `/` em 194 e `⁄` (U+2044) em 5.
* Classe: 45 cadeias; `RESP` = 33, `AGINT RESP` = 31, `AGINT ARESP` = 28,
  `RHC` = 16, `ED AGINT ARESP` = 11, `AGR RESP` = 9, …; prefixos colados por
  erro de formatação (`AgInt nosEMBARGOS DE DIVERGÊNCIA EM RESP`) são
  separados pelo parser.
* Distratores: números de OAB (`RJ012345`) em 171 cabeçalhos — nunca são
  capturados porque o padrão exige `Nº <número> - <UF> (<registro>)`.
* O registro `AAAA/NNNNNNN-D` **é citável**: aparece no corpo de 24 acórdãos
  (75 menções) referindo-se a outros processos, tipicamente em transcrições
  de ementas. Fica indexado (12 dígitos não colidem com nenhum outro formato).

### TSE

O tribunal mais heterogêneo (OCR de PDF escaneado). Quatro layouts:

| Layout | Registros | Exemplo sintético |
|---|---|---|
| `Nº <CNJ> - CLASSE nn - <MUNICÍPIO> - <ESTADO>` (2010–2017) | 104 | `AGRAVO REGIMENTAL NO RECURSO ESPECIAL ELEITORAL Nº 123-45.2016.6.05.0151 - CLASSE 32— CIDADE - BAHIA Relator:` |
| `Nº <CNJ PJe> - <MUNICÍPIO> - <ESTADO>` (2019–2023) | 81 | `AGRAVO EM RECURSO ESPECIAL ELEITORAL Nº 0600123-45.2021.6.06.0121 - CIDADE - CEARÁ Relator:` |
| número antigo + CNJ entre parênteses (2009–2011) | 12 | `RECURSO ESPECIAL ELEITORAL Nº 36.123 ( 43210-98.2009.6.00.0000) -CLASSE 32— CIDADE - ALAGOAS` |
| PJe "capa" | 2 | `05/12/2020 Número: 0601234-56.2018.6.09.0000 Classe: AGRAVO DE INSTRUMENTO Órgão julgador …` |

* 12 registros têm **dois** números próprios (antigo sequencial de 4–5
  dígitos + CNJ); 1 registro de 2009 só tem o sequencial (`AÇÃO CAUTELAR Nº
  3.343`).
* Ruído de OCR no cabeçalho, todos tratados: `TRIEUNAL`, `ACORDAO`,
  `AC€RD O`, `N o`, `N‚`, `No`, ausência do `Nº`, CNJ com espaços
  (`123-45. 2016.6.05.0151`, `612- 2012 6 08 0021`), pontuação perdida
  (`3141-8720146070000`), dígitos dentro de palavras (`DECLARAcA0`,
  `PREsTAcA0`), estado com letras espaçadas (`M A R A N H Ã O`) ou
  corrompido (`PARAN„`), nomes espaçados (`R e l a t o r`), `CLASSE 3ZY`.
  A UF é resolvida por distância de edição contra os 27 nomes de estado
  (tolerância ≈ 1 erro a cada 5 letras, com desempate por prefixo).
* Um cabeçalho perdeu os dígitos verificadores do CNJ (14 dígitos em vez de
  16); o corpo repete o número íntegro 28 vezes, e o índice acrescenta essa
  forma "reparada pelo corpo" (regra só dispara com CNJ < 16 dígitos e ≥ 3
  ocorrências no corpo com o mesmo sufixo `AAAA.J.TR.OOOO`). Um cabeçalho
  está corrompido a ponto de não se reconhecer a classe (fica com cadeia vazia
  e só o CNJ). Três registros ficam sem UF (2 PJe + 1 corrompido).
* Classe: 34 cadeias; `RESPE` = 45, `AGR RESPE` = 33, `RO` = 22, `ARESPE` =
  12, `ED RESPE` = 11, `AGR AI` = 11, …. Nomenclatura muda com a época
  (`RECURSO ORDINÁRIO` × `RECURSO ORDINÁRIO ELEITORAL`; `AGRAVO EM RECURSO
  ESPECIAL` × `… ELEITORAL`): o índice canoniza ambas para a mesma sigla ou
  as declara equivalentes (`RESP≈RESPE`, `ARESP≈ARESPE`).
* Em 23 registros o **mesmo número** reaparece nos primeiros 1.500 chars
  sob outra cadeia: capa do `REspe` seguida do acórdão do `AgR`, ou a
  `AIJE`/`RO`/`HC` de origem — no PJe o CNJ é o mesmo em todas as instâncias
  e recursos do caso. O índice guarda a cadeia da primeira linha; por isso,
  no TSE (como no TST), a classe citada pode legitimamente diferir da classe
  própria, e a classe não pode ser eliminatória.

### TST

O número próprio **não está no cabeçalho**: o texto começa por `A C Ó R D Ã O
(5ª Turma) GMXXX/abc <EMENTA…>` e o número só aparece na fórmula
processual após a ementa:

```
… Vistos, relatados e discutidos estes autos de Agravo de Instrumento em Recurso de
Revista nº TST-AIRR-12345-67.2015.5.24.0123, em que é Agravante …
```

* Fórmula `autos de <classe por extenso> n.º TST-<PREFIXOS>-<CNJ>` presente
  em 198/198; posição mínima 411, **mediana 3.840**, p90 7.060, máx 12.509.
  Conector: `nº` (267 menções), nenhum (43), `n.º` (10), `n . º` (2).
* Rodapé `PROCESSO Nº TST-…` (assinatura digital) em 21 registros; cabeçalho
  `Poder Judiciário Justiça do Trabalho Tribunal Superior do Trabalho PROCESSO
  Nº TST-…` (layout novo) em 2. O índice lê as três zonas e deduplica.
* O prefixo carrega a cadeia de classe: `TST-ED-E-ED-RR` → `ED E ED RR`;
  `TST-Ag-AIRR` → `AG AIRR`; `TST-AgARR` → `AG ARR`; `TST- Ag-Emb-ED-RR` (com
  espaços) → `AG E ED RR`. 32 cadeias; `RR` = 80, `AIRR` = 21, `AG AIRR` =
  15, `ARR` = 11, `RRAG` = 11, `E RR` = 9, ….
* CNJ com sequencial de 1 a 7 dígitos (`71-29.2010…`, `181000-52.2008…`):
  14 a 20 dígitos significativos, sempre preenchidos para 20.
* Sem UF (o TRT de origem está no CNJ: `5.15` = 15ª Região).
* Armadilha específica: o corpo cita outros processos **no mesmo formato**
  (`PROCESSO Nº TST-RR-…`, `processo n.º TST-…`), inclusive ementas
  transcritas com o rodapé. Só a **primeira** fórmula "autos de" conta.

### STM

Três layouts, todos com `<CLASSE> Nº <CNJ>`:

| Layout | Registros | Exemplo sintético |
|---|---|---|
| `Poder Judiciário STM EXTRATO DE ATA DA SESSÃO VIRTUAL DE dd/mm/aaaa A dd/mm/aaaa <CLASSE> Nº <CNJ>/UF RELATOR:` | 133 | `… APELAÇÃO CRIMINAL Nº 7000123-45.2023.7.00.0000/RS RELATOR: MINISTRO …` |
| `Secretaria do Tribunal Pleno <CLASSE> Nº <CNJ> RELATOR:` (sem UF no cabeçalho) | 64 | `Secretaria do Tribunal Pleno AGRAVO INTERNO Nº 7000456-78.2021.7.00.0000 RELATOR: …` |
| `Poder Judiciário SUPERIOR TRIBUNAL MILITAR <CLASSE> Nº <CNJ>/UF APELANTE: …` | 2 | idem, partes antes do relator |
| extrato de ata de 2017: o número só aparece após a lista de presentes (char 837), no formato antigo `241-56.2016.7.11.0213 - DF` | 1 | — |

* CNJ com 7 dígitos de sequencial (`7000123-45.2023.7.00.0000`) em 199; o
  formato antigo (auditoria de origem `7.11.02xx`) em 1.
* UF: no cabeçalho em 136; em 2 só na primeira menção do número no corpo
  (`… Agravo Interno nº 7000456-78.2021.7.00.0000/RS, oposto …`), que o
  índice aproveita; 62 sem UF.
* 10 cadeias: `APL` = 129, `AGINT` = 20, `RSE` = 16, `EI` = 15, `HC` = 6,
  `ED` = 6, `RDI` = 4, `CJ` = 2, `CP` = 1, `RCL` = 1. Atenção: no STM
  `AGRAVO INTERNO` e `EMBARGOS DE DECLARAÇÃO` são a **classe principal**
  (não prefixos), e a citação do gabarito segue isso (`AgInt 7000…`).
* Não há decisões monocráticas nem súmulas entre os acórdãos de nenhum
  tribunal; "súmulas" e "dispositivos" são os 18 registros à parte (seção g).

## b. Ambiguidades: números próprios de ≥ 2 registros

93 chaves (8,4% das 1.105) apontam para ≥ 2 registros; como o STJ contribui
com duas chaves por registro, isso corresponde a **77 grupos de documentos**
(71 pares, 5 trios, 1 quádruplo) envolvendo **161 registros (16% da base)**:
TSE 36 grupos, STJ 15, STM 14, TST 11, STF 1.

Natureza dos grupos (comparação dos textos):

| Tipo | Grupos | Como distinguir |
|---|---|---|
| texto idêntico após colapsar espaços (mesma decisão, dois `id_canonico`) | 31 | impossível pelo texto |
| quase idêntico (Jaccard de 5-gramas ≥ 0,95; diferenças de 1–200 chars) | 31 | impossível na prática |
| parecido (0,5–0,95; mesma classe; extratos de ata em versões diferentes) | 12 | impossível na prática |
| **diferente (< 0,2): decisões sucessivas com classe distinta** | 3 | pela cadeia de classe |

Nos 6 grupos em que a cadeia de classe difere (3 "diferentes" + 3 em que um
ED/AgR sucessivo repete o texto da decisão anterior), a classe resolve:
`AGINT RESP` (2018, ~38 mil chars) × `AGINT ERESP` (2019, ~16 mil chars);
`AGINT RESP` × `AGINT EDV ERESP`; `RHC` × `PEXT RHC`; `ED AGR RESP` × `AGR
RESP`; `RESPE` × `ED RESPE` (TSE); `AGR EDV ED 2O AGR ARE` × `AGR 2O EDV ED
2O AGR ARE` (STF, diferem só por um ordinal: mesmo acórdão em duas
exportações).

**O que o gabarito diz.** Das 77 citações `real` de processo, apenas **1**
cai numa chave ambígua: a citação `AgInt no Recurso Especial nº <n>` aponta
para o registro `AGINT RESP` (o mais antigo e o mais longo), não para o
`AGINT ERESP` de mesmo número. O critério que reproduz o gabarito é
**cadeia de classe exata**; "mais antigo", "mais longo" e "menor
`documento_id`" também escolheriam o mesmo, mas são coincidência. As 76
restantes têm exatamente 1 registro com o número. Nenhuma citação do
gabarito cai num grupo de duplicatas textuais — 1 acerto em 77 sorteios
contra 16% de registros duplicados sugere que o gerador do gabarito **não
amostra duplicatas** (ou o conjunto de desenvolvimento foi gerado antes de
elas entrarem na base); é uma hipótese, não uma garantia para o conjunto
cego.

**Sobre o par "≈61 mil × ≈96 mil chars" citado em `docs/00`:** não existe
na distribuição de 15/09 nenhum grupo com esses tamanhos. O único par
ambíguo tocado pelo gabarito é o `AGINT RESP` × `AGINT ERESP` acima (≈38 mil
× ≈16 mil chars). Os pares TST `RR` × `RR` com ≈97 mil × ≈97 mil e `AG ARR`
com ≈61 mil × ≈61 mil são duplicatas quase idênticas, não decisões distintas.
Conclusão: o critério "mais curto/mais longo" não é sustentado pelos dados;
o critério sustentado é **classe exata → classe principal → (duplicata)
escolha determinística com confiança rebaixada**.

Ordenação determinística: `por_digitos` lista `documento_id` em ordem
crescente; nos 31 grupos idênticos o menor `documento_id` tem o menor
`id_canonico` em 27 casos (sem significado conhecido).

## c. Colisões

* **Entre tribunais: 0.** Nenhum número próprio pertence a registros de dois
  tribunais (o exemplo de colisão STJ×TSE citado no enunciado da tarefa não
  ocorre nesta base). Ainda assim, sequenciais de 5 dígitos do STF e do STJ vivem na mesma
  faixa (`12.345`), então o tribunal/classe continua obrigatório como filtro
  quando a citação o informa.
* **Números próprios curtos no corpo de outros registros** (só números
  "limpos": com pontos, CNJ ou ≥ 4 dígitos corridos):

  | Dígitos | Chaves | Aparecem no corpo de outros registros (≥ 1) | ≥ 5 registros | máx |
  |---|---|---|---|---|
  | 4 | 11 | 8 | 2 | 13 |
  | 5 | 219 | 33 | 7 | 10 |
  | 6 | 15 | 0 | 0 | 0 |
  | 7 | 146 | 23 | 1 | 7 |
  | 20 (CNJ) | 529 | 58 | 0 | 4 |

  Contextos típicos das colisões de 4–5 dígitos: números de ADI (`ADIs 2.1xx
  e 2.1yy` — 341 menções em 10 registros para uma única chave de 4 dígitos),
  outras Rcl/RE citadas como precedente, `fls. 1234/1256`, número de OAB
  (`RS123456`) e datas. Nenhuma chave sequencial coincide com um ano
  (1900–2030) nem com o número de uma lei conhecida (13.105, 10.406, 5.452,
  3.689, 1.001, 8.078, 4.737, 9.504, 13.467, 8.429, 8.666, 14.133, 9.099).
  Chaves de 2–3 dígitos (`Nº 42`) não foram medidas (aparecem em todo lugar);
  citações tão curtas exigem classe + tribunal.
* **Vizinhos a 1 dígito.** 4 das 42 citações `inventada` com número distam
  exatamente 1 dígito de um número próprio real (3 delas com a mesma classe
  `Rcl`/STF, todas com **UF diferente**). O gerador de inventadas perturba
  dígitos de números reais: **nunca** fazer casamento aproximado de dígitos,
  e nunca "corrigir" um dígito por outro (a garantia do desafio é que um
  dígito jamais vira outro dígito).

## d. Quem cita vs. quem é (96 citações `real`)

`scripts/analise/validar_indice.py` termina com `COBERTURA 96/96`:

| Família | Citações | Resolvem pelo índice | Observações |
|---|---|---|---|
| processo (número) | 77 | 77 | 76 com 1 candidato pelo número; 1 com 2 (desempate por cadeia exata); 0 ambíguas após classe/UF |
| súmula | 5 | 5 | `Súmula Vinculante <n>` → STF implícito; `Súmula <n> do STJ` com OCR `S`→`5` |
| dispositivo de lei | 14 | 14 | inclui `Constituição Federal` com OCR `e`→`c` e `Código\nde Processo Penal` |

Armadilha quantificada: para as 77 citações de processo, **21 registros da
base contêm o mesmo número no corpo sem serem o dono** (66 citações têm 0
"falsos donos", 4 têm 1, 5 têm 2, 1 tem 3, 1 tem 4). Exemplos (números
omitidos): um AgR na Rcl do STF que transcreve quatro vezes `AgInt no AREsp
n. <x>/SP` e três vezes `REsp nº <y>/SP` — um índice de texto integral
(BM25/FTS) devolveria o acórdão do STF para duas citações de REsp do STJ; um
REsp afetado como repetitivo é citado por dois outros REsp do mesmo tema; um
RSE do STM é mencionado como conexo em dois outros RSE; o AIRR do TST é
citado por dois outros acórdãos do TST com o rodapé `PROCESSO Nº TST-AIRR-…`
transcrito.

Concordância citação × cabeçalho nos 77 casos: cadeia de classe **exata**
em 75; só a classe principal em 1; **divergente em 1** — o gabarito cita
`TST-AgARR-<n>` e o registro se declara `TST-AIRR-<n>` (a citação usa a
classe do metadado do Jusbrasil, não a do texto). UF: igual em 55, divergente
em 0, ausente na citação em 22 (TSE/TST/STM sem UF, ou N2 sem UF).
Consequência: a classe é **desempate**, não eliminatória; ver seção h.

## e. As 64 citações `inventada`

* 42 processos com número: **0 coincidem com número próprio** (nenhum
  tribunal, nenhuma classe). 40 não aparecem em corpo algum; 1 aparece 1 vez
  (é um número de OAB `UF0xxxxx` dentro de uma lista de advogados); 1 aparece
  em 3 registros (STF, TSE, TST) — é um `MS <n>` real do STF citado como
  precedente, enquanto a citação inventada o chama de `Reclamação nº <n>/PE`:
  a base não tem esse MS como número próprio, e a classe citada difere.
  Conclusão: **para o conjunto de desenvolvimento a resolução não precisa
  checar classe/tribunal para rejeitar inventadas** — o número basta. A
  checagem de classe/tribunal continua necessária para (i) desempatar os
  77 grupos ambíguos e (ii) proteger contra o conjunto cego (5 dígitos do STF
  e do STJ compartilham faixa).
* 7 súmulas (3 do STF com n > 900; 2 SV com n > 180; 2 do TSE com n > 160):
  nenhuma existe na tabela derivada (a base só tem 5 súmulas: 3 do STJ, 1 SV
  e 1 do TST).
* 14 dispositivos: artigo inexistente num diploma coberto (11 casos: número
  acima do último artigo do CPC, do CDC, do Código Eleitoral, da LC 64/1990,
  da CLT ou da CF — ver a tabela de docs/03 §4) ou diploma identificável
  **fora da base** (`Lei nº 9.504/1997` ×2, `Lei nº 13.467/2017`) → diploma sintético `LEI-9504`,
  `LEI-13467` → `inventada`, nunca `incompleta`.
* 1 tema de repercussão geral (`Tema <n.nnn> da repercussão geral`, com OCR
  na palavra): a base não tem temas →
  `inventada`.

## f. As 32 citações `incompleta` (tribunal + ano + relator)

`BaseCanonica.por_relator_ano` com relator tolerante (todos os sobrenomes
citados presentes no relator do registro, 1 erro de OCR permitido por
sobrenome ≥ 5 letras — os 3 nomes com OCR do gabarito têm `a`→`ã` ou `i`→`l`
num sobrenome; `de` aparece como `dc`):

| Registros que casam | Citações |
|---|---|
| 4 | 5 |
| 5 | 4 |
| 6 | 11 |
| 7 | 4 |
| 9 | 3 |
| 11 / 18 | 1 / 1 |
| 26 | 2 |
| 44 | 1 |

**Nenhuma casa com exatamente 1 registro** (armadilha ausente) e nenhuma
casa com 0. Mínimo 4 (dois pares tribunal/ano/relator do STF), máximo 44
(um relator muito produtivo citado sem tribunal). 6 das 32 não nomeiam o
tribunal (molde D: `Rcl de <AAAA>, Rel. Min. <Nome>`, `APL de <AAAA>, Rel.
Min. <NOME>`) — a classe sugere o tribunal (Rcl → STF/STJ; APL → STM), mas a
multiplicidade já justifica `incompleta` sem isso. Não há, nos 26 documentos,
citação vaga que se torne resolvível por (tribunal, ano, relator); manter a
regra "família `vaga` → `incompleta` direto" e usar `por_relator_ano` apenas
como diagnóstico/confiança.

## g. Súmulas e dispositivos

Tabelas derivadas da primeira linha dos 18 registros
(`normativos.derivar_normativos`, sem nada à mão):

| Chave | Registros (só contagens — os números são dados do desafio e não são reproduzidos aqui) |
|---|---|
| súmulas `(tribunal, vinculante, número)` | 5 verbetes: 3 do STJ, 1 Súmula Vinculante (STF) e 1 do TST; números todos distintos entre si |
| dispositivos `(diploma, artigo)` | 13 artigos em 9 diplomas (CC, CDC, CE, CF, CLT, CPC, CPM, CPP, LC64): CF com 3, CLT com 3, os demais com 1 cada |

As chaves exatas ficam em `dados/indice.json` (`normativos`, ignorado pelo git) e são conferidas por
`tests/test_base_canonica.py` contra a base.

Mapa de aliases de diploma (`normativos.DIPLOMAS`), em duas camadas:

1. **Número da lei** (vence sempre): `Lei 13.105[/2015]` → CPC; `Lei
   10.406` → CC; `Decreto-Lei 5.452` → CLT; `DL 3.689` → CPP; `DL 1.001` →
   CPM; `Lei 8.078` → CDC; `Lei 4.737` → CE; `LC 64` → LC64; tolera `nº`,
   `n.`, `n°`, `, de 16 de março de 2015`, quebra de linha e OCR nos dígitos
   (`13.1O5`). Lei conhecida fora da tabela → `LEI-<n>`/`DL-<n>`/`LC-<n>`.
2. **Texto**, por palavras-chave tolerantes a ruído, na ordem: `constitui…`
   /`CF`/`CRFB`/`Carta Magna` → CF; `processo civil`/`CPC`/`NCPC` → CPC;
   `processo penal`/`CPP` → CPP; `penal militar`/`CPM` → CPM; `consumidor`/
   `CDC` → CDC; `consolidação das leis do trabalho`/`CLT` → CLT; `código
   eleitoral`/`CE` → CE; `inelegibilidade` → LC64; `código civil`/`CC` → CC
   (por último, porque "processo civil" contém "civil").

Verificação: as 28 citações de lei (14 real + 14 inventada) e as 12 súmulas
(5 + 7) resolvem coerentemente (`real` ↔ existe com o mesmo `id_canonico`;
`inventada` ↔ não existe): **40/40**.

**Mesmo artigo sob dois códigos:** o gabarito cita o único artigo do Código
Penal Militar presente na base (`real`) e o mesmo número `da Constituição
Federal` (`inventada`: a CF não chega a esse artigo). A chave da tabela é
`(diploma, artigo)`; resolver só pelo artigo produziria uma `inventada→real`
com penalidade dupla. Analogamente um artigo da CF citado duas vezes (real)
× o mesmo número em qualquer outro diploma (não existe na base). Incisos/alíneas/parágrafos (`I`, `IX`, `§
1º-A`, `'g'`) são ignorados na chave: a base indexa o artigo inteiro.

Cuidado adicional: `CE` também é UF (Ceará). `separar_uf` só age no fim de
trechos de processo; para dispositivos o diploma é lido antes.

## h. Recomendações para `resolucao.py`

1. **Chave primária = dígitos canônicos do número.** `candidatos_por_numero`
   devolve só donos (nunca quem cita). Nunca usar FTS/BM25 para resolver
   processo; nunca casar dígitos de forma aproximada.
2. **Filtros na ordem: tribunal → UF → classe.** Tribunal quando a citação o
   informa explicitamente ou a classe é exclusiva de um tribunal (`REspe`,
   `AREspEl`, `RO` eleitoral → TSE; `RR`, `AIRR`, `ARR`, prefixo `TST-` →
   TST; `APL`, `RSE`, `EI`, CNJ `.7.00.` → STM; `REsp`, `AREsp`, `RHC`,
   `RMS`, `EREsp` → STJ; `RE`, `ARE`, `ADI`, `ADPF`, `SV` → STF; `Rcl`,
   `HC`, `MS`, `AR` são **ambíguos** entre STF e STJ e não podem inferir
   tribunal). UF: descarta candidato com UF conhecida **diferente**; mantém
   candidatos sem UF (TST, 62 STM, 3 TSE). Classe: cadeia exata → classe
   principal compatível → família (TST) — e **só como desempate**: se o
   número é único na base e o tribunal é compatível, é `real` mesmo com classe
   divergente (caso `AgARR`/`AIRR`), com confiança rebaixada e registro em
   log. Um número único com **tribunal** incompatível (ex.: 5 dígitos
   próprios do STF citados como `REsp`) deve ir para `inventada` — não há
   caso assim no dev; estimar a confiança pelo caminho.
3. **Ambiguidade residual** (77 grupos, 16% da base): (a) cadeia exata; (b)
   classe principal; (c) se os textos restantes são duplicatas (mesmo
   cabeçalho de 600 chars), escolher deterministicamente o **menor
   `documento_id`** e emitir `real` com confiança ≈ 0,8 (prior declarado na ADR 0007: o
   formato `a:b` de `doc_ids` da métrica aceitaria o grupo inteiro; era ≈ 0,5 até a rodada 2) — `incompleta`
   custaria FN + FP com certeza, enquanto o chute custa 1 FP em ~50% dos
   casos; (d) só chamar o árbitro LLM quando os candidatos têm cabeçalhos
   diferentes e a citação traz contexto que os distinga (ano, relator).
4. **Registro do STJ (`AAAA/NNNNNNN-D`, o exemplo de docs/02)**: manter indexado (12 dígitos,
   sem colisão possível); uma citação que traga só o registro resolve
   sozinha; se trouxer número + registro e eles apontarem para registros
   diferentes, preferir o número e rebaixar a confiança.
5. **TST**: a chave é o CNJ de 20 dígitos; o prefixo `TST-…-` é cadeia de
   classe e **não** entra nos dígitos (letras `S`, `T` nunca são corrigidas
   para dígitos porque o grupo `TST` não contém dígito). Aceitar `TST-`
   ausente, espaços em torno dos hífens (`TST- ED - E-ED-RR-`), `n.º`,
   `n . º`, quebra de linha dentro do CNJ. Classe da família TST é toda
   compatível entre si (`RR`≈`AIRR`≈`ARR`≈`RRAg`≈`Ag-…`).
6. **TSE**: aceitar número antigo (`36.123`) ou CNJ; ambos indexados. CNJ
   sem pontuação (`0600319-5120206160182`) e com sequencial curto
   (`537-81.2012…`, `1-27.2017…`) já são normalizados para 20 dígitos.
7. **STM**: `AgInt`/`ED` são classes principais; CNJ `NNNNNNN-DD.AAAA.7.00.0000`
   com espaços ou sem pontos; UF opcional.
8. **Súmula**: `(tribunal, vinculante, número)`; `Súmula Vinculante` implica
   STF; sem tribunal e sem `vinculante`, resolver só se o número for único na
   tabela; tribunal explícito diferente do da tabela → `inventada`.
9. **Dispositivo**: `(diploma canônico, artigo)`; diploma sintético
   `LEI-<n>` (fora da base) → `inventada`; artigo sem diploma reconhecível →
   `incompleta`; incisos/parágrafos ignorados.
10. **Citações vagas** (tribunal + ano + relator): `incompleta` direto; a
    multiplicidade mínima observada é 4.
11. **Confiança**: caminhos distintos para "número único + classe exata"
    (≈ 0,98), "número único + classe divergente" (rebaixar; sem UF/tribunal ⇒ `inventada`,
    ADR 0006 rodada 4), "duplicata escolhida" (≈ 0,8, ADR 0007), "inventada por ausência" (alta, mas nunca 1,0 — ver
    vizinhos a 1 dígito e OCR letra→dígito).

## Riscos e decisões pendentes

* **Duplicatas na base (16% dos registros)**: se o conjunto cego amostrar
  registros duplicados, metade dessas citações `real` sairá com o `id`
  errado (1 FP cada) independentemente da estratégia; decidir entre "menor
  `documento_id`" e "maior `id_canonico`" (sem evidência que favoreça algum).
* **Classe na citação ≠ classe no texto** (1/77 no dev): a política
  "classe só desempata" evita o FN, mas abre a porta para uma inventada com
  número real e classe trocada. No dev isso não ocorre (0/42); o gerador
  parece produzir inventadas por perturbação de dígitos, não por troca de
  classe. Monitorar nos sintéticos.
* **OCR no TSE**: um cabeçalho reparado pelo corpo e um sem classe; se o
  conjunto cego citar esses dois registros pela classe, o desempate por classe
  fica indisponível (o número ainda resolve).
* **Correção letra→dígito** (`O→0`, `l→1`, `S→5`, `g→9`, `G→6`, `B→8`,
  `Z→2`) só dentro de grupos com maioria de dígitos e sempre depois de
  separar a UF; um falso positivo aqui é exatamente o erro caro
  (`inventada→real`). Os 4 vizinhos a 1 dígito do dev mostram que a margem é
  de um único dígito.
* **Unificação pendente**: `base_canonica/digitos.py` e `classes.py` serão a
  implementação de `normalizacao.digitos_do_identificador`,
  `separar_uf`, `corrigir_ocr_em_numero` e `classe_processual_canonica`;
  detecção e índice devem chamar as **mesmas** funções.
