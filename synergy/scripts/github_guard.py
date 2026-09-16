#!/usr/bin/env python3
"""Block GitHub writes outside the owners this machine allows.

Each person keeps their own list on their own machine, never in a
repository, at ~/.claude/synergy/github-allowlist.json (or the path in
SYNERGY_GITHUB_ALLOWLIST):

    {"account": "AdrienneBosch", "owners": ["Subverting-complexity"]}

With the file present, a write to GitHub (a push, a pull request, an issue, a
comment, a label, a merge, a `gh api`, `hub`, `curl` or `Invoke-RestMethod`
write, a `wf` command that writes, a GitHub MCP write) is denied outright when
its owner is not listed, when the owner cannot be worked out, or when `gh` is
signed in as another account. Reads are never stopped. Without the file
nothing is restricted, so a machine that has not opted in behaves as before.

Owners are worked out locally, from the command, the git remotes and
ClaudeProject.md. The one network call is a GraphQL read made only for a
GraphQL write that names node IDs, to learn which owner each ID belongs to.
"""
import json
import os
import re
import subprocess

from command_parse import (HTTP_TOOLS, READ_METHODS, WRITE_VERBS,
                           closing_paren, expand, flag_value, has_flag,
                           http_data, http_writes, mcp_writes, name_words,
                           push_url, remote_url, tokens, walk)

ALLOWLIST_ENV = 'SYNERGY_GITHUB_ALLOWLIST'

# `gh <group> <action>` pairs that change something on GitHub.
GH_WRITES = {
    'pr': {'create', 'merge', 'comment', 'edit', 'close', 'reopen', 'review',
           'ready', 'lock', 'unlock', 'update-branch', 'revert'},
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
    'ssh-key': {'add', 'delete'},
    'gpg-key': {'add', 'delete'},
}
# `gh <group> <sub> <action>` writes.
GH_NESTED = {('repo', 'deploy-key'): {'add', 'delete'},
             ('repo', 'autolink'): {'create', 'delete'}}
ACCOUNT_GROUPS = {'gist', 'ssh-key', 'gpg-key'}
# gh's own aliases for write actions: `gh pr new` is `gh pr create`.
GH_ALIASES = {'new': 'create', 'remove': 'delete'}
# What `gh repo view -q` may print for its output to be the repository's own.
VIEW_OUTPUTS = {'.nameWithOwner', '.owner.login', '.url'}

# `wf` subcommands that only read, and those that only read with a flag.
WF_READS = {'setup', 'candidates', 'config', 'org-capabilities', 'issue-audit',
            'config-audit', 'sibling-pr'}
WF_DRY_RUN = {'unblock', 'claim-reap', 'board-sync', 'issue-apply'}

GH_API_VALUE_FLAGS = {'-X', '--method', '-H', '--header', '-f', '-F',
                      '--field', '--raw-field', '--input', '-q', '--jq', '-t',
                      '--template', '--hostname', '--cache', '-p', '--preview'}
FIELD_FLAGS = ('-f', '-F', '--field', '--raw-field')

# A GitHub node ID: the current form (I_kwDO..., PVT_kwDO..., U_kgAB) or the
# legacy base64 one (MDU6SXNzdWUx...).
NODE_ID = re.compile(
    r'^(?:[A-Z]{1,8}_[kl][A-Za-z0-9_-]{3,}|MD[A-Za-z0-9+/]{8,}={0,2})$')
NODE_OWNER_QUERY = (
    'query($ids: [ID!]!) { nodes(ids: $ids) { '
    '... on RepositoryOwner { login } '
    '... on Repository { repoOwner: owner { login } } '
    '... on RepositoryNode { repository { owner { login } } } '
    '... on Label { repository { owner { login } } } '
    '... on Milestone { repository { owner { login } } } '
    '... on Ref { repository { owner { login } } } '
    '... on Commit { repository { owner { login } } } '
    '... on ProjectV2 { projectOwner: owner { ... on RepositoryOwner { login } } } '
    '... on ProjectV2Item { project { projectOwner: owner { ... on RepositoryOwner { login } } } } '
    '... on ProjectV2FieldCommon { project { projectOwner: owner { ... on RepositoryOwner { login } } } } '
    '... on Team { organization { login } } } }')

