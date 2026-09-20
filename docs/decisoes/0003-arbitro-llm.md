# ADR 0003 — Árbitro LLM residual (Qwen2.5-7B-Instruct, pesos abertos)

Data: 16/09/2026. Estado: aceita; árbitro **ligado** desde 20/09/2026 (medição 2 com o Qwen real, abaixo).
Escopo: `src/caca_alucinacao/llm/` (`arbitro.py`, `prompts.py`, `backends.py`, `cache.py`),
`tests/test_llm.py`, `scripts/{baixar_modelo.sh,limitar_gpu.ps1,avaliar_arbitro.py}`,
`MANIFESTO_MODELO.md`.

## Contexto

A classe de uma citação é função determinística da consulta por identificador à base
fechada (docs/00 §1; docs/03 §0: 100% das `incompleta` são `vaga`, 0/42 `inventada` têm
número próprio, 77/77 `real` resolvem por dígitos idênticos). O núcleo regex + índice decide
tudo isso sem modelo. Sobram três situações residuais em que o núcleo **não tem informação
suficiente** e um chute custa caro na métrica (`inventada→real` = FN + FP + τ):

1. OCR pesado no número (≥ 2 letras confundíveis, letras em maioria no grupo) — a
   normalização determinística se recusa a converter (docs/04, "Riscos": um falso positivo
   aqui é exatamente o erro caro).
2. Número próprio de ≥ 2 registros com cabeçalhos **diferentes** (6 dos 77 grupos ambíguos;
   docs/04 b) em que só o contexto (ano, relator, cadeia) distingue.
3. Candidatos "fracos" de padrões amplos (sigla desconhecida + número; molde de `vaga`
   inédito) em que o detector não sabe se há citação nem onde ela termina.

A proposta prévia usava um LLM como classificador/cross-encoder sobre BM25 (docs/00 §3):
invalidada porque devolve "quem cita", não "quem é", e porque a classe não é uma decisão
semântica.

## Decisões

1. **Árbitro, não classificador.** O modelo nunca emite `real/inventada/incompleta` nem
   `id_canonico`. Ele (a) normaliza um identificador que o pipeline **reconsulta** no índice;
   (b) escolhe um índice numa lista que o índice já devolveu; (c) confirma/descarta e ajusta as
   fronteiras de um span dentro de uma janela. Em todos os casos a decisão final continua sendo
   a consulta determinística. Consequência: o pior dano possível de uma resposta errada é um
   FP isolado (id errado entre duplicatas ou span espúrio), nunca um `inventada→real` por
   número inventado — a validação `digitos_compativeis` garante que os dígitos devolvidos só
   diferem do trecho por trocas letra→dígito do mapa de OCR (dígito ASCII nunca é alterado,
   removido ou inserido; a UF é separada antes).
2. **Abstenção em qualquer falha.** Dependência ausente, exceção do modelo, resposta vazia,
   JSON inválido, campo fora do domínio, span fora da janela ⇒ `None`. Nunca uma exceção sobe
   até o documento (ADR 0002: exceção numa citação a omite; aqui nem isso acontece — o caminho
   determinístico segue). O Protocol `Arbitro` e a classe base `ArbitroBase` concentram
   parsing, validação e cache; backends só implementam `_gerar(pedidos) -> list[str]`.
3. **`Qwen/Qwen2.5-7B-Instruct`, revisão fixa, sem fine-tuning.** Motivos: pesos abertos com
   licença Apache-2.0 (sem cláusulas de uso); 7B em bf16 (≈ 15,2 GB) cabe com folga nos 24 GB
   com KV cache; treinado com bastante português e JSON estruturado (segue instruções de
   "só JSON" com confiabilidade alta em modelos instruct da família); disponível também em
   AWQ oficial (`Qwen/Qwen2.5-7B-Instruct-AWQ`, 5,6 GB) como contingência de VRAM; suportado
   por `transformers` estável e por vLLM. Descartados: modelos > 14B (não cabem em bf16 e a
   quantização traz não-determinismo adicional entre kernels); modelos < 3B (fraqueza em
   seguir regras negativas — o que é distrator — que são o cerne dos prompts); modelos com
   licença restritiva (Llama 3.x exige aceitação de termos e atribuição; Gemma tem termos
   próprios). Qwen3-8B seria alternativa equivalente, porém com "modo pensamento" que precisa
   ser desligado e gasta tokens; o 2.5 é mais previsível para saída curta.
