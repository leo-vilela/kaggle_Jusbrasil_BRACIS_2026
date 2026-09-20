# ADR 0006 — Resolução: classe por cardinalidade da consulta, filtros e desempates

Data: 16/09/2026. Estado: aceita. Escopo: `src/caca_alucinacao/resolucao.py`,
`scripts/analise/medir_resolucao.py`, `tests/test_resolucao.py`; generalizações de parsing em
`base_canonica/normativos.py` (súmula/dispositivo, ver §5).

## Contexto

A classe de uma citação é função determinística da consulta por identificador à base fechada
(docs/00 §1). A especificação medida está em docs/04 (h.1–h.11) e docs/03 (§9.3): 77/77 `real` de
processo têm dígitos idênticos ao número próprio do registro; 0/42 `inventada` têm número próprio;
32/32 `incompleta` são citações vagas; 40/40 súmulas/dispositivos resolvem pelas tabelas derivadas.
A base tem 77 grupos de números próprios ambíguos (16 % dos registros; docs/04 b), que o dev
quase não amostra mas o conjunto cego pode amostrar. Os custos da métrica (docs/00 §2) são
assimétricos: `inventada→real` custa FN + FP + τ; `real` com id errado custa 1 FP; `incompleta`
num gabarito `real` custa FN + FP.

## Decisões

1. **Chave primária = dígitos canônicos; só donos.** `candidatos_por_numero` (índice de números
   próprios). Nunca FTS/BM25, nunca casamento aproximado de dígitos, nunca dígito→dígito. 0
   candidatos ⇒ `inventada` (`processo:0cand`); 1 ⇒ `real`; ≥ 2 ⇒ filtros e desempates.
2. **Tribunal e UF são eliminatórios só quando certos.** Tribunal "certo" = explícito no span
   (`TST-`, sigla) ou segmento J do CNJ (5/6/7). A inferência **pela classe** (`REsp`→STJ) só
   elimina um candidato cuja classe própria não é sequer compatível com a citada (`RCL` ≠ `RESP`):
   um `Recurso Especial` com número de um `REspe` do TSE é a mesma classe em outra nomenclatura
   (`RESP≈RESPE`, docs/04 h.2) e continua `real` com confiança rebaixada. UF citada ≠ UF própria
   conhecida elimina (`uf_incompativel`); registros sem UF (TST, 62 STM, 3 TSE) são mantidos e, entre
   os restantes, a UF confirmada é um **desempate** (`multi:uf_confirmada`). Medido: nenhum
   identificador próprio da base infere um tribunal diferente do seu registro (0/1.208).
3. **Classe só desempata, nunca elimina** (docs/04 d: 2/77 `real` do dev têm cadeia diferente da
   própria; nos sintéticos OOD, 23/23 `classe_divergente` são `real`). Ordem: cadeia exata →
   classe principal → classe compatível (equivalências entre eras e a família TST) → registro do
   STJ citado junto com o número → UF confirmada. Com 1 candidato, a relação de classe só define
   o sub-caminho (`cadeia_exata` 0,98 … `classe_divergente` rebaixado). Exceção: chave **curta**
   (≤ 3 dígitos, `Nº 42`) com classe divergente ⇒ `inventada` (docs/04 c: colisões de 2–3 dígitos
   são onipresentes). Ordinais que sobram **depois** da classe principal (`44O` = número com OCR
   lido como ordinal) são removidos da cadeia antes da comparação.
4. **Duplicatas: chute determinístico, não `incompleta`.** Restando ≥ 2 candidatos com cabeçalho
   (600 chars, espaços colapsados) idêntico **ou** mesmos tribunal/ano/relator/cadeia (versões da
   mesma decisão com prefixo de exportação diferente — 10 dos 77 grupos), escolhe-se o menor
   `documento_id` (`processo:duplicata`, confiança ≈ 0,5). `incompleta` custaria FN + FP com
   certeza; o chute custa 1 FP em ~50 % dos casos. Candidatos distintos (cabeçalho e metadados
   diferentes) vão ao árbitro (`escolher_candidato`, ADR 0003) ⇒ `processo:llm_escolha`; sem
   árbitro/abstenção ⇒ menor `documento_id` (`processo:ambiguo_chute`, ≈ 0,4).
