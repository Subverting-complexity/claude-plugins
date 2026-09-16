"""
Issue references: parent parsing, closing references, branch names, dependency
edges and unblock verdicts.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

import datetime
import re


# ── Dependency edges ───────────────────────────────────────────
# What an issue is waiting for is read from GitHub's own `blockedBy` edges and
# from nothing else. There is no second answer to compare it against.
#
# There used to be. Dependencies were also written in the body as prose under a
# `## Dependencies` heading, and a parser here turned that prose back into
# issue numbers. Two graphs meant two chances to be wrong, and both were taken:
# on one 70-issue backlog the parser missed a `## Blocked by` heading whose
# references sat on the next line, and read "Nothing. This **was** blocked by
# #980" as a live dependency. The prose and the edges disagreed on nine of the
# fourteen issues carrying both, and the prose was the stale one every time.
#
# So the prose is gone rather than fixed. An edge is structured data GitHub
# renders, validates and lets you query; a sentence is not, and no amount of
# regex makes it one. `wf issue-apply` writes edges, `wf pick` and `wf unblock`
# read them, and a dependency that was never written as an edge does not exist.

# Fixed phrasings that name an issue's parent. The hierarchy is the one thing
# still read out of the body, because GitHub's sub-issue link is not written by
# every path that creates an issue and a body that says "Part of the X epic
# (#N)" is often the only record. Anything looser than these invents a
# hierarchy out of cross-references.
_PARENT_PATTERNS = [
    re.compile(r'\bpart\s+of\s+the\b[^#\n]{0,80}?\bepic\b[^#\n]{0,20}#(\d+)',
               re.IGNORECASE),
    re.compile(r'\bpart\s+of\s+#(\d+)', re.IGNORECASE),
    re.compile(r'\bsub-?issue\s+of\s+#(\d+)', re.IGNORECASE),
    re.compile(r'^\s*(?:\*\*)?parent(?:\*\*)?\s*:\s*(?:\*\*)?#(\d+)',
               re.IGNORECASE | re.MULTILINE),
    re.compile(r'^\s*(?:\*\*)?epic(?:\*\*)?\s*:\s*(?:\*\*)?#(\d+)',
               re.IGNORECASE | re.MULTILINE),
]

DEP_LIMIT = 5


def parse_parent(body):
    """The issue this one says it is part of, or None.

    Fixed phrasings only: `Part of the <name> epic (#N)`, `Part of #N`,
    `Sub-issue of #N`, and `Parent:`/`Epic:` at the start of a line. Returns
    None when the body names more than one distinct candidate, because a body
    that disagrees with itself is a thing to read rather than a thing to
    apply.
    """
    body = body or ''
    # In precedence order: a body that names its epic outright has answered
    # the question, and a looser `part of #N` elsewhere in the prose does not
    # get to make that ambiguous. #1095 says "Part of the Cadence Plus epic
    # (#959)" in its first line and, forty lines down, "the pages would move
    # to the new domain as part of #1005" — one is the parent, the other is a
    # sentence about a plan that was abandoned.
    for pattern in _PARENT_PATTERNS:
        found = set()
        for m in pattern.finditer(body):
            found.add(int(m.group(1)))
        if len(found) == 1:
            return found.pop()
        if found:
            return None
    return None


# ── Closing-reference normalisation ──────────────────────────────────────────
# GitHub reports an issue a PR closes as `closingIssuesReferences`, but the
# shape differs by API — see the helper for the two forms and the crash that
# conflating them caused.

def closing_issue_numbers(refs):
    """Normalise GitHub's `closingIssuesReferences` to a list of issue numbers.

    The field arrives in two different shapes depending on which API the I/O
    shell used, and the two must not be confused:

      - `gh pr view --json closingIssuesReferences` returns a **flat list** of
        issue objects: ``[{'number': 5}, ...]``.
      - The GraphQL API returns the connection wrapped in ``nodes``:
        ``{'nodes': [{'number': 5}, ...]}``.

    Passing the gh-CLI list to ``.get('nodes')`` is what crashed cmd_post_merge
    with ``'list' object has no attribute 'get'``. This accepts either shape
    (and a ``None``/missing value) and always returns a plain list of ints, so
    callers never have to know which API produced the data.
    """
    if not refs:
        return []
    if isinstance(refs, dict):
        refs = refs.get('nodes') or []
    return [n['number'] for n in refs if isinstance(n, dict) and 'number' in n]


# ── Branch naming ────────────────────────────────────────────────────────────
# execute SKILL.md — deterministic slug from the issue title.

def branch_slug(title, max_len=40):
    """Slugify an issue title for a branch name.

    lowercase → non-alphanumeric runs become single hyphens → truncate to
    max_len → strip leading/trailing hyphens. Matches the execute example
    "Fix: User login broken!!!" → "fix-user-login-broken".
    """
    slug = re.sub(r'[^a-z0-9]+', '-', (title or '').lower())
    slug = slug.strip('-')[:max_len].strip('-')
    return slug


# Every placeholder that means "the title slug here". `{short-desc}` is the
# canonical form the template and docs use, but a config (or the example a
# half-finished setup leaves behind) often spells it out as
# `{short-description}` or uses a near-synonym — all of these must render to
# the slug so a literal `{...}` never survives into a git branch name. A
# genuinely unrecognised placeholder is still left untouched (see branch_name).
_SLUG_PLACEHOLDERS = (
    '{short-desc}', '{short-description}', '{short_desc}',
    '{description}', '{desc}', '{slug}', '{title}',
)


def branch_name(convention, number, title):
    """Render the branch convention with the issue number and a title slug.

    `convention` is the pattern from ClaudeProject.md, e.g.
    "feature/{number}/{short-desc}". Any of the slug aliases in
    `_SLUG_PLACEHOLDERS` (`{short-description}`, `{slug}`, …) renders to the
    title slug, so a config that spells the placeholder out does not leak a
    literal `{short-description}` into the branch name. Other, genuinely
    unknown placeholders are left untouched.
    """
    out = convention.replace('{number}', str(number))
    slug = branch_slug(title)
    for token in _SLUG_PLACEHOLDERS:
        out = out.replace(token, slug)
    return out


# ── native dependency edges ──────────────────────────────────────────────────
# GitHub's own `blockedBy` edges — what the issue's own sidebar shows and what
# `addBlockedBy` writes. They are the only record of a dependency, so nothing
# below has a second opinion to reconcile against.

UNBLOCK_RELEASE = 'release'
UNBLOCK_HOLD = 'hold'
UNBLOCK_NO_EDGES = 'no-edges'

# How far back a merge still counts as "this blocker just delivered something".
# Long enough to cover a story that merged over a weekend, short enough that
# the report is about what has just happened rather than about every pull
# request that ever mentioned the issue.
PARTIAL_WINDOW_DAYS = 14


def blocker_ref(edge, repo=None):
    """One blocked-by edge as a reference: the issue number for an issue in
    `repo`, `'owner/name#N'` for one in another repository, None if unreadable.

    A blocker in another repository is a different issue from the local one
    that shares its number, so it cannot be keyed by the number alone: local
    #12 blocked by `org/other#5` read as blocked by local #5, and a run that
    could build local #5 called #12 buildable. The edge only says where it
    lives when the read asked for `repository { nameWithOwner }`; an edge
    that does not say, or a caller that does not know its own repository, is
    taken as local.
    """
    try:
        number = int((edge or {}).get('number'))
    except (TypeError, ValueError):
        return None
    home = ((edge.get('repository') or {}).get('nameWithOwner')
            if isinstance(edge.get('repository'), dict) else None)
    if repo and home and home.lower() != repo.lower():
        return '%s#%d' % (home, number)
    return number


def ref_label(ref):
    """A blocker reference in words: `#5`, or `org/other#5` as it stands."""
    return '#%d' % ref if isinstance(ref, int) else str(ref)


def ref_sort_key(ref):
    """Orders local numbers first, then foreign references, without comparing
    an int with a str."""
    return (0, ref, '') if isinstance(ref, int) else (1, 0, str(ref))


def local_blocker_numbers(issue, repo=None):
    """The local issue numbers an issue's `blockedBy` read names.

    `repo` defaults to the issue's own `repository { nameWithOwner }` where the
    read carried it. A foreign edge is left out, so an entry naming local #5
    is never satisfied, or diffed against, by `org/other#5`.
    """
    home = repo or ((issue.get('repository') or {}).get('nameWithOwner')
                    if isinstance(issue.get('repository'), dict) else None)
    out = []
    for edge in ((issue.get('blockedBy') or {}).get('nodes')) or []:
        ref = blocker_ref(edge, home)
        if isinstance(ref, int) and ref not in out:
            out.append(ref)
    return out


def edges_incomplete(connection):
    """Whether a `blockedBy` connection read fewer edges than it holds.

    Only a read that asked for `totalCount` can say; one that did not is taken
    at its word, as it always was.
    """
    if not isinstance(connection, dict):
        return False
    total = connection.get('totalCount')
    return total is not None and total > len(connection.get('nodes') or [])


def edge_states(edges, repo=None):
    """Split native blocked-by edges into (open_refs, closed_refs).

    `edges` are `{'number': int, 'state': 'OPEN'|'CLOSED'}` nodes in the shape
    GraphQL returns them. Order is kept and duplicates dropped, so a caller
    can name the blockers in the order the issue itself lists them. With
    `repo`, a blocker in another repository comes back as `'owner/name#N'`
    (see `blocker_ref`) rather than as a local number.
    """
    open_numbers, closed_numbers, seen = [], [], set()
    for edge in edges or ():
        number = blocker_ref(edge, repo)
        if number is None:
            continue
        if number in seen:
            continue
        seen.add(number)
        if (edge.get('state') or '').upper() == 'OPEN':
            open_numbers.append(number)
        else:
            closed_numbers.append(number)
    return open_numbers, closed_numbers


def unblock_verdict(edges, repo=None):
    """Decide whether an issue carrying `edges` has been released.

    Returns (verdict, open_numbers, closed_numbers):

      release   every edge points at a closed issue, and there is at least one
      hold      at least one edge points at an open issue
      no-edges  the issue records no native dependency at all

    That "at least one" is the safety rule, and it does the real work here. An
    issue labelled blocked with no edge is not a released issue, it is an issue
    nobody ever wrote a dependency for, and on a real backlog most of those are
    waiting on the world rather than on another issue: a bank account, a device
    pass, a store upload. A sweep that read "no open blockers" as "release"
    would put every one of them into the pool for an agent that cannot do any
    of them.

    An open blocker in another repository holds the issue like any other; one
    that has closed counts as closed.
    """
    open_numbers, closed_numbers = edge_states(edges, repo)
    if not open_numbers and not closed_numbers:
        return UNBLOCK_NO_EDGES, [], []
    if open_numbers:
        return UNBLOCK_HOLD, open_numbers, closed_numbers
    return UNBLOCK_RELEASE, [], closed_numbers


def _merged_at(pull_request):
    """The `mergedAt` of a merged pull request as a datetime, or None."""
    if not isinstance(pull_request, dict):
        return None
    merged = pull_request.get('merged')
    state = (pull_request.get('state') or '').upper()
    if merged is False or (state and state != 'MERGED'):
        return None
    stamp = pull_request.get('mergedAt')
    if not stamp:
        return None
    try:
        return datetime.datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError):
        return None


def title_names_issue(title, number):
    """True when `title` cites issue `number` as a reference, not as a prefix.

    The digit guards on both sides are the whole point: `#97` must not answer
    for `#979`, and neither must `#1979`.
    """
    return bool(re.search(r'(?<!\d)#0*%d(?!\d)' % int(number), title or ''))


def recent_delivery(pull_requests, number, now, window_days=PARTIAL_WINDOW_DAYS):
    """The newest pull request that recently merged *for* issue `number`, or None.

    This is the one case no edge can describe. A story split into a backend
    half and an app half merges the backend, stays open, and its edges stay
    correct — yet whatever only needed the backend's decided shape is free
    now. Nothing here decides that. It reports the merge, with its number and
    date, so a person can judge what the merge actually delivered.

    The pull request has to name the issue **in its title**. A mention anywhere
    in the body is far too weak a signal: tried against a real backlog it
    flagged ten of the eleven held issues, because a pull request body
    routinely lists everything nearby, and a report that fires on nearly
    everything is one nobody reads. A title reference is somebody saying this
    pull request is about that issue.

    `now` is passed in rather than read, because this module does no I/O and a
    test that cannot pin the clock is a test that fails on its own anniversary.
    """
    newest = None
    for pull_request in pull_requests or ():
        if not title_names_issue((pull_request or {}).get('title'), number):
            continue
        when = _merged_at(pull_request)
        if when is None or (now - when).days > window_days:
            continue
        if newest is None or when > newest[0]:
            newest = (when, pull_request)
    if newest is None:
        return None
    return {'number': newest[1].get('number'),
            'merged_at': newest[1].get('mergedAt')}
