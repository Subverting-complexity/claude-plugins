"""
After a merge: closing finished containers and the `post-merge` subcommand.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import wf_core
from wf_config import prepare_cfg
from wf_deps import clear_lifecycle_label
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_ENV, EXIT_OK, emit, gh_graphql, gh_json, run,
)
from wf_stage import set_stage, set_stages
from wf_unblock import unblock_scan


# ── closing a finished container (#240) ──────────────────────────────────────

# How far up a merged story's parents the walk reads: story, Feature, Epic,
# and one more for a tree nested deeper than the usual three levels.
CONTAINER_CHAIN_DEPTH = 4

CONTAINER_CLOSE_COMMENT = (
    'Closing as completed: every sub-issue is closed, and #%d was the last to '
    'close. Reopen this if more work is planned under it.')
CONTAINER_SWEEP_COMMENT = (
    'Closing as completed: every sub-issue is closed. Found by `wf preflight '
    '--fix`; reopen this if more work is planned under it.')

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


def fetch_parent_chain(cfg, number):
    """The parents above one issue, nearest first. (ok, chain, err)."""
    ok, data, err = gh_graphql(
        'query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){'
        ' issue(number:$n){ parent { %s } } } }' % _chain_selection(CONTAINER_CHAIN_DEPTH),
        o=cfg['org'], r=cfg['repo'], n=int(number))
    if not ok or not data:
        return False, [], err or 'the parent query failed'
    node = (((data.get('repository') or {}).get('issue')) or {}).get('parent')
    chain = []
    while node:
        chain.append(_container_node(node))
        node = node.get('parent')
    return True, chain, ''


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
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    done = {int(n) for n in numbers or ()}
    closed, errors = [], []
    for number in numbers or ():
        ok, chain, err = fetch_parent_chain(cfg, number)
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

    settled = []
    for number in linked:
        ok, idata, _ = gh_json(['issue', 'view', str(number), '--repo', repo,
                                '--json', 'state,labels'])
        was_open = ok and idata and (idata.get('state') or '').upper() == 'OPEN'
        label_names = [l['name'] for l in (idata or {}).get('labels', [])]
        # Whether the issue is closed once this is done. The container walk
        # below reads it: an Epic or Feature is only finished by a close that
        # happened, not by one that was attempted.
        closed = bool(ok and idata and (idata.get('state') or '').upper() == 'CLOSED')
        if was_open:
            code, _, _ = run(['gh', 'issue', 'close', str(number), '--repo', repo,
                              '--comment', 'Closing — resolved by merged PR #%d.' % args.pr])
            closed = code == 0
        # A settled issue is Done: strip any open-state lifecycle label it still
        # carries (e.g. a PR that auto-closed the issue but left status-in-review
        # on).
        cleared = clear_lifecycle_label(cfg, number, label_names)
        done_set, stage_msg = set_stage(cfg, number,
                                        wf_core.STAGE_NAMES['stage-done'])
        settled.append({'issue': number, 'closed_now': bool(was_open and closed),
                        'closed': closed,
                        'lifecycle_label_cleared': cleared,
                        'stage_set': done_set, 'stage_message': stage_msg})

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

    emit('ok', EXIT_OK, pr=args.pr, base=data.get('baseRefName'), settled=settled,
         containers_closed=containers, container_errors=container_errors,
         unblocked=unblocked)
