#!/usr/bin/env python3
"""
Tests for `wf worktree-reap`: which finished worktrees a sweep removes.

The harness leaves a worktree on disk for every subagent, and a project that
installs dependencies per worktree makes each one gigabytes. The rules for what
counts as finished are checked offline against `wf_core.worktree_verdict`. The sweep
itself is driven against a real throwaway git repository, because the cases that
matter (a detached HEAD, an untracked file, a linked `node_modules`) are
properties of git and the file system that a fake would only restate.

Run standalone (`python3 tests/test_worktree_reap.py`) or via `run-tests.sh`.
"""

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'synergy', 'scripts'))

import wf  # noqa: E402
import wf_core  # noqa: E402
import wf_worktrees  # noqa: E402

DAY = 24 * 3600


def _tree(**facts):
    base = {'in_scope': True, 'current': False, 'locked': False, 'prunable': False,
            'detached': False}
    base.update(facts)
    return base


# ── the rules ────────────────────────────────────────────────────────────────

class TestParseWorktreeList(unittest.TestCase):

    def test_reads_each_block(self):
        text = ('worktree /c/repo\nHEAD aaa\nbranch refs/heads/main\n\n'
                'worktree /c/repo/.claude/worktrees/agent-1\nHEAD bbb\ndetached\nlocked\n\n'
                'worktree /c/gone\nHEAD ccc\nbranch refs/heads/x\nprunable gitdir file points to non-existent location\n')
        main, detached, gone = wf_core.parse_worktree_list(text)
        self.assertEqual(main['path'], '/c/repo')
        self.assertEqual(main['branch'], 'refs/heads/main')
        self.assertTrue(detached['detached'] and detached['locked'])
        self.assertIsNone(detached['branch'])
        self.assertTrue(gone['prunable'])
        self.assertFalse(gone['locked'])

    def test_empty_output_is_no_worktrees(self):
        self.assertEqual(wf_core.parse_worktree_list(''), [])


class TestInScope(unittest.TestCase):
    ROOT = os.path.join('repo', '.claude', 'worktrees')

    def test_a_harness_folder_directly_under_the_root_is_in_scope(self):
        self.assertTrue(wf_core.worktree_in_scope(os.path.join(self.ROOT, 'agent-a1b2'), self.ROOT))

    def test_a_persons_session_worktree_is_not_swept_by_default(self):
        self.assertFalse(wf_core.worktree_in_scope(os.path.join(self.ROOT, 'fix-login-93a1'), self.ROOT))

    def test_a_wider_pattern_reaches_it(self):
        self.assertTrue(wf_core.worktree_in_scope(os.path.join(self.ROOT, 'fix-login-93a1'), self.ROOT, ('*',)))

    def test_a_folder_elsewhere_is_never_in_scope(self):
        self.assertFalse(wf_core.worktree_in_scope(os.path.join('other', 'agent-a1'), self.ROOT, ('*',)))
        self.assertFalse(wf_core.worktree_in_scope(os.path.join(self.ROOT, 'agent-a1', 'nested'), self.ROOT, ('*',)))


