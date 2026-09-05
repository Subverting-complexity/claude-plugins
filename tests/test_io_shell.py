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
import re
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
import wf_core  # noqa: E402  (the batch-size cap)


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


def _candidates_args(*argv):
    """Build a parsed `candidates` Namespace with real argparse defaults."""
    return wf.build_parser().parse_args(['candidates', *argv])


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

    def test_type_capable_feature_mode_uses_native_types(self):
        """feature mode on a type-capable org filters by native issueType."""
        self._use_cfg(_cfg(type_capable=True))
        with mock.patch.object(wf, 'fetch_native_types',
                               return_value=(True, {1: 'User Story', 2: 'Bug'}, '')), \
                mock.patch.object(wf, 'assemble_candidates',
                                  return_value=(True, [_candidate(1), _candidate(2)], '')):
            # Only issue 1 (User Story) passes the native-type filter;
            # then all claims are lost → all-blocked.
            with mock.patch.object(wf, 'acquire_claim', return_value='lost'):
                code, payload = _capture(wf.cmd_pick, _pick_args('--mode', 'feature'))
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        self.assertEqual(payload['status'], 'all-blocked')
        # Only the User Story candidate was attempted (issue 2 / Bug was filtered out).
        self.assertEqual([s['issue'] for s in payload['side_effects']], [1])

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


# -- bulk-execute: shared branch, sibling dependencies, unclaimed pool read ---

class TestBulkPickPaths(unittest.TestCase):
    """`pick`'s two bulk affordances: `--no-branch` and `--sibling`.

    Both exist for `bulk-execute`, which claims several stories onto one
    branch. Neither may change single-story behaviour, so each test below has
    a counterpart asserting the default path is untouched.
    """

    def setUp(self):
        env = mock.patch.object(wf, 'check_environment', return_value=None)
        env.start()
        self.addCleanup(env.stop)

    def _use_cfg(self, cfg):
        p = mock.patch.object(wf, 'load_config', return_value=(True, cfg, ''))
        p.start()
        self.addCleanup(p.stop)

    @contextlib.contextmanager
    def _claimable(self, candidate, open_issues=()):
        """Stub the claim path so one candidate can be claimed without network.

        `open_issues` are the issue numbers `gh issue view --json state` should
        report as OPEN -- the dependency probe `validate_issue` runs.
        """
        open_set = {int(n) for n in open_issues}

        def fake_gh_json(argv, *a, **kw):
            if argv[:2] == ['issue', 'view']:
                number = int(argv[2])
                return True, {'state': 'OPEN' if number in open_set else 'CLOSED'}, ''
            return True, [], ''

        with mock.patch.object(wf, 'assemble_candidates',
                               return_value=(True, [candidate], '')), \
                mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'apply_in_progress'), \
                mock.patch.object(wf, 'mark_blocked'), \
                mock.patch.object(wf, 'release_claim'), \
                mock.patch.object(wf, 'merged_pr_closing', return_value=None), \
                mock.patch.object(wf, 'gh_json', side_effect=fake_gh_json), \
                mock.patch.object(wf, 'board_move_in_progress',
                                  return_value=(True, 'moved')) as board, \
                mock.patch.object(wf, 'checkout_branch',
                                  return_value=('feature/1/x', True, 'created')) as branch:
            yield board, branch

    def test_no_branch_moves_the_board_but_creates_no_branch(self):
        """Bulk runs share one branch the caller creates, so `pick` must not."""
        self._use_cfg(_cfg())
        with self._claimable(_candidate(1)) as (board, branch):
            code, payload = _capture(wf.cmd_pick,
                                     _pick_args('--checkout', '--no-branch'))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')
        board.assert_called_once()          # the board move still happens
        branch.assert_not_called()          # the branch does not
        self.assertIsNone(payload['branch'])
        self.assertFalse(payload['checked_out'])

    def test_checkout_without_no_branch_still_branches(self):
        """The single-story path is unchanged by the new flag existing."""
        self._use_cfg(_cfg())
        with self._claimable(_candidate(1)) as (board, branch):
            code, payload = _capture(wf.cmd_pick, _pick_args('--checkout'))
        self.assertEqual(code, wf.EXIT_OK)
        board.assert_called_once()
        branch.assert_called_once()
        self.assertEqual(payload['branch'], 'feature/1/x')
        self.assertTrue(payload['checked_out'])

    def test_open_dependency_blocks_when_it_is_not_a_sibling(self):
        """Baseline: execute's dependency rule is intact with no siblings."""
        self._use_cfg(_cfg())
        cand = _candidate(1)
        cand['body'] = 'Blocked by #7'
        with self._claimable(cand, open_issues=[7]):
            code, payload = _capture(wf.cmd_pick, _pick_args())
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        self.assertEqual(payload['side_effects'][0]['action'], 'marked-blocked')
        self.assertIn('#7', payload['side_effects'][0]['detail'])

    def test_open_dependency_on_a_sibling_does_not_block(self):
        """Same issue, same open dependency -- but #7 is in this bulk set."""
        self._use_cfg(_cfg())
        cand = _candidate(1)
        cand['body'] = 'Blocked by #7'
        with self._claimable(cand, open_issues=[7]):
            code, payload = _capture(wf.cmd_pick, _pick_args('--sibling', '7'))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['number'], 1)
        self.assertEqual(payload['siblings'], [7])

    def test_sibling_carve_out_does_not_cover_other_dependencies(self):
        """#7 is a sibling, #8 is not -- #8 still blocks the pick."""
        self._use_cfg(_cfg())
        cand = _candidate(1)
        cand['body'] = 'Depends on #7\nDepends on #8'
        with self._claimable(cand, open_issues=[7, 8]):
            code, payload = _capture(wf.cmd_pick, _pick_args('--sibling', '7'))
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        self.assertIn('#8', payload['side_effects'][0]['detail'])
        self.assertNotIn('#7', payload['side_effects'][0]['detail'])


class TestCandidatesCommand(unittest.TestCase):
    """`wf candidates` reads the pool and claims nothing.

    `bulk-execute` has to see the pool before it can decide which stories
    belong in one pull request, so this command must apply exactly `pick`'s
    filters and sort while performing no writes at all.
    """

    def setUp(self):
        env = mock.patch.object(wf, 'check_environment', return_value=None)
        env.start()
        self.addCleanup(env.stop)
        cfg = mock.patch.object(wf, 'load_config', return_value=(True, _cfg(), ''))
        cfg.start()
        self.addCleanup(cfg.stop)

    def test_pool_is_returned_in_priority_order(self):
        pool = [_candidate(4, labels=('status-ready', 'priority-low')),
                _candidate(2, labels=('status-ready', 'priority-critical'))]
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, pool, '')):
            code, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual([c['number'] for c in payload['candidates']], [2, 4])
        self.assertEqual(payload['total'], 2)

    def test_nothing_is_claimed_or_labelled(self):
        """The whole point of the command: a read with no side effects."""
        with mock.patch.object(wf, 'assemble_candidates',
                               return_value=(True, [_candidate(1)], '')), \
                mock.patch.object(wf, 'acquire_claim') as claim, \
                mock.patch.object(wf, 'apply_in_progress') as marker, \
                mock.patch.object(wf, 'board_move_in_progress') as board:
            code, _ = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(code, wf.EXIT_OK)
        claim.assert_not_called()
        marker.assert_not_called()
        board.assert_not_called()

    def test_dependencies_are_parsed_for_the_caller(self):
        """The set chooser groups on declared linkage, so it needs the deps."""
        cand = _candidate(1)
        cand['body'] = 'Part of the epic.\n\nBlocked by #7'
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, [cand], '')):
            _, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(payload['candidates'][0]['dependencies'], [7])

    def test_bodies_are_truncated_and_flagged(self):
        cand = _candidate(1)
        cand['body'] = 'x' * 900
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, [cand], '')):
            _, payload = _capture(wf.cmd_candidates,
                                  _candidates_args('--body-chars', '10'))
        self.assertEqual(payload['candidates'][0]['body'], 'x' * 10)
        self.assertTrue(payload['candidates'][0]['body_truncated'])

    def test_zero_body_chars_keeps_the_whole_body(self):
        cand = _candidate(1)
        cand['body'] = 'x' * 900
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, [cand], '')):
            _, payload = _capture(wf.cmd_candidates,
                                  _candidates_args('--body-chars', '0'))
        self.assertEqual(len(payload['candidates'][0]['body']), 900)
        self.assertFalse(payload['candidates'][0]['body_truncated'])

    def test_limit_clips_the_listing_but_total_reports_the_pool(self):
        pool = [_candidate(n) for n in range(1, 6)]
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, pool, '')):
            _, payload = _capture(wf.cmd_candidates, _candidates_args('--limit', '2'))
        self.assertEqual(payload['listed'], 2)
        self.assertEqual(payload['total'], 5)

    def test_empty_pool_emits_no_candidates(self):
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, [], '')):
            code, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(code, wf.EXIT_NO_CANDIDATES)
        self.assertEqual(payload['status'], 'no-candidates')


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


# ── org capability resolution ────────────────────────────────────────────────

