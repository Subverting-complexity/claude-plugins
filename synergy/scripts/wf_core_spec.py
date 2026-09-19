"""
Issue specs: the epic, feature and story hierarchy, spec validation, value
shaping and batching.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

from wf_core_fields import (
    AREA_CLASSIFICATION_OPTIONS, MANDATORY_FIELD_KEYS, NATIVE_TYPE_MAP,
    NEVER_WRITTEN_FIELD_KEYS, OPTIONAL_FIELD_KEYS, native_type_for, resolve_field_name,
)
from wf_core_stage import (
    AREA_STAGE, OWNERSHIP_FIELD_OPTIONS, SCOPE_CODE, SCOPE_PREFIXES,
    ownership_scope, scope_from_title, spec_state_stage,
)

# The only native type an area epic may be. An area groups Features and the
# Bugs and Chores filed straight under it, which is what an `Epic` already is.
AREA_TYPE = 'Epic'


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
        if plan.get('state') == AREA_STAGE and plan.get('type') is None:
            # An update asking for `area` without restating its type is judged
            # by the type the issue already carries. `validate_spec` has
            # already refused a create with no type, and an explicit one.
            own = as_number(entry.get('number'))
            live_type = issue_types.get(own) if own is not None else None
            if live_type != AREA_TYPE:
                errors.append("%s: asks for `\"state\": \"area\"` but is %s, and "
                              'only an `%s` can be an area epic'
                              % (entry_label(entry),
                                 "a '%s'" % live_type if live_type else 'untyped',
                                 AREA_TYPE))
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


def settle_classification_areas(entry, value, field_name, field_meta):
    """The `field-type` value to write once its area values are settled.

    Returns (value, notes, err). The Classification field holds two kinds of
    value: what kind of change the work is, and which areas of the system it
    touches (`AREA_CLASSIFICATION_OPTIONS`). An issue tagged only with areas is
    left out of maintenance mode, which picks by the kind value, so:

    - a list of areas alone gains the kind's default value when the entry has a
      `kind`, and is refused when it has none, since nothing says what kind of
      change it is;
    - an area the org's field does not define is dropped with a note, because
      an org without area options should file issues as it did before areas
      existed. Any other value the org does not define is left for
      `field_value_input` to refuse.
    """
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    notes = []
    if values and all(v in AREA_CLASSIFICATION_OPTIONS for v in values):
        implied = default_classification(entry)
        if not implied:
            return None, notes, (
                "'%s' names only areas (%s) and the entry has no `kind` to say "
                "what kind of change it is; add a value such as 'Bug Fix' or "
                "'New Feature' beside them" % (field_name, ', '.join(values)))
        values = implied + values
        notes.append("'%s' named only areas, so the kind's default '%s' was "
                     'added beside them' % (field_name, implied[0]))
    options = field_meta.get('options') or {}
    undefined = [v for v in values
                 if v in AREA_CLASSIFICATION_OPTIONS and v not in options]
    if undefined:
        values = [v for v in values if v not in undefined]
        notes.append("dropped %s: this org's '%s' field does not define %s"
                     % (', '.join("'%s'" % v for v in undefined), field_name,
                        'that area' if len(undefined) == 1 else 'those areas'))
    if not notes:
        return value, notes, None
    return values, notes, None


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

        # The stage the entry asks for, when it asks for one at all.
        state_stage, err = spec_state_stage(entry.get('state'))
        if err:
            errors.append('%s: %s' % (name, err))
        plan['state'] = state_stage
        # An area epic is a permanent part of the product, not work: nothing
        # ranks, sizes or routes it, so it carries none of the fields work must.
        is_area = state_stage == AREA_STAGE

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
        if is_area and not err:
            if type_name and type_name != AREA_TYPE:
                errors.append("%s: asks for `\"state\": \"area\"` but is a '%s', "
                              'and only an `%s` can be an area epic'
                              % (name, type_name, AREA_TYPE))
            elif not type_name and not entry.get('number'):
                errors.append("%s: asks for `\"state\": \"area\"` with no type; "
                              'an area epic is an `%s`, so add `"type": "%s"`'
                              % (name, AREA_TYPE, AREA_TYPE))

        # Field values, including the ones the entry did not name but must.
        wanted = dict(entry.get('fields') or {})
        if 'field-type' not in wanted:
            implied = default_classification(entry)
            if implied:
                wanted['field-type'] = implied

        # Area values in `field-type`, settled before the value is shaped.
        # Only when the org has the field: a field it lacks is skipped below.
        plan['notes'] = []
        type_field = resolve_field_name('field-type', project_fields)
        type_meta = field_map.get(type_field)
        if type_meta is not None and _is_supplied(wanted.get('field-type')):
            settled, notes, err = settle_classification_areas(
                entry, wanted['field-type'], type_field, type_meta)
            plan['notes'].extend('%s: %s' % (name, n) for n in notes)
            if err:
                errors.append('%s: %s' % (name, err))
                wanted.pop('field-type')
            else:
                wanted['field-type'] = settled

        # A release script stamps these, never the workflow.
        for purpose in NEVER_WRITTEN_FIELD_KEYS:
            if purpose in wanted:
                errors.append("%s: '%s' (%s) is set by the project's release "
                              'script, never by a spec; remove it'
                              % (name, resolve_field_name(purpose, project_fields),
                                 purpose))
                wanted.pop(purpose)

        for purpose in () if is_area else mandatory_keys:
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
        plan['unset_optional'] = [] if is_area else sorted(
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

    Every reference is resolved to the entry it names before the walk, so a
    cycle is found however each side spells the other: a `key`, a number, or
    the number as a digit string. Keyed on the reference as written, an entry
    `{"number": 12, "blocked_by": ["a"]}` and `{"key": "a", "blocked_by":
    ["12"]}` were two nodes that never met, and the cycle was applied.
    """
    index = {}
    for position, entry in enumerate(entries):
        for ref in _entry_refs(entry):
            index.setdefault(ref, position)

    def resolve(ref):
        if ref in index:
            return index[ref]
        if isinstance(ref, int):
            return index.get(str(ref))
        if isinstance(ref, str) and ref.strip().isdigit():
            return index.get(int(ref.strip()))
        return None

    graph, label = {}, {}
    for position, entry in enumerate(entries):
        ref = entry.get('key') or entry.get('number')
        if ref is None:
            continue
        label[position] = ref
        # A reference that resolves to nothing points outside the spec, which
        # is not this command's problem.
        graph[position] = [p for p in (resolve(d) for d in entry.get('blocked_by') or [])
                           if p is not None]

    cycles, state = [], {}

    def walk(node, stack):
        state[node] = 'open'
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue
            if state.get(nxt) == 'open':
                cycles.append([label[p] for p in stack[stack.index(nxt):] + [nxt]])
            elif state.get(nxt) is None:
                walk(nxt, stack)
        stack.pop()
        state[node] = 'done'

    for node in graph:
        if state.get(node) is None:
            walk(node, [])
    return cycles


def unparented_creates(entries):
    """The entries this spec creates whose parent chain ends with no parent.

    Each such issue resolves to no area, because an issue's area is the nearest
    area epic above it. Walked within the spec only: a chain that reaches an
    existing issue (a number, or an entry that updates one) is trusted rather
    than read, and one that reaches an entry asking for `"state": "area"` has
    found its area. A reference that names nothing is left to the checks that
    refuse it. Call before anything is created, while a create still has no
    number. Returns the entries, in spec order.
    """
    by_ref = {}
    for entry in entries or ():
        for ref in _entry_refs(entry):
            by_ref[ref] = entry

    def ends_unparented(entry):
        seen, current = set(), entry
        while id(current) not in seen:
            seen.add(id(current))
            if spec_state_stage(current.get('state'))[0] == AREA_STAGE:
                return False
            if current is not entry and current.get('number') is not None:
                return False
            ref = current.get('parent')
            if ref is None:
                return True
            nxt = by_ref.get(ref)
            if nxt is None and isinstance(ref, str) and ref.strip().isdigit():
                nxt = by_ref.get(int(ref.strip()))
            if nxt is None:
                return False
            current = nxt
        return False

    return [e for e in entries or ()
            if e.get('number') is None and ends_unparented(e)]