CURRENT = 'the repository in the working directory'
ACCOUNT = 'the signed-in account'
PROJECT = 'the org named in ClaudeProject.md'
NODES = 'nodes'
# What an owner-extraction step returns to fall through to the next step.
NEXT = object()


def allowlist_path():
    return os.environ.get(ALLOWLIST_ENV) or os.path.join(
        os.path.expanduser('~'), '.claude', 'synergy', 'github-allowlist.json')


def load_allowlist(path=None):
    """The allowlist, None when this machine has none, or one with `error`.
    A byte-order mark, which Windows PowerShell 5 writes, is allowed."""
    path = path or allowlist_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8-sig') as f:
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
        with open(path or gh_hosts_path(), encoding='utf-8-sig') as f:
            lines = f.read().splitlines()
    except (OSError, ValueError):
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


def _github_host(name):
    return bool(re.match(r'^(?:(?:www|ssh)\.)?github\.com(?:-[\w.-]+)?$'
                         r'|^[\w-]*github[\w-]*$', name, re.I))


def ssh_hostname(alias):
    """The host an SSH alias from ~/.ssh/config connects to, or None."""
    try:
        out = subprocess.run(['ssh', '-G', alias], capture_output=True,
                             text=True, encoding='utf-8', errors='replace', timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'^hostname\s+(\S+)', out.stdout or '', re.M)
    return m.group(1) if m else None


def github_owner(url, ssh_host=None):
    """The owner in a GitHub URL: https, scp-style and ssh:// forms, including
    ssh.github.com:443 and an SSH alias such as git@github-work:owner/repo.git.
    `ssh_host` resolves an alias whose name does not say github."""
    if not isinstance(url, str):
        return None
    m = re.match(r'^(?:[a-z][\w+.-]*://)?(?:[^@/\s]+@)?([\w.-]+?)(?::\d+)?'
                 r'[:/]+([^/\s:]+)/', url, re.I)
    if not m:
        return None
    name = m.group(1)
    if not _github_host(name) and ssh_host and '.' not in name:
        name = ssh_host(name) or ''
    return m.group(2) if _github_host(name) else None


def _git(cwd, *args):
    try:
        out = subprocess.run(['git'] + list(args), cwd=cwd or None,
                             capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ''
    return (out.stdout or '').strip() if out.returncode == 0 else ''


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
        owner = github_owner(_git(cwd, 'remote', 'get-url', name), ssh_hostname)
        if owner:
            return owner
    return None


def project_owner(cwd):
    """The org ClaudeProject.md names, which is where `wf` writes."""
    root = _git(cwd, 'rev-parse', '--show-toplevel')
    if not root:
        return None
    try:
        with open(os.path.join(root, 'ClaudeProject.md'), encoding='utf-8-sig') as f:
            text = f.read()
    except (OSError, ValueError):
        return None
    m = re.search(r'^\|\s*org\s*\|\s*`?([^`|\s]+)`?\s*\|', text, re.M | re.I)
    return m.group(1) if m else None


def node_owners(ids):
    """{id: owner login or None} for GitHub node IDs, from one GraphQL read."""
    args = ['gh', 'api', 'graphql', '-f', 'query=' + NODE_OWNER_QUERY]
    for node in ids:
        args += ['-f', 'ids[]=' + node]
    try:
        out = subprocess.run(args, capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=15)
        nodes = (json.loads(out.stdout or '{}').get('data') or {}).get('nodes')
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        nodes = None
    nodes = nodes if isinstance(nodes, list) else []
    return {node: _login(item) for node, item in
            zip(ids, nodes + [None] * (len(ids) - len(nodes)))}


def _login(item):
    for path in (('login',), ('repoOwner', 'login'),
                 ('repository', 'owner', 'login'),
                 ('projectOwner', 'login'),
                 ('project', 'projectOwner', 'login'),
                 ('organization', 'login')):
        value = item
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str):
            return value
    return None


def _text(value):
    return value if isinstance(value, str) else None