5. **OCR que a normalização recusa: reparo determinístico antes do árbitro.** A normalização
   (ADR 0001) exige dígito ASCII no início do núcleo e rejeita grupos com maioria de letras; por
   isso `l.234.567`, `G2.471` e `2016.S.18` (segmento J do CNJ) ficam com chave errada e 0
   candidatos. `chaves_alternativas` converte **só letras** (1–3 letras confundíveis coladas antes
   do 1º dígito, precedidas de espaço/conector/início — nunca uma sigla como `AI12345`; letra
   isolada entre dois grupos numéricos do mesmo núcleo) e reconsulta; uma única alternativa com dono
   resolve (`processo:ocr_reparado:…`), zero mantém `inventada`, várias ficam ambíguas. Como o mapa
   de OCR é o inverso do gerador do desafio, a alternativa é o número original ou nada — não pode
   produzir um `inventada→real` por número diferente. Gatilhos do árbitro (`normalizar_citacao`):
   dígitos vazios, ou 0 candidatos com ≥ 1 letra **não convertida** ou ≥ 2 letras convertidas;
   sem árbitro/abstenção ⇒ `processo:0cand:ocr_ambiguo` (calibrado à parte).
6. **Número + registro do STJ**: o número manda (docs/04 h.4); o registro só desempata e, se o
   número não tem dono mas o registro tem, `processo:0cand:registro_diverge` (inventada, confiança
   menor). Registro citado sozinho resolve (`processo:1cand:registro`).
7. **Súmula**: `(tribunal, vinculante, número)`; `Vinculante` ⇒ STF (tribunal explícito diferente é
   ignorado com log); sem tribunal e sem vinculante ⇒ só se o número for único na tabela; tribunal
   explícito diferente ⇒ `inventada` (`fora_da_tabela:tribunal_divergente`); sem número ⇒
   `incompleta`. **Dispositivo**: `(diploma canônico, artigo)`; diploma sintético `LEI-…`/`DL-…`/
   `LC-…` ⇒ `inventada` (`diploma_fora_da_base`); artigo com um nome de diploma no span que não
   reconhecemos (`Código Penal`) ⇒ `inventada` (`diploma_desconhecido`: identificável e fora da base
   fechada); sem diploma algum ⇒ `incompleta`; sem artigo ⇒ `incompleta`. **Tema** ⇒ `inventada`.
   **Vaga** ⇒ `incompleta` sempre; `por_relator_ano` só alimenta `detalhes["multiplicidade"]` e os
   sub-caminhos `:sem_correspondencia` / `:unica` (calibrados mais baixo; docs/04 f mostra que 1
   registro nunca ocorre no dev).
8. **Achados amplos (`forca < 1`)**: mesma lógica, caminho com sufixo `:amplo` (a calibração
   multiplica pela força quando não há valor específico) e, se a base **não confirma** o achado
   (`inventada` por ausência, vaga com multiplicidade 0, ou `art. N` sem diploma —
   `dispositivo:sem_diploma`, `incompleta`) e `forca < 0,7`, `detalhes["descartar"] = "1"`.
   Raciocínio: P(citação | amplo, sem respaldo) ≈ 0,5; emitir custa 1 FP se não for citação,
   omitir custa 1 FN se for — mas um FP de `inventada` ainda arrisca τ zero e polui a precisão de
   uma classe com suporte pequeno, e o detector pode subir a força quando a forma for reconhecida.
   Para `art. N` solto (revisão R1-06/R2-05): o dev não anota artigo sem diploma e a classe
   `incompleta` tem suporte ≈ 15/nível — 12 FP num conjunto adversarial custavam 0,12 de score;
   omitir custa no máximo 1 FN se o cego anotar essa forma. A forma anafórica (`art. 927 do
   mesmo diploma`) também é omitida: resolvê-la exigiria rastrear o diploma da citação anterior,
   e o gabarito não dá evidência de como a anota. **O pipeline omite as decisões com
   `descartar == "1"`** (`pipeline.py`, rastro `descartada:resolucao`; coberto por
   `tests/test_pipeline.py`/`test_revisao_rodada1.py`).
