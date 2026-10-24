"""
The REST fallback for a session where GraphQL is blocked: the open-issue
read the pick pool is judged from, one issue read, `Stage` writes with their
read-back, the field ids those writes need, the closed pull requests read a
page at a time, and the few issue edits a pick makes on the way (assign,
unassign, comment, close, remove a label).

`wf_io.graphql_blocked()` decides when these run. Each read returns its issues
in the shape the GraphQL query returns them, so everything after the read --
the pool rules, the claim walk, the facts a pick reports -- runs unchanged, and
the same pool gives the same pick either way.

Pull requests have their own fallback in `wf_rest_pr.py`, and settling the
issues a merge closes has its own in `wf_rest_settle.py`. `scripts/README.md`
has the module map.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import wf_core
from wf_capabilities import load_capability_cache, merge_capability_cache
from wf_config import field_name
from wf_io import gh_rest


# Records per page: the REST API's own ceiling.
REST_PAGE = 100
# Pages of open issues one read may take. The REST list counts pull requests
# as issues, so this is 2000 records in all, the same cap the GraphQL read
# has, and reaching it is an error rather than a short pool.
REST_MAX_PAGES = 20
# Requests in flight at once for the per-issue reads (blocked-by edges).
REST_WORKERS = 8
# Recently updated issues read to find a field id when nothing else had it.
FIELD_ID_SCAN = 100

# The capability cache key that keeps the REST field ids between runs.
FIELD_ID_CACHE_KEY = 'rest_field_ids'

# Field name -> REST field id, for this run. Every REST issue read fills it,
# so a `Stage` write after the pool read needs no lookup of its own.
_field_ids = {}


def _repo(cfg):
    return '%s/%s' % (cfg['org'], cfg['repo'])


def repo_of(url):
    """`owner/name` from a REST `.../repos/owner/name/...` URL, or None."""
    rest = (url or '').split('/repos/', 1)
    if len(rest) < 2:
        return None
    parts = rest[1].split('/')
    return '%s/%s' % (parts[0], parts[1]) if len(parts) >= 2 else None


def number_of(url):
    """The issue number that ends a REST issue URL, or None."""
    tail = (url or '').rstrip('/').rsplit('/', 1)[-1]
    return int(tail) if tail.isdigit() else None


# ── shaping REST issues as the GraphQL read returns them ─────────────────────

def remember_field_ids(values):
    """Keep the field id of every value a REST read returned."""
    for value in values or ():
        if isinstance(value, dict) and value.get('issue_field_name') \
                and value.get('issue_field_id') is not None:
            _field_ids[value['issue_field_name']] = value['issue_field_id']


def field_value_nodes(values):
    """REST `issue_field_values` as the GraphQL `issueFieldValues` connection,
    so `wf_issue_io.issue_field_values` flattens both the same way."""
    nodes = []
    for value in values or ():
        if not isinstance(value, dict) or not value.get('issue_field_name'):
            continue
        field = {'name': value['issue_field_name']}
        kind = value.get('data_type')
        if kind == 'single_select':
            option = value.get('single_select_option') or {}
            nodes.append({'field': field, 'name': option.get('name')})
        elif kind == 'multi_select':
            nodes.append({'field': field, 'options': [
                {'name': o.get('name')} for o in value.get('multi_select_options') or ()
                if isinstance(o, dict) and o.get('name')]})
        else:
            nodes.append({'field': field, 'value': value.get('value')})
    return {'nodes': nodes}


def edge_nodes(blockers):
    """REST `dependencies/blocked_by` issues as GraphQL `blockedBy` nodes."""
    return [{'number': b.get('number'), 'state': (b.get('state') or '').upper(),
             'title': b.get('title') or '',
             'repository': {'nameWithOwner': repo_of(b.get('repository_url')
                                                     or b.get('url'))}}
            for b in blockers or () if isinstance(b, dict) and b.get('number')]


def rest_issue_node(raw, repo, children=None, edges=None, closing=None):
    """One REST issue in the shape of the GraphQL pool query's node.

    `children` is the open sub-issues the same read found under it, `edges` its
    blocked-by connection and `closing` its closing pull request connection;
    a key is left out when it was not read, as the GraphQL node leaves out
    what the query did not ask for.
    """
    remember_field_ids(raw.get('issue_field_values'))
    milestone = raw.get('milestone')
    kind = raw.get('type')
    parent_url = raw.get('parent_issue_url')
    node = {
        'id': raw.get('node_id'),
        'number': raw.get('number'),
        'title': raw.get('title') or '',
        'body': raw.get('body') or '',
        'url': raw.get('html_url') or '',
        'state': (raw.get('state') or '').upper(),
        'labels': {'nodes': [{'name': l['name']} for l in raw.get('labels') or ()
                             if isinstance(l, dict) and l.get('name')]},
        'milestone': {'title': milestone.get('title')} if milestone else None,
        'assignees': {'nodes': [{'login': a['login']} for a in raw.get('assignees') or ()
                                if isinstance(a, dict) and a.get('login')]},
        'issueFieldValues': field_value_nodes(raw.get('issue_field_values')),
        'issueType': {'name': kind.get('name')} if isinstance(kind, dict) else None,
        'parent': ({'number': number_of(parent_url),
                    'repository': {'nameWithOwner': repo_of(parent_url)}}
                   if parent_url else None),
    }
    if children is not None:
        summary = raw.get('sub_issues_summary') or {}
        node['subIssues'] = {
            'totalCount': summary.get('total') or len(children),
            'nodes': [{'number': c, 'state': 'OPEN',
                       'repository': {'nameWithOwner': repo}} for c in children]}
    if edges is not None:
        node['blockedBy'] = edges
    if closing is not None:
        node['closedByPullRequestsReferences'] = closing
    return node


# ── reads ────────────────────────────────────────────────────────────────────

def _pages(path, max_pages=REST_MAX_PAGES):
    """Every record of a paged REST list. (ok, records, err).

    Reaching `max_pages` with pages left is an error, never a short answer.
    """
    records = []
    joiner = '&' if '?' in path else '?'
    for page in range(1, max_pages + 1):
        ok, items, err = gh_rest('%s%sper_page=%d&page=%d'
                                 % (path, joiner, REST_PAGE, page))
        if not ok:
            return False, None, err
        if not isinstance(items, list):
            return False, None, 'unexpected REST response for %s' % path
        records.extend(items)
        if len(items) < REST_PAGE:
            return True, records, ''
    return False, None, ('%s holds more than %d records, which is more than one '
                         'pass reads' % (path.split('?', 1)[0],
                                         REST_PAGE * max_pages))


def rest_blocked_by(cfg, number, total=None):
    """One issue's blocked-by edges as a GraphQL connection.

    A failed read keeps `totalCount` and no nodes, which every caller already
    reads as "not every edge was seen", so a failure never reads as unblocked.
    """
    ok, items, _err = gh_rest('repos/%s/issues/%d/dependencies/blocked_by?per_page=%d'
                              % (_repo(cfg), int(number), REST_PAGE))
    if not ok or not isinstance(items, list):
        return {'totalCount': max(1, total or 1), 'nodes': []}
    nodes = edge_nodes(items)
    count = total if total is not None else len(nodes)
    if len(items) >= REST_PAGE:
        # A full page may not be the whole set.
        count = max(count, len(nodes) + 1)
    return {'totalCount': count, 'nodes': nodes}


def rest_open_pr_closing(cfg):
    """{issue number: [open pull request number]} from the open pull requests'
    bodies. (ok, map, err).

    GraphQL reads GitHub's own parse of closing references. REST has no such
    field, so the keywords in each body are read instead, the way GitHub
    reads them.
    """
    ok, prs, err = _pages('repos/%s/pulls?state=open' % _repo(cfg))
    if not ok:
        return False, {}, err
    found = {}
    for pr in prs:
        for number in wf_core.body_closing_numbers(pr.get('body'), _repo(cfg)):
            found.setdefault(number, []).append(pr['number'])
    return True, found, ''


def rest_open_issue_nodes(cfg, pool_facts=True):
    """Every open issue, oldest first, as GraphQL pool nodes. (ok, nodes, err).

    Oldest first because the GraphQL read orders by creation date ascending,
    and the pool's tie-breaks see the issues in the order they are read.

    `pool_facts` adds what the pick pool reads beyond the basics: open
    sub-issues, blocked-by edges and the open pull requests that close each
    issue. The list endpoint carries the type, the parent and the field
    values, so the extra cost is one read of the open pull requests and one
    read per issue that has blockers.
    """
    repo = _repo(cfg)
    ok, records, err = _pages('repos/%s/issues?state=open&sort=created'
                              '&direction=asc' % repo)
    if not ok:
        return False, None, 'open-issue REST read failed: %s' % err
    raws = [r for r in records if isinstance(r, dict) and 'pull_request' not in r]
    if not pool_facts:
        return True, [rest_issue_node(r, repo) for r in raws], ''

    children = {}
    for raw in raws:
        url = raw.get('parent_issue_url')
        if url and repo_of(url) in (None, repo) and number_of(url):
            children.setdefault(number_of(url), []).append(raw['number'])

    with_edges = [r for r in raws
                  if ((r.get('issue_dependencies_summary') or {})
                      .get('total_blocked_by') or 0) > 0]
    with ThreadPoolExecutor(max_workers=REST_WORKERS) as pool:
        futures = {r['number']: pool.submit(
            rest_blocked_by, cfg, r['number'],
            r['issue_dependencies_summary']['total_blocked_by'])
            for r in with_edges}
        prs_future = pool.submit(rest_open_pr_closing, cfg)
        edges = {n: f.result() for n, f in futures.items()}
        prs_ok, closing, prs_err = prs_future.result()
    if not prs_ok:
        # On GraphQL the closing pull requests come in the same query as the
        # issues, so a failure fails the pool read. Going on without them
        # would offer an issue already in review as free work.
        return False, None, 'open pull request REST read failed: %s' % prs_err

    nodes = []
    for raw in raws:
        number = raw['number']
        conn = edges.get(number, {'totalCount': 0, 'nodes': []})
        # No merged pull request is known, so `totalCount` is left unknown and
        # the claim checks the merged pull requests itself.
        prs = {'totalCount': None,
               'nodes': [{'number': p, 'state': 'OPEN'}
                         for p in closing.get(number, ())]}
        nodes.append(rest_issue_node(raw, repo, children.get(number, []), conn, prs))
    return True, nodes, ''


def rest_read_issue(cfg, number):
    """One issue as a GraphQL node with its edges and open closing pull
    requests. (ok, node, err)."""
    ok, raw, err = gh_rest('repos/%s/issues/%d' % (_repo(cfg), int(number)))
    if not ok or not isinstance(raw, dict):
        return False, None, err or 'issue #%d not found' % int(number)
    return True, rest_issue_node(raw, _repo(cfg)), ''


def rest_dependency_facts(cfg, number):
    """`wf_deps.issue_dependency_facts` through REST, or {} on a failed read."""
    conn = rest_blocked_by(cfg, number)
    if not conn['nodes'] and conn['totalCount']:
        return {}
    ok, closing, _err = rest_open_pr_closing(cfg)
    if not ok:
        return {'blockedBy': conn}
    return {'blockedBy': conn, 'open_prs': sorted(closing.get(int(number), [])),
            'prs_complete': False}


# ── closed pull requests ─────────────────────────────────────────────────────

def is_merged(raw):
    """Whether a REST pull request merged. REST has no `MERGED` state: a closed
    pull request merged when `merged_at` is set, whatever its `state` says."""
    return bool(raw.get('merged_at'))


def closing_refs(raw, repo):
    """A REST pull request's closing references, as `gh pr list --json
    closingIssuesReferences` lists them, read from the closing keywords in its
    body. An issue linked by hand, with no keyword, is not among them."""
    return [{'number': n} for n in wf_core.body_closing_numbers(raw.get('body'), repo)]


def rest_closed_prs(cfg, keep, enough=None, max_pages=REST_MAX_PAGES):
    """Closed pull requests, newest first, that `keep` accepts. (ok, kept,
    err), where `kept` holds what was kept before any failure.

    REST cannot filter closed pull requests by whether they merged or by the
    issue they close, so they are read a page at a time and filtered here. The
    read stops at a short page, once `enough` are kept, or after `max_pages`.
    """
    kept = []
    for page in range(1, max_pages + 1):
        ok, prs, err = gh_rest('repos/%s/pulls?state=closed&sort=created'
                               '&direction=desc&per_page=%d&page=%d'
                               % (_repo(cfg), REST_PAGE, page))
        if not ok or not isinstance(prs, list):
            return False, kept, err or 'unexpected REST response'
        kept.extend(p for p in prs if isinstance(p, dict) and keep(p))
        if (enough and len(kept) >= enough) or len(prs) < REST_PAGE:
            break
    return True, kept, ''


# Merged pull requests the claim checks, newest first, as the GraphQL check
# reads, and the pages of closed pull requests it may read to find them.
MERGED_WINDOW = 100
MERGED_MAX_PAGES = 5


def rest_merged_pr_closing(cfg, number):
    """The lowest merged pull request among the newest hundred merged ones
    whose body closes issue `number`, or None.

    REST cannot ask for merged pull requests only, so closed ones are read a
    page at a time until a hundred merged ones are in hand, as many as the
    GraphQL check reads, or `MERGED_MAX_PAGES` run out.
    """
    # A failed page ends the read with what was in hand, as it always has.
    _ok, merged, _err = rest_closed_prs(cfg, is_merged, MERGED_WINDOW, MERGED_MAX_PAGES)
    matches = [pr['number'] for pr in merged[:MERGED_WINDOW]
               if int(number) in wf_core.body_closing_numbers(pr.get('body'), _repo(cfg))]
    return min(matches) if matches else None


# ── field ids ────────────────────────────────────────────────────────────────

def _org_field_ids(cfg):
    ok, fields, _err = gh_rest('orgs/%s/issue-fields' % cfg['org'])
    if not ok or not isinstance(fields, list):
        return {}
    return {f['name']: f['id'] for f in fields
            if isinstance(f, dict) and f.get('name') and f.get('id') is not None}


def rest_field_id(cfg, name, numbers=()):
    """The REST id of the org field `name`, or None.

    Tried in order, cheapest first, and the org endpoint is not the only
    source, because a session that blocks GraphQL may refuse it too: the
    values this run's reads already returned, the ids a past run kept in the
    capability cache, the values on the issues being written, the org's
    field list, and the values on the repository's recently updated issues.
    The first answer is kept in the cache.
    """
    if name in _field_ids:
        return _field_ids[name]
    cached = (load_capability_cache().get(FIELD_ID_CACHE_KEY) or {}).get(name)
    if cached is not None:
        _field_ids[name] = cached
        return cached
    repo = _repo(cfg)
    for number in list(numbers)[:3]:
        ok, values, _err = gh_rest('repos/%s/issues/%d/issue-field-values'
                                   % (repo, int(number)))
        if ok and isinstance(values, list):
            remember_field_ids(values)
        if name in _field_ids:
            break
    if name not in _field_ids:
        _field_ids.update(_org_field_ids(cfg))
    if name not in _field_ids:
        ok, recent, _err = gh_rest('repos/%s/issues?state=all&sort=updated'
                                   '&direction=desc&per_page=%d' % (repo, FIELD_ID_SCAN))
        for raw in recent if ok and isinstance(recent, list) else ():
            remember_field_ids(raw.get('issue_field_values'))
    if name not in _field_ids:
        return None
    try:
        kept = dict(load_capability_cache().get(FIELD_ID_CACHE_KEY) or {})
        kept[name] = _field_ids[name]
        merge_capability_cache({FIELD_ID_CACHE_KEY: kept})
    except OSError:
        pass
    return _field_ids[name]


def _option_spelling(name, field):
    """The org's own spelling of the option `name`, from the cached capability
    record when it has the field, so a write matches the option exactly."""
    meta = ((load_capability_cache().get('field_map') or {}).get(field)) or {}
    return wf_core.option_spelling(meta, name) if meta.get('options') else name


# ── writes ───────────────────────────────────────────────────────────────────

def rest_set_stages(cfg, wanted, extra=None):
    """`wf_stage.set_stages` through REST. {number: (written, message)}.

    One write per issue, and each is read back from its own answer: the REST
    write returns every value the issue now carries, so a write GitHub took
    but did not store is reported, not trusted.

    `extra` is {number: [field input]} for other fields to write in the same
    request, such as the release notes a merge records beside Done. Each is
    read back as `Stage` is, and the issue counts as written only when every
    value landed, as the GraphQL mutation counts it, so a caller that retries
    `Stage` alone on a failure behaves the same either way.
    """
    out = {}
    field = field_name(cfg, 'field-stage')
    inputs = {}
    for number, stage in wanted.items():
        name = wf_core.stage_name(stage)
        if not name:
            out[int(number)] = (False, "'%s' is not a stage (it reads: %s)"
                                % (stage, ', '.join(wf_core.STAGE_NAMES.values())))
            continue
        inputs[int(number)] = name
    if not inputs:
        return out
    fid = rest_field_id(cfg, field, sorted(inputs))
    for number in sorted(inputs):
        if fid is None:
            out[number] = (False, 'could not find the id of the %s field through '
                                  'REST: no issue carries a value for it and the org '
                                  'field list could not be read' % field)
            continue
        others, why = rest_field_values(cfg, (extra or {}).get(number), [number])
        if why:
            out[number] = (False, why)
            continue
        value = _option_spelling(inputs[number], field)
        ok, values, err = gh_rest('repos/%s/issues/%d/issue-field-values'
                                  % (_repo(cfg), number), 'POST',
                                  {'issue_field_values': [{'field_id': fid,
                                                           'value': value}]
                                   + [{'field_id': o['field_id'], 'value': o['value']}
                                      for o in others]})
        if not ok:
            out[number] = (False, 'REST write failed: %s' % err)
            continue
        remember_field_ids(values)
        got = next(((v.get('single_select_option') or {}).get('name')
                    for v in values or () if isinstance(v, dict)
                    and (v.get('issue_field_id') == fid
                         or v.get('issue_field_name') == field)), None)
        if (got or '').strip().lower() != inputs[number].lower():
            out[number] = (False, 'GitHub took the write, but %s reads %s'
                           % (field, "'%s'" % got if got else 'blank'))
            continue
        missed = [o['name'] for o in others if not _value_landed(values, o)]
        if missed:
            out[number] = (False, 'GitHub took the write, but %s did not read back '
                                  'as written' % ', '.join(missed))
            continue
        out[number] = (True, 'Stage set to %s' % inputs[number])
    return out


def _capability_names(field_id):
    """The field name and {option id: option name} for a GraphQL field id,
    from the cached capability record."""
    for name, meta in ((load_capability_cache().get('field_map') or {}).items()):
        if isinstance(meta, dict) and meta.get('id') == field_id:
            return name, {v: k for k, v in (meta.get('options') or {}).items()}
    return None, {}


def rest_field_values(cfg, inputs, numbers=()):
    """GraphQL field inputs as REST values. ([value], err).

    Each value is {'name', 'field_id', 'value', 'kind'}. An input names its
    field by `fieldName` (built on REST, where no GraphQL id was read) or by
    `fieldId`, which the cached capability record turns into a name. Any input
    this cannot turn into a REST value is an error for the whole write, so no
    field is written without the others.
    """
    out = []
    for item in inputs or ():
        name, options = item.get('fieldName'), {}
        if not name:
            name, options = _capability_names(item.get('fieldId'))
        if not name:
            return [], ('could not write a field through REST: its id %s is not '
                        'in the capability cache' % item.get('fieldId'))
        if 'textValue' in item:
            kind, value = 'text', str(item['textValue'])
        elif 'numberValue' in item:
            kind, value = 'number', item['numberValue']
        elif 'dateValue' in item:
            kind, value = 'date', str(item['dateValue'])
        elif 'singleSelectOptionId' in item and item['singleSelectOptionId'] in options:
            kind, value = 'single_select', options[item['singleSelectOptionId']]
        else:
            return [], 'could not write %s through REST: its value type is not supported' % name
        fid = rest_field_id(cfg, name, numbers)
        if fid is None:
            return [], 'could not find the id of the %s field through REST' % name
        out.append({'name': name, 'field_id': fid, 'value': value, 'kind': kind})
    return out, ''


def _value_landed(values, wanted):
    """Whether GitHub's answer to a REST field write holds `wanted`."""
    for v in values or ():
        if not isinstance(v, dict) or not (v.get('issue_field_id') == wanted['field_id']
                                           or v.get('issue_field_name') == wanted['name']):
            continue
        if wanted['kind'] == 'single_select':
            got = (v.get('single_select_option') or {}).get('name') or ''
            return got.strip().lower() == str(wanted['value']).strip().lower()
        if wanted['kind'] == 'number':
            try:
                return float(v.get('value')) == float(wanted['value'])
            except (TypeError, ValueError):
                return False
        if wanted['kind'] == 'date':
            return str(v.get('value') or '')[:10] == wanted['value'][:10]
        return str(v.get('value') or '').strip() == wanted['value'].strip()
    return False


_login = {}


def rest_viewer_login():
    """The login `gh` is signed in as, read once a run, or None."""
    if 'login' not in _login:
        ok, user, _err = gh_rest('user')
        _login['login'] = (user or {}).get('login') if ok else None
    return _login['login']


def _who(login):
    return rest_viewer_login() if login == '@me' else login


def rest_assign(cfg, number, login='@me'):
    """Add an assignee. (ok, err)."""
    who = _who(login)
    if not who:
        return False, 'could not read the signed-in login'
    ok, _data, err = gh_rest('repos/%s/issues/%d/assignees' % (_repo(cfg), int(number)),
                             'POST', {'assignees': [who]})
    return ok, err


def rest_unassign(cfg, number, login='@me'):
    """Remove an assignee. (ok, err)."""
    who = _who(login)
    if not who:
        return False, 'could not read the signed-in login'
    ok, _data, err = gh_rest('repos/%s/issues/%d/assignees' % (_repo(cfg), int(number)),
                             'DELETE', {'assignees': [who]})
    return ok, err


def rest_comment(cfg, number, body):
    """Post one issue comment. (ok, err)."""
    ok, _data, err = gh_rest('repos/%s/issues/%d/comments' % (_repo(cfg), int(number)),
                             'POST', {'body': body})
    return ok, err


def rest_remove_labels(cfg, number, names):
    """Take labels off an issue. (ok, err) for the last one that failed."""
    ok, err = True, ''
    for name in names or ():
        done, _data, why = gh_rest('repos/%s/issues/%d/labels/%s'
                                   % (_repo(cfg), int(number), quote(name, safe='')),
                                   'DELETE')
        if not done:
            ok, err = False, why
    return ok, err


def rest_close_issue(cfg, number, body=None):
    """Close an issue as completed, with a comment first when `body` is set.
    (ok, err)."""
    if body:
        rest_comment(cfg, number, body)
    ok, _data, err = gh_rest('repos/%s/issues/%d' % (_repo(cfg), int(number)), 'PATCH',
                             {'state': 'closed', 'state_reason': 'completed'})
    return ok, err


def reset_rest_state():
    """Forget the field ids and the login this run read. The offline tests
    call this between cases."""
    _field_ids.clear()
    _login.clear()
