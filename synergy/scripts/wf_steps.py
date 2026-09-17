"""
Run boundaries: `start`, `exit-cleanup` and `tree-clean`.

Each replaces a sequence the model used to run by hand and branch over: the
claim, stage, clean-tree check and branch at the start of a build, and the
claim release, review reconcile, scratch delete and tree check at the end.
The decisions are `wf_core_steps.py`; `scripts/README.md` has the module map.
"""

import argparse
import json
import os

import wf_core
from wf_claim import (
    _claim_marker_path, acquire_claim, holds_claim, release_claims,
)
from wf_config import cmd_scratch_clean, prepare_cfg, repo_root
from wf_io import (
    EXIT_ENV, EXIT_LOST, EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, call_command, emit,
    emit_line, gh_json, run,
)
from wf_stage import checkout_branch, set_stage

EXIT_DIRTY = EXIT_PARTIAL


# ── the working tree ─────────────────────────────────────────────────────────

def tree_entries():
    """The working tree's porcelain entries, or None when git cannot say."""
    code, out, _ = run(['git', 'status', '--porcelain', '-z'])
    if code != 0:
        return None
    return wf_core.parse_porcelain(out)


def discard(entries):
    """Restore tracked paths and remove untracked ones. Never `-x`, so a
    gitignored `.env` or `node_modules` is not touched; never `stash`, which
    every worktree on the clone shares. Returns the paths git refused.

    One unmatched path makes git abort the whole command, so a failed batch
    is retried path by path and only the paths that still fail are returned.
    """
    refused = []
    for cmd, paths in ((['git', 'restore', '--staged', '--worktree', '--'],
                        wf_core.tracked(entries)),
                       (['git', 'clean', '-fd', '--'], wf_core.untracked(entries))):
        paths = list(dict.fromkeys(paths))
        if not paths or run(cmd + paths)[0] == 0:
            continue
        refused.extend(p for p in paths if run(cmd + [p])[0] != 0)
    return refused


def start_clean():
    """Reset an inherited dirty tree. Returns (discarded paths, still dirty)."""
    entries = tree_entries() or []
    if not entries:
        return [], []
    discard(entries)
    discarded = list(dict.fromkeys(e['path'] for e in entries))
    return discarded, [e['path'] for e in tree_entries() or []]


def cmd_tree_clean(args):
    """`wf tree-clean`: discard what the model chose to discard, then recheck.

    The choice between committing a change and discarding it stays with the
    model. This does the discard and the re-check that used to loop by hand.
    """
    entries = tree_entries()
    if entries is None:
        emit('error', EXIT_ENV, reason='git status failed; is this a git checkout?')
    if args.all:
        chosen = entries
    else:
        wanted = {p.replace('\\', '/').rstrip('/') for p in args.discard or ()}
        if not wanted:
            emit('usage', EXIT_USAGE, reason='name what to discard: --discard PATH or --all')
        chosen = [e for e in entries
                  if e['path'].rstrip('/') in wanted
                  or any(e['path'].startswith(w + '/') for w in wanted)]
    refused = discard(chosen)
    left = tree_entries() or []
    if left:
        emit('dirty', EXIT_DIRTY, discarded=[e['path'] for e in chosen],
             remaining=left, refused=refused,
             reason='%d path(s) still uncommitted: commit each that is work, '
                    'then discard the rest' % len(left))
    emit_line('ok', EXIT_OK, reason='tree clean; discarded %d path(s)' % len(chosen))


# ── exit cleanup ─────────────────────────────────────────────────────────────

def _bulk_issues():
    path = os.path.join(repo_root(), '.claude', 'bulk-set.json')
    try:
        with open(path, encoding='utf-8') as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return []
    return [int(s['number']) for s in record.get('stories') or () if 'number' in s]


