#!/usr/bin/env bash
# Regenera TODOS os conjuntos adversariais (34; seeds fixas) e roda pipeline + métrica oficial em cada um.
# Uso: bash scripts/adversarial/rodar_todos.sh            (≈ 1 min; exige dados/indice.json e dados/desafio1_bracis.db)
set -u
cd "$(dirname "$0")/../.."
for s in rodar_tudo.sh rodar_r2.sh rodar_r3.sh rodar_r4.sh rodar_r5.sh rodar_r6.sh; do
  bash "scripts/adversarial/$s"
done
