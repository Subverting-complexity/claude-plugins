#!/usr/bin/env pwsh
# Run the offline test suite (decision logic + wf.py I/O shell) on Windows.
# Discovery picks up every tests/test_*.py module, so new test files run
# automatically without editing this script.
# Resolves a Python 3 via synergy/scripts/find-python.ps1: tries the Windows Python
# Launcher (py), then python3, then python.
# Prints which interpreter it found; exits 1 with an install hint if none found.
$ErrorActionPreference = 'Stop'

Set-Location (git rev-parse --show-toplevel)

$discover = @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py')

. (Join-Path $PSScriptRoot 'synergy/scripts/find-python.ps1')
$found = Find-Python
if ($found) {
    Write-Host "==> Using $($found.Label)"
    $runArgs = @($found.Args) + $discover
    & $found.Command @runArgs
    exit $LASTEXITCODE
} else {
    Write-Error @"
Python not found. Install Python 3.x and re-run.
    winget install Python.Python.3.12
Or download from https://python.org.
"@
    exit 1
}