4. **Decodificação determinística e reproduzível por cache.** Greedy (`do_sample=False`,
   `temperature=0`), semente fixa, `max_new_tokens` pequeno, chat template oficial. Toda
   pergunta é cacheada em SQLite pela chave
   `sha256(modelo | revisão | PROMPT_VERSAO | assinatura do backend | operação | entrada canônica)`;
   o cache guarda a resposta **bruta** e o resultado validado, exporta/importa JSONL e roda em
   `somente_cache` (reprodução da submissão sem GPU). Mudança em prompt ⇒ nova `PROMPT_VERSAO`
   ⇒ nova chave.
5. **Prompts em português, com regras explícitas e few-shot sintético.** Sistema comum
   (classe/número/UF/tribunal, distratores, moldes de `vaga`, fronteiras) + instruções por
   operação + exemplos inventados (nenhum número/nome do gabarito ou da base) + pedido de JSON
   puro. `classificar_span` pede o **texto literal** do span (o modelo é ruim em offsets); os
   offsets são calculados localizando o texto na janela, com aparo determinístico de artigo
   inicial e pontuação final (regra geral do gabarito, docs/03 §1).
6. **Envelope de 24 GB imposto em software.** `transformers`:
   `torch.cuda.set_per_process_memory_fraction(24 GB / total)` (5090 → 0,75); vLLM:
   `gpu_memory_utilization = 24·0,92 / total`. `scripts/limitar_gpu.ps1` limita a potência da
   5090 a 450 W no Windows (no WSL o `nvidia-smi -pl` não funciona) para aproximar o
   comportamento térmico de uma 4090/L4 — não afeta VRAM.
7. **Uso residual, gatilhos estreitos.** Ver "Integração" abaixo. O árbitro é opcional em
   runtime (`--arbitro nenhum`), o Mock heurístico (`--arbitro mock`, sem modelo) é o fallback e
   também roda nos testes pelo mesmo caminho de parsing/validação/cache.

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Não-determinismo bf16 entre GPUs (L4/A10/4090 × 5090): ordem de redução, kernels diferentes, *batching* com padding | respostas curtas e estruturadas (a variação numérica raramente muda o argmax de um JSON de 30 tokens); validação estrita; cache exportado com a submissão (`somente_cache`); uso residual — a saída do pipeline depende do modelo em ≈ 0–3 citações por documento; lote pequeno (≤ 4) ordenado por comprimento; TF32 desligado; `CUBLAS_WORKSPACE_CONFIG=:4096:8` no Dockerfile |
| Resposta plausível mas errada em `normalizar` | só trocas letra→dígito do mapa; resultado reconsultado no índice (0 candidatos ⇒ `inventada`, como antes) |
| Chute em `escolher` entre duplicatas idênticas | o pipeline só chama com cabeçalhos diferentes; sem critério o prompt manda devolver `null`; erro custa 1 FP (igual ao chute determinístico) |
| `classificar_span` ampliando/deslocando spans | span precisa ser substring literal da janela, sobrepor o candidato, ≤ 300 chars; artigo/pontuação aparados; abstenção mantém o span original |
| Latência (≤ 60 s/doc em L4) | prompts de 1,5–2,2k tokens (sistema + few-shot + janela de 900 chars), saída ≤ 160 tokens; cache; lote; chamadas só nos gatilhos; pior caso medido em `scripts/avaliar_arbitro.py` |
| VRAM > 24 GB na 5090 | fração de memória por processo / `gpu_memory_utilization`; `CACA_LLM_4BIT=1` como contingência |
| Revisão do modelo não registrada | revisão fixa versionada em `modelos/revisao_fixa.env` (= MANIFESTO = padrão do `Dockerfile.llm`); `ArbitroBase` recusa (`ErroDependencia`) `CACA_MODELO_REVISAO` vazia; `baixar_modelo.sh` falha se o commit resolvido difere da revisão fixa pedida e grava `modelos/manifesto_modelo.json` |
| Dependências pesadas quebrando o núcleo | imports tardios; `ErroDependencia` (ImportError) só ao instanciar; núcleo continua sem dependências |

