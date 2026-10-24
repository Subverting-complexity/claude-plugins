#!/usr/bin/env python3
"""
Claims through an issue assignment, where claim refs are refused (#438).

A Claude Code cloud session answers every claim ref push with HTTP 403. `wf`
then claims through the assignees of the issue or pull request: it reads them,
writes the run's login, reads the answer back, and goes on only when that
login is the only assignee. Releasing removes the assignment. These tests
check the switch, the lost and error outcomes, the release and the held
check, and that a session whose claim push works sees no change at all.

Run standalone (`python3 tests/test_claim_assignment.py`) or via `run-tests.sh`.
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
import wf_claim_assign  # noqa: E402
import wf_rest  # noqa: E402


ME = 'me'
REFUSED = 'remote: Permission denied\nfatal: unable to access: The requested URL returned error: 403'


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'branch_convention': 'feature/{number}/{short-desc}',
            'labels': {}, 'review_labels': {}, 'fields': {}, 'board': {}}


class _Remote:
    """A fake remote: the git side refuses or accepts claim pushes, and the
    REST side keeps each item's assignees."""

    def __init__(self, push_err=None, assignees=None, post_adds=(), drop_write=False):
        self.push_err = push_err
        self.assignees = {k: list(v) for k, v in (assignees or {}).items()}
        self.post_adds = list(post_adds)
        self.drop_write = drop_write
        self.git, self.rest = [], []

    def run(self, cmd, input_text=None):
        self.git.append(list(cmd))
        if cmd[:2] == ['git', 'mktree']:
            return 0, 'tree0\n', ''
        if cmd[:2] == ['git', 'commit-tree']:
            return 0, 'sha1\n', ''
        if cmd[:2] == ['git', 'push']:
            return (1, '', self.push_err) if self.push_err else (0, '', '')
        if cmd[:2] == ['git', 'ls-remote']:
            return 2, '', ''
        return 0, '', ''

    def gh_rest(self, path, method='GET', body=None):
        self.rest.append((method, path, body))
        if path == 'user':
            return True, {'login': ME}, ''
        number = int(path.split('/issues/')[1].split('/')[0])
        current = self.assignees.setdefault(number, [])
        if method == 'POST':
            if not self.drop_write:
                current.extend(body['assignees'])
            current.extend(self.post_adds)
        elif method == 'DELETE':
            for login in body['assignees']:
                while login in current:
                    current.remove(login)
        return True, {'number': number,
                      'assignees': [{'login': name} for name in current]}, ''

    def writes(self):
        return [(m, p) for m, p, _ in self.rest if m != 'GET']


