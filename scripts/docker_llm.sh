#!/usr/bin/env bash
# Prova da imagem de submissão com o árbitro (Dockerfile.llm): constrói `caca-alucinacao:llm` e roda os documentos
# DENTRO do container nos três modos de execução, comparando cada CSV com o de referência (byte a byte):
#   A. núcleo sem LLM            (--arbitro nenhum; CPU)                                   → sempre
#   B. núcleo + LLM só do cache  (--arbitro transformers + CACA_LLM_SOMENTE_CACHE=1; CPU)  → sempre
#   C. núcleo + LLM na GPU       (--arbitro transformers + --gpus all + pesos montados)    → só com o argumento `gpu`
#
#   bash scripts/docker_llm.sh              conjunto de DESENVOLVIMENTO (dados/txt): build + modos A e B
#   bash scripts/docker_llm.sh gpu          idem + modo C (carrega o Qwen3.5-9B em NF4 de MODELOS_DIR/SNAPSHOT)
#   bash scripts/docker_llm.sh cego         conjunto CEGO (dados/cego/txt, depois de scripts/rodar_cego.py): build + A e B,
#                                           comparando com submission_cego_nucleo.csv e submission_cego_llm.csv
#   bash scripts/docker_llm.sh cego gpu     idem + modo C
#
# Este script NÃO gera a submissão do cego — isso é scripts/rodar_cego.py (Windows: rodar_cego_wsl.cmd). Ele prova
# que a imagem que a organização vai rodar reproduz os CSVs já gerados. Referências: no dev,
# saida_llm_q35/submission_llm.csv para os três modos (A = B = C no dev); no cego, o CSV do núcleo para A e o do
# LLM para B e C. Saídas em saida_docker/ (dev) ou saida_docker_cego/ (cego). Exige docker (Docker Desktop com
# integração WSL, ou docker nativo) e, para `gpu`, o NVIDIA Container Toolkit.
set -uo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
IMG="${IMG:-caca-alucinacao:llm}"
MODELOS_DIR="${MODELOS_DIR:-/opt/bracis/models}"
SNAPSHOT="${SNAPSHOT:-qwen35_9b}"
PY="${PY:-python3}"

GPU=0; CEGO=0
for a in "$@"; do
  case "$a" in
    gpu) GPU=1 ;;
    cego) CEGO=1 ;;
    *) echo "argumento desconhecido: $a (use: [cego] [gpu])"; exit 2 ;;
  esac
done
if [ "$CEGO" = 1 ]; then
  ENTRADA="dados/cego/txt"; SAMPLE="dados/cego/sample_submission.csv"
  CACHE="saida_cego_llm/cache_llm.jsonl"; REF_NUCLEO="submission_cego_nucleo.csv"; REF_LLM="submission_cego_llm.csv"
  SAIDA="saida_docker_cego"; ROTULO="conjunto cego"
else
  ENTRADA="dados/txt"; SAMPLE="dados/sample_submission.csv"
  CACHE="saida_llm_q35/cache_llm.jsonl"; REF_NUCLEO="saida_llm_q35/submission_llm.csv"; REF_LLM="saida_llm_q35/submission_llm.csv"
  SAIDA="saida_docker"; ROTULO="conjunto de desenvolvimento"
fi

