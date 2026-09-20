# ADR 0005 — Detecção de spans: padrões estritos ancorados + padrões amplos com força baixa

Data: 16/09/2026. Estado: aceita. Escopo: `src/caca_alucinacao/texto.py`,
`src/caca_alucinacao/deteccao/` (`padroes.py`, `processo.py`, `vaga.py`, `sumula.py`,
`dispositivo.py`, `tema.py`, `distratores.py`, `fusao.py`, `__init__.py`), `tests/test_texto.py`,
`tests/test_deteccao.py`, `scripts/analise/medir_deteccao.py`.

## Contexto

A métrica alinha predição e gabarito por IoU ≥ 0,5 e cobra 1 FP por span espúrio e 1 FN por span
perdido; a classe errada custa duas vezes. `docs/03_analise_gabarito.md` mede, nas 192 citações do
dev, as fronteiras exatas (§1), todas as formas de superfície (§2), o ruído do nível 2 (§3), os
dispositivos (§4), súmulas/tema (§5), o cabeçalho e os distratores (§6). O detector precisa
reproduzir essa especificação com fronteira exata (o Brier e a resolução dependem do span certo) e,
ao mesmo tempo, não perder formas que o conjunto cego pode trazer (docs/05 §5, rótulos `ood:*`).

## Decisões

1. **Cabeçalho primeiro, por posição.** `texto.fim_do_cabecalho` devolve o início da primeira
   linha de prosa (≥ 60 caracteres, duas palavras minúsculas seguidas, não toda em caixa alta,
   não `Chave: valor`); nenhum span começa antes dele. Isso elimina os 39 distratores do
   cabeçalho (`Autos nº`, `Protocolo`, `Memorial`, `Valor da causa`, `PARECER JURÍDICO Nº`,
   `Referência: autos nº`) sem usar a forma do número (o cego pode ter CNJ "legítimos" no
   cabeçalho). Teto de segurança: se a heurística passar de 1.500 caracteres, tenta o limiar de
   30 e, falhando, considera o cabeçalho vazio — perder distratores custa menos que perder
   citações. Resultado: 26/26 documentos com fim entre 171 e 281 e antes do primeiro span.

2. **Uma regex estrita por família, construída de blocos** (`padroes.py`), compilada uma vez,
   com `re.VERBOSE` nas grandes. Todo branco é `\s{1,4}` (espaço, espaço duplo, NBSP, `\n`,
   `\n `), nunca `[ ]` nem `\s*` ilimitado. Quantificadores de repetição são limitados (cadeia
   ≤ 7 tokens hifenizados e ≤ 6 ligações; nome ≤ 6 palavras; janela do amplo ≤ 60/120 chars) para
   que a busca seja linear mesmo em textos patológicos (testado com 20.000 dígitos/pontos e
   6.000 siglas hifenizadas: < 1 s; documento de 4.000 chars: ≈ 4 ms).

3. **Estrito × amplo (o que é cada um).**
   - *Estrito* (`forca 1.0`, origem `regex:<familia>[:<molde>]`): ancorado numa **alternância
     fechada** de classes (`padroes.SIGLAS` gera, para cada sigla CamelCase, as formas exata, em
     caixa alta, com ponto entre segmentos — `R.Esp.`, `A.REsp`, `H.C.`, `Ag. Int.`, `AG.REG` — e
     ponto final; `padroes.EXTENSOS` gera os nomes por extenso com inicial maiúscula, tolerância a
     acento, caixa, quebra de linha entre palavras e ao OCR medido `e↔c`, `a→ã`, `i→l`, `m→rn`,
     `o→0`, `s→5`, `n→ri`); em súmula/tema/dispositivo a âncora é a palavra-chave (`Súmula`,
     `5UMULA`, `Súm.`, `Enunciado`; `Tem[aã]`; `art.`/`art`/`artigo`/`Art.`/`art.º`) e, no
     dispositivo, o diploma da alternância fechada (`padroes.DIPLOMA`: lei numerada, nome por
     extenso, sigla com ano). Na `vaga`, uma só regex cobre os moldes A–E do dev e F–H do gerador
     com as três âncoras obrigatórias: substantivo/classe, tribunal (exceto molde D, que tem
     classe), ano de 4 dígitos, fórmula de relatoria e nome próprio.
   - *Amplo* (`forca < 1`): `regex:processo:amplo` (0,5) = sigla desconhecida em caixa alta
     (2–6 letras) ou CamelCase (3–8, ≥ 2 maiúsculas), possivelmente após prefixos conhecidos, ou
     `Processo/Autos` + conector + número ≥ 4 dígitos; `regex:vaga:amplo` (0,6) = `ano … fórmula
     de relatoria + Nome` (≤ 60 chars) com tribunal até 120 chars antes e sem fim de frase entre
     eles, começando no substantivo/classe que precede o tribunal (ou no tribunal);
     `regex:tema:sem_complemento` (0,7) = `Tema N` sem `da repercussão geral`;
     `regex:dispositivo:amplo` (0,4) = `art. N` sem diploma reconhecível;
     `regex:processo:sigla_rara` (0,8) = cadeia da alternância fechada que `normalizacao` não
     canoniza (`Inq`, `ADO`, `Ext`). Só os amplos passam pelas regras negativas de contexto
     (`fls.`, `R$`, `OAB/UF`, `%`, `NNN/AAAA`, `Protocolo/Memorial/Ofício nº`, `Referência:`,
     datas); os estritos só pela zona do cabeçalho. Nenhum amplo dispara no dev nem nos sintéticos
     `dev` (0 espúrios); a resolução e a calibração usam a `forca` para descartar o que a base não
     confirma.