def _spec_owner(spec):
    """The owner in `owner/name`, `github.com/owner/name` or a GitHub URL."""
    if not isinstance(spec, str):
        return None
    owner = github_owner(spec)
    if owner:
        return owner
    parts = spec.strip('/').split('/')
    if len(parts) == 3 and parts[0].lower() == 'github.com':
        return parts[1]
    return parts[0] if len(parts) == 2 and parts[0] else None


def _substitutions(command):
    """The text of every `$( )` in `command`, nested ones included."""
    found, start = [], command.find('$(')
    while start != -1:
        end = closing_paren(command, start + 1, '\\')
        found.append(command[start + 2:end])
        start = command.find('$(', start + 2)
    return found


def _views_current(sub, env, ctx):
    """Whether a `$( )` prints the current repository: `gh repo view` with no
    repository named, no GH_REPO to name one, and output that is only its
    name, owner or URL."""
    if re.search(r'GH_REPO', sub, re.I):
        return False
    toks = tokens(sub.strip())
    if toks[:3] != ['gh', 'repo', 'view']:
        return False
    if env.get('gh_repo') or ctx['environ'].get('GH_REPO'):
        return False
    rest = toks[3:]
    for flag, value in zip(rest[::2], rest[1::2] + [None] * (len(rest) % 2)):
        if flag in ('-q', '--jq') and value in VIEW_OUTPUTS:
            continue
        if flag == '--json' and value and re.match(r'^[\w,]+$', value):
            continue
        return False
    return True


def _unresolved(text, env, ctx):
    """The owner behind a variable the command never set to text: the current
    repository when it came from `gh repo view` of that repository, otherwise
    unknown."""
    m = re.search(r'\$\{?(?:env:)?(\w+)', text)
    if not m:
        return None
    command = ctx['command']
    if m.group(1).startswith('__sub'):
        subs = _substitutions(command)
        return CURRENT if subs and all(
            _views_current(s, env, ctx) for s in subs) else None
    name = re.escape(m.group(1))
    assigned = list(re.finditer(r'(?<![\w$])\$?%s\s*=\s*["\']?\$\(' % name,
                                command, re.I))
    if len(assigned) != 1:
        return None
    start = assigned[0].end() - 1
    end = closing_paren(command, start, '\\')
    if not _views_current(command[start + 1:end], env, ctx):
        return None
    # Any other mention of the variable, such as `read slug`, could change it.
    flags = re.I if assigned[0].group().startswith('$') else 0
    rest = command[:assigned[0].start()] + command[end + 1:]
    rest = re.sub(r'\$(?:\{(?:env:)?%s\}|(?:env:)?%s(?!\w))' % (name, name),
                  '', rest, flags=flags)
    if re.search(r'(?<![\w$])%s(?!\w)' % name, rest, flags):
        return None
    return CURRENT


def _owner_of_spec(spec, env, ctx):
    spec = expand(spec, env, ctx['environ'])
    return _unresolved(spec, env, ctx) if '$' in spec else _spec_owner(spec)


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


def _gh_words(toks):
    """The group, action and first argument of a `gh` command, skipping a
    `-R`/`--repo` given before or between them."""
    words, i = [], 1
    while i < len(toks) and len(words) < 3:
        token = toks[i]
        if token in ('-R', '--repo'):
            i += 2
            continue
        if token.startswith('-'):
            if len(words) >= 2:
                break
            i += 1
            continue
        words.append(token)
        i += 1
    return words


def _nodes(*ids):
    ids = tuple(i for i in ids if i)
    if ids and all(NODE_ID.match(i) for i in ids):
        return (NODES, ids)
    return None


def _node_ids(*texts):
    found = set()
    for text in texts:
        for word in re.findall(r'[A-Za-z0-9_+/=-]{6,}', text or ''):
            if NODE_ID.match(word):
                found.add(word)
    return sorted(found)


def _graphql(query, blobs, what):
    """The owner a GraphQL call writes to, None when it only reads."""
    if not re.search(r'\bmutation\b', query):
        return None
    ids = _node_ids(query, *blobs)
    return (NODES, tuple(ids)) if ids else CURRENT


