"""
The questions `wf jev` asks Jev, the TypeSafe decision model, and how sure an
answer has to be before a workflow may use it.

Jev answers typed questions about a state and returns probabilities. Each check
in `jev-checks.json` is one such question, asked of every item, every ordered
pair of items, or every rule. This module turns a check and the caller's items
into request bodies, and turns the answers back into one row per question with
a level: `high` (use the answer), `medium` (look again) or `low` (decide
without it).

Pure: `scripts/README.md` has the module map.
"""

import itertools

JEV_LEVELS = ('high', 'medium', 'low')


def jev_key(item_id):
    """The state key for an item id. Ids are issue numbers as a rule, and a
    path such as `items.41` reads as an index, so every key gets a prefix."""
    return 'i' + ''.join(ch if ch.isalnum() else '_' for ch in str(item_id))


def jev_trim(value, limit):
    """An item with its long text cut, so one long body cannot crowd out the rest."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + ' …'
    if isinstance(value, dict):
        return {k: jev_trim(v, limit) for k, v in value.items() if k != 'id'}
    return value


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
    if check['per'] in ('item', 'pair'):
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
    id it is about: an item id, an `[a, b]` pair, or a rule name. Questions are
    cut into batches of `config['batch']`, and a batch's state holds only the
    items its questions name.
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
            else:
                used[target] = items[target]
                instructions = check['instructions'].format(path='items.' + jev_key(target))
                refs['q%d' % n] = target
            questions['q%d' % n] = _question(check, instructions)
        state = dict(base)
        state['items'] = {jev_key(i): jev_trim(item, limit) for i, item in used.items()}
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
        row = {'pair': ref} if check['per'] == 'pair' else (
            {'rule': ref} if check['per'] == 'rule' else {'id': ref})
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
    duplicate: those are counted, not listed."""
    check = config['checks'][check_name]
    if check['type'] != 'noul' or check['per'] == 'rule':
        return rows
    return [row for row in rows if row['answer'] is not False or row['level'] != 'high']