_ORG_CAPS_RESPONSE = {
    'organization': {
        'issueTypes': {'nodes': [
            {'id': 'IT_bug', 'name': 'Bug', 'isEnabled': True},
            {'id': 'IT_story', 'name': 'User Story', 'isEnabled': True},
            {'id': 'IT_task', 'name': 'Task', 'isEnabled': False},
        ]},
        'issueFields': {'nodes': [
            {'__typename': 'IssueFieldSingleSelect', 'id': 'IFSS_pri',
             'name': 'Priority',
             'options': [{'id': 'o_urgent', 'name': 'Urgent'},
                         {'id': 'o_low', 'name': 'Low'}]},
            {'__typename': 'IssueFieldMultiSelect', 'id': 'IFMS_class',
             'name': 'Classification',
             'options': [{'id': 'o_newfeat', 'name': 'New Feature'}]},
            {'__typename': 'IssueFieldDate', 'id': 'IFD_start',
             'name': 'Start date'},
            {'__typename': 'IssueFieldText', 'id': 'IFT_parent',
             'name': 'Parent'},
        ]},
    },
}


class TestParseOrgCapabilities(unittest.TestCase):
    """Shaping the GraphQL response is pure, so assert it without any I/O."""

    def test_enabled_types_and_typed_fields(self):
        capable, types, fields = wf.parse_org_capabilities(_ORG_CAPS_RESPONSE)
        self.assertTrue(capable)
        # `Task` is disabled: carrying it would only invite a mutation that fails.
        self.assertEqual(types, {'Bug': 'IT_bug', 'User Story': 'IT_story'})
        self.assertEqual(fields['Priority']['data_type'], 'single-select')
        self.assertEqual(fields['Classification']['data_type'], 'multi-select')
        self.assertEqual(fields['Start date']['data_type'], 'date')
        self.assertEqual(fields['Parent']['data_type'], 'text')

    def test_multi_select_option_ids_survive(self):
        """The whole reason this query is GraphQL and not REST."""
        _, _, fields = wf.parse_org_capabilities(_ORG_CAPS_RESPONSE)
        self.assertEqual(fields['Classification']['options'],
                         {'New Feature': 'o_newfeat'})
        self.assertEqual(fields['Priority']['options'],
                         {'Urgent': 'o_urgent', 'Low': 'o_low'})

    def test_user_account_is_not_type_capable(self):
        """A user-owned repo resolves `organization` to null. Valid, not an error."""
        capable, types, fields = wf.parse_org_capabilities({'organization': None})
        self.assertFalse(capable)
        self.assertEqual((types, fields), ({}, {}))


class TestCapabilityCache(unittest.TestCase):
    """The cache must hit, miss, refresh, and never clobber a neighbouring key."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = _cfg(org='acme')
        self.calls = []

    def _stub_graphql(self, data=None, errors=(), err=''):
        def fake(query, **fields):
            self.calls.append(fields)
            return (data if data is not None else _ORG_CAPS_RESPONSE), list(errors), err
        return fake

    def test_miss_queries_then_writes_the_cache(self):
        with mock.patch.object(wf, 'gh_graphql_partial', self._stub_graphql()):
            ok, caps, err = wf.resolve_org_capabilities(self.cfg, root=self.root)
        self.assertTrue(ok, err)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(caps['cached'])
        with open(wf.capability_cache_path(self.root), encoding='utf-8') as fh:
            on_disk = json.load(fh)
        self.assertEqual(on_disk['type_map'], {'Bug': 'IT_bug', 'User Story': 'IT_story'})

    def test_hit_skips_the_round_trip(self):
        with mock.patch.object(wf, 'gh_graphql_partial', self._stub_graphql()):
            wf.resolve_org_capabilities(self.cfg, root=self.root)
            ok, caps, _ = wf.resolve_org_capabilities(self.cfg, root=self.root)
        self.assertTrue(ok)
        self.assertTrue(caps['cached'])
        self.assertEqual(len(self.calls), 1, 'second call must not re-query')

    def test_refresh_forces_a_requery(self):
        with mock.patch.object(wf, 'gh_graphql_partial', self._stub_graphql()):
            wf.resolve_org_capabilities(self.cfg, root=self.root)
            ok, caps, _ = wf.resolve_org_capabilities(self.cfg, root=self.root, refresh=True)
        self.assertTrue(ok)
        self.assertFalse(caps['cached'])
        self.assertEqual(len(self.calls), 2)

    def test_merge_preserves_unrelated_keys(self):
        """`issue-apply` and `issue-audit` share this file; a refresh must not eat them."""
        wf.merge_capability_cache({'skips_reported': True, 'type_map': {'stale': 'x'}},
                                  root=self.root)
        with mock.patch.object(wf, 'gh_graphql_partial', self._stub_graphql()):
            wf.resolve_org_capabilities(self.cfg, root=self.root, refresh=True)
        with open(wf.capability_cache_path(self.root), encoding='utf-8') as fh:
            on_disk = json.load(fh)
        self.assertTrue(on_disk['skips_reported'], 'unrelated key was clobbered')
        self.assertNotIn('stale', on_disk['type_map'], 'refresh must replace its own keys')

    def test_unreadable_cache_is_ignored_not_fatal(self):
        path = wf.capability_cache_path(self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('{not json')
        with mock.patch.object(wf, 'gh_graphql_partial', self._stub_graphql()):
            with contextlib.redirect_stderr(io.StringIO()):
                ok, caps, _ = wf.resolve_org_capabilities(self.cfg, root=self.root)
        self.assertTrue(ok)
        self.assertFalse(caps['cached'])


_EMPTY_ORG_RESPONSE = {
    'organization': {
        'issueTypes': {'nodes': []},
        'issueFields': {'nodes': []},
    },
}


class TestEmptyCapabilityRecord(unittest.TestCase):
    """An org answering with nothing is a failed lookup, not a configuration.

    The FORBIDDEN guard above only catches the denial GitHub bothers to name.
    An under-scoped or expired token can also come back with empty nodes and no
    error at all, and caching that made every later run fall back to labels in
    silence -- the exact failure the denial guard exists to prevent.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.calls = []

    def _stub(self, response):
        def fake(query, **fields):
            self.calls.append(fields)
            return response, [], ''
        return fake

    def test_empty_org_answer_is_not_cached(self):
        with mock.patch.object(wf, 'gh_graphql_partial',
                               self._stub(_EMPTY_ORG_RESPONSE)):
            ok, caps, _ = wf.resolve_org_capabilities(_cfg(org='acme'), root=self.root)
        self.assertTrue(ok)
        self.assertFalse(caps['type_capable'])
        self.assertEqual(caps['owner_kind'], 'organization')
        self.assertFalse(os.path.isfile(wf.capability_cache_path(self.root)),
                         'an empty org answer was written to the cache')

    def test_poisoned_cache_re_queries_and_heals(self):
        """Nobody knows to pass `--refresh` for a failure that reports nothing."""
        wf.merge_capability_cache({'type_capable': False, 'type_map': {},
                                   'field_map': {}}, root=self.root)
        with mock.patch.object(wf, 'gh_graphql_partial', self._stub(_ORG_CAPS_RESPONSE)):
            ok, caps, _ = wf.resolve_org_capabilities(_cfg(org='acme'), root=self.root)
        self.assertTrue(ok)
        self.assertFalse(caps['cached'], 'an all-empty record was trusted')
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(caps['type_capable'])
        with open(wf.capability_cache_path(self.root), encoding='utf-8') as fh:
            on_disk = json.load(fh)
        self.assertEqual(on_disk['type_map'],
                         {'Bug': 'IT_bug', 'User Story': 'IT_story'})

    def test_user_owned_empty_is_cached_and_then_trusted(self):
        """A user-owned repo has no issue types by design, so its empty record
        is legitimate and must not cost a round trip on every run."""
        with mock.patch.object(wf, 'gh_graphql_partial', self._stub({'organization': None})):
            wf.resolve_org_capabilities(_cfg(org='someone'), root=self.root)
            ok, caps, _ = wf.resolve_org_capabilities(_cfg(org='someone'), root=self.root)
        self.assertTrue(ok)
        self.assertTrue(caps['cached'])
        self.assertEqual(len(self.calls), 1, 'a legitimate empty record was re-queried')
        with open(wf.capability_cache_path(self.root), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['owner_kind'], 'user')

    def test_populated_legacy_record_is_still_trusted(self):
        """Records written before `owner_kind` existed carry types or fields,
        so they stay a cache hit and nobody pays for the new key."""
        wf.merge_capability_cache({'type_capable': True,
                                   'type_map': {'Bug': 'IT_bug'},
                                   'field_map': {}}, root=self.root)
        with mock.patch.object(wf, 'gh_graphql_partial', self._stub(_ORG_CAPS_RESPONSE)):
            ok, caps, _ = wf.resolve_org_capabilities(_cfg(org='acme'), root=self.root)
        self.assertTrue(ok)
        self.assertTrue(caps['cached'])
        self.assertEqual(self.calls, [])


