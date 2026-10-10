#!/usr/bin/env python3
"""
`wf area-backfill`: copy each issue's area epic to an area label (#389).

A repository that uses area epics has its areas only in the parent chain. The
command reads every issue, open and closed, resolves each to the area epic
above it, and adds the label the `epic` column of the `## Areas` table gives
that epic.

Two halves, both offline. The rules in `wf_core_backfill` are pure and are
tested with plain dicts. The command is run against `FakeRepo`, which stands
in for GitHub at the three seams the shell uses: `wf.gh_graphql` for the
reads, `wf._graphql_json` for the label writes and `wf.run` for closing an
epic. It keeps what a write leaves behind, so a second run sees what the
first one did.

Run standalone (`python3 tests/test_area_backfill.py`) or via `run-tests.sh`.
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

REPO = 'acme/widgets'
AREAS = [
    {'name': 'library', 'description': '', 'colour': '', 'epic': 1, 'was': None},
    {'name': 'listening', 'description': '', 'colour': '', 'epic': 2, 'was': None},
    {'name': 'new', 'description': '', 'colour': '', 'epic': None, 'was': None},
]
LABELS = ('area: library', 'area: listening', 'area: new', 'bug')


def _cfg(areas=AREAS):
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'labels': {}, 'review_labels': {}, 'fields': {},
            'areas': json.loads(json.dumps(areas)), 'release_targets': []}


def issue(number, parent=None, labels=(), state='OPEN', kind='User Story',
          stage=None, parent_repo=REPO, title=None):
    return {'number': number, 'id': 'I_%d' % number,
            'title': title or 'Issue %d' % number, 'state': state,
            'type': kind, 'stage': stage, 'parent': parent,
            'parent_repo': parent_repo, 'labels': list(labels)}


def area(number, state='OPEN', title=None):
    return issue(number, kind='Epic', stage='Area', state=state,
                 title=title or 'Area %d' % number)


def tree():
    """Two area epics. Library holds a feature, a story under it and a closed
    bug; Listening holds one story. #9 has no parent."""
    return [area(1, title='Library'), area(2, title='Listening'),
            issue(3, parent=1, kind='Feature'),
            issue(4, parent=3),
            issue(5, parent=1, kind='Bug', state='CLOSED'),
            issue(6, parent=2),
            issue(9, title='Loose end')]


