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
    wf unblock [--dry-run]                # release what the closed edges freed
    wf config                             # emit .claude/wf-config.json from ClaudeProject.md
    wf org-capabilities [--refresh]       # resolve the org's issue types + issue fields
    wf issue-apply <spec.json>            # create/update fully classified issues

Dependencies are read from GitHub's native `blockedBy` edges and written as
the same. Prose in an issue body is never parsed: a body naming a blocker with
no edge behind it is not blocked. The two used to be kept in step and were
not, disagreeing on most of the issues carrying both, with the prose stale
every time.

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
  - Mutations to the *winning* issue (claim, assign, the In Progress move) are
    silent; mutations to *other* issues (marking blocked, closing resolved) are
    always reported back in the `side_effects` array.

Selection covers `--mode story` plus `--mode feature` / `--mode maintenance`,
on both label-typed and type-capable orgs. The pool is one thing on every
project: the unassigned open issues in the board's `Backlog` column. On a type-capable org,
feature/maintenance filter by the native `issueType` field via a single
GraphQL query instead of the `type-*` label; if the query fails, wf
falls back to label filtering gracefully. The selection rules themselves
live in `wf_core.py`.
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
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
EXIT_DRIFT = 26
EXIT_LOST = 27
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
        'labels': {}, 'review_labels': {}, 'fields': {},
        'type_capable': False,
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

    # Neither `## Ready Gate` nor `## Agent Gating` is read. A project that
    # still carries either section is not misconfigured, it is out of date:
    # there is one pool now, the board's Backlog column, and approval is the
    # card being in it. `config-audit` reports a surviving section so it gets
    # deleted rather than believed.

    type_fields_block = _section(text, 'Issue Types & Fields')
    for cells in _rows(type_fields_block):
        if len(cells) >= 2 and cells[0].lower() == 'type-capable':
            cfg['type_capable'] = cells[1].lower() == 'yes'

    # Field-name overrides: a project that renamed an org field records the new
    # name here, and `wf_core.resolve_field_name` prefers it over the default.
    for cells in _rows(type_fields_block):
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


# GitHub caps a connection page at 100, so the board query pages too. Two
# pages of items match the 200-issue window the label gate reads.
BOARD_PAGE_SIZE = 100
# Twenty pages, not two. The query reads *every* card on the board and filters
# to one column afterwards, so the cap is a limit on the whole board rather
# than on the pool: at two pages, a board whose Done column had run past 200
# cards returned an empty Backlog and `pick` reported a finished backlog. A run
# that still has pages left when it reaches this cap is an error rather than a
# short answer -- see `_board_column_candidates`.
BOARD_MAX_PAGES = 20


def _board_items_query(field_name, paged, extra=''):
    """The board-items query, with the `after:` clause only when paging.

    `extra` is appended to the `Issue` selection. `unblock` asks for the native
    `blockedBy` edges that way, so reading a whole column and reading each
    issue's dependencies is one request rather than one plus one per issue.
    """
    return (
        'query($id:ID!%s){ node(id:$id){ ... on ProjectV2 {'
        ' field(name:"%s"){ ... on ProjectV2SingleSelectField { options { name } } }'
        ' items(first:%d%s){'
        '  pageInfo { hasNextPage endCursor }'
        '  nodes {'
        '   fieldValueByName(name:"%s"){ ... on ProjectV2ItemFieldSingleSelectValue { name } }'
        '   content { ... on Issue {'
        '     number title body state url'
        '     labels(first:20){ nodes { name } }'
        '     milestone { title }'
        '     assignees(first:1){ nodes { login } }'
        '     %s'
        '   } }'
        ' } } } } }'
        % (',$cursor:String!' if paged else '',
           field_name.replace('"', '\\"'), BOARD_PAGE_SIZE,
           ',after:$cursor' if paged else '',
           field_name.replace('"', '\\"'), extra))


def _board_column_candidates(cfg, column_name, unassigned_only=True, extra=''):
    """Fetch the open issues in the named board column via GraphQL.

    Returns (ok, issues, err). `unassigned_only` is what the pick pool wants --
    an assigned issue is somebody's already -- and what `unblock` does not: a
    blocked issue can still carry the assignee it had when it was blocked, and
    skipping it would leave it blocked for good.

    A column the board does not have is an error, not an empty pool. It read as
    an empty pool for as long as this function only filtered items by name: the
    board-column gate asked for `Ready` on a board whose columns were Backlog,
    In Progress, In Review, Blocked, Non-code and Done, matched nothing, and
    returned success with no candidates. A misconfigured project and a finished
    backlog produced the same output, and the misconfiguration was the more
    likely of the two. The query now reads the field's options alongside the
    items so the two cases can be told apart.
    """
    board = cfg.get('board', {})
    node = board.get('project_node_id')
    if not node:
        return False, None, 'the pick pool needs a configured board (project-node-id)'
    field_name = board.get('status_field_name', 'Status')
    nodes, options, cursor, pages, truncated = [], None, None, 0, False
    while pages < BOARD_MAX_PAGES:
        args = {'id': node}
        if cursor:
            args['cursor'] = cursor
        ok, data, err = gh_graphql(
            _board_items_query(field_name, bool(cursor), extra), **args)
        if not ok or not data:
            return False, None, 'board-column query failed: %s' % err
        try:
            connection = data['node']['items']
            nodes.extend(connection['nodes'])
        except (KeyError, TypeError):
            return False, None, 'unexpected board-column response shape'
        if options is None:
            field = data['node'].get('field') or {}
            options = [o['name'] for o in field.get('options') or []]
        pages += 1
        page_info = connection.get('pageInfo') or {}
        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')
        if not cursor:
            break
        truncated = pages >= BOARD_MAX_PAGES

    if truncated:
        # A partial read of the board is not a partial pool, it is an unknown
        # one: the cards this run never saw could be the whole of the column it
        # was asked for. Saying so is the difference between "there is nothing
        # to pick" and "I could not find out".
        return False, None, (
            'the board has more than %d cards, which is more than this reads in '
            'one pass, so the %s column cannot be read completely. Archive the '
            'closed cards (the board\'s own `Archive items` view) and re-run.'
            % (BOARD_PAGE_SIZE * BOARD_MAX_PAGES, column_name))

    if not options:
        return False, None, (
            "the board has no '%s' field, so there is no %s column to pick "
            'from' % (field_name, column_name))
    if not any(o.strip().lower() == column_name.strip().lower()
               for o in options):
        return False, None, (
            "the board has no '%s' column, so the pool cannot be read. Its "
            'columns are: %s. Run `/github-workflow:preflight` to create the '
            'missing one.' % (column_name, ', '.join(options)))

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
        if unassigned_only and assignees:
            continue
        issues.append({
            'number': content['number'],
            'title': content.get('title', ''),
            'labels': [l['name'] for l in content.get('labels', {}).get('nodes', [])],
            'body': content.get('body', '') or '',
            'milestone': content.get('milestone', {}).get('title') if content.get('milestone') else None,
            'url': content.get('url', ''),
            'assigned': bool(assignees),
            'assignees': [a.get('login') for a in assignees if a.get('login')],
            'blockedBy': content.get('blockedBy') or {},
        })
    return True, issues, ''


# -- org capability resolution -----------------------------------------------

CAPABILITY_CACHE_NAME = 'issue-fields-cache.json'

# Bumped when a cached record could have been written by a version whose
# conclusion is no longer trusted. An empty record is only believed when it
# carries the current schema, so a cache poisoned by an older version heals
# itself on the next run instead of waiting for someone to know about
# `--refresh`. Version 2: before it, a capability query that failed with a
# NOT_FOUND error was recorded as `owner_kind: user` -- an org read as a
# personal account, cached forever, every issue thereafter created with no
# type and no field values and no error anywhere.
CAPABILITY_CACHE_SCHEMA = 2

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


# The GraphQL error types that mean "this account could not read it", as
# opposed to "it is not there". `NOT_FOUND` is in here because that is what
# GitHub answers for an org the token may not see -- the same org read by an
# authorised token answers normally. Treating it as an absence is what let a
# real organisation be cached as a personal account.
UNREADABLE_ERROR_TYPES = frozenset({'FORBIDDEN', 'NOT_FOUND', 'UNAUTHORIZED'})


def _denied_paths(errors):
    """The query fields an error says this account could not read.

    Returns e.g. {'issueTypes'}, or {'organization'} when the whole org was
    unreadable. An error carrying no usable path still counts, under the name
    `organization`, so a refusal is never silently discarded for want of a
    path.
    """
    denied = set()
    for e in errors or []:
        if (e.get('type') or '').upper() not in UNREADABLE_ERROR_TYPES:
            continue
        named = {part for part in (e.get('path') or []) if isinstance(part, str)}
        denied |= named or {'organization'}
    return denied


def _capability_record_is_usable(cached):
    """Whether a cached capability record can be trusted without re-querying.

    A record carrying no types and no fields is indistinguishable from never
    having resolved. For an org that is almost always a failed lookup that got
    written, so it is treated as a cache miss and re-queried, which lets an
    already-poisoned cache heal itself without anyone knowing to pass
    `--refresh`. A user-owned repo has no issue types by design, so its empty
    record is legitimate and is trusted -- which is what `owner_kind` is for.
    A record written before that key existed, or by a schema version whose
    conclusion is no longer trusted, has no claim to being empty on purpose, so
    it is re-queried once and rewritten -- which is how a cache poisoned by an
    earlier version heals without anyone knowing to pass `--refresh`.
    """
    if cached.get('type_map') or cached.get('field_map'):
        return True
    return (cached.get('owner_kind') == 'user'
            and cached.get('schema') == CAPABILITY_CACHE_SCHEMA)


def resolve_org_capabilities(cfg, refresh=False, root=None):
    """Resolve the org's issue types and fields, through the cache.

    Returns (ok, capabilities, err). `capabilities` carries `type_capable`,
    `type_map` and `field_map`. A cache hit skips the round trip entirely;
    `refresh=True` forces the query and rewrites those three keys.
    """
    if not refresh:
        cached = load_capability_cache(root)
        if 'type_capable' in cached and 'field_map' in cached and (
                _capability_record_is_usable(cached)):
            return True, {'type_capable': cached['type_capable'],
                          'type_map': cached.get('type_map') or {},
                          'field_map': cached.get('field_map') or {},
                          'owner_kind': cached.get('owner_kind') or '',
                          'cached': True}, ''

    data, errors, err = gh_graphql_partial(ORG_CAPABILITY_QUERY, login=cfg['org'])
    if data is None:
        return False, None, 'org capability query failed: %s' % (
            err or json.dumps(errors))

    denied = _denied_paths(errors)
    type_capable, type_map, field_map = parse_org_capabilities(data)
    owner_kind = 'organization' if (data or {}).get('organization') else 'user'
    caps = {'type_capable': type_capable, 'type_map': type_map,
            'field_map': field_map, 'cached': False,
            'owner_kind': owner_kind,
            'denied': sorted(denied),
            'errors': [e.get('message', '') for e in errors]}

    # Never cache a capability the token was refused. A cached `type_capable:
    # false` that really meant "not allowed to look" would make every later run
    # quietly fall back to labels — the silent-blank failure this whole feature
    # exists to stop.
    #
    # An org that answers with no types and no fields is the same failure
    # wearing different clothes: it is what an under-scoped or expired token
    # looks like, and GitHub does not always attach a FORBIDDEN error to say so.
    # Caching that turns one bad round trip into a permanent silent fallback, so
    # it is not written. A user-owned repo genuinely has neither, so that empty
    # is cached and marked, and does not cost a round trip on every run.
    #
    # An empty answer that arrived alongside *any* GraphQL error is not an
    # answer at all, whatever the error says, so `errors` is checked rather
    # than only the ones recognised as refusals.
    empty = not type_map and not field_map
    if not denied and not (empty and (owner_kind == 'organization' or errors)):
        merge_capability_cache({'type_capable': type_capable, 'type_map': type_map,
                                'field_map': field_map,
                                'owner_kind': owner_kind,
                                'schema': CAPABILITY_CACHE_SCHEMA}, root)
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
             reason='the account signed in to gh may not read %s for %s; switch '
                    'accounts (gh auth switch) or grant it access — this is not '
                    'the same as the org having none, and nothing was cached'
                    % (' and '.join(caps['denied']), cfg['org']))

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
ISSUE_FIELD_VALUES_SELECTION = (
    '  issueFieldValues(first:50){ nodes {'
    '   __typename'
    '   ... on IssueFieldSingleSelectValue { field { ... on IssueFieldSingleSelect { name } } name }'
    '   ... on IssueFieldMultiSelectValue { field { ... on IssueFieldMultiSelect { name } } options { name } }'
    '   ... on IssueFieldTextValue { field { ... on IssueFieldText { name } } value }'
    '   ... on IssueFieldDateValue { field { ... on IssueFieldDate { name } } value }'
    '   ... on IssueFieldNumberValue { field { ... on IssueFieldNumber { name } } value }'
    '  } }'
)

