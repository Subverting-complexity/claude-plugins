"""
`worktree-reap`: remove the finished worktrees a run leaves behind.

Every subagent gets its own worktree, and the harness removes one on its own
schedule, not when the run ends. In a project that installs dependencies per
worktree each one is gigabytes, so they add up between sweeps. This removes
the finished ones from outside them: a run cannot delete the worktree it is
standing in, but the next run can delete the last one's.

`exit-cleanup` calls it at the end of every run, and it is a command in its own
right. The rules for what counts as finished are `wf_core_worktrees.py`;
`scripts/README.md` has the module map.
"""

import os
import shutil
import stat
import time

import wf_core
from wf_config import repo_root
from wf_io import EXIT_ENV, EXIT_OK, EXIT_PARTIAL, emit, emit_line, run

# How far below a worktree's top to look for a symlink or junction. The
# harness links `node_modules` at the root and a monorepo has `pkg/node_modules`.
LINK_SCAN_DEPTH = 2

_REPARSE_POINT = 0x400


# ── reading the facts ────────────────────────────────────────────────────────

def list_worktrees():
    """Every worktree of this clone, or None when git cannot say."""
    code, out, _ = run(['git', 'worktree', 'list', '--porcelain'])
    if code != 0:
        return None
    return wf_core.parse_worktree_list(out)


def _git_dir(path):
    """The directory holding a linked worktree's own HEAD and index."""
    try:
        with open(os.path.join(path, '.git'), encoding='utf-8') as fh:
            line = fh.readline().strip()
    except OSError:
        return None
    if not line.startswith('gitdir:'):
        return None
    target = line[len('gitdir:'):].strip()
    return target if os.path.isabs(target) else os.path.normpath(os.path.join(path, target))


def age_hours(path, now):
    """Hours since the worktree's last git activity or scratch write, or None.

    A run that is still building rewrites its index, its HEAD log or its claim
    markers; a finished or crashed one stops. `None` means nothing could be
    read, which keeps the worktree.
    """
    candidates = []
    gitdir = _git_dir(path)
    if gitdir:
        candidates += [os.path.join(gitdir, name)
                       for name in ('HEAD', 'index', os.path.join('logs', 'HEAD'))]
    folder = os.path.join(path, '.claude')
    try:
        names = os.listdir(folder)
    except OSError:
        names = []
    candidates += [os.path.join(folder, name) for name in names
                   if wf_core.is_run_scratch(name)]
    stamps = []
    for candidate in candidates:
        try:
            stamps.append(os.path.getmtime(candidate))
        except OSError:
            continue
    return (now - max(stamps)) / 3600.0 if stamps else None


def is_dirty(path):
    """Whether the worktree has uncommitted changes, or None when git cannot say.

    Untracked files that are not gitignored count, because deleting the folder
    would lose them. Ignored files (`node_modules`, build output) do not.
    """
    code, out, _ = run(['git', '-C', path, 'status', '--porcelain'])
    return None if code != 0 else bool((out or '').strip())


def is_reachable(sha):
    """Whether a branch, remote branch or tag holds `sha`, or None when git cannot say."""
    code, out, _ = run(['git', 'for-each-ref', '--contains', sha, '--count=1',
                        '--format=%(refname)', 'refs/heads', 'refs/remotes', 'refs/tags'])
    return None if code != 0 else bool((out or '').strip())


def _read_fact(tree, fact, now):
    if fact == 'age_hours':
        return age_hours(tree['path'], now)
    if fact == 'dirty':
        return is_dirty(tree['path'])
    return is_reachable(tree['head']) if tree.get('head') else None


def judge(tree, min_age_hours, now):
    """The verdict for one worktree, reading each fact only when it is needed."""
    while True:
        verdict, detail = wf_core.worktree_verdict(tree, min_age_hours)
        if verdict != wf_core.TREE_NEED:
            return verdict, detail
        tree[detail] = _read_fact(tree, detail, now)


# ── removing one ─────────────────────────────────────────────────────────────

def is_link(path):
    """Whether `path` is a symlink or a Windows junction."""
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, 'isjunction', None)
    if is_junction and is_junction(path):
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attributes & _REPARSE_POINT)


def _unlink(path):
    """Remove the link itself. A junction needs `rmdir`, a symlink `unlink`."""
    try:
        os.unlink(path)
    except OSError:
        os.rmdir(path)


def remove_links(root, depth=1):
    """Remove every symlink or junction near the top of a worktree, and return them.

    Done before the folder is deleted, because a recursive delete that follows
    a link deletes what it points at, which here is the shared `node_modules`
    of the main checkout. Nothing is descended into through a link, and a real
    `node_modules` is not searched. Raises OSError when a link cannot be
    removed, so the caller leaves that worktree alone.
    """
    removed = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return removed
    for entry in entries:
        if entry.name == '.git':
            continue
        if is_link(entry.path):
            _unlink(entry.path)
            removed.append(entry.path)
        elif (depth < LINK_SCAN_DEPTH and entry.name != 'node_modules'
              and entry.is_dir(follow_symlinks=False)):
            removed += remove_links(entry.path, depth + 1)
    return removed


