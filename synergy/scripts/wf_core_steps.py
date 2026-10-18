"""
The decisions behind the single-call workflow steps: `exit-cleanup`,
`tree-clean`, `start`, `pr-create`, `block`, the `current` milestone, the
compact `pick` result and the review picker's head-change tier.

Each used to be a sequence of `gh` and `git` calls the model ran and then
branched over by hand. The branching is here, pure, so the offline suite
checks it; `scripts/README.md` has the module map.
"""

import re


# ── exit cleanup: an unfinished review claim ────────────────────────────────

def exit_pr_action(state, labels, names):
    """What exit cleanup does to a PR whose review claim this run won.

    Returns 'reconcile' when the PR must be recorded as changes-requested
    before its lock goes, and 'keep' when its labels already say where it
    stands. Phase 8's claim applied `reviewing` and releasing frees only the
    lock, so an exit before a verdict would leave a PR the picker skips.

      - merged or closed                       → keep
      - open with a verdict label              → keep (a review finished)
      - open with `needs-review`, no `reviewing` → keep (no review started)
      - open with `reviewing`, or with no state label at all → reconcile
    """
    if (state or '').upper() != 'OPEN':
        return 'keep'
    labels = set(labels or ())
    if names['reviewing'] in labels:
        return 'reconcile'
    verdicts = {names[k] for k in ('approved', 'changes-requested',
                                   'needs-discussion', 'needs-re-review',
                                   'failed')}
    if labels & verdicts or names['needs-review'] in labels:
        return 'keep'
    return 'reconcile'


# ── the working tree ─────────────────────────────────────────────────────────

def parse_porcelain(text):
    """`git status --porcelain -z` as [{'code': 'XY', 'path': path}], in order.

    `-z` output is used because it neither quotes nor escapes a path, so a
    non-ASCII name matches the file on disk. A rename or copy reports both
    paths: the new one still in the tree and the old one it removed, so one
    discard restores both. Newline-separated output is accepted as well.
    """
    entries = []
    if '\0' in (text or ''):
        tokens = text.split('\0')
        i = 0
        while i < len(tokens):
            token = tokens[i]
            i += 1
            if len(token) < 4:
                continue
            code = token[:2]
            entry = {'code': code, 'path': token[3:]}
            entries.append(entry)
            if code[0] in 'RC' and i < len(tokens) and tokens[i]:
                entry['orig'] = tokens[i]
                entries.append({'code': code, 'path': tokens[i]})
                i += 1
        return entries
    for line in (text or '').splitlines():
        if len(line) < 4:
            continue
        paths = [p.strip('"') for p in line[3:].split(' -> ', 1)]
        entry = {'code': line[:2], 'path': paths[-1]}
        entries.append(entry)
        if len(paths) == 2:
            entry['orig'] = paths[0]
            entries.append({'code': line[:2], 'path': paths[0]})
    return entries


def untracked(entries):
    return [e['path'] for e in entries if e['code'] == '??']


def tracked(entries):
    return [e['path'] for e in entries if e['code'] != '??']


# ── pr-create: the body checks ───────────────────────────────────────────────

_WORD = re.compile(r'[A-Za-z0-9]')
_CLOSES = re.compile(r'^\s*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\s*$',
                     re.IGNORECASE | re.MULTILINE)


def closes_numbers(body):
    """The issue numbers a body closes on lines of their own."""
    return sorted({int(n) for n in _CLOSES.findall(body or '')})


def body_problems(body, issues=()):
    """Why a stored PR or issue body is corrupt, or [] when it is not.

    The escaping and stdin bugs that corrupt a body leave it empty, a few
    characters long, or a lone punctuation mark. A PR body must also close
    every issue it was opened for, each on a line of its own.
    """
    text = (body or '').strip()
    problems = []
    if not text:
        problems.append('the body is empty')
    elif len(text) < 10:
        problems.append('the body is %d characters long' % len(text))
    elif not _WORD.search(text):
        problems.append('the body has no words, only punctuation')
    missing = sorted(set(int(n) for n in issues) - set(closes_numbers(text)))
    if missing:
        problems.append('no Closes line for %s'
                        % ', '.join('#%d' % n for n in missing))
    return problems


def with_closes_lines(body, issues):
    """The body with a `Closes #N` line added at the end for each missing one."""
    missing = sorted(set(int(n) for n in issues) - set(closes_numbers(body)))
    if not missing:
        return body
    text = (body or '').rstrip('\n')
    return text + '\n\n' + '\n'.join('Closes #%d' % n for n in missing) + '\n'


def duplicate_flag_lines(by_issue):
    """The warning lines a PR body opens with when another open PR closes the
    same issue. `by_issue` is [{'issue': N, 'prs': [...]}]."""
    lines = []
    for entry in by_issue or ():
        for pr in entry.get('prs') or ():
            lines.append('> ⚠ Possible duplicate of #%d — both close #%d. Pending '
                         'reconciliation by code review, which keeps the '
                         'better-implemented PR and closes the other.'
                         % (pr['number'], entry['issue']))
    return lines


# ── report-issue: the current milestone ─────────────────────────────────────

CURRENT_MILESTONE = 'current'


