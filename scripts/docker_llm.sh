#!/usr/bin/env bash
# Prova da imagem de submissão com o árbitro (Dockerfile.llm): constrói e roda o dev DENTRO do container nos três
# modos de execução, comparando cada CSV com o de referência (byte a byte):
#   A. núcleo sem LLM            (--arbitro nenhum; CPU)                                   → sempre
#   B. núcleo + LLM só do cache  (--arbitro transformers + CACA_LLM_SOMENTE_CACHE=1; CPU)  → sempre
#   C. núcleo + LLM na GPU       (--arbitro transformers + --gpus all + pesos montados)    → só com o argumento `gpu`
#
#   bash scripts/docker_llm.sh          build + modos A e B (sem GPU)
#   bash scripts/docker_llm.sh gpu      build + modos A, B e C (C carrega o Qwen3.5-9B em NF4 de MODELOS_DIR/SNAPSHOT,
#                                       padrão /opt/bracis/models/qwen35_9b — o caminho que a organização roda)
# Referência: saida_llm_q35/submission_llm.csv (no dev os modos A, B e C produzem o mesmo CSV; no cego A pode
# diferir de B/C, que são sempre iguais entre si). Saídas em saida_docker/. Exige docker (Docker Desktop com
# integração WSL, ou docker nativo) e, para `gpu`, o NVIDIA Container Toolkit.
set -uo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
IMG="${IMG:-caca-alucinacao:llm}"
MODELOS_DIR="${MODELOS_DIR:-/opt/bracis/models}"
SNAPSHOT="${SNAPSHOT:-qwen35_9b}"
PY="${PY:-python3}"
REF="saida_llm_q35/submission_llm.csv"
CACHE="saida_llm_q35/cache_llm.jsonl"
command -v docker >/dev/null 2>&1 || { echo "ERRO: docker não encontrado (Docker Desktop: Settings → Resources → WSL integration → ative esta distro)"; exit 1; }
[ -f "$CACHE" ] || { echo "ERRO: $CACHE ausente (rode scripts/rodar_llm_q35_wsl.cmd antes)"; exit 1; }
[ -f "$REF" ] || { echo "ERRO: $REF ausente"; exit 1; }
REV="$(sed -n 's/^export CACA_MODELO_REVISAO="\([0-9a-f]*\)".*/\1/p' modelos/revisao_fixa.env)"
[ -n "$REV" ] || { echo "ERRO: revisão dos pesos não encontrada em modelos/revisao_fixa.env"; exit 1; }
mkdir -p saida_docker
echo "[$(date '+%F %T')] docker build -f Dockerfile.llm --build-arg CACA_MODELO_REVISAO=$REV -t $IMG ." | tee saida_docker/build.log
docker build -f Dockerfile.llm --build-arg "CACA_MODELO_REVISAO=$REV" -t "$IMG" . >> saida_docker/build.log 2>&1 \
  || { echo "BUILD FALHOU — veja saida_docker/build.log"; tail -20 saida_docker/build.log; exit 1; }
echo "build ok: $IMG ($(docker image inspect --format='{{.Size}}' "$IMG" | awk '{printf "%.1f GB", $1/1e9}'))"

csv() {  # csv <pasta com JSONs> <destino.csv>
  PYTHONPATH=src "$PY" scripts/gerar_submissao.py --saida "$1" --destino "$2" --sem-zip >> saida_docker/csv.log 2>&1 \
    || { echo "CSV FALHOU ($1) — veja saida_docker/csv.log"; return 1; }
}
comparar() {  # comparar <csv> <rótulo>
  if cmp -s "$1" "$REF"; then echo "IDÊNTICO ($2): $1 == $REF"; else echo "DIFERE ($2): $1 × $REF"; return 1; fi
}

