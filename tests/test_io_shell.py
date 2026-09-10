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
import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
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

# Sentinel for a keyword whose default is a value, so `None` stays meaningful.


# ── helpers ──────────────────────────────────────────────────────────────────

def _capture(func, *args, **kwargs):
    """Run a command function; return (exit_code, parsed_stdout_json).

    Every command ends in `emit()`, which writes a single JSON object to stdout
    and calls `sys.exit(code)`. Redirect stdout, catch the SystemExit, and parse
    the captured object so a test can assert on both the status and the code.

    The board's Status field is cached for the life of a `wf` process, which in
    production is one command. In here it is one test, so the cache is cleared
    on the way in rather than letting one test's fake board answer the next
    test's question.
    """
    wf._BOARD_FIELD_CACHE.clear()
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
    'labels': {}, 'review_labels': {}, 'fields': {},
    'type_capable': False,
    # A board is no longer optional for selection: the pool *is* its Backlog
    # column. The baseline carries one so every picker test exercises the real
    # path; the tests that care about a board-less project override it.
    'board': {'project_node_id': 'PVT_base', 'project_title': None,
              'status_field_name': 'Status', 'status_field_id': None,
              'start_date_field_id': None, 'columns': {}},
}


_UNSET = object()


def _cfg(**over):
    """A deep copy of the baseline config with top-level overrides applied."""
    cfg = json.loads(json.dumps(_BASE_CFG))
    cfg.update(over)
    return cfg


def _candidate(number, labels=(), milestone=None):
    return {'number': number, 'title': 'issue %d' % number,
            'labels': list(labels), 'body': '', 'milestone': milestone, 'url': ''}


class _CodeOwned(dict):
    """An `Ownership` map answering `Code agent` for any issue not named in it.

    Truthy even when empty, because the picker treats a falsy ownership map as
    "the org told us nothing" and empties the pool.

    The picker excludes anything it cannot confirm is code work, so a fixture
    saying nothing about ownership would empty every pool and every test would
    be asserting that filter rather than what it meant to assert. This is the
    ordinary state of a configured backlog: most issues are code work and the
    org has said so. Tests about ownership pass a real map.
    """

    def get(self, key, default=None):
        return dict.get(self, key, 'Code agent')

    def __bool__(self):
        return True


def _facets(types=None, priority=None, classification=None, effort=None,
            ownership=_UNSET):
    """The `load_issue_facets` return shape.

    `cmd_pick` and `cmd_candidates` read the org's native types and field
    values before selecting, so every test that drives them stubs this. The
    type, priority and classification maps are empty by default — that is the
    org-has-not-typed-this case, and it is a case the picker has to handle.
    Ownership is not: pass `ownership={}` for the org that defines no such
    field, which is a pool of nothing.
    """
    return {'types': types or {}, 'priority': priority or {},
            'classification': classification or {}, 'effort': effort or {},
            'ownership': _CodeOwned() if ownership is _UNSET
            else (ownership or {})}


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
        facets = mock.patch.object(wf, 'load_issue_facets', return_value=_facets())
        facets.start()
        self.addCleanup(facets.stop)

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

    def test_a_project_with_no_board_cannot_pick(self):
        """The pool is the board's Backlog column, so no board means no pool.

        An error rather than `no-candidates`: those look identical to the
        caller, and one of them is a project nobody finished configuring.
        """
        self._use_cfg(_cfg(board={}))
        code, payload = _capture(wf.cmd_pick, _pick_args())
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')
        self.assertIn('project-node-id', payload['reason'])

    def test_type_capable_feature_mode_uses_native_types(self):
        """feature mode on a type-capable org filters by native issueType."""
        self._use_cfg(_cfg(type_capable=True))
        with mock.patch.object(wf, 'load_issue_facets',
                               return_value=_facets({1: 'User Story', 2: 'Bug'})), \
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

    def test_feature_mode_without_native_types_is_refused(self):
        """No classifier, no answer -- and it says which, rather than guessing."""
        self._use_cfg(_cfg(type_capable=False))
        with mock.patch.object(wf, 'load_issue_facets', return_value=_facets({})), \
                mock.patch.object(wf, 'assemble_candidates',
                                  return_value=(True, [_candidate(1)], '')):
            code, payload = _capture(wf.cmd_pick, _pick_args('--mode', 'feature'))
        self.assertEqual(code, wf.EXIT_CAPABILITY)
        self.assertEqual(payload['status'], 'no-capabilities')
        self.assertIn('native issue type', payload['reason'])

    def test_story_mode_never_asks_the_org_for_a_type(self):
        self._use_cfg(_cfg(type_capable=False))
        with mock.patch.object(wf, 'load_issue_facets', return_value=_facets({})), \
                mock.patch.object(wf, 'assemble_candidates',
                                  return_value=(True, [], '')):
            code, payload = _capture(wf.cmd_pick, _pick_args())
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
        facets = mock.patch.object(wf, 'load_issue_facets', return_value=_facets())
        facets.start()
        self.addCleanup(facets.stop)

    def _use_cfg(self, cfg):
        p = mock.patch.object(wf, 'load_config', return_value=(True, cfg, ''))
        p.start()
        self.addCleanup(p.stop)

    @contextlib.contextmanager
    def _claimable(self, candidate, open_issues=(), closed_issues=()):
        """Stub the claim path so one candidate can be claimed without network.

        `open_issues` and `closed_issues` are the candidate's native blocked-by
        edges and their states -- the graph `validate_issue` reads. It used to
        read the body prose and look each reference up one call at a time; the
        edge is the source of truth now, so this stubs the edge.
        """
        edges = ([{'number': int(n), 'state': 'OPEN'} for n in open_issues]
                 + [{'number': int(n), 'state': 'CLOSED'} for n in closed_issues])

        with mock.patch.object(wf, 'assemble_candidates',
                               return_value=(True, [candidate], '')), \
                mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'apply_in_progress'), \
                mock.patch.object(wf, 'mark_blocked',
                                  return_value=(True, 'moved')), \
                mock.patch.object(wf, 'release_claim'), \
                mock.patch.object(wf, 'merged_pr_closing', return_value=None), \
                mock.patch.object(wf, 'issue_edges', return_value=edges), \
                mock.patch.object(wf, 'gh_json', return_value=(True, [], '')), \
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


class TestStartDateStamp(unittest.TestCase):
    """`set_start_date` writes a field, and everything about it is best-effort.

    It is capability-gated, so an org with no `Start date` field returns early
    and the mutation call is never reached. That is why unpacking two values
    from `set_issue_fields` -- which answers (ok, node, err) -- survived: the
    ValueError only fired on orgs that define the field, and only after the
    claim, the label, the assignment and the board move had already landed.
    The run then looked failed and was not.
    """

    def _caps(self, data_type='date'):
        return (True, {'field_map': {'Start date': {'id': 'F_1',
                                                    'data_type': data_type}}}, '')

    def test_a_successful_write_reports_the_date(self):
        with mock.patch.object(wf, 'resolve_org_capabilities',
                               return_value=self._caps()),                 mock.patch.object(wf, 'gh_json',
                                  return_value=(True, {'id': 'I_1'}, '')),                 mock.patch.object(wf, 'set_issue_fields',
                                  return_value=(True, {'id': 'I_1'}, '')) as write:
            done, msg = wf.set_start_date(_cfg(), 1)
        self.assertTrue(done, msg)
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        self.assertIn(today, msg)
        # The date reached the mutation as a date-typed field input.
        self.assertEqual(write.call_args[0][1],
                         [{'fieldId': 'F_1', 'dateValue': today}])

    def test_a_rejected_write_reports_the_mutation_error(self):
        with mock.patch.object(wf, 'resolve_org_capabilities',
                               return_value=self._caps()),                 mock.patch.object(wf, 'gh_json',
                                  return_value=(True, {'id': 'I_1'}, '')),                 mock.patch.object(wf, 'set_issue_fields',
                                  return_value=(False, None, 'field is read-only')):
            done, msg = wf.set_start_date(_cfg(), 1)
        self.assertFalse(done)
        self.assertEqual(msg, 'field is read-only')

    def test_an_org_without_the_field_never_reaches_the_mutation(self):
        with mock.patch.object(wf, 'resolve_org_capabilities',
                               return_value=(True, {'field_map': {}}, '')),                 mock.patch.object(wf, 'set_issue_fields') as write:
            done, msg = wf.set_start_date(_cfg(), 1)
        self.assertFalse(done)
        self.assertIn('does not define', msg)
        write.assert_not_called()

    def test_a_non_date_field_is_reported_not_crashed(self):
        """A `Start date` the org typed as text still shapes a valid input."""
        with mock.patch.object(wf, 'resolve_org_capabilities',
                               return_value=self._caps('text')),                 mock.patch.object(wf, 'gh_json',
                                  return_value=(True, {'id': 'I_1'}, '')),                 mock.patch.object(wf, 'set_issue_fields',
                                  return_value=(True, {'id': 'I_1'}, '')):
            done, msg = wf.set_start_date(_cfg(), 1)
        self.assertTrue(done, msg)


class TestBestEffortSteps(unittest.TestCase):
    """A cosmetic side effect must never cost the run its branch.

    The board move and the start-date stamp sit between the claim and the
    branch. If one of them raises, `checkout_branch` never runs and the story
    is left claimed with nowhere to work -- the one outcome the caller cannot
    recover from on its own.
    """

    def setUp(self):
        env = mock.patch.object(wf, 'check_environment', return_value=None)
        env.start()
        self.addCleanup(env.stop)
        facets = mock.patch.object(wf, 'load_issue_facets', return_value=_facets())
        facets.start()
        self.addCleanup(facets.stop)

    def test_the_wrapper_turns_a_raise_into_a_message(self):
        def boom(cfg, number):
            raise ValueError('too many values to unpack')

        ok, msg = wf.best_effort(boom, _cfg(), 1)
        self.assertFalse(ok)
        self.assertIn('ValueError', msg)
        self.assertIn('too many values to unpack', msg)

    def _pick_with(self, **patches):
        with mock.patch.object(wf, 'load_config',
                               return_value=(True, _cfg(), '')),                 mock.patch.object(wf, 'assemble_candidates',
                                  return_value=(True, [_candidate(1)], '')),                 mock.patch.object(wf, 'acquire_claim', return_value='won'),                 mock.patch.object(wf, 'apply_in_progress'),                 mock.patch.object(wf, 'release_claim'),                 mock.patch.object(wf, 'merged_pr_closing', return_value=None),                 mock.patch.object(wf, 'issue_edges', return_value=[]),                 mock.patch.object(wf, 'gh_json', return_value=(True, [], '')),                 mock.patch.object(wf, 'checkout_branch',
                                  return_value=('feature/1/x', True, 'created')) as branch,                 contextlib.ExitStack() as stack:
            for name, patch in patches.items():
                # `__name__` so the wrapper can label the step it caught,
                # which a bare Mock does not carry and a real function does.
                stack.enter_context(
                    mock.patch.object(wf, name, __name__=name, **patch))
            code, payload = _capture(wf.cmd_pick, _pick_args('--checkout'))
        return code, payload, branch

    def test_a_raising_start_date_still_leaves_a_branch(self):
        code, payload, branch = self._pick_with(
            board_move_in_progress={'return_value': (True, 'moved')},
            set_start_date={'side_effect': ValueError('boom')})
        self.assertEqual(code, wf.EXIT_OK)
        branch.assert_called_once()
        self.assertEqual(payload['branch'], 'feature/1/x')
        self.assertTrue(payload['checked_out'])
        self.assertFalse(payload['start_date_set'])
        self.assertIn('set start date', payload['start_date_message'])

    def test_a_raising_board_move_still_leaves_a_branch(self):
        code, payload, branch = self._pick_with(
            board_move_in_progress={'side_effect': RuntimeError('board down')},
            set_start_date={'return_value': (True, 'stamped')})
        self.assertEqual(code, wf.EXIT_OK)
        branch.assert_called_once()
        self.assertFalse(payload['board_moved'])
        self.assertIn('board move in progress', payload['board_message'])


def _facet_node(number, type_name=None, values=()):
    """One issue as the facets query returns it."""
    nodes = []
    for field, value in values:
        if isinstance(value, (list, tuple)):
            nodes.append({'field': {'name': field},
                          'options': [{'name': v} for v in value]})
        else:
            nodes.append({'field': {'name': field}, 'name': value})
    return {'number': number,
            'issueType': {'name': type_name} if type_name else None,
            'issueFieldValues': {'nodes': nodes}}


def _facet_page(nodes, has_next=False, cursor='c1'):
    return {'repository': {'issues': {
        'pageInfo': {'hasNextPage': has_next, 'endCursor': cursor},
        'nodes': nodes}}}


