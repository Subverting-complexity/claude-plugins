#!/usr/bin/env python3
"""
The single-call workflow steps (#335): `start`, `exit-cleanup`, `tree-clean`,
`pr-create`, `block`, `"milestone": "current"`, the compact `pick` result and
the review picker's moved-head tier.

Each replaced a sequence the model ran by hand and branched over. The rules
are checked offline here, and each command is driven through the `wf` seams
with `run`, `gh_json` and `gh_graphql` faked.

Run standalone (`python3 tests/test_single_commands.py`) or via `run-tests.sh`.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'))
import wf  # noqa: E402
import wf_core  # noqa: E402

NAMES = wf_core.review_names({})


def _capture(func, args):
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            func(args)
        except SystemExit as exc:
            code = exc.code
    out = buf.getvalue()
    return code, out, (json.loads(out) if out.strip() else None)


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'branch_convention': 'feature/{number}/{short-desc}',
            'labels': {}, 'review_labels': {}, 'fields': {}}


def _args(*argv):
    return wf.build_parser().parse_args(list(argv))


# ── the rules ────────────────────────────────────────────────────────────────

class TestExitPrAction(unittest.TestCase):

    def test_an_open_pr_still_marked_reviewing_is_reconciled(self):
        self.assertEqual(wf_core.exit_pr_action('OPEN', [NAMES['reviewing']], NAMES),
                         'reconcile')

    def test_a_verdict_or_an_unstarted_review_is_kept(self):
        for label in ('approved', 'changes-requested', 'needs-review'):
            self.assertEqual(wf_core.exit_pr_action('OPEN', [NAMES[label]], NAMES),
                             'keep', label)

    def test_a_merged_pr_is_kept(self):
        self.assertEqual(wf_core.exit_pr_action('MERGED', [NAMES['reviewing']], NAMES),
                         'keep')

    def test_an_open_pr_with_no_state_label_is_reconciled(self):
        self.assertEqual(wf_core.exit_pr_action('OPEN', ['type-bug'], NAMES), 'reconcile')


class TestPorcelain(unittest.TestCase):

    def test_entries_split_into_tracked_and_untracked(self):
        entries = wf_core.parse_porcelain(' M a.py\n?? new/\nR  old.py -> new.py\n')
        self.assertEqual(wf_core.tracked(entries), ['a.py', 'new.py', 'old.py'])
        self.assertEqual(wf_core.untracked(entries), ['new/'])

    def test_z_output_keeps_unescaped_names_and_both_rename_paths(self):
        entries = wf_core.parse_porcelain(' M caf\u00e9.py\0R  new.py\0old.py\0?? n\u00e4me/\0')
        self.assertEqual(wf_core.tracked(entries), ['caf\u00e9.py', 'new.py', 'old.py'])
        self.assertEqual(wf_core.untracked(entries), ['n\u00e4me/'])


class TestBodyChecks(unittest.TestCase):

    def test_corrupt_bodies_are_named(self):
        self.assertEqual(wf_core.body_problems(''), ['the body is empty'])
        self.assertIn('characters long', wf_core.body_problems('-')[0])
        self.assertIn('punctuation', wf_core.body_problems('-- ## .. @@ !!')[0])

    def test_a_missing_closes_line_is_a_problem(self):
        problems = wf_core.body_problems('## Summary\n\nDid it.\n\nCloses #4', [4, 5])
        self.assertEqual(problems, ['no Closes line for #5'])

    def test_missing_closes_lines_are_added_once(self):
        body = wf_core.with_closes_lines('## Summary\n\nDid it.\n\nCloses #4\n', [4, 5])
        self.assertEqual(wf_core.closes_numbers(body), [4, 5])
        self.assertEqual(wf_core.with_closes_lines(body, [4, 5]), body)

    def test_a_duplicate_flag_names_both_numbers(self):
        lines = wf_core.duplicate_flag_lines([{'issue': 3, 'prs': [{'number': 9}]}])
        self.assertEqual(len(lines), 1)
        self.assertIn('#9', lines[0])
        self.assertIn('#3', lines[0])


class TestCurrentMilestone(unittest.TestCase):

    def test_the_earliest_dated_milestone_with_open_issues_wins(self):
        title, note = wf_core.current_milestone([
            {'title': 'Later', 'due_on': '2026-10-01', 'open_issues': 3},
            {'title': 'Done', 'due_on': '2026-09-01', 'open_issues': 0},
            {'title': 'Now', 'due_on': '2026-09-20', 'open_issues': 1},
            {'title': 'Undated', 'due_on': None, 'open_issues': 9},
        ])
        self.assertEqual((title, note), ('Now', None))

    def test_only_undated_milestones_are_said_out_loud(self):
        title, note = wf_core.current_milestone([{'title': 'A', 'due_on': None,
                                                  'open_issues': 2}])
        self.assertIsNone(title)
        self.assertIn('none has a due date', note)

    def test_no_milestone_at_all(self):
        self.assertIsNone(wf_core.current_milestone([])[0])


class TestCompactPick(unittest.TestCase):

    RESULT = {'number': 1, 'title': 'x', 'url': 'u', 'labels': [], 'milestone': None,
              'body': 'long', 'claim_ref': 'refs/claims/issue-1', 'mode': 'story',
              'backlog_mode': None, 'side_effects': [], 'checked_out': True,
              'stage_set': True, 'stage_message': 'Stage set to In Progress',
              'start_date_set': False, 'start_date_message': 'no field',
              'branch': 'feature/1/x', 'branch_message': 'created'}

    def test_success_messages_nulls_and_the_body_go(self):
        out = wf_core.compact_pick(self.RESULT)
        for key in ('body', 'claim_ref', 'labels', 'milestone', 'backlog_mode',
                    'side_effects', 'stage_message', 'branch_message'):
            self.assertNotIn(key, out, key)
        self.assertEqual(out['start_date_message'], 'no field')

    def test_the_body_stays_when_asked_for(self):
        self.assertEqual(wf_core.compact_pick(self.RESULT, True)['body'], 'long')


class TestAbandonedPr(unittest.TestCase):

    def test_a_closed_unmerged_pr_is_abandoned(self):
        prs = [{'number': 8, 'mergedAt': None,
                'closingIssuesReferences': [{'number': 3}]}]
        self.assertEqual(wf_core.abandoned_pr(prs, 3)['number'], 8)

    def test_a_merged_pr_means_the_work_is_done(self):
        prs = [{'number': 8, 'mergedAt': None, 'closingIssuesReferences': [{'number': 3}]},
               {'number': 9, 'mergedAt': '2026-01-01', 'closingIssuesReferences': [{'number': 3}]}]
        self.assertIsNone(wf_core.abandoned_pr(prs, 3))

    def test_a_pr_closing_another_issue_does_not_count(self):
        prs = [{'number': 8, 'mergedAt': None, 'closingIssuesReferences': [{'number': 4}]}]
        self.assertIsNone(wf_core.abandoned_pr(prs, 3))


class TestReviewNext(unittest.TestCase):

    def _pr(self, number, labels=(), head='abcdef1234', reviewed=None, draft=False):
        return {'number': number, 'labels': list(labels), 'head_sha': head,
                'reviewed_sha': reviewed, 'draft': draft}

    def test_the_last_footer_wins(self):
        self.assertEqual(wf_core.last_reviewed_sha(
            ['Reviewed at 1111111', 'nothing', 'Reviewed at abcdef1']), 'abcdef1')
        self.assertIsNone(wf_core.last_reviewed_sha(['no footer']))

    def test_a_short_footer_matches_its_head(self):
        self.assertFalse(wf_core.head_changed('abcdef1234', 'abcdef1'))
        self.assertTrue(wf_core.head_changed('abcdef1234', '9999999'))

    def test_tiers_and_skips(self):
        prs = [
            self._pr(1, [NAMES['needs-review']]),
            self._pr(2, [NAMES['changes-requested']], reviewed='abcdef1'),
            self._pr(3, [NAMES['approved']], reviewed='1234567'),        # moved
            self._pr(4, [NAMES['needs-re-review']]),
            self._pr(5, [NAMES['approved']], reviewed='abcdef1'),        # settled
            self._pr(6, [NAMES['reviewing']], reviewed='1234567'),       # busy
            self._pr(7, [], reviewed=None),                              # never reviewed
            self._pr(8, [NAMES['needs-review']], draft=True),
            self._pr(9, [NAMES['approved']], reviewed=None),             # approved by hand
        ]
        order = [p['number'] for p in wf_core.select_review_next(prs, NAMES)]
        self.assertEqual(order, [4, 2, 1, 3, 7])

    def test_a_moved_changes_requested_pr_is_reviewed_not_reworked(self):
        pr = self._pr(2, [NAMES['changes-requested']], reviewed='1234567')
        self.assertEqual([p['number'] for p in wf_core.select_review_next([pr], NAMES)], [2])
        self.assertIsNone(wf_core.review_prior_state(pr['labels'], NAMES, moved=True))
        self.assertEqual(wf_core.review_prior_state(pr['labels'], NAMES),
                         NAMES['changes-requested'])


class TestNullFieldValue(unittest.TestCase):

    def test_a_null_node_in_a_create_payload_is_skipped(self):
        issue = {'issueFieldValues': {'nodes': [
            None, {'field': {'name': 'Priority'}, 'name': 'High'}]}}
        self.assertEqual(wf.issue_field_values(issue), {'Priority': 'High'})


# ── the commands ─────────────────────────────────────────────────────────────

class _Repo(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, '.claude'))
        for name, value in (('repo_root', lambda: self.root),
                            ('prepare_cfg', _cfg),
                            ('check_environment', lambda: None),
                            ('ensure_scratch_ignored', lambda root: False)):
            patch = mock.patch.object(wf, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def touch(self, name, text='x'):
        with open(os.path.join(self.root, '.claude', name), 'w', encoding='utf-8') as fh:
            fh.write(text)


class TestExitCleanup(_Repo):

    def _run(self, argv, status='', pr_json=None, calls=None):
        calls = calls if calls is not None else []

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            if cmd[:3] == ['git', 'status', '--porcelain']:
                return 0, status, ''
            if cmd[:3] == ['gh', 'pr', 'view']:
                return 0, json.dumps(pr_json or {}), ''
            return 0, '', ''
        with mock.patch.object(wf, 'run', fake_run):
            return _capture(wf.cmd_exit_cleanup, _args('exit-cleanup', *argv))

    def test_a_clean_exit_is_one_line(self):
        self.touch('plan.md')
        code, out, payload = self._run(['--issue', '3'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(out.count('\n'), 1)
        self.assertIn('released issue-3', payload['reason'])
        self.assertFalse(os.path.exists(os.path.join(self.root, '.claude', 'plan.md')))

    def test_a_dirty_tree_is_left_to_the_caller(self):
        code, _, payload = self._run(['--issue', '3'], status=' M src/a.py\n')
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertEqual(payload['status'], 'dirty')
        self.assertEqual(payload['remaining'], [{'code': ' M', 'path': 'src/a.py'}])

    def test_a_dirty_tree_still_names_a_failed_release(self):
        with mock.patch.object(wf, 'release_claims', lambda t: {x: False for x in t}):
            code, _, payload = self._run(['--issue', '3'], status=' M src/a.py\n')
        self.assertEqual(payload['status'], 'dirty')
        self.assertIn('could not release issue-3', payload['reason'])
        self.assertNotIn('claims and scratch done', payload['reason'])

    def test_a_pr_claim_not_won_is_never_touched(self):
        calls = []
        code, _, _ = self._run(['--pr', '7'], calls=calls)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertFalse(any('pr-7' in ' '.join(c) for c in calls))

    def test_a_won_claim_on_an_unreviewed_pr_is_reconciled_then_released(self):
        self.touch('claim-pr-7.sha', 'abc')
        calls = []
        finish = mock.Mock(side_effect=lambda args: wf.emit('ok', 0, verified=True))
        with mock.patch('wf_review.cmd_review_finish', finish):
            code, _, payload = self._run(
                ['--pr', '7'], calls=calls,
                pr_json={'state': 'OPEN', 'labels': [{'name': NAMES['reviewing']}]})
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(finish.call_args[0][0].verdict, 'changes-requested')
        self.assertTrue(any(':refs/claims/pr-7' in c for c in calls if c[:2] == ['git', 'push']))

    def test_bulk_releases_every_story_in_the_set(self):
        self.touch('bulk-set.json', json.dumps({'stories': [{'number': 4}, {'number': 5}]}))
        calls = []
        code, _, payload = self._run(['--bulk'], calls=calls)
        self.assertEqual(code, wf.EXIT_OK)
        push = next(c for c in calls if c[:2] == ['git', 'push'])
        self.assertEqual(push[3:], [':refs/claims/issue-4', ':refs/claims/issue-5'])


class TestTreeClean(_Repo):

    def test_chosen_paths_are_discarded_and_the_tree_rechecked(self):
        states = iter([' M a.py\n?? junk/\n', ''])
        calls = []

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            if cmd[:2] == ['git', 'status']:
                return 0, next(states), ''
            return 0, '', ''
        with mock.patch.object(wf, 'run', fake_run):
            code, _, payload = _capture(wf.cmd_tree_clean, _args('tree-clean', '--all'))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn(['git', 'restore', '--staged', '--worktree', '--', 'a.py'], calls)
        self.assertIn(['git', 'clean', '-fd', '--', 'junk/'], calls)
        self.assertFalse(any('stash' in c for c in calls))


class TestStart(_Repo):

    def test_a_story_is_claimed_staged_cleaned_and_branched(self):
        calls = []

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            if cmd[:2] == ['git', 'status']:
                return 0, '', ''
            return 0, '', ''
        with mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'holds_claim', lambda t: True), \
                mock.patch.object(wf, 'gh_json', lambda a: (True, {'number': 3, 'title': 'Fix it'}, '')), \
                mock.patch.object(wf, 'set_stage', lambda cfg, n, s: (True, 'ok')), \
                mock.patch.object(wf, 'checkout_branch',
                                  lambda cfg, issue: ('feature/3/fix-it', True, 'created')):
            code, out, payload = _capture(wf.cmd_start, _args('start', '--issue', '3'))
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(payload['branch'], 'feature/3/fix-it')
        self.assertEqual(out.count('\n'), 1)

    def test_a_lost_claim_stops_before_anything_is_written(self):
        stage = mock.Mock()
        with mock.patch.object(wf, 'holds_claim', lambda t: False), \
                mock.patch.object(wf, 'acquire_claim', lambda t: 'lost'), \
                mock.patch.object(wf, 'set_stage', stage):
            code, _, payload = _capture(wf.cmd_start, _args('start', '--issue', '3'))
        self.assertEqual(code, wf.EXIT_LOST)
        stage.assert_not_called()

    def test_a_failed_group_claim_push_is_not_reported_lost(self):
        self.touch('bulk-set.json', json.dumps({
            'stories': [{'number': 4, 'group': 1}], 'groups': [{'group': 1}]}))
        with mock.patch.object(wf, 'run', lambda cmd, input_text=None: (0, '', '')), \
                mock.patch.object(wf, 'holds_claim', lambda t: False), \
                mock.patch.object(wf, 'acquire_claim', lambda t: 'error'):
            code, _, payload = _capture(wf.cmd_start, _args(
                'start', '--group', '1', '--branch', 'feature/4/set'))
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertEqual(payload['lost'], [])
        self.assertEqual(payload['claim_errors'], [4])
        self.assertIn('claim push failed', payload['reason'])

    def test_a_group_branch_is_created_pushed_and_recorded(self):
        self.touch('bulk-set.json', json.dumps({
            'stories': [{'number': 4, 'group': 1}, {'number': 5, 'group': 2}],
            'groups': [{'group': 1}, {'group': 2}]}))
        calls = []

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            return 0, '', ''
        with mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'holds_claim', lambda t: True):
            code, _, payload = _capture(wf.cmd_start, _args(
                'start', '--group', '1', '--branch', 'feature/4/set'))
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertIn(['git', 'push', '-u', 'origin', 'feature/4/set'], calls)
        with open(os.path.join(self.root, '.claude', 'bulk-set.json'), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['groups'][0]['branch'], 'feature/4/set')


class TestBlock(_Repo):

    def _run(self, argv, siblings=None, calls=None, apply_code=0):
        calls = calls if calls is not None else []
        body = os.path.join(self.root, 'why.md')
        with open(body, 'w', encoding='utf-8') as fh:
            fh.write('Waiting on #9.')

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            return 0, '', ''
        applied = []

        def fake_apply(args):
            with open(args.spec, encoding='utf-8') as fh:
                applied.append(json.load(fh))
            wf.emit('ok' if apply_code == 0 else 'partial', apply_code)
        sibling = lambda args: wf.emit('ok', 0, found=len(siblings or []),
                                       prs=siblings or [])
        with mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'gh_json', lambda a: (True, {'number': 3, 'title': 'Fix it'}, '')), \
                mock.patch.object(wf, 'set_stage', lambda cfg, n, s: (True, 'ok')), \
                mock.patch.object(wf, 'release_claims', lambda t: {x: True for x in t}), \
                mock.patch('wf_issue_apply.cmd_issue_apply', fake_apply), \
                mock.patch('wf_review.cmd_sibling_pr', sibling):
            code, out, payload = _capture(wf.cmd_block, _args(
                'block', '--issue', '3', '--body-file', body, *argv))
        return code, payload, applied, calls

    def test_an_issue_blocker_becomes_edges_and_blocked(self):
        code, payload, applied, calls = self._run(['--blocked-by', '9'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(applied, [{'issues': [{'blocked_by': [9], 'number': 3}]}])
        self.assertIn('Blocked', payload['reason'])
        self.assertTrue(any('--remove-assignee' in c for c in calls))

    def test_a_story_with_an_open_pr_stays_assigned(self):
        calls = []
        code, payload, _, calls = self._run(
            [], siblings=[{'number': 12, 'title': 'Other PR'}], calls=calls)
        self.assertEqual(payload['status'], 'has-pr')
        self.assertIn('#12 Other PR', payload['reason'])
        self.assertFalse(any('--remove-assignee' in c for c in calls))

    def test_non_code_work_with_an_open_pr_is_not_relabelled(self):
        code, payload, applied, _ = self._run(
            ['--non-code', 'human'], siblings=[{'number': 12, 'title': 'Other PR'}])
        self.assertEqual(payload['status'], 'has-pr')
        self.assertEqual(applied, [])

    def test_non_code_work_sets_ownership_and_the_prefix(self):
        code, payload, applied, _ = self._run(['--non-code', 'human'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        entry = applied[0]['issues'][0]
        self.assertEqual(entry['title'], '[Manual] Fix it')
        self.assertEqual(entry['fields'], {'field-ownership': 'Human'})
        self.assertIn('Non-code', payload['reason'])

    def test_a_failed_edge_write_is_partial(self):
        code, payload, _, _ = self._run(['--blocked-by', '9'], apply_code=24)
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertIn('#3 Fix it', payload['reason'])


class TestPrCreate(_Repo):

    def _run(self, stored_bodies, siblings=(), calls=None):
        calls = calls if calls is not None else []
        body = os.path.join(self.root, 'pr.md')
        with open(body, 'w', encoding='utf-8') as fh:
            fh.write('## Summary\n\nBuilt the thing.\n')
        stored = iter(stored_bodies)
        sent = []

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            if cmd[:3] == ['git', 'rev-parse', '--abbrev-ref']:
                return 0, 'feature/3/x\n', ''
            if cmd[:3] == ['gh', 'pr', 'create']:
                with open(cmd[cmd.index('--body-file') + 1], encoding='utf-8') as fh:
                    sent.append(fh.read())
                return 0, 'https://github.com/acme/widgets/pull/42\n', ''
            return 0, '', ''
        sibling = lambda args: wf.emit('ok', 0, by_issue=[{'issue': 3, 'prs': list(siblings)}])
        with mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'gh_json', lambda a: (True, {
                    'number': 42, 'url': 'u', 'body': next(stored)}, '')), \
                mock.patch('wf_review.cmd_sibling_pr', sibling):
            code, out, payload = _capture(wf.cmd_pr_create, _args(
                'pr-create', '--title', 'T', '--body-file', body, '--issue', '3'))
        return code, out, payload, sent, calls

    def test_a_good_body_is_one_line(self):
        code, out, payload, sent, calls = self._run(['## Summary\n\nBuilt.\n\nCloses #3'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(out.count('\n'), 1)
        self.assertEqual(payload['pr'], 42)
        self.assertIn('Closes #3', sent[0])
        self.assertIn(['git', 'push', '-u', 'origin', 'HEAD'], calls)

    def test_a_corrupt_body_is_rewritten_once(self):
        code, _, payload, _, calls = self._run(['-', '## Summary\n\nBuilt.\n\nCloses #3'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(len([c for c in calls if c[:3] == ['gh', 'pr', 'edit']]), 1)

    def test_a_body_still_corrupt_is_partial(self):
        code, _, payload, _, _ = self._run(['-', '-'])
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertTrue(payload['problems'])

    def test_a_sibling_pr_is_flagged_at_the_top(self):
        code, _, payload, sent, _ = self._run(
            ['## Summary\n\nBuilt.\n\nCloses #3'],
            siblings=[{'number': 9, 'title': 'Other'}])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertTrue(sent[0].startswith('> ⚠ Possible duplicate of #9'))
        self.assertEqual(payload['duplicates'], [{'issue': 3, 'pr': 9, 'title': 'Other'}])


class TestCurrentMilestoneInSpec(unittest.TestCase):

    def test_current_is_replaced_by_the_sprint_title(self):
        entries = [{'title': 'x', 'milestone': 'current'}]
        with mock.patch.object(wf, 'gh_json', lambda a: (True, [
                {'title': 'Sprint 9', 'due_on': '2026-09-30', 'open_issues': 2}], '')):
            note = wf.resolve_current_milestone(_cfg(), entries)
        self.assertEqual(entries[0]['milestone'], 'Sprint 9')
        self.assertIn('Sprint 9', note)

    def test_no_sprint_drops_the_key_and_says_why(self):
        entries = [{'title': 'x', 'milestone': 'current'}]
        with mock.patch.object(wf, 'gh_json', lambda a: (True, [], '')):
            note = wf.resolve_current_milestone(_cfg(), entries)
        self.assertNotIn('milestone', entries[0])
        self.assertIn('no open milestone', note)

    def test_a_named_milestone_is_left_alone_without_a_read(self):
        entries = [{'title': 'x', 'milestone': 'Sprint 1'}]
        read = mock.Mock()
        with mock.patch.object(wf, 'gh_json', read):
            self.assertIsNone(wf.resolve_current_milestone(_cfg(), entries))
        read.assert_not_called()


class TestReviewNextCommand(_Repo):

    def test_a_moved_head_is_picked_without_a_label(self):
        data = {'repository': {'pullRequests': {'nodes': [{
            'number': 5, 'title': 'T', 'url': 'u', 'headRefName': 'b',
            'headRefOid': 'ffffffff00', 'isDraft': False,
            'labels': {'nodes': []},
            'comments': {'nodes': [{'body': 'x\nReviewed at 1234567',
                                    'createdAt': '2026-01-01'}]},
            'reviews': {'nodes': []}}]}}}
        with mock.patch.object(wf, 'gh_graphql', lambda q, **f: (True, data, '')), \
                mock.patch.object(wf, 'acquire_claim', lambda t: 'won'), \
                mock.patch.object(wf, 'run', lambda cmd, input_text=None: (0, '', '')):
            code, _, payload = _capture(wf.cmd_review_next, _args('review-next'))
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(payload['number'], 5)
        self.assertTrue(payload['head_changed'])

    def test_a_pool_past_one_page_is_an_error_not_no_candidates(self):
        data = {'repository': {'pullRequests': {
            'pageInfo': {'hasNextPage': True}, 'nodes': []}}}
        with mock.patch.object(wf, 'gh_graphql', lambda q, **f: (True, data, '')):
            code, _, payload = _capture(wf.cmd_review_next, _args('review-next'))
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertIn('more than 100', payload['reason'])

    def test_nothing_to_review_is_one_line(self):
        data = {'repository': {'pullRequests': {'nodes': []}}}
        with mock.patch.object(wf, 'gh_graphql', lambda q, **f: (True, data, '')):
            code, out, payload = _capture(wf.cmd_review_next, _args('review-next'))
        self.assertEqual(code, wf.EXIT_NO_CANDIDATES)
        self.assertEqual(out.count('\n'), 1)


if __name__ == '__main__':
    unittest.main()
