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

import re

# ── Story selection ──────────────────────────────────────────────────────────
# The local, no-API filter + sort — the claim/validate loop around it lives
# in wf.py. This module is the only encoding of these rules.

_PRIORITY_ORDER = ['priority-critical', 'priority-high', 'priority-medium', 'priority-low']


def _priority_rank(labels, project_map=None):
    """Returns sort key: 0=critical … 3=low, 4=no priority label.

    Priority labels are matched through the project map (`resolve_label`), so a
    project that renames `priority-high` → `P1` still sorts correctly instead of
    treating every issue as unprioritised.
    """
    project_map = project_map or {}
    for i, key in enumerate(_PRIORITY_ORDER):
        if resolve_label(key, project_map) in labels:
            return i
    return len(_PRIORITY_ORDER)


def _filter_by_mode(candidates, mode, project_map=None):
    """Apply mode filter (label path — non-type-capable orgs).

    story       — no type filter; all issues are eligible.
    feature     — keep type-story issues only.
    maintenance — keep bug / security / debt / architecture issues only.

    This is the `type-*` **label** path, matched through the project map so a
    project that renames the type labels is filtered correctly. On a type-capable
    org the caller passes a `type_map` to `select_pool` instead, which routes
    through `filter_by_native_type` and never reaches this function.
    """
    if mode == 'story':
        return list(candidates)
    project_map = project_map or {}
    feature_keys = {'type-story'}
    maintenance_keys = {'type-bug', 'type-security', 'type-debt', 'type-arch'}
    keys = feature_keys if mode == 'feature' else maintenance_keys
    keep = {resolve_label(k, project_map) for k in keys}
    return [c for c in candidates if any(lbl in keep for lbl in c.get('labels', []))]


# ── Native issue type filtering (type-capable orgs) ────────────────────────
# When the org has native GitHub issue types, the authoritative classification
# is the issueType field, not the type-* label. The type_map is built from a
# single GraphQL query in wf.py and passed through select_pool.
#
# Native type map (from templates/default-labels.md):
#   feature mode  → keep User Story
#   maintenance   → keep Bug + Feature (with Classification filter if available)

NATIVE_FEATURE_TYPES = frozenset({'User Story'})
NATIVE_MAINTENANCE_TYPES = frozenset({'Bug'})
NATIVE_MAINTENANCE_CLASSIFIABLE_TYPES = frozenset({'Feature'})
MAINTENANCE_CLASSIFICATIONS = frozenset({
    'Tech Debt', 'Architecture', 'Security',
})


def filter_by_native_type(candidates, mode, type_map, classification_map=None):
    """Filter candidates by native issue type (type-capable orgs).

    feature mode: keep only User Story.
    maintenance mode: keep Bug unconditionally, plus Feature when the
    Classification field indicates tech debt / architecture / security.
    When classification_map is unavailable (None), all Feature-typed
    candidates are included as a best-effort fallback.
    story mode: no filter (returns all).
    """
    if mode == 'story':
        return list(candidates)
    result = []
    for c in candidates:
        native_type = type_map.get(c['number'])
        if not native_type:
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
                elif classification_map.get(c['number']) in MAINTENANCE_CLASSIFICATIONS:
                    result.append(c)
    return result


def _filter_refinement(candidates, project_map=None):
    """Exclude issues that carry needs-refinement — not yet ready for pickup."""
    needs = resolve_label('needs-refinement', project_map or {})
    return [c for c in candidates if needs not in c.get('labels', [])]


def _filter_agent_gating(candidates, agent_gating, project_map=None):
    """If gating is enabled, keep only human-approved (claude-ready) issues."""
    if agent_gating != 'enabled':
        return list(candidates)
    ready = resolve_label('claude-ready', project_map or {})
    return [c for c in candidates if ready in c.get('labels', [])]


def _sort_candidates(candidates, project_map=None):
    """Sort by priority descending (critical first), then ascending issue number."""
    return sorted(candidates,
                  key=lambda c: (_priority_rank(c.get('labels', []), project_map), c['number']))


def select_story(candidates, mode='story', agent_gating='disabled', project_map=None):
    """Full selection pipeline: filter → sort → top candidate (or None).

    Returns the single best candidate, never a list — the caller claims it.
    The claim-first/validate-lazily loop in wf.py walks the *sorted* pool when
    a claim is lost or a candidate proves blocked, so this returns the ordered
    survivors via `select_pool`; `select_story` is the convenience head.
    """
    pool = select_pool(candidates, mode, agent_gating, project_map)
    return pool[0] if pool else None


