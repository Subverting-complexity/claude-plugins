"""
Picking: the claim and validate walk, container trees, and the `pick` and
`candidates` subcommands.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import wf_core
from wf_candidates import (
    _norm_issue, _prefilter_numbers, claimed_issue_numbers, load_issue_facets,
    pool_verdict, read_pool, report_unprioritised,
)
from wf_claim import acquire_claim, apply_in_progress, release_claim
from wf_config import check_environment, field_name, load_config, prepare_cfg
from wf_deps import (
    close_resolved, issue_dependency_facts, issue_edges_map, known_edges,
    mark_blocked, validate_issue,
)
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_CAPABILITY, EXIT_ENV, EXIT_NEEDS_REFINEMENT,
    EXIT_NO_CANDIDATES, EXIT_OK, EXIT_USAGE, emit, eprint, gh_graphql, gh_json,
    run,
)
from wf_issue_io import add_comments
from wf_stage import (
    best_effort, checkout_branch, set_stage, set_stages, set_start_date,
    stage_in_progress,
)
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


# Stages an explicitly named issue may be picked from, beside a blank one. The
# rule lives in `wf_core_pool`, because the same stages decide which
# prerequisite a set may pull in.
PICKABLE_BY_NAME = wf_core.PICKABLE_BY_NAME


# How far below a container `candidates --parent` looks. Epic, Feature, story
# is two levels; the third is room for a story that has sub-issues of its own.
CONTAINER_TREE_DEPTH = 3


def _tree_selection(depth):
    base = 'number title state issueType { name } repository { nameWithOwner }'
    if depth <= 0:
        # The deepest level reads only how many sub-issues there are, so a
        # container down there reports them as unread rather than as empty.
        return base + ' subIssues { totalCount }'
    # Fifty, not GitHub's hundred, because the levels multiply against the
    # query's node limit. `totalCount` says when a level held more.
    return base + (' subIssues(first:50){ totalCount nodes { %s } }'
                   % _tree_selection(depth - 1))


def _tree_node(node):
    subs = node.get('subIssues') or {}
    nodes = subs.get('nodes') or []
    return {'number': node['number'], 'title': node.get('title') or '',
            'state': node.get('state') or '',
            'type': (node.get('issueType') or {}).get('name'),
            'repo': (node.get('repository') or {}).get('nameWithOwner'),
            'unread': max(0, (subs.get('totalCount') or 0) - len(nodes)),
            'children': [_tree_node(c) for c in nodes]}


def _tree_unread(node, out=None):
    """Every node with sub-issues the tree query did not read, as
    [{'number', 'unread'}]: a Feature past the page size says so rather than
    losing stories from both `candidates` and `excluded`."""
    out = [] if out is None else out
    # Only a container's: a story's own sub-issues are never walked for leaves.
    if node.get('unread') and node.get('type') in wf_core.HIERARCHY_CONTAINER_TYPES:
        out.append({'number': node['number'], 'unread': node['unread']})
    for child in node.get('children') or ():
        _tree_unread(child, out)
    return out


def fetch_container_tree(cfg, number):
    """The sub-issue tree under one issue, in one query. (ok, tree, err)."""
    ok, data, err = gh_graphql(
        'query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){'
        ' issue(number:$n){ %s } } }' % _tree_selection(CONTAINER_TREE_DEPTH),
        o=cfg['org'], r=cfg['repo'], n=int(number))
    if not ok or not data:
        return False, None, err or 'the sub-issue query failed'
    node = (data.get('repository') or {}).get('issue')
    if not node:
        return False, None, 'issue #%d not found' % int(number)
    return True, _tree_node(node), ''


def _tree_titles(node, out=None):
    out = {} if out is None else out
    out[node['number']] = node.get('title') or ''
    for child in node.get('children') or ():
        _tree_titles(child, out)
    return out


def fetch_issue_candidate(cfg, number):
    """Fetch one issue as a normalized candidate for the explicit `--issue` path.

    Emits + exits when the issue cannot be worked, and the checks are the pool's
    own rules rather than a shorter list: this path skips selection, so until
    10.1.2 it skipped every eligibility rule with it. `wf pick --issue N` would
    claim an issue owned by a person, assign itself, mark it In Progress and
    hand back work no code agent can finish — and do the same to an issue
    somebody else was already assigned to.

    Refused, in order: not found, already closed, assigned to somebody,
    `Ownership` that is not `Code agent`, and a `Stage` that means the issue is
    not available. Dependencies are not checked here — `claim_validate_walk`
    does that for every path.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['issue', 'view', str(number), '--repo', repo,
                             '--json', 'number,title,labels,body,milestone,url,'
                                       'state,assignees'])
    if not ok or not data:
        emit('error', EXIT_ENV, reason='could not read issue #%d (%s)' % (number, err))
    if (data.get('state') or '').upper() == 'CLOSED':
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='issue #%d is already closed — nothing to pick' % number,
             number=number)

    # The edges and the closing pull requests in one read, first, so an issue
    # already in review is reported by its pull request rather than by the
    # assignee it still carries, and so the claim walk validates without
    # reading either again.
    facts = issue_dependency_facts(cfg, number)
    if facts.get('open_prs'):
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='open pull request %s already closes issue #%d, so a fresh '
                    'build would duplicate it. Review it with /synergy:pr-review.'
                    % (', '.join('#%d' % p for p in facts['open_prs']), number),
             number=number, open_prs=facts['open_prs'])

    assignees = [a.get('login') for a in data.get('assignees') or []]
    if assignees:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='issue #%d is assigned to %s, so it is already somebody\'s. '
                    'Unassign it first if that claim is stale.'
                    % (number, ', '.join(a for a in assignees if a)),
             number=number, assignees=assignees)

    facets = load_issue_facets(cfg, [number])
    ownership = (facets.get('ownership') or {}).get(number)
    scope = wf_core.effective_scope(ownership, (facets.get('types') or {}).get(number))
    if scope != wf_core.SCOPE_CODE:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason='issue #%d is owned by %s, so a code agent must not take it. '
                    'Set `%s` to `%s` if that is wrong.'
                    % (number, ownership or 'nobody — it carries no `%s` value'
                       % field_name(cfg, 'field-ownership'),
                       field_name(cfg, 'field-ownership'),
                       wf_core.OWNERSHIP_FIELD_OPTIONS[wf_core.SCOPE_CODE]),
             number=number, ownership=ownership)

    stage = (facets.get('stage') or {}).get(number)
    if stage and stage not in PICKABLE_BY_NAME:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason="issue #%d has `%s` set to `%s`, so it is not available to "
                    'pick. Set it to `%s` if it should be.'
                    % (number, field_name(cfg, 'field-stage'), stage,
                       wf_core.STAGE_NAMES[wf_core.POOL_STAGE]),
             number=number, stage=stage)
    cand = _norm_issue(data)
    cand.update(facts)
    return cand


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
    finish_pick(args, cfg, selected, side_effects, None,
                unblocks=[{'number': m, 'title': (by_num.get(m) or {}).get('title', '')}
                          for m in entry['unblocks']],
                prerequisite_for={'number': number, 'title': cand['title'],
                                  'build_order': order})


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
                prerequisite_pick(args, cfg, cand, waiting_on)
        selected, side_effects = claim_validate_walk(cfg, [cand], None, siblings,
                                                     start_date=args.checkout)
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

    emit('ok', EXIT_OK, **result)


