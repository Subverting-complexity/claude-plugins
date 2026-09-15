#!/usr/bin/env python3
"""PreToolUse guard for where the plugin may write.

Two checks, both on the tool call Claude Code is about to make:

- **Outside GitHub, ask.** The plugin posts only to GitHub. On a repository
  hosted elsewhere a run could still reach for that platform's own tools:
  `az repos pr create`, a REST call to dev.azure.com, a push to the Azure
  remote, an Azure DevOps MCP tool. A write to Azure DevOps, GitLab or
  Bitbucket becomes a permission prompt.
- **On GitHub, only where this machine allows.** With a GitHub allowlist on
  this machine (see github_guard.py), a GitHub write outside it is denied
  outright, and so is a call the guard cannot read that looks like one.

Reads pass untouched. The script always prints one line, `{}` when it has
nothing to say, so the hook can tell it ran from an interpreter that did not.
"""
import json
import re
import sys

from command_parse import (HTTP_TOOLS, WRITE_VERBS, expand, flag_value,
                           has_flag, host, http_writes, mcp_writes,
                           name_words, not_read, push_url, remote_url, walk)

# Hosts of the platforms the plugin must not post to on its own.
FORGE_HOSTS = re.compile(
    r'dev\.azure\.com|visualstudio\.com|gitlab\.com|bitbucket\.org', re.I)

AZ_GROUPS = {'repos', 'boards', 'devops', 'pipelines', 'artifacts'}
MCP_FORGE_WORDS = {'devops', 'ado', 'azdo', 'gitlab', 'bitbucket'}

# What a call the guard could not read has to look like to be denied.
GITHUB_HINT = re.compile(r'\bgh\b|\bhub\b|github|wf\.(sh|ps1|py)|\bpush\b', re.I)
WRITE_HINT = re.compile(
    r'\b(create|merge|comment|edit|close|reopen|delete|push|post|patch|put|'
    r'add|set|fork|mutation|review|transfer|claim|pick|stage-set|post-merge|'
    r'handoff|upload|write|update|remove)\b', re.I)


def _subcommand(toks, start):
    """The words of a CLI subcommand, up to its first flag."""
    words = []
    for token in toks[start:]:
        if token.startswith('-'):
            break
        words.append(token)
    return words


def _az(toks, text):
    if len(toks) < 2:
        return None
    if toks[1] == 'rest':
        if FORGE_HOSTS.search(text) and (
                has_flag(toks, ['--body', '-b'])
                or not_read(flag_value(toks, ['--method', '-m']))):
            return 'an Azure DevOps REST call (`az rest`)'
        return None
    if toks[1] not in AZ_GROUPS:
        return None
    words = _subcommand(toks, 2)
    if 'invoke' in words:
        if not_read(flag_value(toks, ['--http-method'])):
            return 'an Azure DevOps API call (`az devops invoke`)'
        return None
    if any(w in WRITE_VERBS for w in words):
        return 'an Azure DevOps command (`az %s`)' % ' '.join([toks[1]] + words)
    return None


def _glab(toks):
    words = _subcommand(toks, 1)
    if words[:1] == ['api']:
        if (has_flag(toks, ['-f', '-F', '--field', '--raw-field', '--input'])
                or not_read(flag_value(toks, ['-X', '--method']))):
            return 'a GitLab API call (`glab api`)'
        return None
    if any(w in WRITE_VERBS for w in words):
        return 'a GitLab command (`glab %s`)' % ' '.join(words)
    return None


def outbound_post(tool_name, tool_input, cwd=None, lookup=remote_url):
    """What this tool call would post outside GitHub, or None."""
    if tool_name.startswith('mcp__'):
        if set(name_words(tool_name)) & MCP_FORGE_WORDS and mcp_writes(tool_name):
            return 'the MCP tool `%s`' % tool_name
        return None
    command = (tool_input or {}).get('command') or ''
    for toks, where, variables in walk(command, cwd, tool_name == 'PowerShell'):
        text = expand(' '.join(toks), variables)
        program = toks[0]
        found = None
        if program == 'az':
            found = _az(toks, text)
        elif program == 'glab':
            found = _glab(toks)
        elif program in HTTP_TOOLS and FORGE_HOSTS.search(text):
            if http_writes(toks):
                found = 'a REST call to %s' % FORGE_HOSTS.search(text).group(0)
        elif program == 'git':
            url = push_url(toks, where, lookup, variables)
            if url and FORGE_HOSTS.search(host(url) or ''):
                found = 'a push to %s' % host(url)
        if found:
            return found
    return None


def decision(reason):
    return {
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'ask',
            'permissionDecisionReason': (
                'synergy: this is %s, which posts outside GitHub. The plugin '
                'never posts to another platform on its own; approve only if '
                'you asked for this.' % reason),
        }
    }


def evaluate(raw, load_allowlist=None, block=None, post=outbound_post):
    """The hook's answer to one PreToolUse event, as a dict, or None to let
    the call run. A call the guard fails to read is let through, unless this
    machine has a GitHub allowlist and the call looks like a GitHub write."""
    import github_guard
    load_allowlist = load_allowlist or github_guard.load_allowlist
    block = block or github_guard.github_block
    allowlist = load_allowlist()
    try:
        event = json.loads(raw)
        name = event.get('tool_name') or ''
        tool_input = event.get('tool_input') or {}
        cwd = event.get('cwd')
        blocked = block(name, tool_input, cwd, allowlist)
        if blocked:
            return github_guard.denial(blocked, allowlist)
        reason = post(name, tool_input, cwd)
    except Exception as exc:  # a broken guard must not break the tool call
        if allowlist is not None and GITHUB_HINT.search(raw or '') \
                and WRITE_HINT.search(raw or ''):
            return github_guard.denial(
                'a tool call synergy could not read (%s: %s) that looks like '
                'a GitHub write' % (type(exc).__name__, exc), allowlist)
        return None
    return decision(reason) if reason else None


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
