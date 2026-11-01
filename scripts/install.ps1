#Requires -Version 5.1
<#
Prepare this checkout on Windows. This script installs the local application;
it does not download a different OpenHarness release or install remote scripts.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ReportProjectDir = Split-Path -Parent $PSScriptRoot
$ReportEnvironmentDir = Join-Path $ReportProjectDir ".venv"
$ReportPython = Join-Path $ReportEnvironmentDir "Scripts\python.exe"
$ReportPreviousUvEnvironment = $env:UV_PROJECT_ENVIRONMENT
Push-Location -LiteralPath $ReportProjectDir

try {
    if (-not (Test-Path -LiteralPath (Join-Path $ReportProjectDir "pyproject.toml"))) {
        throw "Run this installer from the complete annual-report-assistant checkout."
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $env:UV_PROJECT_ENVIRONMENT = $ReportEnvironmentDir
        & uv sync --locked --extra reports | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed. Review the output above and retry."
        }
    }
    else {
        if (-not (Test-Path -LiteralPath $ReportPython)) {
            $ReportBasePython = $null
            $ReportBasePrefix = @()
            foreach ($ReportCandidate in @("py", "python", "python3")) {
                $ReportCommand = Get-Command $ReportCandidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                if (-not $ReportCommand) { continue }
                $ReportPrefix = @()
                if ($ReportCandidate -eq "py") { $ReportPrefix = @("-3") }
                try {
                    & $ReportCommand.Source @ReportPrefix -c "import sys; raise SystemExit(sys.version_info < (3, 10))" *> $null
                    if ($LASTEXITCODE -eq 0) {
                        $ReportBasePython = $ReportCommand.Source
                        $ReportBasePrefix = @($ReportPrefix)
                        break
                    }
                }
                catch {
                    continue
                }
            }
            if (-not $ReportBasePython) {
                throw "Install Python 3.10 or newer (3.12 recommended), or install uv, then rerun this script."
            }
            & $ReportBasePython @ReportBasePrefix -m venv .venv | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "Could not create the project virtual environment." }
        }

        & $ReportPython -c "import sys; raise SystemExit(sys.version_info < (3, 10))" | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "The existing .venv requires Python 3.10 or newer." }
        & $ReportPython -m pip install -e ".[reports]" | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Local project installation failed. Review the output above." }
    }

    if (-not (Test-Path -LiteralPath $ReportPython)) {
        throw "No Windows Python executable was created in this project's .venv."
    }
    & $ReportPython -c "import openharness.annual_reports.server" | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "The annual report application dependencies are incomplete." }

    $ReportLaunchers = @(
        @{ File = "openh.exe"; Guidance = "Launch (PowerShell):     openh" },
        @{ File = "openharness.exe"; Guidance = "Launch (PowerShell):     openharness" },
        @{ File = "oh.exe"; Guidance = "Launch (PowerShell):     oh.exe" }
    )
    $ReportSelectedLauncher = $null
    foreach ($ReportLauncher in $ReportLaunchers) {
        $ReportLauncherPath = Join-Path $ReportEnvironmentDir ("Scripts\" + $ReportLauncher.File)
        if (Test-Path -LiteralPath $ReportLauncherPath) {
            & $ReportLauncherPath --help | Out-Host
            if ($LASTEXITCODE -eq 0) {
                $ReportSelectedLauncher = $ReportLauncher
                break
            }
        }
    }
    if (-not $ReportSelectedLauncher) {
        throw "The local OpenHarness command aliases could not be verified. Reinstall this checkout."
    }

    Write-Host ""
    Write-Host "Annual report assistant is ready. From the project folder, run:"
    Write-Host '  .\start.ps1'
    Write-Host ""
    Write-Host "Optional general OpenHarness terminal: activate .venv first:"
    Write-Host '  .\.venv\Scripts\Activate.ps1'
    Write-Host $ReportSelectedLauncher.Guidance
    Write-Host "The general terminal also needs: cd frontend/terminal; npm ci"
    Write-Host "No model key is needed for local annual report extraction and comparison."
}
finally {
    $env:UV_PROJECT_ENVIRONMENT = $ReportPreviousUvEnvironment
    Pop-Location
}
