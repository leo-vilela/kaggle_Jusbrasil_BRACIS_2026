# Caça-Alucinações — verificador de citações jurídicas (Jusbrasil × BRACIS 2026)

> Estado (20/09/2026, após a revisão da rodada 4): **todos os módulos prontos e testados**
> (563 testes, `make testar`). Núcleo determinístico só com biblioteca padrão; score no
> conjunto de desenvolvimento **1,10000** (1,0999975; τ = 0), nos sintéticos n2/n3 1,10000 /
> 1,09987 e nos 32 conjuntos adversariais das quatro rodadas de revisão entre 1,027 e 1,10000
> (30 deles ≥ 1,085), todos com τ = 0 (ver `docs/decisoes/0005-deteccao.md`, `0006-resolucao.md`
> e `0007-calibracao.md`, seções "Revisão da rodada 4"; geradores em `scripts/adversarial/`,
> `make adversarial`). O árbitro LLM (`llm/`) é opcional, desligado por padrão
> (`--arbitro nenhum`) e **residual por desenho** — 0 chamadas no dev (ADR 0003, rodada 4); a
> submissão de referência é a do núcleo. Histórico de fases em `docs/02_arquitetura.md`.

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
.txt ─▶ deteccao ─▶ normalizacao ─▶ base_canonica ─▶ resolucao ─▶ calibracao ─▶ contrato (JSON 1.2)
                                                          └─▶ llm.arbitro (só casos residuais, opcional)
```

| módulo (`src/caca_alucinacao/`) | papel | estado |
|---|---|---|
| `tipos.py` | `Achado`, `Decisao`, `iou`, enums | pronto |
| `base_canonica/` | índice de números **próprios** (nunca "quem cita"), súmulas e dispositivos | pronto (cobertura 96/96 no dev) |
| `contrato.py` | dataclasses do JSON 1.2, `validar()` espelhando tudo que a métrica rejeita | pronto |
| `pipeline.py` | `processar_texto`/`processar_pasta`: injeção de dependência, saída sempre válida, rastro de decisões | pronto |
| `cli.py`, `config.py` | linha de comando do container; caminhos por `CACA_*` | pronto |
| `deteccao/`, `normalizacao.py` | regex por família + normalização de OCR (núcleos ambíguos nunca viram chave parcial) | pronto (192/192 spans no dev) |
| `resolucao.py`, `calibracao.py` | classe por cardinalidade da consulta; reparo determinístico de OCR; confiança por caminho de decisão | pronto (1,10000 no dev; τ = 0) |
| `llm/` | árbitro Qwen (pesos abertos, revisão fixa, decodificação determinística) | pronto, opcional (`--arbitro transformers`; `Dockerfile.llm`) |
| `scripts/analise/verificar_vazamento.py` | lint: nenhum trecho/número/nome do gabarito ou da base em arquivo versionado (`make vazamento`; também roda em `make testar`) | pronto |
| `scripts/adversarial/` | geradores dos 32 conjuntos adversariais das revisões (gabarito por construção a partir de `dados/indice.json`; sem nenhum número da base no código — consultas posicionais) + `rodar_*.sh` + `erros.py` (diagnóstico) | pronto |

Decisões registradas em `docs/decisoes/`; especificações medidas nos dados em `docs/03_*` e `docs/04_*`.

## Como reproduzir passo a passo

Requisitos: Python ≥ 3.10 (núcleo só com biblioteca padrão); `numpy` e `pandas` **apenas** para a
avaliação local com o script oficial (`pip install -r requirements.txt`). `make` opcional.

**Em um comando** (com `dados/` já preenchido pelo passo 1 abaixo):

```bash
make reproduzir REFERENCIA=../submission_v1_1.csv   # ou: python scripts/reproduzir.py --referencia ../submission_v1_1.csv
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
make adversarial       # regenera os 32 conjuntos adversariais (scripts/adversarial/, seeds fixas) em
                       # dados/adversarial/ e roda pipeline + métrica oficial em cada um (~1 min)

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

Variante com árbitro LLM (GPU): `Dockerfile.llm` (base `pytorch/pytorch:2.7.1-cuda12.8` — cobre
Blackwell/RTX 5090 e as anteriores; `requirements-llm.txt` pinado com `==`; pesos baixados por
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

### 0. Limite de potência (450 W) — PowerShell **como administrador**, no Windows
```powershell
cd C:\Users\leona\Downloads\pipeline-caca-alucinacao\verificador
.\scripts\limitar_gpu.ps1 -Watts 450     # nvidia-smi -pl 450 (o limite é global da placa e vale para o WSL)
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
make indice && make sinteticos && make testar                  # 563 testes
make rodar && make avaliar                                     # 1,10000 esperado no dev
make submissao                                                 # submission.csv + submission_jsons.zip
```

### 3. Árbitro LLM (Qwen2.5-7B-Instruct, revisão fixa) — opcional, residual por desenho
```bash
bash scripts/baixar_modelo.sh            # ~15 GB; usa a revisão de modelos/revisao_fixa.env e confere o commit
make rodar ARBITRO=transformers SAIDA=saida_llm
make avaliar SAIDA=saida_llm             # deve reproduzir a saída do núcleo (0 chamadas no dev)
python scripts/avaliar_arbitro.py --arbitro transformers --casos dados/sinteticos/n3_ood/casos_llm.jsonl
```
O código limita a fração de VRAM para nunca passar de 24 GB numa GPU de 32 GB
(`torch.cuda.set_per_process_memory_fraction`), decodificação greedy com semente fixa e cache em
disco das respostas (`cache_llm/`).

### 4. Docker (o comando exato da organização) e verificação de reprodutibilidade
```bash
make docker && make docker-rodar          # CPU, offline; compare saida/ com a do passo 2
make docker-digests                       # fixa as imagens-base por digest (exige rede)
```

### 5. Kaggle
1. Envie `submission.csv` em **Submit Prediction** (o Kaggle aceita só o CSV; limite de 5 envios/dia por equipe).
2. Quando o conjunto cego for publicado na aba Data: coloque os `.txt` em `dados/cego/txt` e rode
   `make rodar ENTRADA=dados/cego/txt SAIDA=saida_cego` e
   `python scripts/gerar_submissao.py --saida saida_cego --destino submission_cego.csv --sample <sample_submission do cego>`.
3. Marque as 2 submissões finais em *Submissions → Select* antes de 30/09/2026 23h59 (BRT).

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
