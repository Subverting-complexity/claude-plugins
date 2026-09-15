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
# Before 14.0.0 the plugin was `github-workflow`: reuse a venv set up under
# that name rather than silently building a second one.
$newData = Join-Path $HOME '.claude/synergy'
$oldData = Join-Path $HOME '.claude/github-workflow'
$dataRoot = if ($env:CLAUDE_PLUGIN_DATA) { $env:CLAUDE_PLUGIN_DATA }
            elseif ((-not (Test-Path $newData)) -and (Test-Path $oldData)) { $oldData }
            else { $newData }
$venv = Join-Path $dataRoot 'wf-venv'
$venvPy = Join-Path $venv 'Scripts/python.exe'

# Write-Error stops the script under 'Stop' before the exit code is set, and
# callers read exit 20 as "fall back to the inline procedure".
function Stop-Wf([string] $Message, [int] $Code = 20) {
    [Console]::Error.WriteLine($Message)
    exit $Code
}

function Get-VenvPython {
    if ((Test-Path $venvPy) -and (& $venvPy --version 2>$null)) { return $venvPy }
    return $null
}

# Each candidate is run, not just found: the Microsoft Store `python3` stub is
# on PATH but runs nothing, and wf.py needs Python 3.8 or later.
function Get-BasePython {
    foreach ($candidate in @(, @('py', '-3')) + @(, @('python3')) + @(, @('python'))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = @($candidate | Select-Object -Skip 1)
        try {
            $ok = & $candidate[0] @rest -c 'import sys; print(sys.version_info >= (3, 8))' 2>$null
        } catch { continue }
        if ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq 'True') { return , $candidate }
    }
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
            Stop-Wf "wf: Python 3.8 or later is required but was not found. Install it (winget install -e --id Python.Python.3.12), then re-run 'wf.ps1 setup'. Or re-run with -InstallPython."
        }
    }
    $baseArgs = @($base | Select-Object -Skip 1)

    if ($force -and (Test-Path $venv)) { Remove-Item -Recurse -Force $venv }
    New-Item -ItemType Directory -Force (Split-Path $venv) | Out-Null
    Write-Host "wf: creating virtualenv at $venv ..."
    & $base[0] @baseArgs -m venv $venv
    $vpy = Get-VenvPython
    if ($LASTEXITCODE -ne 0 -or -not $vpy) { Stop-Wf 'wf: the virtualenv could not be created, or its interpreter is not usable.' }
    & $vpy -m pip install --quiet --upgrade pip 2>$null
    $req = Join-Path $PSScriptRoot 'requirements.txt'
    if (Test-Path $req) {
        & $vpy -m pip install --quiet -r $req
        if ($LASTEXITCODE -ne 0) { Stop-Wf "wf: installing $req failed; re-run 'wf.ps1 setup -Force' once the error above is fixed." 1 }
    }
    Write-Host "wf: setup complete — $(& $vpy --version). Future calls reuse it automatically."
    exit 0
}

if ($args.Count -ge 1 -and $args[0] -eq 'setup') {
    Invoke-WfSetup -Rest @($args | Select-Object -Skip 1)
}

$vpy = Get-VenvPython
if ($vpy) {
    & $vpy $wf @args
    exit $LASTEXITCODE
}
$base = Get-BasePython
if ($base) {
    Write-Warning "wf: no dedicated virtualenv yet — using system Python. Run 'wf.ps1 setup' to pin one."
    $baseArgs = @($base | Select-Object -Skip 1)
    & $base[0] @baseArgs $wf @args
    exit $LASTEXITCODE
}
Stop-Wf "wf: Python 3 not found; run 'wf.ps1 setup' (or install Python 3.8 or later). Falling back to the inline procedure."
