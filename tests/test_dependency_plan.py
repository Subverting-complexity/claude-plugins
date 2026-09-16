#!/usr/bin/env python3
"""Dependency-aware selection: `plan_set`, `dependency_waves` and the
priority a blocker inherits in `evaluate_pool`.

A dependency decides where a story goes in the build order, never whether it
belongs in the set. Only a blocker the run cannot build takes a story out.
"""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
import wf_core  # noqa: E402

CLEAR = ('## Summary\n\nChange the thing the story names.\n\n'
         '## Acceptance criteria\n\n- [ ] The thing is changed.\n')


def story(blockers=(), parent=None):
    return {'blockers': list(blockers), 'parent': parent}


def numbers(plan):
    return [s['number'] for s in plan['selected']]


class TestPlanSetNamed(unittest.TestCase):

    def test_a_blocker_and_its_dependent_are_both_kept_blocker_first(self):
        universe = {1: story(), 2: story([1])}
        plan = wf_core.plan_set(universe, [2, 1], seeds=[2, 1])
        self.assertEqual(numbers(plan), [1, 2])
        self.assertEqual(plan['waves'], [[1], [2]])
        self.assertEqual(plan['excluded'], [])

    def test_a_named_dependent_pulls_in_an_unnamed_prerequisite(self):
        universe = {1: story(), 2: story([1]), 3: story()}
        plan = wf_core.plan_set(universe, [1, 2, 3], seeds=[2])
        self.assertEqual(numbers(plan), [1, 2])
        self.assertEqual(plan['selected'][0]['why'], 'prerequisite of #2')

    def test_independent_stories_share_a_wave(self):
        universe = {1: story(), 2: story(), 3: story([1, 2])}
        plan = wf_core.plan_set(universe, [1, 2, 3], seeds=[1, 2, 3])
        self.assertEqual(plan['waves'], [[1, 2], [3]])
        self.assertEqual(plan['selected'][2]['blocked_by'], [1, 2])
        self.assertEqual(plan['selected'][0]['unblocks'], [3])

    def test_a_chain_of_three_runs_in_series(self):
        universe = {1: story(), 2: story([1]), 3: story([2])}
        plan = wf_core.plan_set(universe, [3, 2, 1], seeds=[3])
        self.assertEqual(numbers(plan), [1, 2, 3])
        self.assertEqual(plan['waves'], [[1], [2], [3]])

    def test_a_blocker_the_run_cannot_build_excludes_the_story_with_why(self):
        universe = {2: story([9])}
        plan = wf_core.plan_set(universe, [2], seeds=[2],
                                reasons={9: 'owned by Human, not the code agent'})
        self.assertEqual(numbers(plan), [])
        self.assertIn('#9', plan['excluded'][0]['reason'])
        self.assertIn('Human', plan['excluded'][0]['reason'])

    def test_unreadable_edges_are_never_read_as_no_blockers(self):
        plan = wf_core.plan_set({2: {'blockers': None}}, [2], seeds=[2])
        self.assertEqual(numbers(plan), [])
        self.assertIn('could not all be read', plan['excluded'][0]['reason'])

    def test_a_cycle_is_excluded_rather_than_ordered_by_guess(self):
        universe = {1: story([2]), 2: story([1])}
        plan = wf_core.plan_set(universe, [1, 2], seeds=[1, 2])
        self.assertEqual(numbers(plan), [])
        self.assertIn('cycle', plan['excluded'][0]['reason'])

    def test_unrelated_named_stories_are_kept_and_flagged(self):
        universe = {1: story(), 2: story()}
        plan = wf_core.plan_set(universe, [1, 2], seeds=[1, 2])
        self.assertEqual(numbers(plan), [1, 2])
        self.assertTrue(plan['unrelated'])
        self.assertEqual(plan['components'], [[1], [2]])

    def test_shared_parent_or_prerequisite_is_one_group(self):
        universe = {1: story(parent=50), 2: story(parent=50),
                    3: story([9]), 4: story([9]), 9: story()}
        plan = wf_core.plan_set(universe, [1, 2], seeds=[1, 2])
        self.assertFalse(plan['unrelated'])
        plan = wf_core.plan_set(universe, [9, 3, 4], seeds=[3, 4])
        self.assertEqual(numbers(plan), [9, 3, 4])
        self.assertFalse(plan['unrelated'])

    def test_the_cap_keeps_a_named_story_with_its_prerequisites_or_not_at_all(self):
        universe = {1: story(), 2: story(), 3: story([1, 2])}
        plan = wf_core.plan_set(universe, [1, 2, 3], seeds=[1, 3], max_size=2)
        self.assertEqual(numbers(plan), [1])
        self.assertIn('size cap', plan['excluded'][0]['reason'])

    def test_seven_stories_fit_the_default_cap(self):
        universe = {n: story([n - 1] if n > 1 else []) for n in range(1, 8)}
        plan = wf_core.plan_set(universe, list(range(1, 8)), seeds=[7])
        self.assertEqual(numbers(plan), list(range(1, 8)))
        self.assertEqual(wf_core.BULK_MAX, 7)


