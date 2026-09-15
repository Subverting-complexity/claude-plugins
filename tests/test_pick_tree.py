#!/usr/bin/env python3
"""Choosing work from issue data and the Epic and Feature tree (#256).

The rules are `wf_core.evaluate_pool`; the first half of this file drives it
directly. The second half drives `wf pick` and `wf candidates` through their
seams, with no network, to show the rules reach the commands: an Epic or
Feature expands to its stories, an unclear issue stops an attended run and is
sent to refinement by an unattended one, and no board is ever queried.
"""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
import wf  # noqa: E402
import wf_core  # noqa: E402

CLEAR = ('## Summary\n\nChange the thing the story names.\n\n'
         '## Acceptance criteria\n\n- [ ] The thing is changed.\n')


def issue(number, type_name='User Story', stage=None, parent=None, children=(),
          blockers=(), assigned=False, prs=(), body=CLEAR, total=None,
          edge_total=None):
    return {'number': number, 'title': 'issue %d' % number, 'body': body,
            'labels': [], 'milestone': None, 'url': '', 'stage': stage,
            'assigned': assigned, 'assignees': ['someone'] if assigned else [],
            'type': type_name, 'parent': parent,
            'sub_issues': {'total': len(children) if total is None else total,
                           'open': list(children)},
            'blockedBy': {'totalCount': len(blockers) if edge_total is None else edge_total,
                          'nodes': [{'number': b, 'state': 'OPEN'} for b in blockers]},
            'open_prs': list(prs)}


def judge(issues, **kwargs):
    kwargs.setdefault('ownership_map', {i['number']: 'Code agent' for i in issues})
    return wf_core.evaluate_pool(issues, **kwargs)


def numbers(entries):
    return [e['number'] for e in entries]


