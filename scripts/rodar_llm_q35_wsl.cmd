@echo off
rem Medição do árbitro com o Qwen3.5-9B em NF4 (experimento da ADR 0003 §Medição 3), em um clique.
rem Mesmos prompts, mesmo validador, mesmos conjuntos da medição 2 (Qwen2.5-7B-Instruct bf16); a saída vai
rem para saida_llm_q35\ para comparar lado a lado com saida_llm\. Pesos: snapshot local do WSL (nada é baixado);
rem --id/--revisao põem o nome canônico e o commit dos pesos na chave do cache (reprodução sem a pasta).
rem Argumentos extras vão para scripts/rodar_llm_local.py (ex.: --so dev, --completo).
setlocal
set "SAIDA=saida_llm_q35"
set "MODELO=/opt/bracis/models/qwen35_9b"
set "MODELO_ID=Qwen/Qwen3.5-9B"
set "MODELO_REV=c202236235762e1c871ad0ccb60c8ee5ba337b9a"
call "%~dp0rodar_llm_wsl.cmd" --modelo %MODELO% --id %MODELO_ID% --revisao %MODELO_REV% --quatro-bits --saida %SAIDA% %*
endlocal
