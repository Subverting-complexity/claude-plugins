# Shared "find a usable Python 3" cascade for this repo's PowerShell
# scripts. Dot-source this file, then call Find-Python — it is not meant
# to be run directly.
#
# Candidate order: the Windows Python Launcher (`py -3`), then `python3`,
# then `python` — the order bootstrap.ps1 and run-tests.ps1 already agreed
# on before they shared this cascade. A candidate counts as found once
# `Get-Command` resolves it; the caller runs it and handles a broken
# interpreter itself, exactly as bootstrap.ps1 and run-tests.ps1 already
# did. wf.ps1's own `Get-BasePython` goes further (it runs each candidate
# to verify it and to resolve an absolute path) — this helper stays at the
# level bootstrap.ps1/run-tests.ps1 need, shaped so a later story can still
# point wf.ps1 at it without redesigning the interface.
#
# Returns a PSCustomObject with:
#   Command  - the executable to invoke (e.g. 'py', 'python3', 'python')
#   Args     - extra arguments to pass first (e.g. @('-3') for the launcher)
#   Version  - the raw `--version` output, for display
#   Label    - Version, annotated with "(Windows Python Launcher)" for py
# or $null when nothing was found.
function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $ver = (py -3 --version 2>&1)
        return [PSCustomObject]@{ Command = 'py'; Args = @('-3'); Version = $ver; Label = "$ver (Windows Python Launcher)" }
    }
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        $ver = (python3 --version 2>&1)
        return [PSCustomObject]@{ Command = 'python3'; Args = @(); Version = $ver; Label = "$ver" }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $ver = (python --version 2>&1)
        return [PSCustomObject]@{ Command = 'python'; Args = @(); Version = $ver; Label = "$ver" }
    }
    return $null
}