# A. núcleo sem LLM (CPU) --------------------------------------------------------------------------------
rm -rf saida_docker/out_nucleo && mkdir -p saida_docker/out_nucleo
docker run --rm --network none \
  -v "$RAIZ/dados/txt:/data/in:ro" -v "$RAIZ/saida_docker/out_nucleo:/data/out" \
  -v "$RAIZ/dados/desafio1_bracis.db:/data/base/desafio1_bracis.db:ro" \
  "$IMG" --input /data/in --output /data/out --arbitro nenhum > saida_docker/run_nucleo.log 2>&1 \
  || { echo "CONTAINER (modo A, núcleo) FALHOU — veja saida_docker/run_nucleo.log"; tail -20 saida_docker/run_nucleo.log; exit 1; }
csv saida_docker/out_nucleo saida_docker/submission_docker_nucleo.csv || exit 1
comparar saida_docker/submission_docker_nucleo.csv "modo A: núcleo sem LLM" || exit 1

# B. núcleo + LLM só do cache (sem GPU): a mesma saída em qualquer máquina ------------------------------------
rm -rf saida_docker/out && mkdir -p saida_docker/out
docker run --rm --network none \
  -v "$RAIZ/dados/txt:/data/in:ro" -v "$RAIZ/saida_docker/out:/data/out" \
  -v "$RAIZ/dados/desafio1_bracis.db:/data/base/desafio1_bracis.db:ro" \
  -v "$RAIZ/saida_llm_q35:/data/cache:ro" \
  -e CACA_LLM_SOMENTE_CACHE=1 -e CACA_LLM_CACHE_IMPORTAR=/data/cache/cache_llm.jsonl \
  "$IMG" --input /data/in --output /data/out --arbitro transformers > saida_docker/run_cache.log 2>&1 \
  || { echo "CONTAINER FALHOU — veja saida_docker/run_cache.log"; tail -20 saida_docker/run_cache.log; exit 1; }
grep -o '"chamadas_ao_modelo": [0-9]*\|"abstencoes": [0-9]*' saida_docker/out/arbitro_estatisticas.log 2>/dev/null | tr '\n' ' '; echo
csv saida_docker/out saida_docker/submission_docker.csv || exit 1
comparar saida_docker/submission_docker.csv "modo B: LLM só do cache" || exit 1
[ "${1:-}" = "gpu" ] || { echo "Terminado (modos A e B, sem GPU). Para o modo C, com a GPU: bash scripts/docker_llm.sh gpu"; exit 0; }

# C. núcleo + LLM na GPU: o modelo real, NF4, do snapshot local ----------------------------------------------
[ -d "$MODELOS_DIR/$SNAPSHOT" ] || { echo "ERRO: snapshot $MODELOS_DIR/$SNAPSHOT ausente (MODELOS_DIR/SNAPSHOT)"; exit 1; }
rm -rf saida_docker/out_gpu && mkdir -p saida_docker/out_gpu
t0=$(date +%s)
docker run --rm --network none --gpus all \
  -v "$RAIZ/dados/txt:/data/in:ro" -v "$RAIZ/saida_docker/out_gpu:/data/out" \
  -v "$RAIZ/dados/desafio1_bracis.db:/data/base/desafio1_bracis.db:ro" \
  -v "$MODELOS_DIR:/modelos:ro" \
  -e "CACA_MODELO=/modelos/$SNAPSHOT" -e CACA_MODELO_ID=Qwen/Qwen3.5-9B \
  "$IMG" --input /data/in --output /data/out --arbitro transformers > saida_docker/run_gpu.log 2>&1 \
  || { echo "CONTAINER COM GPU FALHOU — veja saida_docker/run_gpu.log"; tail -30 saida_docker/run_gpu.log; exit 1; }
echo "GPU: $(( $(date +%s) - t0 )) s para $(ls saida_docker/out_gpu/*.json | wc -l) documentos; $(grep -o '"chamadas_ao_modelo": [0-9]*\|"abstencoes": [0-9]*' saida_docker/out_gpu/arbitro_estatisticas.log 2>/dev/null | tr '\n' ' ')"
csv saida_docker/out_gpu saida_docker/submission_docker_gpu.csv || exit 1
comparar saida_docker/submission_docker_gpu.csv "modo C: LLM na GPU" || exit 1
echo "Terminado: a imagem constrói e os três modos (núcleo, LLM do cache, LLM na GPU) produzem o CSV esperado."
