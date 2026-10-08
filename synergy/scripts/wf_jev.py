"""
`wf jev`: ask Jev, the TypeSafe decision model, one of the checks in
`jev-checks.json` and print each answer with how sure it is.

Jev is optional. With no `TYPESAFE_API_KEY`, or when the service does not
answer, the command prints `status: unavailable` and exits 30, which every
caller reads as "make this judgment yourself". It never asks for a key and
never prints one.

`scripts/README.md` has the module map.
"""

import json
import os
import time
import urllib.error
import urllib.request

import wf_core
from wf_io import EXIT_OK, EXIT_UNSUPPORTED, EXIT_USAGE, emit, gh_json

JEV_URL = 'https://api.typesafe.ai/v1/systemone'
JEV_KEY_ENV = 'TYPESAFE_API_KEY'
JEV_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jev-checks.json')
JEV_TIMEOUT = 30
JEV_RETRY_ON = (429, 529)


def load_jev_config():
    with open(JEV_CONFIG, encoding='utf-8') as fh:
        return json.load(fh)


def jev_post(body, key):
    """POST one request. Returns (ok, parsed-or-reason). Retries once when the
    service says it is busy; any other failure is reported, never raised."""
    data = json.dumps(body).encode('utf-8')
    for attempt in (0, 1):
        request = urllib.request.Request(JEV_URL, data=data, method='POST', headers={
            'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=JEV_TIMEOUT) as response:
                return True, json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            if exc.code in JEV_RETRY_ON and attempt == 0:
                time.sleep(2)
                continue
            return False, 'Jev answered HTTP %d' % exc.code
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return False, 'Jev could not be reached: %s' % type(exc).__name__
    return False, 'Jev did not answer'


def jev_fetch_items(numbers, open_limit):
    """Issues read straight from GitHub as items, so their bodies never pass
    through the caller. Returns (items, reason-or-None)."""
    items = []
    for number in numbers or ():
        ok, issue, err = gh_json(['issue', 'view', str(number), '--json', 'number,title,body'])
        if not ok or not issue:
            return None, 'could not read issue %s: %s' % (number, err)
        items.append(issue)
    if open_limit:
        ok, issues, err = gh_json(['issue', 'list', '--state', 'open', '--limit',
                                   str(open_limit), '--json', 'number,title,body'])
        if not ok:
            return None, 'could not list open issues: %s' % err
        seen = {issue['number'] for issue in items}
        items.extend(issue for issue in issues or () if issue['number'] not in seen)
    return [{'id': i['number'], 'title': i.get('title') or '', 'body': i.get('body') or ''}
            for i in items], None


def cmd_jev(args):
    config = load_jev_config()
    payload = {}
    if args.input:
        try:
            with open(args.input, encoding='utf-8') as fh:
                payload = json.load(fh)
        except (OSError, ValueError) as exc:
            emit('usage', EXIT_USAGE, reason='could not read %s: %s' % (args.input, exc))
    # Before any read from GitHub: with no key there is nothing to ask.
    key = os.environ.get(JEV_KEY_ENV, '').strip()
    if not key:
        emit('unavailable', EXIT_UNSUPPORTED,
             reason='%s is not set; make this judgment without Jev' % JEV_KEY_ENV)
    if args.issue or args.open_issues:
        fetched, reason = jev_fetch_items(args.issue, args.open_issues)
        if fetched is None:
            emit('unavailable', EXIT_UNSUPPORTED,
                 reason='%s; make this judgment without Jev' % reason)
        if isinstance(payload, dict):
            payload['items'] = list(payload.get('items') or []) + fetched
    problem = wf_core.jev_input_problem(config, args.check, payload)
    if problem:
        emit('usage', EXIT_USAGE, reason=problem)

    rows, tokens = [], {'input_tokens': 0, 'output_tokens': 0}
    for body, refs in wf_core.jev_requests(config, args.check, payload):
        ok, result = jev_post(body, key)
        if not ok:
            emit('unavailable', EXIT_UNSUPPORTED,
                 reason='%s; make this judgment without Jev' % result)
        rows.extend(wf_core.jev_rows(config, args.check, refs, result.get('answers')))
        for name in tokens:
            tokens[name] += int((result.get('usage') or {}).get(name) or 0)

    titles = {str(item.get('id')): item.get('title') for item in payload.get('items') or ()
              if isinstance(item, dict) and item.get('title')}
    for row in rows:
        if row.get('id') in titles:
            row['title'] = titles[row['id']]
    shown = wf_core.jev_rows_worth_reading(config, args.check, rows)
    emit('ok', EXIT_OK, check=args.check, results=shown,
         summary=wf_core.jev_summary(rows), sure_no=len(rows) - len(shown), usage=tokens)