def _mode_maps(cfg, mode, facets):
    """The (type_map, classification_map) `select_pool` reads for `mode`."""
    if mode == 'story':
        # Read only to leave epics out, as `pick` does.
        return facets['types'] or None, None
    if cfg.get('type_capable'):
        types = facets['types'] or None
        return types, (facets['classification'] if types else None)
    return None, None


def cmd_candidates(args):
    """List the pick pool in priority order, claiming nothing.

    `pick` collapses select-claim-branch into one call, which is exactly right
    when the caller wants *a* story. `bulk-execute` needs the opposite: it has
    to see the pool before it can decide which two to seven stories belong in
    one pull request, and that decision is a judgement about relatedness that
    no sort order can make. This command gives it the same filtered, sorted
    pool `pick` would walk — blank or Backlog `Stage`, sprint narrowing,
    ownership filter, mode filter, any effort ceiling, and
    the priority-then-effort sort — and then stops. Nothing is claimed, nothing
    is labelled, nothing is written. The caller picks its set and claims each
    member with `pick --issue`.

    Bodies are truncated to `--body-chars` (0 for the whole body). The relevant
    part for judging relatedness is the opening Context/Requirements, and a
    full pool of untruncated bodies is a large read for a decision that does
    not need it.
    """
    env_err = check_environment()
    if env_err:
        emit('error', EXIT_ENV, reason=env_err)

    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    if not cfg.get('org') or not cfg.get('repo'):
        emit('error', EXIT_ENV, reason='org/repo missing from config')
    if getattr(args, 'parent', None):
        candidates_under_parent(args, cfg)

    ok, issues, err, claimed = read_pool(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)

    facets = load_issue_facets(cfg, _prefilter_numbers(issues, claimed),
                               issues=issues)
    priority_map = facets['priority']
    type_map, classification_map = _mode_maps(cfg, args.mode, facets)
    backlog_mode, verdict = pool_verdict(cfg, args, issues, claimed, facets,
                                         type_map, classification_map)
    pool = verdict['pool']
    by_num = {i['number']: i for i in issues}
    maps = {'priority': priority_map, 'effort': facets['effort'],
            'ownership': facets['ownership']}

    # Issues that would be offered but for one thing a person has to fix, and
    # the ones an open blocker holds. Neither is a candidate; both are listed
    # so a short pool reads as a decision rather than as a gap.
    needs_refinement = [{'number': e['number'], 'title': e['title'],
                         'type': e.get('type'), 'reason': e['unclear']}
                        for e in verdict['ranked'] if e.get('unclear')]
    blocked = [{'number': n, 'title': (by_num.get(n) or {}).get('title', ''),
                'dependencies_open': deps}
               for n, deps in sorted(verdict['blocked'].items())]
    unclassified = sorted(set(verdict.get('unclassified') or ()))
    if not pool:
        emit('no-candidates', EXIT_NO_CANDIDATES,
             reason='nothing with a blank or %s Stage is available to a code '
                    'agent' % wf_core.STAGE_NAMES[wf_core.POOL_STAGE],
             backlog_mode=backlog_mode,
             oversized=sorted(set(verdict.get('oversized') or ())),
             needs_refinement=needs_refinement, blocked=blocked)

    total = len(pool)
    report_unprioritised(pool, priority_map)
    if args.limit and args.limit > 0:
        pool = pool[:args.limit]

    edge_map, edges_unknown = pool_edges(cfg, [c['number'] for c in pool], by_num)
    listed = []
    for cand in pool:
        item = _candidate_entry(cand, edge_map.get(cand['number']) or [],
                                cand['number'] in edges_unknown, maps,
                                args.body_chars)
        item['type'] = cand.get('type')
        if cand.get('stories') is not None:
            # An Epic or Feature: the stories it offers, as one set. An Epic
            # offers its best Feature's.
            item['stories'] = [{'number': n, 'title': by_num[n].get('title', '')}
                               for n in cand['stories']]
            if cand.get('feature'):
                item['feature'] = cand['feature']
        listed.append(item)

    emit('ok', EXIT_OK, mode=args.mode, backlog_mode=backlog_mode,
         total=total, listed=len(listed), candidates=listed,
         needs_refinement=needs_refinement, blocked=blocked,
         # Issues the org has not typed or classified, and which are therefore
         # not in this pool at all. Reported so a short list reads as a gap in
         # the data rather than as a clean backlog.
         unclassified=sorted(set(unclassified)),
         # Candidates the org has given no Priority. Nothing orders them, so
         # they sit at the back of the listing -- reported as a count so a
         # caller reading a long tail of unranked work knows why.
         unprioritised_count=len([c for c in pool
                                  if not priority_map.get(c['number'])]))


