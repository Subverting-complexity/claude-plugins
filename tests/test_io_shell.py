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

    def test_non_forbidden_errors_are_not_denials(self):
        self.assertEqual(wf._denied_paths([{'type': 'NOT_FOUND', 'path': ['x']}]), set())

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