ISSUE_SELECTION = (
    '  id number title body'
    '  issueType { name }'
    '  milestone { title }'
    '  parent { number issueType { name } }'
    '  blockedBy(first:50){ nodes { number } }'
    '  labels(first:50){ nodes { name } }'
    + ISSUE_FIELD_VALUES_SELECTION
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


def resolve_spec_context(cfg, label_names, numbers, repo=None,
                         milestone_titles=None):
    """One lookup for everything the batches need before they can be built.

    The repository's node id, the id of every label and open milestone the
    spec names, and the node id of every issue the spec references but does not
    create. Doing this as one query rather than four keeps the whole
    prerequisite phase to a single round trip, which is what leaves room for
    the epic tree itself.

    Returns (ok, context, err).
    """
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    wanted = sorted({int(n) for n in numbers})
    aliases = [('n%d' % n, n) for n in wanted]
    # The native type comes back with the id because the hierarchy rule needs
    # it: a spec that parents a `User Story` to an existing issue is only legal
    # when that issue is a `Feature`, and this is the one place the referenced
    # issues are read. The title and field values come back for the update
    # rules: an update names only what it changes, so whether it leaves the
    # issue without a required value, or two parties on one issue, is only
    # knowable against what the issue already carries.
    issue_parts = ' '.join(
        '%s: issue(number:%d){ id number title issueType { name }'
        ' parent { number issueType { name } }%s }'
        % (alias, number, ISSUE_FIELD_VALUES_SELECTION)
        for alias, number in aliases)
    ok, data, err = gh_graphql(
        'query($owner:String!,$repo:String!){'
        ' repository(owner:$owner,name:$repo){ id'
        ' labels(first:100){ nodes { id name } }'
        ' milestones(first:100,states:OPEN){ nodes { id title } } %s } }'
        % issue_parts,
        owner=owner, repo=name)
    if not ok:
        return False, None, err

    repository = (data or {}).get('repository')
    if not repository:
        return False, None, 'repository %s/%s not found' % (owner, name)

    have_labels = {n['name']: n['id'] for n
                   in (repository.get('labels') or {}).get('nodes') or []}
    wanted_milestones = sorted(set(milestone_titles or ()))
    have_milestones = {n['title']: n['id'] for n
                       in (repository.get('milestones') or {}).get('nodes') or []}
    issues = {}
    issue_types = {}
    issue_parents = {}
    issue_live = {}
    missing_issues = []
    for alias, number in aliases:
        node = repository.get(alias)
        if node:
            issues[number] = node['id']
            issue_types[number] = (node.get('issueType') or {}).get('name')
            issue_live[number] = {'title': node.get('title') or '',
                                  'fields': issue_field_values(node)}
            parent = node.get('parent') or {}
            issue_parents[number] = (
                parent.get('number'),
                (parent.get('issueType') or {}).get('name'))
        else:
            missing_issues.append(number)

    return True, {
        'repo_id': repository['id'],
        'repo': '%s/%s' % (owner, name),
        'labels': {n: have_labels[n] for n in label_names if n in have_labels},
        'missing_labels': [n for n in label_names if n not in have_labels],
        'milestones': {t: have_milestones[t] for t in wanted_milestones
                       if t in have_milestones},
        'missing_milestones': [t for t in wanted_milestones
                               if t not in have_milestones],
        'issues': issues,
        'issue_types': issue_types,
        'issue_parents': issue_parents,
        'issue_live': issue_live,
        'missing_issues': missing_issues,
    }, ''


def resolve_issue_ids(cfg, numbers, repo=None):
    """Node id for each issue number given. Returns {number: id}.

    Only the ids, and only for issues the caller already knows exist — the
    edge-removal path needs a node id for a blocker the spec no longer names,
    which by definition was not in the spec's own resolve pass. A number that
    cannot be read is left out rather than guessed at, and the caller reports
    the edge it could not remove.
    """
    wanted = sorted({int(n) for n in numbers})
    if not wanted:
        return {}
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    found = {}
    for start in range(0, len(wanted), EDGE_BATCH):
        window = wanted[start:start + EDGE_BATCH]
        parts = ' '.join('n%d: issue(number:%d){ id number }' % (n, n)
                         for n in window)
        ok, data, _err = gh_graphql(
            'query($owner:String!,$repo:String!){'
            ' repository(owner:$owner,name:$repo){ %s } }' % parts,
            owner=owner, repo=name)
        if not ok:
            continue
        repository = (data or {}).get('repository') or {}
        for number in window:
            node = repository.get('n%d' % number)
            if node and node.get('id'):
                found[number] = node['id']
    return found


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
    """Apply every dependency edge in one request.

    `ops` are (alias, kind, variables) with kind `'blocked-by'` to add an edge
    or `'unblocked-by'` to remove one. This is the last phase, run once every
    issue in the spec exists and every reference resolves. It used to carry
    body rewrites too, for the `## Dependencies` prose that mirrored these
    edges; the prose is gone and the edge is the whole record.
    """
    decls, body, aliases = [], [], []
    variables = {}
    for alias, kind, args in ops:
        aliases.append(alias)
        mutation = 'removeBlockedBy' if kind == 'unblocked-by' else 'addBlockedBy'
        decls.append('$%s_i:ID!,$%s_b:ID!' % (alias, alias))
        body.append('%s: %s(input:{issueId:$%s_i,blockingIssueId:$%s_b})'
                    '{ issue { id blockedBy(first:%d){ nodes { number } } } }'
                    % (alias, mutation, alias, alias, EDGE_PAGE))
        variables['%s_i' % alias] = args['issue_id']
        variables['%s_b' % alias] = args['blocking_id']
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
    # The trailing `!` on the variable's type is load-bearing. `issueFields` is
    # declared `[IssueFieldCreateOrUpdateInput!]!` on the input object, and
    # GraphQL refuses a nullable variable in a non-null position even when the
    # value passed is a perfectly good list -- "Nullability mismatch on variable
    # $f". Nothing about the value is wrong, so the failure reads as a data
    # problem and is not one. Every field write went through here, so while it
    # was missing no issue metadata reached GitHub at all.
    code, out, err = _graphql_json(
        'mutation($i:ID!,$f:[IssueFieldCreateOrUpdateInput!]!){'
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


def entry_body(entry):
    """The entry's body, from `body` or from the file `body_file` names.

    A body is prose: fenced code, backticks, `$`, quotes and blank lines. The
    caller writing it to a file and naming the file is what keeps it intact,
    because building the JSON string by hand in a shell is where bodies get
    mangled. Read here rather than at load time so the spec file written back
    afterwards still says `body_file`, not a thousand inlined characters.

    Returns (body, err).
    """
    if entry.get('body') is not None:
        return entry['body'], ''
    path = entry.get('body_file')
    if not path:
        return None, ''
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read(), ''
    except OSError as exc:
        return None, 'could not read body_file %s: %s' % (path, exc)


def spec_body_errors(entries):
    """Every `body_file` that cannot be read, before anything is written."""
    out = []
    for entry in entries:
        _, err = entry_body(entry)
        if err:
            out.append('%s: %s' % (wf_core.entry_label(entry), err))
    return out


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


def _create_input(cfg, ctx, caps, entry, plan, parent_id, body, dropped=None):
    """The `createIssue` input for one entry.

    The native issue type is the classification, so the two older ways of
    saying the same thing are taken back out here rather than left to every
    caller: a `type-*` label is dropped, and a `[BUG]`-style title prefix is
    stripped. This happens on every org, including one with no native types --
    a classifier nothing reads is clutter, not a fallback. Doing it at the one
    place that writes an issue is what stops the three commands that create
    issues from each having their own house style. `dropped`, when a list is
    passed, collects what was removed so the run can report it.
    """
    title = wf_core.strip_title_prefix(entry.get('title') or '')
    labels, type_labels = wf_core.strip_type_labels(entry.get('labels') or [],
                                                    cfg.get('labels'))
    if dropped is not None:
        dropped.extend(type_labels)
        raw = entry.get('title') or ''
        if title != raw:
            dropped.append(raw[:len(raw) - len(title)].strip())
    args = {'repositoryId': ctx['repo_id'], 'title': title}
    if body:
        args['body'] = body
    if plan['type']:
        args['issueTypeId'] = caps['type_map'][plan['type']]
    if parent_id:
        args['parentIssueId'] = parent_id
    milestone = entry.get('milestone')
    if milestone:
        args['milestoneId'] = ctx['milestones'][milestone]
    label_ids = sorted(ctx['labels'][label(cfg, l)] for l in labels)
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

        body, _ = entry_body(entry)
        result['sent_body'] = body
        dropped = []
        ready.append(_create_input(cfg, ctx, caps, entry, plan, parent_id, body,
                                   dropped))
        if dropped:
            # Not an error and not silent: the entry asked for something no
            # longer written anywhere, and the caller should stop asking.
            result['changed'].append(
                'dropped %s -- the issue type classifies this issue now'
                % ', '.join(repr(d) for d in dropped))
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
            result['changed'].insert(0, 'created')
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

    milestone = entry.get('milestone')
    if milestone and (current.get('milestone') or {}).get('title') != milestone:
        code, _, merr = run(['gh', 'issue', 'edit', str(entry['number']),
                             '--repo', repo, '--milestone', milestone])
        if code != 0:
            result['errors'].append('milestone update failed: %s' % merr.strip())
            return result
        result['changed'].append('milestone')

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

    The edge is the whole record. A dependency used to be written twice, once
    as the edge and once as `## Dependencies` prose in the body, and the two
    drifted apart on most of the issues carrying both. Only the edge is written
    now, and only the edge is read.

    **An entry that carries `blocked_by` describes the whole set.** An edge the
    issue holds and the entry does not name is removed, which is how a
    dependency that turned out not to exist is taken back off: `wf unblock`
    releases an issue when its blockers *close*, and nothing else could undo an
    edge somebody added by mistake. An entry with no `blocked_by` key says
    nothing about edges, and nothing is added or removed.
    """
    ops, owners, pending_removals = [], [], []
    for plan, result in zip(plans, results):
        entry = plan['entry']
        if result['errors'] or not result.get('number'):
            continue
        restated = 'blocked_by' in entry
        numbers, unresolved = _blockers(entry, resolved)
        if unresolved:
            result['errors'].append(
                'blocked-by references nothing in this spec or repo: %s'
                % ', '.join(str(u) for u in unresolved))
            continue
        result['blocked_by'] = numbers
        if not restated:
            continue

        issue = result.get('issue') or {}
        have = sorted({n['number'] for n
                       in (issue.get('blockedBy') or {}).get('nodes') or []})
        to_add, to_remove = wf_core.edge_diff(have, numbers)
        for blocker in to_add:
            blocking_id = node_ids.get(blocker)
            if not blocking_id:
                result['errors'].append('blocker #%s could not be resolved' % blocker)
                continue
            owners.append((result, 'blocked-by', blocker))
            ops.append(('blocked-by', {'issue_id': result['issue_id'],
                                       'blocking_id': blocking_id}))
        for blocker in to_remove:
            pending_removals.append((result, blocker))

    # An edge being removed points at an issue the spec never mentions, so its
    # node id was not in the prerequisite lookup. One query for all of them,
    # after the loop, rather than one per edge.
    if pending_removals:
        missing = sorted({b for _result, b in pending_removals
                          if b not in node_ids})
        node_ids.update(resolve_issue_ids(cfg, missing))
        for result, blocker in pending_removals:
            blocking_id = node_ids.get(blocker)
            if not blocking_id:
                result['errors'].append(
                    'this entry drops blocked-by #%s, which is on the issue, '
                    'but that issue could not be resolved to remove the edge'
                    % blocker)
                continue
            owners.append((result, 'unblocked-by', blocker))
            ops.append(('unblocked-by', {'issue_id': result['issue_id'],
                                         'blocking_id': blocking_id}))


    for chunk_start in range(0, len(ops), wf_core.BATCH_MAX_NODES):
        window = slice(chunk_start, chunk_start + wf_core.BATCH_MAX_NODES)
        batch = [('b%d' % n, kind, args)
                 for n, (kind, args) in enumerate(ops[window])]
        outcomes = send_link_batch(batch)
        for offset, (result, kind, blocker) in enumerate(owners[window]):
            ok, node, err = outcomes['b%d' % offset]
            if not ok:
                result['errors'].append(
                    '%s #%s failed: %s'
                    % ('removing blocked-by' if kind == 'unblocked-by'
                       else 'blocked-by', blocker, err))
                continue
            result['changed'].append(
                'removed blocked-by #%s' % blocker if kind == 'unblocked-by'
                else 'blocked-by #%s' % blocker)
            result['issue'] = dict(result.get('issue') or {},
                                   blockedBy=node.get('blockedBy') or {})

    # The edge mutations returned the issue's blockers, so the check is free.
    for result in results:
        if 'blocked_by' not in result:
            continue
        have = {n['number'] for n
                in ((result.get('issue') or {}).get('blockedBy')
                    or {}).get('nodes') or []}
        for want in result['blocked_by']:
            if want not in have:
                result['mismatches'].append('#%s: missing blocked-by edge to #%s'
                                            % (result['number'], want))
        for _result, blocker in pending_removals:
            if _result is result and blocker in have:
                result['mismatches'].append(
                    '#%s: blocked-by edge to #%s is still there'
                    % (result['number'], blocker))
    return results


def lifecycle_phase(cfg, plans, results):
    """Put every issue the spec touched in the board lane its own state names.

    The rule is `wf_core.board_column_for`, applied after the edges exist
    because two of its five inputs depend on them: an owner who is a person or
    a browser agent puts the card in Non-code, an explicit `state` on the entry
    puts it where the entry asked, an issue nothing owns goes to Needs
    refinement, an open edge means Blocked, and everything else is Backlog.

    The column is the whole of the answer. Until 10.0.0 this phase wrote a
    lifecycle label as well and the two were meant to agree; they are one thing
    now, so there is nothing to keep in step and no way for the label and the
    board to disagree about what state an issue is in.

    **A card in a lane this phase does not own is left where it is.** The rule
    above describes an issue nobody is working on, and it was applied to every
    issue a spec touched: an update setting a field value on an issue that was
    in progress moved its card back to Backlog, where a second agent could pick
    up work already underway, and an update to a parked issue silently
    un-parked it. `wf_core.AUTO_MANAGED_COLUMNS` is the set this phase may
    write -- Backlog, Blocked, Non-code, plus any issue with no card or no
    lane at all -- and an entry that names a `state` overrides even that,
    because asking for a lane is a decision rather than an inference.

    **A card is placed the first time regardless.** A created issue has no
    card, and an earlier version returned early on the pickable verdict,
    leaving it in the repository and nowhere on the board. That is not
    survivable now the pool *is* the Backlog column: every issue the workflow
    touches leaves it holding a state.

    **An issue whose edges could not be read is not placed at all**, and the
    entry is failed. The lane depends on whether anything blocks the issue, and
    a failed query is not the same answer as "nothing does" -- re-running the
    spec completes the placement, because every write before it is idempotent.

    **A retired label is taken off.** Whatever `status-*`, `priority-*`,
    scope or `needs-refinement` label an issue is still carrying from the label
    workflow is removed here, which is how an existing backlog migrates without
    anyone sweeping it: an issue is cleaned the next time a command touches it,
    and `config-audit` names the ones no command has reached. Labels are read
    live where the run has them (`result['issue']`, which `update_entry` fills
    from its own read-back) and from the spec otherwise, which is what a create
    just applied.

    Ownership is read from the field the spec just wrote where the spec wrote
    one, and from the issue's own value otherwise: an update about a milestone
    says nothing about ownership, and re-deciding the lane without it would
    read an owned issue as unowned.
    """
    numbers = [r['number'] for r in results
               if r.get('number') and not r.get('errors')]
    # Every issue this phase decides about, not only the ones whose spec entry
    # restated a dependency. An update that did not restate `blocked_by` would
    # otherwise look dependency-free and have its card moved out of Blocked.
    # The edges are the record, so they are read for every issue whose lane is
    # about to be decided.
    edge_map, edges_unknown = issue_edges_map(cfg, numbers)
    lanes_ok, current_lanes, lanes_err = board_current_columns(cfg, numbers)
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ownership_field = field_name(cfg, 'field-ownership')
    placements, by_number = {}, {}
    for plan, result in zip(plans, results):
        number = result.get('number')
        if number not in numbers:
            continue
        entry = plan['entry']
        live = result.get('issue') or {}
        live_labels = (live.get('labels') or {}).get('nodes')
        if live_labels is not None:
            names = [n['name'] for n in live_labels]
        else:
            names = [label(cfg, l) for l in (entry.get('labels') or [])]
        owner = (plan.get('fields') or {}).get(ownership_field, {}).get('value')
        if owner is None:
            owner = issue_field_values(live).get(ownership_field)
        scope = wf_core.ownership_scope(owner)
        open_blockers, _closed = wf_core.edge_states(edge_map.get(number) or [])

        retired = wf_core.retired_labels_on(names, cfg.get('labels') or {})
        if retired:
            args = ['gh', 'issue', 'edit', str(number), '--repo', repo]
            for name in retired:
                args.extend(['--remove-label', name])
            code, _, err = run(args)
            if code != 0:
                # Not fatal, and deliberately: the label is cosmetic and the
                # board move below is the part that decides anything. Failing
                # the issue over a label nothing reads would be the old model
                # again, with the label mattering more than the state.
                result['warnings'] = result.get('warnings') or []
                result['warnings'].append('could not remove retired label(s) %s: %s'
                                          % (', '.join(retired), err.strip()))
            else:
                result['changed'].append('cleared retired label(s) %s'
                                         % ', '.join(retired))

        if number in edges_unknown:
            result['errors'].append(
                'could not read the blocked-by edges, so the lane its card '
                'belongs in is unknown and it was not moved — re-run the spec')
            continue

        requested = plan.get('state')
        column = wf_core.BOARD_COLUMN_NAMES[
            wf_core.board_column_for(scope, open_blockers, requested)]
        result['board_column'] = column

        if not lanes_ok:
            result['errors'].append(
                'could not read where its card sits on the board (%s), so it '
                'was not moved — re-run the spec' % lanes_err)
            continue

        allowed, held_in = wf_core.may_place_card(current_lanes.get(number),
                                                  requested)
        if not allowed:
            # Somebody, or some other run, put the card there. An update about
            # a field value does not overrule that.
            result['board_column'] = held_in
            result['board_column_kept'] = held_in
            by_number[number] = result
            continue

        placements[number] = column
        by_number[number] = result

    # One placement request for the whole spec, not one per issue. Placing them
    # individually cost four round trips each, so a thirteen-issue epic tree
    # spent fifty of them re-reading the same board.
    for number, (moved, message) in board_place_many(cfg, placements).items():
        result = by_number[number]
        result['board_moved'] = moved
        if moved:
            continue
        result['board_message'] = message
        if message == 'no board configured':
            # A project with no board at all is a configuration `preflight`
            # fails on, once, rather than something to fail every entry over.
            result['warnings'] = result.get('warnings') or []
            result['warnings'].append('no board configured, so the issue holds '
                                      'no state')
            continue
        # The card is the state. An issue whose card did not move is in the
        # lane it was in — for a create, in no lane at all — so the entry has
        # not finished, and re-running the spec finishes it.
        result['errors'].append('the card did not reach %s (%s) — re-run the '
                                'spec' % (result.get('board_column'), message))

    # `Classification` and `Origin` are not worth refusing an issue over, and
    # they are worth saying out loud. A one-line stderr warning reaches whoever
    # ran the command and nobody else; a comment reaches whoever opens the
    # issue, which is the person who can actually fill the field in. Creates
    # only: an update that did not restate an optional field is not a gap, it
    # is an update about something else.
    for plan, result in zip(plans, results):
        number = result.get('number')
        # `result['action']`, not `entry['number']`: a create writes its new
        # number back onto the entry so the spec file can be updated, so by the
        # time this loop runs every entry has one.
        if number not in by_number or result.get('action') != 'create':
            continue
        body = wf_core.unset_optional_comment(plan.get('unset_optional'))
        if not body:
            continue
        code, _, err = run(['gh', 'issue', 'comment', str(number),
                            '--repo', repo, '--body', body])
        if code == 0:
            result['changed'].append('commented on unset optional field(s)')
        else:
            eprint('wf: warning — could not comment on #%s (%s)'
                   % (number, err.strip()))
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
    body_errors = spec_body_errors(entries)
    if body_errors:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec, errors=body_errors,
             reason='a body_file the spec names could not be read')

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
    milestones = [e['milestone'] for e in entries if e.get('milestone')]
    ok, ctx, err = resolve_spec_context(cfg, label_names, referenced, args.repo,
                                        milestones)
    if not ok:
        emit('error', EXIT_ENV, reason='could not resolve the repository: %s' % err)
    if ctx['missing_labels']:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='labels the spec names do not exist in this repo',
             labels=ctx['missing_labels'])
    if ctx['missing_milestones']:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='milestones the spec names are not open in this repo',
             milestones=ctx['missing_milestones'])
    if ctx['missing_issues']:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='issues the spec references do not exist in this repo',
             issues=ctx['missing_issues'])

    # Epic → Feature → User Story. Checked here rather than in `validate_spec`
    # because a parent may be an issue that already exists, and its type is only
    # known once the referenced issues have been read.
    hierarchy = wf_core.spec_hierarchy_errors(
        plans, ctx['issue_types'], ctx['issue_parents'], caps['type_map'])
    if hierarchy:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec, errors=hierarchy,
             reason='%d %s outside the epic → feature → story tree; nothing '
                    'was written'
                    % (len(hierarchy),
                       'entry sits' if len(hierarchy) == 1 else 'entries sit'))

    # The rules an update can only break against the issue it updates.
    live_errors = wf_core.spec_live_errors(plans, ctx['issue_live'],
                                           cfg.get('fields', {}))
    if live_errors:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec, errors=live_errors,
             reason='%d spec %s against the issues it updates; nothing was written'
                    % (len(live_errors),
                       'error' if len(live_errors) == 1 else 'errors'))

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
    lifecycle_phase(cfg, ordered_plans, results)

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
                                   open_numbers=open_numbers,
                                   type_map=caps.get('type_map') or {},
                                   parents=args.parents)
               for issue in issues]
    with_gaps = [a for a in audited if a['gaps']]
    summary = wf_core.audit_summary(audited)

    # Normalised because `repo_root()` comes back from git with forward
    # slashes and `os.path.join` adds the platform's, which produced a mixed
    # path the user then had to retype by hand.
    # An explicit `--out` is used exactly as the caller typed it, and needs no
    # repo lookup at all.
    root = None if args.out else repo_root()
    spec_path = os.path.normpath(
        args.out or os.path.join(root or '.', '.claude', AUDIT_SPEC_DEFAULT))
    wrote, write_err = (True, '')
    if with_gaps:
        wrote, write_err = write_audit_spec(spec_path,
                                            [a['proposed'] for a in with_gaps])

    # `spec_written` says whether a spec was written, so a clean run says
    # `false` rather than `true` beside a null path -- which read as "the file
    # is there" every time somebody checked whether the backfill had run.
    payload = {'repo': repo, 'summary': summary,
               'spec': spec_path if with_gaps else None,
               'spec_written': bool(with_gaps) and wrote}
    if not wrote:
        payload['write_error'] = write_err
    if not args.quiet:
        payload['issues'] = [{'number': a['number'], 'title': a['title'],
                              'gaps': a['gaps']} for a in with_gaps]

    if not with_gaps:
        emit('ok', EXIT_OK, reason='every open issue in %s carries its type, its '
                                   'field values, an owner and a place in the '
                                   'epic tree' % repo, **payload)

    # Non-zero so the audit can run as a check. The spec it just wrote is the
    # input to the backfill, but it is deliberately not applied here: every gap
    # it cannot fill deterministically is left as a placeholder for a person to
    # decide, and applying a spec full of `TODO` would write the blank metadata
    # this command exists to find.
    # The path is reported relative to the repo when it sits inside it: the
    # absolute form is long enough that printing it twice buried the counts
    # that are the actual result.
    shown = spec_path
    if root:
        try:
            relative = os.path.relpath(spec_path, root)
        except ValueError:
            relative = spec_path
        if not relative.startswith('..'):
            shown = relative
    emit('gaps', EXIT_GAPS,
         reason='%d of %d open issues in %s are missing metadata. Review %s, '
                'fill in every %s, then run: wf.sh issue-apply %s'
                % (summary['issues_with_gaps'], summary['issues_scanned'], repo,
                   shown, wf_core.SPEC_PLACEHOLDER, shown),
         **payload)


# ── config-audit ─────────────────────────────────────────────────────────────
# What preflight runs. It compares three things that drift apart quietly:
# `ClaudeProject.md`, the labels the repo actually carries, and the org's own
# issue-type and field configuration. Every check is read-only.
#
# The decisions all live in `wf_core`; this half fetches and reports. The API
# calls are deliberately few: one org query for the pinning, one repo query that
# carries the labels and the board together, and the capability cache for the
# rest — so preflight stays cheap enough to run at the top of every session.

PINNED_FIELD_QUERY = (
    'query($login:String!){'
    ' organization(login:$login){'
    '  issueTypes(first:50){ nodes {'
    '   name isEnabled'
    '   pinnedFields {'
    '    __typename'
    '    ... on IssueFieldSingleSelect { name }'
    '    ... on IssueFieldMultiSelect { name }'
    '    ... on IssueFieldDate { name }'
    '    ... on IssueFieldText { name }'
    '    ... on IssueFieldNumber { name }'
    '   }'
    '  } }'
    ' } }'
)

_LABEL_PAGE = (
    '  labels(first:100,after:$after){'
    '   pageInfo { hasNextPage endCursor } nodes { name }'
    '  }'
)

REPO_LABEL_QUERY = (
    'query($owner:String!,$repo:String!,$after:String){'
    ' repository(owner:$owner,name:$repo){' + _LABEL_PAGE + ' } }'
)

# Labels and the board in one document, because they are always wanted together
# and GraphQL will answer both from a single round trip.
REPO_LABEL_BOARD_QUERY = (
    'query($owner:String!,$repo:String!,$after:String,$board:ID!,$status:String!){'
    ' repository(owner:$owner,name:$repo){' + _LABEL_PAGE + ' }'
    ' board: node(id:$board){ ... on ProjectV2 {'
    '  title'
    '  field(name:$status){ ... on ProjectV2SingleSelectField {'
    '   id name options { id name } } }'
    ' } } }'
)


def fetch_issue_type_pins(cfg):
    """Which org fields each issue type pins to its form. (ok, types, err).

    `pinnedFields` is a plain list on `IssueType`, not a connection. A token
    that may not read it, or a schema that does not have it, comes back as
    `ok=False` — preflight reports that as a warning rather than pretending
    every type is pinned correctly.
    """
    data, errors, err = gh_graphql_partial(PINNED_FIELD_QUERY, login=cfg['org'])
    org = (data or {}).get('organization') if data else None
    if not org:
        return False, [], (err or json.dumps(errors)
                           or 'no issue types returned for %s' % cfg['org'])
    types = []
    for node in (org.get('issueTypes') or {}).get('nodes') or []:
        if not node or not node.get('name'):
            continue
        types.append({'name': node['name'],
                      'enabled': bool(node.get('isEnabled')),
                      'pinned': [f['name'] for f in node.get('pinnedFields') or []
                                 if f and f.get('name')]})
    return True, types, ''


def fetch_repo_state(cfg, repo=None):
    """Every label in the repo, plus the configured board. (ok, state, err)."""
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    board_id = (cfg.get('board') or {}).get('project_node_id')
    status_name = (cfg.get('board') or {}).get('status_field_name') or 'Status'

    labels, board, cursor, first = [], None, None, True
    while True:
        fields = {'owner': owner, 'repo': name}
        if cursor:
            fields['after'] = cursor
        if first and board_id:
            query = REPO_LABEL_BOARD_QUERY
            fields.update({'board': board_id, 'status': status_name})
        else:
            query = REPO_LABEL_QUERY
        ok, data, err = gh_graphql(query, **fields)
        if not ok:
            return False, None, err
        if first:
            board = (data or {}).get('board')
        page = (((data or {}).get('repository') or {}).get('labels')) or {}
        labels.extend(n['name'] for n in page.get('nodes') or [] if n.get('name'))
        info = page.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return True, {'labels': labels, 'board': board}, ''
        cursor, first = info.get('endCursor'), False


def _board_placement_query(field_name):
    """Where every open issue sits on the board, if it sits anywhere.

    The `Status` value comes back with the card, so one query answers both
    "which issues have no card" and "which cards are in no lane". Those are the
    two ways an issue can be absent from the board's account of the work, and
    both are invisible to every command that reads a lane.

    The labels ride along for the same reason: the retired-label check needs
    every open issue's labels, and that is the same walk. Two paginated scans of
    the same issues to answer two questions about them is a round trip nobody
    gets back. So do the type and sub-issues the finished-container check reads
    (#240), for the same reason.
    """
    return (
        'query($owner:String!,$repo:String!,$after:String){'
        ' repository(owner:$owner,name:$repo){ issues(states:OPEN,first:100,after:$after){'
        ' pageInfo { hasNextPage endCursor }'
        ' nodes { number title state issueType { name }'
        ' subIssues(first:100){ nodes { number state } }'
        ' assignees(first:1){ totalCount }'
        ' labels(first:50){ nodes { name } }'
        ' projectItems(first:20){ nodes { project { id }'
        '  fieldValueByName(name:"%s"){'
        '   ... on ProjectV2ItemFieldSingleSelectValue { name } } } } } } } }'
        % field_name.replace('"', '\\"'))


def fetch_board_placement(cfg, repo=None):
    """What the open issues look like to the board and to the label checks.

    Returns (ok, orphans, unset, labelled, finished, err) -- issues with no
    card, issues whose card holds no `Status` value, every open issue that
    carries any label at all, and every open Epic or Feature whose sub-issues
    are all closed (`{'number', 'title'}`). The first two are the same failure in the end: the column is
    the state, so an issue in neither a card nor a lane is in no state,
    invisible to `pick` and to every other command that reads one.

    Assigned issues are excluded from `orphans` because they are somebody's
    already and adding a card would not change that. They are **not** excluded
    from `unset`: an assigned issue in no lane is exactly the in-progress work
    that has fallen off the board, which is worth saying.

    A project with no board still gets `labelled`: whether the repo's issues
    carry labels that decide nothing is a question about the repo, not about
    the board, and it is answerable either way.
    """
    board = cfg.get('board') or {}
    board_id = board.get('project_node_id')
    field = board.get('status_field_name', 'Status')
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    query = _board_placement_query(field)
    orphans, unset, labelled, finished, cursor = [], [], [], [], None
    while True:
        fields = {'owner': owner, 'repo': name}
        if cursor:
            fields['after'] = cursor
        ok, data, err = gh_graphql(query, **fields)
        if not ok or not data:
            return False, None, None, None, None, err
        page = ((data.get('repository') or {}).get('issues')) or {}
        for node in page.get('nodes') or []:
            names = [n['name'] for n
                     in (node.get('labels') or {}).get('nodes') or []
                     if n.get('name')]
            if names:
                labelled.append({'number': node['number'], 'labels': names})
            if wf_core.container_finished(_container_node(node)):
                finished.append({'number': node['number'],
                                 'title': node.get('title') or ''})
            if not board_id:
                continue
            assigned = ((node.get('assignees') or {}).get('totalCount') or 0) > 0
            items = [i for i in (node.get('projectItems') or {}).get('nodes') or []
                     if (i.get('project') or {}).get('id') == board_id]
            if not items:
                if not assigned:
                    orphans.append(node['number'])
                continue
            if not any((i.get('fieldValueByName') or {}).get('name')
                       for i in items):
                unset.append(node['number'])
        info = page.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return True, orphans, unset, labelled, finished, ''
        cursor = info.get('endCursor')


def plugin_scan_roots(explicit=None):
    """Where to look for files that tell an agent to apply a label.

    Defaults to the plugin this script ships in — `CLAUDE_PLUGIN_ROOT` at
    runtime, the script's own plugin directory otherwise, which is what makes
    the check work in this repo's own checkout.
    """
    if explicit:
        return [os.path.abspath(r) for r in explicit]
    env = os.environ.get('CLAUDE_PLUGIN_ROOT')
    if env and os.path.isdir(env):
        return [os.path.abspath(env)]
    return [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]


# The instruction files a session actually reads before it does anything: the
# project's own `CLAUDE.md` at any depth, and `ClaudeProject.md` beside it.
# Deliberately not every markdown file in the repo -- a design note describing
# what `Ready` used to be is history somebody wrote on purpose, while a
# `CLAUDE.md` saying the same thing is an instruction a session will follow.
INSTRUCTION_FILE_NAMES = ('CLAUDE.md', 'ClaudeProject.md')
INSTRUCTION_SCAN_MAX = 200


def read_instruction_files(root, exclude=()):
    """Every instruction file under `root`, as {relative path: text}.

    `exclude` is the plugin's own directory, which only sits inside the project
    in the plugin's own repository. Its templates are the plugin describing the
    workflow -- including naming what it retired, so a project knows to drop
    it -- and they are held to the plugin's own test suite rather than to a
    check about the project's instructions. Found live: the shipped
    `ClaudeProject.md` template was reported for the sentence telling projects
    that the retired labels decide nothing.
    """
    skip = {os.path.normcase(os.path.abspath(p)) for p in exclude or ()}
    out = {}
    for dirpath, dirnames, filenames in os.walk(root or '.'):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith('.') and d != 'node_modules'
                       and os.path.normcase(os.path.abspath(
                           os.path.join(dirpath, d))) not in skip]
        for name in INSTRUCTION_FILE_NAMES:
            if name not in filenames:
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding='utf-8') as fh:
                    text = fh.read()
            except OSError:
                continue
            out[os.path.relpath(path, root or '.').replace(os.sep, '/')] = text
        if len(out) >= INSTRUCTION_SCAN_MAX:
            return out
    return out


def scan_plugin_labels(roots, base=None):
    """Every concrete label the instruction files under `roots` apply."""
    references = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith('.') and d != 'node_modules']
            for name in sorted(filenames):
                if not name.endswith('.md'):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path, encoding='utf-8') as fh:
                        text = fh.read()
                except OSError:
                    continue
                rel = os.path.relpath(path, base or root).replace(os.sep, '/')
                for ref in wf_core.scan_label_references(text):
                    references.append(dict(ref, file=rel))
    return references


def cmd_config_audit(args):
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    findings, checked, skipped, _ = collect_config_findings(
        cfg, args, repo_root() or '.')
    return _emit_audit(findings, checked, skipped, cfg, args)


def collect_config_findings(cfg, args, root):
    """Every drift finding, plus the live state a `--fix` would need.

    Split out of `cmd_config_audit` so that `preflight` runs exactly the same
    checks rather than a second implementation of them. Returns
    `(findings, checked, skipped, context)`; `context` carries the board
    placement lists so a repair does not have to re-read them.

    Error paths still `emit()` and exit, because a run that cannot read the org
    has not found a clean configuration -- it has found nothing.
    """
    source = config_paths(root)[1]
    source_rel = os.path.basename(source)

    findings, checked, skipped = [], [], []
    context = {'orphans': [], 'unset': [], 'board': None, 'retired_labels': []}

    # ── offline ──────────────────────────────────────────────────────────────
    headings = []
    if os.path.isfile(source):
        with open(source, encoding='utf-8') as fh:
            headings = re.findall(r'^#{1,3}\s+(.+?)\s*$', fh.read(), re.MULTILINE)
    findings.extend(wf_core.config_section_findings(headings, source_rel))
    checked.append('config-section')

    # Retired vocabulary in the project's own instructions. Offline, and worth
    # running first: a `CLAUDE.md` telling a session to look for a `Ready` label
    # sends it to do work no amount of correct board configuration will make
    # right.
    roots = plugin_scan_roots(args.scan)
    findings.extend(wf_core.instruction_findings(
        read_instruction_files(root, exclude=roots)))
    checked.append('instructions-retired')

    references = scan_plugin_labels(roots, base=root)
    checked.append('label-reference')

    if args.offline:
        skipped = ['label-reference', 'config-label', 'label-drift',
                   'field-unpinned', 'field-unmapped', 'field-absent',
                   'field-options', 'label-retired',
                   'board-column', 'board-lane', 'board-retired',
                   'board-orphan', 'board-unset', 'container-finished']
        return findings, ['config-section', 'instructions-retired'], skipped, context

    # ── the repo: labels and the board, in one round trip ────────────────────
    ok, state, err = fetch_repo_state(cfg, args.repo)
    if not ok:
        emit('error', EXIT_ENV, repo='%s/%s' % (cfg['org'], cfg['repo']),
             reason='could not read the repo\'s labels: %s' % err)
    live = state['labels']

    findings.extend(wf_core.label_reference_findings(references, live,
                                                     cfg.get('labels')))
    findings.extend(wf_core.config_label_findings(
        cfg.get('labels'), cfg.get('review_labels'), live, source_rel))
    findings.extend(wf_core.label_drift_findings(live, cfg.get('labels')))
    findings.extend(wf_core.deprecated_label_findings(
        cfg.get('labels'), live, source_rel))
    checked.extend(['config-label', 'label-drift', 'label-deprecated'])

    board_cfg = cfg.get('board') or {}
    context['board'] = state['board']
    has_board = bool(board_cfg.get('project_node_id'))
    if has_board:
        findings.extend(_board_findings(board_cfg, state['board'], source_rel))
        checked.extend(['board-column', 'board-lane', 'board-retired'])

    # One walk of the open issues answers four questions: which have no card,
    # which sit in no lane, which still carry a label that decides nothing, and
    # which Epic or Feature is finished with nothing having closed it (#240).
    ok, orphans, unset, labelled, finished, err = fetch_board_placement(
        cfg, args.repo)
    if not ok:
        findings.append(wf_core.finding(
            wf_core.WARNING, 'board-orphan',
            'could not read the open issues (%s), so whether any are invisible '
            'to `pick`, still carry a retired label or are a finished Epic or '
            'Feature is unverified' % err,
            'check the token and re-run', source_rel))
        skipped.extend(['board-orphan', 'board-unset', 'label-retired',
                        'container-finished'])
    else:
        findings.extend(wf_core.retired_label_findings(
            labelled, cfg.get('labels'), source_rel))
        findings.extend(wf_core.finished_container_findings(finished, source_rel))
        checked.extend(['label-retired', 'container-finished'])
        context['retired_labels'] = labelled
        context['finished_containers'] = finished
        if has_board:
            findings.extend(wf_core.board_orphan_findings(orphans, source_rel))
            findings.extend(wf_core.board_unset_findings(unset, source_rel))
            checked.extend(['board-orphan', 'board-unset'])
            context['orphans'], context['unset'] = orphans, unset
        else:
            skipped.extend(['board-orphan', 'board-unset'])

    if not has_board:
        # Not a skip. Selection reads the board's Backlog column, so a project
        # without a board cannot pick anything at all, and reporting that as
        # "unchecked" is how it stayed invisible.
        findings.append(wf_core.finding(
            wf_core.CRITICAL, 'board-lane',
            'no `project-node-id` is recorded, and the pick pool is a board '
            'column, so `pick` and `candidates` have nothing to read',
            'run `/github-workflow:setup board` to create or record one',
            source_rel))
        checked.append('board-lane')
        skipped.append('board-column')

    # ── the org: field pinning, and fields nothing maps ──────────────────────
    ok, caps, err = resolve_org_capabilities(cfg, refresh=args.refresh)
    if not ok:
        emit('error', EXIT_ENV, reason=err, org=cfg['org'])
    if caps.get('denied'):
        emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
             denied=caps['denied'],
             reason='the authenticated account may not read %s for this org, so '
                    'the org half of the configuration cannot be checked'
                    % ' and '.join(caps['denied']))

    findings.extend(wf_core.unmapped_field_findings(caps['field_map'],
                                                    cfg.get('fields'), source_rel))
    checked.append('field-unmapped')

    # Options on a mandatory field that no decision here knows. This fails
    # silently otherwise: every issue carrying an unrecognised value sorts last.
    findings.extend(wf_core.field_option_findings(
        caps['field_map'], cfg.get('fields'), source_rel))
    checked.append('field-options')

    # A mandatory field the org has not created is the failure every other
    # check here assumes away: the picker reads these five and nothing else,
    # so a missing one is a decision with no input rather than a degraded one.
    findings.extend(wf_core.absent_field_findings(
        caps['field_map'] or {}, cfg.get('fields'), source_rel))
    checked.append('field-absent')

    if caps['type_capable']:
        # Only the mandatory fields the org actually defines. A field nobody
        # has created cannot be pinned to anything, and reporting five types
        # as "not pinned to Ownership" the day that field joined the mandatory
        # set says nothing about the org and buries the findings that do.
        defined = caps['field_map'] or {}
        required = [name for name in
                    (field_name(cfg, k) for k in wf_core.MANDATORY_FIELD_KEYS)
                    if name in defined]
        ok, types, err = fetch_issue_type_pins(cfg)
        if ok:
            findings.extend(wf_core.pinned_field_findings(types, required))
            checked.append('field-unpinned')
        else:
            # Not knowing is not the same as being fine, and reporting it as a
            # pass would recreate the silent blank this command exists to catch.
            findings.append(wf_core.finding(
                wf_core.WARNING, 'pin-unknown',
                'could not read `IssueType.pinnedFields` for %s (%s), so whether '
                'the tooling\'s fields appear on an issue form is unverified'
                % (cfg['org'], err),
                'check the token carries `read:org`, then re-run'))
            skipped.append('field-unpinned')
    else:
        skipped.append('field-unpinned')

    return findings, checked, skipped, context


def _board_findings(board_cfg, live_board, path):
    """The board half: does the recorded snapshot still describe the live board?"""
    if not live_board:
        # Critical since 9.0.0, and it used to warn. A node id that resolves
        # to nothing cost the board moves back when the lifecycle labels were
        # the authority; now the pool is a column on that board, so it costs
        # selection itself.
        return [wf_core.finding(
            wf_core.CRITICAL, 'board-lane',
            '`project-node-id` `%s` does not resolve to a board, so there is '
            'no pool to pick from and every board move is skipped'
            % board_cfg['project_node_id'],
            "record the current board's node id", path)]
    out = []
    title = board_cfg.get('project_title')
    if title and live_board.get('title') and live_board['title'] != title:
        out.append(wf_core.finding(
            wf_core.WARNING, 'board-title',
            '`project-title` says `%s` but the recorded node id resolves to `%s`'
            % (title, live_board['title']),
            'confirm which board this project should write to, then update '
            'either the title or the node id', path))
    field = live_board.get('field') or {}
    options = {o['id']: o['name'] for o in field.get('options') or []}
    out.extend(wf_core.board_column_findings(board_cfg.get('columns'), options,
                                             path))
    out.extend(wf_core.board_lane_findings(options.values(), path))
    out.extend(wf_core.board_retired_findings(options.values(), path))
    return out


def _emit_audit(findings, checked, skipped, cfg, args):
    summary = wf_core.preflight_summary(findings)
    payload = {'org': cfg['org'], 'repo': args.repo or '%s/%s' % (cfg['org'],
                                                                  cfg['repo']),
               'summary': summary, 'checked': checked, 'skipped': skipped}
    if not args.quiet:
        payload['findings'] = findings

    if summary['critical']:
        emit('drift', EXIT_DRIFT,
             reason='%d configuration problem%s will produce wrong behaviour, '
                    'and %d more will degrade it'
                    % (summary['critical'], '' if summary['critical'] == 1 else 's',
                       summary['warning']),
             **payload)
    if summary['warning']:
        # Warnings alone exit zero: they describe a workflow that still does the
        # right thing, and a preflight that blocks on them would train everyone
        # to skip it.
        emit('ok', EXIT_OK,
             reason='no configuration problem will produce wrong behaviour; %d '
                    'will degrade it' % summary['warning'], **payload)
    if skipped:
        # Never report agreement between things this run did not compare.
        emit('ok', EXIT_OK,
             reason='nothing wrong in the %d check%s that ran; %s did not run'
                    % (len(checked), '' if len(checked) == 1 else 's',
                       ', '.join(sorted(set(skipped)))), **payload)
    emit('ok', EXIT_OK,
         reason='ClaudeProject.md, the repo\'s labels and the org\'s issue '
                'configuration agree', **payload)


# ── preflight ────────────────────────────────────────────────────────────────
# `config-audit` answers "does ClaudeProject.md agree with the live repo, board
# and org?". `preflight` answers the question a command actually has before it
# runs: "can this project be worked on at all?" -- which is that, plus the
# file-level checks, plus a `--fix` that repairs the subset a run can repair
# without guessing.
#
# Those file-level checks used to be shell blocks inside
# `skills/preflight/SKILL.md`. Two implementations of one gate is one too many:
# the shell one could not be tested, could not be reused by `bulk-execute`, and
# quietly disagreed with this one about what counted as critical.

_FENCE_RE = re.compile(r'```[a-zA-Z0-9_+-]*\n(.*?)```', re.DOTALL)


def quality_gate_command(text):
    """The command inside the `## Quality Gate` fenced block, or ''."""
    match = _FENCE_RE.search(_section(text, 'Quality Gate'))
    if not match:
        return ''
    for line in match.group(1).splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            return line
    return ''


_REVIEW_CONFIG_RE = re.compile(r'[A-Za-z0-9._/-]*review\.config\.md')


def review_config_reference(text):
    """The review-state label file `ClaudeProject.md` points at, or None."""
    match = _REVIEW_CONFIG_RE.search(text or '')
    return match.group(0) if match else None


def create_board_columns(field_id, existing, wanted):
    """Add the named options to a single-select field. (ok, options, err).

    `updateProjectV2Field` replaces the whole option list rather than adding to
    it, so every existing option is passed back with its `id` -- omit one and
    GitHub deletes it along with every card sitting in it. That is the single
    most destructive thing this file can do, which is why the existing list is
    read from the same response that told us a column was missing rather than
    from the recorded snapshot.

    `gh api graphql` binds scalars only, so the option list is inlined into the
    query text. Every value written here is either an id GitHub gave us or a
    name from `BOARD_COLUMN_NAMES`, so nothing user-supplied reaches it.
    """
    def literal(value):
        return json.dumps(value or '')

    options = []
    for option in existing or ():
        options.append('{id: %s, name: %s, color: %s, description: %s}'
                       % (literal(option.get('id')), literal(option.get('name')),
                          option.get('color') or 'GRAY',
                          literal(option.get('description'))))
    for name in wanted:
        options.append('{name: %s, color: %s, description: %s}'
                       % (literal(name), wf_core.BOARD_COLUMN_COLOURS.get(name, 'GRAY'),
                          literal(wf_core.BOARD_COLUMN_DESCRIPTIONS.get(name, ''))))
    query = ('mutation { updateProjectV2Field(input: { fieldId: %s'
             ' singleSelectOptions: [%s] }) { projectV2Field {'
             ' ... on ProjectV2SingleSelectField { options { id name } } } } }'
             % (literal(field_id), ', '.join(options)))
    code, out, err = run(['gh', 'api', 'graphql', '-f', 'query=%s' % query])
    if code != 0:
        return False, None, (err.strip() or 'the mutation failed')
    try:
        body = json.loads(out)
    except json.JSONDecodeError as exc:
        return False, None, 'unreadable response (%s)' % exc
    if body.get('errors'):
        return False, None, json.dumps(body['errors'])
    try:
        live = body['data']['updateProjectV2Field']['projectV2Field']['options']
    except (KeyError, TypeError):
        return False, None, 'the response carried no option list'
    return True, live, ''


def board_column_options(cfg):
    """The board's Status field with every option's colour. (ok, field, err).

    `board_status_field` further down answers the same question for a move and
    is cached, but it asks only for `id` and `name`. That is not enough to add
    a column: `updateProjectV2Field` replaces the whole option list, and an
    existing option passed back without its colour and description is silently
    recoloured. So this is a second, uncached read, made only on the repair
    path, and it asks for everything it has to give back.
    """
    board = cfg.get('board') or {}
    node_id = board.get('project_node_id')
    if not node_id:
        return False, None, 'no project-node-id is recorded'
    name = board.get('status_field_name') or 'Status'
    ok, data, err = gh_graphql(
        'query($id:ID!,$field:String!){ node(id:$id){ ... on ProjectV2 { title'
        ' field(name:$field){ ... on ProjectV2SingleSelectField { id'
        '  options { id name color description } } } } } }',
        id=node_id, field=name)
    if not ok or not data:
        return False, None, err or 'the board did not resolve'
    node = data.get('node') or {}
    field = node.get('field') or {}
    if not field.get('id'):
        return False, None, "the board has no `%s` single-select field" % name
    return True, {'id': field['id'], 'title': node.get('title'),
                  'options': field.get('options') or []}, ''


def _config_file_findings(root, source_rel, text):
    """Everything preflight reads out of the two markdown files themselves."""
    findings = []
    headings = re.findall(r'^#{1,3}\s+(.+?)\s*$', text, re.MULTILINE)
    findings.extend(wf_core.retired_section_findings(headings, source_rel))
    findings.extend(wf_core.placeholder_findings(text, source_rel))
    findings.extend(wf_core.quality_gate_findings(quality_gate_command(text),
                                                  source_rel))

    claude_md = os.path.join(root, 'CLAUDE.md')
    exists = os.path.isfile(claude_md)
    references = False
    if exists:
        with open(claude_md, encoding='utf-8') as fh:
            references = 'ClaudeProject.md' in fh.read()
    findings.extend(wf_core.claude_md_findings(exists, references))

    referenced = review_config_reference(text)
    if referenced:
        findings.extend(wf_core.review_config_findings(
            referenced, os.path.isfile(os.path.join(root, referenced)),
            source_rel))
    return findings


def _fix_config_file(root, source, findings):
    """Repairs that rewrite `ClaudeProject.md`. Returns a list of descriptions."""
    with open(source, encoding='utf-8') as fh:
        original = fh.read()
    text, done = original, []

    retired = [f for f in findings if f['check'] == 'config-retired']
    if retired:
        text, removed = wf_core.strip_sections(
            text, sorted(wf_core.RETIRED_CONFIG_SECTIONS))
        for name in removed:
            done.append('deleted the `## %s` section from ClaudeProject.md' % name)

    deprecated = [f for f in findings if f['check'] == 'label-deprecated']
    if deprecated:
        purposes = sorted(wf_core.RETIRED_LABELS)
        text, removed = wf_core.strip_label_map_rows(text, purposes)
        for name in removed:
            done.append('deleted the `%s` row from the label map' % name)

    if text != original:
        with open(source, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
    return done


def _fix_claude_md(root):
    """Point an existing CLAUDE.md at ClaudeProject.md. Never creates one."""
    path = os.path.join(root, 'CLAUDE.md')
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    updated, changed = wf_core.add_config_pointer(text)
    if not changed:
        return []
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(updated)
    return ['added a ClaudeProject.md pointer to CLAUDE.md']


def _fix_board_columns(cfg, source, findings):
    """Create missing lanes, then rewrite the recorded option ids.

    Both halves run off one live read of the Status field, and the second half
    runs whether or not the first had anything to do: a snapshot that no longer
    matches the board is the `board-column` finding, and it is repaired by
    writing what the board actually says.
    """
    wants_lane = any(f['check'] == 'board-lane' for f in findings)
    wants_snapshot = any(f['check'] == 'board-column' for f in findings)
    if not (wants_lane or wants_snapshot):
        return [], []

    ok, field, err = board_column_options(cfg)
    if not ok:
        return [], ['could not read the board (%s), so no column was created '
                    'or recorded' % err]

    live_names = {(o.get('name') or '').strip().lower() for o in field['options']}
    missing = [name for purpose, name in wf_core.BOARD_COLUMN_NAMES.items()
               if name.strip().lower() not in live_names]
    done, blocked = [], []
    options = field['options']
    if missing:
        ok, options, err = create_board_columns(field['id'], field['options'],
                                                missing)
        if not ok:
            return [], ['could not create %s on the board (%s)'
                        % (wf_core._names(missing), err)]
        done.append('created %s on the board' % wf_core._names(missing))

    by_name = {(o.get('name') or '').strip().lower(): o.get('id')
               for o in options or ()}
    columns = {}
    for purpose, name in wf_core.BOARD_COLUMN_NAMES.items():
        option_id = by_name.get(name.strip().lower())
        if option_id:
            columns[purpose] = option_id
    with open(source, encoding='utf-8') as fh:
        text = fh.read()
    updated, changed = wf_core.replace_status_options(text, columns)
    if changed:
        with open(source, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(updated)
        done.append('rewrote the `### Status Options` table from the live board')
    elif wants_snapshot:
        blocked.append('ClaudeProject.md has no `### Status Options` table to '
                       'refresh — run `/github-workflow:setup board`')
    return done, blocked


def _fix_board_placement(cfg, orphans, unset):
    """Put every issue the board does not account for into `Backlog`.

    `Backlog` and not "wherever it belongs": nothing on an orphaned issue says
    where it belongs, and the pool is the one lane whose meaning is "nobody has
    decided anything about this yet". Somebody moving it straight back out is a
    decision; leaving it invisible is not.
    """
    numbers = sorted(set(orphans or ()) | set(unset or ()))
    if not numbers:
        return [], []
    column = wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN]
    placed, failed = [], []
    for number in numbers:
        moved, message = board_move(cfg, number, column)
        (placed if moved else failed).append(
            number if moved else '#%d (%s)' % (number, message))
    done, blocked = [], []
    if placed:
        done.append('put %d issue%s in %s: %s'
                    % (len(placed), '' if len(placed) == 1 else 's', column,
                       ', '.join('#%d' % n for n in placed)))
    if failed:
        blocked.append('could not place %s' % ', '.join(failed))
    return done, blocked


def _fix_retired_labels(cfg, labelled, repo=None):
    """Take every retired label off the open issues still carrying one.

    The only write this command makes to an issue's own content, and it is safe
    because the labels decide nothing: `pick`, `unblock` and the board all read
    fields now. What a stale label still does is mislead a person filtering the
    issues list by hand, which is why it is worth removing rather than leaving
    for the write path to clear one issue at a time.
    """
    repo = repo or '%s/%s' % (cfg['org'], cfg['repo'])
    project_map = cfg.get('labels')
    cleared, failed, names = [], [], set()
    for issue in labelled or ():
        stale = wf_core.retired_label_variants(issue.get('labels'), project_map)
        if not stale:
            continue
        args = []
        for name in stale:
            args.extend(['--remove-label', name])
        code, _out, err = run(['gh', 'issue', 'edit', str(issue['number']),
                               '--repo', repo] + args)
        if code != 0:
            failed.append('#%s (%s)' % (issue['number'],
                                        (err or '').strip() or 'edit failed'))
            continue
        cleared.append(issue['number'])
        names.update(stale)
    done, blocked = [], []
    if cleared:
        done.append('took %s off %d issue%s'
                    % (wf_core._names(sorted(names)), len(cleared),
                       '' if len(cleared) == 1 else 's'))
    if failed:
        blocked.append('could not clear the retired labels on %s'
                       % ', '.join(failed))
    return done, blocked


def _fix_retired_board_column(cfg, findings):
    """Empty a retired lane into `Backlog`, then delete the lane.

    In that order, and only in that order: deleting a single-select option
    deletes the value from every card holding it, so a `Ready` column removed
    while cards sat in it would leave those issues in no lane at all -- which is
    the `board-unset` failure, created by the repair meant to prevent it. A lane
    this run could not empty keeps its column and is reported instead.
    """
    if not any(f['check'] == 'board-retired' for f in findings):
        return [], []
    ok, field, err = board_column_options(cfg)
    if not ok:
        return [], ['could not read the board (%s), so no retired column was '
                    'removed' % err]

    pool = wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN]
    by_name = {(o.get('name') or '').strip().lower(): o for o in field['options']}
    done, blocked = [], []
    doomed = []
    for retired in wf_core.RETIRED_BOARD_COLUMNS:
        option = by_name.get(retired.strip().lower())
        if not option:
            continue
        ok, issues, cerr = _board_column_candidates(cfg, option['name'],
                                                    unassigned_only=False)
        if not ok:
            blocked.append('could not read the `%s` column (%s), so it was left '
                           'in place' % (option['name'], cerr))
            continue
        stuck = []
        for issue in issues:
            moved, message = board_move(cfg, issue['number'], pool)
            if not moved:
                stuck.append('#%d (%s)' % (issue['number'], message))
        if stuck:
            blocked.append('could not move %s out of `%s`, so the column was '
                           'left in place' % (', '.join(stuck), option['name']))
            continue
        if issues:
            done.append('moved %d card%s out of `%s` into %s'
                        % (len(issues), '' if len(issues) == 1 else 's',
                           option['name'], pool))
        doomed.append(option)

    if not doomed:
        return done, blocked
    keep = [o for o in field['options'] if o not in doomed]
    ok, _options, uerr = create_board_columns(field['id'], keep, [])
    if not ok:
        blocked.append('emptied %s but could not remove %s from the board (%s)'
                       % (wf_core._names([o['name'] for o in doomed]),
                          'it' if len(doomed) == 1 else 'them', uerr))
        return done, blocked
    done.append('removed %s from the board'
                % wf_core._names([o['name'] for o in doomed]))
    return done, blocked


def cmd_preflight(args):
    """Is this project in a state a workflow command can run against?

    One command, one JSON object, one exit code — 0 when nothing critical is
    wrong, 26 when something is. `--fix` repairs the subset that can be
    repaired without guessing (`wf_core.FIXABLE_CHECKS`) and re-runs the checks
    afterwards, so what it reports is the state it leaves behind rather than
    the state it found.
    """
    root = repo_root() or '.'
    source = config_paths(root)[1]
    source_rel = os.path.basename(source)

    findings, checked, skipped = [], [], []

    err = check_environment()
    if err:
        findings.append(wf_core.finding(
            wf_core.CRITICAL, 'gh-auth',
            'the GitHub CLI cannot act for this repository (%s)' % err,
            'run `gh auth login`, and run this from inside the repository'))
    checked.append('gh-auth')

    if not os.path.isfile(source):
        findings.append(wf_core.finding(
            wf_core.CRITICAL, 'file-config',
            'there is no %s at %s, so every value the workflow reads is a '
            'default nobody chose' % (source_rel, root),
            'run `/github-workflow:setup`', source_rel))
        return _emit_preflight(findings, checked + ['file-config'],
                               ['config-section'], None, args, [], [])

    checked.append('file-config')
    with open(source, encoding='utf-8') as fh:
        text = fh.read()
    findings.extend(_config_file_findings(root, source_rel, text))
    checked.extend(['config-retired', 'placeholders', 'quality-gate',
                    'claude-md-ref', 'review-config'])

    ok, cfg, cerr = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=cerr)

    audit, audit_checked, audit_skipped, context = collect_config_findings(
        cfg, args, root)
    findings.extend(audit)
    checked.extend(audit_checked)
    skipped.extend(audit_skipped)

    if not args.fix:
        return _emit_preflight(findings, checked, skipped, cfg, args, [], [])

    fixable, _ = wf_core.fix_plan(findings)
    if not fixable:
        return _emit_preflight(findings, checked, skipped, cfg, args, [], [])

    done, blocked = [], []
    done.extend(_fix_config_file(root, source, fixable))
    done.extend(_fix_claude_md(root))
    if not args.offline:
        board_done, board_blocked = _fix_board_columns(cfg, source, fixable)
        done.extend(board_done)
        blocked.extend(board_blocked)
        column_done, column_blocked = _fix_retired_board_column(cfg, fixable)
        done.extend(column_done)
        blocked.extend(column_blocked)
        place_done, place_blocked = _fix_board_placement(
            cfg, context.get('orphans'), context.get('unset'))
        done.extend(place_done)
        blocked.extend(place_blocked)
        label_done, label_blocked = _fix_retired_labels(
            cfg, context.get('retired_labels'), args.repo)
        done.extend(label_done)
        blocked.extend(label_blocked)
        container_done, container_blocked = _fix_finished_containers(
            cfg, context.get('finished_containers'))
        done.extend(container_done)
        blocked.extend(container_blocked)

    # Re-run against the state the repairs left behind, so the findings a
    # person reads are the ones that are still true. A `--fix` that reported
    # what it found rather than what it left would make the second run of an
    # idempotent command look like it had done nothing.
    ok, cfg, cerr = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=cerr)
    with open(source, encoding='utf-8') as fh:
        text = fh.read()
    findings = [f for f in findings if f['check'] in ('gh-auth', 'file-config')]
    findings.extend(_config_file_findings(root, source_rel, text))
    audit, audit_checked, audit_skipped, _ = collect_config_findings(
        cfg, args, root)
    findings.extend(audit)
    return _emit_preflight(findings, checked, skipped, cfg, args, done, blocked)


def _emit_preflight(findings, checked, skipped, cfg, args, fixed, blocked):
    summary = wf_core.preflight_summary(findings)
    payload = {'summary': summary, 'checked': sorted(set(checked)),
               'skipped': sorted(set(skipped))}
    if cfg:
        payload['org'] = cfg.get('org')
        payload['repo'] = '%s/%s' % (cfg.get('org'), cfg.get('repo'))
    if not args.quiet:
        payload['findings'] = [
            dict(f, fixable=wf_core.FIXABLE_CHECKS.get(f['check'])
                 or wf_core.unfixable_reason(f['check']),
                 auto=f['check'] in wf_core.FIXABLE_CHECKS)
            for f in findings]
    if args.fix:
        payload['fixed'] = fixed
        payload['unfixed'] = blocked

    if summary['critical']:
        emit('blocked', EXIT_DRIFT,
             reason='%d problem%s stop%s a workflow command from running '
                    'correctly here%s'
                    % (summary['critical'],
                       '' if summary['critical'] == 1 else 's',
                       's' if summary['critical'] == 1 else '',
                       '' if not summary['warning']
                       else '; %d more will degrade it' % summary['warning']),
             **payload)
    emit('ok', EXIT_OK,
         reason=('nothing blocks a workflow command'
                 + ('' if not summary['warning']
                    else '; %d thing%s will run on a default'
                    % (summary['warning'],
                       '' if summary['warning'] == 1 else 's'))),
         **payload)

# GitHub caps a connection page at 100 records -- asking for more is an
# `EXCESSIVE_PAGINATION` error, not a truncated answer, so the whole query
# fails.
FACET_PAGE_SIZE = 100
FACET_MAX_PAGES = 20

# Issues per aliased request when the caller names them. The same twenty as
# every other aliased read here, for the same reason: GitHub's complexity
# budget.
FACET_BATCH = 20

_FACET_SELECTION = (
    ' number issueType { name }'
    ' issueFieldValues(first:20){ nodes {'
    '  ... on IssueFieldSingleSelectValue {'
    '   field { ... on IssueFieldSingleSelect { name } } name }'
    '  ... on IssueFieldMultiSelectValue {'
    '   field { ... on IssueFieldMultiSelect { name } } options { name } }'
    ' } }'
)


def _facets_query(paged):
    """The open-issue facets query, with the `after:` clause only when paging."""
    return (
        'query($owner:String!,$repo:String!%s){'
        ' repository(owner:$owner,name:$repo){'
        '  issues(first:%d,states:OPEN,orderBy:{field:CREATED_AT,direction:DESC}%s){'
        '   pageInfo { hasNextPage endCursor }'
        '   nodes {%s'
        '   } } } }'
        % (',$cursor:String!' if paged else '', FACET_PAGE_SIZE,
           ',after:$cursor' if paged else '', _FACET_SELECTION))


def _read_facets(node, facets, fields):
    """Fold one issue node into the facet maps."""
    number = node.get('number')
    if number is None:
        return
    native = node.get('issueType') or {}
    if native.get('name'):
        facets['types'][number] = native['name']
    values = issue_field_values(node)
    for key, field in fields.items():
        if values.get(field):
            facets[key][number] = values[field]


def fetch_issue_facets(cfg, numbers=None, priority_field='Priority',
                       classification_field='Classification',
                       effort_field='Effort', ownership_field='Ownership'):
    """Every structured field a decision reads, for the issues it decides about.

    Returns (ok, facets, err) where facets is ``{'types', 'priority',
    'classification', 'effort', 'ownership'}``, each a ``{number: value}`` map.

    One query for all of them because the picker needs all of them about the
    same row: the type to filter the pool, Priority and Effort to order it,
    Effort again for a size ceiling, Ownership to keep work a code agent cannot
    do out of a code agent's pool, and Classification to tell a `Feature` that
    is tech debt from one that is a new feature.

    **Pass `numbers` whenever the caller knows them.** Without it this reads the
    repository's open issues newest-first, and the window used to be two pages:
    on a repository with more than two hundred open issues, an older issue sat
    in the Backlog column with no `Ownership` value in the map, was dropped by
    the pool filter as unowned, and was named nowhere. The pool it belongs to
    is a board column and this was a repository query, so the two windows were
    never the same set of issues. Naming the pool's own numbers removes the
    window entirely.

    A failure is a failure. There is no label fallback left to degrade to since
    10.0.0 -- an empty ownership map means an empty pool, which reads exactly
    like a finished backlog -- so the caller is told, and stops.
    """
    fields = {'priority': priority_field, 'classification': classification_field,
              'effort': effort_field, 'ownership': ownership_field}
    facets = {'types': {}, 'priority': {}, 'classification': {},
              'effort': {}, 'ownership': {}}

    if numbers is not None:
        ordered = sorted({int(n) for n in numbers})
        for chunk in _chunks(ordered, FACET_BATCH):
            parts = ['f%d: issue(number:%d){%s }' % (n, n, _FACET_SELECTION)
                     for n in chunk]
            ok, data, err = gh_graphql(
                'query($owner:String!,$repo:String!){'
                ' repository(owner:$owner,name:$repo){ %s } }' % ' '.join(parts),
                owner=cfg['org'], repo=cfg['repo'])
            if not ok or not data:
                return False, facets, 'issue facet query failed: %s' % err
            repo = data.get('repository') or {}
            for number in chunk:
                node = repo.get('f%d' % number)
                if node:
                    _read_facets(node, facets, fields)
        return True, facets, ''

    cursor, pages = None, 0
    while pages < FACET_MAX_PAGES:
        args = {'owner': cfg['org'], 'repo': cfg['repo']}
        if cursor:
            args['cursor'] = cursor
        ok, data, err = gh_graphql(_facets_query(bool(cursor)), **args)
        if not ok or not data:
            return False, facets, 'issue facet query failed: %s' % err
        try:
            connection = data['repository']['issues']
            nodes = connection['nodes']
        except (KeyError, TypeError):
            return False, facets, 'unexpected issue facet response shape'
        for node in nodes:
            _read_facets(node, facets, fields)
        pages += 1
        page_info = connection.get('pageInfo') or {}
        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')
        if not cursor:
            break
        if pages >= FACET_MAX_PAGES:
            return False, facets, (
                'this repository has more than %d open issues, which is more '
                'than one pass reads' % (FACET_PAGE_SIZE * FACET_MAX_PAGES))
    return True, facets, ''


def report_unprioritised(pool, priority_map):
    """Name the candidates carrying no Priority, which therefore sort last.

    There is no second opinion to fall back on since 10.0.0: `Priority` is the
    whole of the pool's order, so an issue without one is not ordered by a
    label instead, it goes to the back. That is a silent demotion -- the issue
    is pickable, it is just never the pick -- so it is said out loud.

    Only when the org clearly has the field, which is when some other candidate
    carried a value. Silence otherwise: an empty field on an org that has no
    such field is a configuration finding, and `config-audit` is where it
    belongs.
    """
    if not pool or not priority_map:
        return
    missing = sorted(c['number'] for c in pool if not priority_map.get(c['number']))
    if not missing:
        return
    eprint('wf: %d candidate(s) have no Priority field value and sort last: '
           '%s (run `wf issue-audit`, then `wf issue-apply` on the spec it '
           'writes, to backfill)'
           % (len(missing), ', '.join('#%d' % n for n in missing)))


def load_issue_facets(cfg, numbers=None):
    """`fetch_issue_facets` for this project's field names, or stop.

    A failure ends the run rather than returning empty maps. Empty maps used to
    be the fallback, from when a label could answer these questions: with no
    `Ownership` value for anything, every candidate is filtered out, and the
    command reports `no-candidates` -- a finished backlog -- because a query
    failed. There is nothing left to fall back to, so there is nothing to
    report but the failure.
    """
    ok, facets, err = fetch_issue_facets(cfg, numbers,
                                         field_name(cfg, 'field-priority'),
                                         field_name(cfg, 'field-type'),
                                         field_name(cfg, 'field-effort'),
                                         field_name(cfg, 'field-ownership'))
    if not ok:
        emit('error', EXIT_ENV,
             reason='could not read the issue fields every decision here is '
                    'made from (%s), so nothing about this backlog is known. '
                    'Check the token and re-run.' % err)
    return facets


def assemble_candidates(cfg):
    """Fetch the pool: open, unassigned issues in the board's Backlog column.

    Returns (ok, issues, err).

    One source, and it is the board. This replaced four `ready-gate` settings
    -- `label`, `board-column`, `both`, `none` -- of which three required an
    issue to be explicitly marked before anything would look at it. That was
    the opt-in model, and it fails silently in the one way nobody checks: on
    this plugin's own repository, three workable issues sat unassigned in the
    backlog while `wf pick` reported an empty pool, because nobody had applied
    `status-ready`. An empty pool reads as a finished backlog.

    Backlog is now the pool and everything in it is available unless a
    structured field says otherwise. Nothing has to be remembered, because a
    card has to be in *some* column, and `Status` holds one value -- so an
    issue that is in progress, in review, blocked, parked, awaiting refinement
    or done is in that column and not this one, with no exclusion list needed.

    A board is required, and that is the breaking half of 9.0.0. The old `none`
    gate read the whole repository and could not express "in Backlog" at all,
    so it offered work that had deliberately been set aside. Rather than keep a
    second, weaker definition of the pool, a project without a board is told to
    configure one -- `wf preflight --fix` creates it.
    """
    board = cfg.get('board') or {}
    if not board.get('project_node_id'):
        return False, None, (
            'no project board is configured, and the pick pool is the board\'s '
            '%s column. Add `project-node-id` to `## Project Board` in '
            'ClaudeProject.md, or run `wf preflight --fix` to create the board '
            'and record it.' % wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN])
    return _board_column_candidates(
        cfg, wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN])


def ordered_pool(cfg, issues, selector):
    """The filtered, sorted pool, narrowed to a sprint when one applies.

    Returns (backlog_mode, pool). Filtering runs first and narrowing second,
    which is the opposite of the order this ran in until 10.1.2, and the reason
    is that a milestone is not an eligibility rule: narrowing first meant that
    a sprint whose only Backlog issues were owned by a person produced an empty
    pool and `no-candidates`, while pickable work sat in the next milestone.
    For the same reason a sprint that holds nothing this agent may take falls
    back to the flat pool rather than to nothing.
    """
    pool = selector(issues)
    mode, narrowed = narrow_to_sprint(cfg, pool)
    if mode == 'sprint' and narrowed:
        return mode, narrowed
    return 'flat', pool


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
    """Take durable ownership: assign @me and move the card to In Progress.

    The assignment is the part that matters and it is checked; the board move
    is how a person sees it. Neither is a label any more -- an issue in
    progress is one that is assigned and sitting in the In Progress column, and
    those two facts live where GitHub itself keeps them rather than in a name
    somebody has to remember to change.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['issue', 'edit', str(issue['number']), '--repo', repo,
            '--add-assignee', '@me']
    retired = wf_core.retired_labels_on(issue.get('labels') or [],
                                        cfg.get('labels') or {})
    for name in retired:
        args += ['--remove-label', name]
    code, _, err = run(['gh'] + args)
    if code != 0:
        eprint('wf: warning — could not assign #%s (%s)'
               % (issue['number'], err.strip()))
    moved, message = board_move(cfg, issue['number'],
                                wf_core.BOARD_COLUMN_NAMES['col-in-progress'])
    if not moved:
        eprint('wf: warning — could not move #%s to In Progress (%s)'
               % (issue['number'], message))


def revert_in_progress(cfg, number):
    """Undo `apply_in_progress`: unassign and put the card back in Backlog.

    The claim is taken before the issue can be validated, so a candidate that
    turns out not to be workable has already been assigned and moved. Every
    path that gives one back has to leave it exactly as available as it was
    found, or the next run sees an issue somebody is apparently working on and
    skips it for good. Returns (moved, message) for the board half.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    code, _, err = run(['gh', 'issue', 'edit', str(number), '--repo', repo,
                        '--remove-assignee', '@me'])
    if code != 0:
        eprint('wf: warning — could not unassign #%s (%s)' % (number, err.strip()))
    return board_move(cfg, number,
                      wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN])


# ── dependency validation ────────────────────────────────────────────────────

# How many blocked-by edges one read asks for. A full page is treated as "more
# than this can see" rather than as the whole set: releasing an issue because
# its first hundred blockers are closed, while the hundred-and-first is open,
# is the one mistake a dependency reader must not make.
EDGE_PAGE = 100


def issue_edges(cfg, number):
    """The issue's native blocked-by edges, with each blocker's state.

    Returns the edge list, or None when the answer is unknown -- a failed
    query, or more edges than one page holds. None is not "no edges": every
    caller has to tell the two apart, because acting on "no edges" means
    treating the issue as unblocked.

    One query, and it answers the whole question: which issues this one waits
    on, and which of those are still open. The old shape read the body prose
    and then spent a call per reference to look each one up.
    """
    ok, data, _ = gh_graphql(
        'query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){'
        ' issue(number:$n){ blockedBy(first:%d){ nodes { number state } } } } }'
        % EDGE_PAGE,
        o=cfg['org'], r=cfg['repo'], n=int(number))
    if not ok or not data:
        return None
    try:
        nodes = data['repository']['issue']['blockedBy']['nodes'] or []
    except (KeyError, TypeError):
        return None
    return None if len(nodes) >= EDGE_PAGE else nodes


EDGE_BATCH = 20


def issue_edges_map(cfg, numbers):
    """The native blocked-by edges of many issues at once. (found, unknown).

    `found` is {number: [edge]}; `unknown` is every number whose edges this
    could not read — a failed request, an alias GitHub did not answer, or more
    edges than one page holds.

    One aliased query per twenty issues rather than one query per issue. The
    split return is what stops a network failure reading as an unblocked issue:
    an absent number used to come back the same as one with no edges, so a
    transient error on this query moved a genuinely blocked card into Backlog
    and handed the issue to an agent whose dependency was still open.
    """
    found, unknown = {}, []
    ordered = sorted({int(n) for n in (numbers or ())})
    for start in range(0, len(ordered), EDGE_BATCH):
        batch = ordered[start:start + EDGE_BATCH]
        parts = ['e%d: issue(number:%d){ blockedBy(first:%d){'
                 ' nodes { number state title } } }' % (n, n, EDGE_PAGE)
                 for n in batch]
        ok, data, _ = gh_graphql(
            'query($o:String!,$r:String!){ repository(owner:$o,name:$r){ %s } }'
            % ' '.join(parts), o=cfg['org'], r=cfg['repo'])
        if not ok or not data:
            unknown.extend(batch)
            continue
        repo = data.get('repository') or {}
        for number in batch:
            node = repo.get('e%d' % number)
            if node is None:
                unknown.append(number)
                continue
            nodes = (node.get('blockedBy') or {}).get('nodes') or []
            if len(nodes) >= EDGE_PAGE:
                unknown.append(number)
                continue
            found[number] = nodes
    return found, sorted(set(unknown))


def validate_issue(cfg, issue, siblings=()):
    """Validate a claimed issue. Returns (verdict, detail).

    verdict ∈ {'valid', 'blocked', 'resolved', 'unknown'}:
      blocked  → open dependencies (detail = list of open #s, or 'meta' on overflow)
      resolved → already closed by a merged PR (detail = pr number)
      unknown  → the edges could not be read, so nothing here is decidable
      valid    → nothing stops the work starting

    The dependencies come from the native `blockedBy` edges and from nowhere
    else. No body prose is parsed here: a dependency is the edge, and a
    sentence naming one is not a second record of it.

    `unknown` exists because the alternative was worse in a specific way. A
    failed edge query used to return `blocked`, and the caller then moved the
    card to Blocked -- an issue with no edge behind it, which `wf unblock` will
    never release, parked indefinitely by one bad request.

    The dependency ceiling counts **open** blockers only. Counting closed ones
    too made an issue with six delivered dependencies permanently
    unworkable: `pick` marked it blocked, the next sweep found every edge
    closed and released it, and the two took turns.

    `siblings` are the other issues in a bulk set — stories being built in the
    same commit series on the same branch. A dependency on one of those does
    not block, because it is not unmerged work you cannot see; it is work this
    same run is about to write. Everything else is unchanged, so a single-story
    pick (no siblings) behaves exactly as before.
    """
    edges = issue_edges(cfg, issue['number'])
    if edges is None:
        return 'unknown', 'could not read the blocked-by edges'
    open_numbers, closed_numbers = wf_core.edge_states(edges)
    deps = open_numbers + closed_numbers
    if len(open_numbers) > wf_core.DEP_LIMIT:
        return 'blocked', ('meta-issue (> %d open dependencies)'
                           % wf_core.DEP_LIMIT)
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
    the same authoritative signal `sibling-pr` uses
    everywhere — rather than a free-text body search. That catches the real
    "merged but the issue is still open" case (a PR merged into a non-default
    base, e.g. a chained story, where GitHub recognises the reference but does
    not auto-close), and never misfires on a stray "closes"/"#N" in prose.

    The **newest** hundred merged pull requests, and the lowest matching number
    among them so the answer is deterministic when more than one references the
    issue. It read the oldest hundred until 10.1.2, which on any repository
    past its first hundred merges could only ever see the beginning of history
    — so the case this exists to catch, a pull request that merged in the last
    few days, was the one case it could not see.
    """
    query = (
        'query($owner:String!,$repo:String!){'
        ' repository(owner:$owner,name:$repo){'
        ' pullRequests(states:MERGED, first:100,'
        ' orderBy:{field:CREATED_AT, direction:DESC}){'
        ' nodes { number closingIssuesReferences(first:10){ nodes { number } } } } } }'
    )
    ok, data, _ = gh_graphql(query, owner=cfg['org'], repo=cfg['repo'])
    if not ok or not data:
        return None
    try:
        nodes = data['repository']['pullRequests']['nodes']
    except (KeyError, TypeError):
        return None
    matches = [pr['number'] for pr in nodes
               if number in wf_core.closing_issue_numbers(
                   pr.get('closingIssuesReferences'))]
    return min(matches) if matches else None


def mark_blocked(cfg, issue, detail):
    """Return an issue to blocked: unassign, comment, move the card.

    Returns (moved, message) for the board half, which the caller reports. The
    board move is not decoration. It is the whole record of the state: the card
    in Blocked is what says the issue is blocked, and it is what keeps the
    issue out of the pool, because the pool is the Backlog column. A failed
    move therefore leaves the issue in the pool, unassigned, and the next run
    picks it up again — so it has to be said rather than swallowed.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    run(['gh', 'issue', 'edit', str(issue['number']), '--repo', repo,
         '--remove-assignee', '@me'])
    run(['gh', 'issue', 'comment', str(issue['number']), '--repo', repo,
         '--body', 'Blocked — open dependency(ies): %s. Returned to blocked until they close.' % detail])
    moved, message = board_move(cfg, issue['number'],
                                wf_core.BOARD_COLUMN_NAMES['col-blocked'])
    if not moved:
        eprint('wf: warning — #%s is unassigned but its card did not move to '
               'Blocked (%s), so it is still in the pool'
               % (issue['number'], message))
    return moved, message


def clear_lifecycle_label(cfg, number, labels):
    """Strip whatever retired workflow label a now-closed issue still carries.

    A closed issue is closed and its card is in Done; that is the whole "done"
    signal. What this removes is the leftovers of the label workflow -- a
    `status-in-progress` from before the upgrade, a `priority-high` somebody
    set by hand -- so a closed issue does not go on advertising a state nothing
    maintains. Best-effort. Returns the removed label names, or None when there
    was nothing to clear.
    """
    stale = wf_core.retired_labels_on(labels, cfg.get('labels') or {})
    if not stale:
        return None
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['gh', 'issue', 'edit', str(number), '--repo', repo]
    for name in stale:
        args.extend(['--remove-label', name])
    run(args)
    return ', '.join(stale)


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

def best_effort(step, *args):
    """Run one best-effort side effect. Returns (ok, message) and never raises.

    The steps between the claim and the branch — the board move, the start
    date — are cosmetic, and the branch is not. A story that is claimed with
    no branch to work on is the worst outcome available here: the caller has
    nothing to build in and someone has to reap the claim by hand. So an
    unexpected failure inside one of these is reported in its own message and
    the run carries on, exactly as a returned error would be.
    """
    try:
        return step(*args)
    except Exception as exc:  # noqa: BLE001 - deliberate: see docstring
        label = getattr(step, '__name__', 'step').replace('_', ' ')
        return False, '%s failed unexpectedly (%s: %s)' % (
            label, type(exc).__name__, exc)


def board_move_in_progress(cfg, number):
    """Move the issue to the In Progress column. Returns (moved, message)."""
    return board_move(cfg, number, 'In Progress')


# The board's Status field, cached for the life of the process. Its columns do
# not change under a single `wf` run, and this is read once per issue placed:
# reading it per issue turned a thirteen-issue epic tree into fifty round
# trips, most of them asking the same question.
_BOARD_FIELD_CACHE = {}

# Aliases per board request. The same twenty the edge reader uses, for the same
# reason: GitHub's complexity budget, not a limit of the query itself.
BOARD_BATCH = 20


def board_status_field(cfg):
    """The board's Status field and its options. (ok, node id, field, err).

    Cached per (board, field name). A `wf` run is short and a board's columns
    are not edited underneath it, so the second caller pays nothing.
    """
    board = cfg.get('board', {})
    node = board.get('project_node_id')
    if not node:
        return False, None, None, 'no board configured'
    field_name = board.get('status_field_name', 'Status')
    title_cfg = board.get('project_title')
    key = (node, field_name, title_cfg)
    if key in _BOARD_FIELD_CACHE:
        return _BOARD_FIELD_CACHE[key]

    ok, data, err = gh_graphql(
        'query($id:ID!,$fname:String!){ node(id:$id){ ... on ProjectV2 { title'
        ' field(name:$fname){ ... on ProjectV2SingleSelectField { id options { id name } } } } } }',
        id=node, fname=field_name)
    if not ok or not data or not data.get('node'):
        outcome = (False, None, None, 'board identity check failed (%s)' % err)
    else:
        live_title = data['node'].get('title')
        field = data['node'].get('field')
        if title_cfg and live_title != title_cfg:
            outcome = (False, None, None,
                       "board node resolves to '%s' but config says '%s' — skipping"
                       % (live_title, title_cfg))
        elif not field:
            outcome = (False, None, None,
                       'could not resolve %s field (%s)' % (field_name, err))
        else:
            outcome = (True, node, field, '')
    _BOARD_FIELD_CACHE[key] = outcome
    return outcome


def board_current_columns(cfg, numbers):
    """The lane each issue's card is in now. (ok, {number: column or None}, err).

    A number maps to None when the issue has a card with no `Status` value, and
    is absent from the mapping when it has no card on this board at all. Both
    mean "in no lane", and both are lanes `issue-apply` may write; the
    difference matters only to the message it prints.
    """
    board = cfg.get('board') or {}
    node = board.get('project_node_id')
    if not node:
        return False, {}, 'no board configured'
    field_name = (board.get('status_field_name') or 'Status').replace('"', '\\"')
    ordered = sorted({int(n) for n in (numbers or ())})
    out = {}
    for chunk in _chunks(ordered, BOARD_BATCH):
        parts = ['c%d: issue(number:%d){ projectItems(first:20){ nodes {'
                 ' project { id }'
                 ' fieldValueByName(name:"%s"){'
                 '  ... on ProjectV2ItemFieldSingleSelectValue { name } } } } }'
                 % (n, n, field_name) for n in chunk]
        ok, data, err = gh_graphql(
            'query($o:String!,$r:String!){ repository(owner:$o,name:$r){ %s } }'
            % ' '.join(parts), o=cfg['org'], r=cfg['repo'])
        if not ok or not data:
            return False, {}, err or 'board lane lookup failed'
        repo = data.get('repository') or {}
        for number in chunk:
            content = repo.get('c%d' % number)
            if not content:
                continue
            items = [i for i in (content.get('projectItems') or {}).get('nodes') or []
                     if (i.get('project') or {}).get('id') == node]
            if not items:
                continue
            out[number] = next(
                ((i.get('fieldValueByName') or {}).get('name') for i in items
                 if (i.get('fieldValueByName') or {}).get('name')), None)
    return True, out, ''


def board_place_many(cfg, wanted):
    """Put many issues in their columns at once. {number: (moved, message)}.

    `wanted` is {issue number: column name}. Four round trips whatever the
    size: the Status field (cached, so usually none at all), one aliased read
    of the issues' node ids and existing cards, one aliased mutation adding the
    cards that are missing, one aliased mutation writing the column. Placing
    them one at a time cost four *each*, which a thirteen-issue epic tree made
    impossible to miss.

    **The column is resolved before any card is added, and that order is the
    point.** The other way round, an issue destined for a column the board does
    not have was added to the board and *then* found to have nowhere to go: the
    add succeeded, the status write did not, and the card landed in the board's
    `No Status` bucket while the caller was told `moved: false`. A report that
    says nothing happened, next to a card that appeared out of nowhere, is
    worse than either.
    """
    out = {}
    if not wanted:
        return out
    ok, node, field, err = board_status_field(cfg)
    if not ok:
        return dict.fromkeys(wanted, (False, err))

    options = {(o['name'] or '').strip().lower(): o['id'] for o in field['options']}
    live_names = ', '.join(o['name'] for o in field['options']) or 'none'
    targets = {}
    for number, column in wanted.items():
        option_id = options.get((column or '').strip().lower())
        if option_id:
            targets[int(number)] = option_id
        else:
            out[number] = (False, "no '%s' column on the board (it has: %s)"
                                  % (column, live_names))
    if not targets:
        return out

    cards = {}
    for chunk in _chunks(sorted(targets), BOARD_BATCH):
        parts = ['b%d: issue(number:%d){ id projectItems(first:20){'
                 ' nodes { id project { id } } } }' % (n, n) for n in chunk]
        ok, data, err = gh_graphql(
            'query($o:String!,$r:String!){ repository(owner:$o,name:$r){ %s } }'
            % ' '.join(parts), o=cfg['org'], r=cfg['repo'])
        repo = ((data or {}).get('repository') or {}) if ok else {}
        for number in chunk:
            content = repo.get('b%d' % number)
            if not content or not content.get('id'):
                out[number] = (False, 'item lookup failed (%s)'
                                      % (err or 'issue not found'))
                continue
            item = next((i['id'] for i
                         in (content.get('projectItems') or {}).get('nodes') or []
                         if (i.get('project') or {}).get('id') == node), None)
            cards[number] = {'content': content['id'], 'item': item}

    missing = sorted(n for n, card in cards.items() if not card['item'])
    for chunk in _chunks(missing, BOARD_BATCH):
        decls = ','.join('$c%d:ID!' % n for n in chunk)
        parts = ['a%d: addProjectV2ItemById(input:{projectId:$p,contentId:$c%d})'
                 '{ item { id } }' % (n, n) for n in chunk]
        args = {'p': node}
        args.update({'c%d' % n: cards[n]['content'] for n in chunk})
        ok, data, err = gh_graphql('mutation($p:ID!,%s){ %s }'
                                   % (decls, ' '.join(parts)), **args)
        for number in chunk:
            item = ((((data or {}).get('a%d' % number)) or {}).get('item') or {}) if ok else {}
            if not item.get('id'):
                out[number] = (False, 'could not add issue to board (%s)'
                                      % (err or 'no item returned'))
                cards.pop(number, None)
                continue
            cards[number]['item'] = item['id']

    for chunk in _chunks(sorted(cards), BOARD_BATCH):
        decls = ','.join('$i%d:ID!,$o%d:String!' % (n, n) for n in chunk)
        parts = ['m%d: updateProjectV2ItemFieldValue(input:{projectId:$p,'
                 'itemId:$i%d,fieldId:$f,value:{singleSelectOptionId:$o%d}})'
                 '{ projectV2Item { id } }' % (n, n, n) for n in chunk]
        args = {'p': node, 'f': field['id']}
        for number in chunk:
            args['i%d' % number] = cards[number]['item']
            args['o%d' % number] = targets[number]
        ok, data, err = gh_graphql('mutation($p:ID!,$f:ID!,%s){ %s }'
                                   % (decls, ' '.join(parts)), **args)
        for number in chunk:
            out[number] = ((True, 'moved to %s' % wanted[number]) if ok
                           else (False, 'board mutation failed (%s)' % err))
    return out


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def board_move(cfg, number, column_name):
    """Move one issue's card to the named Status column. (moved, message).

    Best-effort and gated on a configured board: with no `project-node-id` the
    board is not in use, so this is a no-op with a reason. One issue is the
    degenerate case of `board_place_many`, and goes through it so there is only
    one description of what placing a card means.
    """
    return board_place_many(cfg, {number: column_name})[number]


def set_start_date(cfg, number):
    """Stamp the org's `Start date` issue field with today. Returns (set, why).

    Best-effort and capability-gated in both directions: an org that does not
    define the field is not misconfigured, and neither is one that denies the
    field API to this token. Independent of the board — the board's own start
    date is a different field on a different object.
    """
    ok, caps, err = resolve_org_capabilities(cfg)
    if not ok:
        return False, 'org capabilities unavailable (%s)' % (err or 'no detail')
    name = field_name(cfg, 'field-start')
    meta = (caps.get('field_map') or {}).get(name)
    if not meta:
        return False, 'the org does not define a %s field' % name
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    value, verr = wf_core.field_value_input(meta, today)
    if verr:
        return False, verr
    ok, data, jerr = gh_json(['issue', 'view', str(number), '--repo',
                              '%s/%s' % (cfg['org'], cfg['repo']), '--json', 'id'])
    if not ok or not data or not data.get('id'):
        return False, 'could not read the issue node id (%s)' % jerr.strip()
    # Three values, not two: `set_issue_fields` answers (ok, node, err) like
    # every other `_mutation_result` caller. Unpacking two raised ValueError
    # *after* the claim, the label, the assignment and the board move had all
    # landed, so the run looked failed and was not.
    applied, _, merr = set_issue_fields(data['id'], [value])
    if not applied:
        return False, merr
    return True, 'set %s to %s' % (name, today)


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
# `templates/default-labels.md` → Review State Labels. Used only by the
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


# ── the unblock sweep ────────────────────────────────────────────────────────
# Nothing here used to release an issue when the thing it waited on landed.
# `post-merge` settles only the issues a pull request *closes*, so a story that
# merges and stays open reports nothing, and the work it freed sits there
# labelled blocked and invisible to the picker until somebody notices by hand.
# On this project somebody had to ask. This is the part that notices.
#
# It reads the native `blockedBy` edges and nothing else, and it checks scope
# before it checks edges: browser and human work is moved into the non-code
# lane rather than released, because no edge closing will ever make a code
# agent able to do it.

UNBLOCK_PAGE = 50
UNBLOCK_BLOCKER_BATCH = 20

_UNBLOCK_SEARCH = (
    'query($q:String!,$c:String){'
    ' search(query:$q, type:ISSUE, first:%d, after:$c){'
    '  pageInfo { hasNextPage endCursor }'
    '  nodes { ... on Issue { id number title body'
    '   labels(first:30){ nodes { name } }'
    '   blockedBy(first:20){ nodes { number state title } } } } } }' % UNBLOCK_PAGE
)


def blocked_issues(cfg):
    """Every open issue in the board's Blocked column, with its native edges.

    Returns (issues, error).

    This read a label search until 10.0.0, and the change is the same one the
    pick pool made: the board's `Status` field is where an issue's state lives,
    so "which issues are blocked" is a question the board answers, once, with
    one value per issue. The label it used to search for could disagree with
    the card -- and did, which is most of why this sweep had to exist in the
    first place.
    """
    ok, issues, err = _board_column_candidates(
        cfg, wf_core.BOARD_COLUMN_NAMES['col-blocked'],
        unassigned_only=False,
        extra='blockedBy(first:20){ nodes { number state title } }')
    if not ok:
        return [], err
    return issues, None


def blocker_deliveries(cfg, numbers, now=None):
    """The newest pull request that merged mentioning each open blocker.

    Keyed by issue number, and absent for a blocker nothing has merged against
    recently. Cross-references rather than closing references, because the case
    this exists to catch is precisely the pull request that deliberately closed
    nothing: it delivered one half of a story and left the issue open for the
    other half, so GitHub records no closing reference to read. Which reference
    counts is `wf_core.recent_delivery`'s decision, and it is a strict one.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    found = {}
    ordered = sorted({int(n) for n in (numbers or ())})
    for start in range(0, len(ordered), UNBLOCK_BLOCKER_BATCH):
        batch = ordered[start:start + UNBLOCK_BLOCKER_BATCH]
        parts = [
            'b%d: issue(number:%d){ timelineItems(last:30,'
            ' itemTypes:[CROSS_REFERENCED_EVENT]){ nodes {'
            ' ... on CrossReferencedEvent { source {'
            ' ... on PullRequest { number title state mergedAt } } } } } }'
            % (number, number) for number in batch]
        ok, data, _ = gh_graphql(
            'query($o:String!,$r:String!){ repository(owner:$o,name:$r){ %s } }'
            % ' '.join(parts), o=cfg['org'], r=cfg['repo'])
        if not ok or not data:
            continue
        repo = data.get('repository') or {}
        for number in batch:
            node = repo.get('b%d' % number) or {}
            sources = [(item or {}).get('source') or {}
                       for item in ((node.get('timelineItems') or {}).get('nodes') or [])]
            delivery = wf_core.recent_delivery(sources, number, now)
            if delivery:
                found[number] = delivery
    return found


UNBLOCK_COMMENT = (
    'Unblocked by `wf unblock`. Every issue this waited on is now closed: %s.\n\n'
    'The card was moved to Backlog on purpose, which is what puts this issue '
    'back in the pick pool. The native blocked-by edges are what decide it, so '
    'if something still blocks this issue, add the edge for it rather than '
    'moving the card back on its own: a card in Blocked with no edge behind it '
    'is invisible to the sweep, and the issue will be released again on the '
    'next run.'
)

RESCOPE_COMMENT = (
    'Moved to `%s` by `wf unblock`. This is %s work, which no code agent can '
    'pick up, so it belongs in the non-code lane rather than in the blocked '
    'one. The Blocked lane means a dependency is open and a sweep will release '
    'it when that dependency closes; this issue would have been released into '
    'a pool that cannot do it. Nothing about the work has changed.'
)


def release_issue(cfg, issue, closed_numbers):
    """Release one issue: move its card to Backlog, then say why. Result dict.

    The move is the release. Backlog is the pick pool, so a card arriving there
    is the issue becoming available -- there is no separate label to take off,
    and no way for the two to disagree about whether the issue was released.

    The comment is not decoration. A bare state change reads to the next agent
    like damage to be repaired, and on this project one promptly repaired it:
    three issues were released by hand and re-blocked two minutes later by a
    concurrent session that took the change for automation stripping labels.
    Saying who did it and why is what stops that.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    number = issue['number']
    result = {'issue': number, 'title': issue.get('title'),
              'closed_blockers': closed_numbers}
    # The pool is the *unassigned* issues in Backlog, so an issue that kept the
    # assignee it had when it was blocked arrives in the pool and is still
    # invisible to every pick. That is said rather than fixed: taking somebody's
    # name off their issue is not a sweep's decision to make.
    if issue.get('assigned'):
        result['still_assigned'] = issue.get('assignees') or True
        eprint('wf: #%s was released to Backlog but is still assigned, so no '
               'pick will offer it until somebody unassigns it' % number)
    moved, message = board_move(cfg, number,
                                wf_core.BOARD_COLUMN_NAMES['col-backlog'])
    result['board_moved'] = moved
    if not moved:
        result['board_message'] = message
        return result

    named = ', '.join('#%d' % n for n in closed_numbers)
    run(['gh', 'issue', 'comment', str(number), '--repo', repo,
         '--body', UNBLOCK_COMMENT % named])
    return result


def rescope_issue(cfg, issue, scope, dry_run=False):
    """Move one non-code issue out of the Blocked lane into the Non-code lane.

    A move rather than a release, and the distinction is the point: browser and
    human work is never pickable by a code agent, so it must leave Blocked
    without ever passing through the pool. Which of the two lanes an issue
    belongs in is `Ownership`, read once for the sweep.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    number = issue['number']
    column = wf_core.BOARD_COLUMN_NAMES['col-non-code']
    result = {'issue': number, 'title': issue.get('title'), 'scope': scope,
              'column': column}
    if dry_run:
        result['dry_run'] = True
        return result
    moved, message = board_move(cfg, number, column)
    result['board_moved'] = moved
    if not moved:
        result['board_message'] = message
        return result
    run(['gh', 'issue', 'comment', str(number), '--repo', repo,
         '--body', RESCOPE_COMMENT % (column, scope)])
    return result


def unblock_scan(cfg, dry_run=False, only=None, now=None):
    """Release every blocked issue whose native dependencies have all closed.

    Returns a report with five parts, and only the first two write anything:

      released  every edge points at a closed issue, so the card moves back
                to Backlog and the issue is in the pool again
      rescoped  browser or human work that was sitting in the blocked lane,
                moved to the non-code lane instead. Never released: no edge
                closing will ever make a code agent able to do it.
      held      at least one blocker is still open, so it stays
      partials  held, but a blocker has just merged something. This is the case
                no edge can describe, reported rather than acted on.
      no_edges  in the Blocked lane with no edge at all, so this cannot speak
                to it either way. Most of those are waiting on the world rather
                than on an issue, which is exactly why the rule needs an edge
                before it will release anything.

    The ownership check comes before the edge check and that order is the whole
    safety property. Both issues this sweep would have released on its first
    real backlog were `[Manual]` device-pass work whose blockers happened to
    close: releasing them would have put a job needing a phone in someone's
    hand into the code agent's pool.

    Ownership is read from the org's field for the whole repository in one
    query. An issue with no value is **held** rather than released, and named:
    the sweep will not decide that an issue nobody has said who owns is safe
    for a code agent, which is the same rule the picker follows.
    """
    issues, error = blocked_issues(cfg)
    wanted = {int(n) for n in (only or ())} or None
    # Ownership for exactly the issues in the lane, and a failure here stops the
    # sweep: with no ownership values every blocked issue reads as unowned, so a
    # failed query would report a lane full of issues nobody owns and release
    # none of them.
    facets = load_issue_facets(cfg, [i['number'] for i in issues])
    ownership = facets.get('ownership') or {}

    released, rescoped, held, no_edges, unowned = [], [], [], [], []
    for issue in issues:
        if wanted is not None and issue['number'] not in wanted:
            continue
        scope = wf_core.ownership_scope(ownership.get(issue['number']))
        if scope is None:
            unowned.append({'issue': issue['number'], 'title': issue.get('title')})
            continue
        if scope != wf_core.SCOPE_CODE:
            rescoped.append(rescope_issue(cfg, issue, scope, dry_run=dry_run))
            continue
        edges = (issue.get('blockedBy') or {}).get('nodes') or []
        verdict, open_numbers, closed_numbers = wf_core.unblock_verdict(edges)
        if verdict == wf_core.UNBLOCK_NO_EDGES:
            no_edges.append(issue['number'])
        elif verdict == wf_core.UNBLOCK_HOLD:
            held.append({'issue': issue['number'], 'title': issue.get('title'),
                         'open_blockers': open_numbers,
                         'closed_blockers': closed_numbers})
        elif dry_run:
            released.append({'issue': issue['number'], 'title': issue.get('title'),
                             'closed_blockers': closed_numbers, 'dry_run': True})
        else:
            released.append(release_issue(cfg, issue, closed_numbers))

    deliveries = blocker_deliveries(
        cfg, {n for entry in held for n in entry['open_blockers']}, now)
    partials = []
    for entry in held:
        recent = [{'blocker': n, 'merged_pr': deliveries[n]['number'],
                   'merged_at': deliveries[n]['merged_at']}
                  for n in entry['open_blockers'] if n in deliveries]
        if recent:
            partials.append({'issue': entry['issue'], 'title': entry['title'],
                             'deliveries': recent})

    report = {'scanned': len(issues), 'released': released,
              'rescoped': rescoped, 'held': held, 'partials': partials,
              'unowned': unowned,
              'no_edges': {'count': len(no_edges), 'issues': no_edges}}
    if error:
        report['error'] = error
    return report


def cmd_unblock(args):
    """Release every blocked issue whose native dependencies have all closed."""
    cfg = prepare_cfg()
    report = unblock_scan(cfg, dry_run=args.dry_run, only=args.issue)
    if report.get('error'):
        # The lane could not be read, so "nothing to release" is not a result.
        # This reported `ok` with the error inside the payload, which is a
        # clean exit code on a sweep that swept nothing.
        emit('error', EXIT_ENV,
             reason='could not read the %s column (%s), so nothing was checked'
                    % (wf_core.BOARD_COLUMN_NAMES['col-blocked'],
                       report['error']),
             dry_run=bool(args.dry_run), **report)
    emit('ok', EXIT_OK, dry_run=bool(args.dry_run), **report)


def auto_unblock_scan(cfg):
    """Release any blocked issue whose dependencies have all closed.

    The last-resort sweep: `pick` calls this when it found nothing to pick, on
    the theory that the pool may only look empty. It is the same sweep
    `wf unblock` and `post-merge` run, so all three agree on what "released"
    means. Returns the number of issues released.
    """
    return len(unblock_scan(cfg).get('released') or [])


def claim_validate_walk(cfg, pool, backlog_mode, siblings=()):
    """Walk the ordered pool: claim the top, validate only that one, act.

    The single claim-first/validate-lazily loop shared by auto-pick and the
    explicit `--issue` path. For each candidate it acquires the atomic claim,
    applies the in-progress marker, then validates: a dependency-blocked issue
    is moved to the Blocked column, an already-resolved one is closed **and
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
        if verdict == 'unknown':
            # Nothing is known about this issue's dependencies, so nothing may
            # be written about them. The claim and the In Progress move are
            # undone and the run stops: retrying the next candidate would
            # almost certainly hit the same failure, one issue at a time.
            restored, message = revert_in_progress(cfg, cand['number'])
            release_claim(target)
            side_effects.append({'issue': cand['number'],
                                 'action': 'released-unverified',
                                 'detail': detail, 'restored': restored,
                                 'board_message': None if restored else message})
            emit('error', EXIT_ENV,
                 reason='could not read the blocked-by edges of #%d, so whether '
                        'it is blocked is unknown and nothing was decided from '
                        'it. The claim and the In Progress move were undone. '
                        'Check the token and the network, then re-run.'
                        % cand['number'],
                 backlog_mode=backlog_mode, side_effects=side_effects)
        if verdict == 'blocked':
            moved, message = mark_blocked(cfg, cand, detail)
            release_claim(target)
            side_effects.append({'issue': cand['number'], 'action': 'marked-blocked',
                                 'detail': detail, 'board_moved': moved,
                                 'board_message': None if moved else message})
            continue
        if verdict == 'resolved':
            board_moved, _ = close_resolved(cfg, cand, detail)
            release_claim(target)
            side_effects.append({'issue': cand['number'], 'action': 'closed-already-resolved',
                                 'pr': detail, 'board_moved_done': board_moved})
            continue
        return cand, side_effects
    return None, side_effects


# Lanes an explicitly named issue may be picked out of. Backlog is the pool;
# Blocked is here because the edge check runs anyway and an issue whose
# blockers have all closed is workable; Needs refinement and Parked are here
# because naming the issue is the person overruling the hold they put on it. In
# Progress and In Review are somebody else's work, Non-code is work a code
# agent cannot do, and Done is finished.
PICKABLE_BY_NAME = frozenset({'Backlog', 'Blocked', 'Needs refinement', 'Parked'})


# How far below a container `candidates --parent` looks. Epic, Feature, story
# is two levels; the third is room for a story that has sub-issues of its own.
CONTAINER_TREE_DEPTH = 3


def _tree_selection(depth):
    base = 'number title state issueType { name } repository { nameWithOwner }'
    if depth <= 0:
        return base
    # Fifty, not GitHub's hundred, because the levels multiply against the
    # query's node limit. `totalCount` says when a level held more.
    return base + (' subIssues(first:50){ totalCount nodes { %s } }'
                   % _tree_selection(depth - 1))


def _tree_node(node):
    subs = node.get('subIssues') or {}
    nodes = subs.get('nodes') or []
    return {'number': node['number'], 'title': node.get('title') or '',
            'state': node.get('state') or '',
            'type': (node.get('issueType') or {}).get('name'),
            'repo': (node.get('repository') or {}).get('nameWithOwner'),
            'unread': max(0, (subs.get('totalCount') or 0) - len(nodes)),
            'children': [_tree_node(c) for c in nodes]}


def _tree_unread(node, out=None):
    """Every node with sub-issues the tree query did not read, as
    [{'number', 'unread'}]: a Feature past the page size says so rather than
    losing stories from both `candidates` and `excluded`."""
    out = [] if out is None else out
    if node.get('unread'):
        out.append({'number': node['number'], 'unread': node['unread']})
    for child in node.get('children') or ():
        _tree_unread(child, out)
    return out


def fetch_container_tree(cfg, number):
    """The sub-issue tree under one issue, in one query. (ok, tree, err)."""
    ok, data, err = gh_graphql(
        'query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){'
        ' issue(number:$n){ %s } } }' % _tree_selection(CONTAINER_TREE_DEPTH),
        o=cfg['org'], r=cfg['repo'], n=int(number))
    if not ok or not data:
        return False, None, err or 'the sub-issue query failed'
    node = (data.get('repository') or {}).get('issue')
    if not node:
        return False, None, 'issue #%d not found' % int(number)
    return True, _tree_node(node), ''


def _tree_titles(node, out=None):
    out = {} if out is None else out
    out[node['number']] = node.get('title') or ''
    for child in node.get('children') or ():
        _tree_titles(child, out)
    return out


def fetch_issue_candidate(cfg, number):
    """Fetch one issue as a normalized candidate for the explicit `--issue` path.

    Emits + exits when the issue cannot be worked, and the checks are the pool's
    own rules rather than a shorter list: this path skips selection, so until
    10.1.2 it skipped every eligibility rule with it. `wf pick --issue N` would
    claim an issue owned by a person, assign itself, move the card to In
    Progress and hand back work no code agent can finish — and do the same to
    an issue somebody else was already assigned to.

    Refused, in order: not found, already closed, assigned to somebody,
    `Ownership` that is not `Code agent`, and a card in a lane that means the
    issue is not available. Dependencies are not checked here —
    `claim_validate_walk` does that for every path.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['issue', 'view', str(number), '--repo', repo,
                             '--json', 'number,title,labels,body,milestone,url,'
                                       'state,assignees'])
    if not ok or not data:
        emit('error', EXIT_ENV, reason='could not read issue #%d (%s)' % (number, err))
    if (data.get('state') or '').upper() == 'CLOSED':
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='issue #%d is already closed — nothing to pick' % number,
             number=number)

    assignees = [a.get('login') for a in data.get('assignees') or []]
    if assignees:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='issue #%d is assigned to %s, so it is already somebody\'s. '
                    'Unassign it first if that claim is stale.'
                    % (number, ', '.join(a for a in assignees if a)),
             number=number, assignees=assignees)

    facets = load_issue_facets(cfg, [number])
    ownership = (facets.get('ownership') or {}).get(number)
    scope = wf_core.ownership_scope(ownership)
    if scope != wf_core.SCOPE_CODE:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='issue #%d is owned by %s, so a code agent must not take it. '
                    'Set `%s` to `%s` if that is wrong.'
                    % (number, ownership or 'nobody — it carries no `%s` value'
                       % field_name(cfg, 'field-ownership'),
                       field_name(cfg, 'field-ownership'),
                       wf_core.OWNERSHIP_FIELD_OPTIONS[wf_core.SCOPE_CODE]),
             number=number, ownership=ownership)

    ok, lanes, lane_err = board_current_columns(cfg, [number])
    if not ok:
        emit('error', EXIT_ENV,
             reason='could not read where #%d sits on the board (%s), and the '
                    'column is what says whether it is available' % (number, lane_err),
             number=number)
    lane = lanes.get(number)
    if lane and lane not in PICKABLE_BY_NAME:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason="issue #%d is in the board's `%s` column, so it is not "
                    'available to pick. Move the card to `%s` if it should be.'
                    % (number, lane, wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN]),
             number=number, column=lane)
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

    # The pool first, then the fields of the issues in it. That order is the
    # point: these fields are read *about the pool*, so asking the repository
    # for its newest issues instead could answer about a different set
    # entirely.
    ok, issues, err = assemble_candidates(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)

    # The org's own view of those issues: native type, Priority, Effort,
    # Ownership, Classification. All five decide the pool -- what is in it,
    # what order it is in, how big each one is, whether a code agent may take
    # it, and which `Feature` counts as maintenance.
    facets = load_issue_facets(cfg, [i['number'] for i in issues])
    priority_map = facets['priority']
    effort_map = facets['effort']
    ownership_map = facets['ownership']
    type_map = classification_map = None
    if args.mode == 'story':
        # Read only to leave epics out; story mode classifies nothing.
        type_map = facets['types'] or None
    else:
        type_map = facets['types'] or None
        classification_map = facets['classification'] if type_map else None
        if not type_map:
            # The native type is the only classifier. Without one, `feature`
            # and `maintenance` are unanswerable -- and answering them wrongly
            # by label is exactly what this replaced.
            emit('no-capabilities', EXIT_CAPABILITY, mode=args.mode,
                 reason='no issue in this pool carries a native issue type, so '
                        '%s mode cannot be told apart from any other. Enable issue '
                        'types for the org and run `wf issue-audit` to backfill '
                        'them, or pick with `--mode story`.' % args.mode)
        eprint('wf: filtering %s mode by native issueType' % args.mode)

    # An issue the org has not typed is out of a feature/maintenance pool --
    # the native type is the only classifier now. Collected here so the run can
    # name it, because a pool that is quietly short reads as a clean backlog.
    unclassified = []

    oversized = []

    def selector(pool_issues):
        return wf_core.select_pool(
            pool_issues, mode=args.mode,
            project_map=cfg.get('labels', {}),
            type_map=type_map, classification_map=classification_map,
            unclassified=unclassified, priority_map=priority_map,
            effort_map=effort_map, ownership_map=ownership_map,
            max_effort=getattr(args, 'max_effort', None), oversized=oversized)

    backlog_mode, pool = ordered_pool(cfg, issues, selector)

    selected, side_effects = None, []
    if pool:
        selected, side_effects = claim_validate_walk(cfg, pool, backlog_mode, siblings)

    if not selected:
        restored = auto_unblock_scan(cfg)
        if restored:
            eprint('wf: unblock sweep released %d issue(s) — retrying' % restored)
            ok, issues, err = assemble_candidates(cfg)
            if ok and issues:
                facets = load_issue_facets(cfg, [i['number'] for i in issues])
                priority_map = facets['priority']
                effort_map = facets['effort']
                ownership_map = facets['ownership']
                backlog_mode, pool = ordered_pool(cfg, issues, selector)
                if pool:
                    selected, more_effects = claim_validate_walk(cfg, pool, backlog_mode,
                                                                 siblings)
                    side_effects.extend(more_effects)

    report_unprioritised(pool, priority_map)

    if unclassified:
        eprint('wf: %d issue(s) left out of the %s pool because the org has not '
               'typed or classified them: %s (run wf issue-audit to backfill)'
               % (len(set(unclassified)), args.mode,
                  ', '.join('#%d' % n for n in sorted(set(unclassified)))))

    if oversized:
        eprint('wf: %d issue(s) left out because their Effort is above '
               '--max-effort %s: %s'
               % (len(set(oversized)), args.max_effort,
                  ', '.join('#%d' % n for n in sorted(set(oversized)))))

    if not selected and not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='nothing in the %s column is available to a code agent'
                    % wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN],
             backlog_mode=backlog_mode, oversized=sorted(set(oversized)))
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
        moved, board_msg = best_effort(board_move_in_progress, cfg,
                                       selected['number'])
        result['board_moved'] = moved
        result['board_message'] = board_msg
        if not moved and board_msg != 'no board configured':
            eprint('wf: board move skipped — %s' % board_msg)
        dated, date_msg = best_effort(set_start_date, cfg, selected['number'])
        result['start_date_set'] = dated
        result['start_date_message'] = date_msg
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