def pool_edges(cfg, numbers, by_num):
    """The blocked-by edges of `numbers`. (found, unknown), as `issue_edges_map`.

    The pool read already holds every issue's edges, so only an issue whose
    read could not see all of them is asked for again.
    """
    found, again = {}, []
    for n in numbers:
        edges = known_edges(by_num.get(n) or {})
        if edges is None:
            again.append(n)
        else:
            found[n] = edges
    unknown = []
    if again:
        more, unknown = issue_edges_map(cfg, again)
        found.update(more)
    return found, unknown


def _candidate_entry(cand, edges, edges_unknown, maps, body_chars):
    """One `candidates` listing entry: the issue, its native edges, and the
    three fields every decision about it is made from."""
    number = cand['number']
    body = cand.get('body') or ''
    truncated = False
    if body_chars and body_chars > 0 and len(body) > body_chars:
        body, truncated = body[:body_chars], True
    open_deps, closed_deps = wf_core.edge_states(edges or [], cand.get('repo'))
    ownership = (maps.get('ownership') or {}).get(number)
    return {
        'number': number,
        'title': cand['title'],
        'url': cand.get('url', ''),
        'labels': cand.get('labels', []),
        'milestone': cand.get('milestone'),
        'body': body,
        'body_truncated': truncated,
        # Straight from the native blocked-by edges: every issue this one
        # waits on, and which of them are still open. A candidate with an
        # open dependency is listed and marked rather than hidden, because
        # this command answers "what is there" and `pick` answers "what can
        # I start".
        'dependencies': sorted(open_deps + closed_deps, key=wf_core.ref_sort_key),
        'dependencies_open': sorted(open_deps, key=wf_core.ref_sort_key),
        'blocked': bool(open_deps),
        # True when the edges could not be read at all, so `blocked` says
        # nothing about this candidate rather than saying "no".
        'dependencies_unknown': bool(edges_unknown),
        'dependency_overflow': len(open_deps) > wf_core.DEP_LIMIT,
        # The three fields every decision about this issue is made from,
        # reported beside the issue so a caller choosing a set can see what
        # the picker saw. `scope` is the `Ownership` value read as one of
        # the three parties, and it is the field's own answer -- it was
        # derived from the title prefix until 10.1.2, which meant this
        # listing could disagree with the filter that produced it.
        'ownership': ownership,
        'scope': wf_core.ownership_scope(ownership),
        'effort': (maps.get('effort') or {}).get(number),
        # The org's own Priority, which is the only thing this listing is
        # ordered by. None means the issue carries no value and sorts last.
        'priority': (maps.get('priority') or {}).get(number),
    }


