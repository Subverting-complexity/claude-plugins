#!/usr/bin/env python3
"""
The REST fallback for a session where GraphQL is blocked.

A Claude Code cloud session answers every GraphQL request with HTTP 403 while
REST still works. `wf` switches to REST on the first 403, says so once, and
from then on picks and writes `Stage` through REST. These tests check the
switch, that the REST read gives the pool the GraphQL read gives, that a
`Stage` write lands and is read back, and that the field id resolves without
the org endpoint.

Run standalone (`python3 tests/test_rest_fallback.py`) or via `run-tests.sh`.
"""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'))
import wf  # noqa: E402
import wf_core  # noqa: E402
import wf_io  # noqa: E402
import wf_rest  # noqa: E402


REPO = 'acme/widgets'
FORBIDDEN = (1, '{"message":"Forbidden"}', 'gh: Forbidden (HTTP 403)')

FIELD_IDS = {'Stage': 501, 'Priority': 502, 'Effort': 503, 'Ownership': 504}


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'labels': {}, 'review_labels': {}, 'fields': {}, 'board': {}}


# One pool, written once and served both ways. Oldest first, as both reads
# return it. #4 is an Epic over #5 and #6; #6 waits on #2, which is open; #7
# is Blocked on #3, which is closed, so it is releasable; #8 already has an
# open pull request; #9 is assigned.
POOL = [
    {'number': 2, 'stage': 'Backlog', 'priority': 'Medium', 'effort': 'Low',
     'type': 'User Story'},
    {'number': 4, 'stage': 'Backlog', 'priority': 'High', 'effort': 'High',
     'type': 'Epic'},
    {'number': 5, 'stage': None, 'priority': 'High', 'effort': 'Medium',
     'type': 'User Story', 'parent': 4},
    {'number': 6, 'stage': 'Backlog', 'priority': 'High', 'effort': 'Low',
     'type': 'User Story', 'parent': 4, 'blockers': [(2, 'OPEN')]},
    {'number': 7, 'stage': 'Blocked', 'priority': 'Low', 'effort': 'Low',
     'type': 'Bug', 'blockers': [(3, 'CLOSED')]},
    {'number': 8, 'stage': 'Backlog', 'priority': 'High', 'effort': 'Low',
     'type': 'Bug', 'open_pr': 90},
    {'number': 9, 'stage': 'In Progress', 'priority': 'High', 'effort': 'Low',
     'type': 'Bug', 'assignee': 'someone'},
]


def _children(number):
    return [i['number'] for i in POOL if i.get('parent') == number]


def _graphql_node(issue):
    fields = [{'field': {'name': 'Ownership'}, 'name': 'Code agent'},
              {'field': {'name': 'Priority'}, 'name': issue['priority']},
              {'field': {'name': 'Effort'}, 'name': issue['effort']}]
    if issue.get('stage'):
        fields.append({'field': {'name': 'Stage'}, 'name': issue['stage']})
    blockers = issue.get('blockers') or []
    prs = [{'number': issue['open_pr'], 'state': 'OPEN'}] if issue.get('open_pr') else []
    return {
        'id': 'I_%d' % issue['number'], 'number': issue['number'],
        'title': 'Issue %d' % issue['number'], 'body': 'Body %d' % issue['number'],
        'url': 'https://github.com/%s/issues/%d' % (REPO, issue['number']),
        'labels': {'nodes': [{'name': 'docs'}]}, 'milestone': None,
        'assignees': {'nodes': [{'login': issue['assignee']}] if issue.get('assignee') else []},
        'issueFieldValues': {'nodes': fields},
        'issueType': {'name': issue['type']},
        'parent': ({'number': issue['parent'], 'repository': {'nameWithOwner': REPO}}
                   if issue.get('parent') else None),
        'subIssues': {'totalCount': len(_children(issue['number'])),
                      'nodes': [{'number': c, 'state': 'OPEN',
                                 'repository': {'nameWithOwner': REPO}}
                                for c in _children(issue['number'])]},
        'blockedBy': {'totalCount': len(blockers), 'nodes': [
            {'number': n, 'state': s, 'title': 'Issue %d' % n,
             'repository': {'nameWithOwner': REPO}} for n, s in blockers]},
        'closedByPullRequestsReferences': {'totalCount': len(prs), 'nodes': prs},
    }


def _single(name, option):
    return {'issue_field_id': FIELD_IDS[name], 'issue_field_name': name,
            'data_type': 'single_select', 'value': 1,
            'single_select_option': {'id': 1, 'name': option}}