class TestOrgCapabilitiesCommand(unittest.TestCase):
    """The command's status/exit contract, which is what callers branch on."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        patches = [
            mock.patch.object(wf, 'repo_root', lambda: self.root),
            mock.patch.object(wf, 'load_config', lambda: (True, _cfg(org='acme'), '')),
        ]
        for pa in patches:
            pa.start()
            self.addCleanup(pa.stop)

    def _args(self, *argv):
        return wf.build_parser().parse_args(['org-capabilities', *argv])

    def test_ok_reports_resolved_purpose_keys(self):
        with mock.patch.object(wf, 'gh_graphql_partial',
                               lambda q, **f: (_ORG_CAPS_RESPONSE, [], '')):
            code, payload = _capture(wf.cmd_org_capabilities, self._args())
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')
        self.assertTrue(payload['type_capable'])
        self.assertEqual(payload['resolved_fields']['field-priority'], 'Priority')
        # Effort is absent from this fixture org, so it is reported, not assumed.
        missing = {m['purpose'] for m in payload['missing_fields']}
        self.assertIn('field-effort', missing)

    def test_user_account_exits_zero(self):
        """Not every repo is org-owned, and that is a configuration, not a fault."""
        self.addCleanup(mock.patch.object(wf, 'org_exists', lambda cfg: False).stop)
        mock.patch.object(wf, 'org_exists', lambda cfg: False).start()
        with mock.patch.object(wf, 'gh_graphql_partial',
                               lambda q, **f: ({'organization': None}, [], '')):
            code, payload = _capture(wf.cmd_org_capabilities, self._args())
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['owner_kind'], 'user')
        self.assertFalse(payload['type_capable'])

    def test_empty_org_exits_non_zero(self):
        """An org that resolves but reports nothing is an under-scoped token."""
        empty = {'organization': {'issueTypes': {'nodes': []},
                                  'issueFields': {'nodes': []}}}

        # The capability query comes back empty; the existence probe confirms
        # the org is really there, which is what makes this a failure.
        with mock.patch.object(wf, 'gh_graphql_partial',
                               lambda q, **f: (empty, [], '')), \
             mock.patch.object(wf, 'org_exists', lambda cfg: True):
            code, payload = _capture(wf.cmd_org_capabilities, self._args())
        self.assertEqual(code, wf.EXIT_CAPABILITY)
        self.assertEqual(payload['status'], 'no-capabilities')
        self.assertIn('read:org', payload['reason'])

    def test_query_failure_is_an_environment_error(self):
        with mock.patch.object(wf, 'gh_graphql_partial',
                               lambda q, **f: (None, [], 'HTTP 401')):
            code, payload = _capture(wf.cmd_org_capabilities, self._args())
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')


class TestFieldNameOverrides(unittest.TestCase):
    """A project that renamed an org field must keep working."""

    def test_claude_project_section_overrides_the_default(self):
        cfg = wf.parse_claude_project(
            '# P\n\n## Issue Types & Fields\n\n'
            '| Purpose key | Field name |\n| --- | --- |\n'
            '| field-priority | `Urgency` |\n'
            '| field-effort | `Effort` |\n')
        self.assertEqual(cfg['fields']['field-priority'], 'Urgency')
        self.assertEqual(wf.field_name(cfg, 'field-priority'), 'Urgency')
        # An unlisted key still falls through to the default inventory.
        self.assertEqual(wf.field_name(cfg, 'field-parent'), 'Parent')

    def test_absent_section_leaves_every_default_in_place(self):
        cfg = wf.parse_claude_project('# P\n\n## Identity\n\n| org | acme |\n')
        self.assertEqual(cfg['fields'], {})
        self.assertEqual(wf.field_name(cfg, 'field-type'), 'Classification')


class TestDeniedCapability(unittest.TestCase):
    """A refused capability must not read as an absent one.

    GraphQL answers a partly-authorised query with the fields the token may
    read plus a FORBIDDEN error for the rest. Treating that as "this org has no
    issue types" is how a run ends up creating issues with blank metadata and
    reporting success.
    """

    FORBIDDEN = [{'type': 'FORBIDDEN', 'path': ['organization', 'issueTypes'],
                  'message': 'acctname does not have permission to retrieve '
                             'issueType information.'}]
    PARTIAL = {'organization': {
        'issueTypes': None,
        'issueFields': {'nodes': [
            {'__typename': 'IssueFieldSingleSelect', 'id': 'IFSS_pri',
             'name': 'Priority', 'options': [{'id': 'o1', 'name': 'Urgent'}]},
        ]},
    }}

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        for pa in (mock.patch.object(wf, 'repo_root', lambda: self.root),
                   mock.patch.object(wf, 'load_config',
                                     lambda: (True, _cfg(org='acme'), ''))):
            pa.start()
            self.addCleanup(pa.stop)

    def _args(self, *argv):
        return wf.build_parser().parse_args(['org-capabilities', *argv])

    def test_denied_path_is_extracted(self):
        self.assertEqual(wf._denied_paths(self.FORBIDDEN),
                         {'organization', 'issueTypes'})

    def test_not_found_is_a_denial(self):
        """NOT_FOUND is what GitHub answers for an org the token may not see.

        Reading it as an absence is how a real organisation came to be cached
        as a personal account, after which every issue was created with no type
        and no field values and nothing reported it.
        """
        self.assertEqual(wf._denied_paths([{'type': 'NOT_FOUND', 'path': ['organization']}]),
                         {'organization'})

    def test_a_refusal_with_no_path_still_counts(self):
        self.assertEqual(wf._denied_paths([{'type': 'FORBIDDEN'}]), {'organization'})

    def test_an_ordinary_error_is_not_a_denial(self):
        self.assertEqual(wf._denied_paths([{'type': 'INTERNAL', 'path': ['x']}]), set())

    def test_denial_exits_non_zero_even_though_fields_resolved(self):
        with mock.patch.object(wf, 'gh_graphql_partial',
                               lambda q, **f: (self.PARTIAL, self.FORBIDDEN, '')):
            code, payload = _capture(wf.cmd_org_capabilities, self._args())
        self.assertEqual(code, wf.EXIT_CAPABILITY)
        self.assertEqual(payload['status'], 'no-capabilities')
        self.assertIn('issueTypes', payload['denied'])
        self.assertIn('gh auth switch', payload['reason'])

    def test_denial_is_never_cached(self):
        """A cached `type_capable: false` that meant 'not allowed to look'
        would make every later run fall back to labels in silence."""
        with mock.patch.object(wf, 'gh_graphql_partial',
                               lambda q, **f: (self.PARTIAL, self.FORBIDDEN, '')):
            ok, caps, _ = wf.resolve_org_capabilities(_cfg(org='acme'), root=self.root)
        self.assertTrue(ok)
        self.assertEqual(caps['denied'], ['issueTypes', 'organization'])
        self.assertFalse(os.path.isfile(wf.capability_cache_path(self.root)),
                         'a denied capability was written to the cache')

    def test_an_org_read_as_a_user_is_not_cached(self):
        """An unreadable org answers with `organization: null` and an error.

        Caching that as a personal account is what silently switched a whole
        org onto the label-only path: no type, no field values, no complaint.
        """
        answer = ({'organization': None},
                  [{'type': 'NOT_FOUND', 'path': ['organization']}], '')
        with mock.patch.object(wf, 'gh_graphql_partial', lambda q, **f: answer):
            ok, caps, _ = wf.resolve_org_capabilities(_cfg(org='acme'), root=self.root)
        self.assertTrue(ok)
        self.assertEqual(caps['denied'], ['organization'])
        self.assertFalse(os.path.isfile(wf.capability_cache_path(self.root)),
                         'an unreadable org was cached as a user account')

    def test_an_empty_answer_carrying_any_error_is_not_cached(self):
        answer = ({'organization': None}, [{'type': 'INTERNAL'}], '')
        with mock.patch.object(wf, 'gh_graphql_partial', lambda q, **f: answer):
            wf.resolve_org_capabilities(_cfg(org='acme'), root=self.root)
        self.assertFalse(os.path.isfile(wf.capability_cache_path(self.root)))

    def test_a_genuine_user_account_is_cached_with_the_schema(self):
        answer = ({'organization': None}, [], '')
        with mock.patch.object(wf, 'gh_graphql_partial', lambda q, **f: answer):
            wf.resolve_org_capabilities(_cfg(org='someone'), root=self.root)
        cached = wf.load_capability_cache(self.root)
        self.assertEqual(cached['owner_kind'], 'user')
        self.assertEqual(cached['schema'], wf.CAPABILITY_CACHE_SCHEMA)

    def test_an_empty_record_from_an_older_schema_is_re_queried(self):
        """A cache poisoned before the fix heals itself, without `--refresh`."""
        wf.merge_capability_cache({'type_capable': False, 'type_map': {},
                                   'field_map': {}, 'owner_kind': 'user'},
                                  self.root)
        self.assertFalse(wf._capability_record_is_usable(
            wf.load_capability_cache(self.root)))
        calls = []

        def _answer(q, **f):
            calls.append(f)
            return ({'organization': {'issueTypes': {'nodes': [
                {'id': 'IT_1', 'name': 'Bug', 'isEnabled': True}]},
                'issueFields': {'nodes': []}}}, [], '')

        with mock.patch.object(wf, 'gh_graphql_partial', _answer):
            ok, caps, _ = wf.resolve_org_capabilities(_cfg(org='acme'), root=self.root)
        self.assertEqual(len(calls), 1, 'the poisoned record was trusted')
        self.assertTrue(caps['type_capable'])
        self.assertEqual(wf.load_capability_cache(self.root)['schema'],
                         wf.CAPABILITY_CACHE_SCHEMA)

    def test_a_current_schema_user_record_costs_no_round_trip(self):
        wf.merge_capability_cache({'type_capable': False, 'type_map': {},
                                   'field_map': {}, 'owner_kind': 'user',
                                   'schema': wf.CAPABILITY_CACHE_SCHEMA}, self.root)

        def _boom(q, **f):
            raise AssertionError('a valid cached record was re-queried')

        with mock.patch.object(wf, 'gh_graphql_partial', _boom):
            ok, caps, _ = wf.resolve_org_capabilities(_cfg(org='someone'), root=self.root)
        self.assertTrue(ok)
        self.assertTrue(caps['cached'])

    def test_unparseable_response_is_an_error(self):
        with mock.patch.object(wf, 'gh_graphql_partial',
                               lambda q, **f: (None, [], 'HTTP 502')):
            code, payload = _capture(wf.cmd_org_capabilities, self._args())
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')


class TestGraphqlPartial(unittest.TestCase):
    """`gh` exits non-zero on a partial response; the body still matters."""

    def test_data_survives_a_non_zero_exit(self):
        body = json.dumps({'data': {'organization': {'issueFields': {'nodes': []}}},
                           'errors': [{'type': 'FORBIDDEN', 'path': ['organization',
                                                                     'issueTypes']}]})
        with mock.patch.object(wf, 'run', lambda a, input_text=None: (1, body, 'forbidden')):
            data, errors, err = wf.gh_graphql_partial('query{}', login='acme')
        self.assertIsNotNone(data)
        self.assertEqual(len(errors), 1)
        self.assertEqual(err, 'forbidden')

    def test_empty_body_is_reported_as_an_error(self):
        with mock.patch.object(wf, 'run', lambda a, input_text=None: (1, '', 'boom')):
            data, errors, err = wf.gh_graphql_partial('query{}', login='acme')
        self.assertIsNone(data)
        self.assertEqual(err, 'boom')


# ── issue-apply ──────────────────────────────────────────────────────────────
# The command writes, so the transport is recorded rather than sent. The fake
# below is a small GitHub: it applies each mutation to an in-memory store and
# serves `read_issue` from the same store, so a test can assert both what was
# sent *and* that reading it back agrees — which is the property the command's
# verification step exists to enforce.

_APPLY_CAPS = {
    'type_capable': True,
    'type_map': {'User Story': 'IT_story', 'Epic': 'IT_epic'},
    'field_map': {
        'Priority': {'id': 'F_pri', 'data_type': 'single-select',
                     'options': {'High': 'o_hi', 'Medium': 'o_med'}},
        'Effort': {'id': 'F_eff', 'data_type': 'single-select',
                   'options': {'Medium': 'o_effmed'}},
        'Classification': {'id': 'F_cls', 'data_type': 'multi-select',
                           'options': {'New Feature': 'o_nf'}},
    },
    'denied': [], 'errors': [], 'cached': False,
}


class _FakeHub(object):
    """An in-memory GitHub for the requests `issue-apply` sends.

    It applies each mutation to a store and serves every read from the same
    store, so a test can assert both what was sent *and* that reading it back
    agrees — which is the property the command's verification exists to
    enforce. It also counts requests, because the round-trip budget for an epic
    tree is itself a requirement.
    """

    def __init__(self, issues=(), labels=None, swallow_fields=False,
                 fail_create=(), fail_link=False):
        self.issues = {i['number']: i for i in issues}
        self.next_number = max(self.issues, default=100) + 1
        self.labels = dict(labels if labels is not None
                           else {'priority-high': 'L_hi', 'priority-medium': 'L_med'})
        self.queries = []      # read round trips
        self.mutations = []    # write round trips
        self.sent = []         # (mutation name, variables) per alias, in order
        # `swallow_fields` models the failure verification is for: a mutation
        # GitHub accepts that changes nothing.
        self.swallow_fields = swallow_fields
        self.fail_create = set(fail_create)
        self.fail_link = fail_link
        self.type_names = {v: k for k, v in _APPLY_CAPS['type_map'].items()}
        self.field_names = {m['id']: (n, m) for n, m
                            in _APPLY_CAPS['field_map'].items()}

    # -- reads --
    def _readback(self, issue):
        nodes = []
        for name, value in issue['fields'].items():
            if isinstance(value, list):
                nodes.append({'field': {'name': name},
                              'options': [{'name': v} for v in value]})
            else:
                nodes.append({'field': {'name': name}, 'name': value})
        return {
            'id': issue['id'], 'number': issue['number'],
            'title': issue['title'], 'body': issue['body'],
            'issueType': {'name': issue['type']} if issue['type'] else None,
            'parent': {'number': issue['parent']} if issue['parent'] else None,
            'blockedBy': {'nodes': [{'number': n} for n in issue['blocked_by']]},
            'labels': {'nodes': [{'name': n} for n in issue['labels']]},
            'issueFieldValues': {'nodes': nodes},
        }

    def gh_graphql(self, query, **fields):
        self.queries.append(query)
        if 'labels(first:100)' in query:
            repository = {'id': 'R_1',
                          'labels': {'nodes': [{'id': i, 'name': n}
                                               for n, i in self.labels.items()]}}
            for alias, number in re.findall(r'(n\d+): issue\(number:(\d+)\)', query):
                issue = self.issues.get(int(number))
                repository[alias] = ({'id': issue['id'], 'number': issue['number']}
                                     if issue else None)
            return True, {'repository': repository}, ''
        if 'issue(number:$number)' in query:
            issue = self.issues.get(int(fields['number']))
            return True, {'repository': {'issue': self._readback(issue)
                                         if issue else None}}, ''
        raise AssertionError('unexpected query: %s' % query)

    def read_issue(self, cfg, number, repo=None):
        ok, data, err = self.gh_graphql(wf.ISSUE_READBACK_QUERY, owner='o',
                                        repo='r', number=number)
        issue = ((data or {}).get('repository') or {}).get('issue')
        if not issue:
            return False, None, 'issue #%s not found' % number
        return True, issue, ''

    # -- writes --
    def _by_id(self, node_id):
        for issue in self.issues.values():
            if issue['id'] == node_id:
                return issue
        return None

    def _apply_fields(self, issue, inputs):
        if self.swallow_fields:
            return
        for spec in inputs:
            name, meta = self.field_names[spec['fieldId']]
            back = {v: k for k, v in (meta.get('options') or {}).items()}
            if 'multiSelectOptionIds' in spec:
                issue['fields'][name] = sorted(back[o] for o
                                               in spec['multiSelectOptionIds'])
            elif 'singleSelectOptionId' in spec:
                issue['fields'][name] = back[spec['singleSelectOptionId']]
            else:
                issue['fields'][name] = list(spec.values())[1]

    def _create(self, arg):
        number = self.next_number
        self.next_number += 1
        issue = {'id': 'I_%d' % number, 'number': number,
                 'title': arg.get('title'), 'body': arg.get('body') or '',
                 'type': self.type_names.get(arg.get('issueTypeId')),
                 'fields': {}, 'parent': None, 'blocked_by': [],
                 'labels': sorted(n for n, i in self.labels.items()
                                  if i in (arg.get('labelIds') or []))}
        self.issues[number] = issue
        self._apply_fields(issue, arg.get('issueFields') or [])
        if arg.get('parentIssueId'):
            parent = self._by_id(arg['parentIssueId'])
            issue['parent'] = parent['number'] if parent else None
        return issue

    def graphql_json(self, query, variables):
        self.mutations.append(query)
        data, errors = {}, []

        if 'createIssue' in query:
            for alias in sorted(variables, key=lambda a: int(a[1:])):
                arg = variables[alias]
                self.sent.append(('createIssue', arg))
                if arg.get('title') in self.fail_create:
                    data[alias] = None
                    errors.append({'path': [alias], 'message': 'nope'})
                    continue
                data[alias] = {'issue': self._readback(self._create(arg))}
            return 0, json.dumps({'data': data, 'errors': errors}), ''

        aliased = re.findall(r'(b\d+): (addBlockedBy|updateIssue)', query)
        if aliased:
            for alias, kind in aliased:
                if self.fail_link:
                    data[alias] = None
                    errors.append({'path': [alias], 'message': 'nope'})
                    continue
                issue = self._by_id(variables['%s_i' % alias])
                if kind == 'addBlockedBy':
                    blocker = self._by_id(variables['%s_b' % alias])
                    self.sent.append(('addBlockedBy', blocker['number']))
                    issue['blocked_by'].append(blocker['number'])
                    data[alias] = {'issue': {
                        'id': issue['id'],
                        'blockedBy': {'nodes': [{'number': n}
                                                for n in issue['blocked_by']]}}}
                else:
                    self.sent.append(('updateIssue', issue['number']))
                    issue['body'] = variables['%s_t' % alias]
                    data[alias] = {'issue': {'id': issue['id'],
                                             'body': issue['body']}}
            return 0, json.dumps({'data': data, 'errors': errors}), ''

        # Single-issue update mutations, which stay unbatched.
        def ok(payload):
            return 0, json.dumps({'data': payload}), ''

        if 'updateIssueIssueType' in query:
            issue = self._by_id(variables['i'])
            self.sent.append(('updateIssueIssueType', variables))
            issue['type'] = self.type_names.get(variables['t'])
            return ok({'updateIssueIssueType': {'issue': {'id': issue['id']}}})

        if 'setIssueFieldValue' in query:
            issue = self._by_id(variables['i'])
            self.sent.append(('setIssueFieldValue', variables))
            self._apply_fields(issue, variables['f'])
            return ok({'setIssueFieldValue': {'issue': {'id': issue['id']}}})

        if 'addSubIssue' in query:
            parent, child = self._by_id(variables['p']), self._by_id(variables['c'])
            self.sent.append(('addSubIssue', variables))
            child['parent'] = parent['number']
            return ok({'addSubIssue': {'issue': {'id': parent['id']}}})

        raise AssertionError('unexpected mutation: %s' % query)

    def names_sent(self):
        return [name for name, _ in self.sent]

    def round_trips(self):
        return len(self.queries) + len(self.mutations)


def _existing(number, **over):
    issue = {'id': 'I_%d' % number, 'number': number, 'title': 'issue %d' % number,
             'body': '', 'type': None, 'fields': {}, 'parent': None,
             'blocked_by': [], 'labels': []}
    issue.update(over)
    return issue


class TestSetIssueFieldsMutation(unittest.TestCase):
    """The mutation text itself, which every other apply test stubs out.

    `issue-apply`'s tests mock `_graphql_json`, so they assert what the caller
    intended to send and never look at the query. That is how a malformed
    declaration reached users: GitHub rejected every field write with
    "Nullability mismatch on variable $f", the value being sent was fine, and
    no test could see the query that was wrong.
    """

    def _capture(self, *args):
        sent = {}

        def fake(query, variables):
            sent['query'] = query
            sent['variables'] = variables
            return 0, json.dumps({'data': {'setIssueFieldValue':
                                           {'issue': {'id': 'I_1'}}}}), ''

        with mock.patch.object(wf, '_graphql_json', fake):
            ok, node, err = wf.set_issue_fields(*args)
        self.assertTrue(ok, err)
        return sent

    def test_the_list_variable_is_declared_non_null(self):
        """`issueFields` is `[IssueFieldCreateOrUpdateInput!]!` on the input
        object, and GraphQL refuses a nullable variable in a non-null position
        however good the value is."""
        sent = self._capture('I_1', [{'fieldId': 'F_1', 'textValue': 'x'}])
        self.assertIn('$f:[IssueFieldCreateOrUpdateInput!]!', sent['query'])

    def test_every_declared_list_variable_is_non_null(self):
        """The same mismatch in any future list argument fails the same way."""
        sent = self._capture('I_1', [{'fieldId': 'F_1', 'textValue': 'x'}])
        decls = re.search(r'mutation\((.*?)\)\{', sent['query']).group(1)
        for decl in decls.split(','):
            if '[' in decl:
                self.assertTrue(decl.rstrip().endswith(']!'),
                                'nullable list variable: %s' % decl)

    def test_the_inputs_are_passed_through_unchanged(self):
        inputs = [{'fieldId': 'F_1', 'singleSelectOptionId': 'O_1'},
                  {'fieldId': 'F_2', 'multiSelectOptionIds': ['O_2', 'O_3']}]
        sent = self._capture('I_9', inputs)
        self.assertEqual(sent['variables'], {'i': 'I_9', 'f': inputs})


class _ApplyCase(unittest.TestCase):
    """Shared plumbing: a spec file on disk and a run against the fake hub."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _spec_file(self, entries):
        path = os.path.join(self.dir, 'spec.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'issues': entries}, fh)
        return path

    def _run(self, entries, hub, extra_argv=()):
        path = self._spec_file(entries)
        args = wf.build_parser().parse_args(['issue-apply', path, *extra_argv])
        stderr = io.StringIO()
        with mock.patch.object(wf, 'load_config', lambda: (True, _cfg(), '')), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg, refresh=False, root=None:
                                  (True, _APPLY_CAPS, '')), \
                mock.patch.object(wf, 'gh_graphql', hub.gh_graphql), \
                mock.patch.object(wf, '_graphql_json', hub.graphql_json), \
                mock.patch.object(wf, 'run',
                                  lambda a, input_text=None: (0, '', '')), \
                contextlib.redirect_stderr(stderr):
            code, payload = _capture(wf.cmd_issue_apply, args)
        with open(path, encoding='utf-8') as fh:
            written = json.load(fh)
        return code, payload, stderr.getvalue(), written

    def _full(self, **over):
        entry = {'key': 'a', 'title': 'A story', 'kind': 'story',
                 'fields': {'field-priority': 'High', 'field-effort': 'Medium'}}
        entry.update(over)
        return entry


