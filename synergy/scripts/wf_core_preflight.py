"""
Preflight findings about configuration: config sections, label and field drift,
instruction files.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

import re

from wf_core_audit import TYPE_LABEL_KINDS
from wf_core_fields import (
    EFFORT_RANK, MANDATORY_FIELD_KEYS, OPTIONAL_FIELD_KEYS,
    PRIORITY_FIELD_RANK, RETIRED_LABELS, field_purpose_for_name,
    resolve_field_name, resolve_label, retired_label_variants,
)
from wf_core_findings import (
    CRITICAL, WARNING, _drift_key, _names, _normalise_heading, finding,
)
from wf_core_review import missing_review_labels
from wf_core_stage import OWNERSHIP_FIELD_OPTIONS, STAGE_NAMES


# Every section of `ClaudeProject.md` the plugin reads. A project missing one
# does not get a smaller feature set; it gets the default silently, which is how
# an entire classification scheme went unapplied without an error.
REQUIRED_CONFIG_SECTIONS = (
    'Identity',
    'Package Manager',
    'Quality Gate',
    'Branch Convention',
    'Issue Types & Fields',
)

_SECTION_FIXES = {
    'Issue Types & Fields': (
        "run `/synergy:setup` to write it from the org's live issue "
        'types and fields, or copy the section from '
        '`synergy/templates/ClaudeProject.md`'),
}
_SECTION_FIX_DEFAULT = ('copy the section from '
                        '`synergy/templates/ClaudeProject.md` and fill '
                        'it in for this project')


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


def config_label_findings(project_map, live_labels, path='ClaudeProject.md'):
    """Labels a surviving `## Label Map` names that the repo does not carry.

    The review-state labels are `review_label_findings`', because the plugin
    knows their colours and can create them; a project's own label it cannot.
    """
    live = set(live_labels or ())
    out = []
    for purpose, name in sorted((project_map or {}).items()):
        if name in live:
            continue
        out.append(finding(
            CRITICAL, 'config-label',
            '`## Label Map` in %s maps `%s` to `%s`, which does not exist in '
            'this repo' % (path, purpose, name),
            'create the label, or correct the mapping to the name the repo '
            'actually uses', path))
    return out


def review_label_findings(names, live_labels):
    """Review-state labels the repo does not carry, one finding for all of them.

    A warning, because nothing fails for want of one: `wf review-finish`
    creates a missing verdict label on the spot. It is still worth repairing
    before a run, since `wf handoff` would open a pull request with no entry
    label and the review picker would never see it.
    """
    missing = [name for _, name, _, _ in missing_review_labels(names, live_labels)]
    if not missing:
        return []
    return [finding(
        WARNING, 'review-label',
        'the repo has no %s, so a pull request cannot carry that review state'
        % _names(missing),
        'run `wf labels-ensure`, which creates each one with its colour and '
        'description and leaves existing labels alone',
        'docs/review.config.md')]


def deprecated_label_findings(project_map, live_labels, path='ClaudeProject.md'):
    """Label-map rows for labels that no longer answer anything.

    Three families, all retired for the same reason: a structured field answers
    the question and the label was a second copy of the answer. `type-*` was
    replaced by the native issue type, `status-*` and `needs-refinement` by the
    `Stage` field, the scope labels by `Ownership`, and `priority-*`
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

    # Every issue label the workflow used to apply: a project part-way through
    # the 10.0.0 migration still has `status-blocked` on real issues, and
    # `blocked` sitting beside it still splits what a person sees when they
    # filter the list by hand.
    present = set(live)
    known = dict(RETIRED_LABELS)
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


def stage_findings(field_map, project_fields=None, path='ClaudeProject.md'):
    """Whether the org's `Stage` field can hold every state the plugin writes.

    Both findings are critical. With no `Stage` field nothing records whether
    an issue is in progress, blocked or done, so a second agent picks up work
    already underway; with an option missing, the transition to it fails at
    GitHub and the issue keeps whatever stage it had, which for a claim is the
    pool.

    `field_map` is the capability record's `{field name: meta}`, where `meta`
    carries `options` as `{option name: id}`.
    """
    name = resolve_field_name('field-stage', project_fields or {})
    meta = (field_map or {}).get(name)
    if not meta:
        return [finding(
            CRITICAL, 'stage-absent',
            'the org defines no `%s` field, so no issue can record whether it '
            'is available, in progress, blocked or done' % name,
            'create `%s` as a single-select org issue field (Planning -> Issue '
            'fields) with the options %s, and pin it to every enabled issue type'
            % (name, _names(STAGE_NAMES.values())), path)]
    have = {str(o).strip().lower() for o in (meta.get('options') or {})}
    missing = [n for n in STAGE_NAMES.values() if n.lower() not in have]
    if not missing:
        return []
    return [finding(
        CRITICAL, 'stage-options',
        '`%s` has no %s option%s, so a transition to %s fails and the issue '
        'keeps the stage it had' % (name, _names(missing),
                                    '' if len(missing) == 1 else 's',
                                    'it' if len(missing) == 1 else 'them'),
        'add %s to the `%s` field in the org settings' % (_names(missing), name),
        path)]


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
     'the `Ready` opt-in, which no longer exists -- the pool is every issue '
     'whose `Stage` is blank or `Backlog`'),
    (r'status[-:_](?:in-progress|blocked|parked|non-code|in-review|needs-attention)|'
     r'\bneeds-refinement\b|\bhuman-required\b|\bbrowser-agent\b|priority[-:](?:critical|high|medium|low)',
     'a lifecycle, scope or priority label that decided something and no '
     'longer does'),
    (r'(?i)blocked by\s*#\d+|depends on\s*#\d+',
     'a dependency written as prose, which nothing reads: the native '
     'blocked-by edge is the only record'),
    (r'/github-workflow:|github-workflow@subverting-complexity',
     'the plugin under its old name, `github-workflow`, which stopped '
     'resolving when 14.0.0 renamed it to `synergy`: a `/github-workflow:` '
     'command is `/synergy:`, except `/github-workflow:code-review`, which is '
     '`/synergy:pr-review`'),
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
                'rewrite those lines against the current workflow: the `Stage` '
                'field is the state, `Priority`, `Effort` and `Ownership` are '
                'the fields every decision reads, and a dependency is a native '
                'blocked-by edge, and the plugin is `synergy`',
                name))
    return out


def preflight_summary(findings):
    """Counts by level and by check, so a run reports a shape, not a wall."""
    checks = {}
    for entry in findings:
        checks[entry['check']] = checks.get(entry['check'], 0) + 1
    return {'critical': sum(1 for f in findings if f['level'] == CRITICAL),
            'warning': sum(1 for f in findings if f['level'] == WARNING),
            'checks': checks}
