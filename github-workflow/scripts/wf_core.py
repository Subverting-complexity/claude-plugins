#!/usr/bin/env python3
"""
Pure decision logic for the `wf` workflow CLI.

This module is the **canonical, executable** encoding of the selection rules
that the workflow templates describe in prose — story selection, label
resolution, backlog-mode detection, dependency parsing, and branch naming.

It is deliberately **pure**: no GitHub API calls, no `git`, no file or network
I/O. Feed plain dicts/strings in, get decisions out. The I/O shell that talks
to `gh`/`git` lives in `wf.py`; the offline test suite
(`tests/test_decision_logic.py`) imports *this* module directly so the rules
stay verifiable without a network.

Reference templates (the prose these functions encode):
  - github-workflow/templates/default-labels.md
  - github-workflow/skills/execute/SKILL.md  (branch convention)
"""

import datetime
import re

# ── Story selection ──────────────────────────────────────────────────────────
# The local, no-API filter + sort — the claim/validate loop around it lives
# in wf.py. This module is the only encoding of these rules.

_PRIORITY_ORDER = ['priority-critical', 'priority-high', 'priority-medium', 'priority-low']


def _priority_rank(field_value):
    """Returns sort key: 0=critical … 3=low, 4=unprioritised.

    The org's `Priority` field is the only input. It is what a person sets in
    the portal, what the portal's own views order by, and what the tooling
    writes on every issue it creates.

    There was a `priority-*` label fallback here until 10.0.0, and removing it
    is the point rather than a simplification. Two answers to "how urgent is
    this" drift the moment anyone edits either, and the drift is invisible:
    the picker silently preferred one issue over another on the strength of a
    label somebody set months ago and the field disagreed with. `Priority` is
    now a field the org must define and every issue must carry -- preflight
    fails when the field is absent and `issue-audit` names any issue missing a
    value, so an unranked issue is a reported gap rather than a quiet
    reordering. An unrecognised option name ranks last for the same reason:
    guessing at a renamed option is the drift again.
    """
    if field_value:
        rank = PRIORITY_FIELD_RANK.get(str(field_value).strip().lower())
        if rank is not None:
            return rank
    return len(_PRIORITY_ORDER)


# ── Native issue type filtering ────────────────────────────────────────────
# The native issueType is the only thing that classifies an issue. There is no
# `type-*` label path any more, on any org: a label saying `bug` beside a type
# saying `Bug` is two answers to one question, and the two drifted apart the
# moment anyone edited either. The type_map is built from a single GraphQL
# query in wf.py and passed through select_pool. An org that has not enabled
# native issue types cannot answer a feature/maintenance question at all, and
# `wf pick` says so rather than guessing.
#
# Native type map (from templates/default-labels.md):
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


def _filter_unavailable(candidates, project_map=None, ownership_map=None):
    """Exclude backlog issues that a code agent must not be handed.

    The pool is the board's Backlog column, so the board's own `Status` field
    has already excluded everything in another lane: an issue that is in
    progress, in review, blocked, parked or done is in that column and not this
    one. `Status` is single-valued, which is what makes the pool an exclusion
    in its own right.

    What remains is the one thing a column cannot express, because it is a
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
    until somebody remembered to mark it. The board column is the opt-out
    replacement, and it cannot be forgotten, because putting the card somewhere
    is how an issue gets onto the board at all.
    """
    ownership_map = ownership_map or {}
    return [c for c in candidates
            if ownership_scope(ownership_map.get(c['number'])) == SCOPE_CODE]


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
    it is now the card's column, which is the same answer in the place every
    other state already lives. A person approves an issue by moving its card
    into Backlog, and withholds approval by leaving it in Needs refinement or
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
    pool = _filter_unavailable(pool, project_map, ownership_map)
    pool = _filter_effort(pool, effort_map, max_effort, oversized)
    return _sort_candidates(pool, project_map, priority_map, effort_map)


# ── Label resolution ─────────────────────────────────────────────────────────
# github-workflow/templates/default-labels.md — "The single resolution path".

# `type-*` is deliberately absent. The native issue type is what classifies an
# issue; a label that repeats it is a second answer nothing reads, and a
# project that still maps one is told to drop the row by
# `deprecated_label_findings`. The names survive in `TYPE_LABEL_KINDS` only so
# the write path can recognise and remove them.
_DEFAULT_LABELS = {
    'claude-authored': 'claude-authored',
}

# Every label that used to answer a question the structured fields now answer.
# They are kept here, and nowhere else, so the write path can recognise one on
# an existing issue and take it off -- and so `deprecated_label_findings` can
# name a project still carrying them. Nothing reads one to make a decision.
#
# `status-*` and `needs-refinement` said what state an issue was in. The board's
# `Status` field says it now, and says it once: a label and a column are two
# records of one fact, and on a real board they disagreed often enough that
# `wf unblock` had to be written to reconcile them. `Status` holds one value and
# a card sits in one column, so there is nothing left to reconcile.
#
# `browser-agent` and `human-required` said who owned the work. The `Ownership`
# field says it now, and unlike the labels it can be grouped by in a board view,
# it cannot be set to two values at once, and it is mandatory, so an issue that
# does not say who owns it is refused at creation rather than picked up by a
# code agent that cannot finish it.
#
# `priority-*` said how urgent the work was, alongside a `Priority` field that
# said the same thing and disagreed. See `_priority_rank`.
#
# `claude-ready` was the human-approval gate, and the last label with a say in
# what got picked. Approval is the card's column now: a person approves an
# issue by moving it into Backlog and withholds approval by leaving it in Needs
# refinement or Parked. That is the same answer in the place every other state
# already lives, and it removes the mode where a fully configured backlog
# selected nothing because nobody had applied a label.
RETIRED_LABELS = {
    'status-ready': 'status-ready',
    'status-in-progress': 'status-in-progress',
    'status-parked': 'status-parked',
    'status-blocked': 'status-blocked',
    'status-non-code': 'status-non-code',
    'status-in-review': 'status-in-review',
    'status-needs-attention': 'status-needs-attention',
    'needs-refinement': 'needs-refinement',
    'scope-browser': 'browser-agent',
    'scope-human': 'human-required',
    'priority-critical': 'priority-critical',
    'priority-high': 'priority-high',
    'priority-medium': 'priority-medium',
    'priority-low': 'priority-low',
    'claude-ready': 'claude-ready',
}

def retired_label_variants(labels, project_map=None):
    """Retired labels on an issue, punctuation variants included.

    `retired_labels_on` matches the exact names, which is what the write path
    wants: it takes a label off somebody's issue, so it may only take off the
    ones this workflow put there. Reporting is the looser question -- a repo
    carrying `status:ready` beside `status-ready` has two spellings of one
    retired idea, and a person filtering the list sees whichever they typed --
    so the check that names them flattens the separators first.
    """
    known = {_drift_key(resolve_label(key, project_map or {}, RETIRED_LABELS))
             for key in RETIRED_LABELS}
    out = []
    for name in labels or ():
        if _drift_key(name) in known and name not in out:
            out.append(name)
    return out


def resolve_label(purpose_key, project_map, defaults=None):
    """Resolve a purpose key to a concrete label name.

    Resolution order (from default-labels.md — "The single resolution path"):
    1. Project map (ClaudeProject.md label map, already in context at runtime).
    2. Default inventory (the table in default-labels.md).
    3. The key itself as a last resort so callers never get an empty string.
    """
    if defaults is None:
        defaults = _DEFAULT_LABELS
    return project_map.get(purpose_key) or defaults.get(purpose_key) or purpose_key


def retired_labels_on(labels, project_map=None):
    """Every retired label the issue still carries, in a stable order.

    The write path takes these off whatever issue it touches, which is how a
    backlog written under the label workflow migrates to the field one without
    anybody sweeping it by hand: an issue is cleaned the next time a command
    touches it, and `config-audit` names the ones no command has reached.
    """
    project_map = project_map or {}
    present = set(labels or ())
    out = []
    for key in RETIRED_LABELS:
        name = resolve_label(key, project_map, RETIRED_LABELS)
        if name in present and name not in out:
            out.append(name)
    return out


# ── Issue types + org field values ───────────────────────────────────────────
# The canonical purpose→value maps for native issue types and org issue
# fields. These were markdown tables, which meant nothing could validate them
# and every consumer re-read prose to apply them. The tables in those files are now
# generated from here; this module is the source of truth.
#
# A project overrides any *field name* in `ClaudeProject.md` →
# `## Issue Types & Fields`, resolved through `resolve_field_name()` — the same
# project-map-then-default path `resolve_label()` uses for labels.

# Workflow kind → native issue type, `Classification` option, and the `type-*`
#
# The Classification entry is the default "by nature" choice, not the only
# valid one. For a bug, prefer `Regression` when something previously worked
# and broke, or `Performance` when the defect is speed or memory. For a
# feature, prefer `Enhancement` when it improves something existing,
# `Integration` when the work is connecting to an external system,
# `Documentation` when it tracks docs only, or `Performance` when speed is the
# point.
NATIVE_TYPE_MAP = {
    'story':        {'type': 'User Story', 'classification': 'New Feature'},
    'bug':          {'type': 'Bug',        'classification': 'Bug Fix'},
    'security':     {'type': 'Bug',        'classification': 'Security'},
    'tech debt':    {'type': 'Feature',    'classification': 'Tech Debt'},
    'architecture': {'type': 'Feature',    'classification': 'Architecture'},
    'feature':      {'type': 'Feature',    'classification': 'New Feature'},
    'epic':         {'type': 'Epic',       'classification': 'New Feature'},
    'spike':        {'type': 'User Story', 'classification': 'Spike'},
    'chore':        {'type': 'User Story', 'classification': 'Chore'},
}

# The type above is the one GitHub always offers. Where an org has enabled a
# better-fitting type, that one wins — this is the preference, in order, and
# `native_type_for()` walks it against the types the org actually has.
#
# Tech debt and chores are the reason this exists. GitHub's built-in set has
# nothing for work that is neither a defect nor a new capability, so both were
# mapped to types that plainly are not what they are: `Feature` for tech debt
# and `User Story` for a chore. An org that has since added `Chore` gets an
# audit reporting every one of its `[DEBT]` issues as a contradiction, with
# the map itself as the thing in the wrong. Preferences are only ever taken
# when the org has the type, so an org with the default set is unaffected.
# Architecture work is deliberately not here. It changes what the system is,
# which `Feature` expresses well enough, and the one org measured had already
# typed all five of its `[ARCH]` issues that way.
NATIVE_TYPE_PREFERENCES = {
    'tech debt': ('Chore',),
    'chore':     ('Chore',),
}


def native_type_for(kind, type_map=None):
    """The native issue type for a kind, given the types an org has enabled.

    `type_map` is the org's `name -> id` map from `org-capabilities`. Without
    it the always-available type is returned, so every caller that has not
    resolved capabilities keeps its previous answer.
    """
    mapped = NATIVE_TYPE_MAP.get(kind)
    if not mapped:
        return None
    if type_map:
        for preferred in NATIVE_TYPE_PREFERENCES.get(kind, ()):
            if preferred in type_map:
                return preferred
    return mapped['type']

# Every valid `Classification` option. A value outside this set is a spec
# error, not a new option — the org owns the field, and adding to it is a
# deliberate org-level change.
CLASSIFICATION_OPTIONS = (
    'New Feature', 'Enhancement', 'Bug Fix', 'Regression', 'Performance',
    'Security', 'Tech Debt', 'Architecture', 'Integration', 'Spike', 'Chore',
    'Documentation', 'Accessibility',
)

# The only Classification values that contradict the kind an issue claims to
# be. `NATIVE_TYPE_MAP` names a *default* classification per kind; almost every
# other value is a legitimate refinement rather than a disagreement, so the
# audit states what cannot be true instead of enumerating what may.
#
# Most of the field says which *area* the work touches — Security, Performance,
# Accessibility, Documentation, Integration — and any kind of work can touch
# any area. Real backlogs are full of accessibility debt, documentation debt
# and security debt, all correctly labelled. Only two small groups say what
# kind of *change* it is, and those are the ones that can conflict:
#
#   `Bug Fix` / `Regression`  — something worked, or should have, and does not.
#   `New Feature` / `Enhancement` — capability that was not there before.
#
# A story is not a regression; a bug is not a new feature; tech debt is by
# definition not new capability. Everything else is left alone. Comparing
# against the default instead produced eleven findings on one real backlog and
# every one of them was wrong, which is worse than no check at all: it teaches
# the reader to skip the output.
_DEFECT_CLASSIFICATIONS = frozenset({'Bug Fix', 'Regression'})
_NEW_WORK_CLASSIFICATIONS = frozenset({'New Feature', 'Enhancement'})

INCOMPATIBLE_CLASSIFICATIONS = {
    'story':        _DEFECT_CLASSIFICATIONS,
    'feature':      _DEFECT_CLASSIFICATIONS,
    'epic':         _DEFECT_CLASSIFICATIONS,
    'bug':          _NEW_WORK_CLASSIFICATIONS,
    'security':     _NEW_WORK_CLASSIFICATIONS,
    'tech debt':    _NEW_WORK_CLASSIFICATIONS,
    'architecture': _NEW_WORK_CLASSIFICATIONS,
    'chore':        _NEW_WORK_CLASSIFICATIONS,
}


def classification_conflicts(kind, values):
    """The values on `kind` that contradict it, or [] when none do.

    A kind with no rule conflicts with nothing: the audit should not invent one
    for a kind this module does not model.
    """
    barred = INCOMPATIBLE_CLASSIFICATIONS.get(str(kind or '').lower())
    if not barred:
        return []
    return [v for v in values if v in barred]


# Purpose key → default org field name, and the field's data type. The data
# type decides which mutation shape a value needs, so it belongs next to the
# name rather than being re-derived from the live schema every time.
FIELD_NAME_DEFAULTS = {
    'field-priority':      'Priority',
    'field-effort':        'Effort',
    'field-ownership':     'Ownership',
    'field-type':          'Classification',
    'field-origin':        'Origin',
    'field-start':         'Start date',
    'field-target':        'Target date',
}

FIELD_DATA_TYPES = {
    'field-priority':      'single-select',
    'field-effort':        'single-select',
    'field-ownership':     'single-select',
    'field-type':          'multi-select',
    'field-origin':        'single-select',
    'field-start':         'date',
    'field-target':        'date',
}

# The fields a decision reads. An issue missing one of these is an issue the
# workflow cannot act on, so a spec that omits one is refused and preflight
# fails on an org that has not created one.
#
#   Priority   the whole of the pool's sort order
#   Effort     the size ceiling `--max-effort` applies, and the tie-break
#              within a priority band
#   Ownership  whether a code agent may pick the issue up at all
#
# There is a fourth required answer and it is not an org field: **state**,
# which is the board column the card sits in. It is required the same way and
# checked the same way -- every write places the card, and `config-audit` fails
# on an open issue with no card (`board-orphan`) or a card in no lane
# (`board-unset`). It is not in this tuple because nothing writes it through
# the field path.
MANDATORY_FIELD_KEYS = ('field-priority', 'field-effort', 'field-ownership')

# Fields the tooling fills in when it can and does not require. Nothing selects
# on them: `Classification` separates a `Feature` that is tech debt from one
# that is new work, which narrows a maintenance pool the native issue type has
# already chosen, and `Origin` records where a piece of work came from. Both
# are worth having and neither is worth refusing an issue over.
#
# A missing one is said out loud rather than swallowed: the writer leaves a
# comment on the issue naming what was left unset, so the gap is visible to
# whoever reads the issue instead of only to whoever reads stderr.
OPTIONAL_FIELD_KEYS = ('field-type', 'field-origin')


