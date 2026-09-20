# ADR 0007 — Calibração da confiança por caminho de decisão

Data: 16/09/2026. Estado: aceita. Escopo: `src/caca_alucinacao/calibracao.py`,
`scripts/treinar_calibracao.py`, `tests/test_calibracao.py`, `dados/calibracao.json` (artefato
versionado, o único de `dados/` que viaja na imagem — ADR 0002).

## Contexto: o que a métrica faz com a confiança

Só os pares casados (IoU ≥ 0,5) com confiança entram: `y = 1` se o acerto foi pleno (mesma classe
e, em `real`, `id_canonico` certo), senão `y = 0`; `brier = média((c − y)²)`;
`b = clip(0,10·(1 − brier), 0, 0,10)`; `score_nível = s·(1 + b)`. Consequências:

* Para um caminho com acurácia verdadeira `p`, `E[(c − y)²] = c²(1 − p) + (1 − c)²p`, mínimo em
  `c = p` (valor `p(1 − p)`). A confiança ótima é a **acurácia do caminho**, não um valor de
  segurança.
* Com `n` observações e `a` acertos, `(a + 1)/(n + 2)` (regra de sucessão de Laplace = média a
  posteriori sob prior uniforme) nunca chega a 1,0: `n` acertos em `n` deixam `1/(n + 2)` de erro.
  O custo é assimétrico — cada erro futuro com `c = 1,0` soma 1 ao Brier; usar `c = 0,98` num
  acerto custa 0,0004. Em 100 pares com 1 erro, `c = 1,0` dá Brier 0,0100 e `c = 0,98` dá 0,0100
  também (99·0,0004 + 0,9604) — mas com 2 erros o teto já ganha, e o bônus máximo perdido pelo
  teto num caminho perfeito é 0,10·0,0004 = 0,00004 de score. **Teto 0,98** (docs/03 §9.4), piso
  0,05.
* O bônus vale ≤ 10 % de `s`: a calibração nunca muda a classe decidida.

## Decisões

1. **Tabela `{caminho: confiança}` com fallback hierárquico por prefixo**:
   `processo:1cand:cadeia_exata` → `processo:1cand` → `processo` → padrão 0,5. Caminhos novos
   herdam o prefixo mais específico presente; a tabela treinada inclui os prefixos (agregados dos
   filhos), logo o fallback é a acurácia **da família** e não um número arbitrário.
2. **`TABELA_INICIAL`** (priors, docs/03 §9.4 e docs/04 h.11): 0,98 para os caminhos com 100 % no
   dev (`1cand:cadeia_exata`); 0,95–0,97 para `0cand`, tabelas de súmula/dispositivo e `vaga`;
   0,5 para `duplicata` (estrutural: dois textos idênticos); 0,4–0,7 para chute, árbitro, OCR
   pesado, `classe_divergente`, `sem_correspondencia`. Usada quando `dados/calibracao.json` falta
   ou não tem o caminho.
3. **Achados amplos**: `caminho:amplo` é calibrado como caminho próprio quando há observações;
   sem valor específico, herda o do caminho estrito **multiplicado pela `forca`** (a acurácia de um
   padrão estrito superestima a de um padrão amplo). Não se multiplica duas vezes.
4. **Ajuste = Laplace generalizado com prior hierárquico**: para cada caminho observado e cada
   prefixo, `p = (a + k·p0)/(n + k)`, com `p0` = valor da tabela inicial (fallback hierárquico;
   0,5 se nada casa — aí é exatamente `(a + 1)/(n + 2)` com `k = 2`) e `k = PESO_PRIOR = 4`: o
   conhecimento de domínio vale quatro observações; `n = 0` devolve o prior; `n ≫ k` devolve a
   acurácia empírica; acertos nunca puxam um caminho abaixo do seu prior (a interpolação linear
   com Laplace centrado em 0,5, testada antes, fazia isso com 6/6 acertos). Piso/teto no fim.
5. **Fontes do treino** (`scripts/treinar_calibracao.py`, semente fixa, determinístico):
   `relatorio.json` do `avaliar.py` (`por_caminho`), `rastro.jsonl` do pipeline alinhado ao
   gabarito com as regras da métrica (IoU ≥ 0,5 guloso; espúrios = erro), o catálogo do dev e os
   sintéticos (resolução direta dos spans do gabarito). `--validacao` mede o Brier fora da amostra
   (nunca o seed de treino). Saída `{"tabela", "meta"}` com contagens, Brier antes/depois e fontes.