def _rest_issue(issue):
    values = [_single('Ownership', 'Code agent'), _single('Priority', issue['priority']),
              _single('Effort', issue['effort'])]
    if issue.get('stage'):
        values.append(_single('Stage', issue['stage']))
    blockers = issue.get('blockers') or []
    raw = {
        'node_id': 'I_%d' % issue['number'], 'number': issue['number'],
        'title': 'Issue %d' % issue['number'], 'body': 'Body %d' % issue['number'],
        'html_url': 'https://github.com/%s/issues/%d' % (REPO, issue['number']),
        'state': 'open', 'labels': [{'name': 'docs'}], 'milestone': None,
        'assignees': [{'login': issue['assignee']}] if issue.get('assignee') else [],
        'issue_field_values': values, 'type': {'name': issue['type']},
        'sub_issues_summary': {'total': len(_children(issue['number'])), 'completed': 0},
        'issue_dependencies_summary': {
            'blocked_by': sum(1 for _n, s in blockers if s == 'OPEN'),
            'total_blocked_by': len(blockers)},
    }
    if issue.get('parent'):
        raw['parent_issue_url'] = 'https://api.github.com/repos/%s/issues/%d' % (
            REPO, issue['parent'])
    return raw


def _rest_blocker(number, state):
    return {'number': number, 'state': state.lower(), 'title': 'Issue %d' % number,
            'repository_url': 'https://api.github.com/repos/%s' % REPO}


class _GitHub(object):
    """Answers `gh` and `git` as GitHub would, with GraphQL on or blocked."""

    def __init__(self, graphql=True, org_fields=True, stage_reads=None,
                 prs_fail=False, closed_prs=()):
        self.graphql = graphql
        self.org_fields = org_fields
        self.stage_reads = stage_reads
        self.prs_fail = prs_fail
        self.closed_prs = list(closed_prs)
        self.calls = []
        self.writes = []

    def run(self, cmd, input_text=None):
        self.calls.append(list(cmd))
        if cmd[:2] == ['git', 'ls-remote']:
            return 0, '', ''
        if cmd[:3] == ['gh', 'api', 'graphql']:
            if not self.graphql:
                return FORBIDDEN
            return 0, json.dumps({'data': {'repository': {'issues': {
                'pageInfo': {'hasNextPage': False, 'endCursor': None},
                'nodes': [_graphql_node(i) for i in POOL]}}}}), ''
        if cmd[:2] == ['gh', 'api'] and '-X' in cmd:
            method, path = cmd[cmd.index('-X') + 1], cmd[cmd.index('-X') + 2]
            body = json.loads(input_text) if input_text else None
            return self._rest(method, path, body)
        if cmd[:2] in (['gh', 'pr'], ['gh', 'issue']) and not self.graphql:
            # `gh` reads through GraphQL inside these subcommands.
            return 1, '', 'HTTP 403: Forbidden (https://api.github.com/graphql)'
        return 1, '', 'unexpected command %r' % cmd

    def _rest(self, method, path, body):
        base = 'repos/%s/' % REPO
        if method == 'GET' and path.startswith(base + 'issues?state=open'):
            page = int(path.rsplit('page=', 1)[1])
            # A pull request in the list, as the REST issue list returns them.
            items = [_rest_issue(i) for i in POOL] + [
                {'number': 90, 'pull_request': {}}] if page == 1 else []
            # GitHub's default order is newest first; only the query asks
            # for the order the GraphQL read uses.
            if not ('sort=created' in path and 'direction=asc' in path):
                items.reverse()
            return 0, json.dumps(items), ''
        if method == 'GET' and path.startswith(base + 'pulls?state=closed'):
            page = int(path.rsplit('page=', 1)[1])
            return 0, json.dumps(self.closed_prs[(page - 1) * 100:page * 100]), ''
        if method == 'GET' and '/dependencies/blocked_by' in path:
            number = int(path.split('/issues/')[1].split('/')[0])
            issue = next(i for i in POOL if i['number'] == number)
            return 0, json.dumps([_rest_blocker(n, s)
                                  for n, s in issue.get('blockers') or []]), ''
        if method == 'GET' and path.startswith(base + 'pulls?state=open'):
            if self.prs_fail:
                return 1, '', 'gh: Server Error (HTTP 502)'
            return 0, json.dumps([{'number': 90, 'body': 'Work.\n\nCloses #8'}]), ''
        if method == 'GET' and path == 'orgs/acme/issue-fields':
            if not self.org_fields:
                return FORBIDDEN
            return 0, json.dumps([{'id': v, 'name': k} for k, v in FIELD_IDS.items()]), ''
        if method == 'GET' and path.endswith('/issue-field-values'):
            return 0, json.dumps([]), ''
        if method == 'GET' and path == 'user':
            return 0, json.dumps({'login': 'builder'}), ''
        if method in ('POST', 'DELETE') and (path.endswith('/assignees')
                                             or path.endswith('/comments')):
            self.writes.append((path, body))
            return 0, '{}', ''
        if method == 'GET' and path.startswith(base + 'issues?state=all'):
            return 0, json.dumps([_rest_issue(POOL[0])]), ''
        if method == 'POST' and path.endswith('/issue-field-values'):
            self.writes.append((path, body))
            value = body['issue_field_values'][0]
            stored = self.stage_reads or value['value']
            return 0, json.dumps([{'issue_field_id': value['field_id'],
                                   'issue_field_name': 'Stage',
                                   'data_type': 'single_select', 'value': 7,
                                   'single_select_option': {'id': 7, 'name': stored}}]), ''
        return 1, '', 'unexpected REST call %s %s' % (method, path)