## Integração (gatilhos — para `resolucao.py` e `deteccao/`)

* `normalizar_citacao(trecho, contexto)` — chamar quando, para um achado `processo`,
  `digitos_do_identificador(trecho) == ""` **ou** (há dígitos, 0 candidatos no índice **e** o
  trecho sem UF tem ≥ 2 letras confundíveis coladas a dígitos/pontuação). Se devolver dict com
  `eh_citacao=True`, reconsultar `candidatos_por_numero_e_classe(r["digitos_canonicos"],
  " ".join(r["classe_cadeia"]) or None, r["tribunal"], r["uf"])` e seguir o caminho normal
  (`caminho="processo:llm_normalizado:<n>candidatos"`, confiança rebaixada). `eh_citacao=False`
  ⇒ o detector pode descartar o achado (ou manter `inventada`, a critério da calibração).
  `None` ⇒ segue como se o árbitro não existisse.
* `escolher_candidato(trecho, contexto, candidatos)` — só depois de tribunal → UF → cadeia
  exata → classe principal, com ≥ 2 candidatos cujos `cabecalho(600)` diferem (docs/04 h.3-d).
  `candidatos` via `llm.candidato_de_registro(registro, base.cabecalho(registro.documento_id))`.
  Índice ⇒ `real` com `caminho="processo:llm_escolha"`; `None` ⇒ escolha determinística (menor
  `documento_id`, confiança ≈ 0,5).
* `classificar_span(trecho, janela, inicio_rel)` — para achados com `forca` abaixo do limiar
  (padrões amplos), com `janela = texto[max(0, ini-200):fim+200]` e `inicio_rel = ini - início da
  janela`. `eh_citacao=False` ⇒ descartar o achado; dict ⇒ `Achado(inicio=ini_janela+inicio_rel,
  fim=ini_janela+fim_rel, trecho=r["trecho"], familia=r["familia"], tipo=r["tipo"],
  origem="llm:classificar_span", forca=…)`; `None` ⇒ manter a decisão determinística.
* `contexto` deve ser a janela de ± 300–450 chars em torno do trecho (o módulo recorta a 900).
* Lote: `arbitro.executar_lote(operacao, [args, …])` agrupa os *misses* do cache numa chamada.

## Padrão ouro: o árbitro LIGADO, como extrator de segundo estágio (20/09/2026)

**Decisão.** O árbitro passa a ter um quarto papel, `extrair_citacoes`, e a imagem de submissão com
GPU (`Dockerfile.llm`, `CACA_ARBITRO=transformers`) roda com ele ligado. O desenho segue o padrão
para verificação de citações contra uma fonte autoritativa (*entity linking* restrito ao catálogo;
recuperação antes de decisão): **o modelo só aponta onde olhar** — extrai e desambigua — e **nunca
classifica**; a classe continua sendo função da cardinalidade da consulta à base.

**Mecanismo** (`llm/extrator.py`, `pipeline._extrair_com_arbitro`, `arbitro.validar_extracao`):

1. depois do regex, o texto fora do cabeçalho é dividido em janelas (parágrafos/frases ≤ 900
   codepoints); só vão ao modelo as que têm **pistas de citação não cobertas** por um achado
   (`nº`, `Rel.`, `Súm`, `art.`, sigla de tribunal, classe processual…) e algum dígito; no máximo
   `MAX_JANELAS_POR_DOCUMENTO = 6` por documento, por ordem de pistas, e dentro de um orçamento de
   30 s/doc (metade do envelope) — estourado o orçamento, as janelas restantes ficam como o regex
   deixou;