6. **Resultado gravado** — *histórico (17/09)*: treino = dev 192 + n2_dev 280 + n2 agressivo seed
   321 424; validação = n3_ood seed 7 288; Brier treino 0,0031 → 0,0008; validação 0,0039 → 0,0007.
   *Vigente (20/09, ver "Retreino reproduzível" abaixo)*: treino = 35 conjuntos no nível do
   pipeline (dev + n2_dev + n2_ag_treino + 32 adversariais = 4.004 decisões, acurácia 99,85 %);
   validação = `n3_ood` (288 decisões, **fora do ajuste**): Brier 0,0027 → 0,0014; treino
   0,0051 → 0,0018; dev 1,0999960. Caminhos sem observação permanecem nos priors (`duplicata`
   0,5, `llm_*`, `ocr_ambiguo` 0,6, `tribunal_incompativel` 0,7). Sub-caminhos raros com poucas
   observações ficam perto do prior.
7. **Revisão da rodada 1** (16/09): dois caminhos novos com prior de domínio, sem observação no
   dev — `processo:0cand:ocr_sem_dono` 0,90 (todas as letras convertidas pelo mapa inverso do
   gerador e a chave não tem dono: tão inventada quanto um `0cand` limpo, descontada a chance de
   uma confusão fora do mapa) e `dispositivo:fora_da_tabela:diploma_outro` 0,85 (diploma
   reconhecido mas não canonizado: pode ser OCR fora da tolerância). `ocr_reparado` mantém 0,88.
   Nos conjuntos adversariais da revisão (então não usados no treino) o Brier ficou ≤ 0,015;
   desde o retreino de 20/09 eles fazem parte do treino (e `n3_ood` é a validação).

## Revisão da rodada 2 (17/09)

- **`processo:duplicata` 0,5 → 0,8.** A métrica oficial documenta o `doc_ids` do gabarito como
  "conjunto aceito, separado por `:`" (ex.: `210631:210632`) — o formato existe para grupos de
  duplicatas. Se o gabarito cego listar todos os ids do grupo, a escolha determinística
  (menor `documento_id`) é sempre certa (p = 1); se listar um só, p = 0,5. Sob incerteza q
  sobre a política, a confiança que minimiza o Brier esperado é 0,5 + 0,5·q; com q ≈ 0,6
  (a existência do formato é evidência a favor) fica 0,8. O caminho não é observado em
  nenhuma fonte de treino (o dev não amostra duplicatas; nos sintéticos e no conjunto
  `r2_duplicatas` a política do gabarito é nossa, logo suas observações são excluídas do
  ajuste) — o valor é prior puro e `tests/test_calibracao.py` o mantém em [0,5; 0,85].
- **Treino com os conjuntos adversariais** (`--relatorio` dos 15 conjuntos de
  `dados/adversarial/`, além do catálogo do dev e dos sintéticos `n2_dev`/`n2_ag_treino`):
  Brier sob deslocamento caiu de 0,056–0,083 para ≤ 0,005 nesses conjuntos e de 0,0039 para
  0,0007 na validação fora da amostra (`n3_ood`, nunca treinada). Caminhos que eram
  subconfiantes com 100 % de acerto (`vaga:incompleta:amplo` 0,588 → 0,98,
  `1cand:tribunal_incompativel` 0,70 → 0,94, `classe_principal:amplo` 0,49 → 0,98,
  `0cand:ocr_ambiguo` 0,60 → 0,87) subiram pela evidência; os caminhos sem observação
  continuam nos priors. Novos priors: `sumula:*:ocr` e `dispositivo:*:ocr` 0,90.
- Reprodução: `PYTHONPATH=src python scripts/treinar_calibracao.py --sinteticos
  dados/sinteticos/n2_dev dados/sinteticos/n2_ag_treino --validacao dados/sinteticos/n3_ood
  --relatorio <relatorio.json de cada conjunto adversarial, sem os caminhos
  processo:duplicata/ambiguo_chute> --saida dados/calibracao.json`.

## Revisão da rodada 3 (17/09)