def select_pool(candidates, mode='story', agent_gating='disabled', project_map=None,
                type_map=None, classification_map=None):
    """The ordered, filtered candidate list (best first). Empty list if none.

    `project_map` is the ClaudeProject.md label map; every label the filters and
    the priority sort key on is resolved through it (`resolve_label`) so the fast
    path resolves purpose keys the same way everywhere rather than diverging
    on a project that renames labels. Defaults to `{}` so
    a default-labelled project (and the offline tests) need not pass it.

    `type_map`, when provided, activates native-type filtering (type-capable
    orgs): a dict of ``{issue_number: native_type_name}`` built from a GraphQL
    query. When set, mode filtering uses ``filter_by_native_type`` instead of
    the label-based ``_filter_by_mode``. `classification_map` is an optional
    companion dict of ``{issue_number: classification_option_name}`` for
    refining Feature-typed issues in maintenance mode.
    """
    if type_map and mode != 'story':
        pool = filter_by_native_type(candidates, mode, type_map, classification_map)
    else:
        pool = _filter_by_mode(candidates, mode, project_map)
    pool = _filter_refinement(pool, project_map)
    pool = _filter_agent_gating(pool, agent_gating, project_map)
    return _sort_candidates(pool, project_map)


# ── Label resolution ─────────────────────────────────────────────────────────
# github-workflow/templates/default-labels.md — "The single resolution path".

_DEFAULT_LABELS = {
    'type-story': 'type-story',
    'type-bug': 'type-bug',
    'type-security': 'type-security',
    'type-debt': 'type-debt',
    'type-arch': 'type-arch',
    'priority-critical': 'priority-critical',
    'priority-high': 'priority-high',
    'priority-medium': 'priority-medium',
    'priority-low': 'priority-low',
    'claude-ready': 'claude-ready',
    'claude-authored': 'claude-authored',
    'status-ready': 'status-ready',
    'needs-refinement': 'needs-refinement',
    'status-in-progress': 'status-in-progress',
    'status-parked': 'status-parked',
    'status-blocked': 'status-blocked',
    'status-in-review': 'status-in-review',
    'status-needs-attention': 'status-needs-attention',
}

# Lifecycle labels are mutually exclusive — exactly one is present at a time.
# The claim marker removes whichever of these the issue currently carries.
LIFECYCLE_KEYS = [
    'status-ready', 'needs-refinement', 'status-in-progress',
    'status-parked', 'status-blocked', 'status-in-review', 'status-needs-attention',
]


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


def current_lifecycle_label(labels, project_map):
    """Return the concrete lifecycle label currently on the issue, or None.

    Used to build the `--remove-label` argument when applying the
    status-in-progress marker, so exactly one lifecycle label remains.
    """
    concrete = {resolve_label(k, project_map): k for k in LIFECYCLE_KEYS}
    for name in labels:
        if name in concrete:
            return name
    return None


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
# label used as the fallback on an org without native types.
#
# The Classification entry is the default "by nature" choice, not the only
# valid one. For a bug, prefer `Regression` when something previously worked
# and broke, or `Performance` when the defect is speed or memory. For a
# feature, prefer `Enhancement` when it improves something existing,
# `Integration` when the work is connecting to an external system,
# `Documentation` when it tracks docs only, or `Performance` when speed is the
# point.
NATIVE_TYPE_MAP = {
    'story':        {'type': 'User Story', 'classification': 'New Feature',  'label': 'type-story'},
    'bug':          {'type': 'Bug',        'classification': 'Bug Fix',      'label': 'type-bug'},
    'security':     {'type': 'Bug',        'classification': 'Security',     'label': 'type-security'},
    'tech debt':    {'type': 'Feature',    'classification': 'Tech Debt',    'label': 'type-debt'},
    'architecture': {'type': 'Feature',    'classification': 'Architecture', 'label': 'type-arch'},
    'feature':      {'type': 'Feature',    'classification': 'New Feature',  'label': 'type-story'},
    'epic':         {'type': 'Epic',       'classification': 'New Feature',  'label': 'type-story'},
    'spike':        {'type': 'User Story', 'classification': 'Spike',        'label': 'type-story'},
    'chore':        {'type': 'User Story', 'classification': 'Chore',        'label': 'type-bug'},
}

