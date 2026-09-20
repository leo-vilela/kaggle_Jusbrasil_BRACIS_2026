#!/usr/bin/env bash
# Baixa os pesos do árbitro LLM do Hugging Face com revisão fixa e registra o
# commit efetivamente baixado (MANIFESTO_MODELO.md + modelos/manifesto_modelo.json).
#
# Onde rodar: na máquina COM internet (o WSL2 do usuário, RTX 5090). O container
# da organização é OFFLINE: os pesos entram por volume (o cache do Hugging Face
# montado em $HF_HOME) e o código roda com HF_HUB_OFFLINE=1.
#
# Uso:
#   bash scripts/baixar_modelo.sh                       # modelo e revisão FIXOS de modelos/revisao_fixa.env (MANIFESTO_MODELO.md)
#   bash scripts/baixar_modelo.sh -r <commit_hash>      # revisão fixa (o que o bundle final deve usar)
#   bash scripts/baixar_modelo.sh -m Qwen/Qwen2.5-7B-Instruct -r a09a35458c702b33eeacc393d103063234e8bc28   # alternativa medida (v1.0-1.2.5)
#   bash scripts/baixar_modelo.sh --sha256              # também calcula SHA-256 de cada arquivo (lento: ~18 GB)
#
# Variáveis: HF_HOME (padrão: $PWD/modelos/hf), HF_TOKEN (não é necessário: o repositório é público).
# Depois: exporte CACA_MODELO_REVISAO=<commit> (ou use o .env gerado em modelos/modelo.env).
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Padrão: a revisão FIXA versionada (modelos/revisao_fixa.env); -r/CACA_MODELO_REVISAO sobrescrevem.
FIXA_MODELO="$(sed -n 's/^export CACA_MODELO="\([^"]*\)".*/\1/p' "$RAIZ/modelos/revisao_fixa.env" 2>/dev/null || true)"
FIXA_REVISAO="$(sed -n 's/^export CACA_MODELO_REVISAO="\([^"]*\)".*/\1/p' "$RAIZ/modelos/revisao_fixa.env" 2>/dev/null || true)"
MODELO="${CACA_MODELO:-${FIXA_MODELO:-Qwen/Qwen3.5-9B}}"
REVISAO="${CACA_MODELO_REVISAO:-${FIXA_REVISAO:-main}}"
CALCULAR_SHA=0
export HF_HOME="${HF_HOME:-$RAIZ/modelos/hf}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--modelo) MODELO="$2"; shift 2 ;;
    -r|--revisao) REVISAO="$2"; shift 2 ;;
    --sha256) CALCULAR_SHA=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$HF_HOME" "$RAIZ/modelos"
echo "modelo:  $MODELO"
echo "revisão: $REVISAO"
echo "HF_HOME: $HF_HOME"

# CLI: 'hf' (huggingface_hub >= 0.34) ou 'huggingface-cli' (versões anteriores)
if command -v hf >/dev/null 2>&1; then
  CLI=(hf download)
elif command -v huggingface-cli >/dev/null 2>&1; then
  CLI=(huggingface-cli download)
else
  echo "instale a CLI do Hugging Face: pip install -U 'huggingface_hub[cli]'" >&2
  exit 2
fi

# O download devolve o diretório do snapshot: .../models--Org--Nome/snapshots/<commit>
SNAPSHOT="$("${CLI[@]}" "$MODELO" --revision "$REVISAO" 2>/dev/null | tail -n 1)"
if [[ ! -d "$SNAPSHOT" ]]; then
  echo "falha no download (saída: $SNAPSHOT)" >&2
  exit 1
fi
COMMIT="$(basename "$SNAPSHOT")"
if [[ ! "$COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "aviso: o nome do snapshot não parece um commit ($COMMIT); conferindo refs/…" >&2
  REPO_DIR="$(dirname "$(dirname "$SNAPSHOT")")"
  [[ -f "$REPO_DIR/refs/$REVISAO" ]] && COMMIT="$(cat "$REPO_DIR/refs/$REVISAO")"
fi
echo "commit:  $COMMIT"
echo "snapshot: $SNAPSHOT"
# Revisão fixa: o commit resolvido tem de ser o pedido (uma tag/branch que "andou" é erro).
if [[ "$REVISAO" =~ ^[0-9a-f]{40}$ && "$COMMIT" != "$REVISAO" ]]; then
  echo "ERRO: commit resolvido ($COMMIT) difere da revisão fixa pedida ($REVISAO)" >&2
  exit 1
fi

# Manifesto JSON (auditoria): arquivos, tamanhos e (opcional) SHA-256.
MANIFESTO_JSON="$RAIZ/modelos/manifesto_modelo.json"
python3 - "$MODELO" "$REVISAO" "$COMMIT" "$SNAPSHOT" "$CALCULAR_SHA" "$MANIFESTO_JSON" <<'PY'
import hashlib, json, os, sys, time
modelo, revisao_pedida, commit, snapshot, sha, destino = sys.argv[1:7]
arquivos = []
total = 0
for nome in sorted(os.listdir(snapshot)):
    caminho = os.path.join(snapshot, nome)
    if not os.path.isfile(caminho):
        continue
    tam = os.path.getsize(caminho)
    total += tam
    item = {"arquivo": nome, "bytes": tam}
    if sha == "1":
        h = hashlib.sha256()
        with open(caminho, "rb") as f:
            for bloco in iter(lambda: f.read(1 << 20), b""):
                h.update(bloco)
        item["sha256"] = h.hexdigest()
    arquivos.append(item)
manifesto = {
    "modelo": modelo,
    "url": f"https://huggingface.co/{modelo}",
    "revisao_pedida": revisao_pedida,
    "revisao": commit,
    "url_revisao": f"https://huggingface.co/{modelo}/tree/{commit}",
    "snapshot": snapshot,
    "bytes_total": total,
    "baixado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "arquivos": arquivos,
}
with open(destino, "w", encoding="utf-8") as f:
    json.dump(manifesto, f, ensure_ascii=False, indent=2)
print(f"manifesto: {destino} ({total/1024**3:.2f} GB em {len(arquivos)} arquivos)")
PY

# Variáveis de ambiente para o pipeline (source modelos/modelo.env)
cat > "$RAIZ/modelos/modelo.env" <<EOF
export CACA_MODELO="$MODELO"
export CACA_MODELO_REVISAO="$COMMIT"
export HF_HOME="$HF_HOME"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
EOF
echo "ambiente: $RAIZ/modelos/modelo.env"

# Aviso se o commit baixado não for o fixado no MANIFESTO (o bundle final usa a revisão fixa).
if [[ -n "$FIXA_REVISAO" && "$COMMIT" != "$FIXA_REVISAO" && "$MODELO" == "$FIXA_MODELO" ]]; then
  echo "aviso: commit baixado ($COMMIT) ≠ revisão fixa de modelos/revisao_fixa.env ($FIXA_REVISAO): só para auditoria" >&2
fi

cat <<EOF

Próximos passos:
  source modelos/modelo.env
  PYTHONPATH=src python scripts/avaliar_arbitro.py --arbitro transformers --casos dados/sinteticos/n3_ood/casos_llm.jsonl
No container offline, monte $HF_HOME em /modelos/hf e exporte HF_HOME=/modelos/hf HF_HUB_OFFLINE=1.
EOF