class TestIssueFacets(unittest.TestCase):
    """The one query that tells the picker what the org itself says.

    It replaced a query that asked for 200 records on a connection GitHub caps
    at 100. That is a hard `EXCESSIVE_PAGINATION` error rather than a short
    answer, so the query failed on every repo, every time, and the picker fell
    back to labels while reporting a type-capable org. Nothing failed loudly
    enough to notice, which is what these tests are for.
    """

    def _run(self, pages, cfg=None):
        """Drive `fetch_issue_facets` over a scripted list of responses."""
        calls = []

        def fake(query, **fields):
            calls.append((query, fields))
            return (True, pages[len(calls) - 1], '')

        with mock.patch.object(wf, 'gh_graphql', side_effect=fake):
            ok, facets, err = wf.fetch_issue_facets(cfg or _cfg())
        return ok, facets, err, calls

    def test_the_page_size_is_within_githubs_connection_limit(self):
        ok, _, _, calls = self._run([_facet_page([])])
        self.assertTrue(ok)
        size = int(re.search(r'issues\(first:(\d+)', calls[0][0]).group(1))
        self.assertLessEqual(size, 100, 'GitHub rejects a page over 100 outright')

    def test_one_query_answers_type_priority_and_classification(self):
        page = _facet_page([
            _facet_node(1, 'Feature', [('Priority', 'Urgent'),
                                       ('Classification', ['Tech Debt'])]),
            _facet_node(2, 'Bug', [('Priority', 'Low')]),
            _facet_node(3),
        ])
        ok, facets, _, calls = self._run([page])
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(facets['types'], {1: 'Feature', 2: 'Bug'})
        self.assertEqual(facets['priority'], {1: 'Urgent', 2: 'Low'})
        self.assertEqual(facets['classification'], {1: ['Tech Debt']})

    def test_a_second_page_is_followed_with_the_cursor(self):
        pages = [_facet_page([_facet_node(1, 'Bug')], has_next=True, cursor='CUR'),
                 _facet_page([_facet_node(2, 'Feature')])]
        ok, facets, _, calls = self._run(pages)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertIn('after:$cursor', calls[1][0])
        self.assertEqual(calls[1][1]['cursor'], 'CUR')
        self.assertEqual(facets['types'], {1: 'Bug', 2: 'Feature'})

    def test_the_first_page_declares_no_cursor_variable(self):
        """An unused non-null variable is a GraphQL error, not a no-op."""
        _, _, _, calls = self._run([_facet_page([])])
        self.assertNotIn('cursor', calls[0][0])
        self.assertNotIn('cursor', calls[0][1])

    def test_paging_stops_at_the_cap_and_says_so(self):
        """A read that stopped at the cap is not a smaller backlog. It used to
        come back as success, and every issue past the cap had no Priority,
        Effort or Ownership as far as the picker knew."""
        pages = [_facet_page([_facet_node(n, 'Bug')], has_next=True,
                             cursor='C%d' % n)
                 for n in range(1, wf.FACET_MAX_PAGES + 2)]
        ok, _, err, calls = self._run(pages)
        self.assertEqual(len(calls), wf.FACET_MAX_PAGES)
        self.assertFalse(ok)
        self.assertIn('more than', err)

    def test_a_failed_query_stops_the_command(self):
        """Every decision reads these fields, so an empty answer is not a
        degraded one. It used to fall back to empty maps, and an empty pool
        read exactly like a finished backlog."""
        with mock.patch.object(wf, 'gh_graphql', return_value=(False, None, 'boom')):
            code, payload = _capture(wf.load_issue_facets, _cfg())
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['status'], 'error')
        self.assertIn('boom', payload['reason'])

    def test_a_renamed_field_is_read_under_the_project_name(self):
        """A project that renamed `Priority` still orders by its field."""
        cfg = _cfg(fields={'field-priority': 'Urgency'})
        page = _facet_page([_facet_node(1, 'Bug', [('Urgency', 'High')])])
        with mock.patch.object(wf, 'gh_graphql', return_value=(True, page, '')):
            facets = wf.load_issue_facets(cfg)
        self.assertEqual(facets['priority'], {1: 'High'})


def _board_item(number, status='Backlog', labels=(), assignee=None, state='OPEN'):
    return {'fieldValueByName': {'name': status} if status else None,
            'content': {'number': number, 'title': 'story %d' % number,
                        'body': '', 'state': state, 'url': '',
                        'labels': {'nodes': [{'name': n} for n in labels]},
                        'milestone': None,
                        'assignees': {'nodes': ([{'login': assignee}]
                                                if assignee else [])}}}


_BOARD_OPTIONS = ('Backlog', 'In Progress', 'In Review', 'Blocked',
                  'Non-code', 'Needs refinement', 'Parked', 'Needs attention',
                  'Done')


def _board_page(items, has_next=False, cursor=None, options=_BOARD_OPTIONS):
    return {'node': {
        'field': {'options': [{'name': n} for n in options]},
        'items': {
            'pageInfo': {'hasNextPage': has_next, 'endCursor': cursor},
            'nodes': list(items)}}}


class TestSpecBodyFile(unittest.TestCase):
    """A body that lives in a file rather than inside the JSON.

    A body is prose -- fenced code, backticks, `$`, quotes, blank lines -- and
    hand-building that into a JSON string in a shell is where bodies get
    mangled. Naming a file sidesteps it.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, 'body.md')
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write('## Summary\n\nA `$PATH` "quote" and a ``fence``.\n')

    def test_the_file_is_read_verbatim(self):
        body, err = wf.entry_body({'body_file': self.path})
        self.assertEqual(err, '')
        self.assertIn('A `$PATH` "quote"', body)

    def test_an_inline_body_wins_and_reads_nothing(self):
        body, err = wf.entry_body({'body': 'inline', 'body_file': 'nope.md'})
        self.assertEqual((body, err), ('inline', ''))

    def test_an_entry_with_neither_has_no_body(self):
        self.assertEqual(wf.entry_body({'title': 'x'}), (None, ''))

    def test_a_file_that_is_not_there_is_a_spec_error(self):
        errors = wf.spec_body_errors([{'title': 'x',
                                       'body_file': os.path.join(self.dir, 'gone.md')}])
        self.assertEqual(len(errors), 1)
        self.assertIn('body_file', errors[0])

    def test_a_readable_spec_reports_nothing(self):
        self.assertEqual(wf.spec_body_errors([{'body_file': self.path}]), [])


class TestTypedCreateInput(unittest.TestCase):
    """What `issue-apply` writes when the org types the issue natively.

    The rule lives at the one place that builds a create, so the three
    commands that file issues cannot each keep their own house style -- which
    is why the board ended up with `[BUG]` titles beside untitled ones and a
    `bug` label beside a `Bug` type.
    """

    CTX = {'repo_id': 'R_1', 'labels': {'type-bug': 'L_type', 'priority-high':
                                        'L_pri', 'status-parked': 'L_parked'}}
    CAPS = {'type_map': {'Bug': 'IT_bug'}}

    def _build(self, entry, native_type='Bug', cfg=None):
        plan = {'type': native_type, 'fields': {}}
        dropped = []
        args = wf._create_input(cfg or _cfg(), self.CTX, self.CAPS, entry, plan,
                                None, entry.get('body'), dropped)
        return args, dropped

    def test_a_type_label_is_not_written_when_the_type_says_it(self):
        args, dropped = self._build(
            {'title': 'Crash on save',
             'labels': ['type-bug', 'priority-high', 'status-parked']})
        self.assertEqual(args['labelIds'], sorted(['L_pri', 'L_parked']))
        self.assertEqual(dropped, ['type-bug'])

    def test_a_kind_prefix_is_not_written_into_the_title(self):
        args, dropped = self._build({'title': '[BUG] Crash on save',
                                     'labels': ['status-parked']})
        self.assertEqual(args['title'], 'Crash on save')
        self.assertIn('[BUG]', dropped)

    def test_the_native_type_is_still_set(self):
        args, _ = self._build({'title': 'Crash on save'})
        self.assertEqual(args['issueTypeId'], 'IT_bug')

    def test_an_untyped_entry_is_stripped_the_same_way(self):
        """On every org: a classifier nothing reads is clutter, not a fallback."""
        args, dropped = self._build({'title': '[BUG] Crash on save',
                                     'labels': ['type-bug', 'status-parked']},
                                    native_type=None)
        self.assertEqual(args['title'], 'Crash on save')
        self.assertEqual(args['labelIds'], ['L_parked'])
        self.assertEqual(dropped, ['type-bug', '[BUG]'])
        self.assertNotIn('issueTypeId', args)

    def test_a_named_milestone_rides_in_the_same_create(self):
        """Sprint placement is part of the one write, not a follow-up edit."""
        ctx = dict(self.CTX, milestones={'Sprint 7': 'MI_7'})
        args = wf._create_input(_cfg(), ctx, self.CAPS,
                                {'title': 'Crash on save', 'milestone': 'Sprint 7'},
                                {'type': 'Bug', 'fields': {}}, None, None, [])
        self.assertEqual(args['milestoneId'], 'MI_7')

    def test_no_milestone_key_means_no_milestone_written(self):
        args, _ = self._build({'title': 'Crash on save'})
        self.assertNotIn('milestoneId', args)

    def test_nothing_is_reported_when_the_entry_was_already_clean(self):
        _, dropped = self._build({'title': 'Crash on save',
                                  'labels': ['status-parked']})
        self.assertEqual(dropped, [])


class TestBoardColumnCandidates(unittest.TestCase):
    """The pool read: every open unassigned issue in the Backlog column.

    Two ways this has failed for real. It asked for 200 records on a connection
    GitHub caps at 100, which is a hard error rather than a short answer -- so
    it did not degrade, it failed the whole `pick` with `candidate fetch
    failed`. And it treated a column the board does not have as an empty
    column, so a misconfigured board and a finished backlog looked identical.
    """

    CFG = None

    def _run(self, pages):
        calls = []

        def fake(query, **fields):
            calls.append((query, fields))
            return (True, pages[len(calls) - 1], '')

        cfg = _cfg()
        cfg['board'] = {'project_node_id': 'PVT_x', 'status_field_name': 'Status'}
        with mock.patch.object(wf, 'gh_graphql', side_effect=fake):
            ok, issues, err = wf._board_column_candidates(cfg, 'Backlog')
        return ok, issues, err, calls

    def test_the_page_size_is_within_githubs_connection_limit(self):
        ok, _, _, calls = self._run([_board_page([])])
        self.assertTrue(ok)
        size = int(re.search(r'items\(first:(\d+)', calls[0][0]).group(1))
        self.assertLessEqual(size, 100, 'GitHub rejects a page over 100 outright')

    def test_a_second_page_is_followed_with_the_cursor(self):
        pages = [_board_page([_board_item(1)], has_next=True, cursor='CUR'),
                 _board_page([_board_item(2)])]
        ok, issues, _, calls = self._run(pages)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertIn('after:$cursor', calls[1][0])
        self.assertEqual(calls[1][1]['cursor'], 'CUR')
        self.assertEqual([i['number'] for i in issues], [1, 2])

    def test_the_first_page_declares_no_cursor_variable(self):
        """An unused non-null variable is a GraphQL error, not a no-op."""
        _, _, _, calls = self._run([_board_page([])])
        self.assertNotIn('cursor', calls[0][0])
        self.assertNotIn('cursor', calls[0][1])

    def test_paging_stops_at_the_cap_and_says_so(self):
        """The cards past the cap could be the whole of the Backlog column,
        so a partial read is an unknown pool rather than a short one."""
        pages = [_board_page([_board_item(n)], has_next=True, cursor='C%d' % n)
                 for n in range(1, wf.BOARD_MAX_PAGES + 2)]
        ok, _, err, calls = self._run(pages)
        self.assertEqual(len(calls), wf.BOARD_MAX_PAGES)
        self.assertFalse(ok)
        self.assertIn('Archive', err)

    def test_a_column_the_board_does_not_have_is_an_error(self):
        """Not an empty pool. The two are indistinguishable to the caller, and
        the misconfiguration is by far the likelier of the two."""
        pages = [_board_page([_board_item(1)],
                             options=('Todo', 'Doing', 'Done'))]
        ok, _, err, _ = self._run(pages)
        self.assertFalse(ok)
        self.assertIn("no 'Backlog' column", err)
        self.assertIn('Todo, Doing, Done', err)

    def test_a_board_with_no_status_field_is_an_error(self):
        ok, _, err, _ = self._run([_board_page([], options=())])
        self.assertFalse(ok)
        self.assertIn("no 'Status' field", err)

    def test_a_board_that_is_not_configured_is_an_error(self):
        """Selection reads the board, so a project without one has no pool."""
        cfg = _cfg()
        cfg['board'] = {}
        ok, _, err = wf._board_column_candidates(cfg, 'Backlog')
        self.assertFalse(ok)
        self.assertIn('project-node-id', err)

    def test_only_open_unassigned_items_in_the_named_column_are_returned(self):
        pages = [_board_page([
            _board_item(1),
            _board_item(2, status='In Progress'),
            _board_item(3, assignee='someone'),
            _board_item(4, state='CLOSED'),
            _board_item(5, status=None),
        ])]
        ok, issues, _, _ = self._run(pages)
        self.assertTrue(ok)
        self.assertEqual([i['number'] for i in issues], [1])


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
        facets = mock.patch.object(wf, 'load_issue_facets', return_value=_facets())
        facets.start()
        self.addCleanup(facets.stop)

    def test_the_pool_is_ordered_by_the_org_priority_field(self):
        """The field is the whole order, and the listing carries its value.

        The labels here are the ones that used to decide it, and they now
        decide nothing: `priority-critical` on #4 loses to an `Urgent` field
        value on #2, and #4 -- carrying no field value at all -- sorts last.
        """
        pool = [_candidate(4, labels=('priority-critical',)),
                _candidate(2, labels=('priority-low',))]
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, pool, '')),                 mock.patch.object(wf, 'load_issue_facets',
                                  return_value=_facets(priority={2: 'Urgent'})):
            code, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([c['number'] for c in payload['candidates']], [2, 4])
        self.assertEqual(payload['candidates'][0]['priority'], 'Urgent')
        self.assertIsNone(payload['candidates'][1]['priority'])
        # #4 has no field value, so nothing ranks it -- and that is reported.
        self.assertEqual(payload['unprioritised_count'], 1)

    def test_pool_is_returned_in_priority_order(self):
        pool = [_candidate(4), _candidate(2)]
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, pool, '')),                 mock.patch.object(wf, 'load_issue_facets',
                                  return_value=_facets(priority={4: 'Low',
                                                                2: 'Urgent'})):
            code, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual([c['number'] for c in payload['candidates']], [2, 4])
        self.assertEqual(payload['total'], 2)
        self.assertEqual(payload['unprioritised_count'], 0)

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

    def test_dependencies_come_from_the_native_edges(self):
        """The set chooser groups on real linkage, and it needs to know which
        of those dependencies are still open. The body says nothing here on
        purpose: prose naming a blocker is not a dependency."""
        cand = _candidate(1)
        cand['body'] = 'Part of the epic.\n\nBlocked by #7'
        edges = {1: [{'number': 7, 'state': 'OPEN'},
                     {'number': 8, 'state': 'CLOSED'}]}
        with mock.patch.object(wf, 'assemble_candidates',
                               return_value=(True, [cand], '')), \
                mock.patch.object(wf, 'issue_edges_map',
                                  return_value=(edges, set())):
            _, payload = _capture(wf.cmd_candidates, _candidates_args())
        entry = payload['candidates'][0]
        self.assertEqual(entry['dependencies'], [7, 8])
        self.assertEqual(entry['dependencies_open'], [7])
        self.assertTrue(entry['blocked'])

    def test_an_issue_with_no_edges_is_not_blocked_whatever_its_body_says(self):
        cand = _candidate(1)
        cand['body'] = '## Blocked by\n\n#979\n'
        with mock.patch.object(wf, 'assemble_candidates',
                               return_value=(True, [cand], '')), \
                mock.patch.object(wf, 'issue_edges_map', return_value=({}, set())):
            _, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(payload['candidates'][0]['dependencies'], [])
        self.assertFalse(payload['candidates'][0]['blocked'])

    def test_work_a_code_agent_cannot_do_is_not_listed(self):
        """`bulk-execute` reads this to decide what goes in one pull request,
        so an issue only a person or a browser agent can finish has no business
        in the answer — whatever lane the board happens to have it in.

        `Ownership` decides it, not the `[Browser]` title and not a label. Both
        are on this issue and neither is read.
        """
        browser = _candidate(1, labels=['browser-agent'])
        browser['title'] = '[Browser] Turn on the API'
        with mock.patch.object(wf, 'assemble_candidates',
                               return_value=(True, [browser, _candidate(2)], '')), \
                mock.patch.object(wf, 'load_issue_facets',
                                  return_value=_facets(ownership={
                                      1: 'Browser agent', 2: 'Code agent'})), \
                mock.patch.object(wf, 'issue_edges_map', return_value=({}, set())):
            _, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual([c['number'] for c in payload['candidates']], [2])

    def test_an_issue_nobody_owns_is_not_listed(self):
        """Opt-out has one exception and this is it. A backlog issue is
        available unless a field says otherwise -- but `Ownership` unset is not
        a field saying "code agent", it is a question nobody has answered, and
        the picker will not answer it on the org's behalf."""
        with mock.patch.object(wf, 'assemble_candidates',
                               return_value=(True, [_candidate(1)], '')), \
                mock.patch.object(wf, 'load_issue_facets',
                                  return_value=_facets(ownership={})), \
                mock.patch.object(wf, 'issue_edges_map', return_value=({}, set())):
            code, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(code, wf.EXIT_NO_CANDIDATES)

    def test_the_listing_says_who_owns_each_candidate(self):
        with mock.patch.object(wf, 'assemble_candidates',
                               return_value=(True, [_candidate(1)], '')), \
                mock.patch.object(wf, 'issue_edges_map', return_value=({}, set())):
            _, payload = _capture(wf.cmd_candidates, _candidates_args())
        self.assertEqual(payload['candidates'][0]['scope'], 'code')

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


