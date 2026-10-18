#!/usr/bin/env python3
"""
`wf labels-ensure` and the area and release labels (#386).

The `## Areas` and `## Release Targets` tables in `ClaudeProject.md` define
the labels an issue may carry, and `labels-ensure` makes the repository match
them: it creates what is missing and renames a label whose row carries `was`.
It never deletes a label and never changes a colour or description, so
everything else it finds is reported for a person to read.

Two halves, both offline. The rules in `wf_core_labels` are pure and are
tested with plain dicts. The command is run against `FakeRepo`, which stands
in for GitHub at the two seams the shell uses, `wf.gh_graphql` for the read
and `wf.run` for each write, and keeps the labels a write leaves behind, so a
second run sees what the first one did.

Run standalone (`python3 tests/test_labels_ensure.py`) or via `run-tests.sh`.
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
REVIEW = list(wf_core.REVIEW_DEFAULT_LABELS.values())

AREAS = [
    {'name': 'api', 'description': 'The public HTTP API', 'colour': '1d76db',
     'epic': None, 'was': None},
    {'name': 'billing', 'description': 'Invoices and payments', 'colour': 'fbca04',
     'epic': 12, 'was': None},
]
TARGETS = [
    {'name': 'mobile', 'description': 'The phone apps', 'colour': '5319e7'},
    {'name': 'web', 'description': 'The browser app', 'colour': 'd93f0b'},
]
TABLE_NAMES = [
    'area: api', 'area: billing',
    'release: mobile', 'released: mobile', 'release: web', 'released: web',
    'release: internal', 'released: internal',
]


def _cfg(areas=None, release_targets=None):
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'labels': {}, 'review_labels': {}, 'fields': {},
            'areas': json.loads(json.dumps(areas or [])),
            'release_targets': json.loads(json.dumps(release_targets or []))}


def _area(name, was=None, colour='1d76db', description='The public HTTP API'):
    return {'name': name, 'description': description, 'colour': colour,
            'epic': None, 'was': was}


def _live(name, colour='ededed', description=''):
    return {'name': name, 'colour': colour, 'description': description}


class FakeRepo:
    """The labels of one GitHub repository, and the issues that carry them.

    A rename is done the way GitHub does it: the label keeps its identity, so
    each issue that carried the old name carries the new one. `page_size`
    makes the read come back in pages, as GitHub's does past 100 labels.
    """

    def __init__(self, labels=(), issues=None, page_size=100, fail=None):
        self.labels = {}
        for label in labels:
            label = _live(label) if isinstance(label, str) else label
            self.labels[label['name']] = {'color': label['colour'],
                                          'description': label['description']}
        self.issues = {n: list(names) for n, names in (issues or {}).items()}
        self.page_size = page_size
        self.fail = fail
        self.writes = []
        self.reads = 0

    def names(self):
        return sorted(self.labels)

    def gh_graphql(self, query, **fields):
        self.reads += 1
        names = list(self.labels)
        start = int(fields.get('after') or 0)
        page = names[start:start + self.page_size]
        more = start + self.page_size < len(names)
        nodes = [dict(self.labels[n], name=n) for n in page]
        return True, {'repository': {'labels': {
            'nodes': nodes,
            'pageInfo': {'hasNextPage': more,
                         'endCursor': str(start + self.page_size) if more else None},
        }}}, ''

    def run(self, cmd, input_text=None):
        cmd = list(cmd)
        if cmd[:2] != ['gh', 'label']:
            raise AssertionError('unexpected command: %r' % (cmd,))
        self.writes.append(cmd)
        if self.fail:
            return 1, '', self.fail
        flags = dict(zip(cmd[4::2], cmd[5::2]))
        if flags.pop('--repo') != REPO:
            raise AssertionError('wrong repository: %r' % (cmd,))
        if cmd[2] == 'create':
            if cmd[3].lower() in {n.lower() for n in self.labels}:
                return 1, '', 'label with name "%s" already exists' % cmd[3]
            self.labels[cmd[3]] = {'color': flags.get('--color', 'ededed'),
                                   'description': flags.get('--description', '')}
        elif cmd[2] == 'edit':
            new = flags['--name']
            self.labels = {(new if n == cmd[3] else n): meta
                           for n, meta in self.labels.items()}
            for carried in self.issues.values():
                carried[:] = [new if n == cmd[3] else n for n in carried]
        else:
            raise AssertionError('labels-ensure must never run: %r' % (cmd,))
        return 0, '', ''


def _ensure(repo, cfg):
    """Run `wf labels-ensure` against `repo`. Returns (code, payload, writes).

    `writes` holds only the write calls this run made.
    """
    before = len(repo.writes)

    def names_only(cfg, repo_slug=None):
        return True, {'labels': list(repo.labels)}, ''

    args = wf.build_parser().parse_args(['labels-ensure'])
    buf, code = io.StringIO(), None
    with mock.patch.object(wf, 'prepare_cfg', lambda: cfg), \
            mock.patch.object(wf, 'run', repo.run), \
            mock.patch.object(wf, 'gh_graphql', repo.gh_graphql), \
            mock.patch.object(wf, 'fetch_repo_state', names_only), \
            contextlib.redirect_stderr(io.StringIO()), \
            contextlib.redirect_stdout(buf):
        try:
            args.func(args)
        except SystemExit as exc:
            code = exc.code
    return code, json.loads(buf.getvalue()), repo.writes[before:]


# ── the rules ────────────────────────────────────────────────────────────────

class TestTableLabels(unittest.TestCase):
    """Which labels the two tables name."""

    def test_no_table_names_no_label(self):
        self.assertEqual(wf_core.table_labels(_cfg()), [])
        self.assertEqual(wf_core.table_labels({'org': 'a', 'repo': 'b'}), [])

    def test_each_row_becomes_its_labels_in_table_order(self):
        wanted = wf_core.table_labels(_cfg(AREAS, TARGETS))
        self.assertEqual([w['name'] for w in wanted], TABLE_NAMES)

    def test_an_area_takes_its_rows_description_and_colour(self):
        wanted = wf_core.table_labels(_cfg(AREAS))
        self.assertEqual(wanted[0], {'name': 'area: api', 'was': None,
                                     'description': 'The public HTTP API',
                                     'colour': '1d76db'})

    def test_areas_alone_add_no_internal_release_labels(self):
        names = [w['name'] for w in wf_core.table_labels(_cfg(AREAS))]
        self.assertEqual(names, ['area: api', 'area: billing'])

    def test_a_release_label_says_waiting_and_a_released_label_says_shipped(self):
        by_name = {w['name']: w for w in wf_core.table_labels(_cfg([], TARGETS))}
        self.assertEqual(by_name['release: mobile']['description'],
                         'Waiting to ship in mobile: The phone apps')
        self.assertEqual(by_name['released: mobile']['description'],
                         'Shipped in mobile: The phone apps')
        self.assertEqual(by_name['release: mobile']['colour'], '5319e7')
        self.assertEqual(by_name['released: mobile']['colour'],
                         by_name['released: web']['colour'])
        self.assertIn('Waiting', by_name['release: internal']['description'])
        self.assertIn('Shipped', by_name['released: internal']['description'])

    def test_no_description_is_longer_than_github_allows(self):
        long_row = [{'name': 'a-rather-long-target-name', 'colour': '',
                     'description': 'x' * 100}]
        for label in wf_core.table_labels(_cfg(AREAS, TARGETS + long_row)):
            with self.subTest(label=label['name']):
                self.assertTrue(label['description'])
                self.assertLessEqual(len(label['description']), 100)

    def test_a_row_named_internal_is_not_added_a_second_time(self):
        targets = [{'name': 'Internal', 'description': 'Staff builds',
                    'colour': 'aaaaaa'}]
        wanted = wf_core.table_labels(_cfg([], targets))
        self.assertEqual([w['name'] for w in wanted],
                         ['release: Internal', 'released: Internal'])

    def test_was_is_the_old_area_name_or_the_old_label_in_full(self):
        wanted = wf_core.table_labels(_cfg([_area('api', was='backend'),
                                            _area('web', was='Area: site')]))
        self.assertEqual([w['was'] for w in wanted], ['area: backend', 'Area: site'])


class TestLabelPlan(unittest.TestCase):
    """What the repository's labels and the tables add up to."""

    def _plan(self, areas, live, targets=None):
        return wf_core.label_plan(wf_core.table_labels(_cfg(areas, targets)), live)

    def test_a_missing_label_is_created_and_a_present_one_is_not(self):
        plan = self._plan(AREAS, [_live('area: api', '1d76db', 'The public HTTP API')])
        self.assertEqual([c['name'] for c in plan['create']], ['area: billing'])
        self.assertEqual(plan['differs'], [])

    def test_a_name_that_differs_only_in_case_is_the_same_label(self):
        plan = self._plan([_area('api')],
                          [_live('Area: API', '1d76db', 'The public HTTP API')])
        self.assertEqual(plan['create'], [])
        self.assertEqual(plan['unknown'], [])

    def test_only_the_old_name_existing_is_a_rename(self):
        plan = self._plan([_area('api', was='backend')], [_live('area: backend')])
        self.assertEqual(plan['rename'], [{'from': 'area: backend', 'to': 'area: api'}])
        self.assertEqual(plan['create'], [])
        self.assertEqual(plan['unknown'], [])

    def test_both_names_existing_is_a_conflict_and_nothing_else(self):
        plan = self._plan([_area('api', was='backend')],
                          [_live('area: backend'),
                           _live('area: api', '1d76db', 'The public HTTP API')])
        self.assertEqual(plan['conflicts'], [{'was': 'area: backend', 'name': 'area: api'}])
        self.assertEqual(plan['rename'], [])
        self.assertEqual(plan['create'], [])
        self.assertEqual(plan['unknown'], [])

    def test_neither_name_existing_is_a_create(self):
        plan = self._plan([_area('api', was='backend')], [])
        self.assertEqual([c['name'] for c in plan['create']], ['area: api'])
        self.assertEqual(plan['rename'], [])

    def test_an_old_name_another_row_now_uses_is_left_to_that_row(self):
        plan = self._plan([_area('api', was='core'), _area('core')],
                          [_live('area: core', '1d76db', 'The public HTTP API')])
        self.assertEqual(plan['rename'], [])
        self.assertEqual([c['name'] for c in plan['create']], ['area: api'])

    def test_a_label_under_a_table_prefix_that_no_row_names_is_unknown(self):
        live = [_live('area: gone'), _live('Release: old'), _live('released: old'),
                _live('bug'), _live('areas'), _live('review-approved')]
        plan = self._plan(AREAS, live)
        self.assertEqual(plan['unknown'], ['area: gone', 'Release: old', 'released: old'])

    def test_a_colour_or_description_that_is_not_the_rows_is_reported(self):
        plan = self._plan([_area('api')], [_live('area: api', 'FF0000', 'Something else')])
        self.assertEqual(plan['differs'], [
            {'name': 'area: api', 'field': 'colour', 'wanted': '1d76db', 'live': 'ff0000'},
            {'name': 'area: api', 'field': 'description',
             'wanted': 'The public HTTP API', 'live': 'Something else'},
        ])
        self.assertEqual(plan['create'], [])

    def test_colours_are_compared_without_case_and_without_the_hash(self):
        plan = self._plan([_area('api')],
                          [_live('area: api', '#1D76DB', 'The public HTTP API')])
        self.assertEqual(plan['differs'], [])

    def test_a_row_that_states_no_colour_or_description_accepts_any(self):
        plan = self._plan([_area('api', colour='', description='')],
                          [_live('area: api', 'ff0000', 'Whatever a person wrote')])
        self.assertEqual(plan['differs'], [])


