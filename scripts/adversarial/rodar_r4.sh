#!/usr/bin/env bash
# Roda pipeline + avaliação oficial nos conjuntos adversariais da rodada 4 (engenheiro, revisão 3).
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=src
python scripts/adversarial/gerar_adversarial_r4.py --seed "${SEED:-444}" > /dev/null
for c in r4_vagas_relator_antes r4_ocr_duplo r4_cabecalhos_novos r4_negativas_vizinhas; do
  d=dados/adversarial/$c
  rm -rf saida/adv_$c
  python -m caca_alucinacao.cli --input $d/txt --output saida/adv_$c --db dados/desafio1_bracis.db \
      --indice dados/indice.json --arbitro nenhum --calibracao dados/calibracao.json --log-level ERROR \
      --rastro saida/adv_$c/rastro.jsonl 2>/dev/null
  printf "%-24s " $c
  python scripts/avaliar.py --saida saida/adv_$c --gabarito $d/goldenset.csv --txt $d/txt \
      --sample /nonexistent --json saida/adv_$c/relatorio.json --quieto 2>&1 | grep -E "^score_final|^Erros|inventada→real" | tr '\n' ' '
  echo
done