def _api_fields(toks):
    values = []
    for i, token in enumerate(toks):
        if token in FIELD_FLAGS and i + 1 < len(toks):
            values.append(toks[i + 1])
        elif token.startswith(('--field=', '--raw-field=')):
            values.append(token.split('=', 1)[1])
        elif re.match(r'^-[fF].', token):
            values.append(token[2:])
    return values


def _reads_file(toks):
    """Whether a `-F`/`--field` value other than the query is read from a file
    (`key=@path`); `-f` values are always literal."""
    for i, token in enumerate(toks):
        if token in ('-F', '--field') and i + 1 < len(toks):
            value = toks[i + 1]
        elif token.startswith('--field='):
            value = token.split('=', 1)[1]
        elif re.match(r'^-F.', token):
            value = token[2:]
        else:
            continue
        key, _, val = value.partition('=')
        if key != 'query' and val.startswith('@'):
            return True
    return False


def _gh_graphql(toks, cwd, env, ctx, what):
    query, blobs = None, []
    for value in _api_fields(toks):
        key, _, val = value.partition('=')
        if key == 'query':
            query = val
        else:
            blobs.append(expand(val, env, ctx['environ']))
    bare = r'^\$\{?(?:env:)?\w+\}?$'
    if query and re.match(bare, query):
        query = expand(query, env, ctx['environ'])
        if re.match(bare, query):
            return [(None, 'a GitHub GraphQL call whose query synergy cannot read')]
    source = flag_value(toks, ['--input'], False)
    if source:
        try:
            if source == '-':
                raise OSError('read from standard input')
            with open(os.path.join(cwd or '.', source), encoding='utf-8-sig') as f:
                body = json.load(f)
            query = body.get('query') or ''
            blobs.append(json.dumps(body.get('variables') or {}))
        except (OSError, ValueError, AttributeError):
            return [(None, 'a GitHub GraphQL call whose body synergy cannot read')]
    if query is None:
        return []
    if query.startswith('@'):
        try:
            with open(os.path.join(cwd or '.', query[1:]), encoding='utf-8-sig') as f:
                query = f.read()
        except (OSError, ValueError):
            return [(None, 'a GitHub GraphQL call whose query synergy cannot read')]
    owner = _graphql(query, blobs, what)
    if owner is None:
        return []
    declared = set()
    for signature in re.findall(r'\bmutation\b[^({]*\(([^)]*)\)', query):
        declared.update(re.findall(r'\$(\w+)\s*:', signature))
    used = set(re.findall(r'\$\{?(\w+)', query))
    shell = {k.lower() for k in env} | {k.lower() for k in ctx['environ']}
    if (any('$' in blob for blob in blobs) or _reads_file(toks)
            or used - declared or {u.lower() for u in used} & shell):
        return [(None, 'a GitHub GraphQL mutation whose values synergy '
                       'cannot read')]
    return [(owner, what)]


def _rest_owner(path, env, ctx, placeholder=CURRENT):
    m = re.match(r'(?:repos|orgs)/([^/?]+)', path)
    if m:
        owner = m.group(1)
        if owner in ('{owner}', ':owner'):
            return placeholder
        return _unresolved(owner, env, ctx) if '$' in owner else owner
    if re.match(r'(?:user|gists)(?:/|$|\?)', path):
        return ACCOUNT
    return None


def _gh_api(toks, cwd, env, ctx):
    start = toks.index('api') + 1 if 'api' in toks else 2
    positionals = _positionals(toks[start:], GH_API_VALUE_FLAGS)
    endpoint = expand(positionals[0], env, ctx['environ']) if positionals else ''
    path = re.sub(r'^https?://api\.github\.com/', '', endpoint, flags=re.I)
    path = path.lstrip('/')
    # gh fills {owner} and :owner, and picks the repository, from GH_REPO.
    override = env.get('gh_repo') or ctx['environ'].get('GH_REPO')
    placeholder = _owner_of_spec(override, env, ctx) if override else CURRENT
    if path.split('?')[0] == 'graphql':
        return [(placeholder if owner is CURRENT else owner, what)
                for owner, what in _gh_graphql(toks, cwd, env, ctx,
                                               'a GitHub GraphQL mutation')]
    method = flag_value(toks, ['-X', '--method'], False)
    if method:
        writes = method.upper() not in READ_METHODS
    else:
        writes = bool(_api_fields(toks)) or has_flag(toks, ['--input'])
    if not writes:
        return []
    return [(_rest_owner(path, env, ctx, placeholder),
             'a GitHub API write (`gh api %s`)' % endpoint)]


