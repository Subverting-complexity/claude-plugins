#!/usr/bin/env python3
"""PreToolUse guard: ask before anything is posted to a platform other than GitHub.

The plugin posts only to GitHub, through `gh`. On a repository hosted
elsewhere (Azure DevOps, GitLab, Bitbucket) a run could still reach for that
platform's own tools: `az repos pr create`, a REST call to dev.azure.com, a
push to the Azure remote, an Azure DevOps MCP tool. This hook reads the tool
call Claude Code is about to make and, when it would write to such a
platform, turns it into a permission prompt, so nothing is posted there
unless the person says yes.

Reads pass untouched, and nothing is denied outright: a person who asked for
the post approves the prompt.
"""
import json
import os
import re
import shlex
import subprocess
import sys

# Hosts of the platforms the plugin must not post to on its own.
FORGE_HOSTS = re.compile(
    r'dev\.azure\.com|visualstudio\.com|gitlab\.com|bitbucket\.org', re.I)

# Words in a CLI subcommand or an MCP tool name that change something.
WRITE_VERBS = {
    'create', 'update', 'delete', 'add', 'remove', 'set-vote', 'vote',
    'abandon', 'complete', 'reactivate', 'run', 'queue', 'import', 'set',
    'link', 'unlink', 'approve', 'merge', 'note', 'comment', 'close',
    'reopen', 'revoke', 'retry', 'cancel', 'publish', 'upload', 'post',
    'reply', 'resolve', 'edit', 'push', 'write',
}

AZ_GROUPS = {'repos', 'boards', 'devops', 'pipelines', 'artifacts'}
MCP_FORGE_WORDS = {'azure', 'devops', 'ado', 'azdo', 'gitlab', 'bitbucket'}
READ_METHODS = {'GET', 'HEAD', 'OPTIONS'}
HTTP_TOOLS = {'curl', 'wget', 'invoke-restmethod', 'invoke-webrequest',
              'irm', 'iwr'}
PREFIXES = {'rtk', 'sudo', 'env', 'command', 'exec', '&', '(', '{'}


def _program(token):
    name = re.split(r'[\\/]', token)[-1].lower()
    return re.sub(r'\.(exe|cmd|bat|ps1)$', '', name)


def _tokens(segment):
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        tokens = segment.split()
    while tokens and (tokens[0] in PREFIXES
                      or re.match(r'^\w+=', tokens[0])):
        tokens = tokens[1:]
    if tokens:
        tokens[0] = _program(tokens[0])
    return tokens


def _flag_value(tokens, names):
    """The value of the first flag in `names`, as `-X POST`, `-XPOST` or
    `--request=POST`. Flag names compare case-insensitively (PowerShell)."""
    lowered = {n.lower() for n in names}
    for i, token in enumerate(tokens):
        low = token.lower()
        if '=' in low and low.split('=', 1)[0] in lowered:
            return token.split('=', 1)[1]
        if low in lowered and i + 1 < len(tokens):
            return tokens[i + 1]
        for name in names:
            if len(name) == 2 and token.startswith(name) and len(token) > 2:
                return token[2:]
    return None


def _has_flag(tokens, names):
    lowered = {n.lower() for n in names}
    return any(t.lower().split('=', 1)[0] in lowered for t in tokens)


def _http_write(tokens):
    program = tokens[0]
    if program == 'az':
        method = _flag_value(tokens, ['--method', '-m'])
        data = _has_flag(tokens, ['--body', '-b'])
    elif program in ('curl', 'wget'):
        method = _flag_value(tokens, ['-X', '--request', '--method'])
        data = _has_flag(tokens, [
            '-d', '--data', '--data-raw', '--data-binary', '--data-urlencode',
            '--json', '-F', '--form', '-T', '--upload-file', '--post-data',
            '--post-file', '--body-data', '--body-file'])
    else:
        method = _flag_value(tokens, ['-Method'])
        data = _has_flag(tokens, ['-Body', '-InFile'])
    return data or (method is not None and method.upper() not in READ_METHODS)