class TestPlanSetOpen(unittest.TestCase):

    def test_a_high_priority_waiting_story_leads_and_brings_its_blocker(self):
        # #5 is urgent and waits on #8, which is low priority. Neither is
        # passed over: #8 is built first, then #5.
        universe = {5: story([8]), 8: story(), 3: story()}
        plan = wf_core.plan_set(universe, [5, 3, 8])
        self.assertEqual(numbers(plan), [8, 5])
        self.assertEqual(plan['lead'], 8)
        whys = {s['number']: s['why'] for s in plan['selected']}
        self.assertEqual(whys[5], 'lead')
        self.assertEqual(whys[8], 'prerequisite of #5')

    def test_unconnected_stories_stay_out_of_an_open_set(self):
        universe = {1: story(parent=40), 2: story(parent=40), 3: story()}
        plan = wf_core.plan_set(universe, [1, 3, 2])
        self.assertEqual(numbers(plan), [1, 2])

    def test_a_story_whose_chain_is_too_long_does_not_lead(self):
        # #3's chain is three stories and the cap is two, so #3 cannot lead.
        # Its group still makes a set of two, which beats the unlinked #4.
        universe = {1: story(), 2: story([1]), 3: story([2]), 4: story()}
        plan = wf_core.plan_set(universe, [3, 4, 1, 2], max_size=2)
        self.assertNotIn(3, numbers(plan))
        self.assertEqual(numbers(plan), [1, 2])

    def test_an_empty_universe_is_an_empty_plan(self):
        plan = wf_core.plan_set({}, [])
        self.assertIsNone(plan['lead'])
        self.assertEqual(plan['selected'], [])


class TestDependencyWaves(unittest.TestCase):

    def test_diamond(self):
        stories = [{'number': 1, 'blocked_by': []},
                   {'number': 2, 'blocked_by': [1]},
                   {'number': 3, 'blocked_by': [1]},
                   {'number': 4, 'blocked_by': [2, 3]}]
        self.assertEqual(wf_core.dependency_waves(stories), [[1], [2, 3], [4]])

    def test_blockers_outside_the_set_are_ignored(self):
        self.assertEqual(wf_core.dependency_waves(
            [{'number': 1, 'blocked_by': [99]}]), [[1]])


def issue(number, stage=None, blockers=(), priority_type='User Story'):
    return {'number': number, 'title': 'issue %d' % number, 'body': CLEAR,
            'labels': [], 'milestone': None, 'url': '', 'stage': stage,
            'assigned': False, 'assignees': [], 'type': priority_type,
            'parent': None, 'sub_issues': {'total': 0, 'open': []},
            'blockedBy': {'totalCount': len(blockers),
                          'nodes': [{'number': b, 'state': 'OPEN'} for b in blockers]},
            'open_prs': []}


class TestBlockerInheritsPriority(unittest.TestCase):

    def judge(self, issues, priority):
        return wf_core.evaluate_pool(
            issues, priority_map=priority,
            ownership_map={i['number']: 'Code agent' for i in issues})

    def test_a_low_priority_blocker_of_urgent_work_is_picked_first(self):
        issues = [issue(1), issue(2), issue(3, blockers=[2])]
        verdict = self.judge(issues, {1: 'High', 2: 'Low', 3: 'Urgent'})
        self.assertEqual([e['number'] for e in verdict['pool']], [2, 1])
        self.assertEqual(verdict['pool'][0]['unblocks'], [3])
        self.assertEqual(verdict['pool'][0]['inherited_priority'], 'Urgent')
        self.assertEqual(verdict['waiting'], {3: [2]})

    def test_a_story_already_in_blocked_still_lends_its_priority(self):
        issues = [issue(1), issue(2), issue(3, stage='Blocked', blockers=[2])]
        verdict = self.judge(issues, {1: 'High', 2: 'Low', 3: 'Urgent'})
        self.assertEqual([e['number'] for e in verdict['pool']], [2, 1])

    def test_priority_passes_down_a_chain(self):
        issues = [issue(1), issue(2, blockers=[1]), issue(3, blockers=[2]), issue(4)]
        verdict = self.judge(issues, {1: 'Low', 2: 'Low', 3: 'Urgent', 4: 'High'})
        self.assertEqual([e['number'] for e in verdict['pool']], [1, 4])
        self.assertEqual(verdict['pool'][0]['unblocks'], [2, 3])

    def test_a_blocked_issue_with_no_open_edge_waits_on_a_person(self):
        issues = [issue(1), issue(3, stage='Blocked')]
        verdict = self.judge(issues, {1: 'Low', 3: 'Urgent'})
        self.assertEqual(verdict['waiting'], {})
        self.assertNotIn('unblocks', verdict['pool'][0])

    def test_nothing_changes_without_dependencies(self):
        issues = [issue(1), issue(2)]
        verdict = self.judge(issues, {1: 'Low', 2: 'High'})
        self.assertEqual([e['number'] for e in verdict['pool']], [2, 1])


if __name__ == '__main__':
    unittest.main()