2. o modelo devolve propostas estruturadas (`trecho` literal, família, cadeia/número/UF, número da
   súmula, artigo/diploma, tribunal/ano/relator); a validação determinística rejeita tudo que não
   se prova no texto: span que não é substring literal da janela, span que toca uma citação já
   detectada ou outra proposta, número que não se obtém de um token do span só por trocas letra→
   dígito (`_numero_presente`; um dígito de OCR fora do número, como `RE5p` ou `Sún1ula`, não
   invalida), UF/artigo/diploma/ano/relator ausentes do span, processo sem classe reconhecível,
   span maior que o máximo da família (90/70/130/70/170);
3. cada proposta aceita é **re-detectada**: os campos são renderizados na forma canônica que os
   detectores por regex entendem (`AGINT no RESP 1234567/SP`, `Súmula 412 do TST`, `art. 802 do
   Código Civil`, `julgado do STJ proferido em 2020 pela relatoria de X`, `Tema 1234 da repercussão
   geral`) e passados por `deteccao.detectar`; o `Achado` herda os `dados` como um achado de regex,
   com os offsets do span original e `origem = llm:extrator:<backend>:<família>`;
4. a resolução é a de sempre (classe pela base); a confiança tem caminho próprio
   (`llm:extrator:<caminho do núcleo>`), com priors conservadores (0,70–0,85), que **nunca herda**
   dos caminhos do regex (fallback só dentro de `llm:*`), nunca recebe o teto consolidado
   (`CAMINHOS_SEM_CONSOLIDACAO`) e só é treinado com rastros do modelo real (decisões de origem
   `mock` são ignoradas por `treinar_calibracao.py`);
5. abstenção, resposta inválida ou exceção do árbitro deixam o documento **exatamente** como o
   regex o deixou (`tests/test_extrator.py`); o saneador do pipeline confere de novo que nenhum
   span novo sobrepõe outro (IoU ≥ 0,5 seria fatal para a submissão).

Os gatilhos anteriores continuam. Correção de 20/09 em `_resolver_processo`: quando
`normalizar_citacao` devolve uma chave que o núcleo **já tinha consultado** (a padrão ou uma
alternativa de OCR), também sem dono, a decisão e a confiança são as do núcleo (`ocr_sem_dono`/
`ocr_ambiguo`), não `llm_normalizou:0cand` — o árbitro não trouxe informação nova, e rebaixar a
confiança custava −0,002 em `r2_chave_parcial`.

**Medição (padrão).** `scripts/comparar_arbitro.py` (`make comparar-arbitro ARBITRO=…`) roda o
núcleo e o árbitro em todos os conjuntos, com a métrica oficial, e aplica o **critério de
decisão**: o árbitro fica ligado se, e só se, (a) em nenhum conjunto o score cai mais que 0,0005;
(b) em nenhum conjunto `inventada→real` aumenta; (c) nos conjuntos que forçam os gatilhos o score
sobe (`r6_extrator_formas`) e o extrator não emite nada onde não há citação
(`r6_extrator_distratores`); (d) o dev fica idêntico ou melhor. `scripts/adversarial/
gerar_adversarial_r6.py` produz os dois conjuntos: formas que os detectores por regex **não**
cobrem (medido em 20/09: classe colada ao número `REsp1.234.567/SP`, `recurso especial de número
N`, palavra quebrada `Re curso`/`Recla-⏎mação`, OCR na palavra `Sún1ula`, vaga com órgão
julgador) e janelas cheias de pistas sem citação.

**Resultado com o `mock`** (20/09; o mock é uma heurística que exercita o caminho, não o modelo):
37 de 38 conjuntos **byte a byte idênticos** ao núcleo (0 citações emitidas pelo extrator, Δ = 0);
`r6_extrator_formas` 0,59657 → 1,09680 (+0,500; 69 citações extraídas, 69 certas, τ = 0);
`r6_extrator_distratores` 0 emissões. Veredito do critério: LIGAR. A medição com o **modelo
real** (`scripts/rodar_llm_local.py` na RTX 5090: ambiente, pesos na revisão fixa, fumaça,
`comparar_arbitro --arbitro transformers`, dev com árbitro, exportação do cache) é o passo que
decide de fato — o mock não mede a precisão do Qwen.

