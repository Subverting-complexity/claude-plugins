"""
Bulk sets: `plan-set` chooses a dependency-ordered set of stories and, with
`--claim`, claims it; `drop-story` returns a story, and whatever waits on it,
to the pool; `bulk-mark` records the branch and each story as it is built.

The choice is `wf_core.plan_set`. What used to be a judgement read off a
listing -- which stories are related, which depends on which, what order to
build them in -- is decided here from the blocked-by edges and the issue tree,
so a story is never left out because it waits on another story in the set.
`scripts/README.md` has the module map.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

import wf_core
from wf_claim import acquire_claim, release_claims
from wf_config import prepare_cfg, repo_root
from wf_deps import close_resolved, validate_issue
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_ENV, EXIT_NO_CANDIDATES, EXIT_OK, EXIT_USAGE, emit,
    gh_graphql, run,
)
from wf_issue_io import _batch_result, _graphql_json
from wf_pick import (
    PICKABLE_BY_NAME, _tree_unread, fetch_container_tree, read_plan_pool,
)
from wf_stage import set_stages, start_date_input


BULK_SET = os.path.join('.claude', 'bulk-set.json')

# Unchosen stories reported beside a plan, so the caller can see what else is
# ready without a second listing. Five is enough to judge a shared surface.
NEARBY = 5
NEARBY_BODY_CHARS = 300


def _admit_named(pool, seeds):
    """Put each named story the pool left out into the universe when naming it
    overrules why it was left out, as `pick --issue` does: a `Stage` of
    Needs refinement, Parked or Blocked, a mode or effort filter. Somebody
    else's issue, a claimed one, one an open pull request already closes and
    work a code agent may not do stay out, with the reason."""
    universe, reasons, by_num = pool['universe'], pool['reasons'], pool['by_num']
    facets = pool['facets']
    for number in seeds:
        issue = by_num.get(number)
        if number in universe or issue is None:
            continue
        stage = wf_core.stage_name(issue.get('stage'))
        scope = wf_core.effective_scope((facets.get('ownership') or {}).get(number),
                                        (facets.get('types') or {}).get(number)
                                        or issue.get('type'))
        if issue.get('assigned'):
            reasons[number] = 'assigned to %s' % (', '.join(issue.get('assignees') or ())
                                                  or 'somebody')
        elif number in pool['claimed']:
            reasons[number] = 'claimed by another run'
        elif issue.get('open_prs'):
            reasons[number] = 'open pull request %s already closes it' % ', '.join(
                '#%d' % p for p in issue['open_prs'])
        elif issue.get('type') in wf_core.HIERARCHY_CONTAINER_TYPES:
            reasons[number] = ('it is %s %s; name its stories, or pass --parent %d'
                               % ('an' if issue['type'] == 'Epic' else 'a',
                                  issue['type'], number))
        elif scope != wf_core.SCOPE_CODE:
            reasons[number] = 'owned by %s, not the code agent' % (
                (facets.get('ownership') or {}).get(number) or 'nobody')
        elif stage and stage not in PICKABLE_BY_NAME:
            reasons[number] = 'its Stage is %s' % stage
        else:
            universe[number] = {'blockers': wf_core._open_blockers(issue),
                                'parent': issue.get('parent')}
            reasons.pop(number, None)


def _story_entry(story, issue, facets, body_chars):
    body = issue.get('body') or ''
    truncated = bool(body_chars and body_chars > 0 and len(body) > body_chars)
    number = story['number']
    return {'number': number, 'title': issue.get('title', ''),
            'url': issue.get('url', ''), 'stage': issue.get('stage'),
            'type': issue.get('type'),
            'priority': (facets.get('priority') or {}).get(number),
            'effort': (facets.get('effort') or {}).get(number),
            'wave': story['wave'], 'blocked_by': story['blocked_by'],
            'unblocks': story['unblocks'], 'why': story['why'],
            'body': body[:body_chars] if truncated else body,
            'body_truncated': truncated}


def _nearby(pool, plan, within):
    """The highest-ranked stories this run could also build that the plan
    did not take, because nothing links them to it."""
    chosen = {s['number'] for s in plan['selected']}
    left = {e['number'] for e in plan['excluded']}
    out = []
    for number in pool['rank']:
        if number in chosen or number in left or (within is not None
                                                  and number not in within):
            continue
        issue = pool['by_num'].get(number) or {}
        out.append({'number': number, 'title': issue.get('title', ''),
                    'priority': (pool['facets'].get('priority') or {}).get(number),
                    'ready': not pool['universe'][number].get('blockers'),
                    'body': (issue.get('body') or '')[:NEARBY_BODY_CHARS]})
        if len(out) >= NEARBY:
            break
    return out


def cmd_plan_set(args):
    """`wf plan-set`: the set, its build order and its waves, and with
    `--claim` every story in it claimed, assigned and In Progress."""
    cfg = prepare_cfg()
    seeds = [int(n) for n in (args.issue or ())]
    if seeds and args.parent:
        emit('usage', EXIT_USAGE,
             reason='name stories or pass --parent, not both')
    size, clamped = args.size, None
    if not wf_core.BULK_MIN <= size <= wf_core.BULK_MAX:
        clamped = size
        size = min(max(size, wf_core.BULK_MIN), wf_core.BULK_MAX)

    pool = read_plan_pool(cfg, args, extra=seeds)
    within, parent, unread = None, None, []
    if args.parent:
        ok, tree, err = fetch_container_tree(cfg, args.parent)
        if not ok:
            emit('error', EXIT_ENV, reason='could not read the sub-issues of #%d (%s)'
                                           % (args.parent, err))
        parent = {'number': tree['number'], 'title': tree['title'],
                  'type': tree['type']}
        if tree['type'] not in wf_core.HIERARCHY_CONTAINER_TYPES:
            emit('usage', EXIT_USAGE, parent=parent,
                 reason='#%d is not an Epic or Feature, so it has no stories to '
                        'choose from. Name the stories instead.' % args.parent)
        groups, _, _ = wf_core.parent_leaf_groups(
            tree, '%s/%s' % (cfg['org'], cfg['repo']))
        within = {n for members in groups.values() for n in members}
        unread = _tree_unread(tree)
    if seeds:
        _admit_named(pool, seeds)

    plan = wf_core.plan_set(pool['universe'], pool['rank'], seeds=seeds or None,
                            max_size=size, reasons=pool['reasons'], within=within)
    by_num = pool['by_num']
    excluded = list(plan['excluded'])
    if within is not None:
        known = {e['number'] for e in excluded} | {s['number'] for s in plan['selected']}
        excluded += [{'number': n, 'reason': pool['reasons'].get(n)
                      or 'not an issue a code agent may take'}
                     for n in sorted(within)
                     if n not in known and n not in pool['universe']]
    for entry in excluded:
        entry['title'] = (by_num.get(entry['number']) or {}).get('title', '')
    common = {'mode': args.mode, 'size': size, 'size_clamped': clamped,
              'parent': parent, 'unread': unread, 'excluded': excluded,
              'nearby': [] if seeds else _nearby(pool, plan, within)}

    if not plan['selected']:
        emit('no-candidates', EXIT_NO_CANDIDATES, **common,
             reason=('none of the named stories can be built by this run'
                     if seeds else 'no story a code agent may take is available'))
    stories = [_story_entry(s, by_num.get(s['number']) or {}, pool['facets'],
                            args.body_chars) for s in plan['selected']]
    if not args.claim:
        emit('ok', EXIT_OK, claimed=False, lead=plan['lead'], stories=stories,
             waves=plan['waves'], unrelated=plan['unrelated'],
             components=plan['components'], **common,
             reason='%d stor%s in %d wave%s' % (
                 len(stories), 'y' if len(stories) == 1 else 'ies',
                 len(plan['waves']), '' if len(plan['waves']) == 1 else 's'))
    claim_plan(cfg, args, pool, plan, stories, common)


def claim_plan(cfg, args, pool, plan, stories, common):
    """Claim a plan: every claim ref at once, then one assignment mutation and
    one Stage and Start date mutation for the whole set. Emits and exits."""
    by_num = pool['by_num']
    numbers = [s['number'] for s in stories]
    targets = {n: 'issue-%d' % n for n in numbers}
    with ThreadPoolExecutor(max_workers=len(numbers)) as workers:
        outcomes = dict(zip(numbers, workers.map(acquire_claim,
                                                 [targets[n] for n in numbers])))
    won = [n for n in numbers if outcomes[n] == 'won']
    if any(o == 'error' for o in outcomes.values()):
        released = release_claims([targets[n] for n in won])
        emit('error', EXIT_ENV, outcomes=outcomes, released=released,
             reason='could not write a claim ref under refs/claims/: no push '
                    'access or a remote failure, not a lost claim. Every claim '
                    'this run took was released.')

    dropped = {n: 'claimed by another run first'
               for n in numbers if outcomes[n] == 'lost'}
    resolved = {}
    for n in won:
        verdict, detail = validate_issue(cfg, by_num[n], set(numbers))
        if verdict == 'resolved':
            close_resolved(cfg, by_num[n], detail)
            resolved[n] = detail
        elif verdict == 'blocked':
            dropped[n] = 'blocked by %s, outside the set' % detail
        elif verdict != 'valid':
            dropped[n] = detail
    changed = True
    while changed:
        changed = False
        for story in stories:
            n = story['number']
            gone = [b for b in story['blocked_by'] if b in dropped]
            if n not in dropped and n not in resolved and gone:
                dropped[n] = 'waits on #%d, which left the set' % gone[0]
                changed = True
    release_claims([targets[n] for n in list(dropped) + list(resolved)
                    if outcomes[n] == 'won'])
    kept = [dict(s, blocked_by=[b for b in s['blocked_by'] if b not in resolved])
            for s in stories if s['number'] not in dropped and s['number'] not in resolved]
    dropped_list = ([{'number': n, 'reason': r} for n, r in dropped.items()]
                    + [{'number': n, 'reason': 'already resolved by #%s, closed' % pr}
                       for n, pr in resolved.items()])
    if not kept:
        emit('all-blocked', EXIT_ALL_BLOCKED, dropped=dropped_list, **common,
             reason='every story in the plan was claimed away, blocked or '
                    'already resolved')

    waves = wf_core.dependency_waves(kept)
    wave_of = {n: i for i, wave in enumerate(waves) for n in wave}
    kept_numbers = [s['number'] for s in kept]
    ids = {n: by_num[n].get('id') for n in kept_numbers}
    assigned = assign_many(ids)
    value, date_msg = start_date_input(cfg)
    extra = {n: [value] for n in kept_numbers} if value is not None else None
    stage = wf_core.STAGE_NAMES['stage-in-progress']
    results = set_stages(cfg, {n: stage for n in kept_numbers}, ids, extra)
    failed = [n for n in kept_numbers if not results[n][0]]
    if failed and extra:
        results.update(set_stages(cfg, {n: stage for n in failed}, ids))
    for story in kept:
        n = story['number']
        story['wave'] = wave_of[n]
        story['unblocks'] = [m for m in story['unblocks'] if m in wave_of]
        story['stage_set'], story['stage_message'] = results[n]
        story['assigned'] = assigned[n][0]
        story['start_date_set'] = bool(extra) and n not in failed

    record = {'lead': kept_numbers[0], 'mode': args.mode, 'parent': args.parent,
              'branch': None, 'waves': waves,
              'stories': [{'number': s['number'], 'title': s['title'],
                           'wave': s['wave'], 'blocked_by': s['blocked_by'],
                           'built': False} for s in kept],
              'dropped': dropped_list}
    _write_set(record)
    emit('ok', EXIT_OK, claimed=True, lead=record['lead'], stories=kept,
         waves=waves, dropped=dropped_list, bulk_set=BULK_SET.replace(os.sep, '/'),
         start_date_message=None if extra else date_msg, **common,
         reason='claimed %d stor%s in %d wave%s' % (
             len(kept), 'y' if len(kept) == 1 else 'ies', len(waves),
             '' if len(waves) == 1 else 's'))


def assign_many(ids):
    """Assign the signed-in account to many issues in one mutation.

    `ids` is {number: node id}. Returns {number: (assigned, message)}. Two
    requests whatever the size of the set, where `gh issue edit` was one each.
    """
    ok, data, err = gh_graphql('query{ viewer { id } }')
    viewer = ((data or {}).get('viewer') or {}).get('id') if ok else None
    if not viewer:
        return {n: (False, 'could not read the signed-in account (%s)'
                    % (err or 'no detail')) for n in ids}
    out = {n: (False, 'could not read the issue node id') for n, i in ids.items() if not i}
    live = sorted(n for n, i in ids.items() if i)
    if not live:
        return out
    decls, body, variables = ['$u:ID!'], [], {'u': viewer}
    for n in live:
        decls.append('$a%d:ID!' % n)
        body.append('a%d: addAssigneesToAssignable(input:{assignableId:$a%d,'
                    'assigneeIds:[$u]}){ assignable { ... on Issue { id } } }' % (n, n))
        variables['a%d' % n] = ids[n]
    code, raw, merr = _graphql_json('mutation(%s){ %s }' % (','.join(decls),
                                                             ' '.join(body)),
                                    variables)
    results = _batch_result(code, raw, merr, ['a%d' % n for n in live],
                            field='assignable')
    for n in live:
        done, _node, why = results['a%d' % n]
        out[n] = (True, 'assigned') if done else (False, why)
    return out


def _set_path():
    return os.path.join(repo_root(), BULK_SET)


def _write_set(record):
    path = _set_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(record, fh, indent=2)
        fh.write('\n')


def _load_set():
    try:
        with open(_set_path(), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        emit('usage', EXIT_USAGE,
             reason='no bulk set is recorded at %s (%s); run plan-set --claim first'
                    % (BULK_SET.replace(os.sep, '/'), exc))


def cmd_drop_story(args):
    """`wf drop-story`: return an unbuilt story to the pool, and every unbuilt
    story that waits on it, since its blocker is no longer being built."""
    cfg = prepare_cfg()
    record = _load_set()
    stories = {s['number']: s for s in record.get('stories') or ()}
    number = args.issue
    if number not in stories:
        emit('usage', EXIT_USAGE, reason='#%d is not in the bulk set' % number)
    if stories[number].get('built'):
        emit('usage', EXIT_USAGE,
             reason='#%d is already built on the branch. Finish it, or reset its '
                    'commits off the branch, before dropping it.' % number)
    drop = {number: args.reason}
    changed = True
    while changed:
        changed = False
        for n, story in stories.items():
            waits = [b for b in story.get('blocked_by') or () if b in drop]
            if n not in drop and waits:
                if story.get('built'):
                    emit('usage', EXIT_USAGE,
                         reason='#%d is built and waits on #%d, so #%d cannot be '
                                'dropped without resetting #%d too' % (n, waits[0],
                                                                        number, n))
                drop[n] = 'waits on #%d, which was dropped' % waits[0]
                changed = True

    released = release_claims(['issue-%d' % n for n in drop])
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    for n, reason in drop.items():
        run(['gh', 'issue', 'edit', str(n), '--repo', repo, '--remove-assignee', '@me'])
        run(['gh', 'issue', 'comment', str(n), '--repo', repo, '--body',
             'Claimed for a bulk run and returned unbuilt: %s.' % reason])
    # A story still waiting on an open issue goes back as Blocked, so the
    # sweep releases it; one waiting on nothing goes back to the pool.
    stages = set_stages(cfg, {
        n: wf_core.STAGE_NAMES['stage-blocked' if stories[n].get('blocked_by')
                               else 'stage-backlog'] for n in drop})

    remaining = [s for s in record.get('stories') or () if s['number'] not in drop]
    waves = wf_core.dependency_waves(remaining)
    for i, wave in enumerate(waves):
        for n in wave:
            next(s for s in remaining if s['number'] == n)['wave'] = i
    record.update(stories=remaining, waves=waves,
                  lead=remaining[0]['number'] if remaining else None,
                  dropped=(record.get('dropped') or [])
                  + [{'number': n, 'reason': r} for n, r in drop.items()])
    _write_set(record)
    emit('ok', EXIT_OK, remaining=[s['number'] for s in remaining], waves=waves,
         dropped=[{'number': n, 'reason': r,
                   'claim_released': released.get('issue-%d' % n, False),
                   'stage_set': stages[n][0],
                   'stage_message': None if stages[n][0] else stages[n][1]}
                  for n, r in drop.items()],
         reason='dropped %s' % ', '.join('#%d' % n for n in drop))


def cmd_bulk_mark(args):
    """`wf bulk-mark`: record the shared branch, and each story once built."""
    record = _load_set()
    if args.branch:
        record['branch'] = args.branch
    by_number = {s['number']: s for s in record.get('stories') or ()}
    for n in args.built or ():
        if n not in by_number:
            emit('usage', EXIT_USAGE, reason='#%d is not in the bulk set' % n)
        by_number[n]['built'] = True
    _write_set(record)
    emit('ok', EXIT_OK, branch=record.get('branch'),
         built=[s['number'] for s in record.get('stories') or () if s.get('built')],
         unbuilt=[s['number'] for s in record.get('stories') or () if not s.get('built')],
         waves=record.get('waves'))
