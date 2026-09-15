#!/usr/bin/env bash
# PreToolUse hook for where the plugin may write. scripts/forge_guard.py makes
# the decision: a write to Azure DevOps, GitLab or Bitbucket asks first, and
# with a GitHub allowlist on this machine a GitHub write outside it is denied.
# A cheap text check runs first, so an ordinary tool call never starts Python.
# It runs before every shell and MCP call, so the check uses bash built-ins
# only: starting cat, sed and grep for it cost about a quarter of a second on
# Windows. The check may let through a call that turns out to be a read; it
# must never stop a write that Python would catch.
IFS= read -r -d '' input

# Look only at the tool name and its input: the working directory and the
# transcript path would otherwise match a repository whose path says "gitlab",
# and the description one that says "push".
# JSON writes a line break as \n, which would join `gh` on a new line to the
# n before it, so escaped breaks and tabs become spaces.
subject=$input
meta='"(cwd|transcript_path|session_id|permission_mode|hook_event_name|tool_use_id|description)"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"'
while [[ $subject =~ $meta ]]; do
    subject=${subject/"${BASH_REMATCH[0]}"/}
done
subject=${subject//\\n/ }
subject=${subject//\\r/ }
subject=${subject//\\t/ }

# forge_guard.py splits an MCP tool name at its capitals, so `myAdo` holds the
# word ado and `createPullRequest` the word create with nothing between them.
# Seeing that needs case, so it is worked out before case is ignored. The
# verbs are command_parse.py's WRITE_VERBS; a test keeps the two in step.
mcp= mcp_forge= mcp_write=
tool='"tool_name"[[:space:]]*:[[:space:]]*"(mcp__[^"]*)"'
if [[ $subject =~ $tool ]]; then
    mcp=${BASH_REMATCH[1]}
    ado='(Ado|ADO)([^[:lower:]]|$)|(^|[^[:alpha:]])ado([^[:lower:]]|$)'
    [[ $mcp =~ $ado ]] && mcp_forge=1
    verbs='abandon|add|approve|archive|assign|cancel|close|comment|complete|create|delete|dismiss|dispatch|edit|fork|import|link|lock|manage|merge|modify|move|note|patch|post|publish|push|put|queue|reactivate|remove|rename|reopen|reply|rerun|resolve|retry|revoke|run|save|send|set|star|submit|transfer|trigger|unlink|unlock|update|upload|vote|write'
    Verbs='Abandon|Add|Approve|Archive|Assign|Cancel|Close|Comment|Complete|Create|Delete|Dismiss|Dispatch|Edit|Fork|Import|Link|Lock|Manage|Merge|Modify|Move|Note|Patch|Post|Publish|Push|Put|Queue|Reactivate|Remove|Rename|Reopen|Reply|Rerun|Resolve|Retry|Revoke|Run|Save|Send|Set|Star|Submit|Transfer|Trigger|Unlink|Unlock|Update|Upload|Vote|Write'
    # A run of capitals, as in CREATE_ISSUE, is a word of its own; rather
    # than list every verb a third time, any such run is checked.
    camel="(^|[^[:alpha:]])($verbs)([^[:lower:]]|$)|($Verbs)([^[:lower:]]|$)|[[:upper:]][[:upper:]]"
    [[ $mcp =~ $camel ]] && mcp_write=1
fi

# bash regex has no \b on every platform, so a word edge is spelt out.
w='[^[:alnum:]_]'
pattern="(^|$w)az($w|$)|azdo|glab|dev\\.azure|visualstudio|gitlab|bitbucket|devops|push|[_-]ado[_-]|invoke-(restmethod|webrequest)|(^|$w)(irm|iwr)($w|$)|(pwsh|powershell)(\\.exe)?([^\"[:alnum:]_]|$)|(^|$w)(--?|/)(ec|en[a-z]*)($w|$)"
# With an allowlist, a GitHub call is checked only when it could write. Most
# GitHub calls are reads such as `gh pr view`, and starting Python for each
# cost about 300 ms. The words are forge_guard.py's WRITE_HINT, every write
# action github_guard.py knows for `gh` and `hub`, and what makes an API call
# a write; `wf` is always checked, since most of its subcommands write.
github="(^|$w)(gh|hub)($w|$)|github|\"owner\"[[:space:]]*:"
wf='wf\.(sh|ps1|py)'
write="(^|$w)(create|merge|comment|edit|close|reopen|delete|push|post|patch|put|add|set|fork|mutation|review|transfer|claim|pick|stage-set|post-merge|handoff|upload|write|update|remove|api|graphql|remote|config|curl|wget|ready|lock|unlock|revert|pin|unpin|develop|rename|archive|unarchive|sync|clone|workflow|rerun|cancel|enable|disable|secret|variable|copy|link|unlink|mark-template|new|pull-request|deploy-key|autolink|release)($w|$)|(^|$w)(-X|--method)"
allowlist="${SYNERGY_GITHUB_ALLOWLIST:-$HOME/.claude/synergy/github-allowlist.json}"
shopt -s nocasematch
if [ -z "$mcp_forge" ] && ! [[ $subject =~ $pattern ]]; then
    [ -f "$allowlist" ] && [[ $subject =~ $github || $subject =~ $wf ]] || exit 0
    if [ -n "$mcp" ]; then
        [ -n "$mcp_write" ] || exit 0
    else
        [[ $subject =~ $wf || $subject =~ $write ]] || exit 0
    fi
fi

# ${BASH_SOURCE[0]%/*} rather than dirname and pwd, which cost two processes.
here=${BASH_SOURCE[0]%[/\\]*}
[ "$here" = "${BASH_SOURCE[0]}" ] && here=.
script="$here/../scripts/forge_guard.py"
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
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"synergy could not start Python to check where this writes. Approve only if you asked for it."}}'
exit 0