def unset_optional_comment(names):
    """The comment body for optional fields an issue was created without."""
    if not names:
        return None
    return (
        'Filed without %s. Nothing selects on %s, so this issue is pickable as '
        'it stands -- but %s worth setting: `Classification` is what separates '
        'a `Feature` that is tech debt from one that is new work, and `Origin` '
        'records where the work came from.\n\n'
        'Set %s in the issue form, or run `wf issue-audit` and apply the spec '
        'it writes to sweep the backlog.'
        % (_names(sorted(names)),
           'it' if len(names) == 1 else 'them',
           'it is' if len(names) == 1 else 'they are',
           'it' if len(names) == 1 else 'them'))

# `priority-*` label purpose → `Priority` field option. The field is what the
# picker orders by (`_priority_rank`) and what the portal's views show; this map
# is how an issue's label is turned into a field value when one is created or
# backfilled, and how a field-less issue is still ordered.
PRIORITY_FIELD_OPTIONS = {
    'priority-critical': 'Urgent',
    'priority-high':     'High',
    'priority-medium':   'Medium',
    'priority-low':      'Low',
}

# `Priority` field option → the same sort rank the `priority-*` label carries,
# derived from the two structures above so a new level cannot be added to one
# and forgotten in the other. Keyed lower-case: the picker matches the org's
# stored option name case-insensitively, and falls back to the label when the
# org renamed its options to something this map does not know.
PRIORITY_FIELD_RANK = {PRIORITY_FIELD_OPTIONS[key].lower(): rank
                       for rank, key in enumerate(_PRIORITY_ORDER)}

# Story size estimate → `Effort` field option.
EFFORT_FIELD_OPTIONS = {
    'large':  'High',
    'medium': 'Medium',
    'small':  'Low',
}

# `Effort` option → sort rank, smallest first. The picker orders on this inside
# a priority band and `--max-effort` compares against it, so the two cannot
# disagree about which of two estimates is the bigger. Keyed lower-case, like
# `PRIORITY_FIELD_RANK`, because the value read back from the org is whatever
# case it was stored in.
EFFORT_RANK = {'low': 0, 'medium': 1, 'high': 2}

# What an issue with no estimate sorts as. The middle, not the back: an
# unestimated issue is unknown rather than large, and sorting every one of them
# behind every estimated one would reorder a backlog on missing data.
EFFORT_RANK_DEFAULT = EFFORT_RANK['medium']


def _effort_rank(field_value):
    """Sort key for an `Effort` value: 0=Low, 1=Medium, 2=High, 1 when unset."""
    if not field_value:
        return EFFORT_RANK_DEFAULT
    return EFFORT_RANK.get(str(field_value).strip().lower(), EFFORT_RANK_DEFAULT)

# Creating command or session → `Origin` field option.
ORIGIN_FIELD_OPTIONS = {
    'feature-discovery': 'Feature Discovery',
    'grill-me':          'Grill-Me Session',
    'security-audit':    'Security Audit',
    'code-review':       'Code Review',
    'report-issue':      'Development',
    'execute':           'Development',
    'human':             'Stakeholder Request',
}


def resolve_field_name(purpose_key, project_map, defaults=None):
    """Resolve a field purpose key to a concrete org field name.

    Same resolution order as `resolve_label()`: the project's own map from
    `ClaudeProject.md` first, then the default inventory, then the key itself
    so a caller never gets an empty string.
    """
    if defaults is None:
        defaults = FIELD_NAME_DEFAULTS
    return (project_map or {}).get(purpose_key) or defaults.get(purpose_key) or purpose_key


def field_purpose_for_name(field_name, project_map, defaults=None):
    """Reverse `resolve_field_name()`: concrete field name → purpose key, or None.

    Preflight uses this to report an org field that no purpose key maps to,
    which is how a newly added org field gets noticed instead of sitting unused.
    """
    for key in (defaults or FIELD_NAME_DEFAULTS):
        if resolve_field_name(key, project_map, defaults) == field_name:
            return key
    return None


# ── duplicate detection: the PRs that will close an issue ────────────────────
# One definition of "duplicate", used by every site that detects or reconciles
# one. It reads GitHub's own parse of closing references — the same parse that
# auto-closes the issue on merge — rather than matching PR bodies, because a
# regex misses closing keywords, cross-repo refs and UI-linked issues, and two
# call sites with two regexes would disagree about what a duplicate is.

def select_sibling_prs(nodes, number, exclude_branch=None):
    """The open PRs that close issue `number`, oldest first.

    `exclude_branch` drops the caller's own PR, which is otherwise reported as
    a duplicate of itself the moment it is created.
    """
    out = []
    for node in nodes or ():
        refs = closing_issue_numbers(node.get('closingIssuesReferences'))
        if number not in refs:
            continue
        if exclude_branch and node.get('headRefName') == exclude_branch:
            continue
        out.append({
            'number': node['number'],
            'title': node.get('title', ''),
            'url': node.get('url', ''),
            'head_ref': node.get('headRefName', ''),
            'draft': bool(node.get('isDraft')),
            'labels': [l['name'] for l in
                       (node.get('labels') or {}).get('nodes', [])],
        })
    return out


# ── claim reaping: which orphaned claim ref is safe to free ──────────────
# Every in-flight issue and PR is locked with a git ref under `refs/claims/`.
# A normal exit releases it; a crash does not, and the orphan then blocks
# pickup of that item forever with no error anywhere. Reaping is therefore
# necessary — and dangerous, because freeing a ref that still backs a running
# session lets two agents build the same story. So the rule is asymmetric:
# reap only on positive evidence the work has moved on, and when the evidence
# is merely absent, report the ref as suspect and leave it alone.

REAP_THRESHOLD_HOURS = 4

REAP, SUSPECT, SKIP = 'reap', 'suspect', 'skip'


def reap_verdict(kind, age_hours, state, labels, threshold=REAP_THRESHOLD_HOURS,
                 review_labels=(), has_open_pr=False, assigned=True):
    """Decide what to do with one claim ref. Returns (verdict, reason).

    `kind` is 'issue' or 'pr'; `state` is GitHub's own state string (OPEN /
    CLOSED / MERGED) or None when it could not be read.

    An issue claim is reaped when the issue is closed, when nobody is assigned
    to it, or when a PR is already open for it (the post-create release did not
    run). It is suspect when the issue is open, assigned and has no PR: that is
    exactly what a slow but healthy session looks like.

    The assignment is the test because the assignment is what `pick` writes.
    Until 10.0.0 this read a `status-in-progress` label instead, which stopped
    being applied when the state moved to the board -- so every claim looked
    abandoned the moment the label went away, and a healthy in-flight session
    would have had its claim reaped out from under it.

    A PR claim is reaped when the PR is closed or merged, or when it is open
    but carries no active review-state label. A pull request has no board card,
    so its review-state label is the only record of where it is, and that is
    why this half still reads labels.
    """
    if age_hours is None:
        return SUSPECT, 'the age of the claim ref could not be read'
    if age_hours < threshold:
        return SKIP, 'only %dh old (threshold %dh)' % (age_hours, threshold)
    if state is None:
        return SUSPECT, 'could not read the %s' % kind

    names = set(labels or ())
    if kind == 'issue':
        if state.upper() == 'CLOSED':
            return REAP, 'the issue is closed'
        if not assigned:
            return REAP, 'nobody is assigned to the issue'
        if has_open_pr:
            return REAP, 'a PR is already open for the issue'
        return SUSPECT, 'the issue is still assigned with no PR open'

    if state.upper() in ('CLOSED', 'MERGED'):
        return REAP, 'the PR is %s' % state.lower()
    if names & set(review_labels or ()):
        return SUSPECT, 'a review is in progress'
    return REAP, 'the PR is open with no review under way'


def reap_summary(results):
    """Count a reap run by verdict. `results` are (target, verdict, reason)."""
    counts = {REAP: 0, SUSPECT: 0, SKIP: 0}
    for _, verdict, _ in results:
        counts[verdict] = counts.get(verdict, 0) + 1
    return {'reaped': counts[REAP], 'suspect': counts[SUSPECT],
            'skipped': counts[SKIP]}


# Board column purpose key → the column's name on the board. `ClaudeProject.md`
# records the purpose key and the option id; the live board is addressed by
# name, and `wf board-move` accepts either.
#
# `col-backlog` is `Backlog`, which is what every other reference in this plugin
# already calls it: the purpose key itself, `templates/default-labels.md`, the
# `ClaudeProject.md` template, and `commands/report-issue.md`. It read `Todo`
# for a long time, which is the name GitHub gives the column on a new Projects
# v2 board rather than the name this plugin uses for it, so `board-move` failed
# on every board that had been renamed to match its own configuration — and
# failed quietly, because a board is a mirror and a failed move is never fatal.
# `setup` now renames a default `Todo` rather than adopting it.
BOARD_COLUMN_NAMES = {
    'col-backlog':     'Backlog',
    'col-in-progress': 'In Progress',
    'col-in-review':   'In Review',
    'col-blocked':     'Blocked',
    'col-non-code':    'Non-code',
    'col-refinement':  'Needs refinement',
    'col-parked':       'Parked',
    'col-attention':   'Needs attention',
    'col-done':        'Done',
}

# The one column the picker selects from. Everything else on the board is a
# lane an issue is *not* available from, which is why the pool needs no
# exclusion list of its own: `Status` holds one value, so a card in any other
# column is already out.
POOL_COLUMN = 'col-backlog'

BOARD_COLUMN_COLOURS = {
    'Backlog':          'GREEN',
    'Needs refinement': 'BLUE',
    'In Progress':      'YELLOW',
    'In Review':        'ORANGE',
    'Needs attention':  'PURPLE',
    'Blocked':          'RED',
    'Non-code':         'PINK',
    'Parked':           'GRAY',
    'Done':             'GRAY',
}

BOARD_COLUMN_DESCRIPTIONS = {
    'Backlog':          'Available to pick',
    'Needs refinement': 'Specced too thinly to start',
    'In Progress':      'Claimed by an agent',
    'In Review':        'Waiting on a pull request',
    'Needs attention':  'Stopped part-way and needs a person',
    'Blocked':          'Waiting on an open blocked-by edge',
    'Non-code':         'Owned by a person or a browser agent',
    'Parked':           'Deliberately set aside',
    'Done':             'Closed',
}

# The lanes `setup` creates and `board-lane` checks for. Every state an issue
# can be in is one of these, because since 10.0.0 the column *is* the state:
# there is no lifecycle label left to hold a state the board has no lane for.
LANE_COLUMNS = tuple(k for k in BOARD_COLUMN_NAMES if k != 'col-done')


# ── work scope: who can actually do this issue ───────────────────────────────
# Three parties touch a backlog and only one of them writes code. An issue that
# needs a browser console, or a person with a device in their hand, is not work
# a code agent can pick up, and an issue body must belong to exactly one of the
# three — a body that mixes them cannot be finished by anyone.
#
# Two signals record it, and they have different jobs. The `Ownership` field is
# the structured answer: it is what the picker reads, what a board view groups
# by, and what `issue-apply` refuses to create an issue without. The title
# prefix is the human echo -- what somebody scanning a list of issue titles
# sees without opening one. `scope_findings` below is what stops the two
# drifting apart.
#
# There were four signals until 10.0.0: those two plus a `browser-agent` /
# `human-required` scope label and a `status-non-code` lifecycle label. Four
# records of one fact is three too many, and they did drift -- the check that
# reported the drift was itself most of `scope_findings`.

SCOPE_CODE = 'code'
SCOPE_BROWSER = 'browser'
SCOPE_HUMAN = 'human'

# Scope → the title prefix. Fixed strings rather than a pattern: the prefix is
# written by this plugin and read by people, and a loose match would claim any
# title that happened to open with a bracket.
SCOPE_PREFIXES = {SCOPE_BROWSER: '[Browser] ', SCOPE_HUMAN: '[Manual] '}


# Scope → the `Ownership` field option that records it. The field is the
# structured answer to "who has to do this", and the picker reads it first.
# Until 9.0.0 there was no field at all: the scope label and the title prefix
# were the only record, so a query could find non-code work but no *view* could
# group by it, and nothing stopped an issue claiming two owners at once.
OWNERSHIP_FIELD_OPTIONS = {
    SCOPE_CODE:    'Code agent',
    SCOPE_BROWSER: 'Browser agent',
    SCOPE_HUMAN:   'Human',
}

OWNERSHIP_BY_OPTION = {v.lower(): k for k, v in OWNERSHIP_FIELD_OPTIONS.items()}


def ownership_scope(field_value):
    """The scope an `Ownership` option names, or None when it names nothing.

    An unrecognised value is None rather than `code`: an org that renamed its
    options should have its issues fall through to the scope labels, not be
    handed to a code agent because the string did not match.
    """
    if not field_value:
        return None
    return OWNERSHIP_BY_OPTION.get(str(field_value).strip().lower())


def scope_from_title(title):
    """The scope a title prefix claims, or None when it carries no prefix.

    Case-insensitive, because real backlogs carry `[MANUAL]` as often as
    `[Manual]` and shouting is not a scope error. The spelling above is what
    new issues are written with; either is read.
    """
    title = (title or '').lower()
    for scope, prefix in SCOPE_PREFIXES.items():
        if title.startswith(prefix.lower()):
            return scope
    return None


def issue_scope(title, ownership=None):
    """The one party that owns this issue: browser, human, or code.

    The `Ownership` field decides. The title prefix is read only when the field
    has no value, and only so an issue written before the field existed still
    routes somewhere sensible while `issue-audit` catches up; a title that
    disagrees with a set field is a finding rather than a second opinion — see
    `scope_findings`. With neither, the issue is code work, which is the answer
    for the overwhelming majority of a backlog and the one the prefix
    convention is defined against.
    """
    scope = ownership_scope(ownership)
    if scope:
        return scope
    return scope_from_title(title) or SCOPE_CODE


def scope_findings(issues, ownership_map=None):
    """Every place an issue's two ownership signals disagree.

    `issues` are dicts carrying `number` and `title`; `ownership_map` is
    ``{issue_number: Ownership option name}`` from the org's field. Returns a
    list of {'number', 'title', 'kind', 'detail'} with these kinds:

      scope-unowned  — no `Ownership` value. The field is mandatory, so this is
                       an issue nothing can route: the picker will not offer it
                       to a code agent and no view will group it.
      scope-prefix   — the field and the title prefix name different parties,
                       or one is present without the other. The field is right
                       and the title is what gets corrected, but a person
                       scanning the list sees the title, so the two have to
                       agree.
      scope-option   — a value the `Ownership` field holds that names no known
                       party, which happens when an org renames its options.
                       Nothing can act on it.

    This used to police four signals against each other -- the field, the
    title prefix, a scope label and a `status-non-code` lifecycle label -- and
    most of it existed because a fact recorded four times is a fact that
    disagrees with itself. Two of those records are gone; what is left is the
    structured answer and the human-readable echo of it.
    """
    ownership_map = ownership_map or {}
    findings = []
    for issue in issues or ():
        number, title = issue.get('number'), issue.get('title') or ''
        value = ownership_map.get(number)
        prefixed = scope_from_title(title)

        def add(kind, detail):
            findings.append({'number': number, 'title': title,
                             'kind': kind, 'detail': detail})

        if not value:
            add('scope-unowned',
                'has no `Ownership` value, so nothing says who has to do it; '
                'set it to %s'
                % ', '.join(OWNERSHIP_FIELD_OPTIONS[k] for k in
                            (SCOPE_CODE, SCOPE_BROWSER, SCOPE_HUMAN)))
            continue

        owned = ownership_scope(value)
        if not owned:
            add('scope-option',
                "`Ownership` is '%s', which names no party this workflow knows "
                '(it reads %s)'
                % (value, ', '.join(OWNERSHIP_FIELD_OPTIONS[k] for k in
                                    (SCOPE_CODE, SCOPE_BROWSER, SCOPE_HUMAN))))
            continue

        expected = SCOPE_PREFIXES.get(owned)
        if expected and prefixed != owned:
            add('scope-prefix',
                'is owned by %s with no "%s" title prefix, so it reads as '
                'ordinary code work in any list of titles'
                % (OWNERSHIP_FIELD_OPTIONS[owned], expected.strip()))
        elif not expected and prefixed:
            add('scope-prefix',
                'is titled "%s" but owned by %s'
                % (SCOPE_PREFIXES[prefixed].strip(),
                   OWNERSHIP_FIELD_OPTIONS[owned]))
    return findings


