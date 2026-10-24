"""
The REST fallback for pull requests, where GraphQL is blocked: opening,
reading and editing one pull request, its labels, the review pool
`review-next` reads, the open pull requests `sibling-pr` and `update-next`
read, the repository's labels, and checking out a pull request's branch.

`gh pr create`, `gh pr view`, `gh pr list`, `gh pr edit` and `gh pr checkout`
all read through GraphQL inside `gh`, so in a session that refuses GraphQL
they fail. `wf_io.graphql_blocked()` decides when these run instead. Each
read returns what the GraphQL read returned, in the same shape, so the rules
after it run unchanged. `wf_rest.py` holds the issue half;
`scripts/README.md` has the module map.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import wf_core
from wf_io import gh_rest, run
from wf_rest import REST_PAGE, REST_WORKERS, _pages, rest_viewer_login


# Comments and reviews the GraphQL review pool reads for each pull request,
# the most recent first, and the most open pull requests it reads at all.
REVIEW_POSTS = 30
OPEN_PR_LIMIT = 100
# Pages of one pull request's comments read to reach its most recent ones:
# REST lists them oldest first and cannot reverse the order.
POST_PAGES = 10


def _repo(cfg):
    return '%s/%s' % (cfg['org'], cfg['repo'])


def pr_state(raw):
    """GitHub's GraphQL state for a REST pull request: OPEN, CLOSED or MERGED."""
    if raw.get('merged_at'):
        return 'MERGED'
    return (raw.get('state') or '').upper()


def pr_view(raw):
    """A REST pull request in the shape `gh pr view --json` returns it."""
    return {
        'number': raw.get('number'),
        'title': raw.get('title') or '',
        'url': raw.get('html_url') or '',
        'body': raw.get('body') or '',
        'state': pr_state(raw),
        'labels': [{'name': l['name']} for l in raw.get('labels') or ()
                   if isinstance(l, dict) and l.get('name')],
        'headRefName': (raw.get('head') or {}).get('ref') or '',
        'headRefOid': (raw.get('head') or {}).get('sha') or '',
        'isDraft': bool(raw.get('draft')),
    }


def sibling_node(raw, repo):
    """A REST open pull request as a node of the GraphQL `sibling-pr` query.

    REST has no `closingIssuesReferences`, so the closing keywords in the body
    stand in for it, read the way GitHub reads them. An issue linked to the
    pull request by hand, with no keyword, is not seen.
    """
    view = pr_view(raw)
    return {
        'number': view['number'], 'title': view['title'], 'url': view['url'],
        'headRefName': view['headRefName'], 'isDraft': view['isDraft'],
        'labels': {'nodes': view['labels']},
        'closingIssuesReferences': {'nodes': [
            {'number': n} for n in wf_core.body_closing_numbers(view['body'], repo)]},
    }


# ── reads ────────────────────────────────────────────────────────────────────

def rest_open_prs(cfg):
    """Every open pull request, oldest first, as GraphQL orders them.
    (ok, raws, err)."""
    ok, prs, err = _pages('repos/%s/pulls?state=open&sort=created&direction=asc'
                          % _repo(cfg))
    if not ok:
        return False, None, 'open pull request REST read failed: %s' % err
    return True, [p for p in prs if isinstance(p, dict)], ''


def rest_find_pr(cfg, ref):
    """The pull request `ref` names, by number or by head branch. (raw, err).

    A branch can have had several pull requests; the open one wins, as `gh pr
    view <branch>` picks it, then the newest.
    """
    repo = _repo(cfg)
    if str(ref).isdigit():
        ok, raw, err = gh_rest('repos/%s/pulls/%d' % (repo, int(ref)))
        return (raw, '') if ok and isinstance(raw, dict) else (None, err or 'not found')
    ok, prs, err = gh_rest('repos/%s/pulls?head=%s&state=all&per_page=%d'
                           % (repo, quote('%s:%s' % (cfg['org'], ref), safe=':'),
                              REST_PAGE))
    if not ok or not isinstance(prs, list):
        return None, err or 'unexpected REST response'
    if not prs:
        return None, 'no pull request found for branch %s' % ref
    prs.sort(key=lambda p: (p.get('state') != 'open', -(p.get('number') or 0)))
    return prs[0], ''


