"""
Reading, writing and verifying single issues: read-back, batched create and
link mutations, type and field writes.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import json

import wf_core
from wf_io import gh_graphql, run


# ── issue-apply ──────────────────────────────────────────────────────────────
# One command that creates or updates an issue with everything on it: native
# type, every org field value, parent, labels, and its blocked-by edges.
#
# It replaces roughly ten hand-run round trips per issue, each of which the
# markdown it came from described as optional. The measured result of "optional"
# across one consuming repo was 7 typed issues out of 82 and no field values at
# all, with no error anywhere. So this command is deliberately strict: it
# refuses a spec that omits metadata the org defines, and it reads every write
# back rather than trusting that an accepted mutation did something.

# The selection every read-back uses. A mutation payload can carry it too, so
# `createIssue` returns the issue *as GitHub now holds it* — which turns
# verification from an extra round trip per issue into a free one.
ISSUE_FIELD_VALUES_SELECTION = (
    '  issueFieldValues(first:50){ nodes {'
    '   __typename'
    '   ... on IssueFieldSingleSelectValue { field { ... on IssueFieldSingleSelect { name } } name }'
    '   ... on IssueFieldMultiSelectValue { field { ... on IssueFieldMultiSelect { name } } options { name } }'
    '   ... on IssueFieldTextValue { field { ... on IssueFieldText { name } } value }'
    '   ... on IssueFieldDateValue { field { ... on IssueFieldDate { name } } value }'
    '   ... on IssueFieldNumberValue { field { ... on IssueFieldNumber { name } } value }'
    '  } }'
)

ISSUE_SELECTION = (
    '  id number title body url'
    '  repository { nameWithOwner }'
    '  issueType { name }'
    '  milestone { title }'
    '  parent { number issueType { name } }'
    '  blockedBy(first:50){ totalCount nodes { number repository { nameWithOwner } } }'
    '  labels(first:50){ nodes { name } }'
    + ISSUE_FIELD_VALUES_SELECTION
)

ISSUE_READBACK_QUERY = (
    'query($owner:String!,$repo:String!,$number:Int!){'
    ' repository(owner:$owner,name:$repo){ issue(number:$number){'
    + ISSUE_SELECTION +
    ' } } }'
)


def read_issue(cfg, number, repo=None):
    """Read an issue's current type, fields, parent and blockers. (ok, issue, err)."""
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    ok, data, err = gh_graphql(ISSUE_READBACK_QUERY, owner=owner, repo=name,
                               number=int(number))
    if not ok:
        return False, None, err
    issue = ((data or {}).get('repository') or {}).get('issue')
    if not issue:
        return False, None, 'issue #%s not found in %s/%s' % (number, owner, name)
    return True, issue, ''


def issue_field_values(issue):
    """Flatten a read-back into {field name: value}, comparable to a spec.

    Single-select and text come back as one value, multi-select as a sorted
    list, so a spec's `["New Feature"]` and the API's option list compare
    directly without the caller re-deriving the shape per field type.
    """
    out = {}
    for node in ((issue.get('issueFieldValues') or {}).get('nodes')) or []:
        # A value whose type matches none of the query's inline fragments
        # comes back as null. `createIssue`'s inline payload returned one in a
        # batched create, and crashing here stopped the run after the issues
        # were written and before their edges and `Stage` were.
        if not isinstance(node, dict):
            continue
        field = (node.get('field') or {}).get('name')
        if not field:
            continue
        if 'options' in node:
            out[field] = sorted(o['name'] for o in node.get('options') or [])
        elif 'name' in node:
            out[field] = node.get('name')
        else:
            out[field] = node.get('value')
    return out


def _values_match(wanted, actual):
    """Whether a spec value and a read-back value are the same, shape-insensitively."""
    if isinstance(wanted, (list, tuple)) or isinstance(actual, (list, tuple)):
        as_list = lambda v: sorted(v) if isinstance(v, (list, tuple)) else (
            [] if v is None else [v])
        return as_list(wanted) == as_list(actual)
    return str(wanted) == str(actual)


