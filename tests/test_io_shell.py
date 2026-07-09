#!/usr/bin/env python3
"""
Integration tests for the `wf` CLI's I/O shell (github-workflow/scripts/wf.py).

The pure decision logic in `wf_core.py` is covered exhaustively by
`tests/test_decision_logic.py`. That suite is deliberately pure — no git, no
`gh`, no I/O — which leaves the *shell* in `wf.py` untested: the atomic claim
push, the status-emission contract (`ok` / `no-candidates` / `all-blocked` /
`error` / `unsupported`), and the two historical `gh`-output-shape bugs. This
glue runs on every real workflow invocation but had no regression net, so a
refactor or a `gh` output-shape change could silently break a fast path with no
test failing.

These tests close that gap **without hitting GitHub**:

  - the atomic-claim CAS is exercised against a real local git repo plus a
    local *bare* remote (no network), so the create / lost / error / release
    behaviour is locked in with repeatable plumbing;
  - the status contract is exercised with `wf`'s own seams
    (`check_environment`, `load_config`, `assemble_candidates`, `acquire_claim`)
    stubbed, asserting each command emits the right `status` and exit code;
  - the shape-regression guards run at the I/O-shell paths that *consume* the
    two shapes (`merged_pr_closing`, `cmd_post_merge`, `_graphql_args`).

Run standalone (`python3 tests/test_io_shell.py`) or via `run-tests.sh` /
`run-tests.ps1`, which now discover every `tests/test_*.py` module.
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

# ── Subject under test ───────────────────────────────────────────────────────
# Import the I/O shell itself (not just its pure core). The shell talks to
# `gh`/`git` through the module-level `run`, `gh_json`, and `gh_graphql`
# helpers, so the tests stub those seams (or use real local git) rather than
# the network.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'github-workflow', 'scripts'),
)
import wf  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _capture(func, *args, **kwargs):
    """Run a command function; return (exit_code, parsed_stdout_json).

    Every command ends in `emit()`, which writes a single JSON object to stdout
    and calls `sys.exit(code)`. Redirect stdout, catch the SystemExit, and parse
    the captured object so a test can assert on both the status and the code.
    """
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            func(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    out = buf.getvalue()
    payload = json.loads(out) if out.strip() else None
    return code, payload


def _pick_args(*argv):
    """Build a parsed `pick` Namespace with real argparse defaults."""
    return wf.build_parser().parse_args(['pick', *argv])


_BASE_CFG = {
    'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
    'branch_convention': 'feature/{number}/{short-desc}',
    'labels': {}, 'review_labels': {}, 'ready_gate': 'label',
    'agent_gating': 'disabled', 'type_capable': False,
    'board': {'project_node_id': None, 'project_title': None,
              'status_field_id': None, 'start_date_field_id': None, 'columns': {}},
}


def _cfg(**over):
    """A deep copy of the baseline config with top-level overrides applied."""
    cfg = json.loads(json.dumps(_BASE_CFG))
    cfg.update(over)
    return cfg


def _candidate(number, labels=('status-ready',), milestone=None):
    return {'number': number, 'title': 'issue %d' % number,
            'labels': list(labels), 'body': '', 'milestone': milestone, 'url': ''}


def _git_available():
    try:
        return subprocess.run(['git', '--version'],
                              capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


# ── status-emission contract ─────────────────────────────────────────────────

class TestPickStatusContract(unittest.TestCase):
    """`wf pick` must emit the documented status + exit code for each outcome.

    The selection/claim logic is driven through `wf`'s own seams; no network.
    """

    def setUp(self):
        env = mock.patch.object(wf, 'check_environment', return_value=None)
        env.start()
        self.addCleanup(env.stop)

    def _use_cfg(self, cfg):
        p = mock.patch.object(wf, 'load_config', return_value=(True, cfg, ''))
        p.start()
        self.addCleanup(p.stop)

    def test_empty_pool_emits_no_candidates(self):
        self._use_cfg(_cfg())
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, [], '')):
            code, payload = _capture(wf.cmd_pick, _pick_args())
        self.assertEqual(code, wf.EXIT_NO_CANDIDATES)
        self.assertEqual(payload['status'], 'no-candidates')

    def test_all_claims_lost_emits_all_blocked(self):
        """Every candidate lost to a rival → all-blocked, never a false ok."""
        self._use_cfg(_cfg())
        pool = [_candidate(1), _candidate(2)]
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, pool, '')), \
                mock.patch.object(wf, 'acquire_claim', return_value='lost'):
            code, payload = _capture(wf.cmd_pick, _pick_args())
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        self.assertEqual(payload['status'], 'all-blocked')
        # Each lost claim is reported as a side effect.
        self.assertEqual({s['issue'] for s in payload['side_effects']}, {1, 2})

    def test_board_column_gate_without_board_emits_error(self):
        """board-column gate with no project-node-id configured → error."""
        self._use_cfg(_cfg(ready_gate='board-column'))
        code, payload = _capture(wf.cmd_pick, _pick_args())
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')

    def test_both_gate_without_board_emits_error(self):
        """both gate with no project-node-id configured → error."""
        self._use_cfg(_cfg(ready_gate='both'))
        with mock.patch.object(wf, 'gh_json', return_value=(True, [], '')):
            code, payload = _capture(wf.cmd_pick, _pick_args())
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')

    def test_type_capable_non_story_mode_emits_unsupported(self):
        """feature/maintenance on a type-capable org defers to the skill."""
        self._use_cfg(_cfg(type_capable=True))
        code, payload = _capture(wf.cmd_pick, _pick_args('--mode', 'feature'))
        self.assertEqual(code, wf.EXIT_UNSUPPORTED)
        self.assertEqual(payload['status'], 'unsupported')
        self.assertEqual(payload['mode'], 'feature')

    def test_label_typed_feature_mode_does_not_defer(self):
        """The same feature mode on a label-typed org runs here (not unsupported)."""
        self._use_cfg(_cfg(type_capable=False))
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, [], '')):
            code, payload = _capture(wf.cmd_pick, _pick_args('--mode', 'feature'))
        # Empty pool, but it reached selection rather than emitting unsupported.
        self.assertEqual(code, wf.EXIT_NO_CANDIDATES)
        self.assertEqual(payload['status'], 'no-candidates')

    def test_missing_org_repo_emits_error(self):
        self._use_cfg(_cfg(org=None))
        code, payload = _capture(wf.cmd_pick, _pick_args())
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')

    def test_config_load_failure_emits_error(self):
        with mock.patch.object(wf, 'load_config',
                               return_value=(False, None, 'no ClaudeProject.md')):
            code, payload = _capture(wf.cmd_pick, _pick_args())
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')
        self.assertIn('ClaudeProject', payload['reason'])

    def test_explicit_closed_issue_emits_all_blocked(self):
        """`--issue N` against an already-closed issue → all-blocked."""
        self._use_cfg(_cfg())

        def fake_run(argv, input_text=None):
            if argv[:3] == ['gh', 'issue', 'view']:
                return 0, json.dumps({
                    'number': 9, 'title': 't', 'labels': [], 'body': '',
                    'milestone': None, 'url': '', 'state': 'CLOSED',
                }), ''
            return 0, '', ''

        with mock.patch.object(wf, 'run', side_effect=fake_run):
            code, payload = _capture(wf.cmd_pick, _pick_args('--issue', '9'))
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        self.assertEqual(payload['status'], 'all-blocked')


# ── atomic claim compare-and-swap (real local git, no network) ───────────────

@unittest.skipUnless(_git_available(), 'git is required for the claim CAS tests')
class TestAtomicClaimCAS(unittest.TestCase):
    """The claim ref is the workflow's exclusive lock. Prove the CAS holds
    against a real bare remote: first writer wins, a rival is detected as a lost
    claim, an unreachable remote is an error (not a phantom lost), and release
    clears both the ref and the local marker."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bare = os.path.join(self.tmp, 'remote.git')
        self.work = os.path.join(self.tmp, 'work')
        self._git(['init', '--bare', self.bare], cwd=self.tmp)
        self._git(['init', self.work], cwd=self.tmp)
        self._configure(self.work)
        # An initial commit so `HEAD^{tree}` resolves for commit-tree.
        with open(os.path.join(self.work, 'README.md'), 'w'):
            pass
        self._git(['add', '.'], cwd=self.work)
        self._git(['commit', '-m', 'init'], cwd=self.work)
        self._git(['remote', 'add', 'origin', self.bare], cwd=self.work)
        self._prev_cwd = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, self._prev_cwd)

    def _git(self, argv, cwd):
        r = subprocess.run(['git'] + argv, cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0:
            self.fail('git %s failed: %s' % (' '.join(argv), r.stderr.strip()))
        return r

    @staticmethod
    def _configure(repo):
        for key, val in (('user.email', 'test@example.com'),
                         ('user.name', 'Test'),
                         ('commit.gpgsign', 'false'),
                         ('init.defaultBranch', 'main')):
            subprocess.run(['git', 'config', key, val], cwd=repo, capture_output=True)

    @staticmethod
    def _ref_exists(target):
        return subprocess.run(
            ['git', 'ls-remote', '--exit-code', 'origin', 'refs/claims/%s' % target],
            capture_output=True, text=True).returncode == 0

    def _marker(self, target):
        # Resolve the marker path the way acquire_claim does, so a symlinked
        # temp dir (e.g. macOS /var → /private/var) doesn't cause a mismatch.
        return wf._claim_marker_path(wf.repo_root(), target)

    def test_first_claim_wins_and_writes_marker(self):
        self.assertEqual(wf.acquire_claim('issue-1'), 'won')
        self.assertTrue(self._ref_exists('issue-1'))
        self.assertTrue(os.path.isfile(self._marker('issue-1')))

    def test_second_distinct_object_is_lost(self):
        self.assertEqual(wf.acquire_claim('issue-1'), 'won')
        # The next attempt builds a different claim object (timestamp/pid/random
        # in the message) and pushes it to the same, already-held ref → a
        # non-fast-forward rejection, which the ls-remote probe resolves to a
        # lost claim rather than an error.
        self.assertEqual(wf.acquire_claim('issue-1'), 'lost')

    def test_release_removes_ref_and_marker(self):
        self.assertEqual(wf.acquire_claim('issue-1'), 'won')
        marker = self._marker('issue-1')
        wf.release_claim('issue-1')
        self.assertFalse(self._ref_exists('issue-1'))
        self.assertFalse(os.path.isfile(marker))

    def test_absent_ref_push_failure_is_error(self):
        """A push that fails while the ref stays absent is an environment error,
        never mistaken for a rival's claim (which would read as a phantom
        all-blocked / empty backlog)."""
        self._git(['remote', 'set-url', 'origin',
                   os.path.join(self.tmp, 'does-not-exist.git')], cwd=self.work)
        with contextlib.redirect_stderr(io.StringIO()):
            outcome = wf.acquire_claim('issue-2')
        self.assertEqual(outcome, 'error')
        self.assertFalse(os.path.isfile(self._marker('issue-2')))


# ── gh-output shape regression guards (I/O-shell consumer paths) ─────────────

class TestShapeRegressionGuards(unittest.TestCase):
    """The two historical `gh`-output-shape bugs, guarded at the I/O-shell paths
    that consume them — complementing the pure-helper tests in
    test_decision_logic.py with the actual shell call sites."""

    def test_merged_pr_closing_reads_graphql_nodes_shape(self):
        """`closingIssuesReferences` arrives wrapped in `{nodes:[…]}` from GraphQL;
        merged_pr_closing must find the issue and return the PR number."""
        cfg = _cfg()
        data = {'repository': {'pullRequests': {'nodes': [
            {'number': 42,
             'closingIssuesReferences': {'nodes': [{'number': 7}]}},
        ]}}}
        with mock.patch.object(wf, 'gh_graphql', return_value=(True, data, '')):
            self.assertEqual(wf.merged_pr_closing(cfg, 7), 42)
            self.assertIsNone(wf.merged_pr_closing(cfg, 999))

    def test_post_merge_consumes_flat_list_shape(self):
        """`gh pr view --json` returns the references as a *flat list*; the
        historical crash fed that list to `.get('nodes')`. cmd_post_merge must
        settle the linked issue without crashing."""
        cfg = _cfg()

        def fake_run(argv, input_text=None):
            if argv[:3] == ['gh', 'pr', 'view']:
                return 0, json.dumps({
                    'number': 50, 'state': 'MERGED', 'mergedAt': '2026-06-24T00:00:00Z',
                    'baseRefName': 'main',
                    'closingIssuesReferences': [{'number': 5}],
                }), ''
            if argv[:3] == ['gh', 'issue', 'view']:
                return 0, json.dumps({'state': 'OPEN', 'labels': []}), ''
            return 0, '', ''  # issue close, etc.

        args = wf.build_parser().parse_args(['post-merge', '--pr', '50'])
        with mock.patch.object(wf, 'check_environment', return_value=None), \
                mock.patch.object(wf, 'load_config', return_value=(True, cfg, '')), \
                mock.patch.object(wf, 'run', side_effect=fake_run):
            code, payload = _capture(args.func, args)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([s['issue'] for s in payload['settled']], [5])
        self.assertTrue(payload['settled'][0]['closed_now'])

    def test_graphql_args_keep_digit_only_id_as_string(self):
        """A digit-only single-select option id must stay a `-f` string; a real
        Int! arg goes through `-F`. (`-F` coerces all-digit values to ints,
        which GitHub rejects for a String!/ID! variable.)"""
        args = wf._graphql_args('mutation($o:String!,$n:Int!){ x }',
                                {'o': '98236657', 'n': 73})
        o_idx = args.index('o=98236657')
        n_idx = args.index('n=73')
        self.assertEqual(args[o_idx - 1], '-f')
        self.assertEqual(args[n_idx - 1], '-F')


class TestRunDecoding(unittest.TestCase):
    """`run()` must decode subprocess output as UTF-8 regardless of host locale.

    `gh` emits UTF-8 (issue bodies carry smart quotes, em dashes, emoji). On
    Windows `subprocess(text=True)` defaults to cp1252, whose reader thread
    dies with `UnicodeDecodeError` on the first unmappable byte — leaving
    `stdout=None` and surfacing only a downstream `'NoneType' … strip` error.
    The picker's fast path crashed exactly here on a real run. These guards
    drive the real `run()` (no mocks) to lock the UTF-8 + errors='replace'
    contract.
    """

    def _emit_bytes(self, raw):
        """Run a child that writes `raw` to stdout's byte buffer; return run()'s stdout."""
        code, out, _ = wf.run([
            sys.executable, '-c',
            'import sys; sys.stdout.buffer.write(%r)' % (raw,),
        ])
        self.assertEqual(code, 0)
        return out

    def test_utf8_output_is_decoded_not_mojibaked(self):
        """An em dash (UTF-8 e2 80 94) round-trips as U+2014, not cp1252 mojibake."""
        self.assertEqual(self._emit_bytes('em—dash'.encode('utf-8')), 'em—dash')

    def test_byte_undefined_in_cp1252_does_not_crash(self):
        """A lone 0x8f (undefined in cp1252, the byte that killed the real run)
        degrades to U+FFFD instead of dropping stdout to None."""
        out = self._emit_bytes(b'before\x8fafter')
        self.assertIsInstance(out, str)
        self.assertIn('before', out)
        self.assertIn('after', out)

    def test_gh_json_tolerates_none_stdout(self):
        """Belt-and-suspenders: even if a future seam hands back None stdout,
        gh_json reports a clean parse outcome rather than an AttributeError."""
        with mock.patch.object(wf, 'run', return_value=(0, None, None)):
            ok, parsed, err = wf.gh_json(['anything'])
        self.assertTrue(ok)
        self.assertIsNone(parsed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
