#!/usr/bin/env python3
"""Release-target labels on the issues a merged pull request closes (#390).

The targets are decided before the merge and ride in the release-notes file
as a `targets` list per issue. `post-merge` adds a `release: {target}` label
for each, `settle-merged` comes back for a merge that left an issue without
one, and `release-targets` gathers what the decision reads. A repository with
no release-targets table gets none of it.
"""

import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
sys.path.insert(0, os.path.dirname(__file__))
import wf  # noqa: E402
import wf_core  # noqa: E402
from test_io_shell import _capture, _cfg, _settle_graphql  # noqa: E402

TARGETS = [{'name': 'Mobile', 'description': 'The phone app', 'colour': ''},
           {'name': 'web', 'description': 'The site', 'colour': ''}]


class TestReleaseTargetNames(unittest.TestCase):

    def test_no_row_means_no_target_at_all(self):
        self.assertEqual(wf_core.release_target_names([]), [])
        self.assertEqual(wf_core.release_target_names(None), [])

    def test_internal_follows_the_rows(self):
        self.assertEqual(wf_core.release_target_names(TARGETS),
                         ['Mobile', 'web', 'internal'])

    def test_a_row_named_internal_is_not_repeated(self):
        rows = TARGETS + [{'name': 'Internal'}]
        self.assertEqual(wf_core.release_target_names(rows),
                         ['Mobile', 'web', 'Internal'])


class TestParseReleaseTargets(unittest.TestCase):

    def parse(self, data, rows=TARGETS):
        return wf_core.parse_release_targets(data, rows)

    def test_a_name_is_matched_without_case_and_spelt_as_the_table_has_it(self):
        targets, errors = self.parse({'5': {'targets': ['mobile', 'WEB']}})
        self.assertEqual((targets, errors), ({5: ['Mobile', 'web']}, []))

    def test_an_issue_can_have_more_than_1_target_and_each_counts_once(self):
        targets, _ = self.parse({'#5': {'targets': ['web', 'release: web', 'Mobile']}})
        self.assertEqual(targets, {5: ['web', 'Mobile']})

    def test_an_empty_list_means_internal(self):
        targets, errors = self.parse({'5': {'user': '* A thing.', 'targets': []}})
        self.assertEqual((targets, errors), ({5: ['internal']}, []))

    def test_an_entry_with_no_targets_key_is_left_out(self):
        self.assertEqual(self.parse({'5': {'user': '* A thing.'}}), ({}, []))

    def test_an_unknown_name_is_an_error_and_the_known_ones_still_apply(self):
        targets, errors = self.parse({'5': {'targets': ['web', 'desktop']}})
        self.assertEqual(targets, {5: ['web']})
        self.assertIn("'desktop'", errors[0])
        self.assertIn('Mobile, web, internal', errors[0])

    def test_only_unknown_names_is_not_a_decision_that_nothing_applies(self):
        targets, errors = self.parse({'5': {'targets': ['desktop']}})
        self.assertEqual(targets, {})
        self.assertEqual(len(errors), 1)

    def test_a_targets_value_that_is_not_a_list_of_names_is_an_error(self):
        targets, errors = self.parse({'5': {'targets': {'web': True}}})
        self.assertEqual(targets, {})
        self.assertEqual(len(errors), 1)

    def test_a_repository_with_no_table_reads_no_targets(self):
        self.assertEqual(self.parse({'5': {'targets': ['web']}}, rows=[]), ({}, []))

    def test_a_bad_key_or_entry_is_left_to_the_notes_parser(self):
        self.assertEqual(self.parse({'x': {'targets': []}, '6': 'text'}), ({}, []))

    def test_the_notes_parser_accepts_the_targets_key(self):
        notes, errors = wf_core.parse_release_notes(
            {'5': {'user': '* A thing.', 'targets': ['web']}})
        self.assertEqual((notes, errors), ({5: {'user': '* A thing.'}}, []))


