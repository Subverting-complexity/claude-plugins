"""
The scratch files a workflow run writes under `.claude/`: which ones git must
ignore, which ones a run deletes when it ends, and the block `wf` keeps in the
clone's `info/exclude` so no project has to list them.

A stray untracked scratch file keeps a worktree dirty, and a dirty worktree is
never reaped. The list used to be copied by hand into `.gitignore` by setup,
and each file added later (the bulk set, issue specs and bodies) was missing
from every project that ran setup before it. It lives here once.

Pure: `scripts/README.md` has the module map.
"""

import fnmatch

# Everything a run may leave under `.claude/`, as git ignore patterns.
# `projected-config.md`, `wf-config.json` and `issue-fields-cache.json` are
# caches that survive a run; the rest belong to one run.
SCRATCH_IGNORE = (
    '.claude/plan.md',
    '.claude/projected-config.md',
    '.claude/preflight-passed.txt',
    '.claude/label-cache.json',
    '.claude/issue-fields-cache.json',
    '.claude/candidates.json',
    '.claude/claim-*.sha',
    '.claude/wf-config.json',
    '.claude/bulk-set.json',
    '.claude/release-notes.json',
    '.claude/*.flag',
    '.claude/*-spec.json',
    '.claude/*-body.md',
)

# What `wf scratch-clean` deletes when a run ends: every per-run file, never a
# cache a later run reads to save a request. The capability cache stamps its
# own age and re-queries after an hour, and the preflight marker is trusted for
# four hours unless ClaudeProject.md changes, so deleting either only cost the
# next run a request, and the preflight marker the whole preflight skill.
SCRATCH_RUN = (
    'plan.md', 'label-cache.json', 'candidates.json',
    'claim-*.sha', 'bulk-set.json', 'release-notes.json', '*.flag',
    '*-spec.json', '*-body.md',
)

EXCLUDE_BEGIN = '# synergy scratch files (managed by wf; do not edit)'
EXCLUDE_END = '# end synergy scratch files'


def exclude_block():
    return '\n'.join((EXCLUDE_BEGIN,) + SCRATCH_IGNORE + (EXCLUDE_END,)) + '\n'


def merge_exclude(text):
    """`info/exclude` with the managed block current, or None when it already is.

    The block is replaced in place, so a list that grows reaches a clone that
    has the old one, and every line outside the block is kept as it was.
    """
    text = text or ''
    block = exclude_block()
    begin = text.find(EXCLUDE_BEGIN)
    if begin != -1:
        end = text.find(EXCLUDE_END, begin)
        if end != -1:
            stop = end + len(EXCLUDE_END)
            if text[stop:stop + 1] == '\n':
                stop += 1
            if text[begin:stop] == block:
                return None
            return text[:begin] + block + text[stop:]
    if text and not text.endswith('\n'):
        text += '\n'
    return text + block


def is_run_scratch(name):
    """Whether a file name directly under `.claude/` is a per-run scratch file."""
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in SCRATCH_RUN)
