# Caça-Alucinações — verificador de citações jurídicas (Jusbrasil × BRACIS 2026)

Encontra citações de jurisprudência e lei em pareceres (`.txt`) e classifica cada uma como `real`,
`inventada` ou `incompleta`, consultando a base canônica do desafio. A classe é sempre função
determinística da consulta à base por identificador; o LLM (**Qwen3.5-9B**, pesos originais, revisão
fixa, carregado em NF4) entra só como **extrator de segundo estágio** — aponta citações escritas de formas
que o regex não cobre, com toda proposta validada no texto e na base — e nunca classifica.

* Núcleo determinístico só com a biblioteca padrão do Python; roda em CPU em menos de 1 s por documento.
* Árbitro LLM (`--arbitro transformers`): 1 GPU de 24 GB, offline, ≈ 7 GB de VRAM, ≈ 6–10 s por documento.
* Saída sempre válida para a métrica oficial; toda execução se reproduz byte a byte, com ou sem GPU.
* Licença Apache-2.0 (`LICENSE`, `NOTICE`). Os dados do desafio **não** são distribuídos aqui.

A submissão final é gerada com o árbitro ligado (Qwen3.5-9B), ao lado da versão só com o núcleo (seção 3).
Decisões de projeto e medições em `docs/decisoes/` (ADR 0001–0007); arquitetura em `docs/02_arquitetura.md`;
modelo em `MANIFESTO_MODELO.md`. A versão 2 (o mesmo pipeline com um LLM treinado como camada final, medido
e desligado) está em <https://github.com/leo-vilela/kaggle_Jusbrasil_BRACIS_2026_LLM>.

## 1. Requisitos e dados

* Python ≥ 3.10. `numpy` e `pandas` **só** para a métrica oficial local (`pip install -r requirements.txt`).
* Para o árbitro LLM: GPU NVIDIA com ≥ 24 GB, `pip install -r requirements-llm.txt` (torch com CUDA 12.8,
  transformers 5.16.1, bitsandbytes 0.50.2 — versões pinadas) e os pesos do Qwen3.5-9B (seção 4).
* `make` é opcional: `make -n <alvo>` mostra o comando Python equivalente.

Os arquivos do desafio (aba *Data* do Kaggle) entram em `dados/` e ficam fora do git:

```bash
make dados ZIP=~/Downloads/desafio-jusbrasil-bracis-2026.zip   # extrai, confere SHA-256, gera o catálogo local
make indice                                                    # índice de números próprios (opcional: o CLI constrói em memória)
make sinteticos && make testar                                 # 596 testes; make lint = ruff + verificação de vazamento
```

No Windows, os `.cmd` em `scripts/` executam os mesmos passos pelo WSL 2 (distro e venv no topo de cada
arquivo — edite se os seus forem outros) e gravam o log na pasta de saída correspondente.

## 2. Rodar

```bash
make rodar                                        # núcleo: dados/txt → saida/*.json (+ saida/rastro.jsonl)
make rodar ARBITRO=transformers SAIDA=saida_llm   # núcleo + árbitro Qwen3.5-9B (GPU; pesos da seção 4)
make avaliar [SAIDA=…]                            # métrica oficial (kaggle_metric.py) + diagnóstico → relatorio.json
make submissao [SAIDA=…]                          # submission.csv pelo conversor oficial + validação + zip dos JSONs
```

O comando por trás de `make rodar` é o mesmo que o container executa:

```bash
PYTHONPATH=src python -m caca_alucinacao.cli --input dados/txt --output saida \
    --db dados/desafio1_bracis.db --calibracao dados/calibracao.json [--arbitro transformers] [--rastro saida/rastro.jsonl]
```