def rest_pr_view(cfg, ref):
    """`gh pr view <ref> --json ...` through REST. (view_or_None, err)."""
    raw, err = rest_find_pr(cfg, ref)
    return (pr_view(raw), '') if raw else (None, err)


def rest_sibling_nodes(cfg):
    """The open pull requests as `sibling-pr` query nodes. (ok, nodes, err)."""
    ok, prs, err = rest_open_prs(cfg)
    if not ok:
        return False, None, err
    return True, [sibling_node(p, _repo(cfg)) for p in prs], ''


def rest_my_open_prs(cfg):
    """Open pull requests assigned to the signed-in login, as `gh pr list
    --assignee @me` returns them. (ok, views, err)."""
    who = rest_viewer_login()
    if not who:
        return False, None, 'could not read the signed-in login'
    ok, prs, err = rest_open_prs(cfg)
    if not ok:
        return False, None, err
    mine = [p for p in prs
            if who in [a.get('login') for a in p.get('assignees') or ()
                       if isinstance(a, dict)]]
    return True, [pr_view(p) for p in mine], ''


def _recent_posts(path, stamp):
    """The bodies and times of the `REVIEW_POSTS` most recent records of a
    REST list read oldest first. None when the read failed."""
    ok, items, _err = _pages(path, max_pages=POST_PAGES)
    if not ok:
        return None
    posts = [{'body': i.get('body') or '', 'createdAt': i.get(stamp) or ''}
             for i in items if isinstance(i, dict)]
    return posts[-REVIEW_POSTS:]


def rest_review_pool(cfg):
    """The open pull requests the review picker reads, each with its head and
    the comments and reviews its last review footer is found in.
    (ok, entries, err), each entry shaped as `assemble_review_prs` builds it
    from the GraphQL nodes.

    REST lists a pull request's comments and reviews on their own, so this is
    one read of the open pull requests and two per pull request that is not a
    draft, in parallel. A draft is never picked, so its posts are not read.
    """
    ok, prs, err = rest_open_prs(cfg)
    if not ok:
        return False, None, err
    if len(prs) > OPEN_PR_LIMIT:
        return False, None, ('more than %d open PRs; the picker reads only the first %d'
                             % (OPEN_PR_LIMIT, OPEN_PR_LIMIT))
    repo = _repo(cfg)
    live = [p for p in prs if not p.get('draft')]
    with ThreadPoolExecutor(max_workers=REST_WORKERS) as pool:
        comments = {p['number']: pool.submit(
            _recent_posts, 'repos/%s/issues/%d/comments' % (repo, p['number']),
            'created_at') for p in live}
        reviews = {p['number']: pool.submit(
            _recent_posts, 'repos/%s/pulls/%d/reviews' % (repo, p['number']),
            'submitted_at') for p in live}
        posts = {}
        for number in comments:
            found = (comments[number].result(), reviews[number].result())
            if None in found:
                # A footer on a page not read could hide a moved head, so a
                # failed read fails the pool, as a failed GraphQL query does.
                return False, None, ('could not read the comments and reviews '
                                     'of PR #%d through REST' % number)
            posts[number] = found[0] + found[1]
    entries = []
    for raw in prs:
        view = pr_view(raw)
        mine = sorted(posts.get(view['number'], ()), key=lambda p: p['createdAt'])
        entries.append({
            'number': view['number'], 'title': view['title'], 'url': view['url'],
            'branch': view['headRefName'],
            'labels': [l['name'] for l in view['labels']],
            'head_sha': view['headRefOid'], 'draft': view['isDraft'],
            'reviewed_sha': wf_core.last_reviewed_sha(p['body'] for p in mine),
        })
    return True, entries, ''