class TestPostMergeClosesFinishedContainers(unittest.TestCase):
    """A merge closes the Epic or Feature its last story finished (#240)."""

    def _post_merge(self, chain, close_fails=False):
        cfg, calls = _cfg(), []

        def fake_run(argv, input_text=None):
            calls.append(argv)
            if close_fails and argv[:4] == ['gh', 'issue', 'close', '5']:
                return 1, '', 'HTTP 502'
            if argv[:3] == ['gh', 'pr', 'view']:
                return 0, json.dumps({
                    'number': 50, 'state': 'MERGED', 'mergedAt': '2026-09-10T00:00:00Z',
                    'baseRefName': 'main',
                    'closingIssuesReferences': [{'number': 5}]}), ''
            if argv[:3] == ['gh', 'issue', 'view']:
                return 0, json.dumps({'state': 'OPEN', 'labels': []}), ''
            return 0, '', ''

        args = wf.build_parser().parse_args(['post-merge', '--pr', '50', '--no-unblock'])
        with mock.patch.object(wf, 'check_environment', return_value=None), \
                mock.patch.object(wf, 'load_config', return_value=(True, cfg, '')), \
                mock.patch.object(wf, 'run', side_effect=fake_run), \
                mock.patch.object(wf, 'board_move', return_value=(True, 'moved')), \
                mock.patch.object(wf, 'fetch_parent_chain',
                                  return_value=(True, chain, '')):
            code, payload = _capture(args.func, args)
        closes = [c for c in calls if c[:3] == ['gh', 'issue', 'close']]
        return code, payload, closes

    @staticmethod
    def _node(number, kind, *children):
        cfg = _cfg()
        return {'number': number, 'type': kind, 'state': 'OPEN',
                'repo': '%s/%s' % (cfg['org'], cfg['repo']),
                'children': [{'number': n, 'state': s} for n, s in children]}

    def test_closing_the_last_story_closes_its_feature_then_its_epic(self):
        # The read still shows #5 open: GitHub may not have caught up with
        # the close this run just made, and the walk must not wait for it.
        chain = [self._node(10, 'Feature', (5, 'OPEN')),
                 self._node(1, 'Epic', (10, 'OPEN'), (20, 'CLOSED'))]
        code, payload, closes = self._post_merge(chain)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([(c['issue'], c['finished_by'], c['closed'])
                          for c in payload['containers_closed']],
                         [(10, 5, True), (1, 10, True)])
        for number, close in zip(('10', '1'), closes[-2:]):
            self.assertEqual(close[3], number)
            self.assertIn('completed', close)

    def test_a_parent_with_an_open_story_left_stays_open(self):
        chain = [self._node(10, 'Feature', (5, 'OPEN'), (6, 'OPEN'))]
        _, payload, closes = self._post_merge(chain)
        self.assertEqual(payload['containers_closed'], [])
        self.assertNotIn('10', [c[3] for c in closes])

    def test_a_story_whose_close_failed_finishes_nothing(self):
        """An attempted close is not a close: the Feature would otherwise be
        closed over a story that is still open."""
        chain = [self._node(10, 'Feature', (5, 'OPEN'))]
        _, payload, closes = self._post_merge(chain, close_fails=True)
        self.assertEqual(payload['containers_closed'], [])
        self.assertFalse(payload['settled'][0]['closed'])
        self.assertNotIn('10', [c[3] for c in closes])


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
            {'__typename': 'IssueFieldText', 'id': 'IFT_notes',
             'name': 'Notes'},
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
        self.assertEqual(fields['Notes']['data_type'], 'text')

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
        self.assertEqual(wf.field_name(cfg, 'field-target'), 'Target date')

    def test_absent_section_leaves_every_default_in_place(self):
        cfg = wf.parse_claude_project('# P\n\n## Identity\n\n| org | acme |\n')
        self.assertEqual(cfg['fields'], {})
        self.assertEqual(wf.field_name(cfg, 'field-type'), 'Classification')


