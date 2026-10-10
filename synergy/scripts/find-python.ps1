# Shared "find a usable Python 3" cascade for PowerShell: wf.ps1 here, and bootstrap.ps1 and run-tests.ps1 at the repository root. Dot-source this file, then call Find-Python. It is not meant to be run directly. It lives inside the plugin because wf.ps1 ships with the plugin and the repository root does not.
#
# Candidate order: the Windows Python Launcher (`py -3`), then `python3`, then `python`. Each candidate must actually run and be Python 3.8 or later, not just be on PATH, so a broken shim (the Microsoft Store python3 stub) or an old Python is skipped in favour of the next candidate.
#
# Returns a PSCustomObject with:
#   Command  - the executable to invoke (e.g. 'py', 'python3', 'python')
#   Args     - extra arguments to pass first (e.g. @('-3') for the launcher)
#   Version  - the raw `--version` output, for display
#   Label    - Version, annotated with "(Windows Python Launcher)" for py
# or $null when nothing was found.
function Find-Python {
    foreach ($candidate in @(
            @{ Command = 'py'; Args = @('-3'); Suffix = ' (Windows Python Launcher)' },
            @{ Command = 'python3'; Args = @(); Suffix = '' },
            @{ Command = 'python'; Args = @(); Suffix = '' })) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) { continue }
        $checkArgs = @($candidate.Args) + @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)')
        try { & $candidate.Command @checkArgs 2>&1 | Out-Null } catch { continue }
        if ($LASTEXITCODE -ne 0) { continue }
        $versionArgs = @($candidate.Args) + @('--version')
        $ver = "$(& $candidate.Command @versionArgs 2>&1)".Trim()
        return [PSCustomObject]@{ Command = $candidate.Command; Args = $candidate.Args; Version = $ver; Label = "$ver$($candidate.Suffix)" }
    }
    return $null
}
