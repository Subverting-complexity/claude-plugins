"""
The unblock sweep: release what closed edges freed, and the `unblock`
subcommand.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

from datetime import datetime, timezone

import wf_core
from wf_candidates import load_issue_facets, stage_issues
from wf_config import prepare_cfg
from wf_io import EXIT_ENV, EXIT_OK, emit, eprint, gh_graphql
from wf_issue_io import add_comments
from wf_stage import set_stages


# ── the unblock sweep ────────────────────────────────────────────────────────
# Nothing here used to release an issue when the thing it waited on landed.
# `post-merge` settles only the issues a pull request *closes*, so a story that
# merges and stays open reports nothing, and the work it freed sits there
# labelled blocked and invisible to the picker until somebody notices by hand.
# On this project somebody had to ask. This is the part that notices.
#
# It reads the native `blockedBy` edges and nothing else, and it checks scope
# before it checks edges: browser and human work is set to Non-code rather
# than released, because no edge closing will ever make a code
# agent able to do it.

UNBLOCK_BLOCKER_BATCH = 20

# What the sweep reads about each Blocked issue beyond the basics. The type
# with the field values lets the ownership check use this same read, and
# `totalCount` says when an issue holds more edges than one page returns.
BLOCKED_SELECTION = (
    'issueType { name }'
    ' blockedBy(first:20){ totalCount nodes { number state title'
    '  repository { nameWithOwner } } }'
)


def blocked_issues(cfg):
    """Every open issue whose `Stage` is Blocked, with its native edges.

    Returns (issues, error).

    `Stage` is where an issue's state lives, so "which issues are blocked" is a
    question one field answers, with one value per issue. This read a label
    search until 10.0.0 and a board column until 12.0.0, and each could
    disagree with the other record of the same fact.
    """
    ok, issues, err = stage_issues(
        cfg, (wf_core.STAGE_NAMES['stage-blocked'],),
        unassigned_only=False, extra=BLOCKED_SELECTION)
    if not ok:
        return [], err
    return issues, None


def blocker_deliveries(cfg, numbers, now=None):
    """The newest pull request that merged mentioning each open blocker.

    Keyed by issue number, and absent for a blocker nothing has merged against
    recently. Cross-references rather than closing references, because the case
    this exists to catch is precisely the pull request that deliberately closed
    nothing: it delivered one half of a story and left the issue open for the
    other half, so GitHub records no closing reference to read. Which reference
    counts is `wf_core.recent_delivery`'s decision, and it is a strict one.

    Local numbers only: a blocker in another repository is not an issue this
    repository's query can read.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    found = {}
    ordered = sorted({int(n) for n in (numbers or ())
                      if isinstance(n, int) or str(n).isdigit()})
    for start in range(0, len(ordered), UNBLOCK_BLOCKER_BATCH):
        batch = ordered[start:start + UNBLOCK_BLOCKER_BATCH]
        parts = [
            'b%d: issue(number:%d){ timelineItems(last:30,'
            ' itemTypes:[CROSS_REFERENCED_EVENT]){ nodes {'
            ' ... on CrossReferencedEvent { source {'
            ' ... on PullRequest { number title state mergedAt } } } } } }'
            % (number, number) for number in batch]
        ok, data, _ = gh_graphql(
            'query($o:String!,$r:String!){ repository(owner:$o,name:$r){ %s } }'
            % ' '.join(parts), o=cfg['org'], r=cfg['repo'])
        if not ok or not data:
            continue
        repo = data.get('repository') or {}
        for number in batch:
            node = repo.get('b%d' % number) or {}
            sources = [(item or {}).get('source') or {}
                       for item in ((node.get('timelineItems') or {}).get('nodes') or [])]
            delivery = wf_core.recent_delivery(sources, number, now)
            if delivery:
                found[number] = delivery
    return found


UNBLOCK_COMMENT = (
    'Unblocked by `wf unblock`. Every issue this waited on is now closed: %s.\n\n'
    '`Stage` was set to Backlog on purpose, which is what puts this issue back '
    'in the pick pool. The native blocked-by edges are what decide it, so if '
    'something still blocks this issue, add the edge for it rather than '
    'setting Blocked on its own: Blocked with no edge behind it is left alone '
    'by the sweep, so nothing would ever release it.'
)

RESCOPE_COMMENT = (
    '`Stage` set to `%s` by `wf unblock`. This is %s work, which no code agent '
    'can pick up, so it belongs in Non-code rather than in Blocked. Blocked '
    'means a dependency is open and a sweep will release it when that '
    'dependency closes; this issue would have been released into a pool that '
    'cannot do it. Nothing about the work has changed.'
)


