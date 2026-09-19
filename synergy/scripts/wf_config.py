"""
Environment and configuration: the repo root, ClaudeProject.md parsing, the
config cache, and the `config` subcommand.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import json
import os
import re
import time

import wf_core
from wf_io import EXIT_ENV, EXIT_OK, emit, eprint, run


# ── environment + config ─────────────────────────────────────────────────────

# The toplevel each working directory resolved to in this process (#300).
_REPO_ROOTS = {}


def repo_root():
    """The repository's toplevel, asked of git once per working directory.

    One command used to ask five times, and each ask is a process launch. It
    is keyed on the working directory so a caller (or a test) that changes
    directory gets the root of where it now is. Only an answer naming a real
    directory is remembered: a failed or faked `git` falls back to the
    working directory for this call and is asked again on the next.
    """
    cwd = os.getcwd()
    known = _REPO_ROOTS.get(cwd)
    if known:
        return known
    code, out, _ = run(['git', 'rev-parse', '--show-toplevel'])
    root = (out or '').strip()
    if code == 0 and root:
        if os.path.isdir(root):
            _REPO_ROOTS[cwd] = root
        return root
    return cwd


def check_environment():
    """Return an error string if the environment can't support a claim, else None."""
    code, _, _ = run(['git', 'rev-parse', '--is-inside-work-tree'])
    if code != 0:
        return 'not inside a git work tree'
    # `gh auth token` answers "is gh signed in" from the local credential store
    # in about 100 ms; `gh auth status` asks GitHub and cost about 750 ms on every
    # wf command. A token GitHub no longer accepts fails on the first real call.
    # gh older than 2.17 has no `auth token`, so a failure is confirmed the slow way.
    code, _, err = run(['gh', 'auth', 'token'])
    if code != 0:
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
        'board': {'project_node_id': None, 'project_title': None},
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
    path = review_config_path(root)
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


def review_config_path(root):
    return os.path.join(root, 'docs', 'review.config.md')


def config_paths(root):
    return (os.path.join(root, '.claude', 'wf-config.json'),
            os.path.join(root, 'ClaudeProject.md'))


def load_config():
    """Load config: JSON cache if fresh, else parse ClaudeProject.md. (ok, cfg, err).

    The cache holds the review-label names too, so it is stale when either
    `ClaudeProject.md` or `docs/review.config.md` is newer than it (#289).
    Setup writes the review config late, after the cache may already exist.
    """
    root = repo_root()
    cache, source = config_paths(root)
    if os.path.isfile(cache):
        built = os.path.getmtime(cache)
        fresh = all(not os.path.isfile(p) or built >= os.path.getmtime(p)
                    for p in (source, review_config_path(root)))
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

def git_common_dir(root):
    """The clone's shared git directory, read from `.git` without running git.

    In a linked worktree `.git` is a file naming the worktree's own git
    directory, and that directory's `commondir` names the shared one, which is
    where `info/exclude` lives for every worktree of the clone. None when
    neither can be read.
    """
    dot_git = os.path.join(root, '.git')
    if os.path.isdir(dot_git):
        return dot_git
    try:
        with open(dot_git, encoding='utf-8') as fh:
            line = fh.readline().strip()
    except OSError:
        return None
    if not line.startswith('gitdir:'):
        return None
    gitdir = line[len('gitdir:'):].strip()
    if not os.path.isabs(gitdir):
        gitdir = os.path.join(root, gitdir)
    try:
        with open(os.path.join(gitdir, 'commondir'), encoding='utf-8') as fh:
            common = fh.readline().strip()
    except OSError:
        return gitdir
    return os.path.normpath(common if os.path.isabs(common)
                            else os.path.join(gitdir, common))


def ensure_scratch_ignored(root):
    """Keep the scratch-file block current in the clone's `info/exclude`.

    Best-effort and silent on success: a file that cannot be written is
    reported on stderr and the command carries on. Returns True when the
    block is in place.
    """
    common = git_common_dir(root)
    if not common:
        return False
    path = os.path.join(common, 'info', 'exclude')
    try:
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    except OSError:
        text = ''
    merged = wf_core.merge_exclude(text)
    if merged is None:
        return True
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(merged)
    except OSError as exc:
        eprint('wf: could not add the scratch files to %s (%s)' % (path, exc))
        return False
    return True


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
    ensure_scratch_ignored(repo_root())
    return cfg


