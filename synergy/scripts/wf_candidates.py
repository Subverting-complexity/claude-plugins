"""
Reading the pool: open issues by stage, their facets (fields, types, edges),
and the candidate list selection runs on.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

from concurrent.futures import ThreadPoolExecutor

import wf_core
from wf_config import field_name
from wf_io import EXIT_ENV, emit, eprint, gh_graphql, run
from wf_issue_io import issue_field_values
from wf_stage import _chunks


# ── candidate assembly ───────────────────────────────────────────────────────

def _norm_issue(raw):
    ms = raw.get('milestone')
    return {
        'number': raw['number'],
        'title': raw.get('title', ''),
        'labels': [l['name'] for l in raw.get('labels', [])],
        'body': raw.get('body', '') or '',
        'milestone': ms['title'] if ms else None,
        'url': raw.get('url', ''),
    }


# GitHub caps a connection page at 100 records, so the open-issue read pages.
STAGE_PAGE_SIZE = 100
# A run that still has pages left when it reaches this cap is an error rather
# than a short answer -- see `stage_issues`.
STAGE_MAX_PAGES = 20


def _stage_issues_query(paged, extra=''):
    """The open-issues query, with the `after:` clause only when paging.

    `extra` is appended to the `Issue` selection. `unblock` asks for the native
    `blockedBy` edges that way, so reading every blocked issue and reading each
    one's dependencies is one request rather than one plus one per issue.
    """
    return (
        'query($owner:String!,$repo:String!%s){'
        ' repository(owner:$owner,name:$repo){'
        '  issues(first:%d,states:OPEN,orderBy:{field:CREATED_AT,direction:ASC}%s){'
        '   pageInfo { hasNextPage endCursor }'
        '   nodes {'
        '    id number title body url'
        '    labels(first:20){ nodes { name } }'
        '    milestone { title }'
        '    assignees(first:1){ nodes { login } }'
        '    issueFieldValues(first:50){ nodes {'
        '     ... on IssueFieldSingleSelectValue {'
        '      field { ... on IssueFieldSingleSelect { name } } name }'
        '     ... on IssueFieldMultiSelectValue {'
        '      field { ... on IssueFieldMultiSelect { name } } options { name } } } }'
        '    %s'
        '   } } } }'
        % (',$cursor:String!' if paged else '', STAGE_PAGE_SIZE,
           ',after:$cursor' if paged else '', extra))


# What the pick pool reads about each open issue beyond the basics: its type,
# where it sits in the Epic and Feature tree, what blocks it, and whether an
# open pull request already closes it. One paged query covers all of it, so a
# pick costs the same few requests on a repository of any size.
POOL_SELECTION = (
    'issueType { name }'
    ' parent { number repository { nameWithOwner } }'
    ' subIssues(first:50){ totalCount nodes { number state'
    '  repository { nameWithOwner } } }'
    ' blockedBy(first:20){ totalCount nodes { number state title } }'
    ' closedByPullRequestsReferences(first:5){ totalCount nodes { number state } }'
)


def _tree_facts(node, repo):
    """The pool's facts about one issue node; empty for what was not asked.

    A parent or sub-issue in another repository is dropped, because its number
    means a different issue here.
    """
    facts = {}
    if 'issueType' in node:
        facts['type'] = (node.get('issueType') or {}).get('name')
    if 'parent' in node:
        parent = node.get('parent') or {}
        home = (parent.get('repository') or {}).get('nameWithOwner')
        facts['parent'] = (parent.get('number')
                           if parent and (not home or home == repo) else None)
    if 'subIssues' in node:
        subs = node.get('subIssues') or {}
        facts['sub_issues'] = {
            'total': subs.get('totalCount') or 0,
            'open': [c['number'] for c in subs.get('nodes') or []
                     if c and (c.get('state') or '').upper() == 'OPEN'
                     and ((c.get('repository') or {}).get('nameWithOwner')
                          in (None, repo))]}
    if 'closedByPullRequestsReferences' in node:
        conn = node.get('closedByPullRequestsReferences') or {}
        refs = conn.get('nodes') or []
        facts['open_prs'] = [p['number'] for p in refs
                             if p and (p.get('state') or '').upper() == 'OPEN']
        # A merged pull request that closes the issue means the work already
        # landed. Read here, the claim does not need its own scan of the
        # repository's merged pull requests to find out; only a read that
        # could not see every reference falls back to that scan.
        facts['merged_prs'] = sorted(p['number'] for p in refs
                                     if p and (p.get('state') or '').upper() == 'MERGED')
        total = conn.get('totalCount')
        facts['prs_complete'] = total is not None and total <= len(refs)
    return facts


def stage_issues(cfg, stages, unassigned_only=True, extra=''):
    """The open issues whose `Stage` is one of `stages`. (ok, issues, err).

    `stages` is a collection of option names, and `''` in it means a blank
    `Stage`, which is how the pool asks for "nobody has decided anything about
    this yet" beside `Backlog`. `unassigned_only` is what the pick pool wants
    -- an assigned issue is somebody's already -- and what `unblock` does not:
    a blocked issue can still carry the assignee it had when it was blocked,
    and skipping it would leave it blocked for good.

    The repository is the source, not a board. Until 12.0.0 the pool was a
    board column, so an issue with no card could not be picked at all and a
    board past its item limit could not be read. An issue holds its own state
    now, so the only thing that can hide one is the page cap, and reaching it
    is an error rather than a short pool.
    """
    stage_field = field_name(cfg, 'field-stage')
    # `stages=None` is every open issue, whatever its stage: the pick pool
    # judges them all, and a parent's stage decides its children.
    wanted = None if stages is None else {(s or '').strip().lower() for s in stages}
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    issues, cursor, pages = [], None, 0
    while True:
        if pages >= STAGE_MAX_PAGES:
            # A partial read is not a partial pool, it is an unknown one: the
            # issues this run never saw could be the whole of it.
            return False, None, (
                'the repository has more than %d open issues, which is more '
                'than one pass reads, so the issues in %s cannot be listed '
                'completely' % (STAGE_PAGE_SIZE * STAGE_MAX_PAGES,
                                'every stage' if stages is None else
                                wf_core._names(sorted(s or 'no stage'
                                                      for s in stages))))
        args = {'owner': cfg['org'], 'repo': cfg['repo']}
        if cursor:
            args['cursor'] = cursor
        ok, data, err = gh_graphql(_stage_issues_query(bool(cursor), extra),
                                   **args)
        if not ok or not data:
            return False, None, 'open-issue query failed: %s' % err
        try:
            connection = data['repository']['issues']
            nodes = connection['nodes']
        except (KeyError, TypeError):
            return False, None, 'unexpected open-issue response shape'
        for node in nodes:
            if not node or not node.get('number'):
                continue
            stage = issue_field_values(node).get(stage_field) or ''
            if wanted is not None and stage.strip().lower() not in wanted:
                continue
            assignees = (node.get('assignees') or {}).get('nodes') or []
            if unassigned_only and assignees:
                continue
            milestone = node.get('milestone')
            issues.append(dict(_tree_facts(node, repo), **{
                'id': node.get('id'),
                # Every field value, so the pick needs no second query for
                # Priority, Effort, Ownership or Classification.
                'fields': issue_field_values(node),
                'number': node['number'],
                'title': node.get('title', ''),
                'labels': [l['name'] for l
                           in (node.get('labels') or {}).get('nodes') or []],
                'body': node.get('body', '') or '',
                'milestone': milestone.get('title') if milestone else None,
                'url': node.get('url', ''),
                'stage': stage or None,
                'assigned': bool(assignees),
                'assignees': [a.get('login') for a in assignees if a.get('login')],
                'blockedBy': node.get('blockedBy') or {},
            }))
        pages += 1
        page_info = connection.get('pageInfo') or {}
        cursor = page_info.get('endCursor')
        if not page_info.get('hasNextPage') or not cursor:
            return True, issues, ''


# -- org capability resolution -----------------------------------------------


# GitHub caps a connection page at 100 records -- asking for more is an
# `EXCESSIVE_PAGINATION` error, not a truncated answer, so the whole query
# fails.
FACET_PAGE_SIZE = 100
FACET_MAX_PAGES = 20

# Issues per aliased request when the caller names them. The same twenty as
# every other aliased read here, for the same reason: GitHub's complexity
# budget.
FACET_BATCH = 20

_FACET_SELECTION = (
    ' number issueType { name }'
    ' issueFieldValues(first:20){ nodes {'
    '  ... on IssueFieldSingleSelectValue {'
    '   field { ... on IssueFieldSingleSelect { name } } name }'
    '  ... on IssueFieldMultiSelectValue {'
    '   field { ... on IssueFieldMultiSelect { name } } options { name } }'
    ' } }'
)


def _facets_query(paged):
    """The open-issue facets query, with the `after:` clause only when paging."""
    return (
        'query($owner:String!,$repo:String!%s){'
        ' repository(owner:$owner,name:$repo){'
        '  issues(first:%d,states:OPEN,orderBy:{field:CREATED_AT,direction:DESC}%s){'
        '   pageInfo { hasNextPage endCursor }'
        '   nodes {%s'
        '   } } } }'
        % (',$cursor:String!' if paged else '', FACET_PAGE_SIZE,
           ',after:$cursor' if paged else '', _FACET_SELECTION))


def _read_facets(node, facets, fields):
    """Fold one issue node into the facet maps."""
    number = node.get('number')
    if number is None:
        return
    native = node.get('issueType') or {}
    if native.get('name'):
        facets['types'][number] = native['name']
    values = issue_field_values(node)
    for key, field in fields.items():
        if values.get(field):
            facets[key][number] = values[field]


def fetch_issue_facets(cfg, numbers=None, priority_field='Priority',
                       classification_field='Classification',
                       effort_field='Effort', ownership_field='Ownership',
                       stage_field='Stage'):
    """Every structured field a decision reads, for the issues it decides about.

    Returns (ok, facets, err) where facets is ``{'types', 'priority',
    'classification', 'effort', 'ownership', 'stage'}``, each a
    ``{number: value}`` map.

    One query for all of them because the picker needs all of them about the
    same row: the type to filter the pool, Priority and Effort to order it,
    Effort again for a size ceiling, Ownership to keep work a code agent cannot
    do out of a code agent's pool, Classification to tell a `Feature` that is
    tech debt from one that is a new feature, and Stage to say what state the
    issue is in.

    **Pass `numbers` whenever the caller knows them.** Without it this reads the
    repository's open issues newest-first, and the window used to be two pages:
    on a repository with more than two hundred open issues, an older pool issue
    had no `Ownership` value in the map, was dropped by the pool filter as
    unowned, and was named nowhere. Naming the pool's own numbers removes the
    window entirely.

    A failure is a failure. There is no label fallback left to degrade to since
    10.0.0 -- an empty ownership map means an empty pool, which reads exactly
    like a finished backlog -- so the caller is told, and stops.
    """
    fields = {'priority': priority_field, 'classification': classification_field,
              'effort': effort_field, 'ownership': ownership_field,
              'stage': stage_field}
    facets = {'types': {}, 'priority': {}, 'classification': {},
              'effort': {}, 'ownership': {}, 'stage': {}}

    if numbers is not None:
        ordered = sorted({int(n) for n in numbers})
        for chunk in _chunks(ordered, FACET_BATCH):
            parts = ['f%d: issue(number:%d){%s }' % (n, n, _FACET_SELECTION)
                     for n in chunk]
            ok, data, err = gh_graphql(
                'query($owner:String!,$repo:String!){'
                ' repository(owner:$owner,name:$repo){ %s } }' % ' '.join(parts),
                owner=cfg['org'], repo=cfg['repo'])
            if not ok or not data:
                return False, facets, 'issue facet query failed: %s' % err
            repo = data.get('repository') or {}
            for number in chunk:
                node = repo.get('f%d' % number)
                if node:
                    _read_facets(node, facets, fields)
        return True, facets, ''

    cursor, pages = None, 0
    while pages < FACET_MAX_PAGES:
        args = {'owner': cfg['org'], 'repo': cfg['repo']}
        if cursor:
            args['cursor'] = cursor
        ok, data, err = gh_graphql(_facets_query(bool(cursor)), **args)
        if not ok or not data:
            return False, facets, 'issue facet query failed: %s' % err
        try:
            connection = data['repository']['issues']
            nodes = connection['nodes']
        except (KeyError, TypeError):
            return False, facets, 'unexpected issue facet response shape'
        for node in nodes:
            _read_facets(node, facets, fields)
        pages += 1
        page_info = connection.get('pageInfo') or {}
        if not page_info.get('hasNextPage'):
            break
        cursor = page_info.get('endCursor')
        if not cursor:
            break
        if pages >= FACET_MAX_PAGES:
            return False, facets, (
                'this repository has more than %d open issues, which is more '
                'than one pass reads' % (FACET_PAGE_SIZE * FACET_MAX_PAGES))
    return True, facets, ''


def report_unprioritised(pool, priority_map):
    """Name the candidates carrying no Priority, which therefore sort last.

    There is no second opinion to fall back on since 10.0.0: `Priority` is the
    whole of the pool's order, so an issue without one is not ordered by a
    label instead, it goes to the back. That is a silent demotion -- the issue
    is pickable, it is just never the pick -- so it is said out loud.

    Only when the org clearly has the field, which is when some other candidate
    carried a value. Silence otherwise: an empty field on an org that has no
    such field is a configuration finding, and `config-audit` is where it
    belongs.
    """
    if not pool or not priority_map:
        return
    missing = sorted(c['number'] for c in pool if not priority_map.get(c['number']))
    if not missing:
        return
    eprint('wf: %d candidate(s) have no Priority field value and sort last: '
           '%s (run `wf issue-audit`, then `wf issue-apply` on the spec it '
           'writes, to backfill)'
           % (len(missing), ', '.join('#%d' % n for n in missing)))


def facets_from_issues(cfg, issues, numbers):
    """The facet maps for `numbers`, built from issues the pool query already
    read with their field values and type. No request."""
    fields = {'priority': field_name(cfg, 'field-priority'),
              'classification': field_name(cfg, 'field-type'),
              'effort': field_name(cfg, 'field-effort'),
              'ownership': field_name(cfg, 'field-ownership'),
              'stage': field_name(cfg, 'field-stage')}
    facets = {'types': {}, 'priority': {}, 'classification': {},
              'effort': {}, 'ownership': {}, 'stage': {}}
    wanted = {int(n) for n in numbers}
    for issue in issues:
        number = issue['number']
        if number not in wanted:
            continue
        if issue.get('type'):
            facets['types'][number] = issue['type']
        values = issue.get('fields') or {}
        for key, field in fields.items():
            if values.get(field):
                facets[key][number] = values[field]
    return facets


def load_issue_facets(cfg, numbers=None, issues=None):
    """`fetch_issue_facets` for this project's field names, or stop.

    When `issues` came from the pool query, which reads every field value and
    the type with each issue, the maps are built from them and nothing is
    requested. That was a second round trip on every pick.

    A failure ends the run rather than returning empty maps. Empty maps used to
    be the fallback, from when a label could answer these questions: with no
    `Ownership` value for anything, every candidate is filtered out, and the
    command reports `no-candidates` -- a finished backlog -- because a query
    failed. There is nothing left to fall back to, so there is nothing to
    report but the failure.
    """
    if issues is not None and numbers is not None:
        wanted = {int(n) for n in numbers}
        read = [i for i in issues if i['number'] in wanted]
        if len(read) == len(wanted) and all('fields' in i and 'type' in i
                                            for i in read):
            return facets_from_issues(cfg, read, wanted)
    ok, facets, err = fetch_issue_facets(cfg, numbers,
                                         field_name(cfg, 'field-priority'),
                                         field_name(cfg, 'field-type'),
                                         field_name(cfg, 'field-effort'),
                                         field_name(cfg, 'field-ownership'),
                                         field_name(cfg, 'field-stage'))
    if not ok:
        emit('error', EXIT_ENV,
             reason='could not read the issue fields every decision here is '
                    'made from (%s), so nothing about this backlog is known. '
                    'Check the token and re-run.' % err)
    return facets


def assemble_candidates(cfg):
    """Fetch every open issue the pool is judged from. (ok, issues, err).

    Every stage, assigned or not, since 12.4.0: `wf_core.evaluate_pool`
    decides what is pickable, and it needs the issues that are not, because a
    Parked Epic holds back the stories under it and a Feature is pickable only
    through its stories. Each issue carries `POOL_SELECTION`'s facts. No board
    is read.

    This replaced four `ready-gate` settings -- `label`, `board-column`,
    `both`, `none` -- of which three required an issue to be explicitly marked
    before anything would look at it. That was the opt-in model, and it fails
    silently in the one way nobody checks: on this plugin's own repository,
    three workable issues sat unassigned in the backlog while `wf pick`
    reported an empty pool, because nobody had applied `status-ready`.

    Everything with a blank or `Backlog` stage is available unless a structured
    field says otherwise. `Stage` holds one value, so an issue that is in
    progress, in review, blocked, parked, awaiting refinement or done says so
    and is not here, with no exclusion list needed. Until 12.0.0 the pool was a
    board column, so an issue with no card could not be picked at all; the
    state lives on the issue now, and no board is needed to read it.
    """
    return stage_issues(cfg, None, unassigned_only=False, extra=POOL_SELECTION)


def claimed_issue_numbers():
    """The issue numbers a claim ref holds on the remote. One `ls-remote`.

    An unreadable remote is an empty set, said out loud: the claim itself is
    atomic, so a candidate somebody holds is still refused when it is claimed.
    """
    code, out, err = run(['git', 'ls-remote', 'origin', 'refs/claims/issue-*'])
    if code != 0:
        eprint('wf: could not list claim refs (%s); a held issue is refused at '
               'claim instead' % (err.strip() or 'git ls-remote failed'))
        return set()
    found = set()
    for line in out.splitlines():
        ref = line.split()[-1] if line.split() else ''
        suffix = ref[len('refs/claims/issue-'):] if ref.startswith('refs/claims/issue-') else ''
        if suffix.isdigit():
            found.add(int(suffix))
    return found


def read_pool(cfg):
    """The open issues and the held claim refs, read at the same time.

    (ok, issues, err, claimed). The two are independent -- a GraphQL read and
    a `git ls-remote` -- so running them one after the other only added the
    shorter one's wait to every pick.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        issues_future = pool.submit(assemble_candidates, cfg)
        claimed_future = pool.submit(claimed_issue_numbers)
        ok, issues, err = issues_future.result()
        claimed = claimed_future.result()
    return ok, issues, err, claimed


