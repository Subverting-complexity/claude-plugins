"""
Environment and configuration: the repo root, ClaudeProject.md parsing, the
config cache, and the `config` subcommand.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import json
import os
import re

import wf_core
from wf_io import EXIT_ENV, EXIT_OK, emit, eprint, run


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
                  'start_date_field_id': None},
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
    # there is one pool now, the open issues whose `Stage` is blank or
    # `Backlog`, and approval is being in it. `config-audit` reports a
    # surviving section so it gets deleted rather than believed.

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
            elif key == 'start-date-field-id':
                cfg['board']['start_date_field_id'] = None if val in ('n/a', '') else val
    # No `status-field-*` row and no `### Status Options` table is read any
    # more. An issue's state is the org's `Stage` field since 12.0.0, so a
    # board's own Status field is a view setting nothing here writes.
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
