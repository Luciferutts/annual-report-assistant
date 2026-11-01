$ErrorActionPreference = "Stop"
$ReportProjectDir = Split-Path -Parent $PSScriptRoot
$ReportPreviousPythonPath = $env:PYTHONPATH
Push-Location -LiteralPath $ReportProjectDir

try {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv run --locked --extra reports annual-report-assistant --open @args
        exit $LASTEXITCODE
    }

    $ReportPython = Join-Path $ReportProjectDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $ReportPython) {
        $ReportSource = Join-Path $ReportProjectDir "src"
        $env:PYTHONPATH = if ($ReportPreviousPythonPath) { "$ReportSource;$ReportPreviousPythonPath" } else { $ReportSource }
        $ReportReady = $false
        try {
            & $ReportPython -c "import openharness.annual_reports.server" 2>$null
            $ReportReady = $LASTEXITCODE -eq 0
        }
        catch {
            $ReportReady = $false
        }
        if ($ReportReady) {
            & $ReportPython -m openharness.annual_reports --open @args
            exit $LASTEXITCODE
        }
    }

    Write-Host "当前项目尚未安装运行环境。"
    Write-Host "推荐：uv sync --locked --extra reports"
    Write-Host "或：py -3.12 -m venv .venv"
    Write-Host '.\.venv\Scripts\python.exe -m pip install -e ".[reports]"'
    Write-Host "完成后重新启动；详细步骤见 README.md。"
    exit 1
}
finally {
    $env:PYTHONPATH = $ReportPreviousPythonPath
    Pop-Location
}