def reconcile_pr(cfg, number):
    """Record an unfinished review as changes-requested when the PR's labels
    do not already say where it stands. Returns (action, error)."""
    from wf_review import cmd_review_finish
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['pr', 'view', str(number), '--repo', repo,
                             '--json', 'state,labels'])
    if not ok or not data:
        return 'unread', 'could not read PR #%d (%s)' % (number, err)
    names = wf_core.review_names(cfg.get('review_labels'))
    labels = [l['name'] for l in data.get('labels') or ()]
    if wf_core.exit_pr_action(data.get('state'), labels, names) == 'keep':
        return 'kept', None
    code, payload = call_command(cmd_review_finish, argparse.Namespace(
        pr=number, verdict='changes-requested', fixes_applied=False))
    if code != EXIT_OK or not payload.get('verified'):
        return 'reconcile-failed', payload.get('reason') or 'label not confirmed'
    return 'changes-requested', None


def cmd_exit_cleanup(args):
    """`wf exit-cleanup`: the last step of every run, whatever ended it.

    Releases the issue claims, reconciles and releases the PR's review claim
    when this run won it, deletes the scratch files, and reports the tree.
    Only a dirty tree is left to the caller, because only the caller knows
    which change is work to commit and which is noise to discard.
    """
    issues = list(dict.fromkeys((args.issue or []) + (_bulk_issues() if args.bulk else [])))
    root = repo_root()
    problems, pr_action = [], None
    targets = ['issue-%d' % n for n in issues]

    # The review claim is ours only when Acquire wrote its marker. Without it
    # another agent may own the review, and touching its lock or label would
    # unlock a PR somebody is reviewing.
    if args.pr and os.path.isfile(_claim_marker_path(root, 'pr-%d' % args.pr)):
        cfg = prepare_cfg()
        pr_action, err = reconcile_pr(cfg, args.pr)
        if err:
            problems.append(err)
        targets.append('pr-%d' % args.pr)
    elif args.pr:
        pr_action = 'not-held'

    released = release_claims(targets) if targets else {}
    failed = [t for t in targets if not released.get(t)]
    if failed:
        problems.append('could not release %s' % ', '.join(failed))

    _, scratch = call_command(cmd_scratch_clean, argparse.Namespace())
    for item in scratch.get('failed') or ():
        problems.append('could not delete %s (%s)' % (item['file'], item['reason']))

    entries = tree_entries()
    if entries is None:
        problems.append('git status failed')
        entries = []

    fields = dict(released=[t for t in targets if released.get(t)], failed=failed,
                  pr_action=pr_action, problems=problems)
    if entries:
        done = ('also: %s' % '; '.join(problems) if problems
                else 'claims and scratch done')
        emit('dirty', EXIT_DIRTY, remaining=entries, **fields,
             reason='%d uncommitted path(s): commit each that is work (and '
                    'push), then `wf tree-clean` the rest; %s'
                    % (len(entries), done))
    if problems:
        emit('partial', EXIT_PARTIAL, reason='; '.join(problems), **fields)
    parts = ['released %s' % ', '.join(fields['released']) if fields['released']
             else 'no claims to release']
    if pr_action in ('changes-requested', 'kept'):
        parts.append('PR #%d review %s' % (args.pr, pr_action))
    parts.append('scratch deleted, tree clean')
    emit_line('ok', EXIT_OK, reason='; '.join(parts))


# ── start ────────────────────────────────────────────────────────────────────

def _claim(target):
    """Take or keep a claim. 'won', 'lost' or 'error'."""
    return 'won' if holds_claim(target) else acquire_claim(target)


def _start_issue(args, cfg):
    number = args.issue
    outcome = _claim('issue-%d' % number)
    if outcome == 'lost':
        emit('lost', EXIT_LOST, number=number,
             reason='#%d is claimed by another run; pick a different story' % number)
    if outcome == 'error':
        emit('error', EXIT_ENV, number=number,
             reason='could not push the claim ref for #%d; check write access '
                    'to refs/claims/*' % number)
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, issue, err = gh_json(['issue', 'view', str(number), '--repo', repo,
                              '--json', 'number,title'])
    if not ok or not issue:
        emit('error', EXIT_ENV, reason='could not read #%d (%s)' % (number, err))
    staged, stage_msg = set_stage(cfg, number, wf_core.STAGE_NAMES['stage-in-progress'])
    discarded, dirty = start_clean()
    branch, checked_out, branch_msg = checkout_branch(cfg, issue)
    return dict(number=number, title=issue.get('title'), branch=branch,
                stage_set=staged, stage_message=stage_msg, checked_out=checked_out,
                branch_message=branch_msg, discarded=discarded, dirty=dirty)