Todo caminho também pode vir do ambiente (`CACA_DB`, `CACA_INDICE`, `CACA_CALIBRACAO`, `CACA_ARBITRO`,
`CACA_MODELO`, `CACA_MODELO_REVISAO`, `CACA_LLM_4BIT`, `CACA_CACHE_LLM`, `CACA_MODELO_DIR`; ver
`src/caca_alucinacao/config.py`). Documento sem citações sai como `"citacoes": []`; erros de entrada
terminam com código 2 e mensagem, nunca com um "sucesso" de zero JSONs.

## 3. Conjunto cego (avaliação final)

Quando a organização publicar os `.txt` do conjunto cego na aba *Data*:

1. Coloque os `.txt` em `dados/cego/txt/` e o `sample_submission.csv` do cego em `dados/cego/`.
2. Rode, em um comando, as **duas** versões:

   ```bash
   python scripts/rodar_cego.py                  # Windows: scripts\rodar_cego_wsl.cmd (um clique)
   ```

   Ele executa o núcleo (`saida_cego/`) e o núcleo + árbitro Qwen3.5-9B (`saida_cego_llm/`), gera e valida
   `submission_cego_nucleo.csv` e `submission_cego_llm.csv` (conversor oficial, `sample_submission` do cego,
   zip dos JSONs), exporta `saida_cego_llm/cache_llm.jsonl` (todas as respostas do modelo, para reprodução
   sem GPU) e imprime o tempo por documento (envelope: média ≤ 60 s), as citações por classe e em quantos
   documentos os dois CSVs diferem. Opções: `--entrada`, `--sample`, `--sem-arbitro`, `--modelo <snapshot local>`.
3. Envie os dois CSVs em *Submit Prediction* e marque **os dois** em *Submissions → Select*: o Kaggle
   conta a melhor das selecionadas no placar privado, então ligar o árbitro nunca rebaixa o resultado.
4. Reprodução exata das duas saídas, em qualquer máquina, sem GPU (seção 5):

   ```bash
   python scripts/reproduzir.py --entrada dados/cego/txt --referencia submission_cego_nucleo.csv
   python scripts/reproduzir.py --entrada dados/cego/txt --arbitro transformers \
       --cache-llm saida_cego_llm/cache_llm.jsonl --referencia submission_cego_llm.csv
   ```

O `cache_llm.jsonl` contém janelas dos documentos do desafio: acompanha o bundle entregue à organização
e **não** entra no repositório.

## 4. Modelo (árbitro LLM): Qwen3.5-9B