class TestEvaluatePool(unittest.TestCase):

    def test_an_unassigned_story_with_no_card_stage_or_owner_is_picked(self):
        verdict = judge([issue(1)], ownership_map={})
        self.assertEqual(numbers(verdict['pool']), [1])

    def test_every_stage_but_backlog_takes_an_issue_out(self):
        for stage in wf_core.STAGE_NAMES.values():
            with self.subTest(stage=stage):
                verdict = judge([issue(1, stage=stage)])
                expected = [1] if stage == 'Backlog' else []
                self.assertEqual(numbers(verdict['pool']), expected)

    def test_assigned_claimed_or_closed_by_an_open_pr_is_not_pickable(self):
        verdict = judge([issue(1, assigned=True), issue(2), issue(3, prs=[40]),
                         issue(4)], claimed={2})
        self.assertEqual(numbers(verdict['pool']), [4])
        self.assertIn('#40', verdict['excluded'][3])
        self.assertIn('claimed', verdict['excluded'][2])

    def test_no_owner_is_code_work_only_for_a_story_or_a_bug(self):
        verdict = judge([issue(1, 'Bug'), issue(2, 'Chore'), issue(3, 'User Story')],
                        ownership_map={})
        self.assertEqual(numbers(verdict['pool']), [1, 3])
        self.assertIn('Ownership', verdict['excluded'][2])

    def test_work_owned_by_somebody_else_is_not_pickable(self):
        verdict = judge([issue(1), issue(2)],
                        ownership_map={1: 'Human', 2: 'Browser agent'})
        self.assertEqual(verdict['pool'], [])

    def test_a_blocked_story_is_skipped_and_its_siblings_are_offered(self):
        issues = [issue(10, 'Feature', children=[11, 12]),
                  issue(11, parent=10, blockers=[99]), issue(12, parent=10)]
        verdict = judge(issues)
        self.assertEqual(verdict['blocked'], {11: [99]})
        feature = next(e for e in verdict['pool'] if e['number'] == 10)
        self.assertEqual(feature['stories'], [12])
        self.assertNotIn(11, numbers(verdict['pool']))

    def test_an_edge_list_past_the_read_is_left_to_the_claim(self):
        verdict = judge([issue(1, blockers=[9], edge_total=25)])
        self.assertEqual(numbers(verdict['pool']), [1])
        self.assertEqual(verdict['blocked'], {})

    def test_an_epic_takes_its_highest_priority_feature_and_its_stories(self):
        issues = [issue(1, 'Epic', children=[2, 3]),
                  issue(2, 'Feature', parent=1, children=[4]),
                  issue(3, 'Feature', parent=1, children=[5, 6]),
                  issue(4, parent=2), issue(5, parent=3), issue(6, parent=3)]
        priority = {1: 'High', 2: 'Low', 3: 'High', 4: 'Urgent', 5: 'Low', 6: 'High'}
        verdict = judge(issues, priority_map=priority)
        epic = next(e for e in verdict['pool'] if e['number'] == 1)
        self.assertEqual(epic['feature'], 3)
        self.assertEqual(epic['stories'], [6, 5])

    def test_a_story_under_a_parked_epic_or_feature_is_not_offered(self):
        for parked in (1, 2):
            with self.subTest(parked=parked):
                issues = [issue(1, 'Epic', stage='Parked' if parked == 1 else None,
                                children=[2]),
                          issue(2, 'Feature', parent=1, children=[3],
                                stage='Parked' if parked == 2 else None),
                          issue(3, parent=2)]
                verdict = judge(issues)
                self.assertEqual(verdict['pool'], [])
                self.assertIn('#%d' % parked, verdict['excluded'][3])

    def test_a_childless_epic_or_feature_needs_refinement(self):
        verdict = judge([issue(1, 'Epic'), issue(2, 'Feature')])
        self.assertEqual(verdict['pool'], [])
        self.assertEqual(sorted(e['number'] for e in verdict['ranked']
                                if e.get('unclear')), [1, 2])

    def test_a_feature_whose_stories_are_all_taken_is_out_not_unclear(self):
        issues = [issue(10, 'Feature', children=[11]), issue(11, parent=10, assigned=True)]
        verdict = judge(issues)
        self.assertEqual(verdict['ranked'], [])
        self.assertIn('nothing under it', verdict['excluded'][10])

    def test_a_thin_story_or_one_with_no_criteria_needs_refinement(self):
        verdict = judge([issue(1, body='Fix it.'),
                         issue(2, body='A long enough body that still says '
                                       'nothing about how to tell it is done.')])
        self.assertEqual(verdict['pool'], [])
        reasons = {e['number']: e['unclear'] for e in verdict['ranked']}
        self.assertIn('nearly empty', reasons[1])
        self.assertIn('acceptance criteria', reasons[2])

    def test_a_verification_section_counts_as_criteria(self):
        verdict = judge([issue(1, body='Make the export include archived rows.\n\n'
                                        '## Verification\n\nExport and count them.')])
        self.assertEqual([c['number'] for c in verdict['pool']], [1])

    def test_the_pool_is_ordered_by_priority_then_effort(self):
        verdict = judge([issue(1), issue(2), issue(3)],
                        priority_map={1: 'Low', 2: 'High', 3: 'High'},
                        effort_map={2: 'High', 3: 'Low'})
        self.assertEqual(numbers(verdict['pool']), [3, 2, 1])

    def test_feature_mode_offers_stories_and_maintenance_mode_bugs(self):
        issues = [issue(1, 'User Story'), issue(2, 'Bug'), issue(3, 'Chore')]
        self.assertEqual(numbers(judge(issues, mode='feature')['pool']), [1])
        self.assertEqual(numbers(judge(issues, mode='maintenance')['pool']), [2, 3])

    def test_maintenance_mode_takes_stories_under_a_tech_debt_feature(self):
        issues = [issue(10, 'Feature', children=[11]), issue(11, parent=10)]
        verdict = judge(issues, mode='maintenance',
                        classification_map={10: ['Tech Debt']})
        self.assertEqual(numbers(verdict['pool']), [10, 11])


# ── the commands ─────────────────────────────────────────────────────────────

_CFG = {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
        'branch_convention': 'feature/{number}/{short-desc}', 'labels': {},
        'review_labels': {}, 'fields': {}, 'type_capable': True, 'board': {}}


def _facets(issues, priority=None):
    return {'types': {i['number']: i['type'] for i in issues if i.get('type')},
            'priority': priority or {}, 'classification': {}, 'effort': {},
            'stage': {}, 'ownership': {i['number']: 'Code agent' for i in issues}}


def _capture(func, argv):
    buf, code = io.StringIO(), None
    with contextlib.redirect_stdout(buf):
        try:
            func(wf.build_parser().parse_args(argv))
        except SystemExit as exc:
            code = exc.code
    out = buf.getvalue()
    return code, (json.loads(out) if out.strip() else None)


