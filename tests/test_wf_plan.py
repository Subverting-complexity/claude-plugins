#!/usr/bin/env python3
"""`wf plan-set`, `wf drop-story`, `wf bulk-mark`, and `pick --issue` on a
story that waits on another, driven through the CLI with every GitHub and git
seam stubbed.

The rule under test throughout: a dependency decides the build order, never
whether a story belongs. A blocker and the story behind it are both taken, the
blocker first.
"""

import contextlib
import io
import json
import os
import shutil
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

CLEAR = ('## Summary\n\nChange the thing the story names.\n\n'
         '## Acceptance criteria\n\n- [ ] The thing is changed.\n')

CFG = {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
       'branch_convention': 'feature/{number}/{short-desc}', 'labels': {},
       'review_labels': {}, 'fields': {}, 'type_capable': True}


def issue(number, stage=None, blockers=(), parent=None, assigned=False):
    return {'id': 'I_%d' % number, 'number': number, 'title': 'story %d' % number,
            'body': CLEAR, 'labels': [], 'milestone': None, 'url': '',
            'stage': stage, 'assigned': assigned,
            'assignees': ['someone'] if assigned else [], 'type': 'User Story',
            'parent': parent, 'sub_issues': {'total': 0, 'open': []},
            'blockedBy': {'totalCount': len(blockers),
                          'nodes': [{'number': b, 'state': 'OPEN'} for b in blockers]},
            'open_prs': [], 'merged_prs': [], 'prs_complete': True}


def facets(issues, priority):
    return {'types': {i['number']: 'User Story' for i in issues},
            'priority': priority, 'classification': {}, 'effort': {}, 'stage': {},
            'ownership': {i['number']: 'Code agent' for i in issues}}


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


