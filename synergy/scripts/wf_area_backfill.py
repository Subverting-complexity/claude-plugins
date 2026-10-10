"""
The `area-backfill` subcommand: copy each issue's area epic to an area label.

A repository that used area epics, which 19.0.0 removed, has its areas only
in the parent chain. This reads every issue, open and closed, resolves each to
the area epic above it, and adds the label the `## Areas` table gives that
epic. It is the one step that moves a repository from area epics to area
labels, so notes for an old release keep their headings after the epics are
closed. It is also the only command that reads an area epic.

The rules are in `wf_core_backfill.py`; this is the reading and the writing.
"""

import wf_core
from wf_candidates import STAGE_MIN_PAGE_SIZE, _resource_limited
from wf_config import field_name, prepare_cfg
from wf_io import EXIT_ENV, EXIT_OK, EXIT_PARTIAL, EXIT_SPEC, emit, gh_graphql, run
from wf_issue_io import _batch_result, _graphql_json
from wf_post_merge import STAGE_VALUES_SELECTION


# GitHub caps a connection page at 100 records. Each issue asks only for what
# the backfill needs, its type, parent, labels and `Stage`, so a full page
# normally fits the query's resource limit. When it does not, the read halves
# the page, as `stage_issues` does.
BACKFILL_PAGE_SIZE = 100

BACKFILL_QUERY = (
    'query($owner:String!,$repo:String!,$size:Int!,$after:String){'
    ' repository(owner:$owner,name:$repo){'
    '  issues(first:$size,after:$after,states:[OPEN,CLOSED],'
    '         orderBy:{field:CREATED_AT,direction:ASC}){'
    '   pageInfo { hasNextPage endCursor }'
    '   nodes { id number title state issueType { name }'
    '    parent { number repository { nameWithOwner } }'
    '    labels(first:30){ nodes { name } }'
    + STAGE_VALUES_SELECTION +
    '   } } } }'
)

BACKFILL_LABELS_QUERY = (
    'query($owner:String!,$repo:String!,$after:String){'
    ' repository(owner:$owner,name:$repo){'
    '  labels(first:100,after:$after){'
    '   pageInfo { hasNextPage endCursor } nodes { id name }'
    '  } } }'
)

# Labels per aliased `addLabelsToLabelable` request: GitHub's complexity
# budget, as for every other aliased write (`COMMENT_BATCH`).
BACKFILL_LABEL_BATCH = 20

BACKFILL_CLOSE_COMMENT = (
    'Closed by `wf area-backfill`. Each issue under this area epic now carries '
    'the label `%s`, and that label is its area from here on. The parent links '
    'are kept.')