class _Case(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        wf_claim_assign.reset_claim_assign_state()
        wf_rest.reset_rest_state()
        self.addCleanup(wf_claim_assign.reset_claim_assign_state)
        self.addCleanup(wf_rest.reset_rest_state)
        env = mock.patch.dict(os.environ, {wf_claim_assign.CLAIM_REFS_ENV: ''})
        env.start()
        self.addCleanup(env.stop)
        for name, value in (('repo_root', lambda: self.root),
                            ('load_config', lambda: (True, _cfg(), '')),
                            ('prepare_cfg', _cfg),
                            ('check_environment', lambda: None),
                            ('ensure_scratch_ignored', lambda root: False)):
            patch = mock.patch.object(wf, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def use(self, remote):
        for name in ('run', 'gh_rest'):
            patch = mock.patch.object(wf, name, getattr(remote, name))
            patch.start()
            self.addCleanup(patch.stop)
        return remote

    def acquire(self, target):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            outcome = wf.acquire_claim(target)
        return outcome, err.getvalue()

    def marker(self, target):
        path = os.path.join(self.root, '.claude', 'claim-%s.sha' % target)
        if not os.path.exists(path):
            return None
        with open(path, encoding='utf-8') as fh:
            return fh.read()


class TestAcquire(_Case):

    def test_a_refused_push_claims_the_issue_by_assignment(self):
        remote = self.use(_Remote(push_err=REFUSED))
        outcome, err = self.acquire('issue-5')
        self.assertEqual(outcome, 'won')
        self.assertEqual(remote.assignees[5], [ME])
        self.assertEqual(self.marker('issue-5'), 'assign:me:added')
        self.assertIn('claims each story through an issue assignment', err)
        self.assertIn('same moment can take the same story', err)

    def test_the_notice_is_said_once_and_later_claims_skip_the_push(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        pushes = sum(1 for c in remote.git if c[:2] == ['git', 'push'])
        outcome, err = self.acquire('issue-6')
        self.assertEqual(outcome, 'won')
        self.assertEqual(err, '')
        self.assertEqual(sum(1 for c in remote.git if c[:2] == ['git', 'push']), pushes)

    def test_an_issue_assigned_to_another_login_is_lost_without_a_write(self):
        remote = self.use(_Remote(push_err=REFUSED, assignees={5: ['rival']}))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'lost')
        self.assertEqual(remote.writes(), [])
        self.assertIsNone(self.marker('issue-5'))

    def test_a_rival_writing_at_the_same_moment_loses_us_the_claim(self):
        remote = self.use(_Remote(push_err=REFUSED, post_adds=['rival']))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'lost')
        self.assertEqual(remote.assignees[5], ['rival'])
        self.assertIsNone(self.marker('issue-5'))

    def test_a_write_github_dropped_is_an_environment_error(self):
        self.use(_Remote(push_err=REFUSED, drop_write=True))
        outcome, err = self.acquire('issue-5')
        self.assertEqual(outcome, 'error')
        self.assertIn('did not assign', err)

    def test_the_environment_variable_starts_on_assignment_claims(self):
        remote = self.use(_Remote())
        with mock.patch.dict(os.environ, {wf_claim_assign.CLAIM_REFS_ENV: 'off'}):
            outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'won')
        self.assertFalse(any(c[:2] == ['git', 'push'] for c in remote.git))

    def test_a_pull_request_already_assigned_to_us_is_kept_on_release(self):
        remote = self.use(_Remote(push_err=REFUSED, assignees={7: [ME]}))
        outcome, _ = self.acquire('pr-7')
        self.assertEqual(outcome, 'won')
        self.assertEqual(self.marker('pr-7'), 'assign:me:kept')
        self.assertEqual(remote.writes(), [])
        self.assertTrue(wf.release_claim('pr-7'))
        self.assertEqual(remote.assignees[7], [ME])
        self.assertIsNone(self.marker('pr-7'))


    def test_a_bulk_set_claimed_at_once_is_all_taken_and_all_released(self):
        """`plan-set --claim` takes every claim in parallel threads."""
        from concurrent.futures import ThreadPoolExecutor
        remote = self.use(_Remote(push_err=REFUSED))
        targets = ['issue-%d' % n for n in (5, 6, 7)]
        err = io.StringIO()
        with contextlib.redirect_stderr(err), ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = list(pool.map(wf.acquire_claim, targets))
        self.assertEqual(outcomes, ['won'] * 3)
        self.assertEqual(err.getvalue().count('claims each story'), 1)
        self.assertEqual(wf.release_claims(targets), dict.fromkeys(targets, True))
        self.assertEqual([remote.assignees[n] for n in (5, 6, 7)], [[], [], []])


class TestRefClaimsUnchanged(_Case):

    def test_a_push_that_works_makes_no_rest_call(self):
        remote = self.use(_Remote())
        outcome, err = self.acquire('issue-5')
        self.assertEqual(outcome, 'won')
        self.assertEqual(err, '')
        self.assertEqual(remote.rest, [])
        self.assertEqual(self.marker('issue-5'), 'sha1')

    def test_a_push_refused_for_another_reason_is_still_an_error(self):
        remote = self.use(_Remote(push_err='fatal: could not read from remote'))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'error')
        self.assertEqual(remote.rest, [])

    def test_a_rate_limit_403_does_not_switch_to_assignments(self):
        remote = self.use(_Remote(push_err='HTTP 403: API rate limit exceeded'))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'error')
        self.assertEqual(remote.rest, [])