| | |
|---|---|
| Modelo | `Qwen/Qwen3.5-9B` — https://huggingface.co/Qwen/Qwen3.5-9B — Apache-2.0, pesos originais, **sem fine-tuning** |
| Revisão fixa | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` (`modelos/revisao_fixa.env` = `MANIFESTO_MODELO.md` = padrão do `Dockerfile.llm`) |
| Carga | `Qwen3_5ForConditionalGeneration` (transformers ≥ 5), NF4 com bitsandbytes (`CACA_LLM_4BIT=1`; `visual` e `lm_head` fora da quantização), ≈ 7 GB de VRAM |
| Decodificação | greedy, semente fixa, 1 prompt por `generate`, chat template oficial com `enable_thinking=False`; `max_new_tokens` 480 na extração |
| Cache | toda resposta em SQLite (`CACA_CACHE_LLM`), exportável em JSONL; com `CACA_LLM_SOMENTE_CACHE=1` o modelo nem é carregado |

Pesos (máquina com internet; o container é offline):

```bash
source modelos/revisao_fixa.env && bash scripts/baixar_modelo.sh   # → modelos/hf (cache do Hugging Face), commit conferido
```

Um snapshot já baixado também serve: `CACA_MODELO=/caminho/do/snapshot CACA_MODELO_ID=Qwen/Qwen3.5-9B`
(o nome canônico entra na chave do cache no lugar do caminho; é o que `scripts/rodar_llm_q35_wsl.cmd` e
`rodar_cego_wsl.cmd` fazem). Medição do árbitro em todos os conjuntos, com veredito automático:
`python scripts/rodar_llm_local.py` (`make comparar-arbitro ARBITRO=transformers` por baixo; ADR 0003).
A alternativa medida anteriormente (`Qwen/Qwen2.5-7B-Instruct` em bf16, mesma saída nos documentos reais,
menos formas recuperadas) está documentada no `MANIFESTO_MODELO.md` e na ADR 0003.

## 5. Reprodutibilidade

### 5.1 Em um comando, sem GPU

```bash
make reproduzir REFERENCIA=submission.csv                                                                   # núcleo
make reproduzir ARBITRO=transformers CACHE_LLM=saida_llm_q35/cache_llm.jsonl REFERENCIA=submission.csv     # com o árbitro, só do cache
```

`scripts/reproduzir.py` confere os SHA-256 dos dados oficiais, gera os derivados que faltarem, roda a
suíte de testes e a verificação de vazamento, roda o pipeline **duas vezes** (a segunda reconstruindo o
índice em memória) exigindo saídas byte a byte idênticas, aplica a métrica e o conversor oficiais e, com
`--referencia`, compara o CSV gerado com o entregue. Com `--cache-llm`, o árbitro responde **só do cache**
exportado (zero chamadas ao modelo; torch não é carregado; falha se alguma janela ficar sem resposta).
Código de saída 0 só com tudo conferido.

### 5.2 Docker — o comando exato da organização

Duas imagens, bases fixadas por digest, dependências pinadas com `==`; nenhum dado nem peso dentro
(só `dados/calibracao.json`, artefato nosso):

```bash
make docker        # caca-alucinacao:latest — núcleo, CPU            (Dockerfile)
make docker-llm    # caca-alucinacao:llm    — núcleo + árbitro, GPU  (Dockerfile.llm; --build-arg CACA_MODELO_REVISAO da revisão fixa)
```

Núcleo (CPU, offline):

```bash
docker run --rm --network none \
  -v /caminho/txt:/data/in:ro -v /caminho/saida:/data/out \
  -v /caminho/desafio1_bracis.db:/data/base/desafio1_bracis.db:ro \
  caca-alucinacao:latest --input /data/in --output /data/out
```

Núcleo + árbitro Qwen3.5-9B na GPU (pesos de `scripts/baixar_modelo.sh` montados em `/modelos`; a imagem
já aponta `HF_HOME=/modelos/hf`, modo offline, revisão fixa e NF4):

```bash
docker run --rm --network none --gpus all \
  -v /caminho/txt:/data/in:ro -v /caminho/saida:/data/out \
  -v /caminho/desafio1_bracis.db:/data/base/desafio1_bracis.db:ro \
  -v $PWD/modelos:/modelos:ro \
  caca-alucinacao:llm --input /data/in --output /data/out --arbitro transformers
# snapshot local no lugar do cache do Hugging Face: -e CACA_MODELO=/modelos/<pasta> -e CACA_MODELO_ID=Qwen/Qwen3.5-9B
```

Núcleo + árbitro **sem GPU**, reproduzindo exatamente a saída submetida a partir do cache exportado:

```bash
docker run --rm --network none \
  -v /caminho/txt:/data/in:ro -v /caminho/saida:/data/out \
  -v /caminho/desafio1_bracis.db:/data/base/desafio1_bracis.db:ro \
  -v /caminho/da/pasta/com/cache_llm.jsonl:/data/cache:ro \
  -e CACA_LLM_SOMENTE_CACHE=1 -e CACA_LLM_CACHE_IMPORTAR=/data/cache/cache_llm.jsonl \
  caca-alucinacao:llm --input /data/in --output /data/out --arbitro transformers
