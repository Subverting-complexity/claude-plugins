"""
Picking, the listing: the `candidates` command, which shows the pool `pick`
would walk, or the one set the tree under `--parent` offers, and claims
nothing.

Split out of `wf_pick.py`; `scripts/README.md` has the module map.
"""

import wf_core
from wf_candidates import (
    _prefilter_numbers, load_issue_facets, pool_verdict, read_pool,
    report_unprioritised,
)
from wf_config import check_environment, load_config
from wf_deps import issue_edges_map, known_edges
from wf_io import EXIT_ENV, EXIT_NO_CANDIDATES, EXIT_OK, EXIT_USAGE, emit
from wf_pick_select import _mode_maps, read_plan_pool
from wf_pick_tree import _tree_titles, _tree_unread, fetch_container_tree


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