def current_milestone(milestones):
    """The sprint an issue filed now belongs in: (title or None, note).

    The open milestone with the earliest due date that still has open issues.
    A milestone with no due date cannot be ordered, so it is left out; when
    every open milestone lacks one, the note says so rather than filing
    outside the sprint in silence.
    """
    open_ones = [m for m in milestones or () if (m.get('state') or 'open').lower() == 'open']
    if not open_ones:
        return None, 'no open milestone, so the issue is filed without one'
    dated = [m for m in open_ones if m.get('due_on')]
    if not dated:
        return None, ('open milestones found, but none has a due date, so the '
                      'issue is filed without one')
    active = [m for m in dated if (m.get('open_issues') or 0) > 0]
    if not active:
        return None, ('no dated open milestone has open issues, so the issue is '
                      'filed without one')
    active.sort(key=lambda m: (m['due_on'], m.get('title') or ''))
    return active[0]['title'], None


# ── pick: the compact result ─────────────────────────────────────────────────

# Messages that only matter when the step they describe did not happen.
_QUIET_ON_SUCCESS = (('stage_set', 'stage_message'),
                     ('checked_out', 'branch_message'))


def compact_pick(result, include_body=False):
    """The `pick` result with what a caller never reads on success left out.

    The body goes unless asked for, and so does every empty list, every null,
    the claim ref (always `refs/claims/issue-{number}`) and the message for a
    step that succeeded. A step that failed keeps its message.
    """
    out = dict(result)
    if not include_body:
        out.pop('body', None)
    out.pop('claim_ref', None)
    for flag, message in _QUIET_ON_SUCCESS:
        if out.get(flag) is True:
            out.pop(message, None)
    return {k: v for k, v in out.items()
            if v is not None and v != [] and v != {}}


# ── pick --issue: a pull request closed without merging ─────────────────────

def abandoned_pr(prs, number):
    """The closed, unmerged PR that closed issue `number`, or None.

    A merged one means the work is done, never abandoned, so any merged PR
    closing the issue answers None.
    """
    closing = [p for p in prs or ()
               if number in _closing(p.get('closingIssuesReferences'))]
    if any(p.get('mergedAt') for p in closing):
        return None
    unmerged = [p for p in closing if not p.get('mergedAt')]
    if not unmerged:
        return None
    unmerged.sort(key=lambda p: p['number'])
    return unmerged[-1]


def _closing(refs):
    if isinstance(refs, dict):
        refs = refs.get('nodes')
    return [r.get('number') for r in refs or () if isinstance(r, dict)]


# ── review-next: new commits since the last review ──────────────────────────

_REVIEWED_AT = re.compile(r'Reviewed at\s+`?([0-9a-fA-F]{7,40})`?')


def last_reviewed_sha(bodies):
    """The SHA the most recent review footer names, or None.

    `bodies` is in the order they were posted, oldest first.
    """
    for body in reversed(list(bodies or ())):
        match = _REVIEWED_AT.search(body or '')
        if match:
            return match.group(1).lower()
    return None


def head_changed(head_sha, reviewed_sha):
    """Whether a PR has commits its last review did not see. A short SHA in
    the footer matches the head it abbreviates."""
    if not reviewed_sha or not head_sha:
        return False
    head = head_sha.lower()
    return not head.startswith(reviewed_sha.lower())


def select_review_next(prs, names):
    """Order every PR that needs a reviewer, in the picker's three tiers.

    Tier 0 `needs-re-review`, tier 1 `changes-requested` (the rework cascade),
    tier 2 `needs-review` or a head that moved since the last review. Lowest
    number first within a tier. Skipped: a draft, a PR carrying `reviewing` or
    `updating`, and an `approved` PR whose head has not moved and which does
    not carry `needs-re-review`.

    Each PR carries `labels`, and may carry `head_sha`, `reviewed_sha` and
    `draft`. A PR no review has ever footered is tier 2 whatever its labels,
    unless it is `approved`, so a PR a person opened without a label is still
    found.
    """
    busy = {names['reviewing'], names['updating']}
    ranked = []
    for pr in prs or ():
        labels = set(pr.get('labels') or ())
        if pr.get('draft') or labels & busy:
            continue
        moved = head_changed(pr.get('head_sha'), pr.get('reviewed_sha'))
        if names['needs-re-review'] in labels:
            tier = 0
        elif names['changes-requested'] in labels and not moved:
            tier = 1
        elif moved:
            tier = 2
        elif names['approved'] in labels:
            continue
        elif names['needs-review'] in labels or not pr.get('reviewed_sha'):
            tier = 2
        else:
            continue
        ranked.append((tier, pr['number'], pr))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [pr for _, _, pr in ranked]


def review_prior_state(labels, names, moved=False):
    """The state label the picker selected a PR by, for Step 1b's routing.

    A `changes-requested` PR whose head moved was selected for a review of
    the new commits, not for rework, so it does not report that label.
    """
    keys = (('needs-re-review', 'needs-review') if moved
            else ('needs-re-review', 'changes-requested', 'needs-review'))
    for key in keys:
        if names[key] in (labels or ()):
            return names[key]
    return None
