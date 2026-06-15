#!/usr/bin/env pwsh
# Thin launcher for wf.py on Windows — same interpreter detection order as
# run-tests.ps1 (Windows Python Launcher first), then runs the CLI and
# preserves its exit code. See wf.sh for the bash equivalent the skill calls.
#
# Usage (from the target repo root):
#   pwsh "$env:CLAUDE_PLUGIN_ROOT/scripts/wf.ps1" pick -checkout
#   pwsh "$env:CLAUDE_PLUGIN_ROOT/scripts/wf.ps1" config
$ErrorActionPreference = 'Stop'

$wf = Join-Path $PSScriptRoot 'wf.py'

if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 $wf @args
    exit $LASTEXITCODE
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    python3 $wf @args
    exit $LASTEXITCODE
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python $wf @args
    exit $LASTEXITCODE
} else {
    Write-Error 'wf: Python 3 not found (install Python 3.x); fall back to the inline procedure.'
    exit 20
}
