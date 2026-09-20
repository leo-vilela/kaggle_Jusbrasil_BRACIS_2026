<#
.SYNOPSIS
  Limita a potência da GPU (RTX 5090) para 450 W durante os experimentos com o árbitro LLM.

.DESCRIPTION
  Roda `nvidia-smi -pl <watts>` como Administrador no WINDOWS. Dentro do WSL2 isso
  NÃO funciona: o driver NVIDIA que controla a placa é o do Windows; o nvidia-smi
  do WSL é um cliente somente-leitura para clocks/potência ("Insufficient
  Permissions" ou "not supported" mesmo com sudo). Por isso o script é PowerShell.

  Por que limitar: a 5090 tem TDP de 575 W; o envelope do desafio é uma GPU de
  24 GB (L4 = 72 W, A10 = 150 W, 4090 = 450 W). Limitar potência aproxima o
  comportamento térmico/tempo de resposta do ambiente da organização e evita
  quedas da fonte no WSL2. O limite NÃO afeta a VRAM: o teto de 24 GB é imposto
  em software (torch.cuda.set_per_process_memory_fraction no backend transformers,
  gpu_memory_utilization no vLLM).

  O ajuste é volátil: volta ao padrão ao reiniciar o Windows (ou com -Restaurar).

.PARAMETER Watts
  Limite de potência em watts (padrão 450). A 5090 aceita ≈ 400–600 W; abaixo do mínimo
  o driver recusa e mostra a faixa permitida.

.PARAMETER Restaurar
  Restaura o limite padrão da placa.

.EXAMPLE
  # PowerShell como Administrador (botão direito > "Executar como administrador")
  Set-ExecutionPolicy -Scope Process Bypass
  .\scripts\limitar_gpu.ps1              # 450 W
  .\scripts\limitar_gpu.ps1 -Watts 400
  .\scripts\limitar_gpu.ps1 -Restaurar
#>
[CmdletBinding()]
param(
    [int]$Watts = 450,
    [switch]$Restaurar
)

$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Execute este script num PowerShell aberto como Administrador (nvidia-smi -pl exige privilégio)."
    exit 1
}

$nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $nvsmi) {
    $candidato = "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    if (Test-Path $candidato) { $nvsmi = $candidato } else { Write-Error "nvidia-smi não encontrado no PATH."; exit 1 }
} else { $nvsmi = $nvsmi.Source }

Write-Host "GPU e limites atuais:"
& $nvsmi --query-gpu=name,power.limit,power.default_limit,power.min_limit,power.max_limit,memory.total --format=csv

if ($Restaurar) {
    $padrao = (& $nvsmi --query-gpu=power.default_limit --format=csv,noheader,nounits).Trim()
    Write-Host "Restaurando o limite padrão ($padrao W)..."
    & $nvsmi -pl $padrao
} else {
    Write-Host "Aplicando limite de $Watts W..."
    & $nvsmi -pl $Watts
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "nvidia-smi devolveu código $LASTEXITCODE. Verifique a faixa permitida (power.min_limit/max_limit) acima."
    exit $LASTEXITCODE
}

Write-Host "Limite aplicado. Conferindo:"
& $nvsmi --query-gpu=power.limit --format=csv
Write-Host "Lembrete: o limite volta ao padrão ao reiniciar o Windows. No WSL2, use apenas 'nvidia-smi' para monitorar."
