$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Split-Path $PSScriptRoot -Parent) ".playwright-browsers"
Set-Location (Split-Path $PSScriptRoot -Parent)
Write-Host "Taller (fichas + chat) en http://127.0.0.1:8010"
.\.venv\Scripts\python.exe -m uvicorn taller.main:app --host 127.0.0.1 --port 8010
