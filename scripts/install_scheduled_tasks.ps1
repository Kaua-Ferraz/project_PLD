param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $PSScriptRoot "run_prospective_collection.ps1"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$TaskNames = @(
    "PLD - Coleta prospectiva - 1145",
    "PLD - Coleta prospectiva - 2030"
)
$Slots = @("11:45", "20:30")

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Ambiente virtual não encontrado em: $Python"
}

$TimeZone = Get-TimeZone
if ($TimeZone.Id -ne "E. South America Standard Time") {
    throw "Fuso atual '$($TimeZone.Id)' não corresponde a America/Sao_Paulo. Corrija o fuso antes de instalar."
}

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

for ($Index = 0; $Index -lt $Slots.Count; $Index++) {
    $Slot = $Slots[$Index]
    $TaskName = $TaskNames[$Index]
    $Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`" -Slot `"$Slot`""
    $Action = New-ScheduledTaskAction `
        -Execute $PowerShell `
        -Argument $Arguments `
        -WorkingDirectory $ProjectRoot
    $Trigger = New-ScheduledTaskTrigger -Daily -At $Slot

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description "Coleta auditável CCEE/ONS do projeto PLD ($Slot, America/Sao_Paulo)." `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Force | Out-Null
}

& $Python -m pld_forecast.automation configure `
    --project-root $ProjectRoot `
    --slots $Slots
if ($LASTEXITCODE -ne 0) {
    throw "As tarefas foram criadas, mas não foi possível registrar a configuração de auditoria."
}

Write-Host "Tarefas instaladas e ativadas para o usuário $CurrentUser no fuso $($TimeZone.DisplayName):"
Write-Warning "As tarefas usam LogonType Interactive: mantenha uma sessão desse usuário iniciada."
Get-ScheduledTask -TaskName $TaskNames |
    Select-Object TaskName, State,
        @{Name="Execute"; Expression={$_.Actions.Execute}},
        @{Name="Arguments"; Expression={$_.Actions.Arguments}}
