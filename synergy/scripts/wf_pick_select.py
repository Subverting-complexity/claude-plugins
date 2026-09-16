"""
Picking, the selection: the claim and validate walk, the judged pool, one
round of auto-pick, the prerequisite redirect, and the `Stage` writes a round
makes on the issues it passes over.

Split out of `wf_pick.py`; `scripts/README.md` has the module map.
"""

import wf_core
from wf_candidates import (
    _prefilter_numbers, claimed_issue_numbers, load_issue_facets, pool_verdict,
    read_pool,
)
from wf_claim import acquire_claim, apply_in_progress, release_claim
from wf_deps import close_resolved, mark_blocked, validate_issue
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_CAPABILITY, EXIT_ENV, EXIT_NEEDS_REFINEMENT, emit,
    eprint, run,
)
from wf_issue_io import add_comments
from wf_stage import set_stage, set_stages
from wf_unblock import UNBLOCK_COMMENT


def claim_validate_walk(cfg, pool, backlog_mode, siblings=(), start_date=False):
    """Walk the ordered pool: claim the top, validate only that one, act.

    The single claim-first/validate-lazily loop shared by auto-pick and the
    explicit `--issue` path. For each candidate it acquires the atomic claim,
    then validates, and only a valid candidate is assigned and set to In
    Progress: a dependency-blocked issue is set to Blocked, an already-resolved
    one is closed **and set to Done**, and the claim is released in both cases
    before walking on. The first valid claim is returned as the selection.

    Validating before the In Progress write, rather than after, is what spares
    a blocked candidate four writes: the assignment and the stage it used to
    get, and the unassignment and stage change that undid them. The claim ref
    already keeps every other run off the issue while it is checked.

    `siblings` is passed straight to `validate_issue` — the other stories of a
    bulk set, whose still-open state does not block a candidate that is being
    built alongside them. `start_date` stamps `Start date` in the same write
    as the stage.

    Returns (selected_or_None, side_effects). Emits + exits on a hard claim
    error (no push access / remote failure), never on a lost claim.
    """
    side_effects = []
    for cand in pool:
        target = 'issue-%d' % cand['number']
        outcome = acquire_claim(target)
        if outcome == 'error':
            emit('error', EXIT_ENV,
                 reason='could not write claim ref %s — no push access to '
                        'refs/claims/* or a remote failure (not a lost claim)' % target,
                 backlog_mode=backlog_mode, side_effects=side_effects)
        if outcome == 'lost':
            side_effects.append({'issue': cand['number'], 'action': 'claim-lost'})
            continue
        verdict, detail = validate_issue(cfg, cand, siblings)
        if verdict == 'unknown':
            # Nothing is known about this issue's dependencies, so nothing may
            # be written about them. Nothing has been written yet either, so
            # only the claim is let go, and the run stops: retrying the next
            # candidate would almost certainly hit the same failure.
            released = release_claim(target)
            side_effects.append({'issue': cand['number'],
                                 'action': 'released-unverified',
                                 'detail': detail, 'restored': True,
                                 'stage_message': None,
                                 'claim_released': released})
            emit('error', EXIT_ENV,
                 reason='could not read the blocked-by edges of #%d, so whether '
                        'it is blocked is unknown and nothing was decided from '
                        'it. The claim was released and nothing else was '
                        'written. Check the token and the network, then re-run.'
                        % cand['number'],
                 backlog_mode=backlog_mode, side_effects=side_effects)
        if verdict == 'blocked':
            written, message = mark_blocked(cfg, cand, detail, assigned=False)
            # A release that failed leaves the ref holding the issue out of
            # every pool until claim-reap, so it is reported beside the rest.
            released = release_claim(target)
            side_effects.append({'issue': cand['number'], 'action': 'marked-blocked',
                                 'detail': detail, 'stage_set': written,
                                 'stage_message': None if written else message,
                                 'claim_released': released})
            continue
        if verdict == 'resolved':
            done_set, _ = close_resolved(cfg, cand, detail)
            released = release_claim(target)
            side_effects.append({'issue': cand['number'], 'action': 'closed-already-resolved',
                                 'pr': detail, 'stage_set': done_set,
                                 'claim_released': released})
            continue
        apply_in_progress(cfg, cand, start_date)
        return cand, side_effects
    return None, side_effects