class _Base(unittest.TestCase):

    def setUp(self):
        wf_io.reset_graphql_state()
        wf_rest.reset_rest_state()
        self.addCleanup(wf_io.reset_graphql_state)
        self.addCleanup(wf_rest.reset_rest_state)
        self.cache = {}
        patches = [
            mock.patch.object(wf, 'load_capability_cache',
                              lambda root=None: dict(self.cache)),
            mock.patch.object(wf, 'merge_capability_cache',
                              lambda values, root=None: self.cache.update(values)),
            mock.patch.dict(os.environ, {}, clear=False),
        ]
        os.environ.pop(wf_io.GRAPHQL_ENV, None)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _quiet(self, func, *args, **kwargs):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = func(*args, **kwargs)
        return result, err.getvalue()


class TestTheSwitch(_Base):

    def test_a_403_is_a_blocked_api_and_a_rate_limit_is_not(self):
        self.assertTrue(wf_io.graphql_refused('', 'gh: Forbidden (HTTP 403)'))
        self.assertFalse(wf_io.graphql_refused(
            '', 'gh: API rate limit exceeded for user (HTTP 403)'))
        self.assertFalse(wf_io.graphql_refused('', 'gh: Bad credentials (HTTP 401)'))
        self.assertFalse(wf_io.graphql_refused('{"errors":[{"type":"FORBIDDEN"}]}', ''))

    def test_the_first_403_switches_the_run_and_says_so_once(self):
        hub = _GitHub(graphql=False)
        with mock.patch.object(wf, 'run', hub.run):
            (first, _), notice = self._quiet(lambda: (wf.gh_graphql('query{a}'), 0))
            (second, _), again = self._quiet(lambda: (wf.gh_graphql('query{b}'), 0))
        self.assertFalse(first[0])
        self.assertFalse(second[0])
        self.assertTrue(wf_io.graphql_blocked())
        self.assertIn('REST', notice)
        self.assertEqual(again, '')
        # The second call never reached GitHub.
        self.assertEqual(len([c for c in hub.calls if c[:3] == ['gh', 'api', 'graphql']]), 1)

    def test_any_other_failure_leaves_graphql_on(self):
        with mock.patch.object(wf, 'run', lambda cmd, input_text=None: (
                1, '', 'gh: Something went wrong (HTTP 502)')):
            self._quiet(wf.gh_graphql, 'query{a}')
        self.assertFalse(wf_io.graphql_blocked())

    def test_the_environment_can_start_a_run_on_rest(self):
        os.environ[wf_io.GRAPHQL_ENV] = 'off'
        self.addCleanup(os.environ.pop, wf_io.GRAPHQL_ENV, None)
        (blocked, notice) = self._quiet(wf_io.graphql_blocked)
        self.assertTrue(blocked)
        self.assertIn('REST', notice)

    def test_a_gh_subcommand_refused_by_graphql_switches_the_run(self):
        with mock.patch.object(wf, 'run', lambda cmd, input_text=None: (
                1, '', 'HTTP 403: Forbidden (https://api.github.com/graphql)')):
            self._quiet(wf.gh_json, ['issue', 'view', '5'])
        self.assertTrue(wf_io.graphql_blocked())

    def test_a_refused_rest_call_does_not_switch_the_run(self):
        with mock.patch.object(wf, 'run', lambda cmd, input_text=None: FORBIDDEN):
            self._quiet(wf.gh_json, ['api', 'repos/acme/widgets/issues'])
        self.assertFalse(wf_io.graphql_blocked())


