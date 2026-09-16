#!/usr/bin/env bash
# Run the offline test suite (decision logic + wf.py I/O shell).
# Discovery picks up every tests/test_*.py module, so new test files run
# automatically without editing this script.
# Resolves a Python 3 via scripts/find-python.sh: tries python3, py -3
# (Windows Python Launcher), then python in order.
# Prints which interpreter it found; exits 1 with an install hint if none found.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# shellcheck source=scripts/find-python.sh
source scripts/find-python.sh

DISCOVER=(-m unittest discover -s tests -p 'test_*.py')

if find_python; then
    if [ "${BASE_PY[0]}" = "py" ]; then
        echo "==> Using $("${BASE_PY[@]}" --version) (Windows Python Launcher)"
    else
        echo "==> Using $("${BASE_PY[@]}" --version)"
    fi
    exec "${BASE_PY[@]}" "${DISCOVER[@]}" "$@"
else
    echo "ERROR: Python not found. Install Python 3.x and re-run." >&2
    echo "  Windows: winget install Python.Python.3.12" >&2
    echo "  macOS:   brew install python" >&2
    echo "  Linux:   sudo apt install python3  (or your distro's equivalent)" >&2
    exit 1
fi
