#!/usr/bin/env python3
"""Dependency-aware selection, the same for `pick` and `plan-set`.

One regression test, or a few, per fault this file was written for: a blocker
in another repository read as a local number, a related group passed over for
one story, a releasable Blocked issue left for a sweep, an unread edge list
taken as no blockers, a claim taken between the read and the write, an edge
list diffed past its first page, a dependency cycle spelt two ways, a
prerequisite held back by `--mode`, and waves that depended on input order.
The commands are driven with every GitHub and git seam stubbed.
"""

import itertools
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
REPO = 'acme/widgets'
CFG = {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main', 'labels': {},
       'review_labels': {}, 'fields': {}, 'type_capable': True, 'board': {}}


def edge(number, state='OPEN', repo=None):
    node = {'number': number, 'state': state}
    if repo:
        node['repository'] = {'nameWithOwner': repo}
    return node


def issue(number, type_name='User Story', stage=None, parent=None, edges=(),
          total=None, assigned=False):
    edges = list(edges)
    return {'id': 'I_%d' % number, 'number': number, 'title': 'issue %d' % number,
            'body': CLEAR, 'labels': [], 'milestone': None, 'url': '', 'repo': REPO,
            'stage': stage, 'assigned': assigned,
            'assignees': ['someone'] if assigned else [], 'type': type_name,
            'parent': parent, 'sub_issues': {'total': 0, 'open': []},
            'blockedBy': {'totalCount': len(edges) if total is None else total,
                          'nodes': edges},
            'open_prs': []}


def judge(issues, **kwargs):
    kwargs.setdefault('ownership_map', {i['number']: 'Code agent' for i in issues})
    return wf_core.evaluate_pool(issues, **kwargs)


def pool_numbers(verdict):
    return [e['number'] for e in verdict['pool']]


def node(blockers=(), parent=None, epic=None, effort='Low'):
    return {'blockers': None if blockers is None else list(blockers),
            'parent': parent, 'epic': epic, 'effort': effort}


def chosen(plan):
    return [s['number'] for s in plan['selected']]


def reasons(plan):
    return {e['number']: e['reason'] for e in plan['excluded']}


class TestCrossRepositoryBlockers(unittest.TestCase):
    """1. A blocker is its repository and its number, never the number alone."""

    def test_an_open_foreign_blocker_is_not_the_local_issue_with_its_number(self):
        issues = [issue(12, edges=[edge(5, repo='org/other')]), issue(5)]
        verdict = judge(issues)
        self.assertEqual(verdict['blocked'], {12: ['org/other#5']})
        self.assertNotIn(12, pool_numbers(verdict))
        self.assertIn(5, pool_numbers(verdict))

    def test_the_plan_says_it_waits_in_another_repository(self):
        plan = wf_core.plan_set({12: node(['org/other#5']), 5: node()}, [12, 5],
                                seeds=[12])
        self.assertIn('org/other#5', reasons(plan)[12])
        self.assertIn('another repository', reasons(plan)[12])

    def test_a_closed_foreign_blocker_is_satisfied(self):
        edges = [edge(5, 'CLOSED', repo='org/other')]
        self.assertEqual(wf_core.edge_states(edges, REPO), ([], ['org/other#5']))
        self.assertEqual(wf_core.unblock_verdict(edges, REPO)[0], wf_core.UNBLOCK_RELEASE)
        self.assertIn(12, pool_numbers(judge([issue(12, edges=edges)])))

    def test_issue_apply_never_treats_a_foreign_edge_as_local(self):
        read = {'repository': {'nameWithOwner': REPO},
                'blockedBy': {'nodes': [edge(5, repo='org/other'), edge(6)]}}
        self.assertEqual(wf_core.local_blocker_numbers(read), [6])
        result = {'errors': [], 'changed': [], 'mismatches': [], 'number': 12,
                  'issue_id': 'I_12',
                  'issue': dict(read, blockedBy={'totalCount': 1,
                                                 'nodes': [edge(5, repo='org/other')]})}
        with mock.patch.object(wf, 'send_link_batch',
                               return_value={'b0': (True, {}, '')}) as batch, \
                mock.patch.object(wf, 'resolve_issue_ids', return_value={}) as ids:
            wf.link_phase(CFG, [{'entry': {'blocked_by': [5]}}], [result], {}, {5: 'I_5'})
        # Local #5 is added, and the foreign edge is neither kept as #5 nor removed.
        kinds = [op[1] for call in batch.call_args_list for op in call[0][0]]
        self.assertEqual(kinds, ['blocked-by'])
        ids.assert_not_called()