**Medição 1 com o modelo real** (20/09, RTX 5090, `scripts/rodar_llm_wsl.cmd`; Qwen2.5-7B-Instruct
`a09a354…`, bf16, greedy; prompt `2026-09-20.1`; 9 conjuntos, 550 chamadas, ≈ 20–40 s/doc):

| conjunto | núcleo | árbitro | Δ | LLM emitiu (certas) |
|---|---|---|---|---|
| dev | 1,10000 (1,0999960) | idêntico | 0 | 0 (0) |
| n3_ood, r5_processos_ocr_combo, ruido_n2, vagas | — | idênticos | 0 | 0 (0) |
| r2_chave_parcial | 1,09998 | 1,09843 | −0,00155 | 0 (0) — normalização rebaixou confiança |
| r5_distratores_orgaos | 1,02667 | 0,97778 | −0,04889 | 6 (0) — FPs |
| r6_extrator_distratores | 1,10000 | 1,10000 | 0 | 3 (0) — FPs sem custo (spans fora do gabarito) |
| r6_extrator_formas | 0,59657 | 1,01414 | +0,41756 | 71 (62), τ = 0 |

Veredito do critério: **MANTER DESLIGADO** (critérios a e c violados). O dev ficou idêntico e
`inventada→real` nunca subiu — o padrão ouro segurou o modelo onde importa — mas a validação
literal de então deixava passar o que o Qwen "batizava": `Apólice nº 1234567` como `AP`,
`Processo nº <CNJ>` como `APL`/`RESP`/`RCL`, `acórdão nº N` como `RRAG`, `Súmula Administrativa
da AGU`, `OJ da SBDI-1`; e para `agravo em recurso especial` devolveu `RESP`, para `Re curso
Especial` devolveu `RESE`, para `Sún1ula 211 do STJ` devolveu tribunal `TST`. Regras acrescentadas
(v1.2.1, `arbitro.validar_extracao`), todas deterministas e provadas no texto:

* **a classe tem de estar escrita no span**: as letras do span sem o número (dígitos de OCR
  revertidos, `RE5p` → `resp`) têm de ser exatamente um apelido da cadeia devolvida, com
  `processo/autos/nº/de número` antes e `/UF`, `oriundo de <estado>` depois; se o texto escreve
  **uma única** cadeia conhecida diferente da devolvida, vale o texto (`agravo em recurso
  especial` → `ARESP`); se nenhuma ou mais de uma, a proposta cai;
* a UF pode vir do **nome do estado** escrito no fim do span (`oriundo de Rio Grande do Sul` → `RS`;
  só correspondência exata com `ESTADOS`);
* o **tribunal da súmula é o escrito no span** (sigla ou por extenso); sem tribunal escrito, a
  súmula fica sem tribunal — o modelo não pode inventá-lo;
* listas de distratores por família: súmula (`administrativa`, `AGU`, `OJ`, `SBDI`, `jornada`,
  `CJF`, `TNU`, `CARF`, conselhos/corregedorias…) e dispositivo (`contrato`, `estatuto social`,
  `regimento`, `edital`, `apólice`, `cláusula`…);
* o **relator** de uma citação vaga tem de vir no span depois de uma pista (`Rel.`, `relator`,
  `relatoria d[ae]`, `Rel. Min.`) e não pode ser um órgão (o modelo devolveu `Supremo Tribunal
  Federal` como relator de `precedente firmado no ano de 2022 pelo Supremo Tribunal Federal`);
* o prompt passa a **mascarar** as citações já detectadas (`⟦…⟧`), para o modelo não as repetir
  (a validação e a chave do cache continuam usando a janela original), e pede a resposta
  **compacta** (só os campos da família; 19 de 455 respostas da medição 1 estouraram os 480
  tokens com os 12 campos por citação, a maioria `null`); uma lista **truncada** pelo limite
  aproveita as propostas completas que vieram antes do corte (`extrair_json_citacoes`) — cada uma
  é validada sozinha, então a lista parcial é tão segura quanto a inteira;