def scan_all_issues(cfg, repo=None):
    """Every issue of the repository, open and closed. (ok, nodes, size, err).

    Paged, oldest first, so an issue filed during the read lands on the last
    page. `size` is the page size the read ended on: when GitHub answers
    RESOURCE_LIMITS_EXCEEDED the page is halved and the same cursor is asked
    again, down to `STAGE_MIN_PAGE_SIZE`, and the smaller size is kept. Nothing
    was read by the refused request, so nothing is skipped or read twice.

    There is no page cap: the backfill has to see every issue, and a partial
    read would leave closed issues without a label for good. A cursor that
    does not advance is an error, so the loop always ends.
    """
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    nodes, cursor, size = [], None, BACKFILL_PAGE_SIZE
    while True:
        fields = {'owner': owner, 'repo': name, 'size': size}
        if cursor:
            fields['after'] = cursor
        ok, data, err = gh_graphql(BACKFILL_QUERY, **fields)
        if not ok and _resource_limited(err) and size > STAGE_MIN_PAGE_SIZE:
            size = max(STAGE_MIN_PAGE_SIZE, size // 2)
            continue
        if not ok or not data:
            return False, None, size, 'issue query failed: %s' % err
        try:
            connection = data['repository']['issues']
            page = connection['nodes']
        except (KeyError, TypeError):
            return False, None, size, 'unexpected issue response shape'
        nodes.extend(n for n in page or [] if n and n.get('number'))
        info = connection.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return True, nodes, size, ''
        following = info.get('endCursor')
        if not following or following == cursor:
            return False, None, size, ('the issue read did not advance past '
                                       'cursor %s' % (cursor or 'the first page'))
        cursor = following


def fetch_label_ids(cfg, repo=None):
    """The node id of every label in the repository. (ok, {name: id}, err).

    Paged, so a repository with more than 100 labels is read whole: an area
    label on a page not read would look missing and stop the run.
    """
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    ids, cursor = {}, None
    while True:
        fields = {'owner': owner, 'repo': name}
        if cursor:
            fields['after'] = cursor
        ok, data, err = gh_graphql(BACKFILL_LABELS_QUERY, **fields)
        if not ok:
            return False, {}, err
        page = (((data or {}).get('repository') or {}).get('labels')) or {}
        for node in page.get('nodes') or []:
            if node and node.get('name') and node.get('id'):
                ids[node['name']] = node['id']
        info = page.get('pageInfo') or {}
        following = info.get('endCursor')
        if not info.get('hasNextPage') or not following or following == cursor:
            return True, ids, ''
        cursor = following


def add_area_labels(items):
    """Add one label to each of many issues. {number: (added, message)}.

    `items` is a list of `{'number', 'id', 'label_id'}`. One aliased request
    per twenty issues, where `gh issue edit --add-label` was one each. A batch
    answers per alias, so one issue that fails does not hide the ones beside
    it that landed. Adding a label an issue already carries is not an error,
    which is what makes a request safe to send again.
    """
    out = {i['number']: (False, 'could not read the issue or label node id')
           for i in items if not i.get('id') or not i.get('label_id')}
    live = [i for i in items if i['number'] not in out]
    for start in range(0, len(live), BACKFILL_LABEL_BATCH):
        chunk = live[start:start + BACKFILL_LABEL_BATCH]
        decls, body, variables = [], [], {}
        for item in chunk:
            n = item['number']
            decls.append('$l%d_i:ID!,$l%d_l:ID!' % (n, n))
            body.append('l%d: addLabelsToLabelable(input:{labelableId:$l%d_i,'
                        'labelIds:[$l%d_l]}){ labelable { __typename } }'
                        % (n, n, n))
            variables['l%d_i' % n] = item['id']
            variables['l%d_l' % n] = item['label_id']
        code, raw, err = _graphql_json(
            'mutation(%s){ %s }' % (','.join(decls), ' '.join(body)), variables)
        results = _batch_result(code, raw, err,
                                ['l%d' % i['number'] for i in chunk],
                                field='labelable')
        for item in chunk:
            added, _node, why = results['l%d' % item['number']]
            out[item['number']] = (True, 'labelled') if added else (False, why)
    return out


def close_area_epics(epics, repo):
    """Close each open area epic in `epics`. Returns (closed, failed).

    `gh issue close` and nothing else: the sub-issue links and the `Stage`
    are left as they are, so a later backfill run still resolves an issue
    through a closed epic.
    """
    closed, failed = [], []
    for number in sorted(epics):
        epic = epics[number]
        if epic['state'] != 'OPEN':
            continue
        code, _, err = run(['gh', 'issue', 'close', str(number), '--repo', repo,
                            '--reason', 'completed',
                            '--comment', BACKFILL_CLOSE_COMMENT % epic['label']])
        if code == 0:
            closed.append(number)
        else:
            failed.append({'number': number,
                           'reason': (err or '').strip() or 'gh failed'})
    return closed, failed


def cmd_area_backfill(args):
    """`wf area-backfill`: add its area label to each issue under an area epic."""
    cfg = prepare_cfg()
    repo = args.repo or '%s/%s' % (cfg['org'], cfg['repo'])
    rows = cfg.get('areas') or []
    if not rows:
        emit('error', EXIT_ENV, repo=repo,
             reason='ClaudeProject.md has no `## Areas` table, so no area epic '
                    'maps to a label')

    ok, nodes, size, err = scan_all_issues(cfg, repo)
    if not ok:
        emit('error', EXIT_ENV, repo=repo, page_size=size,
             reason='could not read the issues in %s: %s' % (repo, err))
    ok, label_ids, err = fetch_label_ids(cfg, repo)
    if not ok:
        emit('error', EXIT_ENV, repo=repo,
             reason='could not read the labels in %s: %s' % (repo, err))

    index = wf_core.backfill_index(nodes, field_name(cfg, 'field-stage'), repo)
    plan = wf_core.backfill_plan(index, rows, list(label_ids))
    fields = dict(repo=repo, scanned=len(index), page_size=size,
                  labelled=0, already=len(plan['already']),
                  counts=plan['counts'], no_area=plan['no_area'],
                  differs=plan['differs'], failed=[], epics_closed=[])

    stopped = wf_core.backfill_stopped(plan['stops'])
    if stopped:
        emit('refused', EXIT_SPEC, reason='nothing was written: %s'
             % '; '.join(stopped), stops=plan['stops'], **fields)

    open_epics = sorted(n for n, e in plan['epics'].items()
                        if e['state'] == 'OPEN')
    # The epics may close only when this run's own read found every issue
    # under them carrying its label. A run that wrote labels has not read
    # them back, so closing always takes a second run.
    clear = not plan['to_label'] and not plan['differs']
    if args.dry_run:
        emit('ok', EXIT_OK, dry_run=True, would_label=len(plan['to_label']),
             would_close=open_epics if clear else [], **fields)

    items = [dict(item, label_id=label_ids.get(item['label']))
             for item in plan['to_label']]
    results = add_area_labels(items)
    fields['labelled'] = sum(1 for added, _ in results.values() if added)
    fields['failed'] = [{'number': n, 'reason': why}
                        for n, (added, why) in sorted(results.items())
                        if not added]

    if args.close_epics:
        if clear:
            fields['epics_closed'], close_failed = close_area_epics(
                plan['epics'], repo)
            if close_failed:
                fields['close_failed'] = close_failed
        elif plan['to_label']:
            fields['close_refused'] = (
                'this run found %d issue%s to label, so no epic was closed; '
                'run `area-backfill --close-epics` again'
                % (len(plan['to_label']),
                   '' if len(plan['to_label']) == 1 else 's'))
        else:
            fields['close_refused'] = (
                '%d issue%s under an area epic carr%s another area label '
                '(`differs`), so no epic was closed; change the label or the '
                'parent, then run again'
                % (len(plan['differs']),
                   '' if len(plan['differs']) == 1 else 's',
                   'ies' if len(plan['differs']) == 1 else 'y'))

    if fields['failed'] or fields.get('close_failed'):
        emit('partial', EXIT_PARTIAL,
             reason='%d label%s and %d epic%s could not be written; run again '
                    'to finish'
                    % (len(fields['failed']),
                       '' if len(fields['failed']) == 1 else 's',
                       len(fields.get('close_failed') or []),
                       '' if len(fields.get('close_failed') or []) == 1 else 's'),
             **fields)
    emit('ok', EXIT_OK, **fields)