class TestTypeCapableTableParsing(unittest.TestCase):
    """`type_capable` is read from the Capability table's own cell, not guessed
    from prose. `templates/ClaudeProject.md` documents the row as `| type-capable
    | `yes` |` and describes it in a sentence that never contains the literal
    phrase "is type-capable" -- a regex keyed on that phrase left every project
    following the template mis-detected as not type-capable, which silently
    emptied the feature/maintenance pool (`select_pool` -> `filter_by_native_type`
    treats a missing type_map as "no native types" and drops every candidate).
    """

    def test_yes_row_is_type_capable(self):
        cfg = wf.parse_claude_project(
            '# P\n\n## Issue Types & Fields\n\n### Capability\n\n'
            '| Setting | Value |\n| --- | --- |\n| type-capable | `yes` |\n\n'
            'The owner is an org with native GitHub issue types enabled.\n')
        self.assertTrue(cfg['type_capable'])

    def test_no_row_is_not_type_capable(self):
        cfg = wf.parse_claude_project(
            '# P\n\n## Issue Types & Fields\n\n### Capability\n\n'
            '| Setting | Value |\n| --- | --- |\n| type-capable | `no` |\n')
        self.assertFalse(cfg['type_capable'])

    def test_absent_section_defaults_to_not_type_capable(self):
        cfg = wf.parse_claude_project('# P\n\n## Identity\n\n| org | acme |\n')
        self.assertFalse(cfg['type_capable'])


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
        'Ownership': {'id': 'F_own', 'data_type': 'single-select',
                      'options': {'Code agent': 'o_code',
                                  'Browser agent': 'o_browser',
                                  'Human': 'o_human'}},
        # `Classification` and `Origin` are the optional pair: an org may
        # define them or not, and a spec may fill them or not. The three the
        # picker reads -- Priority, Effort, Ownership -- are above, and an org
        # missing one of those cannot have an issue filed against it at all.
        'Origin': {'id': 'F_org', 'data_type': 'single-select',
                   'options': {'Development': 'o_dev'}},
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
                 fail_create=(), fail_link=False, closed_edges=(),
                 board_lanes=None, type_map=None):
        # Blocker numbers this hub reports as CLOSED on the batched edge read.
        # Everything else reads OPEN, which is what a freshly written edge is.
        self.closed_edges = set(closed_edges)
        # The board this hub serves. Every lane the plugin can move a card to,
        # so a test that expects a column to exist finds it.
        self.board_columns = list(wf_core.BOARD_COLUMN_NAMES.values())
        # Which lane each issue's card is in before the run. An issue absent
        # here has no card at all, which is what a created issue looks like.
        self.board_lanes = dict(board_lanes or {})
        self.board_placed = {}
        self.board_writes = []
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
        # The caps a test runs with decide which type ids exist, so the hub
        # has to read a created issue's type back under the same map.
        self.type_names = {v: k for k, v
                           in (type_map or _APPLY_CAPS['type_map']).items()}
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
            'parent': ({'number': issue['parent'],
                        'issueType': ({'name': issue['parent_type']}
                                      if issue.get('parent_type') else None)}
                       if issue['parent'] else None),
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
                repository[alias] = self._readback(issue) if issue else None
            return True, {'repository': repository}, ''
        if re.search(r'n\d+: issue\(number:\d+\)\{ id number \}', query):
            # `resolve_issue_ids` — the ids of blockers an entry dropped, which
            # were never in the spec's own prerequisite lookup.
            repository = {}
            for alias, number in re.findall(r'(n\d+): issue\(number:(\d+)\)',
                                            query):
                issue = self.issues.get(int(number))
                repository[alias] = ({'id': issue['id'],
                                      'number': issue['number']}
                                     if issue else None)
            return True, {'repository': repository}, ''
        if re.search(r'blockedBy\(first:\d+\)', query) and ': issue(number:' in query:
            repository = {}
            for alias, number in re.findall(
                    r'(e\d+): issue\(number:(\d+)\)', query):
                issue = self.issues.get(int(number))
                repository[alias] = {'blockedBy': {'nodes': [
                    {'number': n, 'title': 'blocker %d' % n,
                     'state': 'CLOSED' if n in self.closed_edges else 'OPEN'}
                    for n in issue['blocked_by']]}} if issue else None
            return True, {'repository': repository}, ''
        if re.search(r'c\d+: issue\(number:\d+\)', query):
            # `board_current_columns` — the lane each card is in before the run.
            repository = {}
            for alias, number in re.findall(r'(c\d+): issue\(number:(\d+)\)',
                                            query):
                lane = self.board_lanes.get(int(number))
                repository[alias] = {'projectItems': {'nodes': (
                    [{'project': {'id': _cfg()['board']['project_node_id']},
                      'fieldValueByName': {'name': lane} if lane else None}]
                    if int(number) in self.board_lanes else [])}}
            return True, {'repository': repository}, ''
        if 'projectItems' in query:
            repository = {}
            for alias, number in re.findall(
                    r'(b\d+): issue\(number:(\d+)\)', query):
                issue = self.issues.get(int(number))
                if not issue:
                    repository[alias] = None
                    continue
                self.board_placed.setdefault(issue['number'], None)
                repository[alias] = {'id': issue['id'],
                                     'projectItems': {'nodes': []}}
            return True, {'repository': repository}, ''
        if 'issue(number:$number)' in query:
            issue = self.issues.get(int(fields['number']))
            return True, {'repository': {'issue': self._readback(issue)
                                         if issue else None}}, ''
        # The board. `issue-apply` places every issue it touches, so these are
        # part of the command's real traffic rather than incidental.
        if 'ProjectV2SingleSelectField' in query:
            return True, {'node': {'title': None, 'field': {
                'id': 'F_status',
                'options': [{'id': 'o_%s' % n.lower().replace(' ', '_'),
                             'name': n}
                            for n in self.board_columns]}}}, ''
        if 'addProjectV2ItemById' in query:
            return True, {alias: {'item': {'id': 'ITEM_%s' % alias}}
                          for alias in re.findall(r'(a\d+):', query)}, ''
        if 'updateProjectV2ItemFieldValue' in query:
            for alias in re.findall(r'm(\d+):', query):
                self.board_writes.append(fields['o%s' % alias])
            return True, {'m%s' % alias: {'projectV2Item': {'id': 'ITEM_x'}}
                          for alias in re.findall(r'm(\d+):', query)}, ''
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

        aliased = re.findall(r'(b\d+): (addBlockedBy|removeBlockedBy|updateIssue)',
                             query)
        if aliased:
            for alias, kind in aliased:
                if self.fail_link:
                    data[alias] = None
                    errors.append({'path': [alias], 'message': 'nope'})
                    continue
                issue = self._by_id(variables['%s_i' % alias])
                if kind in ('addBlockedBy', 'removeBlockedBy'):
                    blocker = self._by_id(variables['%s_b' % alias])
                    self.sent.append((kind, blocker['number']))
                    if kind == 'addBlockedBy':
                        issue['blocked_by'].append(blocker['number'])
                    else:
                        issue['blocked_by'] = [n for n in issue['blocked_by']
                                               if n != blocker['number']]
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
    # Titled as `_ApplyCase._full` titles its entry, so an update that says
    # nothing new about the title writes none (#242).
    issue = {'id': 'I_%d' % number, 'number': number, 'title': 'A story',
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

    def _run(self, entries, hub, extra_argv=(), calls=None, caps=None):
        path = self._spec_file(entries)
        args = wf.build_parser().parse_args(['issue-apply', path, *extra_argv])
        stderr = io.StringIO()

        def fake_run(cmd, input_text=None):
            if calls is not None:
                calls.append(list(cmd))
            return 0, '', ''

        with mock.patch.object(wf, 'load_config', lambda: (True, _cfg(), '')), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg, refresh=False, root=None:
                                  (True, caps or _APPLY_CAPS, '')), \
                mock.patch.object(wf, 'gh_graphql', hub.gh_graphql), \
                mock.patch.object(wf, '_graphql_json', hub.graphql_json), \
                mock.patch.object(wf, 'run', fake_run), \
                contextlib.redirect_stderr(stderr):
            code, payload = _capture(wf.cmd_issue_apply, args)
        with open(path, encoding='utf-8') as fh:
            written = json.load(fh)
        return code, payload, stderr.getvalue(), written

    def _full(self, **over):
        entry = {'key': 'a', 'title': 'A story', 'kind': 'story',
                 'fields': {'field-priority': 'High', 'field-effort': 'Medium',
                            'field-ownership': 'Code agent'}}
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
        self.assertEqual(len(sent['issueFields']), 4)
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
                                          'Ownership': 'Code agent',
                                          'Classification': ['New Feature']})])
        code, payload, _, _ = self._run([self._full(number=42)], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(hub.mutations, [])
        self.assertEqual(payload['applied'][0]['changed'], [])

    def test_an_update_sets_only_what_differs(self):
        hub = _FakeHub([_existing(42, type='User Story',
                                  fields={'Priority': 'Medium', 'Effort': 'Medium',
                                          'Ownership': 'Code agent',
                                          'Classification': ['New Feature']})])
        _, payload, _, _ = self._run([self._full(number=42)], hub)
        self.assertEqual(hub.names_sent(), ['setIssueFieldValue'])
        self.assertEqual(len(hub.sent[0][1]['f']), 1)
        self.assertEqual(payload['applied'][0]['changed'], ['fields'])

    _CORRECT = {'type': 'User Story',
                'fields': {'Priority': 'High', 'Effort': 'Medium',
                           'Ownership': 'Code agent',
                           'Classification': ['New Feature']}}

    def test_an_update_writes_a_changed_title_and_body(self):
        """#242: an update used to exit 0 and leave both as they were."""
        hub = _FakeHub([_existing(42, **self._CORRECT)])
        body = os.path.join(self.dir, 'body.md')
        with open(body, 'w', encoding='utf-8') as fh:
            fh.write('A new body\n')
        calls = []
        _, payload, _, _ = self._run(
            [self._full(number=42, title='A new title', body_file=body)], hub,
            calls=calls)
        edits = [c for c in calls if c[:3] == ['gh', 'issue', 'edit']]
        self.assertEqual(len(edits), 1)
        self.assertIn('A new title', edits[0])
        self.assertIn('--body-file', edits[0])
        applied = payload['applied'][0]
        self.assertEqual(applied['changed'], ['title', 'body'])
        # The fake hub never applies a `gh issue edit`, so the read-back still
        # holds the old title and body: the mismatch the command must report.
        self.assertTrue(any('title' in m for m in applied['mismatches']))
        self.assertTrue(any('body' in m for m in applied['mismatches']))

    def test_an_update_whose_title_and_body_match_writes_nothing(self):
        hub = _FakeHub([_existing(42, title='A story', body='The body',
                                  **self._CORRECT)])
        calls = []
        _, payload, _, _ = self._run(
            [self._full(number=42, body='The body\r\n')], hub, calls=calls)
        self.assertFalse(any(c[:3] == ['gh', 'issue', 'edit'] for c in calls))
        self.assertEqual(payload['applied'][0]['changed'], [])

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
        """Once per issue would bury the errors that actually matter.

        `Origin` is the field to skip here because it is optional: an org that
        has never created it still files issues, so the spec asking for it is
        a note rather than a failure. Asking for a field the picker reads is
        the other case entirely, and `validate_spec` refuses the whole run.
        """
        hub = _FakeHub()
        caps = dict(_APPLY_CAPS, field_map={
            n: m for n, m in _APPLY_CAPS['field_map'].items() if n != 'Origin'})
        fields = {'field-priority': 'High', 'field-effort': 'Medium',
                  'field-ownership': 'Code agent', 'field-origin': 'Development'}
        entries = [self._full(key='a', fields=fields),
                   self._full(key='b', fields=fields)]
        code, payload, stderr, _ = self._run(entries, hub, caps=caps)
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

    def test_a_dependency_is_written_as_an_edge_and_only_as_an_edge(self):
        """It used to be written twice, as the edge and as `## Dependencies`
        prose, and on one real backlog the two disagreed on nine of the fourteen
        issues carrying both."""
        hub = _FakeHub([_existing(7)])
        code, payload, _, _ = self._run([self._full(blocked_by=[7])], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn('addBlockedBy', hub.names_sent())
        created = hub.issues[payload['applied'][0]['number']]
        self.assertEqual(created['blocked_by'], [7])
        self.assertNotIn('Dependencies', created['body'])

    def test_an_issue_created_with_an_open_dependency_is_placed_in_blocked(self):
        """Nothing did this before: a spec could write the edge and leave the
        issue sitting in the pool, so `pick` offered work whose dependency had
        not been built yet."""
        hub = _FakeHub([_existing(7)])
        code, payload, _, _ = self._run([self._full(blocked_by=[7])], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['applied'][0]['board_column'], 'Blocked')

    def test_browser_work_goes_to_the_non_code_lane_not_the_blocked_one(self):
        """The lane a sweep never releases from. Blocked means a dependency is
        open, and no dependency closing will make a code agent able to click
        through a console.

        `Ownership` decides it. The `[Browser]` title prefix is a fallback for
        an issue the org has not answered for, and it is not what is read here.
        """
        hub = _FakeHub()
        entry = self._full(title='[Browser] Turn on the API',
                           fields={'field-priority': 'High',
                                   'field-effort': 'Medium',
                                   'field-ownership': 'Browser agent'})
        code, payload, _, _ = self._run([entry], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['applied'][0]['board_column'], 'Non-code')

    def test_ownership_wins_over_a_dependency(self):
        """Both are true at once and only one can name a lane. The owner is a
        property of the work, and no dependency closing changes it."""
        hub = _FakeHub([_existing(7)])
        entry = self._full(title='[Manual] Device pass', blocked_by=[7],
                           fields={'field-priority': 'High',
                                   'field-effort': 'Medium',
                                   'field-ownership': 'Human'})
        code, payload, _, _ = self._run([entry], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['applied'][0]['board_column'], 'Non-code')

    def test_a_pickable_issue_is_still_placed_in_backlog(self):
        """The gap the Backlog pool cannot survive. This phase used to return
        early for pickable work, so a created code issue got no board item at
        all — and an issue with no card is an issue the picker cannot see."""
        hub = _FakeHub()
        code, payload, _, _ = self._run([self._full()], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['applied'][0]['board_column'], 'Backlog')

    def test_an_update_whose_blockers_closed_returns_to_the_pool(self):
        """The other half of the early return: an issue whose last dependency
        closed resolved to pickable, so its card stayed in Blocked until a
        separate sweep happened to scan it."""
        hub = _FakeHub([_existing(7, blocked_by=[6]), _existing(6)],
                       closed_edges={6})
        code, payload, _, _ = self._run([self._full(number=7)], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['applied'][0]['board_column'], 'Backlog')

    def test_an_update_leaves_an_in_flight_card_where_it_is(self):
        """Reproduced live: a spec setting one field on an issue in progress
        moved its card back to Backlog, where a second agent could pick up
        work already underway. A lane this phase does not own is kept."""
        hub = _FakeHub([_existing(7, type='User Story')],
                       board_lanes={7: 'In Progress'})
        code, payload, _, _ = self._run([self._full(number=7)], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['applied'][0]['board_column_kept'], 'In Progress')
        self.assertEqual(hub.board_writes, [])

    def test_a_parked_card_is_not_silently_unparked(self):
        hub = _FakeHub([_existing(7, type='User Story')],
                       board_lanes={7: 'Parked'})
        _, payload, _, _ = self._run([self._full(number=7)], hub)
        self.assertEqual(payload['applied'][0]['board_column_kept'], 'Parked')

    def test_an_explicit_state_moves_even_an_in_flight_card(self):
        """Asking for a lane is a decision, not an inference, so it wins."""
        hub = _FakeHub([_existing(7, type='User Story')],
                       board_lanes={7: 'In Progress'})
        code, payload, _, _ = self._run([self._full(number=7, state='parked')],
                                        hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['applied'][0]['board_column'], 'Parked')
        self.assertNotIn('board_column_kept', payload['applied'][0])

    def test_a_thin_issue_can_be_filed_straight_into_needs_refinement(self):
        hub = _FakeHub()
        code, payload, _, _ = self._run([self._full(state='refinement')], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['applied'][0]['board_column'], 'Needs refinement')

    def test_a_state_the_spec_does_not_know_is_refused(self):
        hub = _FakeHub()
        code, payload, _, _ = self._run([self._full(state='ready')], hub)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertEqual(hub.mutations, [])

    def test_a_backlog_card_is_still_re_placed_by_its_state(self):
        """Backlog is a lane this phase owns, so an edge written on an issue
        sitting there moves it to Blocked."""
        hub = _FakeHub([_existing(7, type='User Story'), _existing(6)],
                       board_lanes={7: 'Backlog'})
        _, payload, _, _ = self._run([self._full(number=7, blocked_by=[6])], hub)
        self.assertEqual(payload['applied'][0]['board_column'], 'Blocked')

    def test_restating_blocked_by_removes_an_edge_the_entry_left_out(self):
        """`blocked_by` is the whole set. An edge added by mistake had no way
        back off: `wf unblock` only releases an issue when its blockers close."""
        hub = _FakeHub([_existing(7, type='User Story', blocked_by=[5, 6]),
                        _existing(5), _existing(6)])
        code, payload, _, _ = self._run([self._full(number=7, blocked_by=[5])],
                                        hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(hub.issues[7]['blocked_by'], [5])
        self.assertIn(('removeBlockedBy', 6), hub.sent)
        self.assertIn('removed blocked-by #6', payload['applied'][0]['changed'])

    def test_an_empty_blocked_by_releases_every_edge(self):
        hub = _FakeHub([_existing(7, type='User Story', blocked_by=[6]),
                        _existing(6)], board_lanes={7: 'Blocked'})
        code, payload, _, _ = self._run([self._full(number=7, blocked_by=[])],
                                        hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(hub.issues[7]['blocked_by'], [])
        self.assertEqual(payload['applied'][0]['board_column'], 'Backlog')

    def test_an_entry_without_blocked_by_leaves_the_edges_alone(self):
        hub = _FakeHub([_existing(7, type='User Story', blocked_by=[6]),
                        _existing(6)])
        code, _, _, _ = self._run([self._full(number=7)], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(hub.issues[7]['blocked_by'], [6])
        self.assertNotIn('removeBlockedBy', hub.names_sent())

    def test_one_issue_one_party(self):
        """A `[Manual]` title owned by `Code agent` is refused before any
        write: whichever of the two is wrong, the issue would mislead."""
        hub = _FakeHub()
        code, payload, _, _ = self._run([self._full(title='[Manual] Device pass')],
                                        hub)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertIn('one issue, one party', ' '.join(payload['errors']))
        self.assertEqual(hub.mutations, [])

    def test_a_retired_label_is_taken_off_whatever_the_spec_said(self):
        """How an existing backlog migrates: an issue still carrying a label
        from the label workflow is cleaned the next time a command touches it.

        The labels are read from the issue, not the spec, because an update
        entry does not restate them — which is why the one path that had to
        find a stale label never found one.
        """
        hub = _FakeHub([_existing(7, labels=['status-blocked', 'priority-high'],
                                  blocked_by=[6]),
                        _existing(6)], closed_edges={6})
        calls = []
        _, payload, _, _ = self._run([self._full(number=7)], hub, calls=calls)
        self.assertIn('cleared retired label(s) status-blocked, priority-high',
                      payload['applied'][0]['changed'])
        joined = [' '.join(c) for c in calls]
        self.assertTrue(any('issue edit 7' in c and '--remove-label' in c
                            and 'status-blocked' in c and '--add-label' not in c
                            for c in joined), joined)

    def test_a_created_issue_is_told_what_was_left_unset(self):
        """`Classification` and `Origin` are not worth refusing an issue over
        and are worth saying out loud. A stderr line reaches whoever ran the
        command; a comment reaches whoever opens the issue, who is the person
        who can fill the field in."""
        hub = _FakeHub()
        calls = []
        _, payload, _, _ = self._run(
            [self._full(kind=None, fields={'field-priority': 'High',
                                           'field-effort': 'Medium',
                                           'field-ownership': 'Code agent'})],
            hub, calls=calls)
        self.assertIn('commented on unset optional field(s)',
                      payload['applied'][0]['changed'])
        body = [c for c in calls if 'comment' in c][0][-1]
        self.assertIn('Classification', body)
        self.assertIn('Origin', body)

    def test_an_update_is_not_commented_on_for_a_field_it_never_mentioned(self):
        """An update about something else is not a report on the fields it did
        not restate, and commenting on every one would make the issue unusable
        within a week."""
        hub = _FakeHub([_existing(7)])
        calls = []
        self._run([self._full(number=7)], hub, calls=calls)
        self.assertEqual([c for c in calls if 'comment' in c], [])

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

    def test_a_create_naming_no_labels_is_not_warned_about(self):
        """Labels decide nothing. Priority is a field the spec must carry, so
        an issue with no labels is exactly as orderable as one with ten, and a
        warning saying otherwise sent people to add labels nothing reads."""
        hub = _FakeHub()
        code, _, stderr, _ = self._run([self._full()], hub)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertNotIn('label', stderr)


_FEATURE_CAPS = dict(_APPLY_CAPS,
                     type_map=dict(_APPLY_CAPS['type_map'], Feature='IT_feature'))


class TestIssueHierarchy(_ApplyCase):
    """Epic → Feature → User Story, enforced at the write.

    Only against an org that has the parent type enabled: `_APPLY_CAPS` has no
    `Feature`, which is why every other apply test can file a parentless story.
    """

    def _story(self, **over):
        return self._full(**over)

    def test_a_story_with_no_feature_parent_is_refused(self):
        hub = _FakeHub()
        code, payload, _, _ = self._run([self._story()], hub, caps=_FEATURE_CAPS)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertIn("'Feature' parent", ' '.join(payload['errors']))
        self.assertEqual(hub.mutations, [])

    def test_a_story_under_an_epic_is_refused(self):
        hub = _FakeHub([_existing(50, type='Epic')])
        code, payload, _, _ = self._run([self._story(parent=50)], hub,
                                        caps=_FEATURE_CAPS)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertIn("#50 is a 'Epic'", ' '.join(payload['errors']))

    def test_a_story_under_an_existing_feature_is_accepted(self):
        hub = _FakeHub([_existing(50, type='Feature')])
        code, payload, _, _ = self._run([self._story(parent=50)], hub,
                                        caps=_FEATURE_CAPS)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(hub.issues[payload['applied'][0]['number']]['parent'], 50)

    def test_a_whole_tree_in_one_spec_is_accepted(self):
        fields = self._full()['fields']
        entries = [
            {'key': 'e', 'title': 'Epic', 'kind': 'epic', 'fields': dict(fields)},
            {'key': 'f', 'title': 'Feature', 'kind': 'feature', 'parent': 'e',
             'fields': dict(fields)},
            {'key': 's', 'title': 'Story', 'kind': 'story', 'parent': 'f',
             'fields': dict(fields)},
        ]
        hub = _FakeHub(type_map=_FEATURE_CAPS['type_map'])
        code, payload, _, _ = self._run(entries, hub, caps=_FEATURE_CAPS)
        self.assertEqual(code, wf.EXIT_OK, payload)
        by_key = {r['key']: r['number'] for r in payload['applied']}
        self.assertEqual(hub.issues[by_key['f']]['type'], 'Feature')
        self.assertEqual(hub.issues[by_key['s']]['parent'], by_key['f'])

    def test_a_feature_may_stand_without_an_epic(self):
        hub = _FakeHub(type_map=_FEATURE_CAPS['type_map'])
        entry = self._full(kind='feature', title='A feature')
        code, payload, _, _ = self._run([entry], hub, caps=_FEATURE_CAPS)
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(hub.issues[payload['applied'][0]['number']]['type'],
                         'Feature')

    def test_an_update_moving_a_story_onto_an_epic_is_refused(self):
        """Found live: the entry named no `kind`, so the check never ran and
        a User Story was re-parented straight onto an Epic."""
        hub = _FakeHub([_existing(40, type='Epic'),
                        _existing(50, type='Feature'),
                        _existing(7, type='User Story', parent=50,
                                  parent_type='Feature')])
        code, payload, _, _ = self._run([{'number': 7, 'parent': 40}], hub,
                                        caps=_FEATURE_CAPS)
        self.assertEqual(code, wf.EXIT_SPEC, payload)
        self.assertIn("#40 is a 'Epic'", ' '.join(payload['errors']))
        self.assertEqual(hub.mutations, [])

    def test_an_update_need_not_restate_the_fields_the_issue_carries(self):
        hub = _FakeHub([_existing(7, fields={'Priority': 'High',
                                             'Effort': 'Medium',
                                             'Ownership': 'Code agent'})])
        code, payload, _, _ = self._run(
            [{'number': 7, 'fields': {'field-priority': 'Medium'}}], hub)
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(hub.issues[7]['fields']['Priority'], 'Medium')

    def test_an_update_leaving_the_issue_without_a_required_value_is_refused(self):
        hub = _FakeHub([_existing(7, fields={'Priority': 'High'})])
        code, payload, _, _ = self._run(
            [{'number': 7, 'fields': {'field-priority': 'Medium'}}], hub)
        self.assertEqual(code, wf.EXIT_SPEC)
        joined = ' '.join(payload['errors'])
        self.assertIn('Effort', joined)
        self.assertIn('Ownership', joined)
        self.assertEqual(hub.mutations, [])

    def test_an_update_handing_an_unprefixed_issue_to_a_person_is_refused(self):
        hub = _FakeHub([_existing(7, fields={'Priority': 'High',
                                             'Effort': 'Medium',
                                             'Ownership': 'Code agent'})])
        code, payload, _, _ = self._run(
            [{'number': 7, 'fields': {'field-ownership': 'Human'}}], hub)
        self.assertEqual(code, wf.EXIT_SPEC)
        self.assertIn('[Manual]', ' '.join(payload['errors']))
        self.assertEqual(hub.mutations, [])

    def test_an_update_that_keeps_its_feature_parent_is_accepted(self):
        """An update need not restate a parent it already has."""
        hub = _FakeHub([_existing(50, type='Feature'),
                        _existing(7, type='User Story', parent=50,
                                  parent_type='Feature')])
        code, _, _, _ = self._run([self._story(number=7)], hub,
                                  caps=_FEATURE_CAPS)
        self.assertEqual(code, wf.EXIT_OK)

    def test_an_update_to_an_orphan_story_is_refused(self):
        hub = _FakeHub([_existing(7, type='User Story')])
        code, _, _, _ = self._run([self._story(number=7)], hub,
                                  caps=_FEATURE_CAPS)
        self.assertEqual(code, wf.EXIT_SPEC)

    def test_an_org_without_the_parent_type_is_not_held_to_it(self):
        """Refusing every create until somebody enables a type in the org
        settings would be a workflow this plugin broke."""
        hub = _FakeHub()
        code, _, _, _ = self._run([self._story()], hub)
        self.assertEqual(code, wf.EXIT_OK)


class TestEpicTreeBatching(_ApplyCase):
    """A whole tree in one invocation, batched by hierarchy level."""

    def _tree(self):
        """One epic, three features, nine stories — the shape from the story."""
        fields = {'field-priority': 'High', 'field-effort': 'Medium',
                  'field-ownership': 'Code agent'}
        entries = [{'key': 'epic', 'title': 'Epic', 'kind': 'epic',
                    'fields': dict(fields)}]
        for f in range(3):
            entries.append({'key': 'f%d' % f, 'title': 'Feature %d' % f,
                            'kind': 'story', 'parent': 'epic',
                            'fields': dict(fields)})
            for st in range(3):
                entries.append({'key': 's%d_%d' % (f, st),
                                'title': 'Story %d.%d' % (f, st), 'kind': 'story',
                                'parent': 'f%d' % f, 'fields': dict(fields)})
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
        # Seven requests for thirteen issues, and the number does not move when
        # the tree grows. Three reads -- the prerequisite lookup (repo id and
        # label ids together), one batched edge read, so the lifecycle phase
        # knows which of the edges it just wrote point at something still open,
        # and one batched read of the lane each card is in now, so an update
        # never drags an in-flight card back to Backlog -- then the four the
        # board costs: its Status field, the cards that already exist, the
        # cards that have to be added, the column write.
        self.assertEqual(len(hub.queries), 7)

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
             'options': [{'name': 'New Feature'}]},
            {'field': {'name': 'Origin'}, 'name': 'Development'},
            {'field': {'name': 'Ownership'}, 'name': 'Code agent'}]}, **over)

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

    def test_a_body_dependency_is_no_longer_an_edge_the_audit_can_propose(self):
        """There is nothing to propose from: only an edge records a dependency."""
        issue = self._issue(1, body='## Dependencies\n\nBlocked by #2\n')
        _, payload, _, spec = self._run([issue, self._classified(2)])
        self.assertNotIn('blocked_by', spec['issues'][0])
        kinds = [g['kind'] for g in payload['issues'][0]['gaps']]
        self.assertNotIn('missing-edge', kinds)

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

    def test_handoff_labels_the_pr_moves_the_card_and_frees_the_claim(self):
        calls = []
        code, payload = self._run(['handoff', '--pr', '7', '--issue', '3'], calls)
        self.assertEqual(code, wf.EXIT_OK)
        joined = [' '.join(c) for c in calls]
        self.assertTrue(any('pr edit 7' in c and 'claude-authored' in c
                            and 'review-needs-review' in c for c in joined))
        # No `issue edit` at all: the column is the state, so the move is
        # the whole hand-off and there is no label to swap.
        self.assertFalse(any('issue edit' in c for c in joined))
        self.assertTrue(any('refs/claims/issue-3' in c for c in joined))
        self.assertEqual(payload['issues'][0]['board_moved'], True)

    def test_handoff_takes_the_pr_claim_before_freeing_the_issue_claim(self):
        """#164: the PR is locked from the moment it is handed to review, so a
        scheduled review cannot claim it in the gap before Phase 8."""
        calls = []
        _, payload = self._run(['handoff', '--pr', '7', '--issue', '3'], calls)
        pushes = [' '.join(c) for c in calls if c[:2] == ['git', 'push']]
        claim = next(i for i, c in enumerate(pushes) if 'refs/claims/pr-7' in c)
        release = next(i for i, c in enumerate(pushes) if 'refs/claims/issue-3' in c)
        self.assertLess(claim, release)
        self.assertEqual(payload['pr_claimed'], 'won')

    def test_claim_keeps_a_pr_claim_this_checkout_already_holds(self):
        """After handoff took it, Phase 8's `wf claim --pr` must not read its
        own lock as a rival's."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, '.claude'))
        with open(os.path.join(root, '.claude', 'claim-pr-7.sha'), 'w') as fh:
            fh.write('abc123')

        def fake_run(cmd, input_text=None):
            if cmd[:2] == ['git', 'ls-remote']:
                return 0, 'abc123\trefs/claims/pr-7\n', ''
            if cmd[:2] == ['git', 'push']:
                return 1, '', 'rejected'  # a fresh object would lose
            return 0, '', ''

        args = wf.build_parser().parse_args(['claim', '--pr', '7', '--no-marker'])
        with mock.patch.object(wf, 'check_environment', lambda: None), \
                mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'repo_root', lambda: root), \
                contextlib.redirect_stderr(io.StringIO()):
            code, payload = _capture(args.func, args)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertTrue(payload['claimed'])

    def test_claim_still_loses_to_a_rival_holding_a_different_object(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, '.claude'))
        with open(os.path.join(root, '.claude', 'claim-pr-7.sha'), 'w') as fh:
            fh.write('abc123')

        def fake_run(cmd, input_text=None):
            if cmd[:2] == ['git', 'ls-remote']:
                return 0, 'fff999\trefs/claims/pr-7\n', ''
            if cmd[:2] == ['git', 'push']:
                return 1, '', 'rejected'
            return 0, '', ''

        args = wf.build_parser().parse_args(['claim', '--pr', '7', '--no-marker'])
        with mock.patch.object(wf, 'check_environment', lambda: None), \
                mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'repo_root', lambda: root), \
                contextlib.redirect_stderr(io.StringIO()):
            code, payload = _capture(args.func, args)
        self.assertEqual(code, wf.EXIT_LOST)

    def test_a_failed_gate_enters_review_as_changes_requested(self):
        """The PR is real work but not ready to approve; say so in the label."""
        calls = []
        _, payload = self._run(
            ['handoff', '--pr', '7', '--issue', '3', '--gate-failed'], calls)
        self.assertEqual(payload['review_label'], 'review-changes-requested')

    def test_handoff_reports_an_unmoved_board_without_failing(self):
        """A failed move leaves the card where it was; the PR still exists and
        the claim is still freed, so the run reports it rather than dying."""
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
        states = {'issue-3': ('issue', 3, 'CLOSED', [], False, True),
                  'issue-4': ('issue', 4, 'OPEN', [], False, True)}
        code, payload, released = self._reap(refs, states)
        self.assertEqual(released, ['issue-3'])
        self.assertEqual(payload['summary'], {'reaped': 1, 'suspect': 1, 'skipped': 0})
        self.assertEqual(payload['suspect'][0]['ref'], 'refs/claims/issue-4')

    def test_dry_run_reports_the_verdicts_without_deleting_anything(self):
        refs = [('aaa', 'issue-3')]
        states = {'issue-3': ('issue', 3, 'CLOSED', [], False, True)}
        _, payload, released = self._reap(refs, states, ['--dry-run'])
        self.assertEqual(released, [])
        self.assertEqual(payload['summary']['reaped'], 1)

    def test_a_ref_that_names_neither_an_issue_nor_a_pr_is_never_deleted(self):
        refs = [('aaa', 'sprint-lock')]
        states = {'sprint-lock': (None, None, None, [], False, False)}
        _, payload, released = self._reap(refs, states)
        self.assertEqual(released, [])
        self.assertEqual(payload['summary']['suspect'], 1)


class TestConfigAudit(unittest.TestCase):
    """Preflight's drift checks: what fails, what warns, and what it costs."""

    _SECTIONS = list(wf_core.REQUIRED_CONFIG_SECTIONS)
    _PINNED = ['Priority', 'Effort', 'Classification', 'Origin', 'Ownership']
    _LABELS = ['status-blocked', 'status-in-progress', 'type-bug']
    # A board carrying every lane the workflow writes to. Since 9.0.0 the pool
    # *is* the Backlog column, so a project with no board, or a board missing
    # that column, is a critical finding rather than a clean run — which makes
    # a live board part of the baseline every other check is measured against.
    _LIVE_BOARD = {'title': None, 'field': {'options': [
        {'id': 'opt%d' % i, 'name': name}
        for i, name in enumerate(sorted(wf_core.BOARD_COLUMN_NAMES.values()))]}}

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

    @staticmethod
    def _snapshot(board):
        """The `### Status Options` a project would record for this board."""
        live = {(o.get('name') or '').strip().lower(): o['id']
                for o in ((board or {}).get('field') or {}).get('options') or ()}
        return {purpose: live[name.strip().lower()]
                for purpose, name in wf_core.BOARD_COLUMN_NAMES.items()
                if name.strip().lower() in live}

    def _write_instruction(self, name, text):
        with open(os.path.join(self.scan, name), 'w', encoding='utf-8') as fh:
            fh.write(text)

    def _run(self, sections=None, labels=None, types=None, board=_UNSET,
             cfg_over=None, argv=(), caps=None, pins_ok=True, orphans=()):
        if board is _UNSET:
            board = copy.deepcopy(self._LIVE_BOARD)
        self._write_config(self._SECTIONS if sections is None else sections)
        cfg = _cfg(**(cfg_over or {}))
        if not (cfg_over or {}).get('board'):
            # Record exactly what the live board has. A recorded id the board
            # dropped and a live column the file never recorded are both
            # `board-column` warnings, so a baseline that records nothing --
            # or records a lane the test just deleted -- would put nine of them
            # under every other assertion.
            cfg['board']['columns'] = self._snapshot(board)
        args = wf.build_parser().parse_args(
            ['config-audit', '--scan', self.scan, *argv])
        sent = []

        def gh_graphql(query, **fields):
            if 'projectItems' in query:
                sent.append('orphans')
                return True, {'repository': {'issues': {
                    'pageInfo': {'hasNextPage': False, 'endCursor': None},
                    'nodes': [{'number': n, 'title': 'issue %d' % n,
                               'assignees': {'totalCount': 0},
                               'projectItems': {'nodes': []}}
                              for n in orphans]}}}, ''
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
        self.assertIn('Ownership', payload['findings'][0]['detail'])

    def test_a_mandatory_field_the_org_never_created_is_reported_once(self):
        """A field nobody has created cannot be pinned to anything, so the
        answer is one `field-absent` naming the field rather than one
        `field-unpinned` per issue type saying nothing about the org.

        This used to be a clean run. It is critical since 10.0.0, because the
        picker reads the five mandatory fields and nothing else: an org missing
        one cannot rank, size, classify or route an issue, and staying silent
        about it is how this repository ran for weeks with no `Ownership`.
        """
        caps = dict(_APPLY_CAPS, field_map={
            n: m for n, m in _APPLY_CAPS['field_map'].items() if n != 'Ownership'})
        code, payload, _ = self._run(caps=caps, types=[
            {'name': 'User Story', 'enabled': True,
             'pinned': ['Priority', 'Effort', 'Classification', 'Origin']}])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['field-absent'])
        self.assertIn('Ownership', payload['findings'][0]['detail'])

    # ── the warnings ─────────────────────────────────────────────────────────

    def test_pin_asymmetry_warns_without_failing_the_run(self):
        """A field one type carries and another does not. Soft, not an error."""
        code, payload, _ = self._run(types=[
            {'name': 'User Story', 'enabled': True,
             'pinned': self._PINNED + ['Team']},
            {'name': 'Epic', 'enabled': True, 'pinned': self._PINNED}])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._checks(payload), ['pin-asymmetry'])

    def test_a_status_label_the_map_still_claims_is_deprecated(self):
        """`label-unmapped` used to fail the run here, because a purpose key
        the repo carried under another name left `pick` filtering on a default
        that matched nothing.

        No label reaches a filter since 10.0.0, so a map row for a retired
        label costs nothing but confusion: it is a warning naming the row, and
        the run passes. The repo carries the label too, so this is the map
        being stale rather than the label being missing.
        """
        code, payload, _ = self._run(
            labels=self._LABELS + ['status-non-code'],
            cfg_over={'labels': {'status-non-code': 'status-non-code'}})
        self.assertEqual(self._checks(payload), ['label-deprecated'])
        self.assertIn('status-non-code', payload['findings'][0]['detail'])
        self.assertEqual(code, wf.EXIT_OK)

    def test_a_deprecation_never_asks_anyone_to_delete_a_live_label(self):
        """Deleting a label removes it from every issue that carries it, which
        is history nobody asked to lose. The fix text says to drop the map
        row."""
        _, payload, _ = self._run(
            labels=self._LABELS + ['status-non-code'],
            cfg_over={'labels': {'status-non-code': 'status-non-code'}})
        fix = payload['findings'][0]['fix'].lower()
        self.assertIn('label map', fix)
        self.assertIn('the labels themselves can stay', fix)

    def test_label_drift_warns_without_failing_the_run(self):
        code, payload, _ = self._run(
            labels=self._LABELS + ['type:bug', 'type-feature', 'type:feature'])
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
        board = copy.deepcopy(self._LIVE_BOARD)
        board['title'] = 'widgets'
        board['field']['options'].append({'id': 'live1234', 'name': 'In Progress'})
        columns = dict(self._snapshot(board), **{'col-in-progress': 'dead1234'})
        code, payload, _ = self._run(
            board=board,
            cfg_over={'board': {'project_node_id': 'PVT_1',
                                'project_title': 'widgets',
                                'status_field_name': 'Status',
                                'columns': columns}})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._checks(payload), ['board-column'])

    def test_a_board_without_the_pool_column_fails_the_run(self):
        """The pool is a board column, so this is not a display problem."""
        board = copy.deepcopy(self._LIVE_BOARD)
        board['field']['options'] = [
            o for o in board['field']['options'] if o['name'] != 'Backlog']
        code, payload, _ = self._run(board=board)
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['board-lane'])
        self.assertEqual(payload['summary']['critical'], 1)

    def test_a_missing_lane_that_is_not_the_pool_only_warns(self):
        board = copy.deepcopy(self._LIVE_BOARD)
        board['field']['options'] = [
            o for o in board['field']['options'] if o['name'] != 'Parked']
        code, payload, _ = self._run(board=board)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._checks(payload), ['board-lane'])

    def test_a_project_with_no_board_cannot_pick_at_all(self):
        code, payload, _ = self._run(cfg_over={'board': {}})
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['board-lane'])
        self.assertIn('board-lane', payload['checked'])
        self.assertIn('board-column', payload['skipped'])

    def test_a_node_id_that_resolves_to_nothing_fails_the_run(self):
        code, payload, _ = self._run(board=None)
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['board-lane'])

    def test_a_node_id_pointing_at_a_different_board_warns(self):
        board = copy.deepcopy(self._LIVE_BOARD)
        board['title'] = 'something else'
        _, payload, _ = self._run(
            board=board,
            cfg_over={'board': {'project_node_id': 'PVT_1',
                                'project_title': 'widgets',
                                'status_field_name': 'Status',
                                'columns': self._snapshot(board)}})
        self.assertEqual(self._checks(payload), ['board-title'])

    def test_unreadable_pinning_is_reported_rather_than_assumed_correct(self):
        """Not knowing is not the same as being fine."""
        code, payload, _ = self._run(pins_ok=False)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(self._checks(payload), ['pin-unknown'])
        self.assertIn('field-unpinned', payload['skipped'])

    # ── what it costs, and what it refuses ───────────────────────────────────

    def test_the_api_checks_cost_three_round_trips(self):
        """Preflight runs at the top of every session, so this is a budget.

        Three, not two, since 9.0.0: labels and the board share one query, the
        issue-type pins are a second, and reading which open issues have no
        board card is the third. That last one is the price of the pool being a
        board column, and it is paid once per audit rather than per issue.
        """
        _, _, sent = self._run(
            cfg_over={'board': {'project_node_id': 'PVT_1', 'project_title': None,
                                'status_field_name': 'Status', 'columns': {}}},
            board={'title': None, 'field': {'options': []}})
        self.assertEqual(sent, ['repo', 'orphans', 'pins'])

    def test_an_open_issue_with_no_board_card_fails_the_run(self):
        """The check that makes the Backlog pool safe to adopt: an issue with
        no card is invisible to `pick`, and nothing else would say so."""
        code, payload, _ = self._run(orphans=(164, 224))
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['board-orphan'])
        self.assertIn('#164, #224', payload['findings'][0]['detail'])

    def test_a_board_that_holds_every_open_issue_is_clean(self):
        code, payload, _ = self._run()
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn('board-orphan', payload['checked'])

    def test_offline_runs_the_checks_that_need_no_network(self):
        def explode(*a, **k):
            raise AssertionError('--offline must not touch the network')

        with mock.patch.object(wf, 'gh_graphql', explode):
            code, payload, _ = self._run(
                sections=[s for s in self._SECTIONS if s != 'Label Map'],
                argv=['--offline'])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['config-section'])
        # The instruction-file scan reads local files only, so it runs too.
        self.assertEqual(payload['checked'],
                         ['config-section', 'instructions-retired'])

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


