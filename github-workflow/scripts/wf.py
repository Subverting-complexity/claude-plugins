#!/usr/bin/env python3
"""
wf — programmatic front door to the github-workflow selection/claim machinery.

Replaces the multi-step "read markdown, fire a dozen gh calls, reason about
the result" dance with a single process that does the whole mechanical job and
hands back one already-claimed work item as JSON. The decision rules live in
`wf_core.py` (pure, offline-testable); this file is the I/O shell that talks to
`gh` and `git`.

First cut implements the story picker:

    wf pick [--mode story] [--checkout]   # claim the next story, optionally branch
    wf config                             # emit .claude/wf-config.json from ClaudeProject.md
    wf org-capabilities [--refresh]       # resolve the org's issue types + issue fields
    wf issue-apply <spec.json>            # create/update fully classified issues

Contract:
  - A single JSON object is written to **stdout**; all human diagnostics go to
    **stderr**. A caller can parse stdout without stripping prose.
  - Every run's JSON carries a `status` field; the process exit code mirrors it:
      0  status=ok            an item was claimed (and checked out, if asked)
      10 status=no-candidates the ready pool was empty
      11 status=all-blocked   every candidate was blocked / already resolved
      20 status=error         environment/auth problem (not in a repo, no gh, …)
      21 status=no-capabilities an org that resolves but reports neither issue
                              types nor issue fields — a broken or under-scoped
                              token looks like this, an unconfigured org does not
      22 status=spec-invalid  the spec was refused before anything was written
      23 status=verify-failed a write was accepted but the read-back disagrees
      24 status=partial       some entries landed and some did not
      30 status=unsupported   this path isn't in the CLI yet — caller should
                              fall back to the inline skill procedure
  - Mutations to the *winning* issue (claim, assign, status-in-progress) are
    silent; mutations to *other* issues (marking blocked, closing resolved) are
    always reported back in the `side_effects` array.

Selection covers `--mode story` plus `--mode feature` / `--mode maintenance`
under all four ready-gates (`label`, `none`, `board-column`, `both`), on
both label-typed and type-capable orgs. On a type-capable org,
feature/maintenance filter by the native `issueType` field via a single
GraphQL query instead of the `type-*` label; if the query fails, wf
falls back to label filtering gracefully. See
github-workflow/templates/story-selection.md.
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wf_core  # noqa: E402

EXIT_OK = 0
EXIT_NO_CANDIDATES = 10
EXIT_ALL_BLOCKED = 11
EXIT_ENV = 20
EXIT_CAPABILITY = 21
EXIT_SPEC = 22
EXIT_VERIFY = 23
EXIT_PARTIAL = 24
EXIT_GAPS = 25
EXIT_UNSUPPORTED = 30
EXIT_USAGE = 2


# ── small I/O helpers ────────────────────────────────────────────────────────

def eprint(*args):
    print(*args, file=sys.stderr)


def emit(status, exit_code, **fields):
    """Write the single stdout JSON object and exit with the matching code."""
    payload = {'status': status}
    payload.update(fields)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write('\n')
    sys.exit(exit_code)


def run(args, input_text=None):
    """Run a subprocess, capturing text output. Returns (code, stdout, stderr).

    Decoding is pinned to UTF-8 with ``errors='replace'`` rather than the
    platform locale codec. ``gh`` emits UTF-8 (issue bodies routinely carry
    smart quotes, em dashes, emoji), but on Windows ``text=True`` defaults to
    cp1252, whose reader thread dies with ``UnicodeDecodeError`` on the first
    byte it can't map — leaving ``stdout`` as ``None`` and surfacing only a
    downstream ``NoneType`` error. Pinning the codec keeps the picker working
    on any locale; ``errors='replace'`` degrades stray bytes to U+FFFD instead
    of crashing.
    """
    try:
        proc = subprocess.run(
            args, input=input_text, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
        )
    except FileNotFoundError:
        return 127, '', '%s: not found' % args[0]
    return proc.returncode, proc.stdout, proc.stderr


def gh_json(args):
    """Run `gh <args>` expecting JSON on stdout. Returns (ok, parsed, stderr)."""
    code, out, err = run(['gh'] + args)
    if code != 0:
        return False, None, (err or '').strip()
    out = out or ''
    try:
        return True, json.loads(out) if out.strip() else None, ''
    except json.JSONDecodeError as exc:
        return False, None, 'could not parse gh JSON: %s' % exc


def _graphql_args(query, fields):
    """Build the `gh api graphql` argv, typing each field by its Python type.

    Each field reaches GitHub as the matching GraphQL scalar:

      - ``bool`` → ``-F key=true/false`` (typed JSON boolean → ``Boolean!``)
      - ``int``  → ``-F key=123`` (typed JSON number → ``Int!``)
      - other    → ``-f key=value`` (raw string → ``String!`` / ``ID!``)

    The type split matters: ``-F`` coerces any all-digit value to an int, so an
    ``ID!``/``String!`` variable whose value is digit-only — e.g. a numeric
    single-select option id like ``98236657`` (the board's Done column) — would
    arrive as an Int and GitHub rejects it with *"Variable $o of type String!
    was provided invalid value"*. Routing strings through ``-f`` keeps digit-only
    ids as strings, while genuine ``Int!`` args (Python ints, e.g. an issue
    ``number``) still go through ``-F``. ``bool`` is checked before ``int``
    because ``bool`` is an ``int`` subclass.
    """
    args = ['gh', 'api', 'graphql', '-f', 'query=%s' % query]
    for key, value in fields.items():
        if isinstance(value, bool):
            args += ['-F', '%s=%s' % (key, 'true' if value else 'false')]
        elif isinstance(value, int):
            args += ['-F', '%s=%d' % (key, value)]
        else:
            args += ['-f', '%s=%s' % (key, value)]
    return args


def gh_graphql(query, **fields):
    """Run a GraphQL query/mutation via `gh api graphql`. Returns (ok, data, err).

    Fields are typed by Python type via `_graphql_args` so digit-only ID/String
    values are not coerced to ints (see that helper for the full rationale).
    """
    args = _graphql_args(query, fields)
    code, out, err = run(args)
    if code != 0:
        return False, None, err.strip()
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError as exc:
        return False, None, 'could not parse GraphQL JSON: %s' % exc
    if parsed.get('errors'):
        return False, None, json.dumps(parsed['errors'])
    return True, parsed.get('data'), ''


# ── environment + config ─────────────────────────────────────────────────────

def repo_root():
    code, out, _ = run(['git', 'rev-parse', '--show-toplevel'])
    if code == 0 and out.strip():
        return out.strip()
    return os.getcwd()


def check_environment():
    """Return an error string if the environment can't support a claim, else None."""
    code, _, _ = run(['git', 'rev-parse', '--is-inside-work-tree'])
    if code != 0:
        return 'not inside a git work tree'
    code, _, err = run(['gh', 'auth', 'status'])
    if code != 0:
        return 'gh not available or not authenticated (%s)' % (err.strip() or 'run `gh auth login`')
    return None


def _rows(block):
    """Yield cleaned cells for each markdown table row in a text block."""
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip().strip('`').strip() for c in line.strip('|').split('|')]
        # skip header separators like |---|---|
        if all(set(c) <= set('-: ') for c in cells):
            continue
        yield cells


def _section(text, heading):
    """Return a heading's body, up to the next heading of the same or higher level.

    Level-aware so a `## Label Map` section keeps its `### Priority`/`### Type`
    sub-tables instead of ending at the first deeper heading.

    A trailing parenthetical qualifier on the heading is tolerated, so the
    template's `## Project Board (optional)` / `## Reference Docs (optional)`
    authoring hint still resolves the section — without it the board block
    parses empty and a configured board is silently read as "no board".
    """
    m = re.search(r'^(#{1,6})\s*%s\s*(?:\(.*\))?\s*$' % re.escape(heading), text,
                  re.IGNORECASE | re.MULTILINE)
    if not m:
        return ''
    rest = text[m.end():]
    stop = re.search(r'^#{1,%d}\s' % len(m.group(1)), rest, re.MULTILINE)
    return rest[:stop.start()] if stop else rest


def parse_claude_project(text):
    """Parse ClaudeProject.md into the structured config the CLI needs.

    Tolerant by design — this is the *fallback* path. The fast path is the
    JSON cache emitted by `wf config`. Returns a dict; missing pieces default
    to sensible values so a partial config still drives the common case.
    """
    cfg = {
        'org': None, 'repo': None, 'default_branch': 'main',
        'branch_convention': 'feature/{number}/{short-desc}',
        'labels': {}, 'review_labels': {}, 'fields': {}, 'ready_gate': 'label',
        'agent_gating': 'disabled', 'type_capable': False,
        'board': {'project_node_id': None, 'project_title': None,
                  'status_field_name': 'Status', 'status_field_id': None,
                  'start_date_field_id': None, 'columns': {}},
    }

    for cells in _rows(_section(text, 'Identity')):
        if len(cells) >= 2:
            key, val = cells[0].lower(), cells[1]
            if key == 'org':
                cfg['org'] = val
            elif key == 'repo':
                cfg['repo'] = val
            elif key == 'default-branch':
                cfg['default_branch'] = val

    conv = _section(text, 'Branch Convention')
    m = re.search(r'(\S*\{number\}\S*)', conv)
    if m:
        # The token may come from the backtick-wrapped `Example:` line when the
        # fenced pattern block was left unfilled — strip those backticks so they
        # never leak into a branch name. (Unrecognised slug placeholders are
        # normalised later by wf_core.branch_name.)
        cfg['branch_convention'] = m.group(1).strip('`')

    label_block = _section(text, 'Label Map')
    for cells in _rows(label_block):
        if len(cells) >= 2 and cells[0] and cells[1] and cells[0].lower() != 'purpose':
            # only keep rows whose purpose looks like a known purpose key
            if re.match(r'^[a-z]+-[a-z-]+$', cells[0]):
                cfg['labels'][cells[0]] = cells[1]

    for cells in _rows(_section(text, 'Ready Gate')):
        if len(cells) >= 2 and cells[0].lower() == 'ready-gate':
            gate = cells[1].lower()
            # `off` / `disabled` are natural ways to write "no readiness gate";
            # normalise them to the canonical `none` so the fast path picks a
            # story instead of bouncing an unrecognised token to inline selection.
            cfg['ready_gate'] = 'none' if gate in ('off', 'disabled') else gate
    for cells in _rows(_section(text, 'Agent Gating')):
        if len(cells) >= 2 and cells[0].lower() == 'agent-gating':
            cfg['agent_gating'] = cells[1].lower()

    if re.search(r'is\*{0,2}\s*type-capable', text, re.IGNORECASE):
        cfg['type_capable'] = True

    # Field-name overrides: a project that renamed an org field records the new
    # name here, and `wf_core.resolve_field_name` prefers it over the default.
    for cells in _rows(_section(text, 'Issue Types & Fields')):
        if len(cells) >= 2 and cells[1] and re.match(r'^field-[a-z-]+$', cells[0]):
            cfg['fields'][cells[0]] = cells[1]

    board_block = _section(text, 'Project Board')
    for cells in _rows(board_block):
        if len(cells) >= 2:
            key, val = cells[0].lower(), cells[1]
            if key == 'project-node-id':
                cfg['board']['project_node_id'] = None if val in ('n/a', '') else val
            elif key == 'project-title':
                cfg['board']['project_title'] = val
            elif key == 'status-field-name':
                cfg['board']['status_field_name'] = val or 'Status'
            elif key == 'status-field-id':
                cfg['board']['status_field_id'] = None if val in ('n/a', '') else val
            elif key == 'start-date-field-id':
                cfg['board']['start_date_field_id'] = None if val in ('n/a', '') else val
    # Status Options: purpose key → option id (first hex-ish token in the cell)
    for cells in _rows(_section(text, 'Status Options')):
        purpose = next((c for c in cells if c.startswith('col-')), None)
        if not purpose:
            continue
        for c in cells:
            tok = re.match(r'^([0-9a-f]{6,})', c)
            if tok:
                cfg['board']['columns'][purpose] = tok.group(1)
                break
    return cfg


def load_review_labels(root):
    """Parse review-state label names from docs/review.config.md if present.

    Best-effort: keep any table row whose first cell is a known review-state
    purpose key, mapping it to the next backtick-stripped cell. Absent file →
    empty map, and the resolver falls back to the `review-` prefixed defaults.
    """
    path = os.path.join(root, 'docs', 'review.config.md')
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    purposes = set(wf_core.REVIEW_DEFAULT_LABELS)
    out = {}
    for cells in _rows(text):
        if len(cells) >= 2 and cells[0] in purposes and cells[1]:
            out[cells[0]] = cells[1]
    return out


def config_paths(root):
    return (os.path.join(root, '.claude', 'wf-config.json'),
            os.path.join(root, 'ClaudeProject.md'))


