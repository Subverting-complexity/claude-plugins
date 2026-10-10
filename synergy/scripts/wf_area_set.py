"""
The `area-set` subcommand: give an issue its area label when it has none.

Every issue carries exactly 1 `area: {name}` label, named after a row of the
`## Areas` table in `ClaudeProject.md`, so release notes can place it without
a parent. `issue-apply` writes the label on an issue it files. This command
covers an issue an agent picks that was filed before that, or by hand.

An issue that has its label is left alone. For one that has none, Jev is asked
its `area` check, and a `high` answer that names a row is written. Every other
issue comes back under `choose` with the table rows, and the caller runs the
command again with `--area`. Jev is optional: with no key, or with Jev off for
the repository, every such issue goes straight to `choose`.

`scripts/README.md` has the module map.
"""

import wf_core
from wf_config import load_config
from wf_io import (
    EXIT_ENV, EXIT_GAPS, EXIT_OK, EXIT_PARTIAL, EXIT_SPEC, EXIT_USAGE, emit,
    emit_line, run,
)
from wf_jev import jev_ask
from wf_post_merge import _aliased_repository_read


AREA_SET_SELECTION = 'number title labels(first:50){ nodes { name } }'


def _area_name(label_name):
    """The area a label names: `area: Library` is `Library`."""
    return label_name.split(':', 1)[1].strip()


def _write_area(repo, number, add, remove):
    """Put the area label on and take every other one off. (ok, err)."""
    cmd = ['gh', 'issue', 'edit', str(number), '--repo', repo]
    for name in add:
        cmd += ['--add-label', name]
    for name in remove:
        cmd += ['--remove-label', name]
    code, _, err = run(cmd)
    if code == 0:
        return True, ''
    err = (err or '').strip() or 'gh issue edit failed'
    if add and 'not found' in err.lower():
        err += ("; the repository has no '%s' label, so run `wf labels-ensure` "
                'to create the labels the Areas table names' % add[0])
    return False, err


def _jev_areas(numbers, rows):
    """Ask Jev for the area of each issue. ({number: row name}, `jev` value).

    Only a `high` answer that names a row of the table is returned. `unsure`,
    a lower level and a name the table does not have are all left out, and
    the caller chooses those.
    """
    outcome, result = jev_ask('area', issues=list(numbers))
    if outcome != 'ok':
        return {}, 'unavailable'
    chosen = {}
    for row in result.get('rows') or ():
        if row.get('level') != 'high':
            continue
        match = wf_core.area_row(rows, row.get('answer'))
        try:
            number = int(row.get('id'))
        except (TypeError, ValueError):
            continue
        if match is not None:
            chosen[number] = match['name']
    return chosen, ('used' if chosen else 'not-sure')


def cmd_area_set(args):
    """`wf area-set`: make each issue carry exactly 1 area label."""
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    numbers = list(dict.fromkeys(int(n) for n in args.issue or ()))
    if args.area is not None and len(numbers) != 1:
        emit('usage', EXIT_USAGE,
             reason='--area names the area of 1 issue; pass exactly 1 --issue '
                    'with it')
    table = [r for r in cfg.get('areas') or [] if (r.get('name') or '').strip()]
    rows = [{'name': r['name'], 'description': (r.get('description') or '').strip()}
            for r in table]
    if not table:
        emit_line('ok', EXIT_OK, issues=[],
                  reason='ClaudeProject.md has no Areas table, so no area '
                         'label is set')
    named = None
    if args.area is not None:
        named = wf_core.area_row(table, args.area)
        if named is None:
            emit('spec-invalid', EXIT_SPEC, rows=rows,
                 reason="area '%s' is not in the Areas table (valid: %s)"
                        % (args.area.strip(), ', '.join(r['name'] for r in rows)))

    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    titles, labels = {}, {}
    for number, read, node, err in _aliased_repository_read(
            cfg, numbers, 'a', AREA_SET_SELECTION):
        if not read or not node:
            emit('error', EXIT_ENV, repo=repo, issue=number,
                 reason='could not read #%d in %s: %s'
                        % (number, repo, err or 'no such issue'))
        titles[number] = node.get('title') or ''
        labels[number] = [n.get('name') or '' for n
                          in (node.get('labels') or {}).get('nodes') or []]

    done, wanted, pending = [], {}, []
    for number in numbers:
        have = wf_core.area_labels_on(labels[number])
        if named is not None:
            wanted[number] = (named['name'], 'caller')
        elif len(have) == 1:
            done.append({'number': number, 'title': titles[number],
                         'area': _area_name(have[0]), 'action': 'kept',
                         'source': 'label'})
        else:
            # None, or more than 1: both leave release notes with no one
            # place for the issue, so both get an area chosen.
            pending.append(number)

    jev = None
    if pending:
        chosen, jev = _jev_areas(pending, table)
        for number in pending:
            if number in chosen:
                wanted[number] = (chosen[number], 'jev')

    failed = []
    for number in numbers:
        if number not in wanted:
            continue
        name, source = wanted[number]
        add, remove = wf_core.area_label_edit(labels[number],
                                              wf_core.area_label(name))
        entry = {'number': number, 'title': titles[number], 'area': name,
                 'action': 'kept', 'source': source}
        if add or remove:
            written, err = _write_area(repo, number, add, remove)
            if not written:
                failed.append({'number': number, 'title': titles[number],
                               'area': name, 'error': err})
                continue
            had = wf_core.area_labels_on(labels[number])
            entry['action'] = 'replaced' if had else 'set'
        done.append(entry)

    done.sort(key=lambda e: numbers.index(e['number']))
    choose = [{'number': n, 'title': titles[n]} for n in pending
              if n not in wanted]
    payload = {'issues': done}
    if jev:
        payload['jev'] = jev
    if failed:
        emit('partial', EXIT_PARTIAL, failed=failed, choose=choose, rows=rows,
             reason='%d area label %s not written' % (
                 len(failed), 'was' if len(failed) == 1 else 'were'),
             **payload)
    if choose:
        emit('choose', EXIT_GAPS, choose=choose, rows=rows,
             reason='choose the row in `rows` that best covers each issue in '
                    '`choose`, then run `area-set --issue N --area NAME` for it',
             **payload)
    emit_line('ok', EXIT_OK, **payload)