class TestReleaseLabelRules(unittest.TestCase):

    def test_a_released_label_is_not_a_release_label(self):
        names = ['bug', 'release: web', 'released: web', 'Release: Mobile']
        self.assertEqual(wf_core.release_labels_on(names),
                         ['release: web', 'Release: Mobile'])

    def test_only_the_missing_labels_are_added(self):
        add = wf_core.release_label_add(['Release: Web', 'area: Api'],
                                        ['web', 'Mobile'])
        self.assertEqual(add, ['release: Mobile'])

    def test_nothing_is_added_when_every_label_is_there(self):
        self.assertEqual(wf_core.release_label_add(['release: web'], ['web']), [])


class TestStoryPaths(unittest.TestCase):

    def test_the_story_is_the_number_that_ends_the_first_line(self):
        message = ('feat: resolve labels by purpose key (#41)\n\nThe body names '
                   '#99.\n\nCo-Authored-By: Someone <s@example.com>')
        self.assertEqual(wf_core.commit_story(message), 41)

    def test_a_number_elsewhere_in_the_line_is_not_the_story(self):
        self.assertIsNone(wf_core.commit_story('fix (#41) the picker'))
        self.assertIsNone(wf_core.commit_story('chore: tidy up'))
        self.assertIsNone(wf_core.commit_story(''))

    def test_each_story_gets_the_paths_of_its_own_commits(self):
        commits = [
            {'message': 'feat: one (#41)', 'paths': ['app/a.ts', 'app/b.ts']},
            {'message': 'feat: two (#43)', 'paths': ['api/c.py']},
            {'message': 'fix: one again (#41)', 'paths': ['app/a.ts', 'web/d.ts']},
        ]
        self.assertEqual(wf_core.story_paths(commits, [41, 43]), {
            41: ['app/a.ts', 'app/b.ts', 'web/d.ts'], 43: ['api/c.py']})

    def test_a_commit_with_no_story_number_counts_for_no_story(self):
        commits = [{'message': 'chore: shared setup', 'paths': ['api/x.py']},
                   {'message': 'feat: elsewhere (#77)', 'paths': ['web/y.ts']}]
        self.assertEqual(wf_core.story_paths(commits, [41, 43]), {41: [], 43: []})


