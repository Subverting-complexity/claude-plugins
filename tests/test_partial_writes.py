#!/usr/bin/env python3
"""A `wf` command whose write failed must not report `ok` (#406).

Each command here used to exit 0 with `ok` when one of its writes failed, so a
caller that reads only the status treated a partial run as done. Each test
fails one write and checks that the result is `partial` (exit 24) or `error`,
with a reason built from what really happened.
"""

import argparse
import contextlib
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
import wf  # noqa: E402
import wf_core  # noqa: E402
from test_wf_call_counts import _Counted, _GitHub  # noqa: E402
from test_wf_claim_release import _capture, _cfg  # noqa: E402


class TestCloseResolved(unittest.TestCase):
    """`Done` is written only after the close succeeds."""

    def _close(self, close_code):
        calls, stages = [], []

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            if cmd[:3] == ['gh', 'issue', 'close']:
                return close_code, '', 'HTTP 403: forbidden' if close_code else ''
            return 0, '', ''

        with mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'set_stage',
                                  lambda *a, **k: stages.append(a[1]) or (True, 'Done')):
            result = wf.close_resolved(
                _cfg(), {'number': 7, 'labels': ['status-in-progress']}, 42)
        return result, calls, stages

    def test_a_failed_close_writes_nothing_else(self):
        result, calls, stages = self._close(1)
        self.assertEqual(result, (False, 'not closed: HTTP 403: forbidden'))
        self.assertTrue(wf.close_failed(result))
        self.assertEqual(stages, [])
        self.assertEqual([c for c in calls if c[:3] == ['gh', 'issue', 'edit']], [])

    def test_a_close_that_lands_sets_done(self):
        result, _, stages = self._close(0)
        self.assertEqual(result, (True, 'Done'))
        self.assertFalse(wf.close_failed(result))
        self.assertEqual(stages, [7])

    def test_a_failed_stage_write_is_not_a_failed_close(self):
        self.assertFalse(wf.close_failed((False, 'read-only token')))

    def test_pick_reports_the_failed_close(self):
        cand = {'number': 5, 'title': 't', 'labels': [], 'body': '', 'url': '',
                'milestone': None}
        with mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'validate_issue', return_value=('resolved', '#9')), \
                mock.patch.object(wf, 'close_resolved',
                                  return_value=(False, 'not closed: denied')), \
                mock.patch.object(wf, 'release_claim', return_value=True):
            _, effects = wf.claim_validate_walk(_cfg(), [cand], None)
        self.assertIs(effects[0]['closed'], False)
        self.assertEqual(effects[0]['close_message'], 'not closed: denied')


class TestPlanFailedClose(unittest.TestCase):

    def test_a_resolved_story_whose_close_failed_is_dropped_with_the_reason(self):
        released = []
        story = {'number': 5, 'blocked_by': [], 'group': 1}
        with mock.patch('wf_plan.acquire_claim', return_value='won'), \
                mock.patch('wf_plan.validate_issue_edges',
                           return_value=('resolved', 42, None)), \
                mock.patch('wf_plan.close_resolved',
                           return_value=(False, 'not closed: denied')), \
                mock.patch('wf_plan.release_claims',
                           lambda targets: released.extend(targets) or {}):
            code, payload = _capture(wf.claim_plan, _cfg(), None,
                                     {'by_num': {5: {'number': 5}}}, {}, [story], {})
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        self.assertEqual(payload['dropped'], [
            {'number': 5, 'reason': 'already resolved by #42, not closed: denied'}])
        self.assertEqual(released, ['issue-5'])


class TestPostMergeContainers(_Counted):
    """A container left open or out of Done is a gap, and the reason says so."""

    def _post_merge(self, containers):
        hub = _GitHub(linked=[5])
        with mock.patch('wf_post_merge.close_finished_ancestors',
                        lambda cfg, numbers: (containers, [])):
            return self._drive(hub, ['post-merge', '--pr', '50', '--no-unblock'])

    def test_a_failed_container_close_is_partial(self):
        code, payload = self._post_merge(
            [{'issue': 2, 'closed': False, 'error': 'denied', 'finished_by': 5}])
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertIn('container #2 not closed: denied', payload['reason'])

    def test_a_container_left_out_of_done_is_partial(self):
        code, payload = self._post_merge(
            [{'issue': 2, 'closed': True, 'stage_set': False, 'finished_by': 5}])
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertIn('container #2 Stage not Done', payload['reason'])

    def test_a_closed_container_counts_in_the_ok_reason(self):
        code, payload = self._post_merge(
            [{'issue': 2, 'closed': True, 'stage_set': True, 'finished_by': 5}])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn('1 container(s) closed', payload['reason'])