def load_config():
    """Load config: JSON cache if fresh, else parse ClaudeProject.md. (ok, cfg, err)."""
    root = repo_root()
    cache, source = config_paths(root)
    if os.path.isfile(cache):
        fresh = (not os.path.isfile(source)
                 or os.path.getmtime(cache) >= os.path.getmtime(source))
        if fresh:
            try:
                with open(cache, encoding='utf-8') as fh:
                    return True, json.load(fh), ''
            except (OSError, json.JSONDecodeError) as exc:
                eprint('wf: ignoring unreadable cache (%s); parsing ClaudeProject.md' % exc)
    if not os.path.isfile(source):
        return False, None, 'no ClaudeProject.md found at %s' % root
    with open(source, encoding='utf-8') as fh:
        cfg = parse_claude_project(fh.read())
    cfg['review_labels'] = load_review_labels(root)
    return True, cfg, ''


def label(cfg, purpose):
    return wf_core.resolve_label(purpose, cfg.get('labels', {}))


def field_name(cfg, purpose):
    return wf_core.resolve_field_name(purpose, cfg.get('fields', {}))


# ── candidate assembly ───────────────────────────────────────────────────────

def _norm_issue(raw):
    ms = raw.get('milestone')
    return {
        'number': raw['number'],
        'title': raw.get('title', ''),
        'labels': [l['name'] for l in raw.get('labels', [])],
        'body': raw.get('body', '') or '',
        'milestone': ms['title'] if ms else None,
        'url': raw.get('url', ''),
    }


def _board_column_candidates(cfg, column_name):
    """Fetch unassigned open issues in the named board column via GraphQL.

    Returns (ok, issues, err) with issues in the same normalised shape as
    the label-gate path.
    """
    board = cfg.get('board', {})
    node = board.get('project_node_id')
    if not node:
        return False, None, 'board-column gate requires a configured board (project-node-id)'
    field_name = board.get('status_field_name', 'Status')
    ok, data, err = gh_graphql(
        'query($id:ID!){ node(id:$id){ ... on ProjectV2 {'
        ' items(first:200){ nodes {'
        '   fieldValueByName(name:"%s"){ ... on ProjectV2ItemFieldSingleSelectValue { name } }'
        '   content { ... on Issue {'
        '     number title body state url'
        '     labels(first:20){ nodes { name } }'
        '     milestone { title }'
        '     assignees(first:1){ nodes { login } }'
        '   } }'
        ' } } } } }' % field_name.replace('"', '\\"'),
        id=node)
    if not ok or not data:
        return False, None, 'board-column query failed: %s' % err
    try:
        nodes = data['node']['items']['nodes']
    except (KeyError, TypeError):
        return False, None, 'unexpected board-column response shape'
    issues = []
    for item in nodes:
        fv = item.get('fieldValueByName')
        status = fv.get('name', '') if fv else ''
        content = item.get('content')
        if not content or not content.get('number'):
            continue
        if status.strip().lower() != column_name.strip().lower():
            continue
        if content.get('state', '').upper() != 'OPEN':
            continue
        assignees = content.get('assignees', {}).get('nodes', [])
        if assignees:
            continue
        issues.append({
            'number': content['number'],
            'title': content.get('title', ''),
            'labels': [l['name'] for l in content.get('labels', {}).get('nodes', [])],
            'body': content.get('body', '') or '',
            'milestone': content.get('milestone', {}).get('title') if content.get('milestone') else None,
            'url': content.get('url', ''),
        })
    return True, issues, ''


# -- org capability resolution -----------------------------------------------

CAPABILITY_CACHE_NAME = 'issue-fields-cache.json'

# Both halves of the org's capability surface in one round trip: the enabled
# native issue types, and every issue field with its option ids.
#
# This is GraphQL and not REST on purpose. The REST endpoint
# `/orgs/{org}/issue-fields` returns `null` for every option id, which makes a
# single-select or multi-select field impossible to write -- you can read the
# option names but never name one in a mutation. Do not "simplify" this back to
# REST.
ORG_CAPABILITY_QUERY = (
    'query($login:String!){'
    ' organization(login:$login){'
    '  issueTypes(first:50){ nodes { id name isEnabled } }'
    '  issueFields(first:50){ nodes {'
    '   __typename'
    '   ... on IssueFieldSingleSelect { id name options { id name } }'
    '   ... on IssueFieldMultiSelect { id name options { id name } }'
    '   ... on IssueFieldDate { id name }'
    '   ... on IssueFieldText { id name }'
    '   ... on IssueFieldNumber { id name }'
    '  } }'
    ' } }'
)

_FIELD_TYPENAMES = {
    'IssueFieldSingleSelect': 'single-select',
    'IssueFieldMultiSelect': 'multi-select',
    'IssueFieldDate': 'date',
    'IssueFieldText': 'text',
    'IssueFieldNumber': 'number',
}


def capability_cache_path(root=None):
    return os.path.join(root or repo_root(), '.claude', CAPABILITY_CACHE_NAME)


def load_capability_cache(root=None):
    """Read the capability cache. Returns {} when absent or unreadable."""
    path = capability_cache_path(root)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as fh:
            cached = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        eprint('wf: ignoring unreadable capability cache (%s)' % exc)
        return {}
    return cached if isinstance(cached, dict) else {}


def merge_capability_cache(values, root=None):
    """Merge keys into the capability cache, preserving every other key.

    Merged rather than overwritten because this file is shared: `issue-apply`
    and `issue-audit` write their own keys into it, and a capability refresh
    must not discard them.
    """
    path = capability_cache_path(root)
    cached = load_capability_cache(root)
    cached.update(values)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(cached, fh, indent=2, sort_keys=True)
        fh.write('\n')
    return cached


def parse_org_capabilities(data):
    """Shape the GraphQL response into (type_capable, type_map, field_map).

    `type_map` is {type name: node id} for enabled types only -- a disabled type
    cannot be set, so carrying it would only invite a mutation that fails.
    `field_map` is {field name: {id, data_type, options: {option name: id}}}.
    """
    org = (data or {}).get('organization')
    if not org:
        # A user-owned repo resolves `organization` to null. Issue types are an
        # org-only feature, so this is a valid configuration, not a failure.
        return False, {}, {}

    type_map = {}
    for node in (org.get('issueTypes') or {}).get('nodes') or []:
        if node and node.get('isEnabled') and node.get('name'):
            type_map[node['name']] = node['id']

    field_map = {}
    for node in (org.get('issueFields') or {}).get('nodes') or []:
        if not node or not node.get('name'):
            continue
        field_map[node['name']] = {
            'id': node['id'],
            'data_type': _FIELD_TYPENAMES.get(node.get('__typename'), 'unknown'),
            'options': {o['name']: o['id'] for o in (node.get('options') or [])},
        }

    return bool(type_map), type_map, field_map


def gh_graphql_partial(query, **fields):
    """Like `gh_graphql`, but keeps the data GitHub returned alongside errors.

    GraphQL answers a partly-authorised query with both: the fields the token
    may read, and a `FORBIDDEN` error naming the ones it may not. `gh` exits
    non-zero in that case and `gh_graphql` discards the whole response, which
    is right everywhere else — a half-applied mutation is not a result. Here it
    is the difference between "this org has no issue types" and "this token may
    not see them", and those two must not be reported the same way.

    Returns (data, errors, err) where `errors` is the GraphQL error list.
    """
    code, out, err = run(_graphql_args(query, fields))
    try:
        parsed = json.loads(out) if (out or '').strip() else None
    except json.JSONDecodeError:
        parsed = None
    if parsed is None:
        return None, [], (err or '').strip() or 'no response from gh api graphql'
    return parsed.get('data'), parsed.get('errors') or [], (
        '' if code == 0 else (err or '').strip())


def _denied_paths(errors):
    """The top-level query fields a FORBIDDEN error named, e.g. {'issueTypes'}."""
    denied = set()
    for e in errors or []:
        if (e.get('type') or '').upper() != 'FORBIDDEN':
            continue
        for part in e.get('path') or []:
            if isinstance(part, str):
                denied.add(part)
    return denied


def resolve_org_capabilities(cfg, refresh=False, root=None):
    """Resolve the org's issue types and fields, through the cache.

    Returns (ok, capabilities, err). `capabilities` carries `type_capable`,
    `type_map` and `field_map`. A cache hit skips the round trip entirely;
    `refresh=True` forces the query and rewrites those three keys.
    """
    if not refresh:
        cached = load_capability_cache(root)
        if 'type_capable' in cached and 'field_map' in cached:
            return True, {'type_capable': cached['type_capable'],
                          'type_map': cached.get('type_map') or {},
                          'field_map': cached.get('field_map') or {},
                          'cached': True}, ''

    data, errors, err = gh_graphql_partial(ORG_CAPABILITY_QUERY, login=cfg['org'])
    if data is None:
        return False, None, 'org capability query failed: %s' % (
            err or json.dumps(errors))

    denied = _denied_paths(errors)
    type_capable, type_map, field_map = parse_org_capabilities(data)
    caps = {'type_capable': type_capable, 'type_map': type_map,
            'field_map': field_map, 'cached': False,
            'denied': sorted(denied),
            'errors': [e.get('message', '') for e in errors]}

    # Never cache a capability the token was refused. A cached `type_capable:
    # false` that really meant "not allowed to look" would make every later run
    # quietly fall back to labels — the silent-blank failure this whole feature
    # exists to stop.
    if not denied:
        merge_capability_cache({'type_capable': type_capable, 'type_map': type_map,
                                'field_map': field_map}, root)
    return True, caps, ''


def org_exists(cfg):
    """Whether the configured owner resolves as an organization at all.

    Separates the two ways `resolve_org_capabilities` can come back empty: a
    user-owned repo, which is valid, from an org whose capabilities the token
    cannot see, which is not.
    """
    ok, data, _ = gh_graphql(
        'query($login:String!){ organization(login:$login){ id } }',
        login=cfg['org'])
    return bool(ok and (data or {}).get('organization'))


def cmd_org_capabilities(args):
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)

    ok, caps, err = resolve_org_capabilities(cfg, refresh=args.refresh)
    if not ok:
        emit('error', EXIT_ENV, reason=err, org=cfg['org'])

    # A refused capability is not an absent one. An org that has not enabled
    # issue types is a valid configuration to fall back from; a token that may
    # not read them tells us nothing about the org, and carrying on would
    # create issues with blank metadata and no error — the exact failure this
    # command exists to prevent. Stop and name the account.
    if caps.get('denied'):
        emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
             denied=caps['denied'], errors=caps['errors'],
             reason='the authenticated account may not read %s for this org; '
                    'switch accounts (gh auth switch) or grant it access — this '
                    'is not the same as the org having none'
                    % ' and '.join(caps['denied']))

    # An org that resolves but reports neither types nor fields is not the same
    # as a user account, and not the same as an org that simply has not enabled
    # them: it is what an under-scoped or expired token looks like. Exiting
    # non-zero here is the only thing that tells those apart.
    if not caps['type_capable'] and not caps['field_map']:
        if org_exists(cfg):
            emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
                 reason='org resolves but reports no issue types and no issue '
                        'fields; check the token carries the read:org scope',
                 type_capable=False, type_map={}, field_map={})
        emit('ok', EXIT_OK, org=cfg['org'], owner_kind='user',
             type_capable=False, type_map={}, field_map={},
             cached=caps.get('cached', False),
             note='user-owned repo: native issue types are an org-only feature')

    # Report which purpose keys actually resolve against this org, so a caller
    # does not have to re-derive the mapping to know what it can set.
    resolved, missing = {}, []
    for key in wf_core.FIELD_NAME_DEFAULTS:
        name = field_name(cfg, key)
        if name in caps['field_map']:
            resolved[key] = name
        else:
            missing.append({'purpose': key, 'expected_name': name})

    emit('ok', EXIT_OK, org=cfg['org'], owner_kind='organization',
         type_capable=caps['type_capable'], type_map=caps['type_map'],
         field_map=caps['field_map'], cached=caps.get('cached', False),
         resolved_fields=resolved, missing_fields=missing,
         cache=os.path.relpath(capability_cache_path(), repo_root()))


# ── issue-apply ──────────────────────────────────────────────────────────────
# One command that creates or updates an issue with everything on it: native
# type, every org field value, parent, labels, and its blocked-by edges.
#
# It replaces roughly ten hand-run round trips per issue, each of which the
# markdown it came from described as optional. The measured result of "optional"
# across one consuming repo was 7 typed issues out of 82 and no field values at
# all, with no error anywhere. So this command is deliberately strict: it
# refuses a spec that omits metadata the org defines, and it reads every write
# back rather than trusting that an accepted mutation did something.

