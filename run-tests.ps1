#!/usr/bin/env pwsh
# Run the offline test suite (decision logic + wf.py I/O shell) on Windows.
# Discovery picks up every tests/test_*.py module, so new test files run
# automatically without editing this script.
# Tries the Windows Python Launcher (py), then python3, then python.
# Prints which interpreter it found; exits 1 with an install hint if none found.
$ErrorActionPreference = 'Stop'

Set-Location (git rev-parse --show-toplevel)

$discover = @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py')

if (Get-Command py -ErrorAction SilentlyContinue) {
    $ver = (py -3 --version 2>&1)
    Write-Host "==> Using $ver (Windows Python Launcher)"
    py -3 @discover
    exit $LASTEXITCODE
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $ver = (python3 --version 2>&1)
    Write-Host "==> Using $ver"
    python3 @discover
    exit $LASTEXITCODE
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $ver = (python --version 2>&1)
    Write-Host "==> Using $ver"
    python @discover
    exit $LASTEXITCODE
} else {
    Write-Error @"
Python not found. Install Python 3.x and re-run.
    winget install Python.Python.3.12
Or download from https://python.org.
"@
    exit 1
}
