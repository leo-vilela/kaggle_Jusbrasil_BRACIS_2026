#!/usr/bin/env bash
# Roda pipeline + avaliação oficial nos conjuntos adversariais da rodada 6 (os que FORÇAM o extrator LLM).
# Sem árbitro o recall de r6_extrator_formas cai por construção; a medição com o árbitro é
# scripts/comparar_arbitro.py (núcleo × árbitro, Δscore, τ, precisão do extrator, veredito).
set -u
cd "$(dirname "$0")/../.."
export PYTHONPATH=src
python scripts/adversarial/gerar_adversarial_r6.py --seed "${SEED:-666}" > /dev/null
for c in r6_extrator_formas r6_extrator_distratores; do
  d=dados/adversarial/$c
  rm -rf saida/adv_$c
  python -m caca_alucinacao.cli --input $d/txt --output saida/adv_$c --db dados/desafio1_bracis.db \
      --indice dados/indice.json --arbitro "${ARBITRO:-nenhum}" --calibracao dados/calibracao.json --log-level ERROR \
      --rastro saida/adv_$c/rastro.jsonl 2>/dev/null
  printf "%-26s " $c
  python scripts/avaliar.py --saida saida/adv_$c --gabarito $d/goldenset.csv --txt $d/txt \
      --sample /nonexistent --json saida/adv_$c/relatorio.json --quieto 2>&1 | grep -E "^score_final|^Erros|inventada→real" | tr '\n' ' '
  echo
done