# Every valid `Classification` option. A value outside this set is a spec
# error, not a new option — the org owns the field, and adding to it is a
# deliberate org-level change.
CLASSIFICATION_OPTIONS = (
    'New Feature', 'Enhancement', 'Bug Fix', 'Regression', 'Performance',
    'Security', 'Tech Debt', 'Architecture', 'Integration', 'Spike', 'Chore',
    'Documentation', 'Accessibility',
)

# Purpose key → default org field name, and the field's data type. The data
# type decides which mutation shape a value needs, so it belongs next to the
# name rather than being re-derived from the live schema every time.
FIELD_NAME_DEFAULTS = {
    'field-priority':      'Priority',
    'field-effort':        'Effort',
    'field-type':          'Classification',
    'field-origin':        'Origin',
    'field-start':         'Start date',
    'field-target':        'Target date',
    'field-parent':        'Parent',
    'field-status-reason': 'Status reason',
}

FIELD_DATA_TYPES = {
    'field-priority':      'single-select',
    'field-effort':        'single-select',
    'field-type':          'multi-select',
    'field-origin':        'single-select',
    'field-start':         'date',
    'field-target':        'date',
    'field-parent':        'text',
    'field-status-reason': 'text',
}

# The four fields the tooling sets on every issue it creates. Preflight checks
# that every enabled issue type is pinned to all of them, because a value
# written to an unpinned field is stored and then never shown.
MANDATORY_FIELD_KEYS = ('field-priority', 'field-effort', 'field-type', 'field-origin')

# `priority-*` label purpose → `Priority` field option. Priority is
# dual-tracked: the label drives selection ordering, the field drives the
# portal's own views.
PRIORITY_FIELD_OPTIONS = {
    'priority-critical': 'Urgent',
    'priority-high':     'High',
    'priority-medium':   'Medium',
    'priority-low':      'Low',
}

# Story size estimate → `Effort` field option.
EFFORT_FIELD_OPTIONS = {
    'large':  'High',
    'medium': 'Medium',
    'small':  'Low',
}

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
                 in_progress_label=None, review_labels=(), has_open_pr=False):
    """Decide what to do with one claim ref. Returns (verdict, reason).

    `kind` is 'issue' or 'pr'; `state` is GitHub's own state string (OPEN /
    CLOSED / MERGED) or None when it could not be read.

    An issue claim is reaped when the issue is closed, when its lifecycle
    label has moved off in-progress, or when a PR is already open for it (the
    post-create release did not run). It is suspect when the issue is still
    in-progress with no PR: that is exactly what a slow but healthy session
    looks like.

    A PR claim is reaped when the PR is closed or merged, or when it is open
    but carries no active review-state label. It is suspect while a review is
    genuinely in flight.
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
        if in_progress_label and in_progress_label not in names:
            return REAP, 'the issue is no longer marked in progress'
        if has_open_pr:
            return REAP, 'a PR is already open for the issue'
        return SUSPECT, 'the issue is still in progress with no PR open'

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
BOARD_COLUMN_NAMES = {
    'col-backlog':     'Todo',
    'col-ready':       'Ready',
    'col-in-progress': 'In Progress',
    'col-in-review':   'In Review',
    'col-blocked':     'Blocked',
    'col-done':        'Done',
}


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


def resolve_entry_type(entry):
    """The native issue type an entry asks for, or None. (type_name, err)."""
    if entry.get('type'):
        return entry['type'], None
    kind = entry.get('kind')
    if not kind:
        return None, None
    mapped = NATIVE_TYPE_MAP.get(str(kind).lower())
    if not mapped:
        return None, "unknown kind '%s' (expected one of: %s)" % (
            kind, ', '.join(sorted(NATIVE_TYPE_MAP)))
    return mapped['type'], None


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

    A field the org does not define is skipped, not an error: an org is allowed
    to have fewer fields. A field the org *does* define, that the spec leaves
    empty, is an error — that is the blank-metadata failure this command exists
    to stop.
    """
    project_fields = project_fields or {}
    mandatory_keys = mandatory_keys or MANDATORY_FIELD_KEYS
    errors, skipped, plans = [], set(), []

    seen_keys, seen_numbers = set(), set()

    for entry in entries:
        name = entry_label(entry)
        plan = {'entry': entry, 'type': None, 'fields': {}, 'errors': []}

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

        # Native type.
        type_name, err = resolve_entry_type(entry)
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
                continue  # the org does not define it; nothing to require
            if not _is_supplied(wanted.get(purpose)):
                errors.append("%s: missing a value for '%s' (%s), which this org "
                              'defines and every issue must carry'
                              % (name, concrete, purpose))

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

        plans.append(plan)

    return errors, skipped, plans


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