def _prefilter_numbers(issues, claimed):
    """The issues whose fields are worth reading: rules 1 and 2 of the pool,
    which need no field, plus every unassigned `Blocked` issue, because a
    story waiting on an issue lends its priority to that issue and can join a
    set beside it. Everything else is out whatever its fields say."""
    blocked = wf_core.STAGE_NAMES['stage-blocked']
    return [i['number'] for i in issues
            if (wf_core.is_available_stage(i.get('stage'))
                or wf_core.stage_name(i.get('stage')) == blocked)
            and not i.get('assigned') and i['number'] not in claimed
            and not i.get('open_prs')]


def pool_verdict(cfg, args, issues, claimed, facets, type_map, classification_map):
    """Run `wf_core.evaluate_pool` for this project. (backlog_mode, verdict).

    Sprint narrowing applies to the ranked list, as it did to the pool.
    """
    verdict = {}

    def selector(pool_issues):
        verdict.update(wf_core.evaluate_pool(
            pool_issues, mode=args.mode, type_map=type_map,
            classification_map=classification_map,
            priority_map=facets['priority'], effort_map=facets['effort'],
            ownership_map=facets['ownership'], claimed=claimed,
            max_effort=getattr(args, 'max_effort', None)))
        return verdict['ranked']

    backlog_mode, ranked = ordered_pool(cfg, issues, selector)
    verdict['ranked'] = ranked
    verdict['pool'] = [e for e in ranked if not e.get('unclear')]
    return backlog_mode, verdict


