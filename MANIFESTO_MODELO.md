# Manifesto do modelo — árbitro LLM

Exigência do desafio (regras, aba "Modelos"): só pesos abertos, referenciados por
link do Hugging Face **com revisão fixa (commit)**, decodificação determinística,
execução offline num container com 1 GPU de 24 GB, média ≤ 60 s/documento.
Este arquivo é a referência de modelos do bundle; `modelos/manifesto_modelo.json`
(gerado por `scripts/baixar_modelo.sh`) traz a lista de arquivos e tamanhos.

## Modelo

| Campo | Valor |
|---|---|
| Nome | `Qwen/Qwen3.5-9B` (v1.3.0; ADR 0003 "Medição 3") |
| Link | https://huggingface.co/Qwen/Qwen3.5-9B |
| Licença | Apache-2.0 (LICENSE no repositório do modelo) |
| Revisão (commit) | `c202236235762e1c871ad0ccb60c8ee5ba337b9a`; link fixo: https://huggingface.co/Qwen/Qwen3.5-9B/tree/c202236235762e1c871ad0ccb60c8ee5ba337b9a — a mesma revisão está em `modelos/revisao_fixa.env` (versionado) e é o valor padrão de `--build-arg CACA_MODELO_REVISAO` no `Dockerfile.llm`; `scripts/baixar_modelo.sh -r` confere o commit resolvido contra ela |
| Variável | `CACA_MODELO_REVISAO=<commit>` — obrigatória: o backend **recusa** (código 2) revisão vazia, salvo `CACA_MODELO` apontando para um snapshot local (então o hash de `config.json` + shards vai para o log e, sem `CACA_MODELO_ID`, para a chave do cache); `Dockerfile.llm` grava-a como `ENV` a partir de `--build-arg` (padrão = a revisão acima) e o build falha se ela for esvaziada |
| Quantização | **NF4** (bitsandbytes 0.50.2, dupla quantização, cálculo bf16; `CACA_LLM_4BIT=1`, fixado em `modelos/revisao_fixa.env` e no `Dockerfile.llm`) aplicada na carga aos pesos originais; `visual` (encoder de imagem, não usado) e `lm_head` ficam em bf16. `CACA_LLM_4BIT` entra na assinatura do backend e, portanto, na chave do cache |
| Arquitetura | `Qwen3_5ForConditionalGeneration` (multimodal; só texto é usado), 32 camadas, atenção híbrida, vocabulário 248k; carregada pela classe homônima do `transformers` 5.16.1, SDPA, sem kernels do Hub, *chat template* oficial com `enable_thinking=False` (sem bloco de raciocínio) |
| Parâmetros | ≈ 9 B |
| Formato | safetensors bf16 (≈ 18 GB em disco; ≈ 7 GB de VRAM em NF4) |
| Alternativa medida | `Qwen/Qwen2.5-7B-Instruct`, revisão `a09a35458c702b33eeacc393d103063234e8bc28` (`main` em 2025-01-11; https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/tree/a09a35458c702b33eeacc393d103063234e8bc28; Apache-2.0; bf16 ≈ 15,2 GB; `Qwen2ForCausalLM`, 28 camadas): o árbitro da v1.0–v1.2.5 (medições 1 e 2, ADR 0003) — mesma saída nos documentos reais, menos formas recuperadas (67 × 69 em `r6_extrator_formas`), 2–5× mais rápido por janela; `bash scripts/baixar_modelo.sh -m Qwen/Qwen2.5-7B-Instruct -r a09a35458c702b33eeacc393d103063234e8bc28` e `CACA_LLM_4BIT=""` |
| Quantizada oficial do Qwen2.5 | `Qwen/Qwen2.5-7B-Instruct-AWQ`, revisão `b25037543e9394b818fdfca67ab2a00ecc7dd641` (2024-10-09; https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-AWQ/tree/b25037543e9394b818fdfca67ab2a00ecc7dd641; Apache-2.0; ≈ 5,6 GB; requer `autoawq`/kernels; não medida) |
| Fine-tuning | **nenhum** — pesos originais, sem adaptação; nada a publicar |