- **Sem treino nos caminhos "por política"** (R5-04): as observações de
  `processo:1cand:classe_divergente`, `processo:1cand:tribunal_incompativel`,
  `processo:multi:tribunal_incompativel`, `*:curto_classe_divergente`, `processo:0cand:ocr_ambiguo`,
  `processo:duplicata`, `processo:ambiguo_chute`, `processo:ocr_reparado:1cand:classe_divergente` e
  `sumula:fora_da_tabela:vinculante_tribunal_divergente` são ignoradas por `calibracao.ajustar`
  (`CAMINHOS_SEM_TREINO`), inclusive na agregação dos prefixos: nos sintéticos e adversariais a
  "verdade" desses caminhos é definida pela nossa própria política (classe divergente é `real`
  por construção; tribunal incompatível é `inventada` por construção), logo 9/9 acertos ali são
  evidência circular. Voltam aos priors: 0,75 / 0,70 / 0,70 / 0,60 / 0,60 / 0,80 / 0,40 / 0,85.
  Custo medido: `n3_ood` 1,09995 → 1,09983, `ruido_n2` 1,09981 → 1,09863, `r2_duplicatas`
  1,09859 → 1,09748 (só Brier; nenhum erro de classe).
- **Novos priors**: `processo:1cand:classe_divergente:sem_uf` 0,60,
  `processo:multi:curto_classe_divergente` 0,60, `processo:duplicata:classe_divergente` 0,50,
  `sumula:fora_da_tabela:vinculante_tribunal_divergente` 0,70.
- **`sumula:na_tabela:sem_tribunal` 0,85 → 0,95** (R3-14): `base.sumula(None, …)` só resolve
  quando o número é único na tabela fechada; a única incerteza é o gabarito anotar outro
  tribunal para o mesmo número.
- **`processo:duplicata` 0,8 é prior declarado** (R5-10): o formato `a:b` do `doc_ids` está
  documentado na métrica oficial, mas **nenhuma linha do dev o usa** (0/192); a justificativa
  da rodada 2 é uma hipótese sobre o gabarito cego, não uma observação. O valor fica como prior
  sem evidência; `tests/test_calibracao.py` o mantém em [0,5; 0,85].

## Revisão da rodada 4 (20/09)

- **Caminho-irmão sem o modificador antes de subir ao prefixo** (R6-15):
  `processo:ocr_reparado:1cand:uf_incompativel` herdava 0,978 de `processo:ocr_reparado:1cand`
  (≈ cadeia exata) — uma `inventada` por UF divergente após reparo de OCR saía com confiança de
  acerto pleno. `calibracao.chaves_de_consulta` intercala, para cada prefixo, o irmão sem os
  segmentos `ocr_reparado`/`llm_normalizou` (`MODIFICADORES`): `…:ocr_reparado:1cand:uf_incompativel`
  → `processo:1cand:uf_incompativel` (0,70) → `…:ocr_reparado:1cand` → `processo:1cand` → …
- **Priors coerentes com a classe emitida** (R4-03): `processo:1cand:classe_divergente:sem_uf`
  0,60 → 0,50 e `processo:duplicata:classe_divergente` 0,50, ambos agora emitindo `inventada`
  (ADR 0006): a confiança é a probabilidade da classe EMITIDA, não da hipótese rejeitada.
- **`vaga:incompleta:unica` 0,70 → 0,90** (R4-10): o caminho dispara sempre que (tribunal, ano,
  relator) tem 1 registro (17 % dos acórdãos da base); a classe emitida continua `incompleta` (o
  dev nunca anota `real` para vaga), logo 0,70 só ampliava o Brier. Registrado: as 32 vagas do dev
  têm multiplicidade ≥ 4 (P ≈ 5e-8 sob amostragem uniforme dos únicos) — o gerador evita únicos.
- **`processo:1cand:registro` sem `:sem_uf`** (R4-08): ver ADR 0006.
- `dados/calibracao.json` regenerada com os priors acima (`nota_rodada_4` no `meta`).

## Riscos

* Os sintéticos têm acurácia 100 % por construção nos caminhos frequentes: a tabela treinada
  satura no teto e o Brier no conjunto cego será maior que o medido aqui se o detector errar
  spans (isso entra na acurácia do caminho via `rastro`, não via catálogo). Retreinar com
  `--rastro` de uma rodada completa quando o detector estiver estável.
* Caminhos estruturalmente incertos (`duplicata`, `ambiguo_chute`) recebem evidência escassa e
  enviesada (nos sintéticos não há duplicatas textuais); `k = 4` limita o dano de acertos por sorte.
* `dados/calibracao.json` precisa ser regenerado sempre que o vocabulário de caminhos mudar
  (`make calibrar`); chaves desconhecidas caem no prefixo, então uma tabela antiga não quebra nada.

## Teto consolidado (20/09/2026)