class TestBoardMoveOrdering(unittest.TestCase):
    """The column is resolved before the card is added, and that order matters.

    The other way round, an issue destined for a column the board does not have
    was added to the board and *then* found to have nowhere to go: the add
    succeeded, the status write did not, and the card landed in the board's
    `No Status` bucket while the caller was told `moved: false`. That is how a
    `report-issue` run aimed at a `Ready` column no board had put issues on the
    board with no status at all.
    """

    OPTIONS = [{'id': 'O_back', 'name': 'Backlog'},
               {'id': 'O_done', 'name': 'Done'}]

    def _cfg(self):
        return _cfg(board={'project_node_id': 'PVT_1',
                           'project_title': 'board', 'columns': {},
                           'status_field_name': 'Status'})

    def _move(self, column, on_board=True, options=None):
        """Drive `board_move`, recording every query and mutation it sends."""
        sent = []

        def fake_graphql(query, **fields):
            sent.append(query)
            if 'ProjectV2SingleSelectField' in query:
                return True, {'node': {
                    'title': 'board',
                    'field': {'id': 'F_1',
                              'options': self.OPTIONS if options is None
                              else options}}}, ''
            if 'projectItems' in query:
                items = [{'id': 'ITEM_1', 'project': {'id': 'PVT_1'}}] \
                    if on_board else []
                return True, {'repository': {'b3': {
                    'id': 'I_1', 'projectItems': {'nodes': items}}}}, ''
            if 'addProjectV2ItemById' in query:
                return True, {'a3': {'item': {'id': 'ITEM_NEW'}}}, ''
            if 'updateProjectV2ItemFieldValue' in query:
                return True, {'m3': {'projectV2Item': {'id': 'ITEM_1'}}}, ''
            raise AssertionError('unexpected query: %s' % query)

        wf._BOARD_FIELD_CACHE.clear()
        with mock.patch.object(wf, 'gh_graphql', fake_graphql):
            moved, message = wf.board_move(self._cfg(), 3, column)
        return moved, message, sent

    def test_an_unknown_column_never_touches_the_board(self):
        moved, message, sent = self._move('Ready', on_board=False)
        self.assertFalse(moved)
        self.assertIn("no 'Ready' column", message)
        self.assertFalse([q for q in sent if 'addProjectV2ItemById' in q])
        self.assertFalse([q for q in sent if 'updateProjectV2ItemFieldValue' in q])

    def test_an_unknown_column_names_the_ones_that_exist(self):
        """A report that only says no is a report someone has to go and check."""
        _, message, _ = self._move('Ready')
        self.assertIn('Backlog, Done', message)

    def test_an_unknown_column_costs_one_query(self):
        """Resolving first is also cheaper: the item lookup never happens."""
        _, _, sent = self._move('Ready')
        self.assertEqual(len(sent), 1)

    def test_a_known_column_still_adds_a_missing_card(self):
        moved, _, sent = self._move('Backlog', on_board=False)
        self.assertTrue(moved)
        self.assertTrue([q for q in sent if 'addProjectV2ItemById' in q])
        self.assertTrue([q for q in sent if 'updateProjectV2ItemFieldValue' in q])

    def test_identity_and_column_share_one_query(self):
        """The safer order is a round trip cheaper than the one it replaced."""
        moved, _, sent = self._move('Done')
        self.assertTrue(moved)
        self.assertEqual(len(sent), 3)

    def test_a_board_that_resolves_to_another_project_is_skipped(self):
        def fake_graphql(query, **fields):
            return True, {'node': {'title': 'somebody else', 'field': None}}, ''

        wf._BOARD_FIELD_CACHE.clear()
        with mock.patch.object(wf, 'gh_graphql', fake_graphql):
            moved, message = wf.board_move(self._cfg(), 3, 'Backlog')
        self.assertFalse(moved)
        self.assertIn('somebody else', message)