def _mode_maps(cfg, mode, facets):
    """The (type_map, classification_map) `select_pool` reads for `mode`."""
    if mode == 'story':
        # Read only to leave epics out, as `pick` does.
        return facets['types'] or None, None
    if cfg.get('type_capable'):
        types = facets['types'] or None
        return types, (facets['classification'] if types else None)
    return None, None


def cmd_candidates(args):
    """List the Backlog pool in priority order, claiming nothing.

    `pick` collapses select-claim-branch into one call, which is exactly right
    when the caller wants *a* story. `bulk-execute` needs the opposite: it has
    to see the pool before it can decide which two to five stories belong in
    one pull request, and that decision is a judgement about relatedness that
    no sort order can make. This command gives it the same filtered, sorted
    pool `pick` would walk — the board's Backlog column, sprint narrowing,
    ownership filter, mode filter, any effort ceiling, and
    the priority-then-effort sort — and then stops. Nothing is claimed, nothing
    is labelled, no board moves. The caller picks its set and claims each
    member with `pick --issue`.

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

    ok, issues, err = assemble_candidates(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)

    facets = load_issue_facets(cfg, [i['number'] for i in issues])
    priority_map = facets['priority']
    effort_map = facets['effort']
    ownership_map = facets['ownership']
    type_map, classification_map = _mode_maps(cfg, args.mode, facets)

    unclassified = []
    oversized = []

    def selector(pool_issues):
        return wf_core.select_pool(
            pool_issues, mode=args.mode,
            project_map=cfg.get('labels', {}),
            type_map=type_map, classification_map=classification_map,
            unclassified=unclassified, priority_map=priority_map,
            effort_map=effort_map, ownership_map=ownership_map,
            max_effort=getattr(args, 'max_effort', None), oversized=oversized)

    backlog_mode, pool = ordered_pool(cfg, issues, selector)
    maps = {'priority': priority_map, 'effort': effort_map,
            'ownership': ownership_map}
    if getattr(args, 'parent', None):
        # Before the empty-pool exit: a parent whose leaves are all out of the
        # pool still owes the caller the list of why.
        candidates_under_parent(args, cfg, pool, maps)
    if not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='nothing in the %s column is available to a code agent'
                    % wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN],
             backlog_mode=backlog_mode, oversized=sorted(set(oversized)))

    total = len(pool)
    report_unprioritised(pool, priority_map)
    if args.limit and args.limit > 0:
        pool = pool[:args.limit]

    edge_map, edges_unknown = issue_edges_map(cfg, [c['number'] for c in pool])
    listed = [_candidate_entry(cand, edge_map.get(cand['number']) or [],
                               cand['number'] in edges_unknown, maps,
                               args.body_chars)
              for cand in pool]

    emit('ok', EXIT_OK, mode=args.mode, backlog_mode=backlog_mode,
         total=total, listed=len(listed), candidates=listed,
         # Issues the org has not typed or classified, and which are therefore
         # not in this pool at all. Reported so a short list reads as a gap in
         # the data rather than as a clean backlog.
         unclassified=sorted(set(unclassified)),
         # Candidates the org has given no Priority. Nothing orders them, so
         # they sit at the back of the listing -- reported as a count so a
         # caller reading a long tail of unranked work knows why.
         unprioritised_count=len([c for c in pool
                                  if not priority_map.get(c['number'])]))


def _candidate_entry(cand, edges, edges_unknown, maps, body_chars):
    """One `candidates` listing entry: the issue, its native edges, and the
    three fields every decision about it is made from."""
    number = cand['number']
    body = cand.get('body') or ''
    truncated = False
    if body_chars and body_chars > 0 and len(body) > body_chars:
        body, truncated = body[:body_chars], True
    open_deps, closed_deps = wf_core.edge_states(edges or [])
    ownership = (maps.get('ownership') or {}).get(number)
    return {
        'number': number,
        'title': cand['title'],
        'url': cand.get('url', ''),
        'labels': cand.get('labels', []),
        'milestone': cand.get('milestone'),
        'body': body,
        'body_truncated': truncated,
        # Straight from the native blocked-by edges: every issue this one
        # waits on, and which of them are still open. A candidate with an
        # open dependency is listed and marked rather than hidden, because
        # this command answers "what is there" and `pick` answers "what can
        # I start".
        'dependencies': sorted(open_deps + closed_deps),
        'dependencies_open': sorted(open_deps),
        'blocked': bool(open_deps),
        # True when the edges could not be read at all, so `blocked` says
        # nothing about this candidate rather than saying "no".
        'dependencies_unknown': bool(edges_unknown),
        'dependency_overflow': len(open_deps) > wf_core.DEP_LIMIT,
        # The three fields every decision about this issue is made from,
        # reported beside the issue so a caller choosing a set can see what
        # the picker saw. `scope` is the `Ownership` value read as one of
        # the three parties, and it is the field's own answer -- it was
        # derived from the title prefix until 10.1.2, which meant this
        # listing could disagree with the filter that produced it.
        'ownership': ownership,
        'scope': wf_core.ownership_scope(ownership),
        'effort': (maps.get('effort') or {}).get(number),
        # The org's own Priority, which is the only thing this listing is
        # ordered by. None means the issue carries no value and sorts last.
        'priority': (maps.get('priority') or {}).get(number),
    }


def candidates_under_parent(args, cfg, pool, maps):
    """`candidates --parent N`: the one bulk set the tree under N offers.

    The pool is the same pool as ever, narrowed to N's leaves, plus the one
    exception #239 settled: a leaf in the Blocked column whose every open
    blocker is another leaf taken in the same run. Non-code work is never
    taken, because it is neither in the pool nor owned by the code agent.
    Every other leaf under N is listed in `excluded` with its reason, so a
    short set reads as a decision rather than as a gap. The choice itself is
    `wf_core.choose_parent_set`; this is the reading around it.
    """
    ok, tree, err = fetch_container_tree(cfg, args.parent)
    if not ok:
        emit('error', EXIT_ENV, reason='could not read the sub-issues of #%d (%s)'
                                       % (args.parent, err))
    parent = {'number': tree['number'], 'title': tree['title'], 'type': tree['type']}
    if tree['type'] not in wf_core.HIERARCHY_CONTAINER_TYPES:
        emit('usage', EXIT_USAGE, parent=parent,
             reason='#%d is %s, not an Epic or Feature, so it has no stories to '
                    'choose from. Name its parent, or name the stories directly.'
                    % (args.parent, ('a %s' % tree['type']) if tree['type']
                       else 'untyped'))

    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    groups, _, _ = wf_core.parent_leaf_groups(tree, repo)
    leaves = [n for members in groups.values() for n in members]
    wanted = set(leaves)
    pool = [c for c in pool if c['number'] in wanted]
    pool_by = {c['number']: c for c in pool}
    outside = [n for n in leaves if n not in pool_by]

    # The fields and the Blocked column are read only for leaves the pool did
    # not already answer for.
    out_maps = {'priority': {}, 'effort': {}, 'ownership': {}}
    blocked = {}
    if outside:
        facets = load_issue_facets(cfg, outside)
        out_maps = {k: facets.get(k) or {} for k in out_maps}
        column, berr = blocked_issues(cfg)
        if berr:
            emit('error', EXIT_ENV,
                 reason='could not read the %s column (%s), so which leaves '
                        'wait only on each other is unknown'
                        % (wf_core.BOARD_COLUMN_NAMES['col-blocked'], berr))
        # The same filter the pool went through -- ownership, `--mode`, any
        # effort ceiling -- so the one exception #239 made is about the
        # column and nothing else. A Blocked story does not join a bug's set.
        cards = [i for i in column
                 if i['number'] in wanted and i['number'] not in pool_by
                 and not i.get('assigned')]
        types, classes = _mode_maps(cfg, args.mode, facets)
        blocked = {i['number']: i for i in wf_core.select_pool(
            cards, mode=args.mode, project_map=cfg.get('labels', {}),
            type_map=types, classification_map=classes, unclassified=[],
            priority_map=out_maps['priority'], effort_map=out_maps['effort'],
            ownership_map=out_maps['ownership'],
            max_effort=getattr(args, 'max_effort', None), oversized=[])}

    edge_map, edges_unknown = issue_edges_map(cfg, list(pool_by))
    blocked_edges = {n: ((i.get('blockedBy') or {}).get('nodes')) or []
                     for n, i in blocked.items()}
    deps = {}
    for n in leaves:
        if n in pool_by:
            deps[n] = wf_core.edge_states(edge_map.get(n) or [])[0]
        elif n in blocked:
            deps[n] = wf_core.edge_states(blocked_edges[n])[0]

    pool_column = wf_core.BOARD_COLUMN_NAMES[wf_core.POOL_COLUMN]
    reasons = {}
    rest = [n for n in outside if n not in blocked]
    if rest:
        ok, lanes, _ = board_current_columns(cfg, rest)
        for n in rest:
            lane = lanes.get(n) if ok else None
            owner = out_maps['ownership'].get(n)
            why = []
            if lane and lane != pool_column:
                why.append('in the `%s` column' % lane)
            if wf_core.ownership_scope(owner) != wf_core.SCOPE_CODE:
                why.append('owned by %s, not the code agent' % (owner or 'nobody'))
            reasons[n] = ', '.join(why) or 'not in the pool (assigned, or left out by --mode)'

    choice = wf_core.choose_parent_set(tree, [c['number'] for c in pool], deps,
                                       reasons, max_size=args.size, repo=repo)
    titles = _tree_titles(tree)
    excluded = [dict(e, title=titles.get(e['number'], '')) for e in choice['excluded']]
    listed = []
    for story in choice['selected']:
        n = story['number']
        if n in pool_by:
            entry = _candidate_entry(pool_by[n], edge_map.get(n) or [],
                                     n in edges_unknown, maps, args.body_chars)
            entry['column'] = pool_column
        else:
            entry = _candidate_entry(blocked[n], blocked_edges[n], False,
                                     out_maps, args.body_chars)
            entry['column'] = wf_core.BOARD_COLUMN_NAMES['col-blocked']
        listed.append(entry)

    unread = _tree_unread(tree)
    note = ''
    if unread:
        note = ('; %s had more sub-issues than one read returns, so %d were not '
                'read and are in neither list'
                % (', '.join('#%d' % u['number'] for u in unread),
                   sum(u['unread'] for u in unread)))
    if not listed:
        emit('no-candidates', EXIT_NO_CANDIDATES, parent=parent, excluded=excluded,
             unread=unread,
             reason='nothing under #%d is available to a code agent%s'
                    % (args.parent, note))
    emit('ok', EXIT_OK, mode=args.mode, parent=parent, feature=choice['group'],
         total=len(listed), listed=len(listed), candidates=listed,
         excluded=excluded, unread=unread,
         reason='%d stor%s under #%d%s' % (len(listed), 'y' if len(listed) == 1
                                           else 'ies', args.parent, note))


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


# ── closing a finished container (#240) ──────────────────────────────────────

# How far up a merged story's parents the walk reads: story, Feature, Epic,
# and one more for a tree nested deeper than the usual three levels.
CONTAINER_CHAIN_DEPTH = 4

CONTAINER_CLOSE_COMMENT = (
    'Closing as completed: every sub-issue is closed, and #%d was the last to '
    'close. Reopen this if more work is planned under it.')
CONTAINER_SWEEP_COMMENT = (
    'Closing as completed: every sub-issue is closed. Found by `wf preflight '
    '--fix`; reopen this if more work is planned under it.')

_CONTAINER_NODE = ('number title state issueType { name }'
                   ' repository { nameWithOwner }'
                   ' subIssues(first:100){ nodes { number state } }')


def _container_node(node):
    return {'number': node['number'], 'title': node.get('title') or '',
            'state': node.get('state') or '',
            'type': (node.get('issueType') or {}).get('name'),
            'repo': (node.get('repository') or {}).get('nameWithOwner'),
            'children': [{'number': c.get('number'), 'state': c.get('state')}
                         for c in (node.get('subIssues') or {}).get('nodes') or []]}


def _chain_selection(depth):
    if depth <= 1:
        return _CONTAINER_NODE
    return _CONTAINER_NODE + ' parent { %s }' % _chain_selection(depth - 1)


def fetch_parent_chain(cfg, number):
    """The parents above one issue, nearest first. (ok, chain, err)."""
    ok, data, err = gh_graphql(
        'query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){'
        ' issue(number:$n){ parent { %s } } } }' % _chain_selection(CONTAINER_CHAIN_DEPTH),
        o=cfg['org'], r=cfg['repo'], n=int(number))
    if not ok or not data:
        return False, [], err or 'the parent query failed'
    node = (((data.get('repository') or {}).get('issue')) or {}).get('parent')
    chain = []
    while node:
        chain.append(_container_node(node))
        node = node.get('parent')
    return True, chain, ''


def close_container(cfg, number, comment):
    """Close one finished container as completed and move its card to Done."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    code, _, err = run(['gh', 'issue', 'close', str(number), '--repo', repo,
                        '--reason', 'completed', '--comment', comment])
    if code != 0:
        return {'issue': number, 'closed': False,
                'error': err.strip() or 'gh issue close failed'}
    moved, message = board_move(cfg, number, wf_core.BOARD_COLUMN_NAMES['col-done'])
    return {'issue': number, 'closed': True, 'board_moved_done': moved,
            'board_message': message}