def settle_blocked(cfg, releases=(), rescopes=(), dry_run=False):
    """Release and rescope many Blocked issues at once. (released, rescoped).

    `releases` is [(issue, closed blockers)], each going back to Backlog;
    `rescopes` is [(issue, scope)], each going to Non-code. One `Stage`
    mutation for all of them, using the node ids the read already holds, and
    one comment mutation for every write that landed. It was a `Stage` write
    and a `gh issue comment` per issue.

    The write is the release. Backlog is the pick pool, so an issue arriving
    there is the issue becoming available -- there is no separate label to
    take off, and no way for two records to disagree about the release.

    The comment is not decoration. A bare state change reads to the next agent
    like damage to be repaired, and on this project one promptly repaired it:
    three issues were released by hand and re-blocked two minutes later by a
    concurrent session that took the change for automation stripping labels.
    Saying who did it and why is what stops that.

    A rescope rather than a release, and the distinction is the point: browser
    and human work is never pickable by a code agent, so it must leave Blocked
    without ever passing through the pool.
    """
    non_code = wf_core.STAGE_NAMES['stage-non-code']
    released, rescoped = [], []
    for issue, closed in releases:
        entry = {'issue': issue['number'], 'title': issue.get('title'),
                 'closed_blockers': list(closed)}
        if dry_run:
            entry['dry_run'] = True
        released.append(entry)
    for issue, scope in rescopes:
        entry = {'issue': issue['number'], 'title': issue.get('title'),
                 'scope': scope, 'stage': non_code}
        if dry_run:
            entry['dry_run'] = True
        rescoped.append(entry)
    if dry_run or not (released or rescoped):
        return released, rescoped

    wanted = {issue['number']: wf_core.STAGE_NAMES['stage-backlog']
              for issue, _closed in releases}
    wanted.update({issue['number']: non_code for issue, _scope in rescopes})
    ids = {issue['number']: issue.get('id')
           for issue, _x in list(releases) + list(rescopes)}
    stages = set_stages(cfg, wanted, ids)

    bodies = {}
    for entry, (issue, closed) in zip(released, releases):
        # The pool is the *unassigned* issues in Backlog, so an issue that kept
        # the assignee it had when it was blocked arrives in the pool and is
        # still invisible to every pick. That is said rather than fixed: taking
        # somebody's name off their issue is not a sweep's decision to make.
        if issue.get('assigned'):
            entry['still_assigned'] = issue.get('assignees') or True
            eprint('wf: #%s was released to Backlog but is still assigned, so no '
                   'pick will offer it until somebody unassigns it' % issue['number'])
        bodies[issue['number']] = UNBLOCK_COMMENT % ', '.join(
            wf_core.ref_label(n) for n in closed)
    for entry, (issue, scope) in zip(rescoped, rescopes):
        bodies[issue['number']] = RESCOPE_COMMENT % (non_code, scope)

    comments = {}
    for entry in released + rescoped:
        n = entry['issue']
        written, message = stages.get(n, (False, 'not written'))
        entry['stage_set'] = written
        if not written:
            entry['stage_message'] = message
        else:
            comments[n] = (ids.get(n), bodies[n])
    posted = add_comments(comments) if comments else {}
    for entry in released + rescoped:
        if entry['issue'] in posted:
            entry['commented'] = posted[entry['issue']][0]
    return released, rescoped


def release_issue(cfg, issue, closed_numbers):
    """Release one issue: `settle_blocked` for one. Result dict."""
    return settle_blocked(cfg, releases=[(issue, closed_numbers)])[0][0]


def rescope_issue(cfg, issue, scope, dry_run=False):
    """Set one non-code issue's `Stage` from Blocked to Non-code: `settle_blocked`
    for one. Result dict."""
    return settle_blocked(cfg, rescopes=[(issue, scope)], dry_run=dry_run)[1][0]


