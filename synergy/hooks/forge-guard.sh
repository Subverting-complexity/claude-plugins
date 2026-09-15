#!/usr/bin/env bash
# PreToolUse hook: turn a post to a platform other than GitHub into a
# permission prompt. The decision lives in scripts/forge_guard.py. A cheap
# text check runs first, so an ordinary tool call never starts Python.
input=$(cat)
printf '%s' "$input" | grep -qiE '\baz\b|glab|azure|visualstudio|gitlab|bitbucket|devops|push|[_-]ado[_-]' || exit 0

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts" && pwd)/forge_guard.py"
guard() { printf '%s' "$input" | "$@" "$script"; }

if command -v python3 >/dev/null 2>&1 && python3 -c '' >/dev/null 2>&1; then guard python3
elif command -v py >/dev/null 2>&1 && py -3 -c '' >/dev/null 2>&1; then guard py -3
elif command -v python >/dev/null 2>&1 && python -c '' >/dev/null 2>&1; then guard python
else
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"synergy could not start Python to check whether this posts outside GitHub. Approve only if you asked for it."}}'
fi
exit 0
