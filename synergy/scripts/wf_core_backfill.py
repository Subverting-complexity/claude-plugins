"""
The area backfill: which area label each issue of a repository gets, from the
area epic its parent chain reaches and the `epic` column of the `## Areas`
table in `ClaudeProject.md`.

Area epics were removed in 19.0.0: an issue's area is its `area: {name}`
label. This module is the move off them, and it holds the only read of the
retired `Area` stage (`is_legacy_area_epic`). Two callers use that read and no
other may: `wf area-backfill`, which has to find the epics it copies from, and
preflight, which has to tell a repository that still has them from one that
never did, to name the right fix. No pick, plan, audit, spec or merge decision
reads it.

Pure, like every `wf_core_*` module: the issues GitHub returned, the table
rows and the labels the repository has go in, and a plan comes out.
`wf area-backfill` (`wf_area_backfill.py`) does the reading and the writing.
`scripts/README.md` has the module map.
"""

import wf_core_labels


# The `Stage` option that marked an area epic until 19.0.0. It is no longer
# one of the stages the workflow knows (`STAGE_NAMES`), so nothing writes it
# and an org does not need the option.
LEGACY_AREA_STAGE = 'Area'


def is_legacy_area_epic(type_name, stage):
    """Whether an issue is an area epic as a version before 19.0.0 marked one:
    a native `Epic` whose `Stage` is `Area`. For the move only; see above."""
    return (type_name == 'Epic' and (stage or '').strip().lower()
            == LEGACY_AREA_STAGE.lower())


def legacy_area_epics(issues):
    """The numbers of the area epics among `issues`, each `{'number', 'type',
    'stage'}`, in order. What preflight reads to choose its fix."""
    return sorted(i['number'] for i in issues or ()
                  if is_legacy_area_epic(i.get('type'), i.get('stage')))


# Why an issue resolves to no area. The text is what a person reads.
NO_AREA_NO_PARENT = 'no area epic sits above it in its parent chain'
NO_AREA_FOREIGN = 'a parent in its chain is in another repository'
NO_AREA_UNREAD = 'a parent in its chain was not read'
NO_AREA_CYCLE = 'its parent chain loops'


def _backfill_stage(node, stage_field):
    """The `Stage` value of an issue node as the paged read returns it."""
    for value in ((node.get('issueFieldValues') or {}).get('nodes')) or []:
        if (isinstance(value, dict)
                and (value.get('field') or {}).get('name') == stage_field):
            return value.get('name')
    return None


def backfill_index(nodes, stage_field, repo=None):
    """Every issue the read returned, by number.

    Each entry is `{'id', 'title', 'state', 'parent', 'foreign_parent',
    'is_area', 'labels'}`. `parent` is the parent's number, and None when the
    issue has none or its parent is in another repository, where the number
    means a different issue; `foreign_parent` says which of the two it was.
    `is_area` is `is_legacy_area_epic`: a native `Epic` whose `Stage` is
    `Area`.
    """
    index = {}
    for node in nodes or ():
        if not node or not node.get('number'):
            continue
        parent = node.get('parent') or {}
        home = (parent.get('repository') or {}).get('nameWithOwner')
        foreign = bool(parent) and bool(home) and bool(repo) \
            and home.lower() != repo.lower()
        index[node['number']] = {
            'id': node.get('id'),
            'title': node.get('title') or '',
            'state': (node.get('state') or '').upper(),
            'parent': None if foreign else parent.get('number'),
            'foreign_parent': foreign,
            'is_area': is_legacy_area_epic(
                (node.get('issueType') or {}).get('name'),
                _backfill_stage(node, stage_field)),
            'labels': [l['name'] for l
                       in ((node.get('labels') or {}).get('nodes')) or []
                       if l and l.get('name')],
        }
    return index


def resolve_area_epic(number, index):
    """The nearest area epic above issue `number`. (epic number or None, reason).

    The walk starts at the issue's parent, so an area epic is not its own
    area here. Each number is visited once, so a chain that loops ends with a
    reason and never runs for ever.
    """
    seen = {number}
    current = index.get(number)
    while True:
        if current is None:
            return None, NO_AREA_UNREAD
        if current['foreign_parent']:
            return None, NO_AREA_FOREIGN
        parent = current['parent']
        if parent is None:
            return None, NO_AREA_NO_PARENT
        if parent in seen:
            return None, NO_AREA_CYCLE
        seen.add(parent)
        current = index.get(parent)
        if current is not None and current['is_area']:
            return parent, None