class TestOpenPoolPlanning(unittest.TestCase):
    """2. The budget filled by rank, linked or not."""

    def test_an_unlinked_higher_ranked_story_is_taken_first(self):
        universe = {9: node(), 1: node(parent=50), 2: node(parent=50)}
        plan = wf_core.plan_set(universe, [9, 1, 2])
        self.assertEqual(chosen(plan), [9, 1, 2])
        self.assertEqual(plan['lead'], 9)

    def test_a_single_story_when_nothing_else_fits(self):
        plan = wf_core.plan_set({9: node(effort='High'), 1: node(effort='Medium')},
                                [9, 1])
        self.assertEqual(chosen(plan), [9])

    def test_the_budget_never_keeps_a_dependent_without_its_blocker(self):
        universe = {1: node(effort='Medium'), 2: node([1], effort='Medium'),
                    3: node([2], effort='Medium'), 4: node(effort='Low'),
                    5: node(effort='High')}
        for rank in itertools.permutations([1, 2, 3, 4, 5]):
            plan = wf_core.plan_set(universe, list(rank))
            taken = set(chosen(plan))
            self.assertLessEqual(plan['weight'], wf_core.BULK_BUDGET)
            for n in taken:
                self.assertTrue(set(universe[n]['blockers']) <= taken,
                                (rank, sorted(taken)))


class TestReleasableBlocked(unittest.TestCase):
    """3. A Blocked issue whose edges have all closed is ready in this round."""

    def test_it_is_in_the_pool_and_named_releasable(self):
        verdict = judge([issue(1, stage='Blocked', edges=[edge(9, 'CLOSED')])])
        self.assertIn(1, verdict['releasable'])
        self.assertIn(1, pool_numbers(verdict))

    def test_blocked_with_no_edge_is_not_releasable(self):
        verdict = judge([issue(1, stage='Blocked')])
        self.assertNotIn(1, verdict['releasable'])
        self.assertEqual(pool_numbers(verdict), [])

    def test_the_pick_writes_blocks_and_releases_in_one_call(self):
        by_num = {1: issue(1, stage='Blocked', edges=[edge(9, 'CLOSED')]), 3: issue(3)}
        side_effects = []
        with mock.patch.object(wf, 'claimed_issue_numbers', return_value=set()), \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, ids=None:
                                  {n: (True, '') for n in wanted}) as stages, \
                mock.patch.object(wf, 'add_comments',
                                  return_value={1: (True, 'commented')}) as comments:
            wf.block_in_pool(CFG, {3: [9]}, side_effects, [1], by_num)
        stages.assert_called_once_with(CFG, {3: 'Blocked', 1: 'Backlog'},
                                       {3: 'I_3', 1: 'I_1'})
        comments.assert_called_once()
        self.assertEqual(sorted(comments.call_args[0][0]), [1])
        actions = {e['issue']: e for e in side_effects}
        self.assertEqual(actions[1]['action'], 'released')
        self.assertTrue(actions[1]['commented'])
        self.assertEqual(actions[3]['action'], 'marked-blocked')


class TestUnknownEdges(unittest.TestCase):
    """4. An edge list the read did not finish is unknown, never empty."""

    def test_an_incomplete_read_has_no_known_blockers(self):
        self.assertIsNone(wf_core._open_blockers(issue(1, edges=[edge(2)], total=60)))
        self.assertEqual(wf_core._open_blockers(issue(1, edges=[edge(2, 'CLOSED')])), [])

    def test_the_plan_says_its_dependencies_could_not_be_read(self):
        plan = wf_core.plan_set({1: node(None)}, [1], seeds=[1])
        self.assertEqual(chosen(plan), [])
        self.assertIn('could not all be read', reasons(plan)[1])


class TestClaimRecheck(unittest.TestCase):
    """5. A claim taken after the pool read keeps its `Stage`."""

    def test_an_issue_claimed_in_between_is_not_written(self):
        side_effects = []
        with mock.patch.object(wf, 'claimed_issue_numbers', return_value={3}) as claims, \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, ids=None:
                                  {n: (True, '') for n in wanted}) as stages:
            wf.block_in_pool(CFG, {3: [9], 4: [9]}, side_effects,
                             by_num={3: issue(3), 4: issue(4)})
        claims.assert_called_once_with()
        self.assertEqual(stages.call_args[0][1], {4: 'Blocked'})
        entry = next(e for e in side_effects if e['issue'] == 3)
        self.assertFalse(entry['stage_set'])
        self.assertIn('claimed by another run', entry['stage_message'])