class TestUnblockSweep(unittest.TestCase):
    """`wf unblock`: release what the edges say is free, report the rest."""

    RELEASED = (1313, 'Device pass', [{'number': 1311, 'state': 'CLOSED'}])
    HELD = (1124, 'Create the account at sign-in',
            [{'number': 979, 'state': 'OPEN'},
             {'number': 1311, 'state': 'CLOSED'}])
    NO_EDGES = (1084, 'Open a bank account', [])
    # Human work whose only blocker has closed. Under the old rule this was
    # released into the code agent's pool; it is a device pass, so no agent can
    # do it whatever its edges say.
    SCOPED = (1368, '[Manual] Device pass on iOS',
              [{'number': 1362, 'state': 'CLOSED'}])

    def _cfg(self):
        return _cfg(board={'project_node_id': 'PVT_1', 'project_title': 'Board',
                           'status_field_name': 'Status', 'columns': {}})

    def _sweep(self, issues, calls, dry_run=False, deliveries=None,
               ownership=None, moves=None, queries=None):
        """Drive `unblock_scan` over `issues` with every network call stubbed.

        Each entry is `(number, title, blocked_by)`, laid out the way the board
        query returns it: the sweep reads the Blocked column, so a fixture that
        hands it a search result would be testing a path that no longer exists.
        """
        nodes = [{'fieldValueByName': {'name': 'Blocked'},
                  'content': {'number': n, 'title': t, 'body': '',
                              'state': 'OPEN', 'url': '',
                              'labels': {'nodes': []}, 'milestone': None,
                              'assignees': {'nodes': []},
                              'blockedBy': {'nodes': list(edges)}}}
                 for n, t, edges in issues]
        owned = {n: 'Code agent' for n, _t, _e in issues}
        owned.update(ownership or {})

        def fake_graphql(query, **fields):
            if queries is not None:
                queries.append(query)
            return True, {'node': {
                'field': {'options': [{'name': 'Backlog'}, {'name': 'Blocked'},
                                      {'name': 'Non-code'}]},
                'items': {'pageInfo': {'hasNextPage': False},
                          'nodes': nodes}}}, ''

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            return 0, '', ''

        def fake_move(cfg, number, column):
            (moves if moves is not None else []).append((number, column))
            return True, 'moved to %s' % column

        with mock.patch.object(wf, 'gh_graphql', fake_graphql), \
                mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'fetch_issue_facets',
                                  lambda *a, **k: (True, _facets(
                                      ownership=owned), '')), \
                mock.patch.object(wf, 'blocker_deliveries',
                                  lambda *a, **k: deliveries or {}), \
                mock.patch.object(wf, 'board_move', fake_move):
            return wf.unblock_scan(self._cfg(), dry_run=dry_run)

    def test_the_sweep_reads_the_blocked_column_not_a_label(self):
        """The 10.0.0 change, and the reason the sweep can be trusted at all.

        It searched for `status-blocked` until then, so an issue whose card sat
        in Blocked with no such label was invisible to it and stayed blocked
        for good -- and an issue carrying the label whose card had already
        moved on was swept anyway. One question, one answer, and the board is
        where it lives.
        """
        queries = []
        self._sweep([self.RELEASED], [], queries=queries)
        self.assertTrue(queries)
        self.assertFalse([q for q in queries if 'search(' in q])
        self.assertIn('ProjectV2', queries[0])

    def test_an_issue_whose_blockers_all_closed_is_released(self):
        moves = []
        report = self._sweep([self.RELEASED], [], moves=moves)
        self.assertEqual([r['issue'] for r in report['released']], [1313])
        self.assertEqual(report['released'][0]['closed_blockers'], [1311])
        self.assertTrue(report['released'][0]['board_moved'])
        self.assertEqual(moves, [(1313, 'Backlog')])

    def test_the_release_is_the_move_into_the_pool(self):
        """Backlog is the pick pool, so arriving there *is* being released.

        There is no second write for the two to disagree about, which is what
        the label version could never promise: an issue could carry no
        `status-blocked` label and still sit in the Blocked lane, out of the
        pool, with nothing to notice it.
        """
        moves = []
        self._sweep([self.RELEASED], [], moves=moves)
        self.assertEqual(moves, [(1313, 'Backlog')])

    def test_a_release_says_on_the_issue_why_the_card_moved(self):
        """A bare move reads to the next agent as damage to repair, and one
        repaired it two minutes later. The comment is what stops that."""
        calls = []
        self._sweep([self.RELEASED], calls)
        comments = [c for c in calls if 'comment' in c]
        self.assertEqual(len(comments), 1)
        body = comments[0][-1]
        self.assertIn('#1311', body)
        self.assertIn('on purpose', body)

    def test_an_issue_with_one_open_blocker_is_held_and_untouched(self):
        calls, moves = [], []
        report = self._sweep([self.HELD], calls, moves=moves)
        self.assertEqual(report['released'], [])
        self.assertEqual(report['held'][0]['open_blockers'], [979])
        self.assertEqual(report['held'][0]['closed_blockers'], [1311])
        self.assertEqual(moves, [])
        self.assertFalse([c for c in calls if 'edit' in c or 'comment' in c])

    def test_an_issue_with_no_edges_is_never_released(self):
        """The safety rule, at the level that matters: the manual backlog is
        blocked on bank accounts and device passes, not on issues."""
        calls, moves = [], []
        report = self._sweep([self.NO_EDGES], calls, moves=moves)
        self.assertEqual(report['released'], [])
        self.assertEqual(report['held'], [])
        self.assertEqual(report['no_edges'], {'count': 1, 'issues': [1084]})
        self.assertEqual(calls, [])
        self.assertEqual(moves, [])

    def test_an_issue_nobody_owns_is_held_and_named(self):
        """The sweep will not decide an unowned issue is safe for a code agent.

        Same rule the picker follows, and the same reason: `Ownership` is the
        only thing that says whether a job needs a phone in someone's hand.
        Held rather than dropped, because a repository with unowned issues has
        a configuration problem the report should name.
        """
        moves = []
        report = self._sweep([self.RELEASED], [], ownership={1313: None},
                             moves=moves)
        self.assertEqual(report['released'], [])
        self.assertEqual(report['unowned'],
                         [{'issue': 1313, 'title': 'Device pass'}])
        self.assertEqual(moves, [])

    def test_scoped_work_is_moved_to_the_non_code_lane_not_released(self):
        """The bug this lane exists to close. Both issues the first real sweep
        would have released were `[Manual]` device-pass work whose blockers
        happened to close."""
        moves = []
        report = self._sweep([self.SCOPED], [], ownership={1368: 'Human'},
                             moves=moves)
        self.assertEqual(report['released'], [])
        self.assertEqual([r['issue'] for r in report['rescoped']], [1368])
        self.assertEqual(report['rescoped'][0]['scope'], 'human')
        self.assertEqual(report['rescoped'][0]['column'], 'Non-code')
        self.assertEqual(moves, [(1368, 'Non-code')])

    def test_a_rescope_says_on_the_issue_what_changed_and_what_did_not(self):
        calls = []
        self._sweep([self.SCOPED], calls, ownership={1368: 'Human'})
        body = [c for c in calls if 'comment' in c][0][-1]
        self.assertIn('Non-code', body)
        self.assertIn('Nothing about the work has changed', body)

    def test_a_dry_run_reports_a_rescope_without_writing_it(self):
        calls, moves = [], []
        report = self._sweep([self.SCOPED], calls, dry_run=True,
                             ownership={1368: 'Human'}, moves=moves)
        self.assertTrue(report['rescoped'][0]['dry_run'])
        self.assertEqual(calls, [])
        self.assertEqual(moves, [])

    def test_a_dry_run_reports_the_same_release_and_writes_nothing(self):
        calls, moves = [], []
        report = self._sweep([self.RELEASED], calls, dry_run=True, moves=moves)
        self.assertEqual([r['issue'] for r in report['released']], [1313])
        self.assertTrue(report['released'][0]['dry_run'])
        self.assertEqual(calls, [])
        self.assertEqual(moves, [])

    def test_a_held_issue_whose_blocker_just_shipped_is_reported_as_partial(self):
        report = self._sweep(
            [self.HELD], [],
            deliveries={979: {'number': 1372, 'merged_at': '2026-09-09T09:31:43Z'}})
        self.assertEqual(report['partials'],
                         [{'issue': 1124, 'title': 'Create the account at sign-in',
                           'deliveries': [{'blocker': 979, 'merged_pr': 1372,
                                           'merged_at': '2026-09-09T09:31:43Z'}]}])

    def test_a_held_issue_with_no_recent_delivery_is_not_a_partial(self):
        report = self._sweep([self.HELD], [])
        self.assertEqual(report['partials'], [])

    def test_the_scan_reports_everything_it_looked_at(self):
        report = self._sweep(
            [self.RELEASED, self.HELD, self.NO_EDGES, self.SCOPED], [],
            ownership={1368: 'Human'})
        self.assertEqual(report['scanned'], 4)
        self.assertEqual(len(report['released']), 1)
        self.assertEqual(len(report['held']), 1)
        self.assertEqual(len(report['rescoped']), 1)
        self.assertEqual(report['no_edges']['count'], 1)


