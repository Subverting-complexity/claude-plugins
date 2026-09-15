#!/usr/bin/env python3
"""
Tests for the run lifecycle commands that replaced hand-run `gh` sequences:
`refine` (send a claimed issue back for refinement in one call), `sibling-pr`
for several issues on one read, `review-finish --verdict needs-re-review`, the
claim reaper's read of an unreadable target, the handoff keeping the preflight
marker, and `project-config.sh`.

Run standalone (`python3 tests/test_run_lifecycle.py`) or via `run-tests.sh`.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, '..', 'synergy', 'scripts')
sys.path.insert(0, SCRIPTS)

import wf  # noqa: E402
import wf_claim  # noqa: E402
import wf_core  # noqa: E402
import wf_pick  # noqa: E402
import wf_review  # noqa: E402

CFG = {'org': 'o', 'repo': 'r', 'review_labels': {}}


def invoke(fn, args):
    out = io.StringIO()
    with redirect_stdout(out), mock.patch('sys.exit', side_effect=SystemExit) as ex:
        try:
            fn(args)
        except SystemExit:
            pass
    return json.loads(out.getvalue()), ex.call_args[0][0] if ex.call_args else None


class RefineTests(unittest.TestCase):

    def test_stage_first_then_comment_unassign_release(self):
        calls = []

        def fake_set_stage(cfg, number, stage):
            calls.append(('stage', number, stage))
            return True, 'set'

        def fake_run(cmd, *a, **k):
            calls.append(tuple(cmd[:3]))
            return 0, '', ''

        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as fh:
            fh.write('Say which screen this changes.\n')
        try:
            args = wf.build_parser().parse_args(['refine', '--issue', '7', '--body-file', fh.name])
            with mock.patch.object(wf_pick, 'prepare_cfg', lambda: CFG), \
                    mock.patch.object(wf_pick, 'set_stage', fake_set_stage), \
                    mock.patch.object(wf_pick, 'run', fake_run), \
                    mock.patch.object(wf_claim, 'release_claims', lambda t: {t[0]: True}):
                result, code = invoke(args.func, args)
        finally:
            os.remove(fh.name)
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ('stage', 7, wf_core.STAGE_NAMES['stage-refinement']))
        self.assertEqual(calls[1], ('gh', 'issue', 'comment'))
        self.assertEqual(calls[2], ('gh', 'issue', 'edit'))
        self.assertTrue(result['stage_set'] and result['commented']
                        and result['unassigned'] and result['claim_released'])

    def test_an_empty_comment_is_refused(self):
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as fh:
            fh.write('   \n')
        try:
            args = wf.build_parser().parse_args(['refine', '--issue', '7', '--body-file', fh.name])
            with mock.patch.object(wf_pick, 'prepare_cfg', lambda: CFG):
                result, code = invoke(args.func, args)
        finally:
            os.remove(fh.name)
        self.assertEqual((result['status'], code), ('usage', 2))


def pr(number, closes, branch='b'):
    return {'number': number, 'title': 't', 'url': 'u', 'headRefName': branch,
            'isDraft': False, 'labels': {'nodes': []},
            'closingIssuesReferences': {'nodes': [{'number': n} for n in closes]}}


class SiblingPrTests(unittest.TestCase):

    def run_for(self, argv, nodes):
        reads = []

        def fake_graphql(*a, **k):
            reads.append(a)
            return True, {'repository': {'pullRequests': {'nodes': nodes}}}, ''

        args = wf.build_parser().parse_args(argv)
        with mock.patch.object(wf_review, 'prepare_cfg', lambda: CFG), \
                mock.patch.object(wf_review, 'gh_graphql', fake_graphql):
            result, code = invoke(args.func, args)
        return result, code, len(reads)

    def test_one_issue_keeps_the_old_shape(self):
        result, code, reads = self.run_for(['sibling-pr', '5'], [pr(9, [5], 'other')])
        self.assertEqual((code, reads, result['issue'], result['found']), (0, 1, 5, 1))
        self.assertEqual([p['number'] for p in result['prs']], [9])

    def test_several_issues_share_one_read(self):
        result, code, reads = self.run_for(
            ['sibling-pr', '5', '6', '7', '--exclude-branch', 'mine'],
            [pr(9, [6], 'other'), pr(10, [5, 7], 'mine')])
        self.assertEqual((code, reads, result['found']), (0, 1, 1))
        answers = {e['issue']: [p['number'] for p in e['prs']] for e in result['by_issue']}
        self.assertEqual(answers, {5: [], 6: [9], 7: []})


class ReviewVerdictTests(unittest.TestCase):

    def test_needs_re_review_replaces_approved(self):
        names = wf_core.review_names({})
        add, remove = wf_core.reconcile_review_labels(
            [names['approved']], 'needs-re-review', names)
        self.assertEqual((add, remove), ([names['needs-re-review']], [names['approved']]))

    def test_review_finish_accepts_it(self):
        args = wf.build_parser().parse_args(
            ['review-finish', '--pr', '3', '--verdict', 'needs-re-review'])
        self.assertEqual(args.verdict, 'needs-re-review')


class ClaimTargetStateTests(unittest.TestCase):

    def test_an_unreadable_target_still_returns_six_values(self):
        with mock.patch.object(wf_claim, 'gh_json', lambda *a, **k: (False, None, 'boom')):
            state = wf_claim.claim_target_state(CFG, 'issue-4')
        self.assertEqual(len(state), 6)
        self.assertIsNone(state[2])


class HandoffTests(unittest.TestCase):

    def test_keeps_the_preflight_marker(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, '.claude')
            os.makedirs(folder)
            for name in ('plan.md', 'preflight-passed.txt', 'label-cache.json'):
                open(os.path.join(folder, name), 'w').close()
            args = wf.build_parser().parse_args(['handoff', '--pr', '3', '--issue', '4'])
            with mock.patch.object(wf_review, 'prepare_cfg', lambda: CFG), \
                    mock.patch.object(wf_review, 'holds_claim', lambda t: True), \
                    mock.patch.object(wf_review, 'add_review_label', lambda *a: (True, '')), \
                    mock.patch.object(wf_review, 'set_stages',
                                      lambda cfg, m, *a: {n: (True, 'set') for n in m}), \
                    mock.patch.object(wf_review, 'release_claims',
                                      lambda t: {x: True for x in t}), \
                    mock.patch.object(wf_review, 'repo_root', lambda: root):
                result, code = invoke(args.func, args)
            self.assertEqual(code, 0)
            self.assertEqual(sorted(os.listdir(folder)), ['preflight-passed.txt'])


# The resolved path, not the bare name: on Windows a bare `bash` can start the
# WSL launcher in System32, which cannot see this checkout.
BASH = shutil.which('bash')


@unittest.skipUnless(BASH, 'bash is not on PATH')
class ProjectConfigTests(unittest.TestCase):

    SCRIPT = os.path.normpath(os.path.join(SCRIPTS, 'project-config.sh'))

    def run_in(self, cwd):
        done = subprocess.run([BASH, self.SCRIPT], cwd=cwd, capture_output=True,
                              text=True, encoding='utf-8')
        return done.stdout

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, '.git'))
        os.makedirs(os.path.join(self.root, 'src', 'deep'))

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self):
        with open(os.path.join(self.root, 'ClaudeProject.md'), 'w', newline='\n') as fh:
            fh.write('# P\n\n## Identity\n\norg x\n\n## Project Board\n\nboard\n\n'
                     '## Quality Gate\n\nmake\n')

    def test_drops_later_sections_from_a_subdirectory(self):
        self.write_config()
        out = self.run_in(os.path.join(self.root, 'src', 'deep'))
        self.assertIn('## Identity', out)
        self.assertIn('## Quality Gate', out)
        self.assertNotIn('## Project Board', out)
        self.assertTrue(os.path.isfile(os.path.join(self.root, '.claude', 'projected-config.md')))

    def test_a_deleted_config_is_not_found_despite_a_projection(self):
        self.write_config()
        self.run_in(self.root)
        os.remove(os.path.join(self.root, 'ClaudeProject.md'))
        self.assertEqual(self.run_in(self.root).strip(), 'ClaudeProject.md NOT FOUND')


if __name__ == '__main__':
    unittest.main()
