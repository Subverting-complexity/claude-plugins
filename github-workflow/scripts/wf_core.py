#!/usr/bin/env python3
"""
Pure decision logic for the `wf` workflow CLI.

This module is the **canonical, executable** encoding of the selection rules
that the workflow templates describe in prose — story selection, label
resolution, backlog-mode detection, dependency parsing, and branch naming.

It is deliberately **pure**: no GitHub API calls, no `git`, no file or network
I/O. Feed plain dicts/strings in, get decisions out. The I/O shell that talks
to `gh`/`git` lives in `wf.py`; the offline test suite
(`tests/test_decision_logic.py`) imports *this* module directly so the rules
stay verifiable without a network.

Reference templates (the prose these functions encode):
  - github-workflow/templates/story-selection.md
  - github-workflow/templates/default-labels.md
  - github-workflow/commands/start-story.md  (branch convention)
"""

import re

# ── Story selection ──────────────────────────────────────────────────────────
# Encodes github-workflow/templates/story-selection.md Steps 2–3 (the local,
# no-API filter + sort) — the claim/validate loop around it lives in wf.py.

_PRIORITY_ORDER = ['priority-critical', 'priority-high', 'priority-medium', 'priority-low']


def _priority_rank(labels):
    """Returns sort key: 0=critical … 3=low, 4=no priority label."""
    for i, p in enumerate(_PRIORITY_ORDER):
        if p in labels:
            return i
    return len(_PRIORITY_ORDER)


def _filter_by_mode(candidates, mode):
    """Apply mode filter.

    story       — no type filter; all issues are eligible.
    feature     — keep type-story issues only.
    maintenance — keep bug / security / debt / architecture issues only.

    This is the `type-*` **label** path. On a type-capable org the native
    issue type is authoritative; that refinement happens in wf.py before this
    is called (it annotates each candidate's `labels` with the resolved
    fallback purpose key), so this function stays the single sort/filter core.
    """
    if mode == 'story':
        return list(candidates)
    feature_labels = {'type-story'}
    maintenance_labels = {'type-bug', 'type-security', 'type-debt', 'type-arch'}
    keep = feature_labels if mode == 'feature' else maintenance_labels
    return [c for c in candidates if any(lbl in keep for lbl in c.get('labels', []))]


def _filter_refinement(candidates):
    """Exclude issues that carry needs-refinement — not yet ready for pickup."""
    return [c for c in candidates if 'needs-refinement' not in c.get('labels', [])]


def _filter_agent_gating(candidates, agent_gating):
    """If gating is enabled, keep only human-approved (claude-ready) issues."""
    if agent_gating != 'enabled':
        return list(candidates)
    return [c for c in candidates if 'claude-ready' in c.get('labels', [])]


def _sort_candidates(candidates):
    """Sort by priority descending (critical first), then ascending issue number."""
    return sorted(candidates, key=lambda c: (_priority_rank(c.get('labels', [])), c['number']))


def select_story(candidates, mode='story', agent_gating='disabled'):
    """Full selection pipeline: filter → sort → top candidate (or None).

    Returns the single best candidate, never a list — the caller claims it.
    The claim-first/validate-lazily loop in wf.py walks the *sorted* pool when
    a claim is lost or a candidate proves blocked, so this returns the ordered
    survivors via `select_pool`; `select_story` is the convenience head.
    """
    pool = select_pool(candidates, mode, agent_gating)
    return pool[0] if pool else None


def select_pool(candidates, mode='story', agent_gating='disabled'):
    """The ordered, filtered candidate list (best first). Empty list if none."""
    pool = _filter_by_mode(candidates, mode)
    pool = _filter_refinement(pool)
    pool = _filter_agent_gating(pool, agent_gating)
    return _sort_candidates(pool)


# ── Label resolution ─────────────────────────────────────────────────────────
# github-workflow/templates/default-labels.md — "The single resolution path".

