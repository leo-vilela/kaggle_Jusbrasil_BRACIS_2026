#!/usr/bin/env bash
# Roda pipeline + avaliação oficial nos conjuntos adversariais da rodada 2.
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=src
python scripts/adversarial/gerar_adversarial_r2.py --seed "${SEED:-7777}" > /dev/null
for c in r2_chave_parcial r2_normativos_ruido r2_vagas_ordem r2_processos_forma r2_duplicatas r2_listas r2_fora_da_base; do
  d=dados/adversarial/$c
  rm -rf saida/adv_$c
  python -m caca_alucinacao.cli --input $d/txt --output saida/adv_$c --db dados/desafio1_bracis.db \
      --indice dados/indice.json --arbitro nenhum --calibracao dados/calibracao.json --log-level ERROR 2>/dev/null
  printf "%-22s " $c
  python scripts/avaliar.py --saida saida/adv_$c --gabarito $d/goldenset.csv --txt $d/txt \
      --sample /nonexistent --json saida/adv_$c/relatorio.json --quieto 2>&1 | grep -E "^score_final|^Erros|inventada→real" | tr '\n' ' '
  echo
done
