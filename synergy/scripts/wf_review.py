"""
Pull request review work: the PR pools, review labels, and the `update-next`,
`review-next`, `review-finish`, `labels-ensure`, `sibling-pr` and `handoff`
subcommands.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import os

import wf_core
from wf_capabilities import fetch_repo_state
from wf_claim import acquire_claim, holds_claim, release_claims
from wf_config import prepare_cfg, repo_root
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_ENV, EXIT_NO_CANDIDATES, EXIT_OK, emit, emit_line,
    eprint, gh_graphql, gh_json, run,
)
from wf_stage import set_stages


# ── PR pickers (pr-review pools) ────────────────────────────────────────────

def _norm_pr(raw):
    return {
        'number': raw['number'],
        'title': raw.get('title', '') or '',
        'labels': [l['name'] for l in raw.get('labels', [])],
        'branch': raw.get('headRefName', '') or '',
        'url': raw.get('url', '') or '',
    }


def assemble_prs(cfg, mine):
    """Fetch open PRs (optionally only @me's). Returns (ok, prs, err)."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['pr', 'list', '--repo', repo, '--state', 'open',
            '--json', 'number,title,labels,headRefName,url', '--limit', '200']
    if mine:
        args += ['--assignee', '@me']
    ok, data, err = gh_json(args)
    if not ok:
        return False, None, err
    return True, [_norm_pr(r) for r in data or []], ''


