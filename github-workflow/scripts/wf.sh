#!/usr/bin/env bash
# Thin launcher for wf.py — finds a working Python 3 interpreter (same
# detection order as run-tests.sh: a present-but-broken `python3` Store shim
# on Windows fails its --version probe and falls through to `py -3`), then
# runs the CLI. The interpreter exit code is preserved via exec, so the
# wf contract codes (0/10/11/20/30) propagate unchanged.
#
# Usage (from the target repo root, so wf.py finds ClaudeProject.md + git):
#   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick [--checkout]
#   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WF="$HERE/wf.py"

if command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
    exec python3 "$WF" "$@"
elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
    exec py -3 "$WF" "$@"
elif command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    exec python "$WF" "$@"
else
    echo "wf: Python 3 not found (install Python 3.x); falling back to the inline procedure." >&2
    exit 20
fi
