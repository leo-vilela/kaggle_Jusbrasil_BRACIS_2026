# Caça-Alucinações — verificador de citações jurídicas (Jusbrasil × BRACIS 2026)

> Estado (20/09/2026, v1.3.0): **todos os módulos prontos e testados** (596 testes, `make testar`;
> reprodução em um comando, `make reproduzir`). Núcleo determinístico só com biblioteca padrão;
> score no conjunto de desenvolvimento **1,10000** (1,0999960; τ = 0), nos sintéticos n2/n3
> 1,10000 / 1,09986 e nos 34 conjuntos adversariais das revisões entre 1,027 e 1,10000 (todos com
> τ = 0; ver `docs/decisoes/0005`–`0007`; geradores em `scripts/adversarial/`, `make adversarial`).
> Calibração retreinada de forma reproduzível com validação fora da amostra (`make
> calibrar-completo CACHE_LLM=…`, ADR 0007; desde a v1.2.4 os caminhos do extrator LLM são
> calibrados com as 69 extrações reais da medição 3, holdout por documento incluído). O árbitro LLM (`llm/`, **Qwen3.5-9B em NF4**
> desde a v1.3.0 — pesos originais, revisão fixa; Qwen2.5-7B-Instruct bf16 até a v1.2.5) segue o **padrão ouro** (ADR 0003): extrai e desambigua com toda saída validada
> contra o texto e a base, nunca classifica; `Dockerfile.llm` roda com ele **ligado**, e
> `make comparar-arbitro` mede núcleo × árbitro com veredito automático. Medido com o Qwen real na
> RTX 5090 (20/09, duas rodadas; ADR 0003 "Medição 1/2"): a v1.2.1 fechou as brechas da rodada 1 e a
> rodada 2 deu **VEREDITO: LIGAR** — 8 de 9 conjuntos byte a byte idênticos ao núcleo (dev incluído),
> τ = 0 em todos, 0 emissões nos distratores e `r6_extrator_formas` 0,597 → 1,072 (+0,475; 67
> extrações, 66 certas), a ≈ 7–24 s/doc. A submissão com o árbitro é **idêntica** à do núcleo no dev
> (mesmo SHA-256) e se reproduz sem GPU: `make reproduzir ARBITRO=transformers
> CACHE_LLM=saida_llm_q35/cache_llm.jsonl` (zero chamadas ao modelo). **Medição 3** (v1.2.3–1.2.5,
> `scripts\rodar_llm_q35_wsl.cmd`, ADR 0003): o mesmo árbitro com o Qwen3.5-9B em NF4 no lugar do
> Qwen2.5 — 8 de 9 conjuntos idênticos ao núcleo, τ = 0, 69 extrações (69 certas após a correção do
> validador na v1.2.5) contra 67 do Qwen2.5 em `r6_extrator_formas` (1,09680 × 1,072), 2–5× mais lento
> por janela mas dentro do envelope (7,5 s/doc no dev). **Adotado como padrão na v1.3.0** (`modelos/revisao_fixa.env`,
> `Dockerfile.llm` sobre torch 2.11 + transformers 5.16.1 + bitsandbytes; calibração retreinada com o cache do Qwen3.5).

Repositório público: <https://github.com/leo-vilela/kaggle_Jusbrasil_BRACIS_2026> (v1: núcleo determinístico +
árbitro Qwen2.5 sem fine-tuning). A versão 2, com o LLM treinado como camada final de decisão nos casos residuais, vive
em <https://github.com/leo-vilela/kaggle_Jusbrasil_BRACIS_2026_LLM>. Licença Apache-2.0 (LICENSE, NOTICE); os dados do
desafio não são distribuídos aqui.

## O desafio em 5 linhas

1. Entrada: um `.txt` por parecer jurídico (UTF-8, offsets em codepoints); saída: um JSON por
   documento (`schema_version 1.2`) listando cada citação de jurisprudência ou lei com `inicio`,
   `fim`, `trecho`, `tipo`, `classificacao` e `resolucao`.
