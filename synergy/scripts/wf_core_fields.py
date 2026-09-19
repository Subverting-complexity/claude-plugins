"""
Label resolution, native issue types and the org issue field vocabularies
(names, options, ranks).

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

from wf_core_findings import _drift_key, _names


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


# ── Label resolution ─────────────────────────────────────────────────────────
# The workflow puts no label on an issue, and none on a pull request except the
# review-state labels, which resolve through `REVIEW_DEFAULT_LABELS` below. The
# `claude-authored` marker went in 13.2.0 (#275): it recorded who built a
# change, which the PR's author and commits already say, and it decided
# nothing. A project map that still names labels keeps resolving through
# `resolve_label`, so an older `## Label Map` is read rather than broken.
#
# `type-*` is absent for the same reason. The names survive in
# `TYPE_LABEL_KINDS` only so the write path can recognise and remove them.
_DEFAULT_LABELS = {}

# Every label that used to answer a question the structured fields now answer.
# They are kept here, and nowhere else, so the write path can recognise one on
# an existing issue and take it off -- and so `deprecated_label_findings` can
# name a project still carrying them. Nothing reads one to make a decision.
#
# `status-*` and `needs-refinement` said what state an issue was in. The
# `Stage` issue field says it now, and says it once: a label and a stage are
# two records of one fact, and they disagreed often enough that `wf unblock`
# had to be written to reconcile them. `Stage` holds one value, so there is
# nothing left to reconcile.
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
# what got picked. Approval is the issue's `Stage` now: a person approves an
# issue by leaving it blank or setting Backlog, and withholds approval with
# Needs refinement or Parked. That is the same answer in the place every other state
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

    Resolution order:
    1. Project map (a `## Label Map` in ClaudeProject.md, where one survives).
    2. `defaults`, when the caller passes a table (`RETIRED_LABELS`).
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
#
# The area options say which part of the system the work touches, not what
# kind of change it is, so one is only ever set beside a kind value. Maintenance
# mode picks a `Feature` by its kind value, and a `Feature` tagged only
# `Back end` would be left out of the pool. An org may define none of them.
AREA_CLASSIFICATION_OPTIONS = (
    'Front end', 'Back end', 'API', 'Database', 'Mobile', 'Infrastructure',
    'Build and deploy', 'Testing',
)

CLASSIFICATION_OPTIONS = (
    'New Feature', 'Enhancement', 'Bug Fix', 'Regression', 'Performance',
    'Security', 'Tech Debt', 'Architecture', 'Integration', 'Spike', 'Chore',
    'Documentation', 'Accessibility',
) + AREA_CLASSIFICATION_OPTIONS

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
    'field-stage':         'Stage',
}

FIELD_DATA_TYPES = {
    'field-priority':      'single-select',
    'field-effort':        'single-select',
    'field-ownership':     'single-select',
    'field-type':          'multi-select',
    'field-origin':        'single-select',
    'field-stage':         'single-select',
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
# There is a fourth answer and it is deliberately not required: **state**, the
# `Stage` field. A blank `Stage` means available, so an issue nobody has
# decided anything about is already in a state. The plugin writes `Stage` on
# every transition it makes, and `config-audit` fails when the org does not
# define the field (`stage-absent`) or lacks an option a transition writes
# (`stage-options`).
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
    'pr-review':         'Code Review',
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