class TestIssueApply(_ApplyCase):
    """One command, everything on the issue, and every write read back."""

    def test_a_create_is_one_mutation_carrying_everything(self):
        """The point of the command: no create-then-patch sequence to half-fail."""
        hub = _FakeHub()
        code, payload, _, _ = self._run([self._full()], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(hub.names_sent(), ['createIssue'])
        sent = hub.sent[0][1]
        self.assertEqual(sent['issueTypeId'], 'IT_story')
        self.assertEqual(len(sent['issueFields']), 3)
        self.assertEqual(payload['applied'][0]['action'], 'create')

    def test_the_created_number_is_written_back_to_the_spec(self):
        """So a re-run after a partial failure completes it instead of duplicating."""
        hub = _FakeHub()
        _, payload, _, written = self._run([self._full()], hub)
        self.assertTrue(payload['numbers_written_back'])
        self.assertEqual(written['issues'][0]['number'],
                         payload['applied'][0]['number'])

    def test_re_applying_an_already_correct_issue_writes_nothing(self):
        """Idempotence is what makes re-running a spec a safe recovery step."""
        hub = _FakeHub([_existing(42, type='User Story',
                                  fields={'Priority': 'High', 'Effort': 'Medium',
                                          'Classification': ['New Feature']})])
        code, payload, _, _ = self._run([self._full(number=42)], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(hub.mutations, [])
        self.assertEqual(payload['applied'][0]['changed'], [])

    def test_an_update_sets_only_what_differs(self):
        hub = _FakeHub([_existing(42, type='User Story',
                                  fields={'Priority': 'Medium', 'Effort': 'Medium',
                                          'Classification': ['New Feature']})])
        _, payload, _, _ = self._run([self._full(number=42)], hub)
        self.assertEqual(hub.names_sent(), ['setIssueFieldValue'])
        self.assertEqual(len(hub.sent[0][1]['f']), 1)
        self.assertEqual(payload['applied'][0]['changed'], ['fields'])

    def test_a_missing_mandatory_field_refuses_before_any_write(self):
        hub = _FakeHub()
        code, payload, _, _ = self._run([self._full(fields={'field-effort': 'Medium'})],
                                        hub)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertEqual(payload['status'], 'spec-invalid')
        self.assertIn('Priority', payload['errors'][0])
        self.assertEqual(hub.mutations, [])

    def test_a_cycle_refuses_before_any_write(self):
        hub = _FakeHub()
        entries = [self._full(key='a', blocked_by=['b']),
                   self._full(key='b', blocked_by=['a'])]
        code, payload, _, _ = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertEqual(hub.mutations, [])
        self.assertTrue(payload['cycles'])

    def test_a_parent_cycle_refuses_before_any_write(self):
        """A different fault from a blocked-by cycle, and just as unresolvable."""
        hub = _FakeHub()
        entries = [self._full(key='a', parent='b'), self._full(key='b', parent='a')]
        code, payload, _, _ = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertIn('parent cycle', payload['reason'])
        self.assertEqual(hub.mutations, [])

    def test_an_undefined_field_is_reported_once_for_the_run(self):
        """Once per issue would bury the errors that actually matter."""
        hub = _FakeHub()
        fields = {'field-priority': 'High', 'field-effort': 'Medium',
                  'field-origin': 'Development'}
        entries = [self._full(key='a', fields=fields),
                   self._full(key='b', fields=fields)]
        code, payload, stderr, _ = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['skipped_fields'], ['Origin'])
        self.assertEqual(stderr.count('Origin'), 1)

    def test_a_write_that_does_not_stick_exits_verify_failed(self):
        """An accepted mutation is not a changed value. This is the whole point."""
        hub = _FakeHub(swallow_fields=True)
        code, payload, _, _ = self._run([self._full()], hub)
        self.assertEqual(code, wf.EXIT_VERIFY)
        self.assertEqual(payload['status'], 'verify-failed')
        self.assertTrue(any('Priority' in m for m in payload['mismatches']))

    def test_a_dependency_is_written_as_an_edge_and_in_the_body(self):
        """Both, deliberately: the edge drives the portal, the prose drives unblocking."""
        hub = _FakeHub([_existing(7)])
        code, payload, _, _ = self._run([self._full(blocked_by=[7])], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn('addBlockedBy', hub.names_sent())
        created = hub.issues[payload['applied'][0]['number']]
        self.assertIn('Blocked by #7', created['body'])

    def test_a_spec_local_reference_resolves_to_the_number_just_created(self):
        hub = _FakeHub()
        entries = [self._full(key='epic', kind='epic'),
                   self._full(key='child', parent='epic', blocked_by=['epic'])]
        code, payload, _, _ = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_OK)
        epic_number = payload['applied'][0]['number']
        child = hub.issues[payload['applied'][1]['number']]
        self.assertEqual(child['parent'], epic_number)
        self.assertEqual(child['blocked_by'], [epic_number])

    def test_a_failed_entry_reports_partial_and_keeps_what_landed(self):
        hub = _FakeHub(fail_create={'A story'})
        code, payload, _, _ = self._run([self._full()], hub)
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertEqual(payload['status'], 'partial')
        self.assertIn('create failed', payload['failed'][0]['errors'][0])

    def test_dry_run_validates_and_writes_nothing(self):
        hub = _FakeHub()
        code, payload, _, written = self._run([self._full()], hub, ['--dry-run'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertTrue(payload['dry_run'])
        self.assertEqual(hub.mutations, [])
        self.assertNotIn('number', written['issues'][0])

    def test_a_label_the_repo_does_not_have_refuses_before_writing(self):
        hub = _FakeHub(labels={})
        code, payload, _, _ = self._run([self._full(labels=['priority-high'])], hub)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertEqual(payload['labels'], ['priority-high'])
        self.assertEqual(hub.mutations, [])

    def test_a_denied_capability_refuses_rather_than_writing_blanks(self):
        path = self._spec_file([self._full()])
        args = wf.build_parser().parse_args(['issue-apply', path])
        denied = dict(_APPLY_CAPS, denied=['organization.issueTypes'])
        with mock.patch.object(wf, 'load_config', lambda: (True, _cfg(), '')), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg, refresh=False, root=None:
                                  (True, denied, '')):
            code, payload = _capture(wf.cmd_issue_apply, args)
        self.assertEqual(code, wf.EXIT_CAPABILITY)
        self.assertEqual(payload['status'], 'no-capabilities')

    def test_a_create_naming_no_labels_is_reported(self):
        """Nothing else supplies them, so the issue would be unpickable."""
        hub = _FakeHub()
        code, _, stderr, _ = self._run([self._full()], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn('name no labels', stderr)

    def test_a_create_that_names_labels_is_not_reported(self):
        hub = _FakeHub()
        code, _, stderr, _ = self._run(
            [self._full(labels=['priority-high'])], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertNotIn('name no labels', stderr)

    def test_an_update_is_never_reported_for_labels(self):
        """An issue that already exists got its labels when it was filed."""
        hub = _FakeHub([_existing(42, type='User Story',
                                  fields={'Priority': 'High', 'Effort': 'Medium',
                                          'Classification': ['New Feature']})])
        _, _, stderr, _ = self._run([self._full(number=42)], hub)
        self.assertNotIn('name no labels', stderr)


class TestEpicTreeBatching(_ApplyCase):
    """A whole tree in one invocation, batched by hierarchy level."""

    def _tree(self):
        """One epic, three features, nine stories — the shape from the story."""
        entries = [{'key': 'epic', 'title': 'Epic', 'kind': 'epic',
                    'fields': {'field-priority': 'High', 'field-effort': 'Medium'}}]
        for f in range(3):
            entries.append({'key': 'f%d' % f, 'title': 'Feature %d' % f,
                            'kind': 'story', 'parent': 'epic',
                            'fields': {'field-priority': 'High',
                                       'field-effort': 'Medium'}})
            for st in range(3):
                entries.append({'key': 's%d_%d' % (f, st),
                                'title': 'Story %d.%d' % (f, st), 'kind': 'story',
                                'parent': 'f%d' % f,
                                'fields': {'field-priority': 'High',
                                           'field-effort': 'Medium'}})
        return entries

    def test_thirteen_issues_take_four_round_trips(self):
        """Three levels plus the link phase. Anything more is per-issue chatter."""
        hub = _FakeHub()
        entries = self._tree()
        # One edge, so the link phase runs and is counted.
        entries[1]['blocked_by'] = ['epic']
        code, payload, _, _ = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(len(payload['applied']), 13)
        self.assertEqual(len(hub.mutations), 4)
        # Plus the single prerequisite lookup: repo id and label ids together.
        self.assertEqual(len(hub.queries), 1)

    def test_children_are_created_after_their_parents(self):
        hub = _FakeHub()
        code, payload, _, _ = self._run(self._tree(), hub)
        self.assertEqual(code, wf.EXIT_OK)
        by_key = {r['key']: r['number'] for r in payload['applied']}
        for f in range(3):
            feature = hub.issues[by_key['f%d' % f]]
            self.assertEqual(feature['parent'], by_key['epic'])
            for st in range(3):
                story = hub.issues[by_key['s%d_%d' % (f, st)]]
                self.assertEqual(story['parent'], by_key['f%d' % f])

    def test_a_level_larger_than_the_cap_is_split_across_requests(self):
        """The node limit is real, so a big level becomes several requests."""
        hub = _FakeHub()
        entries = [self._full(key='s%d' % n, title='Story %d' % n)
                   for n in range(wf_core.BATCH_MAX_NODES + 3)]
        code, payload, _, _ = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(len(payload['applied']), wf_core.BATCH_MAX_NODES + 3)
        self.assertEqual(len(hub.mutations), 2)

    def test_an_edge_may_point_at_any_level_because_links_come_last(self):
        hub = _FakeHub()
        entries = self._tree()
        entries[0]['blocked_by'] = ['s2_2']   # the epic waits on the last story
        code, payload, _, _ = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_OK)
        by_key = {r['key']: r['number'] for r in payload['applied']}
        epic = hub.issues[by_key['epic']]
        self.assertEqual(epic['blocked_by'], [by_key['s2_2']])
        self.assertIn('Blocked by #%d' % by_key['s2_2'], epic['body'])

    def test_one_failed_entry_does_not_stop_the_others_in_its_batch(self):
        hub = _FakeHub(fail_create={'Story 1'})
        entries = [self._full(key='s%d' % n, title='Story %d' % n) for n in range(3)]
        code, payload, _, written = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_PARTIAL)
        self.assertEqual([r['entry'] for r in payload['failed']], ['s1'])
        landed = [r['number'] for r in payload['applied'] if r['number']]
        self.assertEqual(len(landed), 2)
        # The two that landed are numbered in the spec, so a re-run updates them.
        self.assertEqual([e.get('number') for e in written['issues']],
                         [landed[0], None, landed[1]])

    def test_re_running_after_a_partial_failure_completes_the_remainder(self):
        hub = _FakeHub(fail_create={'Story 1'})
        entries = [self._full(key='s%d' % n, title='Story %d' % n) for n in range(3)]
        code, first, _, written = self._run(entries, hub)
        self.assertEqual(code, wf.EXIT_PARTIAL)

        hub.fail_create = set()
        code, second, _, _ = self._run(written['issues'], hub)
        self.assertEqual(code, wf.EXIT_OK)
        # Three issues in total, not six: the two that landed were updated.
        self.assertEqual(len(hub.issues), 3)
        self.assertEqual([r['action'] for r in second['applied']],
                         ['create', 'update', 'update'])


class TestIssueAudit(_ApplyCase):
    """The audit reads and proposes. It must never issue a mutation."""

    def _issue(self, number, **over):
        issue = {'number': number, 'title': 'Story %d' % number, 'body': '',
                 'issueType': {'name': 'User Story'},
                 'labels': {'nodes': []}, 'blockedBy': {'nodes': []},
                 'parent': None, 'issueFieldValues': {'nodes': []}}
        issue.update(over)
        return issue

    def _run(self, issues, extra_argv=(), pages=None, caps=None):
        """Run the audit against a canned issue list. Returns (code, payload, sent)."""
        out = os.path.join(self.dir, 'audit.json')
        args = wf.build_parser().parse_args(
            ['issue-audit', '--out', out, *extra_argv])
        sent = []
        remaining = list(pages if pages is not None else [issues])

        def gh_graphql(query, **fields):
            sent.append(('query', fields))
            page = remaining.pop(0)
            return True, {'repository': {'issues': {
                'pageInfo': {'hasNextPage': bool(remaining),
                             'endCursor': 'c%d' % len(sent)},
                'nodes': page}}}, ''

        def no_mutations(*a, **k):
            raise AssertionError('the audit must not write')

        with mock.patch.object(wf, 'load_config', lambda: (True, _cfg(), '')), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg, refresh=False, root=None:
                                  (True, caps or _APPLY_CAPS, '')), \
                mock.patch.object(wf, 'gh_graphql', gh_graphql), \
                mock.patch.object(wf, '_graphql_json', no_mutations), \
                mock.patch.object(wf, 'run', no_mutations), \
                contextlib.redirect_stderr(io.StringIO()):
            code, payload = _capture(wf.cmd_issue_audit, args)
        spec = None
        if os.path.isfile(out):
            with open(out, encoding='utf-8') as fh:
                spec = json.load(fh)
        return code, payload, sent, spec

    def _classified(self, number, **over):
        return self._issue(number, issueFieldValues={'nodes': [
            {'field': {'name': 'Priority'}, 'name': 'High'},
            {'field': {'name': 'Effort'}, 'name': 'Medium'},
            {'field': {'name': 'Classification'},
             'options': [{'name': 'New Feature'}]}]}, **over)

    def test_a_clean_backlog_exits_zero_and_writes_no_spec(self):
        code, payload, _, spec = self._run([self._classified(1)])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIsNone(spec)
        self.assertEqual(payload['summary']['issues_with_gaps'], 0)

    def test_gaps_exit_non_zero_so_it_can_run_as_a_check(self):
        code, payload, _, _ = self._run([self._issue(1)])
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual(payload['status'], 'gaps')

    def test_the_spec_it_writes_is_what_issue_apply_consumes(self):
        code, payload, _, spec = self._run([self._issue(1)])
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual(spec['issues'][0]['number'], 1)
        self.assertEqual(spec['issues'][0]['fields']['field-effort'],
                         wf_core.SPEC_PLACEHOLDER)
        self.assertTrue(payload['spec_written'])

    def test_it_issues_no_mutation_of_its_own(self):
        """Both transports raise if touched, so this asserts by construction."""
        issue = self._issue(1, body='Blocked by #2')
        code, _, sent, _ = self._run([issue, self._issue(2)])
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertEqual([kind for kind, _ in sent], ['query'])

    def test_an_inferred_edge_is_proposed_not_applied(self):
        """Body prose is not reliable enough to build a graph from unattended."""
        issue = self._issue(1, body='## Dependencies\n\nBlocked by #2\n')
        _, payload, _, spec = self._run([issue, self._classified(2)])
        self.assertEqual(spec['issues'][0]['blocked_by'], [2])
        kinds = [g['kind'] for g in payload['issues'][0]['gaps']]
        self.assertIn('missing-edge', kinds)

    def test_quiet_keeps_the_exit_code_and_drops_the_detail(self):
        code, payload, _, _ = self._run([self._issue(1)], ['--quiet'])
        self.assertEqual(code, wf.EXIT_GAPS)
        self.assertNotIn('issues', payload)
        self.assertEqual(payload['summary']['issues_with_gaps'], 1)

    def test_limit_stops_the_scan_early(self):
        issues = [self._issue(n) for n in range(1, 6)]
        _, payload, _, _ = self._run(issues, ['--limit', '2'])
        self.assertEqual(payload['summary']['issues_scanned'], 2)

    def test_since_is_passed_to_the_query(self):
        _, _, sent, _ = self._run([self._classified(1)], ['--since', '2026-01-01'])
        self.assertEqual(sent[0][1]['since'], '2026-01-01')

    def test_pages_are_followed_to_the_end(self):
        pages = [[self._classified(1)], [self._classified(2)]]
        _, payload, sent, _ = self._run(None, pages=pages)
        self.assertEqual(len(sent), 2)
        self.assertEqual(payload['summary']['issues_scanned'], 2)

    def test_repo_targets_another_repo_without_reconfiguring(self):
        """Adoption happens one repo at a time, from a single working copy."""
        _, payload, _, _ = self._run([self._classified(1)],
                                     ['--repo', 'acme/other'])
        self.assertEqual(payload['repo'], 'acme/other')

    def test_a_denied_capability_refuses_rather_than_reporting_a_clean_repo(self):
        code, payload, _, _ = self._run(
            [self._classified(1)],
            caps=dict(_APPLY_CAPS, denied=['organization.issueFields']))
        self.assertEqual(code, wf.EXIT_CAPABILITY)
        self.assertEqual(payload['status'], 'no-capabilities')


class TestHandoffAndClaims(unittest.TestCase):
    """The commands that replaced the mechanism templates."""

    def _cfg(self):
        return _cfg(board={'project_node_id': None, 'project_title': None,
                           'status_field_name': 'Status', 'columns': {}})

    def _run(self, argv, calls, moved=(True, 'moved to In Review'), rc=0):
        args = wf.build_parser().parse_args(argv)

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            return rc, '', ''

        with mock.patch.object(wf, 'prepare_cfg', self._cfg), \
                mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'board_move', lambda *a: moved), \
                mock.patch.object(wf, 'repo_root', lambda: tempfile.mkdtemp()), \
                contextlib.redirect_stderr(io.StringIO()):
            return _capture(args.func, args)

    def test_handoff_labels_the_pr_moves_the_issue_and_frees_the_claim(self):
        calls = []
        code, payload = self._run(['handoff', '--pr', '7', '--issue', '3'], calls)
        self.assertEqual(code, wf.EXIT_OK)
        joined = [' '.join(c) for c in calls]
        self.assertTrue(any('pr edit 7' in c and 'claude-authored' in c
                            and 'review-needs-review' in c for c in joined))
        self.assertTrue(any('issue edit 3' in c and 'status-in-review' in c
                            and 'status-in-progress' in c for c in joined))
        self.assertTrue(any('refs/claims/issue-3' in c for c in joined))
        self.assertEqual(payload['issues'][0]['board_moved'], True)

    def test_a_failed_gate_enters_review_as_changes_requested(self):
        """The PR is real work but not ready to approve; say so in the label."""
        calls = []
        _, payload = self._run(
            ['handoff', '--pr', '7', '--issue', '3', '--gate-failed'], calls)
        self.assertEqual(payload['review_label'], 'review-changes-requested')

    def test_handoff_reports_an_unmoved_board_without_failing(self):
        """A board is a mirror of the labels, never the source of truth."""
        code, payload = self._run(['handoff', '--pr', '7', '--issue', '3'], [],
                                  moved=(False, 'no board configured'))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['issues'][0]['board_moved'], False)

    def test_board_move_accepts_a_purpose_key_as_well_as_a_column_name(self):
        code, payload = self._run(['board-move', '3', '--column', 'col-done'], [],
                                  moved=(True, 'moved to Done'))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['column'], 'Done')

    def test_claim_release_names_everything_it_freed(self):
        calls = []
        with mock.patch.object(wf, 'check_environment', lambda: None):
            code, payload = self._run(
                ['claim-release', '--issue', '3', '--pr', '7'], calls)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['released'], ['issue-3', 'pr-7'])

    def test_claim_release_with_nothing_named_is_a_usage_error(self):
        with mock.patch.object(wf, 'check_environment', lambda: None):
            code, _ = self._run(['claim-release'], [])
        self.assertEqual(code, wf.EXIT_USAGE)


