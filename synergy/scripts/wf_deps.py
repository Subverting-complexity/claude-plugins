"""
Dependency validation: blocked-by edges, merged pull requests that already
resolve an issue, and marking blocked.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import wf_core
from wf_io import eprint, gh_graphql, run
from wf_issue_io import EDGE_BATCH, EDGE_PAGE
from wf_stage import set_stage


# ── dependency validation ────────────────────────────────────────────────────


def issue_edges(cfg, number):
    """The issue's native blocked-by edges, with each blocker's state.

    Returns the edge list, or None when the answer is unknown -- a failed
    query, or more edges than one page holds. None is not "no edges": every
    caller has to tell the two apart, because acting on "no edges" means
    treating the issue as unblocked.

    One query, and it answers the whole question: which issues this one waits
    on, and which of those are still open. The old shape read the body prose
    and then spent a call per reference to look each one up.
    """
    ok, data, _ = gh_graphql(
        'query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){'
        ' issue(number:$n){ blockedBy(first:%d){ nodes { number state } } } } }'
        % EDGE_PAGE,
        o=cfg['org'], r=cfg['repo'], n=int(number))
    if not ok or not data:
        return None
    try:
        nodes = data['repository']['issue']['blockedBy']['nodes'] or []
    except (KeyError, TypeError):
        return None
    return None if len(nodes) >= EDGE_PAGE else nodes


def issue_edges_map(cfg, numbers):
    """The native blocked-by edges of many issues at once. (found, unknown).

    `found` is {number: [edge]}; `unknown` is every number whose edges this
    could not read — a failed request, an alias GitHub did not answer, or more
    edges than one page holds.

    One aliased query per twenty issues rather than one query per issue. The
    split return is what stops a network failure reading as an unblocked issue:
    an absent number used to come back the same as one with no edges, so a
    transient error on this query moved a genuinely blocked card into Backlog
    and handed the issue to an agent whose dependency was still open.
    """
    found, unknown = {}, []
    ordered = sorted({int(n) for n in (numbers or ())})
    for start in range(0, len(ordered), EDGE_BATCH):
        batch = ordered[start:start + EDGE_BATCH]
        parts = ['e%d: issue(number:%d){ blockedBy(first:%d){'
                 ' nodes { number state title } } }' % (n, n, EDGE_PAGE)
                 for n in batch]
        ok, data, _ = gh_graphql(
            'query($o:String!,$r:String!){ repository(owner:$o,name:$r){ %s } }'
            % ' '.join(parts), o=cfg['org'], r=cfg['repo'])
        if not ok or not data:
            unknown.extend(batch)
            continue
        repo = data.get('repository') or {}
        for number in batch:
            node = repo.get('e%d' % number)
            if node is None:
                unknown.append(number)
                continue
            nodes = (node.get('blockedBy') or {}).get('nodes') or []
            if len(nodes) >= EDGE_PAGE:
                unknown.append(number)
                continue
            found[number] = nodes
    return found, sorted(set(unknown))


def validate_issue(cfg, issue, siblings=()):
    """Validate a claimed issue. Returns (verdict, detail).

    verdict ∈ {'valid', 'blocked', 'resolved', 'unknown'}:
      blocked  → open dependencies (detail = list of open #s, or 'meta' on overflow)
      resolved → already closed by a merged PR (detail = pr number)
      unknown  → the edges could not be read, so nothing here is decidable
      valid    → nothing stops the work starting

    The dependencies come from the native `blockedBy` edges and from nowhere
    else. No body prose is parsed here: a dependency is the edge, and a
    sentence naming one is not a second record of it.

    `unknown` exists because the alternative was worse in a specific way. A
    failed edge query used to return `blocked`, and the caller then moved the
    card to Blocked -- an issue with no edge behind it, which `wf unblock` will
    never release, parked indefinitely by one bad request.

    The dependency ceiling counts **open** blockers only. Counting closed ones
    too made an issue with six delivered dependencies permanently
    unworkable: `pick` marked it blocked, the next sweep found every edge
    closed and released it, and the two took turns.

    `siblings` are the other issues in a bulk set — stories being built in the
    same commit series on the same branch. A dependency on one of those does
    not block, because it is not unmerged work you cannot see; it is work this
    same run is about to write. Everything else is unchanged, so a single-story
    pick (no siblings) behaves exactly as before.
    """
    edges = issue_edges(cfg, issue['number'])
    if edges is None:
        return 'unknown', 'could not read the blocked-by edges'
    open_numbers, closed_numbers = wf_core.edge_states(edges)
    deps = open_numbers + closed_numbers
    if len(open_numbers) > wf_core.DEP_LIMIT:
        return 'blocked', ('meta-issue (> %d open dependencies)'
                           % wf_core.DEP_LIMIT)
    open_deps = wf_core.blocking_dependencies(deps, open_numbers, siblings)
    if open_deps:
        return 'blocked', ', '.join('#%d' % d for d in open_deps)
    pr_number = merged_pr_closing(cfg, issue['number'])
    if pr_number is not None:
        return 'resolved', pr_number
    return 'valid', None


def merged_pr_closing(cfg, number):
    """Return the number of a *merged* PR that closes issue `number`, or None.

    Uses GitHub's own parse of closing references (`closingIssuesReferences`) —
    the same authoritative signal `sibling-pr` uses
    everywhere — rather than a free-text body search. That catches the real
    "merged but the issue is still open" case (a PR merged into a non-default
    base, e.g. a chained story, where GitHub recognises the reference but does
    not auto-close), and never misfires on a stray "closes"/"#N" in prose.

    The **newest** hundred merged pull requests, and the lowest matching number
    among them so the answer is deterministic when more than one references the
    issue. It read the oldest hundred until 10.1.2, which on any repository
    past its first hundred merges could only ever see the beginning of history
    — so the case this exists to catch, a pull request that merged in the last
    few days, was the one case it could not see.
    """
    query = (
        'query($owner:String!,$repo:String!){'
        ' repository(owner:$owner,name:$repo){'
        ' pullRequests(states:MERGED, first:100,'
        ' orderBy:{field:CREATED_AT, direction:DESC}){'
        ' nodes { number closingIssuesReferences(first:10){ nodes { number } } } } } }'
    )
    ok, data, _ = gh_graphql(query, owner=cfg['org'], repo=cfg['repo'])
    if not ok or not data:
        return None
    try:
        nodes = data['repository']['pullRequests']['nodes']
    except (KeyError, TypeError):
        return None
    matches = [pr['number'] for pr in nodes
               if number in wf_core.closing_issue_numbers(
                   pr.get('closingIssuesReferences'))]
    return min(matches) if matches else None


def mark_blocked(cfg, issue, detail):
    """Return an issue to blocked: unassign, comment, set `Stage` to Blocked.

    Returns (written, message) for the `Stage` half, which the caller reports.
    The write is not decoration. It is the whole record of the state: `Stage`
    says the issue is blocked, and it is what keeps the issue out of the pool.
    A failed write therefore leaves the issue in the pool, unassigned, and the
    next run picks it up again — so it has to be said rather than swallowed.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    run(['gh', 'issue', 'edit', str(issue['number']), '--repo', repo,
         '--remove-assignee', '@me'])
    run(['gh', 'issue', 'comment', str(issue['number']), '--repo', repo,
         '--body', 'Blocked — open dependency(ies): %s. Returned to blocked until they close.' % detail])
    written, message = set_stage(cfg, issue['number'],
                                 wf_core.STAGE_NAMES['stage-blocked'])
    if not written:
        eprint('wf: warning — #%s is unassigned but its Stage was not set to '
               'Blocked (%s), so it is still in the pool'
               % (issue['number'], message))
    return written, message


def clear_lifecycle_label(cfg, number, labels):
    """Strip whatever retired workflow label a now-closed issue still carries.

    A closed issue is closed and its `Stage` is Done; that is the whole "done"
    signal. What this removes is the leftovers of the label workflow -- a
    `status-in-progress` from before the upgrade, a `priority-high` somebody
    set by hand -- so a closed issue does not go on advertising a state nothing
    maintains. Best-effort. Returns the removed label names, or None when there
    was nothing to clear.
    """
    stale = wf_core.retired_labels_on(labels, cfg.get('labels') or {})
    if not stale:
        return None
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    args = ['gh', 'issue', 'edit', str(number), '--repo', repo]
    for name in stale:
        args.extend(['--remove-label', name])
    run(args)
    return ', '.join(stale)


def close_resolved(cfg, issue, pr_number):
    """Close an already-resolved issue, clear its lifecycle label, set it to Done.

    Returns (stage_set, stage_message) so the caller can report whether
    `Stage` was written — the close itself is the authoritative state.
    """
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    run(['gh', 'issue', 'close', str(issue['number']), '--repo', repo,
         '--comment', 'Closing — already resolved by #%s.' % pr_number])
    clear_lifecycle_label(cfg, issue['number'], issue.get('labels', []))
    return set_stage(cfg, issue['number'], wf_core.STAGE_NAMES['stage-done'])