class TestReleaseAndHold(_Case):

    def test_release_removes_the_assignment_and_pushes_only_ref_claims(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        with open(os.path.join(self.root, '.claude', 'claim-issue-6.sha'), 'w') as fh:
            fh.write('sha9')
        remote.push_err = None
        released = wf.release_claims(['issue-5', 'issue-6'])
        self.assertEqual(released, {'issue-5': True, 'issue-6': True})
        self.assertEqual(remote.assignees[5], [])
        pushes = [c for c in remote.git if c[:2] == ['git', 'push'] and c[3:4] == [':refs/claims/issue-6']]
        self.assertEqual(len(pushes), 1)
        self.assertNotIn(':refs/claims/issue-5', pushes[0])
        self.assertIsNone(self.marker('issue-5'))

    def test_a_failed_removal_with_the_login_still_there_is_not_released(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        real = remote.gh_rest

        def failing(path, method='GET', body=None):
            if method == 'DELETE':
                return False, None, 'HTTP 502'
            return real(path, method, body)
        with mock.patch.object(wf, 'gh_rest', failing), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(wf.release_claims(['issue-5']), {'issue-5': False})
        self.assertEqual(self.marker('issue-5'), 'assign:me:added')

    def test_held_while_the_login_is_the_only_assignee(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        self.assertTrue(wf.holds_claim('issue-5'))
        remote.assignees[5].append('rival')
        self.assertFalse(wf.holds_claim('issue-5'))

    def test_claim_keep_held_keeps_a_review_claim_taken_by_assignment(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('pr-7')
        writes = len(remote.writes())
        args = argparse.Namespace(issue=None, pr=7, keep_held=True, marker=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                wf.cmd_claim(args)
        self.assertEqual(caught.exception.code, wf.EXIT_OK)
        self.assertEqual(json.loads(buf.getvalue())['claimed'], True)
        self.assertEqual(len(remote.writes()), writes)

    def test_exit_cleanup_releases_the_issue_and_review_claims(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        self.acquire('pr-7')
        args = wf.build_parser().parse_args(['exit-cleanup', '--issue', '5', '--pr', '7'])
        buf = io.StringIO()
        with mock.patch.object(wf, 'reconcile_pr', lambda cfg, pr: ('kept', None)), \
                mock.patch.object(wf, 'reap_finished', lambda: 0), \
                mock.patch.object(wf, 'tree_entries', lambda: []), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                wf.cmd_exit_cleanup(args)
        self.assertEqual(caught.exception.code, wf.EXIT_OK)
        self.assertIn('released issue-5, pr-7', buf.getvalue())
        self.assertEqual(remote.assignees[5], [])
        self.assertEqual(remote.assignees[7], [])
        self.assertIsNone(self.marker('issue-5'))
        self.assertIsNone(self.marker('pr-7'))

    def test_handoff_lets_the_issue_claim_go_and_keeps_it_assigned(self):
        """From the open pull request on, the assignment is the issue's
        ownership marker, as it is after a claim ref is released."""
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        released = wf.release_claims(['issue-5'], keep_assignment=True)
        self.assertEqual(released, {'issue-5': True})
        self.assertEqual(remote.assignees[5], [ME])
        self.assertIsNone(self.marker('issue-5'))
        self.assertNotIn('DELETE', [m for m, _ in remote.writes()])

    def test_the_pick_result_names_the_assignment(self):
        self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        self.assertEqual(wf.claim_ref_of('issue-5'), 'assignee:me')
        self.assertEqual(wf.claim_ref_of('issue-6'), 'refs/claims/issue-6')


if __name__ == '__main__':
    unittest.main()
