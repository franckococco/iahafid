# IAHAF: bot local + túnel que se reconecta y se mantiene vivo.
# Doble clic o:  powershell -ExecutionPolicy Bypass -File .\arrancar.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root ".playwright-browsers"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "Falta .venv. En esta carpeta: python -m venv .venv ; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

$up = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $up = $true }
} catch { $up = $false }

if (-not $up) {
    Write-Host "Levanto el bot en http://127.0.0.1:8000"
    Start-Process -FilePath $Python -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory $Root -WindowStyle Minimized
    Start-Sleep -Seconds 3
}

Write-Host "Abro el túnel (se reconecta solo; cada 90s pinea para que no expire)."
Write-Host "Cuando aparezca la URL, pegala en Meta y Verify and save."
& $Python (Join-Path $Root "scripts\keep_tunnel.py")