def read_plan_pool(cfg, args, extra=()):
    """The pool, judged, with what `plan_set` chooses from.

    One read of every open issue and the claim refs at once, field values
    taken from that same read, and the verdict of `evaluate_pool` for `--mode`.
    `extra` names issues outside the pool whose fields are wanted too, such as
    stories a person named. Returns a dict: `issues`, `by_num`, `claimed`,
    `facets`, `verdict`, and `universe`, `rank` and `reasons` from
    `wf_core.plan_universe`.
    """
    ok, issues, err, claimed = read_pool(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)
    present = {i['number'] for i in issues}
    numbers = sorted(set(_prefilter_numbers(issues, claimed))
                     | {int(n) for n in extra if int(n) in present})
    facets = load_issue_facets(cfg, numbers, issues=issues)
    type_map, classification_map = _mode_maps(cfg, args.mode, facets)
    verdict = wf_core.evaluate_pool(
        issues, mode=args.mode, type_map=type_map,
        classification_map=classification_map, priority_map=facets['priority'],
        effort_map=facets['effort'], ownership_map=facets['ownership'],
        claimed=claimed, max_effort=getattr(args, 'max_effort', None))
    universe, rank, reasons = wf_core.plan_universe(verdict, issues, claimed)
    return {'issues': issues, 'by_num': {i['number']: i for i in issues},
            'claimed': claimed, 'facets': facets, 'verdict': verdict,
            'universe': universe, 'rank': rank, 'reasons': reasons}


def _mode_maps(cfg, mode, facets):
    """The (type_map, classification_map) `select_pool` reads for `mode`."""
    if mode == 'story':
        # Read only to leave epics out, as `pick` does.
        return facets['types'] or None, None
    if cfg.get('type_capable'):
        types = facets['types'] or None
        return types, (facets['classification'] if types else None)
    return None, None


def prerequisite_pick(args, cfg, cand, blockers):
    """`pick --issue N` for an issue that waits on open issues: build the
    first prerequisite instead of refusing.

    A named issue blocked by work this run can build is not a dead end. The
    plan puts every prerequisite before it; this claims the first one that is
    ready, sets N to Blocked so the sweep releases it when the last blocker
    merges, and reports the whole order under `prerequisite_for`, so the caller
    can go on to N afterwards. Only a blocker nobody here may build (owned by a
    person, somebody else's, or waiting on such an issue itself) ends the pick,
    and the reason names it.

    Returns (selected, side_effects, extra), where `extra` holds the
    `unblocks` and `prerequisite_for` keywords `finish_pick` reports; the
    caller finishes the pick, so this module never reaches back into the
    `pick` entry point.

    A prerequisite is taken whatever `--mode` or `--max-effort` says, as long
    as a code agent may build it: those choose which work to start, not what
    it needs. Only a story in the pool, with a blank or Backlog `Stage`, is set
    to Blocked; a Parked or Needs refinement story keeps the hold a person put
    on it.
    """
    pool = read_plan_pool(cfg, args)
    by_num, universe = pool['by_num'], pool['universe']
    number = cand['number']
    universe[number] = {'blockers': list(blockers),
                        'parent': (by_num.get(number) or {}).get('parent'),
                        'epic': (pool['verdict'].get('epic') or {}).get(number)}
    wf_core.admit_prerequisites(universe, pool['verdict'], by_num, pool['reasons'])
    plan = wf_core.plan_set(universe, pool['rank'], seeds=[number], max_size=None,
                            reasons=pool['reasons'])
    side_effects = []
    if wf_core.is_available_stage((by_num.get(number) or {}).get('stage')):
        block_in_pool(cfg, {number: list(blockers)}, side_effects, by_num=by_num)
    left_out = {e['number']: e['reason'] for e in plan['excluded']}
    if number in left_out:
        emit('all-blocked', EXIT_ALL_BLOCKED, number=number,
             blocked_by=list(blockers), side_effects=side_effects,
             reason='issue #%d %s' % (number, left_out[number]))
    order = [s['number'] for s in plan['selected']]
    ready = [by_num[s['number']] for s in plan['selected']
             if not s['blocked_by'] and s['number'] != number
             and s['number'] in by_num]
    selected, effects = claim_validate_walk(cfg, ready, None, (),
                                            start_date=args.checkout)
    side_effects.extend(effects)
    if not selected:
        emit('all-blocked', EXIT_ALL_BLOCKED, number=number,
             blocked_by=list(blockers), build_order=order,
             side_effects=side_effects,
             reason='issue #%d waits on %s, and every prerequisite that could '
                    'start was claimed away, blocked or already resolved'
                    % (number, ', '.join(wf_core.ref_label(b) for b in blockers)))
    entry = next(s for s in plan['selected'] if s['number'] == selected['number'])
    return selected, side_effects, {
        'unblocks': [{'number': m, 'title': (by_num.get(m) or {}).get('title', '')}
                     for m in entry['unblocks']],
        'prerequisite_for': {'number': number, 'title': cand['title'],
                             'build_order': order}}


