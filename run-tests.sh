#!/usr/bin/env bash
# Run the offline test suite (decision logic + wf.py I/O shell).
# Discovery picks up every tests/test_*.py module, so new test files run
# automatically without editing this script.
# Tries python3, py -3 (Windows Python Launcher), then python in order.
# Prints which interpreter it found; exits 1 with an install hint if none found.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

DISCOVER=(-m unittest discover -s tests -p 'test_*.py')

if command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
    echo "==> Using $(python3 --version)"
    exec python3 "${DISCOVER[@]}" "$@"
elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
    echo "==> Using $(py -3 --version) (Windows Python Launcher)"
    exec py -3 "${DISCOVER[@]}" "$@"
elif command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    echo "==> Using $(python --version)"
    exec python "${DISCOVER[@]}" "$@"
else
    echo "ERROR: Python not found. Install Python 3.x and re-run." >&2
    echo "  Windows: winget install Python.Python.3.12" >&2
    echo "  macOS:   brew install python" >&2
    echo "  Linux:   sudo apt install python3  (or your distro's equivalent)" >&2
    exit 1
fi