2. A classe é consequência da consulta por **identificador** a uma base fechada (SQLite com
   1.014 registros): 1 registro → `real` (com `id_canonico`); 0 → `inventada`; identificador
   insuficiente → `incompleta`.
3. Métrica oficial (`kaggle_metric.py`): alinhamento de spans por IoU ≥ 0,5, macro-F1 por classe,
   penalidade por `inventada`→`real` (τ), bônus de calibração (Brier) e peso 2× para o nível 2
   (texto com ruído de OCR). Máximo 1,1000.
4. Duas predições sobrepostas (IoU ≥ 0,5) no mesmo documento **invalidam a submissão inteira**.
5. Envelope de execução: container offline, 1 GPU de 24 GB, média ≤ 60 s por documento.

Detalhes: `docs/00_analise_proposta_vs_desafio.md` (formato e métrica linha a linha).

## Arquitetura

```
.txt ─▶ deteccao (regex) ─▶ llm.extrator (janelas com pistas sem achado; propostas validadas no texto) ─┐
                                                                                                        ▼
        contrato (JSON 1.2) ◀─ calibracao ◀─ resolucao ◀─ base_canonica ◀─ normalizacao ◀─ achados (regex ∪ llm)
                                                  └─▶ llm.arbitro: normalizar / escolher entre registros da base (residual)
```
A classe (`real`/`inventada`/`incompleta`) é sempre função da consulta à base; o LLM só aponta onde
olhar e escolhe entre candidatos que a base já devolveu (ADR 0003, "padrão ouro").

| módulo (`src/caca_alucinacao/`) | papel | estado |
|---|---|---|
| `tipos.py` | `Achado`, `Decisao`, `iou`, enums | pronto |
| `base_canonica/` | índice de números **próprios** (nunca "quem cita"), súmulas e dispositivos | pronto (cobertura 96/96 no dev) |
| `contrato.py` | dataclasses do JSON 1.2, `validar()` espelhando tudo que a métrica rejeita | pronto |
| `pipeline.py` | `processar_texto`/`processar_pasta`: injeção de dependência, saída sempre válida, rastro de decisões | pronto |
| `cli.py`, `config.py` | linha de comando do container; caminhos por `CACA_*` | pronto |
| `deteccao/`, `normalizacao.py` | regex por família + normalização de OCR (núcleos ambíguos nunca viram chave parcial) | pronto (192/192 spans no dev) |
| `resolucao.py`, `calibracao.py` | classe por cardinalidade da consulta; reparo determinístico de OCR; confiança por caminho de decisão | pronto (1,10000 no dev; τ = 0) |
| `llm/` | árbitro Qwen (pesos originais, revisão fixa, decodificação determinística): `extrator.py` (2º estágio), `normalizar`, `escolher`; validação determinística em `arbitro.py`; cache exportável (reprodução sem GPU) | pronto (`--arbitro transformers`; `Dockerfile.llm` ligado; `make comparar-arbitro`) |
| `scripts/analise/verificar_vazamento.py` | lint: nenhum trecho/número/nome do gabarito ou da base em arquivo versionado (`make vazamento`; também roda em `make testar`) | pronto |
| `scripts/adversarial/` | geradores dos 34 conjuntos adversariais das revisões (`r6_*` forçam o extrator LLM) (gabarito por construção a partir de `dados/indice.json`; sem nenhum número da base no código — consultas posicionais) + `rodar_*.sh` + `erros.py` (diagnóstico) | pronto |

Decisões registradas em `docs/decisoes/`; especificações medidas nos dados em `docs/03_*` e `docs/04_*`.

## Como reproduzir passo a passo

Requisitos: Python ≥ 3.10 (núcleo só com biblioteca padrão); `numpy` e `pandas` **apenas** para a
avaliação local com o script oficial (`pip install -r requirements.txt`). `make` opcional.

