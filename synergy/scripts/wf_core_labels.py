"""
Area and release labels: the labels the `## Areas` and `## Release Targets`
tables in `ClaudeProject.md` name, and what `wf labels-ensure` has to do for
the repository to carry them.

Pure, like every `wf_core_*` module: the tables and the labels GitHub has go
in, and a plan comes out. `scripts/README.md` has the module map.
"""

import re


# GitHub refuses a label description longer than this.
LABEL_DESCRIPTION_LIMIT = 100

AREA_PREFIX = 'area: '
RELEASE_PREFIX = 'release: '
RELEASED_PREFIX = 'released: '
# The start of every label name the tables own. A label GitHub has under one
# of these that no row names is reported, because nothing else may create one.
TABLE_LABEL_PREFIXES = ('area:', 'release:', 'released:')

# Work that ships to nobody outside the team has no row in the release-targets
# table, so its two labels are added to every repository that has the table.
INTERNAL_TARGET = 'internal'
INTERNAL_COLOUR = 'c5def5'
# What its two labels say: waiting to ship, then shipped.
INTERNAL_DESCRIPTIONS = (
    'Waiting for an internal release, which ships to nobody outside the team',
    'Shipped in an internal release, which went to nobody outside the team',
)
# A `released:` label says the same thing for every target, that the issue has
# shipped, so they share one colour rather than repeating the target's.
RELEASED_COLOUR = '0e8a16'


def _key(name):
    """A label name as GitHub compares it: it treats `Area: Api` and
    `area: api` as one label."""
    return (name or '').strip().lower()


def _colour(value):
    """A colour as 6 lower-case hex digits, however it was written."""
    return (value or '').strip().lstrip('#').lower()


def _described(lead, detail):
    """`lead: detail` when that fits a label description, else `lead` alone."""
    detail = (detail or '').strip()
    text = '%s: %s' % (lead, detail) if detail else lead
    if len(text) > LABEL_DESCRIPTION_LIMIT:
        text = lead
    return text[:LABEL_DESCRIPTION_LIMIT]


def _was_label(was):
    """The label an area carried under its old name. `Was` holds the old area
    name; an old label name written in full is taken as it is."""
    was = (was or '').strip()
    if not was:
        return None
    if _key(was).startswith('area:'):
        return was
    return AREA_PREFIX + was


def table_labels(cfg):
    """The labels the tables name, as dicts in creation order.

    Each is `{'name', 'description', 'colour', 'was'}`. `colour` is an empty
    string when the row gives none, and then the label is created with the
    colour GitHub picks and its colour is never compared. `was` is the label
    name an area had before a rename, and None for every other label.

    An area row becomes `area: {name}`. A release-target row becomes
    `release: {name}`, for an issue waiting to ship in that target, and
    `released: {name}`, for one that has shipped in it. A repository with a
    release-targets table also gets the two `internal` labels. No table, no
    labels: the list is empty and `labels-ensure` does what it always did.
    """
    out = []
    for row in cfg.get('areas') or []:
        out.append({'name': AREA_PREFIX + row['name'],
                    'description': (row.get('description') or '').strip(),
                    'colour': _colour(row.get('colour')),
                    'was': _was_label(row.get('was'))})
    targets = cfg.get('release_targets') or []
    for row in targets:
        name = row['name']
        out.append({'name': RELEASE_PREFIX + name,
                    'description': _described('Waiting to ship in %s' % name,
                                              row.get('description')),
                    'colour': _colour(row.get('colour')), 'was': None})
        out.append({'name': RELEASED_PREFIX + name,
                    'description': _described('Shipped in %s' % name,
                                              row.get('description')),
                    'colour': RELEASED_COLOUR, 'was': None})
    # A row of that name is the project's own account of it, and wins.
    if targets and not any(_key(t['name']) == INTERNAL_TARGET for t in targets):
        waiting, shipped = INTERNAL_DESCRIPTIONS
        out.append({'name': RELEASE_PREFIX + INTERNAL_TARGET, 'description': waiting,
                    'colour': INTERNAL_COLOUR, 'was': None})
        out.append({'name': RELEASED_PREFIX + INTERNAL_TARGET, 'description': shipped,
                    'colour': RELEASED_COLOUR, 'was': None})
    return out


