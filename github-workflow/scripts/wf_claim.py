"""
Claims: the atomic claim refs and markers, and the `claim`, `claim-release` and
`claim-reap` subcommands.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import os
import random
import time
from datetime import datetime, timezone

import wf_core
from wf_config import check_environment, prepare_cfg, repo_root
from wf_io import (
    EXIT_ENV, EXIT_LOST, EXIT_OK, EXIT_USAGE, emit, eprint, gh_json, run,
)
from wf_stage import set_stage


# ── claim + markers ──────────────────────────────────────────────────────────

def _claim_marker_path(root, target):
    return os.path.join(root, '.claude', 'claim-%s.sha' % target)


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
    """
    code, tree, _ = run(['git', 'rev-parse', 'HEAD^{tree}'])
    if code != 0:
        eprint('wf: cannot read HEAD tree to build a claim object')
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
        eprint('wf: claim push for %s failed and the ref is absent — treating '
               'as an environment error (%s)' % (target, push_err.strip() or 'no detail'))
        return 'error'
    root = repo_root()
    os.makedirs(os.path.join(root, '.claude'), exist_ok=True)
    with open(_claim_marker_path(root, target), 'w', encoding='utf-8') as fh:
        fh.write(sha)
    return 'won'


def release_claim(target):
    run(['git', 'push', 'origin', ':refs/claims/%s' % target])
    marker = _claim_marker_path(repo_root(), target)
    try:
        os.remove(marker)
    except OSError:
        pass


def apply_in_progress(cfg, issue):
    """Take durable ownership: assign @me and set `Stage` to In Progress.

    Neither is a label any more -- an issue in progress is one that is assigned
    and whose `Stage` says In Progress, and those two facts live where GitHub
    itself keeps them rather than in a name somebody has to remember to change.
    The `Stage` write is what takes the issue out of the pool, so a failed one
    is said out loud.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['issue', 'edit', str(issue['number']), '--repo', repo,
            '--add-assignee', '@me']
    retired = wf_core.retired_labels_on(issue.get('labels') or [],
                                        cfg.get('labels') or {})
    for name in retired:
        args += ['--remove-label', name]
    code, _, err = run(['gh'] + args)
    if code != 0:
        eprint('wf: warning — could not assign #%s (%s)'
               % (issue['number'], err.strip()))
    written, message = set_stage(cfg, issue['number'],
                                 wf_core.STAGE_NAMES['stage-in-progress'])
    if not written:
        eprint('wf: warning — could not set #%s to In Progress (%s)'
               % (issue['number'], message))


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
    names = wf_core.review_names(cfg.get('review_labels'))
    code, _, err = run(['gh', 'pr', 'edit', str(args.pr), '--repo', repo,
                        '--remove-label', names['needs-review'],
                        '--add-label', names['reviewing']])
    if code != 0:
        eprint('wf: warning - could not apply the reviewing label (%s)' % err.strip())
        return None
    return names['reviewing']


def holds_claim(target):
    """Whether this checkout already holds refs/claims/<target>.

    It does when the marker Acquire wrote names the object the remote ref
    points at. A rival's claim is a different object, so it never matches.
    """
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
         reason='could not push the claim ref for %s; this is an environment '
                'problem, not a rival — check write access to refs/claims/*'
                % target)


def cmd_claim_release(args):
    err = check_environment()
    if err:
        emit('error', EXIT_ENV, reason=err)
    released = []
    for number in args.issue or []:
        release_claim('issue-%d' % number)
        released.append('issue-%d' % number)
    for number in args.pr or []:
        release_claim('pr-%d' % number)
        released.append('pr-%d' % number)
    if not released:
        emit('usage', EXIT_USAGE,
             reason='name what to release: --issue N and/or --pr N')
    emit('ok', EXIT_OK, released=released,
         reason='released %s' % ', '.join(released))


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
        return kind, number, None, [], False
    labels = [l['name'] for l in data.get('labels', [])]
    state = data.get('state', '')
    assigned = bool(data.get('assignees'))

    has_open_pr = False
    if kind == 'issue' and state.upper() == 'OPEN':
        ok, prs, _ = gh_json(['pr', 'list', '--repo', repo, '--state', 'open',
                              '--search', 'closes #%d' % number, '--json', 'number'])
        has_open_pr = bool(ok and prs)
    return kind, number, state, labels, has_open_pr, assigned


def cmd_claim_reap(args):
    """Free claim refs whose work has demonstrably moved on; flag the rest.

    Replaces the hand-run procedure this command was extracted from. The
    judgement is `wf_core.reap_verdict`; everything here is I/O.
    """
    err = check_environment()
    if err:
        emit('error', EXIT_ENV, reason=err)
    cfg = prepare_cfg()
    refs, ferr = list_claim_refs()
    if refs is None:
        emit('error', EXIT_ENV, reason='could not list claim refs (%s)' % ferr)
    if not refs:
        emit('ok', EXIT_OK, reaped=[], suspect=[], skipped=[],
             reason='no active claim refs')

    names = wf_core.review_names(cfg.get('review_labels'))
    active_review = [names['reviewing'], names['updating']]

    results, detail = [], {wf_core.REAP: [], wf_core.SUSPECT: [], wf_core.SKIP: []}
    for sha, target in refs:
        kind, number, state, labels, has_open_pr, assigned = \
            claim_target_state(cfg, target)
        age = claim_age_hours(sha)
        if kind is None:
            verdict, reason = wf_core.SUSPECT, 'not an issue or PR claim'
        else:
            verdict, reason = wf_core.reap_verdict(
                kind, age, state, labels, threshold=args.threshold,
                review_labels=active_review, has_open_pr=has_open_pr,
                assigned=assigned)
        results.append((target, verdict, reason))
        entry = {'ref': 'refs/claims/%s' % target, 'reason': reason}
        if age is not None:
            entry['age_hours'] = age
        if verdict == wf_core.REAP and not args.dry_run:
            release_claim(target)
        detail[verdict].append(entry)

    summary = wf_core.reap_summary(results)
    emit('ok', EXIT_OK, reaped=detail[wf_core.REAP],
         suspect=detail[wf_core.SUSPECT], skipped=detail[wf_core.SKIP],
         summary=summary, dry_run=bool(args.dry_run),
         reason='%d reaped, %d suspect (check by hand), %d too recent'
                % (summary['reaped'], summary['suspect'], summary['skipped']))
