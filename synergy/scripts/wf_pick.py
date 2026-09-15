"""
Picking: the claim and validate walk, container trees, and the `pick` and
`candidates` subcommands.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import wf_core
from wf_candidates import (
    _norm_issue, _prefilter_numbers, assemble_candidates,
    claimed_issue_numbers, load_issue_facets, pool_verdict,
    report_unprioritised,
)
from wf_claim import (
    acquire_claim, apply_in_progress, release_claim, revert_in_progress,
)
from wf_config import check_environment, field_name, load_config
from wf_deps import (
    close_resolved, issue_edges_map, mark_blocked, validate_issue,
)
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_CAPABILITY, EXIT_ENV, EXIT_NEEDS_REFINEMENT,
    EXIT_NO_CANDIDATES, EXIT_OK, EXIT_USAGE, emit, eprint, gh_graphql, gh_json,
    run,
)
from wf_stage import (
    best_effort, checkout_branch, set_stage, set_stages, set_start_date,
    stage_in_progress,
)
from wf_unblock import auto_unblock_scan, blocked_issues


def claim_validate_walk(cfg, pool, backlog_mode, siblings=()):
    """Walk the ordered pool: claim the top, validate only that one, act.

    The single claim-first/validate-lazily loop shared by auto-pick and the
    explicit `--issue` path. For each candidate it acquires the atomic claim,
    applies the in-progress marker, then validates: a dependency-blocked issue
    is set to Blocked, an already-resolved one is closed **and set to Done**,
    and the claim is released in both cases before walking on.
    The first valid claim is returned as the selection.

    `siblings` is passed straight to `validate_issue` — the other stories of a
    bulk set, whose still-open state does not block a candidate that is being
    built alongside them.

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
        apply_in_progress(cfg, cand)
        verdict, detail = validate_issue(cfg, cand, siblings)
        if verdict == 'unknown':
            # Nothing is known about this issue's dependencies, so nothing may
            # be written about them. The claim and the In Progress write are
            # undone and the run stops: retrying the next candidate would
            # almost certainly hit the same failure, one issue at a time.
            restored, message = revert_in_progress(cfg, cand['number'])
            released = release_claim(target)
            side_effects.append({'issue': cand['number'],
                                 'action': 'released-unverified',
                                 'detail': detail, 'restored': restored,
                                 'stage_message': None if restored else message,
                                 'claim_released': released})
            emit('error', EXIT_ENV,
                 reason='could not read the blocked-by edges of #%d, so whether '
                        'it is blocked is unknown and nothing was decided from '
                        'it. The claim and the In Progress write were undone. '
                        'Check the token and the network, then re-run.'
                        % cand['number'],
                 backlog_mode=backlog_mode, side_effects=side_effects)
        if verdict == 'blocked':
            written, message = mark_blocked(cfg, cand, detail)
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
        return cand, side_effects
    return None, side_effects


# Stages an explicitly named issue may be picked from, beside a blank one.
# Backlog is the pool;
# Blocked is here because the edge check runs anyway and an issue whose
# blockers have all closed is workable; Needs refinement and Parked are here
# because naming the issue is the person overruling the hold they put on it. In
# Progress and In Review are somebody else's work, Non-code is work a code
# agent cannot do, and Done is finished.
PICKABLE_BY_NAME = frozenset({'Backlog', 'Blocked', 'Needs refinement', 'Parked'})


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
    return _norm_issue(data)


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
        selected, side_effects = claim_validate_walk(cfg, [cand], None, siblings)
        if not selected:
            emit('all-blocked', EXIT_ALL_BLOCKED,
                 reason='issue #%d is not workable (claimed away, blocked, or '
                        'already resolved by a merged PR)' % args.issue,
                 side_effects=side_effects)
        finish_pick(args, cfg, selected, side_effects, backlog_mode=None)

    side_effects = []
    outcome = _pick_round(cfg, args, siblings, side_effects)
    if not outcome['selected']:
        restored = auto_unblock_scan(cfg)
        if restored:
            eprint('wf: unblock sweep released %d issue(s) — retrying' % restored)
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
                container=outcome['container'], offered=outcome['offered'])


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


def block_in_pool(cfg, blocked, side_effects):
    """Set every issue rule 4 caught to Blocked, in one batched write.

    No comment and no unassign: these were never claimed, and the blocked-by
    edge already says why. The unblock sweep releases each one when its last
    blocker closes.
    """
    if not blocked:
        return
    results = set_stages(cfg, {n: wf_core.STAGE_NAMES['stage-blocked']
                               for n in blocked})
    for number in sorted(blocked):
        written, message = results.get(number, (False, 'not written'))
        side_effects.append({'issue': number, 'action': 'marked-blocked',
                             'detail': ', '.join('#%d' % b for b in blocked[number]),
                             'stage_set': written,
                             'stage_message': None if written else message})