# What a spec entry may ask for in `state`, and the column each asks for. Three
# and not nine: these are the states a *writer* can know. In Progress, In
# Review and Done are written by the run that does the work, and Needs
# attention by the run that gives up on it, so a spec naming one of those would
# be describing something that has not happened.
SPEC_STATE_COLUMNS = {
    'backlog':    'col-backlog',
    'refinement': 'col-refinement',
    'parked':     'col-parked',
}

# The lanes `issue-apply` may move a card out of on its own. Everything else is
# a state some other run, or a person, put the card in, and an update that is
# about a field value has no business overruling it: an issue in progress that
# was moved back to Backlog is offered to a second agent, and one a person
# parked or held for refinement is approved by the update that released it.
#
# `Needs refinement` is deliberately not here. It is where this phase puts an
# issue nothing can route, and it is also where a person withholds approval;
# the two are indistinguishable from the outside, so releasing one releases the
# other. A spec says `"state": "backlog"` to release it deliberately.
AUTO_MANAGED_COLUMNS = frozenset({'Backlog', 'Blocked', 'Non-code'})


def spec_state_column(value):
    """The column purpose key a spec's `state` names. Returns (key, err)."""
    if value is None:
        return None, None
    key = str(value).strip().lower()
    if key in SPEC_STATE_COLUMNS:
        return SPEC_STATE_COLUMNS[key], None
    return None, ("'%s' is not a state a spec may ask for (it reads: %s)"
                  % (value, ', '.join(sorted(SPEC_STATE_COLUMNS))))


def board_column_for(scope, open_blockers, requested=None):
    """The board column purpose key an issue in this state belongs in.

    Five inputs in one order, and the order is the whole rule:

      non-code    `scope` is a browser agent or a person, so the card goes in
                  Non-code. This wins over everything below it: the owner is a
                  property of the work, it survives every blocker closing, and
                  no sweep may release it into a pool that cannot do it.
      requested   the spec named a `state`. A person asking for `parked` or
                  `refinement` is a decision, and a decision outranks the
                  inference below it.
      unowned     `scope` is None, so the org's `Ownership` field says nothing
                  this workflow recognises. Nothing can route the issue -- the
                  picker will not offer it to a code agent and no view groups
                  it -- so it goes to Needs refinement rather than into a pool
                  it would sit in unpickable. Until 10.1.2 it landed in
                  Backlog, on a title-prefix fallback, which is how a card can
                  look available and never be picked.
      blocked     at least one native edge points at an open issue.
      pickable    none of the above, so Backlog, which is what available means.

    `col-backlog` is an answer rather than an absence -- there is no state an
    issue can be in that this does not name a column for, which is what lets
    the board be the whole record of state.

    This used to have a twin, `lifecycle_for`, returning the label that
    mirrored the column. The label is gone; `Status` holds one value and a card
    sits in one column, so there is nothing for a second record to disagree
    with.
    """
    if scope in (SCOPE_BROWSER, SCOPE_HUMAN):
        return 'col-non-code'
    if requested:
        return requested
    if scope is None:
        return 'col-refinement'
    return 'col-blocked' if open_blockers else 'col-backlog'


def may_place_card(current_column, requested=None):
    """Whether `issue-apply` may write this card's lane. (allowed, why_not).

    A card with no lane at all -- no card on the board, or a card sitting in
    the board's `No Status` bucket -- is always placed: an issue in no lane is
    in no state, and it is invisible to every command that reads one.
    """
    if requested:
        return True, None
    current = (current_column or '').strip()
    if not current:
        return True, None
    if current in AUTO_MANAGED_COLUMNS:
        return True, None
    return False, current


# ── issue hierarchy: epic → feature → user story ─────────────────────────────
# The native types are a hierarchy and not a flat vocabulary, so a Feature
# belongs to an Epic and a User Story belongs to a Feature. Recorded here, and
# enforced when an issue is written, because the alternative is where every
# backlog ends up: a scattering of stories that each made sense on the day and
# no epic that shows what they add up to. GitHub renders the tree and reports
# progress against it, and neither can show anything if nothing is attached.
#
# `Bug` and `Chore` are absent on purpose. Both arrive unplanned, both are
# frequently self-contained, and requiring an epic for a typo fix would mean
# inventing one. A parent on either is allowed and never required.
HIERARCHY_PARENT_TYPE = {
    'Feature':    'Epic',
    'User Story': 'Feature',
}

# A feature is expected under an epic, not required to be. An epic groups
# several features toward one outcome; work that is a single feature stands on
# its own, because an epic invented to hold it would only restate it. A feature
# that has a parent still needs an `Epic` one.
HIERARCHY_OPTIONAL_PARENT = frozenset({'Feature'})


def hierarchy_error(type_name, parent_type, type_map=None, parent_label=None):
    """Why this type may not sit under that parent, or None when it may.

    `type_map` is the org's enabled native types. A rule whose parent type the
    org has not enabled is not enforced: an org with no `Epic` cannot put a
    Feature under one, and failing every create until somebody enables a type
    in the org settings would be a workflow this plugin broke rather than one
    it protects.
    """
    required = HIERARCHY_PARENT_TYPE.get(type_name)
    if not required:
        return None
    if type_map is not None and required not in type_map:
        return None
    if not parent_type:
        if type_name in HIERARCHY_OPTIONAL_PARENT:
            return None
        return ("a '%s' needs a '%s' parent, and this one has none -- give it "
                '`parent` (an existing %s issue number, or the spec key of one '
                'this spec creates)' % (type_name, required, required))
    if parent_type != required:
        return ("a '%s' belongs under a '%s', but %s is a '%s'"
                % (type_name, required,
                   parent_label or 'its parent', parent_type))
    return None


def spec_hierarchy_errors(plans, issue_types=None, issue_parents=None,
                          type_map=None):
    """Every hierarchy rule a spec breaks, as plain strings.

    A parent is named three ways and all three resolve here: the spec key of an
    entry this spec creates, the number of an issue that already exists, and --
    for an update that says nothing about its parent -- the parent the issue
    already has. The third is why an update is checked at all: an entry that
    changes a Chore into a User Story has to acquire a Feature parent, and the
    only place that is knowable is against the live issue.

    An entry whose type this spec does not settle is judged by the type the
    issue already carries, but only when the entry moves it: an update that
    names a `parent` is changing the tree, and re-parenting a live User Story
    straight onto an Epic got through live precisely because the entry named no
    `kind`. An update that sets a field value and says nothing about type or
    parent touches nothing structural and is not refused over the tree it
    already sits in; `issue-audit` reports that as a `hierarchy` gap instead.
    """
    issue_types = issue_types or {}
    issue_parents = issue_parents or {}
    # Same index `spec_levels` builds, so a parent resolves to the same entry
    # here as it does when the levels are ordered: spec key, number, or the
    # number as a string.
    by_ref = {}
    for plan in plans:
        for ref in _entry_refs(plan['entry']):
            by_ref[ref] = plan

    def as_number(ref):
        if isinstance(ref, bool):
            return None
        if isinstance(ref, int):
            return ref
        if isinstance(ref, str) and ref.isdigit():
            return int(ref)
        return None

    errors = []
    for plan in plans:
        entry = plan['entry']
        ref = entry.get('parent')
        type_name = plan.get('type')
        if type_name is None and ref is not None:
            own = as_number(entry.get('number'))
            if own is not None:
                type_name = issue_types.get(own)
        if type_name not in HIERARCHY_PARENT_TYPE:
            continue

        parent_type, parent_label = None, None
        if ref is None:
            # An update that says nothing about its parent keeps the one it
            # has, so that is the parent this rule is about.
            number = as_number(entry.get('number'))
            if number is not None:
                live_number, parent_type = issue_parents.get(number,
                                                             (None, None))
                parent_label = '#%s' % live_number if live_number else None
        else:
            number = as_number(ref)
            parent_plan = by_ref.get(ref)
            if parent_plan is not None:
                parent_type = parent_plan.get('type')
                parent_label = entry_label(parent_plan['entry'])
            if parent_type is None and number is not None:
                # Either the parent is an issue outside this spec, or it is an
                # entry the spec updates without restating its type -- both
                # answer to the type the issue already carries.
                parent_type = issue_types.get(number)
                parent_label = '#%d' % number
            if parent_plan is None and number is None:
                # `spec_levels` treats an unknown key as "outside this spec"
                # and there is no issue to read a type from, so this rule has
                # nothing to check.
                continue

        err = hierarchy_error(type_name, parent_type, type_map, parent_label)
        if err:
            errors.append('%s: %s' % (entry_label(entry), err))
    return errors


def ownership_conflict(title, ownership):
    """The one-issue-one-party error for a spec entry, or None.

    An issue belongs to exactly one of the three parties, and it says so twice:
    the `Ownership` field, which every command reads, and the title prefix,
    which is what a person scanning a list of titles sees. A spec whose two
    disagree is refused rather than written, because whichever of them is wrong
    the issue is about to mislead somebody, and the writer is the one place
    where both are in hand at once.
    """
    owned = ownership_scope(ownership)
    if owned is None:
        return None
    # No prefix is the code agent's prefix. `SCOPE_PREFIXES` deliberately has no
    # row for it -- an agent-written issue is the ordinary case and marking it
    # would put a tag on nearly every title -- so an unprefixed title agrees
    # with `Code agent` and disagrees with the other two.
    prefixed = scope_from_title(title) or SCOPE_CODE
    if prefixed == owned:
        return None
    expected = SCOPE_PREFIXES.get(owned)
    if expected:
        return ('is owned by %s, so its title has to start with "%s"'
                % (OWNERSHIP_FIELD_OPTIONS[owned], expected.strip()))
    return ('is titled "%s" but owned by %s -- one issue, one party'
            % (SCOPE_PREFIXES[prefixed].strip(), OWNERSHIP_FIELD_OPTIONS[owned]))


def edge_diff(current, wanted):
    """(to_add, to_remove) for an issue whose spec entry restated `blocked_by`.

    A spec entry that carries the key describes the *whole* set of edges, so an
    edge the issue holds and the entry leaves out is one the entry asks to
    remove. That is the deliberate unblock: `wf unblock` releases an issue when
    its blockers close, and this is how one is released because the dependency
    turned out not to exist. An entry with no `blocked_by` key at all says
    nothing about edges and neither does this -- the caller does not call it.
    """
    have = {int(n) for n in current or ()}
    want = {int(n) for n in wanted or ()}
    return sorted(want - have), sorted(have - want)


# ── issue spec: validation and value shaping ─────────────────────────────────
# `wf issue-apply` reads a spec file and applies it. Everything in this section
# is pure: it decides what the mutations should say, and never sends one.
#
# A spec is {"issues": [entry, ...]}. An entry carrying `number` is an update;
# one without is a create. `key` is a spec-local name so entries can reference
# each other (`parent`, `blocked_by`) before any of them has a real number.

# What an audit writes where it could not infer a value. It exists so silence
# cannot pass: the mandatory-field check treats it as missing, which refuses
# the spec until a human or an agent fills it in.
SPEC_PLACEHOLDER = 'TODO'


def _is_supplied(value):
    """Whether a spec supplied a real value, as opposed to a blank or a placeholder."""
    if value is None:
        return False
    if isinstance(value, str):
        stripped = value.strip()
        return bool(stripped) and stripped != SPEC_PLACEHOLDER
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_is_supplied(v) for v in value)
    return True


def entry_label(entry):
    """How an entry is named in an error message: its number, else its key, else its title."""
    if entry.get('number'):
        return '#%s' % entry['number']
    return entry.get('key') or entry.get('title') or '<unnamed entry>'


def resolve_entry_type(entry, type_map=None):
    """The native issue type an entry asks for, or None. (type_name, err).

    An explicit `type` on the entry always wins. Otherwise the kind decides,
    against the types the org has enabled — see `native_type_for`.
    """
    if entry.get('type'):
        return entry['type'], None
    kind = entry.get('kind')
    if not kind:
        return None, None
    key = str(kind).lower()
    if key not in NATIVE_TYPE_MAP:
        return None, "unknown kind '%s' (expected one of: %s)" % (
            kind, ', '.join(sorted(NATIVE_TYPE_MAP)))
    return native_type_for(key, type_map), None


def default_classification(entry):
    """The Classification a kind implies, when the entry did not name one."""
    mapped = NATIVE_TYPE_MAP.get(str(entry.get('kind') or '').lower())
    return [mapped['classification']] if mapped else None


def field_value_input(field_meta, value):
    """Shape one `IssueFieldCreateOrUpdateInput`. Returns (input, err).

    The value key depends on the field's data type, so the type has to be
    carried alongside the id rather than guessed from the value's shape — a
    single-select and a text field both take a string.
    """
    data_type = field_meta.get('data_type')
    fid = field_meta.get('id')
    options = field_meta.get('options') or {}

    if data_type in ('single-select', 'multi-select'):
        names = value if isinstance(value, (list, tuple)) else [value]
        ids = []
        for name in names:
            if name not in options:
                return None, "'%s' is not an option (valid: %s)" % (
                    name, ', '.join(sorted(options)) or 'none')
            ids.append(options[name])
        if data_type == 'single-select':
            if len(ids) != 1:
                return None, 'single-select takes exactly one value, got %d' % len(ids)
            return {'fieldId': fid, 'singleSelectOptionId': ids[0]}, None
        return {'fieldId': fid, 'multiSelectOptionIds': ids}, None

    if data_type == 'date':
        return {'fieldId': fid, 'dateValue': str(value)}, None
    if data_type == 'text':
        return {'fieldId': fid, 'textValue': str(value)}, None
    if data_type == 'number':
        try:
            return {'fieldId': fid, 'numberValue': float(value)}, None
        except (TypeError, ValueError):
            return None, "'%s' is not a number" % value
    return None, "unsupported field data type '%s'" % data_type


