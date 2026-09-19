"""
After a merge: closing finished containers and the `post-merge` subcommand.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import json

import wf_core
from wf_capabilities import gh_graphql_partial
from wf_config import prepare_cfg
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_ENV, EXIT_OK, emit, emit_line, gh_json, run,
)
from wf_issue_io import _batch_result, _graphql_json
from wf_stage import _chunks, release_note_inputs, set_stage, set_stages
from wf_unblock import unblock_scan


# ── closing a finished container (#240) ──────────────────────────────────────

# How far up a merged story's parents the walk reads: story, Feature, Epic,
# and one more for a tree nested deeper than the usual three levels.
CONTAINER_CHAIN_DEPTH = 4

# Issues per aliased read or write in this module. The same twenty the `Stage`
# and edge writers use, for the same reason: GitHub's complexity budget. A
# merge closes one to five issues, so every run fits in one request (#300).
SETTLE_BATCH = 20

CONTAINER_CLOSE_COMMENT = (
    'Closing as completed: every sub-issue is closed, and #%d was the last to '
    'close. Reopen this if more work is planned under it.')
CONTAINER_SWEEP_COMMENT = (
    'Closing as completed: every sub-issue is closed. Found by `wf preflight '
    '--fix`; reopen this if more work is planned under it.')
SETTLE_COMMENT = 'Closing — resolved by merged PR #%d.'

_CONTAINER_NODE = ('number title state issueType { name }'
                   ' repository { nameWithOwner }'
                   ' subIssues(first:100){ nodes { number state } }')


def _container_node(node):
    return {'number': node['number'], 'title': node.get('title') or '',
            'state': node.get('state') or '',
            'type': (node.get('issueType') or {}).get('name'),
            'repo': (node.get('repository') or {}).get('nameWithOwner'),
            'children': [{'number': c.get('number'), 'state': c.get('state')}
                         for c in (node.get('subIssues') or {}).get('nodes') or []]}


def _chain_selection(depth):
    if depth <= 1:
        return _CONTAINER_NODE
    return _CONTAINER_NODE + ' parent { %s }' % _chain_selection(depth - 1)


def _alias_errors(errors, aliases):
    """Split a GraphQL error list by the alias each error's path names.

    Returns ({alias: message}, general), where `general` joins the errors
    that name no alias. An aliased read answers a partial failure with the
    aliases that worked and an error for each that did not, so one unreadable
    issue is reported against that issue instead of failing the batch.
    """
    wanted, per, general = set(aliases), {}, []
    for entry in errors or []:
        message = entry.get('message') or 'the query failed'
        hit = next((p for p in entry.get('path') or [] if p in wanted), None)
        if hit:
            per.setdefault(hit, message)
        else:
            general.append(message)
    return per, '; '.join(general)


def _aliased_repository_read(cfg, numbers, prefix, selection):
    """Read `selection` for many issues, one aliased request per batch.

    Yields (number, ok, node, err) for each number, in order. `node` is the
    aliased issue (None when GitHub has no such issue and said nothing).
    """
    for chunk in _chunks(list(numbers), SETTLE_BATCH):
        aliases = ['%s%d' % (prefix, n) for n in chunk]
        parts = ' '.join('%s: issue(number:%d){ %s }' % (a, n, selection)
                         for a, n in zip(aliases, chunk))
        data, errors, err = gh_graphql_partial(
            'query($o:String!,$r:String!){ repository(owner:$o,name:$r){ %s } }'
            % parts, o=cfg['org'], r=cfg['repo'])
        repository = (data or {}).get('repository')
        per, general = _alias_errors(errors, aliases)
        for alias, number in zip(aliases, chunk):
            why = per.get(alias) or general
            if why or not repository:
                yield number, False, None, (why or err
                                            or 'the query returned no repository')
            else:
                yield number, True, repository.get(alias), ''


def fetch_parent_chains(cfg, numbers):
    """The parents above each issue, nearest first. {number: (ok, chain, err)}.

    One aliased read for every issue a merge settled (#300), where there was
    a read per issue.
    """
    wanted = list(dict.fromkeys(int(n) for n in numbers or ()))
    out = {}
    for number, ok, node, err in _aliased_repository_read(
            cfg, wanted, 'p', 'parent { %s }' % _chain_selection(CONTAINER_CHAIN_DEPTH)):
        if not ok:
            out[number] = (False, [], err)
            continue
        parent, chain = (node or {}).get('parent'), []
        while parent:
            chain.append(_container_node(parent))
            parent = parent.get('parent')
        out[number] = (True, chain, '')
    return out


def fetch_parent_chain(cfg, number):
    """The parents above one issue, nearest first. (ok, chain, err)."""
    return fetch_parent_chains(cfg, [number])[int(number)]


def close_container(cfg, number, comment):
    """Close one finished container as completed and set its `Stage` to Done."""
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    code, _, err = run(['gh', 'issue', 'close', str(number), '--repo', repo,
                        '--reason', 'completed', '--comment', comment])
    if code != 0:
        return {'issue': number, 'closed': False,
                'error': err.strip() or 'gh issue close failed'}
    written, message = set_stage(cfg, number, wf_core.STAGE_NAMES['stage-done'])
    return {'issue': number, 'closed': True, 'stage_set': written,
            'stage_message': message}


def close_finished_ancestors(cfg, numbers):
    """Close every Epic or Feature that closing `numbers` finished (#240).

    Walks up each issue's parents and stops at the first that still has an
    open child, so closing a Feature can finish its Epic in the same run. A
    parent in another repository is left alone. Returns (closed, errors):
    one entry per container it tried to close, and each parent chain that
    could not be read.

    Every chain is read up front in one request. Reading them one at a time
    after each close bought nothing: GitHub may not show a close this run just
    made, so the walk already judges each chain against `done` rather than
    against what the read says.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    done = {int(n) for n in numbers or ()}
    closed, errors = [], []
    chains = fetch_parent_chains(cfg, numbers) if numbers else {}
    for number in numbers or ():
        ok, chain, err = chains.get(int(number), (False, [], 'not read'))
        if not ok:
            errors.append('#%d: %s' % (number, err))
            continue
        for step in wf_core.ancestors_to_close(number, chain, done, repo):
            if step['number'] in done:
                continue
            result = close_container(cfg, step['number'],
                                     CONTAINER_CLOSE_COMMENT % step['finished_by'])
            result['finished_by'] = step['finished_by']
            closed.append(result)
            if not result['closed']:
                # The ancestors above were judged on this one closing.
                break
            done.add(step['number'])
    return closed, errors


def _fix_finished_containers(cfg, containers):
    """Close every open Epic or Feature preflight found already finished.

    The preflight half of #240: the merge closes what it finishes from now
    on, and `fetch_open_issue_state` finds the ones that finished before it did.
    """
    if not containers:
        return [], []
    closed, failed = [], []
    for container in containers:
        result = close_container(cfg, container['number'], CONTAINER_SWEEP_COMMENT)
        if result['closed']:
            closed.append(container['number'])
        else:
            failed.append('#%d (%s)' % (container['number'], result['error']))
    # The same rule as post-merge: closing a Feature can finish its Epic, and
    # a second `--fix` should not be what it takes to see that.
    above, errors = close_finished_ancestors(cfg, closed)
    closed += [c['issue'] for c in above if c['closed']]
    failed += ['#%d (%s)' % (c['issue'], c['error']) for c in above if not c['closed']]
    done, blocked = [], []
    if closed:
        done.append('closed %d finished Epic or Feature issue%s: %s'
                    % (len(closed), '' if len(closed) == 1 else 's',
                       ', '.join('#%d' % n for n in closed)))
    if failed:
        blocked.append('could not close %s' % ', '.join(failed))
    if errors:
        # Its own wording: the container did close, and saying "could not
        # close" beside "closed" would contradict the line above.
        blocked.append('could not read the parents of %s, so whether an Epic '
                       'above is now finished is unchecked' % '; '.join(errors))
    return done, blocked


def _fix_stage_drift(cfg, drifted):
    """Write the stage each drifted issue's own GitHub state puts it in.

    Safe without a person because only a blank or `Backlog` stage is ever
    judged (`wf_core.stage_drift_target`), so no stage a run or a person chose
    is overwritten. One aliased write for all of them.
    """
    if not drifted:
        return [], []
    outcomes = set_stages(cfg, {d['number']: d['stage'] for d in drifted})
    written, failed = [], []
    for entry in drifted:
        ok, message = outcomes.get(int(entry['number']), (False, 'not attempted'))
        if ok:
            written.append('#%d to %s' % (entry['number'],
                                          wf_core.STAGE_NAMES[entry['stage']]))
        else:
            failed.append('#%d (%s)' % (entry['number'], message))
    done, blocked = [], []
    if written:
        done.append('set the `Stage` of %s' % ', '.join(written))
    if failed:
        blocked.append('could not set the `Stage` of %s' % ', '.join(failed))
    return done, blocked


# ── settling the linked issues ───────────────────────────────────────────────

def read_linked_issues(cfg, numbers):
    """Each linked issue's node id, state and labels. {number: (ok, issue, err)}.

    `issue` is {'id', 'state', 'labels': [{'id', 'name'}]}. The label ids come
    back with the names because removing a retired label by mutation takes
    its id. One aliased read for every issue (#300).
    """
    out = {}
    for number, ok, node, err in _aliased_repository_read(
            cfg, numbers, 'i', 'id state labels(first:50){ nodes { id name } }'):
        if ok and not node:
            ok, err = False, 'issue #%d not found' % number
        out[number] = (ok, None if not ok else {
            'id': node.get('id'), 'state': (node.get('state') or '').upper(),
            'labels': [l for l in (node.get('labels') or {}).get('nodes') or []
                       if l and l.get('name')]}, err)
    return out


def settle_issues(plan, pr):
    """Close and strip every linked issue that needs it, in one request per batch.

    `plan` is [{'number', 'id', 'close', 'label_ids'}]; each entry needs at
    least one of the two. A close posts its comment first and closes as
    completed, as `gh issue close --comment` did. Returns {number: {'closed':
    bool or None, 'cleared': bool or None}}, None where nothing was asked.

    GraphQL runs every field of a mutation whatever an earlier one did, and
    answers each with its own outcome, so one issue that refuses its close is
    reported against that issue and the rest still land.
    """
    out = {}
    for chunk in _chunks(list(plan), SETTLE_BATCH):
        decls, body, variables = [], [], {}
        comments, closes, strips = [], [], []
        for entry in chunk:
            n = entry['number']
            decls.append('$i%d:ID!' % n)
            variables['i%d' % n] = entry['id']
            if entry['close']:
                decls.append('$b%d:String!' % n)
                variables['b%d' % n] = SETTLE_COMMENT % pr
                body.append('m%d: addComment(input:{subjectId:$i%d,body:$b%d})'
                            '{ subject { id } }' % (n, n, n))
                body.append('c%d: closeIssue(input:{issueId:$i%d,'
                            'stateReason:COMPLETED}){ issue { id state } }' % (n, n))
                comments.append('m%d' % n)
                closes.append('c%d' % n)
            if entry['label_ids']:
                decls.append('$l%d:[ID!]!' % n)
                variables['l%d' % n] = list(entry['label_ids'])
                body.append('l%d: removeLabelsFromLabelable(input:{labelableId:$i%d,'
                            'labelIds:$l%d}){ labelable { __typename } }' % (n, n, n))
                strips.append('l%d' % n)
        code, raw, err = _graphql_json('mutation(%s){ %s }'
                                       % (','.join(decls), ' '.join(body)),
                                       variables)
        closed = _batch_result(code, raw, err, closes, field='issue')
        cleared = _batch_result(code, raw, err, strips, field='labelable')
        for entry in chunk:
            n = entry['number']
            out[n] = {
                'closed': closed['c%d' % n][0] if entry['close'] else None,
                'cleared': cleared['l%d' % n][0] if entry['label_ids'] else None,
            }
    return out


def cmd_post_merge(args):
    """Settle a merged PR's linked issues: force-close any still open, set all to Done.

    GitHub only auto-closes a linked issue when the PR carried a recognised
    closing keyword **and** merged into the default branch — so a chained-story
    PR (non-default base) or an unparsed reference leaves the issue open with
    nothing to notice. And even when the issue does auto-close, nothing takes
    its `Stage` out of In Review. This makes both deterministic: for every
    issue the PR closes (GitHub's own `closingIssuesReferences` parse, plus any
    `--issue` the caller names for an unrecognised reference), close it if still
    open and set its `Stage` to Done.

    The same five requests however many issues the PR closes (#300): the PR,
    one read of every issue, one write closing and stripping them, one `Stage`
    write, and one read of their parents. It was five per issue.
    """
    cfg = prepare_cfg()
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['pr', 'view', str(args.pr), '--repo', repo,
                             '--json', 'number,state,mergedAt,baseRefName,closingIssuesReferences'])
    if not ok or not data:
        emit('error', EXIT_ENV, reason='could not read PR #%d (%s)' % (args.pr, err))
    if (data.get('state') or '').upper() != 'MERGED':
        emit('not-merged', EXIT_ALL_BLOCKED,
             reason='PR #%d is %s, not MERGED — refusing to close its issues'
                    % (args.pr, data.get('state')),
             pr=args.pr)

    # `gh pr view --json` returns the references as a flat list, unlike the
    # GraphQL API (used by merged_pr_closing) which wraps them as {nodes: [...]};
    # closing_issue_numbers normalises both so this can't crash on the shape.
    linked = wf_core.closing_issue_numbers(data.get('closingIssuesReferences'))
    for extra in (args.issue or []):
        if extra not in linked:
            linked.append(extra)

    issues = read_linked_issues(cfg, linked) if linked else {}
    facts, plan = {}, []
    for number in linked:
        ok, issue, _ = issues.get(number, (False, None, ''))
        issue = issue or {}
        state = issue.get('state') or ''
        # A settled issue is Done: strip any retired lifecycle label it still
        # carries (e.g. a PR that auto-closed the issue but left
        # status-in-progress on).
        stale = wf_core.retired_labels_on([l['name'] for l in issue.get('labels') or []],
                                          cfg.get('labels') or {})
        label_ids = [l['id'] for l in issue.get('labels') or []
                     if l['name'] in stale and l.get('id')]
        facts[number] = {'id': issue.get('id'), 'was_open': state == 'OPEN',
                         'closed': state == 'CLOSED', 'stale': stale}
        if ok and issue.get('id') and (state == 'OPEN' or label_ids):
            plan.append({'number': number, 'id': issue['id'],
                         'close': state == 'OPEN', 'label_ids': label_ids})

    outcomes = settle_issues(plan, args.pr) if plan else {}
    notes, note_errors = read_release_notes(getattr(args, 'notes', None))
    note_inputs, note_facts = release_note_writes(cfg, linked, notes)
    done = wf_core.STAGE_NAMES['stage-done']
    ids = {n: facts[n]['id'] for n in linked if facts[n]['id']}
    stages = set_stages(cfg, {n: done for n in linked}, ids=ids,
                        extra=note_inputs)
    # The notes ride in the `Stage` write, so a text the API refuses would
    # hold the issue out of Done. Retry the stage alone for any issue whose
    # combined write failed: the transition matters more than the notes.
    retry = [n for n in note_inputs if not stages.get(n, (False,))[0]]
    if retry:
        again = set_stages(cfg, {n: done for n in retry}, ids=ids)
        for n in retry:
            note_facts[n]['error'] = stages[n][1]
            note_facts[n]['written'] = []
            stages[n] = again[n]

    settled = []
    for number in linked:
        fact, outcome = facts[number], outcomes.get(number) or {}
        # Whether the issue is closed once this is done. The container walk
        # below reads it: an Epic or Feature is only finished by a close that
        # happened, not by one that was attempted.
        closed = fact['closed']
        if fact['was_open']:
            closed = bool(outcome.get('closed'))
        cleared = ', '.join(fact['stale']) if outcome.get('cleared') else None
        done_set, stage_msg = stages.get(int(number), (False, 'not attempted'))
        entry = {'issue': number, 'closed_now': bool(fact['was_open'] and closed),
                 'closed': closed,
                 'lifecycle_label_cleared': cleared,
                 'stage_set': done_set, 'stage_message': stage_msg}
        if number in note_facts:
            entry['release_notes'] = note_facts[number]
        settled.append(entry)

    # Settling the issues the PR closed is only half of a merge. The other half
    # is releasing whatever was waiting on them, and nothing used to do it: a
    # PR that closes nothing reports `settled: []`, which reads as "finished"
    # and is not. The sweep runs whether or not anything settled, because the
    # merge may have closed a blocker through a reference this never saw.
    # Closing a story can finish the Epic or Feature above it, and nothing
    # else ever closes one (#240). Walked before the unblock sweep, so anything
    # waiting on a container this closes is released by the same run.
    containers, container_errors = close_finished_ancestors(
        cfg, [s['issue'] for s in settled if s['closed']])

    unblocked = unblock_scan(cfg) if not args.no_unblock else None

    clean = (all(s['closed'] and s['stage_set'] for s in settled)
             and not note_errors
             and not any((s.get('release_notes') or {}).get('error')
                         for s in settled)
             and not container_errors
             and not (unblocked or {}).get('error')
             and not (unblocked or {}).get('rescoped')
             and not (unblocked or {}).get('partials')
             and all(r.get('stage_set', True) and not r.get('still_assigned')
                     for r in ((unblocked or {}).get('released') or [])
                     + ((unblocked or {}).get('rescoped') or [])))
    if clean:
        # Everything landed: one line, with only what the report names.
        released = [{'issue': r['issue'], 'title': r.get('title')}
                    for r in (unblocked or {}).get('released') or ()]
        cleared = {str(s['issue']): s['lifecycle_label_cleared'] for s in settled
                   if s['lifecycle_label_cleared']}
        extra = {'cleared': cleared} if cleared else {}
        no_edges = ((unblocked or {}).get('no_edges') or {}).get('count')
        if no_edges:
            extra['no_edges'] = no_edges
        noted = {str(n): f['written'] for n, f in note_facts.items() if f['written']}
        if noted:
            extra['release_notes'] = noted
        emit_line('ok', EXIT_OK, pr=args.pr, settled=[s['issue'] for s in settled],
                  containers_closed=containers, released=released, **extra,
                  reason='PR #%d settled: %d issue(s) closed and Done, %d '
                         'container(s) closed, %d issue(s) released'
                         % (args.pr, len(settled), len(containers), len(released)))
    emit('ok', EXIT_OK, pr=args.pr, base=data.get('baseRefName'), settled=settled,
         containers_closed=containers, container_errors=container_errors,
         release_note_errors=note_errors, unblocked=unblocked)


def read_release_notes(path):
    """The `--notes` file, parsed. ({number: texts}, errors).

    No path is no notes, and not an error: a run that wrote none (a project
    without the fields, a PR merged by hand) settles exactly as before.
    """
    if not path:
        return {}, []
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return {}, ['could not read %s (%s)' % (path, exc)]
    return wf_core.parse_release_notes(data)


def release_note_writes(cfg, linked, notes):
    """The field inputs to write beside each linked issue's `Stage`.

    Returns (extra, facts): `extra` is {number: [field input]} for
    `set_stages`, and `facts` is {number: {'written': [field names],
    'skipped': [why]}} for the report. Only the issues this PR closes are
    written: a container `post-merge` closes because its children finished
    is never passed here, and a note for an issue the PR does not close is
    ignored.
    """
    extra, facts = {}, {}
    for number in linked:
        if number not in notes:
            continue
        inputs, written, skipped = release_note_inputs(cfg, notes[number])
        facts[number] = {'written': written, 'skipped': skipped}
        if inputs:
            extra[number] = inputs
    return extra, facts
