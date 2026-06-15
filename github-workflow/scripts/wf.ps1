#!/usr/bin/env pwsh
# Windows launcher for wf.py — PowerShell mirror of wf.sh. See that file for
# the full contract. Two jobs:
#
#   wf.ps1 setup [-InstallPython] [-Force]
#       Bootstrap a dedicated virtualenv (under the plugin's persistent data
#       dir) and install requirements into it. Idempotent; reused on later runs.
#
#   wf.ps1 pick|config|...
#       Run the CLI, preferring the venv interpreter created by setup and
#       falling back to a probed system Python. Exit code is preserved.
$ErrorActionPreference = 'Stop'

$wf = Join-Path $PSScriptRoot 'wf.py'
$dataRoot = if ($env:CLAUDE_PLUGIN_DATA) { $env:CLAUDE_PLUGIN_DATA } else { Join-Path $HOME '.claude/github-workflow' }
$venv = Join-Path $dataRoot 'wf-venv'
$venvPy = Join-Path $venv 'Scripts/python.exe'

function Get-VenvPython {
    if ((Test-Path $venvPy) -and (& $venvPy --version 2>$null)) { return $venvPy }
    return $null
}

function Get-BasePython {
    if (Get-Command py -ErrorAction SilentlyContinue) { return , @('py', '-3') }
    elseif (Get-Command python3 -ErrorAction SilentlyContinue) { return , @('python3') }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { return , @('python') }
    return $null
}

function Invoke-WfSetup {
    param([string[]] $Rest)
    $force = $Rest -contains '-Force' -or $Rest -contains '--force'
    $install = $Rest -contains '-InstallPython' -or $Rest -contains '--install-python'

    $vpy = Get-VenvPython
    if ((-not $force) -and $vpy) {
        Write-Host "wf: virtualenv already set up at $venv"
        exit 0
    }

    $base = Get-BasePython
    if (-not $base) {
        if ($install -and (Get-Command winget -ErrorAction SilentlyContinue)) {
            Write-Host 'wf: no Python 3 found — attempting install (this changes your system)...'
            winget install -e --id Python.Python.3.12
            $base = Get-BasePython
        }
        if (-not $base) {
            Write-Error "wf: Python 3 is required but was not found. Install it (winget install -e --id Python.Python.3.12), then re-run 'wf.ps1 setup'. Or re-run with -InstallPython."
            exit 20
        }
    }

    if ($force -and (Test-Path $venv)) { Remove-Item -Recurse -Force $venv }
    New-Item -ItemType Directory -Force (Split-Path $venv) | Out-Null
    Write-Host "wf: creating virtualenv at $venv ..."
    & $base[0] $base[1..($base.Count - 1)] -m venv $venv
    $vpy = Get-VenvPython
    if (-not $vpy) { Write-Error 'wf: virtualenv created but its interpreter is not usable.'; exit 20 }
    & $vpy -m pip install --quiet --upgrade pip 2>$null
    $req = Join-Path $PSScriptRoot 'requirements.txt'
    if (Test-Path $req) { & $vpy -m pip install --quiet -r $req }
    Write-Host "wf: setup complete — $(& $vpy --version). Future calls reuse it automatically."
    exit 0
}

if ($args.Count -ge 1 -and $args[0] -eq 'setup') {
    Invoke-WfSetup -Rest @($args[1..($args.Count - 1)])
}

$vpy = Get-VenvPython
if ($vpy) {
    & $vpy $wf @args
    exit $LASTEXITCODE
}
$base = Get-BasePython
if ($base) {
    Write-Warning "wf: no dedicated virtualenv yet — using system Python. Run 'wf.ps1 setup' to pin one."
    & $base[0] $base[1..($base.Count - 1)] $wf @args
    exit $LASTEXITCODE
}
Write-Error "wf: Python 3 not found; run 'wf.ps1 setup' (or install Python 3.x). Falling back to the inline procedure."
exit 20
