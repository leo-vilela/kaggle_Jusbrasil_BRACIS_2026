@echo off
rem Medição do árbitro LLM na GPU, pelo WSL2, em um clique (duplo clique neste arquivo ou `scripts\rodar_llm_wsl.cmd`).
rem Usa a distro e o venv abaixo (edite se os seus forem outros); grava tudo em saida_llm\ (log.txt, ambiente.json,
rem modelo.json, comparacao\comparacao_arbitro.json, dev_arbitro\, submission_llm.csv, cache_llm.jsonl).
rem Argumentos extras vão para scripts/rodar_llm_local.py (ex.: --completo, --modelo /opt/bracis/models/x, --so dev).
setlocal
set "DISTRO=debian-distro"
set "PYWSL=/opt/bracis/venv/bin/python"
cd /d "%~dp0.."
if not exist saida_llm mkdir saida_llm
echo [%date% %time%] iniciando no WSL (%DISTRO%) em %CD% > saida_llm\log.txt
wsl.exe --distribution %DISTRO% --exec bash -lc "cd \"$(wslpath -u '%CD%')\" && PY=%PYWSL%; [ -x \"$PY\" ] || PY=python3; echo \"python: $PY\" >> saida_llm/log.txt; \"$PY\" -c 'import torch, transformers, huggingface_hub' 2>>saida_llm/log.txt || \"$PY\" -m pip install -r requirements-llm.txt >> saida_llm/log.txt 2>&1; \"$PY\" -c 'import pandas, numpy' 2>/dev/null || \"$PY\" -m pip install -r requirements.txt >> saida_llm/log.txt 2>&1; \"$PY\" scripts/rodar_llm_local.py %* >> saida_llm/log.txt 2>&1; echo \"[fim] codigo $?\" >> saida_llm/log.txt"
echo Terminado. Veja saida_llm\log.txt
endlocal