def validate_spec(entries, field_map, type_map, project_fields=None,
                  mandatory_keys=None):
    """Check a spec against the org's real capabilities before anything is written.

    Returns (errors, skipped_fields, plans). `errors` is a list of plain
    strings, each naming the entry and the problem. `skipped_fields` is the set
    of field names the spec asked for that this org does not define — reported
    once for the run, not once per issue. `plans` carries the resolved per-entry
    work, so the caller does not resolve any of it a second time.

    Three fields are required and the rest are not, and the line between them
    is whether a decision reads the value. `Priority`, `Effort` and `Ownership`
    are the picker's whole input, so an org that does not define one, or a spec
    that leaves one empty, is refused -- that is the blank-metadata failure this
    command exists to stop. `Classification` and `Origin` are worth having and
    not worth refusing an issue over, so a gap in one lands on the plan as
    `unset_optional` and the writer comments on the issue instead. Every other
    field the org defines is skipped when the spec says nothing about it.
    """
    project_fields = project_fields or {}
    mandatory_keys = mandatory_keys or MANDATORY_FIELD_KEYS
    errors, skipped, plans = [], set(), []

    seen_keys, seen_numbers = set(), set()

    for entry in entries:
        name = entry_label(entry)
        plan = {'entry': entry, 'type': None, 'fields': {}, 'errors': [],
                'live_required': []}

        if not entry.get('number') and not entry.get('title'):
            errors.append('%s: an entry needs a title to create, or a number to update'
                          % name)

        key = entry.get('key')
        if key:
            if key in seen_keys:
                errors.append("%s: duplicate key '%s' in this spec" % (name, key))
            seen_keys.add(key)
        number = entry.get('number')
        if number:
            if number in seen_numbers:
                errors.append('%s: issue appears more than once in this spec' % name)
            seen_numbers.add(number)

        # The lane the entry asks for, when it asks for one at all.
        state_column, err = spec_state_column(entry.get('state'))
        if err:
            errors.append('%s: %s' % (name, err))
        plan['state'] = state_column

        # Native type.
        type_name, err = resolve_entry_type(entry, type_map)
        if err:
            errors.append('%s: %s' % (name, err))
        elif type_name:
            if type_map and type_name not in type_map:
                errors.append("%s: native type '%s' is not enabled on this org "
                              '(enabled: %s)' % (name, type_name,
                                                 ', '.join(sorted(type_map)) or 'none'))
            else:
                plan['type'] = type_name

        # Field values, including the ones the entry did not name but must.
        wanted = dict(entry.get('fields') or {})
        if 'field-type' not in wanted:
            implied = default_classification(entry)
            if implied:
                wanted['field-type'] = implied

        for purpose in mandatory_keys:
            concrete = resolve_field_name(purpose, project_fields)
            if concrete not in field_map:
                # Refused, not skipped. Priority, Effort and Ownership are what
                # the picker reads, so filing an issue the org cannot record one
                # on creates work nothing can rank, size or route -- and does it
                # silently, which is how a repository ran for weeks with no
                # `Ownership` field and a clean audit. The fix is a one-off org
                # change, and `config-audit` names it before anybody gets here.
                errors.append("%s: the org defines no '%s' field (%s), and "
                              'every issue must carry one; create it and re-run'
                              % (name, concrete, purpose))
                continue
            if purpose not in wanted and entry.get('number'):
                # An update names what it changes. A value it leaves out is
                # judged against the issue once that has been read
                # (`spec_live_errors`); a placeholder it writes is not left out.
                plan['live_required'].append(concrete)
                continue
            if not _is_supplied(wanted.get(purpose)):
                errors.append("%s: missing a value for '%s' (%s), which this org "
                              'defines and every issue must carry'
                              % (name, concrete, purpose))

        # The optional two. A gap here is recorded on the plan rather than
        # raised, and the writer turns it into a comment on the issue.
        plan['unset_optional'] = sorted(
            resolve_field_name(purpose, project_fields)
            for purpose in OPTIONAL_FIELD_KEYS
            if resolve_field_name(purpose, project_fields) in field_map
            and not _is_supplied(wanted.get(purpose)))

        for purpose, value in wanted.items():
            concrete = resolve_field_name(purpose, project_fields)
            meta = field_map.get(concrete)
            if meta is None:
                skipped.add(concrete)
                continue
            if not _is_supplied(value):
                continue  # already reported above when it was mandatory
            shaped, err = field_value_input(meta, value)
            if err:
                errors.append("%s: %s — %s" % (name, concrete, err))
            else:
                plan['fields'][concrete] = {'input': shaped, 'value': value,
                                            'purpose': purpose}

        # One issue, one party. Checked here rather than at the write, because
        # the title and the `Ownership` value are both in hand at this point
        # and neither is recoverable from the other afterwards.
        owner_name = resolve_field_name('field-ownership', project_fields)
        owner_plan = plan['fields'].get(owner_name)
        if entry.get('title') and owner_plan:
            conflict = ownership_conflict(entry['title'], owner_plan['value'])
            if conflict:
                errors.append('%s: %s' % (name, conflict))

        plans.append(plan)

    return errors, skipped, plans


def spec_live_errors(plans, live, project_fields=None):
    """What an update breaks once the issue it updates is taken into account.

    `live` is {number: {'title': str, 'fields': {field name: value}}}, read in
    the same lookup as the referenced issues' types. Two rules need it, because
    an update names only what it changes:

    - A required field the entry leaves out has to be on the issue already. An
      update is refused for leaving the issue without a value, not for failing
      to restate one it carries.
    - One issue, one party, judged on the title and the owner the issue will
      have afterwards. An update that sets `Human` on an unprefixed issue, or
      retitles a code-agent issue `[Manual] ...`, is the same contradiction as a
      create that does. An update that touches neither is not judged: refusing
      a priority change over a conflict it did not make blocks the fix.
    """
    project_fields = project_fields or {}
    owner_name = resolve_field_name('field-ownership', project_fields)
    errors = []
    for plan in plans:
        entry = plan['entry']
        try:
            number = int(entry.get('number'))
        except (TypeError, ValueError):
            continue
        issue = live.get(number)
        if issue is None:
            continue
        have = issue.get('fields') or {}
        name = entry_label(entry)
        for field in plan.get('live_required') or ():
            if not _is_supplied(have.get(field)):
                errors.append("%s: missing a value for '%s', which the issue does "
                              'not carry either and every issue must' % (name, field))

        sets_owner = owner_name in plan['fields']
        if entry.get('title') and sets_owner:
            continue  # both in the spec, and `validate_spec` judged them
        if not entry.get('title') and not sets_owner:
            continue
        title = entry.get('title') or issue.get('title') or ''
        owner = (plan['fields'][owner_name]['value'] if sets_owner
                 else have.get(owner_name))
        if title and _is_supplied(owner):
            conflict = ownership_conflict(title, owner)
            if conflict:
                errors.append('%s: %s' % (name, conflict))
    return errors


# How many issues ride in one aliased multi-mutation. GraphQL caps the nodes a
# single request may address, and a whole backlog in one document would trip it,
# so a large spec is split into several requests rather than failing at the
# limit. Twenty is comfortably inside GitHub's cap while still turning a
# thirteen-issue epic tree into three requests.
BATCH_MAX_NODES = 20


def batch_entries(items, size=BATCH_MAX_NODES):
    """Split a level into requests of at most `size` entries."""
    size = size if size and size > 0 else len(items) or 1
    return [list(items[i:i + size]) for i in range(0, len(items), size)]


def _entry_refs(entry):
    """Every name this entry answers to: its spec key, and its number both ways."""
    refs = []
    if entry.get('key') is not None:
        refs.append(entry['key'])
    if entry.get('number') is not None:
        refs.extend([entry['number'], str(entry['number'])])
    return refs


def spec_levels(entries):
    """Group entries into hierarchy levels, parents before children.

    Aliased multi-mutations cannot reference each other's output, so a child's
    `parentIssueId` only exists once its parent's batch has come back. Level 0
    is everything whose parent is absent or lives outside this spec; each later
    level is the entries whose parent landed in the level before it.

    Returns (levels, unplaceable). `unplaceable` is the entries in a parent
    cycle — a different fault from `spec_cycles`, which looks at `blocked_by`,
    and one that no amount of retrying would resolve.

    This is a level assignment rather than the flat build order
    `plan_bulk_order()` produces, and it is keyed on spec-local `key`s that
    have no issue number yet, so it is a separate walk rather than a second
    copy of one.
    """
    by_ref = {}
    for entry in entries:
        for ref in _entry_refs(entry):
            by_ref[ref] = entry

    levels, placed, remaining = [], set(), list(entries)
    while remaining:
        layer = [e for e in remaining
                 if e.get('parent') is None
                 or e.get('parent') not in by_ref
                 or id(by_ref[e['parent']]) in placed]
        if not layer:
            break
        placed.update(id(e) for e in layer)
        levels.append(layer)
        remaining = [e for e in remaining if id(e) not in placed]
    return levels, remaining


def spec_cycles(entries):
    """Dependency cycles within a spec, as lists of entry references.

    Applied before any mutation runs: a cycle cannot be written correctly, and
    finding it after half the tree exists is much worse than finding it first.
    """
    graph, refs = {}, set()
    for entry in entries:
        ref = entry.get('key') or entry.get('number')
        if ref is None:
            continue
        refs.add(ref)
        graph[ref] = [d for d in (entry.get('blocked_by') or [])]

    cycles, state = [], {}

    def walk(node, stack):
        state[node] = 'open'
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue  # points outside the spec; not this command's problem
            if state.get(nxt) == 'open':
                cycles.append(stack[stack.index(nxt):] + [nxt])
            elif state.get(nxt) is None:
                walk(nxt, stack)
        stack.pop()
        state[node] = 'done'

    for ref in graph:
        if state.get(ref) is None:
            walk(ref, [])
    return cycles


# ── issue audit ──────────────────────────────────────────────────────────────
# Nothing detected that the metadata was never applied, which is why the gap
# went unnoticed for months: 82 issues in one repo, 7 typed, no field values,
# no dependency edges, and no error anywhere. Everything here is pure — the
# audit reads, decides, and proposes; it never writes.

# The kind an issue claims to be in its title. Titles are written by hand, so
# this is evidence rather than proof — it is used to *contradict* a native type,
# never to set one unattended.
TITLE_PREFIX_KINDS = {
    'STORY': 'story', 'BUG': 'bug', 'SECURITY': 'security',
    'DEBT': 'tech debt', 'TECH DEBT': 'tech debt', 'TECH-DEBT': 'tech debt',
    'ARCH': 'architecture', 'ARCHITECTURE': 'architecture',
    'EPIC': 'epic', 'FEATURE': 'feature', 'SPIKE': 'spike', 'CHORE': 'chore',
}

TYPE_LABEL_KINDS = {
    'type-story': 'story', 'type-bug': 'bug', 'type-security': 'security',
    'type-debt': 'tech debt', 'type-arch': 'architecture',
}

_TITLE_PREFIX_RE = re.compile(r'^\s*\[([^\]]{1,20})\]')


def declared_kind(title, labels, project_map=None):
    """The kind an issue says it is. Returns (kind, source) or (None, None).

    A `type-*` label is the stronger claim, so it wins over the title prefix.
    """
    project_map = project_map or {}
    present = set(labels or ())
    for key, kind in TYPE_LABEL_KINDS.items():
        if resolve_label(key, project_map) in present:
            return kind, 'label'
    match = _TITLE_PREFIX_RE.match(title or '')
    if match:
        kind = TITLE_PREFIX_KINDS.get(match.group(1).strip().upper())
        if kind:
            return kind, 'title'
    return None, None


# ── writing an issue: what is no longer written ────────────────────────────
# The native issue type is the classification. Writing it a second and third
# time as a `type-*` label and a `[BUG]` title prefix buys nothing and costs
# plenty: GitHub renders the type badge in every list, the prefix eats title
# width in all of them, and a label that drifts from the type gives the picker
# two answers to one question. These two functions are what the create path
# uses, and they take the redundancy out of a caller's spec rather than
# trusting every call site to remember -- so a spec that still names
# `type-bug`, or a title that still starts `[BUG]`, produces a clean issue
# anyway.
#
# This applies on every org, including one with no native types: a classifier
# the tooling never reads is not a classifier, it is just clutter that outlives
# whoever wrote it.

def strip_type_labels(labels, project_map=None):
    """The labels minus any `type-*` one. Returns (kept, dropped).

    Order is preserved, and a label is matched through the project map like
    everywhere else, so a project that renamed `type-bug` to `kind/bug` has it
    dropped too.
    """
    project_map = project_map or {}
    type_names = {resolve_label(key, project_map) for key in TYPE_LABEL_KINDS}
    kept, dropped = [], []
    for name in labels or []:
        # A spec may name either the purpose key or the literal label.
        literal = resolve_label(name, project_map) if name in TYPE_LABEL_KINDS else name
        (dropped if literal in type_names else kept).append(name)
    return kept, dropped


def same_text(a, b):
    """Whether two issue titles or bodies say the same thing.

    A read-back can carry `\\r\\n` where the spec has `\\n`, and trailing
    whitespace is not a difference anyone wrote, so neither makes an update
    rewrite a body that already matches.
    """
    def norm(text):
        return (text or '').replace('\r\n', '\n').strip()
    return norm(a) == norm(b)


def strip_title_prefix(title):
    """The title minus a leading `[KIND]` the native type already states.

    Only a prefix this workflow recognises as a kind is removed. A title that
    opens with a bracket meaning something else -- `[v2]`, `[iOS]` -- is left
    exactly as written, because guessing there would silently edit somebody's
    words.

    `[Manual]` and `[Browser]` are deliberately not kinds and must never
    become ones. They mark *who* has to finish an issue -- a person, or a
    browser agent driving a console someone signed into -- which no native
    field records, so the title is the only place either can live. Adding
    either to TITLE_PREFIX_KINDS would strip it off every issue that needs it.
    """
    match = _TITLE_PREFIX_RE.match(title or '')
    if not match:
        return title
    if match.group(1).strip().upper() not in TITLE_PREFIX_KINDS:
        return title
    return (title or '')[match.end():].strip()