Por que este modelo: docs/decisoes/0003-arbitro-llm.md ("Medição 3": 8 de 9 conjuntos idênticos ao
núcleo, τ = 0, 0 emissões nos distratores, 69 de 69 extrações certas nas formas que o regex não cobre,
contra 67 do Qwen2.5; dentro do envelope de tempo).

## VRAM e tempo esperados (envelope: 24 GB, offline)

| Configuração | VRAM | Latência medida/esperada |
|---|---|---|
| **Qwen3.5-9B NF4, `transformers`, greedy (padrão, v1.3.0)** | ≈ 7 GB (pesos) + KV/ativações → **≈ 8–10 GB** | RTX 5090 (420 W): 7,5 s/doc no dev (≈ 4 janelas/doc; ≈ 2 s por janela de extração), 17–39 s/doc nos adversariais densos em janelas; L4/A10 ≈ 3–4× mais lento por janela — o orçamento interno do extrator (30 s/doc) corta janelas antes de o envelope de 60 s/doc ser tocado |
| Qwen2.5-7B-Instruct bf16, `transformers`, greedy (v1.0–v1.2.5) | ≈ 15,5 GB + ≈ 1–2 GB → ≈ 17–18 GB | RTX 5090: 7,0 s/doc no dev, 3,5–24 s/doc nos adversariais (medição 2) |
| vLLM bf16, `gpu_memory_utilization` calculado para 24 GB | reserva ≈ 22 GB (pesos + KV cache pré-alocado) | prefill em lote; melhor throughput; só medido com o Qwen2.5 |

Orçamento de tempo: o árbitro é **residual** (docs/04, h.3): nos documentos reais do dev ele não
emite nada (as citações já vêm do regex) e o custo é o das janelas consultadas (≈ 4 por documento).
O cache em disco (`CACA_CACHE_LLM`) elimina chamadas repetidas.

Numa GPU maior (RTX 5090, 32 GB) o backend `transformers` chama
`torch.cuda.set_per_process_memory_fraction(24/32)` e o vLLM recebe
`gpu_memory_utilization = 24·0,92/32 ≈ 0,69`: o processo nunca usa mais de 24 GB,
o que reproduz o envelope da organização.

## Decodificação (determinística)

* `transformers`: `do_sample=False`, `num_beams=1`, `temperature=None`, `top_p=None`,
  `top_k=None`, `repetition_penalty=1.0`, `max_new_tokens` = 96 / 64 / 160 / 480 por operação
  (`normalizar` / `escolher` / `classificar` / `extrair` — o extrator de segundo estágio, ADR 0003),
  `torch.manual_seed(1234)` antes de cada `generate`, TF32 desligado, chat template
  oficial do modelo (`apply_chat_template(add_generation_prompt=True)`; nos modelos com modo de
  raciocínio, Qwen3.x, `enable_thinking=False` — a resposta é o JSON, direto), **um prompt por
  `generate` (lote = 1, sem padding)** — a resolução consulta o árbitro um achado por vez e a
  decodificação greedy em lote com padding pode diferir numericamente da de prompt único;
  `CACA_LLM_LOTE` > 1 existe só para medição e entra na assinatura do backend (logo na chave
  do cache), de modo que respostas de lotes diferentes nunca se misturam.
* `vllm`: `temperature=0`, `top_p=1`, `top_k=-1`, `seed=1234`, `dtype=bfloat16`,
  `max_model_len=4096`, decodificação guiada por esquema JSON quando a versão suporta.
* Toda resposta passa por parsing tolerante + validação estrita; qualquer falha =
  abstenção (`None`). Respostas e resultados ficam em `CACA_CACHE_LLM` (SQLite) e
  podem ser exportados com `CacheLLM.exportar_jsonl` — o JSONL exportado da submissão
  permite reproduzir a saída **sem GPU** (`somente_cache=True`).

