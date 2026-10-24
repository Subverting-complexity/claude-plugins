#!/usr/bin/env python3
"""
Claims with a session label beside the claim ref (#440).

Every claim adds the label `session: <guid>` to the issue or pull request.
Where the claim ref push works, the ref stays the primary lock and the label
is added beside it. Where it is refused with HTTP 403, as in a Claude Code
cloud session, the label is the only lock. When two sessions label the same
item, the one whose label was added first keeps it. These tests check both
kinds of session against each other, the race, the release, the held check,
pull request claims, and the reaping of unused labels.

Run standalone (`python3 tests/test_claim_label.py`) or via `run-tests.sh`.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'))
import wf  # noqa: E402
import wf_claim_label  # noqa: E402
import wf_io  # noqa: E402
import wf_rest  # noqa: E402


MINE = 'session: me-guid'
RIVAL = 'session: rival-guid'
REFUSED = 'remote: Permission denied\nfatal: unable to access: The requested URL returned error: 403'


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'branch_convention': 'feature/{number}/{short-desc}',
            'labels': {}, 'review_labels': {}, 'fields': {}, 'board': {}}


class _Remote:
    """A fake remote: claim refs on the git side, labels and their events on
    the REST side."""

    def __init__(self, push_err=None, refs=(), labels=None, race=None):
        self.push_err = push_err
        self.refs = set(refs)
        self.labels = {k: list(v) for k, v in (labels or {}).items()}
        self.repo_labels = {name for names in self.labels.values() for name in names}
        # A rival label GitHub adds just before ours, as in a race.
        self.race = race
        # Finished work: closed, completed issues and merged pull requests.
        self.closed, self.merged = set(), set()
        self.events = {}
        self.next_id = 100
        for number, names in self.labels.items():
            for name in names:
                self._event(number, name)
        self.git, self.rest = [], []

    def _event(self, number, name):
        self.next_id += 1
        self.events.setdefault(number, []).append(
            {'id': self.next_id, 'event': 'labeled', 'label': {'name': name},
             'created_at': '2026-01-01T00:00:00Z'})

    def run(self, cmd, input_text=None):
        self.git.append(list(cmd))
        if cmd[:2] == ['git', 'mktree']:
            return 0, 'tree0\n', ''
        if cmd[:2] == ['git', 'commit-tree']:
            return 0, 'sha1\n', ''
        if cmd[:2] == ['git', 'push']:
            if self.push_err:
                return 1, '', self.push_err
            for spec in cmd[2:]:
                src, _, ref = spec.partition(':')
                if ref.startswith('refs/claims/'):
                    if src:
                        self.refs.add(ref)
                    else:
                        self.refs.discard(ref)
            return 0, '', ''
        if cmd[:2] == ['git', 'ls-remote']:
            listed = [a for a in cmd if a in self.refs]
            if listed:
                return 0, ''.join('sha1\t%s\n' % r for r in listed), ''
            return 2, '', ''
        return 0, '', ''

    def gh_rest(self, path, method='GET', body=None):
        self.rest.append((method, path, body))
        if path.startswith('repos/acme/widgets/labels'):
            if method == 'DELETE':
                self.repo_labels.discard(unquote(path.rsplit('/', 1)[1]))
                return True, None, ''
            return True, [{'name': n} for n in sorted(self.repo_labels)], ''
        if path.startswith('repos/acme/widgets/issues?'):
            wanted = unquote(path.split('labels=')[1])
            return True, [{'number': n} for n, names in self.labels.items()
                          if wanted in names], ''
        number = int(path.split('/issues/')[1].split('/')[0].split('?')[0])
        current = self.labels.setdefault(number, [])
        if '/events' in path:
            return True, list(self.events.get(number, [])), ''
        if path.endswith('/labels') and method == 'POST':
            if self.race and self.race not in current:
                current.append(self.race)
                self._event(number, self.race)
            for name in body['labels']:
                if name not in current:
                    current.append(name)
                    self.repo_labels.add(name)
                    self._event(number, name)
            return True, [{'name': n} for n in current], ''
        if '/labels/' in path and method == 'DELETE':
            name = unquote(path.rsplit('/', 1)[1])
            if name not in current:
                return False, None, 'HTTP 404: Label does not exist'
            current.remove(name)
            return True, [{'name': n} for n in current], ''
        if path.endswith('/labels'):
            return True, [{'name': n} for n in current], ''
        item = {'number': number, 'labels': [{'name': n} for n in current],
                'state': 'closed' if number in self.closed | self.merged else 'open',
                'state_reason': 'completed' if number in self.closed else None}
        if number in self.merged:
            item['pull_request'] = {'merged_at': '2026-10-24T00:00:00Z'}
        return True, item, ''

    def writes(self):
        return [(m, p) for m, p, _ in self.rest if m != 'GET']


class _Case(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        wf_claim_label.reset_claim_label_state()
        wf_rest.reset_rest_state()
        # GraphQL is off so that every label write goes through the REST fake.
        with contextlib.redirect_stderr(io.StringIO()):
            wf_io.mark_graphql_blocked()
        self.addCleanup(wf_io.reset_graphql_state)
        self.addCleanup(wf_claim_label.reset_claim_label_state)
        self.addCleanup(wf_rest.reset_rest_state)
        env = mock.patch.dict(os.environ, {wf_claim_label.CLAIM_REFS_ENV: '',
                                           wf_claim_label.SESSION_ENV: 'me-guid'})
        env.start()
        self.addCleanup(env.stop)
        for name, value in (('repo_root', lambda: self.root),
                            ('load_config', lambda: (True, _cfg(), '')),
                            ('prepare_cfg', _cfg),
                            ('check_environment', lambda: None),
                            ('ensure_scratch_ignored', lambda root: False)):
            patch = mock.patch.object(wf, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def use(self, remote):
        for name in ('run', 'gh_rest'):
            patch = mock.patch.object(wf, name, getattr(remote, name))
            patch.start()
            self.addCleanup(patch.stop)
        return remote

    def acquire(self, target):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            outcome = wf.acquire_claim(target)
        return outcome, err.getvalue()

    def marker(self, target):
        path = os.path.join(self.root, '.claude', 'claim-%s.sha' % target)
        if not os.path.exists(path):
            return None
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def as_session(self, guid):
        """Switch this process to another session's GUID."""
        wf_claim_label.reset_claim_label_state()
        os.environ[wf_claim_label.SESSION_ENV] = guid