class TestThePoolReadsTheSameEitherWay(_Base):

    # What only GraphQL can say: whether every closing pull request was seen.
    # The REST read leaves it unknown, and the claim checks merged pull
    # requests itself.
    GRAPHQL_ONLY = ('prs_complete', 'merged_prs')

    def _pool(self, graphql):
        hub = _GitHub(graphql=graphql)
        with mock.patch.object(wf, 'run', hub.run):
            (ok, issues, err), notice = self._quiet(wf.assemble_candidates, _cfg())
        self.assertTrue(ok, err)
        return issues, notice, hub

    def _strip(self, issues):
        return [{k: v for k, v in i.items() if k not in self.GRAPHQL_ONLY}
                for i in issues]

    def test_rest_returns_the_issues_graphql_returns_in_the_same_order(self):
        graphql, quiet, _ = self._pool(True)
        rest, notice, hub = self._pool(False)
        self.assertEqual(quiet, '')
        self.assertIn('REST', notice)
        self.assertEqual([i['number'] for i in rest], [2, 4, 5, 6, 7, 8, 9])
        self.assertEqual(self._strip(rest), self._strip(graphql))
        # Only the issues with blockers cost a read of their own.
        edge_reads = [c for c in hub.calls if any('blocked_by' in a for a in c)]
        self.assertEqual(len(edge_reads), 2)

    def test_a_failed_pull_request_read_fails_the_pool_read(self):
        """Without it, an issue already in review would read as free work."""
        hub = _GitHub(graphql=False, prs_fail=True)
        with mock.patch.object(wf, 'run', hub.run):
            (ok, issues, err), _ = self._quiet(wf.assemble_candidates, _cfg())
        self.assertFalse(ok)
        self.assertIsNone(issues)
        self.assertIn('open pull request', err)

    def test_the_pool_ranks_the_same_either_way(self):
        def ranked(issues):
            facets = wf.facets_from_issues(_cfg(), issues, [i['number'] for i in issues])
            verdict = wf_core.evaluate_pool(
                issues, mode='story', type_map=facets['types'],
                classification_map=None, priority_map=facets['priority'],
                effort_map=facets['effort'], ownership_map=facets['ownership'],
                claimed=set())
            return ([e['number'] for e in verdict['ranked']],
                    sorted(verdict['blocked']), sorted(verdict.get('releasable') or ()))
        graphql, _, _ = self._pool(True)
        rest, _, _ = self._pool(False)
        self.assertEqual(ranked(rest), ranked(graphql))
        self.assertEqual(ranked(rest)[2], [7])


class TestStageThroughRest(_Base):

    def _set(self, hub, wanted):
        with mock.patch.object(wf, 'run', hub.run):
            out, _ = self._quiet(wf.set_stages, _cfg(), wanted)
        return out

    def test_a_refused_graphql_write_lands_through_rest_and_is_read_back(self):
        hub = _GitHub(graphql=False)
        out = self._set(hub, {5: 'stage-in-progress'})
        self.assertEqual(out[5], (True, 'Stage set to In Progress'))
        path, body = hub.writes[0]
        self.assertEqual(path, 'repos/acme/widgets/issues/5/issue-field-values')
        self.assertEqual(body, {'issue_field_values': [{'field_id': 501,
                                                        'value': 'In Progress'}]})

    def test_a_write_github_took_but_did_not_store_is_a_failure(self):
        hub = _GitHub(graphql=False, stage_reads='Backlog')
        written, message = self._set(hub, {5: 'stage-in-progress'})[5]
        self.assertFalse(written)
        self.assertIn("reads 'Backlog'", message)

    def test_the_field_id_resolves_with_the_org_endpoint_refused(self):
        """No value on the issue and no org list: the recent issues have it."""
        hub = _GitHub(graphql=False, org_fields=False)
        self.assertTrue(self._set(hub, {5: 'Done'})[5][0])
        self.assertEqual(hub.writes[0][1]['issue_field_values'][0]['field_id'], 501)
        self.assertEqual(self.cache['rest_field_ids'], {'Stage': 501})

    def test_a_kept_field_id_needs_no_lookup(self):
        self.cache['rest_field_ids'] = {'Stage': 777}
        hub = _GitHub(graphql=False)
        self.assertTrue(self._set(hub, {5: 'Done'})[5][0])
        self.assertEqual(hub.writes[0][1]['issue_field_values'][0]['field_id'], 777)
        self.assertFalse([c for c in hub.calls if 'issue-fields' in ' '.join(c)])

    def test_the_pool_read_supplies_the_field_id(self):
        hub = _GitHub(graphql=False)
        with mock.patch.object(wf, 'run', hub.run):
            self._quiet(wf.assemble_candidates, _cfg())
            before = len(hub.calls)
            out, _ = self._quiet(wf.set_stages, _cfg(), {5: 'Done'})
        self.assertTrue(out[5][0])
        # The write and nothing else: no field id lookup.
        self.assertEqual(len(hub.calls) - before, 1)

    def test_with_graphql_on_nothing_goes_through_rest(self):
        calls = []

        def run(cmd, input_text=None):
            calls.append(list(cmd))
            return 0, json.dumps({'data': {'s5': {'issue': {'id': 'I_5'}}}}), ''

        caps = {'type_capable': True, 'type_map': {}, 'cached': True,
                'field_map': {'Stage': {'id': 'F', 'data_type': 'single-select',
                                        'options': {'Done': 'o'}}}}
        with mock.patch.object(wf, 'run', run), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg: (True, caps, '')):
            out, notice = self._quiet(wf.set_stages, _cfg(), {5: 'Done'}, {5: 'I_5'})
        self.assertTrue(out[5][0])
        self.assertEqual(notice, '')
        self.assertEqual([c[:3] for c in calls], [['gh', 'api', 'graphql']])