# The selection every read-back uses. A mutation payload can carry it too, so
# `createIssue` returns the issue *as GitHub now holds it* — which turns
# verification from an extra round trip per issue into a free one.
ISSUE_SELECTION = (
    '  id number title body'
    '  issueType { name }'
    '  parent { number }'
    '  blockedBy(first:50){ nodes { number } }'
    '  labels(first:50){ nodes { name } }'
    '  issueFieldValues(first:50){ nodes {'
    '   __typename'
    '   ... on IssueFieldSingleSelectValue { field { ... on IssueFieldSingleSelect { name } } name }'
    '   ... on IssueFieldMultiSelectValue { field { ... on IssueFieldMultiSelect { name } } options { name } }'
    '   ... on IssueFieldTextValue { field { ... on IssueFieldText { name } } value }'
    '   ... on IssueFieldDateValue { field { ... on IssueFieldDate { name } } value }'
    '   ... on IssueFieldNumberValue { field { ... on IssueFieldNumber { name } } value }'
    '  } }'
)

ISSUE_READBACK_QUERY = (
    'query($owner:String!,$repo:String!,$number:Int!){'
    ' repository(owner:$owner,name:$repo){ issue(number:$number){'
    + ISSUE_SELECTION +
    ' } } }'
)


def read_issue(cfg, number, repo=None):
    """Read an issue's current type, fields, parent and blockers. (ok, issue, err)."""
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    ok, data, err = gh_graphql(ISSUE_READBACK_QUERY, owner=owner, repo=name,
                               number=int(number))
    if not ok:
        return False, None, err
    issue = ((data or {}).get('repository') or {}).get('issue')
    if not issue:
        return False, None, 'issue #%s not found in %s/%s' % (number, owner, name)
    return True, issue, ''


def issue_field_values(issue):
    """Flatten a read-back into {field name: value}, comparable to a spec.

    Single-select and text come back as one value, multi-select as a sorted
    list, so a spec's `["New Feature"]` and the API's option list compare
    directly without the caller re-deriving the shape per field type.
    """
    out = {}
    for node in ((issue.get('issueFieldValues') or {}).get('nodes')) or []:
        field = (node.get('field') or {}).get('name')
        if not field:
            continue
        if 'options' in node:
            out[field] = sorted(o['name'] for o in node.get('options') or [])
        elif 'name' in node:
            out[field] = node.get('name')
        else:
            out[field] = node.get('value')
    return out


def _values_match(wanted, actual):
    """Whether a spec value and a read-back value are the same, shape-insensitively."""
    if isinstance(wanted, (list, tuple)) or isinstance(actual, (list, tuple)):
        as_list = lambda v: sorted(v) if isinstance(v, (list, tuple)) else (
            [] if v is None else [v])
        return as_list(wanted) == as_list(actual)
    return str(wanted) == str(actual)


def resolve_spec_context(cfg, label_names, numbers, repo=None):
    """One lookup for everything the batches need before they can be built.

    The repository's node id, the id of every label the spec names, and the
    node id of every issue the spec references but does not create. Doing this
    as one query rather than three keeps the whole prerequisite phase to a
    single round trip, which is what leaves room for the epic tree itself.

    Returns (ok, context, err).
    """
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    wanted = sorted({int(n) for n in numbers})
    aliases = [('n%d' % n, n) for n in wanted]
    issue_parts = ' '.join('%s: issue(number:%d){ id number }' % (alias, number)
                           for alias, number in aliases)
    ok, data, err = gh_graphql(
        'query($owner:String!,$repo:String!){'
        ' repository(owner:$owner,name:$repo){ id'
        ' labels(first:100){ nodes { id name } } %s } }' % issue_parts,
        owner=owner, repo=name)
    if not ok:
        return False, None, err

    repository = (data or {}).get('repository')
    if not repository:
        return False, None, 'repository %s/%s not found' % (owner, name)

    have_labels = {n['name']: n['id'] for n
                   in (repository.get('labels') or {}).get('nodes') or []}
    issues = {}
    missing_issues = []
    for alias, number in aliases:
        node = repository.get(alias)
        if node:
            issues[number] = node['id']
        else:
            missing_issues.append(number)

    return True, {
        'repo_id': repository['id'],
        'repo': '%s/%s' % (owner, name),
        'labels': {n: have_labels[n] for n in label_names if n in have_labels},
        'missing_labels': [n for n in label_names if n not in have_labels],
        'issues': issues,
        'missing_issues': missing_issues,
    }, ''


def _mutation_result(code, out, err, path):
    """Unwrap a `gh api graphql` mutation response. Returns (ok, node, err)."""
    try:
        parsed = json.loads(out) if (out or '').strip() else None
    except json.JSONDecodeError as exc:
        return False, None, 'could not parse GraphQL JSON: %s' % exc
    if parsed and parsed.get('errors'):
        return False, None, json.dumps(parsed['errors'])
    if code != 0:
        return False, None, (err or '').strip() or 'mutation failed'
    node = (parsed or {}).get('data') or {}
    for step in path:
        node = (node or {}).get(step)
    return (True, node, '') if node else (False, None, 'mutation returned no %s'
                                          % path[-1])


def _graphql_json(query, variables):
    """Send a mutation whose variables include lists or objects.

    `_graphql_args` types each variable as a GraphQL scalar, which is right for
    the query path but cannot express a list of input objects — and stringifying
    one into the mutation body is what defeated the earlier `-f fields='[...]'`
    attempts. Sending a JSON request body keeps the types intact.
    """
    code, out, err = run(['gh', 'api', 'graphql', '--input', '-'],
                         input_text=json.dumps({'query': query,
                                                'variables': variables}))
    return code, out, err


def _batch_result(code, out, err, aliases, field='issue'):
    """Unwrap an aliased multi-mutation. Returns {alias: (ok, node, err)}.

    GraphQL answers a partial failure with the aliases that worked in `data`
    and an error carrying the path of each one that did not, so a batch reports
    per-entry outcomes rather than collapsing to one verdict. That is what lets
    the caller say which issues landed.
    """
    try:
        parsed = json.loads(out) if (out or '').strip() else None
    except json.JSONDecodeError as exc:
        parsed = None
        err = 'could not parse GraphQL JSON: %s' % exc
    data = (parsed or {}).get('data') or {}
    by_alias = {}
    for entry in (parsed or {}).get('errors') or []:
        path = entry.get('path') or []
        if path:
            by_alias.setdefault(path[0], entry.get('message', 'mutation failed'))

    out_map = {}
    for alias in aliases:
        node = (data.get(alias) or {}).get(field) if data.get(alias) else None
        if node:
            out_map[alias] = (True, node, '')
        else:
            out_map[alias] = (False, None, by_alias.get(alias)
                              or (err or '').strip()
                              or ('mutation failed' if code else 'mutation returned nothing'))
    return out_map


def send_create_batch(inputs):
    """Create many issues in one request. Returns {alias: (ok, issue, err)}.

    Aliases cannot reference each other's output, which is exactly why the
    caller batches by hierarchy level: everything in one request is independent
    of everything else in it.
    """
    aliases = ['a%d' % n for n in range(len(inputs))]
    decls = ','.join('$%s:CreateIssueInput!' % a for a in aliases)
    body = ' '.join('%s: createIssue(input:$%s){ issue { %s } }'
                    % (a, a, ISSUE_SELECTION) for a in aliases)
    code, out, err = _graphql_json('mutation(%s){ %s }' % (decls, body),
                                   dict(zip(aliases, inputs)))
    return _batch_result(code, out, err, aliases)


def send_link_batch(ops):
    """Apply dependency edges and body rewrites in one request.

    `ops` are (alias, kind, variables) with kind `'blocked-by'` or `'body'`.
    Both kinds ride together because they are the same phase: the last one,
    once every issue in the spec exists and every reference resolves.
    """
    decls, body, aliases = [], [], []
    variables = {}
    for alias, kind, args in ops:
        aliases.append(alias)
        if kind == 'blocked-by':
            decls.append('$%s_i:ID!,$%s_b:ID!' % (alias, alias))
            body.append('%s: addBlockedBy(input:{issueId:$%s_i,blockingIssueId:$%s_b})'
                        '{ issue { id blockedBy(first:50){ nodes { number } } } }'
                        % (alias, alias, alias))
            variables['%s_i' % alias] = args['issue_id']
            variables['%s_b' % alias] = args['blocking_id']
        else:
            decls.append('$%s_i:ID!,$%s_t:String!' % (alias, alias))
            body.append('%s: updateIssue(input:{id:$%s_i,body:$%s_t})'
                        '{ issue { id body } }' % (alias, alias, alias))
            variables['%s_i' % alias] = args['issue_id']
            variables['%s_t' % alias] = args['body']
    code, out, err = _graphql_json('mutation(%s){ %s }' % (','.join(decls),
                                                           ' '.join(body)),
                                   variables)
    return _batch_result(code, out, err, aliases)


def set_issue_type(issue_id, type_id):
    code, out, err = _graphql_json(
        'mutation($i:ID!,$t:ID!){ updateIssueIssueType(input:{issueId:$i,issueTypeId:$t})'
        '{ issue { id } } }', {'i': issue_id, 't': type_id})
    return _mutation_result(code, out, err, ['updateIssueIssueType', 'issue'])


def set_issue_fields(issue_id, field_inputs):
    code, out, err = _graphql_json(
        'mutation($i:ID!,$f:[IssueFieldCreateOrUpdateInput!]){'
        ' setIssueFieldValue(input:{issueId:$i,issueFields:$f}){ issue { id } } }',
        {'i': issue_id, 'f': list(field_inputs)})
    return _mutation_result(code, out, err, ['setIssueFieldValue', 'issue'])


def add_sub_issue(parent_id, child_id):
    code, out, err = _graphql_json(
        'mutation($p:ID!,$c:ID!){ addSubIssue(input:{issueId:$p,subIssueId:$c,'
        'replaceParent:true}){ issue { id } } }', {'p': parent_id, 'c': child_id})
    return _mutation_result(code, out, err, ['addSubIssue', 'issue'])


def add_blocked_by(issue_id, blocking_id):
    code, out, err = _graphql_json(
        'mutation($i:ID!,$b:ID!){ addBlockedBy(input:{issueId:$i,blockingIssueId:$b})'
        '{ issue { id } } }', {'i': issue_id, 'b': blocking_id})
    return _mutation_result(code, out, err, ['addBlockedBy', 'issue'])


def issue_mismatches(number, issue, plan, expect_type=None, expect_parent=None,
                     expect_blocked_by=()):
    """Compare an issue as GitHub holds it against what the spec asked for.

    A mutation GitHub accepts is not a value GitHub stored — an unpinned field,
    a silently-ignored id, a permission that stops short of writing. Every
    mismatch is named, because "the write succeeded and the value is not there"
    is precisely the failure that went unnoticed for months.

    Pure, so it serves both a read-back query and a mutation payload that
    carried the same selection.
    """
    mismatches = []
    if expect_type:
        got = (issue.get('issueType') or {}).get('name')
        if got != expect_type:
            mismatches.append("#%s: native type is %s, expected '%s'"
                              % (number, "'%s'" % got if got else 'unset', expect_type))

    actual = issue_field_values(issue)
    for field, spec in (plan.get('fields') or {}).items():
        if not _values_match(spec['value'], actual.get(field)):
            mismatches.append("#%s: field '%s' is %r, expected %r"
                              % (number, field, actual.get(field), spec['value']))

    if expect_parent:
        got = (issue.get('parent') or {}).get('number')
        if got != expect_parent:
            mismatches.append('#%s: parent is %s, expected #%s'
                              % (number, '#%s' % got if got else 'unset', expect_parent))

    have = {n['number'] for n in (issue.get('blockedBy') or {}).get('nodes') or []}
    for want in expect_blocked_by or ():
        if want not in have:
            mismatches.append('#%s: missing blocked-by edge to #%s' % (number, want))

    return mismatches


def verify_issue(cfg, number, plan, expect_type=None, expect_parent=None,
                 expect_blocked_by=(), repo=None):
    """Read the issue back and compare it. Returns (passed, mismatches)."""
    ok, issue, err = read_issue(cfg, number, repo)
    if not ok:
        return False, ['#%s: could not read back: %s' % (number, err)]
    mismatches = issue_mismatches(number, issue, plan, expect_type,
                                  expect_parent, expect_blocked_by)
    return not mismatches, mismatches


DEPENDENCY_HEADING = '## Dependencies'


def ensure_dependency_section(body, blocked_by):
    """Keep the body `## Dependencies` markers in step with the native edges.

    Both are written, deliberately. The native edge is what the portal and the
    audit read; the body prose is what `wf_core.parse_dependencies()` reads to
    decide when an issue unblocks. Dropping the prose would silently break
    auto-unblocking, so this is duplication with a reason.
    """
    if not blocked_by:
        return body or ''
    lines = ['Blocked by #%s' % n for n in blocked_by]
    section = '%s\n\n%s\n' % (DEPENDENCY_HEADING, '\n'.join(lines))
    body = body or ''
    if DEPENDENCY_HEADING not in body:
        return (body.rstrip() + '\n\n' + section) if body.strip() else section
    head, _, rest = body.partition(DEPENDENCY_HEADING)
    tail = ''
    nxt = re.search(r'^##\s', rest, re.MULTILINE)
    if nxt:
        tail = rest[nxt.start():]
    return head.rstrip() + '\n\n' + section + ('\n' + tail if tail else '')


