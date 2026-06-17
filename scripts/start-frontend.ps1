# Runs the Vite dev server.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\frontend"

if (-not (Test-Path node_modules)) {
    Write-Host "Installing frontend dependencies (one-time)..." -ForegroundColor Cyan
    npm install
}

Write-Host "Frontend starting on http://localhost:5173" -ForegroundColor Green
npm run dev