**Contexto.** Com teto 0,98 em todos os caminhos, o dev pontuava 1,09996 (Brier 0,0004–0,0005
por nível): 100 % de acerto com confiança 0,98 custa (0,02)² por par. A evidência acumulada nas
quatro rodadas de revisão (dev + 2 sintéticos + 32 conjuntos adversariais = 4.292 decisões avaliadas
pela métrica oficial) mostrou vários caminhos com **centenas de decisões e zero erros**
(`processo:1cand:cadeia_exata`, `processo:0cand`, `vaga:incompleta`, `dispositivo:na_tabela`,
`sumula:na_tabela`, `dispositivo:fora_da_tabela`, `sumula:fora_da_tabela` e os prefixos que só
agregam filhos sem erro).

**Decisão.** `ajustar` concede um teto maior, `CONFIANCA_TETO_CONSOLIDADO = 0,998`, apenas ao
caminho com `n ≥ N_MINIMO_CONSOLIDADO = 100` decisões avaliadas **e nenhum erro** (um prefixo só
consolida se todos os filhos acertaram; `CAMINHOS_SEM_TREINO` nunca consolidam). Os demais
continuam em 0,98; priors nunca passam de 0,98; 1,0 continua proibido. `confianca()` aceita
valores até 0,998 vindos da tabela treinada.

**Por que é honesto.** A média a posteriori de Laplace com prior 0,98 e `k = 4` já passa de 0,999
em `n = 100` sem erros; 0,998 fica abaixo dela. Custo no Brier: um acerto a 0,998 custa 0,000004
(a 0,98 custava 0,0004); um erro custa 0,996 (a 0,98 custava 0,960) — a diferença por erro é
0,036, contra 0,0004 por acerto: o teto consolidado só perde para 0,98 se a acurácia real do
caminho no conjunto cego cair abaixo de ≈ 99 %, e mesmo aí a perda é de ~0,0005 no Brier.

**Consequências.** Dev 1,09996 → **1,10000** (1,0999975); Brier total de treino 0,0049 → 0,0017;
nenhuma classe muda (a calibração não altera decisões). O sub-caminho `tema:inventada` foi
dividido em `:repercussao` (forma do gabarito, 0,98), `:repetitivo` e `:solto` (apostas, priors
baixos) para que um conjunto adversarial de distratores de tema não rebaixasse a forma confirmada.

**Quando revisitar.** Se o conjunto cego mostrar erro em algum caminho consolidado, voltar esse
caminho a 0,98 (`N_MINIMO_CONSOLIDADO` maior ou lista de exclusão) e retreinar.

## Retreino reproduzível e validação fora da amostra (20/09/2026, correção)

**Problema encontrado.** A tabela gerada logo após o teto consolidado (v1.1) tinha sido treinada
com os 36 conjuntos — inclusive `n3_ood`, que esta ADR descrevia como validação — e `meta.validacao`
estava vazio; além disso, os 36 rastros usados tinham sido produzidos à mão, sem comando no bundle
que os regenerasse. A afirmação "validação fora da amostra" não valia para a tabela entregue.

**Correção.** `scripts/calibrar_completo.py` (`make calibrar-completo`, `GRAVAR=1` para gravar) é o
único caminho oficial de treino: regenera os sintéticos e os 32 conjuntos adversariais (seeds
fixas), roda o núcleo com `--rastro` em cada um, treina sobre **35** e mantém `n3_ood` **fora do
ajuste** como validação no nível do pipeline (`treinar_calibracao.py --validacao-rastro`, que
recusa um rastro presente nos dois lados). O `meta` passou a registrar `validacao` (n, acertos,
Brier antes/depois), `teto_consolidado`, `n_minimo_consolidado` e `caminhos_consolidados`;
`tests/test_calibracao.py` exige, na tabela versionada, validação não vazia e disjunta do treino,
Brier de validação não pior após o ajuste, e que todo caminho acima de 0,98 tenha ≥ 100 decisões
sem erro. Sem `--gravar`, o script compara a tabela reproduzida com a versionada e falha se
diferirem (caminhos ou contagens) — é a prova de reprodução.

**Efeito.** `sumula:fora_da_tabela` cai de 100 para 89 decisões sem `n3_ood` e perde o teto
consolidado (0,998 → 0,98); os demais 11 caminhos consolidados permanecem. Dev 1,0999975 →
**1,0999960**; nos 36 conjuntos a maior variação foi −0,0000048 (`r3_sumulas_forma`), τ = 0 em
todos. O limiar `N_MINIMO_CONSOLIDADO = 100` **não** foi rebaixado para recuperar o caminho: a
posteriori de Laplace com 89/89 ainda passa de 0,999, mas mudar o limiar depois de ver o resultado
seria ajuste ao dev.