* `_resolver_processo`: a normalização do árbitro só muda a decisão quando **ancora** a citação num
  registro compatível (classe `real`); chave nova sem dono ou candidatos incompatíveis mantêm a
  decisão e a confiança do núcleo (`normalizou_sem_dono`/`candidato_rejeitado` nos detalhes).

*Replay* determinístico das 455 respostas de extração da medição 1 pelo validador novo
(`saida_llm/analise/`): 81 propostas aceitas → 65; as 16 que caíram são exatamente as FPs acima
(mais o span que engolia a frase); as 3 cadeias/tribunal errados foram corrigidos pelo texto; todas
as 65 restantes estão em `r6_extrator_formas`; as 19 respostas truncadas, recuperadas, acrescentam 0
propostas aceitas. A medição 2 (prompt `2026-09-20.3`) é o que decide.

**Medição 2 com o modelo real — DECISÃO: LIGAR** (20/09, mesma máquina, v1.2.1, prompt
`2026-09-20.3`; 9 conjuntos, 1.088 chamadas, 26 min no total, `saida_llm/analise/log_medicao2.txt`):

| conjunto | núcleo | árbitro | Δ | LLM emitiu (certas) | s/doc |
|---|---|---|---|---|---|
| dev | 1,10000 (1,0999960) | idêntico | 0 | 0 (0) | 7,0 |
| n3_ood | 1,09986 | idêntico | 0 | 0 (0) | 7,1 |
| r2_chave_parcial | 1,09998 | idêntico | 0 | 0 (0) | 14,0 |
| r5_distratores_orgaos | 1,02667 | idêntico | 0 | 0 (0) | 3,5 |
| r5_processos_ocr_combo | 1,09945 | idêntico | 0 | 0 (0) | 8,4 |
| r6_extrator_distratores | 1,10000 | idêntico | 0 | 0 (0) | 19,5 |
| r6_extrator_formas | 0,59657 | **1,07203** | **+0,47546** | 67 (66), τ = 0 | 24,1 |
| ruido_n2 | 1,09866 | idêntico | 0 | 0 (0) | 8,1 |
| vagas | 1,08506 | idêntico | 0 | 0 (0) | 9,4 |

Os quatro critérios passam: (a) nenhuma queda; (b) `inventada→real` 0 → 0 em todos; (c)
`r6_extrator_formas` sobe e `r6_extrator_distratores` tem 0 emissões (a medição 1 tinha 3); (d) dev
idêntico byte a byte — a `submission.csv` com o árbitro tem o **mesmo SHA-256** da do núcleo
(`a5f6b066…`). A máscara e a resposta compacta cortaram o custo de 19,7 para 7,0 s/doc no dev (nenhuma
resposta truncada). A única extração errada é um defeito do gerador, não do pipeline: em
`adv_r6_extrator_formas_n2_004` o texto dizia "oriundo de São Paulo" para um registro de outra UF
(o mapa `UF_EXT` só tinha 9 estados e caía em São Paulo) — o validador leu SP, a resolução deu
`uf_incompativel` → `inventada`, e o gabarito dizia `real`. Corrigido na v1.2.2 (os 27 estados; o
conjunto regenerado muda só nesse documento; a tabela acima é a medida no conjunto de então).

Consequências: o árbitro fica **ligado** na imagem de submissão (`Dockerfile.llm`) e na rodada do
conjunto cego; no dev a saída é a mesma do núcleo, então a submissão de referência não muda. A
reprodução da submissão com o árbitro é `make reproduzir ARBITRO=transformers
CACHE_LLM=saida_llm/cache_llm.jsonl` (`reproduzir.py --arbitro --cache-llm`): o pipeline roda 2×
só do cache exportado (`CACA_LLM_SOMENTE_CACHE=1`), com zero chamadas ao modelo, e o CSV bate byte a
byte — 5 s, sem torch. O `cache_llm.jsonl` contém janelas dos documentos e por isso **não é
versionado**: acompanha a submissão como `dados/`. Para o cego, a estratégia é rodar núcleo e
núcleo + árbitro, enviar os dois CSVs e selecionar os dois no Kaggle (vale a melhor das
selecionadas no placar privado): ligar o árbitro nunca rebaixa a posição final.

