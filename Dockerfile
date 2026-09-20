# Núcleo determinístico (sem árbitro LLM). Sem dados do desafio nem pesos dentro:
# o banco entra por volume e o índice é construído em memória na partida (~0,2 s).
#
# Contrato de execução da organização:
#   docker run --rm --network none \
#     -v <txt>:/data/in:ro -v <saida>:/data/out \
#     -v <db>:/data/base/desafio1_bracis.db:ro \
#     <imagem> --input /data/in --output /data/out
# Fixe por digest antes do build de referência (docker inspect --format='{{index .RepoDigests 0}}'):
# a tag slim muda com cada patch do 3.12/Debian (R3b-07).
FROM python:3.12-slim

ENV PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    CACA_DB=/data/base/desafio1_bracis.db \
    CACA_INDICE=/app/dados/indice.json \
    CACA_CALIBRACAO=/app/dados/calibracao.json \
    CACA_ARBITRO=nenhum

WORKDIR /app
# Núcleo: só biblioteca padrão (requirements.txt fica vazio de propósito).
COPY pyproject.toml README.md /app/
COPY src/ /app/src/
# Tabela de calibração (artefato nosso, pequeno; `make docker` cria uma vazia se faltar).
COPY dados/calibracao.json /app/dados/calibracao.json

# Cinto e suspensórios do .dockerignore (**/__pycache__/): a imagem nunca carrega bytecode do
# desenvolvedor, para que o conteúdo seja reproduzível byte a byte (R3q-07).
RUN mkdir -p /data/in /data/out /data/base \
    && find /app -name __pycache__ -type d -prune -exec rm -rf {} + \
    && find /app -name '*.pyc' -delete
# Roda como root de propósito (revisão R3-02): /data/out é um bind mount criado pela
# organização e herda o dono/modo do host — com um usuário sem privilégios (uid 1000)
# uma pasta root:755 daria PermissionError e ZERO JSONs. O processo não abre rede
# (--network none), não escreve fora de /data/out e a imagem não guarda segredos.
# Quem preferir um usuário sem privilégios passa `--user $(id -u):$(id -g)` no
# `docker run` (o CLI confere a permissão de escrita logo na partida e explica o erro).

ENTRYPOINT ["python", "-m", "caca_alucinacao.cli"]
CMD ["--input", "/data/in", "--output", "/data/out"]
