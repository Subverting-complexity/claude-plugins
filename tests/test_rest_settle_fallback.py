#!/usr/bin/env python3
"""
Settling a merge through REST, where GraphQL is blocked.

`post-merge` reads the merged pull request, closes the issues it closes, sets
them to Done with their release notes, closes a parent the merge finished and
releases what waited on them. In a session that refuses GraphQL every one of
those steps failed and the agent did them by hand. These tests drive the
command against a fake GitHub that answers GraphQL with HTTP 403, and check
each write lands and is read back.

Run standalone (`python3 tests/test_rest_settle_fallback.py`) or via `run-tests.sh`.
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'))
import wf  # noqa: E402
import wf_io  # noqa: E402
import wf_rest  # noqa: E402
import wf_rest_settle  # noqa: E402


REPO = 'acme/widgets'
BASE = 'repos/%s/' % REPO
GRAPHQL_403 = (1, '', 'HTTP 403: Forbidden (https://api.github.com/graphql)')
FIELDS = {'Stage': (501, 'single_select'), 'Priority': (502, 'single_select'),
          'Effort': (503, 'single_select'), 'Ownership': (504, 'single_select'),
          'User release notes': (601, 'text'),
          'Internal release notes': (602, 'text')}
NAME_OF = {fid: name for name, (fid, _kind) in FIELDS.items()}
NOTES_COMMENT = ('<!-- synergy:release-notes -->\n```json\n'
                 '{"5": {"user": "* Sync finishes faster.", "internal": "* Moved the sync to REST."}}\n```')


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'labels': {}, 'review_labels': {}, 'fields': {}}


def _issues():
    """#4 is a Feature over #5 only, so closing #5 finishes it. #7 is Blocked
    on #5 and nothing else, so the merge releases it."""
    return {
        4: {'type': 'Feature', 'state': 'open', 'parent': None, 'labels': [],
            'values': {'Stage': 'In Progress'}},
        5: {'type': 'User Story', 'state': 'open', 'parent': 4, 'labels': [],
            'values': {'Stage': 'In Review'}},
        7: {'type': 'Bug', 'state': 'open', 'parent': None, 'labels': [],
            'blockers': [5],
            'values': {'Stage': 'Blocked', 'Ownership': 'Code agent',
                       'Priority': 'Low', 'Effort': 'Low'}},
    }