def unblock_scan(cfg, dry_run=False, only=None, now=None):
    """Release every blocked issue whose native dependencies have all closed.

    Returns a report with five parts, and only the first two write anything:

      released  every edge points at a closed issue, so `Stage` goes back to
                Backlog and the issue is in the pool again
      rescoped  browser or human work that was sitting in Blocked, set to
                Non-code instead. Never released: no edge closing will ever
                make a code agent able to do it.
      held      at least one blocker is still open, or the issue holds more
                edges than the read returned (`edges_unread`), so it stays
      partials  held, but a blocker has just merged something. This is the case
                no edge can describe, reported rather than acted on.
      no_edges  Blocked with no edge at all, which a person set, so this never
                clears it. Most of those are waiting on the world rather than
                on an issue, which is exactly why the rule needs an edge before
                it will release anything.

    The ownership check comes before the edge check and that order is the whole
    safety property. Both issues this sweep would have released on its first
    real backlog were `[Manual]` device-pass work whose blockers happened to
    close: releasing them would have put a job needing a phone in someone's
    hand into the code agent's pool.

    Ownership is read with the issues themselves. An issue with no value is
    **held** rather than released, and named: the sweep will not decide that
    an issue nobody has said who owns is safe for a code agent, which is the
    same rule the picker follows.

    An issue whose edges ran past the read is held, never released: the edge
    past the page may be the one still open. A blocker in another repository
    holds while it is open, like any other.
    """
    issues, error = blocked_issues(cfg)
    wanted = {int(n) for n in (only or ())} or None
    # Ownership for exactly the blocked issues, and a failure here stops the
    # sweep: with no ownership values every blocked issue reads as unowned, so a
    # failed query would report a stage full of issues nobody owns and release
    # none of them.
    facets = load_issue_facets(cfg, [i['number'] for i in issues], issues=issues)
    ownership = facets.get('ownership') or {}
    repo = '%s/%s' % (cfg['org'], cfg['repo'])

    releases, rescopes, held, no_edges, unowned = [], [], [], [], []
    for issue in issues:
        if wanted is not None and issue['number'] not in wanted:
            continue
        scope = wf_core.effective_scope(ownership.get(issue['number']),
                                        (facets.get('types') or {}).get(issue['number']))
        if scope is None:
            unowned.append({'issue': issue['number'], 'title': issue.get('title')})
            continue
        if scope != wf_core.SCOPE_CODE:
            rescopes.append((issue, scope))
            continue
        connection = issue.get('blockedBy') or {}
        edges = connection.get('nodes') or []
        verdict, open_numbers, closed_numbers = wf_core.unblock_verdict(edges, repo)
        if wf_core.edges_incomplete(connection):
            held.append({'issue': issue['number'], 'title': issue.get('title'),
                         'open_blockers': open_numbers,
                         'closed_blockers': closed_numbers,
                         'edges_unread': connection['totalCount'] - len(edges)})
        elif verdict == wf_core.UNBLOCK_NO_EDGES:
            no_edges.append(issue['number'])
        elif verdict == wf_core.UNBLOCK_HOLD:
            held.append({'issue': issue['number'], 'title': issue.get('title'),
                         'open_blockers': open_numbers,
                         'closed_blockers': closed_numbers})
        else:
            releases.append((issue, closed_numbers))
    released, rescoped = settle_blocked(cfg, releases, rescopes, dry_run=dry_run)

    deliveries = blocker_deliveries(
        cfg, {n for entry in held for n in entry['open_blockers']
              if isinstance(n, int)}, now)
    partials = []
    for entry in held:
        recent = [{'blocker': n, 'merged_pr': deliveries[n]['number'],
                   'merged_at': deliveries[n]['merged_at']}
                  for n in entry['open_blockers'] if n in deliveries]
        if recent:
            partials.append({'issue': entry['issue'], 'title': entry['title'],
                             'deliveries': recent})

    report = {'scanned': len(issues), 'released': released,
              'rescoped': rescoped, 'held': held, 'partials': partials,
              'unowned': unowned,
              'no_edges': {'count': len(no_edges), 'issues': no_edges}}
    if error:
        report['error'] = error
    return report


def cmd_unblock(args):
    """Release every blocked issue whose native dependencies have all closed."""
    cfg = prepare_cfg()
    report = unblock_scan(cfg, dry_run=args.dry_run, only=args.issue)
    if report.get('error'):
        # The blocked issues could not be read, so "nothing to release" is not
        # a result. This reported `ok` with the error inside the payload, which
        # is a clean exit code on a sweep that swept nothing.
        emit('error', EXIT_ENV,
             reason='could not read the issues whose Stage is %s (%s), so '
                    'nothing was checked'
                    % (wf_core.STAGE_NAMES['stage-blocked'], report['error']),
             dry_run=bool(args.dry_run), **report)
    emit('ok', EXIT_OK, dry_run=bool(args.dry_run), **report)