def resolve_spec_context(cfg, label_names, numbers, repo=None,
                         milestone_titles=None):
    """One lookup for everything the batches need before they can be built.

    The repository's node id, the id of every label and open milestone the
    spec names, and the node id of every issue the spec references but does not
    create. Doing this as one query rather than four keeps the whole
    prerequisite phase to a single round trip, which is what leaves room for
    the epic tree itself.

    Returns (ok, context, err).
    """
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    wanted = sorted({int(n) for n in numbers})
    aliases = [('n%d' % n, n) for n in wanted]
    # The native type comes back with the id because the hierarchy rule needs
    # it: a spec that parents a `User Story` to an existing issue is only legal
    # when that issue is a `Feature`, and this is the one place the referenced
    # issues are read. The title and field values come back for the update
    # rules: an update names only what it changes, so whether it leaves the
    # issue without a required value, or two parties on one issue, is only
    # knowable against what the issue already carries.
    issue_parts = ' '.join(
        '%s: issue(number:%d){ id number title issueType { name }'
        ' parent { number issueType { name } }%s }'
        % (alias, number, ISSUE_FIELD_VALUES_SELECTION)
        for alias, number in aliases)
    ok, data, err = gh_graphql(
        'query($owner:String!,$repo:String!){'
        ' repository(owner:$owner,name:$repo){ id'
        ' labels(first:100){ nodes { id name } }'
        ' milestones(first:100,states:OPEN){ nodes { id title } } %s } }'
        % issue_parts,
        owner=owner, repo=name)
    if not ok:
        return False, None, err

    repository = (data or {}).get('repository')
    if not repository:
        return False, None, 'repository %s/%s not found' % (owner, name)

    have_labels = {n['name']: n['id'] for n
                   in (repository.get('labels') or {}).get('nodes') or []}
    wanted_milestones = sorted(set(milestone_titles or ()))
    have_milestones = {n['title']: n['id'] for n
                       in (repository.get('milestones') or {}).get('nodes') or []}
    issues = {}
    issue_types = {}
    issue_parents = {}
    issue_live = {}
    missing_issues = []
    for alias, number in aliases:
        node = repository.get(alias)
        if node:
            issues[number] = node['id']
            issue_types[number] = (node.get('issueType') or {}).get('name')
            issue_live[number] = {'title': node.get('title') or '',
                                  'fields': issue_field_values(node)}
            parent = node.get('parent') or {}
            issue_parents[number] = (
                parent.get('number'),
                (parent.get('issueType') or {}).get('name'))
        else:
            missing_issues.append(number)

    return True, {
        'repo_id': repository['id'],
        'repo': '%s/%s' % (owner, name),
        'labels': {n: have_labels[n] for n in label_names if n in have_labels},
        'missing_labels': [n for n in label_names if n not in have_labels],
        'milestones': {t: have_milestones[t] for t in wanted_milestones
                       if t in have_milestones},
        'missing_milestones': [t for t in wanted_milestones
                               if t not in have_milestones],
        'issues': issues,
        'issue_types': issue_types,
        'issue_parents': issue_parents,
        'issue_live': issue_live,
        'missing_issues': missing_issues,
    }, ''


def resolve_issue_ids(cfg, numbers, repo=None):
    """Node id for each issue number given. Returns {number: id}.

    Only the ids, and only for issues the caller already knows exist — the
    edge-removal path needs a node id for a blocker the spec no longer names,
    which by definition was not in the spec's own resolve pass. A number that
    cannot be read is left out rather than guessed at, and the caller reports
    the edge it could not remove.
    """
    wanted = sorted({int(n) for n in numbers})
    if not wanted:
        return {}
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    found = {}
    for start in range(0, len(wanted), EDGE_BATCH):
        window = wanted[start:start + EDGE_BATCH]
        parts = ' '.join('n%d: issue(number:%d){ id number }' % (n, n)
                         for n in window)
        ok, data, _err = gh_graphql(
            'query($owner:String!,$repo:String!){'
            ' repository(owner:$owner,name:$repo){ %s } }' % parts,
            owner=owner, repo=name)
        if not ok:
            continue
        repository = (data or {}).get('repository') or {}
        for number in window:
            node = repository.get('n%d' % number)
            if node and node.get('id'):
                found[number] = node['id']
    return found


def _mutation_result(code, out, err, path):
    """Unwrap a `gh api graphql` mutation response. Returns (ok, node, err)."""
    try:
        parsed = json.loads(out) if (out or '').strip() else None
    except json.JSONDecodeError as exc:
        return False, None, 'could not parse GraphQL JSON: %s' % exc
    if parsed and parsed.get('errors'):
        return False, None, json.dumps(parsed['errors'])
    if code != 0:
        return False, None, (err or '').strip() or 'mutation failed'
    node = (parsed or {}).get('data') or {}
    for step in path:
        node = (node or {}).get(step)
    return (True, node, '') if node else (False, None, 'mutation returned no %s'
                                          % path[-1])


def _graphql_json(query, variables):
    """Send a mutation whose variables include lists or objects.

    `_graphql_args` types each variable as a GraphQL scalar, which is right for
    the query path but cannot express a list of input objects — and stringifying
    one into the mutation body is what defeated the earlier `-f fields='[...]'`
    attempts. Sending a JSON request body keeps the types intact.
    """
    code, out, err = run(['gh', 'api', 'graphql', '--input', '-'],
                         input_text=json.dumps({'query': query,
                                                'variables': variables}))
    return code, out, err