class TestClaimReap(unittest.TestCase):

    def _reap(self, refs, states, argv=()):
        args = wf.build_parser().parse_args(['claim-reap', *argv])
        released = []

        def target_state(cfg, target):
            return states[target]

        with mock.patch.object(wf, 'check_environment', lambda: None), \
                mock.patch.object(wf, 'prepare_cfg', lambda: _cfg()), \
                mock.patch.object(wf, 'list_claim_refs', lambda: (refs, '')), \
                mock.patch.object(wf, 'claim_age_hours', lambda sha: 9), \
                mock.patch.object(wf, 'claim_target_state', target_state), \
                mock.patch.object(wf, 'release_claim', released.append), \
                contextlib.redirect_stderr(io.StringIO()):
            code, payload = _capture(wf.cmd_claim_reap, args)
        return code, payload, released

    def test_an_empty_remote_is_reported_rather_than_walked(self):
        code, payload, _ = self._reap([], {})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['reaped'], [])

    def test_a_stale_ref_is_freed_and_a_live_one_is_left_alone(self):
        refs = [('aaa', 'issue-3'), ('bbb', 'issue-4')]
        states = {'issue-3': ('issue', 3, 'CLOSED', [], False),
                  'issue-4': ('issue', 4, 'OPEN', ['status-in-progress'], False)}
        code, payload, released = self._reap(refs, states)
        self.assertEqual(released, ['issue-3'])
        self.assertEqual(payload['summary'], {'reaped': 1, 'suspect': 1, 'skipped': 0})
        self.assertEqual(payload['suspect'][0]['ref'], 'refs/claims/issue-4')

    def test_dry_run_reports_the_verdicts_without_deleting_anything(self):
        refs = [('aaa', 'issue-3')]
        states = {'issue-3': ('issue', 3, 'CLOSED', [], False)}
        _, payload, released = self._reap(refs, states, ['--dry-run'])
        self.assertEqual(released, [])
        self.assertEqual(payload['summary']['reaped'], 1)

    def test_a_ref_that_names_neither_an_issue_nor_a_pr_is_never_deleted(self):
        refs = [('aaa', 'sprint-lock')]
        states = {'sprint-lock': (None, None, None, [], False)}
        _, payload, released = self._reap(refs, states)
        self.assertEqual(released, [])
        self.assertEqual(payload['summary']['suspect'], 1)