class TestRefine(unittest.TestCase):

    def _refine(self, fail_cmd=None, released=True):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        body = os.path.join(root, 'body.md')
        with open(body, 'w', encoding='utf-8') as fh:
            fh.write('Say which screen.\n')

        def fake_run(cmd, input_text=None):
            if fail_cmd and cmd[:3] == fail_cmd:
                return 1, '', 'denied'
            return 0, '', ''

        args = wf.build_parser().parse_args(['refine', '--issue', '7',
                                             '--body-file', body])
        with mock.patch.object(wf, 'prepare_cfg', _cfg), \
                mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'set_stage', return_value=(True, 'set')), \
                mock.patch('wf_claim.release_claims',
                           lambda targets: {t: released for t in targets}):
            return _capture(args.func, args)

    def test_every_write_landing_is_ok(self):
        code, payload = self._refine()
        self.assertEqual(code, wf.EXIT_OK)

    def test_a_failed_comment_is_partial(self):
        code, payload = self._refine(fail_cmd=['gh', 'issue', 'comment'])
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertIn('commented failed', payload['reason'])

    def test_a_failed_release_is_partial(self):
        code, payload = self._refine(released=False)
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertIn('claim_released', payload['reason'])


class TestHandoffLabel(unittest.TestCase):

    def test_a_failed_label_is_partial_and_never_called_labelled(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        args = wf.build_parser().parse_args(['handoff', '--pr', '7', '--issue', '3'])
        with mock.patch.object(wf, 'prepare_cfg', _cfg), \
                mock.patch.object(wf, 'holds_claim', return_value=True), \
                mock.patch.object(wf, 'add_review_label', return_value=(False, 'denied')), \
                mock.patch.object(wf, 'set_stages',
                                  lambda cfg, wanted: {int(n): (True, 'In Review')
                                                       for n in wanted}), \
                mock.patch.object(wf, 'release_claims',
                                  lambda targets, **kw: {t: True for t in targets}), \
                mock.patch.object(wf, 'repo_root', lambda: root):
            code, payload = _capture(args.func, args)
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertIn('PR #7 not labelled', payload['reason'])
        self.assertNotIn('labelled review',
                         payload['reason'].replace('not labelled', ''))


class TestClaimReap(unittest.TestCase):

    def test_a_failed_release_is_not_listed_as_reaped(self):
        args = wf.build_parser().parse_args(['claim-reap'])
        refs = [('aaa', 'issue-3'), ('bbb', 'issue-4')]
        states = {'issue-3': ('issue', 3, 'CLOSED', [], False, True),
                  'issue-4': ('issue', 4, 'CLOSED', [], False, True)}
        with mock.patch.object(wf, 'check_environment', lambda: None), \
                mock.patch.object(wf, 'prepare_cfg', _cfg), \
                mock.patch.object(wf, 'list_claim_refs', lambda: (refs, '')), \
                mock.patch.object(wf, 'claim_age_hours', lambda sha: 9), \
                mock.patch.object(wf, 'claim_target_state',
                                  lambda cfg, target: states[target]), \
                mock.patch.object(wf, 'release_claim', lambda t: t != 'issue-4'):
            code, payload = _capture(wf.cmd_claim_reap, args)
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertEqual([e['ref'] for e in payload['reaped']], ['refs/claims/issue-3'])
        self.assertEqual([e['ref'] for e in payload['release_failed']],
                         ['refs/claims/issue-4'])
        self.assertEqual(payload['summary']['reaped'], 1)
        self.assertIn('1 release(s) failed', payload['reason'])


class TestUnexpectedException(unittest.TestCase):

    def _main(self, func):
        parser = types.SimpleNamespace(
            parse_args=lambda argv: argparse.Namespace(func=func))
        with mock.patch.object(wf, 'build_parser', lambda: parser):
            return _capture(wf.main, [])

    def test_an_exception_gives_an_error_result_and_exit_20(self):
        def boom(args):
            raise KeyError('nodes')

        code, payload = self._main(boom)
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')
        self.assertEqual(payload['reason'], "unexpected KeyError: 'nodes'")

    def test_an_exit_from_the_command_is_left_alone(self):
        code, payload = self._main(lambda args: wf.emit('ok', wf.EXIT_OK))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')


class TestPreflightConfigParse(unittest.TestCase):

    def test_a_malformed_config_is_a_critical_finding(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, 'ClaudeProject.md'), 'w', encoding='utf-8') as fh:
            fh.write('# Project\n\n## Identity\n\n| org |\n')
        args = wf.build_parser().parse_args(['preflight', '--offline'])
        with mock.patch.object(wf, 'check_environment', lambda: None), \
                mock.patch.object(wf, 'repo_root', lambda: root), \
                mock.patch.object(wf, 'load_config',
                                  lambda: (False, None, 'bad Identity table')), \
                contextlib.redirect_stderr(io.StringIO()):
            code, payload = _capture(wf.cmd_preflight, args)
        self.assertEqual(code, wf.EXIT_DRIFT)
        found = [f for f in payload['findings'] if f['check'] == 'config-parse']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['level'], wf_core.CRITICAL)
        self.assertIn('bad Identity table', found[0]['detail'])
        self.assertFalse(found[0]['auto'])


if __name__ == '__main__':
    unittest.main()