class Harness(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        for name, value in (('prepare_cfg', dict(CFG)),
                            ('check_environment', None),
                            ('load_config', (True, dict(CFG), '')),
                            ('repo_root', self.root),
                            # A write re-lists the claim refs first; the pool
                            # fixture says who holds one.
                            ('claimed_issue_numbers', set())):
            patch = mock.patch.object(wf, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    @contextlib.contextmanager
    def pool(self, issues, priority, claimed=()):
        with mock.patch.object(wf, 'read_pool',
                               return_value=(True, issues, '', set(claimed))), \
                mock.patch.object(wf, 'load_issue_facets',
                                  return_value=facets(issues, priority)):
            yield

    def bulk_set(self):
        with open(os.path.join(self.root, '.claude', 'bulk-set.json'),
                  encoding='utf-8') as fh:
            return json.load(fh)


class TestPlanSet(Harness):

    def test_a_blocker_and_the_urgent_story_behind_it_are_one_set(self):
        issues = [issue(1), issue(2, stage='Blocked', blockers=[1]), issue(3)]
        with self.pool(issues, {1: 'Low', 2: 'Urgent', 3: 'High'}):
            code, payload = capture(['plan-set'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertFalse(payload['claimed'])
        # #3 is High and #1 carries #2's Urgent: one level apart, so all three
        # fit a budget of 7 (unestimated stories cost Medium).
        self.assertEqual([s['number'] for s in payload['stories']], [1, 2, 3])
        self.assertEqual(payload['groups'][0]['waves'], [[1, 3], [2]])
        self.assertEqual(payload['stories'][1]['blocked_by'], [1])
        self.assertEqual((payload['weight'], payload['budget']), (6, 7))

    def test_naming_the_dependent_brings_its_prerequisite(self):
        issues = [issue(1), issue(2, stage='Blocked', blockers=[1]), issue(3)]
        with self.pool(issues, {}):
            code, payload = capture(['plan-set', '--issue', '2'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([s['number'] for s in payload['stories']], [1, 2])
        self.assertEqual(payload['stories'][0]['why'], 'prerequisite of #2')

    def test_a_blocker_somebody_else_holds_excludes_the_named_story(self):
        issues = [issue(9, assigned=True), issue(2, stage='Blocked', blockers=[9])]
        with self.pool(issues, {}):
            code, payload = capture(['plan-set', '--issue', '2'])
        self.assertEqual(code, wf.EXIT_NO_CANDIDATES)
        self.assertIn('#9', payload['excluded'][0]['reason'])
        self.assertIn('assigned', payload['excluded'][0]['reason'])

    def test_size_is_gone_and_max_groups_is_one_or_two(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in (['plan-set', '--size', '3'], ['plan-set', '--max-groups', '3']):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    wf.build_parser().parse_args(argv)
        self.assertEqual(wf.build_parser().parse_args(['plan-set']).max_groups, 2)

    def test_a_bug_and_a_story_become_two_groups_or_one_with_max_groups_1(self):
        issues = [issue(1), issue(2)]
        issues[0]['type'] = 'Bug'
        the_facets = facets(issues, {})
        the_facets['types'][1] = 'Bug'
        for argv, expected in (([], [[1], [2]]), (['--max-groups', '1'], [[1]])):
            with self.subTest(argv=argv), \
                    mock.patch.object(wf, 'read_pool', return_value=(True, issues, '', set())), \
                    mock.patch.object(wf, 'load_issue_facets', return_value=the_facets):
                code, payload = capture(['plan-set'] + argv)
            self.assertEqual(code, wf.EXIT_OK)
            self.assertEqual([g['stories'] for g in payload['groups']], expected)

    def _claim(self, issues, outcomes):
        mutation = json.dumps({'data': {'a%d' % i['number']: {'assignable': {'id': i['id']}}
                                        for i in issues}})
        with self.pool(issues, {}), \
                mock.patch.object(wf, 'acquire_claim',
                                  side_effect=lambda target: outcomes[target]), \
                mock.patch.object(wf, 'release_claims',
                                  side_effect=lambda t: {x: True for x in t}) as release, \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, ids=None:
                                  {n: (True, 'Stage set') for n in wanted}) as stages, \
                mock.patch.object(wf, 'gh_graphql',
                                  return_value=(True, {'viewer': {'id': 'U_1'}}, '')), \
                mock.patch.object(wf, '_graphql_json', return_value=(0, mutation, '')):
            code, payload = capture(['plan-set', '--claim'])
        return code, payload, release, stages

    def test_claiming_records_the_set_and_writes_every_stage_in_one_call(self):
        issues = [issue(1), issue(2, stage='Blocked', blockers=[1])]
        code, payload, _, stages = self._claim(
            issues, {'issue-1': 'won', 'issue-2': 'won'})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertTrue(payload['claimed'])
        self.assertTrue(all(s['assigned'] and s['stage_set'] for s in payload['stories']))
        stages.assert_called_once()
        self.assertEqual(sorted(stages.call_args[0][1]), [1, 2])
        record = self.bulk_set()
        self.assertEqual([(g['group'], g['branch'], g['waves']) for g in record['groups']],
                         [(1, None, [[1], [2]])])
        self.assertEqual([s['group'] for s in record['stories']], [1, 1])
        self.assertNotIn('waves', record)
        self.assertEqual([s['built'] for s in record['stories']], [False, False])

    def test_a_lost_blocker_takes_its_dependent_out_and_releases_it(self):
        issues = [issue(1), issue(2, stage='Blocked', blockers=[1])]
        code, payload, release, _ = self._claim(
            issues, {'issue-1': 'lost', 'issue-2': 'won'})
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        reasons = {d['number']: d['reason'] for d in payload['dropped']}
        self.assertIn('another run', reasons[1])
        self.assertIn('#1', reasons[2])
        release.assert_called_once_with(['issue-2'])


class TestSelectionAcrossFilters(Harness):
    """What `--mode` and a closed blocker do to a plan."""

    def _plan(self, issues, the_facets, argv):
        with mock.patch.object(wf, 'read_pool', return_value=(True, issues, '', set())), \
                mock.patch.object(wf, 'load_issue_facets', return_value=the_facets):
            return capture(['plan-set'] + list(argv))

    def test_a_prerequisite_the_mode_holds_back_is_still_taken(self):
        """`--mode` chooses which work to start, not what that work needs. The
        prerequisite is maintenance work, so it is its own pull request, built
        first."""
        issues = [issue(1), issue(2, blockers=[1])]
        issues[0]['type'] = 'Bug'
        the_facets = facets(issues, {})
        the_facets['types'][1] = 'Bug'
        code, payload = self._plan(issues, the_facets, ['--mode', 'feature'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([s['number'] for s in payload['stories']], [1, 2])
        self.assertEqual([(g['mode'], g['stories']) for g in payload['groups']],
                         [('maintenance', [1]), ('feature', [2])])

    def test_a_prerequisite_a_person_owns_still_excludes(self):
        issues = [issue(1), issue(2, blockers=[1])]
        issues[0]['type'] = 'Bug'
        the_facets = facets(issues, {})
        the_facets['types'][1] = 'Bug'
        the_facets['ownership'][1] = 'Human'
        code, payload = self._plan(issues, the_facets, ['--mode', 'feature', '--issue', '2'])
        self.assertEqual(code, wf.EXIT_NO_CANDIDATES)
        self.assertIn('#1', payload['excluded'][0]['reason'])

    def test_a_blocked_story_whose_edges_all_closed_is_released_and_reported(self):
        freed = issue(5, stage='Blocked')
        freed['blockedBy'] = {'totalCount': 1, 'nodes': [{'number': 8, 'state': 'CLOSED'}]}
        issues = [freed]
        code, payload = self._plan(issues, facets(issues, {}), [])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['released'],
                         [{'number': 5, 'title': 'story 5', 'closed_blockers': [8]}])
        self.assertEqual([s['number'] for s in payload['stories']], [5])

    def test_a_story_under_a_maintenance_feature_is_its_own_group_in_story_mode(self):
        feature = issue(40)
        feature.update(type='Feature', sub_issues={'total': 1, 'open': [1]})
        issues = [feature, issue(1, parent=40), issue(2)]
        the_facets = facets(issues, {})
        the_facets['types'][40] = 'Feature'
        the_facets['classification'] = {40: ['Tech Debt']}
        code, payload = self._plan(issues, the_facets, [])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(sorted((g['mode'], tuple(g['stories'])) for g in payload['groups']),
                         [('feature', (2,)), ('maintenance', (1,))])

    def test_unlinked_stories_fill_the_budget_and_nothing_is_left_to_judge(self):
        issues = [issue(1, parent=40), issue(2, parent=40), issue(3),
                  issue(4, blockers=[9]), issue(9, assigned=True)]
        the_facets = facets(issues, {})
        the_facets['effort'] = {1: 'Medium', 2: 'Medium', 3: 'Medium'}
        code, payload = self._plan(issues, the_facets, [])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([s['number'] for s in payload['stories']], [1, 2, 3])
        self.assertNotIn('nearby', payload)


class TestDropAndMark(Harness):

    def write(self, stories):
        os.makedirs(os.path.join(self.root, '.claude'), exist_ok=True)
        with open(os.path.join(self.root, '.claude', 'bulk-set.json'), 'w',
                  encoding='utf-8') as fh:
            json.dump({'lead': 1, 'mode': 'story',
                       'groups': [{'group': g, 'branch': None,
                                   'waves': wf_core.dependency_waves(
                                       [s for s in stories if s.get('group', 1) == g])}
                                  for g in sorted({s.get('group', 1) for s in stories})],
                       'stories': stories, 'dropped': []}, fh)

    def write_legacy(self, stories):
        os.makedirs(os.path.join(self.root, '.claude'), exist_ok=True)
        with open(os.path.join(self.root, '.claude', 'bulk-set.json'), 'w',
                  encoding='utf-8') as fh:
            json.dump({'lead': 1, 'mode': 'story', 'branch': 'feature/1/old',
                       'waves': wf_core.dependency_waves(stories),
                       'stories': stories, 'dropped': []}, fh)

    def test_dropping_a_blocker_drops_what_waits_on_it(self):
        self.write([{'number': 1, 'title': 'a', 'id': 'I_1', 'blocked_by': [], 'built': False},
                    {'number': 2, 'title': 'b', 'id': 'I_2', 'blocked_by': [1], 'built': False},
                    {'number': 3, 'title': 'c', 'id': 'I_3', 'blocked_by': [], 'built': False}])
        answer = json.dumps({'data': dict(
            {'u%d' % n: {'assignable': {'id': 'I_%d' % n}} for n in (1, 2)},
            **{'c%d' % n: {'subject': {'id': 'I_%d' % n}} for n in (1, 2)})})
        with mock.patch.object(wf, 'release_claims',
                               side_effect=lambda t: {x: True for x in t}), \
                mock.patch.object(wf, 'run', return_value=(0, '', '')) as run, \
                mock.patch.object(wf, 'gh_graphql',
                                  return_value=(True, {'viewer': {'id': 'U_1'}}, '')), \
                mock.patch.object(wf, '_graphql_json',
                                  return_value=(0, answer, '')) as mutation, \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, ids=None:
                                  {n: (True, '') for n in wanted}) as stages:
            code, payload = capture(['drop-story', '--issue', '1', '--reason', 'too big'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['remaining'], [3])
        self.assertEqual(stages.call_args[0][1],
                         {1: wf_core.STAGE_NAMES['stage-backlog'],
                          2: wf_core.STAGE_NAMES['stage-blocked']})
        self.assertEqual(stages.call_args[0][2], {1: 'I_1', 2: 'I_2'})
        self.assertEqual([d['number'] for d in self.bulk_set()['dropped']], [1, 2])
        # Both stories unassigned and told why in one mutation, not a
        # `gh issue edit` and a `gh issue comment` each.
        mutation.assert_called_once()
        query = mutation.call_args[0][0]
        self.assertEqual(query.count('removeAssigneesFromAssignable'), 2)
        self.assertEqual(query.count('addComment'), 2)
        run.assert_not_called()
        self.assertTrue(all(d['unassigned'] and d['commented'] for d in payload['dropped']))

    def test_a_built_story_is_never_dropped(self):
        self.write([{'number': 1, 'title': 'a', 'blocked_by': [], 'built': True}])
        code, payload = capture(['drop-story', '--issue', '1', '--reason', 'x'])
        self.assertEqual(code, wf.EXIT_USAGE)
        self.assertIn('already built', payload['reason'])

    def test_bulk_mark_records_the_branch_and_what_is_built(self):
        self.write([{'number': 1, 'title': 'a', 'blocked_by': [], 'built': False},
                    {'number': 2, 'title': 'b', 'blocked_by': [1], 'built': False}])
        code, payload = capture(['bulk-mark', '--branch', 'feature/1/x', '--built', '1'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['built'], [1])
        self.assertEqual(payload['unbuilt'], [2])
        self.assertEqual(self.bulk_set()['groups'][0]['branch'], 'feature/1/x')

    def test_bulk_mark_records_each_groups_branch_on_its_own(self):
        self.write([{'number': 1, 'title': 'a', 'blocked_by': [], 'built': False, 'group': 1},
                    {'number': 2, 'title': 'b', 'blocked_by': [], 'built': False, 'group': 2}])
        capture(['bulk-mark', '--branch', 'feature/1/x', '--built', '1'])
        code, payload = capture(['bulk-mark', '--group', '2', '--branch', 'feature/2/y'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual((payload['built'], payload['unbuilt']), ([], [2]))
        self.assertEqual([g['branch'] for g in self.bulk_set()['groups']],
                         ['feature/1/x', 'feature/2/y'])
        code, payload = capture(['bulk-mark', '--group', '3', '--branch', 'z'])
        self.assertEqual(code, wf.EXIT_USAGE)

    def test_a_record_from_before_groups_is_read_as_one_group(self):
        self.write_legacy([{'number': 1, 'title': 'a', 'blocked_by': [], 'built': False}])
        code, payload = capture(['bulk-mark', '--built', '1'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['branch'], 'feature/1/old')
        self.assertEqual(self.bulk_set()['groups'][0]['branch'], 'feature/1/old')

    def _drop_group(self, stories, group):
        self.write(stories)
        numbers = [s['number'] for s in stories]
        answer = json.dumps({'data': dict(
            {'u%d' % n: {'assignable': {'id': 'I_%d' % n}} for n in numbers},
            **{'c%d' % n: {'subject': {'id': 'I_%d' % n}} for n in numbers})})
        with mock.patch.object(wf, 'release_claims',
                               side_effect=lambda t: {x: True for x in t}), \
                mock.patch.object(wf, 'gh_graphql',
                                  return_value=(True, {'viewer': {'id': 'U_1'}}, '')), \
                mock.patch.object(wf, '_graphql_json', return_value=(0, answer, '')), \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, ids=None:
                                  {n: (True, '') for n in wanted}):
            return capture(['drop-group', '--group', str(group), '--reason', 'inline review'])

    def test_drop_group_returns_a_whole_unbuilt_group_and_keeps_the_numbers(self):
        code, payload = self._drop_group(
            [{'number': 1, 'title': 'a', 'id': 'I_1', 'blocked_by': [], 'built': True, 'group': 1},
             {'number': 2, 'title': 'b', 'id': 'I_2', 'blocked_by': [], 'built': False, 'group': 2},
             {'number': 3, 'title': 'c', 'id': 'I_3', 'blocked_by': [2], 'built': False,
              'group': 2}], 2)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['remaining'], [1])
        self.assertEqual(sorted(d['number'] for d in payload['dropped']), [2, 3])
        self.assertEqual([(g['group'], g['waves']) for g in self.bulk_set()['groups']],
                         [(1, [[1]]), (2, [])])

    def test_drop_group_refuses_a_group_with_anything_built(self):
        code, payload = self._drop_group(
            [{'number': 1, 'title': 'a', 'id': 'I_1', 'blocked_by': [], 'built': True, 'group': 1}],
            1)
        self.assertEqual(code, wf.EXIT_USAGE)
        self.assertIn('#1', payload['reason'])


class TestPickBuildsThePrerequisite(Harness):

    def _pick(self, issues, requested):
        with self.pool(issues, {}), \
                mock.patch.object(wf, 'fetch_issue_candidate', return_value=requested), \
                mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'apply_in_progress'), \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, *a, **k:
                                  {n: (True, '') for n in wanted}):
            return capture(['pick', '--issue', str(requested['number'])])

    def test_a_named_story_waiting_on_takeable_work_claims_that_work_first(self):
        issues = [issue(1), issue(2, blockers=[1])]
        code, payload = self._pick(issues, issue(2, blockers=[1]))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['number'], 1)
        self.assertEqual(payload['prerequisite_for']['number'], 2)
        self.assertEqual(payload['prerequisite_for']['build_order'], [1, 2])
        self.assertEqual([u['number'] for u in payload['unblocks']], [2])
        self.assertEqual(payload['side_effects'][0]['action'], 'marked-blocked')

    def test_a_three_link_chain_through_a_bug_redirects_to_its_first_link(self):
        """A story waiting on a bug that waits on another story: the pick
        claims the first link and reports the whole order. `prerequisite_pick`
        plans with no budget and no work modes, so the cross-mode case itself
        is `test_no_budget_orders_a_chain_that_crosses_modes_both_ways` in
        `test_dependency_plan.py`."""
        issues = [issue(10, blockers=[20]), issue(20, blockers=[30]), issue(30)]
        issues[1]['type'] = 'Bug'
        the_facets = facets(issues, {})
        the_facets['types'][20] = 'Bug'
        with mock.patch.object(wf, 'read_pool', return_value=(True, issues, '', set())), \
                mock.patch.object(wf, 'load_issue_facets', return_value=the_facets), \
                mock.patch.object(wf, 'fetch_issue_candidate',
                                  return_value=issue(10, blockers=[20])), \
                mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'apply_in_progress'), \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, *a, **k:
                                  {n: (True, '') for n in wanted}):
            code, payload = capture(['pick', '--issue', '10'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['number'], 30)
        self.assertEqual(payload['prerequisite_for']['build_order'], [30, 20, 10])

    def test_a_named_parked_story_keeps_its_stage(self):
        """Only a blank or Backlog story is set to Blocked: Parked is a hold
        a person put on it, and building its prerequisite does not lift it."""
        issues = [issue(1), issue(2, stage='Parked', blockers=[1])]
        with self.pool(issues, {}), \
                mock.patch.object(wf, 'fetch_issue_candidate',
                                  return_value=issue(2, stage='Parked', blockers=[1])), \
                mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'apply_in_progress'), \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, *a, **k:
                                  {n: (True, '') for n in wanted}) as stages:
            code, payload = capture(['pick', '--issue', '2'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['number'], 1)
        for call in stages.call_args_list:
            self.assertNotIn(2, call[0][1])
        self.assertNotIn('marked-blocked',
                         [e['action'] for e in payload.get('side_effects') or ()])

    def test_a_named_story_whose_prerequisite_the_mode_holds_back_builds_it(self):
        issues = [issue(1), issue(2, blockers=[1])]
        issues[0]['type'] = 'Bug'
        the_facets = facets(issues, {})
        the_facets['types'][1] = 'Bug'
        with mock.patch.object(wf, 'read_pool', return_value=(True, issues, '', set())), \
                mock.patch.object(wf, 'load_issue_facets', return_value=the_facets), \
                mock.patch.object(wf, 'fetch_issue_candidate',
                                  return_value=issue(2, blockers=[1])), \
                mock.patch.object(wf, 'acquire_claim', return_value='won'), \
                mock.patch.object(wf, 'apply_in_progress'), \
                mock.patch.object(wf, 'set_stages',
                                  side_effect=lambda cfg, wanted, *a, **k:
                                  {n: (True, '') for n in wanted}):
            code, payload = capture(['pick', '--issue', '2', '--mode', 'feature'])
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['number'], 1)

    def test_a_blocker_nobody_here_may_build_ends_the_pick_with_why(self):
        issues = [issue(9, assigned=True), issue(2, stage='Blocked', blockers=[9])]
        code, payload = self._pick(issues, issue(2, blockers=[9]))
        self.assertEqual(code, wf.EXIT_ALL_BLOCKED)
        self.assertIn('#9', payload['reason'])
        self.assertIn('assigned', payload['reason'])


if __name__ == '__main__':
    unittest.main()