def pr_label_names(cfg, number):
    """Read a PR's current label names. Returns (names_or_None, err)."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['pr', 'view', str(number), '--repo', repo, '--json', 'labels'])
    if not ok or not data:
        return None, err
    return [l['name'] for l in data.get('labels', [])], ''


def apply_pr_labels(cfg, number, add, remove=None):
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['pr', 'edit', str(number), '--repo', repo, '--add-label', add]
    if remove:
        args += ['--remove-label', remove]
    code, _, err = run(['gh'] + args)
    if code != 0:
        eprint('wf: warning — could not apply PR label (%s)' % err.strip())


def checkout_pr(cfg, number):
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    code, _, err = run(['gh', 'pr', 'checkout', str(number), '--repo', repo])
    if code != 0:
        return False, 'gh pr checkout failed (%s)' % err.strip()
    return True, 'checked out the PR branch'


def claim_first_pr(pool, apply_marker, no_claim=False):
    """Walk the ordered pool, claim the first PR we win, apply its marker.

    Unlike stories there is no per-candidate validation — the first successful
    claim is the selection. Returns (outcome, selected_pr_or_None, side_effects)
    where outcome is:
      'ok'    — a PR is selected (claimed and marked, or — in no_claim mode —
                simply chosen without a lock).
      'none'  — the pool was exhausted; every candidate was lost to a rival.
      'error' — a claim push failed for a non-rival reason (no write access,
                network); abort rather than walking on.

    With no_claim=True (read-only review, which has no push access), the first
    pool item is returned as-is — no ref is pushed and no marker is applied.
    """
    side_effects = []
    for pr in pool:
        if no_claim:
            return 'ok', pr, side_effects
        outcome = acquire_claim('pr-%d' % pr['number'])
        if outcome == 'error':
            return 'error', None, side_effects
        if outcome == 'lost':
            side_effects.append({'pr': pr['number'], 'action': 'claim-lost'})
            continue
        apply_marker(pr)
        return 'ok', pr, side_effects
    return 'none', None, side_effects


def cmd_update_next(args):
    cfg = prepare_cfg()
    names = wf_core.review_names(cfg.get('review_labels'))
    ok, prs, err = assemble_prs(cfg, mine=True)
    if not ok:
        emit('error', EXIT_ENV, reason='PR fetch failed: %s' % err)
    pool = wf_core.select_update_pool(prs, names)
    if not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='no PRs assigned to you have feedback to address')

    # Marker: add `updating`, but keep the actionable state label so the
    # pr-review skill can make its final relabel decision.
    outcome, selected, side_effects = claim_first_pr(
        pool, lambda pr: apply_pr_labels(cfg, pr['number'], add=names['updating']))
    if outcome == 'error':
        emit('error', EXIT_ENV,
             reason='could not write a PR claim ref — no push access to '
                    'refs/claims/* or a remote failure (not a lost claim)',
             side_effects=side_effects)
    if outcome == 'none':
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='every candidate PR is already claimed by another agent',
             side_effects=side_effects)

    result = {
        'kind': 'pr-update',
        'number': selected['number'], 'title': selected['title'],
        'url': selected['url'], 'branch': selected['branch'],
        'labels': selected['labels'],
        'claim_ref': 'refs/claims/pr-%d' % selected['number'],
        'prior_state': wf_core.actionable_update_label(selected['labels'], names),
        'side_effects': side_effects, 'checked_out': False,
    }
    if args.checkout:
        okc, msg = checkout_pr(cfg, selected['number'])
        result['checked_out'] = okc
        result['checkout_message'] = msg
        if not okc:
            eprint('wf: %s' % msg)
    emit('ok', EXIT_OK, **result)


REVIEW_POOL_QUERY = (
    'query($owner:String!,$repo:String!){'
    ' repository(owner:$owner,name:$repo){'
    ' pullRequests(states:OPEN, first:100, orderBy:{field:CREATED_AT, direction:ASC}){'
    ' pageInfo { hasNextPage }'
    ' nodes { number title url headRefName headRefOid isDraft'
    ' labels(first:30){ nodes { name } }'
    ' comments(last:30){ nodes { body createdAt } }'
    ' reviews(last:30){ nodes { body createdAt } } } } } }'
)


def assemble_review_prs(cfg):
    """Every open PR with its head and the SHA its last review footer names.

    One query, so the picker can see a PR whose head moved since its last
    review without reading each PR's comments. Returns (ok, prs, err).
    """
    ok, data, err = gh_graphql(REVIEW_POOL_QUERY, owner=cfg['org'], repo=cfg['repo'])
    if not ok or not data:
        return False, None, err or 'no data'
    try:
        pulls = data['repository']['pullRequests']
        nodes = pulls['nodes']
    except (KeyError, TypeError):
        return False, None, 'unexpected pullRequests shape'
    # `no-candidates` is conclusive, so a pool it could not read whole is an
    # error rather than an answer.
    if (pulls.get('pageInfo') or {}).get('hasNextPage'):
        return False, None, 'more than 100 open PRs; the picker reads only the first 100'
    prs = []
    for node in nodes or ():
        posts = (((node.get('comments') or {}).get('nodes') or [])
                 + ((node.get('reviews') or {}).get('nodes') or []))
        posts.sort(key=lambda p: p.get('createdAt') or '')
        prs.append({
            'number': node['number'], 'title': node.get('title') or '',
            'url': node.get('url') or '', 'branch': node.get('headRefName') or '',
            'labels': [l['name'] for l in (node.get('labels') or {}).get('nodes') or ()],
            'head_sha': node.get('headRefOid') or '', 'draft': bool(node.get('isDraft')),
            'reviewed_sha': wf_core.last_reviewed_sha(p.get('body') for p in posts),
        })
    return True, prs, ''


def cmd_review_next(args):
    cfg = prepare_cfg()
    names = wf_core.review_names(cfg.get('review_labels'))
    ok, prs, err = assemble_review_prs(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='PR fetch failed: %s' % err)
    # Labels and moved heads both count, so an empty pool is the answer: no
    # PR carries a review state and none has commits its last review missed.
    pool = wf_core.select_review_next(prs, names)
    if not pool:
        emit_line('no-candidates', EXIT_NO_CANDIDATES,
                  reason='no open PR needs review, rework or a re-review')

    def marker(pr):
        labels = set(pr['labels'])
        prior = next((names[k] for k in ('needs-re-review', 'needs-review')
                      if names[k] in labels), None)
        apply_pr_labels(cfg, pr['number'], add=names['reviewing'], remove=prior)

    no_claim = getattr(args, 'no_claim', False)
    outcome, selected, side_effects = claim_first_pr(pool, marker, no_claim=no_claim)
    if outcome == 'error':
        emit('error', EXIT_ENV,
             reason='could not write a PR claim ref — no push access to '
                    'refs/claims/* or a remote failure (not a lost claim)',
             side_effects=side_effects)
    if outcome == 'none':
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='every candidate PR is already claimed by another agent',
             side_effects=side_effects)

    moved = wf_core.head_changed(selected.get('head_sha'), selected.get('reviewed_sha'))
    result = {
        'kind': 'pr-review',
        'number': selected['number'], 'title': selected['title'],
        'url': selected['url'], 'branch': selected['branch'],
        'labels': selected['labels'],
        # In read-only (no_claim) mode nothing was locked or relabelled, so
        # there is no claim ref to release and the `reviewing` marker is absent.
        'claimed': not no_claim,
        'claim_ref': None if no_claim else 'refs/claims/pr-%d' % selected['number'],
        'prior_state': wf_core.review_prior_state(selected['labels'], names, moved),
        'head_changed': moved,
        'side_effects': side_effects, 'checked_out': False,
    }
    if args.checkout:
        okc, msg = checkout_pr(cfg, selected['number'])
        result['checked_out'] = okc
        result['checkout_message'] = msg
        if not okc:
            eprint('wf: %s' % msg)
    emit('ok', EXIT_OK, **result)


def cmd_review_finish(args):
    """Reconcile a reviewed PR's state labels to exactly the verdict label.

    Encodes the pr-review skill's Step 10/10b deterministic label dance:
    read the PR's labels, strip every stale review-state label, leave exactly
    the verdict label (keeping the sticky `fixes-applied` when fixes were
    pushed), then read back and — if the verdict label did not stick because
    the repo lacks it — create it guarded (no `--force`) and re-apply. The
    label decisions are the pure, tested `wf_core` functions; this shell only
    does the `gh` I/O.
    """
    cfg = prepare_cfg()
    names = wf_core.review_names(cfg.get('review_labels'))
    repo = '%s/%s' % (cfg['org'], cfg['repo'])

    current, err = pr_label_names(cfg, args.pr)
    if current is None:
        emit('error', EXIT_ENV, reason='could not read PR #%d labels (%s)' % (args.pr, err))

    add, remove = wf_core.reconcile_review_labels(
        current, args.verdict, names, fixes_applied=args.fixes_applied)
    if add or remove:
        edit = ['gh', 'pr', 'edit', str(args.pr), '--repo', repo]
        for a in add:
            edit += ['--add-label', a]
        for r in remove:
            edit += ['--remove-label', r]
        code, _, eerr = run(edit)
        if code != 0:
            eprint('wf: review-finish label edit warning (%s)' % eerr.strip())

    target = names[args.verdict]
    created_label = False
    after, _ = pr_label_names(cfg, args.pr)
    if after is not None and wf_core.review_label_missing(after, args.verdict, names):
        color, desc = wf_core.REVIEW_LABEL_META[args.verdict]
        run(['gh', 'label', 'create', target, '--repo', repo,
             '--description', desc, '--color', color])
        run(['gh', 'pr', 'edit', str(args.pr), '--repo', repo, '--add-label', target])
        created_label = True
        after, _ = pr_label_names(cfg, args.pr)

    verified = after is not None and target in after
    if not verified:
        eprint('wf: review-finish could not confirm %r on PR #%d' % (target, args.pr))
    emit('ok', EXIT_OK, pr=args.pr, verdict=args.verdict, verdict_label=target,
         added=add, removed=remove, created_label=created_label,
         verified=verified, labels=after)


def ensure_review_labels(cfg, live=None, repo=None):
    """Create every review label the repo lacks. Returns (created, failed, err).

    Guarded: a label that exists is never touched, so there is no `--force` to
    churn a colour somebody chose, and a create that loses a race to another
    agent ("already exists") counts as created rather than failed. `err` is
    set only when the repo's labels could not be read at all.
    """
    repo = repo or '%s/%s' % (cfg['org'], cfg['repo'])
    if live is None:
        ok, state, err = fetch_repo_state(cfg, repo)
        if not ok:
            return [], [], err
        live = state['labels']
    names = wf_core.review_names(cfg.get('review_labels'))
    created, failed = [], []
    for _, name, colour, description in wf_core.missing_review_labels(names, live):
        code, _, cerr = run(['gh', 'label', 'create', name, '--repo', repo,
                             '--description', description, '--color', colour])
        if code == 0 or 'already exists' in (cerr or ''):
            created.append(name)
        else:
            failed.append('%s (%s)' % (name, (cerr or '').strip() or 'gh failed'))
    return created, failed, ''


def add_review_label(cfg, number, add, remove=None):
    """Put a review-state label on a PR, creating it when the repo lacks it.

    `gh pr edit` refuses a label the repo does not have ("'x' not found").
    Until #290 only `review-finish` recovered, so a PR handed to review on a
    repo without the labels opened with no entry label and the picker never
    found it. On that refusal, create the review labels the repo lacks
    (guarded, never `--force`) and try the edit once more. Returns (ok, err).
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    edit = ['gh', 'pr', 'edit', str(number), '--repo', repo]
    if remove:
        edit += ['--remove-label', remove]
    edit += ['--add-label', add]
    code, _, err = run(edit)
    if code != 0 and 'not found' in (err or '').lower():
        _, _, lerr = ensure_review_labels(cfg, repo=repo)
        if not lerr:
            code, _, err = run(edit)
    return code == 0, err or ''


