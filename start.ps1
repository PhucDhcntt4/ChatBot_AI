$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectPath
$Host.UI.RawUI.WindowTitle = "Dong Hai - FastAPI"

Write-Host "Starting Bot Conversation at http://127.0.0.1:8001" -ForegroundColor Green
python -m uvicorn app.main:app --reload --reload-include ".env" --host 127.0.0.1 --port 8001
