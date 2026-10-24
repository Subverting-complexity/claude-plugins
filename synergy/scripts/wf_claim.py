"""
Claims: the atomic claim refs and markers, and the `claim`, `claim-release` and
`claim-reap` subcommands. Every claim also carries its session label, and a
session that refuses claim refs with 403 claims with that label alone
(`wf_claim_label.py`).

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import os
import random
import time
from datetime import datetime, timezone

import wf_core
import wf_rest
from wf_claim_label import (
    acquire_by_label, add_and_settle, claim_error_reason, claim_label,
    claim_marker_path, claim_refs_refused, claim_session_path, holds_label, keep_label_path, label_claims, release_label,
    mark_claim_refs_refused, push_refused, read_label_marker, reap_session_labels,
    session_guid, session_label, write_claim_marker,
    remove_every_session_label, remove_session_label, remove_session_labels,
)
from wf_config import check_environment, prepare_cfg, repo_root
from wf_io import (
    EXIT_ENV, EXIT_LOST, EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, emit, eprint, gh_json,
    graphql_blocked, run,
)
from wf_stage import set_stage, set_stages


# ── claim + markers ──────────────────────────────────────────────────────────

# The one marker path, shared with the label claims.
_claim_marker_path = claim_marker_path


def acquire_claim(target):
    """Atomically acquire refs/claims/<target> (compare-and-swap).

    Returns one of three outcomes — never a bare bool, so the caller can tell
    a rival apart from a broken environment:

      'won'   — the ref was created and we hold the claim (marker written).
      'lost'  — the ref already exists with a different object: a rival agent
                got there first. A normal outcome — try the next pool item.
      'error' — the push failed for a reason that is *not* a lost claim: no
                write access to refs/claims/*, an auth or network failure, a
                missing remote. The caller must surface this instead of
                walking the pool, so a broken environment is never mistaken
                for "every candidate was already claimed" (a phantom
                all-blocked the user reads as an empty backlog).

    A won ref also gets this session's label (#440), so a session that cannot
    read refs by pushing them still sees the claim. When another session's
    label was added first, this run gives the ref back and loses.

    A push the remote refuses with 403, while the ref is absent, is a session
    that allows no claim refs at all (#438). The claim is then held by the
    session label alone, and so is every later claim in the run.
    """
    if claim_refs_refused():
        return acquire_by_label(target)
    # The claim commit carries the empty tree and no parent, so its push holds
    # two objects whatever the remote already has (#431). Built on HEAD's tree
    # with no parent, git could not tell the remote had that tree and sent the
    # whole project with every claim. A parent of HEAD is not the fix either:
    # it would push unpushed local commits into refs/claims/. The empty tree is
    # written rather than hard-coded, because its id differs in a SHA-256
    # repository. Nothing reads a claim commit's tree or parent: holders compare
    # its sha, and claim-reap reads its commit time.
    code, tree, err = run(['git', 'mktree'], input_text='')
    if code != 0:
        eprint('wf: cannot write the empty tree to build a claim object (%s)'
               % (err.strip() or 'no detail'))
        return 'error'
    msg = 'claim %s %s pid%d-%d' % (
        target,
        datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        os.getpid(), random.randint(0, 1_000_000),
    )
    code, sha, err = run(['git', 'commit-tree', tree.strip(), '-m', msg])
    if code != 0:
        eprint('wf: git commit-tree failed (%s)' % err.strip())
        return 'error'
    sha = sha.strip()
    code, _, push_err = run(['git', 'push', 'origin', '%s:refs/claims/%s' % (sha, target)])
    if code != 0:
        # A failed push is a *lost claim* only if the ref now exists on the
        # remote (a rival pushed a different object first). Probe it: if the
        # ref is present the rival won; if it is absent the push failed for
        # another reason (no write access, auth, network) and we must report
        # an error rather than silently pretend a rival took it.
        exists, _, _ = run(['git', 'ls-remote', '--exit-code', 'origin',
                            'refs/claims/%s' % target])
        if exists == 0:
            return 'lost'
        if push_refused(push_err):
            mark_claim_refs_refused()
            return acquire_by_label(target)
        eprint('wf: claim push for %s failed and the ref is absent — treating '
               'as an environment error (%s)' % (target, push_err.strip() or 'no detail'))
        return 'error'
    # The GUID goes beside the marker, so the release removes the label this
    # claim adds even after the session id changed (#442).
    write_claim_marker(repo_root(), target, sha, session_guid())
    labelled = add_and_settle(target)
    if labelled == 'lost':
        # Another session's label came first: it holds the item, by label alone
        # if it is a cloud session. Give the ref back.
        if not release_claim(target):
            eprint('wf: warning - %s is held by another session, and its claim '
                   'ref could not be given back' % target)
        return 'lost'
    if labelled == 'error':
        eprint('wf: warning - %s is claimed by its ref, but without its session '
               'label a cloud session cannot see the claim' % target)
    return 'won'


def _marked(target):
    """Whether this checkout has a marker for `target`: it holds the claim."""
    return os.path.exists(_claim_marker_path(repo_root(), target))


def _keep_label_path(target):
    return keep_label_path(repo_root(), target)


def _unlabels(target):
    """Whether releasing `target` takes this session's label off it: this
    checkout holds the claim, and no `handoff` asked to keep the label. A
    handoff whose release failed leaves a `.keep-label` file beside the
    marker, so the `exit-cleanup` that retries the release keeps it too."""
    return _marked(target) and not os.path.exists(_keep_label_path(target))


def _drop_marker(target):
    root = repo_root()
    for path in (_claim_marker_path(root, target), _keep_label_path(target),
                 claim_session_path(root, target)):
        try:
            os.remove(path)
        except OSError:
            pass


def _keep_label_on_retry(target):
    try:
        with open(_keep_label_path(target), 'w', encoding='utf-8') as fh:
            fh.write('handoff')
    except OSError:
        pass


def release_claim(target, every_label=False, keep_label=False):
    """Delete refs/claims/<target> and this checkout's marker for it.

    Returns True when the ref is gone from the remote and False when it may
    still be there. A failed release is not harmless: the ref goes on holding
    the item out of every pool until `claim-reap` frees it hours later, so the
    caller has to be able to say so rather than report it released.

    Deleting a ref that is already gone fails the push too, and that is the
    outcome the caller wanted, so releasing stays idempotent: a failed push is
    a failed release only when the ref is still there or the remote cannot be
    asked.

    When this checkout holds the claim, its session label comes off that item
    too (#440), and a label that stays is a failed release: it would go on
    holding the item from every other session. A closed, completed issue and
    a merged pull request keep the label as their record (`release_label`).
    With no marker, this checkout holds nothing, and a label still on the
    item is a record `handoff` left, so it stays. `keep_label` leaves it on
    purpose, for `handoff`. `every_label` takes every session's label off an
    open item, for `claim-reap` freeing a claim this session never held. A
    claim held by the label alone is released by removing the label.
    """
    held = _unlabels(target)
    if read_label_marker(target) is not None and not every_label:
        return _release_label_claim(target, keep_label or not held)
    if every_label:
        labels_off = remove_every_session_label(target)
    elif held and not keep_label:
        labels_off = release_label(target, claim_label(target))
    else:
        labels_off = True
    ref = 'refs/claims/%s' % target
    code, _, err = run(['git', 'push', 'origin', ':%s' % ref])
    if code != 0:
        # `--exit-code` makes ls-remote exit 2 only when it reached the remote
        # and found no such ref; any other answer leaves the ref's fate unknown.
        probe, _, _ = run(['git', 'ls-remote', '--exit-code', 'origin', ref])
        if probe != 2:
            eprint('wf: warning - could not release %s (%s); it stays claimed '
                   'until this is re-run or claim-reap frees it'
                   % (ref, err.strip() or 'no detail'))
            # The marker stays as well: the ref is still this checkout's, and
            # the marker is what lets `claim --keep-held` recognise it as such.
            return False
    if not labels_off:
        # The marker stays, so a re-run takes the label off.
        eprint('wf: warning - %s is released from its ref, but its session '
               'label is still on it' % target)
        return False
    _drop_marker(target)
    return True


def _release_label_claim(target, keep_label=False):
    """Release a claim held by the label alone. A label still on an open item
    keeps its marker, so a re-run can release it. The label removed is the
    one the marker names, which differs from this session's after a
    `/clear` gave the session a new id."""
    label = claim_label(target)
    if not keep_label and not release_label(target, label):
        return False
    _drop_marker(target)
    return True


def release_claims(targets, keep_label=False):
    """Delete many claim refs in one push. Returns {target: released}.

    `release_claim` for a list, at the cost of one push however many refs
    there are, rather than a push each (#300): `handoff` for a bulk run of
    five stories paid five. The outcome per target means what it means there,
    so an already-gone ref still counts as released.

    A push naming several refs deletes each it can and fails if any one
    failed, so a non-zero push says nothing about which. One `ls-remote` over
    all of them settles it: a ref still listed was not released. `--exit-code`
    makes ls-remote exit 2 when it reached the remote and found none of them;
    any other failure leaves every ref's fate unknown, and none is reported as
    released. Only a released target's marker is removed, for the reason
    `release_claim` gives. The session labels of the claims this checkout
    holds come off in one batch (`remove_session_labels`), finished work
    keeping its label, and a label that stays fails its target's release.
    `keep_label` leaves every label where it is, for `handoff`. The push names
    only the ref claims.
    """
    targets = list(dict.fromkeys(targets or ()))
    if not targets:
        return {}
    mine = session_guid()
    # A label-only claim whose marker names another id (the session had a
    # `/clear`) is released on its own, with the label its marker names.
    other = [t for t in targets if read_label_marker(t) not in (None, mine)]
    released = {t: _release_label_claim(t, keep_label or not _unlabels(t))
                for t in other}
    targets = [t for t in targets if t not in other]
    label_only = [t for t in targets if read_label_marker(t) is not None]
    ref_targets = [t for t in targets if t not in label_only]
    unlabel = [] if keep_label else [t for t in targets if _unlabels(t)]
    labels_off = dict.fromkeys(targets, True)
    # Each label is the one its claim added (#442), not this session's.
    labels_off.update(remove_session_labels(
        unlabel, {t: claim_label(t) for t in unlabel}))
    released.update((t, bool(labels_off.get(t))) for t in label_only)
    for target in label_only:
        if released[target]:
            _drop_marker(target)
    targets = ref_targets
    if not targets:
        return released
    refs = {target: 'refs/claims/%s' % target for target in targets}
    labelled = released
    released = dict.fromkeys(targets, True)
    released.update(labelled)
    code, _, err = run(['git', 'push', 'origin']
                       + [':%s' % refs[target] for target in targets])
    if code != 0:
        probe, out, _ = run(['git', 'ls-remote', '--exit-code', 'origin']
                            + [refs[target] for target in targets])
        if probe == 2:
            present = set()
        elif probe == 0:
            present = {parts[1] for parts in (line.split() for line in
                                              (out or '').splitlines())
                       if len(parts) == 2}
        else:
            present = None
        failed = [target for target in targets
                  if present is None or refs[target] in present]
        for target in failed:
            released[target] = False
        if failed:
            eprint('wf: warning - could not release %s (%s); %s claimed until '
                   'this is re-run or claim-reap frees %s'
                   % (', '.join(refs[t] for t in failed),
                      err.strip() or 'no detail',
                      'it stays' if len(failed) == 1 else 'they stay',
                      'it' if len(failed) == 1 else 'them'))
    stuck = [t for t in targets if released[t] and not labels_off.get(t)]
    for target in stuck:
        released[target] = False
    if stuck:
        eprint('wf: warning - %s released from %s ref, but the session label is '
               'still on %s' % (', '.join(stuck), 'its' if len(stuck) == 1 else 'their',
                                'it' if len(stuck) == 1 else 'them'))
    for target in targets:
        if released[target]:
            _drop_marker(target)
        elif keep_label:
            _keep_label_on_retry(target)
    return released


def apply_in_progress(cfg, issue):
    """Take durable ownership: assign @me and set `Stage` to In Progress.

    Neither is a label any more -- an issue in progress is one that is assigned
    and whose `Stage` says In Progress, and those two facts live where GitHub
    itself keeps them rather than in a name somebody has to remember to change.
    The `Stage` write is what takes the issue out of the pool, so a failed one
    is said out loud.

    The write uses the node id the pool read already holds, and its result is
    left on the issue as `_stage_result` so `finish_pick` does not write the
    `Stage` a second time.
    """
    _assign(cfg, issue)
    number = int(issue['number'])
    ids = {number: issue['id']} if issue.get('id') else None
    written, message = set_stages(
        cfg, {number: wf_core.STAGE_NAMES['stage-in-progress']}, ids)[number]
    issue['_stage_result'] = (written, message)
    if not written:
        eprint('wf: warning — could not set #%s to In Progress (%s)'
               % (issue['number'], message))


def _assign(cfg, issue):
    """Assign @me, removing any retired workflow label in the same call."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['issue', 'edit', str(issue['number']), '--repo', repo,
            '--add-assignee', '@me']
    retired = wf_core.retired_labels_on(issue.get('labels') or [],
                                        cfg.get('labels') or {})
    if graphql_blocked():
        # `gh issue edit` reads through GraphQL, so it fails here too.
        ok, err = wf_rest.rest_assign(cfg, issue['number'])
        wf_rest.rest_remove_labels(cfg, issue['number'], retired)
        if not ok:
            eprint('wf: warning — could not assign #%s (%s)' % (issue['number'], err))
        return
    for name in retired:
        args += ['--remove-label', name]
    code, _, err = run(['gh'] + args)
    if code != 0:
        eprint('wf: warning — could not assign #%s (%s)'
               % (issue['number'], err.strip()))


def revert_in_progress(cfg, number):
    """Undo `apply_in_progress`: unassign and set `Stage` back to Backlog.

    The claim is taken before the issue can be validated, so a candidate that
    turns out not to be workable has already been assigned and marked. Every
    path that gives one back has to leave it exactly as available as it was
    found, or the next run sees an issue somebody is apparently working on and
    skips it for good. Backlog rather than blank: both are the pool, and the
    written value is the one a board shows under a column. Returns
    (written, message) for the `Stage` half.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    if graphql_blocked():
        ok, err = wf_rest.rest_unassign(cfg, number)
        code = 0 if ok else 1
    else:
        code, _, err = run(['gh', 'issue', 'edit', str(number), '--repo', repo,
                            '--remove-assignee', '@me'])
    if code != 0:
        eprint('wf: warning — could not unassign #%s (%s)' % (number, err.strip()))
    return set_stage(cfg, number, wf_core.STAGE_NAMES[wf_core.POOL_STAGE])


def apply_claim_marker(cfg, args):
    """Apply the human-visible ownership marker for a won claim.

    Returns a short description of what was applied, or None. Best-effort:
    the claim is already held, and failing to advertise it is worth a warning
    rather than giving the item back.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    if args.issue is not None:
        # The labels are read only so that any retired one can be taken off
        # on the way past; nothing is applied in their place.
        ok, data, _ = gh_json(['issue', 'view', str(args.issue), '--repo', repo,
                               '--json', 'labels'])
        if not ok or data is None:
            eprint('wf: warning - could not read issue #%d to mark it' % args.issue)
            return None
        apply_in_progress(cfg, {'number': args.issue,
                                'labels': [l['name'] for l in data.get('labels', [])]})
        return '@me + Stage In Progress'
    # Imported here because wf_review imports this module.
    from wf_review import add_review_label
    names = wf_core.review_names(cfg.get('review_labels'))
    ok, err = add_review_label(cfg, args.pr, names['reviewing'],
                               remove=names['needs-review'])
    if not ok:
        eprint('wf: warning - could not apply the reviewing label (%s)' % err.strip())
        return None
    return names['reviewing']


def holds_claim(target):
    """Whether this checkout already holds refs/claims/<target>.

    It does when the marker Acquire wrote names the object the remote ref
    points at. A rival's claim is a different object, so it never matches.
    The ref is checked first. A claim held by the label alone is held while
    no claim ref is there and this session's label was added first.
    """
    if read_label_marker(target) is not None:
        return holds_label(target)
    try:
        with open(_claim_marker_path(repo_root(), target), encoding='utf-8') as fh:
            held = fh.read().strip()
    except OSError:
        return False
    if not held:
        return False
    code, out, _ = run(['git', 'ls-remote', 'origin', 'refs/claims/%s' % target])
    return code == 0 and out.split()[:1] == [held]


def cmd_claim(args):
    """Take the atomic claim on one issue or PR, without selecting anything.

    `pick` and `review-next` claim what they select. This is for the caller
    that already knows which item it wants — a named PR under review, a story
    a person asked for by number — and needs the same compare-and-swap.
    """
    err = check_environment()
    if err:
        emit('error', EXIT_ENV, reason=err)
    if (args.issue is None) == (args.pr is None):
        emit('usage', EXIT_USAGE, reason='name exactly one of --issue N or --pr N')
    target = ('issue-%d' % args.issue) if args.issue else ('pr-%d' % args.pr)

    # `--keep-held` keeps a claim this checkout already holds (#164): `handoff`
    # takes the PR's review claim, and Phase 8's own `claim --pr` must not
    # then read that lock as a rival's, which a fresh object always would.
    # Only on request, so a second session sharing the checkout still loses.
    held = getattr(args, 'keep_held', False) and holds_claim(target)
    outcome = 'won' if held else acquire_claim(target)
    if outcome == 'won':
        # The ref is the lock, but it is ephemeral. Ownership has to be
        # visible on GitHub too, or a picker running after this session dies
        # selects the item again: assignment plus the in-progress label for an
        # issue, the `reviewing` state label for a PR.
        marker = apply_claim_marker(prepare_cfg(), args) if args.marker else None
        emit('ok', EXIT_OK, target=target, claimed=True, marker=marker,
             reason='claimed %s' % target)
    if outcome == 'lost':
        # A rival agent holds it. Normal, and not an error: the caller moves on
        # to the next item rather than reporting a broken environment.
        emit('lost', EXIT_LOST, target=target, claimed=False,
             reason='%s is already claimed by another run' % target)
    emit('error', EXIT_ENV, target=target, claimed=False,
         reason=claim_error_reason(
             target, 'could not push the claim ref for %s; this is an environment '
             'problem, not a rival — check write access to refs/claims/*' % target))


def cmd_claim_release(args):
    err = check_environment()
    if err:
        emit('error', EXIT_ENV, reason=err)
    targets = (['issue-%d' % number for number in args.issue or []]
               + ['pr-%d' % number for number in args.pr or []])
    if not targets:
        emit('usage', EXIT_USAGE,
             reason='name what to release: --issue N and/or --pr N')
    outcomes = release_claims(targets)
    released = [target for target in targets if outcomes.get(target)]
    failed = [target for target in targets if not outcomes.get(target)]
    # Still exit 0, as the command always has, so a caller tidying up is never
    # stopped by it; but a ref that is still there is named in `failed` and in
    # the reason, never listed as released.
    parts = []
    if released:
        parts.append('released %s' % ', '.join(released))
    if failed:
        parts.append('could not release %s, which stay%s claimed until this is '
                     're-run or claim-reap frees %s'
                     % (', '.join(failed), 's' if len(failed) == 1 else '',
                        'it' if len(failed) == 1 else 'them'))
    emit('ok', EXIT_OK, released=released, failed=failed, reason='; '.join(parts))


# ── claim-reap ───────────────────────────────────────────────────────────────

def list_claim_refs():
    """Every claim ref on the remote, as [(sha, target)]. Fetches the objects
    first so their commit timestamps can be read without a call per ref."""
    run(['git', 'fetch', '--prune', 'origin',
         '+refs/claims/*:refs/remotes/origin/claims/*'])
    code, out, err = run(['git', 'ls-remote', 'origin', 'refs/claims/*'])
    if code != 0:
        return None, err.strip() or 'git ls-remote failed'
    refs = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith('refs/claims/'):
            refs.append((parts[0], parts[1][len('refs/claims/'):]))
    return refs, ''


def claim_age_hours(sha):
    """Hours since the claim object was written, or None if unreadable."""
    code, out, _ = run(['git', 'show', '-s', '--format=%ct', sha])
    if code != 0 or not out.strip():
        return None
    try:
        return int((time.time() - int(out.strip().split()[-1])) // 3600)
    except ValueError:
        return None


def claim_target_state(cfg, target):
    """Read the issue or PR a claim ref names.

    Returns `(kind, number, state, labels, has_open_pr, assigned)`. `state` is
    None when the lookup failed. `assigned` is what tells a live issue claim
    from an abandoned one now that no label does: `apply_in_progress` assigns
    `@me`, so an issue claim over an unassigned issue is a claim nobody holds.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    kind, _, raw = target.partition('-')
    try:
        number = int(raw)
    except ValueError:
        return None, None, None, [], False, False
    if kind not in ('issue', 'pr'):
        return None, None, None, [], False, False

    fields = 'state,labels,assignees' if kind == 'issue' else 'state,labels'
    ok, data, _ = gh_json([kind, 'view', str(number), '--repo', repo,
                           '--json', fields])
    if not ok or not data:
        return kind, number, None, [], False, False
    labels = [l['name'] for l in data.get('labels', [])]
    state = data.get('state', '')
    assigned = bool(data.get('assignees'))

    has_open_pr = False
    if kind == 'issue' and state.upper() == 'OPEN':
        ok, prs, _ = gh_json(['pr', 'list', '--repo', repo, '--state', 'open',
                              '--search', 'closes #%d' % number, '--json', 'number'])
        has_open_pr = bool(ok and prs)
    return kind, number, state, labels, has_open_pr, assigned


def _labels_reason(deleted, failed):
    text = ''
    if deleted:
        text += '; %d unused session label(s) deleted' % len(deleted)
    if failed:
        text += '; %d unused session label(s) could not be deleted' % len(failed)
    return text


def cmd_claim_reap(args):
    """Free claim refs whose work has demonstrably moved on; flag the rest.

    Replaces the hand-run procedure this command was extracted from. The
    judgement is `wf_core.reap_verdict`; everything here is I/O.

    A freed open item loses every `session:` label, not only this session's:
    a crashed session's label would otherwise stay first on it and every
    later claim would lose to it (#440). A claim held by a label alone, which
    a cloud session takes, is judged the same way, its age read from the
    label's `labeled` event, and freed by taking that label off; an issue in
    review keeps the label `handoff` left on it. Finished work keeps its
    labels. Last, each `session:` label no issue or pull request carries,
    open or closed, is deleted from the repository.
    """
    err = check_environment()
    if err:
        emit('error', EXIT_ENV, reason=err)
    cfg = prepare_cfg()
    refs, ferr = list_claim_refs()
    if refs is None:
        emit('error', EXIT_ENV, reason='could not list claim refs (%s)' % ferr)

    names = wf_core.review_names(cfg.get('review_labels'))
    active_review = [names['reviewing'], names['updating']]

    def judge(target, age, label=None):
        kind, number, state, labels, has_open_pr, assigned = \
            claim_target_state(cfg, target)
        if kind is None:
            return wf_core.SUSPECT, 'not an issue or PR claim'
        if label and has_open_pr:
            # `handoff` leaves the label on an issue in review, so that it
            # still carries it once the pull request merges. Not a claim.
            return None, None
        return wf_core.reap_verdict(
            kind, age, state, labels, threshold=args.threshold,
            review_labels=active_review, has_open_pr=has_open_pr,
            assigned=assigned)

    results, detail = [], {wf_core.REAP: [], wf_core.SUSPECT: [], wf_core.SKIP: []}
    release_failed = []
    claims = [('refs/claims/%s' % target, target, None, claim_age_hours(sha))
              for sha, target in refs]
    claims += [('label:%s' % label, target, label, age)
               for target, label, age in label_claims({t for _, t in refs})]
    for held_by, target, label, age in claims:
        verdict, reason = judge(target, age, label)
        if verdict is None:
            continue
        results.append((target, verdict, reason))
        entry = {'ref': held_by, 'reason': reason}
        if age is not None:
            entry['age_hours'] = age
        if verdict == wf_core.REAP and not args.dry_run:
            freed = (remove_session_label(target, label) if label
                     else release_claim(target, every_label=True))
            if not freed:
                # The ref or the label is still there, so it is not reaped.
                release_failed.append(entry)
                continue
        detail[verdict].append(entry)

    # A `session:` label that no open issue or pull request carries is a
    # finished session's; deleting it keeps the label list short (#440).
    labels_deleted, labels_failed = reap_session_labels(dry_run=args.dry_run)
    label_fields = {'labels_deleted': labels_deleted} if labels_deleted else {}
    if labels_failed:
        label_fields['labels_failed'] = labels_failed
    if not claims:
        emit('ok', EXIT_OK, reaped=[], suspect=[], skipped=[], **label_fields,
             reason='no active claim refs' + _labels_reason(labels_deleted, labels_failed))

    summary = wf_core.reap_summary(results)
    summary['reaped'] -= len(release_failed)
    reason = ('%d reaped, %d suspect (check by hand), %d too recent'
              % (summary['reaped'], summary['suspect'], summary['skipped'])
              + _labels_reason(labels_deleted, labels_failed))
    fields = dict(reaped=detail[wf_core.REAP], suspect=detail[wf_core.SUSPECT],
                  skipped=detail[wf_core.SKIP], summary=summary,
                  dry_run=bool(args.dry_run), **label_fields)
    if release_failed:
        emit('partial', EXIT_PARTIAL, release_failed=release_failed, **fields,
             reason='%s; %d release(s) failed: %s' % (
                 reason, len(release_failed),
                 ', '.join(e['ref'] for e in release_failed)))
    emit('ok', EXIT_OK, **fields, reason=reason)
