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
  outright.

Reads pass untouched.
"""
import json
import re
import sys

from command_parse import (READ_METHODS, WRITE_VERBS, expand, flag_value,
                           has_flag, host, mcp_writes, name_words, push_url,
                           remote_url, walk)

# Hosts of the platforms the plugin must not post to on its own.
FORGE_HOSTS = re.compile(
    r'dev\.azure\.com|visualstudio\.com|gitlab\.com|bitbucket\.org', re.I)

AZ_GROUPS = {'repos', 'boards', 'devops', 'pipelines', 'artifacts'}
MCP_FORGE_WORDS = {'devops', 'ado', 'azdo', 'gitlab', 'bitbucket'}
HTTP_TOOLS = {'curl', 'wget', 'invoke-restmethod', 'invoke-webrequest',
              'irm', 'iwr'}
DATA_FLAGS = {'--data', '--data-raw', '--data-binary', '--data-urlencode',
              '--data-ascii', '--json', '--form', '--form-string',
              '--upload-file', '--post-data', '--post-file', '--body-data',
              '--body-file'}
# curl's short flags that take no value, so they can sit in a cluster ahead
# of -X or -d, as in -sXPOST.
CURL_BARE = 'sSLkfivgnq'


def _not_read(method):
    return bool(method) and method.upper() not in READ_METHODS


def _subcommand(toks, start):
    """The words of a CLI subcommand, up to its first flag."""
    words = []
    for token in toks[start:]:
        if token.startswith('-'):
            break
        words.append(token)
    return words


def _curl_write(toks):
    method, data = None, False
    for i, token in enumerate(toks[1:], 1):
        after = toks[i + 1] if i + 1 < len(toks) else ''
        if token.startswith('--'):
            name, eq, value = token.partition('=')
            if name in ('--request', '--method'):
                method = value if eq else after
            elif name in DATA_FLAGS:
                data = True
        elif token.startswith('-'):
            cluster_method = re.match(r'^-[%s]*X(.*)$' % CURL_BARE, token)
            if cluster_method:
                method = cluster_method.group(1) or after
            elif re.match(r'^-[%s]*[dFT]' % CURL_BARE, token):
                data = True
    return data or _not_read(method)


def _powershell_write(toks):
    return (has_flag(toks, ['-Body', '-InFile'])
            or _not_read(flag_value(toks, ['-Method'])))


def _az(toks, text):
    if len(toks) < 2:
        return None
    if toks[1] == 'rest':
        if FORGE_HOSTS.search(text) and (
                has_flag(toks, ['--body', '-b'])
                or _not_read(flag_value(toks, ['--method', '-m']))):
            return 'an Azure DevOps REST call (`az rest`)'
        return None
    if toks[1] not in AZ_GROUPS:
        return None
    words = _subcommand(toks, 2)
    if 'invoke' in words:
        if _not_read(flag_value(toks, ['--http-method'])):
            return 'an Azure DevOps API call (`az devops invoke`)'
        return None
    if any(w in WRITE_VERBS for w in words):
        return 'an Azure DevOps command (`az %s`)' % ' '.join([toks[1]] + words)
    return None


def _glab(toks):
    words = _subcommand(toks, 1)
    if words[:1] == ['api']:
        if (has_flag(toks, ['-f', '-F', '--field', '--raw-field', '--input'])
                or _not_read(flag_value(toks, ['-X', '--method']))):
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
    for toks, where, variables in walk(command, cwd):
        text = expand(' '.join(toks), variables)
        program = toks[0]
        found = None
        if program == 'az':
            found = _az(toks, text)
        elif program == 'glab':
            found = _glab(toks)
        elif program in HTTP_TOOLS and FORGE_HOSTS.search(text):
            writes = (_curl_write(toks) if program in ('curl', 'wget')
                      else _powershell_write(toks))
            if writes:
                found = 'a REST call to %s' % FORGE_HOSTS.search(text).group(0)
        elif program == 'git':
            url = push_url(toks, where, lookup)
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


def main():
    try:
        event = json.load(sys.stdin)
        name = event.get('tool_name') or ''
        tool_input = event.get('tool_input') or {}
        cwd = event.get('cwd')
        import github_guard
        allowlist = github_guard.load_allowlist()
        blocked = github_guard.github_block(name, tool_input, cwd, allowlist)
        if blocked:
            print(json.dumps(github_guard.denial(blocked, allowlist)))
            return 0
        reason = outbound_post(name, tool_input, cwd)
    except Exception:  # a broken guard must never break the tool call
        return 0
    if reason:
        print(json.dumps(decision(reason)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