def _start_group(args, cfg):
    from wf_plan import cmd_bulk_mark
    record_issues = []
    path = os.path.join(repo_root(), '.claude', 'bulk-set.json')
    try:
        with open(path, encoding='utf-8') as fh:
            record = json.load(fh)
        record_issues = [int(s['number']) for s in record.get('stories') or ()
                         if s.get('group') == args.group]
    except (OSError, ValueError, KeyError):
        emit('usage', EXIT_USAGE, reason='no readable .claude/bulk-set.json; run plan-set --claim first')
    if not record_issues:
        emit('usage', EXIT_USAGE, reason='group %d has no stories in the bulk set' % args.group)
    outcomes = {n: _claim('issue-%d' % n) for n in record_issues}
    lost = [n for n, o in outcomes.items() if o == 'lost']
    claim_errors = [n for n, o in outcomes.items() if o == 'error']
    discarded, dirty = start_clean()
    default = cfg['default_branch']
    run(['git', 'fetch', 'origin', default])
    code, _, err = run(['git', 'checkout', '-b', args.branch, 'origin/%s' % default])
    checked_out = code == 0
    branch_msg = ('created from origin/%s' % default if checked_out
                  else 'could not create branch (%s)' % err.strip())
    pushed = False
    if checked_out:
        pcode, _, perr = run(['git', 'push', '-u', 'origin', args.branch])
        pushed = pcode == 0
        if not pushed:
            branch_msg += '; push failed (%s)' % perr.strip()
    mcode, _ = call_command(cmd_bulk_mark, argparse.Namespace(
        group=args.group, branch=args.branch, built=None)) if checked_out else (1, None)
    return dict(group=args.group, stories=record_issues, lost=lost,
                claim_errors=claim_errors,
                branch=args.branch, checked_out=checked_out, pushed=pushed,
                recorded=mcode == EXIT_OK, branch_message=branch_msg,
                discarded=discarded, dirty=dirty)


def cmd_start(args):
    """`wf start`: everything between a claim and the first edit, in one call.

    `--issue N` re-takes a lost claim, sets `In Progress`, resets an inherited
    dirty tree and creates or checks out the story branch. `--group G
    --branch B` does the same for a bulk group: confirms every story's claim,
    resets the tree, creates and pushes the shared branch and records it.
    """
    if (args.issue is None) == (args.group is None):
        emit('usage', EXIT_USAGE, reason='name exactly one of --issue N or --group G')
    if args.group is not None and not args.branch:
        emit('usage', EXIT_USAGE, reason='--group needs --branch')
    cfg = prepare_cfg()
    result = _start_issue(args, cfg) if args.issue is not None else _start_group(args, cfg)

    failures = []
    if result.get('stage_set') is False:
        failures.append('Stage not set: %s' % result['stage_message'])
    if not result['checked_out']:
        failures.append(result['branch_message'])
    if result.get('pushed') is False and result['checked_out']:
        failures.append('branch not pushed')
    if result.get('recorded') is False and result['checked_out']:
        failures.append('branch not recorded in the bulk set')
    if result.get('lost'):
        failures.append('claims lost to another run: %s'
                        % ', '.join('#%d' % n for n in result['lost']))
    if result.get('claim_errors'):
        failures.append('claim push failed, not lost (retry `wf start`): %s'
                        % ', '.join('#%d' % n for n in result['claim_errors']))
    if result['dirty']:
        failures.append('tree still dirty after reset')
    if failures:
        emit('partial', EXIT_PARTIAL, reason='; '.join(failures), **result)
    note = ('; reset an inherited dirty tree (%s)' % ', '.join(result['discarded'])
            if result['discarded'] else '')
    emit_line('ok', EXIT_OK, branch=result['branch'],
              reason='on %s, ready to build%s' % (result['branch'], note))