def cmd_labels_ensure(args):
    """Create the review-state labels a repo lacks, and nothing else.

    These are the only labels the workflow applies (#275), so this is the whole
    of label setup: `setup` runs it, `preflight --fix` runs it for a
    `review-label` finding, and a person can run it any time.
    """
    cfg = prepare_cfg()
    created, failed, err = ensure_review_labels(cfg)
    if err:
        emit('error', EXIT_ENV, reason="could not read the repo's labels: %s" % err)
    names = wf_core.review_names(cfg.get('review_labels'))
    fields = dict(created=created, failed=failed,
                  labels=[names[k] for k in wf_core.REVIEW_DEFAULT_LABELS])
    if failed:
        emit('error', EXIT_ENV, reason='could not create %d review label%s'
             % (len(failed), '' if len(failed) == 1 else 's'), **fields)
    emit('ok', EXIT_OK, **fields)


# ── sibling-pr ───────────────────────────────────────────────────────────────

SIBLING_PR_QUERY = (
    'query($owner:String!,$repo:String!){'
    ' repository(owner:$owner,name:$repo){'
    ' pullRequests(states:OPEN, first:100,'
    ' orderBy:{field:CREATED_AT, direction:ASC}){'
    ' nodes { number title url headRefName isDraft'
    ' labels(first:20){ nodes { name } }'
    ' closingIssuesReferences(first:10){ nodes { number } } } } } }'
)