def close_finished_ancestors(cfg, numbers):
    """Close every Epic or Feature that closing `numbers` finished (#240).

    Walks up each issue's parents and stops at the first that still has an
    open child, so closing a Feature can finish its Epic in the same run. A
    parent in another repository is left alone. Returns (closed, errors):
    one entry per container it tried to close, and each parent chain that
    could not be read.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    done = {int(n) for n in numbers or ()}
    closed, errors = [], []
    for number in numbers or ():
        ok, chain, err = fetch_parent_chain(cfg, number)
        if not ok:
            errors.append('#%d: %s' % (number, err))
            continue
        for step in wf_core.ancestors_to_close(number, chain, done, repo):
            if step['number'] in done:
                continue
            result = close_container(cfg, step['number'],
                                     CONTAINER_CLOSE_COMMENT % step['finished_by'])
            result['finished_by'] = step['finished_by']
            closed.append(result)
            if not result['closed']:
                # The ancestors above were judged on this one closing.
                break
            done.add(step['number'])
    return closed, errors


def _fix_finished_containers(cfg, containers):
    """Close every open Epic or Feature preflight found already finished.

    The preflight half of #240: the merge closes what it finishes from now
    on, and `fetch_board_placement` finds the ones that finished before it did.
    """
    if not containers:
        return [], []
    closed, failed = [], []
    for container in containers:
        result = close_container(cfg, container['number'], CONTAINER_SWEEP_COMMENT)
        if result['closed']:
            closed.append(container['number'])
        else:
            failed.append('#%d (%s)' % (container['number'], result['error']))
    # The same rule as post-merge: closing a Feature can finish its Epic, and
    # a second `--fix` should not be what it takes to see that.
    above, errors = close_finished_ancestors(cfg, closed)
    closed += [c['issue'] for c in above if c['closed']]
    failed += ['#%d (%s)' % (c['issue'], c['error']) for c in above if not c['closed']]
    failed += errors
    done, blocked = [], []
    if closed:
        done.append('closed %d finished Epic or Feature issue%s: %s'
                    % (len(closed), '' if len(closed) == 1 else 's',
                       ', '.join('#%d' % n for n in closed)))
    if failed:
        blocked.append('could not close %s' % ', '.join(failed))
    return done, blocked


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
        # Whether the issue is closed once this is done. The container walk
        # below reads it: an Epic or Feature is only finished by a close that
        # happened, not by one that was attempted.
        closed = bool(ok and idata and (idata.get('state') or '').upper() == 'CLOSED')
        if was_open:
            code, _, _ = run(['gh', 'issue', 'close', str(number), '--repo', repo,
                              '--comment', 'Closing — resolved by merged PR #%d.' % args.pr])
            closed = code == 0
        # A settled issue is Done: strip any open-state lifecycle label it still
        # carries (e.g. a PR that auto-closed the issue but left status-in-review
        # on).
        cleared = clear_lifecycle_label(cfg, number, label_names)
        board_moved, board_msg = board_move(cfg, number, 'Done')
        settled.append({'issue': number, 'closed_now': bool(was_open and closed),
                        'closed': closed,
                        'lifecycle_label_cleared': cleared,
                        'board_moved_done': board_moved, 'board_message': board_msg})

    # Settling the issues the PR closed is only half of a merge. The other half
    # is releasing whatever was waiting on them, and nothing used to do it: a
    # PR that closes nothing reports `settled: []`, which reads as "finished"
    # and is not. The sweep runs whether or not anything settled, because the
    # merge may have closed a blocker through a reference this never saw.
    # Closing a story can finish the Epic or Feature above it, and nothing
    # else ever closes one (#240). Walked before the unblock sweep, so anything
    # waiting on a container this closes is released by the same run.
    containers, container_errors = close_finished_ancestors(
        cfg, [s['issue'] for s in settled if s['closed']])

    unblocked = unblock_scan(cfg) if not args.no_unblock else None

    emit('ok', EXIT_OK, pr=args.pr, base=data.get('baseRefName'), settled=settled,
         containers_closed=containers, container_errors=container_errors,
         unblocked=unblocked)


# ── board-move and claim-release ─────────────────────────────────────────────
# The two pieces a caller still needs to reach on their own: moving an issue
# to a named column, and letting a claim go. Everything else — identity
# verification, adding the issue to the board, resolving the option id, the
# compare-and-swap — is already the body of `board_move()` and
# `release_claim()` above.


def cmd_board_move(args):
    cfg = prepare_cfg()
    column = args.column
    if column.startswith('col-'):
        # Accept the purpose key as well as the column's own name, because
        # `ClaudeProject.md` records the purpose and the board holds the name.
        column = wf_core.BOARD_COLUMN_NAMES.get(column, column)

    moved, message = board_move(cfg, args.number, column)
    if moved:
        emit('ok', EXIT_OK, number=args.number, column=column, moved=True,
             reason='#%d moved to %s' % (args.number, column))
    # A failed move is reported and never fatal, but it is not harmless
    # either: the column *is* the state, so an issue whose move failed is left
    # in whichever lane it was already in. Callers surface the reason.
    emit('ok', EXIT_OK, number=args.number, column=column, moved=False,
         reason='board not updated: %s' % message)


def apply_claim_marker(cfg, args):
    """Apply the human-visible ownership marker for a won claim.

    Returns a short description of what was applied, or None. Best-effort:
    the claim is already held, and failing to advertise it is worth a warning
    rather than giving the item back.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    if args.issue is not None:
        # The labels are read only so that any retired one can be taken off
        # on the way past; nothing is applied in their place.
        ok, data, _ = gh_json(['issue', 'view', str(args.issue), '--repo', repo,
                               '--json', 'labels'])
        if not ok or data is None:
            eprint('wf: warning - could not read issue #%d to mark it' % args.issue)
            return None
        apply_in_progress(cfg, {'number': args.issue,
                                'labels': [l['name'] for l in data.get('labels', [])]})
        return '@me + the In Progress column'
    names = wf_core.review_names(cfg.get('review_labels'))
    code, _, err = run(['gh', 'pr', 'edit', str(args.pr), '--repo', repo,
                        '--remove-label', names['needs-review'],
                        '--add-label', names['reviewing']])
    if code != 0:
        eprint('wf: warning - could not apply the reviewing label (%s)' % err.strip())
        return None
    return names['reviewing']