class TestLocalSession(_Case):

    def test_a_local_claim_takes_the_ref_and_the_label_and_releases_both(self):
        remote = self.use(_Remote())
        outcome, err = self.acquire('issue-5')
        self.assertEqual(outcome, 'won')
        self.assertEqual(err, '')
        self.assertIn('refs/claims/issue-5', remote.refs)
        self.assertEqual(remote.labels[5], [MINE])
        self.assertEqual(self.marker('issue-5'), 'sha1')
        self.assertTrue(wf.release_claim('issue-5'))
        self.assertNotIn('refs/claims/issue-5', remote.refs)
        self.assertEqual(remote.labels[5], [])
        self.assertIsNone(self.marker('issue-5'))

    def test_a_story_a_cloud_session_labelled_first_is_lost_and_the_ref_given_back(self):
        remote = self.use(_Remote(labels={5: [RIVAL]}))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'lost')
        self.assertNotIn('refs/claims/issue-5', remote.refs)
        self.assertEqual(remote.labels[5], [RIVAL])
        self.assertIsNone(self.marker('issue-5'))

    def test_a_rival_ref_is_lost_without_a_label(self):
        remote = self.use(_Remote(push_err='rejected', refs={'refs/claims/issue-5'}))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'lost')
        self.assertEqual(remote.writes(), [])

    def test_a_failed_label_write_keeps_the_ref_claim_with_a_warning(self):
        remote = self.use(_Remote())
        real = remote.gh_rest

        def failing(path, method='GET', body=None):
            if method == 'POST':
                return False, None, 'HTTP 502'
            return real(path, method, body)
        with mock.patch.object(wf, 'gh_rest', failing):
            outcome, err = self.acquire('issue-5')
        self.assertEqual(outcome, 'won')
        self.assertIn('without its session label', err)
        self.assertIn('refs/claims/issue-5', remote.refs)

    def test_a_push_refused_for_another_reason_is_still_an_error(self):
        remote = self.use(_Remote(push_err='fatal: could not read from remote'))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'error')
        self.assertEqual(remote.rest, [])

    def test_a_rate_limit_403_does_not_switch_to_labels(self):
        remote = self.use(_Remote(push_err='HTTP 403: API rate limit exceeded'))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'error')
        self.assertEqual(remote.rest, [])