class _GitHub(object):
    """GitHub with GraphQL refused, answering the REST calls a merge makes."""

    def __init__(self, store_texts=True, pr_body='Work.\n\nCloses #5',
                 labels=('release: app',), note_fields=True):
        self.issues = _issues()
        self.store_texts = store_texts
        self.note_fields = note_fields
        self.pr_body = pr_body
        self.repo_labels = set(labels)
        self.calls, self.comments, self.writes, self.added = [], [], [], []

    def run(self, cmd, input_text=None):
        self.calls.append(list(cmd))
        if cmd[:3] == ['gh', 'api', 'graphql'] or cmd[:2] in (['gh', 'pr'], ['gh', 'issue']):
            return GRAPHQL_403
        if cmd[:2] == ['gh', 'api'] and '-X' in cmd:
            method, path = cmd[cmd.index('-X') + 1], cmd[cmd.index('-X') + 2]
            return self._rest(method, path, json.loads(input_text) if input_text else None)
        return 1, '', 'unexpected command %r' % cmd

    def _values(self, issue):
        out = []
        for name, value in issue['values'].items():
            fid, kind = FIELDS[name]
            entry = {'issue_field_id': fid, 'issue_field_name': name, 'data_type': kind}
            if kind == 'single_select':
                entry.update(value=1, single_select_option={'id': 1, 'name': value})
            else:
                entry['value'] = value
            out.append(entry)
        return out

    def _raw(self, number):
        issue = self.issues[number]
        raw = {'node_id': 'I_%d' % number, 'number': number, 'title': 'Issue %d' % number,
               'body': '', 'html_url': 'https://github.com/%s/issues/%d' % (REPO, number),
               'state': issue['state'], 'assignees': [], 'milestone': None,
               'labels': [{'name': n, 'node_id': 'L_%s' % n} for n in issue['labels']],
               'type': {'name': issue['type']},
               'issue_field_values': self._values(issue),
               'issue_dependencies_summary': {
                   'total_blocked_by': len(issue.get('blockers') or ())}}
        if issue['parent']:
            raw['parent_issue_url'] = 'https://api.github.com/repos/%s/issues/%d' % (
                REPO, issue['parent'])
        return raw

    def _number(self, path):
        return int(path[len(BASE + 'issues/'):].split('/')[0].split('?')[0])

    def _rest(self, method, path, body):
        if method == 'GET' and path == BASE + 'pulls/50':
            return 0, json.dumps({'number': 50, 'state': 'closed',
                                  'merged_at': '2026-10-24T00:00:00Z', 'body': self.pr_body,
                                  'base': {'ref': 'main'}, 'head': {'ref': 'feature/5/x'}}), ''
        if method == 'GET' and path.startswith(BASE + 'issues/50/comments'):
            return 0, json.dumps([{'body': 'Looks good'}, {'body': NOTES_COMMENT}]), ''
        if method == 'GET' and path.startswith(BASE + 'issues?state=open'):
            return 0, json.dumps([self._raw(n) for n in sorted(self.issues)
                                  if self.issues[n]['state'] == 'open']), ''
        if method == 'GET' and path.startswith(BASE + 'pulls?state=open'):
            return 0, '[]', ''
        if method == 'GET' and path == 'orgs/acme/issue-fields':
            return 0, json.dumps([{'id': fid, 'name': name}
                                  for name, (fid, kind) in FIELDS.items()
                                  if self.note_fields or kind != 'text']), ''
        if method == 'GET' and path.startswith(BASE + 'labels/'):
            name = path[len(BASE + 'labels/'):].replace('%3A', ':').replace('%20', ' ')
            return (0, '{}', '') if name in self.repo_labels else (1, '', 'HTTP 404')
        if path.startswith(BASE + 'issues/'):
            number = self._number(path)
            if number not in self.issues:
                return 1, '', 'gh: Not Found (HTTP 404)'
            issue = self.issues[number]
            tail = path[len(BASE + 'issues/%d' % number):]
            if method == 'GET' and tail == '':
                return 0, json.dumps(self._raw(number)), ''
            if method == 'GET' and tail.startswith('/sub_issues'):
                return 0, json.dumps([{'number': n, 'state': i['state']}
                                      for n, i in self.issues.items()
                                      if i['parent'] == number]), ''
            if method == 'GET' and tail.startswith('/dependencies/blocked_by'):
                return 0, json.dumps([
                    {'number': n, 'state': self.issues[n]['state'], 'title': 'Issue %d' % n,
                     'repository_url': 'https://api.github.com/repos/%s' % REPO}
                    for n in issue.get('blockers') or ()]), ''
            if method == 'GET' and tail == '/issue-field-values':
                return 0, json.dumps(self._values(issue)), ''
            if method == 'POST' and tail == '/comments':
                self.comments.append((number, body['body']))
                return 0, '{}', ''
            if method == 'PATCH' and tail == '':
                issue['state'] = body['state']
                return 0, json.dumps(self._raw(number)), ''
            if method == 'POST' and tail == '/issue-field-values':
                self.writes.append((number, body['issue_field_values']))
                for value in body['issue_field_values']:
                    name = NAME_OF[value['field_id']]
                    if FIELDS[name][1] == 'text' and not self.store_texts:
                        continue
                    issue['values'][name] = value['value']
                return 0, json.dumps(self._values(issue)), ''
            if method == 'DELETE' and tail.startswith('/labels/'):
                issue['labels'].remove(tail[len('/labels/'):].replace('%20', ' '))
                return 0, '', ''
            if method == 'POST' and tail == '/labels':
                self.added.append((number, body['labels']))
                issue['labels'].extend(body['labels'])
                return 0, '[]', ''
        return 1, '', 'unexpected REST call %s %s' % (method, path)