def _constant(call, owner):
    return owner


def _flag(call, names):
    return flag_value(call['toks'], names, False) or NEXT


def _switch(call, names, owner):
    return owner if has_flag(call['toks'], names) else NEXT


def _node_flag(call, names):
    return _nodes(flag_value(call['toks'], names, False))


def _owner_flag(call, names):
    owner = flag_value(call['toks'], names, False)
    return ACCOUNT if owner in (None, '@me') else owner


def _spec_flag(call, names):
    spec = flag_value(call['toks'], names, False)
    return _owner_of_spec(spec, call['env'], call['ctx']) if spec else NEXT


def _url_arg(call):
    return github_owner(call['first']) if (
        call['first'] and github_owner(call['first'])) else NEXT


def _positional(call, index):
    args = _positionals(call['toks'][1:], {'-R', '--repo'})
    return (_owner_of_spec(args[index], call['env'], call['ctx'])
            if len(args) > index else NEXT)


def _env_repo(call):
    spec = call['env'].get('gh_repo') or call['ctx']['environ'].get('GH_REPO')
    return _owner_of_spec(spec, call['env'], call['ctx']) if spec else NEXT


# The owner-extraction strategies an OWNER_RULES row may name. Each takes the
# call and the row's arguments, and returns an owner, or NEXT to fall through
# to the row's next step.
STRATEGIES = {
    'constant': _constant,     # always this owner
    'flag': _flag,             # the flag's value, used as the owner as given
    'switch': _switch,         # this owner when the flag is present
    'node-flag': _node_flag,   # the owner of the node ID the flag names
    'owner-flag': _owner_flag,  # --owner, where absent or @me is the account
    'spec-flag': _spec_flag,   # the owner of the owner/repo the flag names
    'url-arg': _url_arg,       # the owner in a GitHub URL given as first word
    'env-repo': _env_repo,     # the owner of the repository GH_REPO names
    'positional': _positional,  # the owner of the owner/repo at that index
}
# A step written ('also', strategy, args...) adds its owner and carries on,
# for a command that writes to two owners.
ALSO = 'also'

# Where gh acts when nothing more specific names an owner: -R/--repo, a
# GitHub URL argument, GH_REPO, then the repository in the working directory.
IN_REPO = (('spec-flag', ('-R', '--repo')), ('url-arg',), ('env-repo',),
           ('constant', CURRENT))
# An org or user secret or variable is written to that owner, not a repo.
SETTINGS = (('flag', ('--org', '-o')), ('switch', ('--user', '-u'), ACCOUNT)) + IN_REPO

# How each `gh` write's owner is worked out, most specific key first:
# (group, action), then group. A row is a sequence of (strategy, args...)
# steps tried in order until one returns an owner. Adding a guard rule for a
# new subcommand is a GH_WRITES entry plus, when it needs one, a row here.
OWNER_RULES = {
    ('project', 'item-edit'): (('node-flag', ('--project-id',)),),
    ('project', 'field-delete'): (('node-flag', ('--id',)),),
    'project': (('owner-flag', ('--owner',)),),
    'secret': SETTINGS,
    'variable': SETTINGS,
    ('repo', 'fork'): (('flag', ('--org',)), ('constant', ACCOUNT)),
    # `gh issue transfer <issue> <destination>` writes to both repositories:
    # args[3] counts `gh issue transfer` itself, so it is the destination.
    ('issue', 'transfer'): (('also', 'positional', 3),) + IN_REPO,
}


def _rule_owners(rule, call):
    """The owners one OWNER_RULES row yields, in order."""
    owners = []
    for step in rule:
        also = step[0] == ALSO
        step = step[1:] if also else step
        owner = STRATEGIES[step[0]](call, *step[1:])
        if owner is NEXT:
            continue
        owners.append(owner)
        if not also:
            return owners
    raise ValueError('an OWNER_RULES row must end in a step that always decides')