REFINEMENT_COMMENT = (
    '`Stage` set to `%s` by `wf pick`: %s. An unattended run cannot ask what '
    'was meant, so it moved on to the next candidate. Add what is missing, '
    'then set `Stage` back to `Backlog`.'
)


def send_to_refinement(cfg, entry):
    """Set an unclear issue to Needs refinement and say why. Side effect dict."""
    stage = wf_core.STAGE_NAMES['stage-refinement']
    written, message = set_stage(cfg, entry['number'], stage)
    if written:
        run(['gh', 'issue', 'comment', str(entry['number']), '--repo',
             '%s/%s' % (cfg['org'], cfg['repo']),
             '--body', REFINEMENT_COMMENT % (stage, entry['unclear'])])
    return {'issue': entry['number'], 'action': 'sent-to-refinement',
            'detail': entry['unclear'], 'stage_set': written,
            'stage_message': None if written else message}


def block_in_pool(cfg, blocked, side_effects, releasable=(), by_num=None):
    """Set every issue rule 4 caught to Blocked, and every `Blocked` issue whose
    edges have all closed back to Backlog, in one batched write.

    No comment on a block and no unassign: these were never claimed, and the
    blocked-by edge already says why. The unblock sweep releases each one when
    its last blocker closes. A release says why on the issue, as the sweep
    does, in one comment mutation for all of them.

    `by_num` is the pool read, whose node ids spare the id read. The pool was
    read a moment ago, and a claim taken since belongs to the run that took it,
    which writes its own `Stage`; so the claim refs are listed once more before
    anything is written, and an issue claimed in between is left alone.
    """
    by_num = by_num or {}
    wanted = {n: wf_core.STAGE_NAMES['stage-blocked'] for n in blocked}
    wanted.update({n: wf_core.STAGE_NAMES['stage-backlog'] for n in releasable})
    if not wanted:
        return
    taken = claimed_issue_numbers() & set(wanted)
    live = {n: stage for n, stage in wanted.items() if n not in taken}
    results = set_stages(cfg, live, {n: (by_num.get(n) or {}).get('id')
                                     for n in live}) if live else {}

    def effect(number, action, detail):
        if number in taken:
            written, message = False, ('claimed by another run after the pool was '
                                       'read, so its Stage is left to that run')
        else:
            written, message = results.get(number, (False, 'not written'))
        return {'issue': number, 'action': action, 'detail': detail,
                'stage_set': written, 'stage_message': None if written else message}

    for number in sorted(blocked):
        side_effects.append(effect(number, 'marked-blocked', ', '.join(
            wf_core.ref_label(b) for b in blocked[number])))
    comments, released = {}, []
    for number in sorted(releasable):
        issue = by_num.get(number) or {}
        closed = wf_core.edge_states(((issue.get('blockedBy') or {}).get('nodes')) or [],
                                     issue.get('repo'))[1]
        named = ', '.join(wf_core.ref_label(n) for n in closed)
        entry = effect(number, 'released', named)
        released.append(entry)
        side_effects.append(entry)
        if entry['stage_set']:
            comments[number] = (issue.get('id'), UNBLOCK_COMMENT % named)
    if comments:
        posted = add_comments(comments)
        for entry in released:
            if entry['issue'] in posted:
                entry['commented'] = posted[entry['issue']][0]