9. **`Decisao.candidatos`** = ids considerados (ordem de `documento_id`); `detalhes` (só strings)
   traz dígitos/formato, cadeia citada × própria, UF, tribunal e sua fonte (`explicito`/`cnj`/
   `classe`), filtros aplicados com contagens, restantes, o que o árbitro fez e o reparo de OCR.
10. **Contrato**: `resolver(achado, base, arbitro=None, contexto=None)`. `contexto` é a janela para
    o árbitro; na falta, `achado.dados["contexto"]` e por fim o trecho. Exceções do árbitro nunca
    sobem (abstenção). `dados` do detector (`digitos`, `cadeia`, `uf`, `tribunal`, `numero_sumula`,
    `vinculante`, `diploma`, `artigo`, `ano`, `relator`) são usados quando válidos e recalculados
    do trecho quando faltam — detector e resolução chamam as mesmas funções de `normalizacao`.

## Revisão da rodada 1 (16/09) — o que mudou nesta ADR

- **Chave parcial nunca** (R2-01): um número com um grupo de maioria de letras confundíveis
  (`1.GO1.157`), um segmento só de letras (`7.OO.0000`) ou letras no lugar do primeiro dígito
  (`G2.471`) produz `Nucleo.ambiguo` com `digitos == ""` — antes, `nucleos` fechava o núcleo e
  reabria no dígito seguinte, montando chaves de 4–5 dígitos na faixa dos sequenciais do STF/STJ
  (mecanismo de `inventada → real`). A resolução tenta `chaves_alternativas` — `letra_no_meio`,
  `letra_inicial` e a nova **conversão relaxada** de todas as letras (`relaxado`) — e só aceita
  uma alternativa com **um** dono (`processo:ocr_reparado:…`, conf. 0,88); sem dono após converter
  todas as letras, `processo:0cand:ocr_sem_dono` (0,9 — tão inventada quanto um `0cand` limpo, já
  que o mapa é a inversa do gerador); sem dígitos ou com duas alternativas com dono,
  `processo:0cand:ocr_ambiguo` (0,6). É seguro para τ porque `CONFUSOES` é a inversa bijetiva das
  trocas do gerador (l→1, O→0, S→5, g→9, G→6): converter uma letra recupera o dígito original,
  e um número inventado continua sem dono.
- **OCR no primeiro dígito é detectado** (R1-02): `padroes.NUMERO` aceita 1–3 letras confundíveis
  coladas antes do primeiro dígito (`REsp l.234.567`, `Rcl G2.471`); o reparo `letra_inicial`
  deixou de ser código morto (teste ponta a ponta).
- **Tribunal pela classe não é eliminatório** (R2-11): o detector grava `dados["tribunal_fonte"]`
  (`explicito` só com prefixo `TST-`; `cnj`; `classe`) e `extrair_processo` só trata como
  explícito o que o detector marcou assim ou o que está escrito no span. `Recurso Especial nº
  <n>` com número de um REspe do TSE continua `real` (item 2).
- **Súmula Vinculante**: o detector não grava mais `tribunal = STF` implícito; a resolução infere
  (`sumula:na_tabela:tribunal_implicito`, chave calibrada própria) — R1-08.
- **`dispositivo:fora_da_tabela:diploma_outro`** (R2-04): diploma reconhecido pela regex mas não
  canonizado (Resolução, Portaria… ou OCR fora da tolerância) → `inventada` com confiança 0,85, não
  0,98. A tolerância de `tolerante()` passou a aceitar **uma** troca do mapa de confusões em
  palavras de 3–4 letras (`Lcis` = `Leis`); `dc` ≠ `de` continua.