class TestCloudSession(_Case):

    def test_a_refused_push_claims_with_the_label_alone(self):
        remote = self.use(_Remote(push_err=REFUSED))
        outcome, err = self.acquire('issue-5')
        self.assertEqual(outcome, 'won')
        self.assertEqual(remote.labels[5], [MINE])
        self.assertEqual(self.marker('issue-5'), 'session:me-guid')
        self.assertIn('with its session label alone', err)
        self.assertEqual(wf.claim_ref_of('issue-5'), 'label:' + MINE)
        self.assertEqual(wf.claim_ref_of('issue-6'), 'refs/claims/issue-6')

    def test_a_local_run_then_treats_the_cloud_claim_as_taken(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        self.as_session('local-guid')
        remote.push_err = None
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'lost')
        self.assertEqual(remote.labels[5], [MINE])
        self.assertNotIn('refs/claims/issue-5', remote.refs)

    def test_a_story_a_local_run_holds_by_ref_and_label_is_taken(self):
        remote = self.use(_Remote(refs={'refs/claims/issue-5'}, labels={5: [RIVAL]},
                                  push_err=REFUSED))
        with mock.patch.dict(os.environ, {wf_claim_label.CLAIM_REFS_ENV: 'off'}):
            outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'lost')
        self.assertEqual(remote.writes(), [])

    def test_only_the_label_added_first_keeps_a_raced_story(self):
        remote = self.use(_Remote(push_err=REFUSED, race=RIVAL))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'lost')
        self.assertEqual(remote.labels[5], [RIVAL])
        self.assertIsNone(self.marker('issue-5'))
        self.assertTrue(any('/events' in p for _, p, _ in remote.rest))

    def test_the_session_whose_label_came_first_keeps_it_through_the_race(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        # A rival in the same moment adds its label after ours.
        remote.labels[5].append(RIVAL)
        remote._event(5, RIVAL)
        self.assertTrue(wf.holds_claim('issue-5'))
        self.as_session('rival-guid')
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'lost')
        self.assertEqual(remote.labels[5], [MINE])

    def test_a_second_run_in_the_same_session_treats_the_claim_as_its_own(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        os.remove(os.path.join(self.root, '.claude', 'claim-issue-5.sha'))
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'won')
        self.assertEqual(remote.labels[5], [MINE])

    def test_the_notice_is_said_once_and_later_claims_skip_the_push(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        pushes = sum(1 for c in remote.git if c[:2] == ['git', 'push'])
        outcome, err = self.acquire('issue-6')
        self.assertEqual(outcome, 'won')
        self.assertEqual(err, '')
        self.assertEqual(sum(1 for c in remote.git if c[:2] == ['git', 'push']), pushes)

    def test_a_label_github_did_not_add_is_an_environment_error(self):
        remote = self.use(_Remote(push_err=REFUSED))
        real = remote.gh_rest

        def dropping(path, method='GET', body=None):
            if method == 'POST':
                return True, [], ''
            return real(path, method, body)
        args = argparse.Namespace(issue=5, pr=None, keep_held=False, marker=False)
        buf = io.StringIO()
        with mock.patch.object(wf, 'gh_rest', dropping), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                wf.cmd_claim(args)
        reason = json.loads(buf.getvalue())['reason']
        self.assertIn('session label', reason)
        self.assertNotIn('refs/claims', reason)

    def test_a_bulk_set_claimed_at_once_is_all_taken_and_all_released(self):
        """`plan-set --claim` takes every claim in parallel threads."""
        from concurrent.futures import ThreadPoolExecutor
        remote = self.use(_Remote(push_err=REFUSED))
        targets = ['issue-%d' % n for n in (5, 6, 7)]
        err = io.StringIO()
        with contextlib.redirect_stderr(err), ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = list(pool.map(wf.acquire_claim, targets))
        self.assertEqual(outcomes, ['won'] * 3)
        self.assertEqual(err.getvalue().count('session label alone'), 1)
        self.assertEqual(wf.release_claims(targets), dict.fromkeys(targets, True))
        self.assertEqual([remote.labels[n] for n in (5, 6, 7)], [[], [], []])


class TestPullRequestClaims(_Case):

    def test_a_review_claim_behaves_as_an_issue_claim(self):
        remote = self.use(_Remote(push_err=REFUSED))
        outcome, _ = self.acquire('pr-7')
        self.assertEqual(outcome, 'won')
        self.assertEqual(remote.labels[7], [MINE])
        writes = len(remote.writes())
        args = argparse.Namespace(issue=None, pr=7, keep_held=True, marker=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                wf.cmd_claim(args)
        self.assertEqual(caught.exception.code, wf.EXIT_OK)
        self.assertEqual(len(remote.writes()), writes)
        self.as_session('rival-guid')
        self.assertEqual(self.acquire('pr-7')[0], 'lost')

    def test_a_local_review_claim_carries_the_label(self):
        remote = self.use(_Remote())
        self.assertEqual(self.acquire('pr-7')[0], 'won')
        self.assertEqual(remote.labels[7], [MINE])
        self.assertIn('refs/claims/pr-7', remote.refs)


class TestReleaseAndHold(_Case):

    def test_release_removes_labels_and_pushes_only_ref_claims(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        remote.push_err = None
        with open(os.path.join(self.root, '.claude', 'claim-issue-6.sha'), 'w') as fh:
            fh.write('sha9')
        released = wf.release_claims(['issue-5', 'issue-6'])
        self.assertEqual(released, {'issue-5': True, 'issue-6': True})
        self.assertEqual(remote.labels[5], [])
        pushes = [c for c in remote.git if c[:2] == ['git', 'push'] and c[3:4] == [':refs/claims/issue-6']]
        self.assertEqual(len(pushes), 1)
        self.assertNotIn(':refs/claims/issue-5', pushes[0])
        self.assertIsNone(self.marker('issue-5'))

    def test_a_label_that_could_not_be_removed_is_not_released(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        real = remote.gh_rest

        def failing(path, method='GET', body=None):
            if method == 'DELETE':
                return False, None, 'HTTP 502'
            return real(path, method, body)
        with mock.patch.object(wf, 'gh_rest', failing), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(wf.release_claims(['issue-5']), {'issue-5': False})
        self.assertEqual(self.marker('issue-5'), 'session:me-guid')

    def test_not_held_once_a_claim_ref_appears(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        self.assertTrue(wf.holds_claim('issue-5'))
        remote.refs.add('refs/claims/issue-5')
        self.assertFalse(wf.holds_claim('issue-5'))

    def test_exit_cleanup_releases_the_issue_and_review_claims(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        self.acquire('pr-7')
        args = wf.build_parser().parse_args(['exit-cleanup', '--issue', '5', '--pr', '7'])
        buf = io.StringIO()
        with mock.patch.object(wf, 'reconcile_pr', lambda cfg, pr: ('kept', None)), \
                mock.patch.object(wf, 'reap_finished', lambda: 0), \
                mock.patch.object(wf, 'tree_entries', lambda: []), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                wf.cmd_exit_cleanup(args)
        self.assertEqual(caught.exception.code, wf.EXIT_OK)
        self.assertIn('released issue-5, pr-7', buf.getvalue())
        self.assertEqual(remote.labels[5], [])
        self.assertEqual(remote.labels[7], [])

    def test_a_claim_never_touches_the_assignment(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        wf.release_claims(['issue-5'])
        self.assertFalse(any('assignees' in p for _, p, _ in remote.rest))


class TestReleaseKeepsTheRepositoryLabel(_Case):

    def test_a_dropped_story_loses_the_label_and_the_repository_keeps_it(self):
        remote = self.use(_Remote())
        self.acquire('issue-5')
        self.assertTrue(wf.release_claim('issue-5'))
        self.assertEqual(remote.labels[5], [])
        self.assertIn(MINE, remote.repo_labels)
        self.assertFalse(any(m == 'DELETE' and '/labels/' in p and '/issues/' not in p
                             for m, p, _ in remote.rest))

    def test_release_takes_the_label_off_that_item_only(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        self.acquire('issue-6')
        self.assertEqual(wf.release_claims(['issue-5']), {'issue-5': True})
        self.assertEqual((remote.labels[5], remote.labels[6]), ([], [MINE]))

    def test_exit_cleanup_on_an_unbuilt_story_takes_the_label_off(self):
        remote = self.use(_Remote())
        self.acquire('issue-5')
        args = wf.build_parser().parse_args(['exit-cleanup', '--issue', '5'])
        with mock.patch.object(wf, 'reap_finished', lambda: 0),                 mock.patch.object(wf, 'tree_entries', lambda: []),                 contextlib.redirect_stdout(io.StringIO()),                 contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                wf.cmd_exit_cleanup(args)
        self.assertEqual(remote.labels[5], [])

    def test_a_ref_release_that_leaves_the_label_is_not_released(self):
        remote = self.use(_Remote())
        self.acquire('issue-5')
        real = remote.gh_rest

        def failing(path, method='GET', body=None):
            if method == 'DELETE' and '/issues/' in path:
                return False, None, 'HTTP 502'
            return real(path, method, body)
        with mock.patch.object(wf, 'gh_rest', failing),                 contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(wf.release_claim('issue-5'))
            self.assertEqual(wf.release_claims(['issue-5']), {'issue-5': False})
        self.assertEqual(self.marker('issue-5'), 'sha1')
        self.assertTrue(wf.release_claim('issue-5'))
        self.assertEqual(remote.labels[5], [])


class TestFinishedWorkKeepsTheLabel(_Case):

    def test_handoff_leaves_the_label_on_the_issue_in_review(self):
        remote = self.use(_Remote())
        self.acquire('issue-5')
        self.assertEqual(wf.release_claims(['issue-5'], keep_label=True), {'issue-5': True})
        self.assertEqual(remote.labels[5], [MINE])
        self.assertIsNone(self.marker('issue-5'))

    def test_exit_cleanup_after_the_handoff_leaves_the_label(self):
        remote = self.use(_Remote())
        self.acquire('issue-5')
        wf.release_claims(['issue-5'], keep_label=True)
        self.assertTrue(wf.release_claim('issue-5'))
        self.assertEqual(remote.labels[5], [MINE])

    def test_a_closed_completed_issue_keeps_the_label_at_release(self):
        remote = self.use(_Remote(push_err=REFUSED))
        self.acquire('issue-5')
        remote.closed.add(5)
        self.assertTrue(wf.release_claim('issue-5'))
        self.assertEqual(remote.labels[5], [MINE])
        self.assertIsNone(self.marker('issue-5'))

    def test_a_merged_pull_request_keeps_the_label_at_exit_cleanup(self):
        remote = self.use(_Remote())
        self.acquire('pr-7')
        remote.merged.add(7)
        self.assertEqual(wf.release_claims(['pr-7']), {'pr-7': True})
        self.assertEqual(remote.labels[7], [MINE])

    def test_reap_never_strips_finished_work(self):
        remote = self.use(_Remote(refs={'refs/claims/issue-5'}, labels={5: [RIVAL]}))
        remote.closed.add(5)
        self.assertTrue(wf.release_claim('issue-5', every_label=True))
        self.assertEqual(remote.labels[5], [RIVAL])


class TestUnreadableOrder(_Case):

    def test_a_rival_label_with_no_event_read_is_no_win(self):
        remote = self.use(_Remote(push_err=REFUSED, labels={5: [RIVAL]}))
        remote.events[5] = []
        outcome, _ = self.acquire('issue-5')
        self.assertEqual(outcome, 'error')
        self.assertEqual(remote.labels[5], [RIVAL])
        self.assertIsNone(self.marker('issue-5'))


class TestReapFreesCrashedClaims(_Case):

    def _reap(self, remote, refs, target_state):
        args = wf.build_parser().parse_args(['claim-reap'])
        buf = io.StringIO()
        with mock.patch.object(wf, 'list_claim_refs', lambda: (refs, '')),                 mock.patch.object(wf, 'claim_age_hours', lambda sha: 9),                 mock.patch.object(wf, 'claim_target_state', target_state),                 contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                wf.cmd_claim_reap(args)
        return json.loads(buf.getvalue())

    def test_a_crashed_local_claim_loses_its_label_and_the_story_can_be_claimed(self):
        remote = self.use(_Remote(refs={'refs/claims/issue-5'}, labels={5: [RIVAL]}))
        payload = self._reap(remote, [('sha0', 'issue-5')],
                             lambda cfg, t: ('issue', 5, 'OPEN', [], False, False))
        self.assertEqual([e['ref'] for e in payload['reaped']], ['refs/claims/issue-5'])
        self.assertEqual(remote.labels[5], [])
        self.assertNotIn('refs/claims/issue-5', remote.refs)
        self.assertEqual(self.acquire('issue-5')[0], 'won')

    def test_a_crashed_cloud_claim_held_by_its_label_alone_is_reaped(self):
        remote = self.use(_Remote(labels={6: [RIVAL]}))
        payload = self._reap(remote, [],
                             lambda cfg, t: ('issue', 6, 'OPEN', [], False, False))
        self.assertEqual([e['ref'] for e in payload['reaped']], ['label:' + RIVAL])
        self.assertEqual(remote.labels[6], [])
        self.assertEqual(self.acquire('issue-6')[0], 'won')

    def test_an_issue_in_review_keeps_the_label_handoff_left(self):
        remote = self.use(_Remote(labels={6: [RIVAL]}))
        payload = self._reap(remote, [],
                             lambda cfg, t: ('issue', 6, 'OPEN', [], True, False))
        self.assertEqual(payload['reaped'], [])
        self.assertEqual(remote.labels[6], [RIVAL])

    def test_a_live_cloud_claim_is_left_alone(self):
        remote = self.use(_Remote(labels={6: [RIVAL]}))
        payload = self._reap(remote, [],
                             lambda cfg, t: ('issue', 6, 'OPEN', [], False, True))
        self.assertEqual(payload['reaped'], [])
        self.assertEqual(remote.labels[6], [RIVAL])


class TestBatchedRelease(_Case):

    def test_many_labels_come_off_in_one_graphql_read_and_one_mutation(self):
        wf_io.reset_graphql_state()
        calls = []

        def graphql(query, **fields):
            calls.append(query)
            if query.startswith('query'):
                return True, {'repository': {
                    'label': {'id': 'L_me'},
                    't0': {'id': 'I_5'}, 't1': {'id': 'PR_7'}}}, ''
            return True, {}, ''
        with mock.patch.object(wf, 'gh_graphql', graphql):
            done = wf_claim_label.remove_session_labels(['issue-5', 'pr-7'])
        self.assertEqual(done, {'issue-5': True, 'pr-7': True})
        self.assertEqual(len(calls), 2)
        self.assertIn('labelableId: "I_5"', calls[1])
        self.assertIn('labelableId: "PR_7"', calls[1])
        self.assertIn('L_me', calls[1])

    def test_a_failed_batch_falls_back_to_one_request_each(self):
        wf_io.reset_graphql_state()
        remote = self.use(_Remote(labels={5: [MINE], 6: [MINE]}))
        with mock.patch.object(wf, 'gh_graphql', lambda q, **f: (False, None, 'HTTP 502')):
            done = wf_claim_label.remove_session_labels(['issue-5', 'issue-6'])
        self.assertEqual(done, {'issue-5': True, 'issue-6': True})
        self.assertEqual((remote.labels[5], remote.labels[6]), ([], []))


class TestSessionGuid(_Case):

    def test_the_id_the_session_start_hook_recorded_comes_first(self):
        with mock.patch.dict(os.environ, {wf_claim_label.SESSION_ENV: 'hook-id',
                                          wf_claim_label.CLAUDE_SESSION_ENV: 'env-id'}):
            wf_claim_label.reset_claim_label_state()
            self.assertEqual(wf_claim_label.session_label(), 'session: hook-id')

    def test_the_claude_session_id_names_the_session(self):
        with mock.patch.dict(os.environ, {wf_claim_label.SESSION_ENV: '',
                                          wf_claim_label.CLAUDE_SESSION_ENV:
                                          'f0028945-9bea-4127-ae04-221153a20946'}):
            wf_claim_label.reset_claim_label_state()
            self.assertEqual(wf_claim_label.session_label(),
                             'session: f0028945-9bea-4127-ae04-221153a20946')

    def test_outside_claude_code_the_checkout_keeps_one_guid(self):
        with mock.patch.dict(os.environ, {wf_claim_label.SESSION_ENV: '',
                                          wf_claim_label.CLAUDE_SESSION_ENV: ''}):
            wf_claim_label.reset_claim_label_state()
            first = wf_claim_label.session_guid()
            wf_claim_label.reset_claim_label_state()
            self.assertEqual(wf_claim_label.session_guid(), first)
            self.assertLessEqual(len(wf_claim_label.session_label()), 50)


class TestReap(_Case):

    def test_reap_deletes_only_labels_no_item_carries_open_or_closed(self):
        remote = self.use(_Remote(labels={5: [RIVAL]}))
        remote.closed.add(5)
        remote.repo_labels.add('session: gone-guid')
        remote.repo_labels.add('bug')
        deleted, failed = wf_claim_label.reap_session_labels()
        self.assertEqual(deleted, ['session: gone-guid'])
        self.assertEqual(failed, [])
        self.assertEqual(remote.repo_labels, {RIVAL, 'bug'})

    def test_a_dry_run_deletes_nothing(self):
        remote = self.use(_Remote())
        remote.repo_labels.add('session: gone-guid')
        deleted, _ = wf_claim_label.reap_session_labels(dry_run=True)
        self.assertEqual(deleted, ['session: gone-guid'])
        self.assertIn('session: gone-guid', remote.repo_labels)


if __name__ == '__main__':
    unittest.main()