**Em um comando** (com `dados/` já preenchido pelo passo 1 abaixo):

```bash
make reproduzir REFERENCIA=../submission_v1_2.csv   # ou: python scripts/reproduzir.py --referencia ../submission_v1_2.csv
```

`scripts/reproduzir.py` confere os SHA-256 dos dados oficiais, gera os derivados que faltarem
(catálogo e sintéticos, seeds fixas), roda a suíte inteira (falha se algum teste ficar `skipped`
com os dados presentes), a verificação de vazamento, o pipeline **duas vezes** (a segunda sem
`dados/indice.json`, reconstruindo o índice em memória) exigindo saídas byte a byte idênticas,
a métrica oficial e o conversor oficial; com `--referencia`, compara o CSV gerado byte a byte com
o entregue. Código de saída 0 só com tudo conferido (3 = métrica pulada por falta de
`numpy`/`pandas`; 1 = alguma etapa falhou). Só biblioteca padrão e sem `make`; validado em
Ubuntu 22.04 (Python 3.10) e no contêiner (Python 3.11) — no Windows, use o WSL2.

Passo a passo equivalente:

```bash
# 1. dados: zip da aba Data do Kaggle → dados/ (SHA-256 conferidos; offsets do gabarito validados)
make dados ZIP=~/Downloads/desafio-jusbrasil-bracis-2026.zip
#    (sem o zip, `make dados` só verifica o que já está em dados/; num clone limpo lista os arquivos
#    AUSENTES e pede o zip — sem erro e sem chamar isso de "divergência")

# 2. índice de números próprios (opcional: o CLI constrói em memória em ~0,2 s se faltar)
make indice

# 3. testes (a verificação de vazamento exige dados/catalogo_gabarito.json, gerado por `make dados`
#    ou `make catalogo`; com dados/goldenset.csv presente e sem o catálogo, o lint FALHA em vez de calar).
#    Os testes com sintéticos (n2_dev seed 123, n3_ood seed 7) ficam "skipped" até `make sinteticos`
#    (geração determinística; docs/05)
make sinteticos
make testar            # ou: PYTHONPATH=src python -m unittest discover -s tests -v
make lint              # ruff (se instalado) + scripts/analise/verificar_vazamento.py
make adversarial       # regenera os 34 conjuntos adversariais (scripts/adversarial/, seeds fixas) em
                       # dados/adversarial/ e roda pipeline + métrica oficial em cada um (~1 min)
make calibrar-completo CACHE_LLM=saida_llm_q35/cache_llm.jsonl
                       # reproduz o TREINO da calibração (ADR 0007): regenera os conjuntos, roda o pipeline em
                       # 38 com o árbitro só do cache da medição (zero chamadas, sem GPU), treina em 37 e valida
                       # em n3_ood (fora do ajuste) + metade de r6_extrator_formas para os caminhos llm:*; falha
                       # se a tabela obtida diferir de dados/calibracao.json (~1 min; GRAVAR=1 grava uma nova).
                       # Sem CACHE_LLM só o núcleo roda e os caminhos llm:* ficam nos priors (a tabela
                       # versionada desde a v1.2.4 exige o JSONL, cujo SHA-256 está em meta.cache_llm)

# 4. rodar sobre os 26 documentos de desenvolvimento → saida/*.json (+ saida/rastro.jsonl)
make rodar             # = PYTHONPATH=src python -m caca_alucinacao.cli --input dados/txt --output saida --db dados/desafio1_bracis.db

# 5. avaliar com o kaggle_metric.py oficial + diagnóstico (matriz de confusão, erros por documento, τ, Brier)
make avaliar           # relatório em relatorio.json
python scripts/avaliar.py --sanidade   # prova que a avaliação reproduz o oficial: 1.1000 / 1.0000 / 0.0

# 6. submissão: json_to_submission.py oficial + validação (todos os documento_id, nenhum ParticipantVisibleError) + zip dos JSONs
make submissao         # submission.csv e submission_jsons.zip

# 7. imagem Docker (sem dados nem pesos) e execução exatamente como a organização fará
make docker && make docker-rodar
```

