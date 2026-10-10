#!/usr/bin/env python3
"""
Tests for `wf jev`, the optional checks a workflow may ask Jev, the TypeSafe
decision model.

Nothing here reaches the network: the request builder and the routing are pure,
and the command is run with `jev_post` replaced. The rule that matters most is
that Jev is never required, so a missing key and a failed call both end as
`unavailable`, the result every caller reads as "decide without it".

Run standalone (`python3 tests/test_jev.py`) or via `run-tests.sh`.
"""

import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'synergy', 'scripts'))

import wf  # noqa: E402
import wf_core  # noqa: E402
import wf_jev  # noqa: E402

CONFIG = wf_jev.load_jev_config()
ITEMS = {'items': [{'id': 41, 'title': 'Login fails', 'body': 'Blank page on Safari.'},
                   {'id': 43, 'title': 'Add export', 'body': 'Export a report as CSV.'}]}


def run_jev(check, payload, key='test-key', post=None, issue=None, open_issues=None):
    """Run `cmd_jev` on a payload. Returns (exit_code, parsed stdout)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'in.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {wf_jev.JEV_KEY_ENV: key or ''}), \
                mock.patch.object(wf, 'jev_post', post or mock.Mock()), \
                redirect_stdout(buf):
            try:
                wf.cmd_jev(types.SimpleNamespace(check=check, input=path, issue=issue,
                                                 open_issues=open_issues))
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, json.loads(buf.getvalue())


def level_names(check):
    return [level[0] for level in CONFIG['checks'][check]['levels']]


class ConfigTests(unittest.TestCase):

    def test_every_check_is_well_formed(self):
        for name, check in CONFIG['checks'].items():
            self.assertIn(check['per'], ('item', 'pair', 'rule'), name)
            self.assertIn(check['type'], ('noul', 'score', 'choice'), name)
            if check['type'] == 'score':
                self.assertTrue(2 <= len(check['levels']) <= 10, name)
            if check['per'] == 'rule':
                self.assertTrue(check['rules'], name)

    def test_a_choice_always_offers_a_way_out(self):
        for name, check in CONFIG['checks'].items():
            if check['type'] == 'choice':
                self.assertIn('unsure', check['options'], name)

    def test_the_priority_and_effort_levels_are_the_field_options(self):
        self.assertEqual(level_names('priority'), ['Low', 'Medium', 'High', 'Urgent'])
        self.assertEqual(level_names('effort'), ['Low', 'Medium', 'High'])


class RequestTests(unittest.TestCase):

    def test_an_item_check_asks_one_question_per_item(self):
        (body, refs), = wf_core.jev_requests(CONFIG, 'priority', ITEMS)
        self.assertEqual(sorted(refs.values()), ['41', '43'])
        self.assertEqual(set(body['state']['items']), {'i41', 'i43'})
        question = body['questions']['q0']
        self.assertEqual(question['type'], 'score')
        self.assertIn('`items.i41`', question['instructions'])
        self.assertEqual(len(question['criteria']), 4)

    def test_the_id_is_not_sent_as_part_of_the_item(self):
        (body, _), = wf_core.jev_requests(CONFIG, 'readiness', ITEMS)
        self.assertNotIn('id', body['state']['items']['i41'])

    def test_long_text_is_cut(self):
        payload = {'items': [{'id': 1, 'body': 'x' * 10000}]}
        (body, _), = wf_core.jev_requests(CONFIG, 'effort', payload)
        self.assertLess(len(body['state']['items']['i1']['body']), CONFIG['max_text'] + 10)

    def test_questions_are_cut_into_batches_with_only_their_items(self):
        payload = {'items': [{'id': n, 'title': 't%d' % n} for n in range(45)]}
        requests = wf_core.jev_requests(CONFIG, 'readiness', payload)
        self.assertEqual([len(b['questions']) for b, _ in requests], [20, 20, 5])
        self.assertEqual(len(requests[2][0]['state']['items']), 5)

    def test_a_pair_check_asks_both_directions(self):
        (body, refs), = wf_core.jev_requests(CONFIG, 'depends', ITEMS)
        self.assertEqual(sorted(refs.values()), [['41', '43'], ['43', '41']])
        self.assertEqual(body['questions']['q0']['type'], 'noul')

    def test_duplicate_puts_the_subject_in_the_state(self):
        payload = dict(ITEMS, subject={'title': 'Safari login is blank'})
        (body, _), = wf_core.jev_requests(CONFIG, 'duplicate', payload)
        self.assertEqual(body['state']['subject'], {'title': 'Safari login is blank'})

    def test_draft_asks_one_question_per_rule(self):
        (body, refs), = wf_core.jev_requests(CONFIG, 'draft', {'draft': 'Some text.'})
        self.assertEqual(set(refs.values()), set(CONFIG['checks']['draft']['rules']))
        self.assertEqual(body['state'], {'draft': 'Some text.'})


class InputTests(unittest.TestCase):

    def problem(self, check, payload):
        return wf_core.jev_input_problem(CONFIG, check, payload)

    def test_good_input_has_no_problem(self):
        self.assertIsNone(self.problem('priority', ITEMS))

    def test_bad_input_is_named(self):
        self.assertIn('unknown check', self.problem('nope', ITEMS))
        self.assertIn('items', self.problem('priority', {}))
        self.assertIn('"id"', self.problem('priority', {'items': [{'title': 'x'}]}))
        self.assertIn('unique', self.problem('priority', {'items': [{'id': 1}, {'id': 1}]}))
        self.assertIn('subject', self.problem('duplicate', ITEMS))
        self.assertIn('draft', self.problem('draft', {}))
        self.assertIn('two', self.problem('depends', {'items': [{'id': 1}]}))
        many = {'items': [{'id': n} for n in range(CONFIG['max_pair_items'] + 1)]}
        self.assertIn('at most', self.problem('depends', many))


class RoutingTests(unittest.TestCase):

    def test_confidence_levels(self):
        self.assertEqual(wf_core.jev_level(CONFIG, 'score', 0.8), 'high')
        self.assertEqual(wf_core.jev_level(CONFIG, 'choice', 0.79), 'medium')
        self.assertEqual(wf_core.jev_level(CONFIG, 'choice', 0.49), 'low')

    def test_a_yes_probability_is_judged_from_either_end(self):
        self.assertEqual(wf_core.jev_level(CONFIG, 'noul', 0.95), 'high')
        self.assertEqual(wf_core.jev_level(CONFIG, 'noul', 0.05), 'high')
        self.assertEqual(wf_core.jev_level(CONFIG, 'noul', 0.75), 'medium')
        self.assertEqual(wf_core.jev_level(CONFIG, 'noul', 0.5), 'low')

    def test_a_score_names_its_nearest_level_counted_from_zero(self):
        rows = wf_core.jev_rows(CONFIG, 'priority', {'q0': '41'},
                                {'q0': {'score': 2.6, 'confidence': 0.9}})
        self.assertEqual(rows, [{'id': '41', 'answer': 'Urgent', 'score': 2.6,
                                 'confidence': 0.9, 'level': 'high'}])

    def test_a_missing_or_broken_answer_is_low_with_no_answer(self):
        rows = wf_core.jev_rows(CONFIG, 'priority', {'q0': '41', 'q1': '43'},
                                {'q0': {'score': 'x'}})
        self.assertEqual([(r['answer'], r['level']) for r in rows], [(None, 'low')] * 2)

    def test_a_pair_row_names_the_pair(self):
        rows = wf_core.jev_rows(CONFIG, 'depends', {'q0': ['41', '43']}, {'q0': {'noul': 0.97}})
        self.assertEqual(rows, [{'pair': ['41', '43'], 'answer': True,
                                 'probability': 0.97, 'level': 'high'}])


class CommandTests(unittest.TestCase):

    def test_no_key_is_unavailable_and_asks_nothing(self):
        post = mock.Mock()
        code, out = run_jev('priority', ITEMS, key=None, post=post)
        self.assertEqual((code, out['status']), (wf.EXIT_UNSUPPORTED, 'unavailable'))
        post.assert_not_called()

    def test_a_failed_call_is_unavailable(self):
        post = mock.Mock(return_value=(False, 'Jev answered HTTP 401'))
        code, out = run_jev('priority', ITEMS, post=post)
        self.assertEqual((code, out['status']), (wf.EXIT_UNSUPPORTED, 'unavailable'))
        self.assertIn('401', out['reason'])

    def test_a_repository_that_turns_jev_off_is_unavailable_with_a_key_set(self):
        post = mock.Mock()
        with mock.patch.object(wf, 'load_config', lambda: (True, {'jev': 'off'}, '')):
            code, out = run_jev('priority', ITEMS, key='test-key', post=post)
        self.assertEqual((code, out['status']), (wf.EXIT_UNSUPPORTED, 'unavailable'))
        self.assertEqual(code, 30)
        self.assertIn('off', out['reason'])
        post.assert_not_called()

    def test_a_project_with_no_configuration_leaves_jev_on(self):
        post = mock.Mock(return_value=(False, 'Jev answered HTTP 401'))
        with mock.patch.object(wf, 'load_config', lambda: (False, None, 'no ClaudeProject.md')):
            _, out = run_jev('priority', ITEMS, post=post)
        self.assertIn('401', out['reason'])

    def test_bad_input_is_a_usage_error_before_any_call(self):
        post = mock.Mock()
        code, out = run_jev('duplicate', ITEMS, post=post)
        self.assertEqual((code, out['status']), (wf.EXIT_USAGE, 'usage'))
        post.assert_not_called()

    def test_answers_come_back_as_rows_with_a_summary(self):
        def post(body, key):
            answers = {name: {'score': 2.0, 'confidence': 0.9 if name == 'q0' else 0.3}
                       for name in body['questions']}
            return True, {'answers': answers, 'usage': {'input_tokens': 10, 'output_tokens': 2}}
        code, out = run_jev('readiness', ITEMS, post=post)
        self.assertEqual((code, out['status']), (0, 'ok'))
        self.assertEqual(out['summary'], {'high': 1, 'medium': 0, 'low': 1})
        self.assertEqual(out['usage'], {'input_tokens': 10, 'output_tokens': 2})
        self.assertEqual({r['answer'] for r in out['results']}, {'ready'})

    def test_sure_noes_are_counted_not_listed(self):
        def post(body, key):
            return True, {'answers': {'q0': {'noul': 0.99}, 'q1': {'noul': 0.02}}}
        payload = dict(ITEMS, subject={'title': 'Safari login is blank'})
        code, out = run_jev('duplicate', payload, post=post)
        self.assertEqual(code, 0)
        self.assertEqual(out['sure_no'], 1)
        self.assertEqual([(r['id'], r['title'], r['answer']) for r in out['results']],
                         [('41', 'Login fails', True)])
        self.assertEqual(out['summary']['high'], 2)

    def test_issues_can_be_read_from_github_instead_of_a_file(self):
        def gh(argv):
            if argv[:2] == ['issue', 'view']:
                return True, {'number': 7, 'title': 'Named', 'body': 'b'}, ''
            return True, [{'number': 7, 'title': 'Named', 'body': 'b'},
                          {'number': 9, 'title': 'Open', 'body': None}], ''
        seen = []

        def post(body, key):
            seen.append(body)
            return True, {'answers': {n: {'noul': 0.6} for n in body['questions']}}
        with mock.patch.object(wf, 'gh_json', gh):
            code, out = run_jev('duplicate', {'subject': {'title': 's'}}, post=post,
                                issue=[7], open_issues=50)
        self.assertEqual(code, 0)
        self.assertEqual(set(seen[0]['state']['items']), {'i7', 'i9'})
        self.assertEqual(sorted(r['id'] for r in out['results']), ['7', '9'])

    def test_a_github_read_that_fails_is_unavailable(self):
        with mock.patch.object(wf, 'gh_json', lambda argv: (False, None, 'no auth')):
            code, out = run_jev('readiness', {}, issue=[7])
        self.assertEqual((code, out['status']), (wf.EXIT_UNSUPPORTED, 'unavailable'))

    def test_the_key_is_never_printed(self):
        post = mock.Mock(return_value=(False, 'Jev answered HTTP 401'))
        _, out = run_jev('priority', ITEMS, key='secret-key-value', post=post)
        self.assertNotIn('secret-key-value', json.dumps(out))


if __name__ == '__main__':
    unittest.main()
