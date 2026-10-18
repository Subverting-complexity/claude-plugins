#!/usr/bin/env pwsh
# Windows launcher for wf.py — PowerShell mirror of wf.sh. See that file for
# the full contract. Two jobs:
#
#   wf.ps1 setup [-InstallPython] [-Force]
#       Bootstrap a dedicated virtualenv (under the plugin's persistent data
#       dir) and install requirements into it. Idempotent; reused on later runs.
#
#   wf.ps1 pick|config|...
#       Run the CLI on the dedicated venv, building it first if a usable
#       system Python exists, else on that system Python. Exit code is preserved.
#
# The venv, its cache (`wf-python-ps1`), the build lock and pip all live in
# wf_launch.py, shared with wf.sh. This file keeps only what cannot run in
# Python: where the data dir is, trusting a cached venv interpreter without
# launching anything, and finding (or installing) a base Python 3.
$ErrorActionPreference = 'Stop'

$wf = Join-Path $PSScriptRoot 'wf.py'
$launch = Join-Path $PSScriptRoot 'wf_launch.py'
. (Join-Path $PSScriptRoot 'find-python.ps1')

# Before 14.0.0 the plugin was `github-workflow`: reuse a venv set up under
# that name rather than silently building a second one.
$newData = Join-Path $HOME '.claude/synergy'
$oldData = Join-Path $HOME '.claude/github-workflow'
$dataRoot = if ($env:CLAUDE_PLUGIN_DATA) { $env:CLAUDE_PLUGIN_DATA }
            elseif ((-not (Test-Path $newData)) -and (Test-Path $oldData)) { $oldData }
            else { $newData }
# Two lines, written by wf_launch.py: `venv` or `base`, then a path.
$pyCache = Join-Path $dataRoot 'wf-python-ps1'
$launchArgs = @($launch, '--launcher', 'wf.ps1', '--data-root', $dataRoot)

# Write-Error stops the script under 'Stop' before the exit code is set, and
# callers read exit 20 as "fall back to the inline procedure".
function Stop-Wf([string] $Message, [int] $Code = 20) {
    [Console]::Error.WriteLine($Message)
    exit $Code
}

function Remove-PythonCache {
    Remove-Item -LiteralPath $pyCache -Force -ErrorAction SilentlyContinue
}

if ($args.Count -ge 1 -and $args[0] -eq 'setup') {
    $rest = @($args | Select-Object -Skip 1)
    # wf_launch.py clears the cache too; this covers a setup that ends here.
    Remove-PythonCache
    $base = Find-Python
    $force = $rest -contains '-Force' -or $rest -contains '--force'
    if (-not $base -and -not $force) {
        # No base Python, but a ready venv is still a finished setup. Only its
        # own interpreter can say so, and it is never asked to rebuild itself.
        foreach ($vpy in @((Join-Path $dataRoot 'wf-venv/Scripts/python.exe'), (Join-Path $dataRoot 'wf-venv/bin/python'))) {
            if (Test-Path -LiteralPath $vpy -PathType Leaf) {
                try {
                    & $vpy @launchArgs setup --ready-only
                    if ($LASTEXITCODE -eq 0) { exit 0 }
                } catch { }
                break
            }
        }
    }
    if (-not $base) {
        $install = $rest -contains '-InstallPython' -or $rest -contains '--install-python'
        if ($install -and (Get-Command winget -ErrorAction SilentlyContinue)) {
            Write-Host 'wf: no Python 3 found — attempting install (this changes your system)...'
            winget install -e --id Python.Python.3.12
            $base = Find-Python
        }
        if (-not $base) {
            Stop-Wf "wf: Python 3.8 or later is required but was not found. Install it (winget install -e --id Python.Python.3.12), then re-run 'wf.ps1 setup'. Or re-run with -InstallPython."
        }
    }
    $setupArgs = @($base.Args) + $launchArgs + @('setup') + $rest
    & $base.Command @setupArgs
    exit $LASTEXITCODE
}

# Launching Python only to find it is slow on Windows, so a cached venv
# interpreter is trusted while its path exists. A cached system Python still
# goes through wf_launch.py, which builds the venv if it can.
$cached = $null
if (Test-Path -LiteralPath $pyCache) {
    try { $lines = @(Get-Content -LiteralPath $pyCache -ErrorAction Stop) } catch { $lines = @() }
    if ($lines.Count -ge 2) {
        $kind = "$($lines[0])".Trim()
        $path = "$($lines[1])".Trim()
        if ($path -and ($kind -eq 'venv' -or $kind -eq 'base') -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            $cached = @{ Kind = $kind; Path = $path }
        }
    }
}
if ($cached) {
    try {
        if ($cached.Kind -eq 'venv') { & $cached.Path $wf @args }
        else { & $cached.Path @launchArgs run @args }
        exit $LASTEXITCODE
    } catch [System.Management.Automation.CommandNotFoundException], [System.Management.Automation.ApplicationFailedException] {
        # The interpreter would not start, which is not an answer from wf.py.
        Remove-PythonCache
        [Console]::Error.WriteLine("wf: the cached interpreter $($cached.Path) would not start; looking for Python again.")
    }
}

$base = Find-Python
if ($base) {
    $runArgs = @($base.Args) + $launchArgs + @('run') + $args
    & $base.Command @runArgs
    exit $LASTEXITCODE
}
Stop-Wf "wf: Python 3 not found; run 'wf.ps1 setup' (or install Python 3.8 or later). Falling back to the inline procedure."