def rest_repo_labels(repo):
    """Every label in `repo` with its colour and description.
    (ok, labels, err)."""
    ok, items, err = _pages('repos/%s/labels' % repo)
    if not ok:
        return False, [], err
    return True, [{'name': l['name'], 'colour': l.get('color') or '',
                   'description': l.get('description') or ''}
                  for l in items if isinstance(l, dict) and l.get('name')], ''


def rest_label_exists(cfg, name):
    """Whether the repository has the label `name`."""
    ok, _data, _err = gh_rest('repos/%s/labels/%s' % (_repo(cfg), quote(name, safe='')))
    return ok


# ── writes ───────────────────────────────────────────────────────────────────

def rest_pr_create(cfg, base, head, title, body):
    """Open a pull request. (raw_or_None, already_existed, err).

    When GitHub refuses because the branch already has an open pull request,
    that pull request is returned and `already_existed` is True, as `gh pr
    create` reports "already exists".
    """
    ok, raw, err = gh_rest('repos/%s/pulls' % _repo(cfg), 'POST',
                           {'title': title, 'head': head, 'base': base, 'body': body})
    if ok and isinstance(raw, dict) and raw.get('number'):
        return raw, False, ''
    existing, _ = rest_find_pr(cfg, head)
    if existing and existing.get('state') == 'open':
        return existing, True, ''
    return None, False, err or 'no pull request in the answer'


def rest_pr_edit_body(cfg, number, body):
    """Replace a pull request's body. (ok, err)."""
    ok, _raw, err = gh_rest('repos/%s/pulls/%d' % (_repo(cfg), int(number)), 'PATCH',
                            {'body': body})
    return ok, err


def rest_edit_labels(cfg, number, add=(), remove=()):
    """Take labels off and put labels on an issue or pull request, as `gh pr
    edit --remove-label --add-label` does. (ok, err) naming what failed.

    A label the pull request does not carry answers 404 on its delete. That
    label is already off, as `gh pr edit` treats it, so it is not a failure.
    """
    repo, failed = _repo(cfg), []
    for name in remove or ():
        ok, _data, err = gh_rest('repos/%s/issues/%d/labels/%s'
                                 % (repo, int(number), quote(name, safe='')), 'DELETE')
        if not ok and 'http 404' not in (err or '').lower():
            failed.append('remove %s (%s)' % (name, err))
    if add:
        ok, _data, err = gh_rest('repos/%s/issues/%d/labels' % (repo, int(number)),
                                 'POST', {'labels': list(add)})
        if not ok:
            failed.append('add %s (%s)' % (', '.join(add), err))
    return not failed, '; '.join(failed)


def rest_checkout_pr(cfg, number):
    """Check out a pull request's branch, as `gh pr checkout` does, from the
    head the REST read names. (ok, message).

    A branch already here is moved forward to the remote head and never
    reset, so local commits are kept or the checkout fails.
    """
    raw, err = rest_find_pr(cfg, number)
    if not raw:
        return False, 'could not read PR #%s through REST (%s)' % (number, err)
    head = raw.get('head') or {}
    branch = head.get('ref')
    if (head.get('repo') or {}).get('full_name', _repo(cfg)).lower() != _repo(cfg).lower():
        return False, 'PR #%s comes from a fork, which the REST checkout does not fetch' % number
    code, _, ferr = run(['git', 'fetch', 'origin',
                         '+refs/heads/%s:refs/remotes/origin/%s' % (branch, branch)])
    if code != 0:
        return False, 'git fetch failed (%s)' % ferr.strip()
    code, _, _ = run(['git', 'rev-parse', '--verify', '--quiet', 'refs/heads/%s' % branch])
    if code == 0:
        steps = [['git', 'checkout', branch],
                 ['git', 'merge', '--ff-only', 'origin/%s' % branch]]
    else:
        steps = [['git', 'checkout', '-b', branch, '--track', 'origin/%s' % branch]]
    for step in steps:
        code, _, serr = run(step)
        if code != 0:
            return False, '%s failed (%s)' % (' '.join(step[:2]), serr.strip())
    return True, 'checked out the PR branch'
