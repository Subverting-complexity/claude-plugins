#!/usr/bin/env python3
"""
Tests for `wf jev`, the optional checks a workflow may ask Jev, the TypeSafe
decision model.

Nothing here reaches the network: the request builder and the routing are pure,
and the command is run with `jev_post` replaced. The rule that matters most is
that Jev is never required, so a missing key and a failed call both end as
`unavailable`, the result every caller reads as "decide without it".

The `area` and `target` checks take their answers from tables in
`ClaudeProject.md`. A test of either check replaces `load_config`, so it holds
whatever tables this repository's own file has.

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
AREAS = [{'name': 'billing', 'description': 'Invoices and payments', 'colour': '',
          'epic': '', 'was': ''},
         {'name': 'mobile-app', 'description': 'The iOS and Android apps', 'colour': '',
          'epic': '', 'was': ''}]
TARGETS = [{'name': 'web', 'description': 'The browser app', 'colour': ''},
           {'name': 'mobile', 'description': 'The apps in the two app stores', 'colour': ''}]


def tables(areas=(), targets=(), jev='on'):
    """Replace `load_config` with a project that has these tables."""
    cfg = {'areas': list(areas), 'release_targets': list(targets), 'jev': jev}
    return mock.patch.object(wf, 'load_config', lambda: (True, cfg, ''))


def resolved(check):
    """The configuration with `check` filled in from the tables above."""
    return wf_core.jev_resolve(CONFIG, check, AREAS if check == 'area' else TARGETS)


def text_length(item):
    """Every character of an item that is sent: its strings and its folders."""
    return (sum(len(v) for v in item.values() if isinstance(v, str))
            + sum(len(folder) for folder in item.get('folders', ())))


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
            self.assertIn(check['per'], ('item', 'pair', 'rule', 'item-target'), name)
            self.assertIn(check['type'], ('noul', 'score', 'choice'), name)
            if check['type'] == 'score':
                self.assertTrue(2 <= len(check['levels']) <= 10, name)
            if check['per'] == 'rule':
                self.assertTrue(check['rules'], name)

    def test_a_check_filled_from_a_table_names_a_table_and_keeps_its_fixed_text(self):
        for name, check in CONFIG['checks'].items():
            # Only a choice has options to fill, and only a check of items and
            # targets has targets: neither marker may sit on another shape.
            if 'options_from' in check:
                self.assertEqual(check['type'], 'choice', name)
                self.assertIn(check['options_from'], ('areas', 'release_targets'), name)
            self.assertEqual('targets_from' in check, check['per'] == 'item-target', name)
            if check['per'] == 'item-target':
                self.assertEqual(check['type'], 'noul', name)
                self.assertIn(check['targets_from'], ('areas', 'release_targets'), name)
                self.assertNotIn('targets', check, name)
                for field in ('{path}', '{target}'):
                    self.assertIn(field, check['instructions'], name)
                for field in ('{target}', '{description}'):
                    self.assertIn(field, check['describe'], name)
            elif check['per'] in ('item', 'pair'):
                self.assertTrue(check['instructions'], name)

    def test_the_area_and_target_checks_read_the_tables_they_are_named_for(self):
        self.assertEqual(wf_core.jev_table_needed(CONFIG, 'area'), 'areas')
        self.assertEqual(wf_core.jev_table_needed(CONFIG, 'target'), 'release_targets')
        self.assertIsNone(wf_core.jev_table_needed(CONFIG, 'priority'))
        self.assertIsNone(wf_core.jev_table_needed(CONFIG, 'nope'))

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


class TableCheckTests(unittest.TestCase):
    """`area` and `target`: the two checks whose answers come from a table."""

    def test_area_offers_the_table_rows_and_unsure(self):
        (body, refs), = wf_core.jev_requests(resolved('area'), 'area', ITEMS)
        self.assertEqual(sorted(refs.values()), ['41', '43'])
        question = body['questions']['q0']
        self.assertEqual(question['type'], 'choice')
        self.assertIn('`items.i41`', question['instructions'])
        self.assertEqual(list(question['criteria']), ['billing', 'mobile-app', 'unsure'])
        self.assertEqual(question['criteria']['billing'], 'Invoices and payments')

    def test_filling_a_check_in_leaves_the_loaded_configuration_alone(self):
        resolved('area')
        resolved('target')
        self.assertEqual(list(CONFIG['checks']['area']['options']), ['unsure'])
        self.assertNotIn('targets', CONFIG['checks']['target'])
        self.assertIs(wf_core.jev_resolve(CONFIG, 'priority', AREAS), CONFIG)

    def test_a_row_with_no_description_is_described_by_its_name(self):
        config = wf_core.jev_resolve(CONFIG, 'area', [{'name': 'api', 'description': ''}])
        self.assertEqual(config['checks']['area']['options']['api'], 'api')

    def test_a_row_with_no_name_is_not_a_row(self):
        rows = [{'name': '', 'description': 'x'}, {'name': 'api'}, {'name': 'api'}]
        self.assertEqual(wf_core.jev_table_rows(rows), [('api', '')])
        self.assertEqual(wf_core.jev_table_rows(None), [])

    def test_target_asks_one_yes_or_no_per_item_and_target(self):
        (body, refs), = wf_core.jev_requests(resolved('target'), 'target', ITEMS)
        self.assertEqual(list(refs.values()), [['41', 'web'], ['41', 'mobile'],
                                               ['43', 'web'], ['43', 'mobile']])
        self.assertEqual(set(body['state']['items']), {'i41', 'i43'})
        question = body['questions']['q1']
        self.assertEqual(question['type'], 'noul')
        self.assertNotIn('criteria', question)
        self.assertIn('`items.i41`', question['instructions'])
        self.assertIn('`mobile`', question['instructions'])
        self.assertIn('The apps in the two app stores', question['instructions'])
        self.assertNotIn('{', question['instructions'])

    def test_a_target_description_with_a_brace_is_sent_as_text(self):
        config = wf_core.jev_resolve(CONFIG, 'target',
                                     [{'name': 'web', 'description': 'Served from {cdn}'}])
        (body, _), = wf_core.jev_requests(config, 'target', ITEMS)
        self.assertIn('Served from {cdn}', body['questions']['q0']['instructions'])

    def test_a_target_with_no_description_is_asked_by_name_alone(self):
        config = wf_core.jev_resolve(CONFIG, 'target', [{'name': 'web', 'description': ''}])
        (body, _), = wf_core.jev_requests(config, 'target', ITEMS)
        self.assertTrue(body['questions']['q0']['instructions'].endswith('`web`?'))

    def test_target_questions_are_cut_into_batches_with_only_their_items(self):
        payload = {'items': [{'id': n, 'title': 't%d' % n} for n in range(15)]}
        requests = wf_core.jev_requests(resolved('target'), 'target', payload)
        self.assertEqual([len(b['questions']) for b, _ in requests], [20, 10])
        self.assertEqual(len(requests[0][0]['state']['items']), 10)
        self.assertEqual(len(requests[1][0]['state']['items']), 5)

    def test_paths_are_reduced_to_distinct_folders_in_order(self):
        paths = ['src/api/a.py', 'src/api/b.py', 'README.md', './docs/guide/x.md',
                 'src\\win\\z.py', 'src/api/deep/c.py', 'LICENSE', '', '/abs/file.txt']
        self.assertEqual(wf_core.jev_folders(paths),
                         ['src/api', wf_core.JEV_ROOT_FOLDER, 'docs/guide', 'src/win',
                          'src/api/deep', 'abs'])

    def test_a_target_item_sends_folders_and_never_the_paths(self):
        payload = {'items': [{'id': 41, 'title': 'Login fails',
                              'paths': ['apps/web/login.tsx', 'apps/web/form.tsx',
                                        'apps/ios/Login.swift']}]}
        (body, _), = wf_core.jev_requests(resolved('target'), 'target', payload)
        self.assertEqual(body['state']['items']['i41'],
                         {'title': 'Login fails', 'folders': ['apps/web', 'apps/ios']})

    def test_a_long_paths_list_is_sent_as_folders_inside_the_limit(self):
        limit = CONFIG['max_text']
        paths = ['packages/module-%04d/src/components/file-%d.ts' % (n // 2, n)
                 for n in range(1200)]
        self.assertGreater(sum(len(path) for path in paths), 10 * limit)
        payload = {'items': [{'id': 41, 'title': 'Rename a helper', 'body': 'Short.',
                              'paths': paths}]}
        (body, _), = wf_core.jev_requests(resolved('target'), 'target', payload)
        item = body['state']['items']['i41']
        self.assertNotIn('paths', item)
        self.assertLessEqual(text_length(item), limit)
        self.assertLessEqual(len(', '.join(item['folders'])) + len('Rename a helper')
                             + len('Short.'), limit)
        every = wf_core.jev_folders(paths)
        self.assertEqual(len(every), 600)
        # What is sent is the start of the list, whole folders only, and the
        # item says how many it left out.
        self.assertEqual(item['folders'], every[:len(item['folders'])])
        self.assertGreater(len(item['folders']), 20)
        self.assertEqual(item['folders_left_out'], 600 - len(item['folders']))
        self.assertEqual((item['title'], item['body']), ('Rename a helper', 'Short.'))

    def test_a_long_body_and_a_long_paths_list_share_the_limit(self):
        limit = CONFIG['max_text']
        payload = {'items': [{'id': 41, 'title': 'T' * 50, 'body': 'x' * 10000,
                              'paths': ['dir-%04d/sub/f.py' % n for n in range(500)]}]}
        (body, _), = wf_core.jev_requests(resolved('target'), 'target', payload)
        item = body['state']['items']['i41']
        self.assertLessEqual(text_length(item) + 2 * (len(item['folders']) - 1), limit)
        self.assertEqual(item['title'], 'T' * 50)
        self.assertTrue(item['body'].endswith(' …'))
        # The folders keep half the limit however long the body is.
        self.assertGreater(len(', '.join(item['folders'])), limit // 2 - 20)
        self.assertGreater(len(item['body']), limit // 2 - 100)

    def test_a_target_item_with_no_paths_is_still_held_to_the_limit(self):
        payload = {'items': [{'id': 1, 'title': 'T', 'body': 'x' * 10000}]}
        (body, _), = wf_core.jev_requests(resolved('target'), 'target', payload)
        item = body['state']['items']['i1']
        self.assertNotIn('folders', item)
        self.assertEqual(text_length(item), CONFIG['max_text'])

    def test_one_folder_longer_than_the_limit_is_left_out_whole(self):
        kept, left_out = wf_core.jev_fit_folders(['a' * 50, 'b'], 10)
        self.assertEqual((kept, left_out), ([], 2))
        self.assertEqual(wf_core.jev_fit_folders(['aa', 'bb', 'cc'], 6), (['aa', 'bb'], 1))

    def test_paths_must_be_a_list_of_strings(self):
        for paths in ('src/a.py', [1, 2], {'a': 1}):
            problem = wf_core.jev_input_problem(resolved('target'), 'target',
                                                {'items': [{'id': 1, 'paths': paths}]})
            self.assertIn('paths', problem)
        self.assertIsNone(wf_core.jev_input_problem(
            resolved('target'), 'target', {'items': [{'id': 1, 'paths': ['a/b.py']}]}))
        self.assertIn('items', wf_core.jev_input_problem(resolved('target'), 'target', {}))

    def test_a_target_row_names_the_item_and_the_target(self):
        rows = wf_core.jev_rows(resolved('target'), 'target',
                                {'q0': ['41', 'web'], 'q1': ['41', 'mobile']},
                                {'q0': {'noul': 0.97}, 'q1': {'noul': 0.02}})
        self.assertEqual(rows, [
            {'id': '41', 'target': 'web', 'answer': True, 'probability': 0.97,
             'level': 'high'},
            {'id': '41', 'target': 'mobile', 'answer': False, 'probability': 0.02,
             'level': 'high'}])

    def test_every_target_row_is_worth_reading_the_sure_noes_too(self):
        config = resolved('target')
        rows = wf_core.jev_rows(config, 'target', {'q0': ['41', 'web'], 'q1': ['41', 'mobile']},
                                {'q0': {'noul': 0.97}, 'q1': {'noul': 0.02}})
        self.assertEqual(wf_core.jev_rows_worth_reading(config, 'target', rows), rows)

    def test_an_area_row_names_the_area(self):
        rows = wf_core.jev_rows(resolved('area'), 'area', {'q0': '41'},
                                {'q0': {'choice': 'billing', 'confidence': 0.91}})
        self.assertEqual(rows, [{'id': '41', 'answer': 'billing', 'confidence': 0.91,
                                 'level': 'high'}])


class TableCommandTests(unittest.TestCase):
    """`wf jev --check area` and `--check target`, end to end with no network."""

    def assert_unavailable(self, check, post, **kwargs):
        gh = mock.Mock()
        with mock.patch.object(wf, 'gh_json', gh):
            code, out = run_jev(check, ITEMS, post=post, issue=[41], **kwargs)
        self.assertEqual((code, out['status']), (30, 'unavailable'), check)
        self.assertEqual(code, wf.EXIT_UNSUPPORTED)
        post.assert_not_called()
        gh.assert_not_called()
        return out['reason']

    def test_area_answers_one_area_for_an_issue_read_from_github(self):
        seen = []

        def post(body, key):
            seen.append(body)
            return True, {'answers': {'q0': {'choice': 'mobile-app', 'confidence': 0.93}}}

        def gh(argv):
            return True, {'number': 41, 'title': 'Login fails', 'body': 'On iOS.'}, ''
        with tables(areas=AREAS), mock.patch.object(wf, 'gh_json', gh):
            code, out = run_jev('area', {}, post=post, issue=[41])
        self.assertEqual((code, out['status']), (0, 'ok'))
        self.assertEqual(out['results'], [{'id': '41', 'answer': 'mobile-app',
                                           'confidence': 0.93, 'level': 'high',
                                           'title': 'Login fails'}])
        self.assertEqual(list(seen[0]['questions']['q0']['criteria']),
                         ['billing', 'mobile-app', 'unsure'])

    def test_area_can_answer_unsure(self):
        def post(body, key):
            return True, {'answers': {name: {'choice': 'unsure', 'confidence': 0.6}
                                      for name in body['questions']}}
        with tables(areas=AREAS):
            code, out = run_jev('area', ITEMS, post=post)
        self.assertEqual(code, 0)
        self.assertEqual({(r['answer'], r['level']) for r in out['results']},
                         {('unsure', 'medium')})

    def test_target_answers_every_target_and_an_item_can_get_yes_for_two(self):
        yes = {('41', 'web'): 0.96, ('41', 'mobile'): 0.93,
               ('43', 'web'): 0.98, ('43', 'mobile'): 0.03}

        def post(body, key):
            answers = {}
            for name, question in body['questions'].items():
                item = '41' if '`items.i41`' in question['instructions'] else '43'
                target = 'mobile' if '`mobile`' in question['instructions'] else 'web'
                answers[name] = {'noul': yes[(item, target)]}
            return True, {'answers': answers}
        with tables(targets=TARGETS):
            code, out = run_jev('target', ITEMS, post=post)
        self.assertEqual((code, out['status']), (0, 'ok'))
        got = {(r['id'], r['target']): (r['answer'], r['level']) for r in out['results']}
        self.assertEqual(got, {('41', 'web'): (True, 'high'), ('41', 'mobile'): (True, 'high'),
                               ('43', 'web'): (True, 'high'), ('43', 'mobile'): (False, 'high')})
        # The sure no is listed, not counted away.
        self.assertEqual(out['sure_no'], 0)
        self.assertEqual(out['summary']['high'], 4)
        self.assertEqual(out['results'][0]['title'], 'Login fails')

    def test_target_sends_a_long_paths_list_as_folders_inside_the_limit(self):
        seen = []

        def post(body, key):
            seen.append(body)
            return True, {'answers': {n: {'noul': 0.5} for n in body['questions']}}
        payload = {'items': [{'id': 41, 'title': 'Big change', 'body': 'b' * 5000,
                              'paths': ['services/svc-%04d/internal/handlers/h%d.go' % (n // 3, n)
                                        for n in range(3000)]}]}
        with tables(targets=TARGETS):
            code, _ = run_jev('target', payload, post=post)
        self.assertEqual(code, 0)
        item = seen[0]['state']['items']['i41']
        self.assertNotIn('paths', item)
        self.assertLessEqual(text_length(item), CONFIG['max_text'])
        self.assertTrue(all(folder.startswith('services/svc-') and folder.endswith('/handlers')
                            for folder in item['folders']))

    def test_an_empty_table_is_unavailable_before_any_read_or_request(self):
        for check, table in (('area', 'Areas'), ('target', 'Release Targets')):
            with tables():
                reason = self.assert_unavailable(check, mock.Mock())
            self.assertIn(table, reason)
            self.assertIn('without Jev', reason)

    def test_the_other_table_does_not_stand_in_for_the_one_a_check_needs(self):
        with tables(targets=TARGETS):
            self.assertIn('Areas', self.assert_unavailable('area', mock.Mock()))
        with tables(areas=AREAS):
            self.assertIn('Release Targets', self.assert_unavailable('target', mock.Mock()))

    def test_a_project_with_no_configuration_has_no_tables(self):
        with mock.patch.object(wf, 'load_config', lambda: (False, None, 'no ClaudeProject.md')):
            for check in ('area', 'target'):
                self.assertIn('table', self.assert_unavailable(check, mock.Mock()))

    def test_jev_switched_off_is_unavailable_and_is_said_before_the_table(self):
        for check in ('area', 'target'):
            with tables(areas=AREAS, targets=TARGETS, jev='off'):
                self.assertIn('off', self.assert_unavailable(check, mock.Mock()))
            with tables(jev='off'):
                self.assertIn('off', self.assert_unavailable(check, mock.Mock()))

    def test_no_key_is_unavailable_and_is_said_before_the_table(self):
        for check in ('area', 'target'):
            with tables(areas=AREAS, targets=TARGETS):
                reason = self.assert_unavailable(check, mock.Mock(), key=None)
            self.assertIn(wf_jev.JEV_KEY_ENV, reason)
            with tables():
                reason = self.assert_unavailable(check, mock.Mock(), key=None)
            self.assertIn(wf_jev.JEV_KEY_ENV, reason)

    def test_a_failed_call_is_unavailable(self):
        post = mock.Mock(return_value=(False, 'Jev answered HTTP 500'))
        with tables(areas=AREAS, targets=TARGETS):
            for check in ('area', 'target'):
                code, out = run_jev(check, ITEMS, post=post)
                self.assertEqual((code, out['status']), (30, 'unavailable'))


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

    def test_jev_off_holds_when_a_table_row_is_refused(self):
        # A repeated area name makes the file fail to load. The privacy switch
        # in the same file must still be obeyed, so nothing is sent.
        text = ('## Areas\n\n| Name | Description | Colour |\n| --- | --- | --- |\n'
                '| docs | One | ffffff |\n| docs | Two | 000000 |\n\n'
                '## Jev\n\n| Setting | Value |\n| --- | --- |\n| jev | off |\n')
        post = mock.Mock()
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'ClaudeProject.md'), 'w', encoding='utf-8') as fh:
                fh.write(text)
            with mock.patch.object(wf, 'repo_root', lambda: root):
                self.assertFalse(wf.load_config()[0])
                code, out = run_jev('priority', ITEMS, key='test-key', post=post)
        self.assertEqual((code, out['status']), (30, 'unavailable'))
        post.assert_not_called()

    def test_a_configuration_file_that_cannot_be_read_counts_as_off(self):
        post = mock.Mock()
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'ClaudeProject.md'), 'wb') as fh:
                fh.write(b'## Jev\n\n| jev | on |\n\xff\xfe\n')
            with mock.patch.object(wf, 'repo_root', lambda: root):
                code, out = run_jev('priority', ITEMS, key='test-key', post=post)
        self.assertEqual((code, out['status']), (30, 'unavailable'))
        post.assert_not_called()

    def test_a_project_with_no_configuration_file_leaves_jev_on(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(wf, 'repo_root', lambda: root):
            self.assertFalse(wf.jev_switched_off())

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