class _Base(unittest.TestCase):

    def setUp(self):
        wf_io.reset_graphql_state()
        wf_rest.reset_rest_state()
        self.addCleanup(wf_io.reset_graphql_state)
        self.addCleanup(wf_rest.reset_rest_state)
        os.environ.pop(wf_io.GRAPHQL_ENV, None)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, '.claude'))
        for name, value in (('repo_root', lambda: self.root), ('prepare_cfg', _cfg)):
            patch = mock.patch.object(wf, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def _call(self, hub, argv):
        args = wf.build_parser().parse_args(argv)
        out, err = io.StringIO(), io.StringIO()
        code = None
        with mock.patch.object(wf, 'run', hub.run), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                args.func(args)
            except SystemExit as exc:
                code = exc.code
        text = out.getvalue()
        return code, (json.loads(text) if text.strip() else None), err.getvalue()

    def _quiet(self, hub, func, *args):
        wf_io.mark_graphql_blocked()
        with mock.patch.object(wf, 'run', hub.run), \
                contextlib.redirect_stderr(io.StringIO()):
            return func(*args)


class TestPostMergeThroughRest(_Base):

    def test_a_merge_settles_its_issues_parent_and_dependants(self):
        hub = _GitHub()
        code, payload, notice = self._call(hub, ['post-merge', '--pr', '50'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertIn('REST', notice)
        self.assertEqual(payload['settled'], [5])
        # The story: closed with its comment, Done, and its notes read back.
        story = hub.issues[5]
        self.assertEqual(story['state'], 'closed')
        self.assertIn((5, 'Closing — resolved by merged PR #50.'), hub.comments)
        self.assertEqual(story['values']['Stage'], 'Done')
        self.assertEqual(story['values']['User release notes'], '* Sync finishes faster.')
        self.assertEqual(story['values']['Internal release notes'],
                         '* Moved the sync to REST.')
        self.assertEqual(sorted(payload['release_notes']['5']),
                         ['Internal release notes', 'User release notes'])
        # The Feature the story finished: closed and Done.
        self.assertEqual(hub.issues[4]['state'], 'closed')
        self.assertEqual(hub.issues[4]['values']['Stage'], 'Done')
        self.assertEqual([c['issue'] for c in payload['containers_closed']], [4])
        # What waited on the story: out of Blocked.
        self.assertEqual(hub.issues[7]['values']['Stage'], 'Backlog')
        self.assertEqual([r['issue'] for r in payload['released']], [7])
        # GraphQL was tried once, by the pull request read, and never again.
        refused = [c for c in hub.calls
                   if c[:3] == ['gh', 'api', 'graphql'] or c[:2] in (['gh', 'pr'], ['gh', 'issue'])]
        self.assertEqual(refused, [hub.calls[0]])

    def test_notes_github_did_not_store_are_reported_and_the_stage_still_lands(self):
        hub = _GitHub(store_texts=False)
        code, payload, _ = self._call(hub, ['post-merge', '--pr', '50', '--no-unblock'])
        self.assertEqual(code, wf.EXIT_PARTIAL, payload)
        self.assertEqual(hub.issues[5]['values']['Stage'], 'Done')
        entry = payload['settled'][0]
        self.assertTrue(entry['stage_set'])
        self.assertIn('did not read back', entry['release_notes']['error'])
        self.assertIn('#5 release notes not written', payload['reason'])

    def test_notes_whose_field_cannot_be_found_are_a_gap_not_skipped(self):
        """No issue, cache or org list shows the notes fields' ids. The fields
        may exist all the same, so the notes are reported as not written."""
        hub = _GitHub(note_fields=False)
        code, payload, _ = self._call(hub, ['post-merge', '--pr', '50', '--no-unblock'])
        self.assertEqual(code, wf.EXIT_PARTIAL, payload)
        self.assertEqual(hub.issues[5]['values']['Stage'], 'Done')
        self.assertIn('could not be found through REST',
                      payload['settled'][0]['release_notes']['error'])

    def test_a_closed_issue_has_its_retired_label_taken_off(self):
        hub = _GitHub()
        hub.issues[5].update(state='closed', labels=['status-in-review'])
        code, payload, _ = self._call(hub, ['post-merge', '--pr', '50', '--no-unblock'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(hub.issues[5]['labels'], [])
        self.assertEqual(payload['cleared'], {'5': 'status-in-review'})
        # Already closed, so no second close and no closing comment.
        self.assertNotIn(5, [n for n, _b in hub.comments])

    def test_an_issue_with_no_closing_keyword_is_not_settled(self):
        """REST has no closingIssuesReferences, so the body is the source."""
        hub = _GitHub(pr_body='Work for #5, linked by hand.')
        code, payload, _ = self._call(hub, ['post-merge', '--pr', '50', '--no-unblock'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(payload['settled'], [])
        self.assertEqual(hub.issues[5]['state'], 'open')

    def test_an_issue_named_with_issue_is_settled_without_a_keyword(self):
        hub = _GitHub(pr_body='Work for #5, linked by hand.')
        code, payload, _ = self._call(hub, ['post-merge', '--pr', '50', '--issue', '5',
                                            '--no-unblock'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(hub.issues[5]['state'], 'closed')


class TestSettleMergedThroughRest(_Base):

    def test_only_merged_pull_requests_are_listed(self):
        def run(cmd, input_text=None):
            return 0, json.dumps([
                {'number': 52, 'merged_at': None, 'body': 'Closes #6'},
                {'number': 51, 'merged_at': '2026-10-24T00:00:00Z', 'body': 'Fixes #5'},
            ]), ''
        ok, prs, err = self._quiet(argparse.Namespace(run=run), wf_rest_settle.rest_merged_prs,
                                   _cfg(), 30)
        self.assertTrue(ok, err)
        self.assertEqual(prs, [{'number': 51, 'closingIssuesReferences': [{'number': 5}]}])


class TestPartsThroughRest(_Base):

    def test_a_release_label_goes_on_through_rest(self):
        hub = _GitHub()
        ok, err = self._quiet(hub, wf.add_release_labels, _cfg(), 5, ['release: app'])
        self.assertTrue(ok, err)
        self.assertEqual(hub.added, [(5, ['release: app'])])

    def test_a_missing_release_label_is_refused_not_created_grey(self):
        hub = _GitHub(labels=())
        ok, err = self._quiet(hub, wf.add_release_labels, _cfg(), 5, ['release: app'])
        self.assertFalse(ok)
        self.assertIn('labels-ensure', err)
        self.assertEqual(hub.added, [])

    def test_a_parent_in_another_repository_ends_the_walk_unread(self):
        hub = _GitHub()
        hub.issues[5]['parent'] = None
        raw5 = hub._raw(5)
        raw5['parent_issue_url'] = 'https://api.github.com/repos/other/repo/issues/9'
        answers = {BASE + 'issues/5': raw5,
                   'repos/other/repo/issues/9': dict(hub._raw(4), number=9)}

        def run(cmd, input_text=None):
            path = cmd[cmd.index('-X') + 2]
            hub.calls.append(path)
            return (0, json.dumps(answers[path]), '') if path in answers else (1, '', 'no')
        ok, chain, err = self._quiet(argparse.Namespace(run=run),
                                     wf_rest_settle.rest_parent_chain, _cfg(), 5, 4)
        self.assertTrue(ok, err)
        self.assertEqual([n['number'] for n in chain], [9])
        self.assertEqual(chain[0]['repository'], {'nameWithOwner': 'other/repo'})
        self.assertFalse([p for p in hub.calls if 'sub_issues' in p])

    def test_a_graphql_field_input_is_written_by_name_through_rest(self):
        """A notes input built while the capability record was cached names
        its field by GraphQL id; the REST write finds the name from the cache."""
        hub = _GitHub()
        cache = {'field_map': {'User release notes': {'id': 'GQL_U', 'data_type': 'text'}}}
        with mock.patch.object(wf, 'load_capability_cache', lambda root=None: cache), \
                mock.patch.object(wf, 'merge_capability_cache', lambda values, root=None: None):
            out = self._quiet(hub, wf.set_stages, _cfg(), {5: 'Done'}, None,
                              {5: [{'fieldId': 'GQL_U', 'textValue': '* Faster sync'}]})
        self.assertEqual(out[5], (True, 'Stage set to Done'))
        self.assertEqual(hub.writes, [(5, [{'field_id': 501, 'value': 'Done'},
                                           {'field_id': 601, 'value': '* Faster sync'}])])

    def test_a_field_input_with_an_unknown_id_writes_nothing(self):
        hub = _GitHub()
        with mock.patch.object(wf, 'load_capability_cache', lambda root=None: {}), \
                mock.patch.object(wf, 'merge_capability_cache', lambda values, root=None: None):
            written, message = self._quiet(hub, wf.set_stages, _cfg(), {5: 'Done'}, None,
                                           {5: [{'fieldId': 'GQL_X', 'textValue': 'x'}]})[5]
        self.assertFalse(written)
        self.assertIn('capability cache', message)
        self.assertEqual(hub.writes, [])


if __name__ == '__main__':
    unittest.main()