Determinismo entre GPUs diferentes (L4 × 4090 × 5090) não é garantido pelo
hardware em bf16 nem nos kernels NF4 (ordem de redução nos kernels). Mitigações: prompts curtos com
resposta curta e estruturada; validação que rejeita qualquer resposta fora do
domínio; cache exportado junto com a submissão; uso residual (a esmagadora maioria
das decisões é do núcleo determinístico e não depende do modelo). Ver ADR 0003.

## Download (máquina com internet; o container é offline)

```bash
pip install -U "huggingface_hub[cli]"
source modelos/revisao_fixa.env                  # CACA_MODELO + CACA_MODELO_REVISAO + CACA_LLM_4BIT fixados (versionado)
bash scripts/baixar_modelo.sh                    # baixa a revisão fixada e confere o commit resolvido
bash scripts/baixar_modelo.sh -r main            # só para AUDITAR se main mudou (o bundle usa a revisão fixa)
source modelos/modelo.env                        # exporta CACA_MODELO, CACA_MODELO_REVISAO, HF_HOME, *_OFFLINE=1
```

O script chama `hf download` (ou `huggingface-cli download`) com `--revision`,
grava `modelos/manifesto_modelo.json` (arquivos, bytes, SHA-256 com `--sha256`) e
falha se o commit resolvido for diferente do fixado em `modelos/revisao_fixa.env`
(a menos que `-r` peça outra revisão explicitamente). No container: montar `modelos/` em `/modelos`
(`-v $PWD/modelos:/modelos:ro`); o `Dockerfile.llm` já define `HF_HOME=/modelos/hf`,
`HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1`, e `config.preparar_ambiente_hf` aponta
`HF_HOME` para `<CACA_MODELO_DIR>/hf` sempre que a pasta existir e `HF_HOME` não estiver
definido — nada a exportar à mão (`transformers` carrega por `revision=<commit>` do cache
local; `CACA_MODELO` também aceita o caminho de um snapshot, e um snapshot em
`CACA_MODELO_DIR` com `config.json` é usado diretamente).

## O que o árbitro pode e não pode decidir

Pode (sempre sujeito a validação e reconsulta determinística):

1. **Normalizar** um identificador que a normalização determinística não leu
   (`normalizar_citacao`): devolve cadeia de classes, dígitos, UF e tribunal. Os
   dígitos são aceitos **só** se forem obtidos do trecho por trocas letra→dígito
   do mapa de OCR (`O→0, l/I→1, S→5, g/q→9, G→6, B→8, Z→2`); um dígito ASCII
   alterado, removido ou inserido invalida a resposta. O pipeline então
   **reconsulta o índice** com os dígitos: o modelo nunca produz um `id_canonico`.
2. **Escolher entre candidatos** que o índice já devolveu (`escolher_candidato`),
   quando ≥ 2 registros com cabeçalhos diferentes sobram após tribunal/UF/classe.
   Devolve um índice na lista ou `None` (sem critério no contexto).
3. **Confirmar/descartar e ajustar fronteiras** de um candidato fraco de padrão
   amplo (`classificar_span`): família, tipo e span literal dentro da janela; o span
   devolvido precisa ser substring da janela e sobrepor o candidato original.

Não pode:

* inventar, corrigir ou "aproximar" dígitos (garantia do desafio: dígito nunca vira
  dígito); trocar a UF do trecho; criar `id_canonico`;
* classificar `real`/`inventada`/`incompleta` — a classe é sempre consequência da
  consulta por identificador à base fechada;
* substituir o detector ou o resolvedor: sem árbitro (`--arbitro nenhum`) o
  pipeline roda inteiro e determinístico; o Mock heurístico (`--arbitro mock`) é
  o fallback sem GPU.
