#!/usr/bin/env bash
# Launcher for wf.py. Two jobs:
#
#   wf.sh setup [--install-python] [--force]
#       One-time bootstrap: find (or, with --install-python, install) a
#       Python 3, create a dedicated virtualenv under the plugin's persistent
#       data dir, install requirements.txt into it, and verify it. Idempotent
#       — a valid venv is reused, not rebuilt (use --force to recreate).
#
#   wf.sh pick|config|...   (anything else)
#       Run the CLI. Prefers the dedicated venv interpreter created by setup
#       (so it never depends on PATH or a broken `python3` Store shim); falls
#       back to a probed system Python if setup hasn't run yet. The CLI exit
#       code is preserved via exec (wf contract codes 0/10/11/20/30).
#
# Run from the target repo root so wf.py finds ClaudeProject.md and git.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WF="$HERE/wf.py"

# The venv lives in the plugin's persistent data dir (survives plugin
# updates); fall back to a stable home location when run outside a plugin.
DATA_ROOT="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/github-workflow}"
VENV="$DATA_ROOT/wf-venv"

# Echo the venv's python path if it exists and runs, else fail.
venv_python() {
    local p=''
    if [ -f "$VENV/bin/python" ]; then p="$VENV/bin/python"
    elif [ -f "$VENV/Scripts/python.exe" ]; then p="$VENV/Scripts/python.exe"
    else return 1; fi
    "$p" --version >/dev/null 2>&1 || return 1
    printf '%s' "$p"
}

# Detect a usable system Python 3 into the BASE_PY array (verifies --version
# actually runs, so the broken Windows `python3` Store shim is skipped).
detect_base_py() {
    if command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then BASE_PY=(python3); return 0; fi
    if command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then BASE_PY=(py -3); return 0; fi
    if command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then BASE_PY=(python); return 0; fi
    return 1
}

py_install_hint() {
    case "$(uname -s 2>/dev/null)" in
        Darwin) echo "brew install python" ;;
        MINGW*|MSYS*|CYGWIN*) echo "winget install -e --id Python.Python.3.12" ;;
        *) echo "sudo apt-get install -y python3 python3-venv   # or your distro's package manager" ;;
    esac
}

# Best-effort system install (opt-in via --install-python only — this changes
# the user's machine, so it never runs unless explicitly requested).
try_install_python() {
    case "$(uname -s 2>/dev/null)" in
        Darwin) command -v brew >/dev/null 2>&1 && brew install python ;;
        MINGW*|MSYS*|CYGWIN*) command -v winget >/dev/null 2>&1 && winget install -e --id Python.Python.3.12 ;;
        *) if command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y python3 python3-venv
           elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y python3
           elif command -v pacman >/dev/null 2>&1; then sudo pacman -S --noconfirm python; fi ;;
    esac
}

wf_setup() {
    local force=0 install=0 a
    for a in "$@"; do
        case "$a" in
            --force) force=1 ;;
            --install-python) install=1 ;;
        esac
    done

    if [ "$force" -eq 0 ] && VPY=$(venv_python); then
        echo "wf: virtualenv already set up — $("$VPY" --version 2>&1) at $VENV" >&2
        exit 0
    fi

    if ! detect_base_py; then
        if [ "$install" -eq 1 ]; then
            echo "wf: no Python 3 found — attempting install (this changes your system)..." >&2
            try_install_python || true
            detect_base_py || { echo "wf: install did not produce a usable Python 3. Install manually: $(py_install_hint)" >&2; exit 20; }
        else
            echo "wf: Python 3 is required but was not found." >&2
            echo "    Install it, then re-run 'wf.sh setup':" >&2
            echo "      $(py_install_hint)" >&2
            echo "    Or re-run as 'wf.sh setup --install-python' to attempt it automatically." >&2
            exit 20
        fi
    fi

    if ! "${BASE_PY[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
        echo "wf: found $("${BASE_PY[@]}" --version 2>&1) but Python >= 3.8 is required." >&2
        exit 20
    fi

    [ "$force" -eq 1 ] && [ -d "$VENV" ] && rm -rf "$VENV"
    mkdir -p "$(dirname "$VENV")"
    echo "wf: creating virtualenv at $VENV ..." >&2
    if ! "${BASE_PY[@]}" -m venv "$VENV"; then
        echo "wf: could not create the virtualenv (on Debian/Ubuntu install python3-venv first)." >&2
        exit 20
    fi
    VPY=$(venv_python) || { echo "wf: virtualenv created but its interpreter is not usable." >&2; exit 20; }
    "$VPY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || echo "wf: warning — could not upgrade pip; continuing." >&2
    if [ -f "$HERE/requirements.txt" ]; then
        "$VPY" -m pip install --quiet -r "$HERE/requirements.txt" || { echo "wf: failed to install requirements.txt." >&2; exit 20; }
    fi
    echo "wf: setup complete — $("$VPY" --version 2>&1)" >&2
    echo "    Future 'wf.sh' calls reuse this interpreter automatically." >&2
    exit 0
}

if [ "${1:-}" = "setup" ]; then
    shift
    wf_setup "$@"
fi

# Run path: prefer the dedicated venv, else a probed system Python.
if VPY=$(venv_python); then
    exec "$VPY" "$WF" "$@"
elif detect_base_py; then
    echo "wf: no dedicated virtualenv yet — using $("${BASE_PY[@]}" --version 2>&1) on PATH. Run 'wf.sh setup' to pin one." >&2
    exec "${BASE_PY[@]}" "$WF" "$@"
else
    echo "wf: Python 3 not found; run 'wf.sh setup' (or install Python 3.x). Falling back to the inline procedure." >&2
    exit 20
fi
