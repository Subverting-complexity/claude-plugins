#!/usr/bin/env python3
"""`wf bulk-schedule` and `wf bulk-integrate`.

The schedule is pure and tested offline: stories that share a file never run
in the same batch, and a story whose files are unknown runs alone. Integration
runs real git against a bare repository standing in for `origin`, because the
behaviour that matters (a conflicting cherry-pick is aborted and leaves the
tree as it was) is git's, not ours, and a stub would only test the stub.
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
import wf_core  # noqa: E402


def capture(argv):
    buf, code = io.StringIO(), None
    args = wf.build_parser().parse_args(argv)
    with contextlib.redirect_stdout(buf):
        try:
            args.func(args)
        except SystemExit as exc:
            code = exc.code
    out = buf.getvalue()
    return code, (json.loads(out) if out.strip() else None)


class TestSchedule(unittest.TestCase):

    def test_stories_with_no_shared_file_form_one_parallel_batch(self):
        waves, nxt, _ = wf_core.schedule_waves(
            [[1, 2, 3]], {1: ['a.py'], 2: ['b.py'], 3: ['c.py']})
        self.assertEqual(waves[0]['batches'], [[1, 2, 3]])
        self.assertTrue(waves[0]['parallel'])
        self.assertEqual(waves[0]['overlaps'], [])
        self.assertEqual(nxt, 0)

    def test_stories_sharing_a_file_go_in_different_batches(self):
        waves, _, _ = wf_core.schedule_waves(
            [[10, 11, 12]], {10: ['src/x.ts', 'a.ts'], 11: ['src/x.ts'], 12: ['c.ts']})
        self.assertEqual(waves[0]['batches'], [[10, 12], [11]])
        self.assertTrue(waves[0]['parallel'])
        self.assertEqual(waves[0]['overlaps'], [{'file': 'src/x.ts', 'stories': [10, 11]}])

    def test_an_unplanned_story_runs_alone(self):
        waves, _, _ = wf_core.schedule_waves([[1, 2]], {1: ['a.py']})
        self.assertEqual(waves[0]['batches'], [[1], [2]])
        self.assertFalse(waves[0]['parallel'])
        self.assertEqual(waves[0]['unplanned'], [2])

    def test_built_stories_are_skipped_and_next_wave_follows(self):
        waves, nxt, _ = wf_core.schedule_waves(
            [[1], [2, 3]], {1: ['a'], 2: ['b.py'], 3: ['c.py']}, built={1, 2})
        self.assertEqual(waves[0]['stories'], [])
        self.assertEqual(waves[0]['batches'], [])
        self.assertEqual(waves[1]['stories'], [3])
        self.assertEqual(nxt, 1)
        _, nxt, _ = wf_core.schedule_waves([[1]], {1: ['a.py']}, built={1})
        self.assertIsNone(nxt)

    def test_a_shared_file_alone_does_not_force_serial(self):
        waves, _, shared = wf_core.schedule_waves(
            [[1, 2]], {1: ['lib/s.ts', 'a.ts'], 2: ['./lib/s.ts', 'b.ts']},
            shared=['lib\\s.ts'])
        self.assertEqual(waves[0]['batches'], [[1, 2]])
        self.assertEqual(shared, [{'file': 'lib/s.ts', 'stories': [1, 2]}])

    def test_spellings_of_one_path_overlap(self):
        for a, b in (('./src/a.ts', 'src/a.ts'), ('src\\a.ts', 'src/a.ts'),
                     ('`src/a.ts`', 'src/a.ts,')):
            waves, _, _ = wf_core.schedule_waves([[1, 2]], {1: [a], 2: [b]})
            self.assertEqual(waves[0]['batches'], [[1], [2]], (a, b))

    def test_normalise_plan_path(self):
        self.assertEqual(wf_core.normalise_plan_path(' `./src\\x\\y.py`: '), 'src/x/y.py')
        self.assertEqual(wf_core.normalise_plan_path('.\\a.md.'), 'a.md')

    def test_parse_plan(self):
        plan = '\n'.join([
            '# Plan',
            '## Shared',
            '- [ ] src/labels/resolve.ts — the lookup two stories build on',
            '',
            '## Wave 0 — Story #41 — Resolve labels by purpose key',
            '- [ ] `src/labels/resolve.ts` — add the purpose-key path',
            '- [x] tests\\labels.test.ts — cover it',
            '- [ ] Write the docs — not a path',
            '### Tests',
            '* [X] ./tests/more.test.ts, then run it',
            '## Notes',
            '- [ ] ignored/file.ts',
            '## Wave 1 — Story #42 (after #41)',
            '- [ ] src/other.ts',
            '- [ ] src/other.ts — twice',
            '- plain bullet src/not-a-task.ts',
        ])
        parsed = wf_core.parse_plan(plan)
        self.assertEqual(parsed['shared'], ['src/labels/resolve.ts'])
        self.assertEqual(parsed['stories'][41], ['src/labels/resolve.ts',
                                                  'tests/labels.test.ts',
                                                  'tests/more.test.ts'])
        self.assertEqual(parsed['stories'][42], ['src/other.ts'])

    def test_set_waves_falls_back_to_each_story_wave(self):
        record = {'stories': [{'number': 5, 'wave': 1}, {'number': 4, 'wave': 0,
                                                         'built': True}]}
        self.assertEqual(wf_core.set_waves(record), ([[4], [5]], {4}))


class TestScheduleCommand(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        patch = mock.patch.object(wf, 'repo_root', return_value=self.root)
        patch.start()
        self.addCleanup(patch.stop)
        os.makedirs(os.path.join(self.root, '.claude'))

    def write(self, name, text):
        with open(os.path.join(self.root, '.claude', name), 'w', encoding='utf-8') as fh:
            fh.write(text)

    def test_a_missing_set_is_usage(self):
        code, out = capture(['bulk-schedule'])
        self.assertEqual((code, out['status']), (2, 'usage'))

    def test_schedule_is_emitted_and_recorded(self):
        self.write('bulk-set.json', json.dumps({
            'branch': 'feature/b', 'waves': [[1], [2, 3]],
            'stories': [{'number': 1, 'wave': 0, 'blocked_by': [], 'built': True},
                        {'number': 2, 'wave': 1, 'blocked_by': [1], 'built': False},
                        {'number': 3, 'wave': 1, 'blocked_by': [1], 'built': False}]}))
        self.write('plan.md', '## Story #2\n- [ ] a.py\n## Story #3\n- [ ] b.py\n')
        code, out = capture(['bulk-schedule'])
        self.assertEqual((code, out['status']), (0, 'ok'))
        self.assertEqual(out['next_wave'], 1)
        self.assertEqual(out['waves'][1]['batches'], [[2, 3]])
        with open(os.path.join(self.root, '.claude', 'bulk-set.json'), encoding='utf-8') as fh:
            record = json.load(fh)
        self.assertEqual(record['schedule']['waves'][1]['batches'], [[2, 3]])
        self.assertEqual(record['groups'][0]['branch'], 'feature/b')

    def test_schedule_reads_only_the_group_it_is_given(self):
        self.write('bulk-set.json', json.dumps({
            'groups': [{'group': 1, 'branch': 'a', 'waves': [[1]]},
                       {'group': 2, 'branch': None, 'waves': [[2, 3]]}],
            'stories': [{'number': 1, 'group': 1, 'wave': 0, 'built': True},
                        {'number': 2, 'group': 2, 'wave': 0, 'built': False},
                        {'number': 3, 'group': 2, 'wave': 0, 'built': False}]}))
        code, out = capture(['bulk-schedule', '--group', '2'])
        self.assertEqual(code, 0)
        self.assertEqual([w['stories'] for w in out['waves']], [[2, 3]])
        self.assertEqual(out['group'], 2)

    def test_a_missing_plan_makes_every_story_unplanned(self):
        self.write('bulk-set.json', json.dumps({
            'waves': [[1, 2]], 'stories': [{'number': 1, 'wave': 0},
                                           {'number': 2, 'wave': 0}]}))
        code, out = capture(['bulk-schedule'])
        self.assertEqual(code, 0)
        self.assertFalse(out['plan_found'])
        self.assertEqual(out['waves'][0]['unplanned'], [1, 2])
        self.assertEqual(out['waves'][0]['batches'], [[1], [2]])


GIT_ENV = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t',
           'GIT_CONFIG_NOSYSTEM': '1'}


@unittest.skipUnless(shutil.which('git'), 'git is not on PATH')
class TestIntegrate(unittest.TestCase):
    """A bare `origin`, a clone on the shared branch, and one clone per builder."""

    BRANCH = 'feature/set'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.origin = os.path.join(self.tmp, 'origin.git')
        self.git(self.tmp, 'init', '-q', '--bare', '-b', 'main', self.origin)
        self.clone = self.make_clone('main')
        self.commit(self.clone, 'base.txt', 'one\ntwo\nthree\n')
        self.git(self.clone, 'push', '-q', 'origin', 'main')
        self.git(self.clone, 'checkout', '-q', '-b', self.BRANCH)
        self.git(self.clone, 'push', '-q', '-u', 'origin', self.BRANCH)
        patch = mock.patch.object(wf, 'repo_root', return_value=self.clone)
        patch.start()
        self.addCleanup(patch.stop)

    def git(self, cwd, *args):
        proc = subprocess.run(['git', '-c', 'core.autocrlf=false'] + list(args),
                              cwd=cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError('git %s failed: %s' % (' '.join(args), proc.stderr))
        return proc.stdout.strip()

    def make_clone(self, ref):
        path = tempfile.mkdtemp(dir=self.tmp)
        self.git(self.tmp, 'clone', '-q', self.origin, path)
        self.git(path, 'config', 'core.autocrlf', 'false')
        if ref != 'main':
            self.git(path, 'checkout', '-q', ref)
        return path

    def commit(self, cwd, name, text):
        with open(os.path.join(cwd, name), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
        self.git(cwd, 'add', name)
        self.git(cwd, 'commit', '-q', '-m', 'edit %s' % name)
        return self.git(cwd, 'rev-parse', 'HEAD')

    def builder(self, number, edits):
        """What a parallel builder does: branch from origin/{branch}, commit, push."""
        path = self.make_clone(self.BRANCH)
        temp = '%s--%d' % (self.BRANCH, number)
        self.git(path, 'checkout', '-q', '-b', temp)
        shas = [self.commit(path, name, text) for name, text in edits]
        self.git(path, 'push', '-q', 'origin', temp)
        return shas

    def write_set(self, numbers):
        os.makedirs(os.path.join(self.clone, '.claude'), exist_ok=True)
        with open(os.path.join(self.clone, '.claude', 'bulk-set.json'), 'w',
                  encoding='utf-8') as fh:
            json.dump({'branch': self.BRANCH, 'waves': [list(numbers)],
                       'stories': [{'number': n, 'wave': 0, 'blocked_by': [],
                                    'built': False} for n in numbers]}, fh)

    def bulk_set(self):
        with open(os.path.join(self.clone, '.claude', 'bulk-set.json'), encoding='utf-8') as fh:
            return json.load(fh)

    def remote_heads(self):
        out = self.git(self.clone, 'ls-remote', '--heads', 'origin')
        return {line.split('refs/heads/', 1)[1] for line in out.splitlines()}

    def test_two_clean_builders_are_integrated_pushed_marked_and_deleted(self):
        self.write_set([1, 2])
        a = self.builder(1, [('a.txt', 'a\n'), ('a2.txt', 'a2\n')])
        b = self.builder(2, [('b.txt', 'b\n')])
        code, out = capture(['bulk-integrate', '--wave', '0'])
        self.assertEqual((code, out['status']), (0, 'ok'), out)
        self.assertEqual([e['number'] for e in out['integrated']], [1, 2])
        self.assertEqual(len(out['integrated'][0]['commits']), len(a))
        self.assertEqual(len(out['integrated'][1]['commits']), len(b))
        self.assertTrue(out['pushed'])
        self.assertEqual(out['remaining'], [])
        self.assertEqual(sorted(out['branches_deleted']),
                         ['%s--1' % self.BRANCH, '%s--2' % self.BRANCH])
        self.assertEqual(self.remote_heads(), {'main', self.BRANCH})
        self.assertTrue(all(s['built'] for s in self.bulk_set()['stories']))
        tree = self.git(self.clone, 'ls-tree', '--name-only', 'origin/%s' % self.BRANCH)
        self.assertEqual(set(tree.split()), {'base.txt', 'a.txt', 'a2.txt', 'b.txt'})

    def test_a_conflicting_builder_is_aborted_and_left_unbuilt(self):
        self.write_set([1, 2])
        self.builder(1, [('base.txt', 'ONE\ntwo\nthree\n')])
        self.builder(2, [('base.txt', 'uno\ntwo\nthree\n')])
        code, out = capture(['bulk-integrate', '--wave', '0', '--keep-branches'])
        self.assertEqual((code, out['status']), (24, 'partial'), out)
        self.assertEqual([e['number'] for e in out['integrated']], [1])
        self.assertEqual([e['number'] for e in out['conflicted']], [2])
        self.assertTrue(out['pushed'])
        self.assertEqual(out['branches_deleted'], [])
        self.assertEqual(out['remaining'], [2])
        self.assertEqual(self.git(self.clone, 'status', '--porcelain',
                                  '--untracked-files=no'), '')
        self.assertFalse(os.path.exists(os.path.join(self.clone, '.git',
                                                     'CHERRY_PICK_HEAD')))
        built = {s['number']: s['built'] for s in self.bulk_set()['stories']}
        self.assertEqual(built, {1: True, 2: False})
        self.assertIn('%s--2' % self.BRANCH, self.remote_heads())

    def test_missing_and_empty_branches_are_reported(self):
        self.write_set([1, 2])
        path = self.make_clone(self.BRANCH)
        self.git(path, 'push', '-q', 'origin', '%s:%s--2' % (self.BRANCH, self.BRANCH))
        code, out = capture(['bulk-integrate', '--wave', '0'])
        self.assertEqual((code, out['status']), (24, 'partial'), out)
        self.assertEqual([e['number'] for e in out['missing']], [1])
        self.assertEqual([e['number'] for e in out['empty']], [2])
        self.assertFalse(out['pushed'])
        self.assertEqual(out['remaining'], [1, 2])

    def test_the_wrong_branch_or_a_dirty_tree_is_usage(self):
        self.write_set([1])
        with open(os.path.join(self.clone, 'base.txt'), 'a') as fh:
            fh.write('dirty\n')
        code, out = capture(['bulk-integrate', '--wave', '0'])
        self.assertEqual((code, out['status']), (2, 'usage'))
        self.git(self.clone, 'checkout', '-q', '--', 'base.txt')
        self.git(self.clone, 'checkout', '-q', 'main')
        code, out = capture(['bulk-integrate', '--wave', '0'])
        self.assertEqual((code, out['status']), (2, 'usage'))


if __name__ == '__main__':
    unittest.main()
