"""
Pull request review-state labels: names, selection pools and reconciliation
after a review.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""


# ── PR review-state labels + selection ───────────────────────────────────────
# Mirrors the pr-review skill (Step 1). These are the only labels the
# workflow applies. Names default to the `review-` prefix and are overridden
# by the Labels table in review.config.md; the colours and descriptions are
# what `wf labels-ensure` and the review-finish readback create them with.

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

REVIEW_LABEL_META = {
    'needs-review': ('C2E0C6', 'Open PR awaiting its first review'),
    'reviewing': ('0E8A16', 'Review in progress'),
    'approved': ('1D76DB', 'Review passed'),
    'changes-requested': ('E4E669', 'Problems remain to be addressed'),
    'needs-discussion': ('D93F0B', 'Needs a person to decide'),
    'needs-re-review': ('FBCA04', 'New commits since last review'),
    'failed': ('B60205', 'Review could not complete'),
    'updating': ('0E8A16', 'Builder addressing feedback'),
    'fixes-applied': ('5319E7', 'Claude pushed fix commits (sticky)'),
}


def missing_review_labels(names, live_labels):
    """Review labels the repo lacks, as `(purpose, name, colour, description)`.

    `names` is `review_names(...)`. In `REVIEW_DEFAULT_LABELS` order, so a
    create loop and a finding name them the same way every run.
    """
    live = set(live_labels or ())
    out = []
    for purpose in REVIEW_DEFAULT_LABELS:
        name = names.get(purpose) or REVIEW_DEFAULT_LABELS[purpose]
        if name in live:
            continue
        colour, description = REVIEW_LABEL_META[purpose]
        out.append((purpose, name, colour, description))
    return out


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
    """Order PRs that need *my* review feedback addressed (pr-review rework pool).

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
    """Order PRs that need reviewing (pr-review pool).

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
    pr-review skill needs it for its final relabel decision).
    """
    for purpose in ('changes-requested', 'needs-discussion', 'needs-re-review'):
        if names[purpose] in labels:
            return names[purpose]
    return None


# ── Review-finish label reconciliation ───────────────────────────────────────
# Encodes the pr-review skill's Step 10/10b: on a verdict, strip every stale
# review-state label and leave exactly the one verdict label. The seven state
# labels are mutually exclusive — exactly one belongs on a settled PR.

REVIEW_STATE_KEYS = [
    'needs-review', 'reviewing', 'approved', 'changes-requested',
    'needs-discussion', 'needs-re-review', 'failed',
]
# The verdicts pr-review can record (the three a review can conclude with;
# `failed` is set on the error path, not by review-finish).
REVIEW_VERDICT_KEYS = ('approved', 'changes-requested', 'needs-discussion')


def reconcile_review_labels(current_labels, verdict, names, fixes_applied=False):
    """Compute the (add, remove) label deltas that record a review verdict.

    Given the PR's current labels and a verdict purpose key, returns the
    concrete label names to add and to remove so the PR ends carrying exactly
    one review-state label (the verdict) — the deterministic "label dance" the
    pr-review skill used to spell out in prose.

      - remove: every managed state label currently present except the verdict.
      - add:    the verdict label if not already present, plus `fixes-applied`
                when `fixes_applied` is set and it is not already present
                (the sticky action label, never removed here).

    `names` is the resolved review-name map (`review_names`). Both lists are
    sorted for deterministic output. Raises ValueError on an unknown verdict so
    a caller can never silently apply the wrong label.
    """
    if verdict not in REVIEW_VERDICT_KEYS:
        raise ValueError('unknown review verdict %r (expected one of %s)'
                         % (verdict, ', '.join(REVIEW_VERDICT_KEYS)))
    target = names[verdict]
    current = set(current_labels)
    managed = {names[k] for k in REVIEW_STATE_KEYS}
    remove = sorted((managed & current) - {target})
    add = []
    if target not in current:
        add.append(target)
    if fixes_applied and names['fixes-applied'] not in current:
        add.append(names['fixes-applied'])
    return add, remove


def review_label_missing(labels_after, verdict, names):
    """Return the verdict label if it did not stick after the edit, else None.

    Drives the guarded create-if-missing readback: when the verdict label is
    absent from the post-edit labels, the label likely does not exist on the
    repo and must be created (without `--force`) and re-applied.
    """
    target = names[verdict]
    return None if target in labels_after else target
