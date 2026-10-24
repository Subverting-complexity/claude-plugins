#!/usr/bin/env python3
"""
The REST fallback for pull requests, where GraphQL is blocked.

`gh pr create`, `gh pr view`, `gh pr list`, `gh pr edit` and `gh pr checkout`
read through GraphQL inside `gh`, so a session that refuses GraphQL could not
open a pull request, find the next one to review or move its review labels.
These tests check that `pr-create`, the review pool, `sibling-pr` and the
label edits go through REST there and give what the GraphQL path gives, and
that with GraphQL on nothing goes through REST.

Run standalone (`python3 tests/test_rest_pr_fallback.py`) or via `run-tests.sh`.
"""

import argparse
import contextlib
import copy
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
import wf_core  # noqa: E402
import wf_io  # noqa: E402
import wf_rest  # noqa: E402


REPO = 'acme/widgets'
GRAPHQL_403 = (1, '', 'HTTP 403: Forbidden (https://api.github.com/graphql)')
NAMES = wf_core.review_names({})


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'labels': {}, 'review_labels': {}, 'fields': {}}


def _pr(number, labels=(), body='', draft=False, head='a' * 40, posts=(),
        reviews=(), assignee=None):
    return {'number': number, 'title': 'PR %d' % number, 'labels': list(labels),
            'body': body, 'draft': draft, 'head': head,
            'branch': 'feature/%d/x' % number, 'posts': list(posts),
            'reviews': list(reviews), 'assignee': assignee}


# Oldest first. #10 was reviewed at its head; #11's head moved since its
# review; #12 is new and unlabelled; #13 is a draft; #14 is under review;
# #15 asks for a re-review.
PRS = [
    _pr(10, [NAMES['approved']], 'Closes #5', head='b' * 40,
        posts=[('Reviewed at `bbbbbbb`', '2026-10-01T00:00:00Z')]),
    _pr(11, [NAMES['changes-requested']], 'Fixes #6', head='c' * 40,
        reviews=[('Reviewed at `ddddddd`', '2026-10-02T00:00:00Z')]),
    _pr(12, [], 'Work for #7, closes #7', assignee='builder'),
    _pr(13, [NAMES['needs-review']], draft=True),
    _pr(14, [NAMES['reviewing']]),
    _pr(15, [NAMES['needs-re-review']], 'Resolves acme/widgets#8',
        posts=[('Reviewed at `aaaaaaa`', '2026-10-03T00:00:00Z')]),
]


def _graphql_pr(pr):
    return {
        'number': pr['number'], 'title': pr['title'],
        'url': 'https://github.com/%s/pull/%d' % (REPO, pr['number']),
        'headRefName': pr['branch'], 'headRefOid': pr['head'], 'isDraft': pr['draft'],
        'labels': {'nodes': [{'name': n} for n in pr['labels']]},
        'comments': {'nodes': [{'body': b, 'createdAt': t} for b, t in pr['posts']]},
        'reviews': {'nodes': [{'body': b, 'createdAt': t} for b, t in pr['reviews']]},
        'closingIssuesReferences': {'nodes': [
            {'number': n} for n in wf_core.body_closing_numbers(pr['body'], REPO)]},
    }


def _rest_pr(pr):
    return {
        'number': pr['number'], 'title': pr['title'], 'state': 'open',
        'merged_at': None, 'body': pr['body'], 'draft': pr['draft'],
        'html_url': 'https://github.com/%s/pull/%d' % (REPO, pr['number']),
        'labels': [{'name': n} for n in pr['labels']],
        'head': {'ref': pr['branch'], 'sha': pr['head'],
                 'repo': {'full_name': REPO}},
        'assignees': [{'login': pr['assignee']}] if pr['assignee'] else [],
    }