def audit_issue(issue, field_map, type_capable=True, project_map=None,
                project_fields=None, open_numbers=None, type_map=None,
                parents=False):
    """Every gap on one issue, plus the spec entry that would close them.

    `issue` is a read-back node. Returns a dict carrying `gaps` (each with a
    `kind` and a human-readable `detail`) and `proposed`, an `issue-apply` spec
    entry. Values the audit cannot infer are `SPEC_PLACEHOLDER`, so
    `validate_spec()` refuses the spec until a person fills them in — silence
    must not pass for a value.

    Dependency edges are not audited, because there is nothing to audit them
    against: the native `blockedBy` edge is the only record of a dependency, so
    it cannot disagree with anything. What is audited in its place is
    **ownership** — whether the `Ownership` field and the title prefix agree
    about which of the three parties owns the issue — and **hierarchy**, whether
    a Feature sits under an Epic and a User Story under a Feature.

    `parents` is off by default, and that is a statement about where parents
    come from rather than about how well the parsing works. A story created
    through `feature-discovery` carries its epic in the spec that creates it,
    so reading the sentence back out of the body afterwards re-derives
    something the pipeline already knew. The prose is the only source for a
    backlog written before any of this existed, or for an issue somebody typed
    into the GitHub UI, so the capability stays — it just has to be asked for,
    which keeps a routine audit from reporting a parent gap on every issue
    whose body politely repeats its epic.
    """
    project_map = project_map or {}
    project_fields = project_fields or {}
    gaps = []

    number = issue.get('number')
    title = issue.get('title') or ''
    labels = [n['name'] for n in (issue.get('labels') or {}).get('nodes') or []]
    native = (issue.get('issueType') or {}).get('name')
    kind, source = declared_kind(title, labels, project_map)

    if type_capable and not native:
        gaps.append({'kind': 'missing-type',
                     'detail': 'no native issue type'})
    elif type_capable and kind:
        expected = native_type_for(kind, type_map)
        if native != expected:
            gaps.append({'kind': 'type-contradiction',
                         'detail': "native type is '%s' but the %s says '%s', "
                                   "which is '%s'" % (native, source, kind, expected)})

    # The field values the issue already carries, by field name.
    have = {}
    for node in (issue.get('issueFieldValues') or {}).get('nodes') or []:
        name = (node.get('field') or {}).get('name')
        if not name:
            continue
        if 'options' in node:
            have[name] = sorted(o['name'] for o in node.get('options') or [])
        elif 'name' in node:
            have[name] = node.get('name')
        else:
            have[name] = node.get('value')

    # A `[DEBT]` issue typed `Feature` is not a native-type contradiction —
    # GitHub's five types cannot express tech debt, which is exactly why
    # `Classification` exists. So the contradiction to look for there is in the
    # field, not the type.
    if kind:
        class_name = resolve_field_name('field-type', project_fields)
        current = have.get(class_name)
        if _is_supplied(current):
            values = current if isinstance(current, list) else [current]
            conflicts = classification_conflicts(kind, values)
            if conflicts:
                gaps.append({'kind': 'classification-contradiction',
                             'detail': "%s is %s, which cannot be true of a '%s'"
                                       ' (the %s says it is one)'
                                       % (class_name, ', '.join(repr(c) for c in conflicts),
                                          kind, source)})

    # The three required fields plus the two the workflow fills in when it can.
    # The other fields an org defines — a start date, a target date, a free-text
    # parent — are situational, and the backfill has never proposed a value for
    # one. Reporting them anyway made every issue in a fully classified backlog
    # come back as "missing metadata": 275 findings across 69 issues on one real
    # repo, every one of them a field nobody was ever going to fill. An audit
    # that cannot come back clean cannot be used as a check, which is what it is
    # for.
    proposed_fields = {}
    for purpose in MANDATORY_FIELD_KEYS + OPTIONAL_FIELD_KEYS:
        concrete = resolve_field_name(purpose, project_fields)
        if concrete not in field_map:
            continue
        if _is_supplied(have.get(concrete)):
            # Carry the value the issue already holds into the proposal.
            # `issue-apply` refuses a spec that leaves a mandatory field blank,
            # and it does not first check whether the issue is already carrying
            # one — so an entry proposed for some other reason entirely, a
            # parent or an edge, was rejected for "missing" a value that was
            # sitting on the issue. Repeating it makes the write a no-op and
            # the spec round-trip.
            proposed_fields[purpose] = have[concrete]
            continue
        gaps.append({
            'kind': 'missing-field' if purpose in MANDATORY_FIELD_KEYS
            else 'missing-optional-field',
            'detail': "no value for '%s'" % concrete})
        if purpose == 'field-type' and kind:
            proposed_fields[purpose] = default_classification({'kind': kind})
        elif purpose == 'field-ownership':
            # From the title prefix when there is one, and a placeholder
            # otherwise. The prefix is written by this workflow and means
            # exactly one thing, so reading it back is not a guess. The absence
            # of one is not evidence of anything: until 10.1.2 a title with no
            # prefix was proposed as `Code agent`, which is the wrong answer in
            # the one direction that matters -- an issue needing a person, read
            # as code work, handed to an agent that cannot finish it.
            prefixed = scope_from_title(title)
            proposed_fields[purpose] = (OWNERSHIP_FIELD_OPTIONS[prefixed]
                                        if prefixed else SPEC_PLACEHOLDER)
        else:
            # `Priority` included, and it used to be inferred from a
            # `priority-*` label. A label decides nothing since 10.0.0, and
            # reading one here would have let a label somebody set months ago
            # write the field the picker orders on.
            proposed_fields[purpose] = SPEC_PLACEHOLDER

    # Who owns this issue: the `Ownership` field, and the title prefix that is
    # supposed to echo it. A backfill proposed above counts as the value, so an
    # issue this run is about to own is not also reported as unowned.
    #
    # Only when the org defines the field. Reporting "nobody owns this" against
    # an org that has nowhere to record an owner names the wrong thing: the
    # field is missing, not the value, and `config-audit`'s `field-absent` is
    # the check that says so, once for the org rather than once per issue.
    owner_field = resolve_field_name('field-ownership', project_fields)
    if owner_field in field_map:
        owner = have.get(owner_field)
        if not _is_supplied(owner):
            owner = proposed_fields.get('field-ownership')
        # A placeholder is the audit saying it does not know. The
        # `missing-field` gap above already says Ownership has no value, so an
        # unowned issue is not reported a second time as `scope-unowned`; what
        # is left to check is whether a value that exists agrees with the title.
        if _is_supplied(owner):
            for finding in scope_findings([{'number': number, 'title': title}],
                                          {number: owner}):
                gaps.append({'kind': finding['kind'],
                             'detail': finding['detail']})

    # The parent the body claims and the hierarchy does not have. An issue
    # whose first line says "Part of the X epic (#N)" and which GitHub shows
    # as a free-standing issue is the gap this closes: the epic renders with
    # no children, and nothing anywhere reports that they disagree.
    #
    # Opt-in, because on a backlog whose issues are created from specs the
    # parent is already in the spec, and re-reading it out of the body is a
    # backfill for the ones that predate that. See the docstring.
    #
    # An issue that already has *a* parent is left alone, even when the body
    # names a different one. A deeper parent is usually the more specific
    # truth — four slices parented to the architecture issue that split them,
    # whose bodies all still name the epic two levels up — and reparenting
    # them to the epic would flatten a hierarchy somebody built on purpose.
    proposed_parent = None
    claimed_parent = parse_parent(issue.get('body')) if parents else None
    current_parent = (issue.get('parent') or {}).get('number')
    if claimed_parent and claimed_parent != number and not current_parent:
        if open_numbers is not None and claimed_parent not in open_numbers:
            gaps.append({'kind': 'parent-closed',
                         'detail': 'the body says this is part of #%s, which is '
                                   'not open' % claimed_parent})
        else:
            gaps.append({'kind': 'missing-parent',
                         'detail': 'the body says this is part of #%s and it has '
                                   'no parent' % claimed_parent})
            proposed_parent = claimed_parent
    elif claimed_parent and current_parent and claimed_parent != current_parent:
        gaps.append({'kind': 'parent-differs',
                     'detail': 'the body says this is part of #%s but its parent '
                               'is #%s; not changed automatically'
                               % (claimed_parent, current_parent)})

    # Where the issue sits in the epic → feature → user story tree. Reported
    # and never proposed: which epic a feature belongs to is a judgement about
    # the work, and an audit that guessed would attach a story to whichever
    # epic happened to be nearest.
    if native and type_map:
        parent_type = ((issue.get('parent') or {}).get('issueType') or {}).get('name')
        problem = hierarchy_error(
            native, parent_type, type_map,
            parent_label='#%s' % current_parent if current_parent else None)
        if problem:
            gaps.append({'kind': 'hierarchy', 'detail': problem})

    proposed = {'number': number, 'title': title}
    if kind:
        proposed['kind'] = kind
    if proposed_fields:
        proposed['fields'] = proposed_fields
    if proposed_parent:
        proposed['parent'] = proposed_parent
    return {'number': number, 'title': title, 'gaps': gaps, 'proposed': proposed}


def audit_summary(audited):
    """Count the gaps by kind, so a run reports a shape rather than a wall."""
    counts = {}
    for entry in audited:
        for gap in entry['gaps']:
            counts[gap['kind']] = counts.get(gap['kind'], 0) + 1
    return {'issues_scanned': len(audited),
            'issues_with_gaps': sum(1 for e in audited if e['gaps']),
            'gaps': counts}


# ── preflight: configuration and label drift ─────────────────────────────────
# Everything a project can get wrong between `ClaudeProject.md`, the labels the
# repo actually carries, and the org's own field pinning. It is all pure: this
# section decides what is wrong and what the fix is, and never looks anything up.
#
# The severity split is deliberate, and comes from one question — does the
# workflow produce a *wrong* result or a *degraded* one? A missing section, or a
# label an agent is told to apply that does not exist, produce wrong behaviour,
# so they fail. An org field nobody mapped, or a board snapshot that has gone
# stale, degrade gracefully, so they warn.

CRITICAL, WARNING = 'critical', 'warning'

# Every section of `ClaudeProject.md` the plugin reads. A project missing one
# does not get a smaller feature set; it gets the default silently, which is how
# an entire classification scheme went unapplied without an error.
REQUIRED_CONFIG_SECTIONS = (
    'Identity',
    'Package Manager',
    'Quality Gate',
    'Branch Convention',
    'Label Map',
    'Issue Types & Fields',
)

_SECTION_FIXES = {
    'Issue Types & Fields': (
        "run `/github-workflow:setup` to write it from the org's live issue "
        'types and fields, or copy the section from '
        '`github-workflow/templates/ClaudeProject.md`'),
}
_SECTION_FIX_DEFAULT = ('copy the section from '
                        '`github-workflow/templates/ClaudeProject.md` and fill '
                        'it in for this project')


def finding(level, check, detail, fix, where=None):
    """One preflight result. `where` is the file a person would open to fix it."""
    out = {'level': level, 'check': check, 'detail': detail, 'fix': fix}
    if where:
        out['where'] = where
    return out


def _names(values):
    """`a`, `b` and `c` — because a finding is read by a person, not parsed."""
    names = ['`%s`' % v for v in values]
    if len(names) < 2:
        return names[0] if names else ''
    return '%s and %s' % (', '.join(names[:-1]), names[-1])


def _normalise_heading(text):
    return re.sub(r'\s*\(.*\)\s*$', '', (text or '').strip()).strip().lower()


def config_section_findings(headings, path='ClaudeProject.md',
                            required=REQUIRED_CONFIG_SECTIONS):
    """Sections the plugin reads that `ClaudeProject.md` does not carry.

    Named one at a time rather than counted, because "your config is
    incomplete" is not something anyone can act on.
    """
    present = {_normalise_heading(h) for h in headings or ()}
    out = []
    for section in required:
        if _normalise_heading(section) in present:
            continue
        out.append(finding(
            CRITICAL, 'config-section',
            '%s has no `## %s` section, so every value in it falls back to the '
            'default without saying so' % (path, section),
            _SECTION_FIXES.get(section, _SECTION_FIX_DEFAULT), path))
    return out


# A label flag in an instruction file: `--add-label`, `--remove-label` or plain
# `--label`, with the value written any of the three ways a shell takes it.
_LABEL_FLAG_RE = re.compile(
    r'--(?:add-|remove-)?labels?[\s=]+("[^"]*"|\'[^\']*\'|[^\s|;&)]+)')

# What a real label name looks like. Anything else inside a label flag is one of
# these files saying "the label you resolved" — `{status_ready_label}`,
# `<verdict-label>`, a bare `X` in an example — which is not a claim about any
# particular label and must not be checked as if it were.
_LABEL_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._:/-]{1,49}$')

_LABEL_TRIM = '`\'".,;:*()[]'


def scan_label_references(text):
    """Every concrete label an instruction file tells an agent to apply.

    Returns `[{'label': name, 'line': n}]`. Literals only — see
    `_LABEL_NAME_RE` for why placeholders are skipped rather than resolved.
    """
    found = []
    for number, line in enumerate((text or '').splitlines(), 1):
        for match in _LABEL_FLAG_RE.finditer(line):
            raw = match.group(1).strip('"\'')
            for token in raw.split(','):
                token = token.strip().strip(_LABEL_TRIM)
                if token and _LABEL_NAME_RE.match(token):
                    found.append({'label': token, 'line': number})
    return found


def _purpose_note(name, project_map):
    """If a hard-coded label is a purpose key the project renamed, say so."""
    mapped = (project_map or {}).get(name)
    if mapped and mapped != name:
        return (' — this project maps `%s` to `%s`, and the file hard-codes the '
                'default' % (name, mapped))
    return ''


def label_reference_findings(references, live_labels, project_map=None):
    """Files that tell an agent to apply a label the repo does not have.

    `references` is `[{'file': path, 'label': name, 'line': n}]`. The agent runs
    the command, `gh` refuses it, and the issue stays in whatever state it was
    already in — so this fails rather than warns.
    """
    live = set(live_labels or ())
    seen, out = set(), []
    for ref in references:
        key = (ref['file'], ref['label'])
        if ref['label'] in live or key in seen:
            continue
        seen.add(key)
        out.append(finding(
            CRITICAL, 'label-missing',
            '`%s` tells an agent to apply `%s`, which does not exist in this '
            'repo%s' % (ref['file'], ref['label'],
                        _purpose_note(ref['label'], project_map)),
            'either create the label, or rewrite the call site to resolve it '
            'through the label map',
            '%s:%s' % (ref['file'], ref['line'])))
    return out


def config_label_findings(project_map, review_labels, live_labels,
                          path='ClaudeProject.md'):
    """Labels the project's own config names that the repo does not carry."""
    live = set(live_labels or ())
    out = []
    for source, mapping in (('`## Label Map` in %s' % path, project_map or {}),
                            ('`docs/review.config.md`', review_labels or {})):
        for purpose, name in sorted(mapping.items()):
            if name in live:
                continue
            out.append(finding(
                CRITICAL, 'config-label',
                '%s maps `%s` to `%s`, which does not exist in this repo'
                % (source, purpose, name),
                'create the label, or correct the mapping to the name the repo '
                'actually uses', path))
    return out


def deprecated_label_findings(project_map, live_labels, path='ClaudeProject.md'):
    """Label-map rows for labels that no longer answer anything.

    Three families, all retired for the same reason: a structured field answers
    the question and the label was a second copy of the answer. `type-*` was
    replaced by the native issue type, `status-*` and `needs-refinement` by the
    board's `Status` field, the scope labels by `Ownership`, and `priority-*`
    by `Priority`.

    A row left in the label map is a standing invitation to hand-label an issue
    in a way nothing will read, so the rows are reported together with the
    instruction to delete them. The labels themselves are left alone: deleting
    a label deletes it off every issue that carries it, which is a data loss
    this command must not perform on the strength of a config check, and the
    write path takes them off issue by issue as it touches them.
    """
    rows = sorted(k for k in (project_map or {})
                  if k in TYPE_LABEL_KINDS or k in RETIRED_LABELS)
    if not rows:
        return []
    return [finding(
        WARNING, 'label-deprecated',
        '`## Label Map` in %s still maps %s, but nothing reads %s -- the '
        'structured fields answer what they used to answer, and the write path '
        'strips them off every issue it touches'
        % (path, _names(rows), 'that label' if len(rows) == 1 else 'those labels'),
        'delete %s from the label map; the labels themselves can stay until '
        'nobody is filtering on them by hand, because deleting one removes it '
        'from every issue that carries it'
        % ('that row' if len(rows) == 1 else 'those rows'),
        path)]


def _drift_key(name):
    """A label name with every separator flattened, for near-miss grouping."""
    return re.sub(r'[\s:_/]+', '-', (name or '').strip().lower())


def label_drift_findings(live_labels, project_map=None):
    """Two live labels that plainly mean the same thing.

    Two shapes, both seen in the wild: a separator that drifted
    (`priority:medium` beside `priority-medium`), and a prefix that was dropped
    (`blocked` beside `status-blocked`). Neither breaks a command — no label
    drives a decision since 10.0.0 — so both warn. They are still worth saying:
    a person filtering the issues list by hand sees one of the pair and thinks
    they are looking at all of it.
    """
    live = sorted(set(live_labels or ()))
    out = []

    grouped = {}
    for name in live:
        grouped.setdefault(_drift_key(name), []).append(name)
    for names in sorted(grouped.values()):
        if len(names) < 2:
            continue
        if len(retired_label_variants(names, project_map)) == len(names):
            # Two spellings of a label nothing reads. Asking which of them to
            # keep is the wrong question, and `label-retired` asks the right
            # one about the same pair.
            continue
        out.append(finding(
            WARNING, 'label-drift',
            '%s differ only in punctuation, so issues carrying one are invisible '
            'to a query for the other' % _names(names),
            'move every issue onto one of them and delete the rest'))

    # Every name the workflow applies, plus every name it used to: a project
    # part-way through the 10.0.0 migration still has `status-blocked` on real
    # issues, and `blocked` sitting beside it still splits what a person sees
    # when they filter the list by hand.
    present = set(live)
    known = dict(RETIRED_LABELS, **_DEFAULT_LABELS)
    for purpose in sorted(known):
        name = resolve_label(purpose, project_map or {}, known)
        if name not in present or '-' not in name:
            continue
        bare = name.split('-', 1)[1]
        if bare in present:
            out.append(finding(
                WARNING, 'label-drift',
                '`%s` exists alongside `%s`, and the workflow only ever applies '
                '`%s`' % (bare, name, name),
                'move every issue off `%s` onto `%s`, then delete `%s`'
                % (bare, name, bare)))
    return out