def cmd_claim(args):
    """Take the atomic claim on one issue or PR, without selecting anything.

    `pick` and `review-next` claim what they select. This is for the caller
    that already knows which item it wants — a named PR under review, a story
    a person asked for by number — and needs the same compare-and-swap.
    """
    err = check_environment()
    if err:
        emit('error', EXIT_ENV, reason=err)
    if (args.issue is None) == (args.pr is None):
        emit('usage', EXIT_USAGE, reason='name exactly one of --issue N or --pr N')
    target = ('issue-%d' % args.issue) if args.issue else ('pr-%d' % args.pr)

    outcome = acquire_claim(target)
    if outcome == 'won':
        # The ref is the lock, but it is ephemeral. Ownership has to be
        # visible on GitHub too, or a picker running after this session dies
        # selects the item again: assignment plus the in-progress label for an
        # issue, the `reviewing` state label for a PR.
        marker = apply_claim_marker(prepare_cfg(), args) if args.marker else None
        emit('ok', EXIT_OK, target=target, claimed=True, marker=marker,
             reason='claimed %s' % target)
    if outcome == 'lost':
        # A rival agent holds it. Normal, and not an error: the caller moves on
        # to the next item rather than reporting a broken environment.
        emit('lost', EXIT_LOST, target=target, claimed=False,
             reason='%s is already claimed by another run' % target)
    emit('error', EXIT_ENV, target=target, claimed=False,
         reason='could not push the claim ref for %s; this is an environment '
                'problem, not a rival — check write access to refs/claims/*'
                % target)