_DEFAULT_LABELS = {
    'type-story': 'type-story',
    'type-bug': 'type-bug',
    'type-security': 'type-security',
    'type-debt': 'type-debt',
    'type-arch': 'type-arch',
    'priority-critical': 'priority-critical',
    'priority-high': 'priority-high',
    'priority-medium': 'priority-medium',
    'priority-low': 'priority-low',
    'claude-ready': 'claude-ready',
    'claude-authored': 'claude-authored',
    'status-ready': 'status-ready',
    'needs-refinement': 'needs-refinement',
    'status-in-progress': 'status-in-progress',
    'status-parked': 'status-parked',
    'status-blocked': 'status-blocked',
    'status-in-review': 'status-in-review',
    'status-needs-attention': 'status-needs-attention',
}

# Lifecycle labels are mutually exclusive — exactly one is present at a time.
# The claim marker removes whichever of these the issue currently carries.
LIFECYCLE_KEYS = [
    'status-ready', 'needs-refinement', 'status-in-progress',
    'status-parked', 'status-blocked', 'status-in-review', 'status-needs-attention',
]


def resolve_label(purpose_key, project_map, defaults=None):
    """Resolve a purpose key to a concrete label name.

    Resolution order (from default-labels.md — "The single resolution path"):
    1. Project map (ClaudeProject.md label map, already in context at runtime).
    2. Default inventory (the table in default-labels.md).
    3. The key itself as a last resort so callers never get an empty string.
    """
    if defaults is None:
        defaults = _DEFAULT_LABELS
    return project_map.get(purpose_key) or defaults.get(purpose_key) or purpose_key


def current_lifecycle_label(labels, project_map):
    """Return the concrete lifecycle label currently on the issue, or None.

    Used to build the `--remove-label` argument when applying the
    status-in-progress marker, so exactly one lifecycle label remains.
    """
    concrete = {resolve_label(k, project_map): k for k in LIFECYCLE_KEYS}
    for name in labels:
        if name in concrete:
            return name
    return None


# ── PR review-state labels + selection ───────────────────────────────────────
# Mirrors github-workflow/commands/update-pr.md (Step 2) and the code-review
# skill (Step 1). Review-state names default to the `review-` prefix
# (templates/label-reference.md) and are overridden by review.config.md.

REVIEW_DEFAULT_LABELS = {
    'needs-review': 'review-needs-review',
    'reviewing': 'review-reviewing',
    'approved': 'review-approved',
    'changes-requested': 'review-changes-requested',
    'needs-discussion': 'review-needs-discussion',
    'needs-re-review': 'review-needs-re-review',
    'failed': 'review-failed',
    'updating': 'review-updating',
    'fixes-applied': 'review-fixes-applied',
}


def resolve_review_label(purpose_key, review_map=None, defaults=None):
    """Resolve a review-state purpose key to a concrete label name.

    Same three-step path as resolve_label: review.config.md map →
    `review-` prefixed default → the key itself.
    """
    review_map = review_map or {}
    if defaults is None:
        defaults = REVIEW_DEFAULT_LABELS
    return review_map.get(purpose_key) or defaults.get(purpose_key) or purpose_key


def review_names(review_map=None):
    """Resolve every review-state purpose to its concrete name (one dict)."""
    return {k: resolve_review_label(k, review_map) for k in REVIEW_DEFAULT_LABELS}


def select_update_pool(prs, names):
    """Order PRs that need *my* review feedback addressed (update-pr pool).

    Keep PRs carrying an actionable state — changes-requested >
    needs-discussion > needs-re-review (priority order) — and drop any
    carrying reviewing / updating / approved / needs-review / failed (another
    agent owns it, or there is no feedback to apply). Sort by that priority,
    then ascending PR number. `names` maps purpose keys to concrete labels.
    """
    priority = [names['changes-requested'], names['needs-discussion'], names['needs-re-review']]
    skip = {names[k] for k in ('reviewing', 'updating', 'approved', 'needs-review', 'failed')}
    ranked = []
    for pr in prs:
        labels = set(pr.get('labels', []))
        if labels & skip:
            continue
        rank = next((i for i, name in enumerate(priority) if name in labels), None)
        if rank is None:
            continue
        ranked.append((rank, pr['number'], pr))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [pr for _, _, pr in ranked]