class TestPickFromTheTree(unittest.TestCase):

    def setUp(self):
        for name, value in (('check_environment', None),
                            ('load_config', (True, dict(_CFG), '')),
                            ('claimed_issue_numbers', set()),
                            ('acquire_claim', 'won'),
                            ('apply_in_progress', None),
                            ('release_claim', None),
                            ('merged_pr_closing', None),
                            ('issue_edges', [])):
            patch = mock.patch.object(wf, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    @contextlib.contextmanager
    def _pool(self, issues, priority=None):
        with mock.patch.object(wf, 'assemble_candidates', return_value=(True, issues, '')), \
                mock.patch.object(wf, 'load_issue_facets',
                                  return_value=_facets(issues, priority)):
            yield

    def test_picking_a_feature_claims_its_best_story_and_offers_the_rest(self):
        issues = [issue(10, 'Feature', children=[11, 12]),
                  issue(11, parent=10), issue(12, parent=10)]
        with self._pool(issues, {10: 'Urgent', 11: 'Low', 12: 'High'}):
            code, payload = _capture(wf.cmd_pick, ['pick'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['number'], 12)
        self.assertEqual(payload['container']['number'], 10)
        self.assertEqual([o['number'] for o in payload['offered']], [11])

    def test_an_attended_run_stops_on_an_unclear_issue_and_claims_nothing(self):
        issues = [issue(1, body='Fix it.'), issue(2)]
        with self._pool(issues, {1: 'High', 2: 'Low'}):
            code, payload = _capture(wf.cmd_pick, ['pick'])
        self.assertEqual(code, wf.EXIT_NEEDS_REFINEMENT)
        self.assertEqual(payload['status'], 'needs-refinement')
        self.assertEqual(payload['number'], 1)
        wf.acquire_claim.assert_not_called()

    def test_an_unattended_run_sends_it_to_refinement_and_picks_the_next(self):
        issues = [issue(1, body='Fix it.'), issue(2)]
        with self._pool(issues, {1: 'High', 2: 'Low'}), \
                mock.patch.object(wf, 'set_stage', return_value=(True, 'set')) as stage, \
                mock.patch.object(wf, 'run', return_value=(0, '', '')):
            code, payload = _capture(wf.cmd_pick, ['pick', '--unattended'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['number'], 2)
        stage.assert_called_once_with(mock.ANY, 1, 'Needs refinement')
        self.assertEqual(payload['side_effects'][0]['action'], 'sent-to-refinement')

    def test_an_issue_with_an_open_edge_is_set_to_blocked_and_passed_over(self):
        issues = [issue(1, blockers=[9]), issue(2)]
        with self._pool(issues, {1: 'High', 2: 'Low'}), \
                mock.patch.object(wf, 'set_stages',
                                  return_value={1: (True, 'set')}) as stages:
            code, payload = _capture(wf.cmd_pick, ['pick'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['number'], 2)
        # One write, naming the node id the pool read already holds.
        stages.assert_called_once_with(mock.ANY, {1: 'Blocked'}, mock.ANY)


class TestNoBoardIsRead(unittest.TestCase):
    """Every GraphQL request `candidates` makes, recorded: none names a board."""

    def test_candidates_reads_issues_and_never_a_project(self):
        node = {'number': 1, 'title': 't', 'body': CLEAR, 'url': '',
                'labels': {'nodes': []}, 'milestone': None,
                'assignees': {'nodes': []}, 'issueFieldValues': {'nodes': []},
                'issueType': {'name': 'User Story'}, 'parent': None,
                'subIssues': {'totalCount': 0, 'nodes': []},
                'blockedBy': {'totalCount': 0, 'nodes': []},
                'closedByPullRequestsReferences': {'nodes': []}}
        queries = []

        def fake(query, **fields):
            queries.append(query)
            if 'issues(first:' in query:
                return True, {'repository': {'issues': {
                    'pageInfo': {'hasNextPage': False, 'endCursor': None},
                    'nodes': [node]}}}, ''
            return True, {'repository': {}}, ''

        with mock.patch.object(wf, 'check_environment', return_value=None), \
                mock.patch.object(wf, 'load_config', return_value=(True, dict(_CFG), '')), \
                mock.patch.object(wf, 'claimed_issue_numbers', return_value=set()), \
                mock.patch.object(wf, 'gh_graphql', side_effect=fake):
            code, payload = _capture(wf.cmd_candidates, ['candidates'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([c['number'] for c in payload['candidates']], [1])
        self.assertTrue(queries)
        for query in queries:
            self.assertNotIn('projectV2', query)
            self.assertNotIn('ProjectV2', query)
            self.assertNotIn('projectItems', query)


if __name__ == '__main__':
    unittest.main()
