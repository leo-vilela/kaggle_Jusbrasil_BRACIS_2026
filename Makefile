# Caça-Alucinações (Jusbrasil × BRACIS 2026) — atalhos de desenvolvimento e reprodução.
# Todos os alvos aceitam sobrescrita de variáveis: make rodar SAIDA=saida_v2 ARBITRO=mock
PYTHON     ?= python3
ZIP        ?= desafio-jusbrasil-bracis-2026.zip
ENTRADA    ?= dados/txt
SAIDA      ?= saida
DB         ?= dados/desafio1_bracis.db
INDICE     ?= dados/indice.json
CALIBRACAO ?= dados/calibracao.json
ARBITRO    ?= nenhum
RASTRO     ?= $(SAIDA)/rastro.jsonl
RELATORIO  ?= relatorio.json
SUBMISSAO  ?= submission.csv
REFERENCIA ?=
IMAGEM     ?= caca-alucinacao:latest
IMAGEM_LLM ?= caca-alucinacao:llm
# a imagem roda como root (ver Dockerfile); para um usuário sem privilégios: make docker-rodar DOCKER_USER='--user $(id -u):$(id -g)'
DOCKER_USER ?=
export PYTHONPATH := src
export PYTHONHASHSEED := 0

.PHONY: ajuda reproduzir dados catalogo indice testar lint vazamento vazamento-historico rodar avaliar submissao sinteticos adversarial calibrar calibrar-completo comparar-arbitro docker docker-rodar docker-digests docker-llm limpar

ajuda:
	@echo "alvos: reproduzir dados indice testar lint rodar avaliar submissao sinteticos adversarial calibrar docker docker-rodar docker-llm limpar"
	@echo "ex.: make dados ZIP=~/Downloads/desafio-jusbrasil-bracis-2026.zip && make indice && make rodar && make avaliar"

reproduzir:       ## tudo de uma vez: SHA-256 dos dados, derivados, testes, vazamento, pipeline 2x (byte a byte), métrica oficial, CSV
	$(PYTHON) scripts/reproduzir.py $(if $(REFERENCIA),--referencia $(REFERENCIA),)

dados:            ## extrai o zip da aba Data para dados/, confere SHA-256 e offsets do gabarito; gera o catálogo local
	$(PYTHON) scripts/preparar_dados.py --zip $(ZIP) --dados dados
	$(PYTHON) scripts/analise/catalogar_gabarito.py --dados dados --saida dados/catalogo_gabarito.json

catalogo:         ## dados/catalogo_gabarito.json (ignorado pelo git): exigido pela verificação de vazamento
	$(PYTHON) scripts/analise/catalogar_gabarito.py --dados dados --saida dados/catalogo_gabarito.json

indice:           ## índice de números próprios (SQLite -> JSON); opcional: o CLI constrói em memória se faltar
	$(PYTHON) scripts/construir_indice.py --db $(DB) --saida $(INDICE)

testar:           ## suíte completa (unittest; os testes com dados reais e o de vazamento exigem dados/ e o catálogo de make dados)
	$(PYTHON) -m unittest discover -s tests -v

lint:             ## ruff (só se instalado) + verificação de vazamento de dados do desafio
	@if command -v ruff >/dev/null 2>&1; then ruff check src scripts tests; else echo "ruff ausente; lint ignorado"; fi
	$(PYTHON) scripts/analise/verificar_vazamento.py

vazamento:        ## falha se algum trecho/número/nome do gabarito ou da base estiver em arquivo versionado (ou novo)
	$(PYTHON) scripts/analise/verificar_vazamento.py

vazamento-historico: ## idem, inspecionando também todo o histórico do git (obrigatório antes de publicar)
	$(PYTHON) scripts/analise/verificar_vazamento.py --historico

rodar:            ## gera um JSON por .txt em $(SAIDA) (mesmo comando que o container executa)
	$(PYTHON) -m caca_alucinacao.cli --input $(ENTRADA) --output $(SAIDA) --db $(DB) --indice $(INDICE) \
	    --arbitro $(ARBITRO) --calibracao $(CALIBRACAO) --rastro $(RASTRO)

avaliar:          ## métrica oficial + diagnóstico sobre $(SAIDA) (relatório JSON em $(RELATORIO))
	$(PYTHON) scripts/avaliar.py --saida $(SAIDA) --rastro $(RASTRO) --json $(RELATORIO)

