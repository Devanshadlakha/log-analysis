# Runs log-collectors from its venv.
# REQUIRED — without this, no new logs flow into Elasticsearch.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\log-collectors"

if (-not (Test-Path "venv\Scripts\python.exe")) {
    throw "log-collectors venv missing. Run: python -m venv venv ; venv\Scripts\pip install -r requirements.txt"
}

Write-Host "log-collectors starting (7 collectors)" -ForegroundColor Green
& ".\venv\Scripts\python.exe" "main.py"