def candidates_under_parent(args, cfg):
    """`candidates --parent N`: the one bulk set the tree under N offers.

    The same choice `plan-set --parent N` makes, because it is the same call:
    `wf_core.plan_set` over the pool, limited to N's leaves. A leaf waiting on
    another leaf is taken after it; a prerequisite outside the tree is taken
    when a leaf needs it, and says so in `why`. Only related leaves share a
    set. Non-code work is never taken. Every other leaf under N is listed in
    `excluded` with its reason, so a short set reads as a decision rather than
    as a gap.
    """
    ok, tree, err = fetch_container_tree(cfg, args.parent)
    if not ok:
        emit('error', EXIT_ENV, reason='could not read the sub-issues of #%d (%s)'
                                       % (args.parent, err))
    parent = {'number': tree['number'], 'title': tree['title'], 'type': tree['type']}
    if tree['type'] not in wf_core.HIERARCHY_CONTAINER_TYPES:
        emit('usage', EXIT_USAGE, parent=parent,
             reason='#%d is %s, not an Epic or Feature, so it has no stories to '
                    'choose from. Name its parent, or name the stories directly.'
                    % (args.parent, ('a %s' % tree['type']) if tree['type']
                       else 'untyped'))

    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    groups, empty, foreign = wf_core.parent_leaf_groups(tree, repo)
    leaves = [n for members in groups.values() for n in members]
    group_of = {n: g for g, members in groups.items() for n in members}
    pool = read_plan_pool(cfg, args, extra=leaves)
    by_num, facets, universe = pool['by_num'], pool['facets'], pool['universe']
    plan = wf_core.plan_set(universe, pool['rank'], max_size=args.size,
                            reasons=pool['reasons'], within=set(leaves))
    chosen = [s['number'] for s in plan['selected']]

    titles = _tree_titles(tree)
    known = set(chosen) | {e['number'] for e in plan['excluded']}
    excluded = list(plan['excluded'])
    for n in leaves:
        if n in known:
            continue
        if n in universe:
            reason = 'nothing links it to the stories this run takes'
        else:
            reason = (pool['reasons'].get(n)
                      or 'not open, or not an issue a code agent may take')
        excluded.append({'number': n, 'reason': reason})
    excluded += [{'number': n, 'reason': 'a Feature with no open stories yet'}
                 for n in empty]
    excluded += [{'number': n, 'reason': 'in another repository'} for n in foreign]
    excluded = [dict(e, title=titles.get(e['number'])
                     or (by_num.get(e['number']) or {}).get('title', ''))
                for e in excluded]

    maps = {'priority': facets['priority'], 'effort': facets['effort'],
            'ownership': facets['ownership']}
    edge_map, edges_unknown = pool_edges(cfg, chosen, by_num)
    listed = []
    for story in plan['selected']:
        n = story['number']
        entry = _candidate_entry(by_num[n], edge_map.get(n) or [],
                                 n in edges_unknown, maps, args.body_chars)
        entry.update(stage=by_num[n].get('stage'), wave=story['wave'],
                     blocked_by=story['blocked_by'], unblocks=story['unblocks'],
                     why=story['why'])
        listed.append(entry)

    unread = _tree_unread(tree)
    note = ''
    if unread:
        note = ('; %s had more sub-issues than one read returns, so %d were not '
                'read and are in neither list'
                % (', '.join('#%d' % u['number'] for u in unread),
                   sum(u['unread'] for u in unread)))
    if not listed:
        emit('no-candidates', EXIT_NO_CANDIDATES, parent=parent, excluded=excluded,
             unread=unread,
             reason='nothing under #%d is available to a code agent%s'
                    % (args.parent, note))
    # The Feature the set came from, when every leaf in it shares one.
    features = {group_of[n] for n in chosen if n in group_of}
    emit('ok', EXIT_OK, mode=args.mode, parent=parent,
         feature=features.pop() if len(features) == 1 else None,
         total=len(listed), listed=len(listed), candidates=listed,
         lead=plan['lead'], waves=plan['waves'],
         excluded=excluded, unread=unread,
         reason='%d stor%s under #%d%s' % (len(listed), 'y' if len(listed) == 1
                                           else 'ies', args.parent, note))