**O que a calibração não pode provar.** A acurácia de treino é 99,85 % e a de validação 100 %:
a tabela aprende sobretudo *n* e o prior, não a taxa de erro real — é um limite superior. Os
conjuntos de treino e validação foram gerados pelo desenvolvedor e pelos revisores a partir da
mesma leitura dos dados; a única evidência independente virá do conjunto cego.

## Caminhos do extrator LLM treinados com o modelo real (20/09/2026, v1.2.4)

**Problema.** Até a v1.2.3 os caminhos `llm:extrator:*` ficavam nos priors (0,65–0,85): o retreino
oficial rodava o núcleo (`--arbitro nenhum`), e as decisões do `mock` nunca treinam esses caminhos
(ADR 0003). Com o árbitro ligado (medição 2), as 64 extrações do Qwen em `r6_extrator_formas` eram
todas certas e saíam com confiança 0,70–0,85 — Brier 0,031 nesse conjunto, contra 0,002 no resto.

**Decisão.** `scripts/calibrar_completo.py --cache-llm <cache_llm.jsonl da medição>` (`make
calibrar-completo CACHE_LLM=…`) roda os 38 conjuntos com `--arbitro transformers` **só do cache**
exportado da medição (`CACA_LLM_SOMENTE_CACHE=1`, zero chamadas, sem GPU, modelo e revisão de
`modelos/revisao_fixa.env`; o script falha se algum conjunto fizer uma chamada ou ficar sem cache) e
treina como antes — a única diferença é que o rastro passa a conter as extrações do modelo **real**,
única evidência admitida para `llm:*`. A tabela registra a proveniência em `meta.cache_llm` (SHA-256
do JSONL, modelo, revisão, extrações por conjunto) e só se reproduz com o mesmo arquivo (que
acompanha a submissão, como `dados/`; nunca é versionado — contém janelas dos documentos).
`tests/test_calibracao.py` exige que um caminho `llm:*` só saia do prior com `meta.cache_llm`
presente e nunca receba o teto consolidado.

**Validação fora da amostra dos caminhos `llm:*`.** Além de `n3_ood`, o script divide
`r6_extrator_formas` por documento (índices pares treinam, ímpares validam; `treino_holdout_llm.log`,
`meta.holdout_llm`) e falha se o Brier da metade de validação piorar. Resultado: 46 citações, 46
certas, Brier **0,0296 → 0,0044**. A tabela final é a do treino completo (37 conjuntos); o holdout é
diagnóstico. Limite do que isso prova: a metade de validação vem do mesmo gerador que a de treino —
mede que a estimativa não depende dos documentos escolhidos, não a precisão do extrator em texto
real (no dev e nos distratores ele emitiu 0; nos 26 documentos reais não há evidência de erro nem
de acerto).

**Efeito** (cache da medição 2, Qwen2.5-7B-Instruct `a09a354…`): 11 caminhos mudam, todos `llm:*`
(`llm:extrator:processo:1cand` 0,85 → 0,98 [27/27]; `:0cand` 0,70 → 0,94 [16/16]; `sumula` 0,80 →
0,938 [9/9]; `vaga` 0,75 → 0,938 [12/12]; `llm:extrator:dispositivo`, `:tema`, `:processo:multi`
sem observação, no prior); nenhum caminho do núcleo muda (mesmas contagens: o extrator é residual).
`r6_extrator_formas` com árbitro 1,06714 → **1,06991** (+0,00277; Brier 0,032 → 0,002); os outros 8
conjuntos medidos e o dev ficam **byte a byte idênticos** (0 emissões), e a `submission.csv` do dev
mantém o SHA-256 `a5f6b066…`. O ganho é pequeno por construção — o bônus de Brier vale ≤ 10 % do
score e só toca as citações que o extrator emite — e no conjunto cego será zero se ele não emitir;
o que muda é que, quando emitir, a confiança reportada reflete 64 decisões reais em vez de um chute.
Com a adoção do Qwen3.5-9B (v1.3.0, ADR 0003 "Medição 3") a tabela versionada passou a ser a treinada
com `saida_llm_q35/cache_llm.jsonl` (69 extrações reais, todas certas; holdout 51/51, Brier 0,0329 →
0,0044; `meta.cache_llm` com modelo, revisão, `quatro_bits` e SHA-256): em relação à tabela treinada com
o Qwen2.5 só `llm:extrator:processo` (0,979 → 0,98) e `:0cand` (0,94 → 0,948) mudam. Estado final:
`r6_extrator_formas` com árbitro 1,09983; dev e demais conjuntos byte a byte idênticos ao núcleo.
