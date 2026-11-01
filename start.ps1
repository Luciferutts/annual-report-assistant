$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "scripts\run.ps1") @args
exit $LASTEXITCODE
