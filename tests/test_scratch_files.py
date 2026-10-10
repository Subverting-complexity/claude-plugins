#!/usr/bin/env python3
"""
Tests for the scratch files a run writes under `.claude/`.

A stray untracked scratch file keeps a worktree dirty, and a dirty worktree is
never reaped. `wf` keeps one managed block in the clone's `info/exclude`, read
by every worktree of the clone, and `wf scratch-clean` deletes a run's files
when it ends. The patterns live once in `wf_core_scratch`; this repository's
own `.gitignore` is checked against them so the two cannot drift.

Run standalone (`python3 tests/test_scratch_files.py`) or via `run-tests.sh`.
"""

import fnmatch
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'synergy', 'scripts'))

import wf_config  # noqa: E402
import wf_core  # noqa: E402

REPO = os.path.normpath(os.path.join(HERE, '..'))


class MergeExcludeTests(unittest.TestCase):

    def test_adds_the_block_to_an_empty_file(self):
        merged = wf_core.merge_exclude('')
        self.assertEqual(merged, wf_core.exclude_block())

    def test_keeps_existing_lines_and_adds_a_newline_first(self):
        merged = wf_core.merge_exclude('*.log')
        self.assertTrue(merged.startswith('*.log\n' + wf_core.EXCLUDE_BEGIN))

    def test_a_current_block_needs_no_write(self):
        self.assertIsNone(wf_core.merge_exclude('x\n' + wf_core.exclude_block() + 'y\n'))

    def test_an_old_block_is_replaced_in_place(self):
        old = 'a\n%s\n.claude/plan.md\n%s\nb\n' % (wf_core.EXCLUDE_BEGIN, wf_core.EXCLUDE_END)
        merged = wf_core.merge_exclude(old)
        self.assertEqual(merged, 'a\n' + wf_core.exclude_block() + 'b\n')
        self.assertIsNone(wf_core.merge_exclude(merged))


class RunScratchTests(unittest.TestCase):

    def test_per_run_files_are_scratch(self):
        for name in ('plan.md', 'bulk-set.json', 'gate-failed.flag', 'claim-issue-4.sha',
                     'report-spec.json', 'story-1-body.md'):
            self.assertTrue(wf_core.is_run_scratch(name), name)

    def test_caches_and_project_files_are_kept(self):
        for name in ('projected-config.md', 'wf-config.json', 'issue-fields-cache.json',
                     'preflight-passed.txt', 'ecosystem.md',
                     'settings.json', 'architecture.md', 'preflight-dismiss.md'):
            self.assertFalse(wf_core.is_run_scratch(name), name)

    def test_every_run_file_is_also_ignored(self):
        for pattern in wf_core.SCRATCH_RUN:
            sample = pattern.replace('*', 'x')
            self.assertTrue(any(fnmatch.fnmatchcase('.claude/' + sample, p)
                                for p in wf_core.SCRATCH_IGNORE), pattern)

    def test_this_repository_ignores_every_pattern(self):
        with open(os.path.join(REPO, '.gitignore'), encoding='utf-8') as fh:
            lines = {line.strip() for line in fh}
        missing = [p for p in wf_core.SCRATCH_IGNORE if '**/' + p not in lines]
        self.assertEqual(missing, [])


class GitDirTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_plain_clone_uses_its_git_directory(self):
        os.makedirs(os.path.join(self.root, '.git'))
        self.assertEqual(wf_config.git_common_dir(self.root), os.path.join(self.root, '.git'))

    def test_a_linked_worktree_follows_commondir(self):
        common = os.path.join(self.root, 'clone', '.git')
        own = os.path.join(common, 'worktrees', 'wt')
        os.makedirs(own)
        with open(os.path.join(own, 'commondir'), 'w') as fh:
            fh.write('../..\n')
        tree = os.path.join(self.root, 'wt')
        os.makedirs(tree)
        with open(os.path.join(tree, '.git'), 'w') as fh:
            fh.write('gitdir: %s\n' % own)
        self.assertEqual(wf_config.git_common_dir(tree), os.path.normpath(common))

    def test_no_git_is_none(self):
        self.assertIsNone(wf_config.git_common_dir(self.root))

    def test_ensure_writes_once(self):
        os.makedirs(os.path.join(self.root, '.git'))
        self.assertTrue(wf_config.ensure_scratch_ignored(self.root))
        path = os.path.join(self.root, '.git', 'info', 'exclude')
        with open(path) as fh:
            first = fh.read()
        self.assertIn('.claude/bulk-set.json', first)
        before = os.path.getmtime(path)
        self.assertTrue(wf_config.ensure_scratch_ignored(self.root))
        self.assertEqual(os.path.getmtime(path), before)


class ScratchCleanTests(unittest.TestCase):

    def test_deletes_run_files_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, '.git'))
            folder = os.path.join(root, '.claude')
            os.makedirs(folder)
            for name in ('plan.md', 'bulk-set.json', 'no-merge.flag', 'wf-config.json',
                         'ecosystem.md', 'report-spec.json'):
                open(os.path.join(folder, name), 'w').close()
            out = io.StringIO()
            with mock.patch.object(wf_config, 'repo_root', lambda: root), \
                    redirect_stdout(out), self.assertRaises(SystemExit) as done:
                wf_config.cmd_scratch_clean(None)
            self.assertEqual(done.exception.code, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(sorted(result['removed']),
                             ['.claude/bulk-set.json', '.claude/no-merge.flag',
                              '.claude/plan.md', '.claude/report-spec.json'])
            self.assertEqual(sorted(os.listdir(folder)), ['ecosystem.md', 'wf-config.json'])


if __name__ == '__main__':
    unittest.main()