def cmd_sibling_pr(args):
    """Report the open PRs that will close an issue on merge.

    One call, one definition of "duplicate", for the three places that ask:
    the pre-start guard, the create-time duplicate flag, and code review's
    reconciliation. Finding none is the normal answer, so it is `ok` and exit
    0 with an empty list — only a failed lookup is an error.
    """
    cfg = prepare_cfg()
    ok, data, err = gh_graphql(SIBLING_PR_QUERY, owner=cfg['org'], repo=cfg['repo'])
    if not ok or not data:
        emit('error', EXIT_ENV,
             reason='could not read open PRs (%s)' % (err.strip() or 'no detail'))
    try:
        nodes = data['repository']['pullRequests']['nodes']
    except (KeyError, TypeError):
        emit('error', EXIT_ENV, reason='unexpected pullRequests shape')
    # One read answers every issue asked about: a bulk set checks all its
    # stories here instead of reading the same open PRs once per story.
    numbers = [int(n) for n in (args.number if isinstance(args.number, list)
                                else [args.number])]
    by_issue = {n: wf_core.select_sibling_prs(nodes, n, args.exclude_branch)
                for n in numbers}
    found = {n: prs for n, prs in by_issue.items() if prs}
    first = numbers[0]
    emit('ok', EXIT_OK, issue=first, found=sum(len(p) for p in by_issue.values()),
         prs=by_issue[first],
         by_issue=[{'issue': n, 'prs': by_issue[n]} for n in numbers],
         reason=('no open PR closes %s' % ', '.join('#%d' % n for n in numbers))
                if not found else '; '.join(
                    'open PR(s) closing #%d: %s'
                    % (n, ', '.join('#%d' % p['number'] for p in prs))
                    for n, prs in found.items()))