def _gh(toks, cwd, env, ctx):
    words = _gh_words(toks)
    group = words[0] if words else ''
    if group == 'api':
        return _gh_api(toks, cwd, env, ctx)
    action = GH_ALIASES.get(words[1], words[1]) if len(words) > 1 else ''
    first = words[2] if len(words) > 2 else ''
    nested = GH_NESTED.get((group, action))
    if nested is not None:
        first = GH_ALIASES.get(first, first)
        if first not in nested:
            return []
        what, first = '`gh %s %s %s`' % (group, action, first), ''
    elif action in GH_WRITES.get(group, ()):
        what = '`gh %s %s`' % (group, action)
    else:
        return []
    if group in ACCOUNT_GROUPS:
        return [(ACCOUNT, what)]
    rule = OWNER_RULES.get((group, action)) or OWNER_RULES.get(group)
    if rule:
        call = {'toks': toks, 'first': first, 'env': env, 'ctx': ctx}
        return [(owner, what) for owner in _rule_owners(rule, call)]
    writes = []
    spec = flag_value(toks, ['-R', '--repo'], False)
    if spec:
        return writes + [(_owner_of_spec(spec, env, ctx), what)]
    if first and github_owner(first):
        return writes + [(github_owner(first), what)]
    if group == 'repo' and first and '/' in first:
        return writes + [(_owner_of_spec(first, env, ctx), what)]
    if group == 'repo' and action == 'create':
        return writes + [(ACCOUNT if first else None, what)]
    spec = env.get('gh_repo') or ctx['environ'].get('GH_REPO')
    if spec:
        return writes + [(_owner_of_spec(spec, env, ctx), what)]
    return writes + [(CURRENT, what)]


def _hub(toks, cwd, env, ctx, lookup, ssh_host):
    words = [t for t in toks[1:] if not t.startswith('-')]
    sub = words[0] if words else ''
    if sub == 'push':
        return _push(['git'] + toks[1:], cwd, env, lookup, ssh_host)
    if sub == 'api':
        return _gh_api(['gh'] + toks[1:], cwd, env, ctx)
    what = '`hub %s`' % sub
    if sub in ('pull-request', 'merge', 'sync'):
        return [(CURRENT, what)]
    if sub == 'fork':
        return [(flag_value(toks, ['--org'], False) or ACCOUNT, what)]
    if sub in ('create', 'delete'):
        spec = words[1] if len(words) > 1 else ''
        return [(_owner_of_spec(spec, env, ctx) if '/' in spec else ACCOUNT, what)]
    if (sub in ('issue', 'release', 'gist') and len(words) > 1
            and words[1] in WRITE_VERBS):
        return [(ACCOUNT if sub == 'gist' else CURRENT,
                 '`hub %s %s`' % (sub, words[1]))]
    return []


def _http(toks, env, ctx):
    text = expand(' '.join(toks), env, ctx['environ'])
    m = re.search(r'https?://(?:api|uploads)\.github\.com/?([^\s\'"]*)', text,
                  re.I)
    if not m or not http_writes(toks):
        return []
    what = 'a GitHub API write (`%s`)' % toks[0]
    path = m.group(1)
    if path.split('?')[0].rstrip('/') == 'graphql':
        data = [expand(d, env, ctx['environ']) for d in http_data(toks)]
        if not data or any(d.startswith('@') or re.match(r'^\$[\w:]+$', d)
                           for d in data):
            return [(None, what)]
        owner = _graphql(' '.join(data), [], what)
        if owner is None:
            return []
        return [(None if owner is CURRENT else owner, what)]
    owner = _rest_owner(path, env, ctx)
    return [(None if owner is CURRENT else owner, what)]


def _push(toks, cwd, env, lookup, ssh_host):
    url = push_url(toks, cwd, lookup, env)
    if url is None:
        return []
    if not url or '$' in url:
        return [(None, 'a push whose destination synergy cannot work out')]
    owner = github_owner(url, ssh_host)
    return [(owner, 'a push')] if owner else []


