#!/usr/bin/env bash
# Shared "find a usable Python 3" cascade for bash: wf.sh here, and bootstrap.sh and run-tests.sh at the repository root. Source this file, then call find_python. It is not meant to be run directly. It lives inside the plugin because wf.sh ships with the plugin and the repository root does not.
#
# Candidate order: python3, then `py -3` (the Windows Python Launcher), then python. Each candidate must actually run `--version`, not just be on PATH, so a broken shim (e.g. the Microsoft Store python3 stub) is skipped.
#
# On success, sets BASE_PY to the resolved command as an array (so `"${BASE_PY[@]}"` runs it, and `py -3` stays two words) and returns 0. On failure, returns 1 and leaves BASE_PY unset. The caller decides the install-hint message, since it differs by script.
find_python() {
    if command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
        BASE_PY=(python3); return 0
    fi
    if command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
        BASE_PY=(py -3); return 0
    fi
    if command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
        BASE_PY=(python); return 0
    fi
    return 1
}