# ── handoff ──────────────────────────────────────────────────────────────────

def cmd_handoff(args):
    """Hand a finished story to review: label the PR, set each issue's `Stage`
    to In Review, and release the issue claim.

    One command for what was a combined GraphQL mutation plus a fallback
    chain. Plain `gh` edits cost fewer round trips than the mutation did once
    its node-id and label-id lookups are counted, and they need no label
    cache, so the fallback has nothing left to fall back from.
    """
    cfg = prepare_cfg()
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    names = wf_core.review_names(cfg.get('review_labels'))
    state_label = names['changes-requested' if args.gate_failed else 'needs-review']

    # The review claim first, before any issue claim is let go (#164). Until
    # 11.2.0 the issue claims went here and the PR claim waited for Phase 8,
    # and a scheduled review firing in between claimed the run's own PR,
    # failed to check out a branch this worktree held, and stranded it as
    # `review-failed`. No marker: the entry label stays until Phase 8's own
    # `claim --pr --keep-held`, which keeps this claim and applies `reviewing`.
    target = 'pr-%d' % args.pr
    pr_claimed = 'won' if holds_claim(target) else acquire_claim(target)
    if pr_claimed != 'won':
        eprint('wf: warning - could not take the review claim on PR #%d (%s)'
               % (args.pr, pr_claimed))

    pr_labelled, perr = add_review_label(cfg, args.pr, state_label)
    if not pr_labelled:
        eprint('wf: warning - could not label PR #%d (%s)' % (args.pr, perr.strip()))

    # The `Stage` write *is* the hand-off. There is no label to swap any more:
    # an issue waiting on a review is one whose `Stage` says In Review, and
    # that is the only place the state is written. One aliased write for every
    # issue the PR closes.
    numbers = list(args.issue or [])
    in_review = wf_core.STAGE_NAMES['stage-in-review']
    outcomes = set_stages(cfg, {n: in_review for n in numbers})
    # Reported rather than fatal, like the stage: the PR exists either way,
    # but a claim left behind keeps the issue locked until claim-reap. One
    # push for every issue claim (#300).
    releases = release_claims(['issue-%d' % n for n in numbers])
    issues = []
    for number in numbers:
        written, message = outcomes.get(int(number), (False, 'not attempted'))
        if not written:
            eprint('wf: warning - could not set #%d to In Review (%s)'
                   % (number, message))
        issues.append({'number': number, 'stage_set': written,
                       'stage_message': message,
                       'claim_released': releases.get('issue-%d' % number, False)})

    # The preflight marker is kept: an issue filed during review re-ran the
    # whole preflight when it was deleted here. Exit cleanup removes it.
    for name in ('plan.md', 'label-cache.json'):
        try:
            os.remove(os.path.join(repo_root(), '.claude', name))
        except OSError:
            pass

    if (pr_claimed == 'won' and pr_labelled
            and all(i['stage_set'] and i['claim_released'] for i in issues)):
        emit_line('ok', EXIT_OK, pr=args.pr,
                  reason='PR #%d claimed and labelled %s; %s In Review and released'
                         % (args.pr, state_label,
                            ', '.join('#%d' % i['number'] for i in issues) or 'no issue'))
    emit('ok', EXIT_OK, pr=args.pr, pr_claimed=pr_claimed, pr_labelled=pr_labelled,
         review_label=state_label, issues=issues,
         reason='PR #%d labelled %s; %d issue(s) handed to review'
                % (args.pr, state_label, len(issues)))