def _az(tokens):
    if len(tokens) < 2:
        return None
    if tokens[1] == 'rest':
        if FORGE_HOSTS.search(' '.join(tokens)) and _http_write(tokens):
            return 'an Azure DevOps REST call (`az rest`)'
        return None
    if tokens[1] not in AZ_GROUPS:
        return None
    if 'invoke' in tokens:
        method = _flag_value(tokens, ['--http-method'])
        if method and method.upper() not in READ_METHODS:
            return 'an Azure DevOps API call (`az devops invoke`)'
        return None
    if any(t in WRITE_VERBS for t in tokens[2:]):
        return 'an Azure DevOps command (`az %s`)' % ' '.join(tokens[1:3])
    return None


def _glab(tokens):
    if len(tokens) < 2:
        return None
    if tokens[1] == 'api':
        method = _flag_value(tokens, ['-X', '--method'])
        data = _has_flag(tokens, ['-f', '-F', '--field', '--raw-field',
                                  '--input'])
        if data or (method and method.upper() not in READ_METHODS):
            return 'a GitLab API call (`glab api`)'
        return None
    if any(t in WRITE_VERBS for t in tokens[1:]):
        return 'a GitLab command (`glab %s`)' % ' '.join(tokens[1:3])
    return None


def _host(url):
    m = re.match(r'^[a-z][\w+.-]*://(?:[^@/]+@)?([^/:]+)', url, re.I)
    if m:
        return m.group(1).lower()
    m = re.match(r'^(?:[^@/\s]+@)?([^:/\s]+):(?!\\)', url)
    if m and '.' in m.group(1):
        return m.group(1).lower()
    return None


def _is_github(host):
    return host == 'github.com' or host.endswith(('.github.com', '.ghe.com'))


def remote_url(cwd, remote):
    """The push URL for `remote` (or the current branch's push remote)."""
    def git(*args):
        try:
            out = subprocess.run(['git'] + list(args), cwd=cwd,
                                 capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return ''
        return out.stdout.strip() if out.returncode == 0 else ''

    if remote is None:
        push = git('rev-parse', '--abbrev-ref', '--symbolic-full-name',
                   '@{push}')
        remote = push.split('/', 1)[0] if push else 'origin'
    if '://' in remote or _host(remote):
        return remote
    return git('remote', 'get-url', '--push', remote)


def _git_push(tokens, cwd, lookup):
    i = 1
    while i < len(tokens) and tokens[i].startswith('-'):
        if tokens[i] in ('-C', '-c'):
            if tokens[i] == '-C' and i + 1 < len(tokens):
                cwd = os.path.join(cwd or '.', tokens[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(tokens) or tokens[i] != 'push':
        return None
    remote = None
    rest = tokens[i + 1:]
    j = 0
    while j < len(rest):
        token = rest[j]
        if token in ('-o', '--push-option', '--receive-pack', '--exec'):
            j += 2
            continue
        if token.startswith('--repo='):
            remote = token.split('=', 1)[1]
            break
        if not token.startswith('-'):
            remote = token
            break
        j += 1
    if remote and ('://' in remote or _host(remote)):
        host = _host(remote)
    else:
        host = _host(lookup(cwd, remote) or '')
    if host and not _is_github(host):
        return 'a push to %s' % host
    return None


def _mcp(tool_name):
    words = set(re.split(r'[_\-.]+', tool_name.lower()))
    if words & MCP_FORGE_WORDS and words & WRITE_VERBS:
        return 'the MCP tool `%s`' % tool_name
    return None


def outbound_post(tool_name, tool_input, cwd=None, lookup=remote_url):
    """What this tool call would post outside GitHub, or None."""
    if tool_name.startswith('mcp__'):
        return _mcp(tool_name)
    command = (tool_input or {}).get('command') or ''
    for segment in re.split(r'&&|\|\||[;|\n]', command):
        tokens = _tokens(segment.strip())
        if not tokens:
            continue
        program = tokens[0]
        if program == 'az':
            found = _az(tokens)
        elif program == 'glab':
            found = _glab(tokens)
        elif program in HTTP_TOOLS:
            found = ('a REST call to %s' % FORGE_HOSTS.search(segment).group(0)
                     if FORGE_HOSTS.search(segment) and _http_write(tokens)
                     else None)
        elif program == 'git':
            found = _git_push(tokens, cwd, lookup)
        else:
            found = None
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
        reason = outbound_post(event.get('tool_name') or '',
                               event.get('tool_input') or {},
                               event.get('cwd'))
    except Exception:  # a broken guard must never break the tool call
        return 0
    if reason:
        print(json.dumps(decision(reason)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
