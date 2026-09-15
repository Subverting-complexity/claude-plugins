"""
The finding record every preflight and audit check returns, and the small
helpers findings are worded with.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

import re


# ── preflight: configuration and label drift ─────────────────────────────────
# Everything a project can get wrong between `ClaudeProject.md`, the labels the
# repo actually carries, and the org's own field pinning. It is all pure: this
# section decides what is wrong and what the fix is, and never looks anything up.
#
# The severity split is deliberate, and comes from one question — does the
# workflow produce a *wrong* result or a *degraded* one? A missing section, or a
# label an agent is told to apply that does not exist, produce wrong behaviour,
# so they fail. An org field nobody mapped degrades gracefully, so it warns.

CRITICAL, WARNING = 'critical', 'warning'


def finding(level, check, detail, fix, where=None):
    """One preflight result. `where` is the file a person would open to fix it."""
    out = {'level': level, 'check': check, 'detail': detail, 'fix': fix}
    if where:
        out['where'] = where
    return out


def _names(values):
    """`a`, `b` and `c` — because a finding is read by a person, not parsed."""
    names = ['`%s`' % v for v in values]
    if len(names) < 2:
        return names[0] if names else ''
    return '%s and %s' % (', '.join(names[:-1]), names[-1])


def _normalise_heading(text):
    return re.sub(r'\s*\(.*\)\s*$', '', (text or '').strip()).strip().lower()


def _drift_key(name):
    """A label name with every separator flattened, for near-miss grouping."""
    return re.sub(r'[\s:_/]+', '-', (name or '').strip().lower())
