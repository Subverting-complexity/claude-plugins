#!/usr/bin/env python3
"""Block GitHub writes outside the owners this machine allows.

Each person keeps their own list on their own machine, never in a
repository, at ~/.claude/synergy/github-allowlist.json (or the path in
SYNERGY_GITHUB_ALLOWLIST):

    {"account": "AdrienneBosch", "owners": ["Subverting-complexity"]}

With the file present, a write to GitHub (a push, a pull request, an issue, a
comment, a label, a merge, a `gh api` write, a `wf` command that writes, a
GitHub MCP write) is denied outright when its owner is not listed, when the
owner cannot be worked out, or when `gh` is signed in as another account.
Reads are never stopped. Without the file nothing is restricted, so a machine
that has not opted in behaves as before.
"""
import json
import os
import re
import subprocess

from command_parse import (READ_METHODS, flag_value, has_flag, mcp_writes,
                           name_words, push_url, remote_url, walk)

ALLOWLIST_ENV = 'SYNERGY_GITHUB_ALLOWLIST'

# `gh <group> <action>` pairs that change something on GitHub.
GH_WRITES = {
    'pr': {'create', 'merge', 'comment', 'edit', 'close', 'reopen', 'review',
           'ready', 'lock', 'unlock', 'update-branch'},
    'issue': {'create', 'comment', 'edit', 'close', 'reopen', 'delete',
              'transfer', 'lock', 'unlock', 'pin', 'unpin', 'develop'},
    'release': {'create', 'edit', 'delete', 'upload', 'delete-asset'},
    'repo': {'create', 'delete', 'edit', 'fork', 'rename', 'archive',
             'unarchive', 'sync'},
    'label': {'create', 'edit', 'delete', 'clone'},
    'workflow': {'run', 'enable', 'disable'},
    'run': {'rerun', 'cancel', 'delete'},
    'secret': {'set', 'delete', 'remove'},
    'variable': {'set', 'delete'},
    'cache': {'delete'},
    'project': {'create', 'edit', 'delete', 'close', 'copy', 'link', 'unlink',
                'mark-template', 'item-add', 'item-archive', 'item-create',
                'item-delete', 'item-edit', 'field-create', 'field-delete'},
    'gist': {'create', 'edit', 'delete', 'rename'},
}

# `wf` subcommands that only read, and those that only read with a flag.
WF_READS = {'setup', 'candidates', 'config', 'org-capabilities', 'issue-audit',
            'config-audit', 'sibling-pr'}
WF_DRY_RUN = {'unblock', 'claim-reap', 'board-sync', 'issue-apply'}

GH_API_VALUE_FLAGS = {'-X', '--method', '-H', '--header', '-f', '-F',
                      '--field', '--raw-field', '--input', '-q', '--jq', '-t',
                      '--template', '--hostname', '--cache', '-p', '--preview'}

CURRENT = 'the repository in the working directory'
ACCOUNT = 'the signed-in account'


def allowlist_path():
    return os.environ.get(ALLOWLIST_ENV) or os.path.join(
        os.path.expanduser('~'), '.claude', 'synergy', 'github-allowlist.json')


def load_allowlist(path=None):
    """The allowlist, None when this machine has none, or one with `error`."""
    path = path or allowlist_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        owners = data.get('owners')
        if not isinstance(owners, list) or not all(
                isinstance(o, str) for o in owners):
            raise ValueError('"owners" must be a list of names')
        account = data.get('account')
        if account is not None and not isinstance(account, str):
            raise ValueError('"account" must be a name')
    except (OSError, ValueError, AttributeError) as exc:
        return {'path': path, 'error': str(exc), 'owners': [], 'account': None}
    return {'path': path, 'account': account, 'owners': owners}


def gh_hosts_path():
    base = os.environ.get('GH_CONFIG_DIR')
    if not base and os.name == 'nt':
        base = os.path.join(os.environ.get('APPDATA', ''), 'GitHub CLI')
    elif not base:
        base = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.join(
            os.path.expanduser('~'), '.config'), 'gh')
    return os.path.join(base, 'hosts.yml')