Variáveis úteis: `SAIDA=`, `ARBITRO=nenhum|mock|transformers|vllm`, `CALIBRACAO=`, `ENTRADA=`.
Todos os caminhos também podem vir do ambiente: `CACA_DB`, `CACA_INDICE`, `CACA_CALIBRACAO`,
`CACA_MODELO_DIR` (snapshot ou `<dir>/hf`), `CACA_MODELO`, `CACA_MODELO_REVISAO`, `CACA_CACHE_LLM`
(arquivo SQLite; padrão `cache_llm/arbitro_llm.sqlite`), `CACA_ARBITRO` — todos lidos por `config.py`.

## Comando exato para a organização

```bash
docker build -t caca-alucinacao:latest .
docker run --rm --network none \
  -v /caminho/txt:/data/in:ro \
  -v /caminho/saida:/data/out \
  -v /caminho/desafio1_bracis.db:/data/base/desafio1_bracis.db:ro \
  caca-alucinacao:latest --input /data/in --output /data/out
```

Produz `/data/out/<documento_id>.json` para **todo** `.txt` (documento sem citação → `"citacoes": []`;
a extensão não distingue caixa e arquivos que não são `.txt` são listados no log como ignorados).
Em seguida, `python json_to_submission.py /caminho/saida submission.csv` (conversor oficial).

A imagem roda como **root** de propósito: `/data/out` é um bind mount criado pela organização e
herda dono/modo do host — um usuário sem privilégios numa pasta `root:755` não conseguiria
escrever nenhum JSON. O CLI confere a permissão de escrita na partida e, se faltar, termina com
código 2 e mensagem clara (`--user $(id -u):$(id -g)` ou `chmod` na pasta). Banco corrompido,
`--output` apontando para um arquivo, tabela de calibração malformada e **lote vazio** (nenhum
`.txt` na pasta de entrada — p. ex. a pasta-mãe montada no lugar da dos `.txt`) também terminam
com código 2 e mensagem — nunca com traceback nem com um "sucesso" de zero JSONs. Arquivos
ocultos (`.x.txt`, `._x.txt`) são ignorados com aviso.

Variante com árbitro LLM (GPU): `Dockerfile.llm` (base `pytorch/pytorch:2.11.0-cuda12.8` — cobre
Blackwell/RTX 5090 e as anteriores; `requirements-llm.txt` pinado com `==`: transformers 5.16.1 + bitsandbytes 0.50.2; pesos baixados por
`scripts/baixar_modelo.sh` e montados em `/modelos`, com `HF_HOME` apontado automaticamente para
`/modelos/hf`; revisão fixa dos pesos em `modelos/revisao_fixa.env` = `MANIFESTO_MODELO.md` = padrão
do `Dockerfile.llm`).

## Envelope

| item | exigido | este sistema |
|---|---|---|
| rede | offline | nenhum acesso; `--network none` funciona |
| GPU / RAM | 1 × 24 GB VRAM, ~8 vCPU, 32 GB | núcleo determinístico roda em CPU, < 1 s/doc; árbitro LLM opcional |
| tempo | média ≤ 60 s/doc, teto 4 h | medido e logado por documento (`WARNING` se a média passar de 60 s) |
| determinismo | decodificação determinística, pesos com revisão fixa | `PYTHONHASHSEED=0`, semente fixa, ordenação explícita, sem iteração sobre `set` |
| dados | não redistribuir | `dados/` fora do git e da imagem (só `dados/calibracao.json`, artefato nosso) |

Regra de robustez do pipeline: uma exceção numa citação **omite só aquela citação** (custa no
máximo 1 FN); uma exceção num documento gera JSON vazio para ele; uma falha de E/S na escrita de um
JSON é registrada e o lote continua; a submissão nunca fica sem linha. O saneamento de sobreposições
é O(n log n) e há um teto defensivo de 5 000 achados por documento (envelope de 60 s/doc).