class TestMergedPullRequestCheck(_Base):

    def _check(self, closed):
        wf_io.mark_graphql_blocked()
        hub = _GitHub(graphql=False, closed_prs=closed)
        with mock.patch.object(wf, 'run', hub.run):
            found, _ = self._quiet(wf.merged_pr_closing, _cfg(), 5)
        return found, hub

    def test_only_a_merged_pull_request_resolves_the_issue(self):
        closed = [{'number': 70, 'merged_at': None, 'body': 'Closes #5'},
                  {'number': 71, 'merged_at': '2026-10-01T00:00:00Z',
                   'body': 'Fixes #5'},
                  {'number': 72, 'merged_at': '2026-10-01T00:00:00Z',
                   'body': 'Closes #6'}]
        self.assertEqual(self._check(closed)[0], 71)

    def test_closed_unmerged_pull_requests_do_not_shrink_the_window(self):
        """A hundred abandoned pull requests on top: the merged one under
        them is still found, as the GraphQL check would find it."""
        closed = [{'number': 200 + n, 'merged_at': None, 'body': ''}
                  for n in range(100)]
        closed.append({'number': 99, 'merged_at': '2026-10-01T00:00:00Z',
                       'body': 'Closes #5'})
        found, hub = self._check(closed)
        self.assertEqual(found, 99)
        self.assertEqual(len([c for c in hub.calls if 'pulls?state=closed' in c[4]]), 2)


class TestPickEditsThroughRest(_Base):
    """The edits a pick makes beside `Stage`: `gh issue edit` and `gh issue
    comment` read through GraphQL, so they go through REST too."""

    def _blocked_run(self, calls):
        def run(cmd, input_text=None):
            calls.append((list(cmd), json.loads(input_text) if input_text else None))
            if cmd[:2] == ['gh', 'api'] and cmd[-1] == 'user':
                return 0, json.dumps({'login': 'builder'}), ''
            return 0, '{}', ''
        return run

    def test_the_claim_assigns_through_rest(self):
        calls = []
        wf_io.mark_graphql_blocked()
        with mock.patch.object(wf, 'run', self._blocked_run(calls)):
            self._quiet(wf._assign, _cfg(), {'number': 5, 'labels': []})
        self.assertIn((['gh', 'api', '-X', 'POST', 'repos/acme/widgets/issues/5/assignees',
                        '--input', '-'], {'assignees': ['builder']}), calls)
        self.assertFalse([c for c, _ in calls if c[:3] == ['gh', 'issue', 'edit']])

    def test_comments_go_one_call_each(self):
        calls = []
        wf_io.mark_graphql_blocked()
        with mock.patch.object(wf, 'run', self._blocked_run(calls)):
            out, _ = self._quiet(wf.post_comments, _cfg(),
                                 {5: ('I_5', 'one'), 6: (None, 'two')})
        self.assertEqual(out, {5: (True, 'commented'), 6: (True, 'commented')})
        self.assertEqual([b for _c, b in calls], [{'body': 'one'}, {'body': 'two'}])


