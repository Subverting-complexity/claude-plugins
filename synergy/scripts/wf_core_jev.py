"""
The questions `wf jev` asks Jev, the TypeSafe decision model, and how sure an
answer has to be before a workflow may use it.

Jev answers typed questions about a state and returns probabilities. Each check
in `jev-checks.json` is one such question, asked of every item, every ordered
pair of items, every rule, or every item and release target. This module turns
a check and the caller's items into request bodies, and turns the answers back
into one row per question with a level: `high` (use the answer), `medium` (look
again) or `low` (decide without it).

Two checks have answers that differ per repository: `area` picks one of the
repository's areas and `target` asks about each of its release targets. Their
entries name the `ClaudeProject.md` table the answers come from, and
`jev_resolve` fills them in from the rows the caller read. Nothing here reads
configuration.

Pure: `scripts/README.md` has the module map.
"""

import itertools

JEV_LEVELS = ('high', 'medium', 'low')
# What a file at the top of the repository is counted under in a folder list.
JEV_ROOT_FOLDER = '(root)'
_CUT = ' …'


def jev_key(item_id):
    """The state key for an item id. Ids are issue numbers as a rule, and a
    path such as `items.41` reads as an index, so every key gets a prefix."""
    return 'i' + ''.join(ch if ch.isalnum() else '_' for ch in str(item_id))