## Revisão da rodada 2 (17/09) — o que mudou nesta ADR

- **Grupo final só de letras confundíveis** (R4-01 crítica): `_regiao_numerica` inclui o grupo
  (≤ 4 letras, colado por um sinal de pontuação) e `chaves_alternativas` só oferece a conversão
  `relaxado` do número inteiro (`1.140.OSl` → `1140051`); a chave padrão é vazia (núcleo
  ambíguo, ADR 0001). Com dono → `processo:ocr_reparado:…` (real); sem dono →
  `processo:0cand:ocr_sem_dono`/`ocr_ambiguo` (inventada). O prefixo nunca é consultado.
- **Sufixo `:ocr`** em `sumula:na_tabela`, `sumula:fora_da_tabela`, `dispositivo:na_tabela`
  e `dispositivo:fora_da_tabela` quando o detector converteu letras confundíveis no número
  (`letras_ocr`): mesma classe, confiança calibrada à parte (priors 0,90; treinados a 0,96–0,98
  nos adversariais, ADR 0007).
- **`vaga:amplo` sem substantivo nem classe** (`sem_substantivo == "1"`) entra em
  `_marcar_amplo` como "não confirmada" e é descartado (força 0,4 < 0,7), como o dispositivo
  amplo; `regex:sumula:orgao_externo` (força 0,5, `Enunciado N do FONAJE`) idem.
- **Tribunal explícito no meio do span** (`Reclamação do STF nº N`): o detector marca
  `tribunal_fonte = explicito` e o filtro de tribunal é eliminatório, como para `TST-`.
- **Registro depois da UF** (`REsp N - UF (AAAA/NNNNNNN-D)`): o detector grava `registro` e o
  span inteiro chega à resolução, que já derivava `registro_secundario` de `nucleos` — os
  caminhos `0cand:registro_diverge` e `multi:registro` (docs/04 h.4) passam a ser alcançáveis.
- **Fallback do resolvedor nunca trunca** (R4-02, fechamento): quando o achado chega SEM os
  dados do detector (span devolvido pelo árbitro em `classificar_span`; medição a partir do
  gabarito em `medir_resolucao`), `_resolver_sumula`/`_resolver_dispositivo` leem o número do
  trecho com `normativos.sumula_canonica`/`artigo_canonico`, que liam só o prefixo numérico
  (`Súmula 8l` → 8, `art. 5o` → 50). Agora o grupo do número admite letras de OCR com guarda
  `(?![\dL])` e `normativos.numero_com_ocr` (compartilhado com o detector) devolve o número
  inteiro ou `None` (→ `sumula:sem_numero`, incompleta): `8l` → 81, `1O` → 10, `lO` → nada; o
  `o` minúsculo final é ordinal. Encontrado pelo teste `test_sinteticos_se_existirem` no n3_ood
  regenerado com `ood:ocr_fora_do_processo` (ADR 0004).

## Revisão da rodada 3 (17/09) — o que mudou nesta ADR

- **Chave curta com classe divergente, antes do atalho de duplicatas** (R3-11): a proteção
  "≤ `DIGITOS_CURTOS` dígitos + classe principal divergente ⇒ inventada" passa a valer também com
  ≥ 2 candidatos quando TODOS são de classe divergente (`processo:multi:curto_classe_divergente`),
  ANTES de `sao_duplicatas` — `HC nº 87` num grupo de `QO CautInom` e `MS 1662` num grupo de `RO`
  eram `real` 0,8 pelo atalho. `DIGITOS_CURTOS` sobe de 3 para **4**: com 4 dígitos a colisão de
  um número perturbado com um número existente de outra classe é frequente demais (a base tem
  ~1.000 números; o espaço de 4 dígitos é 9.000) e uma citação real com a classe errada nunca foi
  observada (as 2/77 do dev são classes compatíveis). Um grupo duplicado cuja classe própria
  diverge da citada com ≥ 5 dígitos continua `real`, mas em `processo:duplicata:classe_divergente`
  (prior 0,5). **Superado na rodada 4 (R4-03): passa a `inventada`.**