# ── the command ──────────────────────────────────────────────────────────────

class TestLabelsEnsureTables(unittest.TestCase):
    """`wf labels-ensure` against a repository, write by write."""

    def test_a_first_run_creates_every_label_the_tables_name(self):
        repo = FakeRepo()
        code, payload, writes = _ensure(repo, _cfg(AREAS, TARGETS))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(repo.names(), sorted(REVIEW + TABLE_NAMES))
        self.assertEqual(payload['created'], REVIEW + TABLE_NAMES)
        self.assertEqual(payload['table_labels'], TABLE_NAMES)
        self.assertEqual(payload['failed'], [])
        self.assertTrue(all(w[2] == 'create' for w in writes))
        self.assertFalse(any('--force' in w for w in writes))
        self.assertEqual(repo.labels['area: billing'],
                         {'color': 'fbca04', 'description': 'Invoices and payments'})

    def test_a_second_run_writes_nothing(self):
        repo = FakeRepo()
        cfg = _cfg(AREAS, TARGETS)
        _ensure(repo, cfg)
        code, payload, writes = _ensure(repo, cfg)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(writes, [])
        self.assertEqual(payload['created'], [])
        for key in ('renamed', 'conflicts', 'unknown', 'differs', 'failed'):
            self.assertEqual(payload[key], [], key)

    def test_the_review_labels_are_created_first_and_reported_as_before(self):
        repo = FakeRepo()
        _, payload, writes = _ensure(repo, _cfg(AREAS, TARGETS))
        self.assertEqual([w[3] for w in writes[:len(REVIEW)]], REVIEW)
        self.assertEqual(payload['labels'], REVIEW)

    def test_the_labels_are_read_once_for_both_halves(self):
        repo = FakeRepo()
        _ensure(repo, _cfg(AREAS, TARGETS))
        self.assertEqual(repo.reads, 1)

    def test_a_row_with_was_renames_the_label_and_each_issue_keeps_it(self):
        repo = FakeRepo(REVIEW + ['area: backend', 'area: billing'],
                        issues={7: ['area: backend', 'bug'], 9: ['area: billing']})
        cfg = _cfg([_area('api', was='backend'), AREAS[1]])
        code, payload, writes = _ensure(repo, cfg)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(writes, [['gh', 'label', 'edit', 'area: backend',
                                   '--repo', REPO, '--name', 'area: api']])
        self.assertEqual(payload['renamed'], [{'from': 'area: backend', 'to': 'area: api'}])
        self.assertEqual(payload['created'], [])
        self.assertEqual(payload['unknown'], [])
        self.assertEqual(repo.issues, {7: ['area: api', 'bug'], 9: ['area: billing']})
        self.assertNotIn('area: backend', repo.labels)
        _, again, writes = _ensure(repo, cfg)
        self.assertEqual(writes, [])
        self.assertEqual(again['renamed'], [])

    def test_both_names_existing_is_reported_and_nothing_is_written_for_the_row(self):
        repo = FakeRepo(REVIEW + ['area: backend', 'area: api'],
                        issues={7: ['area: backend']})
        code, payload, writes = _ensure(repo, _cfg([_area('api', was='backend')]))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(writes, [])
        self.assertEqual(payload['conflicts'],
                         [{'was': 'area: backend', 'name': 'area: api'}])
        self.assertEqual(payload['unknown'], [])
        self.assertEqual(repo.issues, {7: ['area: backend']})
        self.assertIn('area: backend', repo.labels)

    def test_a_label_the_tables_do_not_name_is_reported_and_still_exists(self):
        repo = FakeRepo(['area: gone', 'released: old', 'bug'])
        code, payload, writes = _ensure(repo, _cfg(AREAS, TARGETS))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['unknown'], ['area: gone', 'released: old'])
        self.assertTrue({'area: gone', 'released: old', 'bug'} <= set(repo.labels))
        self.assertFalse(any(w[2] == 'delete' for w in writes))

    def test_a_differing_colour_or_description_is_reported_and_not_changed(self):
        mine = {'name': 'area: api', 'colour': 'ff0000', 'description': 'My own words'}
        repo = FakeRepo(REVIEW + [mine, 'area: billing'])
        code, payload, writes = _ensure(repo, _cfg(AREAS))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(writes, [])
        self.assertEqual([(d['name'], d['field']) for d in payload['differs']],
                         [('area: api', 'colour'), ('area: api', 'description'),
                          ('area: billing', 'colour'), ('area: billing', 'description')])
        self.assertEqual(repo.labels['area: api'],
                         {'color': 'ff0000', 'description': 'My own words'})

    def test_a_row_with_no_colour_is_created_with_the_colour_github_picks(self):
        repo = FakeRepo(REVIEW)
        _, _, writes = _ensure(repo, _cfg([_area('api', colour='')]))
        self.assertEqual(len(writes), 1)
        self.assertNotIn('--color', writes[0])

    def test_a_repository_with_more_than_one_page_of_labels_is_read_whole(self):
        filler = ['topic-%03d' % i for i in range(7)]
        repo = FakeRepo(filler + REVIEW + TABLE_NAMES, page_size=5)
        code, payload, writes = _ensure(repo, _cfg(AREAS, TARGETS))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(writes, [])
        self.assertEqual(payload['created'], [])
        self.assertGreater(repo.reads, 1)

    def test_losing_a_race_to_another_agent_is_not_a_failure(self):
        repo = FakeRepo(REVIEW, fail='label with name "x" already exists')
        code, payload, _ = _ensure(repo, _cfg(AREAS))
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(payload['created'], ['area: api', 'area: billing'])

    def test_a_write_that_fails_for_real_is_reported(self):
        repo = FakeRepo(REVIEW + ['area: backend'], fail='HTTP 403')
        code, payload, _ = _ensure(repo, _cfg([_area('api', was='backend'), AREAS[1]]))
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(payload['renamed'], [])
        self.assertEqual(payload['failed'], ['area: billing (HTTP 403)',
                                             'area: backend -> area: api (HTTP 403)'])

    def test_labels_that_cannot_be_read_stop_the_run_before_any_write(self):
        repo = FakeRepo()
        repo.gh_graphql = lambda query, **fields: (False, None, 'HTTP 502')
        code, payload, writes = _ensure(repo, _cfg(AREAS))
        self.assertEqual(code, wf.EXIT_ENV)
        self.assertEqual(writes, [])
        self.assertIn('HTTP 502', payload['reason'])


class TestLabelsEnsureWithoutTables(unittest.TestCase):
    """A repository with neither table gets the review labels, as before."""

    def test_only_the_review_labels_are_created(self):
        repo = FakeRepo(['area: something', 'bug'])
        code, payload, writes = _ensure(repo, _cfg())
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual([w[3] for w in writes], REVIEW)
        self.assertEqual(payload['created'], REVIEW)

    def test_the_result_carries_the_same_keys_as_before(self):
        _, payload, _ = _ensure(FakeRepo(), _cfg())
        self.assertEqual(sorted(payload), ['created', 'failed', 'labels', 'status'])

    def test_the_detailed_read_is_not_made(self):
        repo = FakeRepo()
        _ensure(repo, _cfg())
        self.assertEqual(repo.reads, 0)

    def test_a_config_from_before_the_tables_existed_behaves_the_same(self):
        cfg = _cfg()
        del cfg['areas'], cfg['release_targets']
        repo = FakeRepo()
        code, payload, writes = _ensure(repo, cfg)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(len(writes), len(REVIEW))
        self.assertNotIn('unknown', payload)


if __name__ == '__main__':
    unittest.main()
