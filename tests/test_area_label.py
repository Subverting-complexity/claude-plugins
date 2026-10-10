#!/usr/bin/env python3
"""
Tests for the area label on one issue (#388).

Every issue carries exactly 1 `area: {name}` label, named after a row of the
`## Areas` table in `ClaudeProject.md`. Three things are tested here, all
offline:

  - the pure rules in `wf_core_labels`: which row a name means, and what has
    to be added and removed for an issue to carry that label and no other;
  - `validate_spec` with an areas table: what `issue-apply` refuses before it
    writes anything;
  - `wf area-set`, with the GitHub read, the `gh` writes and the request to
    Jev all replaced, so no test reaches a real issue or the Jev service.

`issue-apply` itself, against the in-memory hub, is in `test_io_shell.py`.
"""

import contextlib
import io
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
import wf  # noqa: E402
import wf_core  # noqa: E402
import wf_jev  # noqa: E402


_AREAS = [
    {'name': 'Library', 'description': 'Books, shelves and importing'},
    {'name': 'Listening', 'description': 'Playback and voices'},
]

_FIELDS = {
    'Priority': {'id': 'F_pri', 'data_type': 'single-select',
                 'options': {'High': 'o_hi'}},
    'Effort': {'id': 'F_eff', 'data_type': 'single-select',
               'options': {'Medium': 'o_med'}},
    'Ownership': {'id': 'F_own', 'data_type': 'single-select',
                  'options': {'Code agent': 'o_code'}},
}
_TYPES = {'User Story': 'IT_story', 'Epic': 'IT_epic'}


def _entry(**over):
    entry = {'key': 'a', 'title': 'A story', 'kind': 'story',
             'fields': {'field-priority': 'High', 'field-effort': 'Medium',
                        'field-ownership': 'Code agent'}}
    entry.update(over)
    return entry


# ── pure rules ───────────────────────────────────────────────────────────────

class TestAreaRules(unittest.TestCase):

    def test_the_label_is_the_prefix_and_the_name(self):
        self.assertEqual(wf_core.area_label('Library'), 'area: Library')
        self.assertEqual(wf_core.area_label(' Library '), 'area: Library')

    def test_a_row_is_matched_trimmed_and_without_case(self):
        self.assertEqual(wf_core.area_row(_AREAS, '  library ')['name'], 'Library')
        self.assertEqual(wf_core.area_row(_AREAS, 'LISTENING')['name'], 'Listening')

    def test_a_name_the_table_lacks_matches_no_row(self):
        self.assertIsNone(wf_core.area_row(_AREAS, 'Syncing'))
        self.assertIsNone(wf_core.area_row(_AREAS, ''))
        self.assertIsNone(wf_core.area_row(_AREAS, None))
        self.assertIsNone(wf_core.area_row([], 'Library'))

    def test_only_area_labels_are_area_labels(self):
        self.assertEqual(
            wf_core.area_labels_on(['bug', 'area: Library', 'Area: Old',
                                    'release: web', 'areas']),
            ['area: Library', 'Area: Old'])

    def test_an_issue_with_no_area_label_gains_one(self):
        self.assertEqual(wf_core.area_label_edit(['bug'], 'area: Library'),
                         (['area: Library'], []))

    def test_an_issue_with_the_label_is_left_alone(self):
        self.assertEqual(wf_core.area_label_edit(['area: Library', 'bug'],
                                                 'area: Library'), ([], []))

    def test_the_same_label_in_another_case_is_the_same_label(self):
        self.assertEqual(wf_core.area_label_edit(['Area: library'],
                                                 'area: Library'), ([], []))

    def test_another_area_is_replaced(self):
        self.assertEqual(wf_core.area_label_edit(['area: Listening', 'bug'],
                                                 'area: Library'),
                         (['area: Library'], ['area: Listening']))

    def test_two_present_leave_only_the_wanted_one(self):
        self.assertEqual(
            wf_core.area_label_edit(['area: Library', 'area: Listening'],
                                    'area: Library'),
            ([], ['area: Listening']))
        self.assertEqual(
            wf_core.area_label_edit(['area: Old', 'area: Listening'],
                                    'area: Library'),
            (['area: Library'], ['area: Old', 'area: Listening']))


# ── validate_spec with an areas table ────────────────────────────────────────