class FakeRepo:
    """The issues and labels of one GitHub repository.

    `limit` is the largest page the issue read answers; a larger one gets
    RESOURCE_LIMITS_EXCEEDED, as GitHub gives a query too large for one
    request. `fail` holds the issue numbers whose label write is refused, and
    `fail_close` makes every `gh issue close` fail.
    """

    def __init__(self, issues, labels=LABELS, limit=100, fail=(),
                 fail_close=False, stuck=False):
        self.issues = {i['number']: i for i in issues}
        self.labels = {name: 'L_%d' % n for n, name in enumerate(labels)}
        self.limit = limit
        self.fail = set(fail)
        self.fail_close = fail_close
        self.stuck = stuck
        self.pages = []       # (size, after) of each issue read
        self.mutations = []   # the issue numbers of each label request
        self.closes = []      # the `gh issue close` commands

    def carried(self, number):
        return sorted(self.issues[number]['labels'])

    def _node(self, i):
        stage = ([{'field': {'name': 'Stage'}, 'name': i['stage']}]
                 if i['stage'] else [])
        parent = ({'number': i['parent'],
                   'repository': {'nameWithOwner': i['parent_repo']}}
                  if i['parent'] else None)
        return {'id': i['id'], 'number': i['number'], 'title': i['title'],
                'state': i['state'], 'issueType': {'name': i['type']},
                'parent': parent,
                'labels': {'nodes': [{'name': n} for n in i['labels']]},
                'issueFieldValues': {'nodes': stage}}

    def gh_graphql(self, query, **fields):
        if (fields['owner'], fields['repo']) != tuple(REPO.split('/')):
            raise AssertionError('wrong repository: %r' % (fields,))
        if 'issues(first' not in query:
            return True, {'repository': {'labels': {
                'nodes': [{'id': i, 'name': n} for n, i in self.labels.items()],
                'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}, ''
        if 'states:[OPEN,CLOSED]' not in query:
            raise AssertionError('the backfill must read closed issues too')
        size, after = fields['size'], fields.get('after')
        self.pages.append((size, after))
        if size > self.limit:
            return False, None, json.dumps(
                [{'type': 'RESOURCE_LIMITS_EXCEEDED', 'message': 'too large'}])
        numbers = sorted(self.issues)
        start = int(after or 0)
        more = start + size < len(numbers)
        cursor = after if self.stuck else str(start + size)
        return True, {'repository': {'issues': {
            'nodes': [self._node(self.issues[n])
                      for n in numbers[start:start + size]],
            'pageInfo': {'hasNextPage': more or self.stuck,
                         'endCursor': cursor if more or self.stuck else None},
        }}}, ''

    def graphql_json(self, query, variables):
        if 'addLabelsToLabelable' not in query:
            raise AssertionError('unexpected mutation: %s' % query)
        by_id = {i['id']: i for i in self.issues.values()}
        names = {v: k for k, v in self.labels.items()}
        aliases = sorted({k.rsplit('_', 1)[0] for k in variables},
                         key=lambda a: int(a[1:]))
        self.mutations.append([int(a[1:]) for a in aliases])
        data, errors = {}, []
        for alias in aliases:
            target = by_id[variables[alias + '_i']]
            if target['number'] in self.fail:
                data[alias] = None
                errors.append({'path': [alias], 'message': 'refused'})
                continue
            name = names[variables[alias + '_l']]
            if name not in target['labels']:
                target['labels'].append(name)
            data[alias] = {'labelable': {'__typename': 'Issue'}}
        out = {'data': data}
        if errors:
            out['errors'] = errors
        return (1 if errors else 0), json.dumps(out), ''

    def run(self, cmd, input_text=None):
        cmd = list(cmd)
        if cmd[:3] != ['gh', 'issue', 'close']:
            raise AssertionError('unexpected command: %r' % (cmd,))
        self.closes.append(cmd)
        if cmd[cmd.index('--repo') + 1] != REPO:
            raise AssertionError('wrong repository: %r' % (cmd,))
        if self.fail_close:
            return 1, '', 'could not close'
        self.issues[int(cmd[3])]['state'] = 'CLOSED'
        return 0, '', ''


def backfill(repo, *flags, cfg=None):
    """Run `wf area-backfill` against `repo`. Returns (code, payload)."""
    cfg = _cfg() if cfg is None else cfg
    args = wf.build_parser().parse_args(['area-backfill'] + list(flags))
    buf, code = io.StringIO(), None
    with mock.patch.object(wf, 'prepare_cfg', lambda: cfg), \
            mock.patch.object(wf, 'run', repo.run), \
            mock.patch.object(wf, 'gh_graphql', repo.gh_graphql), \
            mock.patch.object(wf, '_graphql_json', repo.graphql_json), \
            contextlib.redirect_stderr(io.StringIO()), \
            contextlib.redirect_stdout(buf):
        try:
            args.func(args)
        except SystemExit as exc:
            code = exc.code
    return code, json.loads(buf.getvalue())


# ── the rules ────────────────────────────────────────────────────────────────

def _index(issues):
    repo = FakeRepo(issues)
    return wf_core.backfill_index([repo._node(i) for i in issues], 'Stage', REPO)


class TestResolveAreaEpic(unittest.TestCase):

    def test_a_child_and_a_grandchild_reach_the_epic(self):
        index = _index(tree())
        self.assertEqual(wf_core.resolve_area_epic(3, index), (1, None))
        self.assertEqual(wf_core.resolve_area_epic(4, index), (1, None))
        self.assertEqual(wf_core.resolve_area_epic(6, index), (2, None))

    def test_an_issue_with_no_parent_has_no_area(self):
        epic, reason = wf_core.resolve_area_epic(9, _index(tree()))
        self.assertIsNone(epic)
        self.assertEqual(reason, wf_core.NO_AREA_NO_PARENT)

    def test_a_cycle_ends(self):
        index = _index([issue(3, parent=4), issue(4, parent=3)])
        self.assertEqual(wf_core.resolve_area_epic(3, index),
                         (None, wf_core.NO_AREA_CYCLE))

    def test_an_issue_that_is_its_own_parent_ends(self):
        index = _index([issue(3, parent=3)])
        self.assertEqual(wf_core.resolve_area_epic(3, index),
                         (None, wf_core.NO_AREA_CYCLE))

    def test_a_parent_in_another_repository_is_not_followed(self):
        # #1 is an area epic here, and the parent is #1 of another repository.
        index = _index([area(1), issue(3, parent=1, parent_repo='acme/other')])
        self.assertEqual(wf_core.resolve_area_epic(3, index),
                         (None, wf_core.NO_AREA_FOREIGN))

    def test_a_parent_the_read_did_not_return_is_not_guessed_at(self):
        index = _index([issue(3, parent=77)])
        self.assertEqual(wf_core.resolve_area_epic(3, index),
                         (None, wf_core.NO_AREA_UNREAD))

    def test_an_epic_that_is_not_an_area_is_walked_past(self):
        index = _index([area(1), issue(2, parent=1, kind='Epic', stage='Backlog'),
                        issue(3, parent=2)])
        self.assertEqual(wf_core.resolve_area_epic(3, index), (1, None))


class TestBackfillPlan(unittest.TestCase):

    def test_the_plan_names_each_issue_and_its_label(self):
        plan = wf_core.backfill_plan(_index(tree()), AREAS, LABELS)
        self.assertEqual(
            [(i['number'], i['label']) for i in plan['to_label']],
            [(3, 'area: library'), (4, 'area: library'), (5, 'area: library'),
             (6, 'area: listening')])
        self.assertEqual(plan['counts']['library'],
                         {'to_label': 3, 'already': 0, 'differs': 0, 'total': 3})
        self.assertEqual([i['number'] for i in plan['no_area']], [9])
        self.assertFalse(any(plan['stops'].values()))

    def test_an_area_epic_is_never_labelled_or_reported(self):
        plan = wf_core.backfill_plan(_index(tree()), AREAS, LABELS)
        listed = ([i['number'] for i in plan['to_label']] + plan['already']
                  + [i['number'] for i in plan['no_area']])
        self.assertNotIn(1, listed)
        self.assertNotIn(2, listed)

    def test_a_label_is_matched_without_case(self):
        plan = wf_core.backfill_plan(
            _index([area(1), issue(3, parent=1, labels=['AREA: Library'])]),
            AREAS[:1], ['Area: Library'])
        self.assertEqual(plan['already'], [3])
        self.assertEqual(plan['epics'][1]['label'], 'Area: Library')

    def test_two_rows_for_one_epic_stop_the_plan(self):
        rows = [dict(AREAS[0]), dict(AREAS[1], epic=1)]
        plan = wf_core.backfill_plan(_index([area(1)]), rows, LABELS)
        self.assertEqual(plan['stops']['duplicate_epic_rows'],
                         [{'epic': 1, 'areas': ['library', 'listening']}])

    def test_a_row_whose_epic_is_not_an_area_epic_stops_the_plan(self):
        plan = wf_core.backfill_plan(
            _index([area(1), issue(2, kind='Epic', stage='Backlog')]),
            AREAS, LABELS)
        self.assertEqual(plan['stops']['rows_without_area_epic'],
                         [{'area': 'listening', 'epic': 2}])

    def test_an_area_epic_a_merge_closed_and_set_to_done_is_still_copied(self):
        """`wf post-merge` closes an area epic whose sub-issues are all closed
        and writes `Done` over `Area`. The row still names it, so the move
        labels what sits under it."""
        plan = wf_core.backfill_plan(
            _index([issue(1, kind='Epic', stage='Done', state='CLOSED'),
                    issue(3, parent=1, state='CLOSED')]),
            AREAS[:1], LABELS)
        self.assertFalse(any(plan['stops'].values()))
        self.assertEqual([(i['number'], i['label']) for i in plan['to_label']],
                         [(3, 'area: library')])
        self.assertEqual(plan['no_area'], [])


# ── the command ──────────────────────────────────────────────────────────────

class TestAreaBackfill(unittest.TestCase):

    def test_child_grandchild_and_closed_issue_get_the_epics_label(self):
        repo = FakeRepo(tree())
        code, out = backfill(repo)
        self.assertEqual((code, out['status']), (0, 'ok'))
        self.assertEqual(repo.carried(3), ['area: library'])
        self.assertEqual(repo.carried(4), ['area: library'])
        self.assertEqual(repo.carried(5), ['area: library'])   # closed
        self.assertEqual(repo.carried(6), ['area: listening'])
        self.assertEqual(out['labelled'], 4)
        self.assertEqual(out['scanned'], 7)
        self.assertEqual(out['counts']['listening']['to_label'], 1)
        # The epics and the parent links are left as they were.
        self.assertEqual(repo.carried(1), [])
        self.assertEqual(repo.issues[4]['parent'], 3)
        self.assertEqual(repo.closes, [])

    def test_a_second_run_writes_nothing(self):
        repo = FakeRepo(tree())
        backfill(repo)
        sent = len(repo.mutations)
        code, out = backfill(repo)
        self.assertEqual((code, out['status']), (0, 'ok'))
        self.assertEqual(len(repo.mutations), sent)
        self.assertEqual((out['labelled'], out['already']), (0, 4))

    def test_a_failed_write_is_partial_and_the_next_run_finishes_it(self):
        repo = FakeRepo(tree(), fail={4})
        code, out = backfill(repo)
        self.assertEqual((code, out['status']), (24, 'partial'))
        self.assertEqual([f['number'] for f in out['failed']], [4])
        self.assertEqual(out['labelled'], 3)
        self.assertEqual(repo.carried(3), ['area: library'])
        repo.fail = set()
        code, out = backfill(repo)
        self.assertEqual((code, out['status']), (0, 'ok'))
        self.assertEqual(repo.mutations[-1], [4])
        self.assertEqual(repo.carried(4), ['area: library'])

    def test_many_issues_are_written_twenty_a_request(self):
        repo = FakeRepo([area(1)] + [issue(n, parent=1) for n in range(10, 55)],
                        labels=LABELS)
        code, out = backfill(repo, cfg=_cfg(AREAS[:1]))
        self.assertEqual((code, out['labelled']), (0, 45))
        self.assertEqual([len(m) for m in repo.mutations], [20, 20, 5])

    def test_an_area_epic_with_no_row_stops_before_any_write(self):
        repo = FakeRepo(tree() + [area(7, title='Sync'), issue(8, parent=7)])
        code, out = backfill(repo)
        self.assertEqual((code, out['status']), (22, 'refused'))
        self.assertEqual(out['stops']['epics_without_row'],
                         [{'number': 7, 'title': 'Sync'}])
        self.assertEqual(repo.mutations, [])
        self.assertEqual(repo.carried(3), [])

    def test_a_row_whose_label_is_missing_stops_before_any_write(self):
        repo = FakeRepo(tree(), labels=('area: library', 'bug'))
        code, out = backfill(repo)
        self.assertEqual((code, out['status']), (22, 'refused'))
        self.assertEqual(out['stops']['missing_labels'], ['area: listening'])
        self.assertIn('labels-ensure', out['reason'])
        self.assertEqual(repo.mutations, [])

    def test_no_areas_table_is_an_error(self):
        repo = FakeRepo(tree())
        code, out = backfill(repo, cfg=_cfg([]))
        self.assertEqual((code, out['status']), (20, 'error'))
        self.assertEqual(repo.pages, [])

    def test_an_issue_with_another_area_label_is_skipped_and_reported(self):
        issues = tree()
        issues[3]['labels'] = ['area: listening']   # #4, under Library
        repo = FakeRepo(issues)
        code, out = backfill(repo)
        self.assertEqual(code, 0)
        self.assertEqual(repo.carried(4), ['area: listening'])
        self.assertEqual(out['differs'], [{
            'number': 4, 'title': 'Issue 4', 'has': ['area: listening'],
            'resolves_to': 'area: library'}])
        self.assertNotIn(4, [n for m in repo.mutations for n in m])

    def test_issues_with_no_area_are_reported_and_never_written(self):
        issues = tree() + [issue(10, parent=11), issue(11, parent=10),
                           issue(12, parent=1, parent_repo='acme/other'),
                           issue(13, labels=['area: new'])]
        repo = FakeRepo(issues)
        code, out = backfill(repo)
        self.assertEqual(code, 0)
        self.assertEqual([(i['number'], i['title']) for i in out['no_area']],
                         [(9, 'Loose end'), (10, 'Issue 10'), (11, 'Issue 11'),
                          (12, 'Issue 12')])
        written = [n for m in repo.mutations for n in m]
        for number in (9, 10, 11, 12, 13):
            self.assertNotIn(number, written)
        self.assertEqual(repo.carried(9), [])
        # #13 has no epic above it, and its label is its area already.
        self.assertEqual(repo.carried(13), ['area: new'])

    def test_a_dry_run_prints_the_counts_and_writes_nothing(self):
        repo = FakeRepo(tree())
        code, out = backfill(repo, '--dry-run', '--close-epics')
        self.assertEqual((code, out['status']), (0, 'ok'))
        self.assertTrue(out['dry_run'])
        self.assertEqual(out['would_label'], 4)
        self.assertEqual(out['counts'], {
            'library': {'to_label': 3, 'already': 0, 'differs': 0, 'total': 3},
            'listening': {'to_label': 1, 'already': 0, 'differs': 0, 'total': 1}})
        self.assertEqual(out['would_close'], [])
        self.assertEqual((repo.mutations, repo.closes), ([], []))
        self.assertEqual(repo.carried(3), [])

    def test_a_dry_run_after_the_backfill_names_the_epics_to_close(self):
        repo = FakeRepo(tree())
        backfill(repo)
        _code, out = backfill(repo, '--dry-run')
        self.assertEqual((out['would_label'], out['would_close']), (0, [1, 2]))
        self.assertEqual(repo.closes, [])


class TestCloseEpics(unittest.TestCase):

    def test_a_run_that_labelled_closes_nothing_and_the_next_one_closes(self):
        repo = FakeRepo(tree())
        code, out = backfill(repo, '--close-epics')
        self.assertEqual((code, out['epics_closed']), (0, []))
        self.assertIn('run `area-backfill --close-epics` again',
                      out['close_refused'])
        self.assertEqual(repo.closes, [])
        code, out = backfill(repo, '--close-epics')
        self.assertEqual((code, out['epics_closed']), (0, [1, 2]))
        self.assertEqual(repo.issues[1]['state'], 'CLOSED')
        self.assertIn('area: library', repo.closes[0][-1])
        self.assertEqual(repo.closes[0][repo.closes[0].index('--reason') + 1],
                         'completed')
        # Still resolved through the closed epic, and the links are kept.
        self.assertEqual(repo.issues[3]['parent'], 1)
        code, out = backfill(repo, '--close-epics')
        self.assertEqual((code, out['epics_closed'], out['already']), (0, [], 4))
        self.assertEqual(len(repo.closes), 2)

    def test_an_epic_that_is_closed_already_is_skipped(self):
        issues = tree()
        issues[1]['state'] = 'CLOSED'   # Listening
        repo = FakeRepo(issues)
        backfill(repo)
        _code, out = backfill(repo, '--close-epics')
        self.assertEqual(out['epics_closed'], [1])
        self.assertEqual([c[3] for c in repo.closes], ['1'])

    def test_without_the_flag_no_epic_is_closed(self):
        repo = FakeRepo(tree())
        backfill(repo)
        backfill(repo)
        self.assertEqual(repo.closes, [])

    def test_a_failed_write_keeps_the_epics_open(self):
        repo = FakeRepo(tree(), fail={4})
        code, out = backfill(repo, '--close-epics')
        self.assertEqual(code, 24)
        code, out = backfill(repo, '--close-epics')
        self.assertEqual((code, out['epics_closed']), (24, []))
        self.assertEqual(repo.closes, [])

    def test_a_differing_label_keeps_the_epics_open(self):
        issues = tree()
        issues[3]['labels'] = ['area: listening']
        repo = FakeRepo(issues)
        backfill(repo)
        code, out = backfill(repo, '--close-epics')
        self.assertEqual((code, out['epics_closed']), (0, []))
        self.assertIn('differs', out['close_refused'])
        self.assertEqual(repo.closes, [])

    def test_an_epic_that_cannot_be_closed_is_partial(self):
        repo = FakeRepo(tree(), fail_close=True)
        backfill(repo)
        code, out = backfill(repo, '--close-epics')
        self.assertEqual((code, out['status']), (24, 'partial'))
        self.assertEqual([f['number'] for f in out['close_failed']], [1, 2])


class TestTheRead(unittest.TestCase):

    def test_250_issues_come_back_over_3_pages(self):
        repo = FakeRepo([area(1)] + [issue(n, parent=1) for n in range(2, 251)])
        with mock.patch.object(wf, 'gh_graphql', repo.gh_graphql):
            ok, nodes, size, err = wf.scan_all_issues(_cfg())
        self.assertTrue(ok, err)
        self.assertEqual(len(nodes), 250)
        self.assertEqual(repo.pages, [(100, None), (100, '100'), (100, '200')])
        self.assertEqual(size, 100)

    def test_a_resource_limit_asks_the_same_cursor_at_half_the_page(self):
        repo = FakeRepo([area(1)] + [issue(n, parent=1) for n in range(2, 121)],
                        limit=50)
        with mock.patch.object(wf, 'gh_graphql', repo.gh_graphql):
            ok, nodes, size, err = wf.scan_all_issues(_cfg())
        self.assertTrue(ok, err)
        self.assertEqual(sorted(n['number'] for n in nodes), list(range(1, 121)))
        self.assertEqual(repo.pages, [(100, None), (50, None), (50, '50'),
                                      (50, '100')])
        self.assertEqual(size, 50)

    def test_the_page_is_not_halved_below_the_floor(self):
        repo = FakeRepo(tree(), limit=0)
        with mock.patch.object(wf, 'gh_graphql', repo.gh_graphql):
            ok, _nodes, size, err = wf.scan_all_issues(_cfg())
        self.assertFalse(ok)
        self.assertEqual(size, wf.STAGE_MIN_PAGE_SIZE)
        self.assertIn('RESOURCE_LIMITS_EXCEEDED', err)

    def test_a_cursor_that_does_not_advance_is_an_error(self):
        repo = FakeRepo(tree(), stuck=True)
        # The first page says there is more and gives no cursor to follow.
        with mock.patch.object(wf, 'gh_graphql', repo.gh_graphql):
            ok, _nodes, _size, err = wf.scan_all_issues(_cfg())
        self.assertFalse(ok)
        self.assertIn('did not advance', err)
        self.assertEqual(len(repo.pages), 1)

    def test_the_page_size_is_reported_and_a_failed_read_writes_nothing(self):
        repo = FakeRepo(tree(), limit=25)
        code, out = backfill(repo, '--dry-run')
        self.assertEqual((code, out['page_size']), (0, 25))
        repo = FakeRepo(tree(), limit=0)
        code, out = backfill(repo)
        self.assertEqual((code, out['status']), (20, 'error'))
        self.assertEqual(repo.mutations, [])

    def test_repo_flag_names_the_repository_read_and_written(self):
        repo = FakeRepo(tree())
        cfg = dict(_cfg(), org='elsewhere', repo='other')
        code, out = backfill(repo, '--repo', REPO, cfg=cfg)
        self.assertEqual((code, out['repo'], out['labelled']), (0, REPO, 4))


if __name__ == '__main__':
    unittest.main()