def cmd_scratch_clean(args):
    """`wf scratch-clean`: delete the run's scratch files under `.claude/`.

    Needs neither gh nor a network, so it runs on every exit path, including
    one caused by a broken environment.
    """
    root = repo_root()
    ignored = ensure_scratch_ignored(root)
    folder = os.path.join(root, '.claude')
    removed, failed = [], []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(folder, name)
        if not wf_core.is_run_scratch(name) or not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            removed.append('.claude/' + name)
        except OSError as exc:
            failed.append({'file': '.claude/' + name, 'reason': str(exc)})
    emit('ok', EXIT_OK, removed=removed, failed=failed, excluded=ignored)


def _preflight_cached(root):
    """Whether a clean or warning-only `wf preflight` still stands here."""
    source = config_paths(root)[1]
    marker = os.path.join(root, '.claude', 'preflight-passed.txt')
    marker_mtime = os.path.getmtime(marker) if os.path.isfile(marker) else None
    source_mtime = os.path.getmtime(source) if os.path.isfile(source) else None
    return wf_core.preflight_marker_fresh(marker_mtime, source_mtime, time.time())


def cmd_preflight_cached(args):
    """`wf preflight-cached`: read-only. Whether a clean or warning-only
    `wf preflight` already stands within the last four hours, for a caller
    (`block-story`, `report-issue`) that only needs that one bit and must not
    touch the invocation-flag files `run-init` resets -- filing an issue is
    not the start of a build.
    """
    emit('ok', EXIT_OK, cached=_preflight_cached(repo_root()))


def cmd_run_init(args):
    """`wf run-init`: the start-of-run housekeeping `execute` and
    `bulk-execute` used to do as a hand-written shell block -- reset and set
    the invocation-flag files, sweep the claim markers a hard-killed run left
    behind, and report whether preflight is still cached and what the GitHub
    API quota looks like. One command, one verdict, run exactly once per run
    for the same reason the flag-file block was: a compaction re-running it
    would drop a flag the arguments are no longer in context to restate.
    """
    root = repo_root()
    claude_dir = os.path.join(root, '.claude')
    os.makedirs(claude_dir, exist_ok=True)

    for name in ('no-merge.flag', 'bypass-ci.flag', 'unattended.flag',
                'gate-failed.flag', 'self-review.flag'):
        try:
            os.remove(os.path.join(claude_dir, name))
        except OSError:
            pass
    if args.bulk:
        try:
            os.remove(os.path.join(claude_dir, 'bulk-set.json'))
        except OSError:
            pass

    # Stray claim-marker scratch a hard-killed run left behind. `--others`
    # (untracked only) spares a marker a project committed on purpose.
    _, out, _ = run(['git', 'ls-files', '-z', '--others', '--',
                    '.claude/claim-issue-*.sha'])
    for rel in (out or '').split('\0'):
        if rel:
            try:
                os.remove(os.path.join(root, rel))
            except OSError:
                pass

    flags = {'no_merge': bool(args.no_merge), 'bypass_ci': bool(args.bypass_ci),
             'unattended': bool(args.unattended)}
    for key, flag_file in (('no_merge', 'no-merge.flag'),
                           ('bypass_ci', 'bypass-ci.flag'),
                           ('unattended', 'unattended.flag')):
        if flags[key]:
            open(os.path.join(claude_dir, flag_file), 'a').close()

    preflight_cached = _preflight_cached(root)

    remaining = None
    code, out, _err = run(['gh', 'api', 'rate_limit', '--jq', '.rate.remaining'])
    if code == 0:
        try:
            remaining = int((out or '').strip())
        except ValueError:
            remaining = None

    emit('ok', EXIT_OK, flags=flags, preflight_cached=preflight_cached,
         quota={'remaining': remaining,
                'low': wf_core.quota_low(remaining)})


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