def _clear_readonly(function, path, _excinfo):
    """`rmtree` error handler: git marks pack files read-only, which Windows will not delete."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _long_path(path):
    """The extended-length form on Windows, where `node_modules` overflows MAX_PATH."""
    path = os.path.abspath(path)
    return '\\\\?\\' + path if os.name == 'nt' and not path.startswith('\\\\?\\') else path


def remove_worktree(path, root):
    """Remove one worktree. Returns (ok, reason).

    Links go first (see `remove_links`). `git worktree remove` does the work and
    clears git's record; when it cannot, because a file is too deep or
    read-only, the folder is deleted directly, but only when it really sits
    inside `root`, and the stale record is pruned afterwards.
    """
    if not os.path.isdir(path):
        return True, 'folder already gone'
    try:
        remove_links(path)
    except OSError as exc:
        return False, 'could not remove a link inside it (%s)' % exc
    code, _, err = run(['git', 'worktree', 'remove', '--force', path])
    if code == 0 and not os.path.exists(path):
        return True, None
    if wf_core.norm_path(os.path.dirname(os.path.realpath(path))) != wf_core.norm_path(os.path.realpath(root)):
        return False, 'git would not remove it (%s)' % (err or '').strip()
    try:
        shutil.rmtree(_long_path(path), onerror=_clear_readonly)
    except OSError as exc:
        return False, 'could not delete the folder (%s)' % exc
    run(['git', 'worktree', 'prune'])
    return True, None


# ── the sweep ────────────────────────────────────────────────────────────────

def sweep(patterns=wf_core.WORKTREE_PATTERNS, min_age_hours=wf_core.WORKTREE_MIN_AGE_HOURS,
          dry_run=False, now=None):
    """Remove (or with `dry_run`, list) the finished worktrees.

    Returns a dict: `removed` and `failed` ([{'path', 'reason'}]), `kept`
    (the in-scope worktrees left alone, each with its reason) and `outside`
    (how many other worktrees were not considered). None when git cannot list
    the worktrees.
    """
    trees = list_worktrees()
    if trees is None:
        return None
    now = time.time() if now is None else now
    root = wf_core.worktree_root(trees[0]['path']) if trees else ''
    here = wf_core.norm_path(repo_root())
    result = {'removed': [], 'failed': [], 'kept': [], 'outside': 0}
    for tree in trees[1:]:
        tree['in_scope'] = wf_core.worktree_in_scope(tree['path'], root, patterns)
        tree['current'] = wf_core.norm_path(tree['path']) == here
        verdict, reason = judge(tree, min_age_hours, now)
        if reason == wf_core.KEPT_OUTSIDE:
            result['outside'] += 1
        elif verdict == wf_core.TREE_KEEP:
            result['kept'].append({'path': tree['path'], 'reason': reason})
        elif dry_run:
            result['removed'].append({'path': tree['path'], 'reason': 'would remove'})
        else:
            ok, why = remove_worktree(tree['path'], root)
            result['removed' if ok else 'failed'].append(
                {'path': tree['path'], 'reason': why or 'removed'})
    if not dry_run and result['removed']:
        run(['git', 'worktree', 'prune'])
    return result


def reap_finished():
    """The number of worktrees removed, for a caller that must not fail on this.

    `exit-cleanup` ends every run, so a sweep that cannot read git or cannot
    delete a folder is not a reason to report that run as unfinished.
    """
    try:
        result = sweep()
    except Exception:  # noqa: BLE001 - a clean-up that must never fail its caller
        return 0
    return len(result['removed']) if result else 0


# ── the command ──────────────────────────────────────────────────────────────

def cmd_worktree_reap(args):
    """`wf worktree-reap`: remove the finished `agent-*` worktrees of this clone.

    A worktree is kept when it is the one this runs in, is locked, was used
    within `--min-age-hours`, has uncommitted changes, or holds commits on a
    detached HEAD that no branch or tag has. Removing a worktree leaves its
    branch where it was.
    """
    result = sweep(patterns=tuple(args.pattern) if args.pattern else wf_core.WORKTREE_PATTERNS,
                   min_age_hours=args.min_age_hours, dry_run=args.dry_run)
    if result is None:
        emit('error', EXIT_ENV, reason='git worktree list failed; is this a git checkout?')
    kept = wf_core.worktree_kept_summary(k['reason'] for k in result['kept'])
    tail = '; kept %d (%s)' % (len(result['kept']), kept) if result['kept'] else ''
    if args.dry_run:
        emit('ok', EXIT_OK, dry_run=True, would_remove=result['removed'],
             kept=result['kept'], outside=result['outside'],
             reason='would remove %d worktree(s)%s' % (len(result['removed']), tail))
    if result['failed']:
        emit('partial', EXIT_PARTIAL, removed=len(result['removed']),
             failed=result['failed'], kept=result['kept'],
             reason='removed %d, could not remove %d%s'
                    % (len(result['removed']), len(result['failed']), tail))
    emit_line('ok', EXIT_OK, removed=len(result['removed']),
              reason='removed %d finished worktree(s)%s' % (len(result['removed']), tail))