def _pick_round(cfg, args, siblings, side_effects):
    """Read the pool, judge it, and walk it once. Emits and exits on a hard
    stop; otherwise returns what it chose and what it read."""
    ok, issues, err, claimed = read_pool(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)

    # The org's own view of the issues still in the running: native type,
    # Priority, Effort, Ownership, Classification. All five decide the pool,
    # and the pool read already carries them.
    facets = load_issue_facets(cfg, _prefilter_numbers(issues, claimed),
                               issues=issues)
    type_map = facets['types'] or None
    classification_map = None
    if args.mode != 'story':
        classification_map = facets['classification'] if type_map else None
        if not type_map and not any(i.get('type') for i in issues):
            # The native type is the only classifier. Without one, `feature`
            # and `maintenance` are unanswerable -- and answering them wrongly
            # by label is exactly what this replaced.
            emit('no-capabilities', EXIT_CAPABILITY, mode=args.mode,
                 reason='no issue in this pool carries a native issue type, so '
                        '%s mode cannot be told apart from any other. Enable issue '
                        'types for the org and run `wf issue-audit` to backfill '
                        'them, or pick with `--mode story`.' % args.mode)
        eprint('wf: filtering %s mode by native issueType' % args.mode)

    backlog_mode, verdict = pool_verdict(cfg, args, issues, claimed, facets,
                                         type_map, classification_map)
    by_num = {i['number']: i for i in issues}
    block_in_pool(cfg, verdict['blocked'], side_effects,
                  verdict.get('releasable') or (), by_num)
    outcome = {'verdict': verdict, 'backlog_mode': backlog_mode,
               'priority': facets['priority'], 'selected': None,
               'container': None, 'offered': [], 'unblocks': []}

    tried = set()
    for entry in verdict['ranked']:
        if entry.get('unclear'):
            if getattr(args, 'unattended', False):
                side_effects.append(send_to_refinement(cfg, entry))
                continue
            # A person is there to say what was meant, so the run stops on the
            # highest-ranked unclear issue rather than skipping past it.
            emit('needs-refinement', EXIT_NEEDS_REFINEMENT,
                 number=entry['number'], title=entry['title'],
                 url=entry.get('url', ''), type=entry.get('type'),
                 detail=entry['unclear'], backlog_mode=backlog_mode,
                 side_effects=side_effects,
                 reason='#%d is the next pick but %s' % (entry['number'],
                                                         entry['unclear']))
        stories = entry.get('stories')
        if stories is None:
            walk = [entry] if entry['number'] not in tried else []
        else:
            walk = [by_num[n] for n in stories if n not in tried]
        tried.update(c['number'] for c in walk)
        if not walk:
            continue
        selected, effects = claim_validate_walk(cfg, walk, backlog_mode, siblings,
                                                start_date=args.checkout)
        side_effects.extend(effects)
        if not selected:
            continue
        outcome['selected'] = selected
        # The waiting stories this one frees, so the caller knows what its
        # merge releases and which story the sweep will offer next.
        outcome['unblocks'] = [
            {'number': w, 'title': (by_num.get(w) or {}).get('title', '')}
            for w, blockers in sorted((verdict.get('waiting') or {}).items())
            if selected['number'] in blockers]
        if stories is not None:
            outcome['container'] = {'number': entry['number'], 'title': entry['title'],
                                    'type': entry.get('type'),
                                    'feature': entry.get('feature')}
            rest = stories[stories.index(selected['number']) + 1:]
            outcome['offered'] = [{'number': n, 'title': by_num[n].get('title', '')}
                                  for n in rest][:wf_core.BULK_MAX - 1]
        return outcome
    return outcome
