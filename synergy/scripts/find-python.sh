#!/usr/bin/env bash
# Shared "find a usable Python 3" cascade for bash: wf.sh here, and bootstrap.sh and run-tests.sh at the repository root. Source this file, then call find_python. It is not meant to be run directly. It lives inside the plugin because wf.sh ships with the plugin and the repository root does not.
#
# Candidate order: python3, then `py -3` (the Windows Python Launcher), then python. Each candidate must actually run and be Python 3.8 or later, not just be on PATH, so a broken shim (e.g. the Microsoft Store python3 stub) or an old Python is skipped in favour of the next candidate.
#
# On success, sets BASE_PY to the resolved command as an array (so `"${BASE_PY[@]}"` runs it, and `py -3` stays two words) and returns 0. On failure, returns 1 and leaves BASE_PY unset. The caller decides the install-hint message, since it differs by script.
_FIND_PYTHON_CHECK='import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'

find_python() {
    if command -v python3 >/dev/null 2>&1 && python3 -c "$_FIND_PYTHON_CHECK" >/dev/null 2>&1; then
        BASE_PY=(python3); return 0
    fi
    if command -v py >/dev/null 2>&1 && py -3 -c "$_FIND_PYTHON_CHECK" >/dev/null 2>&1; then
        BASE_PY=(py -3); return 0
    fi
    if command -v python >/dev/null 2>&1 && python -c "$_FIND_PYTHON_CHECK" >/dev/null 2>&1; then
        BASE_PY=(python); return 0
    fi
    return 1
}
