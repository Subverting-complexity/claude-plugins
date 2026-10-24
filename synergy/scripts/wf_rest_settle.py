"""
The REST fallback for settling a merge, where GraphQL is blocked: the merged
pull request with its closing references and comments, the merged pull
requests `settle-merged` sweeps, the issues they close, the parents above
them, and closing and stripping those issues.

`gh pr view`, `gh pr list` and `gh issue close` read through GraphQL inside
`gh`, and the issue and parent reads are aliased GraphQL queries, so in a
session that refuses GraphQL `post-merge` could not settle anything.
`wf_io.graphql_blocked()` decides when these run instead. Each read returns
what the GraphQL read returned, in the same shape, so the rules after it run
unchanged. REST has no `closingIssuesReferences`: the closing keywords in the
pull request body stand in for it, so an issue linked by hand, with no
keyword, is not settled. `scripts/README.md` has the module map.
"""

from concurrent.futures import ThreadPoolExecutor

from wf_io import gh_rest
from wf_rest import (
    REST_WORKERS, _pages, closing_refs, is_merged, number_of, repo_of,
    rest_close_issue, rest_closed_prs, rest_issue_node, rest_remove_labels,
)
from wf_rest_pr import pr_state, rest_find_pr


# Pages of closed pull requests `settle-merged` may read to find the merged
# ones it was asked for. REST cannot ask for merged pull requests only.
MERGED_LIST_PAGES = 10


def _repo(cfg):
    return '%s/%s' % (cfg['org'], cfg['repo'])


# ── the merged pull requests ─────────────────────────────────────────────────

def rest_merged_pr_view(cfg, number):
    """`gh pr view N --json number,state,mergedAt,baseRefName,
    closingIssuesReferences,comments` through REST. (view_or_None, err).

    The comments are read only for a merged pull request, because `post-merge`
    reads them only then, for the release notes the run posted.
    """
    repo = _repo(cfg)
    raw, err = rest_find_pr(cfg, number)
    if not raw:
        return None, err
    view = {'number': raw.get('number'), 'state': pr_state(raw),
            'mergedAt': raw.get('merged_at'),
            'baseRefName': (raw.get('base') or {}).get('ref') or '',
            'closingIssuesReferences': closing_refs(raw, repo), 'comments': []}
    if view['state'] != 'MERGED':
        return view, ''
    ok, comments, err = _pages('repos/%s/issues/%d/comments' % (repo, int(number)))
    if not ok:
        return None, 'could not read the comments of PR #%d through REST (%s)' % (
            int(number), err)
    view['comments'] = [{'body': c.get('body') or ''} for c in comments
                        if isinstance(c, dict)]
    return view, ''


def rest_merged_prs(cfg, limit):
    """The newest `limit` merged pull requests with their closing references,
    as `gh pr list --state merged --json number,closingIssuesReferences`
    returns them. (ok, prs, err)."""
    ok, merged, err = rest_closed_prs(cfg, is_merged, limit, MERGED_LIST_PAGES)
    if not ok:
        return False, None, 'merged pull request REST read failed: %s' % err
    repo = _repo(cfg)
    return True, [{'number': p['number'], 'closingIssuesReferences': closing_refs(p, repo)}
                  for p in merged[:limit]], ''


# ── the issues a merge closes ────────────────────────────────────────────────

def _read_issue(repo, number):
    ok, raw, err = gh_rest('repos/%s/issues/%d' % (repo, int(number)))
    if not ok or not isinstance(raw, dict):
        return None, err or 'issue #%d not found' % int(number)
    return raw, ''


def _linked_row(cfg, number):
    raw, err = _read_issue(_repo(cfg), number)
    if raw is None:
        return number, False, None, err
    node = rest_issue_node(raw, _repo(cfg))
    # Removing a label on REST takes its name, but the GraphQL read returns
    # each label's id too, and the caller keeps both.
    node['labels'] = {'nodes': [{'id': l.get('node_id'), 'name': l['name']}
                                for l in raw.get('labels') or ()
                                if isinstance(l, dict) and l.get('name')]}
    return number, True, node, ''


def rest_linked_rows(cfg, numbers):
    """Each issue as the aliased GraphQL read yields it: [(number, ok, node,
    err)], in order. One read per issue, in parallel."""
    numbers = list(numbers or ())
    if not numbers:
        return []
    with ThreadPoolExecutor(max_workers=REST_WORKERS) as pool:
        return list(pool.map(lambda n: _linked_row(cfg, n), numbers))


def rest_settle_issues(cfg, plan, comment):
    """`wf_post_merge.settle_issues` through REST. {number: {'closed',
    'cleared'}}, None where nothing was asked.

    Each entry closes with `comment` posted first when `close` is set, and
    takes off `label_names`.
    """
    out = {}
    for entry in plan:
        n = entry['number']
        closed = cleared = None
        if entry['close']:
            closed = rest_close_issue(cfg, n, comment)[0]
        if entry.get('label_names'):
            cleared = rest_remove_labels(cfg, n, entry['label_names'])[0]
        out[n] = {'closed': closed, 'cleared': cleared}
    return out


# ── the parents above them ───────────────────────────────────────────────────

def _container(raw, repo, children):
    """A REST parent issue as the GraphQL container node of the chain read."""
    node = rest_issue_node(raw, repo)
    node['repository'] = {'nameWithOwner': repo}
    node['subIssues'] = {'nodes': [{'number': c.get('number'),
                                    'state': (c.get('state') or '').upper()}
                                   for c in children if isinstance(c, dict)]}
    return node


def rest_parent_chain(cfg, number, depth):
    """The parents above one issue, nearest first, as GraphQL container nodes.
    (ok, nodes, err).

    A parent in another repository ends the walk, read without its children,
    because the walk never closes one there.
    """
    repo = _repo(cfg)
    raw, err = _read_issue(repo, number)
    if raw is None:
        return False, [], err
    chain = []
    for _ in range(depth):
        url = raw.get('parent_issue_url')
        if not url:
            break
        where, parent = repo_of(url) or repo, number_of(url)
        if not parent:
            return False, [], 'could not read the parent of #%d from %s' % (number, url)
        raw, err = _read_issue(where, parent)
        if raw is None:
            return False, [], 'parent #%d: %s' % (parent, err)
        if where.lower() != repo.lower():
            chain.append(_container(raw, where, []))
            break
        ok, children, err = _pages('repos/%s/issues/%d/sub_issues' % (where, parent))
        if not ok:
            return False, [], 'sub-issues of #%d: %s' % (parent, err)
        chain.append(_container(raw, where, children))
    return True, chain, ''


def rest_parent_chains(cfg, numbers, depth):
    """`rest_parent_chain` for many issues, in parallel. {number: (ok, nodes, err)}."""
    numbers = list(numbers or ())
    if not numbers:
        return {}
    with ThreadPoolExecutor(max_workers=REST_WORKERS) as pool:
        found = list(pool.map(lambda n: rest_parent_chain(cfg, n, depth), numbers))
    return dict(zip(numbers, found))