submissao:        ## submission.csv via conversor oficial + validação + zip dos JSONs
	$(PYTHON) scripts/gerar_submissao.py --saida $(SAIDA) --destino $(SUBMISSAO)

sinteticos:       ## conjuntos sintéticos que os testes e a calibração esperam (docs/05; determinístico por seed)
	$(PYTHON) scripts/gerar_sinteticos.py --saida dados/sinteticos/n2_dev --n-docs 40 --nivel 2 --seed 123 --perfil dev
	$(PYTHON) scripts/gerar_sinteticos.py --saida dados/sinteticos/n3_ood --n-docs 40 --nivel 3 --seed 7
	$(PYTHON) scripts/gerar_sinteticos.py --saida dados/sinteticos/n2_ag_treino --n-docs 60 --nivel 2 --seed 321 --perfil agressivo

adversarial:      ## regenera os 34 conjuntos adversariais das revisões (scripts/adversarial/, seeds fixas) e roda pipeline + métrica em cada um
	bash scripts/adversarial/rodar_todos.sh

calibrar:         ## ajuste rápido de $(CALIBRACAO) a partir de UM rastro (scripts/treinar_calibracao.py); o oficial é calibrar-completo
	$(PYTHON) scripts/treinar_calibracao.py --rastro $(RASTRO) --relatorio $(RELATORIO) --saida $(CALIBRACAO)

calibrar-completo: ## retreino oficial e reproduzível: regenera sintéticos + 34 adversariais, pipeline em 38 conjuntos, treina em 37 e valida em n3_ood; compara com dados/calibracao.json (GRAVAR=1 grava)
	$(PYTHON) scripts/calibrar_completo.py $(if $(GRAVAR),--gravar,)

comparar-arbitro: ## núcleo × árbitro (ARBITRO=mock|transformers|vllm) em todos os conjuntos, com a métrica oficial: Δscore, τ, precisão do extrator e VEREDITO (ADR 0003)
	$(PYTHON) scripts/comparar_arbitro.py --arbitro $(if $(filter nenhum,$(ARBITRO)),mock,$(ARBITRO)) $(if $(CACHE_LLM),--cache $(CACHE_LLM),)

docker:           ## imagem do núcleo determinístico (sem dados nem pesos); a calibração viaja dentro
	@test -f $(CALIBRACAO) || { echo '{}' > $(CALIBRACAO); echo "AVISO: $(CALIBRACAO) ausente; criada vazia"; }
	docker build -t $(IMAGEM) .

docker-rodar:     ## contrato de execução da organização, tal qual será rodado na verificação
	mkdir -p $(SAIDA)
	docker run --rm --network none $(DOCKER_USER) \
	    -v $(abspath $(ENTRADA)):/data/in:ro \
	    -v $(abspath $(SAIDA)):/data/out \
	    -v $(abspath $(DB)):/data/base/desafio1_bracis.db:ro \
	    $(IMAGEM) --input /data/in --output /data/out

# commit dos pesos: MODELO_REVISAO=<commit>, senão a revisão fixa versionada (modelos/revisao_fixa.env)
MODELO_REVISAO ?= $(shell sed -n 's/^export CACA_MODELO_REVISAO="\([0-9a-f]*\)".*/\1/p' modelos/revisao_fixa.env)
docker-digests:   ## imprime os digests das imagens-base para fixar em FROM …@sha256:… (exige acesso ao registry; R3b-07)
	@for img in python:3.12-slim pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime; do \
	  docker pull -q $$img >/dev/null && docker inspect --format='FROM {{index .RepoDigests 0}}   # '$$img $$img; done

docker-llm:       ## imagem com CUDA para o árbitro LLM (exige o commit dos pesos; ver Dockerfile.llm)
	@test -n "$(MODELO_REVISAO)" || { echo "MODELO_REVISAO vazio: confira modelos/revisao_fixa.env ou passe MODELO_REVISAO=<commit>"; exit 1; }
	docker build -f Dockerfile.llm --build-arg CACA_MODELO_REVISAO=$(MODELO_REVISAO) -t $(IMAGEM_LLM) .

limpar:
	rm -rf $(SAIDA) $(RELATORIO) $(SUBMISSAO) $(basename $(SUBMISSAO))_jsons.zip .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
