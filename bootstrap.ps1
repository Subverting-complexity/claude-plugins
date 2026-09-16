#!/usr/bin/env pwsh
# Bootstrap this clone for development. Idempotent — safe to re-run.
# See bootstrap.sh for the rationale (LF line endings + pre-commit hook).
$ErrorActionPreference = 'Stop'

Set-Location (git rev-parse --show-toplevel)

Write-Host "==> Pinning line endings to LF for this clone"
git config core.autocrlf false
git config core.eol lf

Write-Host "==> Renormalizing tracked files to LF (no-op if already clean)"
git add --renormalize .

Write-Host "==> Installing pre-commit hook"
$hookDir = git rev-parse --git-path hooks
New-Item -ItemType Directory -Force -Path $hookDir | Out-Null
Copy-Item hooks/pre-commit (Join-Path $hookDir 'pre-commit') -Force

Write-Host "==> Checking Python availability"
$pyFound = $false
if (Get-Command py -ErrorAction SilentlyContinue) {
    $ver = (py -3 --version 2>&1)
    Write-Host "    Found: $ver (Windows Python Launcher)"
    $pyFound = $true
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $ver = (python3 --version 2>&1)
    Write-Host "    Found: $ver"
    $pyFound = $true
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $ver = (python --version 2>&1)
    Write-Host "    Found: $ver"
    $pyFound = $true
}
if (-not $pyFound) {
    Write-Warning "Python not found. The quality gate requires Python 3.x."
    Write-Warning "Install it with: winget install Python.Python.3.12"
    Write-Warning "Then verify by running: .\run-tests.ps1"
}

Write-Host "==> Done. If 'git status' now lists renormalized files, commit them once."
