#!/usr/bin/env bash
# Roda pipeline + avaliação oficial nos conjuntos adversariais da rodada 5 (revisor 2, 4ª revisão).
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=src
python scripts/adversarial/gerar_adversarial_r5.py --seed "${SEED:-555}" > /dev/null
for c in r5_vagas_lavra_final r5_processos_plural_nos r5_normativos_ocr r5_processos_ocr_combo r5_distratores_orgaos r5_layouts; do
  d=dados/adversarial/$c
  rm -rf saida/adv_$c
  python -m caca_alucinacao.cli --input $d/txt --output saida/adv_$c --db dados/desafio1_bracis.db \
      --indice dados/indice.json --arbitro nenhum --calibracao dados/calibracao.json --log-level ERROR \
      --rastro saida/adv_$c/rastro.jsonl 2>/dev/null
  printf "%-26s " $c
  python scripts/avaliar.py --saida saida/adv_$c --gabarito $d/goldenset.csv --txt $d/txt \
      --sample /nonexistent --json saida/adv_$c/relatorio.json --quieto 2>&1 | grep -E "^score_final|^Erros|inventada→real" | tr '\n' ' '
  echo
done