class TestSpecArea(unittest.TestCase):

    def _validate(self, entries, areas=_AREAS):
        return wf_core.validate_spec(entries, _FIELDS, _TYPES, {}, areas=areas)

    def test_a_named_area_lands_on_the_plan_in_the_rows_spelling(self):
        errors, _, plans = self._validate([_entry(area=' library')])
        self.assertEqual(errors, [])
        self.assertEqual(plans[0]['area'], 'Library')

    def test_an_unknown_name_is_refused_with_the_valid_ones(self):
        errors, _, _ = self._validate([_entry(area='Syncing')])
        self.assertEqual(errors, ["a: area 'Syncing' is not in the Areas table "
                                  '(valid: Library, Listening)'])

    def test_a_create_with_no_area_is_refused(self):
        errors, _, _ = self._validate([_entry()])
        self.assertEqual(len(errors), 1)
        self.assertIn('a: missing `area`', errors[0])
        self.assertIn('Library, Listening', errors[0])

    def test_an_update_with_no_area_passes(self):
        errors, _, plans = self._validate([{'number': 7, 'fields': {
            'field-priority': 'High'}}])
        self.assertEqual(errors, [])
        self.assertIsNone(plans[0]['area'])

    def test_an_area_epic_is_exempt(self):
        errors, _, plans = self._validate([
            {'key': 'lib', 'title': 'Library', 'type': 'Epic', 'state': 'area'}])
        self.assertEqual(errors, [])
        self.assertIsNone(plans[0]['area'])

    def test_an_area_label_in_labels_is_refused(self):
        errors, _, _ = self._validate([_entry(area='Library',
                                              labels=['Area: Listening'])])
        self.assertEqual(len(errors), 1)
        self.assertIn('use the `area` key', errors[0])
        self.assertIn("'Area: Listening'", errors[0])

    def test_an_area_that_is_not_a_name_is_refused(self):
        for value in ('', '  ', 3, ['Library']):
            errors, _, _ = self._validate([_entry(area=value)])
            self.assertEqual(len(errors), 1, value)
            self.assertIn('`area` must be the name', errors[0])

    def test_no_table_asks_nothing_about_areas(self):
        for areas in (None, []):
            errors, _, plans = self._validate(
                [_entry(labels=['area: mine'])], areas=areas)
            self.assertEqual(errors, [])
            self.assertIsNone(plans[0]['area'])

    def test_an_area_with_no_table_is_refused(self):
        for areas in (None, []):
            errors, _, _ = self._validate([_entry(area='Library')], areas=areas)
            self.assertEqual(len(errors), 1)
            self.assertIn('no Areas table', errors[0])


# ── wf area-set ──────────────────────────────────────────────────────────────

_CFG = {'org': 'acme', 'repo': 'widgets', 'labels': {}, 'fields': {},
        'areas': _AREAS}


class _Repo(object):
    """The issues `area-set` reads and edits, held in memory.

    `gh_graphql_partial` serves the aliased read, and `run` serves the
    `gh issue view` Jev's items come from and applies each `gh issue edit`,
    so a second run reads what the first one wrote.
    """

    def __init__(self, issues, missing_label=None):
        self.issues = {n: {'title': t, 'labels': list(labels)}
                       for n, (t, labels) in issues.items()}
        self.edits = []
        self.views = []
        self.missing_label = missing_label

    def gh_graphql_partial(self, query, **fields):
        repository = {}
        for alias, number in re.findall(r'(a\d+): issue\(number:(\d+)\)', query):
            issue = self.issues.get(int(number))
            repository[alias] = {
                'number': int(number), 'title': issue['title'],
                'labels': {'nodes': [{'name': n} for n in issue['labels']]},
            } if issue else None
        return {'repository': repository}, [], ''

    def run(self, cmd, input_text=None):
        if cmd[:3] == ['gh', 'issue', 'view']:
            number = int(cmd[3])
            self.views.append(number)
            return 0, json.dumps({'number': number,
                                  'title': self.issues[number]['title'],
                                  'body': 'A body.'}), ''
        if cmd[:3] == ['gh', 'issue', 'edit']:
            number = int(cmd[3])
            self.edits.append(list(cmd))
            flags = list(zip(cmd[6::2], cmd[7::2]))
            if any(f == '--add-label' and v == self.missing_label
                   for f, v in flags):
                return 1, '', ("could not add label: '%s' not found"
                               % self.missing_label)
            labels = self.issues[number]['labels']
            for flag, value in flags:
                if flag == '--add-label' and value not in labels:
                    labels.append(value)
                elif flag == '--remove-label' and value in labels:
                    labels.remove(value)
            return 0, '', ''
        raise AssertionError('unexpected command: %s' % cmd)