4. **Fronteiras exatas (docs/03 §1), uma regra por armadilha.**
   - Artigo anterior fora: a cadeia começa numa sigla/nome com maiúscula e há guarda `(?<![A-Za-zÀ-ÿ0-9/])`.
   - Pontuação final fora: nenhum bloco termina em `,`/`.` (o ponto de `REspe.` é interno à sigla).
   - Número: começa por dígito ASCII; letras de OCR só coladas a dígitos; um grupo depois de
     espaço/hífen precisa conter dígito (`- SP` nunca é engolido); exceção documentada: letra
     sozinha no lugar de um segmento de 1 dígito do CNJ (`2016 S 00 0000`), aceita só entre
     separadores e seguida de dígito, e corrigida antes de `digitos_do_identificador` (que a
     rejeitaria por "maioria de letras"). Um grupo separado por espaço não pode ser seguido de
     `/dígito` (`12/03/2022`).
   - UF: lista fechada das 27 siglas, com o separador (`/`, `/ `, `-`, ` - `, ` – `, ` — `, ` (`…`)`,
     `\n- `, `/\n`, espaço), `)` só se abriu `(`, nunca seguida de letra/dígito.
   - `processo nº`/`Processo n°` só entra quando seguido de `TST-`; `TST-` sempre entra.
   - Súmula até `do <T>` (inclusive `999\ndo STF`, `do\nSTF`, `/STJ`); tema até `da repercussão
     geral`; dispositivo até o fim do diploma (`da Lei nº 13.105, de 16 de março de 2015`,
     `Constituição\nda República`, `Lei Complemcntar\nnº 64/1990`, `CPC/2015`).
   - Nome do relator: 1–6 palavras com inicial maiúscula (partículas `de/da/do/dos/e` em qualquer
     caixa), `\n` permitido entre palavras, parando em `,`, `.`, palavra minúscula ou fim; lista de
     parada (`DJe`, `Turma`, `Seção`, `Plenário`) para citações completas fora do molde.
   - `AR 2019`/`RE 2020` (sigla de 2–3 letras + ano sem conector nem pontos) não é processo;
     `REsp 12` (menos de 4 dígitos sem conector) tampouco.

5. **Ordem e fusão.** `vaga → dispositivo → sumula → tema → processo` (estrito e amplo de cada
   família), depois `distratores.filtrar`, depois `fusao.fundir`: prioridade = maior `forca`,
   depois **span mais longo**, depois a ordem das famílias, depois posição; qualquer candidato
   que **interseque** um aceito é descartado (não só IoU ≥ 0,5 — o gabarito não tem spans
   aninhados). Regra extra em `detectar`: `vaga:amplo` sem substantivo/classe a menos de 40 chars
   de um processo/súmula/tema, sem `.;:` no meio, é a cauda de uma citação completa
   (`…/SP, 2ª Turma, STF, j. 2021, Rel. Min. X`) e cai. Saída ordenada por `(inicio, fim)`;
   `sem_sobreposicao` é verificado nos testes.

6. **`Achado.dados` (contrato com a resolução).** Todas as chaves existem sempre, como `str`
   (vazia quando não se aplica): `classe` (superfície da cadeia, sem `processo nº`/`TST-`),
   `cadeia` (siglas canônicas de `normalizacao.cadeia_de_classes`, ex. `"ED AGINT ARESP"`),
   `classe_principal`, `numero` (superfície, sem UF), `digitos` (`digitos_do_identificador`,
   CNJ → 20, registro → 12, curto como está), `formato` (`cnj20 | curto | registro | outro`),
   `uf`, `tribunal`, `ano`, `relator`, `artigo`, `diploma`, `numero_sumula`, `vinculante`
   (`"1"/"0"`), `numero_tema`. Observações que a resolução precisa saber:
   - `tribunal` **nunca é explícito no processo**: é `TST` quando há prefixo `TST-`, senão
     `normalizacao.inferir_tribunal` (segmento J do CNJ → TST/TSE/STM; classe exclusiva → STJ/STF/
     TSE/TST/STM; `Rcl`/`HC`/`MS`/`AR`/`RMS` → vazio). Na `vaga` é o tribunal explícito (sigla ou
     nome por extenso mapeado) ou o inferido pela classe do molde C/D; na súmula é o explícito ou
     `STF` se vinculante; no tema é `STF` (ou `STJ` com `recursos repetitivos`/`do STJ`).
   - `ano`: no processo, o do CNJ (`digitos[9:13]`) ou do registro (`digitos[:4]`); na `vaga`, o
     ano citado.
   - `relator`: nome como escrito, com brancos colapsados (`FULANA DE\nTAL` → `FULANA DE TAL`);
     comparar com `tolerante`/`relator_compativel`.
   - `diploma`: `normativos.diploma_canonico` (`CPC`, `CF`, `LC64`, `LEI-9504`, `DL-…`, `LC-…`);
     códigos identificáveis que a base não cobre recebem sigla própria (`CP`, `CPPM`, `CTN`,
     `CTB`, `ECA`, `LEP`, `LOMAN`, `LINDB`, `RISTF`…, `LEI-11340` para a Lei Maria da Penha) e
     qualquer outro diploma reconhecido pela regex recebe `OUTRO` — nunca vazio quando há
     diploma; vazio só no amplo `art. N` (→ `incompleta`). `artigo` são os dígitos após OCR e
     sem pontos (`3l2` → `312`, `1.026` → `1026`); incisos/§ ficam em `complemento`.
   - Chaves extras por família: processo `conector`, `prefixo_tst`; vaga `substantivo`, `molde`
     (`A`–`H`, `outro`); dispositivo `diploma_superficie`, `complemento`.
   - `origem` distingue estrito de amplo (`:amplo`, `:sem_complemento`, `:sigla_rara`) e o molde
     da vaga; `forca` alimenta a calibração (`calibracao.py` multiplica pela força quando o
     caminho não tem estatística própria) e o descarte de amplos sem respaldo na base.

7. **Medição integrada ao repositório.** `scripts/analise/medir_deteccao.py` replica o
   alinhamento oficial (IoU ≥ 0,5 guloso por maior IoU; EXTRA ≥ 90 % contida) e imprime recall,
   precisão, IoU médio, fronteira exata, família/tipo, cabeçalho, tempo e cada erro sem trechos
   completos (≤ 40 chars). `tests/test_deteccao.py` verifica as metas nos dados reais
   (`skipUnless(TEM_DADOS)`) e nos sintéticos quando existem.

## Resultados (16/09)