class TestPostMergeSetsReleaseLabels(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(os.remove, self.path)

    def _post_merge(self, notes=None, targets=TARGETS, comments=(), linked=(5,),
                    issues=None, edit_fails=False):
        argv = ['post-merge', '--pr', '50', '--no-unblock']
        if notes is not None:
            with open(self.path, 'w', encoding='utf-8') as fh:
                json.dump(notes, fh)
            argv += ['--notes', self.path]
        self.edits = []

        def fake_run(cmd, input_text=None):
            if cmd[:3] == ['gh', 'pr', 'view']:
                return 0, json.dumps({
                    'number': 50, 'state': 'MERGED', 'baseRefName': 'main',
                    'closingIssuesReferences': [{'number': n} for n in linked],
                    'comments': list(comments)}), ''
            if cmd[:3] == ['gh', 'issue', 'edit']:
                self.edits.append(cmd)
                return (1, '', "'release: web' not found") if edit_fails else (0, '', '')
            return _settle_graphql(cmd, input_text, state='CLOSED') or (0, '', '')

        patches = [
            mock.patch.object(wf, 'check_environment', return_value=None),
            mock.patch.object(wf, 'load_config', return_value=(
                True, _cfg(release_targets=targets), '')),
            mock.patch.object(wf, 'resolve_org_capabilities',
                              return_value=(True, {'field_map': {}}, '')),
            mock.patch.object(wf, 'set_stages', lambda cfg, wanted, ids=None, extra=None: {
                int(n): (True, 'Stage set to Done') for n in wanted}),
            mock.patch.object(wf, 'close_finished_ancestors', return_value=([], [])),
            mock.patch.object(wf, 'run', side_effect=fake_run),
        ]
        if issues is not None:
            patches.append(mock.patch.object(wf, 'read_linked_issues',
                                             return_value=issues))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        args = wf.build_parser().parse_args(argv)
        return _capture(args.func, args)

    def _labels(self, edit):
        return [edit[i + 1] for i, a in enumerate(edit) if a == '--add-label']

    def test_each_closed_issue_gets_a_label_for_each_of_its_targets(self):
        code, payload = self._post_merge(
            {'5': {'targets': ['web', 'mobile']}, '6': {'targets': ['web']}},
            linked=(5, 6))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([(e[3], self._labels(e)) for e in self.edits], [
            ('5', ['release: web', 'release: Mobile']), ('6', ['release: web'])])
        self.assertEqual(payload['release_labels'], {
            '5': ['release: web', 'release: Mobile'], '6': ['release: web']})

    def test_no_target_applies_sets_release_internal(self):
        code, _ = self._post_merge({'5': {'internal': '* Refactored.', 'targets': []}})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._labels(self.edits[0]), ['release: internal'])

    def test_a_repository_with_no_table_merges_as_before(self):
        code, payload = self._post_merge({'5': {'targets': ['web']}}, targets=[])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self.edits, [])
        self.assertNotIn('release_labels', payload)

    def test_no_table_and_no_targets_is_not_a_gap(self):
        code, _ = self._post_merge({'5': {'internal': '* Refactored.'}}, targets=[])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self.edits, [])

    def test_without_a_file_the_targets_come_from_the_pr_comment(self):
        """A merge from the queue has no agent and no file: the comment the
        run posted before the merge is what the labels are read from."""
        comments = [{'body': wf.NOTES_MARKER + '\nNotes.\n\n```json\n'
                             '{"5": {"internal": "* Refactored.", '
                             '"targets": ["web"]}}\n```'}]
        code, _ = self._post_merge(comments=comments)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._labels(self.edits[0]), ['release: web'])

    def test_an_issue_with_no_targets_and_no_label_is_a_gap(self):
        code, payload = self._post_merge({'5': {'internal': '* Refactored.'}})
        self.assertEqual(code, wf.EXIT_PARTIAL)
        fact = payload['settled'][0]['release_labels']
        self.assertTrue(fact['missing'])
        self.assertIn('no release targets', fact['error'])
        self.assertTrue(payload['settled'][0]['stage_set'])
        self.assertEqual(wf.missing_target_issues(payload), [5])

    def test_an_issue_that_already_has_a_release_label_is_not_a_gap(self):
        labelled = {5: (True, {'id': 'I_5', 'state': 'CLOSED', 'stage': 'Done',
                               'has_notes': True,
                               'labels': [{'id': 'L1', 'name': 'release: web'}]}, '')}
        code, _ = self._post_merge({}, issues=labelled)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self.edits, [])

    def test_a_label_the_issue_carries_is_not_written_again(self):
        labelled = {5: (True, {'id': 'I_5', 'state': 'CLOSED', 'stage': 'Done',
                               'has_notes': True,
                               'labels': [{'id': 'L1', 'name': 'release: web'}]}, '')}
        self._post_merge({'5': {'targets': ['web', 'mobile']}}, issues=labelled)
        self.assertEqual(self._labels(self.edits[0]), ['release: Mobile'])

    def test_a_refused_label_makes_the_result_partial_and_says_how_to_fix_it(self):
        code, payload = self._post_merge({'5': {'targets': ['web']}}, edit_fails=True)
        self.assertEqual(code, wf.EXIT_PARTIAL)
        fact = payload['settled'][0]['release_labels']
        self.assertIn('labels-ensure', fact['error'])
        self.assertNotIn('missing', fact)
        self.assertEqual(wf.missing_target_issues(payload), [])

    def test_an_unknown_target_is_reported(self):
        code, payload = self._post_merge({'5': {'targets': ['web', 'desktop']}})
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertIn("'desktop'", payload['release_target_errors'][0])
        self.assertEqual(self._labels(self.edits[0]), ['release: web'])


