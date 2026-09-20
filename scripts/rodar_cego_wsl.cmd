@echo off
rem Conjunto cego em um clique (README §5): nucleo e nucleo + arbitro (Qwen3.5-9B NF4, snapshot local do WSL),
rem dois CSVs prontos para o Kaggle: submission_cego_nucleo.csv e submission_cego_llm.csv (+ zips dos JSONs),
rem saidas em saida_cego\ e saida_cego_llm\ (cache_llm.jsonl exportado = reproducao sem GPU); log em saida_cego\log.txt.
rem Antes: coloque os .txt do cego em dados\cego\txt e o sample_submission.csv do cego em dados\cego\.
rem Argumentos extras vao para scripts/rodar_cego.py (ex.: --sem-arbitro, --entrada /outra/pasta).
setlocal
if not defined DISTRO set "DISTRO=debian-distro"
if not defined PYWSL set "PYWSL=/opt/bracis/venv/bin/python"
set "MODELO=/opt/bracis/models/qwen35_9b"
cd /d "%~dp0.."
if not exist saida_cego mkdir saida_cego
echo [%date% %time%] iniciando no WSL (%DISTRO%) em %CD% > saida_cego\log.txt
wsl.exe --distribution %DISTRO% --exec bash -lc "cd \"$(wslpath -u '%CD%')\" && PY=%PYWSL%; [ -x \"$PY\" ] || PY=python3; echo \"python: $PY\" >> saida_cego/log.txt; \"$PY\" -c 'import pandas, numpy' 2>/dev/null || \"$PY\" -m pip install -r requirements.txt >> saida_cego/log.txt 2>&1; \"$PY\" scripts/rodar_cego.py --modelo %MODELO% %* >> saida_cego/log.txt 2>&1; echo \"[fim] codigo $?\" >> saida_cego/log.txt"
echo Terminado. Veja saida_cego\log.txt e os CSVs submission_cego_nucleo.csv / submission_cego_llm.csv
endlocal