def _pick_round(cfg, args, siblings, side_effects):
    """Read the pool, judge it, and walk it once. Emits and exits on a hard
    stop; otherwise returns what it chose and what it read."""
    ok, issues, err = assemble_candidates(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)
    claimed = claimed_issue_numbers()

    # The org's own view of the issues still in the running: native type,
    # Priority, Effort, Ownership, Classification. All five decide the pool.
    facets = load_issue_facets(cfg, _prefilter_numbers(issues, claimed))
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
    block_in_pool(cfg, verdict['blocked'], side_effects)
    by_num = {i['number']: i for i in issues}
    outcome = {'verdict': verdict, 'backlog_mode': backlog_mode,
               'priority': facets['priority'], 'selected': None,
               'container': None, 'offered': []}

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
        selected, effects = claim_validate_walk(cfg, walk, backlog_mode, siblings)
        side_effects.extend(effects)
        if not selected:
            continue
        outcome['selected'] = selected
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
                offered=()):
    """Build the `ok` result for a selected story, optionally checking out, and emit.

    `container` and `offered` are set when the pick came through an Epic or
    Feature: the story claimed is the first of the stories it offers, and
    `offered` is the rest, which the caller may build alongside it.
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

    if args.checkout:
        written, stage_msg = best_effort(stage_in_progress, cfg,
                                         selected['number'])
        result['stage_set'] = written
        result['stage_message'] = stage_msg
        if not written:
            eprint('wf: Stage not set — %s' % stage_msg)
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
    to see the pool before it can decide which two to five stories belong in
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

    ok, issues, err = assemble_candidates(cfg)
    if not ok:
        emit('error', EXIT_ENV, reason='candidate fetch failed: %s' % err)
    claimed = claimed_issue_numbers()

    facets = load_issue_facets(cfg, _prefilter_numbers(issues, claimed))
    priority_map = facets['priority']
    type_map, classification_map = _mode_maps(cfg, args.mode, facets)
    backlog_mode, verdict = pool_verdict(cfg, args, issues, claimed, facets,
                                         type_map, classification_map)
    pool = verdict['pool']
    by_num = {i['number']: i for i in issues}
    maps = {'priority': priority_map, 'effort': facets['effort'],
            'ownership': facets['ownership']}
    if getattr(args, 'parent', None):
        # Before the empty-pool exit: a parent whose leaves are all out of the
        # pool still owes the caller the list of why.
        candidates_under_parent(args, cfg, pool, maps, verdict, by_num)

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

    edge_map, edges_unknown = issue_edges_map(cfg, [c['number'] for c in pool])
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


def _candidate_entry(cand, edges, edges_unknown, maps, body_chars):
    """One `candidates` listing entry: the issue, its native edges, and the
    three fields every decision about it is made from."""
    number = cand['number']
    body = cand.get('body') or ''
    truncated = False
    if body_chars and body_chars > 0 and len(body) > body_chars:
        body, truncated = body[:body_chars], True
    open_deps, closed_deps = wf_core.edge_states(edges or [])
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
        'dependencies': sorted(open_deps + closed_deps),
        'dependencies_open': sorted(open_deps),
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


def candidates_under_parent(args, cfg, pool, maps, verdict=None, by_num=None):
    """`candidates --parent N`: the one bulk set the tree under N offers.

    The pool is the same pool as ever, narrowed to N's leaves, plus the one
    exception #239 settled: a leaf whose `Stage` is Blocked and whose every open
    blocker is another leaf taken in the same run. Non-code work is never
    taken, because it is neither in the pool nor owned by the code agent.
    Every other leaf under N is listed in `excluded` with its reason, so a
    short set reads as a decision rather than as a gap. The choice itself is
    `wf_core.choose_parent_set`; this is the reading around it.
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
    groups, _, _ = wf_core.parent_leaf_groups(tree, repo)
    leaves = [n for members in groups.values() for n in members]
    wanted = set(leaves)
    pool = [c for c in pool if c['number'] in wanted]
    pool_by = {c['number']: c for c in pool}
    outside = [n for n in leaves if n not in pool_by]

    # The fields and the Blocked issues are read only for leaves the pool did
    # not already answer for.
    out_maps = {'priority': {}, 'effort': {}, 'ownership': {}}
    out_stages, out_types = {}, {}
    blocked, refused = {}, {}
    if outside:
        facets = load_issue_facets(cfg, outside)
        out_maps = {k: facets.get(k) or {} for k in out_maps}
        out_stages = facets.get('stage') or {}
        out_types = facets.get('types') or {}
        blocked_now, berr = blocked_issues(cfg)
        if berr:
            emit('error', EXIT_ENV,
                 reason='could not read the issues whose Stage is %s (%s), so '
                        'which leaves wait only on each other is unknown'
                        % (wf_core.STAGE_NAMES['stage-blocked'], berr))
        # The same filter the pool went through -- ownership, `--mode`, any
        # effort ceiling -- so the one exception #239 made is about the
        # stage and nothing else. A Blocked story does not join a bug's set.
        cards = [i for i in blocked_now
                 if i['number'] in wanted and i['number'] not in pool_by
                 and not i.get('assigned')]
        # A Backlog leaf the pool held back for an open edge waits exactly as
        # a Blocked one does, so it gets the same exception.
        seen = {i['number'] for i in cards}
        cards += [(by_num or {})[n] for n in sorted((verdict or {}).get('blocked') or ())
                  if n in wanted and n not in pool_by and n not in seen
                  and n in (by_num or {})]
        types, classes = _mode_maps(cfg, args.mode, facets)
        untyped, heavy = [], []
        blocked = {i['number']: i for i in wf_core.select_pool(
            cards, mode=args.mode, project_map=cfg.get('labels', {}),
            type_map=types, classification_map=classes, unclassified=untyped,
            priority_map=out_maps['priority'], effort_map=out_maps['effort'],
            ownership_map=out_maps['ownership'],
            max_effort=getattr(args, 'max_effort', None), oversized=heavy)}
        # Why the filter refused a code-owned Blocked leaf. Being Blocked is
        # what #239 lets a leaf through with, so it is never the reason.
        for card in cards:
            n = card['number']
            if n in blocked or (wf_core.effective_scope(out_maps['ownership'].get(n),
                                                        out_types.get(n))
                                != wf_core.SCOPE_CODE):
                continue
            if n in heavy:
                refused[n] = 'over the `--max-effort` ceiling'
            elif n in untyped:
                refused[n] = 'untyped, so `--mode %s` cannot place it' % args.mode
            else:
                refused[n] = 'left out by `--mode %s`' % args.mode
        # Only a leaf waiting on another issue. Most Blocked issues wait on a
        # person or a decision and carry no edge, and building siblings frees
        # none of those; with no open blocker one would even lead the run.
        for n in list(blocked):
            nodes = ((blocked[n].get('blockedBy') or {}).get('nodes')) or []
            if not wf_core.edge_states(nodes)[0]:
                refused[n] = ('`%s` with no open blocker, so it waits on '
                              'something other than an issue'
                              % wf_core.STAGE_NAMES['stage-blocked'])
                del blocked[n]

    edge_map, edges_unknown = issue_edges_map(cfg, list(pool_by))
    blocked_edges = {n: ((i.get('blockedBy') or {}).get('nodes')) or []
                     for n, i in blocked.items()}
    deps = {}
    for n in leaves:
        if n in pool_by:
            deps[n] = wf_core.edge_states(edge_map.get(n) or [])[0]
        elif n in blocked:
            deps[n] = wf_core.edge_states(blocked_edges[n])[0]

    reasons = {}
    rest = [n for n in outside if n not in blocked]
    if rest:
        for n in rest:
            if n in refused:
                reasons[n] = refused[n]
                continue
            stage = out_stages.get(n)
            owner = out_maps['ownership'].get(n)
            why = []
            if not wf_core.is_available_stage(stage):
                why.append('`%s` is `%s`' % (field_name(cfg, 'field-stage'), stage))
            if wf_core.effective_scope(owner, out_types.get(n)) != wf_core.SCOPE_CODE:
                why.append('owned by %s, not the code agent' % (owner or 'nobody'))
            reasons[n] = (', '.join(why)
                          or ((verdict or {}).get('excluded') or {}).get(n)
                          or 'not in the pool (assigned, or left out by --mode)')

    # The Blocked leaves ranked in among the pool by the pool's own sort, or
    # the build order would put every one of them behind every pool leaf.
    ranked = wf_core._sort_candidates(
        pool + list(blocked.values()), cfg.get('labels', {}),
        {**(maps.get('priority') or {}), **out_maps['priority']},
        {**(maps.get('effort') or {}), **out_maps['effort']})
    choice = wf_core.choose_parent_set(tree, [c['number'] for c in ranked], deps,
                                       reasons, max_size=args.size, repo=repo)
    titles = _tree_titles(tree)
    excluded = [dict(e, title=titles.get(e['number'], '')) for e in choice['excluded']]
    listed = []
    for story in choice['selected']:
        n = story['number']
        if n in pool_by:
            entry = _candidate_entry(pool_by[n], edge_map.get(n) or [],
                                     n in edges_unknown, maps, args.body_chars)
            entry['stage'] = pool_by[n].get('stage')
        else:
            entry = _candidate_entry(blocked[n], blocked_edges[n], False,
                                     out_maps, args.body_chars)
            entry['stage'] = blocked[n].get('stage') or wf_core.STAGE_NAMES['stage-blocked']
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
    emit('ok', EXIT_OK, mode=args.mode, parent=parent, feature=choice['group'],
         total=len(listed), listed=len(listed), candidates=listed,
         excluded=excluded, unread=unread,
         reason='%d stor%s under #%d%s' % (len(listed), 'y' if len(listed) == 1
                                           else 'ies', args.parent, note))