def cmd_claim_release(args):
    err = check_environment()
    if err:
        emit('error', EXIT_ENV, reason=err)
    released = []
    for number in args.issue or []:
        release_claim('issue-%d' % number)
        released.append('issue-%d' % number)
    for number in args.pr or []:
        release_claim('pr-%d' % number)
        released.append('pr-%d' % number)
    if not released:
        emit('usage', EXIT_USAGE,
             reason='name what to release: --issue N and/or --pr N')
    emit('ok', EXIT_OK, released=released,
         reason='released %s' % ', '.join(released))


# ── sibling-pr ───────────────────────────────────────────────────────────────

SIBLING_PR_QUERY = (
    'query($owner:String!,$repo:String!){'
    ' repository(owner:$owner,name:$repo){'
    ' pullRequests(states:OPEN, first:100,'
    ' orderBy:{field:CREATED_AT, direction:ASC}){'
    ' nodes { number title url headRefName isDraft'
    ' labels(first:20){ nodes { name } }'
    ' closingIssuesReferences(first:10){ nodes { number } } } } } }'
)


def cmd_sibling_pr(args):
    """Report the open PRs that will close an issue on merge.

    One call, one definition of "duplicate", for the three places that ask:
    the pre-start guard, the create-time duplicate flag, and code review's
    reconciliation. Finding none is the normal answer, so it is `ok` and exit
    0 with an empty list — only a failed lookup is an error.
    """
    cfg = prepare_cfg()
    ok, data, err = gh_graphql(SIBLING_PR_QUERY, owner=cfg['org'], repo=cfg['repo'])
    if not ok or not data:
        emit('error', EXIT_ENV,
             reason='could not read open PRs (%s)' % (err.strip() or 'no detail'))
    try:
        nodes = data['repository']['pullRequests']['nodes']
    except (KeyError, TypeError):
        emit('error', EXIT_ENV, reason='unexpected pullRequests shape')
    prs = wf_core.select_sibling_prs(nodes, args.number, args.exclude_branch)
    emit('ok', EXIT_OK, issue=args.number, found=len(prs), prs=prs,
         reason=('no open PR closes #%d' % args.number) if not prs else
                'open PR(s) closing #%d: %s'
                % (args.number, ', '.join('#%d' % p['number'] for p in prs)))


