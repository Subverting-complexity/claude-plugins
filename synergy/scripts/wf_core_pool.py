"""
Choosing work from the issue tree: the verdict on every open issue in the pool.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

import re

from wf_core_fields import _priority_rank
from wf_core_refs import edge_states, edges_incomplete, ref_label, ref_sort_key
from wf_core_select import (
    HIERARCHY_CONTAINER_TYPES, NATIVE_FEATURE_TYPES, NATIVE_MAINTENANCE_TYPES,
    _filter_effort, _sort_candidates, is_maintenance_classification,
)
from wf_core_stage import (
    SCOPE_CODE, STAGE_NAMES, effective_scope, is_available_stage, stage_name,
)


# ── choosing work from the issue tree (#256) ─────────────────────────────────
# The pool is every open issue in the repository, judged one rule at a time
# with the first rule that applies deciding. An Epic or Feature is not work,
# but it can be chosen: it expands to the stories under it. The rules were
# settled on #256, and `evaluate_pool` is their executable statement.


# A body shorter than this, once stripped, says too little to build from.
UNCLEAR_MIN_BODY = 40

# Stages an explicitly named issue may be picked from, beside a blank one.
# Backlog is the pool;
# Blocked is here because the edge check runs anyway and an issue whose
# blockers have all closed is workable; Needs refinement and Parked are here
# because naming the issue is the person overruling the hold they put on it. In
# Progress and In Review are somebody else's work, Non-code is work a code
# agent cannot do, and Done is finished. The same stages decide which open
# prerequisite a set may pull in whatever `--mode` or `--max-effort` says.
PICKABLE_BY_NAME = frozenset({'Backlog', 'Blocked', 'Needs refinement', 'Parked'})

# Acceptance criteria, as a body carries them: a heading naming them, or a
# task-list item. `Requirements` is the story template's name for the same
# section and `Verification` the issue standard's.
_CRITERIA_RE = re.compile(
    r'^\s*(#{1,6}\s*(acceptance criteria|requirements|verification)\b|[-*]\s+\[[ xX]\])',
    re.IGNORECASE | re.MULTILINE)


def unclear_reason(issue, type_name=None):
    """Why an issue is too unclear to build, or None when it is clear enough.

    The script half of the unclear check; the agent's judgement at claim is
    the other half. A container is unclear when it has no sub-issues at all,
    because there is nothing under it to build. A leaf is unclear when its
    body is nearly empty or carries no acceptance criteria.
    """
    if type_name in HIERARCHY_CONTAINER_TYPES:
        if not (issue.get('sub_issues') or {}).get('total'):
            return 'an %s with no sub-issues, so there is nothing under it to build' % type_name
        return None
    body = (issue.get('body') or '').strip()
    if len(body) < UNCLEAR_MIN_BODY:
        return 'the body is nearly empty'
    if not _CRITERIA_RE.search(body):
        return 'the body has no acceptance criteria'
    return None


def _open_blockers(issue):
    """The open blockers of an issue as read with it, or None when the read
    could not see every edge. None is not "none": the claim reads the edges
    again in full.

    A blocker in another repository comes back as `'owner/name#N'` when the
    issue carries its own `repo`, so it is never mistaken for the local issue
    with the same number. Local numbers sort first.
    """
    edges = issue.get('blockedBy') or {}
    if edges_incomplete(edges):
        return None
    open_refs, _closed = edge_states(edges.get('nodes') or [], issue.get('repo'))
    return sorted(open_refs, key=ref_sort_key)


def _releasable(issue, kind, ownership_map, claimed):
    """Whether a `Blocked` issue is one the unblock sweep would release now.

    Code work nobody holds, whose every blocked-by edge was read, with at
    least one edge and every one of them closed. The sweep's own rule, applied
    to the pool read already in hand, so a pick does not have to find the pool
    empty, sweep, and read it all again before it can see the issue.
    """
    n = issue['number']
    if stage_name(issue.get('stage')) != STAGE_NAMES['stage-blocked']:
        return False
    if issue.get('assigned') or n in claimed or issue.get('open_prs'):
        return False
    if effective_scope(ownership_map.get(n), kind(n)) != SCOPE_CODE:
        return False
    edges = issue.get('blockedBy')
    if (not isinstance(edges, dict) or edges.get('totalCount') is None
            or edges_incomplete(edges)):
        return False
    open_refs, closed_refs = edge_states(edges.get('nodes') or [], issue.get('repo'))
    return bool(closed_refs) and not open_refs


def _leaf_in_mode(number, mode, kind, nearest_feature, classification_map):
    """(in_mode, unclassified) for a leaf under `--mode`."""
    if mode == 'story':
        return True, False
    type_name = kind(number)
    if not type_name:
        return False, True
    if mode == 'feature':
        return type_name in NATIVE_FEATURE_TYPES, False
    if type_name in NATIVE_MAINTENANCE_TYPES:
        return True, False
    feature = nearest_feature(number)
    return bool(feature and is_maintenance_classification(
        (classification_map or {}).get(feature))), False


def evaluate_pool(issues, mode='story', type_map=None, classification_map=None,
                  priority_map=None, effort_map=None, ownership_map=None,
                  claimed=(), max_effort=None):
    """Judge every open issue by the pick rules, first rule that applies wins.

    `issues` is every open issue in the repository, each carrying `number`,
    `stage`, `assigned`, `body`, and where known `type`, `parent`,
    `sub_issues` ({'total', 'open'}), `blockedBy`, `open_prs` and `repo`. The
    maps are the org's fields; `type_map` wins over an issue's own `type`.
    `claimed` is the issue numbers a claim ref holds.

      1  a `Stage` other than blank or Backlog: not pickable, except a
         `Blocked` issue the unblock sweep would release now, which is judged
         as if it were in Backlog and listed in `releasable`
      2  assigned, claimed, or closed by an open pull request: not pickable
      3  not `Code agent` (a blank `User Story` or `Bug` counts as one)
      -  a leaf outside `--mode`, or above `--max-effort`, unless a story the
         run could take waits on it (see below)
      4  an open blocked-by edge: not pickable, and reported in `blocked`
      4a under a Parked Epic or Feature: not pickable
      5  any other leaf: pickable as itself
      6  a Feature with pickable stories: pickable, offering those stories
      7  an Epic with a pickable Feature: pickable, taking its best Feature
      8  a childless Epic or Feature, or an unclear leaf: needs refinement

    A filter is about which work to start, not about what that work needs, so
    an open prerequisite of a story in the running is taken whatever `--mode`
    or `--max-effort` says: into the pool when it is ready, into `waiting`
    (and `blocked`) when it waits in turn.

    Returns a dict:
      ranked      pickable and needs-refinement entries in pool order
                  (Priority, then Effort, then number). Each is a copy of
                  the issue with `type`; a container adds `stories`, the
                  pickable story numbers it offers in the same order, and an
                  Epic adds `feature`; a needs-refinement entry adds `unclear`.
      pool        `ranked` without the needs-refinement entries
      excluded    {number: reason} for everything else
      blocked     {number: [open blockers]} for rule 4
      unclassified, oversized   numbers, as `select_pool` reports them
      waiting     {number: [open blockers]} for work held back only by edges
      releasable  `Blocked` numbers whose edges have all closed
      buildable   {number: [open blockers] or None} for every leaf a code
                  agent may build when it is needed: its `Stage` is one a
                  named pick accepts, nobody holds it, and it is code work
      epic        {number: nearest Epic ancestor}
      effective_priority   the Priority each issue carries, inherited
    """
    type_map = type_map or {}
    priority_map = priority_map or {}
    effort_map = effort_map or {}
    ownership_map = ownership_map or {}
    claimed = {int(n) for n in (claimed or ())}
    by_num = {i['number']: i for i in issues}

    def kind(n):
        return type_map.get(n) or (by_num.get(n) or {}).get('type')

    def ancestors(n):
        seen, parent = {n}, (by_num.get(n) or {}).get('parent')
        while parent in by_num and parent not in seen:
            seen.add(parent)
            yield parent
            parent = by_num[parent].get('parent')

    def nearest_feature(n):
        return next((p for p in ancestors(n) if kind(p) == 'Feature'), None)

    def parked_ancestor(n):
        return next((p for p in ancestors(n)
                     if kind(p) in HIERARCHY_CONTAINER_TYPES
                     and stage_name(by_num[p].get('stage')) == STAGE_NAMES['stage-parked']),
                    None)

    def held_by_filter(issue, oversized=None):
        """(why `--mode` or `--max-effort` leaves a leaf out, or None; untyped)."""
        n = issue['number']
        in_mode, untyped = _leaf_in_mode(n, mode, kind, nearest_feature,
                                         classification_map)
        if not in_mode:
            return ('untyped, so `--mode %s` cannot place it' % mode if untyped
                    else 'left out by `--mode %s`' % mode), untyped
        if not _filter_effort([issue], effort_map, max_effort, oversized):
            return 'over the `--max-effort` ceiling', False
        return None, False

    releasable = [i['number'] for i in issues
                  if _releasable(i, kind, ownership_map, claimed)]
    release = set(releasable)

    excluded, blocked, unclassified, oversized = {}, {}, [], []
    eligible, held_ready = [], {}
    for issue in issues:
        n = issue['number']
        type_name = kind(n)
        stage = issue.get('stage')
        if not is_available_stage(stage) and n not in release:
            excluded[n] = '`Stage` is `%s`' % stage
            continue
        if issue.get('assigned'):
            excluded[n] = 'assigned to %s' % (', '.join(issue.get('assignees') or [])
                                              or 'somebody')
            continue
        if n in claimed:
            excluded[n] = 'claimed by another run'
            continue
        if issue.get('open_prs'):
            excluded[n] = 'an open pull request already closes it (%s)' % ', '.join(
                '#%d' % p for p in issue['open_prs'])
            continue
        owner = ownership_map.get(n)
        if effective_scope(owner, type_name) != SCOPE_CODE:
            excluded[n] = ('owned by %s, not the code agent' % owner if owner
                           else 'no `Ownership`, and a %s is not assumed to be code work'
                           % (type_name or 'untyped issue'))
            continue
        container = type_name in HIERARCHY_CONTAINER_TYPES
        if not container:
            reason, untyped = held_by_filter(issue, oversized)
            if reason:
                if untyped:
                    unclassified.append(n)
                excluded[n] = reason
                # Held back by a filter alone. Kept to one side, because a
                # story in the running may wait on it (below).
                if _open_blockers(issue) == [] and parked_ancestor(n) is None:
                    held_ready[n] = issue
                continue
        open_blockers = _open_blockers(issue)
        if open_blockers:
            blocked[n] = open_blockers
            excluded[n] = 'blocked by %s' % ', '.join(ref_label(b) for b in open_blockers)
            continue
        parked = parked_ancestor(n)
        if parked is not None:
            excluded[n] = 'under #%d, which is Parked' % parked
            continue
        eligible.append(issue)

    # Waiting work and what it waits on. A story held back only by an open
    # edge is still work a run could take once its blocker lands, so the
    # blocker inherits its priority: the pool puts a low-priority issue that
    # unblocks an urgent one ahead of the rest of its own band, which is what
    # finishes the urgent one soonest. `waiting` also feeds `plan-set`, which
    # builds a blocker and the stories behind it in one run.
    waiting = _waiting_work(issues, by_num, kind, ancestors, nearest_feature,
                            mode, classification_map, effort_map, max_effort,
                            ownership_map, claimed)
    unfiltered = _waiting_work(issues, by_num, kind, ancestors, nearest_feature,
                               'story', classification_map, effort_map, None,
                               ownership_map, claimed)

    # A prerequisite the filters held back is taken all the same: leaving it
    # out would leave out every story waiting on it too.
    admitted, frontier, seen = set(), [b for bl in waiting.values() for b in bl], set()
    while frontier:
        b = frontier.pop()
        if b in seen or not isinstance(b, int):
            continue
        seen.add(b)
        if b in held_ready and unclear_reason(held_ready[b], kind(b)) is None:
            admitted.add(b)
            eligible.append(held_ready[b])
            excluded.pop(b, None)
        elif b in unfiltered and b not in waiting:
            admitted.add(b)
            waiting[b] = unfiltered[b]
            frontier.extend(unfiltered[b])
            if is_available_stage(by_num[b].get('stage')):
                blocked[b] = unfiltered[b]
                excluded[b] = 'blocked by %s' % ', '.join(ref_label(x)
                                                         for x in unfiltered[b])
    unclassified = [n for n in unclassified if n not in admitted]
    oversized = [n for n in oversized if n not in admitted]

    # A `Blocked` story is out by rule 1, but "its Stage is Blocked" says
    # nothing a person can act on. Say what it is really waiting for.
    blocked_stage = STAGE_NAMES['stage-blocked']
    for issue in issues:
        n = issue['number']
        if (stage_name(issue.get('stage')) != blocked_stage or n in release
                or n in waiting or issue.get('assigned') or n in claimed
                or issue.get('open_prs') or kind(n) in HIERARCHY_CONTAINER_TYPES
                or effective_scope(ownership_map.get(n), kind(n)) != SCOPE_CODE):
            continue
        if n in unfiltered:
            excluded[n] = held_by_filter(issue)[0] or excluded[n]
        elif _open_blockers(issue) == []:
            excluded[n] = ('`%s` with no open blocker, so it waits on something '
                           'other than an issue' % blocked_stage)

    def ordered(entries):
        return _sort_candidates(entries, None, priority_map, effort_map)

    def entry(issue, **extra):
        return dict(issue, type=kind(issue['number']), **extra)

    leaves, unclear = {}, {}
    for issue in eligible:
        n = issue['number']
        if kind(n) in HIERARCHY_CONTAINER_TYPES:
            continue
        reason = unclear_reason(issue, kind(n))
        if reason:
            unclear[n] = entry(issue, unclear=reason)
        else:
            leaves[n] = issue

    def children(issue):
        return [c for c in (issue.get('sub_issues') or {}).get('open') or ()
                if c in by_num]

    features = {}
    for issue in eligible:
        n = issue['number']
        if kind(n) != 'Feature':
            continue
        reason = unclear_reason(issue, 'Feature')
        if reason:
            unclear[n] = entry(issue, unclear=reason)
            continue
        stories = [c['number'] for c in ordered([leaves[c] for c in children(issue)
                                                 if c in leaves])]
        if stories:
            features[n] = entry(issue, stories=stories)
        else:
            excluded[n] = 'nothing under it can be picked'

    epics = {}
    for issue in eligible:
        n = issue['number']
        if kind(n) != 'Epic':
            continue
        reason = unclear_reason(issue, 'Epic')
        if reason:
            unclear[n] = entry(issue, unclear=reason)
            continue
        mine = ordered([features[c] for c in children(issue) if c in features])
        if mine:
            best = mine[0]
            epics[n] = entry(issue, feature=best['number'], stories=best['stories'])
        else:
            excluded[n] = 'no Feature under it can be picked'

    for n, e in unclear.items():
        excluded[n] = 'needs refinement: %s' % e['unclear']

    effective = dict(priority_map)
    unblocks = {}
    for w, blockers in waiting.items():
        wanted = priority_map.get(w)
        frontier, seen = list(blockers), set()
        while frontier:
            b = frontier.pop()
            # A blocker in another repository is not work here to rank.
            if b in seen or b == w or not isinstance(b, int):
                continue
            seen.add(b)
            unblocks.setdefault(b, set()).add(w)
            if wanted and _priority_rank(wanted) < _priority_rank(effective.get(b)):
                effective[b] = wanted
            frontier.extend(waiting.get(b) or ())

    def ordered(entries):
        return _sort_candidates(entries, None, effective, effort_map)

    def with_unblocks(e):
        n = e['number']
        if n in unblocks:
            e = dict(e, unblocks=sorted(unblocks[n]))
            if effective.get(n) != priority_map.get(n):
                e['inherited_priority'] = effective[n]
        return e

    buildable = {}
    for issue in issues:
        n = issue['number']
        stage = (issue.get('stage') or '').strip()
        if (kind(n) in HIERARCHY_CONTAINER_TYPES
                or (stage and stage_name(stage) not in PICKABLE_BY_NAME)
                or issue.get('assigned') or n in claimed or issue.get('open_prs')
                or effective_scope(ownership_map.get(n), kind(n)) != SCOPE_CODE):
            continue
        buildable[n] = _open_blockers(issue)
    epic = {}
    for n in by_num:
        found = next((p for p in ancestors(n) if kind(p) == 'Epic'), None)
        if found is not None:
            epic[n] = found

    leaf_entries = [with_unblocks(entry(i)) for i in leaves.values()]
    for f in list(features.values()) + list(epics.values()):
        f['stories'] = [e['number'] for e in ordered([leaves[s] for s in f['stories']])]
    pool = ordered(leaf_entries + list(features.values()) + list(epics.values()))
    ranked = ordered(pool + list(unclear.values()))
    return {'ranked': ranked, 'pool': pool, 'excluded': excluded,
            'blocked': blocked, 'unclassified': unclassified,
            'oversized': oversized, 'waiting': waiting,
            'releasable': releasable, 'buildable': buildable, 'epic': epic,
            'effective_priority': effective}


def plan_universe(verdict, issues, claimed=()):
    """What `plan_set` chooses from, read off one `evaluate_pool` verdict.

    Returns (universe, rank, reasons). `universe` holds every story in the
    pool, which is ready now, every waiting story a person does not have to
    clarify first, and every open prerequisite of those a code agent may build
    whatever `--mode` or `--max-effort` says, each with its open blockers, its
    parent and its Epic. A story whose edges could not all be read carries
    `blockers` None, never an empty list. `rank` orders them by the priority
    each carries, inherited from what it unblocks. `reasons` says why each
    other open issue cannot be taken, so a plan that needs one names the
    reason rather than calling it unknown.
    """
    by_num = {i['number']: i for i in issues}
    effective = verdict.get('effective_priority') or {}
    epic = verdict.get('epic') or {}

    def story(n, blockers):
        return {'blockers': blockers, 'parent': (by_num.get(n) or {}).get('parent'),
                'epic': epic.get(n)}

    universe, position = {}, {}
    for index, entry in enumerate(verdict.get('pool') or ()):
        if entry.get('stories') is not None:
            continue
        n = entry['number']
        universe[n] = story(n, _open_blockers(by_num.get(n) or entry))
        position[n] = index
    for n, blockers in (verdict.get('waiting') or {}).items():
        issue = by_num.get(n)
        if issue is None or n in universe or unclear_reason(issue, issue.get('type')):
            continue
        universe[n] = story(n, list(blockers))
    admit_prerequisites(universe, verdict, by_num)
    rank = sorted(universe, key=lambda n: (_priority_rank(effective.get(n)),
                                           position.get(n, len(position)), n))
    reasons = dict(verdict.get('excluded') or {})
    for n in universe:
        reasons.pop(n, None)
    claimed = set(claimed or ())
    for issue in issues:
        n = issue['number']
        if n in universe or n in reasons:
            continue
        stage = stage_name(issue.get('stage'))
        if issue.get('assigned'):
            reasons[n] = 'assigned to %s' % (', '.join(issue.get('assignees') or ())
                                             or 'somebody')
        elif n in claimed:
            reasons[n] = 'claimed by another run'
        elif issue.get('open_prs'):
            reasons[n] = 'open pull request %s already closes it' % ', '.join(
                '#%d' % p for p in issue['open_prs'])
        elif stage and not is_available_stage(stage):
            reasons[n] = 'its Stage is %s' % stage
    return universe, rank, reasons


def admit_prerequisites(universe, verdict, by_num, reasons=None):
    """Add to `universe`, in place, every open prerequisite of a story in it
    that a code agent may build, however far down the chain.

    `buildable` in the verdict decides: code work nobody holds, not a
    container, with a `Stage` a named pick accepts. `--mode` and
    `--max-effort` do not come into it, because they choose which work to
    start, not what that work needs. A prerequisite a person has to clarify
    first stays out. Each one admitted is dropped from `reasons`. Returns the
    numbers admitted.
    """
    buildable = verdict.get('buildable') or {}
    epic = verdict.get('epic') or {}
    admitted = []
    frontier = [b for s in universe.values() for b in s.get('blockers') or ()]
    while frontier:
        b = frontier.pop()
        if not isinstance(b, int) or b in universe or b not in buildable:
            continue
        issue = by_num.get(b) or {}
        if unclear_reason(issue, issue.get('type')):
            continue
        blockers = buildable[b]
        universe[b] = {'blockers': None if blockers is None else list(blockers),
                       'parent': issue.get('parent'), 'epic': epic.get(b)}
        admitted.append(b)
        if reasons is not None:
            reasons.pop(b, None)
        frontier.extend(blockers or ())
    return admitted


def _waiting_work(issues, by_num, kind, ancestors, nearest_feature, mode,
                  classification_map, effort_map, max_effort, ownership_map,
                  claimed):
    """`{number: [open blockers]}` for every story a code agent could take
    but for an open blocked-by edge.

    Its `Stage` is blank, `Backlog` or `Blocked`, nobody holds it, it is code
    work in `--mode` under no Parked container, and every edge was read. An
    issue in `Blocked` with no open edge waits on a person, not an issue, so
    it is not here. `evaluate_pool` calls this a second time with no filter,
    to find the prerequisites a filter must not hold back.
    """
    blocked_stage = STAGE_NAMES['stage-blocked']
    out = {}
    for issue in issues:
        n = issue['number']
        type_name = kind(n)
        stage = issue.get('stage')
        if not (is_available_stage(stage) or stage_name(stage) == blocked_stage):
            continue
        if (issue.get('assigned') or n in claimed or issue.get('open_prs')
                or type_name in HIERARCHY_CONTAINER_TYPES
                or effective_scope(ownership_map.get(n), type_name) != SCOPE_CODE):
            continue
        blockers = _open_blockers(issue)
        if not blockers:
            continue
        if not _leaf_in_mode(n, mode, kind, nearest_feature, classification_map)[0]:
            continue
        if not _filter_effort([issue], effort_map, max_effort):
            continue
        if any(kind(p) in HIERARCHY_CONTAINER_TYPES
               and stage_name(by_num[p].get('stage')) == STAGE_NAMES['stage-parked']
               for p in ancestors(n)):
            continue
        out[n] = blockers
    return out