def _wf(toks, env, ctx):
    for i, token in enumerate(toks):
        if re.search(r'(^|[\\/])wf\.(sh|ps1|py)$', token, re.I):
            rest = toks[i + 1:]
            break
    else:
        return []
    if not rest or rest[0].startswith('-'):
        return []
    sub = rest[0]
    if (sub in WF_READS
            or (sub == 'preflight' and '--fix' not in rest)
            or (sub in WF_DRY_RUN and '--dry-run' in rest)
            or (sub == 'review-next' and '--no-claim' in rest)):
        return []
    what = '`wf %s`' % sub
    spec = flag_value(rest, ['--repo'], False)
    if spec:
        return [(_owner_of_spec(spec, env, ctx), what)]
    # wf writes to the org and repository ClaudeProject.md names, and pushes
    # its claim refs to the git remote, so both have to be allowed.
    return [(PROJECT, what), (CURRENT, what)]


def _mcp(tool_name, tool_input):
    if not mcp_writes(tool_name):
        return []
    keys = set(tool_input)
    if ('github' not in tool_name.lower()
            and not ('owner' in keys and keys & {'repo', 'repository'})):
        return []
    words = name_words('__'.join(tool_name.split('__')[2:]))
    what = 'the MCP tool `%s`' % tool_name
    if 'fork' in words or ('create' in words and keys.isdisjoint({'owner'})
                           and ('repository' in words or 'repo' in words)):
        for key in ('organization', 'org'):
            if key in tool_input:
                return [(_text(tool_input[key]), what)]
        return [(ACCOUNT, what)]
    if 'gist' in words:
        return [(ACCOUNT, what)]
    if 'owner' in tool_input:
        return [(_text(tool_input['owner']), what)]
    return [(_spec_owner(tool_input.get('repo') or tool_input.get('repository')),
             what)]


def github_writes(tool_name, tool_input, cwd=None, lookup=remote_url,
                  ssh_host=None, environ=None):
    """Each GitHub write in this tool call, as (owner, what, cwd). The owner
    is a name, CURRENT, ACCOUNT, PROJECT, (NODES, ids), or None when it
    cannot be worked out."""
    tool_input = {} if tool_input is None else tool_input
    if tool_name.startswith('mcp__'):
        return [w + (cwd,) for w in _mcp(tool_name, tool_input)]
    command = tool_input.get('command') or ''
    ctx = {'command': command, 'environ': {} if environ is None else environ}
    writes = []
    for toks, where, env in walk(command, cwd, tool_name == 'PowerShell'):
        head = toks[0]
        if head == 'gh':
            found = _gh(toks, where, env, ctx)
        elif head == 'git':
            found = _push(toks, where, env, lookup, ssh_host)
        elif head == 'hub':
            found = _hub(toks, where, env, ctx, lookup, ssh_host)
        elif head in HTTP_TOOLS:
            found = _http(toks, env, ctx)
        else:
            found = _wf(toks, env, ctx)
        writes.extend(w + (where,) for w in found)
    return writes


def github_block(tool_name, tool_input, cwd=None, allowlist=None,
                 account=active_account, owner_of=repo_owner,
                 lookup=remote_url, project_of=project_owner,
                 nodes=node_owners, ssh_host=ssh_hostname, environ=None):
    """Why this tool call is blocked, or None when it may go ahead."""
    if allowlist is None:
        return None
    writes = github_writes(tool_name, tool_input, cwd, lookup, ssh_host,
                           os.environ if environ is None else environ)
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
            names = [signed_in]
        elif owner is CURRENT:
            names = [owner_of(where)]
        elif owner is PROJECT:
            names = [project_of(where) or owner_of(where)]
        elif isinstance(owner, tuple):
            resolved = nodes(list(owner[1]))
            names = [resolved.get(node) for node in owner[1]]
        else:
            names = [owner]
        for name in names:
            if not name:
                return ('%s, and synergy cannot tell which GitHub owner it '
                        'writes to' % what)
            if name.lower() not in owners:
                return ('%s to %s, which is not on this machine\'s GitHub '
                        'allowlist' % (what, name))
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