```

Em seguida, `python json_to_submission.py /caminho/saida submission.csv` (conversor oficial) ou
`scripts/gerar_submissao.py --saida /caminho/saida --destino submission.csv --sample <sample_submission>`.

Prova da imagem do árbitro em um comando — constrói, reproduz o conjunto de desenvolvimento **dentro do
container** só do cache e, com `gpu`, carrega o Qwen3.5-9B na GPU; compara os CSVs com o da medição de referência:

```bash
bash scripts/docker_llm.sh [gpu]          # Windows: scripts\docker_llm.cmd [gpu]
```

Resultado verificado: build OK; só do cache → CSV idêntico (0 chamadas, 0 abstenções); com GPU → 7,3 GB de
VRAM, 100 chamadas reais ao modelo, ≈ 6 s/doc, CSV idêntico.

A imagem roda como root de propósito (`/data/out` é um bind mount da organização); `--user $(id -u):$(id -g)`
funciona se a pasta de saída for gravável por esse usuário.

### 5.3 Determinismo

`PYTHONHASHSEED=0`, semente fixa, ordenação explícita, sem iteração sobre `set`; no árbitro, greedy,
TF32 desligado, `CUBLAS_WORKSPACE_CONFIG=:4096:8`, um prompt por `generate`. Entre GPUs diferentes a
aritmética bf16/NF4 pode divergir em alguma janela; por isso a saída submetida é sempre acompanhada do
`cache_llm.jsonl`, que a reproduz byte a byte em qualquer hardware.

## 6. Como funciona (resumo)

```
.txt ─▶ deteccao (regex) ─▶ llm.extrator (janelas com pistas sem achado; propostas validadas no texto) ─┐
                                                                                                        ▼
        contrato (JSON 1.2) ◀─ calibracao ◀─ resolucao ◀─ base_canonica ◀─ normalizacao ◀─ achados (regex ∪ llm)
```

* `deteccao/` + `normalizacao.py`: regex por família (processo, súmula, dispositivo, vaga, tema) e
  normalização de OCR — um dígito nunca vira outro dígito.
* `base_canonica/`: índice de números **próprios** (nunca "quem cita"), súmulas e dispositivos.
* `resolucao.py`: classe pela cardinalidade da consulta (1 registro → `real` com `id_canonico`; 0 →
  `inventada`; identificador insuficiente → `incompleta`).
* `calibracao.py`: confiança por caminho de decisão, treinada de forma reproduzível com validação fora da
  amostra e com as extrações reais do Qwen3.5 (`make calibrar-completo CACHE_LLM=saida_llm_q35/cache_llm.jsonl`, ADR 0007).
* `llm/`: o árbitro — `extrator.py` (2º estágio), validação determinística em `arbitro.py`, backends
  `transformers`/`vllm`/`mock`, cache exportável. Critério para ligar: `make comparar-arbitro` (ADR 0003).
* `contrato.py`: JSON 1.2 e `validar()` espelhando tudo que a métrica rejeita; sobreposições são saneadas.

Resultados (métrica oficial): conjunto de desenvolvimento **1,10000** (máximo), sintéticos 1,10000 / 1,09986,
34 conjuntos adversariais entre 1,027 e 1,10000, todos com τ = 0 (nenhum `inventada→real`). O árbitro
Qwen3.5-9B, medido com o modelo real, deixa 8 de 9 conjuntos byte a byte idênticos ao núcleo (dev incluído)
e recupera as formas que o regex não cobre (`r6_extrator_formas`: 0,597 → 1,100, 69 extrações, 69 certas).
Tabelas completas e o critério de decisão: `docs/decisoes/0003-arbitro-llm.md`.

## 7. Política de dados

Os dados do desafio não podem ser redistribuídos: nenhum trecho, número ou nome do gabarito ou da base
aparece em código, testes, docs ou nos geradores adversariais (todos os exemplos são sintéticos).
`scripts/analise/verificar_vazamento.py` deriva a lista proibida do catálogo local e varre os arquivos
versionados e os novos (`make vazamento`; `make vazamento-historico` varre também o histórico do git);
`tests/test_vazamento.py` falha se encontrar algo. Pastas de saída, caches do árbitro e submissões ficam
fora do git (`.gitignore`) e fora das imagens (`.dockerignore`).