def _batch_result(code, out, err, aliases, field='issue'):
    """Unwrap an aliased multi-mutation. Returns {alias: (ok, node, err)}.

    GraphQL answers a partial failure with the aliases that worked in `data`
    and an error carrying the path of each one that did not, so a batch reports
    per-entry outcomes rather than collapsing to one verdict. That is what lets
    the caller say which issues landed.
    """
    try:
        parsed = json.loads(out) if (out or '').strip() else None
    except json.JSONDecodeError as exc:
        parsed = None
        err = 'could not parse GraphQL JSON: %s' % exc
    data = (parsed or {}).get('data') or {}
    by_alias = {}
    for entry in (parsed or {}).get('errors') or []:
        path = entry.get('path') or []
        if path:
            by_alias.setdefault(path[0], entry.get('message', 'mutation failed'))

    out_map = {}
    for alias in aliases:
        node = (data.get(alias) or {}).get(field) if data.get(alias) else None
        if node:
            out_map[alias] = (True, node, '')
        else:
            out_map[alias] = (False, None, by_alias.get(alias)
                              or (err or '').strip()
                              or ('mutation failed' if code else 'mutation returned nothing'))
    return out_map


# Comments per aliased `addComment` request: GitHub's complexity budget, as
# for every other aliased write here.
COMMENT_BATCH = 20


def add_comments(comments):
    """Post many issue comments in one mutation. {number: (posted, message)}.

    `comments` is {issue number: (issue node id, body)}. One request per
    twenty comments, where `gh issue comment` was one each.
    """
    out = {n: (False, 'could not read the issue node id')
           for n, (node_id, _body) in comments.items() if not node_id}
    live = sorted(n for n, (node_id, _body) in comments.items() if node_id)
    for start in range(0, len(live), COMMENT_BATCH):
        chunk = live[start:start + COMMENT_BATCH]
        decls, body, variables = [], [], {}
        for n in chunk:
            decls.append('$c%d_s:ID!,$c%d_b:String!' % (n, n))
            body.append('c%d: addComment(input:{subjectId:$c%d_s,body:$c%d_b})'
                        '{ subject { id } }' % (n, n, n))
            variables['c%d_s' % n], variables['c%d_b' % n] = comments[n]
        code, raw, err = _graphql_json('mutation(%s){ %s }' % (','.join(decls),
                                                                ' '.join(body)),
                                       variables)
        results = _batch_result(code, raw, err, ['c%d' % n for n in chunk],
                                field='subject')
        for n in chunk:
            posted, _node, why = results['c%d' % n]
            out[n] = (True, 'commented') if posted else (False, why)
    return out


def send_create_batch(inputs):
    """Create many issues in one request. Returns {alias: (ok, issue, err)}.

    Aliases cannot reference each other's output, which is exactly why the
    caller batches by hierarchy level: everything in one request is independent
    of everything else in it.
    """
    aliases = ['a%d' % n for n in range(len(inputs))]
    decls = ','.join('$%s:CreateIssueInput!' % a for a in aliases)
    body = ' '.join('%s: createIssue(input:$%s){ issue { %s } }'
                    % (a, a, ISSUE_SELECTION) for a in aliases)
    code, out, err = _graphql_json('mutation(%s){ %s }' % (decls, body),
                                   dict(zip(aliases, inputs)))
    return _batch_result(code, out, err, aliases)


def send_link_batch(ops):
    """Apply every dependency edge in one request.

    `ops` are (alias, kind, variables) with kind `'blocked-by'` to add an edge
    or `'unblocked-by'` to remove one. This is the last phase, run once every
    issue in the spec exists and every reference resolves. It used to carry
    body rewrites too, for the `## Dependencies` prose that mirrored these
    edges; the prose is gone and the edge is the whole record.
    """
    decls, body, aliases = [], [], []
    variables = {}
    for alias, kind, args in ops:
        aliases.append(alias)
        mutation = 'removeBlockedBy' if kind == 'unblocked-by' else 'addBlockedBy'
        decls.append('$%s_i:ID!,$%s_b:ID!' % (alias, alias))
        body.append('%s: %s(input:{issueId:$%s_i,blockingIssueId:$%s_b})'
                    '{ issue { id repository { nameWithOwner } blockedBy(first:%d){'
                    ' totalCount nodes { number repository { nameWithOwner } } } } }'
                    % (alias, mutation, alias, alias, EDGE_PAGE))
        variables['%s_i' % alias] = args['issue_id']
        variables['%s_b' % alias] = args['blocking_id']
    code, out, err = _graphql_json('mutation(%s){ %s }' % (','.join(decls),
                                                           ' '.join(body)),
                                   variables)
    return _batch_result(code, out, err, aliases)


