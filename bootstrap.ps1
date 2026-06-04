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

Write-Host "==> Done. If 'git status' now lists renormalized files, commit them once."
