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
#       code is preserved (see the exit-code table in README.md).
#
# Finding the interpreter used to launch it with `--version` on every call,
# about 420 ms on Windows where no venv exists. The answer is now cached in
# `$DATA_ROOT/wf-python` and trusted while the path it names still exists;
# `setup` rewrites it, and an interpreter that will not launch is forgotten.
#
# Run from the target repo root so wf.py finds ClaudeProject.md and git.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WF="$HERE/wf.py"

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
VENV="$DATA_ROOT/wf-venv"
# `mkdir` on this path is the exclusivity check for auto-bootstrap below: it
# either succeeds for exactly one concurrent caller or fails for the rest.
VENV_LOCK="$DATA_ROOT/wf-venv.lock"
# Two lines: `venv` or `base`, then the interpreter's path. wf.ps1 keeps its
# own, because a path this shell writes is not one PowerShell can run.
PY_CACHE="$DATA_ROOT/wf-python"
PY=''
PY_KIND=''

# Echo the venv's python path if it exists and runs, else fail.
venv_python() {
    local p=''
    if [ -f "$VENV/bin/python" ]; then p="$VENV/bin/python"
    elif [ -f "$VENV/Scripts/python.exe" ]; then p="$VENV/Scripts/python.exe"
    else return 1; fi
    "$p" --version >/dev/null 2>&1 || return 1
    printf '%s' "$p"
}

# Whether a venv interpreter file exists, without running it.
venv_present() {
    [ -f "$VENV/bin/python" ] || [ -f "$VENV/Scripts/python.exe" ]
}

# Detect a usable system Python 3 into the BASE_PY array (verifies --version
# actually runs, so the broken Windows `python3` Store shim is skipped).
detect_base_py() {
    if command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then BASE_PY=(python3); return 0; fi
    if command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then BASE_PY=(py -3); return 0; fi
    if command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then BASE_PY=(python); return 0; fi
    return 1
}

# Record which interpreter runs wf.py. Best-effort: a cache that cannot be
# written only means the next call probes again.
save_python_cache() {
    { mkdir -p "$DATA_ROOT" && printf '%s\n%s\n' "$1" "$2" > "$PY_CACHE"; } 2>/dev/null || true
}

# Load the cached interpreter into PY without running it. The path must still
# exist, and a cached system Python gives way as soon as a venv exists, so a
# venv made by the other launcher's setup is picked up.
cached_python() {
    [ -f "$PY_CACHE" ] || return 1
    local kind='' path=''
    { IFS= read -r kind; IFS= read -r path; } < "$PY_CACHE" || true
    kind="${kind%$'\r'}"
    path="${path%$'\r'}"
    [ -n "$path" ] && [ -f "$path" ] || return 1
    case "$kind" in
        venv) ;;
        base) if venv_present; then return 1; fi ;;
        *) return 1 ;;
    esac
    PY="$path"
    PY_KIND="$kind"
}

# Resolve the interpreter by running the candidates, and cache the answer. A
# system Python is cached by its absolute path, so a later call neither
# searches PATH nor goes through the `py` launcher.
probe_python() {
    local p=''
    if p=$(venv_python); then
        PY="$p"; PY_KIND=venv
        save_python_cache venv "$p"
        return 0
    fi
    detect_base_py || return 1
    PY_KIND=base
    p=$("${BASE_PY[@]}" -c 'import sys; print(sys.executable)' 2>/dev/null) || p=''
    p="${p%$'\r'}"
    if [ -n "$p" ] && [ -f "$p" ]; then
        PY="$p"
        save_python_cache base "$p"
    fi
    return 0
}

base_warning() {
    echo "wf: no dedicated virtualenv yet — using system Python ${PY:-${BASE_PY[*]}}. Run 'wf.sh setup' to pin one." >&2
}

