"""
Issue audit: what an existing issue is missing or contradicts, and the spec
that would fix it.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

import re

from wf_core_fields import (
    MANDATORY_FIELD_KEYS, OPTIONAL_FIELD_KEYS, classification_conflicts,
    native_type_for, resolve_field_name, resolve_label,
)
from wf_core_refs import parse_parent
from wf_core_spec import (
    SPEC_PLACEHOLDER, _is_supplied, default_classification, hierarchy_error,
)
from wf_core_stage import (
    OWNERSHIP_FIELD_OPTIONS, is_area_stage, scope_findings, scope_from_title,
)


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


def _field_values(issue):
    """The field values an issue carries, by field name."""
    have = {}
    for node in (issue.get('issueFieldValues') or {}).get('nodes') or []:
        if not isinstance(node, dict):
            continue
        name = (node.get('field') or {}).get('name')
        if not name:
            continue
        if 'options' in node:
            have[name] = sorted(o['name'] for o in node.get('options') or [])
        elif 'name' in node:
            have[name] = node.get('name')
        else:
            have[name] = node.get('value')
    return have


def area_chain_map(issues, project_fields=None):
    """{number: (parent number, stage, type)} for every scanned issue.

    What `audit_issue` walks to find an issue's area: the nearest area epic
    above it. Built once from the open issues a scan read, so the walk costs
    no round trip; a parent the scan did not read is simply absent.
    """
    stage_field = resolve_field_name('field-stage', project_fields or {})
    out = {}
    for issue in issues or ():
        number = issue.get('number')
        if number is None:
            continue
        out[number] = ((issue.get('parent') or {}).get('number'),
                       _field_values(issue).get(stage_field),
                       (issue.get('issueType') or {}).get('name'))
    return out


def resolves_to_no_area(number, chain):
    """Whether an issue's parent chain, read in full, reaches no area epic.

    `chain` is `area_chain_map`'s output. True only when every step is known
    and the chain ends at an issue with no parent. A parent outside the map
    (closed, in another repository, or past a `--limit`) is unknown, and an
    unknown is not reported as a gap: the audit does not guess.
    """
    if number not in chain:
        return False
    seen, current = set(), number
    while current not in seen:
        seen.add(current)
        entry = chain.get(current)
        if entry is None:
            return False
        parent, stage, _ = entry
        if is_area_stage(stage):
            return False
        if parent is None:
            return True
        current = parent
    return False


def audit_issue(issue, field_map, type_capable=True, project_map=None,
                project_fields=None, open_numbers=None, type_map=None,
                parents=False, chain=None):
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

    An area epic (`Stage` is `Area`) is exempt from every field and ownership
    gap: it is a permanent part of the product rather than work, so nothing
    ranks, sizes or routes it. `chain` is `area_chain_map` over the scanned
    issues; with it, an open issue whose parent chain reaches no area epic is a
    `no-area` gap, and nothing is proposed for it, because which area an issue
    belongs to is a judgement about the product.

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
    have = _field_values(issue)
    area = is_area_stage(have.get(resolve_field_name('field-stage', project_fields)))

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
    # The other fields an org defines — a date, a free-text parent — are
    # situational, and the backfill has never proposed a value for
    # one. Reporting them anyway made every issue in a fully classified backlog
    # come back as "missing metadata": 275 findings across 69 issues on one real
    # repo, every one of them a field nobody was ever going to fill. An audit
    # that cannot come back clean cannot be used as a check, which is what it is
    # for.
    proposed_fields = {}
    for purpose in () if area else MANDATORY_FIELD_KEYS + OPTIONAL_FIELD_KEYS:
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
    if owner_field in field_map and not area:
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

    # Which permanent part of the product this issue belongs to: the nearest
    # area epic above it. Reported and never proposed, like the tree above.
    if chain is not None and not area and resolves_to_no_area(number, chain):
        gaps.append({'kind': 'no-area',
                     'detail': 'no area epic above it, so it belongs to no part '
                               'of the product and its release notes cannot be '
                               'grouped; file it under a Feature or an area epic'})

    # No title: an update now writes the title it is given, and the one read
    # here would strip a prefix or undo an edit made after the audit.
    proposed = {'number': number}
    if area:
        # So the entry validates without the fields work carries: an area
        # epic is exempt, and `issue-apply` knows one by this state.
        proposed['state'] = 'area'
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