## Roteiro na máquina local (RTX 5090, Windows + WSL2 + Docker Desktop)

### 0. Limite de potência (420 W) — PowerShell **como administrador**, no Windows
```powershell
cd C:\Users\leona\Downloads\pipeline-caca-alucinacao\verificador
.\scripts\limitar_gpu.ps1 -Watts 420     # nvidia-smi -pl 420 (o limite é global da placa e vale para o WSL); perfil usado em todas as medições
```

### 1. Ambiente no WSL2 (Ubuntu)
```bash
cd /mnt/c/Users/leona/Downloads/pipeline-caca-alucinacao/verificador
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # numpy/pandas (só para a métrica oficial)
pip install -r requirements-llm.txt      # torch cu128 + transformers (5090 = Blackwell, CUDA ≥ 12.8)
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

### 2. Núcleo determinístico (o que gera a submissão de referência)
```bash
make dados ZIP=../arquivos/desafio-jusbrasil-bracis-2026.zip   # ou pule se dados/ já estiver completo
make indice && make sinteticos && make testar                  # 591 testes
make rodar && make avaliar                                     # 1,10000 esperado no dev
make submissao                                                 # submission.csv + submission_jsons.zip
```

### 3. Árbitro LLM (Qwen3.5-9B em NF4, revisão fixa; até a v1.2.5, Qwen2.5-7B-Instruct bf16) — ligado no padrão ouro, medido antes de valer
```bash
# tudo em um comando (baixa os pesos se faltarem, fumaça, medição núcleo × árbitro, dev, cache):
python scripts/rodar_llm_local.py                 # --rapido (padrão) ≈ 500 chamadas; --completo = todos os conjuntos
python scripts/rodar_llm_local.py --modelo /caminho/de/um/snapshot/local   # teste de fumaça com pesos já no disco
# passo a passo equivalente:
bash scripts/baixar_modelo.sh                     # ~15 GB; revisão de modelos/revisao_fixa.env, commit conferido
make comparar-arbitro ARBITRO=transformers CACHE_LLM=saida_llm/cache_llm.sqlite   # Δscore, τ, precisão, VEREDITO
make rodar ARBITRO=transformers SAIDA=saida_llm && make avaliar SAIDA=saida_llm
```
Pelo Windows, em um clique: `scripts\rodar_llm_wsl.cmd` (duplo clique no Explorador ou no
PowerShell; distro `debian-distro` e venv `/opt/bracis/venv` no topo do arquivo — edite se forem
outros). Ele instala o que faltar no venv, roda `scripts/rodar_llm_local.py` no WSL e deixa tudo em
`saida_llm\` (`log.txt` para acompanhar; `ambiente.json` com torch/transformers/GPU, `modelo.json`
com o hash dos pesos). Equivalente manual: `wsl.exe -d debian-distro --exec /opt/bracis/venv/bin/python
scripts/rodar_llm_local.py` a partir da pasta do repositório. O código limita a fração de VRAM para nunca passar de 24 GB numa GPU de 32 GB
(`torch.cuda.set_per_process_memory_fraction`), decodificação greedy com semente fixa, 1 prompt
por `generate`, cache em disco das respostas.

**O que decide se o árbitro entra na submissão** é o veredito de `scripts/comparar_arbitro.py`
(ADR 0003): nenhum conjunto pode cair mais que 0,0005, nenhum `inventada→real` pode aparecer, os
conjuntos que forçam os gatilhos (`r6_extrator_formas`, `r6_extrator_distratores`) têm de melhorar
sem falsos positivos, e o dev tem de ficar idêntico ou melhor. Com o `mock` (heurística, não o
modelo): 37/38 conjuntos byte a byte iguais ao núcleo e `r6_extrator_formas` +0,500 com τ = 0.
**Com o Qwen real** (RTX 5090, 20/09, medição 2 — `saida_llm/analise/log_medicao2.txt`):

| conjunto | núcleo | árbitro | Δ | LLM emitiu (certas) | s/doc |
|---|---|---|---|---|---|
| dev, n3_ood, r2_chave_parcial, r5_distratores_orgaos, r5_processos_ocr_combo, r6_extrator_distratores, ruido_n2, vagas | — | **idênticos** (byte a byte) | 0 | 0 (0) | 3,5–19,5 |
| r6_extrator_formas | 0,59657 | **1,07203** | **+0,47546** | 67 (66), τ = 0 | 24,1 |

→ **VEREDITO: LIGAR** (1.088 chamadas, 26 min). A medição 1 (mesma máquina, prompt anterior) tinha
dado MANTER DESLIGADO por FPs em distratores e normalização; a v1.2.1 fechou isso na validação
determinística (ADR 0003, "Medição 1"), não no modelo. A única extração errada da medição 2 era um
defeito do gerador (estado por extenso diferente do registro; corrigido na v1.2.2).

**Medição 3 — Qwen3.5-9B em NF4 no lugar do Qwen2.5** (v1.2.3; ADR 0003 "Medição 3"): mesmo
árbitro, mesmos prompts e validador, só os pesos mudam. Em um clique, `scripts\rodar_llm_q35_wsl.cmd`
(≈ 30–60 min; grava em `saida_llm_q35\`, log em `saida_llm_q35\log.txt`) — equivale a
`python scripts/rodar_llm_local.py --modelo /opt/bracis/models/qwen35_9b --id Qwen/Qwen3.5-9B
--revisao c202236235762e1c871ad0ccb60c8ee5ba337b9a --quatro-bits --saida saida_llm_q35`. O backend lê
`architectures` do `config.json`: a família `*ForConditionalGeneration` (Qwen3.5) é carregada pela
classe homônima do `transformers` (≥ 5), NF4 com `visual`/`lm_head` fora da quantização e o *chat
template* com `enable_thinking=False`; `--id`/`--revisao` põem o nome canônico e o commit dos pesos na
chave do cache (`CACA_MODELO_ID`), para o `cache_llm.jsonl` reproduzir sem a pasta local. O Qwen3.5 só
substitui o Qwen2.5 se passar no critério **e** ficar ≥ o Qwen2.5 em todos os conjuntos, dentro do
envelope de tempo (≤ 60 s/doc); empate → fica o Qwen2.5. Resultado (ADR 0003 "Medição 3"): passou —
8 de 9 idênticos, τ = 0, `r6_extrator_formas` 1,08398 medido (69 emitidas, 68 certas; a errada era uma
brecha do validador, `agravo em recurso especial` lido como AG+RESP, fechada na v1.2.5) e **1,09680**
no replay do cache pelo validador corrigido (69/69); 7,5 s/doc no dev, 17–39 s/doc nos adversariais.

**Reprodução sem GPU** do que o modelo respondeu: `saida_llm_q35/cache_llm.jsonl` (exportado ao fim
da medição 3; acompanha a submissão junto com `dados/`, **nunca versionado** — contém janelas dos
documentos) + `make reproduzir ARBITRO=transformers CACHE_LLM=saida_llm_q35/cache_llm.jsonl
REFERENCIA=submission.csv` (o modelo não é carregado, torch não é exigido, zero chamadas ao modelo, e
a saída é a mesma; ≈ 20 s com a suíte). A chave do cache inclui modelo, revisão e `CACA_LLM_4BIT`
(`modelos/revisao_fixa.env`): o cache do Qwen2.5 (`saida_llm/cache_llm.jsonl`, medição 2) só
responde com `CACA_MODELO=Qwen/Qwen2.5-7B-Instruct CACA_MODELO_REVISAO=a09a354… CACA_LLM_4BIT=`.
Equivalente manual: `CACA_LLM_SOMENTE_CACHE=1 CACA_LLM_CACHE_IMPORTAR=saida_llm_q35/cache_llm.jsonl make
rodar ARBITRO=transformers`. No dev a submissão com o árbitro é idêntica à do núcleo (o regex já
cobre tudo); a diferença aparece em formas que o regex não cobre — o que o conjunto cego pode trazer.

### 4. Docker (o comando exato da organização) e verificação de reprodutibilidade
```bash
make docker && make docker-rodar          # CPU, offline; compare saida/ com a do passo 2
make docker-llm                           # imagem com o árbitro (Dockerfile.llm; bases fixadas por digest)
bash scripts/docker_llm.sh [gpu]          # prova da imagem do árbitro: constrói, reproduz o dev DENTRO do container
                                          # só do cache (sem GPU) e, com `gpu`, carrega o Qwen3.5-9B NF4 na GPU;
                                          # compara os CSVs com saida_llm_q35/submission_llm.csv (Windows: scripts\docker_llm.cmd)