class TestAbandonedResetThroughRest(_Base):
    """`pick --issue N` resets an issue whose pull request was closed without
    merging. `gh pr list`, `gh issue edit` and `gh issue comment` read through
    GraphQL, so where it is blocked the reset goes through REST."""

    ABANDONED = {'number': 70, 'title': 'Old attempt', 'merged_at': None,
                 'body': 'Closes #5'}

    def _reset(self, closed, assignees=('someone',)):
        hub = _GitHub(graphql=False, closed_prs=closed)
        with mock.patch.object(wf, 'run', hub.run):
            found, _ = self._quiet(wf.reset_abandoned, _cfg(), 5, list(assignees))
        return found, hub

    def test_the_first_refused_read_resets_the_issue_through_rest(self):
        closed = [{'number': 71, 'merged_at': None, 'body': 'Closes #6'},
                  self.ABANDONED]
        found, hub = self._reset(closed)
        self.assertEqual(found, 70)
        self.assertTrue(wf_io.graphql_blocked())
        self.assertIn(('repos/acme/widgets/issues/5/assignees',
                       {'assignees': ['someone']}), hub.writes)
        self.assertIn(('repos/acme/widgets/issues/5/comments',
                       {'body': 'Resetting — PR #70 closed without merge.'}),
                      hub.writes)
        stage = [b for p, b in hub.writes if p.endswith('/issue-field-values')]
        self.assertEqual(stage[0]['issue_field_values'][0]['value'], 'Backlog')
        # The refused `gh pr list` was the only GraphQL call tried.
        self.assertEqual([c[:3] for c in hub.calls if c[1] != 'api'],
                         [['gh', 'pr', 'list']])

    def test_a_merged_pull_request_is_never_abandoned(self):
        merged = {'number': 72, 'merged_at': '2026-10-01T00:00:00Z',
                  'state': 'closed', 'body': 'Fixes #5'}
        found, hub = self._reset([merged, self.ABANDONED])
        self.assertIsNone(found)
        self.assertEqual(hub.writes, [])

    def test_an_issue_no_closed_pull_request_closes_is_left_alone(self):
        found, hub = self._reset([{'number': 71, 'merged_at': None,
                                   'body': 'See #5'}])
        self.assertIsNone(found)
        self.assertEqual(hub.writes, [])

    def test_with_graphql_on_the_reset_is_unchanged(self):
        calls = []

        def run(cmd, input_text=None):
            calls.append(list(cmd))
            if cmd[:3] == ['gh', 'pr', 'list']:
                return 0, json.dumps([{'number': 70, 'title': 'Old attempt',
                                       'mergedAt': None, 'closingIssuesReferences':
                                       [{'number': 5}]}]), ''
            return 0, '', ''

        stages = []
        with mock.patch.object(wf, 'run', run),                 mock.patch.object(wf, 'set_stage',
                                  lambda cfg, n, stage, node_id=None:
                                  stages.append((n, stage)) or (True, '')):
            found, notice = self._quiet(wf.reset_abandoned, _cfg(), 5, ['someone'])
        self.assertEqual(found, 70)
        self.assertEqual(notice, '')
        self.assertEqual(stages, [(5, 'Backlog')])
        self.assertEqual(calls, [
            ['gh', 'pr', 'list', '--repo', REPO, '--state', 'closed', '--search', '#5',
             '--json', 'number,title,mergedAt,closingIssuesReferences'],
            ['gh', 'issue', 'edit', '5', '--repo', REPO, '--remove-assignee', 'someone'],
            ['gh', 'issue', 'comment', '5', '--repo', REPO, '--body',
             'Resetting — PR #70 closed without merge.'],
        ])


class TestClosingReferences(unittest.TestCase):

    def test_keywords_are_read_the_way_github_reads_them(self):
        body = ('Closes #5\nThis fixes: #6 and resolved acme/widgets#7.\n'
                'Fixes https://github.com/acme/widgets/issues/8\n'
                'Closes other/repo#9, see #10.')
        self.assertEqual(wf_core.body_closing_numbers(body, 'acme/widgets'), [5, 6, 7, 8])

    def test_without_the_repository_only_short_references_count(self):
        self.assertEqual(wf_core.body_closing_numbers('Closes acme/widgets#7, fixes #3'), [3])


if __name__ == '__main__':
    unittest.main()