def jev_trim(value, limit):
    """An item with its long text cut, so one long body cannot crowd out the rest."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + _CUT
    if isinstance(value, dict):
        return {k: jev_trim(v, limit) for k, v in value.items() if k != 'id'}
    return value


def jev_table_needed(config, check_name):
    """The `ClaudeProject.md` table a check takes its answers from: `areas`,
    `release_targets`, or None for a check whose answers are fixed."""
    check = config['checks'].get(check_name) or {}
    return check.get('options_from') or check.get('targets_from')


def jev_table_rows(rows):
    """The usable rows of an areas or release-targets table as `(name,
    description)` pairs, in table order. A row with no name is left out, and a
    name that comes twice counts once."""
    out, seen = [], set()
    for row in rows or ():
        name = str(row.get('name') or '').strip() if isinstance(row, dict) else ''
        if name and name not in seen:
            seen.add(name)
            out.append((name, str(row.get('description') or '').strip()))
    return out


def jev_resolve(config, check_name, rows):
    """The configuration with one check's answers filled in from a table.

    For a check with `options_from`, each row becomes an option, name to
    description, ahead of the fixed options such as `unsure`. For a check with
    `targets_from`, the rows become its `targets`. A row with no description
    is described by its name. Any other check comes back unchanged, and the
    configuration passed in is never altered.
    """
    check = config['checks'].get(check_name)
    if not check or not jev_table_needed(config, check_name):
        return config
    table = jev_table_rows(rows)
    check = dict(check)
    if check.get('options_from'):
        options = {name: description or name for name, description in table}
        options.update(check.get('options') or {})
        check['options'] = options
    else:
        check['targets'] = [list(row) for row in table]
    return dict(config, checks=dict(config['checks'], **{check_name: check}))


def jev_folders(paths):
    """The distinct folders a list of file paths touches, in the order they
    first appear. A folder is the directory of a path, and a file at the top
    of the repository counts under `JEV_ROOT_FOLDER`. Fifty files in one
    folder say no more about where work ships than one does."""
    out = []
    for path in paths or ():
        if not isinstance(path, str) or not path.strip():
            continue
        path = path.strip().replace('\\', '/')
        while path.startswith('./'):
            path = path[2:]
        folder = path.rsplit('/', 1)[0].strip('/') if '/' in path else ''
        folder = folder or JEV_ROOT_FOLDER
        if folder not in out:
            out.append(folder)
    return out


def _folders_length(folders):
    """The length of a folder list when it is written out with separators."""
    return sum(len(folder) for folder in folders) + 2 * max(len(folders) - 1, 0)


def jev_fit_folders(folders, limit):
    """The folders that fit in `limit` characters, and how many were left out.

    A folder is kept whole or not at all, because half a path names a
    different folder. The list stops at the first folder that does not fit, so
    what is kept is always the start of the list.
    """
    kept = []
    for folder in folders:
        if _folders_length(kept + [folder]) > limit:
            break
        kept.append(folder)
    return kept, len(folders) - len(kept)


def jev_target_item(item, limit):
    """An item as the `target` check sends it: `paths` reduced to `folders`,
    and the item's text, folders included, inside `limit`.

    `jev_trim` holds each string to the limit on its own, which a long list
    of paths would pass through untouched. Here the limit is shared. The
    folders get what the title and body leave, and half the limit at least,
    since the folders say most about where work ships; the strings then share
    what the folders leave, in the item's own order. When folders are left out
    the item says how many, so Jev does not read a cut list as the whole one.
    """
    paths = item.get('paths')
    folders = jev_folders(paths) if isinstance(paths, list) else []
    wanted = sum(len(value) for name, value in item.items()
                 if isinstance(value, str) and name != 'id')
    folders, left_out = jev_fit_folders(folders, max(limit // 2, limit - wanted))
    room = limit - _folders_length(folders)

    out = {}
    for name, value in item.items():
        if name in ('id', 'paths'):
            continue
        if not isinstance(value, str):
            out[name] = jev_trim(value, limit)
            continue
        if len(value) > room:
            value = value[:room - len(_CUT)] + _CUT if room > len(_CUT) else ''
        room -= len(value)
        if value:
            out[name] = value
    if folders:
        out['folders'] = folders
    if left_out:
        out['folders_left_out'] = left_out
    return out


def jev_input_problem(config, check_name, payload):
    """Why this input cannot be asked, or None. Checked before any request."""
    check = config['checks'].get(check_name)
    if check is None:
        return 'unknown check %r; known: %s' % (
            check_name, ', '.join(sorted(config['checks'])))
    if not isinstance(payload, dict):
        return 'the input must be a JSON object'
    needs = check.get('needs')
    if needs and not payload.get(needs):
        return 'the %s check needs %r in the input' % (check_name, needs)
    if check['per'] in ('item', 'pair', 'item-target'):
        items = payload.get('items')
        if not isinstance(items, list) or not items:
            return 'the %s check needs a non-empty "items" list' % check_name
        ids = [str(item.get('id', '')) if isinstance(item, dict) else '' for item in items]
        if '' in ids:
            return 'every item needs an "id"'
        if len(set(ids)) != len(ids):
            return 'item ids must be unique'
        if check['per'] == 'pair':
            if len(items) < 2:
                return 'the %s check needs at least two items' % check_name
            if len(items) > config['max_pair_items']:
                return 'the %s check takes at most %d items' % (
                    check_name, config['max_pair_items'])
        if check['per'] == 'item-target':
            for item in items:
                paths = item.get('paths', [])
                if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                    return 'the "paths" of an item must be a list of file paths'
    return None


def _question(check, instructions):
    question = {'type': check['type'], 'instructions': instructions}
    if check['type'] == 'score':
        question['criteria'] = [level[1] for level in check['levels']]
    elif check['type'] == 'choice':
        question['criteria'] = dict(check['options'])
    return question


def _chunks(seq, size):
    for start in range(0, len(seq), size):
        yield seq[start:start + size]


def jev_requests(config, check_name, payload):
    """The request bodies for one check, and what each question name refers to.

    Returns a list of `(body, refs)`, where `refs` maps a question name to the
    id it is about: an item id, an `[a, b]` pair, a rule name, or an `[item
    id, target]` pair. Questions are cut into batches of `config['batch']`, and
    a batch's state holds only the items its questions name.

    A check whose answers come from a table must be resolved first, with
    `jev_resolve`: unresolved, `target` has no targets and asks nothing.
    """
    check = config['checks'][check_name]
    limit = config['max_text']
    base = {}
    if check.get('needs'):
        base[check['needs']] = jev_trim(payload[check['needs']], limit)

    if check['per'] == 'rule':
        out = []
        for batch in _chunks(sorted(check['rules'].items()), config['batch']):
            questions, refs = {}, {}
            for n, (rule, instructions) in enumerate(batch):
                questions['q%d' % n] = _question(check, instructions)
                refs['q%d' % n] = rule
            out.append(({'model': config['model'], 'state': base, 'questions': questions}, refs))
        return out

    items = {str(item['id']): item for item in payload['items']}
    if check['per'] == 'pair':
        targets = list(itertools.permutations(items, 2))
    elif check['per'] == 'item-target':
        targets = [(item, name, description) for item in items
                   for name, description in check.get('targets') or ()]
    else:
        targets = list(items)

    out = []
    for batch in _chunks(targets, config['batch']):
        questions, refs, used = {}, {}, {}
        for n, target in enumerate(batch):
            if check['per'] == 'pair':
                a, b = target
                used[a], used[b] = items[a], items[b]
                instructions = check['instructions'].format(
                    a='items.' + jev_key(a), b='items.' + jev_key(b))
                refs['q%d' % n] = [a, b]
            elif check['per'] == 'item-target':
                item, name, description = target
                used[item] = items[item]
                # The table's text is put in by replacement and last, so a
                # brace in a description is text and never a field.
                instructions = check['instructions']
                if description:
                    instructions += check.get('describe', '')
                instructions = (instructions.replace('{path}', 'items.' + jev_key(item))
                                .replace('{target}', name)
                                .replace('{description}', description))
                refs['q%d' % n] = [item, name]
            else:
                used[target] = items[target]
                instructions = check['instructions'].format(path='items.' + jev_key(target))
                refs['q%d' % n] = target
            questions['q%d' % n] = _question(check, instructions)
        state = dict(base)
        fit = jev_target_item if check['per'] == 'item-target' else jev_trim
        state['items'] = {jev_key(i): fit(item, limit) for i, item in used.items()}
        out.append(({'model': config['model'], 'state': state, 'questions': questions}, refs))
    return out


def jev_level(config, kind, value):
    """`high`, `medium` or `low` for a confidence, or for a yes probability.

    A yes probability has no separate confidence: it is sure near 0 or 1 and
    unsure near 0.5, so it is judged by its distance from the nearer end.
    """
    if kind == 'noul':
        value = max(value, 1 - value)
    cut = config['thresholds']['noul' if kind == 'noul' else 'confidence']
    if value >= cut['high']:
        return 'high'
    if value >= cut['medium']:
        return 'medium'
    return 'low'


def jev_rows(config, check_name, refs, answers):
    """One row per question: what it was about, the answer and its level.

    A question the response left out is a `low` row with no answer, so a caller
    never mistakes a missing answer for a decision.
    """
    check = config['checks'][check_name]
    rows = []
    for name, ref in refs.items():
        if check['per'] == 'pair':
            row = {'pair': ref}
        elif check['per'] == 'rule':
            row = {'rule': ref}
        elif check['per'] == 'item-target':
            row = {'id': ref[0], 'target': ref[1]}
        else:
            row = {'id': ref}
        answer = answers.get(name) if isinstance(answers, dict) else None
        try:
            if check['type'] == 'noul':
                p = float(answer['noul'])
                row.update(answer=p >= 0.5, probability=round(p, 3),
                           level=jev_level(config, 'noul', p))
            elif check['type'] == 'score':
                score = float(answer['score'])
                index = min(max(int(round(score)), 0), len(check['levels']) - 1)
                row.update(answer=check['levels'][index][0], score=round(score, 2),
                           confidence=round(float(answer['confidence']), 3),
                           level=jev_level(config, 'score', float(answer['confidence'])))
            else:
                row.update(answer=answer['choice'],
                           confidence=round(float(answer['confidence']), 3),
                           level=jev_level(config, 'choice', float(answer['confidence'])))
        except (KeyError, TypeError, ValueError):
            row.update(answer=None, level='low')
        rows.append(row)
    return rows


def jev_summary(rows):
    return {level: sum(1 for row in rows if row['level'] == level) for level in JEV_LEVELS}


def jev_rows_worth_reading(config, check_name, rows):
    """The rows a caller has to read. A check of items or pairs that asks a yes
    or no question is mostly sure noes, such as every open issue that is not a
    duplicate: those are counted, not listed.

    A check of items and release targets lists every row. Its caller sets a
    value from the whole set of answers for an item, and a sure no is as much
    a part of that set as a yes."""
    check = config['checks'][check_name]
    if check['type'] != 'noul' or check['per'] in ('rule', 'item-target'):
        return rows
    return [row for row in rows if row['answer'] is not False or row['level'] != 'high']