# ── claim-reap ───────────────────────────────────────────────────────────────

def list_claim_refs():
    """Every claim ref on the remote, as [(sha, target)]. Fetches the objects
    first so their commit timestamps can be read without a call per ref."""
    run(['git', 'fetch', '--prune', 'origin',
         '+refs/claims/*:refs/remotes/origin/claims/*'])
    code, out, err = run(['git', 'ls-remote', 'origin', 'refs/claims/*'])
    if code != 0:
        return None, err.strip() or 'git ls-remote failed'
    refs = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith('refs/claims/'):
            refs.append((parts[0], parts[1][len('refs/claims/'):]))
    return refs, ''


def claim_age_hours(sha):
    """Hours since the claim object was written, or None if unreadable."""
    code, out, _ = run(['git', 'show', '-s', '--format=%ct', sha])
    if code != 0 or not out.strip():
        return None
    try:
        return int((time.time() - int(out.strip().split()[-1])) // 3600)
    except ValueError:
        return None


def claim_target_state(cfg, target):
    """Read the issue or PR a claim ref names.

    Returns `(kind, number, state, labels, has_open_pr, assigned)`. `state` is
    None when the lookup failed. `assigned` is what tells a live issue claim
    from an abandoned one now that no label does: `apply_in_progress` assigns
    `@me`, so an issue claim over an unassigned issue is a claim nobody holds.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    kind, _, raw = target.partition('-')
    try:
        number = int(raw)
    except ValueError:
        return None, None, None, [], False, False
    if kind not in ('issue', 'pr'):
        return None, None, None, [], False, False

    fields = 'state,labels,assignees' if kind == 'issue' else 'state,labels'
    ok, data, _ = gh_json([kind, 'view', str(number), '--repo', repo,
                           '--json', fields])
    if not ok or not data:
        return kind, number, None, [], False
    labels = [l['name'] for l in data.get('labels', [])]
    state = data.get('state', '')
    assigned = bool(data.get('assignees'))

    has_open_pr = False
    if kind == 'issue' and state.upper() == 'OPEN':
        ok, prs, _ = gh_json(['pr', 'list', '--repo', repo, '--state', 'open',
                              '--search', 'closes #%d' % number, '--json', 'number'])
        has_open_pr = bool(ok and prs)
    return kind, number, state, labels, has_open_pr, assigned


def cmd_claim_reap(args):
    """Free claim refs whose work has demonstrably moved on; flag the rest.

    Replaces the hand-run procedure this command was extracted from. The
    judgement is `wf_core.reap_verdict`; everything here is I/O.
    """
    err = check_environment()
    if err:
        emit('error', EXIT_ENV, reason=err)
    cfg = prepare_cfg()
    refs, ferr = list_claim_refs()
    if refs is None:
        emit('error', EXIT_ENV, reason='could not list claim refs (%s)' % ferr)
    if not refs:
        emit('ok', EXIT_OK, reaped=[], suspect=[], skipped=[],
             reason='no active claim refs')

    names = wf_core.review_names(cfg.get('review_labels'))
    active_review = [names['reviewing'], names['updating']]

    results, detail = [], {wf_core.REAP: [], wf_core.SUSPECT: [], wf_core.SKIP: []}
    for sha, target in refs:
        kind, number, state, labels, has_open_pr, assigned = \
            claim_target_state(cfg, target)
        age = claim_age_hours(sha)
        if kind is None:
            verdict, reason = wf_core.SUSPECT, 'not an issue or PR claim'
        else:
            verdict, reason = wf_core.reap_verdict(
                kind, age, state, labels, threshold=args.threshold,
                review_labels=active_review, has_open_pr=has_open_pr,
                assigned=assigned)
        results.append((target, verdict, reason))
        entry = {'ref': 'refs/claims/%s' % target, 'reason': reason}
        if age is not None:
            entry['age_hours'] = age
        if verdict == wf_core.REAP and not args.dry_run:
            release_claim(target)
        detail[verdict].append(entry)

    summary = wf_core.reap_summary(results)
    emit('ok', EXIT_OK, reaped=detail[wf_core.REAP],
         suspect=detail[wf_core.SUSPECT], skipped=detail[wf_core.SKIP],
         summary=summary, dry_run=bool(args.dry_run),
         reason='%d reaped, %d suspect (check by hand), %d too recent'
                % (summary['reaped'], summary['suspect'], summary['skipped']))


# ── handoff ──────────────────────────────────────────────────────────────────

def cmd_handoff(args):
    """Hand a finished story to review: label the PR, move the issue and its
    board item to in-review, and release the issue claim.

    One command for what was a combined GraphQL mutation plus a fallback
    chain. Plain `gh` edits cost fewer round trips than the mutation did once
    its node-id and label-id lookups are counted, and they need no label
    cache, so the fallback has nothing left to fall back from.
    """
    cfg = prepare_cfg()
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    names = wf_core.review_names(cfg.get('review_labels'))
    state_label = names['changes-requested' if args.gate_failed else 'needs-review']

    code, _, perr = run(['gh', 'pr', 'edit', str(args.pr), '--repo', repo,
                         '--add-label', label(cfg, 'claude-authored'),
                         '--add-label', state_label])
    pr_labelled = code == 0
    if not pr_labelled:
        eprint('wf: warning - could not label PR #%d (%s)' % (args.pr, perr.strip()))

    issues = []
    for number in args.issue or []:
        # The move *is* the hand-off. There is no label to swap any more:
        # an issue waiting on a review is one whose card sits in In Review,
        # and that is the only place the state is written.
        moved, message = board_move(cfg, number,
                                    wf_core.BOARD_COLUMN_NAMES['col-in-review'])
        if not moved:
            eprint('wf: warning - could not move #%d to In Review (%s)'
                   % (number, message))
        release_claim('issue-%d' % number)
        issues.append({'number': number, 'board_moved': moved, 'board': message})

    for name in ('plan.md', 'preflight-passed.txt', 'label-cache.json'):
        try:
            os.remove(os.path.join(repo_root(), '.claude', name))
        except OSError:
            pass

    emit('ok', EXIT_OK, pr=args.pr, pr_labelled=pr_labelled,
         review_label=state_label, issues=issues,
         reason='PR #%d labelled %s; %d issue(s) handed to review'
                % (args.pr, state_label, len(issues)))


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
                      help='selection mode; feature and maintenance filter the pool '
                           "by the org's native issueType")
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
    pick.add_argument('--max-effort', default=None, choices=['low', 'medium', 'high'],
                      help='skip anything the org has estimated larger than this. '
                           'An issue with no Effort value is always kept: a '
                           'ceiling is a statement about known size, not a '
                           'reason to hide unestimated work')
    pick.add_argument('--sibling', type=int, action='append', default=None,
                      help='an issue being built alongside this one on the same branch '
                           '(repeatable); a dependency on one of them does not block the '
                           'pick, because this run writes it too')
    pick.set_defaults(func=cmd_pick)

    cand = sub.add_parser('candidates',
                          help='list the Backlog pool in priority order without claiming '
                               'anything (bulk-execute chooses its set from this)')
    cand.add_argument('--mode', default='story', choices=['story', 'feature', 'maintenance'],
                      help='selection mode, applied exactly as `pick` applies it')
    cand.add_argument('--max-effort', default=None, choices=['low', 'medium', 'high'],
                      help='skip anything the org has estimated larger than this. '
                           'An issue with no Effort value is always kept: a '
                           'ceiling is a statement about known size, not a '
                           'reason to hide unestimated work')
    cand.add_argument('--limit', type=int, default=25,
                      help='maximum candidates to list, highest priority first (default 25; '
                           '0 for all). `total` always reports the unclipped pool size')
    cand.add_argument('--body-chars', type=int, default=600,
                      help='truncate each body to this many characters (default 600; '
                           '0 for the whole body)')
    cand.add_argument('--parent', type=int, default=None,
                      help='narrow to the leaves under this Epic or Feature and '
                           'choose one bulk set from them: one Feature per run, '
                           'Backlog leaves plus any Blocked leaf waiting only on '
                           'another leaf taken; everything else is listed in '
                           '`excluded` with its reason')
    cand.add_argument('--size', type=int, default=wf_core.BULK_MAX,
                      help='with --parent, the most leaves to take, highest '
                           'priority first (default %d)' % wf_core.BULK_MAX)
    cand.set_defaults(func=cmd_candidates)

    pm = sub.add_parser('post-merge',
                        help='settle a merged PR: close any still-open linked issue and '
                             'move every linked issue to Done')
    pm.add_argument('--pr', type=int, required=True, help='the merged PR number')
    pm.add_argument('--issue', type=int, action='append', default=None,
                    help='also settle this issue (repeatable) — for a reference GitHub did '
                         'not parse into closingIssuesReferences')
    pm.add_argument('--no-unblock', action='store_true',
                    help='settle the linked issues without running the unblock sweep '
                         'afterwards (the sweep is the half that releases whatever was '
                         'waiting on them, so skip it only when running it separately)')
    pm.set_defaults(func=cmd_post_merge)

    ub = sub.add_parser('unblock',
                        help='release every blocked issue whose native blocked-by '
                             'edges have all closed, and report the rest')
    ub.add_argument('--issue', type=int, action='append', default=None,
                    help='consider only this issue (repeatable); the default is every '
                         'open issue carrying the blocked label')
    ub.add_argument('--dry-run', action='store_true',
                    help='report what would be released without writing anything')
    ub.set_defaults(func=cmd_unblock)

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
    au.add_argument('--parents', action='store_true',
                    help='also read the parent each body claims ("Part of the '
                         'X epic (#N)") and propose it where the issue has '
                         'none. Off by default: an issue created from a spec '
                         'already carries its parent, so this is for a backlog '
                         'written before that, or issues filed by hand')
    au.add_argument('--quiet', action='store_true',
                    help='report counts only, keeping the exit code, for CI')
    au.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    au.set_defaults(func=cmd_issue_audit)

    ca = sub.add_parser('config-audit',
                        help='report configuration and label drift between '
                             'ClaudeProject.md, the repo and the org')
    ca.add_argument('--repo', default=None,
                    help='audit this owner/name instead of the configured repo')
    ca.add_argument('--scan', action='append', default=None,
                    help='directory of instruction files to scan for label '
                         'references (repeatable; defaults to the plugin root)')
    ca.add_argument('--offline', action='store_true',
                    help='run only the checks that need no network')
    ca.add_argument('--quiet', action='store_true',
                    help='report counts only, keeping the exit code, for CI')
    ca.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    ca.set_defaults(func=cmd_config_audit)

    pf = sub.add_parser('preflight',
                        help='is this project in a state a workflow command '
                             'can run against? `--fix` repairs what can be '
                             'repaired without guessing')
    pf.add_argument('--fix', action='store_true',
                    help='repair every finding that has a safe automatic fix, '
                         'then re-run the checks and report what is left')
    pf.add_argument('--repo', default=None,
                    help='check this owner/name instead of the configured repo')
    pf.add_argument('--scan', action='append', default=None,
                    help='directory of instruction files to scan for label '
                         'references (repeatable; defaults to the plugin root)')
    pf.add_argument('--offline', action='store_true',
                    help='run only the checks that need no network')
    pf.add_argument('--quiet', action='store_true',
                    help='report counts only, keeping the exit code, for CI')
    pf.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    pf.set_defaults(func=cmd_preflight)

    bm = sub.add_parser('board-move',
                        help='move an issue to a board column (no-op with no '
                             'board configured)')
    bm.add_argument('number', type=int, help='issue number')
    bm.add_argument('--column', required=True,
                    help='column name ("In Review") or purpose key (col-in-review)')
    bm.set_defaults(func=cmd_board_move)

    cl = sub.add_parser('claim',
                        help='take the atomic claim on a named issue or PR')
    cl.add_argument('--issue', type=int, default=None, help='issue number')
    cl.add_argument('--pr', type=int, default=None, help='PR number')
    cl.add_argument('--no-marker', dest='marker', action='store_false',
                    default=True,
                    help='take the lock without advertising it on GitHub '
                         '(assignment / reviewing label)')
    cl.set_defaults(func=cmd_claim)

    cr = sub.add_parser('claim-release',
                        help='release the claim ref an interrupted run left behind')
    cr.add_argument('--issue', type=int, action='append', default=None,
                    help='issue number to release (repeatable)')
    cr.add_argument('--pr', type=int, action='append', default=None,
                    help='PR number to release (repeatable)')
    cr.set_defaults(func=cmd_claim_release)

    rp = sub.add_parser('claim-reap',
                        help='free claim refs a crashed run left behind')
    rp.add_argument('--threshold', type=int, default=wf_core.REAP_THRESHOLD_HOURS,
                    help='minimum age in hours before a ref may be reaped '
                         '(default %d)' % wf_core.REAP_THRESHOLD_HOURS)
    rp.add_argument('--dry-run', action='store_true',
                    help='report the verdicts without deleting any ref')
    rp.set_defaults(func=cmd_claim_reap)

    sp = sub.add_parser('sibling-pr',
                        help='list the open PRs that will close an issue')
    sp.add_argument('number', type=int, help='issue number')
    sp.add_argument('--exclude-branch', default=None,
                    help='drop the PR on this head branch (your own)')
    sp.set_defaults(func=cmd_sibling_pr)

    ho = sub.add_parser('handoff',
                        help='hand a finished story to review: label the PR, '
                             'move the issue and board, release the claim')
    ho.add_argument('--pr', type=int, required=True, help='the PR just opened')
    ho.add_argument('--issue', type=int, action='append', default=None,
                    help='issue the PR closes (repeatable)')
    ho.add_argument('--gate-failed', action='store_true',
                    help='the quality gate failed, so enter review as '
                         'changes-requested rather than needs-review')
    ho.set_defaults(func=cmd_handoff)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
