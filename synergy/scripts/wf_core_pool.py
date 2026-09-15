"""
Choosing work from the issue tree: the verdict on every open issue in the pool.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

import re

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
    again in full."""
    edges = issue.get('blockedBy') or {}
    nodes = edges.get('nodes') or []
    total = edges.get('totalCount')
    if total is not None and total > len(nodes):
        return None
    return sorted(n['number'] for n in nodes
                  if (n.get('state') or '').upper() == 'OPEN' and n.get('number'))


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
    `sub_issues` ({'total', 'open'}), `blockedBy` and `open_prs`. The maps
    are the org's fields; `type_map` wins over an issue's own `type`.
    `claimed` is the issue numbers a claim ref holds.

      1  a `Stage` other than blank or Backlog: not pickable
      2  assigned, claimed, or closed by an open pull request: not pickable
      3  not `Code agent` (a blank `User Story` or `Bug` counts as one)
      -  a leaf outside `--mode`, or above `--max-effort`
      4  an open blocked-by edge: not pickable, and reported in `blocked`
      4a under a Parked Epic or Feature: not pickable
      5  any other leaf: pickable as itself
      6  a Feature with pickable stories: pickable, offering those stories
      7  an Epic with a pickable Feature: pickable, taking its best Feature
      8  a childless Epic or Feature, or an unclear leaf: needs refinement

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

    excluded, blocked, unclassified, oversized = {}, {}, [], []
    eligible = []
    for issue in issues:
        n = issue['number']
        type_name = kind(n)
        stage = issue.get('stage')
        if not is_available_stage(stage):
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
            in_mode, untyped = _leaf_in_mode(n, mode, kind, nearest_feature,
                                             classification_map)
            if not in_mode:
                if untyped:
                    unclassified.append(n)
                excluded[n] = ('untyped, so `--mode %s` cannot place it' % mode
                               if untyped else 'left out by `--mode %s`' % mode)
                continue
            if not _filter_effort([issue], effort_map, max_effort, oversized):
                excluded[n] = 'over the `--max-effort` ceiling'
                continue
        open_blockers = _open_blockers(issue)
        if open_blockers:
            blocked[n] = open_blockers
            excluded[n] = 'blocked by %s' % ', '.join('#%d' % b for b in open_blockers)
            continue
        parked = next((p for p in ancestors(n)
                       if kind(p) in HIERARCHY_CONTAINER_TYPES
                       and stage_name(by_num[p].get('stage')) == STAGE_NAMES['stage-parked']),
                      None)
        if parked is not None:
            excluded[n] = 'under #%d, which is Parked' % parked
            continue
        eligible.append(issue)

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

    pool = ordered([entry(i) for i in leaves.values()]
                   + list(features.values()) + list(epics.values()))
    ranked = ordered(pool + list(unclear.values()))
    for n, e in unclear.items():
        excluded[n] = 'needs refinement: %s' % e['unclear']
    return {'ranked': ranked, 'pool': pool, 'excluded': excluded,
            'blocked': blocked, 'unclassified': unclassified,
            'oversized': oversized}
