"""
Preflight file-level checks, what `--fix` may repair, and editing
ClaudeProject.md in place.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

import re

from wf_core_findings import WARNING, _normalise_heading, finding


# ── preflight: the file-level checks, and what `--fix` may repair ────────────
# `config-audit` compares `ClaudeProject.md` against the live repo and org. It never looked at the file's own contents beyond its headings, so the
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
    'Ready Gate': ('the pool is every issue whose `Stage` is blank or '
                   '`Backlog`, which no setting turns off'),
    'Agent Gating': ('approval is an issue\'s `Stage` being blank or `Backlog`, '
                     'so there is no gate to enable'),
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
        'fill them in, or run `/synergy:setup` to write them from the '
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
    quality gate, the fields -- is invisible outside the slash commands.
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
    'label-deprecated': 'delete the row from the label map',
    'label-retired': 'take the retired labels off the open issues carrying them',
    'config-retired': 'delete the section',
    'claude-md-ref': 'add the pointer to CLAUDE.md',
    'container-finished': 'close each finished container as completed and '
                          'set its `Stage` to `Done`',
    'stage-drift': 'set each issue\'s `Stage` to the one its open pull request '
                   'or assignee says it is in',
    'review-label': 'create each missing review label with its colour and '
                    'description, never overwriting one that exists',
}

UNFIXABLE_REASONS = {
    'gh-auth': 'only the person at the keyboard can authenticate',
    'config-section': 'the section holds decisions no run can make for a project',
    'file-config': 'there is nothing to repair until the file exists',
    'file-claude-md': "writing a project's CLAUDE.md is the project's call",
    'stage-absent': 'an org-level issue field is created in the org settings, '
                    'not through the API this runs on',
    'stage-options': "adding an option to an org field is done in the org "
                     'settings',
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


CLAUDE_MD_POINTER = (
    'Project configuration -- org and repo, branch convention, quality gate, '
    'label map and issue fields -- lives in [`ClaudeProject.md`]'
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
