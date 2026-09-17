"""
Picking, the entry point: the `pick` and `refine` commands and the result a
pick returns.

The selection is `wf_pick_select.py`, the tree and single-issue reads are
`wf_pick_tree.py`, and `candidates` is `wf_pick_candidates.py`.
`scripts/README.md` has the module map.
"""

import wf_core
from wf_candidates import report_unprioritised
from wf_config import check_environment, load_config, prepare_cfg
from wf_deps import known_edges
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_ENV, EXIT_NO_CANDIDATES, EXIT_OK, EXIT_USAGE, emit,
    emit_line, eprint, run,
)
from wf_pick_select import _pick_round, claim_validate_walk, prerequisite_pick
from wf_pick_tree import fetch_issue_candidate
from wf_stage import (
    best_effort, checkout_branch, set_stage, set_start_date, stage_in_progress,
)


def cmd_pick(args):
    env_err = check_environment()
    if env_err:
        emit('error', EXIT_ENV, reason=env_err)

    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    if not cfg.get('org') or not cfg.get('repo'):
        emit('error', EXIT_ENV, reason='org/repo missing from config')

    # Stories being built alongside this one on a shared branch (bulk-execute).
    # A dependency on one of them is satisfied by this same run, so it does not
    # block; every other open dependency still does.
    siblings = [int(n) for n in (getattr(args, 'sibling', None) or [])]

    # Explicit target: skip selection/sort entirely and run the same claim +
    # validate machinery against the one named issue, so the explicit-number
    # path auto-closes an already-resolved story exactly like auto-pick does.
    if getattr(args, 'issue', None):
        cand = fetch_issue_candidate(cfg, args.issue)
        edges = known_edges(cand)
        if edges is not None and not siblings:
            # A bulk claim names its siblings and must claim exactly the story
            # it asked for, so only a single-story pick is redirected.
            waiting_on = wf_core.edge_states(
                edges, '%s/%s' % (cfg['org'], cfg['repo']))[0]
            if waiting_on and len(waiting_on) <= wf_core.DEP_LIMIT:
                selected, side_effects, extra = prerequisite_pick(
                    args, cfg, cand, waiting_on)
                finish_pick(args, cfg, selected, side_effects, None, **extra)
        selected, side_effects = claim_validate_walk(cfg, [cand], None, siblings,
                                                     start_date=args.checkout)
        if cand.get('reset_from_pr'):
            side_effects.insert(0, {'issue': args.issue, 'action': 'reset-abandoned-pr',
                                    'pr': cand['reset_from_pr']})
        if not selected:
            emit('all-blocked', EXIT_ALL_BLOCKED,
                 reason='issue #%d is not workable (claimed away, blocked, or '
                        'already resolved by a merged PR)' % args.issue,
                 side_effects=side_effects)
        finish_pick(args, cfg, selected, side_effects, backlog_mode=None)

    # One round. A Blocked issue whose edges have all closed is released and
    # judged in that same round, from the same read, so an empty pool is not
    # swept and read a second time on the chance it only looked empty.
    side_effects = []
    outcome = _pick_round(cfg, args, siblings, side_effects)

    verdict, backlog_mode = outcome['verdict'], outcome['backlog_mode']
    report_unprioritised(verdict['pool'], outcome['priority'])
    unclassified = sorted(set(verdict.get('unclassified') or ()))
    oversized = sorted(set(verdict.get('oversized') or ()))
    if unclassified:
        eprint('wf: %d issue(s) left out of the %s pool because the org has not '
               'typed or classified them: %s (run wf issue-audit to backfill)'
               % (len(unclassified), args.mode,
                  ', '.join('#%d' % n for n in unclassified)))
    if oversized:
        eprint('wf: %d issue(s) left out because their Effort is above '
               '--max-effort %s: %s'
               % (len(oversized), args.max_effort,
                  ', '.join('#%d' % n for n in oversized)))

    if not outcome['selected'] and not verdict['ranked']:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='nothing with a blank or %s Stage is available to a code '
                    'agent' % wf_core.STAGE_NAMES[wf_core.POOL_STAGE],
             backlog_mode=backlog_mode, oversized=oversized,
             side_effects=side_effects)
    if not outcome['selected']:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='every candidate was claimed-away, blocked, or already resolved',
             backlog_mode=backlog_mode, side_effects=side_effects)

    finish_pick(args, cfg, outcome['selected'], side_effects, backlog_mode,
                container=outcome['container'], offered=outcome['offered'],
                unblocks=outcome['unblocks'])