| conjunto | citações | recall (IoU ≥ 0,5) | espúrios | fronteira exata | família/tipo | ms/doc |
|---|---|---|---|---|---|---|
| dev (26 docs) | 192 | 192/192 | 0 | 192/192 | 192/192 | 4 |
| `n2_dev` (seed 123, 40 docs) | 280 | 280/280 | 0 | 280/280 | 280/280 | 4 |
| `n3_ood` (seed 7, 40 docs) | 288 | 288/288 | 0 | 288/288 | 288/288 | 4 |
| n3, seeds 1/2/3 (60 docs cada) | 429/425/454 | 429/424/454 | 0 | 428/424/454 | todos | 4 |
| n2 dev, seeds 101/102/103 | 423/419/423 | todos | 0 | todos | todos | 4 |

Pipeline completo (`cli --arbitro nenhum` + `scripts/avaliar.py`): dev 1,09996; `n2_dev` 1,09996;
`n3_ood` 1,09991 (máximo 1,10), τ = 0 em todos.

Erros residuais conhecidos (só em seeds extras dos sintéticos):
- Nome de relator terminado em partícula (`… Lima de`, artefato do recorte a 4 palavras do
  gerador): o span para antes do `de`; IoU 0,95, sem consequência na métrica.
- Nome de relator em minúsculas (`da relatoria de fulana de tal`): não detectado — sem a
  maiúscula não há fronteira segura para o fim do nome, e o gabarito/gerador nunca usam a forma.

### Resultados da rodada 2 (17/09) — pipeline completo, `avaliar.py` (máximo 1,10), τ = 0 em todos

| conjunto | antes | depois | | conjunto | antes | depois |
|---|---|---|---|---|---|---|
| dev (26 docs) | 1,09996 | 1,09996 | | `r2_chave_parcial` | 0,63975 (τ 12) | 1,09996 |
| `n2_dev` (seed 123) | 1,09996 | 1,09996 | | `r2_normativos_ruido` | 0,85279 | 1,09995 |
| `n3_ood` (seed 7) | 1,09991 | 1,09995¹ | | `r2_vagas_ordem` | 1,01210 | 1,09996 |
| `siglas` | 1,09954 | 1,09995 | | `r2_processos_forma` | 0,97205 | 1,09996 |
| `conectores` | 1,09996 | 1,09996 | | `r2_duplicatas` | 1,09174 | 1,09859 |
| `ruido_n2` | 1,09853 | 1,09981 | | `r2_listas` | 1,09996 | 1,09996 |
| `vagas` | 1,08315 | 1,08503 | | `r2_fora_da_base` | 1,08419 | 1,09996 |
| `distratores`/`frases`/`cabecalhos` | 1,09996 | 1,09996 | | `normativos` | 1,09990 | 1,09996 |

