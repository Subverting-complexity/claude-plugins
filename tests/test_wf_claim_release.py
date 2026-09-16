#!/usr/bin/env python3
"""A claim release that fails must be said, never reported as released.

The release push used to be fired and forgotten. When it failed, `claim-release`
still listed the target as released and `pick` and `handoff` said nothing, while
the ref went on holding the issue out of every pool until `claim-reap` freed it
hours later.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
import wf  # noqa: E402


def _capture(func, *args, **kwargs):
    """Run a command function; return (exit_code, parsed_stdout_json)."""
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            func(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    out = buf.getvalue()
    return code, (json.loads(out) if out.strip() else None)


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'labels': {}, 'review_labels': {}, 'fields': {}, 'board': {}}


def _fake_git(refused=(), still_there=True, calls=None):
    """A `run` whose release push fails for each target in `refused`.

    `still_there` is what the ls-remote probe then finds: the ref still on the
    remote (exit 0) or gone (exit 2). A push naming several refs fails if any
    one is refused, and the probe then lists the refused refs it was asked
    about, as git does after deleting the rest."""
    def fake(cmd, input_text=None):
        if calls is not None:
            calls.append(list(cmd))
        if cmd[:2] == ['git', 'push'] and any(
                ':refs/claims/%s' % t in cmd for t in refused):
            return 1, '', 'remote: permission denied'
        if cmd[:2] == ['git', 'ls-remote']:
            if not still_there:
                return 2, '', ''
            held = [a for a in cmd if a in ['refs/claims/%s' % t for t in refused]]
            return 0, ''.join('abc\t%s\n' % r for r in held or cmd[-1:]), ''
        return 0, '', ''
    return fake


def _git_available():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


class TestReleaseOutcome(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        patch = mock.patch.object(wf, 'repo_root', lambda: self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def _release(self, target, fake):
        err = io.StringIO()
        with mock.patch.object(wf, 'run', fake), contextlib.redirect_stderr(err):
            return wf.release_claim(target), err.getvalue()

    def test_a_ref_still_on_the_remote_is_a_failed_release(self):
        ok, err = self._release('issue-3', _fake_git(refused=['issue-3']))
        self.assertFalse(ok)
        self.assertIn('could not release refs/claims/issue-3', err)

    def test_a_ref_already_gone_is_released(self):
        """Releasing stays idempotent: the push fails, but the ref is gone."""
        ok, err = self._release('issue-3', _fake_git(refused=['issue-3'],
                                                     still_there=False))
        self.assertTrue(ok)
        self.assertEqual(err, '')

    def test_a_successful_push_is_released_without_a_probe(self):
        calls = []
        ok, _ = self._release('issue-3', _fake_git(calls=calls))
        self.assertTrue(ok)
        self.assertFalse(any(c[:2] == ['git', 'ls-remote'] for c in calls))


class TestClaimReleaseCommand(unittest.TestCase):

    def _run(self, fake, *argv):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        args = wf.build_parser().parse_args(['claim-release', *argv])
        with mock.patch.object(wf, 'check_environment', lambda: None), \
                mock.patch.object(wf, 'run', fake), \
                mock.patch.object(wf, 'repo_root', lambda: root):
            return _capture(args.func, args)

    def test_a_failed_release_is_named_and_not_listed_as_released(self):
        code, payload = self._run(_fake_git(refused=['issue-3']),
                                  '--issue', '3', '--pr', '7')
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['released'], ['pr-7'])
        self.assertEqual(payload['failed'], ['issue-3'])
        self.assertIn('could not release issue-3', payload['reason'])
        self.assertNotIn('released issue-3', payload['reason'])

    def test_every_release_succeeding_reports_no_failures(self):
        code, payload = self._run(_fake_git(), '--issue', '3', '--pr', '7')
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['released'], ['issue-3', 'pr-7'])
        self.assertEqual(payload['failed'], [])
        self.assertEqual(payload['reason'], 'released issue-3, pr-7')


class TestPickReportsTheRelease(unittest.TestCase):
    """Each path in the claim walk that gives an issue back says whether its
    claim actually went, without changing the exit code it already had."""

    def _walk(self, verdict, released):
        cand = {'number': 5, 'title': 't', 'labels': [], 'body': '', 'url': '',
                'milestone': None}
        with mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'apply_in_progress'), \
                mock.patch.object(wf, 'validate_issue', return_value=(verdict, '#9')), \
                mock.patch.object(wf, 'mark_blocked', return_value=(True, 'moved')), \
                mock.patch.object(wf, 'close_resolved', return_value=(True, 'done')), \
                mock.patch.object(wf, 'revert_in_progress', return_value=(True, 'back')), \
                mock.patch.object(wf, 'release_claim', return_value=released):
            code, payload = _capture(lambda: wf.emit(
                'walked', 0, side_effects=wf.claim_validate_walk(_cfg(), [cand], None)[1]))
        return code, payload['side_effects']

    def test_blocked_and_resolved_report_the_release(self):
        for verdict, action in (('blocked', 'marked-blocked'),
                                ('resolved', 'closed-already-resolved')):
            for released in (True, False):
                with self.subTest(verdict=verdict, released=released):
                    _, effects = self._walk(verdict, released)
                    self.assertEqual(effects[0]['action'], action)
                    self.assertIs(effects[0]['claim_released'], released)

    def test_unknown_edges_report_the_release_and_keep_their_exit(self):
        code, effects = self._walk('unknown', False)
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(effects[0]['action'], 'released-unverified')
        self.assertIs(effects[0]['claim_released'], False)

    def test_a_named_blocked_issue_still_exits_all_blocked(self):
        cand = {'number': 5, 'title': 't', 'labels': [], 'body': '', 'url': '',
                'milestone': None}
        args = wf.build_parser().parse_args(['pick', '--issue', '5'])
        with mock.patch.object(wf, 'check_environment', return_value=None), \
                mock.patch.object(wf, 'load_config', return_value=(True, _cfg(), '')), \
                mock.patch.object(wf, 'fetch_issue_candidate', return_value=cand), \
                mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'apply_in_progress'), \
                mock.patch.object(wf, 'validate_issue', return_value=('blocked', '#9')), \
                mock.patch.object(wf, 'mark_blocked', return_value=(True, 'moved')), \
                mock.patch.object(wf, 'release_claim', return_value=False):
            code, payload = _capture(wf.cmd_pick, args)
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        self.assertIs(payload['side_effects'][0]['claim_released'], False)


class TestHandoffReportsTheRelease(unittest.TestCase):

    def _handoff(self, fake):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        args = wf.build_parser().parse_args(['handoff', '--pr', '7', '--issue', '3'])
        with mock.patch.object(wf, 'prepare_cfg', _cfg), \
                mock.patch.object(wf, 'run', fake), \
                mock.patch.object(wf, 'set_stages',
                                  lambda cfg, wanted: {int(n): (True, 'In Review')
                                                       for n in wanted}), \
                mock.patch.object(wf, 'repo_root', lambda: root):
            return _capture(args.func, args)

    def test_a_failed_issue_release_is_reported_and_the_exit_is_unchanged(self):
        code, payload = self._handoff(_fake_git(refused=['issue-3']))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertTrue(payload['issues'][0]['stage_set'])
        self.assertIs(payload['issues'][0]['claim_released'], False)

    def test_a_successful_release_is_reported(self):
        code, payload = self._handoff(_fake_git())
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIs(payload['issues'][0]['claim_released'], True)


@unittest.skipUnless(_git_available(), 'git is required for the real-remote tests')
class TestReleaseAgainstARealRemote(unittest.TestCase):
    """The same outcomes against a local bare remote, so git's own exit codes
    for a missing ref and an unreachable remote are what is tested."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bare = os.path.join(self.tmp, 'remote.git')
        self.work = os.path.join(self.tmp, 'work')
        self._git(['init', '--bare', self.bare], cwd=self.tmp)
        self._git(['init', self.work], cwd=self.tmp)
        for key, val in (('user.email', 'test@example.com'), ('user.name', 'Test'),
                         ('commit.gpgsign', 'false')):
            self._git(['config', key, val], cwd=self.work)
        with open(os.path.join(self.work, 'README.md'), 'w'):
            pass
        self._git(['add', '.'], cwd=self.work)
        self._git(['commit', '-m', 'init'], cwd=self.work)
        self._git(['remote', 'add', 'origin', self.bare], cwd=self.work)
        prev = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, prev)

    def _git(self, argv, cwd):
        r = subprocess.run(['git'] + argv, cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0:
            self.fail('git %s failed: %s' % (' '.join(argv), r.stderr.strip()))

    def _quiet(self, func, *args):
        with contextlib.redirect_stderr(io.StringIO()):
            return func(*args)

    def test_releasing_a_ref_that_was_never_claimed_succeeds(self):
        self.assertTrue(self._quiet(wf.release_claim, 'issue-8'))

    def test_a_claim_released_twice_succeeds_both_times(self):
        self.assertEqual(self._quiet(wf.acquire_claim, 'issue-1'), 'won')
        self.assertTrue(self._quiet(wf.release_claim, 'issue-1'))
        self.assertTrue(self._quiet(wf.release_claim, 'issue-1'))

    def test_an_unreachable_remote_is_a_failed_release_and_keeps_the_marker(self):
        self.assertEqual(self._quiet(wf.acquire_claim, 'issue-2'), 'won')
        marker = wf._claim_marker_path(wf.repo_root(), 'issue-2')
        self._git(['remote', 'set-url', 'origin',
                   os.path.join(self.tmp, 'does-not-exist.git')], cwd=self.work)
        self.assertFalse(self._quiet(wf.release_claim, 'issue-2'))
        self.assertTrue(os.path.isfile(marker))


if __name__ == '__main__':
    unittest.main()