class TestConfigAudit(unittest.TestCase):
    """Preflight's drift checks: what fails, what warns, and what it costs."""

    _SECTIONS = list(wf_core.REQUIRED_CONFIG_SECTIONS)
    _PINNED = ['Priority', 'Effort', 'Classification', 'Origin']
    _LABELS = ['status-ready', 'status-in-progress', 'type-bug']

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.scan = os.path.join(self.dir, 'plugin')
        os.makedirs(self.scan)

    def _write_config(self, sections):
        path = os.path.join(self.dir, 'ClaudeProject.md')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('# Project\n\n')
            for name in sections:
                fh.write('## %s\n\nbody\n\n' % name)

    def _write_instruction(self, name, text):
        with open(os.path.join(self.scan, name), 'w', encoding='utf-8') as fh:
            fh.write(text)

    def _run(self, sections=None, labels=None, types=None, board=None,
             cfg_over=None, argv=(), caps=None, pins_ok=True):
        self._write_config(self._SECTIONS if sections is None else sections)
        cfg = _cfg(**(cfg_over or {}))
        args = wf.build_parser().parse_args(
            ['config-audit', '--scan', self.scan, *argv])
        sent = []

        def gh_graphql(query, **fields):
            sent.append('repo')
            return True, {'repository': {'labels': {
                'pageInfo': {'hasNextPage': False, 'endCursor': None},
                'nodes': [{'name': n} for n
                          in (self._LABELS if labels is None else labels)]}},
                'board': board}, ''

        def gh_graphql_partial(query, **fields):
            sent.append('pins')
            if not pins_ok:
                return None, [{'message': 'forbidden'}], 'boom'
            nodes = [{'name': t['name'], 'isEnabled': t['enabled'],
                      'pinnedFields': [{'name': n} for n in t['pinned']]}
                     for t in (types if types is not None
                               else [{'name': 'User Story', 'enabled': True,
                                      'pinned': self._PINNED}])]
            return {'organization': {'issueTypes': {'nodes': nodes}}}, [], ''

        with mock.patch.object(wf, 'load_config', lambda: (True, cfg, '')), \
                mock.patch.object(wf, 'repo_root', lambda: self.dir), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg, refresh=False, root=None:
                                  (True, caps or _APPLY_CAPS, '')), \
                mock.patch.object(wf, 'gh_graphql', gh_graphql), \
                mock.patch.object(wf, 'gh_graphql_partial', gh_graphql_partial), \
                contextlib.redirect_stderr(io.StringIO()):
            code, payload = _capture(wf.cmd_config_audit, args)
        return code, payload, sent

    def _checks(self, payload):
        return [f['check'] for f in payload['findings']]

    # ── the clean case ───────────────────────────────────────────────────────

    def test_a_configured_project_passes(self):
        code, payload, _ = self._run()
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['findings'], [])

    def test_the_clean_case_says_what_it_compared(self):
        _, payload, _ = self._run()
        for check in ('config-section', 'label-reference', 'config-label',
                      'label-drift', 'field-unmapped', 'field-unpinned'):
            self.assertIn(check, payload['checked'])

    # ── the four failures ────────────────────────────────────────────────────

    def test_a_missing_section_fails_the_run(self):
        code, payload, _ = self._run(
            sections=[s for s in self._SECTIONS if s != 'Issue Types & Fields'])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(payload['status'], 'drift')
        self.assertEqual(self._checks(payload), ['config-section'])

    def test_a_call_site_applying_a_retired_label_fails_the_run(self):
        """The named case: `set-selection.md` still applying `status-ready`."""
        self._write_instruction(
            'set-selection.md',
            'Mark it ready:\n\n    gh issue edit $n --add-label status-ready\n')
        code, payload, _ = self._run(labels=['status-in-progress'])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['label-missing'])
        self.assertIn('set-selection.md', payload['findings'][0]['detail'])

    def test_a_configured_label_the_repo_lacks_fails_the_run(self):
        code, payload, _ = self._run(
            cfg_over={'labels': {'claude-ready': 'claude-ready'}})
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertIn('config-label', self._checks(payload))

    def test_an_unpinned_mandatory_field_fails_the_run(self):
        code, payload, _ = self._run(types=[
            {'name': 'User Story', 'enabled': True,
             'pinned': ['Priority', 'Effort', 'Classification']}])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['field-unpinned'])
        self.assertIn('Origin', payload['findings'][0]['detail'])

    # ── the warnings ─────────────────────────────────────────────────────────

    def test_pin_asymmetry_warns_without_failing_the_run(self):
        """`Epic` is not pinned to `Parent`, correctly. That is not an error."""
        code, payload, _ = self._run(types=[
            {'name': 'User Story', 'enabled': True,
             'pinned': self._PINNED + ['Parent']},
            {'name': 'Epic', 'enabled': True, 'pinned': self._PINNED}])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._checks(payload), ['pin-asymmetry'])

    def test_label_drift_warns_without_failing_the_run(self):
        code, payload, _ = self._run(
            labels=self._LABELS + ['priority-medium', 'priority:medium', 'bug'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(set(self._checks(payload)), {'label-drift'})
        self.assertEqual(payload['summary']['warning'], 2)

    def test_an_unmapped_org_field_warns(self):
        caps = dict(_APPLY_CAPS, field_map=dict(_APPLY_CAPS['field_map'],
                                                **{'Team': {}}))
        code, payload, _ = self._run(caps=caps)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn('field-unmapped', self._checks(payload))

    def test_a_board_column_that_no_longer_resolves_warns(self):
        board = {'title': 'widgets', 'field': {'options': [
            {'id': 'live1234', 'name': 'In Progress'}]}}
        code, payload, _ = self._run(
            board=board,
            cfg_over={'board': {'project_node_id': 'PVT_1',
                                'project_title': 'widgets',
                                'status_field_name': 'Status',
                                'columns': {'col-in-progress': 'dead1234'}}})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._checks(payload), ['board-column'])

    def test_a_node_id_pointing_at_a_different_board_warns(self):
        board = {'title': 'something else', 'field': {'options': []}}
        _, payload, _ = self._run(
            board=board,
            cfg_over={'board': {'project_node_id': 'PVT_1',
                                'project_title': 'widgets',
                                'status_field_name': 'Status', 'columns': {}}})
        self.assertEqual(self._checks(payload), ['board-title'])

    def test_unreadable_pinning_is_reported_rather_than_assumed_correct(self):
        """Not knowing is not the same as being fine."""
        code, payload, _ = self._run(pins_ok=False)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._checks(payload), ['pin-unknown'])
        self.assertIn('field-unpinned', payload['skipped'])

    # ── what it costs, and what it refuses ───────────────────────────────────

    def test_the_api_checks_cost_two_round_trips(self):
        """Preflight runs at the top of every session, so this is a budget."""
        _, _, sent = self._run(
            cfg_over={'board': {'project_node_id': 'PVT_1', 'project_title': None,
                                'status_field_name': 'Status', 'columns': {}}},
            board={'title': None, 'field': {'options': []}})
        self.assertEqual(sent, ['repo', 'pins'])

    def test_offline_runs_the_checks_that_need_no_network(self):
        def explode(*a, **k):
            raise AssertionError('--offline must not touch the network')

        with mock.patch.object(wf, 'gh_graphql', explode):
            code, payload, _ = self._run(
                sections=[s for s in self._SECTIONS if s != 'Label Map'],
                argv=['--offline'])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['config-section'])
        self.assertEqual(payload['checked'], ['config-section'])

    def test_quiet_keeps_the_exit_code_and_drops_the_detail(self):
        code, payload, _ = self._run(sections=[], argv=['--quiet'])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertNotIn('findings', payload)
        self.assertEqual(payload['summary']['critical'], len(self._SECTIONS))

    def test_a_denied_capability_refuses_rather_than_reporting_a_clean_org(self):
        code, payload, _ = self._run(
            caps=dict(_APPLY_CAPS, denied=['organization.issueFields']))
        self.assertEqual(code, wf.EXIT_CAPABILITY)
        self.assertEqual(payload['status'], 'no-capabilities')

    def test_a_placeholder_in_an_instruction_file_is_not_a_label(self):
        self._write_instruction(
            'claim.md', 'gh issue edit $n --add-label "{status_ready_label}"\n')
        code, payload, _ = self._run(labels=[])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._checks(payload), [])


class TestDependencySection(unittest.TestCase):
    """The body prose `wf_core.parse_dependencies()` reads back."""

    def test_a_section_is_added_to_a_body_that_has_none(self):
        body = wf.ensure_dependency_section('Some context.', [7, 9])
        self.assertIn('## Dependencies', body)
        self.assertIn('Blocked by #7', body)
        self.assertIn('Some context.', body)

    def test_an_existing_section_is_replaced_not_appended(self):
        body = wf.ensure_dependency_section(
            'Intro\n\n## Dependencies\n\nBlocked by #1\n', [7])
        self.assertEqual(body.count('## Dependencies'), 1)
        self.assertNotIn('#1', body)

    def test_a_following_section_survives(self):
        body = wf.ensure_dependency_section(
            'Intro\n\n## Dependencies\n\nBlocked by #1\n\n## Acceptance\n\nA thing.\n',
            [7])
        self.assertIn('## Acceptance', body)
        self.assertIn('A thing.', body)

    def test_no_dependencies_leaves_the_body_alone(self):
        self.assertEqual(wf.ensure_dependency_section('Intro', []), 'Intro')


if __name__ == '__main__':
    unittest.main(verbosity=2)
