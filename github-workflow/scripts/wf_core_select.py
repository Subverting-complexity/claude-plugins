"""
Story selection: the local filter and sort over candidates, native issue type
filtering and backlog-mode detection.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

from wf_core_fields import EFFORT_RANK, _effort_rank, _priority_rank
from wf_core_stage import SCOPE_CODE, effective_scope


# ── Native issue type filtering ────────────────────────────────────────────
# The native issueType is the only thing that classifies an issue. There is no
# `type-*` label path any more, on any org: a label saying `bug` beside a type
# saying `Bug` is two answers to one question, and the two drifted apart the
# moment anyone edited either. The type_map is built from a single GraphQL
# query in wf.py and passed through select_pool. An org that has not enabled
# native issue types cannot answer a feature/maintenance question at all, and
# `wf pick` says so rather than guessing.
#
# Native type map (NATIVE_TYPE_MAP below):
#   feature mode  → keep User Story
#   maintenance   → keep Bug + Chore + Feature (with Classification filter
#                   if available)
#
# `Chore` is unconditional rather than classification-filtered because an org
# only has that type if it added it, and it added it for exactly this work.
# It has to be here: the moment tech debt starts being typed `Chore` (see
# `NATIVE_TYPE_PREFERENCES`), a maintenance pool that only knows about `Bug`
# and `Feature` stops returning any of it, and an empty pool reads as a clean
# backlog rather than as a filter that no longer matches anything.

NATIVE_FEATURE_TYPES = frozenset({'User Story'})
NATIVE_CONTAINER_TYPES = frozenset({'Epic'})
# The levels of the Epic -> Feature -> story tree that group work rather than
# being it. Wider than `NATIVE_CONTAINER_TYPES` on purpose: the pool still
# offers an untyped-tree `Feature` as work, but a walk of the tree treats one
# as a grouping level, which is what a Feature with stories under it is.
HIERARCHY_CONTAINER_TYPES = frozenset({'Epic', 'Feature'})
NATIVE_MAINTENANCE_TYPES = frozenset({'Bug', 'Chore'})
NATIVE_MAINTENANCE_CLASSIFIABLE_TYPES = frozenset({'Feature'})
MAINTENANCE_CLASSIFICATIONS = frozenset({
    'Tech Debt', 'Architecture', 'Security',
})

# On a type-capable org the native type is the *only* classifier. There is
# deliberately no `type-*` label or `[PREFIX]` title fallback here: guessing
# from a label the workflow no longer writes, or a prefix it no longer adds,
# reintroduces the two-sources-of-truth problem native types exist to end --
# and it guessed wrongly, routing an untyped `[CHORE]` into feature mode while
# a natively typed `Chore` went to maintenance. An issue the org has not typed
# is neither mis-filed nor silently dropped: it is left out of the mode pool
# and named to the caller, so it reads as a gap in the data somebody can fill
# rather than a guess nobody can see.
#
# Orgs with no native types at all never reach this function. `_filter_by_mode`
# reads their `type-*` labels, which for them are the real classification
# rather than a shadow of one.
#
# An epic is in no set on purpose: it is a container for work rather than work,
# which is why `NATIVE_FEATURE_TYPES` excludes the native `Epic`.


def is_maintenance_classification(value):
    """True when a `Classification` value marks the issue as maintenance work.

    Classification is a multi-select, so a value arrives as a list at least as
    often as a string, and one maintenance option among several is enough --
    an issue classified `Architecture, New Feature` is architecture work that
    also ships something new, and maintenance mode is where it belongs.
    """
    if not value:
        return False
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return any(v in MAINTENANCE_CLASSIFICATIONS for v in values)


def filter_by_native_type(candidates, mode, type_map, classification_map=None,
                          project_map=None, unclassified=None):
    """Filter candidates by native issue type (type-capable orgs).

    feature mode: keep only User Story.
    maintenance mode: keep Bug and Chore unconditionally, plus Feature when the
    Classification field marks it as maintenance work. With no Classification
    field to read at all (`classification_map` is None) every Feature is kept:
    a stray candidate beats a missed one when the org cannot answer at all.
    story mode: every type except `Epic`. An epic is the outcome its features
    and stories deliver, so handing one to an agent hands it the whole tree
    under it at once; found live, when the pool offered a freshly filed epic
    beside its own stories.

    The org's own answer is the only one consulted. An issue it has not typed,
    and a `Feature` it has not classified on an org that does classify, are
    left out of the mode pool and their numbers appended to `unclassified` when
    a list is passed, so the caller can name them. Neither is guessed at from a
    `type-*` label or a `[PREFIX]` title: the workflow stopped writing both on
    type-capable orgs, so reading them would be reading its own stale exhaust.
    """
    if mode == 'story':
        return [c for c in candidates
                if type_map.get(c['number']) not in NATIVE_CONTAINER_TYPES]
    result = []
    for c in candidates:
        native_type = type_map.get(c['number'])
        classification = classification_map.get(c['number']) if classification_map else None
        if not native_type:
            if unclassified is not None:
                unclassified.append(c['number'])
            continue
        if mode == 'feature':
            if native_type in NATIVE_FEATURE_TYPES:
                result.append(c)
        elif mode == 'maintenance':
            if native_type in NATIVE_MAINTENANCE_TYPES:
                result.append(c)
            elif native_type in NATIVE_MAINTENANCE_CLASSIFIABLE_TYPES:
                if classification_map is None:
                    result.append(c)
                elif is_maintenance_classification(classification):
                    result.append(c)
                elif not classification and unclassified is not None:
                    # A `Feature` on an org that does classify, carrying no
                    # value of its own: unanswerable, so it is named rather
                    # than guessed at.
                    unclassified.append(c['number'])
    return result


def _filter_unavailable(candidates, project_map=None, ownership_map=None,
                        type_map=None):
    """Exclude backlog issues that a code agent must not be handed.

    The pool is the open issues whose `Stage` is blank or `Backlog`, so `Stage`
    has already excluded everything in another stage: an issue that is in
    progress, in review, blocked, parked or done says so and is not here.
    `Stage` is single-valued, which is what makes the pool an exclusion in its
    own right.

    What remains is the one thing a stage cannot express, because it is a
    property of the work rather than a position in a workflow: **who can do
    it**. An issue scoped to a person or a browser agent is not work a code
    agent can finish, and one can sit in Backlog perfectly legitimately — a
    person filed it there, or it was moved back when its dependency closed.

    `ownership_map` is ``{issue_number: Ownership option name}`` from the org's
    own field, and it is the only input. An issue with no value in it is **not**
    handed to a code agent: `Ownership` is a mandatory field, preflight fails
    when the org does not define it, and `issue-audit` names every issue missing
    a value, so a blank is a reported gap rather than a silent "probably code".
    Guessing the safe-looking answer is what the `browser-agent` /
    `human-required` label fallback did until 10.0.0, and the guess was wrong in
    the one direction that matters -- an unlabelled issue that needed a person
    read as code work and was picked up by an agent that could not finish it.

    This used to read six lifecycle labels and treat `status-ready` as the only
    one meaning "pick me". That was the opt-in model: an issue was invisible
    until somebody remembered to mark it. A blank `Stage` is the opt-out
    replacement, and it cannot be forgotten, because an issue nobody has
    decided anything about is available by default.
    """
    ownership_map = ownership_map or {}
    type_map = type_map or {}
    # Since 12.4.0 one blank is answered: a `User Story` or `Bug` with no
    # `Ownership` is code work (`effective_scope`). Every other blank still
    # keeps the issue out.
    return [c for c in candidates
            if effective_scope(ownership_map.get(c['number']),
                               type_map.get(c['number']) or c.get('type')) == SCOPE_CODE]


def _filter_effort(candidates, effort_map, max_effort, oversized=None):
    """Drop anything estimated larger than the session can finish.

    Off unless a caller asks for it, because a ceiling nobody set should not
    quietly shrink a backlog. An issue with no estimate is always kept: a
    ceiling is a statement about known size, and refusing to consider
    unestimated work would hide most of a young backlog behind a flag.
    """
    if not max_effort:
        return list(candidates)
    ceiling = EFFORT_RANK.get(str(max_effort).strip().lower())
    if ceiling is None:
        return list(candidates)
    effort_map = effort_map or {}
    keep = []
    for c in candidates:
        rank = EFFORT_RANK.get(str(effort_map.get(c['number']) or '').strip().lower())
        if rank is None or rank <= ceiling:
            keep.append(c)
        elif oversized is not None:
            oversized.append(c['number'])
    return keep


def _sort_candidates(candidates, project_map=None, priority_map=None,
                     effort_map=None):
    """Sort by priority, then by effort, then by issue number.

    `priority_map` is ``{issue_number: Priority option name}`` read from the
    org's own field, and it is the only ranking input. An issue with no value
    sorts last within the pool rather than being ranked from a `priority-*`
    label -- see `_priority_rank` for why that fallback went.

    `effort_map` is ``{issue_number: Effort option name}``, and it breaks the
    tie *within* a priority band rather than across bands: a Low-effort issue
    never overtakes a more urgent one. Smaller first, so a band is cleared from
    the cheap end and a session that can only fit one item gets the one most
    likely to finish. An issue with no Effort value sorts as if it were Medium
    — the middle rather than the back, because an unestimated issue is unknown,
    not large, and pushing every unestimated issue behind every estimated one
    would reorder a backlog on the strength of missing data.
    """
    priority_map = priority_map or {}
    effort_map = effort_map or {}
    return sorted(candidates,
                  key=lambda c: (_priority_rank(priority_map.get(c['number'])),
                                 _effort_rank(effort_map.get(c['number'])),
                                 c['number']))


def select_story(candidates, mode='story', project_map=None,
                 priority_map=None, **kwargs):
    """Full selection pipeline: filter → sort → top candidate (or None).

    Returns the single best candidate, never a list — the caller claims it.
    The claim-first/validate-lazily loop in wf.py walks the *sorted* pool when
    a claim is lost or a candidate proves blocked, so this returns the ordered
    survivors via `select_pool`; `select_story` is the convenience head.
    """
    pool = select_pool(candidates, mode, project_map,
                       priority_map=priority_map, **kwargs)
    return pool[0] if pool else None


def select_pool(candidates, mode='story', project_map=None,
                type_map=None, classification_map=None, unclassified=None,
                priority_map=None, effort_map=None, ownership_map=None,
                max_effort=None, oversized=None):
    """The ordered, filtered candidate list (best first). Empty list if none.

    No filter here reads a label, and there is no `agent_gating` argument any
    more. Human approval used to be a `claude-ready` label a person applied
    during triage, and it was the last label with a say in what gets picked;
    it is now the issue's `Stage`, which is the same answer in the place every
    other state already lives. A person approves an issue by leaving `Stage`
    blank or setting `Backlog`, and withholds approval with Needs refinement or
    Parked. `project_map` survives for the label names the *writers* resolve.

    `type_map` is a dict of ``{issue_number: native_type_name}`` built from a
    GraphQL query, and it is the only classifier: outside `story` mode, an org
    that supplies none has no way to tell a bug from a story, so every
    candidate comes back named in `unclassified` and the pool is empty.
    `classification_map` is an optional
    companion dict of ``{issue_number: classification_option_name}`` for
    refining Feature-typed issues in maintenance mode. `unclassified`, when
    passed a list, is appended with the number of every candidate the org has
    not typed (or, for a `Feature`, not classified) and which was therefore
    left out of the pool, so the caller can name the gap rather than return a
    quietly short list.

    `priority_map` is ``{issue_number: Priority option name}`` from the org's
    own field, and it is the whole of the pool's order. An issue absent from it
    sorts last and is named by the caller -- there is no label to fall back to,
    on purpose.

    `effort_map` is the same shape for the org's `Effort` field. It breaks ties
    inside a priority band, and with `max_effort` it also excludes: a session
    that cannot fit a High-effort story should not be handed one and then have
    to give it back. Every issue excluded that way is appended to `oversized`
    when a list is passed, so the run can say the pool was trimmed rather than
    report a backlog that looks empty.

    `ownership_map` is ``{issue_number: Ownership option name}``, and it is the
    only thing that decides whether a code agent may take an issue. Anything it
    does not mark `Code agent` is out of the pool -- including an issue it says
    nothing about, because an unanswered question is not a yes.
    """
    if mode == 'story':
        # Every type but a container. An org with no types has no epics to
        # leave out, so the whole pool stands.
        pool = filter_by_native_type(candidates, mode, type_map or {})
    elif type_map:
        pool = filter_by_native_type(candidates, mode, type_map, classification_map,
                                     project_map, unclassified)
    else:
        # No native types on this org, and nothing else classifies an issue.
        # Every candidate is unanswerable rather than eligible -- naming them
        # is the whole point, since a pool that silently held everything would
        # route a story into maintenance mode.
        if unclassified is not None:
            unclassified.extend(c['number'] for c in candidates)
        pool = []
    pool = _filter_unavailable(pool, project_map, ownership_map, type_map)
    pool = _filter_effort(pool, effort_map, max_effort, oversized)
    return _sort_candidates(pool, project_map, priority_map, effort_map)


# ── Backlog-mode detection ───────────────────────────────────────────────────
# Backlog mode — sprint vs flat from milestone presence.

def detect_backlog_mode(candidates):
    """Return 'sprint' if any candidate has a milestone, otherwise 'flat'."""
    return 'sprint' if any(c.get('milestone') for c in candidates) else 'flat'


def get_sprint_candidates(candidates, sprint_title):
    """Narrow candidates to those belonging to the active sprint."""
    return [c for c in candidates if c.get('milestone') == sprint_title]