def pinned_field_findings(issue_types, required_names, portal_hint=True):
    """Types whose issue form will not show a field the tooling writes to.

    A field value is stored against the issue and the field, not against the
    type, so an unpinned field keeps whatever it holds and simply stops
    appearing on the issue's form. The write succeeds, the value is real, and
    nobody can see it — which is why this fails rather than warns.

    Asymmetry between types is a separate and softer matter: a field some
    enabled types carry and others do not is a warning, and only the fields the
    tooling actually writes are ever a failure.
    """
    enabled = [t for t in issue_types or () if t.get('enabled')]
    required = list(required_names or ())
    out = []

    for entry in enabled:
        missing = [n for n in required if n not in set(entry.get('pinned') or ())]
        if not missing:
            continue
        fix = 'pin them to `%s`' % entry['name']
        if portal_hint:
            fix += (' in the org settings: Planning → Issue fields → the '
                    'field\'s edit form → "Pin to issues"')
        out.append(finding(
            CRITICAL, 'field-unpinned',
            'issue type `%s` is not pinned to %s, so a value the tooling writes '
            'is stored and then never shown on the issue'
            % (entry['name'], _names(missing)),
            fix))

    everywhere = {}
    for entry in enabled:
        for name in entry.get('pinned') or ():
            everywhere.setdefault(name, set()).add(entry['name'])
    names = {e['name'] for e in enabled}
    for name in sorted(everywhere):
        if name in required:
            continue
        absent = sorted(names - everywhere[name])
        if not absent:
            continue
        out.append(finding(
            WARNING, 'pin-asymmetry',
            '`%s` is pinned to %s but not to %s'
            % (name, _names(sorted(everywhere[name])), _names(absent)),
            'no action if that is deliberate — a type that cannot hold the '
            'field should not pin it'))
    return out


def unmapped_field_findings(field_names, project_fields=None,
                            path='ClaudeProject.md'):
    """Org fields that no purpose key resolves to.

    The tooling cannot write one, so the field sits empty on every issue the
    workflow creates. That degrades rather than breaks, so it warns.
    """
    out = []
    for name in sorted(set(field_names or ())):
        if field_purpose_for_name(name, project_fields or {}):
            continue
        out.append(finding(
            WARNING, 'field-unmapped',
            'the org defines `%s`, which no purpose key in `## Issue Types & '
            'Fields` maps to, so nothing ever sets it' % name,
            'add a row mapping a `field-*` purpose key to `%s`, or leave the '
            'field to be filled in by hand' % name, path))
    return out


def board_column_findings(columns, live_options, path='ClaudeProject.md'):
    """Where the recorded snapshot and the live board disagree, either way.

    `columns` is `{purpose key: option id}`, `live_options` is
    `{option id: name}`. Two disagreements, both warnings, because a stale
    snapshot costs the recorded shortcut and not the move -- `board-move`
    resolves a column by name at write time. Whether the column exists at all
    is `board_lane_findings`, and that one is critical for `Backlog`.

    The second direction is the one a repair creates. Adding a lane to the
    board fixes `board-lane` and leaves the file recording that lane as `n/a`,
    which nothing reported until this checked for it -- so the run that created
    three columns looked clean while the file still said the board had none of
    them.
    """
    live = live_options or {}
    recorded = columns or {}
    out = []
    for purpose, option_id in sorted(recorded.items()):
        if option_id in live:
            continue
        out.append(finding(
            WARNING, 'board-column',
            '`%s` is recorded as option `%s`, which the board no longer has, so '
            'that move is skipped' % (purpose, option_id),
            'refresh the `### Status Options` table from the live board',
            path))
    names = {(name or '').strip().lower() for name in live.values()}
    for purpose, name in sorted(BOARD_COLUMN_NAMES.items()):
        if purpose in recorded or name.strip().lower() not in names:
            continue
        out.append(finding(
            WARNING, 'board-column',
            'the board has a `%s` column and `%s` records no option id for it, '
            'so every move to that lane costs a lookup it should not have to '
            'make' % (name, path),
            'refresh the `### Status Options` table from the live board',
            path))
    return out


def board_lane_findings(live_option_names, path='ClaudeProject.md'):
    """Lanes the workflow moves issues into that the live board does not have.

    The pool column is the severe one, and it is severe because selection reads
    it: a board with no `Backlog` column gives `pick` nowhere to look. Until
    9.0.0 that came back as an empty pool rather than an error, so a board
    nobody had configured and a backlog nobody had filled produced the same
    answer — and the misconfiguration was the likelier of the two. The rest
    warn: a missing lane loses one state's board move, which a person notices
    on the board and no command depends on.
    """
    live = {(name or '').strip().lower() for name in live_option_names or ()}
    out = []
    for purpose, name in sorted(BOARD_COLUMN_NAMES.items()):
        if name.strip().lower() in live:
            continue
        if purpose == POOL_COLUMN:
            out.append(finding(
                CRITICAL, 'board-lane',
                'the board has no `%s` column, and that column *is* the pick '
                'pool, so selection has nothing to read' % name,
                "add a `%s` option to the board's status field" % name, path))
        else:
            out.append(finding(
                WARNING, 'board-lane',
                'the board has no `%s` column, so an issue that reaches that '
                'state stays in whichever lane it was already in' % name,
                "add a `%s` option to the board's status field" % name, path))
    return out


def absent_field_findings(defined_names, project_fields=None,
                          path='ClaudeProject.md'):
    """Fields the org has not created, split by whether a decision reads one.

    The required three are critical, and this is the check the whole
    field-driven workflow rests on. `Priority` is the pool's sort order,
    `Effort` its size ceiling, `Ownership` whether a code agent may touch the
    issue at all. A field the org has not defined is a question with no answer
    and no way to acquire one, so it is reported rather than skipped -- and
    skipping is exactly what happened before 10.0.0, which is how a repository
    ran for weeks with no `Ownership` field while `wf config-audit` reported a
    clean configuration.

    `Classification` and `Origin` warn. Nothing selects on them, so an org
    without them still works; it just files issues with less on them.

    `defined_names` is the org's live field-name set.
    """
    defined = {str(n).strip().lower() for n in (defined_names or ())}

    def absent(keys):
        return [resolve_field_name(k, project_fields or {}) for k in keys
                if resolve_field_name(k, project_fields or {}).strip().lower()
                not in defined]

    out = []
    missing = absent(MANDATORY_FIELD_KEYS)
    if missing:
        out.append(finding(
            CRITICAL, 'field-absent',
            'the org defines no %s field%s, and the picker reads %s on every '
            'issue: nothing can be ranked, sized or routed without %s'
            % (_names(missing), '' if len(missing) == 1 else 's',
               'it' if len(missing) == 1 else 'them',
               'it' if len(missing) == 1 else 'them'),
            'create %s as an org issue field (Planning -> Issue fields), pin it '
            'to every enabled issue type, then run `wf issue-audit` and apply the '
            'spec it writes to backfill the backlog' % _names(missing),
            path))
    optional = absent(OPTIONAL_FIELD_KEYS)
    if optional:
        out.append(finding(
            WARNING, 'field-absent-optional',
            'the org defines no %s field%s, so every issue is filed without '
            '%s; nothing selects on %s, so this costs detail rather than '
            'behaviour'
            % (_names(optional), '' if len(optional) == 1 else 's',
               'it' if len(optional) == 1 else 'them',
               'it' if len(optional) == 1 else 'them'),
            'create %s as an org issue field, or leave it and accept that '
            'issues carry less' % _names(optional),
            path))
    return out


# Board columns a previous version of the workflow selected from. `Ready` was
# the opt-in pool: an issue was invisible until somebody moved it there or
# labelled it. Backlog is the pool now, and a board that still carries a Ready
# lane has a column whose cards nothing will ever look at.
RETIRED_BOARD_COLUMNS = ('Ready',)


def retired_label_findings(issues, project_map=None, path='ClaudeProject.md'):
    """Open issues still carrying a label the workflow retired.

    `issues` are dicts with `number` and `labels`. The label decides nothing,
    which is exactly why it is worth taking off: it is a second, stale answer
    to a question the fields now answer, and a person filtering the issues list
    by hand still believes it.

    Repairable, and one of the few writes `--fix` will make to an issue: the
    write path already strips these off any issue it touches, so this is the
    same operation applied to the issues no command has reached.
    """
    carrying = []
    for issue in issues or ():
        stale = retired_label_variants(issue.get('labels'), project_map)
        if stale:
            carrying.append((issue.get('number'), stale))
    if not carrying:
        return []
    names = sorted({n for _number, stale in carrying for n in stale})
    numbers = sorted(n for n, _stale in carrying if n is not None)
    shown = ', '.join('#%d' % n for n in numbers[:10])
    if len(numbers) > 10:
        shown += ' and %d more' % (len(numbers) - 10)
    return [finding(
        WARNING, 'label-retired',
        '%d open issue%s still carr%s %s, %s the structured fields answered '
        'and nothing reads any more (%s)'
        % (len(carrying), '' if len(carrying) == 1 else 's',
           'ies' if len(carrying) == 1 else 'y', _names(names),
           'a question' if len(names) == 1 else 'questions', shown),
        'run `wf preflight --fix`, which takes them off, or leave them and let '
        'the write path clear each issue the next time a command touches it',
        path)]


def board_retired_findings(live_option_names, path='ClaudeProject.md'):
    """A lane on the board that this workflow no longer selects from."""
    live = {(name or '').strip().lower(): name for name in live_option_names or ()}
    out = []
    for retired in RETIRED_BOARD_COLUMNS:
        name = live.get(retired.strip().lower())
        if not name:
            continue
        out.append(finding(
            WARNING, 'board-retired',
            'the board still has a `%s` column, which nothing selects from: the '
            'pool is `%s`, and a card left in `%s` is invisible to every command'
            % (name, BOARD_COLUMN_NAMES[POOL_COLUMN], name),
            'run `wf preflight --fix`, which moves any card still in it to `%s` '
            'and then removes the column'
            % BOARD_COLUMN_NAMES[POOL_COLUMN],
            path))
    return out


# The option names each mandatory field's decision is defined against. A value
# outside these is not an error in the org's data -- a project may call its
# levels whatever it likes -- but it is one this code cannot act on, and the
# way it fails is silent: an unrankable `Priority` sorts last, an unreadable
# `Effort` sorts as Medium, and an `Ownership` nothing recognises is never
# offered to any agent.
def _known_field_options():
    return {
        'field-priority': (sorted(PRIORITY_FIELD_RANK), WARNING,
                           'issues carrying it sort last, behind every issue '
                           'the picker can rank'),
        'field-effort': (sorted(EFFORT_RANK), WARNING,
                         'issues carrying it are sized as `Medium`, and '
                         '`--max-effort` cannot exclude them'),
        'field-ownership': (sorted(o.lower() for o
                                   in OWNERSHIP_FIELD_OPTIONS.values()),
                            CRITICAL,
                            'nothing can route an issue carrying it, so no '
                            'agent is ever offered it'),
    }


def field_option_findings(field_map, project_fields=None,
                          path='ClaudeProject.md'):
    """Options on a mandatory field that no decision in this workflow knows.

    The check the field-driven workflow was missing: `field-absent` proves the
    org has a `Priority` field, and nothing proved that its options were the
    ones the picker ranks. An org that renamed `Urgent` to `P0` kept a clean
    audit and a backlog that silently sorted every P0 issue last.
    """
    field_map = field_map or {}
    out = []
    for purpose, (known, level, consequence) in sorted(_known_field_options().items()):
        name = resolve_field_name(purpose, project_fields or {})
        meta = field_map.get(name)
        if not meta:
            continue  # `field-absent` owns the missing case
        options = list((meta.get('options') or {}))
        if not options:
            continue
        unknown = sorted(o for o in options if str(o).strip().lower() not in known)
        if not unknown:
            continue
        readable = ', '.join('`%s`' % o for o in known)
        if len(unknown) == len(options):
            out.append(finding(
                level, 'field-options',
                'no option on `%s` is one this workflow knows (it has %s, and '
                'reads %s), so %s'
                % (name, _names(options), readable, consequence),
                'rename the options to %s, or leave them and accept that %s'
                % (readable, consequence), path))
            continue
        out.append(finding(
            level, 'field-options',
            '`%s` carries %s, which %s not %s, so %s'
            % (name, _names(unknown), 'is' if len(unknown) == 1 else 'are',
               'an option this workflow reads (%s)' % readable, consequence),
            'rename %s to one of %s, or move the issues carrying %s onto an '
            'option this workflow reads'
            % (_names(unknown), readable,
               'it' if len(unknown) == 1 else 'them'), path))
    return out


# Vocabulary a project's own instructions can still carry from before the
# structured-field workflow. Each pattern is a thing a session would act on:
# telling the model to look for a `Ready` label or to read a dependency out of
# a body sends it to do work the tooling will not agree with, and nothing else
# reports that.
_RETIRED_INSTRUCTION_PATTERNS = (
    (r'status[-:_ ]ready|claude-ready|`?Ready`? (?:label|column|gate|status)|##\s*Ready Gate',
     'the `Ready` opt-in, which no longer exists -- the pool is the board\'s '
     '`Backlog` column'),
    (r'status[-:_](?:in-progress|blocked|parked|non-code|in-review|needs-attention)|'
     r'\bneeds-refinement\b|\bhuman-required\b|\bbrowser-agent\b|priority[-:](?:critical|high|medium|low)',
     'a lifecycle, scope or priority label that decided something and no '
     'longer does'),
    (r'(?i)blocked by\s*#\d+|depends on\s*#\d+',
     'a dependency written as prose, which nothing reads: the native '
     'blocked-by edge is the only record'),
)


def instruction_findings(files, path=None):
    """Retired workflow vocabulary in a project's own instruction files.

    `files` is ``{relative path: text}``. Reported per file with the line
    numbers, and never repaired: these are somebody's sentences, and an
    automatic edit would either mangle the paragraph around the phrase or
    delete a line that was explaining the history on purpose.
    """
    out = []
    for name in sorted(files or {}):
        text = files[name] or ''
        hits = {}
        for pattern, why in _RETIRED_INSTRUCTION_PATTERNS:
            matcher = re.compile(pattern)
            for number, line in enumerate(text.splitlines(), 1):
                if matcher.search(line):
                    hits.setdefault(why, []).append(number)
        for why in sorted(hits):
            lines = sorted(set(hits[why]))
            shown = ', '.join(str(n) for n in lines[:5])
            if len(lines) > 5:
                shown += ' and %d more' % (len(lines) - 5)
            out.append(finding(
                WARNING, 'instructions-retired',
                '%s describes %s (line%s %s), so a session reading it is told '
                'to do something the tooling no longer does'
                % (name, why, '' if len(lines) == 1 else 's', shown),
                'rewrite those lines against the current workflow: the board '
                'column is the state, `Priority`, `Effort` and `Ownership` are '
                'the fields every decision reads, and a dependency is a native '
                'blocked-by edge',
                name))
    return out


def board_unset_findings(numbers, path='ClaudeProject.md'):
    """Open issues whose board card holds no `Status` value.

    Critical for the same reason as `board_orphan_findings`, and separate from
    it because the fix is a different one: the card exists, so nothing needs
    adding, but it sits in the board's `No Status` bucket rather than in a
    lane. Since the column *is* the state, an issue there is in no state at
    all -- not available, not blocked, not in progress, and invisible to every
    command that reads a lane.

    A card lands there when somebody adds an issue to the board by hand, which
    is the one path that does not go through `board-move`.
    """
    numbers = sorted(set(numbers or ()))
    if not numbers:
        return []
    shown = ', '.join('#%d' % n for n in numbers[:10])
    if len(numbers) > 10:
        shown += ' and %d more' % (len(numbers) - 10)
    return [finding(
        CRITICAL, 'board-unset',
        '%d open issue%s a board card with no `Status` value (%s), so %s in no '
        'lane at all -- the column is the state, and these have none'
        % (len(numbers), ' has' if len(numbers) == 1 else 's have', shown,
           'it is' if len(numbers) == 1 else 'they are'),
        'run `wf board-move <number> --column col-backlog` for each, or move '
        'the card into whichever lane matches its real state',
        path)]


