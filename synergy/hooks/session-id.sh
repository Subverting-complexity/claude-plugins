#!/usr/bin/env bash
# SessionStart hook: records the Claude Code session's own id where wf reads
# it, so every claim in the session carries the label `session: <id>` (#440).
#
# Claude Code passes `session_id` in the JSON a hook reads on stdin, and a
# SessionStart hook may append `export` lines to the file `CLAUDE_ENV_FILE`
# names, which Claude Code applies to the shell commands it runs later in the
# session. This hook appends `export WF_SESSION_ID=<id>` there. It prints
# nothing, so it adds nothing to the context of any chat.
#
# Bash built-ins only, as in repo-host.sh: it runs at every session start, and
# a process start costs tens of milliseconds on Windows. With no session id or
# no CLAUDE_ENV_FILE it does nothing, and wf falls back as
# scripts/wf_claim_label.py says.
input=
while IFS= read -r line || [ -n "$line" ]; do
    input+="$line"
done
[ -n "${CLAUDE_ENV_FILE:-}" ] || exit 0
re='"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9-]{1,40})"'
[[ $input =~ $re ]] || exit 0
printf 'export WF_SESSION_ID=%s\n' "${BASH_REMATCH[1]}" >> "$CLAUDE_ENV_FILE" 2>/dev/null
exit 0