**Reprodução sem GPU.** Todas as respostas do modelo ficam em `CACA_CACHE_LLM` (SQLite) e são
exportadas em JSONL (`cache_llm.jsonl`); com `CACA_LLM_SOMENTE_CACHE=1` e
`CACA_LLM_CACHE_IMPORTAR=<jsonl>` o backend `transformers`/`vllm` nem carrega o modelo (nem exige
torch) e responde só do cache — a mesma saída, byte a byte, em qualquer máquina. Um *miss* no
cache é abstenção (o documento fica como o regex deixou), nunca uma chamada.

**Custo.** No dev, 4–6 janelas por documento vão ao modelo (0 extrações com o mock). Com
prompt ≈ 1,2k tokens e resposta ≤ 480 tokens: 5090 ≈ 2–3 s por chamada (≈ 15 s/doc), L4 ≈ 6–10 s
(≈ 40–60 s/doc, no limite — o orçamento de 30 s/doc corta as janelas menos promissoras). Medir.

## Revisão da rodada 4 (20/09) — o árbitro é residual POR DESENHO (R3q-10)

Medido com `--arbitro mock`: **0 chamadas** ao modelo nos 26 documentos do dev e nos 40 do
`n3_ood`; 1 chamada (abstenção) em 60 documentos do `n2_ag_treino`. Isso não é falha de
integração — é o resultado esperado da ordem de decisão do `resolucao.py`: o núcleo determinístico
resolve tudo o que o índice resolve, e o árbitro só entra nos gatilhos residuais, que os dados do
desafio quase não exercitam:

| gatilho (`resolucao.py`) | quando | frequência observada |
|---|---|---|
| `normalizar_citacao` (`_normalizar_com_arbitro`) | achado `processo` com 0 candidatos (depois de `chaves_alternativas`) E (sem dígitos, ou ≥ `LETRAS_OCR_PARA_ARBITRO` = 2 letras confundíveis convertidas, ou ≥ 1 letra não convertida no núcleo) | 0 no dev; 1/60 no `n2_ag_treino` |
| `escolher_candidato` (`_escolher_com_arbitro`) | ≥ 2 candidatos depois de tribunal → UF → cadeia → registro → UF confirmada, que NÃO são duplicatas textuais (`sao_duplicatas` = cabeçalhos iguais) | 0 no dev (os 77 grupos ambíguos da base são duplicatas, docs/04 h.3) |
| `classificar_span` | reservado a achados amplos abaixo do limiar; não é chamado pelo pipeline atual | 0 |

Consequências assumidas: (1) a **submissão de referência é a do núcleo** (`--arbitro nenhum`;
`Dockerfile`), e `Dockerfile.llm` é uma variante opcional cujo custo/benefício não é mensurável
com os conjuntos existentes; (2) a execução "de ponta a ponta com mock" exercita a carga, a
assinatura, o cache e as estatísticas, não a decisão do modelo — o comportamento das operações é
coberto por `tests/test_llm.py` com respostas simuladas; (3) para medir o árbitro de verdade é
preciso um perfil do gerador que force os gatilhos (duplicatas com cabeçalhos distintos e núcleos
com ≥ 2 letras ambíguas sem reparo) — pendência registrada abaixo, não bloqueante para a entrega.

## Revisão da rodada 3 (17/09) — engenharia

- **Falha na CARGA do árbitro recua para o núcleo** (R3e-01, alta): `cli.criar_arbitro` captura
  qualquer exceção ao instanciar o backend (`ErroDependencia`, `ValueError`, `OSError` de
  snapshot ausente em `HF_HOME`/volume não montado, `RuntimeError` de CUDA, `KeyError` de
  config) e segue com `arbitro=None` e log ERROR — antes só `ImportError`/`ValueError` viravam
  código 2 e o resto era traceback com ZERO JSONs escritos. A promessa "qualquer falha do
  árbitro = abstenção" passa a valer também para a carga. A revisão dos pesos vazia continua
  a ser um erro de configuração, mas agora também recua (logado). Teste em
  `tests/test_revisao_rodada3.py::TestEngenharia`.