def infer_priority(labels, project_map=None):
    """The Priority value the issue's own `priority-*` label implies."""
    present = set(labels or ())
    for key, value in PRIORITY_FIELD_OPTIONS.items():
        if resolve_label(key, project_map or {}) in present:
            return value
    return None


def audit_issue(issue, field_map, type_capable=True, project_map=None,
                project_fields=None, open_numbers=None):
    """Every gap on one issue, plus the spec entry that would close them.

    `issue` is a read-back node. Returns a dict carrying `gaps` (each with a
    `kind` and a human-readable `detail`) and `proposed`, an `issue-apply` spec
    entry. Values the audit cannot infer are `SPEC_PLACEHOLDER`, so
    `validate_spec()` refuses the spec until a person fills them in — silence
    must not pass for a value.

    Dependency edges are **proposed, never written**. Body prose is not
    reliable enough to build a dependency graph from unattended, so a missing
    edge lands in the spec for review rather than in a mutation.
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
        expected = NATIVE_TYPE_MAP[kind]['type']
        if native != expected:
            gaps.append({'kind': 'type-contradiction',
                         'detail': "native type is '%s' but the %s says '%s', "
                                   "which is '%s'" % (native, source, kind, expected)})

    # Field values. Every field the org defines is checked, because a field
    # nobody fills is indistinguishable from one nobody needed until someone
    # looks.
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
        expected = (default_classification({'kind': kind}) or [None])[0]
        if _is_supplied(current) and expected:
            values = current if isinstance(current, list) else [current]
            if expected not in values:
                gaps.append({'kind': 'classification-contradiction',
                             'detail': "%s is %r but the %s says '%s', which is "
                                       "'%s'" % (class_name, current, source,
                                                 kind, expected)})

    proposed_fields = {}
    for purpose in FIELD_NAME_DEFAULTS:
        concrete = resolve_field_name(purpose, project_fields)
        if concrete not in field_map:
            continue
        if _is_supplied(have.get(concrete)):
            continue
        gaps.append({'kind': 'missing-field',
                     'detail': "no value for '%s'" % concrete})
        if purpose not in MANDATORY_FIELD_KEYS:
            # Situational by nature — a start date nobody set is not a gap the
            # backfill should invent a value for.
            continue
        if purpose == 'field-type' and kind:
            proposed_fields[purpose] = default_classification({'kind': kind})
        elif purpose == 'field-priority':
            proposed_fields[purpose] = (infer_priority(labels, project_map)
                                        or SPEC_PLACEHOLDER)
        else:
            proposed_fields[purpose] = SPEC_PLACEHOLDER

    # Dependency edges the body claims and the graph does not have.
    deps, overflow = parse_dependencies(issue.get('body'))
    native_edges = {n['number'] for n
                    in (issue.get('blockedBy') or {}).get('nodes') or []}
    proposed_edges = []
    for dep in deps:
        if dep == number or dep in native_edges:
            continue
        if open_numbers is not None and dep not in open_numbers:
            # Worth saying, not worth proposing: an edge to a closed issue
            # would be applied and then immediately be inert.
            gaps.append({'kind': 'dependency-closed',
                         'detail': 'the body depends on #%s, which is not open' % dep})
            continue
        gaps.append({'kind': 'missing-edge',
                     'detail': 'the body depends on #%s with no native edge' % dep})
        proposed_edges.append(dep)
    if overflow:
        gaps.append({'kind': 'dependency-overflow',
                     'detail': 'more than %d dependencies in the body; not '
                               'proposed automatically' % DEP_LIMIT})

    proposed = {'number': number, 'title': title}
    if kind:
        proposed['kind'] = kind
    if proposed_fields:
        proposed['fields'] = proposed_fields
    if proposed_edges:
        proposed['blocked_by'] = sorted(proposed_edges)
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


def _drift_key(name):
    """A label name with every separator flattened, for near-miss grouping."""
    return re.sub(r'[\s:_/]+', '-', (name or '').strip().lower())


def label_drift_findings(live_labels, project_map=None):
    """Two live labels that plainly mean the same thing.

    Two shapes, both seen in the wild: a separator that drifted
    (`priority:medium` beside `priority-medium`), and a prefix that was dropped
    (`bug` beside `type-bug`). Neither breaks a command, so both warn — but each
    one silently splits a backlog in half, because selection matches one name
    and some of the issues carry the other.
    """
    live = sorted(set(live_labels or ()))
    out = []

    grouped = {}
    for name in live:
        grouped.setdefault(_drift_key(name), []).append(name)
    for names in sorted(grouped.values()):
        if len(names) < 2:
            continue
        out.append(finding(
            WARNING, 'label-drift',
            '%s differ only in punctuation, so issues carrying one are invisible '
            'to a query for the other' % _names(names),
            'move every issue onto one of them and delete the rest'))

    present = set(live)
    for purpose in sorted(_DEFAULT_LABELS):
        name = resolve_label(purpose, project_map or {})
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

    Asymmetry between types is a separate and softer matter: `Epic` is not
    pinned to `Parent` on purpose, because an epic is the parent. So a field
    some enabled types carry and others do not is a warning, and only the
    fields the tooling actually writes are ever a failure.
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
            'field should not pin it, which is why `Epic` correctly does not '
            'pin `Parent`: an epic is the parent'))
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
    """Board columns recorded in config that no longer resolve on the board.

    `columns` is `{purpose key: option id}`, `live_options` is
    `{option id: name}`. A stale id means the move is skipped, not that the
    issue is lost — the lifecycle labels stay authoritative — so this warns.
    """
    live = live_options or {}
    out = []
    for purpose, option_id in sorted((columns or {}).items()):
        if option_id in live:
            continue
        out.append(finding(
            WARNING, 'board-column',
            '`%s` is recorded as option `%s`, which the board no longer has, so '
            'that move is skipped' % (purpose, option_id),
            'refresh the `### Status Options` table from the live board',
            path))
    return out


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


# ── Dependency parsing ───────────────────────────────────────────────────────
# Story validation — fixed patterns, no judgment.

_DEP_LINE_PATTERNS = [
    re.compile(r'\bdepends on\s+#(\d+)', re.IGNORECASE),
    re.compile(r'\bblocked by\s+#(\d+)', re.IGNORECASE),
    re.compile(r'\bafter\s+#(\d+)', re.IGNORECASE),
    re.compile(r'\brequires\s+#(\d+)', re.IGNORECASE),
]
_DEP_SECTION_RE = re.compile(
    r'^#{1,6}\s*dependencies\s*$(.*?)(?=^#{1,6}\s|\Z)',
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_HASH_REF_RE = re.compile(r'#(\d+)')
DEP_LIMIT = 5


def parse_dependencies(body):
    """Extract dependency issue numbers from an issue body.

    Recognises the fixed markers `Depends on #N`, `Blocked by #N`, `After #N`,
    `Requires #N`, and bare `#N` references inside a `## Dependencies` section.
    Self-references and duplicates are dropped.

    Returns (deps, overflow):
      deps     — sorted unique list of referenced issue numbers (ints).
      overflow — True if more than DEP_LIMIT distinct deps were found. Per the
                 template, that many references means a meta/epic issue whose
                 dependencies cannot be cheaply validated, so the caller treats
                 it as unresolved rather than checking each one.
    """
    body = body or ''
    found = set()
    for pat in _DEP_LINE_PATTERNS:
        for m in pat.finditer(body):
            found.add(int(m.group(1)))
    section = _DEP_SECTION_RE.search(body)
    if section:
        for m in _HASH_REF_RE.finditer(section.group(1)):
            found.add(int(m.group(1)))
    deps = sorted(found)
    return deps, len(deps) > DEP_LIMIT


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


def plan_bulk_order(stories, max_size=BULK_MAX):
    """Trim a proposed bulk set to size and put it in build order.

    `stories` is the proposed set in preference order, **lead first** — dicts
    carrying `number` and `body`. Two passes:

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
        parsed, _overflow = parse_dependencies(story.get('body'))
        deps_in_set[story['number']] = {d for d in parsed
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