def load_spec(path):
    """Read a spec file. Returns (ok, entries, raw, err)."""
    if not os.path.isfile(path):
        return False, None, None, 'no spec file at %s' % path
    try:
        with open(path, encoding='utf-8') as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return False, None, None, 'could not read spec: %s' % exc
    entries = raw.get('issues') if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return False, None, None, "spec must be a list, or an object with an 'issues' list"
    return True, entries, raw, ''


def write_back_numbers(path, raw, entries):
    """Write created issue numbers back into the spec file.

    So a re-run after a partial failure completes the remainder instead of
    creating everything a second time: an entry that now carries a number is an
    update, and an update whose values are already right is a no-op.
    """
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(raw if isinstance(raw, dict) else entries, fh, indent=2)
            fh.write('\n')
        return True, ''
    except OSError as exc:
        return False, str(exc)


def _resolve_reference(ref, resolved):
    """A spec reference — an issue number, or another entry's `key` — to a number."""
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str) and ref.isdigit():
        return int(ref)
    return resolved.get(ref)


def _blockers(entry, resolved):
    """(resolved numbers, references that resolve to nothing)."""
    numbers, unresolved = [], []
    for ref in entry.get('blocked_by') or []:
        number = _resolve_reference(ref, resolved)
        (numbers if number is not None else unresolved).append(
            number if number is not None else ref)
    return numbers, unresolved


def _result(entry, action):
    return {'entry': wf_core.entry_label(entry), 'key': entry.get('key'),
            'action': action, 'number': entry.get('number'), 'changed': [],
            'errors': [], 'mismatches': []}


def _parent_id(entry, resolved, node_ids):
    """(parent number, parent node id, err). (None, None, '') when there is none."""
    if entry.get('parent') is None:
        return None, None, ''
    number = _resolve_reference(entry['parent'], resolved)
    if number is None:
        return None, None, ('parent %r is neither an issue number nor a key in '
                            'this spec' % entry['parent'])
    node_id = node_ids.get(number)
    if not node_id:
        return number, None, 'parent #%s could not be resolved' % number
    return number, node_id, ''


def _create_input(cfg, ctx, caps, entry, plan, parent_id, body):
    args = {'repositoryId': ctx['repo_id'], 'title': entry.get('title') or ''}
    if body:
        args['body'] = body
    if plan['type']:
        args['issueTypeId'] = caps['type_map'][plan['type']]
    if parent_id:
        args['parentIssueId'] = parent_id
    label_ids = sorted(ctx['labels'][label(cfg, l)]
                       for l in entry.get('labels') or [])
    if label_ids:
        args['labelIds'] = label_ids
    fields = [f['input'] for f in plan['fields'].values()]
    if fields:
        args['issueFields'] = fields
    return args


def create_level(cfg, ctx, caps, plans, resolved, node_ids):
    """Create one hierarchy level, in batches. Returns a result per plan.

    Everything in a level is independent of everything else in it, which is
    what makes one aliased request correct: no alias needs another alias's
    output. A level of thirteen and a level of one cost the same one round
    trip, capped by `wf_core.BATCH_MAX_NODES`.
    """
    results, ready, pending = {}, [], []
    for plan in plans:
        entry = plan['entry']
        result = _result(entry, 'create')
        results[id(entry)] = result

        parent_number, parent_id, err = _parent_id(entry, resolved, node_ids)
        if err:
            result['errors'].append(err)
            continue
        result['parent_number'] = parent_number

        numbers, _unresolved = _blockers(entry, resolved)
        # Only the blockers that already have numbers can go in the body now.
        # The rest are patched in the link phase, once every issue exists.
        body = ensure_dependency_section(entry.get('body'), numbers)
        result['sent_body'] = body
        ready.append(_create_input(cfg, ctx, caps, entry, plan, parent_id, body))
        pending.append((plan, result))

    for chunk_start in range(0, len(pending), wf_core.BATCH_MAX_NODES):
        window = slice(chunk_start, chunk_start + wf_core.BATCH_MAX_NODES)
        outcomes = send_create_batch(ready[window])
        for offset, (plan, result) in enumerate(pending[window]):
            ok, issue, err = outcomes['a%d' % offset]
            if not ok:
                result['errors'].append('create failed: %s' % err)
                continue
            result['number'] = issue['number']
            result['issue_id'] = issue['id']
            result['issue'] = issue
            result['changed'] = ['created']
            node_ids[issue['number']] = issue['id']
            if plan['entry'].get('key'):
                resolved[plan['entry']['key']] = issue['number']
            plan['entry']['number'] = issue['number']
            # The create payload carried the full selection, so the issue is
            # verified here without a second round trip.
            result['mismatches'] = issue_mismatches(
                issue['number'], issue, plan, expect_type=plan['type'],
                expect_parent=result.get('parent_number'))

    return [results[id(p['entry'])] for p in plans]


def update_entry(cfg, ctx, caps, plan, resolved, node_ids):
    """Bring an existing issue in line with the spec, setting only what differs.

    An update that changes nothing is what makes re-running a spec safe, so
    every property is compared before it is written.
    """
    entry = plan['entry']
    result = _result(entry, 'update')
    repo = ctx['repo']

    parent_number, parent_id, err = _parent_id(entry, resolved, node_ids)
    if err:
        result['errors'].append(err)
        return result
    result['parent_number'] = parent_number

    ok, current, err = read_issue(cfg, entry['number'], repo)
    if not ok:
        result['errors'].append(err)
        return result
    result['issue_id'] = current['id']
    result['issue'] = current
    node_ids[int(entry['number'])] = current['id']

    if plan['type'] and (current.get('issueType') or {}).get('name') != plan['type']:
        ok, _, err = set_issue_type(current['id'], caps['type_map'][plan['type']])
        if not ok:
            result['errors'].append('set type failed: %s' % err)
            return result
        result['changed'].append('type')

    have = issue_field_values(current)
    stale = [f['input'] for name, f in plan['fields'].items()
             if not _values_match(f['value'], have.get(name))]
    if stale:
        ok, _, err = set_issue_fields(current['id'], stale)
        if not ok:
            result['errors'].append('set fields failed: %s' % err)
            return result
        result['changed'].append('fields')

    if parent_id and (current.get('parent') or {}).get('number') != parent_number:
        ok, _, err = add_sub_issue(parent_id, current['id'])
        if not ok:
            result['errors'].append('set parent failed: %s' % err)
            return result
        result['changed'].append('parent')

    wanted = {label(cfg, l) for l in entry.get('labels') or []}
    present = {n['name'] for n in (current.get('labels') or {}).get('nodes') or []}
    add = sorted(wanted - present)
    if add:
        code, _, lerr = run(['gh', 'issue', 'edit', str(entry['number']),
                             '--repo', repo]
                            + sum((['--add-label', n] for n in add), []))
        if code != 0:
            result['errors'].append('label update failed: %s' % lerr.strip())
            return result
        result['changed'].append('labels')

    if result['changed']:
        _, result['mismatches'] = verify_issue(
            cfg, entry['number'], plan, expect_type=plan['type'],
            expect_parent=parent_number, repo=repo)
    return result


def link_phase(cfg, plans, results, resolved, node_ids):
    """Apply every dependency edge and body rewrite, in one batch per chunk.

    Last, deliberately: an edge may point at any issue in the tree, including
    one created in the final level, and an alias cannot reference another
    alias's output. Waiting until everything exists is what makes a reference
    to any level legal.

    Edges are written twice on purpose — a native `addBlockedBy`, which is what
    GitHub's UI and the audit read, and a `## Dependencies` body section, which
    is what `wf_core.parse_dependencies()` reads to decide when an issue
    unblocks. Dropping the prose would silently break auto-unblocking.
    """
    ops, owners = [], []
    for plan, result in zip(plans, results):
        entry = plan['entry']
        if result['errors'] or not result.get('number'):
            continue
        numbers, unresolved = _blockers(entry, resolved)
        if unresolved:
            result['errors'].append(
                'blocked-by references nothing in this spec or repo: %s'
                % ', '.join(str(u) for u in unresolved))
            continue
        result['blocked_by'] = numbers
        if not numbers:
            continue

        issue = result.get('issue') or {}
        have = {n['number'] for n in (issue.get('blockedBy') or {}).get('nodes') or []}
        for blocker in numbers:
            if blocker in have:
                continue
            blocking_id = node_ids.get(blocker)
            if not blocking_id:
                result['errors'].append('blocker #%s could not be resolved' % blocker)
                continue
            owners.append((result, 'blocked-by', blocker))
            ops.append(('blocked-by', {'issue_id': result['issue_id'],
                                       'blocking_id': blocking_id}))

        wanted_body = ensure_dependency_section(entry.get('body'), numbers)
        current_body = result.get('sent_body', issue.get('body'))
        if wanted_body != current_body:
            owners.append((result, 'body', None))
            ops.append(('body', {'issue_id': result['issue_id'],
                                 'body': wanted_body}))

    for chunk_start in range(0, len(ops), wf_core.BATCH_MAX_NODES):
        window = slice(chunk_start, chunk_start + wf_core.BATCH_MAX_NODES)
        batch = [('b%d' % n, kind, args)
                 for n, (kind, args) in enumerate(ops[window])]
        outcomes = send_link_batch(batch)
        for offset, (result, kind, blocker) in enumerate(owners[window]):
            ok, node, err = outcomes['b%d' % offset]
            if not ok:
                result['errors'].append(
                    '%s failed: %s' % ('blocked-by #%s' % blocker
                                       if kind == 'blocked-by' else 'body update',
                                       err))
                continue
            result['changed'].append('blocked-by #%s' % blocker
                                     if kind == 'blocked-by' else 'body')
            if kind == 'blocked-by':
                result['issue'] = dict(result.get('issue') or {},
                                       blockedBy=node.get('blockedBy') or {})

    # The edge mutations returned the issue's blockers, so the check is free.
    for result in results:
        for want in result.get('blocked_by') or ():
            have = {n['number'] for n
                    in ((result.get('issue') or {}).get('blockedBy')
                        or {}).get('nodes') or []}
            if want not in have:
                result['mismatches'].append('#%s: missing blocked-by edge to #%s'
                                            % (result['number'], want))
    return results


def cmd_issue_apply(args):
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)

    ok, entries, raw, err = load_spec(args.spec)
    if not ok:
        emit('spec-invalid', EXIT_SPEC, reason=err, spec=args.spec)

    ok, caps, err = resolve_org_capabilities(cfg, refresh=args.refresh)
    if not ok:
        emit('error', EXIT_ENV, reason=err, org=cfg['org'])
    if caps.get('denied'):
        emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
             denied=caps['denied'],
             reason='the authenticated account may not read %s for this org, so a '
                    'spec cannot be checked against it'
                    % ' and '.join(caps['denied']))

    # Everything that can be decided offline is decided before the first write.
    # A spec that is wrong should cost nothing, and a half-applied tree is much
    # harder to reason about than a refused one.
    cycles = wf_core.spec_cycles(entries)
    if cycles:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='dependency cycle in the spec',
             cycles=[' -> '.join(str(n) for n in c) for c in cycles])

    levels, unplaceable = wf_core.spec_levels(entries)
    if unplaceable:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='parent cycle in the spec: these entries can never be created '
                    'because each waits on another in the group',
             entries=[wf_core.entry_label(e) for e in unplaceable])

    errors, skipped, plans = wf_core.validate_spec(
        entries, caps['field_map'], caps['type_map'], cfg.get('fields', {}))
    if errors:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec, errors=errors,
             reason='%d spec %s; nothing was written'
                    % (len(errors), 'error' if len(errors) == 1 else 'errors'))

    # One line for the run, not one per issue: an org with fewer fields than the
    # spec names is a normal configuration, and repeating it per issue buries
    # the errors that matter.
    if skipped:
        eprint('wf: skipped %d field(s) this org does not define: %s'
               % (len(skipped), ', '.join(sorted(skipped))))

    label_names = sorted({label(cfg, l) for e in entries
                          for l in (e.get('labels') or [])})
    referenced = set()
    for entry in entries:
        candidates = [entry.get('number'), entry.get('parent')]
        candidates.extend(entry.get('blocked_by') or [])
        for ref in candidates:
            if isinstance(ref, int):
                referenced.add(ref)
            elif isinstance(ref, str) and ref.isdigit():
                referenced.add(int(ref))
    ok, ctx, err = resolve_spec_context(cfg, label_names, referenced, args.repo)
    if not ok:
        emit('error', EXIT_ENV, reason='could not resolve the repository: %s' % err)
    if ctx['missing_labels']:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='labels the spec names do not exist in this repo',
             labels=ctx['missing_labels'])
    if ctx['missing_issues']:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='issues the spec references do not exist in this repo',
             issues=ctx['missing_issues'])

    if args.dry_run:
        emit('ok', EXIT_OK, spec=args.spec, dry_run=True,
             levels=[[wf_core.entry_label(e) for e in level] for level in levels],
             would_apply=[{'entry': wf_core.entry_label(p['entry']),
                           'action': 'update' if p['entry'].get('number') else 'create',
                           'type': p['type'],
                           'fields': sorted(p['fields'])} for p in plans],
             skipped_fields=sorted(skipped))

    plan_by_entry = {id(p['entry']): p for p in plans}
    resolved = {e['key']: int(e['number']) for e in entries
                if e.get('key') and e.get('number')}
    node_ids = dict(ctx['issues'])

    ordered_plans, results = [], []
    for level in levels:
        level_plans = [plan_by_entry[id(e)] for e in level]
        creates = [p for p in level_plans if not p['entry'].get('number')]
        updates = [p for p in level_plans if p['entry'].get('number')]
        if creates:
            ordered_plans.extend(creates)
            results.extend(create_level(cfg, ctx, caps, creates, resolved, node_ids))
        for plan in updates:
            ordered_plans.append(plan)
            results.append(update_entry(cfg, ctx, caps, plan, resolved, node_ids))

    link_phase(cfg, ordered_plans, results, resolved, node_ids)

    wrote_back, wb_err = write_back_numbers(args.spec, raw, entries)

    payload = {'spec': args.spec, 'applied': results,
               'skipped_fields': sorted(skipped),
               'numbers_written_back': wrote_back}
    if not wrote_back:
        payload['write_back_error'] = wb_err

    failed = [r for r in results if r['errors']]
    mismatched = [r for r in results if r['mismatches']]

    if failed:
        landed = [r for r in results if r.get('number') and not r['errors']]
        emit('partial', EXIT_PARTIAL,
             reason='%d of %d entries failed; %d landed. Re-run the spec to '
                    'complete the rest — the numbers written back turn the ones '
                    'that landed into no-op updates'
                    % (len(failed), len(results), len(landed)),
             failed=[{'entry': r['entry'], 'errors': r['errors']} for r in failed],
             **payload)
    if mismatched:
        emit('verify-failed', EXIT_VERIFY,
             reason='%d issue(s) were written but do not read back as specified'
                    % len(mismatched),
             mismatches=sum((r['mismatches'] for r in mismatched), []),
             **payload)

    emit('ok', EXIT_OK, **payload)