- **`scripts/avaliar_arbitro.py` avalia os `casos_llm.jsonl` do gerador** (R3e-03): os nomes
  `classificar_span`/`normalizar_citacao`/`escolher_candidato` são mapeados para
  `classificar`/`normalizar`/`escolher`; operação desconhecida → código 2 com mensagem, em vez
  de tabela vazia. `baixar_modelo.sh` aponta para `<conjunto>/casos_llm.jsonl`.
- **Semente e estatísticas** (R3e-09): `config.fixar_semente(com_bibliotecas=False)` com
  `--arbitro nenhum` (não importa numpy/torch); com árbitro, `arbitro.estatisticas()` vai
  para o log e para `<saida>/arbitro_estatisticas.log` (JSON; nunca `.json`, que o conversor oficial leria como documento) ao fim do lote (auditoria do
  envelope de 60 s/doc).

## Revisão da rodada 2 (17/09) — engenharia

- **Revisão dos pesos obrigatória** (R3b-02): `ArbitroBase` levanta `ErroDependencia`
  (código 2 no CLI) com `CACA_MODELO_REVISAO` vazia, salvo `CACA_MODELO` apontando para um
  snapshot local — então a identidade dos pesos é `local-<sha256 de config.json + shards>`,
  registrada no log e na chave do cache. A revisão fixa é **versionada** em
  `modelos/revisao_fixa.env` (`Qwen/Qwen2.5-7B-Instruct` @ `a09a35458c702b33eeacc393d103063234e8bc28`,
  `main` em 2025-01-11, Apache-2.0; alternativa AWQ @ `b25037543e9394b818fdfca67ab2a00ecc7dd641`,
  2024-10-09) e é o valor padrão do `ARG CACA_MODELO_REVISAO` do `Dockerfile.llm`, gravado como
  `ENV`; o build falha se o argumento for esvaziado; `make docker-llm` lê o mesmo arquivo;
  `scripts/baixar_modelo.sh` baixa essa revisão por padrão e falha se o commit resolvido for
  outro. `tests/test_revisao_rodada2.py` confere que MANIFESTO, Dockerfile e o `.env` batem.
- **Hash do prompt na chave do cache** (R3b-03): `PROMPT_ID = PROMPT_VERSAO + "+" + sha256
  curto(SISTEMA + templates)`; mudar o texto invalida o cache mesmo que a versão humana não
  seja incrementada; `tests/test_llm.py` fixa o hash.
- **Lote = 1 por padrão** (R3b-08): a resolução consulta o árbitro um achado por vez; o
  tamanho do lote entra na assinatura do backend (logo na chave do cache).
- Contingência NF4 documentada como fora da imagem (sem pin verificado de `bitsandbytes`).

## Pendências

* ~~Perfil do gerador que force os gatilhos do árbitro (R3q-10) e teste de integração
  LLM→resolução com `mock`; medição com o modelo real~~ — feito em 20/09 (`gerar_adversarial_r6.py`,
  `tests/test_extrator.py`, `comparar_arbitro.py`, `rodar_llm_local.py`/`rodar_llm_wsl.cmd`; medições
  1 e 2 acima, veredito LIGAR).
* ~~**Pesos**: download e hash na máquina com GPU~~ — feito em 20/09 (`saida_llm/modelo.json`: snapshot
  `a09a354…`, hash `2ea2bfcc05657159`; `scripts/baixar_modelo.sh` continua sendo o caminho do Docker).
* Medir num L4/A10 emulado (fração de VRAM + 450 W): na 5090 o extrator custa 3,5–24 s/doc (dev 7,0);
  numa L4 (≈ 3× mais lenta) o orçamento de 30 s/doc cortaria janelas em documentos longos — por isso
  a rodada do cego é feita na 5090 e o cache exportado acompanha a submissão. Decidir por
  `transformers` (padrão) ou `vllm`; fixar versões em `requirements-llm.txt`.
* Comparar `PROMPT_VERSAO` futuras só pelo avaliador (acurácia por operação, taxa de
  abstenção, `digitos_errados` = 0 obrigatório).
