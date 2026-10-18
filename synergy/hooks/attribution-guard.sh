#!/usr/bin/env bash
# PreToolUse hook against AI attribution. scripts/attribution_guard.py makes
# the decision: a commit, pull request, issue or comment that says an AI wrote
# it is denied. A cheap text check runs first, so an ordinary tool call never
# starts Python. It runs before every shell and MCP call, so the check uses
# bash built-ins only: starting cat, sed and grep for it cost about a quarter
# of a second on Windows. The check may start Python for a call that turns out
# to be harmless; it must never pass a call that Python would deny.
IFS= read -r -d '' input

# The words of attribution_guard.py's ATTRIBUTION, each cut to a part that
# every match holds.
pattern='co-authored-by|generated with|noreply@anthropic|reviewed with claude'
shopt -s nocasematch
[[ $input =~ $pattern ]] || exit 0

# ${BASH_SOURCE[0]%/*} rather than dirname and pwd, which cost two processes.
here=${BASH_SOURCE[0]%[/\\]*}
[ "$here" = "${BASH_SOURCE[0]}" ] && here=.
script="$here/../scripts/attribution_guard.py"
cache="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/synergy}/guard-python"

# The script always prints a JSON line, `{}` when it has nothing to say. An
# interpreter that exits without printing did not run it (a Microsoft Store
# `python3` stub can do that), and one that prints anything else is not
# Python running it, so neither is trusted or cached.
judge() {
    out=$("$@" "$script" <<<"$input" 2>/dev/null) || return 1
    [ "${out:0:1}" = '{' ] || return 1
    [ "$out" = '{}' ] || printf '%s\n' "$out"
    return 0
}

# Finding a working Python costs a few hundred milliseconds on Windows, so
# the first one that runs the script is kept, as the interpreter's own path:
# `py -3` would otherwise start the launcher and then Python on every call.
py=
[ -f "$cache" ] && read -r py < "$cache"
if [ -n "$py" ]; then
    judge "$py" && exit 0
    rm -f "$cache"
fi
for py in python3 'py -3' python; do
    # Unquoted on purpose: `py -3` is a program and its first argument.
    if judge $py; then
        exe=$($py -c 'import sys; sys.stdout.write(sys.executable)' 2>/dev/null)
        if [ -n "$exe" ]; then
            [ -d "${cache%/*}" ] || mkdir -p "${cache%/*}" 2>/dev/null
            printf '%s' "$exe" > "$cache" 2>/dev/null
        fi
        exit 0
    fi
done
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"synergy could not start Python to check this call for an AI attribution line. Approve only if the call adds no such line."}}'
exit 0