def board_orphan_findings(numbers, path='ClaudeProject.md'):
    """Open unassigned issues with no card on the board.

    Critical, and this is the check that makes the 9.0.0 pool safe to adopt.
    The pool is the board's `Backlog` column, so an issue with no card is
    invisible to `pick` whatever it carries — and an upgrade silently shrinks
    the backlog to whatever happened to be on the board already. New issues
    cannot land in this state (`issue-apply` places every issue it touches);
    every issue filed before that did can.
    """
    numbers = sorted(set(numbers or ()))
    if not numbers:
        return []
    shown = ', '.join('#%d' % n for n in numbers[:10])
    if len(numbers) > 10:
        shown += ' and %d more' % (len(numbers) - 10)
    return [finding(
        CRITICAL, 'board-orphan',
        '%d open unassigned issue%s no card on the board (%s), and the pick '
        'pool is a board column, so nothing can select %s'
        % (len(numbers), ' has' if len(numbers) == 1 else 's have', shown,
           'it' if len(numbers) == 1 else 'them'),
        'run `wf board-move <number> --column col-backlog` for each, which '
        'adds the card as well as setting the column',
        path)]


def preflight_summary(findings):
    """Counts by level and by check, so a run reports a shape, not a wall."""
    checks = {}
    for entry in findings:
        checks[entry['check']] = checks.get(entry['check'], 0) + 1
    return {'critical': sum(1 for f in findings if f['level'] == CRITICAL),
            'warning': sum(1 for f in findings if f['level'] == WARNING),
            'checks': checks}


# ── PR review-state labels + selection ───────────────────────────────────────
# Mirrors the code-review
# skill (Step 1). Review-state names default to the `review-` prefix
# (templates/default-labels.md) and are overridden by review.config.md.

REVIEW_DEFAULT_LABELS = {
    'needs-review': 'review-needs-review',
    'reviewing': 'review-reviewing',
    'approved': 'review-approved',
    'changes-requested': 'review-changes-requested',
    'needs-discussion': 'review-needs-discussion',
    'needs-re-review': 'review-needs-re-review',
    'failed': 'review-failed',
    'updating': 'review-updating',
    'fixes-applied': 'review-fixes-applied',
}


def resolve_review_label(purpose_key, review_map=None, defaults=None):
    """Resolve a review-state purpose key to a concrete label name.

    Same three-step path as resolve_label: review.config.md map →
    `review-` prefixed default → the key itself.
    """
    review_map = review_map or {}
    if defaults is None:
        defaults = REVIEW_DEFAULT_LABELS
    return review_map.get(purpose_key) or defaults.get(purpose_key) or purpose_key


def review_names(review_map=None):
    """Resolve every review-state purpose to its concrete name (one dict)."""
    return {k: resolve_review_label(k, review_map) for k in REVIEW_DEFAULT_LABELS}


def select_update_pool(prs, names):
    """Order PRs that need *my* review feedback addressed (code-review rework pool).

    Keep PRs carrying an actionable state — changes-requested >
    needs-discussion > needs-re-review (priority order) — and drop any
    carrying reviewing / updating / approved / needs-review / failed (another
    agent owns it, or there is no feedback to apply). Sort by that priority,
    then ascending PR number. `names` maps purpose keys to concrete labels.
    """
    priority = [names['changes-requested'], names['needs-discussion'], names['needs-re-review']]
    skip = {names[k] for k in ('reviewing', 'updating', 'approved', 'needs-review', 'failed')}
    ranked = []
    for pr in prs:
        labels = set(pr.get('labels', []))
        if labels & skip:
            continue
        rank = next((i for i, name in enumerate(priority) if name in labels), None)
        if rank is None:
            continue
        ranked.append((rank, pr['number'], pr))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [pr for _, _, pr in ranked]


def select_review_pool(prs, names):
    """Order PRs that need reviewing (code-review pool).

    Keep PRs carrying needs-re-review or needs-review; drop any carrying
    reviewing / updating (an agent is on it), and drop approved unless it also
    carries needs-re-review (approved + new commits still needs a re-review).
    needs-re-review is reviewed before needs-review; ties break on ascending
    number. (SHA-drift detection — a PR whose head changed since the last
    review without a label — stays in the skill; this is the label-driven
    subset.)
    """
    skip = {names['reviewing'], names['updating']}
    ranked = []
    for pr in prs:
        labels = set(pr.get('labels', []))
        if labels & skip:
            continue
        has_rereview = names['needs-re-review'] in labels
        has_review = names['needs-review'] in labels
        if not (has_rereview or has_review):
            continue
        if names['approved'] in labels and not has_rereview:
            continue
        ranked.append((0 if has_rereview else 1, pr['number'], pr))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [pr for _, _, pr in ranked]


def actionable_update_label(labels, names):
    """The highest-priority actionable state label present on an update PR.

    Returned so the caller can record which feedback state it claimed (the
    code-review skill needs it for its final relabel decision).
    """
    for purpose in ('changes-requested', 'needs-discussion', 'needs-re-review'):
        if names[purpose] in labels:
            return names[purpose]
    return None


# ── Review-finish label reconciliation ───────────────────────────────────────
# Encodes the code-review skill's Step 10/10b: on a verdict, strip every stale
# review-state label and leave exactly the one verdict label. The seven state
# labels are mutually exclusive — exactly one belongs on a settled PR.

REVIEW_STATE_KEYS = [
    'needs-review', 'reviewing', 'approved', 'changes-requested',
    'needs-discussion', 'needs-re-review', 'failed',
]
# The verdicts code-review can record (the three a review can conclude with;
# `failed` is set on the error path, not by review-finish).
REVIEW_VERDICT_KEYS = ('approved', 'changes-requested', 'needs-discussion')


def reconcile_review_labels(current_labels, verdict, names, fixes_applied=False):
    """Compute the (add, remove) label deltas that record a review verdict.

    Given the PR's current labels and a verdict purpose key, returns the
    concrete label names to add and to remove so the PR ends carrying exactly
    one review-state label (the verdict) — the deterministic "label dance" the
    code-review skill used to spell out in prose.

      - remove: every managed state label currently present except the verdict.
      - add:    the verdict label if not already present, plus `fixes-applied`
                when `fixes_applied` is set and it is not already present
                (the sticky action label, never removed here).

    `names` is the resolved review-name map (`review_names`). Both lists are
    sorted for deterministic output. Raises ValueError on an unknown verdict so
    a caller can never silently apply the wrong label.
    """
    if verdict not in REVIEW_VERDICT_KEYS:
        raise ValueError('unknown review verdict %r (expected one of %s)'
                         % (verdict, ', '.join(REVIEW_VERDICT_KEYS)))
    target = names[verdict]
    current = set(current_labels)
    managed = {names[k] for k in REVIEW_STATE_KEYS}
    remove = sorted((managed & current) - {target})
    add = []
    if target not in current:
        add.append(target)
    if fixes_applied and names['fixes-applied'] not in current:
        add.append(names['fixes-applied'])
    return add, remove


def review_label_missing(labels_after, verdict, names):
    """Return the verdict label if it did not stick after the edit, else None.

    Drives the guarded create-if-missing readback: when the verdict label is
    absent from the post-edit labels, the label likely does not exist on the
    repo and must be created (without `--force`) and re-applied.
    """
    target = names[verdict]
    return None if target in labels_after else target


# ── Backlog-mode detection ───────────────────────────────────────────────────
# Backlog mode — sprint vs flat from milestone presence.

def detect_backlog_mode(candidates):
    """Return 'sprint' if any candidate has a milestone, otherwise 'flat'."""
    return 'sprint' if any(c.get('milestone') for c in candidates) else 'flat'


def get_sprint_candidates(candidates, sprint_title):
    """Narrow candidates to those belonging to the active sprint."""
    return [c for c in candidates if c.get('milestone') == sprint_title]


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


# ── Bulk set planning (bulk-execute) ─────────────────────────────────────────
# `bulk-execute` builds two to five related stories on one branch behind one
# pull request. Two of its decisions are pure enough to live here rather than
# in prose: which dependencies still block a story that is being built
# alongside its own dependency, and what order the set has to be built in.

BULK_MIN = 2
BULK_MAX = 5


def blocking_dependencies(deps, open_numbers, siblings=()):
    """Return the dependencies that genuinely block a story.

    A dependency blocks when it is still **open** and is **not** being built
    alongside this story. That sibling carve-out is the whole reason a bulk
    run can take a dependency chain: `execute`'s rule is "do not build on
    unmerged work you cannot see", and a story landing in the same commit
    series on the same branch is work you can see. Anything open and outside
    the set still blocks, exactly as it does for a single-story run.

    `deps` are the numbers parsed out of the issue body, `open_numbers` those
    of them the caller found still open, and `siblings` the rest of the bulk
    set. Returns the blocking numbers in the order they appear in `deps`.
    """
    open_set = {int(n) for n in (open_numbers or ())}
    sib = {int(n) for n in (siblings or ())}
    return [d for d in deps if int(d) in open_set and int(d) not in sib]


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


def edge_states(edges):
    """Split native blocked-by edges into (open_numbers, closed_numbers).

    `edges` are `{'number': int, 'state': 'OPEN'|'CLOSED'}` nodes in the shape
    GraphQL returns them. Order is kept and duplicates dropped, so a caller
    can name the blockers in the order the issue itself lists them.
    """
    open_numbers, closed_numbers, seen = [], [], set()
    for edge in edges or ():
        try:
            number = int(edge.get('number'))
        except (TypeError, ValueError):
            continue
        if number in seen:
            continue
        seen.add(number)
        if (edge.get('state') or '').upper() == 'OPEN':
            open_numbers.append(number)
        else:
            closed_numbers.append(number)
    return open_numbers, closed_numbers


