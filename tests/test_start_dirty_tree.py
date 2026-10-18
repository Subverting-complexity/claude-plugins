#!/usr/bin/env python3
"""
`wf start` on a dirty tree (#405).

`start` used to restore and clean every uncommitted path before it checked
out the story branch, so a re-run after a lost claim deleted the build in
progress. Now it keeps the tree on the story branch, resets it only in a new
worktree, and otherwise stops with `dirty` before it writes anything.

Run standalone (`python3 tests/test_start_dirty_tree.py`) or via `run-tests.sh`.
"""

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

BRANCH = 'feature/3/fix-it'
DIRTY = ' M a.py\0?? notes/\0'


def _capture(func, args):
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            func(args)
        except SystemExit as exc:
            code = exc.code
    out = buf.getvalue()
    return code, (json.loads(out) if out.strip() else None)


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'branch_convention': 'feature/{number}/{short-desc}',
            'labels': {}, 'review_labels': {}, 'fields': {}}


def _args(*argv):
    return wf.build_parser().parse_args(list(argv))


def _fake_git(calls, head, linked, reflog_lines):
    """A `run` for a dirty checkout: HEAD on `head`, a linked worktree or the
    main one, and a HEAD reflog of `reflog_lines` entries."""
    def fake_run(cmd, input_text=None):
        calls.append(list(cmd))
        if cmd[:2] == ['git', 'status']:
            return 0, DIRTY, ''
        if cmd[:2] == ['git', 'symbolic-ref']:
            return 0, head + '\n', ''
        if cmd == ['git', 'rev-parse', '--git-dir']:
            return 0, ('/r/.git/worktrees/w' if linked else '/r/.git') + '\n', ''
        if cmd == ['git', 'rev-parse', '--git-common-dir']:
            return 0, '/r/.git\n', ''
        if cmd[:3] == ['git', 'reflog', 'show']:
            return 0, ''.join('%040d\n' % i for i in range(reflog_lines)), ''
        if cmd[:3] == ['git', 'rev-parse', '--verify']:
            return 1, '', ''
        return 0, '', ''
    return fake_run


def _discarded(calls):
    return [c for c in calls if c[:2] in (['git', 'restore'], ['git', 'clean'])]


def _checkouts(calls):
    return [c for c in calls if c[:2] == ['git', 'checkout']]


class TestStartTreeAction(unittest.TestCase):

    def test_a_clean_tree_is_kept(self):
        for on in (True, False):
            for new in (True, False):
                self.assertEqual(wf_core.start_tree_action(False, on, new), 'keep')

    def test_work_on_the_story_branch_is_kept(self):
        self.assertEqual(wf_core.start_tree_action(True, True, False), 'keep')
        self.assertEqual(wf_core.start_tree_action(True, True, True), 'keep')

    def test_only_a_new_worktree_is_reset(self):
        self.assertEqual(wf_core.start_tree_action(True, False, True), 'reset')
        self.assertEqual(wf_core.start_tree_action(True, False, False), 'refuse')


class _Repo(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, '.claude'))
        for name, value in (('repo_root', lambda: self.root),
                            ('prepare_cfg', _cfg),
                            ('check_environment', lambda: None),
                            ('ensure_scratch_ignored', lambda root: False),
                            ('holds_claim', lambda t: True)):
            patch = mock.patch.object(wf, name, value)
            patch.start()
            self.addCleanup(patch.stop)


class TestStartIssueOnADirtyTree(_Repo):

    def _run(self, head, linked=False, reflog_lines=5):
        calls, stage, checkout = [], mock.Mock(return_value=(True, 'ok')), mock.Mock(
            return_value=(BRANCH, True, 'created'))
        with mock.patch.object(wf, 'run', _fake_git(calls, head, linked, reflog_lines)), \
                mock.patch.object(wf, 'gh_json', lambda a: (True, {'number': 3, 'title': 'Fix it'}, '')), \
                mock.patch.object(wf, 'set_stage', stage), \
                mock.patch.object(wf, 'checkout_branch', checkout):
            code, payload = _capture(wf.cmd_start, _args('start', '--issue', '3'))
        return code, payload, calls, stage, checkout

    def test_dirty_work_on_the_story_branch_is_kept_with_no_checkout(self):
        code, payload, calls, stage, checkout = self._run(BRANCH)
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(_discarded(calls), [])
        checkout.assert_not_called()
        stage.assert_called_once()
        self.assertIn('already on the branch', payload['reason'])

    def test_a_dirty_tree_elsewhere_is_refused_before_any_write(self):
        code, payload, calls, stage, checkout = self._run('main')
        self.assertEqual(code, 24)
        self.assertEqual(payload['status'], 'dirty')
        self.assertEqual(payload['dirty'], ['a.py', 'notes/'])
        self.assertIn('commit', payload['reason'])
        self.assertEqual(_discarded(calls), [])
        stage.assert_not_called()
        checkout.assert_not_called()

    def test_a_used_linked_worktree_is_not_new(self):
        code, payload, calls, stage, _ = self._run('main', linked=True, reflog_lines=3)
        self.assertEqual(payload['status'], 'dirty')
        stage.assert_not_called()

    def test_a_new_worktree_is_reset_as_before(self):
        code, payload, calls, stage, checkout = self._run('main', linked=True, reflog_lines=1)
        self.assertIn(['git', 'restore', '--staged', '--worktree', '--', 'a.py'], calls)
        self.assertIn(['git', 'clean', '-fd', '--', 'notes/'], calls)
        checkout.assert_called_once()
        stage.assert_called_once()
        # The fake tree stays dirty, so the reset is reported as incomplete.
        self.assertEqual(payload['discarded'], ['a.py', 'notes/'])


class TestStartGroupOnADirtyTree(_Repo):

    def setUp(self):
        super().setUp()
        with open(os.path.join(self.root, '.claude', 'bulk-set.json'), 'w', encoding='utf-8') as fh:
            json.dump({'stories': [{'number': 4, 'group': 1}], 'groups': [{'group': 1}]}, fh)

    def _run(self, head, linked=False, reflog_lines=5):
        calls = []
        with mock.patch.object(wf, 'run', _fake_git(calls, head, linked, reflog_lines)):
            code, payload = _capture(wf.cmd_start, _args(
                'start', '--group', '1', '--branch', 'feature/4/set'))
        return code, payload, calls

    def test_dirty_work_on_the_group_branch_is_kept_with_no_checkout(self):
        code, payload, calls = self._run('feature/4/set')
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(_discarded(calls), [])
        self.assertEqual(_checkouts(calls), [])

    def test_a_dirty_tree_elsewhere_is_refused(self):
        code, payload, calls = self._run('main')
        self.assertEqual(code, 24)
        self.assertEqual(payload['dirty'], ['a.py', 'notes/'])
        self.assertEqual(_discarded(calls), [])
        self.assertEqual(_checkouts(calls), [])
        self.assertFalse(any(c[:2] == ['git', 'push'] for c in calls))

    def test_a_new_worktree_is_reset_and_branched(self):
        code, payload, calls = self._run('main', linked=True, reflog_lines=1)
        self.assertIn(['git', 'clean', '-fd', '--', 'notes/'], calls)
        self.assertIn(['git', 'checkout', '-b', 'feature/4/set', 'origin/main'], calls)


if __name__ == '__main__':
    unittest.main()