- **`classe_divergente` sem UF nem tribunal certo** (R5-04): `Rcl/HC/MS NN.NNN` com o número de
  outra classe continua `real` (número manda), mas em `processo:1cand:classe_divergente:sem_uf`
  (prior 0,60, nunca treinado): só o número sustenta a escolha. **Superado na rodada 4 (R4-03): passa a `inventada`, prior 0,50.**
- **Súmula Vinculante com tribunal explícito ≠ STF** (R5-08): `Súmula Vinculante N do STJ` → `inventada`
  (`sumula:fora_da_tabela:vinculante_tribunal_divergente`, prior 0,70), como docs/04 h.8 já
  dizia; a exceção "Vinculante implica STF" (§7 da rodada anterior) foi retirada porque um
  inventada→real custa FN + FP + τ e um real→inventada só FN + FP.
- **Enumeração de súmulas**: um span, resolvido pelo primeiro número (ADR 0005, rodada 3).

## Revisão da rodada 4 (20/09) — o que mudou nesta ADR

- **`classe_divergente` sem UF/tribunal e duplicata de outra classe ⇒ `inventada`** (R4-03,
  média). A rodada 3 emitia `real` em `processo:1cand:classe_divergente:sem_uf` (prior 0,60) e
  `processo:duplicata:classe_divergente` (prior 0,50) — "número manda". O revisor mediu no
  `kaggle_metric.py`, com a submissão perfeita do dev, o custo de cada erro: inventada→real
  Δ −0,0091 (N1) / −0,0187 (N2) contra −0,0034 / −0,0073 de real→inventada — razão ≈ 2,6 — logo
  emitir `real` só compensa quando P(real) > ≈ 0,73, em qualquer confiança. Com P(real) estimada
  em 0,5–0,6 pelos nossos próprios priors, a decisão de menor custo esperado nesses dois
  sub-caminhos é `inventada`, e a confiança 0,5 declara a incerteza (coerente com a classe emitida,
  como pede o Brier). `processo:1cand:classe_divergente` COM UF (ou tribunal) confirmada continua
  `real` (prior 0,75 > 0,73 por pouco; a UF é evidência positiva). **Evidência disponível e seus
  limites**: o rastro do dev não tem NENHUMA decisão `classe_divergente` (as 2/77 citadas na
  rodada anterior são `classe_principal`/`classe_compativel`, intocadas); os "23/23 reais" dos
  sintéticos são construção do nosso gerador (circular); perturbar 1 dígito dos 391 números
  sequenciais da base gera 78 colisões (68 mesma classe, 10 divergentes) — a colisão existe, mas é
  rara. A decisão repousa na assimetria de custos da métrica, não numa frequência observada; se o
  cego mostrar reais com classe divergente sem UF, inverter é trocar duas linhas
  (`_decidir_entre_candidatos`) e o prior.
- **`Enunciado N` de órgão externo nunca é súmula** (R6-11): `_marcar_amplo` descarta o achado com
  `dados["orgao_externo"] == "1"` independentemente da classificação (antes só quando a decisão
  era `inventada`, e o número existente na tabela dava `real` com id de outro tribunal).
- **Registro do STJ manda** (R4-08): `processo:1cand:registro` não recebe mais `:sem_uf` — um
  registro `AAAA/NNNNNNN-D` com dígito verificador não colide por perturbação; a classe citada é
  irrelevante (era `processo:1cand:registro:sem_uf` sem prior, caindo em 0,96 por acaso).
- **`vaga:incompleta:unica`** (R4-10): a classe emitida continua `incompleta` (o gabarito do dev
  nunca traz `real` para vaga; multiplicidade ≥ 4 em 32/32, embora 17 % dos acórdãos da base
  tenham (tribunal, ano, relator) único — o gerador evita únicos); o prior sobe para 0,90 (ADR
  0007).