class TestMarkBlocked(unittest.TestCase):
    """Returning an issue to blocked moves its card, and that is the whole act.

    The board is how a person sees the state of the work, and until 10.0.0 it
    was also given a `status-blocked` label to agree with. Two records of one
    fact is one record too many: a card in In Progress carrying a blocked label
    is two answers, and the one a human reads is the wrong one.
    """

    def _mark(self):
        calls, moves = [], []
        with mock.patch.object(wf, 'run',
                               lambda c, input_text=None:
                               (calls.append(list(c)), (0, '', ''))[1]), \
                mock.patch.object(wf, 'board_move',
                                  lambda cfg, number, column:
                                  (moves.append((number, column)), (True, ''))[1]):
            wf.mark_blocked(_cfg(), {'number': 7}, '#9')
        return calls, moves

    def test_the_card_moves_to_the_blocked_lane(self):
        _calls, moves = self._mark()
        self.assertEqual(moves, [(7, 'Blocked')])

    def test_the_claim_is_given_back(self):
        """The issue is nobody's again, which is what puts it back in reach of
        the sweep that releases it when its dependency closes."""
        calls, _moves = self._mark()
        joined = ' '.join(' '.join(c) for c in calls)
        self.assertIn('--remove-assignee @me', joined)

    def test_no_label_is_written(self):
        calls, _moves = self._mark()
        joined = ' '.join(' '.join(c) for c in calls)
        self.assertNotIn('--add-label', joined)

    def test_the_issue_says_what_it_is_waiting_for(self):
        calls, _moves = self._mark()
        body = [c for c in calls if 'comment' in c][0][-1]
        self.assertIn('#9', body)


