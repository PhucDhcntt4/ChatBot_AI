$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$workerCommand = @"
Set-Location -LiteralPath '$projectPath'
`$Host.UI.RawUI.WindowTitle = 'Dong Hai - Product Sync Worker'
python -m app.workers.product_sync_worker
"@

Write-Host "Starting product sync worker..." -ForegroundColor Cyan
Start-Process powershell `
    -WorkingDirectory $projectPath `
    -ArgumentList @(
        "-NoExit", 
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $workerCommand
    )

Set-Location -LiteralPath $projectPath
$Host.UI.RawUI.WindowTitle = "Dong Hai - FastAPI"

Write-Host "Starting FastAPI at http://127.0.0.1:8000" -ForegroundColor Green
python -m uvicorn app.main:app --reload --port 8000