class _GitHub(object):
    """Answers `gh` and `git` as GitHub would, with GraphQL on or blocked."""

    def __init__(self, graphql=True, prs=None, labels=None):
        self.graphql = graphql
        self.prs = {p['number']: copy.deepcopy(p)
                    for p in (prs if prs is not None else PRS)}
        self.repo_labels = set(labels if labels is not None
                               else wf_core.REVIEW_DEFAULT_LABELS.values())
        self.calls = []
        self.grey = []
        self.created = []
        self.edited = []

    def rest_calls(self):
        return [c for c in self.calls if c[:2] == ['gh', 'api'] and c[2:3] != ['graphql']]

    def run(self, cmd, input_text=None):
        self.calls.append(list(cmd))
        if cmd[:1] == ['git']:
            if cmd[:3] == ['git', 'rev-parse', '--abbrev-ref']:
                return 0, 'feature/5/x\n', ''
            if cmd[:3] == ['git', 'rev-parse', '--verify']:
                return 1, '', ''
            return 0, '', ''
        if cmd[:3] == ['gh', 'api', 'graphql']:
            if not self.graphql:
                return GRAPHQL_403
            return 0, json.dumps({'data': {'repository': {'pullRequests': {
                'pageInfo': {'hasNextPage': False},
                'nodes': [_graphql_pr(p) for p in self.prs.values()]}}}}), ''
        if cmd[:2] == ['gh', 'label']:
            self.repo_labels.add(cmd[3])
            return 0, '', ''
        if cmd[:2] == ['gh', 'pr']:
            if not self.graphql:
                return GRAPHQL_403
            return self._gh_pr(cmd)
        if cmd[:2] == ['gh', 'api'] and '-X' in cmd:
            method, path = cmd[cmd.index('-X') + 1], cmd[cmd.index('-X') + 2]
            return self._rest(method, path, json.loads(input_text) if input_text else None)
        return 1, '', 'unexpected command %r' % cmd

    def _gh_pr(self, cmd):
        if cmd[2] == 'create':
            self.created.append(cmd)
            return 0, 'https://github.com/%s/pull/42\n' % REPO, ''
        if cmd[2] == 'view':
            pr = self.prs.get(int(cmd[3]))
            return 0, json.dumps({'number': pr['number'], 'url': 'u', 'body': pr['body'],
                                  'labels': [{'name': n} for n in pr['labels']]}), ''
        if cmd[2] == 'edit':
            pr = self.prs[int(cmd[3])]
            for flag, name in zip(cmd, cmd[1:]):
                if flag == '--remove-label' and name in pr['labels']:
                    pr['labels'].remove(name)
                if flag == '--add-label':
                    pr['labels'].append(name)
            return 0, '', ''
        return 0, '', ''

    def _rest(self, method, path, body):
        base = 'repos/%s/' % REPO
        if path == 'user':
            return 0, json.dumps({'login': 'builder'}), ''
        if method == 'POST' and path == base + 'pulls':
            self.created.append(body)
            self.prs[42] = _pr(42, body=body['body'])
            self.prs[42]['branch'] = body['head']
            return 0, json.dumps(_rest_pr(self.prs[42])), ''
        if method == 'GET' and path.startswith(base + 'pulls?state=open'):
            if 'sort=created' not in path or 'direction=asc' not in path:
                return 1, '', 'the open pull requests were not read oldest first'
            page = int(path.rsplit('page=', 1)[1])
            items = [_rest_pr(p) for p in self.prs.values()] if page == 1 else []
            return 0, json.dumps(items), ''
        if method == 'GET' and path.startswith(base + 'pulls/') and '/reviews' in path:
            number = int(path.split('/pulls/')[1].split('/')[0])
            page = int(path.rsplit('page=', 1)[1])
            reviews = self.prs[number]['reviews'] if page == 1 else []
            return 0, json.dumps([{'body': b, 'submitted_at': t} for b, t in reviews]), ''
        if method == 'GET' and '/comments' in path:
            number = int(path.split('/issues/')[1].split('/')[0])
            page = int(path.rsplit('page=', 1)[1])
            posts = self.prs[number]['posts'] if page == 1 else []
            return 0, json.dumps([{'body': b, 'created_at': t} for b, t in posts]), ''
        if method == 'GET' and path.startswith(base + 'pulls/'):
            number = int(path.split('/pulls/')[1])
            return 0, json.dumps(_rest_pr(self.prs[number])), ''
        if method == 'PATCH' and path.startswith(base + 'pulls/'):
            self.edited.append(body)
            return 0, '{}', ''
        if method == 'GET' and path.startswith(base + 'labels/'):
            name = path.split('/labels/')[1]
            return (0, '{}', '') if name in self.repo_labels else (
                1, '', 'gh: Not Found (HTTP 404)')
        if method == 'GET' and path.startswith(base + 'labels?'):
            return 0, json.dumps([{'name': n, 'color': 'ededed', 'description': ''}
                                  for n in sorted(self.repo_labels)]), ''
        if method == 'DELETE' and '/labels/' in path:
            number = int(path.split('/issues/')[1].split('/')[0])
            name = path.rsplit('/', 1)[1]
            if name not in self.prs[number]['labels']:
                return 1, '', 'gh: Label does not exist (HTTP 404)'
            self.prs[number]['labels'].remove(name)
            return 0, '[]', ''
        if method == 'POST' and path.endswith('/labels'):
            number = int(path.split('/issues/')[1].split('/')[0])
            for name in body['labels']:
                # GitHub creates a label it lacks, grey and undescribed.
                if name not in self.repo_labels:
                    self.repo_labels.add(name)
                    self.grey.append(name)
            self.prs[number]['labels'].extend(body['labels'])
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
        for name, value in (('repo_root', lambda: self.root),
                            ('prepare_cfg', _cfg)):
            patch = mock.patch.object(wf, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def _call(self, hub, func, args):
        out, err = io.StringIO(), io.StringIO()
        code = None
        with mock.patch.object(wf, 'run', hub.run), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                func(args)
            except SystemExit as exc:
                code = exc.code
        text = out.getvalue()
        return code, (json.loads(text) if text.strip() else None), err.getvalue()

    def _quiet(self, hub, func, *args):
        with mock.patch.object(wf, 'run', hub.run), \
                contextlib.redirect_stderr(io.StringIO()):
            return func(*args)


class TestPrCreate(_Base):

    def _create(self, hub):
        body = os.path.join(self.root, 'pr.md')
        with open(body, 'w', encoding='utf-8') as fh:
            fh.write('## Summary\n\nBuilt the thing.\n')
        return self._call(hub, wf.cmd_pr_create, argparse.Namespace(
            body_file=body, issue=[5], title='Build the thing', base=None))

    def test_a_pull_request_opens_through_rest(self):
        hub = _GitHub(graphql=False, prs=[])
        code, payload, notice = self._create(hub)
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(payload['pr'], 42)
        self.assertIn('REST', notice)
        sent = hub.created[0]
        self.assertEqual((sent['title'], sent['head'], sent['base']),
                         ('Build the thing', 'feature/5/x', 'main'))
        self.assertIn('Built the thing.', sent['body'])
        self.assertIn('Closes #5', sent['body'])
        # The switch came at the duplicate check, so `gh pr create` never ran.
        self.assertFalse([c for c in hub.calls if c[:3] == ['gh', 'pr', 'create']])

    def test_a_sibling_is_flagged_through_rest(self):
        hub = _GitHub(graphql=False, prs=[_pr(9, body='Closes #5')])
        code, payload, _ = self._create(hub)
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(payload['duplicates'], [{'issue': 5, 'pr': 9, 'title': 'PR 9'}])
        self.assertTrue(hub.created[0]['body'].startswith('> ⚠ Possible duplicate of #9'))

    def test_with_graphql_on_nothing_goes_through_rest(self):
        hub = _GitHub(graphql=True, prs=[_pr(42, body='Built.\n\nCloses #5')])
        code, payload, notice = self._create(hub)
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(notice, '')
        self.assertEqual(hub.rest_calls(), [])
        self.assertEqual(hub.created[0][:3], ['gh', 'pr', 'create'])


class TestReviewPool(_Base):

    def _pool(self, graphql):
        hub = _GitHub(graphql=graphql)
        ok, prs, err = self._quiet(hub, wf.assemble_review_prs, _cfg())
        self.assertTrue(ok, err)
        return prs, hub

    def test_rest_reads_the_pool_graphql_reads(self):
        graphql, _ = self._pool(True)
        rest, hub = self._pool(False)
        self.assertEqual(rest, graphql)
        # A draft is never picked, so its comments and reviews are not read.
        self.assertFalse([c for c in hub.calls if '/13/' in ' '.join(c)])

    def test_the_same_pull_request_is_next_either_way(self):
        graphql, _ = self._pool(True)
        rest, _ = self._pool(False)
        order = lambda prs: [p['number'] for p in wf_core.select_review_next(prs, NAMES)]
        self.assertEqual(order(rest), order(graphql))
        self.assertEqual(order(rest), [15, 11, 12])

    def test_review_next_claims_and_marks_through_rest(self):
        hub = _GitHub(graphql=False)
        with mock.patch.object(wf, 'acquire_claim', lambda target: 'won'):
            code, payload, _ = self._call(hub, wf.cmd_review_next,
                                          argparse.Namespace(checkout=True, no_claim=False))
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(payload['number'], 15)
        self.assertTrue(payload['checked_out'], payload)
        self.assertEqual(hub.prs[15]['labels'], [NAMES['reviewing']])
        self.assertIn(['git', 'checkout', '-b', 'feature/15/x', '--track',
                       'origin/feature/15/x'], hub.calls)

    def test_my_pull_requests_come_through_rest(self):
        hub = _GitHub(graphql=False)
        ok, prs, err = self._quiet(hub, wf.assemble_prs, _cfg(), True)
        self.assertTrue(ok, err)
        self.assertEqual([p['number'] for p in prs], [12])


class TestSiblingPr(_Base):

    def test_the_closing_keywords_find_the_sibling(self):
        hub = _GitHub(graphql=False)
        code, payload, _ = self._call(hub, wf.cmd_sibling_pr, argparse.Namespace(
            number=[7, 8, 9], exclude_branch=None))
        self.assertEqual(code, wf.EXIT_OK, payload)
        found = {e['issue']: [p['number'] for p in e['prs']] for e in payload['by_issue']}
        self.assertEqual(found, {7: [12], 8: [15], 9: []})


class TestReviewLabels(_Base):

    def test_review_finish_moves_the_labels_through_rest(self):
        hub = _GitHub(graphql=False, prs=[_pr(11, [NAMES['reviewing'],
                                                   NAMES['changes-requested']])])
        code, payload, _ = self._call(hub, wf.cmd_review_finish, argparse.Namespace(
            pr=11, verdict='approved', fixes_applied=False))
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertTrue(payload['verified'], payload)
        self.assertEqual(hub.prs[11]['labels'], [NAMES['approved']])

    def test_the_label_moves_the_same_either_way(self):
        def finish(graphql):
            hub = _GitHub(graphql=graphql, prs=[_pr(11, [NAMES['reviewing'], 'docs'])])
            self._call(hub, wf.cmd_review_finish, argparse.Namespace(
                pr=11, verdict='changes-requested', fixes_applied=False))
            return sorted(hub.prs[11]['labels'])
        self.assertEqual(finish(False), finish(True))

    def test_a_missing_review_label_is_created_before_it_goes_on(self):
        hub = _GitHub(graphql=False, prs=[_pr(42)], labels=[])
        ok, err = self._quiet(hub, wf.add_review_label, _cfg(), 42, NAMES['needs-review'])
        self.assertTrue(ok, err)
        self.assertEqual(hub.prs[42]['labels'], [NAMES['needs-review']])
        create = [c for c in hub.calls if c[:3] == ['gh', 'label', 'create']]
        self.assertIn(NAMES['needs-review'], [c[3] for c in create])
        self.assertIn('--color', create[0])
        self.assertEqual(hub.grey, [])

    def test_review_finish_creates_a_missing_verdict_label_with_its_colour(self):
        labels = [n for n in wf_core.REVIEW_DEFAULT_LABELS.values()
                  if n != NAMES['approved']]
        hub = _GitHub(graphql=False, prs=[_pr(11, [NAMES['reviewing']])], labels=labels)
        code, payload, _ = self._call(hub, wf.cmd_review_finish, argparse.Namespace(
            pr=11, verdict='approved', fixes_applied=False))
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertTrue(payload['verified'], payload)
        self.assertEqual(hub.grey, [])
        create = [c for c in hub.calls if c[:3] == ['gh', 'label', 'create']]
        self.assertEqual([c[3] for c in create], [NAMES['approved']])
        self.assertIn('--color', create[0])

    def test_claim_marks_a_pull_request_that_has_no_needs_review(self):
        hub = _GitHub(graphql=False, prs=[_pr(11, [NAMES['changes-requested']])])
        marker = self._quiet(hub, wf.apply_claim_marker, _cfg(),
                             argparse.Namespace(issue=None, pr=11))
        self.assertEqual(marker, NAMES['reviewing'])
        self.assertIn(NAMES['reviewing'], hub.prs[11]['labels'])


if __name__ == '__main__':
    unittest.main()
