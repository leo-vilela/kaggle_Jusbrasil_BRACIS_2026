@echo off
rem Prova da imagem de submissao com o arbitro (Dockerfile.llm), em um clique, pelo WSL (Docker Desktop com a
rem integracao WSL ativada para a distro). Constroi caca-alucinacao:llm e roda os documentos DENTRO do container:
rem   A. nucleo sem LLM (CPU)            - sempre
rem   B. nucleo + LLM so do cache (CPU)  - sempre   (reproduz a submissao com LLM sem GPU)
rem   C. nucleo + LLM na GPU             - so com o argumento `gpu` (carrega o Qwen3.5-9B em NF4 de /opt/bracis/models)
rem Sem `cego`: conjunto de desenvolvimento (dados\txt), comparando com saida_llm_q35\submission_llm.csv.
rem Com `cego`: dados\cego\txt, comparando com submission_cego_nucleo.csv (A) e submission_cego_llm.csv (B e C) —
rem   so DEPOIS de rodar_cego_wsl.cmd, que e quem gera a submissao do cego; este script apenas a reproduz no container.
rem   docker_llm.cmd            -> dev:  build + A + B          docker_llm.cmd gpu       -> dev:  build + A + B + C
rem   docker_llm.cmd cego       -> cego: build + A + B          docker_llm.cmd cego gpu  -> cego: build + A + B + C
rem Log em saida_docker\log.txt (dev) ou saida_docker_cego\log.txt (cego). Detalhes: scripts/docker_llm.sh.
setlocal
if not defined DISTRO set "DISTRO=debian-distro"
if not defined PYWSL set "PYWSL=/opt/bracis/venv/bin/python"
cd /d "%~dp0.."
set "SAIDA=saida_docker"
echo %* | findstr /i "cego" >nul && set "SAIDA=saida_docker_cego"
if not exist %SAIDA% mkdir %SAIDA%
echo [%date% %time%] iniciando no WSL (%DISTRO%) em %CD% > %SAIDA%\log.txt
wsl.exe --distribution %DISTRO% --exec bash -lc "cd \"$(wslpath -u '%CD%')\" && PY=%PYWSL%; [ -x \"$PY\" ] || PY=python3; PY=\"$PY\" bash scripts/docker_llm.sh %* >> %SAIDA%/log.txt 2>&1; echo \"[fim] codigo $?\" >> %SAIDA%/log.txt"
echo.
echo ---- %SAIDA%\log.txt ----
type %SAIDA%\log.txt
echo.
echo Terminado. Se apareceu "docker nao encontrado": instale o Docker Desktop (backend WSL2) e, em Settings ^> Resources ^>
echo WSL integration, ative a distro %DISTRO%; depois clique de novo. Com o argumento gpu roda tambem o modelo na GPU.
pause
endlocal
