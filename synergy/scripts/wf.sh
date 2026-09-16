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
#       Run the CLI on the dedicated venv, building it first if a usable
#       system Python exists, else on that system Python. The CLI exit code is
#       preserved (see the exit-code table in README.md).
#
# The venv, its cache, the build lock and pip all live in wf_launch.py, shared
# with wf.ps1. This file keeps only what cannot run in Python: where the data
# dir is, trusting a cached venv interpreter without launching anything, and
# finding (or installing) a base Python 3 to hand over to.
#
# Run from the target repo root so wf.py finds ClaudeProject.md and git.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WF="$HERE/wf.py"
LAUNCH="$HERE/wf_launch.py"
# shellcheck source=find-python.sh
source "$HERE/find-python.sh"

# The venv lives in the plugin's persistent data dir (survives plugin
# updates); fall back to a stable home location when run outside a plugin.
# Before 14.0.0 the plugin was `github-workflow`: reuse a venv set up under
# that name rather than silently building a second one.
if [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then
    DATA_ROOT="$CLAUDE_PLUGIN_DATA"
elif [ ! -d "$HOME/.claude/synergy" ] && [ -d "$HOME/.claude/github-workflow" ]; then
    DATA_ROOT="$HOME/.claude/github-workflow"
else
    DATA_ROOT="$HOME/.claude/synergy"
fi
# Two lines, written by wf_launch.py: `venv` or `base`, then a path.
PY_CACHE="$DATA_ROOT/wf-python"

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

if [ "${1:-}" = "setup" ]; then
    shift
    # wf_launch.py clears the cache too; this covers a setup that ends here.
    rm -f "$PY_CACHE"
    if ! find_python; then
        # No base Python, but a ready venv is still a finished setup. Only its
        # own interpreter can say so, and it is never asked to rebuild itself.
        case " $* " in
            *" --force "*) ;;
            *)
                for vpy in "$DATA_ROOT/wf-venv/bin/python" "$DATA_ROOT/wf-venv/Scripts/python.exe"; do
                    if [ -f "$vpy" ]; then
                        code=0
                        "$vpy" "$LAUNCH" --launcher wf.sh --data-root "$DATA_ROOT" setup --ready-only || code=$?
                        [ "$code" -eq 0 ] && exit 0
                        break
                    fi
                done ;;
        esac
        case " $* " in
            *" --install-python "*)
                echo "wf: no Python 3 found — attempting install (this changes your system)..." >&2
                try_install_python || true
                find_python || { echo "wf: install did not produce a usable Python 3. Install manually: $(py_install_hint)" >&2; exit 20; } ;;
            *)
                echo "wf: Python 3 is required but was not found." >&2
                echo "    Install it, then re-run 'wf.sh setup':" >&2
                echo "      $(py_install_hint)" >&2
                echo "    Or re-run as 'wf.sh setup --install-python' to attempt it automatically." >&2
                exit 20 ;;
        esac
    fi
    exec "${BASE_PY[@]}" "$LAUNCH" --launcher wf.sh --data-root "$DATA_ROOT" setup "$@"
fi

# Launching Python only to find it costs about 420 ms on Windows, so a cached
# venv interpreter is trusted while its path exists. A cached system Python
# still goes through wf_launch.py, which builds the venv if it can.
cached_kind=''
cached_path=''
if [ -f "$PY_CACHE" ]; then
    { IFS= read -r cached_kind; IFS= read -r cached_path; } < "$PY_CACHE" || true
    cached_kind="${cached_kind%$'\r'}"
    cached_path="${cached_path%$'\r'}"
fi
if [ -n "$cached_path" ] && [ -f "$cached_path" ] && { [ "$cached_kind" = venv ] || [ "$cached_kind" = base ]; }; then
    set +e
    if [ "$cached_kind" = venv ]; then
        "$cached_path" "$WF" "$@"
    else
        "$cached_path" "$LAUNCH" --launcher wf.sh --data-root "$DATA_ROOT" run "$@"
    fi
    code=$?
    set -e
    # 126 and 127 are the shell saying the interpreter would not launch; wf.py
    # never exits with either. Anything else is wf's own answer, passed on.
    if [ "$code" -ne 126 ] && [ "$code" -ne 127 ]; then
        exit "$code"
    fi
    rm -f "$PY_CACHE"
    echo "wf: the cached interpreter $cached_path would not start; looking for Python again." >&2
fi

if find_python; then
    exec "${BASE_PY[@]}" "$LAUNCH" --launcher wf.sh --data-root "$DATA_ROOT" run "$@"
fi
echo "wf: Python 3 not found; run 'wf.sh setup' (or install Python 3.x). Falling back to the inline procedure." >&2
exit 20