# ── issue-audit ──────────────────────────────────────────────────────────────
# Reads. Never writes. It exists because nothing detected that the metadata was
# never applied, and it produces the spec that `issue-apply` uses to backfill.

AUDIT_PAGE = 100
AUDIT_SPEC_DEFAULT = 'issue-audit-spec.json'

AUDIT_QUERY = (
    'query($owner:String!,$repo:String!,$after:String,$since:DateTime){'
    ' repository(owner:$owner,name:$repo){'
    '  issues(states:OPEN,first:%d,after:$after,filterBy:{since:$since},'
    '         orderBy:{field:CREATED_AT,direction:DESC}){'
    '   pageInfo { hasNextPage endCursor }'
    '   nodes {' % AUDIT_PAGE
    + ISSUE_SELECTION +
    '   }'
    '  }'
    ' } }'
)


def scan_open_issues(cfg, repo=None, limit=None, since=None):
    """Every open issue in the repo, newest first. Returns (ok, issues, err).

    `since` narrows to issues updated after a timestamp and `limit` caps the
    scan, so a large backlog can be worked through in slices rather than all at
    once.
    """
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    issues, cursor = [], None
    while True:
        fields = {'owner': owner, 'repo': name}
        if cursor:
            fields['after'] = cursor
        if since:
            fields['since'] = since
        ok, data, err = gh_graphql(AUDIT_QUERY, **fields)
        if not ok:
            return False, None, err
        page = (((data or {}).get('repository') or {}).get('issues')) or {}
        issues.extend(page.get('nodes') or [])
        if limit and len(issues) >= limit:
            return True, issues[:limit], ''
        info = page.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return True, issues, ''
        cursor = info.get('endCursor')


def write_audit_spec(path, entries):
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'issues': entries}, fh, indent=2)
            fh.write('\n')
        return True, ''
    except OSError as exc:
        return False, str(exc)


def cmd_issue_audit(args):
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)

    ok, caps, err = resolve_org_capabilities(cfg, refresh=args.refresh)
    if not ok:
        emit('error', EXIT_ENV, reason=err, org=cfg['org'])
    if caps.get('denied'):
        emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
             denied=caps['denied'],
             reason='the authenticated account may not read %s for this org, so '
                    'there is nothing to audit issues against'
                    % ' and '.join(caps['denied']))

    repo = args.repo or '%s/%s' % (cfg['org'], cfg['repo'])
    ok, issues, err = scan_open_issues(cfg, args.repo, args.limit, args.since)
    if not ok:
        emit('error', EXIT_ENV, reason='could not read issues in %s: %s'
                                       % (repo, err), repo=repo)

    open_numbers = {i['number'] for i in issues}
    audited = [wf_core.audit_issue(issue, caps['field_map'],
                                   type_capable=caps['type_capable'],
                                   project_map=cfg.get('labels') or {},
                                   project_fields=cfg.get('fields') or {},
                                   open_numbers=open_numbers)
               for issue in issues]
    with_gaps = [a for a in audited if a['gaps']]
    summary = wf_core.audit_summary(audited)

    spec_path = args.out or os.path.join(repo_root() or '.', '.claude',
                                         AUDIT_SPEC_DEFAULT)
    wrote, write_err = (True, '')
    if with_gaps:
        wrote, write_err = write_audit_spec(spec_path,
                                            [a['proposed'] for a in with_gaps])

    payload = {'repo': repo, 'summary': summary,
               'spec': spec_path if with_gaps else None,
               'spec_written': wrote}
    if not wrote:
        payload['write_error'] = write_err
    if not args.quiet:
        payload['issues'] = [{'number': a['number'], 'title': a['title'],
                              'gaps': a['gaps']} for a in with_gaps]

    if not with_gaps:
        emit('ok', EXIT_OK, reason='every open issue in %s carries its type, '
                                   'its field values and its dependency edges'
                                   % repo, **payload)

    # Non-zero so the audit can run as a check. The spec it just wrote is the
    # input to the backfill, but it is deliberately not applied here: the
    # dependency edges in it are inferred from body prose, which is not
    # reliable enough to write a graph from unattended.
    emit('gaps', EXIT_GAPS,
         reason='%d of %d open issues in %s are missing metadata. Review %s, '
                'fill in every %s, then run: wf.sh issue-apply %s'
                % (summary['issues_with_gaps'], summary['issues_scanned'], repo,
                   spec_path, wf_core.SPEC_PLACEHOLDER, spec_path),
         **payload)


def fetch_native_types(cfg):
    """Fetch native issue types for all open issues via GraphQL.

    Returns (ok, type_map, err) where type_map is {issue_number: type_name}.
    Used on type-capable orgs so the fast path can filter by native type
    instead of deferring to the inline skill procedure.
    """
    ok, data, err = gh_graphql(
        'query($owner:String!,$repo:String!){'
        ' repository(owner:$owner,name:$repo){'
        '  issues(first:200,states:OPEN){ nodes { number issueType { name } } }'
        ' } }',
        owner=cfg['org'], repo=cfg['repo'])
    if not ok or not data:
        return False, None, 'native type query failed: %s' % err
    try:
        nodes = data['repository']['issues']['nodes']
    except (KeyError, TypeError):
        return False, None, 'unexpected native type response shape'
    type_map = {}
    for node in nodes:
        it = node.get('issueType')
        if it and it.get('name'):
            type_map[node['number']] = it['name']
    return True, type_map, ''


