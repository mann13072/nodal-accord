# One-time setup on Windows (PowerShell). Run from the nodal-accord folder:  .\scripts\bootstrap.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]"
npm install
Write-Host "Done. Start everything with:  npm run dev   (API :8000, worker, web :5173)"