def unblock_verdict(edges):
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
    """
    open_numbers, closed_numbers = edge_states(edges)
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


def plan_bulk_order(stories, max_size=BULK_MAX):
    """Trim a proposed bulk set to size and put it in build order.

    `stories` is the proposed set in preference order, **lead first** — dicts
    carrying `number`, and `blocked_by` when the story has native dependency
    edges (a list of issue numbers). Two passes:

      1. **Trim** to `max_size`, keeping input order, so the lead and the
         highest-preference siblings are the ones that survive.
      2. **Order** so each story is built after every story in the set it
         depends on. Stories that are ready at the same time keep their input
         order, so a set with no internal dependencies comes back unchanged.

    A dependency cycle inside the set cannot be ordered. Once no story is
    ready, the ones still unplaced are appended in input order and reported,
    so the caller can say so rather than silently choosing an order.

    Returns (ordered, notes). `ordered` is the story dicts in build order.
    `notes` is a list of {'number', 'reason'} with reason `'trimmed'` (cut by
    `max_size`) or `'dependency-cycle'`. Enforcing `BULK_MIN` is the caller's
    job: a set that shrinks to one story is a single-story run, not an error.
    """
    stories = list(stories or [])
    notes = []
    if max_size is not None and max_size > 0 and len(stories) > max_size:
        for extra in stories[max_size:]:
            notes.append({'number': extra['number'], 'reason': 'trimmed'})
        stories = stories[:max_size]
    if not stories:
        return [], notes

    present = {s['number'] for s in stories}
    deps_in_set = {}
    for story in stories:
        edges = [int(d) for d in (story.get('blocked_by') or ())]
        deps_in_set[story['number']] = {d for d in edges
                                        if d in present and d != story['number']}

    ordered, placed, remaining = [], set(), list(stories)
    while remaining:
        ready = [s for s in remaining if deps_in_set[s['number']] <= placed]
        if not ready:
            for stuck in remaining:
                notes.append({'number': stuck['number'], 'reason': 'dependency-cycle'})
            ordered.extend(remaining)
            break
        for story in ready:
            ordered.append(story)
            placed.add(story['number'])
        remaining = [s for s in remaining if s['number'] not in placed]
    return ordered, notes


# ── a bulk set chosen from a container (`candidates --parent`) ───────────────
# An Epic or grouping Feature is not work, but its tree is the best answer
# there is to "which stories belong in one pull request". These two functions
# are the decision half of that answer; `cmd_candidates --parent` does the
# reading. The rules were settled on #239.

def parent_leaf_groups(root, repo=None):
    """Walk a container's sub-issue tree and group its open leaves.

    `root` is `{'number', 'type', 'state', 'repo', 'children': [...]}`,
    nested. A leaf is an open descendant that is not a container. Each leaf is
    grouped under its nearest `Feature` ancestor, or under the root itself when
    it hangs directly off it.

    Returns (groups, empty, foreign). `groups` maps a group number to its
    leaves in tree order. `empty` lists the open Features with no open leaf
    under them: building a whole Feature as one story is the oversized unit
    the tree exists to prevent. `foreign` lists open descendants in another
    repository, which this repository's board and claims cannot speak for.
    """
    groups, empty, foreign = {}, [], []

    def walk(node, group):
        found = False
        for child in node.get('children') or ():
            if (child.get('state') or '').upper() != 'OPEN':
                continue
            if repo and child.get('repo') and child['repo'] != repo:
                foreign.append(child['number'])
                continue
            kind = child.get('type')
            if kind in HIERARCHY_CONTAINER_TYPES:
                inner = child['number'] if kind == 'Feature' else group
                if walk(child, inner):
                    found = True
                elif kind == 'Feature' and not child.get('unread'):
                    # A Feature whose stories were past the tree read is
                    # not empty; the caller reports it as unread instead.
                    empty.append(child['number'])
                continue
            groups.setdefault(group, []).append(child['number'])
            found = True
        return found

    walk(root, root['number'])
    return groups, empty, foreign


def choose_parent_set(root, pool_order, deps, reasons=None, max_size=BULK_MAX,
                      repo=None):
    """Choose one bulk set from the leaves under an Epic or Feature.

    `pool_order` is the pool -- Backlog, owned by the code agent, unassigned --
    in priority order. `deps` maps every leaf a run could take to its **open**
    blockers: the pool's leaves, and the leaves in the Blocked column that the
    code agent owns, which appear in `deps` but not in `pool_order`.
    `reasons` is the caller's explanation for any other leaf: its column, its
    owner. Nothing else is ever taken, so Non-code work never is.

    - **One group per run.** The Feature (or the root, for leaves hanging off
      it directly) holding the highest-priority pool leaf with no open
      blocker. A group is one deliverable surface; leaves from two are the
      unrelated bundle bulk-execute exists to avoid.
    - **A leaf with open blockers is taken only when every one of them is
      taken too.** That is the only way a Blocked leaf gets in: its blocker is
      a sibling being built in the same run.
    - **Put in build order, then cut to `max_size`.** The order is greedy:
      the next leaf is always the highest-priority one whose blockers are
      already placed, so a waiting leaf keeps its priority and every prefix
      carries its own blockers. The set only comes back short when the tree
      is short.

    Returns {'group', 'selected', 'excluded'}: `selected` is story dicts in
    build order, each carrying `blocked_by`; `excluded` is every other leaf
    as {'number', 'reason'}.
    """
    reasons = reasons or {}
    groups, empty, foreign = parent_leaf_groups(root, repo)
    order = [leaf for leaves in groups.values() for leaf in leaves]
    group_of = {leaf: g for g, leaves in groups.items() for leaf in leaves}
    in_pool = [n for n in pool_order if n in group_of]
    takeable = in_pool + [n for n in deps if n in group_of and n not in in_pool]
    ready = [n for n in in_pool if not deps.get(n)]
    group = group_of[ready[0]] if ready else None

    kept, trimmed = [], set()
    if group is not None:
        members = [n for n in takeable if group_of[n] == group]
        chosen = {n for n in members if not deps.get(n)}
        grew = True
        while grew:
            grew = False
            for n in members:
                if n not in chosen and set(deps.get(n) or ()) <= chosen:
                    chosen.add(n)
                    grew = True
        stories = [{'number': n, 'blocked_by': list(deps.get(n) or ())}
                   for n in members if n in chosen]
        # Greedy, not `plan_bulk_order`'s rounds: a round puts every ready
        # leaf ahead of any leaf waiting on one, whatever their priority, so
        # the cut would take a higher-priority dependent before a ready leaf
        # below it. Every blocker of a chosen leaf was chosen before it, so
        # there is always a next one, and every prefix carries its blockers.
        ordered, placed, remaining = [], set(), list(stories)
        while remaining:
            story = next(s for s in remaining if set(s['blocked_by']) <= placed)
            ordered.append(story)
            placed.add(story['number'])
            remaining.remove(story)
        cap = max_size if max_size and max_size > 0 else len(ordered)
        kept = ordered[:cap]
        trimmed = {s['number'] for s in ordered[cap:]}

    selected = {s['number'] for s in kept}
    excluded = []
    for n in order:
        if n in selected:
            continue
        if n in trimmed:
            reason = ('left out by --size; the stories ahead of it in priority '
                      'and build order were kept')
        elif group is not None and group_of[n] != group and n in takeable:
            reason = 'under #%d, not the Feature this run takes' % group_of[n]
        elif deps.get(n):
            reason = 'blocked by %s, which this run is not building' % ', '.join(
                '#%d' % d for d in deps[n])
        else:
            reason = reasons.get(n, 'not in the pool')
        excluded.append({'number': n, 'reason': reason})
    excluded += [{'number': n, 'reason': 'a Feature with no open stories yet'}
                 for n in empty]
    excluded += [{'number': n, 'reason': 'in another repository'}
                 for n in foreign]
    return {'group': group, 'selected': kept, 'excluded': excluded}


# ── closing a finished container (#240) ──────────────────────────────────────
# GitHub's native sub-issues never close a parent, and a merge closes only the
# issues its pull request names. So an Epic or Feature whose last story merged
# stayed open, in a column nobody routinely looks at, until somebody noticed.

def container_finished(node, closed=()):
    """Whether an Epic or Feature is finished: open, and every sub-issue closed.

    `node` is `{'number', 'type', 'state', 'children': [{'number', 'state'}]}`.
    `closed` names issues this run has just closed, whose read may predate it.

    Any close counts, including "not planned": a container held open by one
    dropped story would stay open for ever. A container with no sub-issues is
    never finished, because an empty Epic may be a placeholder.
    """
    if node.get('type') not in HIERARCHY_CONTAINER_TYPES:
        return False
    if (node.get('state') or '').upper() != 'OPEN':
        return False
    children = node.get('children') or []
    if not children:
        return False
    done = set(closed or ())
    return all((c.get('state') or '').upper() == 'CLOSED' or c.get('number') in done
               for c in children)


def ancestors_to_close(origin, chain, closed=(), repo=None):
    """The ancestors closing `origin` finishes, nearest first.

    `chain` is `origin`'s parents, nearest first, each shaped as
    `container_finished` reads it plus `repo`. The walk stops at the first
    parent that is not finished, because every ancestor above it has it as an
    open child, and at the first one in another repository, which this
    repository has no business closing.

    Returns [{'number', 'finished_by'}], where `finished_by` is the child whose
    close finished it -- `origin` for the nearest, the one below for the rest.
    """
    done = set(closed or ()) | {origin}
    out, child = [], origin
    for node in chain or ():
        if repo and node.get('repo') and node['repo'] != repo:
            break
        if not container_finished(node, done):
            break
        out.append({'number': node['number'], 'finished_by': child})
        done.add(node['number'])
        child = node['number']
    return out


def finished_container_findings(containers, path='ClaudeProject.md'):
    """One warning naming every open Epic or Feature that is already finished."""
    if not containers:
        return []
    count = len(containers)
    return [finding(
        WARNING, 'container-finished',
        '%d open Epic or Feature issue%s %s every sub-issue closed, and nothing '
        'closes a container on its own: %s'
        % (count, '' if count == 1 else 's', 'has' if count == 1 else 'have',
           ', '.join('#%d' % c['number'] for c in containers)),
        'close each as completed, or run `wf preflight --fix`', path)]


# ── preflight: the file-level checks, and what `--fix` may repair ────────────
# `config-audit` compares `ClaudeProject.md` against the live repo, board and
# org. It never looked at the file's own contents beyond its headings, so the
# checks below lived in shell blocks inside `skills/preflight/SKILL.md` -- a
# second implementation, in a second language, of the same idea. They are here
# now because a check that decides whether a workflow runs has to be as
# testable as the picker it gates.

# The template's own placeholder vocabulary. A file that still carries one was
# copied and not filled in, and every value it holds is a guess.
_PLACEHOLDER_RE = re.compile(
    r'\{(org|repo|name|id|package_manager|quality_gate_command|branch_pattern'
    r'|default_branch|n|criteria|path/to/doc)\}')

# Sections a previous version of the workflow read and this one does not. A
# file that still carries one is not misconfigured, it is out of date -- but
# leaving it in place means the next person to read the file believes it.
RETIRED_CONFIG_SECTIONS = {
    'Ready Gate': ("the pool is the board's `Backlog` column, which no setting "
                   'turns off'),
    'Agent Gating': ('approval is the card being in `Backlog`, so there is no '
                     'gate to enable'),
}


def placeholder_findings(text, path='ClaudeProject.md'):
    """Template placeholders nobody replaced.

    A warning rather than a failure: a placeholder in a section no command
    reaches costs nothing, and the ones that do matter fail their own check.
    """
    hits = []
    for number, line in enumerate((text or '').splitlines(), 1):
        if _PLACEHOLDER_RE.search(line):
            hits.append(number)
    if not hits:
        return []
    shown = ', '.join(str(n) for n in hits[:5])
    if len(hits) > 5:
        shown += ' and %d more' % (len(hits) - 5)
    return [finding(
        WARNING, 'placeholders',
        '%d line%s in %s still carr%s a template placeholder (line%s %s), so '
        "the value there is the template's, not this project's"
        % (len(hits), '' if len(hits) == 1 else 's', path,
           'ies' if len(hits) == 1 else 'y', '' if len(hits) == 1 else 's', shown),
        'fill them in, or run `/github-workflow:setup` to write them from the '
        'live repo', path)]


def retired_section_findings(headings, path='ClaudeProject.md'):
    """Sections this version of the workflow reads and ignores."""
    present = {_normalise_heading(h) for h in headings or ()}
    out = []
    for section, why in sorted(RETIRED_CONFIG_SECTIONS.items()):
        if _normalise_heading(section) not in present:
            continue
        out.append(finding(
            WARNING, 'config-retired',
            '%s still has a `## %s` section, which nothing reads -- %s'
            % (path, section, why),
            'delete the section', path))
    return out


def quality_gate_findings(command, path='ClaudeProject.md'):
    """The pre-commit command, or the absence of one.

    Unset means every run decides for itself what "the tests pass" means, which
    is the difference between a gate and a habit. It still warns: a project
    with no gate is a project, not a broken configuration.
    """
    value = (command or '').strip()
    if value and value != '{quality_gate_command}':
        return []
    return [finding(
        WARNING, 'quality-gate',
        '%s records no quality gate%s, so nothing checks a change before it is '
        'committed' % (path,
                       ' (the template placeholder is still there)'
                       if value else ''),
        "put the project's pre-commit command in the `## Quality Gate` fenced "
        'block', path)]


def claude_md_findings(exists, references_config, path='CLAUDE.md',
                       config='ClaudeProject.md'):
    """Whether a session that never runs a workflow command finds the config.

    `CLAUDE.md` is what a plain session reads. If it does not point at
    `ClaudeProject.md`, everything in there -- the branch convention, the
    quality gate, the board -- is invisible outside the slash commands.
    """
    if not exists:
        return [finding(
            WARNING, 'file-claude-md',
            'this project has no %s, so a session that runs no workflow command '
            'never sees %s' % (path, config),
            'add a %s that points at %s' % (path, config), path)]
    if references_config:
        return []
    return [finding(
        WARNING, 'claude-md-ref',
        '%s does not mention %s, so a session reading it alone does not know '
        'the project has one' % (path, config),
        'add a line to %s pointing at %s' % (path, config), path)]


def review_config_findings(referenced, exists, path='ClaudeProject.md'):
    """A review-state label file the config names and the repo does not have.

    Named but missing is the failure: every review-state label falls back to
    its `review-` default, so the labels a run applies are not the ones the
    project chose, and nothing says so.
    """
    if not referenced or exists:
        return []
    return [finding(
        WARNING, 'review-config',
        '%s points at `%s`, which is not there, so every review-state label '
        'falls back to its default name' % (path, referenced),
        'create `%s`, or drop the reference from %s' % (referenced, path),
        path)]


# What `--fix` will do, per check. A check absent from this map is one a run
# must not repair on its own -- either because the repair is a guess (which of
# two disagreeing values is right) or because it is not a repair at all (a
# missing `## Identity` section is a project nobody has configured).
#
# The reasons live here rather than at each call site so that `preflight`
# without `--fix` can tell a person, per finding, whether running it again with
# `--fix` would change anything.
FIXABLE_CHECKS = {
    'board-lane': 'create the missing column on the live board',
    'board-column': 'refresh the recorded option ids from the live board',
    'board-orphan': 'add the card and put it in `Backlog`',
    'board-unset': 'put the card in `Backlog`',
    'label-deprecated': 'delete the row from the label map',
    'label-retired': 'take the retired labels off the open issues carrying them',
    'board-retired': 'move any card still in the retired column to `Backlog`, '
                     'then remove the column',
    'config-retired': 'delete the section',
    'claude-md-ref': 'add the pointer to CLAUDE.md',
    'container-finished': 'close each finished container as completed and '
                          'move it to `Done`',
}

UNFIXABLE_REASONS = {
    'gh-auth': 'only the person at the keyboard can authenticate',
    'config-section': 'the section holds decisions no run can make for a project',
    'file-config': 'there is nothing to repair until the file exists',
    'file-claude-md': "writing a project's CLAUDE.md is the project's call",
    'board-title': 'the title and the node id disagree and either could be the '
                   'right one',
    'field-absent': 'an org-level issue field is created in the org settings, '
                    'not through the API this runs on',
    'field-absent-optional': 'an org-level issue field is created in the org '
                             'settings, not through the API this runs on',
    'field-unpinned': 'pinning a field to an issue type is done in the org '
                      'settings',
    'field-unmapped': "which purpose key a project's field serves is the "
                      "project's decision",
    'field-options': "renaming an org field's options moves every issue "
                     'carrying one, so it is the org\'s decision',
    'instructions-retired': 'the lines are somebody\'s own sentences, and an '
                            'automatic edit would either mangle the paragraph '
                            'or delete a line explaining the history on purpose',
    'label-reference': 'the fix is an edit to a plugin instruction file, not to '
                       'this project',
    'config-label': 'creating a label the config names would guess at its '
                    'colour and description',
    'label-drift': "which of two equivalent labels to keep is the project's "
                   'decision',
    'placeholders': "the replacement values are the project's to supply",
    'quality-gate': 'nobody but the project knows what its gate should run',
    'review-config': "the file's contents are the project's to choose",
    'pin-unknown': 'nothing is known to be wrong yet',
}


def fix_plan(findings):
    """Split findings into what `--fix` repairs and what it must not touch.

    Pure, so that "would this run change anything?" is answerable without a
    network call -- which is what makes `preflight` safe to run before every
    command and `preflight --fix` safe to run twice.
    """
    fixable, blocked = [], []
    for entry in findings or ():
        if entry.get('check') in FIXABLE_CHECKS:
            fixable.append(entry)
        else:
            blocked.append(entry)
    return fixable, blocked


def unfixable_reason(check):
    """Why `--fix` leaves this check alone. Falls back to a truthful blank."""
    return UNFIXABLE_REASONS.get(check, 'no automatic repair is defined for it')


# ── editing ClaudeProject.md in place ────────────────────────────────────────
# Three repairs rewrite the file. Each is a whole-section operation on the
# markdown rather than a line match, because a project is free to word the
# prose inside a section however it likes -- the heading is the only part the
# parser depends on, so the heading is the only part these may key on.

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*$')


def _section_bounds(lines, heading, level=2):
    """`(start, end)` line indices of a section, or `None`. End is exclusive."""
    want = _normalise_heading(heading)
    start = None
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        if start is None:
            if (len(match.group(1)) == level
                    and _normalise_heading(match.group(2)) == want):
                start = index
            continue
        if len(match.group(1)) <= level:
            return (start, index)
    if start is None:
        return None
    return (start, len(lines))


def strip_sections(text, headings, level=2):
    """Remove whole level-2 sections. Returns `(text, removed_names)`."""
    lines = (text or '').split('\n')
    removed = []
    for heading in headings or ():
        bounds = _section_bounds(lines, heading, level)
        if not bounds:
            continue
        start, end = bounds
        # Take the blank lines the section left behind with it, so removing a
        # section twice in a row cannot leave a growing gap.
        while end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]
        removed.append(heading)
    return '\n'.join(lines), removed


def strip_label_map_rows(text, labels):
    """Drop `## Label Map` table rows whose purpose key is in `labels`.

    Only rows inside that section, and only rows whose *first* cell matches --
    a project is free to mention a retired label in the prose, and prose is not
    a claim that the workflow applies it.
    """
    wanted = {l.strip().strip('`') for l in labels or () if l}
    if not wanted:
        return text, []
    lines = (text or '').split('\n')
    bounds = _section_bounds(lines, 'Label Map')
    if not bounds:
        return text, []
    start, end = bounds
    kept, removed = [], []
    for line in lines[start:end]:
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            cells = [c.strip().strip('`') for c in stripped.strip('|').split('|')]
            if cells and cells[0] in wanted:
                removed.append(cells[0])
                continue
        kept.append(line)
    if not removed:
        return text, []
    return '\n'.join(lines[:start] + kept + lines[end:]), removed


STATUS_OPTIONS_HEADING = 'Status Options'


def render_status_options(columns):
    """The `### Status Options` table, rebuilt from `{purpose key: option id}`.

    Written in the canonical column order rather than whatever order the live
    board returns, so the same board always produces the same table and a
    refresh that changes nothing changes nothing in the file either.
    """
    rows = ['| Column | Purpose Key | Option ID |',
            '| ------ | ----------- | --------- |']
    for purpose, name in BOARD_COLUMN_NAMES.items():
        option_id = (columns or {}).get(purpose)
        rows.append('| %s | `%s` | %s |'
                    % (name, purpose, '`%s`' % option_id if option_id else 'n/a'))
    return '\n'.join(rows)


def replace_status_options(text, columns):
    """Swap the table inside `### Status Options` for one built from `columns`.

    Returns `(text, changed)`. Only the table's own lines are replaced. The
    first version of this replaced the whole section, which ate the paragraphs
    a project had written around the table -- on the repository this plugin is
    developed in, four of them, including the one recording why `col-backlog`
    kept its old option id through a rename. A repair that destroys the
    project's own writing is not a repair.

    A section with no table is left alone, and so is a file with no section:
    the table is written by `setup`, and inventing one here would put a heading
    into a `## Project Board` section that may not exist either.
    """
    lines = (text or '').split('\n')
    bounds = _section_bounds(lines, STATUS_OPTIONS_HEADING, level=3)
    if not bounds:
        return text, False
    start, end = bounds
    first = next((i for i in range(start + 1, end)
                  if lines[i].strip().startswith('|')), None)
    if first is None:
        return text, False
    last = first
    while last + 1 < end and lines[last + 1].strip().startswith('|'):
        last += 1
    block = render_status_options(columns).split('\n')
    if lines[first:last + 1] == block:
        return text, False
    lines[first:last + 1] = block
    return '\n'.join(lines), True


CLAUDE_MD_POINTER = (
    'Project configuration -- org and repo, branch convention, quality gate, '
    'label map and project board -- lives in [`ClaudeProject.md`]'
    '(ClaudeProject.md). Read it before running a workflow command.')


def add_config_pointer(text, pointer=CLAUDE_MD_POINTER):
    """Append the `ClaudeProject.md` pointer to a CLAUDE.md that lacks one.

    Idempotent on the filename rather than on the sentence, so a project that
    worded its own pointer differently is left exactly as it is.
    """
    body = text or ''
    if 'ClaudeProject.md' in body:
        return body, False
    if body and not body.endswith('\n'):
        body += '\n'
    return body + ('\n' if body else '') + pointer + '\n', True