class TestSettleMergedChasesReleaseLabels(unittest.TestCase):

    def _sweep(self, labels, targets=TARGETS, post_merge_settled=None,
               post_merge_code=0):
        prs = [{'number': 50, 'closingIssuesReferences': [{'number': 5}]},
               {'number': 51, 'closingIssuesReferences': [{'number': 6}]}]
        issues = {n: (True, {'stage': 'Done', 'has_notes': True,
                             'labels': [{'name': name} for name in names]}, '')
                  for n, names in labels.items()}
        settled = []

        def post_merge(args):
            settled.append(args.pr)
            wf.emit('ok' if post_merge_code == 0 else 'partial', post_merge_code,
                    settled=post_merge_settled or [])

        args = wf.build_parser().parse_args(['settle-merged'])
        with mock.patch.object(wf, 'check_environment', return_value=None), \
                mock.patch.object(wf, 'load_config', return_value=(
                    True, _cfg(release_targets=targets), '')), \
                mock.patch.object(wf, 'gh_json', return_value=(True, prs, '')), \
                mock.patch.object(wf, 'read_linked_issues', return_value=issues), \
                mock.patch.object(wf, 'notes_fields_defined', return_value=True), \
                mock.patch.object(wf, 'cmd_post_merge', post_merge):
            code, payload = _capture(args.func, args)
        return code, payload, settled

    def test_a_done_issue_with_no_release_label_is_still_unsettled(self):
        code, _, settled = self._sweep({5: ['release: web'], 6: ['released: web']})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(settled, [51])

    def test_a_repository_with_no_table_never_chases_a_label(self):
        _, _, settled = self._sweep({5: [], 6: []}, targets=[])
        self.assertEqual(settled, [])

    def test_a_pr_still_without_targets_is_named_for_the_caller(self):
        entry = {'issue': 6, 'stage_set': True,
                 'release_labels': {'added': [], 'missing': True,
                                    'error': 'no release targets were supplied for #6'}}
        code, payload, _ = self._sweep(
            {5: ['release: web'], 6: []}, post_merge_code=wf.EXIT_PARTIAL,
            post_merge_settled=[entry])
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertEqual(payload['needs_targets'], [{'pr': 51, 'issues': [6]}])
        self.assertEqual(payload['needs_notes'], [])


