#!/usr/bin/env bash
# Roda pipeline + avaliação oficial nos conjuntos adversariais da rodada 3.
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=src
python scripts/adversarial/gerar_adversarial_r3.py --seed "${SEED:-333}" > /dev/null
for c in r3_atos_normativos r3_enumeracoes r3_vagas_redacao r3_sumulas_forma r3_dispositivos_forma r3_caps_corpo r3_prefixo_tribunal; do
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