def select_review_pool(prs, names):
    """Order PRs that need reviewing (code-review pool).

    Keep PRs carrying needs-re-review or needs-review; drop any carrying
    reviewing / updating (an agent is on it), and drop approved unless it also
    carries needs-re-review (approved + new commits still needs a re-review).
    needs-re-review is reviewed before needs-review; ties break on ascending
    number. (SHA-drift detection — a PR whose head changed since the last
    review without a label — stays in the skill; this is the label-driven
    subset.)
    """
    skip = {names['reviewing'], names['updating']}
    ranked = []
    for pr in prs:
        labels = set(pr.get('labels', []))
        if labels & skip:
            continue
        has_rereview = names['needs-re-review'] in labels
        has_review = names['needs-review'] in labels
        if not (has_rereview or has_review):
            continue
        if names['approved'] in labels and not has_rereview:
            continue
        ranked.append((0 if has_rereview else 1, pr['number'], pr))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [pr for _, _, pr in ranked]


def actionable_update_label(labels, names):
    """The highest-priority actionable state label present on an update PR.

    Returned so the caller can record which feedback state it claimed (the
    update-pr skill needs it for its final relabel decision).
    """
    for purpose in ('changes-requested', 'needs-discussion', 'needs-re-review'):
        if names[purpose] in labels:
            return names[purpose]
    return None


# ── Backlog-mode detection ───────────────────────────────────────────────────
# story-selection.md Step 2 — sprint vs flat from milestone presence.

def detect_backlog_mode(candidates):
    """Return 'sprint' if any candidate has a milestone, otherwise 'flat'."""
    return 'sprint' if any(c.get('milestone') for c in candidates) else 'flat'


def get_sprint_candidates(candidates, sprint_title):
    """Narrow candidates to those belonging to the active sprint."""
    return [c for c in candidates if c.get('milestone') == sprint_title]


# ── Dependency parsing ───────────────────────────────────────────────────────
# story-selection.md Step 3 validation — fixed patterns, no judgment.

_DEP_LINE_PATTERNS = [
    re.compile(r'\bdepends on\s+#(\d+)', re.IGNORECASE),
    re.compile(r'\bblocked by\s+#(\d+)', re.IGNORECASE),
    re.compile(r'\bafter\s+#(\d+)', re.IGNORECASE),
    re.compile(r'\brequires\s+#(\d+)', re.IGNORECASE),
]
_DEP_SECTION_RE = re.compile(
    r'^#{1,6}\s*dependencies\s*$(.*?)(?=^#{1,6}\s|\Z)',
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_HASH_REF_RE = re.compile(r'#(\d+)')
DEP_LIMIT = 5


def parse_dependencies(body):
    """Extract dependency issue numbers from an issue body.

    Recognises the fixed markers `Depends on #N`, `Blocked by #N`, `After #N`,
    `Requires #N`, and bare `#N` references inside a `## Dependencies` section.
    Self-references and duplicates are dropped.

    Returns (deps, overflow):
      deps     — sorted unique list of referenced issue numbers (ints).
      overflow — True if more than DEP_LIMIT distinct deps were found. Per the
                 template, that many references means a meta/epic issue whose
                 dependencies cannot be cheaply validated, so the caller treats
                 it as unresolved rather than checking each one.
    """
    body = body or ''
    found = set()
    for pat in _DEP_LINE_PATTERNS:
        for m in pat.finditer(body):
            found.add(int(m.group(1)))
    section = _DEP_SECTION_RE.search(body)
    if section:
        for m in _HASH_REF_RE.finditer(section.group(1)):
            found.add(int(m.group(1)))
    deps = sorted(found)
    return deps, len(deps) > DEP_LIMIT


# ── Branch naming ────────────────────────────────────────────────────────────
# start-story.md Step 6 — deterministic slug from the issue title.

def branch_slug(title, max_len=40):
    """Slugify an issue title for a branch name.

    lowercase → non-alphanumeric runs become single hyphens → truncate to
    max_len → strip leading/trailing hyphens. Matches the start-story example
    "Fix: User login broken!!!" → "fix-user-login-broken".
    """
    slug = re.sub(r'[^a-z0-9]+', '-', (title or '').lower())
    slug = slug.strip('-')[:max_len].strip('-')
    return slug


def branch_name(convention, number, title):
    """Render the branch convention with the issue number and a title slug.

    `convention` is the pattern from ClaudeProject.md, e.g.
    "feature/{number}/{short-desc}". Unknown placeholders are left untouched.
    """
    return (convention
            .replace('{number}', str(number))
            .replace('{short-desc}', branch_slug(title)))
