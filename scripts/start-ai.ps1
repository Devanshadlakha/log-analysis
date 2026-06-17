# Runs the Python AI service from its venv.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\ai-service"

if (-not (Test-Path "venv\Scripts\python.exe")) {
    throw "ai-service venv missing. Run: python -m venv venv ; venv\Scripts\pip install -r requirements.txt"
}

Write-Host "AI service starting on http://localhost:5000" -ForegroundColor Green
& ".\venv\Scripts\python.exe" "app.py"
