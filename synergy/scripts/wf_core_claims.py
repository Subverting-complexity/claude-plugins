"""
Claims: sibling pull requests that would duplicate a claim, and which orphaned
claim ref is safe to reap.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

from wf_core_refs import closing_issue_numbers


# ── duplicate detection: the PRs that will close an issue ────────────────────
# One definition of "duplicate", used by every site that detects or reconciles
# one. It reads GitHub's own parse of closing references — the same parse that
# auto-closes the issue on merge — rather than matching PR bodies, because a
# regex misses closing keywords, cross-repo refs and UI-linked issues, and two
# call sites with two regexes would disagree about what a duplicate is.

def select_sibling_prs(nodes, number, exclude_branch=None):
    """The open PRs that close issue `number`, oldest first.

    `exclude_branch` drops the caller's own PR, which is otherwise reported as
    a duplicate of itself the moment it is created.
    """
    out = []
    for node in nodes or ():
        refs = closing_issue_numbers(node.get('closingIssuesReferences'))
        if number not in refs:
            continue
        if exclude_branch and node.get('headRefName') == exclude_branch:
            continue
        out.append({
            'number': node['number'],
            'title': node.get('title', ''),
            'url': node.get('url', ''),
            'head_ref': node.get('headRefName', ''),
            'draft': bool(node.get('isDraft')),
            'labels': [l['name'] for l in
                       (node.get('labels') or {}).get('nodes', [])],
        })
    return out


# ── claim reaping: which orphaned claim ref is safe to free ──────────────
# Every in-flight issue and PR is locked with a git ref under `refs/claims/`.
# A normal exit releases it; a crash does not, and the orphan then blocks
# pickup of that item forever with no error anywhere. Reaping is therefore
# necessary — and dangerous, because freeing a ref that still backs a running
# session lets two agents build the same story. So the rule is asymmetric:
# reap only on positive evidence the work has moved on, and when the evidence
# is merely absent, report the ref as suspect and leave it alone.

REAP_THRESHOLD_HOURS = 4

REAP, SUSPECT, SKIP = 'reap', 'suspect', 'skip'


def reap_verdict(kind, age_hours, state, labels, threshold=REAP_THRESHOLD_HOURS,
                 review_labels=(), has_open_pr=False, assigned=True):
    """Decide what to do with one claim ref. Returns (verdict, reason).

    `kind` is 'issue' or 'pr'; `state` is GitHub's own state string (OPEN /
    CLOSED / MERGED) or None when it could not be read.

    An issue claim is reaped when the issue is closed, when nobody is assigned
    to it, or when a PR is already open for it (the post-create release did not
    run). It is suspect when the issue is open, assigned and has no PR: that is
    exactly what a slow but healthy session looks like.

    The assignment is the test because the assignment is what `pick` writes.
    Until 10.0.0 this read a `status-in-progress` label instead, which stopped
    being applied when the state moved to the board -- so every claim looked
    abandoned the moment the label went away, and a healthy in-flight session
    would have had its claim reaped out from under it.

    A PR claim is reaped when the PR is closed or merged, or when it is open
    but carries no active review-state label. A pull request has no board card,
    so its review-state label is the only record of where it is, and that is
    why this half still reads labels.
    """
    if age_hours is None:
        return SUSPECT, 'the age of the claim ref could not be read'
    if age_hours < threshold:
        return SKIP, 'only %dh old (threshold %dh)' % (age_hours, threshold)
    if state is None:
        return SUSPECT, 'could not read the %s' % kind

    names = set(labels or ())
    if kind == 'issue':
        if state.upper() == 'CLOSED':
            return REAP, 'the issue is closed'
        if not assigned:
            return REAP, 'nobody is assigned to the issue'
        if has_open_pr:
            return REAP, 'a PR is already open for the issue'
        return SUSPECT, 'the issue is still assigned with no PR open'

    if state.upper() in ('CLOSED', 'MERGED'):
        return REAP, 'the PR is %s' % state.lower()
    if names & set(review_labels or ()):
        return SUSPECT, 'a review is in progress'
    return REAP, 'the PR is open with no review under way'


def reap_summary(results):
    """Count a reap run by verdict. `results` are (target, verdict, reason)."""
    counts = {REAP: 0, SUSPECT: 0, SKIP: 0}
    for _, verdict, _ in results:
        counts[verdict] = counts.get(verdict, 0) + 1
    return {'reaped': counts[REAP], 'suspect': counts[SUSPECT],
            'skipped': counts[SKIP]}