class TestReleaseTargetsCommand(unittest.TestCase):

    COMMITS = [
        {'sha': 'aaa', 'commit': {'message': 'feat: one (#5)\n\nBody.'}},
        {'sha': 'bbb', 'commit': {'message': 'chore: shared setup'}},
        {'sha': 'ccc', 'commit': {'message': 'feat: two (#6)'}},
    ]
    FILES = {'aaa': ['app/a.ts', 'app/b.ts'], 'bbb': ['api/shared.py'],
             'ccc': ['site/c.ts']}

    def _run(self, linked=(5,), targets=TARGETS, jev=('unavailable', 'no key'),
             labels=()):
        self.calls, self.asked = [], []

        def fake_run(cmd, input_text=None):
            self.calls.append(cmd)
            if cmd[:3] == ['gh', 'pr', 'view']:
                return 0, json.dumps({
                    'number': 50,
                    'closingIssuesReferences': [{'number': n} for n in linked],
                    'files': [{'path': 'app/a.ts'}, {'path': 'README.md'}]}), ''
            if cmd[:3] == ['gh', 'api', 'graphql']:
                query = next((a for a in cmd if a.startswith('query=')), '')
                return 0, json.dumps({'data': {'repository': {
                    'r%s' % n: {'number': int(n), 'title': 'Story %s' % n,
                                'body': 'Body %s' % n,
                                'labels': {'nodes': [{'name': l} for l in labels]}}
                    for n in re.findall(r'r(\d+): issue\(number:', query)}}}), ''
            if cmd[:2] == ['gh', 'api'] and '/pulls/50/commits' in cmd[2]:
                return 0, json.dumps(self.COMMITS), ''
            if cmd[:2] == ['gh', 'api'] and '/commits/' in cmd[2]:
                sha = cmd[2].rsplit('/', 1)[1]
                return 0, json.dumps({'files': [{'filename': f}
                                                for f in self.FILES[sha]]}), ''
            return 0, '', ''

        def jev_ask(check, payload=None, issues=None, open_issues=None):
            self.asked.append((check, payload))
            return jev

        args = wf.build_parser().parse_args(['release-targets', '--pr', '50'])
        with mock.patch.object(wf, 'check_environment', return_value=None), \
                mock.patch.object(wf, 'load_config', return_value=(
                    True, _cfg(release_targets=targets), '')), \
                mock.patch.object(wf, 'jev_ask', jev_ask), \
                mock.patch.object(wf, 'run', side_effect=fake_run):
            return _capture(args.func, args)

    def test_no_table_reads_nothing_and_asks_nothing(self):
        code, payload = self._run(targets=[])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['issues'], [])
        self.assertEqual((self.calls, self.asked), ([], []))

    def test_a_single_story_gets_every_path_of_the_pull_request(self):
        code, payload = self._run()
        self.assertEqual(code, wf.EXIT_OK)
        (issue,) = payload['issues']
        self.assertEqual(issue['number'], 5)
        self.assertEqual(issue['folders'], ['app', '(root)'])
        # One story: no commit is read.
        self.assertFalse(any('/commits' in c[2] for c in self.calls
                             if c[:2] == ['gh', 'api'] and c[2] != 'graphql'))

    def test_without_jev_every_target_is_the_callers_to_decide(self):
        """No key, or Jev off for the repository: nothing stops, and the
        caller decides every target."""
        code, payload = self._run()
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['jev'], 'unavailable')
        self.assertEqual(payload['issues'][0]['targets'], [])
        self.assertEqual(payload['issues'][0]['decide'], ['Mobile', 'web'])

    def test_each_story_of_a_bulk_pull_request_gets_its_own_commits(self):
        self._run(linked=(5, 6))
        (check, sent), = self.asked
        self.assertEqual(check, 'target')
        self.assertEqual([(i['id'], i['paths']) for i in sent['items']], [
            (5, ['app/a.ts', 'app/b.ts']), (6, ['site/c.ts'])])
        self.assertEqual(sent['items'][0]['body'], 'Body 5')
        # The commit that names no story is never read.
        read = [c[2].rsplit('/', 1)[1] for c in self.calls
                if c[:2] == ['gh', 'api'] and '/commits/' in c[2]]
        self.assertEqual(read, ['aaa', 'ccc'])

    def test_a_sure_answer_is_decided_and_the_rest_are_left_to_the_caller(self):
        rows = [{'id': '5', 'target': 'Mobile', 'answer': True, 'level': 'high'},
                {'id': '5', 'target': 'web', 'answer': False, 'level': 'high'},
                {'id': '6', 'target': 'Mobile', 'answer': True, 'level': 'medium'},
                {'id': '6', 'target': 'web', 'answer': None, 'level': 'low'}]
        code, payload = self._run(linked=(5, 6), jev=('ok', {'rows': rows}))
        self.assertEqual(code, wf.EXIT_OK)
        five, six = payload['issues']
        self.assertEqual((five['targets'], five['decide']), (['Mobile'], []))
        self.assertEqual((six['targets'], six['decide']), ([], ['Mobile', 'web']))
        self.assertEqual(payload['jev'], 'used')

    def test_the_release_labels_an_issue_already_has_are_shown(self):
        _, payload = self._run(labels=('release: web', 'released: web', 'bug'))
        self.assertEqual(payload['issues'][0]['labels'], ['release: web'])

    def test_the_guard_treats_the_command_as_a_read(self):
        import github_guard
        self.assertIn('release-targets', github_guard.WF_READS)


if __name__ == '__main__':
    unittest.main()
