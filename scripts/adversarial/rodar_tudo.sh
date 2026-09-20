#!/usr/bin/env bash
# Roda pipeline + avaliação oficial nos 8 conjuntos adversariais da rodada 1 (gera-os antes, em dados/adversarial/).
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=src
python scripts/adversarial/gerar_adversarial.py --seed "${SEED:-2026}" > /dev/null
for c in siglas conectores ruido_n2 vagas distratores frases cabecalhos normativos; do
  d=dados/adversarial/$c
  rm -rf saida/adv_$c
  python -m caca_alucinacao.cli --input $d/txt --output saida/adv_$c --db dados/desafio1_bracis.db \
      --indice dados/indice.json --arbitro nenhum --calibracao dados/calibracao.json \
      --log-level ERROR --rastro saida/adv_$c/rastro.jsonl 2>/dev/null || \
  python -m caca_alucinacao.cli --input $d/txt --output saida/adv_$c --db dados/desafio1_bracis.db \
      --indice dados/indice.json --arbitro nenhum --calibracao dados/calibracao.json --log-level ERROR
  python scripts/avaliar.py --saida saida/adv_$c --gabarito $d/goldenset.csv --txt $d/txt \
      --sample /nonexistent --json saida/adv_$c/relatorio.json --quieto 2>&1 | grep -E "score|Score|N1|N2|tau|τ|brier|Brier" | head -12
  echo "=== $c acima ==="
done