Os 6 erros restantes em `vagas` são nomes de relator em minúsculas (aceito, ver "Quando
revisitar"); a diferença de `r2_duplicatas` é só Brier (`processo:duplicata` a 0,8; ADR 0007).
¹ `n3_ood` regenerado com o gerador da rodada 2 (perfil agressivo injeta OCR letra↔dígito também
em súmula/tema/artigo/ano — `ood:ocr_fora_do_processo`, ADR 0004); o conjunto antigo, com o
código novo, também dá 1,09991 com 0 erros.

## Revisão da rodada 1 (16/09) — o que mudou nesta ADR

- **OCR no primeiro dígito** (R1-02): `AREsp n° l 150 231/RS`/`REsp l.234.567` passam a ser
  detectados (`padroes.PREFIXO_OCR`, 1–3 letras confundíveis coladas ao número, precedidas de
  branco/conector). A justificativa anterior ("custaria FN + FP") ignorava o reparo determinístico
  da ADR 0006 (`chaves_alternativas`), que converte a letra e consulta a base: dono único → `real`;
  nenhum → `inventada` com confiança 0,6 — exatamente o que o gabarito espera de um número
  inventado. A chave padrão fica vazia (núcleo ambíguo), nunca um número truncado.
- **Ano solto só sem UF** (R1-03): `AR 2019` continua descartado; `AR 2019/SP` é processo.
- **Grupo depois de branco** (R1-04): `_GRUPO_APOS_BRANCO` — um ano de 4 dígitos ou um caractere
  sozinho só entram se o número continua (CNJ com espaços), e nenhum grupo é seguido de ordinal
  (`2ª Turma`), `/dígito` ou `.dd.dddd` (datas).
- **Ordinal no meio da cadeia** (R1-05): `EDcl no 2º AgRg na Rcl` → `ED 2O AGR RCL`.
- **Números de 2–3 dígitos** (R1-07/R2-08): sem conector só com UF, nome por extenso (≥ 2
  palavras) ou classe de numeração curta (`ADPF 684`, `ADI 583`, `SL 12`).
- **OCR na sigla** (R2-02): `regex_sigla` gera classes com o dígito confundível em cada letra
  (nunca na primeira: `RE5P`, `ARE5P`, `Aglnt`; `e↔c` fica de fora para `Rel.` não virar `Rcl`), e
  `cadeia_de_classes` desfaz a confusão ao canonizar.
- **Súmula com OCR na palavra** (R2-03) e **fronteiras** (R2-07): `Súmulã`, `Súrnula`, `5UMULA`,
  `Vinculãnte`; `Súmula N da jurisprudência do T`, `Enunciado N da Súmula do T`, `verbete nº N da
  Súmula do T` (minúsculas só com conector/tribunal), `SV N`.
- **Moldes de citação vaga com outra ordem** (R2-06): `min_sem_rel` (`… de 2023, Min. Nome`, só
  colado à vírgula do ano), `parenteses` (`voto do relator Ministro Nome (T, ano)`),
  `parenteses_rel` (`precedente do T (Rel. Min. Nome, ano)`), `relator_antes_ano` (`acórdão
  relatado pela Ministra Nome em ano no T`). Partícula `dc` (OCR de `de`) no nome (R1-11).
- **Cabeçalho** (R2-09/R1-12-c): frases curtas de prosa (≥ 15 chars, terminadas em pontuação, ≥ 2
  palavras minúsculas) imediatamente antes da primeira linha longa contam como prosa; uma ementa
  em caixa mista sem prefixo seguida de `Autos nº`/`Chave: valor` continua cabeçalho; e, para o
  amplo `Processo/Autos nº`, um número igual ao do cabeçalho é distrator (`numero_do_cabecalho`).
- **Formas raras** (R1-12-a/R2-10): sufixo de incidente do STF depois do número (`RE 123.456
  AgR/SP` → `AGR RE`), `sob o nº`, UF colada à sigla antes do conector (`REsp/SP nº …`).
- **`art. N` solto** (R1-06/R2-05): o amplo de dispositivo continua existindo, mas a resolução o
  marca para descarte (ADR 0006 §8).

## Revisão da rodada 2 (17/09) — o que mudou nesta ADR

Três revisores independentes (correção, generalização, engenharia) mostraram que a robustez a
OCR letra↔dígito só existia nos números de processo e que várias formas plausíveis de citação
(redações de vaga, `REsp: N`, `inc.`, caixa alta na preposição) eram FN. Todas as correções são
regras GERAIS; nenhuma foi ajustada a um documento do dev. Conjuntos adversariais dos revisores
em `dados/adversarial/*` (scores em `## Resultados` abaixo).

- **Grupo numérico final só de letras confundíveis** (`Rcl 1.140.OSl/SP`; R4-01 crítica): a
  regex consome o grupo (1–4 letras colado por UM sinal de pontuação, nunca depois de branco,
  nunca igual a uma UF), `nucleos` marca o núcleo como ambíguo e a resolução só o lê pela
  conversão relaxada — o prefixo `1140` nunca vira chave. Grupos do meio aceitam 1–3 letras.
  `r2_chave_parcial`: 0,640 (τ = 12/30) → 1,09996 (τ = 0).
- **OCR no número da súmula, do tema, do artigo e do ano da vaga** (R4-02 crítica; R4-01/03
  do revisor 1): `Súmula 8l`, `SV l2`, `Tema l.234`, `art. 12G`, `art. l40`, `2O21` — letras
  confundíveis coladas ao número entram no span e são convertidas pelo mapa inverso do gerador
  (bijetivo); o span nunca para no prefixo (`Súmula 8` de `Súmula 8l` era classe errada). O
  ordinal `5o` continua ordinal (`o` minúsculo no fim não é OCR). O achado grava `letras_ocr`
  e a resolução usa o sufixo `:ocr` (confiança própria). No dispositivo estrito o número pode
  ser só letras (`art. g do Código Penal Militar`): o diploma garante a citação.
- **Palavras de ligação com OCR e caixa alta** (R4-03/R4-07): `d0`, `dã`, `DA`, `DO` na
  preposição do dispositivo e da súmula; `repercüssão` no complemento do tema.
- **Moldes de vaga** (R4-04/R4-11): ano antes do tribunal (`julgado de 2024 do TST, Rel. Min.
  X`), `Rel.ª Min.ª`/`Relª. Minª.`, `cujo relator foi o Ministro X`, `tendo como relator`,
  honoríficos entre a fórmula e o nome (`do e. Min. X`, `do Exmo. Min. X` — entram no span, não
  no nome), `(Rel. Min. X, j. 2023)`, `do STF (2023), Rel. Min. X`, órgão fracionário e verbo
  entre o substantivo e o tribunal (`acórdão da Corte Especial do STJ`, `entendimento firmado
  pelo TST`, `decisão proferida pelo STM`), `do Eg. STJ`. Todos com força 1,0 (três âncoras).
  `r2_vagas_ordem`: 29 FN → 0.
- **`vaga:amplo` sem substantivo nem classe** (R4-04 do revisor 1): tribunal + ano + relatoria
  em prosa corrente (`O STJ, já em 2019, pela relatoria do Min. X, assentou…`) sai com força 0,4
  e `sem_substantivo`; a resolução o descarta (custo: 1 FN se o gabarito anotasse essa prosa —
  no dev 32/32 vagas têm substantivo ou classe). Parêntese aberto no amplo é fechado quando o
  `)` segue o nome. Inícios de frase comuns depois de quebra de linha (`Quanto`, `Nesse`…)
  não entram no nome do relator.
- **Formas de processo** (R4-05/R4-15): dois-pontos depois da sigla (`REsp: 1.234.567/SP`,
  estilo de ementa `STJ - REsp: 1234567 SP, Relator: …`), `nº.` (ponto depois do ordinal),
  `T5T-`, `EMB.DIV.`/`Emb.Infr.` nas siglas, tribunal entre a classe e o conector (`Reclamação
  do STF nº 12.345` — tribunal explícito), registro do STJ depois da UF (`REsp 1.234.567 - SP
  (2019/0123456-7)` — entra no span e vira `registro_secundario`; R4-07), plural com
  enumeração (`REsps X/UF e Y/UF` → dois spans; o segundo herda a cadeia e exige UF), nomes
  de 2º grau (`Apelação Cível`, `Agravo de Petição`, `Recurso Inominado`, `Remessa
  Necessária` → inventada por não estarem na base; R4-12) e OCR no nome por extenso
  (`Recurso Espccial` → `RESP` por casamento tolerante nos aliases; R4-08).
- **Itens do dispositivo** (R4-06): `inc.`/`incs.`, alínea de uma letra sem aspas só depois de
  inciso romano (`I, g,`), `caput e § 8º`, `§ 8.º`, `parte final`/`in fine`/`primeira parte`,
  formas em caixa alta.
- **Súmula** (R4-09/10/13/16): `súmula`/`súm.` minúsculas com conector ou tribunal; item
  entre o número e o tribunal (`Súmula 999, IV, do TST`, `, item IV,`, `, § 1º,`) — **fronteira
  assumida** (o dev não tem itens): o item só entra quando o tribunal o segue; separadores
  `(STJ)`, `- STJ`, `, do STJ`, `do Eg. STJ`; `Enunciado N`/`Verbete N` seguido de órgão
  não jurisdicional (`do FONAJE`, `da I Jornada de Direito Civil`, `do CJF`) sai com força 0,5
  e é descartado — decisão registrada: o gabarito injeta citações das famílias medidas e um
  enunciado do FONAJE não é súmula de tribunal superior (custo máximo 1 FN por ocorrência).
- **`Relatório: …`/`Ementa: …` na primeira linha de prosa** (R4-09-a): um título de seção
  seguido de ≥ 60 caracteres de prosa é prosa, não `Chave: valor` do cabeçalho.
- **Testes** (R4-08 do revisor 1): `fronteira_exata == 192` sem folga; limites de tempo ×10.

## Revisão da rodada 3 (17/09) — o que mudou nesta ADR

Três revisores (correção, generalização, engenharia) mediram formas plausíveis fora dos moldes e
regras negativas ausentes. Regras GERAIS, nenhuma ajustada a documento do dev; conjuntos dos
revisores em `dados/adversarial/r3_*` e do engenheiro em `dados/adversarial/r4_*`
(`gerar_adversarial_r4.py`). Testes sintéticos em `tests/test_revisao_rodada3.py`.

- **Relator antes do ano, sem parênteses** (R5-01/R3-05, alta): molde `relator_antes_ano_virgula`
  (`acórdão do T, Rel. Min. X, j. 2021`, `…, de 2021`, `…, julgado em 2021`, `…, DJe 2021`,
  `decisão do T, Relator Ministro X, 2021`, `precedente do T, da relatoria do Ministro X, de 2021`,
  com data completa opcional `j. 12/03/2021`/`DJe de 3 de maio de 2021`); molde
  `tribunal_primeiro` (`STF, 2024, Rel. Min. X` — só com a fórmula abreviada `Rel. Min.`, que é
  de citação, não de prosa; o span começa no tribunal); molde `lavra_nome_antes` (`acórdão da
  lavra do Ministro X, STF, 2026`); `(Min. X)`/`(Ministro X)` entre parênteses logo depois do
  ano (`min_sem_rel`). Fórmulas novas em `RELATORIA`: `da lavra do Ministro`, `relatado por Nome`,
  `Rel. p/ acórdão Min.`, `Redator Ministro`, `cuja relatoria coube ao Ministro`, `Rel. o/a Min.`.
  O amplo ganhou a ordem inversa (`relatoria Nome … ano`, janela ≤ 40) e aceita o substantivo
  DEPOIS do tribunal (`o STJ, em acórdão de 2019 relatado pelo Ministro X`); o `<meio>` do
  amplo nunca atravessa um fim de frase (R5-09). `tribunal_primeiro` sem substantivo a ≤ 40
  chars de um processo é cauda de citação completa (mesma regra do amplo).
- **Caixa alta e OCR na vaga** (R3-06): `TRIBUNAL_SIGLA` aceita `5TJ`/`T5T`/`5TM` e a forma
  pontuada `S.T.J.` (`sigla_tribunal_canonica` desfaz); palavras de ligação (`DO`, `EM`,
  `PELA`, `DE`) e a fórmula (`REL. MIN.`, `MINISTRA`) em qualquer caixa; dígitos `0`/`1`/`5`
  dentro do nome (`J0se`). Uma vaga inteira em CAIXA ALTA dispara.
- **Nome do relator** (R5-07): ordinais (`Primeira`…`Décima`) e mais inícios de frase
  (`Não`, `Em`, `No`, `Este`, `Cabe`, `Há`, `De`, `Os`, `Com`, `Por`, `Se`, `Ementa`…) param o
  nome; partículas continuam entrando.
- **Súmulas no plural** (R3-03/R5-06, alta): `Súmulas N e M do T`, `Súmulas nºs N e M`, `Súmulas
  N/T e M/U`, `Súmulas N, M e P do T` viram **UM span por enumeração** (do `Súmulas` até o
  último tribunal), com o número do primeiro elemento (os demais ficam em `dados["enumeracao"]`).
  Decisão de fronteira (ambiguidade genuína, não medida no dev): o gabarito é gerado por
  inserção de um texto de citação com uma classe e um id — uma enumeração inserida é um span
  só; a métrica aceita `doc_ids` em conjunto (`a:b`), coerente com isso; e a mesma política já
  valia para `arts. X e Y do D`. Sob a hipótese contrária (um span por número) a perda é
  2 FN + 1 FP por enumeração; sob a hipótese adotada, emitir por número perderia 1 FN + 2 FP.
  Para processos (`REsp X/UF e Y/UF`) continua UM span por número: os números são longos e o
  primeiro span tem IoU ≥ 0,5 com a enumeração inteira, os demais são "extras contidos" —
  cobre as duas hipóteses. A enumeração só abre com a palavra no plural (`(?(plural)…)`):
  `Súmula 7, 1ª Turma` e `Súmula 7 e 8 anos` não enumeram.
- **Formas de súmula** (R3-08): tribunal entre a palavra e o número (`Súmula STJ 999`, `Súmula
  STJ nº 12`, `Súmula STJ/12`), `vinculante` em minúsculas (também `súmula vinculante 45` toda
  minúscula), tribunal por extenso entre parênteses, `do S.T.J.`, `, STJ`, `Verbete Sumular`,
  `Enunciado N da Súmula Vinculante do STF`, `verbete N da súmula do TST`, `do 5TJ` (R3-13).
- **Dispositivo** (R5-02, R3-04, R3-07): a palavra `art.` tolera o OCR medido (`artlgo`, `ãrt.`,
  `Art1go`), como `Súmula`/`Tema` já toleravam; enumerações com diploma no fim (`arts. X e Y,
  ambos do D`, `artigos X, Y e Z do D`, `art. X c/c o art. Y, ambos do D`, `arts. X e 1.022`)
  num só span com o primeiro artigo; `Lei Federal/Estadual/Municipal/Ordinária nº`; sigla do
  diploma **sem preposição** depois de vírgula ou espaço (`art. N, caput, CPP`, `art. N, CF/88`,
  `art N CF` — só com sigla, nunca com nome por extenso); siglas pontuadas (`C.P.C.`, `C.D.C.`,
  o ponto final entra); `Consolidação das Leis Trabalhistas` → CLT. O amplo `art. N` continua
  descartado pela resolução.
- **Regras negativas no ESTRITO de processo** (R3-01/R3-02, alta): uma sigla NUA de 2–3
  letras sem UF é distrator quando (a) precedida imediatamente por substantivo de ato
  normativo/administrativo (`Portaria MS nº`, `Resolução CC nº`, `Ofício AR nº`, `Instrução
  Normativa RE`, `Ato CC nº`; `IN`/`OS` só em caixa alta exata — `os EI nº …` é o artigo), ou
  (b) o número é seguido de `/AAAA` ou, com ≤ 5 dígitos, de `, de AAAA` (`RE 123456, de 2019`
  continua); classes citadas na base só por CNJ (família TST: `RR`, `AIRR`, `ARR`, `RRAg`,
  `ROT`, e `Ag`) com número de < 13 dígitos sem `TST-`/`processo nº` (`Ag. 1234` de agência)
  e `Ag` em contexto bancário (`conta`, `agência`, `Banco`, `c/c`). Cadeias com prefixo, UF
  ou nome por extenso nunca caem nas regras. As mesmas regras valem para o amplo.
- **Prefixo de tribunal** (R3-09): `STJ/REsp N/UF`, `STF/Rcl N` (o `/` deixa de barrar o início
  quando o que o precede é uma das cinco siglas; o prefixo fica FORA do span, como o artigo, e
  vira `tribunal_fonte = explicito`); `Apelação (STM) nº CNJ` (tribunal entre parênteses no
  meio, dentro do span).
- **Enumeração sem plural** (R3-12): `REsp X/UF e Y/UF` abre a enumeração quando o número
  seguinte tem o MESMO formato, UF, ≥ 4 dígitos e não é um ano.
- **Fronteiras** (R3-13): sufixo de incidente com hífen (`Rcl N-AgR/UF`), ligação `n0`/`nã`
  (OCR), UF com `S`→`5`/`O`→`0` (`/5P`, `/R0`; `uf_canonica` desfaz).
- **Cabeçalho** (R5-05, R3-10): uma linha longa em caixa mista que começa por classe + `nº` +
  CNJ (`Apelação Cível nº <CNJ> da Comarca de …, em que é apelante …`) nas 8 primeiras linhas é
  identificação dos autos (cabeçalho); um parágrafo de prosa **todo em caixa alta** conta
  como prosa quando tem ≥ 10 palavras, ≥ 30 % de palavras gramaticais, ≥ 7 palavras por frase
  e um sinal de oração (`QUE`, `SE`, `NÃO`, `É`, `-SE`) — uma ementa nominal (`PROCESSUAL
  CIVIL. AGRAVO INTERNO. …`) e um endereçamento (`EXCELENTÍSSIMO … DA COMARCA DE …`) não
  passam. Risco aceito: uma ementa verbosa em caixa alta sem o rótulo `EMENTA:` pode virar
  prosa (FP por citação da ementa); o dev não tem prosa em caixa alta e a rotulada
  (`EMENTA:`) continua `Chave: valor`.

Resultados (pipeline completo, `avaliar.py`, máximo 1,10, τ = 0 em todos):

| conjunto | antes | depois | | conjunto | antes | depois |
|---|---|---|---|---|---|---|
| dev (26 docs) | 1,09996 | 1,09996 | | `r3_atos_normativos` | 0,85878 | 1,09996 |
| `n2_dev` / `n3_ood` | 1,09996 / 1,09995 | 1,09996 / 1,09983¹ | | `r3_enumeracoes` | 0,77667 | 1,09996 |
| `r3_vagas_redacao` | 0,83737 | 1,09995 | | `r3_sumulas_forma` | 1,04863 | 1,09996 |
| `r3_dispositivos_forma` | 0,97811 | 1,09996 | | `r3_caps_corpo` | 0,70275 | 1,09996 |
| `r3_prefixo_tribunal` | 0,88580 | 1,09982 | | `r4_vagas_relator_antes` (R5-01) | — | 1,09996 |
| `r4_ocr_duplo` (R5-02) | — | 1,09996 | | `r4_cabecalhos_novos` (R5-05) | — | 1,09996 |
| `r4_negativas_vizinhas` | — | 1,09996 | | conjuntos r1/r2 | sem regressão (`vagas` 1,08503 = nomes em minúsculas) |

¹ Só Brier: os caminhos "por política" voltaram aos priors (ADR 0007, R5-04).

## Revisão da rodada 4 (20/09) — o que mudou nesta ADR

Três revisores (correção, generalização, engenharia; 36 achados) mediram formas plausíveis
ainda fora dos moldes. Regras GERAIS, nenhuma ajustada a documento do dev; conjuntos do revisor 2
em `dados/adversarial/r5_*`. Os geradores de TODOS os conjuntos adversariais agora são
versionados em `scripts/adversarial/` (R3q-06; sem nenhum número da base: consultas posicionais
ao índice, `artigo_k`/`sumula_k`, e formas com OCR montadas em tempo de execução) — `make
adversarial` regenera os 32 conjuntos e roda a métrica em cada um. Testes sintéticos em
`tests/test_revisao_rodada4.py` (42 testes).

- **CNJ com branco no lugar do ponto entre o ano e o segmento J** (R4-01, alta): `7000123-45.2023
  7.00.0000`, `…2016\n5.24.0091`, NBSP, espaço duplo. O grupo de 1 caractere depois do branco era
  rejeitado pela guarda anti-data (`d.dd.dddd` é a forma de `J.TR.OOOO`) e a chave parcial de 13
  dígitos virava `inventada` 0,98 (ou nenhum span, no TST). `_SEGMENTO_J_APOS_BRANCO` reconhece o
  caractere quando precedido de ano de 4 dígitos + branco e seguido de `.TR.OOOO`, ANTES da guarda;
  a guarda continua para `12.03.2022` depois do número.
- **Regra negativa `, de AAAA` mais específica** (R6-01/R4-02, alta): eliminava toda `Rcl` do STF
  (5 dígitos) e `RHC`/`HC`/`RMS` do STJ. Agora só elimina uma sigla NUA que é também órgão emissor
  (`_SIGLAS_DE_ORGAO`: `MS`, `CC`, `AR`, `RE`, `SS`, `CP`, `AI`, `PC`, `AC`…), com ≤ 3 dígitos, SEM
  conector e sem fórmula de relatoria depois do ano; `/AAAA` colado e substantivo de ato antes
  continuam eliminatórios. `Rcl 12.345, de 2024`, `AR 1.234, de 2015`, `MS nº 123, de 2015` e
  `MS 123, de 2015, Rel. Min. X` são processos; `Portaria MS nº 2.048, de 2002`, `Ato CC nº 1, de
  2015` e `MS 12, de 2015` não.
- **Enumerações com a classe no plural — política** (R6-02/R6-07/R3-12, alta): `REsps nºs X/UF e
  Y/UF`, `Recursos Especiais X/UF e Y/UF`, `Reclamações X/UF e Y/UF` (conector plural em `CONECTOR`;
  `EXTENSOS_PLURAL` como alias da mesma cadeia em `normalizacao`), `REsps X, Y e Z, todos do STJ` e
  `Rcls X e Y` (sem UF: só com o plural, ≥ 5 dígitos, mesmo formato e nunca um ano), `REsp nº X/UF e
  o nº Y/UF` (conector repetido). **Um span por número**, coerente com a política anterior para
  processos e DIFERENTE da de súmulas (um span por enumeração): cada número de processo é um
  identificador completo com UF/conector próprios, tem IoU ≥ 0,5 com o span da enumeração inteira
  (o primeiro) ou é "extra contido" (os demais) — cobre as duas hipóteses de gabarito; uma súmula
  enumerada partilha a palavra e o tribunal com as vizinhas, e o span por número (`83`) não teria
  IoU ≥ 0,5 com nada. `Rcls`/`HCs` são normalizados para a sigla (`cadeia_de_classes`).
- **OCR na palavra `Lei`** (R6-03, alta): `Lci nº 13.105/2015`, `Dccreto-Lci`, `Lci Complementar`,
  `Lci Fcderal` eram detectados mas `diploma_canonico` devolvia `OUTRO` → `inventada` 0,85.
  `normativos._corrigir_palavras_tipo` corrige `lei`/`leis` a UMA troca do mapa de confusões (3–4
  letras) e `federal`/`estadual`/`municipal`/`ordinaria` a 1 edição, como já fazia com `decreto`/
  `complementar`.
- **Enumeração de súmulas com dois tribunais** (R6-04, alta): `Súmulas N e M do STJ e K do
  TST` virava UM span com o tribunal do FIM (TST) → `inventada` 0,98. O span fecha no PRIMEIRO
  tribunal da enumeração (`Súmulas N e M do STJ`) e o que segue não é emitido (um span `K do
  TST` sem a palavra `Súmula` não tem forma de citação; se o cego anotar, é 1 FN, nunca τ).
- **Vagas com tribunal/ano DEPOIS do nome** (R6-05/R6-06, alta/média): moldes `nome_tribunal_ano`
  (`precedente da lavra do Ministro X, julgado pelo T em AAAA`, `voto condutor do Ministro X no T,
  em AAAA`) e `ano_nome_tribunal` (`julgado de AAAA da relatoria do Ministro X, do T`); `cujo
  relator, Ministro X,`; honoríficos `S. Exa.`/`Sua Excelência`/`V. Exa.`; separadores `;` e ` - `
  entre o ano e `Rel. Min.`; `da lavra do Min. X (T, AAAA)` (molde `parenteses`); `voto condutor`
  em `_SUBSTANTIVO`. R4-06 (baixa): data completa antes da fórmula (`julgado em 12/03/2015, Rel.
  Min.`) no molde principal; `Relator(a): Ministro(a)`; inicial abreviada (`J. Paciornik`).
- **UF com OCR e separador ` - `** (R6-08, alta): `REsp 1.234.567 - 5P` casava `…567 - 5` como
  número. `_FIM_NUMERO` proíbe o número de terminar antes de letra/dígito (salvo UF colada) e o
  `5P` vira UF (`uf_canonica` desfaz); `normalizacao.separar_uf` também aceita a UF com OCR. R4-09:
  uma letra fora do mapa colada ao número (`1.234.56A`) não casa em parte alguma — chave parcial
  nunca é emitida.
- **Dispositivo** (R6-09/R6-10/R4-07/R4-08): `Lei nº l3.105` (OCR no 1º dígito do número da lei);
  alínea de uma letra entre vírgulas sem inciso (`art. N, a, da CLT`) só quando o que segue é a
  preposição do diploma ou uma sigla; `Novo CPC`; `art. N, I e II, c/c o art. M da CLT` sem
  marca de diploma comum (`ambos/todos do`) → o span estrito recomeça no ÚLTIMO `art.` (o primeiro
  fica como amplo, descartado) — fronteira assumida: só o artigo ao qual o diploma pertence;
  `CF de 1988` e `Código de Processo Civil (Lei nº 13.105/2015)` entram no span; `Leis
  Trabalhistas` no detector.
- **`Enunciado N` de órgão não jurisdicional** (R6-11, média): `Enunciado N do CJF`/`da V
  Jornada` saía `real` (o número existe na tabela de súmulas) com 0,475. O achado leva
  `orgao_externo = 1` e a resolução o descarta SEMPRE (ADR 0006).
- **OCR `l`/`i` → `1`/`|` dentro do nome da classe** (R6-12, média): `Rec1amação`, `Recurso
  Espec1al`, `Agravo 1nterno` (`_ACENTOS`; a inicial continua literal).
- **Cabeçalho** (R6-13/R4-04): arquivo inteiro em linhas curtas (< 60 colunas) usa o limiar
  relaxado COM o recuo de frases curtas de prosa (antes descartava a súmula da 2ª linha); ementa
  longa antes do `ACÓRDÃO` (além de 1.500 chars) continua cabeçalho até 4.000 chars, senão o
  bloco de identificação (nunca mais 0 com cabeçalho presente); `Recorrente – Fulano de Tal,
  brasileiro…` (travessão) é cabeçalho; **uma só política para ementas**: uma linha com a forma
  de ementa (≥ 3 frases curtas nominais) é cabeçalho em qualquer caixa, com ou sem `EMENTA:`.
- **Nome do relator** (R6-14, baixa): depois de uma QUEBRA o nome só continua se a palavra
  seguinte não abre frase (`Importante`, `Houve`, `Brasília`, `Unânime`, `Julgamento`…); nunca
  uma palavra seguida de `:` nem pronominal (`Ressalta-se`); `e Outros` é rol de partes.
- **`Tema N` solto — aposta documentada** (R6-16, baixa): `Tema 1234` sem complemento é
  ambíguo (tema de repercussão geral ou item de sumário; o dev só tem `Tema N da repercussão
  geral`). Emite-se `inventada` (força 0,7 → confiança ≈ 0,69) **só com indício jurisprudencial na
  mesma frase** (`afetado`, `repercussão`, `repetitivo`, `STF`/`STJ`, `tese`, `julgamento`,
  `precedente`…); sem indício a força cai a 0,4 e a resolução descarta. `Tema Repetitivo N` tem
  complemento (força 1,0; STJ). Se o cego não anotar temas soltos, cada emissão é 1 FP
  `inventada` (nunca τ); se anotar, cada descarte seria 1 FN — o indício decide pelo lado mais
  provável em cada frase. `r5_distratores_orgaos` (1,02663) mede exatamente essa aposta: os 6
  "erros" são `Tema 1234`/`Tema Repetitivo 988` que o revisor construiu como não-citação numa
  frase com `afetados`.
- **`vaga:amplo` como cabeça de citação numerada** (R4-05, média): `O acórdão do STJ … em 2019,
  sob a relatoria do Ministro X (REsp N/UF)` emitia a vaga amplo E o processo. A vaga amplo cujo
  fim está a ≤ 5 caracteres (só brancos e `(`) do início de um processo/súmula/tema é a mesma
  citação — o número é o span (regra simétrica à da cauda).

Resultados (pipeline completo, `avaliar.py`, máximo 1,10, τ = 0 em todos; "antes" = medição dos
revisores sobre a rodada 3):

| conjunto | antes | depois | | conjunto | antes | depois |
|---|---|---|---|---|---|---|
| dev (26 docs) | 1,09996 | 1,09996 | | `r5_vagas_lavra_final` | 0,95550 | 1,09996 |
| `n2_dev` / `n3_ood` | 1,09996 / 1,09983 | 1,09996 / 1,09983 | | `r5_processos_plural_nos` | 0,56984 | 1,09996 |
| `r5_normativos_ocr` | 0,40004 | 1,09996 | | `r5_processos_ocr_combo` | 0,67447 | 1,09943 |
| `r5_distratores_orgaos` | 0,99414 | 1,02663¹ | | `r5_layouts` | 1,09666 | 1,09996 |
| 26 conjuntos r1–r4 | 1,085–1,09996 | sem regressão (`vagas` 1,08503 = nomes em minúsculas) | | | | |

¹ Só a aposta dos temas soltos (acima); nenhum erro de classe fora dela.

## O que foi rejeitado

- **Shape + validação pela tabela de aliases** (qualquer token CamelCase + `cadeia_de_classes`):
  daria precisão dependente de aliases privados de `normalizacao` e fronteiras difíceis de
  explicar. A alternância fechada gerada de listas explícitas é auditável; o amplo cobre o resto.
- **Uma regex por molde de vaga**: uma só regex com âncoras obrigatórias generaliza para F–H e
  para variações de OCR sem multiplicar casos.
- **Fusão só por IoU ≥ 0,5**: dois spans com interseção pequena seriam ou o mesmo identificador
  ou erro; descartar toda interseção é mais seguro e o gabarito confirma (0 spans sobrepostos).
- **Regras negativas para os estritos** (datas, `fls.`): a âncora de classe já as exclui; regra
  a mais só criaria falsos negativos.

## Quando revisitar

- Se o cego trouxer citações completas com relator após o número (`REsp …/SP, Rel. Min. X, DJe
  …`), rever a regra da cauda (hoje só para `vaga:amplo` sem substantivo) e medir.
- Se aparecer `Lei nº X, art. Y` (lei antes do artigo) ou enumerações (`arts. 8º e 9º da CF`
  como dois spans; `REsp X e AREsp Y`), o gabarito decide a fronteira — hoje enumerações de
  artigos ficam num só span e enumerações de processos viram dois spans. **Risco conhecido
  (rodada 2, R4-09-b):** `Lei nº 8.078/90, art. 14` produz só o amplo `art. 14`, descartado
  (1 FN por ocorrência); não foi corrigido às cegas porque a fronteira (`Lei…` incluída ou
  não) não está medida — se o cego trouxer a forma, medir e decidir.
- Se o cego trouxer nomes de relator em minúsculas (`da relatoria de fulano de tal`), o molde
  exige inicial maiúscula (6 FN em `adv_vagas`, aceitos: em minúsculas qualquer sequência de
  palavras casaria).
- `REsp X e Y/UF` sem plural: desde a rodada 3 o segundo número (mesmo formato, com UF) também é
  span próprio; com a classe no plural (`REsps nºs X/UF e Y/UF`, `Rcls X e Y`) idem, desde a rodada 4;
  enumerações de súmulas são um span só (ver "Revisão da rodada 3" e "rodada 4") — se o cego
  anotar súmulas por número, inverter a política e medir.
- Se o padrão amplo de processo gerar espúrios no cego (siglas de órgãos, `Processo nº` no corpo),
  baixar `forca` para 0,3 ou exigir UF/CNJ; a calibração já rebaixa a confiança.
- Se o cabeçalho de alguma peça tiver prosa longa antes do título (ementa em caixa mista),
  `fim_do_cabecalho` cairá cedo demais e um CNJ de `Autos nº` pode virar candidato amplo; a
  resolução (0 candidatos + `forca` 0,5) o descarta.
