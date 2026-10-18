"""
The decisions behind `worktree-reap`: which finished worktrees a run may remove.

The harness makes a worktree for every subagent and leaves it on disk until its
own sweep decides to remove it, and a project that installs dependencies into
each one carries a full `node_modules` per worktree. `worktree-reap` removes the
ones that are finished, from outside them, so it can do what a run cannot do to
the worktree it is sitting in.

A worktree is finished when nothing in it is lost by deleting the folder. A
branch survives the removal (only the folder and git's record of it go), so the
two things that would be lost are uncommitted work and commits on a detached
HEAD that no branch or tag holds. Everything else is a question of whether a run
is still using it, which `age_hours` answers.

Pure: no git, no disk. `wf_worktrees.py` gathers the facts and acts on the
verdict; `scripts/README.md` has the module map.
"""

import fnmatch
import os

# Hours since a worktree's last git activity or scratch write before it counts
# as abandoned. A run that is still building touches its index or its claim
# markers far more often than this.
WORKTREE_MIN_AGE_HOURS = 6

# The folders the harness makes for subagents. A person's own session worktrees
# (named for their task) carry a conversation that can be resumed, so they are
# left alone unless a caller names a wider pattern.
WORKTREE_PATTERNS = ('agent-*',)

TREE_KEEP, TREE_REAP, TREE_NEED = 'keep', 'reap', 'need'

KEPT_OUTSIDE = 'outside the swept folders'
KEPT_CURRENT = 'the worktree this command runs in'
KEPT_LOCKED = 'locked'
KEPT_RECENT = 'used recently'
KEPT_UNREADABLE = 'could not be read'
KEPT_DIRTY = 'uncommitted changes'
KEPT_DETACHED = 'commits no branch holds'


def parse_worktree_list(text):
    """`git worktree list --porcelain` as one dict per worktree, in order.

    Each has `path`, `head` and `branch` (None when detached), plus `detached`,
    `locked` and `prunable` flags. The main working tree is always first.
    """
    trees, tree = [], None
    for line in (text or '').splitlines():
        if not line.strip():
            tree = None
            continue
        key, _, value = line.partition(' ')
        if key == 'worktree':
            tree = {'path': value, 'head': None, 'branch': None,
                    'detached': False, 'locked': False, 'prunable': False}
            trees.append(tree)
        elif tree is None:
            continue
        elif key == 'HEAD':
            tree['head'] = value
        elif key == 'branch':
            tree['branch'] = value
        elif key in ('detached', 'locked', 'prunable'):
            tree[key] = True
    return trees


def norm_path(path):
    """A path in the form two spellings of it compare equal in."""
    return os.path.normcase(os.path.normpath(path))


def worktree_root(main_path):
    """The folder the harness puts worktrees in, under the main checkout."""
    return os.path.join(main_path, '.claude', 'worktrees')


def worktree_in_scope(path, root, patterns=WORKTREE_PATTERNS):
    """Whether `path` is a direct child of `root` whose name matches a pattern."""
    parent, name = os.path.split(norm_path(path))
    return (parent == norm_path(root)
            and any(fnmatch.fnmatch(name, pattern) for pattern in patterns))


def worktree_verdict(tree, min_age_hours=WORKTREE_MIN_AGE_HOURS):
    """What to do with one worktree: (TREE_REAP, None), (TREE_KEEP, reason) or (TREE_NEED, fact).

    `tree` holds the facts known so far: `in_scope`, `current`, `locked` and
    `prunable` from the list, then `age_hours`, `dirty` and (for a detached
    HEAD) `reachable` once they are read. A fact that is absent has not been
    read yet, so the answer is (TREE_NEED, name) and the caller reads that one
    fact and asks again. A fact that is None was read and could not be
    answered, which keeps the worktree. The cheap checks come first, because
    `dirty` costs a `git status` over the whole tree.
    """
    if not tree.get('in_scope'):
        return TREE_KEEP, KEPT_OUTSIDE
    if tree.get('current'):
        return TREE_KEEP, KEPT_CURRENT
    if tree.get('locked'):
        return TREE_KEEP, KEPT_LOCKED
    if tree.get('prunable'):
        return TREE_REAP, None
    if 'age_hours' not in tree:
        return TREE_NEED, 'age_hours'
    age = tree['age_hours']
    if age is None or age < min_age_hours:
        return TREE_KEEP, KEPT_RECENT
    if 'dirty' not in tree:
        return TREE_NEED, 'dirty'
    if tree['dirty'] is None:
        return TREE_KEEP, KEPT_UNREADABLE
    if tree['dirty']:
        return TREE_KEEP, KEPT_DIRTY
    if tree.get('detached'):
        if 'reachable' not in tree:
            return TREE_NEED, 'reachable'
        if tree['reachable'] is None:
            return TREE_KEEP, KEPT_UNREADABLE
        if not tree['reachable']:
            return TREE_KEEP, KEPT_DETACHED
    return TREE_REAP, None


def worktree_kept_summary(reasons):
    """'2 used recently, 1 uncommitted changes' from the list of reasons kept."""
    counts = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ', '.join('%d %s' % (n, reason) for reason, n in ordered)