def _differences(wanted, live):
    """How a label GitHub has differs from its row, as `differs` entries.

    Only what the row states is compared: a row with no colour, or an area
    with no description, accepts whatever the label has.
    """
    out = []
    pairs = (('colour', wanted['colour'], _colour(live.get('colour'))),
             ('description', wanted['description'],
              (live.get('description') or '').strip()))
    for field, want, have in pairs:
        if want and want != have:
            out.append({'name': wanted['name'], 'field': field,
                        'wanted': want, 'live': have})
    return out


def label_plan(wanted, live):
    """What `labels-ensure` has to do, from `table_labels` and GitHub's labels.

    `live` is every label the repository has, as `{'name', 'colour',
    'description'}`. Names are matched the way GitHub matches them, without
    case, so a label that only differs in case is the same label and is never
    created a second time. Returns a dict of lists:

      create     wanted labels the repository lacks.
      rename     `{'from', 'to'}`: the row carries `was`, and only the old
                 name exists. Renamed in place, so every issue keeps it.
      conflicts  `{'was', 'name'}`: both names exist. Nothing is written for
                 that row; a person has to move the issues and delete one.
      unknown    names of `area:`, `release:` and `released:` labels the
                 repository has and no row names. Reported, never deleted.
                 The old name of a rename or a conflict is not listed again.
      differs    `{'name', 'field', 'wanted', 'live'}`: a colour or
                 description that is not the row's. Reported, never changed,
                 because a person may have chosen it. A label about to be
                 renamed is compared under its new name.

    A plan computed from the labels a finished run leaves behind has nothing
    in `create` or `rename`, which is what makes a second run write nothing.
    """
    by_key = {}
    for label in live or ():
        if label.get('name'):
            by_key.setdefault(_key(label['name']), label)
    wanted_keys = {_key(w['name']) for w in wanted}
    plan = {'create': [], 'rename': [], 'conflicts': [], 'unknown': [],
            'differs': []}
    accounted = set(wanted_keys)
    for label in wanted:
        current = by_key.get(_key(label['name']))
        was_key = _key(label.get('was'))
        # An old name another row now uses is that row's label, not this one's.
        old = by_key.get(was_key) if was_key and was_key not in wanted_keys else None
        if old is not None:
            accounted.add(was_key)
        if current is not None and old is not None:
            plan['conflicts'].append({'was': old['name'], 'name': current['name']})
        elif current is None and old is not None:
            plan['rename'].append({'from': old['name'], 'to': label['name']})
            current = old
        elif current is None:
            plan['create'].append(label)
        if current is not None:
            plan['differs'].extend(_differences(label, current))
    for key in sorted(by_key):
        if key.startswith(TABLE_LABEL_PREFIXES) and key not in accounted:
            plan['unknown'].append(by_key[key]['name'])
    return plan


# ── the area label on one issue ──────────────────────────────────────────────
# Every issue carries exactly 1 `area: {name}` label, named after a row of the
# areas table. These rules say which label a name means and what has to change
# on an issue for it to carry that one and no other.

def area_label(name):
    """The label an area row's name stands for: `area: {name}`."""
    return AREA_PREFIX + (name or '').strip()


def area_row(rows, name):
    """The areas-table row `name` means, or None when no row has that name.

    Matched trimmed and without case, the way GitHub compares label names, so
    `library ` finds the `Library` row and the label is written in the row's
    own spelling.
    """
    wanted = _key(name) if isinstance(name, str) else ''
    if not wanted:
        return None
    for row in rows or ():
        if isinstance(row, dict) and _key(row.get('name')) == wanted:
            return row
    return None


def area_names(rows):
    """The names of the areas-table rows, in table order."""
    return [row['name'] for row in rows or ()
            if isinstance(row, dict) and (row.get('name') or '').strip()]


def area_labels_on(names):
    """The area labels among an issue's label names, in the order given."""
    return [name for name in names or () if _key(name).startswith('area:')]


def area_label_edit(present, wanted):
    """What to add and remove so an issue carries `wanted` and no other area
    label. Returns `(add, remove)`, two lists of label names.

    `present` is every label name on the issue. `add` is empty when the issue
    already carries `wanted`, and `remove` is every other area label, so a
    correction never leaves 2. Both are empty when nothing has to change.
    """
    have = area_labels_on(present)
    carried = any(_key(name) == _key(wanted) for name in have)
    add = [] if carried else [wanted]
    remove = [name for name in have if _key(name) != _key(wanted)]
    return add, remove


# ── the release labels on a closed issue ─────────────────────────────────────
# A merged pull request leaves each issue it closes with at least 1
# `release: {target}` label, so a release script can tell what waits to ship
# in each target. The targets are decided before the merge and travel in the
# release-notes file as a `targets` list per issue. These rules say which
# names that list may hold and which labels an issue still lacks.
# `references/release-labels.md` has the contract a release script follows.