def backfill_plan(index, rows, live_label_names):
    """What `area-backfill` has to do. A dict:

      epics      `{epic number: {'area', 'label', 'title', 'state'}}` for each
                 area epic a row names. `label` is the label as the repository
                 spells it, and None when the repository lacks it.
      stops      why nothing may be written, as lists that are all empty
                 in a plan that may run: `epics_without_row` (an area
                 epic no row names, `{number, title}`), `missing_labels`
                 (label names the repository lacks), `duplicate_epic_rows`
                 (`{epic, areas}`: two rows name one epic), and
                 `rows_without_area_epic` (`{area, epic}`: the row's epic is
                 not an area epic of this repository).
      to_label   `{number, id, label, area}`: the issue resolves to an area
                 and carries no area label.
      already    numbers of the issues that carry an area label and need no
                 write: the right one, or any one on an issue no epic covers.
      differs    `{number, title, has, resolves_to}`: the issue carries an
                 area label, and not the one of the area it resolves to.
                 Reported, never written, because a person may have chosen it.
      no_area    `{number, title, reason}`: no area epic above it and no area
                 label on it. Never written.
      counts     `{area name: {'to_label', 'already', 'differs', 'total'}}`,
                 one entry per row that names an epic.

    The area epics themselves are in none of the lists: an epic is the area,
    not an issue in it. A plan built from what a finished run leaves behind
    has an empty `to_label`, which is what makes a second run write nothing.
    """
    key = wf_core_labels._key
    live = {}
    for name in live_label_names or ():
        live.setdefault(key(name), name)

    by_epic = {}
    for row in rows or ():
        if row.get('epic') is not None:
            by_epic.setdefault(row['epic'], []).append(row['name'])
    stops = {
        'epics_without_row': [
            {'number': n, 'title': index[n]['title']}
            for n in sorted(index) if index[n]['is_area'] and n not in by_epic],
        'missing_labels': [],
        'duplicate_epic_rows': [
            {'epic': n, 'areas': names}
            for n, names in sorted(by_epic.items()) if len(names) > 1],
        'rows_without_area_epic': [
            {'area': names[0], 'epic': n}
            for n, names in sorted(by_epic.items())
            if n not in index or not index[n]['is_area']],
    }

    epics, counts = {}, {}
    for n, names in sorted(by_epic.items()):
        wanted = wf_core_labels.AREA_PREFIX + names[0]
        label = live.get(key(wanted))
        if label is None:
            stops['missing_labels'].append(wanted)
        entry = index.get(n) or {}
        epics[n] = {'area': names[0], 'label': label,
                    'title': entry.get('title', ''),
                    'state': entry.get('state', '')}
        counts[names[0]] = {'to_label': 0, 'already': 0, 'differs': 0,
                            'total': 0}

    plan = {'epics': epics, 'stops': stops, 'to_label': [], 'already': [],
            'differs': [], 'no_area': [], 'counts': counts}
    for number in sorted(index):
        issue = index[number]
        if issue['is_area']:
            continue
        carried = wf_core_labels.area_labels_on(issue['labels'])
        epic, reason = resolve_area_epic(number, index)
        area = epics.get(epic)
        if area is None:
            # No area epic above it, or one no row names (a stop already).
            if carried:
                plan['already'].append(number)
            elif epic is None:
                plan['no_area'].append({'number': number,
                                        'title': issue['title'],
                                        'reason': reason})
            continue
        tally = counts[area['area']]
        tally['total'] += 1
        wanted = key(wf_core_labels.AREA_PREFIX + area['area'])
        if any(key(name) == wanted for name in carried):
            plan['already'].append(number)
            tally['already'] += 1
        elif carried:
            plan['differs'].append({'number': number, 'title': issue['title'],
                                    'has': carried,
                                    'resolves_to': wf_core_labels.AREA_PREFIX
                                    + area['area']})
            tally['differs'] += 1
        else:
            plan['to_label'].append({'number': number, 'id': issue['id'],
                                     'label': area['label'],
                                     'area': area['area']})
            tally['to_label'] += 1
    return plan


def backfill_stopped(stops):
    """One sentence per reason a plan may not run; empty when it may."""
    out = []
    if stops['epics_without_row']:
        out.append('no row of the `## Areas` table names area epic %s in its '
                   '`epic` column'
                   % ', '.join('#%d' % e['number']
                               for e in stops['epics_without_row']))
    if stops['duplicate_epic_rows']:
        out.append('more than one row names epic %s'
                   % ', '.join('#%d' % e['epic']
                               for e in stops['duplicate_epic_rows']))
    if stops['rows_without_area_epic']:
        out.append('%s not an area epic of this repository'
                   % ', '.join('#%d (area "%s") is' % (e['epic'], e['area'])
                               for e in stops['rows_without_area_epic']))
    if stops['missing_labels']:
        out.append('the repository lacks the label %s; run `wf labels-ensure`'
                   % ', '.join('`%s`' % n for n in stops['missing_labels']))
    return out
