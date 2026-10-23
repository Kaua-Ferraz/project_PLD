param(
    [ValidateSet("11:45", "20:30", "manual")]
    [string]$Slot = "manual",
    [int]$MaxAttempts = 2,
    [int]$RetryDelaySeconds = 300
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python do ambiente virtual não encontrado em: $Python"
}

Set-Location -LiteralPath $ProjectRoot
$env:PYTHONUTF8 = "1"

& $Python -m pld_forecast.automation run `
    --project-root $ProjectRoot `
    --slot $Slot `
    --max-attempts $MaxAttempts `
    --retry-delay-seconds $RetryDelaySeconds

exit $LASTEXITCODE
