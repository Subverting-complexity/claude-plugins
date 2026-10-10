"""
Picking, the tree and single-issue reads: the sub-issue tree under an Epic or
Feature, and one named issue fetched and checked as a pick candidate.

Split out of `wf_pick.py`; `scripts/README.md` has the module map.
"""

import wf_core
from wf_candidates import _norm_issue, load_issue_facets
from wf_config import field_name
from wf_deps import issue_dependency_facts
from wf_io import EXIT_ALL_BLOCKED, EXIT_ENV, emit, gh_graphql, gh_json, run


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
    reset_from = None
    if assignees:
        reset_from = reset_abandoned(cfg, number, assignees)
        if reset_from:
            assignees = []
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
    if reset_from:
        stage = None
    elif stage == wf_core.STAGE_NAMES['stage-in-review']:
        reset_from = reset_abandoned(cfg, number, [])
        if reset_from:
            stage = None
    if stage and stage not in PICKABLE_BY_NAME:
        emit('all-blocked', EXIT_ALL_BLOCKED,
             reason="issue #%d has `%s` set to `%s`, so it is not available to "
                    'pick. Set it to `%s` if it should be.'
                    % (number, field_name(cfg, 'field-stage'), stage,
                       wf_core.STAGE_NAMES[wf_core.POOL_STAGE]),
             number=number, stage=stage)
    cand = _norm_issue(data)
    cand.update(facts)
    if reset_from:
        cand['reset_from_pr'] = reset_from
    return cand


def reset_abandoned(cfg, number, assignees):
    """Return an issue whose pull request was closed unmerged to the pool.

    An assigned or `In Review` issue with no open PR is either somebody's work
    or the remains of a PR that was abandoned. Only the second is reset: the
    assignees removed, `Stage` set to Backlog and a comment saying why. A
    merged PR means the work is done, so it never counts. Returns the PR
    number when the issue was reset, else None.
    """
    from wf_stage import set_stage
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, prs, _ = gh_json(['pr', 'list', '--repo', repo, '--state', 'closed',
                          '--search', '#%d' % number, '--json',
                          'number,title,mergedAt,closingIssuesReferences'])
    pr = wf_core.abandoned_pr(prs, number) if ok and isinstance(prs, list) else None
    if not pr:
        return None
    for login in assignees:
        run(['gh', 'issue', 'edit', str(number), '--repo', repo,
             '--remove-assignee', login])
    set_stage(cfg, number, wf_core.STAGE_NAMES[wf_core.POOL_STAGE])
    run(['gh', 'issue', 'comment', str(number), '--repo', repo, '--body',
         'Resetting — PR #%d closed without merge.' % pr['number']])
    return pr['number']