# Try to create the dedicated venv from a usable base Python, silently, on a
# run that would otherwise fall back to system Python. Mirrors wf_setup's
# create step but never installs a system Python and never prints anything:
# any failure here is not this call's problem to report, so it just leaves
# the caller to fall back to base_warning and system Python as before.
# Echoes the venv's python path on success.
#
# Unlike `setup` (a one-off command a person runs by hand), this can now run
# from any ordinary invocation, so two calls with no venv yet can start at the
# same moment — plausible here since parallel agents on one machine share
# $DATA_ROOT (docs/worktree-config.md). `mkdir "$VENV_LOCK"` is atomic: only
# one caller creates it, so only one caller builds the venv. A loser polls for
# the winner's result instead of racing it into the same `python -m venv`
# target, which could otherwise interleave two writes into one venv directory
# and leave it corrupted.
autobootstrap_venv() {
    local base=("$@") vpy=''
    [ "${#base[@]}" -gt 0 ] && [ -n "${base[0]}" ] || return 1
    "${base[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1 || return 1
    vpy=$(
        set -e
        mkdir -p "$DATA_ROOT" 2>/dev/null
        waited=0
        while ! mkdir "$VENV_LOCK" 2>/dev/null; do
            if existing=$(venv_python); then printf '%s' "$existing"; exit 0; fi
            [ "$waited" -ge 30 ] && exit 1
            sleep 1
            waited=$((waited + 1))
        done
        trap 'rmdir "$VENV_LOCK" 2>/dev/null' EXIT
        # The winner may have finished between our first check and the lock.
        if existing=$(venv_python); then printf '%s' "$existing"; exit 0; fi
        mkdir -p "$(dirname "$VENV")"
        "${base[@]}" -m venv "$VENV" >/dev/null 2>&1 || exit 1
        created=$(venv_python) || exit 1
        "$created" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
        if [ -f "$HERE/requirements.txt" ]; then
            "$created" -m pip install --quiet -r "$HERE/requirements.txt" >/dev/null 2>&1 || exit 1
        fi
        printf '%s' "$created"
    ) || return 1
    [ -n "$vpy" ] || return 1
    save_python_cache venv "$vpy"
    printf '%s' "$vpy"
}

# Called whenever PY_KIND is "base": try the silent auto-bootstrap first, and
# only warn if it did not produce a usable venv. On success this switches PY
# and PY_KIND to the new venv in place, so the caller runs on it unchanged.
maybe_bootstrap_or_warn() {
    [ "$PY_KIND" = base ] || return 0
    local base=() vpy=''
    if [ -n "$PY" ]; then base=("$PY"); else base=("${BASE_PY[@]}"); fi
    if vpy=$(autobootstrap_venv "${base[@]}"); then
        PY="$vpy"
        PY_KIND=venv
    else
        base_warning
    fi
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

    # Whatever setup ends with is what the next call should run, so the old
    # answer goes first and a failed setup leaves nothing stale behind. Also
    # clear a stale auto-bootstrap lock (e.g. left by a killed process), since
    # an explicit setup run is not itself subject to the lock.
    rm -f "$PY_CACHE"
    rm -rf "$VENV_LOCK"

    if [ "$force" -eq 0 ] && VPY=$(venv_python); then
        save_python_cache venv "$VPY"
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
    save_python_cache venv "$VPY"
    echo "wf: setup complete — $("$VPY" --version 2>&1)" >&2
    echo "    Future 'wf.sh' calls reuse this interpreter automatically." >&2
    exit 0
}

if [ "${1:-}" = "setup" ]; then
    shift
    wf_setup "$@"
fi

# Run path: the cached interpreter, else the venv, else a probed system Python.
if cached_python; then
    maybe_bootstrap_or_warn
    set +e
    "$PY" "$WF" "$@"
    code=$?
    set -e
    # 126 and 127 are the shell saying the interpreter would not launch; wf.py
    # never exits with either. Anything else is wf's own answer, passed on.
    if [ "$code" -ne 126 ] && [ "$code" -ne 127 ]; then
        exit "$code"
    fi
    rm -f "$PY_CACHE"
    echo "wf: the cached interpreter $PY would not start; looking for Python again." >&2
    PY=''
    PY_KIND=''
fi

if probe_python; then
    maybe_bootstrap_or_warn
    if [ -n "$PY" ]; then
        exec "$PY" "$WF" "$@"
    fi
    exec "${BASE_PY[@]}" "$WF" "$@"
fi
echo "wf: Python 3 not found; run 'wf.sh setup' (or install Python 3.x). Falling back to the inline procedure." >&2
exit 20