class TestReapVerdict(unittest.TestCase):

    def verdict(self, **facts):
        return wf_core.worktree_verdict(_tree(**facts), 6)

    def test_outside_current_and_locked_are_kept_before_anything_is_read(self):
        self.assertEqual(self.verdict(in_scope=False), (wf_core.TREE_KEEP, wf_core.KEPT_OUTSIDE))
        self.assertEqual(self.verdict(current=True), (wf_core.TREE_KEEP, wf_core.KEPT_CURRENT))
        self.assertEqual(self.verdict(locked=True), (wf_core.TREE_KEEP, wf_core.KEPT_LOCKED))

    def test_age_is_asked_for_first_and_dirty_only_once_it_is_old_enough(self):
        self.assertEqual(self.verdict(), (wf_core.TREE_NEED, 'age_hours'))
        self.assertEqual(self.verdict(age_hours=1), (wf_core.TREE_KEEP, wf_core.KEPT_RECENT))
        self.assertEqual(self.verdict(age_hours=7), (wf_core.TREE_NEED, 'dirty'))

    def test_an_unknown_age_keeps_the_worktree(self):
        self.assertEqual(self.verdict(age_hours=None), (wf_core.TREE_KEEP, wf_core.KEPT_RECENT))

    def test_uncommitted_changes_and_an_unreadable_status_are_kept(self):
        self.assertEqual(self.verdict(age_hours=9, dirty=True), (wf_core.TREE_KEEP, wf_core.KEPT_DIRTY))
        self.assertEqual(self.verdict(age_hours=9, dirty=None), (wf_core.TREE_KEEP, wf_core.KEPT_UNREADABLE))

    def test_a_clean_old_worktree_on_a_branch_is_reaped(self):
        self.assertEqual(self.verdict(age_hours=9, dirty=False), (wf_core.TREE_REAP, None))

    def test_a_detached_head_needs_a_branch_or_tag_to_hold_it(self):
        base = dict(age_hours=9, dirty=False, detached=True)
        self.assertEqual(self.verdict(**base), (wf_core.TREE_NEED, 'reachable'))
        self.assertEqual(self.verdict(reachable=True, **base), (wf_core.TREE_REAP, None))
        self.assertEqual(self.verdict(reachable=False, **base), (wf_core.TREE_KEEP, wf_core.KEPT_DETACHED))
        self.assertEqual(self.verdict(reachable=None, **base), (wf_core.TREE_KEEP, wf_core.KEPT_UNREADABLE))

    def test_a_prunable_worktree_has_nothing_left_to_lose(self):
        self.assertEqual(self.verdict(prunable=True), (wf_core.TREE_REAP, None))

    def test_the_summary_orders_by_count(self):
        self.assertEqual(wf_core.worktree_kept_summary(['a', 'b', 'a']), '2 a, 1 b')


# ── the sweep against a real repository ──────────────────────────────────────

def _git(cwd, *args):
    out = subprocess.run(
        ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false']
        + list(args), cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _clear_readonly(function, path, _excinfo):
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _link(target, link):
    """A directory link the platform allows without privileges, or False."""
    try:
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', link, target],
                           capture_output=True, check=True)
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


class SweepCase(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, onerror=_clear_readonly)
        self.main = os.path.join(os.path.realpath(tmp), 'repo')
        os.makedirs(self.main)
        _git(self.main, 'init', '-b', 'main')
        with open(os.path.join(self.main, 'a.txt'), 'w') as fh:
            fh.write('a\n')
        _git(self.main, 'add', '.')
        _git(self.main, 'commit', '-m', 'first')
        self.folder = os.path.join(self.main, '.claude', 'worktrees')
        os.makedirs(self.folder)
        cwd = os.getcwd()
        os.chdir(self.main)
        self.addCleanup(os.chdir, cwd)
        # The current worktree is the main checkout, so no candidate is "here".
        patch = mock.patch.object(wf_worktrees, 'repo_root', return_value=self.main)
        patch.start()
        self.addCleanup(patch.stop)

    def add(self, name, branch=None, detach=False):
        path = os.path.join(self.folder, name)
        if detach:
            _git(self.main, 'worktree', 'add', '--detach', path)
        else:
            _git(self.main, 'worktree', 'add', '-b', branch or 'b-' + name, path)
        return path

    def old(self):
        """A clock two days on, so every worktree made in the test is long idle."""
        return time.time() + 2 * DAY

    def names(self, entries):
        return sorted(os.path.basename(e['path']) for e in entries)


