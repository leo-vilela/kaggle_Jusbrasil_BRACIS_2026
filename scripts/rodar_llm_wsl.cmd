@echo off
rem Medição do árbitro LLM na GPU, pelo WSL2, em um clique (duplo clique neste arquivo ou `scripts\rodar_llm_wsl.cmd`).
rem Usa a distro e o venv abaixo (edite se os seus forem outros); grava tudo em saida_llm\ (log.txt, ambiente.json,
rem modelo.json, comparacao\comparacao_arbitro.json, dev_arbitro\, submission_llm.csv, cache_llm.jsonl).
rem Argumentos extras vão para scripts/rodar_llm_local.py (ex.: --completo, --modelo /opt/bracis/models/x, --so dev).
rem A pasta de saída do log segue a variável SAIDA (padrão saida_llm) — os wrappers (rodar_llm_q35_wsl.cmd) a definem
rem junto com o --saida correspondente.
setlocal
if not defined DISTRO set "DISTRO=debian-distro"
if not defined PYWSL set "PYWSL=/opt/bracis/venv/bin/python"
if not defined SAIDA set "SAIDA=saida_llm"
cd /d "%~dp0.."
if not exist "%SAIDA%" mkdir "%SAIDA%"
echo [%date% %time%] iniciando no WSL (%DISTRO%) em %CD% > "%SAIDA%\log.txt"
wsl.exe --distribution %DISTRO% --exec bash -lc "cd \"$(wslpath -u '%CD%')\" && PY=%PYWSL%; [ -x \"$PY\" ] || PY=python3; echo \"python: $PY\" >> %SAIDA%/log.txt; \"$PY\" -c 'import torch, transformers, huggingface_hub' 2>>%SAIDA%/log.txt || \"$PY\" -m pip install -r requirements-llm.txt >> %SAIDA%/log.txt 2>&1; \"$PY\" -c 'import pandas, numpy' 2>/dev/null || \"$PY\" -m pip install -r requirements.txt >> %SAIDA%/log.txt 2>&1; \"$PY\" scripts/rodar_llm_local.py %* >> %SAIDA%/log.txt 2>&1; echo \"[fim] codigo $?\" >> %SAIDA%/log.txt"
echo Terminado. Veja %SAIDA%\log.txt
endlocal