class TestPreflight(unittest.TestCase):
    """The one gate every workflow command runs first.

    It used to be shell blocks inside `skills/preflight/SKILL.md` plus a
    separate `config-audit`, which is two implementations of one question and
    they disagreed about what counted as critical. These tests pin the answer.
    """

    _LIVE_BOARD = {'title': 'Board', 'field': {'options': [
        {'id': 'opt%d' % i, 'name': name}
        for i, name in enumerate(sorted(wf_core.BOARD_COLUMN_NAMES.values()))]}}

    _CONFIG = '\n'.join([
        '# Project', '',
        '## Identity', '', '| org | acme |', '| repo | widgets |', '',
        '## Package Manager', '', 'pnpm', '',
        '## Quality Gate', '', '```bash', 'pnpm test', '```', '',
        '## Branch Convention', '', '```', 'feature/{number}/{short-desc}', '```', '',
        '## Label Map', '', '| Purpose | Label |', '| --- | --- |',
        '| claude-authored | `claude-authored` |', '',
        '## Issue Types & Fields', '', '| type-capable | yes |', '',
        '## Project Board', '', '| project-node-id | PVT_1 |',
        '| project-title | Board |', '',
        '### Status Options', '',
        '| Column | Purpose Key | Option ID |', '| ------ | ----------- | --------- |',
    ] + ['| %s | `%s` | `opt%d` |'
         % (name, purpose,
            sorted(wf_core.BOARD_COLUMN_NAMES.values()).index(name))
         for purpose, name in wf_core.BOARD_COLUMN_NAMES.items()] + [''])

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.scan = os.path.join(self.dir, 'plugin')
        os.makedirs(self.scan)
        self._write('ClaudeProject.md', self._CONFIG)
        self._write('CLAUDE.md', '# Repo\n\nSee ClaudeProject.md.\n')

    def _write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        return path

    def _read(self, name):
        with open(os.path.join(self.dir, name), encoding='utf-8') as fh:
            return fh.read()

    # ── finished containers (#240) ───────────────────────────────────────────

    def test_a_finished_container_is_a_warning_the_fix_can_repair(self):
        _, payload, _ = self._run(finished=[40])
        found = [f for f in payload['findings'] if f['check'] == 'container-finished']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['level'], wf_core.WARNING)
        self.assertIn('#40', found[0]['detail'])
        self.assertTrue(found[0]['auto'])

    def test_fix_closes_a_finished_container_as_completed(self):
        _, payload, calls = self._run(['--fix'], finished=[40])
        closes = [c for c in calls if c[:3] == ['gh', 'issue', 'close']]
        self.assertEqual(len(closes), 1)
        self.assertIn('40', closes[0])
        self.assertIn('completed', closes[0])
        self.assertTrue(any('#40' in line for line in payload['fixed']))

    def test_fix_walks_up_to_an_epic_the_closed_container_finished(self):
        """The same rule as post-merge, so one `--fix` is enough."""
        epic = {'number': 1, 'title': 'e', 'state': 'OPEN', 'type': 'Epic',
                'repo': None, 'children': [{'number': 40, 'state': 'OPEN'}]}
        with mock.patch.object(wf, 'fetch_parent_chain',
                               return_value=(True, [epic], '')):
            _, payload, calls = self._run(['--fix'], finished=[40])
        closed = [c[3] for c in calls if c[:3] == ['gh', 'issue', 'close']]
        self.assertEqual(closed, ['40', '1'])
        self.assertTrue(any('#1' in line for line in payload['fixed']))

    def test_fix_says_when_it_could_not_read_a_parent(self):
        with mock.patch.object(wf, 'fetch_parent_chain',
                               return_value=(False, [], 'HTTP 502')):
            _, payload, _ = self._run(['--fix'], finished=[40])
        self.assertTrue(any('#40' in line for line in payload['fixed']))
        self.assertTrue(any('could not read the parents of #40' in line
                            for line in payload['unfixed']))
        self.assertFalse(any('could not close' in line for line in payload['unfixed']))

    def _run(self, argv=(), board=_UNSET, orphans=(), unset=(), env_err=None,
             mutation=None, moves=None, finished=()):
        if board is _UNSET:
            board = copy.deepcopy(self._LIVE_BOARD)
        args = wf.build_parser().parse_args(
            ['preflight', '--scan', self.scan, *argv])
        cfg = _cfg(board={'project_node_id': 'PVT_1', 'project_title': 'Board',
                          'status_field_name': 'Status',
                          'status_field_id': 'FIELD_1',
                          'columns': {p: 'opt%d' % i for i, p
                                      in enumerate(wf_core.BOARD_COLUMN_NAMES)}})

        def gh_graphql(query, **fields):
            if 'projectItems' in query:
                nodes = ([{'number': n, 'title': 't', 'assignees': {'totalCount': 0},
                           'projectItems': {'nodes': []}} for n in orphans]
                         + [{'number': n, 'title': 't', 'assignees': {'totalCount': 1},
                             'projectItems': {'nodes': [
                                 {'project': {'id': 'PVT_1'},
                                  'fieldValueByName': None}]}} for n in unset]
                         # An Epic whose only sub-issue is closed, carded in a
                         # lane, so it is finished and nothing else (#240).
                         + [{'number': n, 'title': 'container %d' % n,
                             'state': 'OPEN', 'issueType': {'name': 'Epic'},
                             'subIssues': {'nodes': [
                                 {'number': n + 1, 'state': 'CLOSED'}]},
                             'assignees': {'totalCount': 0},
                             'projectItems': {'nodes': [
                                 {'project': {'id': 'PVT_1'},
                                  'fieldValueByName': {'name': 'Backlog'}}]}}
                            for n in finished])
                return True, {'repository': {'issues': {
                    'pageInfo': {'hasNextPage': False, 'endCursor': None},
                    'nodes': nodes}}}, ''
            if 'labels(' in query:
                return True, {'repository': {'labels': {
                    'pageInfo': {'hasNextPage': False, 'endCursor': None},
                    'nodes': [{'name': 'claude-authored'}]}}, 'board': board}, ''
            if not board:
                return False, None, 'no board'
            return True, {'node': {'title': board.get('title'),
                                   'field': dict(board['field'],
                                                 id='FIELD_1')}}, ''

        def gh_graphql_partial(query, **fields):
            return {'organization': {'issueTypes': {'nodes': [
                {'name': 'User Story', 'isEnabled': True,
                 'pinnedFields': [{'name': n} for n
                                  in ('Priority', 'Effort', 'Ownership')]}]}}}, [], ''

        calls = []

        def fake_run(cmd, input_text=None):
            calls.append(list(cmd))
            if mutation is not None and 'graphql' in cmd:
                return mutation
            return 0, '{}', ''

        with mock.patch.object(wf, 'load_config',
                               lambda: (True, copy.deepcopy(cfg), '')), \
                mock.patch.object(wf, 'repo_root', lambda: self.dir), \
                mock.patch.object(wf, 'check_environment', lambda: env_err), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg, refresh=False, root=None:
                                  (True, _APPLY_CAPS, '')), \
                mock.patch.object(wf, 'gh_graphql', gh_graphql), \
                mock.patch.object(wf, 'gh_graphql_partial', gh_graphql_partial), \
                mock.patch.object(wf, 'run', fake_run), \
                mock.patch.object(wf, 'board_move',
                                  lambda c, n, col: (moves if moves is not None
                                                     else (True, 'moved'))), \
                contextlib.redirect_stderr(io.StringIO()):
            code, payload = _capture(wf.cmd_preflight, args)
        return code, payload, calls

    def _checks(self, payload):
        return [f['check'] for f in payload['findings']]

    # ── the clean case ───────────────────────────────────────────────────────

    def test_a_healthy_project_reports_nothing_and_exits_zero(self):
        code, payload, _ = self._run()
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['summary']['critical'], 0)
        self.assertEqual(payload['findings'], [])

    def test_the_checks_that_ran_are_named_so_silence_can_be_read(self):
        _, payload, _ = self._run()
        for check in ('gh-auth', 'file-config', 'config-section', 'board-lane',
                      'quality-gate', 'claude-md-ref'):
            self.assertIn(check, payload['checked'], check)

    # ── the critical cases ───────────────────────────────────────────────────

    def test_an_unauthenticated_cli_is_critical(self):
        code, payload, _ = self._run(env_err='gh not available')
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(payload['status'], 'blocked')
        self.assertIn('gh-auth', self._checks(payload))

    def test_a_missing_config_file_stops_before_the_network(self):
        os.remove(os.path.join(self.dir, 'ClaudeProject.md'))
        code, payload, calls = self._run()
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertEqual(self._checks(payload), ['file-config'])
        self.assertEqual(calls, [])

    def test_an_orphaned_issue_is_critical_because_nothing_can_select_it(self):
        code, payload, _ = self._run(orphans=[41])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertIn('board-orphan', self._checks(payload))

    # ── the warning cases ────────────────────────────────────────────────────

    def test_a_surviving_ready_gate_warns_without_blocking(self):
        self._write('ClaudeProject.md',
                    self._CONFIG + '\n## Ready Gate\n\nmode: strict\n')
        code, payload, _ = self._run()
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn('config-retired', self._checks(payload))

    def test_an_unfilled_quality_gate_warns(self):
        self._write('ClaudeProject.md',
                    self._CONFIG.replace('pnpm test', '{quality_gate_command}'))
        code, payload, _ = self._run()
        self.assertEqual(code, wf.EXIT_OK)
        self.assertIn('quality-gate', self._checks(payload))

    def test_a_claude_md_that_never_mentions_the_config_warns(self):
        self._write('CLAUDE.md', '# Repo\n\nNothing here.\n')
        _, payload, _ = self._run()
        self.assertIn('claude-md-ref', self._checks(payload))

    def test_a_named_review_config_that_is_missing_warns(self):
        self._write('ClaudeProject.md',
                    self._CONFIG + '\nSee docs/review.config.md.\n')
        _, payload, _ = self._run()
        self.assertIn('review-config', self._checks(payload))

    # ── every finding says whether --fix would touch it ──────────────────────

    def test_each_finding_says_whether_it_can_be_repaired_automatically(self):
        self._write('CLAUDE.md', '# Repo\n')
        _, payload, _ = self._run()
        found = {f['check']: f for f in payload['findings']}
        self.assertTrue(found['claude-md-ref']['auto'])
        self.assertIn('CLAUDE.md', found['claude-md-ref']['fixable'])

    def test_something_no_run_should_decide_says_why_not(self):
        self._write('ClaudeProject.md',
                    self._CONFIG.replace('pnpm test', '{quality_gate_command}'))
        _, payload, _ = self._run()
        gate = [f for f in payload['findings'] if f['check'] == 'quality-gate'][0]
        self.assertFalse(gate['auto'])
        self.assertIn('project', gate['fixable'])

    # ── --fix ────────────────────────────────────────────────────────────────

    def test_fix_deletes_a_retired_section_and_says_so(self):
        self._write('ClaudeProject.md',
                    self._CONFIG + '\n## Agent Gating\n\n| agent-gating | on |\n')
        code, payload, _ = self._run(['--fix'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertNotIn('Agent Gating', self._read('ClaudeProject.md'))
        self.assertTrue(any('Agent Gating' in line for line in payload['fixed']))

    def test_fix_reports_the_state_it_leaves_not_the_state_it_found(self):
        """A second run of an idempotent command must look like a clean run."""
        self._write('ClaudeProject.md', self._CONFIG + '\n## Ready Gate\n\nx\n')
        _, first, _ = self._run(['--fix'])
        self.assertNotIn('config-retired', self._checks(first))
        _, second, _ = self._run(['--fix'])
        self.assertEqual(second['fixed'], [])
        self.assertEqual(second['findings'], [])

    def test_fix_adds_the_config_pointer_to_an_existing_claude_md(self):
        self._write('CLAUDE.md', '# Repo\n')
        _, payload, _ = self._run(['--fix'])
        self.assertIn('ClaudeProject.md', self._read('CLAUDE.md'))
        self.assertTrue(any('CLAUDE.md' in line for line in payload['fixed']))

    def test_fix_never_writes_a_claude_md_that_does_not_exist(self):
        os.remove(os.path.join(self.dir, 'CLAUDE.md'))
        _, payload, _ = self._run(['--fix'])
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'CLAUDE.md')))
        self.assertIn('file-claude-md', self._checks(payload))

    def test_fix_places_an_orphaned_issue_in_the_backlog(self):
        _, payload, _ = self._run(['--fix'], orphans=[41, 42])
        self.assertTrue(any('#41' in line and '#42' in line
                            for line in payload['fixed']))

    def test_a_card_in_no_lane_is_placed_too(self):
        _, payload, _ = self._run(['--fix'], unset=[7])
        self.assertTrue(any('#7' in line for line in payload['fixed']))

    def test_a_placement_that_fails_is_reported_rather_than_claimed(self):
        _, payload, _ = self._run(['--fix'], orphans=[41],
                                  moves=(False, 'no board'))
        self.assertEqual(payload['fixed'], [])
        self.assertTrue(any('#41' in line for line in payload['unfixed']))

    def test_fix_creates_a_missing_lane_and_records_its_id(self):
        board = {'title': 'Board', 'field': {'options': [
            {'id': 'o1', 'name': 'Backlog'}, {'id': 'o2', 'name': 'Done'}]}}
        created = json.dumps({'data': {'updateProjectV2Field': {
            'projectV2Field': {'options': [
                {'id': 'o1', 'name': 'Backlog'}, {'id': 'o2', 'name': 'Done'},
                {'id': 'o3', 'name': 'In Progress'}]}}}})
        _, payload, calls = self._run(['--fix'], board=board,
                                      mutation=(0, created, ''))
        mutations = [c for c in calls if 'graphql' in c]
        self.assertTrue(mutations)
        self.assertIn('In Progress', ' '.join(mutations[0]))
        self.assertIn('`o3`', self._read('ClaudeProject.md'))

    def test_creating_a_lane_passes_back_every_existing_option(self):
        """`updateProjectV2Field` replaces the option list. Omit one and the
        column is deleted along with every card sitting in it."""
        board = {'title': 'Board', 'field': {'options': [
            {'id': 'o1', 'name': 'Backlog'}, {'id': 'o2', 'name': 'Done'}]}}
        _, _, calls = self._run(
            ['--fix'], board=board,
            mutation=(0, json.dumps({'data': {'updateProjectV2Field': {
                'projectV2Field': {'options': []}}}}), ''))
        sent = ' '.join([c for c in calls if 'graphql' in c][0])
        self.assertIn('"o1"', sent)
        self.assertIn('"o2"', sent)

    def test_a_failed_mutation_is_reported_and_nothing_is_recorded(self):
        board = {'title': 'Board', 'field': {'options': [
            {'id': 'o1', 'name': 'Backlog'}]}}
        before = self._read('ClaudeProject.md')
        code, payload, _ = self._run(['--fix'], board=board,
                                     mutation=(1, '', 'insufficient scope'))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertTrue(any('insufficient scope' in line
                            for line in payload['unfixed']))
        self.assertEqual(self._read('ClaudeProject.md'), before)

    def test_a_graphql_error_body_is_a_failure_even_with_exit_zero(self):
        """GraphQL returns HTTP 200 with an `errors` array."""
        board = {'title': 'Board', 'field': {'options': [
            {'id': 'o1', 'name': 'Backlog'}]}}
        _, payload, _ = self._run(
            ['--fix'], board=board,
            mutation=(0, json.dumps({'errors': [{'message': 'nope'}]}), ''))
        self.assertTrue(any('nope' in line for line in payload['unfixed']))

    def test_fix_leaves_a_critical_it_must_not_decide_alone(self):
        """A missing `## Identity` is a project nobody configured, not drift."""
        self._write('ClaudeProject.md',
                    self._CONFIG.replace('## Identity', '## Who We Are'))
        code, payload, _ = self._run(['--fix'])
        self.assertEqual(code, wf.EXIT_DRIFT)
        self.assertIn('config-section', self._checks(payload))
        self.assertEqual(payload['fixed'], [])


# ── candidates --parent (#239) ───────────────────────────────────────────────

def _node(number, kind, *children, title=None):
    return {'number': number, 'title': title or 'issue %d' % number,
            'state': 'OPEN', 'type': kind, 'repo': None,
            'children': list(children)}


def _blocked_card(number, *blockers):
    return {'number': number, 'title': 'issue %d' % number, 'body': '',
            'labels': [], 'milestone': None, 'url': '', 'assigned': False,
            'assignees': [],
            'blockedBy': {'nodes': [{'number': b, 'state': 'OPEN'} for b in blockers]}}


class TestCandidatesUnderParent(unittest.TestCase):
    """`wf candidates --parent N`: the one set a container's tree offers."""

    def setUp(self):
        for name, value in (('check_environment', None),
                            ('load_config', (True, _cfg(), '')),
                            ('issue_edges_map', ({}, set()))):
            patch = mock.patch.object(wf, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def _run(self, tree, pool, blocked=(), lanes=None, ownership=None, argv=(),
             types=None):
        facets = (_facets(types=types, ownership=ownership) if ownership
                  else _facets(types=types))
        with mock.patch.object(wf, 'fetch_container_tree', return_value=(True, tree, '')), \
                mock.patch.object(wf, 'assemble_candidates', return_value=(True, pool, '')), \
                mock.patch.object(wf, 'load_issue_facets', return_value=facets), \
                mock.patch.object(wf, 'blocked_issues', return_value=(list(blocked), None)), \
                mock.patch.object(wf, 'board_current_columns',
                                  return_value=(True, lanes or {}, '')):
            return _capture(wf.cmd_candidates,
                            _candidates_args('--parent', str(tree['number']), *argv))

    def test_backlog_leaves_and_a_leaf_waiting_on_them_are_offered(self):
        tree = _node(50, 'Feature', _node(51, 'User Story'), _node(52, 'User Story'),
                     _node(53, 'User Story'))
        code, payload = self._run(
            tree, [_candidate(51)], blocked=[_blocked_card(52, 51)],
            lanes={53: 'Non-code'},
            ownership={51: 'Code agent', 52: 'Code agent', 53: 'Human'})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([c['number'] for c in payload['candidates']], [51, 52])
        self.assertEqual([c['column'] for c in payload['candidates']],
                         ['Backlog', 'Blocked'])
        self.assertEqual(payload['feature'], 50)
        reason = next(e['reason'] for e in payload['excluded'] if e['number'] == 53)
        self.assertIn('Non-code', reason)
        self.assertIn('Human', reason)

    def test_a_blocked_leaf_waiting_on_other_work_is_not_offered(self):
        tree = _node(50, 'Feature', _node(51, 'User Story'), _node(52, 'User Story'))
        _, payload = self._run(tree, [_candidate(51)], blocked=[_blocked_card(52, 99)])
        self.assertEqual([c['number'] for c in payload['candidates']], [51])
        self.assertIn('#99', payload['excluded'][0]['reason'])

    def test_a_blocked_leaf_outside_the_mode_is_not_offered(self):
        """`--mode` holds for a Blocked leaf as it does for the pool, because
        a set never mixes modes: a waiting story does not join a bug's set."""
        tree = _node(50, 'Feature', _node(51, 'Bug'), _node(52, 'User Story'))
        with mock.patch.object(wf, 'load_config',
                               return_value=(True, _cfg(type_capable=True), '')):
            _, payload = self._run(tree, [_candidate(51)],
                                   blocked=[_blocked_card(52, 51)],
                                   types={51: 'Bug', 52: 'User Story'},
                                   argv=('--mode', 'maintenance'))
        self.assertEqual([c['number'] for c in payload['candidates']], [51])
        reason = next(e['reason'] for e in payload['excluded'] if e['number'] == 52)
        self.assertIn('--mode maintenance', reason)
        self.assertNotIn('Blocked', reason)

    def test_sub_issues_past_the_page_size_are_reported(self):
        tree = _node(50, 'Feature', _node(51, 'User Story'))
        tree['unread'] = 3
        _, payload = self._run(tree, [_candidate(51)])
        self.assertEqual(payload['unread'], [{'number': 50, 'unread': 3}])
        self.assertIn('#50', payload['reason'])

    def test_a_tree_read_in_full_reports_nothing_unread(self):
        tree = _node(50, 'Feature', _node(51, 'User Story'))
        _, payload = self._run(tree, [_candidate(51)])
        self.assertEqual(payload['unread'], [])

    def test_a_story_is_not_a_parent(self):
        code, payload = self._run(_node(51, 'User Story'), [_candidate(51)])
        self.assertEqual(code, wf.EXIT_USAGE)
        self.assertIn('not an Epic or Feature', payload['reason'])

    def test_nothing_available_still_says_why(self):
        tree = _node(50, 'Feature', _node(51, 'User Story'))
        code, payload = self._run(tree, [], lanes={51: 'Parked'})
        self.assertEqual(code, wf.EXIT_NO_CANDIDATES)
        self.assertIn('Parked', payload['excluded'][0]['reason'])


class TestPickBlockedSibling(unittest.TestCase):
    """`pick --issue N --sibling M` claims a Blocked leaf whose only open
    blocker is M, which is how `--parent`'s Blocked leaves get claimed."""

    def test_a_blocked_card_is_accepted_and_a_sibling_does_not_block_it(self):
        data = {'number': 52, 'title': 't', 'labels': [], 'body': '',
                'milestone': None, 'url': '', 'state': 'OPEN', 'assignees': []}
        cfg = _cfg()
        with mock.patch.object(wf, 'gh_json', return_value=(True, data, '')), \
                mock.patch.object(wf, 'load_issue_facets', return_value=_facets()), \
                mock.patch.object(wf, 'board_current_columns',
                                  return_value=(True, {52: 'Blocked'}, '')):
            self.assertEqual(wf.fetch_issue_candidate(cfg, 52)['number'], 52)
        with mock.patch.object(wf, 'issue_edges',
                               return_value=[{'number': 51, 'state': 'OPEN'}]), \
                mock.patch.object(wf, 'merged_pr_closing', return_value=None):
            self.assertEqual(wf.validate_issue(cfg, {'number': 52}, siblings=[51])[0],
                             'valid')
            self.assertEqual(wf.validate_issue(cfg, {'number': 52})[0], 'blocked')


if __name__ == '__main__':
    unittest.main(verbosity=2)
