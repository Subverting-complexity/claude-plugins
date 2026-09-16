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
#
# The resolved interpreter is cached in `wf-python-ps1` under the data dir and
# trusted while its path exists, so a call does not launch Python once just to
# find it. `setup` rewrites the cache; an interpreter that will not start is
# forgotten and looked for again.
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
# `New-Item -ErrorAction Stop` on this path is the exclusivity check shared by
# Invoke-WfSetup and Try-AutoBootstrapVenv: it either succeeds for exactly one
# concurrent caller or throws for the rest, so only one of them ever builds
# the venv at a time.
$venvLock = Join-Path $dataRoot 'wf-venv.lock'
# Written last, only by whichever caller holds $venvLock while building, so it
# marks the venv as fully provisioned rather than merely present.
$venvReadyMarker = Join-Path $venv '.wf-ready'
# Seconds a caller waits for a concurrent build before treating the lock as
# abandoned (its owner was killed without releasing it) and reclaiming it.
$venvLockTimeoutSec = 120
# Two lines: `venv` or `base`, then the interpreter's path. Separate from
# wf.sh's `wf-python`, whose paths are written in a form PowerShell cannot run.
$pyCache = Join-Path $dataRoot 'wf-python-ps1'
$script:baseExe = ''

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

# The venv's python path, but only if the venv is not just present but fully
# provisioned. Get-VenvPython alone is true as soon as `-m venv` finishes,
# before pip install has run — it must never be used to decide that a build
# (as opposed to the bare interpreter) is complete.
function Get-VenvReady {
    if (-not (Test-Path -LiteralPath $venvReadyMarker -PathType Leaf)) { return $null }
    return Get-VenvPython
}

# Try to acquire $venvLock, waiting up to $venvLockTimeoutSec seconds. Shared
# by Invoke-WfSetup and Try-AutoBootstrapVenv so neither can build the venv
# while the other holds the lock — both write to the same $venv. Returns
# $true once this call holds the lock, $false on timeout (including a
# reclaim attempt that lost to another late arrival).
function Acquire-VenvLock {
    New-Item -ItemType Directory -Force $dataRoot -ErrorAction SilentlyContinue | Out-Null
    $waited = 0
    while ($true) {
        try {
            New-Item -ItemType Directory -Path $venvLock -ErrorAction Stop | Out-Null
            return $true
        } catch {
            if ($waited -ge $venvLockTimeoutSec) {
                Remove-Item -LiteralPath $venvLock -Recurse -Force -ErrorAction SilentlyContinue
                try {
                    New-Item -ItemType Directory -Path $venvLock -ErrorAction Stop | Out-Null
                    return $true
                } catch { return $false }
            }
            Start-Sleep -Seconds 1
            $waited++
        }
    }
}

function Release-VenvLock {
    Remove-Item -LiteralPath $venvLock -Recurse -Force -ErrorAction SilentlyContinue
}

# Each candidate is run, not just found: the Microsoft Store `python3` stub is
# on PATH but runs nothing, and wf.py needs Python 3.8 or later. The same run
# reports the interpreter's absolute path, which is what gets cached.
function Get-BasePython {
    foreach ($candidate in @(, @('py', '-3')) + @(, @('python3')) + @(, @('python'))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = @($candidate | Select-Object -Skip 1)
        try {
            $out = @(& $candidate[0] @rest -c 'import sys; print(sys.version_info >= (3, 8)); print(sys.executable)' 2>$null)
        } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $out.Count -ge 1 -and "$($out[0])".Trim() -eq 'True') {
            $script:baseExe = if ($out.Count -ge 2) { "$($out[1])".Trim() } else { '' }
            return , $candidate
        }
    }
    return $null
}

# Best-effort: a cache that cannot be written only means the next call probes.
function Save-PythonCache([string] $Kind, [string] $Path) {
    try {
        New-Item -ItemType Directory -Force $dataRoot | Out-Null
        Set-Content -LiteralPath $pyCache -Value @($Kind, $Path) -Encoding utf8 -ErrorAction Stop
    } catch { }
}

function Remove-PythonCache {
    Remove-Item -LiteralPath $pyCache -Force -ErrorAction SilentlyContinue
}