class TestSweep(SweepCase):

    def test_a_clean_idle_worktree_is_removed_and_its_branch_stays(self):
        path = self.add('agent-a1', branch='feature/one')
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(self.names(result['removed']), ['agent-a1'])
        self.assertFalse(os.path.exists(path))
        self.assertIn('feature/one', _git(self.main, 'branch', '--list', 'feature/one'))
        self.assertNotIn('agent-a1', _git(self.main, 'worktree', 'list'))

    def test_a_worktree_used_within_the_age_is_kept(self):
        path = self.add('agent-a1')
        result = wf_worktrees.sweep(now=time.time())
        self.assertEqual(result['removed'], [])
        self.assertEqual(result['kept'][0]['reason'], wf_core.KEPT_RECENT)
        self.assertTrue(os.path.isdir(path))

    def test_uncommitted_work_is_kept_including_an_untracked_file(self):
        tracked = self.add('agent-tracked')
        untracked = self.add('agent-untracked')
        with open(os.path.join(tracked, 'a.txt'), 'w') as fh:
            fh.write('changed\n')
        with open(os.path.join(untracked, 'new.txt'), 'w') as fh:
            fh.write('new\n')
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(result['removed'], [])
        self.assertEqual({k['reason'] for k in result['kept']}, {wf_core.KEPT_DIRTY})
        self.assertTrue(os.path.isdir(tracked) and os.path.isdir(untracked))

    def test_ignored_files_do_not_make_a_worktree_dirty(self):
        with open(os.path.join(self.main, '.gitignore'), 'w') as fh:
            fh.write('node_modules/\n.claude/worktrees/\n')
        _git(self.main, 'add', '.gitignore')
        _git(self.main, 'commit', '-m', 'ignore')
        path = self.add('agent-a1')
        os.makedirs(os.path.join(path, 'node_modules', 'pkg'))
        with open(os.path.join(path, 'node_modules', 'pkg', 'index.js'), 'w') as fh:
            fh.write('x\n')
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(self.names(result['removed']), ['agent-a1'])
        self.assertFalse(os.path.exists(path))

    def test_a_detached_commit_no_branch_holds_is_kept(self):
        path = self.add('agent-lost', detach=True)
        with open(os.path.join(path, 'b.txt'), 'w') as fh:
            fh.write('b\n')
        _git(path, 'add', 'b.txt')
        _git(path, 'commit', '-m', 'only here')
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(result['removed'], [])
        self.assertEqual(result['kept'][0]['reason'], wf_core.KEPT_DETACHED)
        self.assertTrue(os.path.isdir(path))

    def test_a_detached_head_a_branch_holds_is_removed(self):
        path = self.add('agent-held', detach=True)
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(self.names(result['removed']), ['agent-held'])
        self.assertFalse(os.path.exists(path))

    def test_the_current_worktree_is_never_removed(self):
        path = self.add('agent-here')
        with mock.patch.object(wf_worktrees, 'repo_root', return_value=path):
            result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(result['removed'], [])
        self.assertEqual(result['kept'][0]['reason'], wf_core.KEPT_CURRENT)
        self.assertTrue(os.path.isdir(path))

    def test_a_locked_worktree_is_kept(self):
        path = self.add('agent-locked')
        _git(self.main, 'worktree', 'lock', path)
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(result['kept'][0]['reason'], wf_core.KEPT_LOCKED)
        self.assertTrue(os.path.isdir(path))

    def test_a_persons_session_worktree_is_left_alone_unless_named(self):
        path = self.add('fix-login-93a1')
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual((result['removed'], result['kept'], result['outside']), ([], [], 1))
        self.assertTrue(os.path.isdir(path))
        result = wf_worktrees.sweep(patterns=('fix-*',), now=self.old())
        self.assertEqual(self.names(result['removed']), ['fix-login-93a1'])

    def test_dry_run_removes_nothing(self):
        path = self.add('agent-a1')
        result = wf_worktrees.sweep(dry_run=True, now=self.old())
        self.assertEqual(self.names(result['removed']), ['agent-a1'])
        self.assertTrue(os.path.isdir(path))

    def test_a_worktree_whose_folder_is_already_gone_is_pruned(self):
        path = self.add('agent-a1')
        shutil.rmtree(path, onerror=_clear_readonly)
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(self.names(result['removed']), ['agent-a1'])
        self.assertNotIn('agent-a1', _git(self.main, 'worktree', 'list'))

    def test_a_scratch_file_written_now_marks_the_run_as_live(self):
        path = self.add('agent-live')
        os.makedirs(os.path.join(path, '.claude'))
        with open(os.path.join(path, '.claude', 'plan.md'), 'w') as fh:
            fh.write('plan\n')
        # The clock is only a little ahead of the scratch write, so it is fresh.
        result = wf_worktrees.sweep(now=time.time() + 3600)
        self.assertEqual(result['removed'], [])
        self.assertEqual(result['kept'][0]['reason'], wf_core.KEPT_RECENT)


