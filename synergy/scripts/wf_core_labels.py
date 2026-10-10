"""
Area and release labels: the labels the `## Areas` and `## Release Targets`
tables in `ClaudeProject.md` name, and what `wf labels-ensure` has to do for
the repository to carry them.

Pure, like every `wf_core_*` module: the tables and the labels GitHub has go
in, and a plan comes out. `scripts/README.md` has the module map.
"""


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