# Try to create the dedicated venv from a usable base Python, silently, on a
# run that would otherwise fall back to system Python. Mirrors Invoke-WfSetup's
# create step but never installs a system Python and never writes to the
# console: any failure here is not this call's problem to report, so it just
# returns $null and leaves the caller to warn and fall back to system Python.
#
# Unlike `setup` (a one-off command a person runs by hand), this can now run
# from any ordinary invocation, so two calls with no venv yet can start at the
# same moment — plausible here since parallel agents on one machine share
# $dataRoot. The lock (shared with Invoke-WfSetup, so an explicit setup run
# can never race this either) makes only one caller build at a time; everyone
# else waits for it rather than racing it into the same `-m venv` target,
# which could otherwise interleave two writes into one venv directory and
# leave it corrupted. Readiness is checked only after this call itself holds
# the lock, so it never mistakes a build still in progress under someone
# else's hold for a finished one.
function Try-AutoBootstrapVenv {
    param([string] $ExePath, [string[]] $BaseArgs)
    if (-not $ExePath) { return $null }
    if (-not (Acquire-VenvLock)) { return $null }
    try {
        $existing = Get-VenvReady
        if ($existing) { return $existing }
        Remove-Item -LiteralPath $venv -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force (Split-Path $venv) | Out-Null
        & $ExePath @BaseArgs -m venv $venv 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return $null }
        $vpy = Get-VenvPython
        if (-not $vpy) { return $null }
        & $vpy -m pip install --quiet --upgrade pip 2>$null | Out-Null
        $req = Join-Path $PSScriptRoot 'requirements.txt'
        if (Test-Path $req) {
            & $vpy -m pip install --quiet -r $req 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { return $null }
        }
        New-Item -ItemType File -Path $venvReadyMarker -Force | Out-Null
        Save-PythonCache 'venv' $vpy
        return $vpy
    } finally {
        Release-VenvLock
    }
}

# The cached interpreter, trusted without running it. Its path must still
# exist, and a cached system Python gives way as soon as a venv exists.
function Get-CachedPython {
    if (-not (Test-Path -LiteralPath $pyCache)) { return $null }
    try { $lines = @(Get-Content -LiteralPath $pyCache -ErrorAction Stop) } catch { return $null }
    if ($lines.Count -lt 2) { return $null }
    $kind = "$($lines[0])".Trim()
    $path = "$($lines[1])".Trim()
    if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    if ($kind -eq 'base' -and (Test-Path $venvPy)) { return $null }
    if ($kind -ne 'venv' -and $kind -ne 'base') { return $null }
    return @{ Kind = $kind; Path = $path }
}

function Invoke-WfSetup {
    param([string[]] $Rest)
    $force = $Rest -contains '-Force' -or $Rest -contains '--force'
    $install = $Rest -contains '-InstallPython' -or $Rest -contains '--install-python'

    # Whatever setup ends with is what the next call runs, so a failed setup
    # leaves no stale answer behind.
    Remove-PythonCache

    # Share the lock with Try-AutoBootstrapVenv: an explicit setup run must
    # wait for an auto-bootstrap already building $venv rather than racing
    # it, and vice versa. Stop-Wf's `exit` still runs this finally block.
    if (-not (Acquire-VenvLock)) {
        Stop-Wf "wf: timed out waiting for another wf process building the virtualenv. Try again shortly."
    }
    try {
        $vpy = Get-VenvReady
        if ((-not $force) -and $vpy) {
            Save-PythonCache 'venv' $vpy
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
        New-Item -ItemType File -Path $venvReadyMarker -Force | Out-Null
        Save-PythonCache 'venv' $vpy
        Write-Host "wf: setup complete — $(& $vpy --version). Future calls reuse it automatically."
        exit 0
    } finally {
        Release-VenvLock
    }
}

if ($args.Count -ge 1 -and $args[0] -eq 'setup') {
    Invoke-WfSetup -Rest @($args | Select-Object -Skip 1)
}

$cached = Get-CachedPython
if ($cached) {
    if ($cached.Kind -eq 'base') {
        $vpy = Try-AutoBootstrapVenv -ExePath $cached.Path -BaseArgs @()
        if ($vpy) { $cached = @{ Kind = 'venv'; Path = $vpy } }
        else { Write-Warning "wf: no dedicated virtualenv yet — using system Python. Run 'wf.ps1 setup' to pin one." }
    }
    try {
        & $cached.Path $wf @args
        exit $LASTEXITCODE
    } catch [System.Management.Automation.CommandNotFoundException], [System.Management.Automation.ApplicationFailedException] {
        # The interpreter would not start, which is not an answer from wf.py.
        Remove-PythonCache
        [Console]::Error.WriteLine("wf: the cached interpreter $($cached.Path) would not start; looking for Python again.")
    }
}

$vpy = Get-VenvPython
if ($vpy) {
    Save-PythonCache 'venv' $vpy
    & $vpy $wf @args
    exit $LASTEXITCODE
}
$base = Get-BasePython
if ($base) {
    $exePath = if ($script:baseExe -and (Test-Path -LiteralPath $script:baseExe -PathType Leaf)) { $script:baseExe } else { $null }
    $baseArgs = @($base | Select-Object -Skip 1)
    $vpy = if ($exePath) { Try-AutoBootstrapVenv -ExePath $exePath -BaseArgs @() } else { Try-AutoBootstrapVenv -ExePath $base[0] -BaseArgs $baseArgs }
    if ($vpy) {
        & $vpy $wf @args
        exit $LASTEXITCODE
    }
    Write-Warning "wf: no dedicated virtualenv yet — using system Python. Run 'wf.ps1 setup' to pin one."
    if ($exePath) {
        Save-PythonCache 'base' $exePath
        & $exePath $wf @args
    } else {
        & $base[0] @baseArgs $wf @args
    }
    exit $LASTEXITCODE
}
Stop-Wf "wf: Python 3 not found; run 'wf.ps1 setup' (or install Python 3.8 or later). Falling back to the inline procedure."