def _answers(*choices):
    """A Jev response: one `(choice, confidence)` per question, in order."""
    return (True, {'answers': {'q%d' % n: {'choice': c, 'confidence': p}
                               for n, (c, p) in enumerate(choices)}})


class TestAreaSet(unittest.TestCase):

    def _run(self, argv, repo, key='', post=None, cfg=None):
        args = wf.build_parser().parse_args(['area-set', *argv])
        post = post or mock.Mock(side_effect=AssertionError('Jev was asked'))
        cfg = _CFG if cfg is None else cfg
        buf = io.StringIO()
        code = None
        with mock.patch.dict(os.environ, {wf_jev.JEV_KEY_ENV: key}), \
                mock.patch.object(wf, 'load_config', lambda: (True, cfg, '')), \
                mock.patch.object(wf, 'gh_graphql_partial',
                                  repo.gh_graphql_partial), \
                mock.patch.object(wf, 'run', repo.run), \
                mock.patch.object(wf, 'jev_post', post), \
                contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                args.func(args)
            except SystemExit as exc:
                code = exc.code
        self.post = post
        return code, json.loads(buf.getvalue())

    def test_an_issue_with_its_label_is_kept_and_nothing_is_written(self):
        repo = _Repo({5: ('Import a book', ['bug', 'area: Library'])})
        code, payload = self._run(['--issue', '5'], repo, key='k')
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload, {'status': 'ok', 'issues': [
            {'number': 5, 'title': 'Import a book', 'area': 'Library',
             'action': 'kept', 'source': 'label'}]})
        self.assertEqual((repo.edits, repo.views), ([], []))

    def test_no_key_gives_choose_with_the_rows_and_asks_jev_nothing(self):
        repo = _Repo({5: ('Import a book', [])})
        code, payload = self._run(['--issue', '5'], repo)
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual(payload['status'], 'choose')
        self.assertEqual(payload['choose'],
                         [{'number': 5, 'title': 'Import a book'}])
        self.assertEqual(payload['rows'], [
            {'name': 'Library', 'description': 'Books, shelves and importing'},
            {'name': 'Listening', 'description': 'Playback and voices'}])
        self.assertEqual(payload['jev'], 'unavailable')
        self.assertEqual((repo.edits, repo.views), ([], []))

    def test_a_high_answer_is_written(self):
        repo = _Repo({5: ('Import a book', ['bug'])})
        code, payload = self._run(['--issue', '5'], repo, key='k',
                                  post=mock.Mock(return_value=_answers(
                                      ('Library', 0.95))))
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(payload['issues'], [
            {'number': 5, 'title': 'Import a book', 'area': 'Library',
             'action': 'set', 'source': 'jev'}])
        self.assertEqual(payload['jev'], 'used')
        self.assertEqual(repo.edits, [['gh', 'issue', 'edit', '5', '--repo',
                                       'acme/widgets', '--add-label',
                                       'area: Library']])
        self.assertEqual(repo.issues[5]['labels'], ['bug', 'area: Library'])

    def test_a_medium_answer_and_unsure_are_left_to_the_caller(self):
        repo = _Repo({5: ('Import a book', []), 6: ('Something', [])})
        code, payload = self._run(
            ['--issue', '5', '--issue', '6'], repo, key='k',
            post=mock.Mock(return_value=_answers(('Library', 0.6),
                                                 ('unsure', 0.99))))
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual([c['number'] for c in payload['choose']], [5, 6])
        self.assertEqual(payload['jev'], 'not-sure')
        self.assertEqual(repo.edits, [])
        self.assertEqual(self.post.call_count, 1)

    def test_one_sure_and_one_not_writes_one_and_returns_the_other(self):
        repo = _Repo({5: ('Import a book', []), 6: ('Something', [])})
        code, payload = self._run(
            ['--issue', '5', '--issue', '6'], repo, key='k',
            post=mock.Mock(return_value=_answers(('Listening', 0.9),
                                                 ('Library', 0.3))))
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual([(i['number'], i['area']) for i in payload['issues']],
                         [(5, 'Listening')])
        self.assertEqual([c['number'] for c in payload['choose']], [6])
        self.assertEqual(repo.issues[5]['labels'], ['area: Listening'])

    def test_jev_that_does_not_answer_gives_choose(self):
        repo = _Repo({5: ('Import a book', [])})
        code, payload = self._run(['--issue', '5'], repo, key='k',
                                  post=mock.Mock(return_value=(False, 'HTTP 500')))
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual(payload['jev'], 'unavailable')
        self.assertEqual(repo.edits, [])

    def test_jev_off_gives_choose_and_sends_nothing(self):
        repo = _Repo({5: ('Import a book', [])})
        code, payload = self._run(['--issue', '5'], repo, key='k',
                                  cfg=dict(_CFG, jev='off'))
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual(payload['jev'], 'unavailable')
        self.assertEqual(repo.views, [])
        self.post.assert_not_called()

    def test_area_writes_and_a_second_call_is_kept(self):
        repo = _Repo({5: ('Import a book', [])})
        code, payload = self._run(['--issue', '5', '--area', 'library'], repo)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['issues'], [
            {'number': 5, 'title': 'Import a book', 'area': 'Library',
             'action': 'set', 'source': 'caller'}])
        self.assertNotIn('jev', payload)
        code, payload = self._run(['--issue', '5', '--area', 'Library'], repo)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['issues'][0]['action'], 'kept')
        self.assertEqual(len(repo.edits), 1)
        code, payload = self._run(['--issue', '5'], repo)
        self.assertEqual(payload['issues'][0]['action'], 'kept')
        self.assertEqual(payload['issues'][0]['source'], 'label')

    def test_area_replaces_another_area_in_one_call(self):
        repo = _Repo({5: ('Import a book', ['area: Listening', 'bug'])})
        code, payload = self._run(['--issue', '5', '--area', 'Library'], repo)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['issues'][0]['action'], 'replaced')
        self.assertEqual(repo.edits, [['gh', 'issue', 'edit', '5', '--repo',
                                       'acme/widgets', '--add-label',
                                       'area: Library', '--remove-label',
                                       'area: Listening']])
        self.assertEqual(repo.issues[5]['labels'], ['bug', 'area: Library'])

    def test_two_area_labels_are_not_kept(self):
        repo = _Repo({5: ('Import a book', ['area: Listening', 'area: Library'])})
        code, payload = self._run(['--issue', '5'], repo)
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual([c['number'] for c in payload['choose']], [5])

    def test_an_unknown_area_is_refused_with_the_rows(self):
        repo = _Repo({5: ('Import a book', [])})
        code, payload = self._run(['--issue', '5', '--area', 'Syncing'], repo)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertEqual(payload['status'], 'spec-invalid')
        self.assertEqual([r['name'] for r in payload['rows']],
                         ['Library', 'Listening'])
        self.assertEqual(repo.edits, [])

    def test_area_with_two_issues_is_a_usage_error(self):
        repo = _Repo({5: ('a', []), 6: ('b', [])})
        code, payload = self._run(
            ['--issue', '5', '--issue', '6', '--area', 'Library'], repo)
        self.assertEqual(code, wf.EXIT_USAGE)
        self.assertEqual(repo.edits, [])

    def test_no_table_is_ok_and_reads_nothing(self):
        repo = _Repo({5: ('Import a book', [])})
        repo.gh_graphql_partial = mock.Mock(
            side_effect=AssertionError('nothing to read without a table'))
        code, payload = self._run(['--issue', '5'], repo, key='k',
                                  cfg=dict(_CFG, areas=[]))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')
        self.assertIn('no Areas table', payload['reason'])

    def test_a_label_the_repository_lacks_is_partial_and_names_the_fix(self):
        repo = _Repo({5: ('Import a book', [])}, missing_label='area: Library')
        code, payload = self._run(['--issue', '5', '--area', 'Library'], repo)
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertEqual(payload['status'], 'partial')
        self.assertIn('wf labels-ensure', payload['failed'][0]['error'])
        self.assertEqual(payload['issues'], [])

    def test_an_issue_that_cannot_be_read_is_an_error(self):
        repo = _Repo({})
        code, payload = self._run(['--issue', '9'], repo)
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertIn('#9', payload['reason'])


if __name__ == '__main__':
    unittest.main()