def active_account(path=None):
    """The account gh is signed in as on github.com, read from its local
    config so no network call is made. None when it cannot be told, which
    includes a token in the environment, since that overrides the config."""
    if os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN'):
        return None
    try:
        with open(path or gh_hosts_path(), encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    inside, best = False, None
    for line in lines:
        if re.match(r'^\S', line):
            inside = line.strip().rstrip(':').strip('"\'') == 'github.com'
            continue
        m = re.match(r'^(\s+)user:\s*["\']?([^"\'\s]+)', line)
        if inside and m and (best is None or len(m.group(1)) < best[0]):
            best = (len(m.group(1)), m.group(2))
    return best[1] if best else None


def github_owner(url):
    """The owner in a github.com URL, including an SSH host alias such as
    git@github.com-work:owner/repo.git."""
    m = re.match(r'^(?:[a-z][\w+.-]*://)?(?:[^@/\s]+@)?(?:www\.)?'
                 r'github\.com(?:-[\w.-]+)?[:/]+([^/\s]+)/', url or '', re.I)
    return m.group(1) if m else None


def _git(cwd, *args):
    try:
        out = subprocess.run(['git'] + list(args), cwd=cwd or None,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ''
    return out.stdout.strip() if out.returncode == 0 else ''


def repo_owner(cwd):
    """The owner of the GitHub repository `gh` acts on from `cwd`: the remote
    `gh repo set-default` chose, else upstream, github, then origin."""
    names = []
    for line in _git(cwd, 'config', '--get-regexp',
                     r'^remote\..*\.gh-resolved$').splitlines():
        key, _, value = line.partition(' ')
        if value.strip() == 'base':
            names.append(key[len('remote.'):-len('.gh-resolved')])
    for name in names + ['upstream', 'github', 'origin']:
        owner = github_owner(_git(cwd, 'remote', 'get-url', name))
        if owner:
            return owner
    return None


def _spec_owner(spec):
    """The owner in `owner/name`, `github.com/owner/name` or a GitHub URL."""
    owner = github_owner(spec)
    if owner:
        return owner
    parts = (spec or '').strip('/').split('/')
    if len(parts) == 3 and parts[0].lower() == 'github.com':
        return parts[1]
    return parts[0] if len(parts) == 2 and parts[0] else None


def _positionals(toks, value_flags):
    out, skip = [], False
    for token in toks:
        if skip:
            skip = False
        elif token.startswith('-'):
            skip = token in value_flags
        else:
            out.append(token)
    return out


def _graphql_mutation(toks, cwd):
    query, has_input = None, False
    for i, token in enumerate(toks):
        if token == '--input':
            has_input = True
        value = None
        if token in ('-f', '-F', '--field', '--raw-field') and i + 1 < len(toks):
            value = toks[i + 1]
        elif re.match(r'^-[fF]query=', token):
            value = token[2:]
        if value and value.startswith('query='):
            query = value[len('query='):]
    if query is None:
        return has_input
    if query.startswith('@'):
        try:
            with open(os.path.join(cwd or '.', query[1:]), encoding='utf-8') as f:
                query = f.read()
        except OSError:
            return True
    return re.search(r'\bmutation\b', query) is not None


def _gh_api(toks, cwd):
    positionals = _positionals(toks[2:], GH_API_VALUE_FLAGS)
    endpoint = positionals[0] if positionals else ''
    path = endpoint.lstrip('/')
    if path == 'graphql':
        if _graphql_mutation(toks, cwd):
            return CURRENT, 'a GitHub GraphQL mutation'
        return None
    method = flag_value(toks, ['-X', '--method'])
    if method:
        writes = method.upper() not in READ_METHODS
    else:
        writes = has_flag(toks, ['-f', '-F', '--field', '--raw-field',
                                 '--input'])
    if not writes:
        return None
    what = 'a GitHub API write (`gh api %s`)' % endpoint
    m = re.match(r'(?:repos|orgs)/([^/?]+)', path)
    if m:
        return (CURRENT if m.group(1) == '{owner}' else m.group(1)), what
    if re.match(r'(?:user|gists)(?:/|$|\?)', path):
        return ACCOUNT, what
    return None, what


def _gh(toks, cwd):
    group = toks[1] if len(toks) > 1 else ''
    if group == 'api':
        return _gh_api(toks, cwd)
    action = toks[2] if len(toks) > 2 else ''
    if action not in GH_WRITES.get(group, ()):
        return None
    first = toks[3] if len(toks) > 3 and not toks[3].startswith('-') else ''
    what = '`gh %s %s`' % (group, action)
    if group == 'gist':
        return ACCOUNT, what
    if group == 'project':
        owner = flag_value(toks, ['--owner'])
        return (ACCOUNT if owner in (None, '@me') else owner), what
    if group in ('secret', 'variable'):
        org = flag_value(toks, ['--org', '-o'])
        if org:
            return org, what
    if group == 'repo' and action == 'fork':
        return (flag_value(toks, ['--org']) or ACCOUNT), what
    spec = flag_value(toks, ['-R', '--repo'])
    if spec:
        return _spec_owner(spec), what
    if first and github_owner(first):
        return github_owner(first), what
    if group == 'repo' and first and '/' in first:
        return _spec_owner(first), what
    if group == 'repo' and action == 'create':
        return (ACCOUNT if first else None), what
    return CURRENT, what


def _wf(toks):
    for i, token in enumerate(toks):
        if re.search(r'(^|[\\/])wf\.(sh|ps1|py)$', token, re.I):
            rest = toks[i + 1:]
            break
    else:
        return None
    if not rest or rest[0].startswith('-'):
        return None
    sub = rest[0]
    if (sub in WF_READS
            or (sub == 'preflight' and '--fix' not in rest)
            or (sub in WF_DRY_RUN and '--dry-run' in rest)
            or (sub == 'review-next' and '--no-claim' in rest)):
        return None
    spec = flag_value(rest, ['--repo'])
    return (_spec_owner(spec) if spec else CURRENT), '`wf %s`' % sub


def github_writes(tool_name, tool_input, cwd=None, lookup=remote_url):
    """Each GitHub write in this tool call, as (owner, what, cwd). The owner
    is a name, CURRENT, ACCOUNT, or None when it cannot be worked out."""
    tool_input = tool_input or {}
    if tool_name.startswith('mcp__'):
        if 'github' in name_words(tool_name) and mcp_writes(tool_name):
            owner = tool_input.get('owner') or _spec_owner(
                tool_input.get('repo') or tool_input.get('repository') or '')
            return [(owner, 'the MCP tool `%s`' % tool_name, cwd)]
        return []
    writes = []
    for toks, where, _ in walk(tool_input.get('command') or '', cwd):
        if toks[0] == 'gh':
            found = _gh(toks, where)
        elif toks[0] == 'git':
            owner = github_owner(push_url(toks, where, lookup) or '')
            found = (owner, 'a push') if owner else None
        else:
            found = _wf(toks)
        if found:
            writes.append(found + (where,))
    return writes


def github_block(tool_name, tool_input, cwd=None, allowlist=None,
                 account=active_account, owner_of=repo_owner,
                 lookup=remote_url):
    """Why this tool call is blocked, or None when it may go ahead."""
    if allowlist is None:
        return None
    writes = github_writes(tool_name, tool_input, cwd, lookup)
    if not writes:
        return None
    if allowlist.get('error'):
        return ('%s, and the GitHub allowlist at %s could not be read (%s)'
                % (writes[0][1], allowlist['path'], allowlist['error']))
    owners = {o.lower() for o in allowlist['owners']}
    expected = allowlist.get('account')
    signed_in = account()
    for owner, what, where in writes:
        if expected and not signed_in:
            return ('%s, and synergy cannot tell which account gh is signed '
                    'in as (this machine allows only %s)' % (what, expected))
        if expected and signed_in.lower() != expected.lower():
            return ('%s while gh is signed in as %s; this machine allows '
                    'GitHub writes only as %s' % (what, signed_in, expected))
        if owner is ACCOUNT:
            owner = signed_in
        elif owner is CURRENT:
            owner = owner_of(where)
        if not owner:
            return ('%s, and synergy cannot tell which GitHub owner it '
                    'writes to' % what)
        if owner.lower() not in owners:
            return ('%s to %s, which is not on this machine\'s GitHub '
                    'allowlist' % (what, owner))
    return None


def denial(reason, allowlist):
    allowed = ', '.join(allowlist.get('owners') or []) or 'no owner'
    return {
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': (
                'synergy blocked this: it is %s. This machine allows GitHub '
                'writes only to %s (set in %s). Do not look for another way '
                'to make this write; tell the person what was blocked.'
                % (reason, allowed, allowlist['path'])),
        }
    }