class TestEdgeTotals(unittest.TestCase):
    """6. Every edge read asks how many edges there are."""

    def test_the_reads_ask_for_the_total(self):
        self.assertIn('blockedBy(first:20){ totalCount', wf.BLOCKED_SELECTION)
        self.assertIn('blockedBy(first:50){ totalCount', wf.ISSUE_SELECTION)

    def _scan(self, blocked):
        with mock.patch.object(wf, 'blocked_issues', return_value=(blocked, None)), \
                mock.patch.object(wf, 'load_issue_facets',
                                  return_value={'ownership': {i['number']: 'Code agent'
                                                              for i in blocked},
                                                'types': {}}), \
                mock.patch.object(wf, 'blocker_deliveries', return_value={}), \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, ids=None:
                                  {n: (True, '') for n in wanted}) as stages, \
                mock.patch.object(wf, 'add_comments',
                                  side_effect=lambda c: {n: (True, '') for n in c}) as comments:
            return wf.unblock_scan(CFG), stages, comments

    def test_the_sweep_holds_an_issue_whose_edges_ran_past_the_read(self):
        report, stages, _ = self._scan(
            [issue(7, stage='Blocked', edges=[edge(1, 'CLOSED')], total=25)])
        self.assertEqual(report['released'], [])
        self.assertEqual(report['held'][0]['edges_unread'], 24)
        stages.assert_not_called()

    def test_issue_apply_changes_no_edge_on_a_partial_read(self):
        result = {'errors': [], 'number': 7, 'issue_id': 'I_7',
                  'issue': {'blockedBy': {'totalCount': 60, 'nodes': [edge(3)]}}}
        with mock.patch.object(wf, 'send_link_batch') as batch, \
                mock.patch.object(wf, 'resolve_issue_ids', return_value={}):
            wf.link_phase(CFG, [{'entry': {'blocked_by': [4]}}], [result], {}, {4: 'I_4'})
        batch.assert_not_called()
        self.assertIn('no edge was changed', ' '.join(result['errors']))

    def test_several_releases_cost_one_stage_write_and_one_comment_write(self):
        report, stages, comments = self._scan(
            [issue(n, stage='Blocked', edges=[edge(1, 'CLOSED')]) for n in (7, 8, 9)])
        self.assertEqual([r['issue'] for r in report['released']], [7, 8, 9])
        stages.assert_called_once()
        self.assertEqual(stages.call_args[0][2], {7: 'I_7', 8: 'I_8', 9: 'I_9'})
        comments.assert_called_once()
        self.assertTrue(all(r['commented'] for r in report['released']))


class TestSpecCycleReferences(unittest.TestCase):
    """8. A cycle is found however each side spells the other."""

    def test_a_number_and_a_digit_string_meet(self):
        entries = [{'number': 12, 'blocked_by': ['a']},
                   {'key': 'a', 'blocked_by': ['12']}]
        self.assertEqual(len(wf_core.spec_cycles(entries)), 1)

    def test_a_key_and_a_number_meet(self):
        entries = [{'key': 'a', 'number': 12, 'blocked_by': [13]},
                   {'number': 13, 'blocked_by': ['a']}]
        self.assertEqual(len(wf_core.spec_cycles(entries)), 1)


class TestHeldPrerequisites(unittest.TestCase):
    """9. `--mode` and `--max-effort` never hold back a prerequisite a code
    agent may build."""

    def _issues(self):
        return [issue(1, 'Bug', edges=[edge(2)]), issue(2, 'User Story')]

    def test_auto_pick_admits_the_prerequisite(self):
        verdict = judge(self._issues(), mode='maintenance')
        self.assertIn(2, pool_numbers(verdict))
        self.assertNotIn(2, verdict['excluded'])

    def test_the_plan_universe_carries_it(self):
        issues = self._issues()
        verdict = judge(issues, mode='maintenance')
        universe, _rank, _reasons = wf_core.plan_universe(verdict, issues, set())
        self.assertIn(2, universe)
        plan = wf_core.plan_set(universe, [1, 2], seeds=[1])
        self.assertEqual(chosen(plan), [2, 1])

    def test_a_person_owned_or_assigned_prerequisite_still_excludes(self):
        for over in ({'ownership_map': {1: 'Code agent', 2: 'Human'}},
                     {'claimed': {2}}):
            with self.subTest(over=over):
                issues = self._issues()
                verdict = judge(issues, mode='maintenance', **over)
                self.assertNotIn(2, pool_numbers(verdict))
                universe, _rank, _reasons = wf_core.plan_universe(
                    verdict, issues, over.get('claimed') or set())
                self.assertNotIn(2, universe)
        issues = self._issues()
        issues[1]['assigned'] = True
        self.assertNotIn(2, pool_numbers(judge(issues, mode='maintenance')))


class TestWavesAreOrderIndependent(unittest.TestCase):
    """11. The waves are levels of the graph, not of the input order."""

    def test_every_order_gives_the_same_waves(self):
        stories = [{'number': 1, 'blocked_by': []}, {'number': 2, 'blocked_by': [1]},
                   {'number': 3, 'blocked_by': [2]}, {'number': 4, 'blocked_by': [1]}]
        expected = [[1], [2, 4], [3]]
        for order in itertools.permutations(stories):
            waves = wf_core.dependency_waves(list(order))
            self.assertEqual([sorted(w) for w in waves], expected)


class TestWithinAContainer(unittest.TestCase):
    """12. `within` limits the set, except for a member's own prerequisite."""

    def test_a_prerequisite_outside_is_taken_and_a_relative_outside_is_not(self):
        universe = {1: node([3], parent=50), 2: node(parent=50), 3: node(parent=60),
                    4: node(parent=50)}
        plan = wf_core.plan_set(universe, [1, 2, 3, 4], within={1, 2})
        self.assertEqual(sorted(chosen(plan)), [1, 2, 3])
        self.assertLess(chosen(plan).index(3), chosen(plan).index(1))

    def test_choose_parent_set_is_gone(self):
        self.assertFalse(hasattr(wf_core, 'choose_parent_set'))


if __name__ == '__main__':
    unittest.main()