- **Enumerações de processos no plural** resolvem número a número (ADR 0005).

## Generalizações de parsing (em `normativos.py`)

Encontradas na análise dos erros dos sintéticos OOD (todas regras gerais, não formas específicas):
`art.º` (ordinal após o ponto); `Enunciado` como sinônimo de `Súmula` e `nº` antes de
`Vinculante`; OCR nas palavras do diploma (`Constltuição`, `C0nstituição`, `Deereto-Lei`,
`Complcmentar`, `Consurnidor`) resolvido com a mesma tolerância de `normalizacao.tolerante` (1
edição por palavra ≥ 5 letras), como fallback das regras por regex.

## Resultados (sem árbitro)

| conjunto | citações | corretas (classe + id) | inventada→real | ids certos |
|---|---|---|---|---|
| dev (catálogo, 192) | 192 | **192** | 0 | 96/96 |
| sintético n2_dev (seed 123) | 280 | 280 | 0 | 133/133 |
| sintético n3_ood (seed 7; regenerado na rodada 2 com `ood:ocr_fora_do_processo`) | 288 | 288 | 0 | 148/148 |
| sintéticos n3 extras (seeds 11, 99, 2024; 60 docs) | 417 / 441 / 425 | todos | 0 | todos |
| pipeline completo no dev (detector + resolução + calibração) | 192 | score oficial 1,09996 | 0 | — |

Antes das generalizações, o n3_ood tinha 11 erros (6 `art.º`, 3 `Enunciado`, 2 OCR no diploma) e
os seeds extras tinham 7 (3 OCR no primeiro dígito, 2 letra isolada no CNJ, 2 OCR em `Decreto`/
`Complementar`/`C0nstituição`). Caminhos raros observados: `classe_divergente` 23 (todos `real`),
`ocr_reparado` 4, `ambiguo_chute` 2 (ambos por cadeia truncada pela normalização de `R.H.C.`/
`44O` — ver "Pendências"), `registro` 26, `sem_classe` 5.

## O que o detector e o pipeline precisam respeitar

* Detector: `Achado.familia`/`tipo` corretos; `dados` opcionais mas, se presentes, produzidos com
  `normalizacao` (`digitos` só dígitos; `cadeia` canônica; `uf` de `separar_uf`); `forca < 1` só
  em padrões amplos; `dados["contexto"]` (janela ± 300 chars) se o pipeline não passar `contexto`.
* Pipeline: repassar `arbitro=` (já faz) e, idealmente, `contexto=`; **omitir** citações com
  `detalhes["descartar"] == "1"`; gravar `caminho` e `forca` no rastro (já faz) para a calibração.
* Normalização (pendências observadas, fora deste ADR): `R.H.C.` → `HC` em vez de `RHC`; `R.E.` →
  `E`; `Ag.REsp` → `AG RESP` em vez de `ARESP`; `Ap.` → `AP` (Ação Penal) mesmo no STM; número com
  OCR `44O` vira token ordinal na cadeia. A resolução tolera tudo isso pela regra "número manda",
  mas cada caso vira `classe_divergente`/`chute` com confiança menor.

## Rejeitado

* `incompleta` para empates (custa FN + FP com certeza).
* Rebaixar a `inventada` TODA classe divergente. (A justificativa antiga — "2/77 `real` do dev
  teriam virado FN + FP" — estava errada: esses dois casos são `classe_principal`/`classe_compativel`.
  Desde a rodada 4 só os sub-caminhos SEM UF/tribunal e o de duplicata de outra classe emitem
  `inventada`, pela assimetria de custos medida; ver "Revisão da rodada 4".)
* Casamento aproximado de dígitos / correção dígito→dígito (os 4 "vizinhos a 1 dígito" do dev são
  inventadas).
* Chamar o árbitro para duplicatas idênticas (indecidível por definição; gasto de GPU sem ganho).
