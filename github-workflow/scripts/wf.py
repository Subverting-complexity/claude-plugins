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

Contract:
  - A single JSON object is written to **stdout**; all human diagnostics go to
    **stderr**. A caller can parse stdout without stripping prose.
  - Every run's JSON carries a `status` field; the process exit code mirrors it:
      0  status=ok            an item was claimed (and checked out, if asked)
      10 status=no-candidates the ready pool was empty
      11 status=all-blocked   every candidate was blocked / already resolved
      20 status=error         environment/auth problem (not in a repo, no gh, …)
      30 status=unsupported   this path isn't in the CLI yet — caller should
                              fall back to the inline skill procedure
  - Mutations to the *winning* issue (claim, assign, status-in-progress) are
    silent; mutations to *other* issues (marking blocked, closing resolved) are
    always reported back in the `side_effects` array.

Selection covers `--mode story` plus `--mode feature` / `--mode maintenance`
on label-typed projects, under the `label` / `none` ready-gates. The paths
that still exit 30 so the skill handles them: feature/maintenance on a
*type-capable* org (native issue type is authoritative, not resolved here),
and the `board-column` / `both` ready-gates. See
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
    """Run a subprocess, capturing text output. Returns (code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            args, input=input_text, capture_output=True, text=True,
        )
    except FileNotFoundError:
        return 127, '', '%s: not found' % args[0]
    return proc.returncode, proc.stdout, proc.stderr


def gh_json(args):
    """Run `gh <args>` expecting JSON on stdout. Returns (ok, parsed, stderr)."""
    code, out, err = run(['gh'] + args)
    if code != 0:
        return False, None, err.strip()
    try:
        return True, json.loads(out) if out.strip() else None, ''
    except json.JSONDecodeError as exc:
        return False, None, 'could not parse gh JSON: %s' % exc


def gh_graphql(query, **fields):
    """Run a GraphQL query/mutation via `gh api graphql`. Returns (ok, data, err).

    String fields are passed with -F (typed: ints stay ints, etc.).
    """
    args = ['gh', 'api', 'graphql', '-f', 'query=%s' % query]
    for key, value in fields.items():
        args += ['-F', '%s=%s' % (key, value)]
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
    """
    m = re.search(r'^(#{1,6})\s*%s\s*$' % re.escape(heading), text,
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
        'labels': {}, 'review_labels': {}, 'ready_gate': 'label',
        'agent_gating': 'disabled', 'type_capable': False,
        'board': {'project_node_id': None, 'project_title': None,
                  'status_field_id': None, 'start_date_field_id': None,
                  'columns': {}},
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
        cfg['branch_convention'] = m.group(1)

    label_block = _section(text, 'Label Map')
    for cells in _rows(label_block):
        if len(cells) >= 2 and cells[0] and cells[1] and cells[0].lower() != 'purpose':
            # only keep rows whose purpose looks like a known purpose key
            if re.match(r'^[a-z]+-[a-z-]+$', cells[0]):
                cfg['labels'][cells[0]] = cells[1]

    for cells in _rows(_section(text, 'Ready Gate')):
        if len(cells) >= 2 and cells[0].lower() == 'ready-gate':
            cfg['ready_gate'] = cells[1].lower()
    for cells in _rows(_section(text, 'Agent Gating')):
        if len(cells) >= 2 and cells[0].lower() == 'agent-gating':
            cfg['agent_gating'] = cells[1].lower()

    if re.search(r'is\*{0,2}\s*type-capable', text, re.IGNORECASE):
        cfg['type_capable'] = True

    board_block = _section(text, 'Project Board')
    for cells in _rows(board_block):
        if len(cells) >= 2:
            key, val = cells[0].lower(), cells[1]
            if key == 'project-node-id':
                cfg['board']['project_node_id'] = None if val in ('n/a', '') else val
            elif key == 'project-title':
                cfg['board']['project_title'] = val
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
    return False, None, 'ready-gate %r not supported by wf (use the skill)' % gate


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

def validate_issue(cfg, issue):
    """Validate a claimed issue. Returns (verdict, detail).

    verdict ∈ {'valid', 'blocked', 'resolved'}:
      blocked  → open dependencies (detail = list of open #s, or 'meta' on overflow)
      resolved → already closed by a merged PR (detail = pr number)
      valid    → ready to work
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    deps, overflow = wf_core.parse_dependencies(issue['body'])
    if overflow:
        return 'blocked', 'meta-issue (> %d dependencies)' % wf_core.DEP_LIMIT
    open_deps = []
    for dep in deps:
        ok, data, _ = gh_json(['issue', 'view', str(dep), '--repo', repo, '--json', 'state'])
        if ok and data and data.get('state', '').upper() == 'OPEN':
            open_deps.append(dep)
    if open_deps:
        return 'blocked', ', '.join('#%d' % d for d in open_deps)
    ok, data, _ = gh_json(['pr', 'list', '--repo', repo, '--state', 'merged',
                           '--search', 'closes #%d OR fixes #%d' % (issue['number'], issue['number']),
                           '--json', 'number'])
    if ok and data:
        return 'resolved', data[0]['number']
    return 'valid', None


def mark_blocked(cfg, issue, detail):
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    run(['gh', 'issue', 'edit', str(issue['number']), '--repo', repo,
         '--remove-assignee', '@me',
         '--remove-label', label(cfg, 'status-in-progress'),
         '--add-label', label(cfg, 'status-blocked')])
    run(['gh', 'issue', 'comment', str(issue['number']), '--repo', repo,
         '--body', 'Blocked — open dependency(ies): %s. Returned to blocked until they close.' % detail])


def close_resolved(cfg, issue, pr_number):
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    run(['gh', 'issue', 'close', str(issue['number']), '--repo', repo,
         '--comment', 'Closing — already resolved by #%s.' % pr_number])


# ── board move + branch (--checkout) ─────────────────────────────────────────

def board_move_in_progress(cfg, number):
    """Move the issue to the In Progress column. Returns (moved, message)."""
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

    ok, data, err = gh_graphql(
        'query($id:ID!){ node(id:$id){ ... on ProjectV2 {'
        ' field(name:"Status"){ ... on ProjectV2SingleSelectField { id options { id name } } } } } }',
        id=node)
    if not ok or not data or not data.get('node', {}).get('field'):
        return False, 'could not resolve Status field (%s)' % err
    field = data['node']['field']
    option_id = next((o['id'] for o in field['options']
                      if o['name'].strip().lower() == 'in progress'), None)
    if not option_id:
        return False, "no 'In Progress' column on the board"

    ok, _, err = gh_graphql(
        'mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){ updateProjectV2ItemFieldValue('
        'input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){'
        ' projectV2Item { id } } }',
        p=node, i=item_id, f=field['id'], o=option_id)
    if not ok:
        return False, 'board mutation failed (%s)' % err
    return True, 'moved to In Progress'


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


# ── PR pickers (update-pr / code-review pools) ───────────────────────────────

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


def cmd_pick(args):
    env_err = check_environment()
    if env_err:
        emit('error', EXIT_ENV, reason=env_err)

    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    if not cfg.get('org') or not cfg.get('repo'):
        emit('error', EXIT_ENV, reason='org/repo missing from config')

    # feature / maintenance modes: wf filters them by the type-* LABEL
    # (wf_core._filter_by_mode). On a type-capable org the *native* issue type
    # is authoritative and wf does not resolve it — defer those to the skill's
    # inline native-type path. Plain label-typed projects (the common case) run
    # here, so the fast path covers feature/maintenance too.
    if args.mode != 'story' and cfg.get('type_capable'):
        emit('unsupported', EXIT_UNSUPPORTED,
             reason="mode %r needs native-issue-type resolution on a type-capable "
                    "org; use the skill's inline selection" % args.mode,
             mode=args.mode)

    if cfg.get('ready_gate', 'label') not in ('label', 'none'):
        emit('unsupported', EXIT_UNSUPPORTED,
             reason="ready-gate %r not implemented in wf; use the skill" % cfg['ready_gate'])

    ok, issues, err = assemble_candidates(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)

    backlog_mode, issues = narrow_to_sprint(cfg, issues)
    pool = wf_core.select_pool(issues, mode=args.mode, agent_gating=cfg.get('agent_gating', 'disabled'))
    if not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='no ready, unassigned issues match', backlog_mode=backlog_mode)

    side_effects = []
    selected = None
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
        verdict, detail = validate_issue(cfg, cand)
        if verdict == 'blocked':
            mark_blocked(cfg, cand, detail)
            release_claim(target)
            side_effects.append({'issue': cand['number'], 'action': 'marked-blocked', 'detail': detail})
            continue
        if verdict == 'resolved':
            close_resolved(cfg, cand, detail)
            release_claim(target)
            side_effects.append({'issue': cand['number'], 'action': 'closed-already-resolved', 'pr': detail})
            continue
        selected = cand
        break

    if not selected:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='every candidate was claimed-away, blocked, or already resolved',
             backlog_mode=backlog_mode, side_effects=side_effects)

    result = {
        'number': selected['number'],
        'title': selected['title'],
        'url': selected['url'],
        'labels': selected['labels'],
        'milestone': selected['milestone'],
        'body': selected['body'],
        'claim_ref': 'refs/claims/issue-%d' % selected['number'],
        'mode': args.mode,
        'backlog_mode': backlog_mode,
        'side_effects': side_effects,
        'checked_out': False,
    }

    if args.checkout:
        moved, board_msg = board_move_in_progress(cfg, selected['number'])
        result['board_moved'] = moved
        result['board_message'] = board_msg
        if not moved and board_msg != 'no board configured':
            eprint('wf: board move skipped — %s' % board_msg)
        branch, checked_out, branch_msg = checkout_branch(cfg, selected)
        result['branch'] = branch
        result['checked_out'] = checked_out
        result['branch_message'] = branch_msg
        if not checked_out:
            eprint('wf: %s' % branch_msg)

    emit('ok', EXIT_OK, **result)


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
    # update-pr skill can make its final relabel decision (Step 8).
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
                      help='selection mode; feature/maintenance run here on label-typed '
                           'projects and defer to the skill on type-capable orgs')
    pick.add_argument('--checkout', action='store_true',
                      help='also move the board to In Progress and create/check out the branch')
    pick.set_defaults(func=cmd_pick)

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

    cfg = sub.add_parser('config', help='emit .claude/wf-config.json from ClaudeProject.md')
    cfg.set_defaults(func=cmd_config)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