def set_issue_type(issue_id, type_id):
    code, out, err = _graphql_json(
        'mutation($i:ID!,$t:ID!){ updateIssueIssueType(input:{issueId:$i,issueTypeId:$t})'
        '{ issue { id } } }', {'i': issue_id, 't': type_id})
    return _mutation_result(code, out, err, ['updateIssueIssueType', 'issue'])


def set_issue_fields(issue_id, field_inputs):
    # The trailing `!` on the variable's type is load-bearing. `issueFields` is
    # declared `[IssueFieldCreateOrUpdateInput!]!` on the input object, and
    # GraphQL refuses a nullable variable in a non-null position even when the
    # value passed is a perfectly good list -- "Nullability mismatch on variable
    # $f". Nothing about the value is wrong, so the failure reads as a data
    # problem and is not one. Every field write went through here, so while it
    # was missing no issue metadata reached GitHub at all.
    code, out, err = _graphql_json(
        'mutation($i:ID!,$f:[IssueFieldCreateOrUpdateInput!]!){'
        ' setIssueFieldValue(input:{issueId:$i,issueFields:$f}){ issue { id } } }',
        {'i': issue_id, 'f': list(field_inputs)})
    return _mutation_result(code, out, err, ['setIssueFieldValue', 'issue'])


def add_sub_issue(parent_id, child_id):
    code, out, err = _graphql_json(
        'mutation($p:ID!,$c:ID!){ addSubIssue(input:{issueId:$p,subIssueId:$c,'
        'replaceParent:true}){ issue { id } } }', {'p': parent_id, 'c': child_id})
    return _mutation_result(code, out, err, ['addSubIssue', 'issue'])


def add_blocked_by(issue_id, blocking_id):
    code, out, err = _graphql_json(
        'mutation($i:ID!,$b:ID!){ addBlockedBy(input:{issueId:$i,blockingIssueId:$b})'
        '{ issue { id } } }', {'i': issue_id, 'b': blocking_id})
    return _mutation_result(code, out, err, ['addBlockedBy', 'issue'])


def issue_mismatches(number, issue, plan, expect_type=None, expect_parent=None,
                     expect_blocked_by=(), expect_title=None, expect_body=None):
    """Compare an issue as GitHub holds it against what the spec asked for.

    A mutation GitHub accepts is not a value GitHub stored — an unpinned field,
    a silently-ignored id, a permission that stops short of writing. Every
    mismatch is named, because "the write succeeded and the value is not there"
    is precisely the failure that went unnoticed for months.

    Pure, so it serves both a read-back query and a mutation payload that
    carried the same selection.
    """
    mismatches = []
    if expect_type:
        got = (issue.get('issueType') or {}).get('name')
        if got != expect_type:
            mismatches.append("#%s: native type is %s, expected '%s'"
                              % (number, "'%s'" % got if got else 'unset', expect_type))

    actual = issue_field_values(issue)
    for field, spec in (plan.get('fields') or {}).items():
        if not _values_match(spec['value'], actual.get(field)):
            mismatches.append("#%s: field '%s' is %r, expected %r"
                              % (number, field, actual.get(field), spec['value']))

    if expect_parent:
        got = (issue.get('parent') or {}).get('number')
        if got != expect_parent:
            mismatches.append('#%s: parent is %s, expected #%s'
                              % (number, '#%s' % got if got else 'unset', expect_parent))

    # Local edges only: `org/other#5` is not the local #5 an entry names.
    have = set(wf_core.local_blocker_numbers(issue))
    for want in expect_blocked_by or ():
        if want not in have:
            mismatches.append('#%s: missing blocked-by edge to #%s' % (number, want))

    if expect_title is not None and not wf_core.same_text(expect_title,
                                                          issue.get('title')):
        mismatches.append("#%s: title is %r, expected %r"
                          % (number, issue.get('title'), expect_title))
    if expect_body is not None and not wf_core.same_text(expect_body,
                                                         issue.get('body')):
        mismatches.append('#%s: body is not the one the spec wrote' % number)

    return mismatches


def verify_issue(cfg, number, plan, expect_type=None, expect_parent=None,
                 expect_blocked_by=(), repo=None, expect_title=None,
                 expect_body=None):
    """Read the issue back and compare it. Returns (passed, mismatches)."""
    ok, issue, err = read_issue(cfg, number, repo)
    if not ok:
        return False, ['#%s: could not read back: %s' % (number, err)]
    mismatches = issue_mismatches(number, issue, plan, expect_type,
                                  expect_parent, expect_blocked_by,
                                  expect_title, expect_body)
    return not mismatches, mismatches


# How many blocked-by edges one read asks for. A full page is treated as "more
# than this can see" rather than as the whole set: releasing an issue because
# its first hundred blockers are closed, while the hundred-and-first is open,
# is the one mistake a dependency reader must not make.
EDGE_PAGE = 100


EDGE_BATCH = 20