_STORY_SUFFIX = re.compile(r'\(#(\d+)\)\s*$')


def release_label(name):
    """The label a release target's name stands for: `release: {name}`."""
    return RELEASE_PREFIX + (name or '').strip()


def release_labels_on(names):
    """The `release:` labels among an issue's label names, in the order given.
    A `released:` label is not one: it says the issue has shipped."""
    return [name for name in names or () if _key(name).startswith('release:')]


def release_target_names(rows):
    """The target names an issue may carry: each row of the release-targets
    table in table order, then `internal` unless a row has that name.

    Empty when the table has no row. Such a repository has no release labels
    at all, so a merge there sets none.
    """
    out, seen = [], set()
    for row in rows or ():
        name = (row.get('name') or '').strip() if isinstance(row, dict) else ''
        if name and _key(name) not in seen:
            seen.add(_key(name))
            out.append(name)
    if out and INTERNAL_TARGET not in seen:
        out.append(INTERNAL_TARGET)
    return out


def parse_release_targets(data, rows):
    """The `targets` lists of a release-notes file, read into {issue number:
    [target names]}. Returns (targets, errors).

    The file is {"<number>": {"targets": ["web", "backend"]}} beside the
    notes texts. A name is matched without case and written in the table's
    own spelling, and the label form `release: web` is taken as `web`. An
    empty list means no target applies and becomes `internal`. An entry with
    no `targets` key is left out: nothing was decided for that issue, which
    the caller reports as a gap. A name the table does not have is an error
    and is dropped; when every name of an entry is dropped the entry is left
    out too, because a wrong name is not a decision that nothing applies.

    A key that is not an issue number, or an entry that is not an object, is
    skipped without an error: `parse_release_notes` reports those.
    """
    valid = {_key(name): name for name in release_target_names(rows)}
    targets, errors = {}, []
    if not valid or not isinstance(data, dict):
        return targets, errors
    for key, entry in data.items():
        try:
            number = int(str(key).lstrip('#'))
        except ValueError:
            continue
        if not isinstance(entry, dict) or 'targets' not in entry:
            continue
        raw = entry['targets']
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
            errors.append('#%d: targets is a list of release-target names' % number)
            continue
        chosen, unknown = [], []
        for name in raw:
            name = name.strip()
            if _key(name).startswith('release:'):
                name = name.split(':', 1)[1].strip()
            if not name:
                continue
            match = valid.get(_key(name))
            if match is None:
                unknown.append(name)
            elif match not in chosen:
                chosen.append(match)
        if unknown:
            errors.append('#%d: %s not in the Release Targets table (valid: %s)'
                          % (number, ', '.join("'%s'" % n for n in unknown),
                             ', '.join(valid.values())))
            if not chosen:
                continue
        targets[number] = chosen or [valid[INTERNAL_TARGET]]
    return targets, errors


def release_label_add(present, targets):
    """The `release:` labels to add so an issue carries one for each target.

    `present` is every label name on the issue. Only what is missing is
    returned, and nothing is ever removed: a release script reads these
    labels, and the plugin takes none of them off.
    """
    have = {_key(name) for name in release_labels_on(present)}
    out = []
    for target in targets or ():
        label = release_label(target)
        if _key(label) not in have:
            have.add(_key(label))
            out.append(label)
    return out


def commit_story(message):
    """The story a commit belongs to: the number in the `(#N)` that ends the
    first line of its message, or None when that line ends with no number.

    The first line, because a message goes on to a body and trailers, and
    `execute` and `bulk-execute` end the subject with the story it answers.
    """
    lines = (message or '').strip().splitlines()
    match = _STORY_SUFFIX.search(lines[0]) if lines else None
    return int(match.group(1)) if match else None


def story_paths(commits, stories):
    """The file paths each story's own commits changed. {story: [paths]}.

    `commits` is a list of `{'message', 'paths'}` and `stories` the issue
    numbers a pull request closes. A path counts once per story, in the order
    first seen. A commit that names no story, or a story the pull request
    does not close, counts for no story, so shared work in such a commit
    never decides where a story ships.
    """
    out = {int(number): [] for number in stories or ()}
    for commit in commits or ():
        story = commit_story((commit or {}).get('message'))
        if story not in out:
            continue
        for path in commit.get('paths') or ():
            if path and path not in out[story]:
                out[story].append(path)
    return out
