#!/usr/bin/env bash
# PreToolUse hook for where the plugin may write. scripts/forge_guard.py makes
# the decision: a write to Azure DevOps, GitLab or Bitbucket asks first, and
# with a GitHub allowlist on this machine a GitHub write outside it is denied.
# A cheap text check runs first, so an ordinary tool call never starts Python.
input=$(cat)

# Look only at the tool name and its input: the working directory and the
# transcript path would otherwise match a repository whose path says "gitlab".
subject=$(printf '%s' "$input" | sed -E 's/"(cwd|transcript_path|session_id|permission_mode|hook_event_name|tool_use_id)"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"//g')
pattern='\baz\b|glab|dev\.azure|visualstudio|gitlab|bitbucket|devops|push|[_-]ado[_-]|invoke-(restmethod|webrequest)|\birm\b|\biwr\b'
allowlist="${SYNERGY_GITHUB_ALLOWLIST:-$HOME/.claude/synergy/github-allowlist.json}"
[ -f "$allowlist" ] && pattern="$pattern|\\bgh\\b|github|wf\\.(sh|ps1|py)"
printf '%s' "$subject" | grep -qiE "$pattern" || exit 0

script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts" && pwd)/forge_guard.py"
cache="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/synergy}/guard-python"

# Finding a working Python costs a few hundred milliseconds on Windows, where
# `python3` can be the Microsoft Store stub, so the first one found is kept.
if [ -f "$cache" ]; then
    py=$(cat "$cache")
    printf '%s' "$input" | $py "$script" && exit 0
fi
for py in python3 'py -3' python; do
    if $py -c '' >/dev/null 2>&1; then
        mkdir -p "$(dirname "$cache")" 2>/dev/null && printf '%s' "$py" > "$cache"
        printf '%s' "$input" | $py "$script"
        exit 0
    fi
done
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"synergy could not start Python to check where this writes. Approve only if you asked for it."}}'
exit 0