```

### 5. Kaggle
1. Envie `submission.csv` em **Submit Prediction** (o Kaggle aceita só o CSV; limite de 5 envios/dia por equipe).
2. Quando o conjunto cego for publicado na aba Data: coloque os `.txt` em `dados/cego/txt` e o
   `sample_submission.csv` do cego em `dados/cego/`, e rode **`scripts\rodar_cego_wsl.cmd`** (um clique;
   `python scripts/rodar_cego.py` no WSL/Linux): ele roda as **duas** versões — núcleo (`saida_cego/`)
   e núcleo + árbitro (`saida_cego_llm/`, Qwen3.5-9B NF4 do snapshot local, cache exportado em
   `saida_cego_llm/cache_llm.jsonl`) —, gera e valida `submission_cego_nucleo.csv` e
   `submission_cego_llm.csv` (conversor oficial, `--sample` do cego, zip dos JSONs) e imprime o tempo por
   documento (envelope 60 s), as citações por classe e em quantos documentos os dois CSVs diferem
   (`saida_cego\log.txt`). Equivalente à mão: `make rodar ENTRADA=dados/cego/txt SAIDA=saida_cego` e
   `make rodar ARBITRO=transformers …` + `scripts/gerar_submissao.py --sample <sample do cego>`.
3. Envie os dois CSVs e marque **os dois** em *Submissions → Select* antes de 30/09/2026 23h59 (BRT):
   o Kaggle conta a melhor das selecionadas no placar privado, então ligar o árbitro nunca rebaixa.
   O bundle reproduz os dois (o do árbitro pelo `cache_llm.jsonl` do cego, sem GPU:
   `reproduzir.py --entrada dados/cego/txt --arbitro transformers --cache-llm saida_cego_llm/cache_llm.jsonl`).

## Política de dados

Os dados do desafio (`dados/`) não podem ser redistribuídos: **nenhum trecho, número ou nome do
gabarito ou da base** aparece em código, testes, docs ou nos geradores adversariais — todos os
exemplos são sintéticos (os geradores consultam o índice por POSIÇÃO: `artigo_k("CLT", 1)` é
"o 2º artigo da CLT na tabela", seja ele qual for).
`scripts/analise/verificar_vazamento.py` deriva a lista proibida do catálogo local (ignorado pelo
git) e varre os arquivos versionados **e os novos ainda não adicionados**; `tests/test_vazamento.py`
falha se encontrar algo.

**Histórico limpo é exigência de publicação.** Um `git clone` redistribui todo commit, então antes
de publicar/entregar o repositório: (1) rode `make vazamento-historico`
(`verificar_vazamento.py --historico` varre as linhas adicionadas por `git log -p --all`); (2) se
houver ocorrências em commits antigos, reescreva o histórico — o caminho mais simples é um ramo
órfão com a árvore atual (`git checkout --orphan limpo && git add -A && git commit`), descartando
os ramos antigos, ou `git filter-repo` com a lista proibida — e rode o verificador de novo em cada
commit restante. Commits com dados do desafio nunca devem ser enviados a um remoto.