class TestLinkedDependencies(SweepCase):

    def test_removing_a_worktree_never_deletes_what_its_node_modules_links_to(self):
        shared = os.path.join(self.main, 'node_modules')
        os.makedirs(os.path.join(shared, 'pkg'))
        with open(os.path.join(shared, 'pkg', 'index.js'), 'w') as fh:
            fh.write('x\n')
        path = self.add('agent-a1')
        os.makedirs(os.path.join(path, 'backend'))
        if not (_link(shared, os.path.join(path, 'node_modules'))
                and _link(shared, os.path.join(path, 'backend', 'node_modules'))):
            self.skipTest('this platform cannot make a directory link here')
        # Linked paths are not part of the checkout, so the tree stays clean.
        with open(os.path.join(self.main, '.git', 'info', 'exclude'), 'a') as fh:
            fh.write('node_modules\n')
        result = wf_worktrees.sweep(now=self.old())
        self.assertEqual(self.names(result['removed']), ['agent-a1'], result)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.isfile(os.path.join(shared, 'pkg', 'index.js')))

    def test_remove_links_leaves_a_real_node_modules_alone(self):
        path = self.add('agent-a1')
        real = os.path.join(path, 'node_modules', 'pkg')
        os.makedirs(real)
        self.assertEqual(wf_worktrees.remove_links(path), [])
        self.assertTrue(os.path.isdir(real))


class TestCommands(SweepCase):

    def run_command(self, *argv):
        buf = io.StringIO()
        code = None
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            try:
                wf.cmd_worktree_reap(wf.build_parser().parse_args(['worktree-reap'] + list(argv)))
            except SystemExit as exc:
                code = exc.code
        return code, json.loads(buf.getvalue())

    def test_dry_run_reports_and_keeps_every_folder(self):
        path = self.add('agent-a1')
        with mock.patch.object(wf_worktrees.time, 'time', return_value=self.old()):
            code, payload = self.run_command('--dry-run')
        self.assertEqual(code, wf.EXIT_OK)
        self.assertTrue(payload['dry_run'])
        self.assertEqual(self.names(payload['would_remove']), ['agent-a1'])
        self.assertTrue(os.path.isdir(path))

    def test_a_real_run_prints_one_line(self):
        self.add('agent-a1')
        self.add('agent-a2')
        with mock.patch.object(wf_worktrees.time, 'time', return_value=self.old()):
            code, payload = self.run_command()
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['removed'], 2)
        self.assertIn('removed 2 finished worktree(s)', payload['reason'])

    def test_a_worktree_that_cannot_be_removed_makes_the_result_partial(self):
        self.add('agent-a1')
        with mock.patch.object(wf_worktrees, 'remove_worktree', return_value=(False, 'locked by a process')), \
                mock.patch.object(wf_worktrees.time, 'time', return_value=self.old()):
            code, payload = self.run_command()
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertEqual(payload['failed'][0]['reason'], 'locked by a process')

    def test_the_summary_says_what_was_kept_and_why(self):
        path = self.add('agent-dirty')
        with open(os.path.join(path, 'new.txt'), 'w') as fh:
            fh.write('new\n')
        with mock.patch.object(wf_worktrees.time, 'time', return_value=self.old()):
            _, payload = self.run_command()
        self.assertIn('kept 1 (1 uncommitted changes)', payload['reason'])


class TestExitCleanupCall(unittest.TestCase):

    def test_a_sweep_that_raises_never_fails_the_run(self):
        with mock.patch.object(wf_worktrees, 'sweep', side_effect=RuntimeError('boom')):
            self.assertEqual(wf_worktrees.reap_finished(), 0)

    def test_git_that_cannot_list_worktrees_reaps_nothing(self):
        with mock.patch.object(wf_worktrees, 'sweep', return_value=None):
            self.assertEqual(wf_worktrees.reap_finished(), 0)

    def test_the_count_is_what_was_removed(self):
        result = {'removed': [{}, {}], 'failed': [], 'kept': [], 'outside': 0}
        with mock.patch.object(wf_worktrees, 'sweep', return_value=result):
            self.assertEqual(wf_worktrees.reap_finished(), 2)


if __name__ == '__main__':
    unittest.main()
