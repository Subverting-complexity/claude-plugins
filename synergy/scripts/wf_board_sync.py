"""
The `board-sync` subcommand: put every open issue on the boards that should
show it.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import json
import re
import time

import wf_core
from wf_config import field_name, prepare_cfg
from wf_io import (
    EXIT_CAPABILITY, EXIT_ENV, EXIT_OK, EXIT_PARTIAL, emit, gh_graphql, run,
)
from wf_issue_io import _batch_result, _graphql_json, issue_field_values
from wf_stage import NO_STAGE_FIELD, _chunks, set_stages, stage_field_meta


# ── board-sync ───────────────────────────────────────────────────────────────
# The scheduled backup for everything a run or a person did not keep in step.
# GitHub's own "Auto-add to project" workflow is what puts issues on boards;
# this adds any card it missed, and brings each issue's `Stage` into line with
# what the issue itself shows, which auto-add cannot do.
#
# The logs of a public repository's workflow are public, so this reports
# totals and nothing else: no repository, issue number, title or error text a
# reader could trace back to one of them.

SYNC_REPO_PAGE = 50
SYNC_ISSUE_PAGE = 50
SYNC_MAX_PAGES = 40
SYNC_CLOSED_DAYS = 7
CARD_BATCH = 20


def _sync_repos_query(paged):
    return (
        'query($login:String!%s){ organization(login:$login){'
        ' repositories(first:%d%s,orderBy:{field:NAME,direction:ASC}){'
        '  pageInfo { hasNextPage endCursor }'
        '  nodes { name isArchived hasIssuesEnabled'
        '   projectsV2(first:20){ nodes { id closed } } } } } }'
        % (',$cursor:String!' if paged else '', SYNC_REPO_PAGE,
           ',after:$cursor' if paged else ''))


def _sync_issues_query(state, paged):
    """One page of a repository's issues, with everything a sync decides on.

    Newest update first, so the closed-issue read can stop at the first issue
    older than its window instead of reading the repository's whole history.
    """
    return (
        'query($owner:String!,$repo:String!%s){'
        ' repository(owner:$owner,name:$repo){'
        '  issues(first:%d,states:%s,orderBy:{field:UPDATED_AT,direction:DESC}%s){'
        '   pageInfo { hasNextPage endCursor }'
        '   nodes { id number updatedAt'
        '    assignees(first:1){ nodes { login } }'
        '    blockedBy(first:50){ pageInfo { hasNextPage } nodes { state } }'
        '    closedByPullRequestsReferences(first:10,includeClosedPrs:false){'
        '     nodes { state isDraft } }'
        '    projectItems(first:20){ nodes { project { id } } }'
        '    issueFieldValues(first:50){ nodes {'
        '     ... on IssueFieldSingleSelectValue {'
        '      field { ... on IssueFieldSingleSelect { name } } name } } }'
        '   } } } }'
        % (',$cursor:String!' if paged else '', SYNC_ISSUE_PAGE, state,
           ',after:$cursor' if paged else ''))


def _paged_nodes(query_for, path, args, stop=None):
    """Every node of a paged connection. (ok, nodes, err).

    `stop(node)` ends the read at the first node it accepts, without keeping
    it. Reaching the page cap is an error rather than a short list, because a
    sync that acts on part of a repository has not synced it.
    """
    nodes, cursor, pages = [], None, 0
    while True:
        if pages >= SYNC_MAX_PAGES:
            return False, None, 'page cap reached'
        page_args = dict(args)
        if cursor:
            page_args['cursor'] = cursor
        ok, data, err = gh_graphql(query_for(bool(cursor)), **page_args)
        if not ok or not data:
            return False, None, err or 'query returned nothing'
        connection = data
        for step in path:
            connection = (connection or {}).get(step)
        if not isinstance(connection, dict):
            return False, None, 'unexpected response shape'
        pages += 1
        for node in connection.get('nodes') or []:
            if not node:
                continue
            if stop and stop(node):
                return True, nodes, ''
            nodes.append(node)
        info = connection.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return True, nodes, ''
        cursor = info.get('endCursor')


def repo_issue_claims(owner, repo):
    """The issue numbers holding a claim ref. (ok, numbers, err).

    Read over REST rather than `git ls-remote`, so a sync needs no clone of
    each repository and no credential beyond the token it already has.
    """
    code, out, err = run(['gh', 'api', '/repos/%s/%s/git/matching-refs/'
                          'claims/issue-?per_page=100' % (owner, repo)])
    if code != 0:
        return False, None, err.strip() or 'claim ref read failed'
    try:
        refs = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        return False, None, 'could not parse claim refs'
    numbers = set()
    for ref in refs if isinstance(refs, list) else []:
        match = re.match(r'refs/claims/issue-(\d+)$', (ref or {}).get('ref', ''))
        if match:
            numbers.add(int(match.group(1)))
    return True, numbers, ''


def add_cards(pairs):
    """Add each (project id, issue node id) as a card. Returns (added, failed)."""
    added = failed = 0
    for chunk in _chunks(list(pairs), CARD_BATCH):
        decls, body, variables, aliases = [], [], {}, []
        for index, (project_id, content_id) in enumerate(chunk):
            alias = 'c%d' % index
            aliases.append(alias)
            decls.append('$%s_p:ID!,$%s_c:ID!' % (alias, alias))
            body.append('%s: addProjectV2ItemById(input:{projectId:$%s_p,'
                        'contentId:$%s_c}){ item { id } }'
                        % (alias, alias, alias))
            variables['%s_p' % alias] = project_id
            variables['%s_c' % alias] = content_id
        code, raw, merr = _graphql_json('mutation(%s){ %s }'
                                        % (','.join(decls), ' '.join(body)),
                                        variables)
        for ok, _node, _why in _batch_result(code, raw, merr, aliases,
                                             field='item').values():
            if ok:
                added += 1
            else:
                failed += 1
    return added, failed


def sync_plan(issues, is_open, projects, claims, stage_field, ownership_field=None):
    """What one repository needs. Returns (cards, stages, ids).

    `cards` is [(project id, issue node id)] for each open issue missing from a
    linked board, `stages` is {number: stage name} for each issue whose `Stage`
    is wrong, and `ids` is {number: node id} so the write needs no second read.
    `claims` is None when the claim refs could not be read.
    """
    cards, stages, ids = [], {}, {}
    for node in issues:
        number = node.get('number')
        if not number:
            continue
        ids[number] = node.get('id')
        if is_open and node.get('id'):
            on = {((item or {}).get('project') or {}).get('id')
                  for item in (node.get('projectItems') or {}).get('nodes') or []}
            cards.extend((project, node['id']) for project in projects
                         if project not in on)
        edge_connection = node.get('blockedBy') or {}
        edges = edge_connection.get('nodes') or []
        # An edge the token cannot read comes back null. It is not known to be
        # closed, so it counts as open: releasing a blocked issue on a guess is
        # the one mistake a sync must not make.
        open_blockers = sum(1 for e in edges
                            if (e or {}).get('state') != 'CLOSED')
        if ((edge_connection.get('pageInfo') or {}).get('hasNextPage')
                and not open_blockers):
            # More edges than one page holds, and none open among those read:
            # the rest are unknown, so this issue's stage is not judged.
            continue
        prs = [pr for pr in ((node.get('closedByPullRequestsReferences')
                              or {}).get('nodes') or [])
               if pr and (pr.get('state') or '').upper() == 'OPEN']
        values = issue_field_values(node)
        target = wf_core.reconcile_stage(
            is_open,
            values.get(stage_field) or '',
            scope=wf_core.ownership_scope(values.get(ownership_field)),
            blockers=len(edges),
            open_blockers=open_blockers,
            assigned=bool((node.get('assignees') or {}).get('nodes')),
            claimed=True if claims is None else number in claims,
            open_prs=prs)
        if target:
            stages[number] = target
    return cards, stages, ids


def cmd_board_sync(args):
    cfg = prepare_cfg()
    stage_field = field_name(cfg, 'field-stage')
    ownership_field = field_name(cfg, 'field-ownership')
    ok, _meta, err = stage_field_meta(cfg)
    if not ok:
        emit('error', EXIT_CAPABILITY if err == NO_STAGE_FIELD else EXIT_ENV,
             reason=('the org defines no Stage field' if err == NO_STAGE_FIELD
                     else 'the org issue fields could not be read'))
    ok, repos, _err = _paged_nodes(
        _sync_repos_query, ('organization', 'repositories'),
        {'login': cfg['org']})
    if not ok:
        emit('error', EXIT_ENV, reason='the org repositories could not be listed')

    since = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(
        time.time() - args.closed_days * 86400))
    totals = {'repos': 0, 'repos_with_boards': 0, 'repos_failed': 0,
              'claims_unread': 0, 'issues_read': 0, 'cards_added': 0,
              'cards_failed': 0, 'stages_set': 0, 'stages_failed': 0,
              'stages_by_value': {}}
    for repo in repos:
        if repo.get('isArchived') or not repo.get('hasIssuesEnabled'):
            continue
        name = repo.get('name')
        totals['repos'] += 1
        projects = [p['id'] for p in (repo.get('projectsV2') or {})
                    .get('nodes') or [] if p and p.get('id')
                    and not p.get('closed')]
        if projects:
            totals['repos_with_boards'] += 1
        repo_args = {'owner': cfg['org'], 'repo': name}
        ok_open, open_issues, _ = _paged_nodes(
            lambda paged: _sync_issues_query('OPEN', paged),
            ('repository', 'issues'), repo_args)
        # `--closed-days 0` reads every closed issue. The window alone left an
        # issue closed before it with whatever Stage it had, In Review or
        # Backlog, for good; the scheduled full sweep is what corrects those.
        ok_closed, closed_issues, _ = _paged_nodes(
            lambda paged: _sync_issues_query('CLOSED', paged),
            ('repository', 'issues'), repo_args,
            stop=(None if args.closed_days <= 0
                  else lambda node: (node.get('updatedAt') or '') < since))
        if not (ok_open and ok_closed):
            totals['repos_failed'] += 1
            continue
        ok_claims, claims, _ = repo_issue_claims(cfg['org'], name)
        if not ok_claims:
            claims = None
            totals['claims_unread'] += 1
        totals['issues_read'] += len(open_issues) + len(closed_issues)

        cards, stages, ids = sync_plan(open_issues, True, projects, claims,
                                       stage_field, ownership_field)
        _, closed_stages, closed_ids = sync_plan(closed_issues, False, [],
                                                 claims, stage_field, ownership_field)
        stages.update(closed_stages)
        ids.update(closed_ids)

        if args.dry_run:
            totals['cards_added'] += len(cards)
            written = {n: (True, '') for n in stages}
        else:
            added, failed = add_cards(cards)
            totals['cards_added'] += added
            totals['cards_failed'] += failed
            written = set_stages(dict(cfg, repo=name), stages, ids=ids)
        for number, (landed, _why) in written.items():
            if landed:
                totals['stages_set'] += 1
                by = totals['stages_by_value']
                by[stages[number]] = by.get(stages[number], 0) + 1
            else:
                totals['stages_failed'] += 1

    failures = (totals['repos_failed'] + totals['cards_failed']
                + totals['stages_failed'])
    verb = 'would add' if args.dry_run else 'added'
    reason = ('%s %d card(s) and %s %d stage(s) across %d repositories'
              % (verb, totals['cards_added'],
                 'would set' if args.dry_run else 'set',
                 totals['stages_set'], totals['repos']))
    if failures:
        emit('partial', EXIT_PARTIAL, dry_run=args.dry_run, totals=totals,
             reason='%s; %d write(s) or repositories failed' % (reason, failures))
    emit('ok', EXIT_OK, dry_run=args.dry_run, totals=totals, reason=reason)
