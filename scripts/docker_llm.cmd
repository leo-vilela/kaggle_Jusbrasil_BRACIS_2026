@echo off
rem Prova da imagem de submissao com o arbitro (Dockerfile.llm), em um clique, pelo WSL (Docker Desktop com a
rem integracao WSL ativada para a distro). Constroi caca-alucinacao:llm e roda o dev DENTRO do container nos modos:
rem   A. nucleo sem LLM (CPU)            - sempre
rem   B. nucleo + LLM so do cache (CPU)  - sempre   (reproduz a submissao sem GPU)
rem   C. nucleo + LLM na GPU             - so com o argumento `gpu` (carrega o Qwen3.5-9B em NF4 de /opt/bracis/models)
rem Cada CSV e comparado com saida_llm_q35\submission_llm.csv. Log em saida_docker\log.txt. Detalhes: scripts/docker_llm.sh.
rem   docker_llm.cmd        -> build + A + B
rem   docker_llm.cmd gpu    -> build + A + B + C
setlocal
if not defined DISTRO set "DISTRO=debian-distro"
if not defined PYWSL set "PYWSL=/opt/bracis/venv/bin/python"
cd /d "%~dp0.."
if not exist saida_docker mkdir saida_docker
echo [%date% %time%] iniciando no WSL (%DISTRO%) em %CD% > saida_docker\log.txt
wsl.exe --distribution %DISTRO% --exec bash -lc "cd \"$(wslpath -u '%CD%')\" && PY=%PYWSL%; [ -x \"$PY\" ] || PY=python3; PY=\"$PY\" bash scripts/docker_llm.sh %* >> saida_docker/log.txt 2>&1; echo \"[fim] codigo $?\" >> saida_docker/log.txt"
echo.
echo ---- saida_docker\log.txt ----
type saida_docker\log.txt
echo.
echo Terminado. Se apareceu "docker nao encontrado": instale o Docker Desktop (backend WSL2) e, em Settings ^> Resources ^>
echo WSL integration, ative a distro %DISTRO%; depois clique de novo. Com o argumento gpu roda tambem o modelo na GPU.
pause
endlocal