def ordered_pool(cfg, issues, selector):
    """The filtered, sorted pool, narrowed to a sprint when one applies.

    Returns (backlog_mode, pool). Filtering runs first and narrowing second,
    which is the opposite of the order this ran in until 10.1.2, and the reason
    is that a milestone is not an eligibility rule: narrowing first meant that
    a sprint whose only pool issues were owned by a person produced an empty
    pool and `no-candidates`, while pickable work sat in the next milestone.
    For the same reason a sprint that holds nothing this agent may take falls
    back to the flat pool rather than to nothing.
    """
    pool = selector(issues)
    mode, narrowed = narrow_to_sprint(cfg, pool)
    if mode == 'sprint' and narrowed:
        return mode, narrowed
    return 'flat', pool


def narrow_to_sprint(cfg, issues):
    """If any candidate has a milestone, narrow to the earliest open sprint."""
    if wf_core.detect_backlog_mode(issues) != 'sprint':
        return 'flat', issues
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    # `--jq .[0].title` emits a *raw* (unquoted) string, not JSON, so read
    # stdout directly rather than through gh_json's json.loads.
    code, out, err = run(['gh', 'api', 'repos/%s/milestones' % repo,
                          '--jq', 'sort_by(.due_on) | map(select(.open_issues > 0)) | .[0].title'])
    sprint = out.strip()
    if code != 0 or not sprint or sprint == 'null':
        # Can't resolve the active sprint — fall back to the flat pool.
        eprint('wf: could not resolve active sprint (%s); using flat pool' % (err.strip() or 'none open'))
        return 'flat', issues
    return 'sprint', wf_core.get_sprint_candidates(issues, sprint)
