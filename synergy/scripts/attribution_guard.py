#!/usr/bin/env python3
"""PreToolUse guard against AI attribution.

A commit message, pull request, issue or comment that says an AI wrote it
(`Co-Authored-By: Claude`, "Generated with Claude Code") is denied. Claude
Code adds those lines by default, so the check stops a run that follows that
default.

The plugin does not check where a call writes. That belongs to a guard on
the machine, which knows which owners and organisations the person trusts.

The script always prints one line, `{}` when it has nothing to say, so the
hook can tell it ran from an interpreter that did not.
"""
import json
import re
import sys

# The hook keeps the first interpreter that prints an answer. One too old for
# this script would be kept too, so it exits without printing and the hook
# tries the next.
if sys.version_info < (3, 7):
    sys.exit(1)

# The lines Claude Code adds to say an AI wrote a commit or a pull request.
ATTRIBUTION = re.compile(
    r'co-authored-by:[^\n]*(claude|anthropic)|generated with[^\n]*claude'
    r'|noreply@anthropic\.com|reviewed with claude code', re.I)
# A shell call that writes a commit message, or posts to GitHub.
WRITES_TEXT = re.compile(r'\bgit\b[^\n;|&]*\bcommit\b|\b(gh|hub)\b', re.I)

# Words in an MCP tool name that change something.
WRITE_VERBS = {
    'create', 'update', 'delete', 'add', 'remove', 'set', 'set-vote', 'vote',
    'abandon', 'complete', 'reactivate', 'run', 'trigger', 'queue', 'import',
    'link', 'unlink', 'approve', 'merge', 'note', 'comment', 'close',
    'reopen', 'revoke', 'retry', 'rerun', 'cancel', 'publish', 'upload',
    'post', 'reply', 'resolve', 'edit', 'push', 'write', 'assign', 'fork',
    'dismiss', 'star', 'transfer', 'lock', 'unlock', 'archive', 'rename',
    'move', 'submit', 'send', 'dispatch', 'patch', 'put', 'modify', 'save',
    'manage',
}

# Words that make an MCP tool a read when they come before any write word,
# so `list_merge_requests` and `get_issue_link` read.
READ_VERBS = {
    'get', 'list', 'search', 'read', 'view', 'fetch', 'describe', 'show',
    'query', 'find', 'download', 'export', 'check', 'count', 'compare',
    'diff', 'preview', 'whoami', 'lookup', 'browse', 'inspect',
}


def name_words(name):
    return [w.lower() for w in
            re.findall(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+', name)]


def mcp_writes(tool_name):
    """Whether an MCP tool changes something, judged from its action name:
    the first read or write word decides."""
    action = '__'.join(tool_name.split('__')[2:])
    for word in name_words(action):
        if word in READ_VERBS:
            return False
        if word in WRITE_VERBS:
            return True
    return False


def attribution(tool_name, tool_input):
    """The attribution line this tool call would write, or None. Only a call
    that writes a commit or posts text is read, so a command that merely
    searches for the phrase passes."""
    tool_input = tool_input or {}
    if tool_name.startswith('mcp__'):
        if not mcp_writes(tool_name):
            return None
        text = '\n'.join(str(v) for v in tool_input.values())
    else:
        text = tool_input.get('command') or ''
        if not WRITES_TEXT.search(text):
            return None
    found = ATTRIBUTION.search(text)
    return found.group(0) if found else None


def attribution_denial(line):
    return {
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': (
                'synergy blocked this: it adds an AI attribution line (%r). '
                'This person does not allow AI attribution in commits, pull '
                'requests, issues or comments. Remove the line and try '
                'again. Do not add it in another form.' % line),
        }
    }


def evaluate(raw):
    """The hook's answer to one PreToolUse event, as a dict, or None to let
    the call run. A call the guard fails to read is let through."""
    try:
        event = json.loads(raw)
        line = attribution(event.get('tool_name') or '',
                           event.get('tool_input') or {})
    except Exception:  # a broken guard must not break the tool call
        return None
    return attribution_denial(line) if line else None


def main():
    out = None
    try:
        raw = sys.stdin.buffer.read().decode('utf-8', 'replace')
        out = evaluate(raw)
    except Exception:
        out = None
    print(json.dumps(out) if out else '{}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