def cmd_refine(args):
    """`wf refine`: send a claimed issue back for refinement in one call.

    Four writes a run used to make by hand: `Stage` to Needs refinement, the
    comment saying what is missing, the assignment given up and the claim
    released. The stage goes first, because it is the issue's state; a run
    that stopped after an unassign and before the stage write left an
    unassigned issue reading `In Progress` that no pool would ever offer.
    """
    from wf_claim import release_claims

    cfg = prepare_cfg()
    number = args.issue
    try:
        with open(args.body_file, encoding='utf-8') as fh:
            body = fh.read().strip()
    except OSError as exc:
        emit('usage', EXIT_USAGE, reason='could not read %s (%s)' % (args.body_file, exc))
    if not body:
        emit('usage', EXIT_USAGE, reason='the comment is empty: say what a person '
                                         'must add before the issue can be built')
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    stage = wf_core.STAGE_NAMES['stage-refinement']
    stage_set, stage_message = set_stage(cfg, number, stage)
    code, _, err = run(['gh', 'issue', 'comment', str(number), '--repo', repo,
                        '--body-file', args.body_file])
    commented = code == 0
    code, _, uerr = run(['gh', 'issue', 'edit', str(number), '--repo', repo,
                         '--remove-assignee', '@me'])
    unassigned = code == 0
    released = release_claims(['issue-%d' % number]).get('issue-%d' % number, False)
    emit('ok', EXIT_OK, number=number, stage_set=stage_set,
         stage_message=None if stage_set else stage_message, commented=commented,
         comment_error=None if commented else (err or '').strip(),
         unassigned=unassigned, unassign_error=None if unassigned else (uerr or '').strip(),
         claim_released=released,
         reason='#%d sent to %s' % (number, stage))


def finish_pick(args, cfg, selected, side_effects, backlog_mode, container=None,
                offered=(), unblocks=(), prerequisite_for=None):
    """Build the `ok` result for a selected story, optionally checking out, and emit.

    `container` and `offered` are set when the pick came through an Epic or
    Feature: the story claimed is the first of the stories it offers, and
    `offered` is the rest, which the caller may build alongside it.
    `unblocks` lists the waiting stories this one frees, and
    `prerequisite_for` is set when the story was claimed in place of a named
    issue that waits on it.
    """
    result = {
        'number': selected['number'],
        'title': selected['title'],
        'url': selected['url'],
        'labels': selected['labels'],
        'milestone': selected['milestone'],
        'body': selected['body'],
        'claim_ref': 'refs/claims/issue-%d' % selected['number'],
        'mode': getattr(args, 'mode', 'story'),
        'backlog_mode': backlog_mode,
        'side_effects': side_effects,
        'checked_out': False,
    }
    siblings = [int(n) for n in (getattr(args, 'sibling', None) or [])]
    if siblings:
        result['siblings'] = siblings
    if container:
        result['container'] = container
        result['offered'] = list(offered)
    if unblocks:
        result['unblocks'] = list(unblocks)
    if prerequisite_for:
        result['prerequisite_for'] = prerequisite_for

    if args.checkout:
        # The claim walk wrote both already, in one mutation, when it could.
        if '_stage_result' in selected:
            written, stage_msg = selected['_stage_result']
        else:
            written, stage_msg = best_effort(stage_in_progress, cfg,
                                             selected['number'])
        result['stage_set'] = written
        result['stage_message'] = stage_msg
        if not written:
            eprint('wf: Stage not set — %s' % stage_msg)
        if '_date_result' in selected:
            dated, date_msg = selected['_date_result']
        else:
            dated, date_msg = best_effort(set_start_date, cfg, selected['number'])
        result['start_date_set'] = dated
        result['start_date_message'] = date_msg
        if getattr(args, 'no_branch', False):
            # Bulk runs: every story in the set gets the claim, the marker and
            # the Stage write, but they all share one branch the caller creates
            # once. Branching per story here would give each its own.
            result['branch'] = None
            result['branch_message'] = 'branch skipped (--no-branch) — caller owns the branch'
        else:
            branch, checked_out, branch_msg = checkout_branch(cfg, selected)
            result['branch'] = branch
            result['checked_out'] = checked_out
            result['branch_message'] = branch_msg
            if not checked_out:
                eprint('wf: %s' % branch_msg)

    # Compact by default: no body unless `--body`, and no message for a step
    # that succeeded. `execute` asks for the body; nothing else reads it.
    emit_line('ok', EXIT_OK, **wf_core.compact_pick(result, getattr(args, 'body', False)))