def assemble_candidates(cfg):
    """Fetch the unassigned ready pool per ready-gate. Returns (ok, issues, err)."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    fields = 'number,title,labels,body,milestone,url'
    gate = cfg.get('ready_gate', 'label')
    if gate == 'label':
        args = ['issue', 'list', '--repo', repo, '--state', 'open',
                '--assignee', '', '--label', label(cfg, 'status-ready'),
                '--json', fields, '--limit', '200']
        ok, data, err = gh_json(args)
        if not ok:
            return False, None, err
        return True, [_norm_issue(r) for r in data or []], ''
    if gate == 'none':
        args = ['issue', 'list', '--repo', repo, '--state', 'open',
                '--assignee', '', '--json', fields, '--limit', '200']
        ok, data, err = gh_json(args)
        if not ok:
            return False, None, err
        blocked = label(cfg, 'status-blocked')
        issues = [_norm_issue(r) for r in data or []]
        return True, [i for i in issues if blocked not in i['labels']], ''
    if gate == 'board-column':
        return _board_column_candidates(cfg, 'Ready')
    if gate == 'both':
        label_ok, label_issues, label_err = assemble_candidates(
            dict(cfg, ready_gate='label'))
        if not label_ok:
            return False, None, label_err
        board_ok, board_issues, board_err = _board_column_candidates(cfg, 'Ready')
        if not board_ok:
            return False, None, board_err
        board_numbers = {i['number'] for i in board_issues}
        return True, [i for i in label_issues if i['number'] in board_numbers], ''
    return False, None, 'ready-gate %r not supported by wf' % gate


def narrow_to_sprint(cfg, issues):
    """If any candidate has a milestone, narrow to the earliest open sprint."""
    if wf_core.detect_backlog_mode(issues) != 'sprint':
        return 'flat', issues
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    # `--jq .[0].title` emits a *raw* (unquoted) string, not JSON, so read
    # stdout directly rather than through gh_json's json.loads.
    code, out, err = run(['gh', 'api', 'repos/%s/milestones' % repo,
                          '--jq', 'sort_by(.due_on) | map(select(.open_issues > 0)) | .[0].title'])
    sprint = out.strip()
    if code != 0 or not sprint or sprint == 'null':
        # Can't resolve the active sprint — fall back to the flat pool.
        eprint('wf: could not resolve active sprint (%s); using flat pool' % (err.strip() or 'none open'))
        return 'flat', issues
    return 'sprint', wf_core.get_sprint_candidates(issues, sprint)


# ── claim + markers ──────────────────────────────────────────────────────────

def _claim_marker_path(root, target):
    return os.path.join(root, '.claude', 'claim-%s.sha' % target)


def acquire_claim(target):
    """Atomically acquire refs/claims/<target> (compare-and-swap).

    Returns one of three outcomes — never a bare bool, so the caller can tell
    a rival apart from a broken environment:

      'won'   — the ref was created and we hold the claim (marker written).
      'lost'  — the ref already exists with a different object: a rival agent
                got there first. A normal outcome — try the next pool item.
      'error' — the push failed for a reason that is *not* a lost claim: no
                write access to refs/claims/*, an auth or network failure, a
                missing remote. The caller must surface this instead of
                walking the pool, so a broken environment is never mistaken
                for "every candidate was already claimed" (a phantom
                all-blocked the user reads as an empty backlog).
    """
    code, tree, _ = run(['git', 'rev-parse', 'HEAD^{tree}'])
    if code != 0:
        eprint('wf: cannot read HEAD tree to build a claim object')
        return 'error'
    msg = 'claim %s %s pid%d-%d' % (
        target,
        datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        os.getpid(), random.randint(0, 1_000_000),
    )
    code, sha, err = run(['git', 'commit-tree', tree.strip(), '-m', msg])
    if code != 0:
        eprint('wf: git commit-tree failed (%s)' % err.strip())
        return 'error'
    sha = sha.strip()
    code, _, push_err = run(['git', 'push', 'origin', '%s:refs/claims/%s' % (sha, target)])
    if code != 0:
        # A failed push is a *lost claim* only if the ref now exists on the
        # remote (a rival pushed a different object first). Probe it: if the
        # ref is present the rival won; if it is absent the push failed for
        # another reason (no write access, auth, network) and we must report
        # an error rather than silently pretend a rival took it.
        exists, _, _ = run(['git', 'ls-remote', '--exit-code', 'origin',
                            'refs/claims/%s' % target])
        if exists == 0:
            return 'lost'
        eprint('wf: claim push for %s failed and the ref is absent — treating '
               'as an environment error (%s)' % (target, push_err.strip() or 'no detail'))
        return 'error'
    root = repo_root()
    os.makedirs(os.path.join(root, '.claude'), exist_ok=True)
    with open(_claim_marker_path(root, target), 'w', encoding='utf-8') as fh:
        fh.write(sha)
    return 'won'


def release_claim(target):
    run(['git', 'push', 'origin', ':refs/claims/%s' % target])
    marker = _claim_marker_path(repo_root(), target)
    try:
        os.remove(marker)
    except OSError:
        pass


def apply_in_progress(cfg, issue):
    """Assign @me and move the issue to status-in-progress (durable ownership)."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    prev = wf_core.current_lifecycle_label(issue['labels'], cfg.get('labels', {}))
    args = ['issue', 'edit', str(issue['number']), '--repo', repo,
            '--add-assignee', '@me', '--add-label', label(cfg, 'status-in-progress')]
    if prev:
        args += ['--remove-label', prev]
    code, _, err = run(['gh'] + args)
    if code != 0:
        eprint('wf: warning — could not apply status-in-progress marker (%s)' % err.strip())


# ── dependency validation ────────────────────────────────────────────────────

def validate_issue(cfg, issue, siblings=()):
    """Validate a claimed issue. Returns (verdict, detail).

    verdict ∈ {'valid', 'blocked', 'resolved'}:
      blocked  → open dependencies (detail = list of open #s, or 'meta' on overflow)
      resolved → already closed by a merged PR (detail = pr number)
      valid    → ready to work

    `siblings` are the other issues in a bulk set — stories being built in the
    same commit series on the same branch. A dependency on one of those does
    not block, because it is not unmerged work you cannot see; it is work this
    same run is about to write. Everything else is unchanged, so a single-story
    pick (no siblings) behaves exactly as before.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    deps, overflow = wf_core.parse_dependencies(issue['body'])
    if overflow:
        return 'blocked', 'meta-issue (> %d dependencies)' % wf_core.DEP_LIMIT
    open_numbers = []
    for dep in deps:
        if int(dep) in {int(s) for s in (siblings or ())}:
            continue  # built alongside — no need to spend a call on its state
        ok, data, _ = gh_json(['issue', 'view', str(dep), '--repo', repo, '--json', 'state'])
        if ok and data and data.get('state', '').upper() == 'OPEN':
            open_numbers.append(dep)
    open_deps = wf_core.blocking_dependencies(deps, open_numbers, siblings)
    if open_deps:
        return 'blocked', ', '.join('#%d' % d for d in open_deps)
    pr_number = merged_pr_closing(cfg, issue['number'])
    if pr_number is not None:
        return 'resolved', pr_number
    return 'valid', None


def merged_pr_closing(cfg, number):
    """Return the number of a *merged* PR that closes issue `number`, or None.

    Uses GitHub's own parse of closing references (`closingIssuesReferences`) —
    the same authoritative signal `templates/sibling-pr-lookup.md` mandates
    everywhere — rather than a free-text body search. That catches the real
    "merged but the issue is still open" case (a PR merged into a non-default
    base, e.g. a chained story, where GitHub recognises the reference but does
    not auto-close), and never misfires on a stray "closes"/"#N" in prose.

    Returns the lowest such PR number (oldest-first) so the result is
    deterministic when more than one merged PR references the issue.
    """
    query = (
        'query($owner:String!,$repo:String!){'
        ' repository(owner:$owner,name:$repo){'
        ' pullRequests(states:MERGED, first:100,'
        ' orderBy:{field:CREATED_AT, direction:ASC}){'
        ' nodes { number closingIssuesReferences(first:10){ nodes { number } } } } } }'
    )
    ok, data, _ = gh_graphql(query, owner=cfg['org'], repo=cfg['repo'])
    if not ok or not data:
        return None
    try:
        nodes = data['repository']['pullRequests']['nodes']
    except (KeyError, TypeError):
        return None
    for pr in nodes:
        if number in wf_core.closing_issue_numbers(pr.get('closingIssuesReferences')):
            return pr['number']
    return None


def mark_blocked(cfg, issue, detail):
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    run(['gh', 'issue', 'edit', str(issue['number']), '--repo', repo,
         '--remove-assignee', '@me',
         '--remove-label', label(cfg, 'status-in-progress'),
         '--add-label', label(cfg, 'status-blocked')])
    run(['gh', 'issue', 'comment', str(issue['number']), '--repo', repo,
         '--body', 'Blocked — open dependency(ies): %s. Returned to blocked until they close.' % detail])


def clear_lifecycle_label(cfg, number, labels):
    """Strip whatever open-state lifecycle label a now-closed issue still carries.

    Closed/Done issues must not advertise an open-state lifecycle label such as
    `status-ready` or `status-in-review`: the closed state plus the Done board
    column are the authoritative "done" signal, and there is no "done" lifecycle
    label to swap in. Best-effort. Returns the removed label name, or None when
    there was nothing to clear.
    """
    stale = wf_core.current_lifecycle_label(labels, cfg.get('labels', {}))
    if not stale:
        return None
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    run(['gh', 'issue', 'edit', str(number), '--repo', repo, '--remove-label', stale])
    return stale


def close_resolved(cfg, issue, pr_number):
    """Close an already-resolved issue, clear its lifecycle label, move it to Done.

    Returns (board_moved, board_message) so the caller can report whether the
    board mirror was updated — the close itself is the authoritative state, the
    board move is a best-effort mirror.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    run(['gh', 'issue', 'close', str(issue['number']), '--repo', repo,
         '--comment', 'Closing — already resolved by #%s.' % pr_number])
    clear_lifecycle_label(cfg, issue['number'], issue.get('labels', []))
    return board_move(cfg, issue['number'], 'Done')


# ── board move + branch (--checkout) ─────────────────────────────────────────

def board_move_in_progress(cfg, number):
    """Move the issue to the In Progress column. Returns (moved, message)."""
    return board_move(cfg, number, 'In Progress')


def board_move(cfg, number, column_name):
    """Move the issue's board item to the named Status column. Returns (moved, message).

    Best-effort and gated on a configured board: with no `project-node-id`
    the board is simply not in use, so this is a silent no-op. The column is
    resolved by name (case-insensitive) against the live Status field options,
    so the same code moves an issue to In Progress, In Review, or Done.
    """
    board = cfg.get('board', {})
    node = board.get('project_node_id')
    if not node:
        return False, 'no board configured'
    title_cfg = board.get('project_title')
    ok, data, err = gh_graphql(
        'query($id:ID!){ node(id:$id){ ... on ProjectV2 { title } } }', id=node)
    if not ok or not data or not data.get('node'):
        return False, 'board identity check failed (%s)' % err
    live_title = data['node'].get('title')
    if title_cfg and live_title != title_cfg:
        return False, "board node resolves to '%s' but config says '%s' — skipping" % (live_title, title_cfg)

    ok, data, err = gh_graphql(
        'query($owner:String!,$repo:String!,$number:Int!){'
        ' repository(owner:$owner,name:$repo){ issue(number:$number){ id'
        ' projectItems(first:20){ nodes { id project { id } } } } } }',
        owner=cfg['org'], repo=cfg['repo'], number=number)
    if not ok or not data:
        return False, 'item lookup failed (%s)' % err
    issue_node = data['repository']['issue']
    item_id = next((n['id'] for n in issue_node['projectItems']['nodes']
                    if n['project']['id'] == node), None)
    if not item_id:
        ok, data, err = gh_graphql(
            'mutation($project:ID!,$content:ID!){ addProjectV2ItemById('
            'input:{projectId:$project,contentId:$content}){ item { id } } }',
            project=node, content=issue_node['id'])
        if not ok or not data:
            return False, 'could not add issue to board (%s)' % err
        item_id = data['addProjectV2ItemById']['item']['id']

    field_name = board.get('status_field_name', 'Status')
    ok, data, err = gh_graphql(
        'query($id:ID!,$fname:String!){ node(id:$id){ ... on ProjectV2 {'
        ' field(name:$fname){ ... on ProjectV2SingleSelectField { id options { id name } } } } } }',
        id=node, fname=field_name)
    if not ok or not data or not data.get('node', {}).get('field'):
        return False, 'could not resolve %s field (%s)' % (field_name, err)
    field = data['node']['field']
    option_id = next((o['id'] for o in field['options']
                      if o['name'].strip().lower() == column_name.strip().lower()), None)
    if not option_id:
        return False, "no '%s' column on the board" % column_name

    ok, _, err = gh_graphql(
        'mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){ updateProjectV2ItemFieldValue('
        'input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){'
        ' projectV2Item { id } } }',
        p=node, i=item_id, f=field['id'], o=option_id)
    if not ok:
        return False, 'board mutation failed (%s)' % err
    return True, 'moved to %s' % column_name


def checkout_branch(cfg, issue):
    """Create/check out the working branch. Returns (branch, checked_out, message)."""
    default = cfg['default_branch']
    branch = wf_core.branch_name(cfg['branch_convention'], issue['number'], issue['title'])
    run(['git', 'fetch', 'origin', default])
    local = run(['git', 'branch', '--list', branch])[1].strip()
    remote = run(['git', 'ls-remote', '--heads', 'origin', branch])[1].strip()
    if local or remote:
        code, _, err = run(['git', 'checkout', branch])
        if code != 0:
            return branch, False, 'branch exists but checkout failed (%s)' % err.strip()
        code, _, err = run(['git', 'rebase', 'origin/%s' % default])
        if code != 0:
            run(['git', 'rebase', '--abort'])
            return branch, True, 'checked out, but rebase onto %s conflicts — resolve before working' % default
        return branch, True, 'checked out existing branch, rebased onto %s' % default
    code, _, err = run(['git', 'checkout', '-b', branch, 'origin/%s' % default])
    if code != 0:
        return branch, False, 'could not create branch (%s)' % err.strip()
    return branch, True, 'created from origin/%s' % default


# ── PR pickers (code-review pools) ────────────────────────────────────────────

def _norm_pr(raw):
    return {
        'number': raw['number'],
        'title': raw.get('title', '') or '',
        'labels': [l['name'] for l in raw.get('labels', [])],
        'branch': raw.get('headRefName', '') or '',
        'url': raw.get('url', '') or '',
    }


def assemble_prs(cfg, mine):
    """Fetch open PRs (optionally only @me's). Returns (ok, prs, err)."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['pr', 'list', '--repo', repo, '--state', 'open',
            '--json', 'number,title,labels,headRefName,url', '--limit', '200']
    if mine:
        args += ['--assignee', '@me']
    ok, data, err = gh_json(args)
    if not ok:
        return False, None, err
    return True, [_norm_pr(r) for r in data or []], ''


# Color + description for each review-state purpose, mirroring
# templates/label-reference.md → Review State Labels. Used only by the
# review-finish readback to recreate a verdict label the repo is missing
# (guarded create, never `--force`).
REVIEW_LABEL_META = {
    'needs-review': ('C2E0C6', 'Open PR awaiting its first review'),
    'reviewing': ('0E8A16', 'Review in progress'),
    'approved': ('1D76DB', 'Ready for human merge'),
    'changes-requested': ('E4E669', 'Issues need human action'),
    'needs-discussion': ('D93F0B', 'Architectural questions'),
    'needs-re-review': ('FBCA04', 'New commits since last review'),
    'failed': ('B60205', 'Review could not complete'),
    'updating': ('0E8A16', 'Builder addressing feedback'),
    'fixes-applied': ('5319E7', 'Claude pushed fix commits (sticky)'),
}


def pr_label_names(cfg, number):
    """Read a PR's current label names. Returns (names_or_None, err)."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['pr', 'view', str(number), '--repo', repo, '--json', 'labels'])
    if not ok or not data:
        return None, err
    return [l['name'] for l in data.get('labels', [])], ''


def apply_pr_labels(cfg, number, add, remove=None):
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['pr', 'edit', str(number), '--repo', repo, '--add-label', add]
    if remove:
        args += ['--remove-label', remove]
    code, _, err = run(['gh'] + args)
    if code != 0:
        eprint('wf: warning — could not apply PR label (%s)' % err.strip())


def checkout_pr(cfg, number):
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    code, _, err = run(['gh', 'pr', 'checkout', str(number), '--repo', repo])
    if code != 0:
        return False, 'gh pr checkout failed (%s)' % err.strip()
    return True, 'checked out the PR branch'


def claim_first_pr(pool, apply_marker, no_claim=False):
    """Walk the ordered pool, claim the first PR we win, apply its marker.

    Unlike stories there is no per-candidate validation — the first successful
    claim is the selection. Returns (outcome, selected_pr_or_None, side_effects)
    where outcome is:
      'ok'    — a PR is selected (claimed and marked, or — in no_claim mode —
                simply chosen without a lock).
      'none'  — the pool was exhausted; every candidate was lost to a rival.
      'error' — a claim push failed for a non-rival reason (no write access,
                network); abort rather than walking on.

    With no_claim=True (read-only review, which has no push access), the first
    pool item is returned as-is — no ref is pushed and no marker is applied.
    """
    side_effects = []
    for pr in pool:
        if no_claim:
            return 'ok', pr, side_effects
        outcome = acquire_claim('pr-%d' % pr['number'])
        if outcome == 'error':
            return 'error', None, side_effects
        if outcome == 'lost':
            side_effects.append({'pr': pr['number'], 'action': 'claim-lost'})
            continue
        apply_marker(pr)
        return 'ok', pr, side_effects
    return 'none', None, side_effects


# ── commands ─────────────────────────────────────────────────────────────────

def prepare_cfg():
    """Shared command preamble: verify environment + load config, or emit+exit."""
    env_err = check_environment()
    if env_err:
        emit('error', EXIT_ENV, reason=env_err)
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    if not cfg.get('org') or not cfg.get('repo'):
        emit('error', EXIT_ENV, reason='org/repo missing from config')
    return cfg


def auto_ready_scan(cfg):
    """Scan blocked issues and restore any whose dependencies are all closed.

    Mirrors story-selection-auto-ready.md Step 4: fetch issues with the
    status-blocked label, parse their dependency markers, check whether all
    referenced issues are now closed, and if so swap their label to
    status-ready so the next selection round can pick them.

    Returns the count of issues restored (0 means nothing was unblocked).
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    blocked_label = label(cfg, 'status-blocked')
    ready_label = label(cfg, 'status-ready')
    ok, data, _ = gh_json(['issue', 'list', '--repo', repo, '--state', 'open',
                            '--label', blocked_label,
                            '--json', 'number,body', '--limit', '100'])
    if not ok or not data:
        return 0
    restored = 0
    for raw in data:
        deps, overflow = wf_core.parse_dependencies(raw.get('body', ''))
        if overflow or not deps:
            continue
        all_closed = True
        for dep in deps:
            dep_ok, dep_data, _ = gh_json(
                ['issue', 'view', str(dep), '--repo', repo, '--json', 'state'])
            if not dep_ok or not dep_data or dep_data.get('state', '').upper() != 'CLOSED':
                all_closed = False
                break
        if all_closed:
            code, _, _ = run(['gh', 'issue', 'edit', str(raw['number']), '--repo', repo,
                              '--remove-label', blocked_label,
                              '--add-label', ready_label])
            if code == 0:
                run(['gh', 'issue', 'comment', str(raw['number']), '--repo', repo,
                     '--body', 'Dependencies resolved — restored to ready.'])
                restored += 1
    return restored


def claim_validate_walk(cfg, pool, backlog_mode, siblings=()):
    """Walk the ordered pool: claim the top, validate only that one, act.

    The single claim-first/validate-lazily loop shared by auto-pick and the
    explicit `--issue` path. For each candidate it acquires the atomic claim,
    applies the in-progress marker, then validates: a dependency-blocked issue
    is returned to `status-blocked`, an already-resolved one is closed **and
    moved to Done**, and the claim is released in both cases before walking on.
    The first valid claim is returned as the selection.

    `siblings` is passed straight to `validate_issue` — the other stories of a
    bulk set, whose still-open state does not block a candidate that is being
    built alongside them.

    Returns (selected_or_None, side_effects). Emits + exits on a hard claim
    error (no push access / remote failure), never on a lost claim.
    """
    side_effects = []
    for cand in pool:
        target = 'issue-%d' % cand['number']
        outcome = acquire_claim(target)
        if outcome == 'error':
            emit('error', EXIT_ENV,
                 reason='could not write claim ref %s — no push access to '
                        'refs/claims/* or a remote failure (not a lost claim)' % target,
                 backlog_mode=backlog_mode, side_effects=side_effects)
        if outcome == 'lost':
            side_effects.append({'issue': cand['number'], 'action': 'claim-lost'})
            continue
        apply_in_progress(cfg, cand)
        verdict, detail = validate_issue(cfg, cand, siblings)
        if verdict == 'blocked':
            mark_blocked(cfg, cand, detail)
            release_claim(target)
            side_effects.append({'issue': cand['number'], 'action': 'marked-blocked', 'detail': detail})
            continue
        if verdict == 'resolved':
            board_moved, _ = close_resolved(cfg, cand, detail)
            release_claim(target)
            side_effects.append({'issue': cand['number'], 'action': 'closed-already-resolved',
                                 'pr': detail, 'board_moved_done': board_moved})
            continue
        return cand, side_effects
    return None, side_effects


def fetch_issue_candidate(cfg, number):
    """Fetch one issue as a normalized candidate for the explicit `--issue` path.

    Emits + exits when the issue cannot be worked: not found (error) or already
    closed (all-blocked — there is nothing to pick, and closing-on-pickup only
    applies to *open* issues a merged PR resolved). Otherwise returns the
    single normalized candidate for `claim_validate_walk`.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['issue', 'view', str(number), '--repo', repo,
                             '--json', 'number,title,labels,body,milestone,url,state'])
    if not ok or not data:
        emit('error', EXIT_ENV, reason='could not read issue #%d (%s)' % (number, err))
    if (data.get('state') or '').upper() == 'CLOSED':
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='issue #%d is already closed — nothing to pick' % number,
             number=number)
    return _norm_issue(data)


def cmd_pick(args):
    env_err = check_environment()
    if env_err:
        emit('error', EXIT_ENV, reason=env_err)

    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    if not cfg.get('org') or not cfg.get('repo'):
        emit('error', EXIT_ENV, reason='org/repo missing from config')

    # Stories being built alongside this one on a shared branch (bulk-execute).
    # A dependency on one of them is satisfied by this same run, so it does not
    # block; every other open dependency still does.
    siblings = [int(n) for n in (getattr(args, 'sibling', None) or [])]

    # Explicit target: skip selection/sort entirely and run the same claim +
    # validate machinery against the one named issue, so the explicit-number
    # path auto-closes an already-resolved story exactly like auto-pick does.
    if getattr(args, 'issue', None):
        cand = fetch_issue_candidate(cfg, args.issue)
        selected, side_effects = claim_validate_walk(cfg, [cand], None, siblings)
        if not selected:
            emit('all-blocked', EXIT_ALL_BLOCKED,
                 reason='issue #%d is not workable (claimed away, blocked, or '
                        'already resolved by a merged PR)' % args.issue,
                 side_effects=side_effects)
        finish_pick(args, cfg, selected, side_effects, backlog_mode=None)

    # On a type-capable org, feature/maintenance modes filter by native
    # issueType instead of the type-* label. Fetch once before selection.
    type_map = None
    if args.mode != 'story' and cfg.get('type_capable'):
        ok_t, type_map, t_err = fetch_native_types(cfg)
        if not ok_t:
            eprint('wf: native type query failed (%s); falling back to label filtering' % t_err)
            type_map = None
        elif type_map:
            eprint('wf: type-capable org — filtering %s mode by native issueType' % args.mode)

    gate = cfg.get('ready_gate', 'label')
    if gate not in ('label', 'none', 'board-column', 'both'):
        emit('unsupported', EXIT_UNSUPPORTED,
             reason="ready-gate %r not recognised" % gate)

    ok, issues, err = assemble_candidates(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)

    backlog_mode, issues = narrow_to_sprint(cfg, issues)
    pool = wf_core.select_pool(issues, mode=args.mode,
                               agent_gating=cfg.get('agent_gating', 'disabled'),
                               project_map=cfg.get('labels', {}),
                               type_map=type_map)

    selected, side_effects = None, []
    if pool:
        selected, side_effects = claim_validate_walk(cfg, pool, backlog_mode, siblings)

    if not selected:
        restored = auto_ready_scan(cfg)
        if restored:
            eprint('wf: auto-ready scan restored %d issue(s) — retrying' % restored)
            ok, issues, err = assemble_candidates(cfg)
            if ok and issues:
                backlog_mode, issues = narrow_to_sprint(cfg, issues)
                pool = wf_core.select_pool(issues, mode=args.mode,
                                           agent_gating=cfg.get('agent_gating', 'disabled'),
                                           project_map=cfg.get('labels', {}),
                                           type_map=type_map)
                if pool:
                    selected, more_effects = claim_validate_walk(cfg, pool, backlog_mode,
                                                                 siblings)
                    side_effects.extend(more_effects)

    if not selected and not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='no ready, unassigned issues match', backlog_mode=backlog_mode)
    if not selected:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='every candidate was claimed-away, blocked, or already resolved',
             backlog_mode=backlog_mode, side_effects=side_effects)

    finish_pick(args, cfg, selected, side_effects, backlog_mode)


def finish_pick(args, cfg, selected, side_effects, backlog_mode):
    """Build the `ok` result for a selected story, optionally checking out, and emit."""
    result = {
        'number': selected['number'],
        'title': selected['title'],
        'url': selected['url'],
        'labels': selected['labels'],
        'milestone': selected['milestone'],
        'body': selected['body'],
        'claim_ref': 'refs/claims/issue-%d' % selected['number'],
        'mode': getattr(args, 'mode', 'story'),
        'backlog_mode': backlog_mode,
        'side_effects': side_effects,
        'checked_out': False,
    }
    siblings = [int(n) for n in (getattr(args, 'sibling', None) or [])]
    if siblings:
        result['siblings'] = siblings

    if args.checkout:
        moved, board_msg = board_move_in_progress(cfg, selected['number'])
        result['board_moved'] = moved
        result['board_message'] = board_msg
        if not moved and board_msg != 'no board configured':
            eprint('wf: board move skipped — %s' % board_msg)
        if getattr(args, 'no_branch', False):
            # Bulk runs: every story in the set gets the claim, the marker and
            # the board move, but they all share one branch the caller creates
            # once. Branching per story here would give each its own.
            result['branch'] = None
            result['branch_message'] = 'branch skipped (--no-branch) — caller owns the branch'
        else:
            branch, checked_out, branch_msg = checkout_branch(cfg, selected)
            result['branch'] = branch
            result['checked_out'] = checked_out
            result['branch_message'] = branch_msg
            if not checked_out:
                eprint('wf: %s' % branch_msg)

    emit('ok', EXIT_OK, **result)


def cmd_candidates(args):
    """List the ready pool in priority order, claiming nothing.

    `pick` collapses select-claim-branch into one call, which is exactly right
    when the caller wants *a* story. `bulk-execute` needs the opposite: it has
    to see the pool before it can decide which two to five stories belong in
    one pull request, and that decision is a judgement about relatedness that
    no sort order can make. This command gives it the same filtered, sorted
    pool `pick` would walk — ready gate, sprint narrowing, refinement and
    agent-gating filters, mode filter, priority sort — and then stops. Nothing
    is claimed, nothing is labelled, no board moves. The caller picks its set
    and claims each member with `pick --issue`.

    Bodies are truncated to `--body-chars` (0 for the whole body). The relevant
    part for judging relatedness is the opening Context/Requirements, and a
    full pool of untruncated bodies is a large read for a decision that does
    not need it.
    """
    env_err = check_environment()
    if env_err:
        emit('error', EXIT_ENV, reason=env_err)

    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    if not cfg.get('org') or not cfg.get('repo'):
        emit('error', EXIT_ENV, reason='org/repo missing from config')

    type_map = None
    if args.mode != 'story' and cfg.get('type_capable'):
        ok_t, type_map, t_err = fetch_native_types(cfg)
        if not ok_t:
            eprint('wf: native type query failed (%s); falling back to label filtering' % t_err)
            type_map = None

    gate = cfg.get('ready_gate', 'label')
    if gate not in ('label', 'none', 'board-column', 'both'):
        emit('unsupported', EXIT_UNSUPPORTED, reason="ready-gate %r not recognised" % gate)

    ok, issues, err = assemble_candidates(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)

    backlog_mode, issues = narrow_to_sprint(cfg, issues)
    pool = wf_core.select_pool(issues, mode=args.mode,
                               agent_gating=cfg.get('agent_gating', 'disabled'),
                               project_map=cfg.get('labels', {}),
                               type_map=type_map)
    if not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='no ready, unassigned issues match', backlog_mode=backlog_mode)

    total = len(pool)
    if args.limit and args.limit > 0:
        pool = pool[:args.limit]

    listed = []
    for cand in pool:
        body = cand.get('body') or ''
        truncated = False
        if args.body_chars and args.body_chars > 0 and len(body) > args.body_chars:
            body, truncated = body[:args.body_chars], True
        deps, dep_overflow = wf_core.parse_dependencies(cand.get('body'))
        listed.append({
            'number': cand['number'],
            'title': cand['title'],
            'url': cand.get('url', ''),
            'labels': cand.get('labels', []),
            'milestone': cand.get('milestone'),
            'body': body,
            'body_truncated': truncated,
            'dependencies': deps,
            'dependency_overflow': dep_overflow,
        })

    emit('ok', EXIT_OK, mode=args.mode, backlog_mode=backlog_mode,
         total=total, listed=len(listed), candidates=listed)


def cmd_update_next(args):
    cfg = prepare_cfg()
    names = wf_core.review_names(cfg.get('review_labels'))
    ok, prs, err = assemble_prs(cfg, mine=True)
    if not ok:
        emit('error', EXIT_ENV, reason='PR fetch failed: %s' % err)
    pool = wf_core.select_update_pool(prs, names)
    if not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='no PRs assigned to you have feedback to address')

    # Marker: add `updating`, but keep the actionable state label so the
    # code-review skill can make its final relabel decision.
    outcome, selected, side_effects = claim_first_pr(
        pool, lambda pr: apply_pr_labels(cfg, pr['number'], add=names['updating']))
    if outcome == 'error':
        emit('error', EXIT_ENV,
             reason='could not write a PR claim ref — no push access to '
                    'refs/claims/* or a remote failure (not a lost claim)',
             side_effects=side_effects)
    if outcome == 'none':
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='every candidate PR is already claimed by another agent',
             side_effects=side_effects)

    result = {
        'kind': 'pr-update',
        'number': selected['number'], 'title': selected['title'],
        'url': selected['url'], 'branch': selected['branch'],
        'labels': selected['labels'],
        'claim_ref': 'refs/claims/pr-%d' % selected['number'],
        'prior_state': wf_core.actionable_update_label(selected['labels'], names),
        'side_effects': side_effects, 'checked_out': False,
    }
    if args.checkout:
        okc, msg = checkout_pr(cfg, selected['number'])
        result['checked_out'] = okc
        result['checkout_message'] = msg
        if not okc:
            eprint('wf: %s' % msg)
    emit('ok', EXIT_OK, **result)


def cmd_review_next(args):
    cfg = prepare_cfg()
    names = wf_core.review_names(cfg.get('review_labels'))
    ok, prs, err = assemble_prs(cfg, mine=False)
    if not ok:
        emit('error', EXIT_ENV, reason='PR fetch failed: %s' % err)
    pool = wf_core.select_review_pool(prs, names)
    if not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES, reason='no open PRs need review')

    def marker(pr):
        labels = set(pr['labels'])
        prior = names['needs-re-review'] if names['needs-re-review'] in labels else names['needs-review']
        apply_pr_labels(cfg, pr['number'], add=names['reviewing'], remove=prior)

    no_claim = getattr(args, 'no_claim', False)
    outcome, selected, side_effects = claim_first_pr(pool, marker, no_claim=no_claim)
    if outcome == 'error':
        emit('error', EXIT_ENV,
             reason='could not write a PR claim ref — no push access to '
                    'refs/claims/* or a remote failure (not a lost claim)',
             side_effects=side_effects)
    if outcome == 'none':
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='every candidate PR is already claimed by another agent',
             side_effects=side_effects)

    result = {
        'kind': 'pr-review',
        'number': selected['number'], 'title': selected['title'],
        'url': selected['url'], 'branch': selected['branch'],
        'labels': selected['labels'],
        # In read-only (no_claim) mode nothing was locked or relabelled, so
        # there is no claim ref to release and the `reviewing` marker is absent.
        'claimed': not no_claim,
        'claim_ref': None if no_claim else 'refs/claims/pr-%d' % selected['number'],
        'side_effects': side_effects, 'checked_out': False,
    }
    if args.checkout:
        okc, msg = checkout_pr(cfg, selected['number'])
        result['checked_out'] = okc
        result['checkout_message'] = msg
        if not okc:
            eprint('wf: %s' % msg)
    emit('ok', EXIT_OK, **result)


def cmd_review_finish(args):
    """Reconcile a reviewed PR's state labels to exactly the verdict label.

    Encodes the code-review skill's Step 10/10b deterministic label dance:
    read the PR's labels, strip every stale review-state label, leave exactly
    the verdict label (keeping the sticky `fixes-applied` when fixes were
    pushed), then read back and — if the verdict label did not stick because
    the repo lacks it — create it guarded (no `--force`) and re-apply. The
    label decisions are the pure, tested `wf_core` functions; this shell only
    does the `gh` I/O.
    """
    cfg = prepare_cfg()
    names = wf_core.review_names(cfg.get('review_labels'))
    repo = '%s/%s' % (cfg['org'], cfg['repo'])

    current, err = pr_label_names(cfg, args.pr)
    if current is None:
        emit('error', EXIT_ENV, reason='could not read PR #%d labels (%s)' % (args.pr, err))

    add, remove = wf_core.reconcile_review_labels(
        current, args.verdict, names, fixes_applied=args.fixes_applied)
    if add or remove:
        edit = ['gh', 'pr', 'edit', str(args.pr), '--repo', repo]
        for a in add:
            edit += ['--add-label', a]
        for r in remove:
            edit += ['--remove-label', r]
        code, _, eerr = run(edit)
        if code != 0:
            eprint('wf: review-finish label edit warning (%s)' % eerr.strip())

    target = names[args.verdict]
    created_label = False
    after, _ = pr_label_names(cfg, args.pr)
    if after is not None and wf_core.review_label_missing(after, args.verdict, names):
        color, desc = REVIEW_LABEL_META.get(args.verdict, ('ededed', 'review-state label'))
        run(['gh', 'label', 'create', target, '--repo', repo,
             '--description', desc, '--color', color])
        run(['gh', 'pr', 'edit', str(args.pr), '--repo', repo, '--add-label', target])
        created_label = True
        after, _ = pr_label_names(cfg, args.pr)

    verified = after is not None and target in after
    if not verified:
        eprint('wf: review-finish could not confirm %r on PR #%d' % (target, args.pr))
    emit('ok', EXIT_OK, pr=args.pr, verdict=args.verdict, verdict_label=target,
         added=add, removed=remove, created_label=created_label,
         verified=verified, labels=after)


def cmd_post_merge(args):
    """Settle a merged PR's linked issues: force-close any still open, move all to Done.

    GitHub only auto-closes a linked issue when the PR carried a recognised
    closing keyword **and** merged into the default branch — so a chained-story
    PR (non-default base) or an unparsed reference leaves the issue open with
    nothing to notice. And even when the issue does auto-close, nothing moves
    its board item out of In Review. This makes both deterministic: for every
    issue the PR closes (GitHub's own `closingIssuesReferences` parse, plus any
    `--issue` the caller names for an unrecognised reference), close it if still
    open and move its board item to Done.
    """
    cfg = prepare_cfg()
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['pr', 'view', str(args.pr), '--repo', repo,
                             '--json', 'number,state,mergedAt,baseRefName,closingIssuesReferences'])
    if not ok or not data:
        emit('error', EXIT_ENV, reason='could not read PR #%d (%s)' % (args.pr, err))
    if (data.get('state') or '').upper() != 'MERGED':
        emit('not-merged', EXIT_ALL_BLOCKED,
             reason='PR #%d is %s, not MERGED — refusing to close its issues'
                    % (args.pr, data.get('state')),
             pr=args.pr)

    # `gh pr view --json` returns the references as a flat list, unlike the
    # GraphQL API (used by merged_pr_closing) which wraps them as {nodes: [...]};
    # closing_issue_numbers normalises both so this can't crash on the shape.
    linked = wf_core.closing_issue_numbers(data.get('closingIssuesReferences'))
    for extra in (args.issue or []):
        if extra not in linked:
            linked.append(extra)

    settled = []
    for number in linked:
        ok, idata, _ = gh_json(['issue', 'view', str(number), '--repo', repo,
                                '--json', 'state,labels'])
        was_open = ok and idata and (idata.get('state') or '').upper() == 'OPEN'
        label_names = [l['name'] for l in (idata or {}).get('labels', [])]
        if was_open:
            run(['gh', 'issue', 'close', str(number), '--repo', repo,
                 '--comment', 'Closing — resolved by merged PR #%d.' % args.pr])
        # A settled issue is Done: strip any open-state lifecycle label it still
        # carries (e.g. a PR that auto-closed the issue but left status-ready on).
        cleared = clear_lifecycle_label(cfg, number, label_names)
        board_moved, board_msg = board_move(cfg, number, 'Done')
        settled.append({'issue': number, 'closed_now': bool(was_open),
                        'lifecycle_label_cleared': cleared,
                        'board_moved_done': board_moved, 'board_message': board_msg})

    emit('ok', EXIT_OK, pr=args.pr, base=data.get('baseRefName'), settled=settled)


def cmd_config(args):
    root = repo_root()
    cache, source = config_paths(root)
    if not os.path.isfile(source):
        emit('error', EXIT_ENV, reason='no ClaudeProject.md at %s' % root)
    with open(source, encoding='utf-8') as fh:
        cfg = parse_claude_project(fh.read())
    cfg['review_labels'] = load_review_labels(root)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, 'w', encoding='utf-8') as fh:
        json.dump(cfg, fh, indent=2)
        fh.write('\n')
    emit('ok', EXIT_OK, wrote=os.path.relpath(cache, root), config=cfg)


def build_parser():
    parser = argparse.ArgumentParser(prog='wf', description='github-workflow programmatic picker')
    sub = parser.add_subparsers(dest='command', required=True)

    pick = sub.add_parser('pick', help='claim the next story and return it as JSON')
    pick.add_argument('--mode', default='story', choices=['story', 'feature', 'maintenance'],
                      help='selection mode; feature/maintenance filter by type-* label '
                           'on label-typed projects and by native issueType on '
                           'type-capable orgs')
    pick.add_argument('--issue', type=int, default=None,
                      help='target this specific issue instead of auto-selecting; runs the '
                           'same claim + validate machinery (auto-closes it if a merged PR '
                           'already resolved it)')
    pick.add_argument('--checkout', action='store_true',
                      help='also move the board to In Progress and create/check out the branch')
    pick.add_argument('--no-branch', action='store_true',
                      help='with --checkout, move the board but do not create or check out '
                           'a branch — for bulk runs where several stories share one branch '
                           'the caller creates')
    pick.add_argument('--sibling', type=int, action='append', default=None,
                      help='an issue being built alongside this one on the same branch '
                           '(repeatable); a dependency on one of them does not block the '
                           'pick, because this run writes it too')
    pick.set_defaults(func=cmd_pick)

    cand = sub.add_parser('candidates',
                          help='list the ready pool in priority order without claiming '
                               'anything (bulk-execute chooses its set from this)')
    cand.add_argument('--mode', default='story', choices=['story', 'feature', 'maintenance'],
                      help='selection mode, applied exactly as `pick` applies it')
    cand.add_argument('--limit', type=int, default=25,
                      help='maximum candidates to list, highest priority first (default 25; '
                           '0 for all). `total` always reports the unclipped pool size')
    cand.add_argument('--body-chars', type=int, default=600,
                      help='truncate each body to this many characters (default 600; '
                           '0 for the whole body)')
    cand.set_defaults(func=cmd_candidates)

    pm = sub.add_parser('post-merge',
                        help='settle a merged PR: close any still-open linked issue and '
                             'move every linked issue to Done')
    pm.add_argument('--pr', type=int, required=True, help='the merged PR number')
    pm.add_argument('--issue', type=int, action='append', default=None,
                    help='also settle this issue (repeatable) — for a reference GitHub did '
                         'not parse into closingIssuesReferences')
    pm.set_defaults(func=cmd_post_merge)

    upd = sub.add_parser('update-next',
                         help='claim the next PR of mine that needs review feedback addressed')
    upd.add_argument('--checkout', action='store_true',
                     help='also check out the PR branch (gh pr checkout)')
    upd.set_defaults(func=cmd_update_next)

    rev = sub.add_parser('review-next', help='claim the next PR that needs reviewing')
    rev.add_argument('--checkout', action='store_true',
                     help='also check out the PR branch (gh pr checkout)')
    rev.add_argument('--no-claim', action='store_true',
                     help='select without pushing a claim ref or applying the '
                          'reviewing marker (read-only review, which has no push access)')
    rev.set_defaults(func=cmd_review_next)

    fin = sub.add_parser('review-finish',
                         help='reconcile a reviewed PR to exactly its verdict label '
                              '(strip stale state labels, readback-verify, create-if-missing)')
    fin.add_argument('--pr', type=int, required=True, help='the reviewed PR number')
    fin.add_argument('--verdict', required=True,
                     choices=list(wf_core.REVIEW_VERDICT_KEYS),
                     help='the review verdict; resolves to exactly one state label')
    fin.add_argument('--fixes-applied', action='store_true',
                     help='also ensure the sticky fixes-applied label is present '
                          '(set when Step 7 pushed fix commits)')
    fin.set_defaults(func=cmd_review_finish)

    cfg = sub.add_parser('config', help='emit .claude/wf-config.json from ClaudeProject.md')
    cfg.set_defaults(func=cmd_config)

    caps = sub.add_parser('org-capabilities',
                          help="resolve the org's enabled native issue types and its "
                               'issue fields (with option ids) into '
                               '.claude/issue-fields-cache.json')
    caps.add_argument('--refresh', action='store_true',
                      help='re-query the org instead of reading the cache')
    caps.set_defaults(func=cmd_org_capabilities)

    ia = sub.add_parser('issue-apply',
                        help='create or update fully classified issues from a spec file')
    ia.add_argument('spec', help='path to the JSON spec file')
    ia.add_argument('--repo', default=None,
                    help='apply against this owner/name instead of the configured repo')
    ia.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    ia.add_argument('--dry-run', action='store_true',
                    help='validate the spec and report what would be applied, '
                         'without writing anything')
    ia.set_defaults(func=cmd_issue_apply)

    au = sub.add_parser('issue-audit',
                        help='report open issues missing type, fields or '
                             'dependency edges, and write a backfill spec')
    au.add_argument('--repo', default=None,
                    help='audit this owner/name instead of the configured repo')
    au.add_argument('--limit', type=int, default=None,
                    help='stop after this many issues, newest first')
    au.add_argument('--since', default=None,
                    help='only issues updated since this ISO-8601 timestamp')
    au.add_argument('--out', default=None,
                    help='where to write the backfill spec '
                         '(default .claude/%s)' % AUDIT_SPEC_DEFAULT)
    au.add_argument('--quiet', action='store_true',
                    help='report counts only, keeping the exit code, for CI')
    au.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    au.set_defaults(func=cmd_issue_audit)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