falhar() { echo "ERRO: $*"; exit 1; }
command -v docker >/dev/null 2>&1 || falhar "docker não encontrado (Docker Desktop: Settings → Resources → WSL integration → ative esta distro)"
[ -d "$ENTRADA" ] && ls "$ENTRADA"/*.txt >/dev/null 2>&1 || falhar "nenhum .txt em $ENTRADA$([ "$CEGO" = 1 ] && echo ' — coloque os .txt do cego em dados/cego/txt e o sample_submission.csv do cego em dados/cego/, rode scripts/rodar_cego.py e só então este script')"
[ -f "$SAMPLE" ] || falhar "$SAMPLE ausente$([ "$CEGO" = 1 ] && echo ' (o sample_submission.csv publicado com o cego)')"
[ -f "$CACHE" ] || falhar "$CACHE ausente — $([ "$CEGO" = 1 ] && echo 'rode scripts/rodar_cego.py (modo C) primeiro; ele exporta o cache' || echo 'rode scripts/rodar_llm_q35_wsl.cmd antes')"
[ -f "$REF_NUCLEO" ] || falhar "$REF_NUCLEO ausente$([ "$CEGO" = 1 ] && echo ' — rode scripts/rodar_cego.py primeiro')"
[ -f "$REF_LLM" ] || falhar "$REF_LLM ausente$([ "$CEGO" = 1 ] && echo ' — rode scripts/rodar_cego.py primeiro')"
REV="$(sed -n 's/^export CACA_MODELO_REVISAO="\([0-9a-f]*\)".*/\1/p' modelos/revisao_fixa.env)"
[ -n "$REV" ] || falhar "revisão dos pesos não encontrada em modelos/revisao_fixa.env"
mkdir -p "$SAIDA"
N_TXT=$(ls "$ENTRADA"/*.txt | wc -l)
echo "prova da imagem no $ROTULO: $N_TXT documentos em $ENTRADA; referências: A ← $REF_NUCLEO, B/C ← $REF_LLM; cache: $CACHE"
echo "[$(date '+%F %T')] docker build -f Dockerfile.llm --build-arg CACA_MODELO_REVISAO=$REV -t $IMG ." | tee "$SAIDA/build.log"
docker build -f Dockerfile.llm --build-arg "CACA_MODELO_REVISAO=$REV" -t "$IMG" . >> "$SAIDA/build.log" 2>&1 \
  || { echo "BUILD FALHOU — veja $SAIDA/build.log"; tail -20 "$SAIDA/build.log"; exit 1; }
echo "build ok: $IMG ($(docker image inspect --format='{{.Size}}' "$IMG" | awk '{printf "%.1f GB", $1/1e9}'))"

csv() {  # csv <pasta com JSONs> <destino.csv>  — o Python roda a partir da raiz; tenta 3× (a montagem /mnt/c às vezes falha logo após um container soltar o bind mount)
  local tentativa
  for tentativa in 1 2 3; do
    ( cd "$RAIZ" && PYTHONPATH=src "$PY" scripts/gerar_submissao.py --saida "$1" --destino "$2" --sample "$SAMPLE" --txt "$ENTRADA" --sem-zip ) >> "$SAIDA/csv.log" 2>&1 && return 0
    echo "  (csv: tentativa $tentativa falhou; repetindo em 3 s)" | tee -a "$SAIDA/csv.log"; sleep 3
  done
  echo "CSV FALHOU ($1) — últimas linhas de $SAIDA/csv.log:"; tail -12 "$SAIDA/csv.log"; return 1
}
comparar() {  # comparar <csv> <referência> <rótulo>
  if cmp -s "$1" "$2"; then echo "IDÊNTICO ($3): $1 == $2"; else echo "DIFERE ($3): $1 × $2"; return 1; fi
}
rodar_modo() {  # rodar_modo <pasta de saída> <log> <argumentos extras do docker run…> -- <argumentos do CLI…>
  local pasta="$1" log="$2"; shift 2
  local extras=(); while [ $# -gt 0 ] && [ "$1" != "--" ]; do extras+=("$1"); shift; done; shift || true
  rm -rf "$pasta" && mkdir -p "$pasta"
  docker run --rm --network none ${extras[@]+"${extras[@]}"} \
    -v "$RAIZ/$ENTRADA:/data/in:ro" -v "$RAIZ/$pasta:/data/out" \
    -v "$RAIZ/dados/desafio1_bracis.db:/data/base/desafio1_bracis.db:ro" \
    "$IMG" --input /data/in --output /data/out "$@" > "$log" 2>&1
}
estat() { grep -o '"chamadas_ao_modelo": [0-9]*\|"abstencoes": [0-9]*' "$1/arbitro_estatisticas.log" 2>/dev/null | tr '\n' ' '; }

# A. núcleo sem LLM (CPU) --------------------------------------------------------------------------------
rodar_modo "$SAIDA/out_nucleo" "$SAIDA/run_nucleo.log" -- --arbitro nenhum \
  || { echo "CONTAINER (modo A, núcleo) FALHOU — veja $SAIDA/run_nucleo.log"; tail -20 "$SAIDA/run_nucleo.log"; exit 1; }
csv "$SAIDA/out_nucleo" "$SAIDA/submission_docker_nucleo.csv" || exit 1
comparar "$SAIDA/submission_docker_nucleo.csv" "$REF_NUCLEO" "modo A: núcleo sem LLM" || exit 1

# B. núcleo + LLM só do cache (sem GPU): a mesma saída em qualquer máquina ------------------------------------
rodar_modo "$SAIDA/out" "$SAIDA/run_cache.log" -v "$RAIZ/$(dirname "$CACHE"):/data/cache:ro" \
  -e CACA_LLM_SOMENTE_CACHE=1 -e "CACA_LLM_CACHE_IMPORTAR=/data/cache/$(basename "$CACHE")" -- --arbitro transformers \
  || { echo "CONTAINER (modo B, LLM só do cache) FALHOU — veja $SAIDA/run_cache.log"; tail -20 "$SAIDA/run_cache.log"; exit 1; }
echo "modo B: $(estat "$SAIDA/out")"
csv "$SAIDA/out" "$SAIDA/submission_docker.csv" || exit 1
comparar "$SAIDA/submission_docker.csv" "$REF_LLM" "modo B: LLM só do cache" || exit 1
[ "$GPU" = 1 ] || { echo "Terminado (modos A e B, sem GPU). Para o modo C, com a GPU: bash scripts/docker_llm.sh $([ "$CEGO" = 1 ] && echo 'cego ')gpu"; exit 0; }

# C. núcleo + LLM na GPU: o modelo real, NF4, do snapshot local ----------------------------------------------
[ -d "$MODELOS_DIR/$SNAPSHOT" ] || falhar "snapshot $MODELOS_DIR/$SNAPSHOT ausente (MODELOS_DIR/SNAPSHOT)"
t0=$(date +%s)
rodar_modo "$SAIDA/out_gpu" "$SAIDA/run_gpu.log" --gpus all -v "$MODELOS_DIR:/modelos:ro" \
  -e "CACA_MODELO=/modelos/$SNAPSHOT" -e CACA_MODELO_ID=Qwen/Qwen3.5-9B -- --arbitro transformers \
  || { echo "CONTAINER (modo C, LLM na GPU) FALHOU — veja $SAIDA/run_gpu.log"; tail -30 "$SAIDA/run_gpu.log"; exit 1; }
echo "modo C: $(( $(date +%s) - t0 )) s para $N_TXT documentos; $(estat "$SAIDA/out_gpu")"
csv "$SAIDA/out_gpu" "$SAIDA/submission_docker_gpu.csv" || exit 1
comparar "$SAIDA/submission_docker_gpu.csv" "$REF_LLM" "modo C: LLM na GPU" || exit 1
echo "Terminado: a imagem constrói e os três modos (núcleo, LLM do cache, LLM na GPU) reproduzem os CSVs do $ROTULO."
