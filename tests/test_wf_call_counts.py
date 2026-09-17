#!/usr/bin/env python3
"""The GitHub calls a command makes must not grow with the size of its run.

On Windows most `gh` and `git` calls cost 520 to 815 ms (#300). `post-merge`
used to make five per linked issue and `handoff` a push per issue claim, so a
bulk run of five stories paid for the same work five times. These tests drive
the commands through a recording `run` and assert that one issue and four
issues cost the same number of calls, and that a partial failure is still
reported against the issue it belongs to.
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
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


def _capture(func, *args):
    """Run a command function; return (exit_code, parsed_stdout_json)."""
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            func(*args)
        except SystemExit as exc:
            code = exc.code
    out = buf.getvalue()
    return code, (json.loads(out) if out.strip() else None)


def _cfg():
    return {'org': 'acme', 'repo': 'widgets', 'default_branch': 'main',
            'labels': {}, 'review_labels': {}, 'fields': {}, 'board': {}}


_STAGE = {'id': 'F_stage', 'data_type': 'single-select',
          'options': {name: 'o_%d' % i
                      for i, name in enumerate(wf_core.STAGE_NAMES.values())}}
_CAPS = {'type_capable': True, 'type_map': {}, 'field_map': {'Stage': _STAGE},
         'owner_kind': 'organization', 'denied': [], 'errors': [], 'cached': True}

_RETIRED_KEY = next(iter(wf_core.RETIRED_LABELS))
_RETIRED = wf_core.resolve_label(_RETIRED_KEY, {}, wf_core.RETIRED_LABELS)

# The payload field each mutation's alias is read back by.
_PAYLOAD = {'addComment': 'subject', 'closeIssue': 'issue',
            'removeLabelsFromLabelable': 'labelable',
            'setIssueFieldValue': 'issue',
            'removeAssigneesFromAssignable': 'assignable'}


class _GitHub(object):
    """A recording `run` that answers every call these commands make.

    `calls` holds each `gh` and `git` argv, which is the whole of what a run
    costs in round trips once the environment check and config are stubbed.
    """

    def __init__(self, linked=(), close_fails=(), push_fails=False, held=()):
        self.linked = list(linked)
        self.close_fails = {int(n) for n in close_fails}
        self.push_fails = push_fails
        self.held = set(held)
        self.calls = []

    def run(self, cmd, input_text=None):
        self.calls.append(list(cmd))
        if cmd[:3] == ['gh', 'pr', 'view']:
            return 0, json.dumps({
                'number': 50, 'state': 'MERGED', 'mergedAt': '2026-09-15T00:00:00Z',
                'baseRefName': 'main',
                'closingIssuesReferences': [{'number': n} for n in self.linked]}), ''
        if cmd[:3] == ['gh', 'api', 'graphql']:
            if input_text is not None:
                return self._mutation(json.loads(input_text)['query'])
            return self._query(next(a for a in cmd if a.startswith('query=')))
        if cmd[:2] == ['git', 'rev-parse']:
            return 0, 'tree\n', ''
        if cmd[:2] == ['git', 'commit-tree']:
            return 0, 'sha\n', ''
        if cmd[:2] == ['git', 'push']:
            deleting = any(a.startswith(':') for a in cmd)
            return (1, '', 'remote: rejected') if deleting and self.push_fails else (0, '', '')
        if cmd[:2] == ['git', 'ls-remote']:
            listed = [a for a in cmd if a in self.held]
            return (0, ''.join('abc\t%s\n' % r for r in listed), '') if listed else (2, '', '')
        return 0, '', ''

    def _query(self, query):
        if 'viewer' in query:
            return 0, json.dumps({'data': {'viewer': {'id': 'U_1'}}}), ''
        repository = {}
        for prefix, number in re.findall(r'(\w)(\d+): issue\(number:\d+\)', query):
            node = {'id': 'I_%s' % number, 'number': int(number)}
            if prefix == 'i':
                node.update(state='OPEN', labels={'nodes': [
                    {'id': 'L_retired', 'name': _RETIRED}]})
            elif prefix == 'p':
                node['parent'] = None
            repository['%s%s' % (prefix, number)] = node
        return 0, json.dumps({'data': {'repository': repository}}), ''

    def _mutation(self, query):
        data, errors = {}, []
        for alias, kind in re.findall(r'(\w+\d+): (\w+)\(input:', query):
            if kind == 'closeIssue' and int(alias[1:]) in self.close_fails:
                data[alias] = None
                errors.append({'path': [alias], 'message': 'HTTP 502'})
                continue
            data[alias] = {_PAYLOAD[kind]: {'id': 'X'}}
        return 0, json.dumps({'data': data, 'errors': errors}), ''


class _Counted(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def _drive(self, hub, argv):
        # A checkout of its own per run: a claim marker the previous run left
        # would make this one probe the remote, and the counts would differ
        # for a reason that has nothing to do with the number of issues.
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        args = wf.build_parser().parse_args(argv)
        with mock.patch.object(wf, 'check_environment', lambda: None), \
                mock.patch.object(wf, 'load_config', lambda: (True, _cfg(), '')), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg, refresh=False, root=None, **_:
                                  (True, dict(_CAPS), '')), \
                mock.patch.object(wf, 'repo_root', lambda: self.root), \
                mock.patch.object(wf, 'run', hub.run):
            return _capture(args.func, args)


class TestPostMergeCallCount(_Counted):

    def _post_merge(self, numbers, **hub_args):
        hub = _GitHub(linked=numbers, **hub_args)
        code, payload = self._drive(hub, ['post-merge', '--pr', '50', '--no-unblock'])
        self.assertEqual(code, wf.EXIT_OK)
        return payload, hub.calls

    def test_one_issue_and_four_cost_the_same(self):
        one, one_calls = self._post_merge([5])
        four, four_calls = self._post_merge([5, 6, 7, 8])
        self.assertEqual(len(one_calls), len(four_calls))
        # The PR, the issue read, the close-and-strip write, the `Stage` write
        # and the parent read.
        self.assertEqual(len(four_calls), 5)
        # Every close, strip and `Stage` write landed, so each is one line.
        self.assertEqual(one['settled'], [5])
        self.assertEqual(four['settled'], [5, 6, 7, 8])
        self.assertEqual(four['cleared'], {str(n): _RETIRED for n in (5, 6, 7, 8)})
        self.assertEqual(four['containers_closed'], [])

    def test_the_one_line_result_keeps_the_no_edges_count(self):
        hub = _GitHub(linked=[5])
        sweep = {'released': [], 'rescoped': [], 'partials': [], 'held': [],
                 'no_edges': {'count': 2, 'issues': [8, 9]}}
        with mock.patch('wf_post_merge.unblock_scan', lambda cfg: sweep):
            code, payload = self._drive(hub, ['post-merge', '--pr', '50'])
        self.assertEqual(code, wf.EXIT_OK, payload)
        self.assertEqual(payload['no_edges'], 2)

    def test_no_close_goes_through_the_cli_one_issue_at_a_time(self):
        _, calls = self._post_merge([5, 6, 7, 8])
        self.assertFalse(any(c[:3] in (['gh', 'issue', 'close'], ['gh', 'issue', 'view'],
                                       ['gh', 'issue', 'edit']) for c in calls))

    def test_a_refused_close_is_reported_against_its_own_issue(self):
        payload, calls = self._post_merge([5, 6, 7, 8], close_fails=[7])
        self.assertEqual(len(calls), 5)
        by_issue = {s['issue']: s for s in payload['settled']}
        self.assertFalse(by_issue[7]['closed'])
        self.assertFalse(by_issue[7]['closed_now'])
        for number in (5, 6, 8):
            self.assertTrue(by_issue[number]['closed_now'])
        # `Stage` is written for every linked issue, as it always was.
        self.assertTrue(all(s['stage_set'] for s in payload['settled']))


class TestHandoffCallCount(_Counted):

    def _handoff(self, numbers, **hub_args):
        hub = _GitHub(**hub_args)
        argv = ['handoff', '--pr', '9']
        for number in numbers:
            argv += ['--issue', str(number)]
        code, payload = self._drive(hub, argv)
        self.assertEqual(code, wf.EXIT_OK)
        return payload, hub.calls

    def test_one_issue_and_four_cost_the_same(self):
        one, one_calls = self._handoff([3])
        four, four_calls = self._handoff([3, 4, 5, 6])
        self.assertEqual(len(one_calls), len(four_calls))
        pushes = [c for c in four_calls if c[:2] == ['git', 'push']]
        # The review claim, then one push releasing every issue claim.
        self.assertEqual(len(pushes), 2)
        self.assertEqual(pushes[1][3:], [':refs/claims/issue-%d' % n
                                         for n in (3, 4, 5, 6)])
        self.assertIn('#3, #4, #5, #6 In Review and released', four['reason'])

    def test_a_release_the_remote_still_holds_is_reported_per_issue(self):
        payload, calls = self._handoff(
            [3, 4, 5, 6], push_fails=True, held={'refs/claims/issue-5'})
        released = {i['number']: i['claim_released'] for i in payload['issues']}
        self.assertEqual(released, {3: True, 4: True, 5: False, 6: True})
        self.assertEqual(len([c for c in calls if c[:2] == ['git', 'ls-remote']]), 1)


class TestDropStoryCallCount(_Counted):
    """Dropping a story and every story waiting on it: one mutation unassigns
    and comments on all of them, where it was two `gh` calls per story."""

    def _drop(self, dependents):
        hub = _GitHub()
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        stories = [{'number': 1, 'title': 'a', 'id': 'I_1', 'blocked_by': [],
                    'built': False}]
        stories += [{'number': n, 'title': 't', 'id': 'I_%d' % n, 'blocked_by': [1],
                     'built': False} for n in dependents]
        os.makedirs(os.path.join(root, '.claude'))
        with open(os.path.join(root, '.claude', 'bulk-set.json'), 'w',
                  encoding='utf-8') as fh:
            json.dump({'lead': 1, 'mode': 'story', 'branch': None,
                       'waves': wf_core.dependency_waves(stories),
                       'stories': stories, 'dropped': []}, fh)
        args = wf.build_parser().parse_args(['drop-story', '--issue', '1',
                                             '--reason', 'too big'])
        with mock.patch.object(wf, 'prepare_cfg', _cfg), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  lambda cfg, refresh=False, root=None, **_:
                                  (True, dict(_CAPS), '')), \
                mock.patch.object(wf, 'repo_root', lambda: root), \
                mock.patch.object(wf, 'run', hub.run):
            code, payload = _capture(args.func, args)
        self.assertEqual(code, wf.EXIT_OK)
        return payload, hub.calls

    def test_one_story_and_four_cost_the_same(self):
        one, one_calls = self._drop([])
        four, four_calls = self._drop([2, 3, 4])
        self.assertEqual(len(one_calls), len(four_calls))
        self.assertEqual(len(four['dropped']), 4)
        self.assertFalse([c for c in four_calls if c[:2] == ['gh', 'issue']])
        for entry in four['dropped']:
            self.assertTrue(entry['unassigned'])
            self.assertTrue(entry['commented'])
            self.assertTrue(entry['stage_set'])


class TestClaimReleaseCallCount(_Counted):

    def test_one_ref_and_four_cost_the_same(self):
        counts = []
        for numbers in ([3], [3, 4, 5, 6]):
            hub = _GitHub()
            argv = ['claim-release']
            for number in numbers:
                argv += ['--issue', str(number)]
            code, payload = self._drive(hub, argv)
            self.assertEqual(code, wf.EXIT_OK)
            self.assertEqual(payload['failed'], [])
            counts.append(len(hub.calls))
        self.assertEqual(counts, [1, 1])

    def test_a_remote_that_cannot_be_asked_releases_nothing(self):
        def run(cmd, input_text=None):
            return (128, '', 'fatal: unable to access') if cmd[0] == 'git' else (0, '', '')
        with mock.patch.object(wf, 'run', run), \
                mock.patch.object(wf, 'repo_root', lambda: self.root), \
                contextlib.redirect_stderr(io.StringIO()):
            outcome = wf.release_claims(['issue-3', 'issue-4'])
        self.assertEqual(outcome, {'issue-3': False, 'issue-4': False})


class TestPreflightCapabilitiesAndPins(unittest.TestCase):
    """Preflight's org read: types, fields and pins in one request."""

    _ORG = {'issueTypes': {'nodes': [
                {'id': 'IT_story', 'name': 'User Story', 'isEnabled': True,
                 'pinnedFields': [{'name': 'Stage'}]}]},
            'issueFields': {'nodes': [
                {'__typename': 'IssueFieldSingleSelect', 'id': 'F_stage',
                 'name': 'Stage', 'options': [{'id': 'o_done', 'name': 'Done'}]}]}}

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def _resolve(self, answers):
        calls = []

        def run(cmd, input_text=None):
            calls.append(list(cmd))
            return answers[min(len(calls), len(answers)) - 1]

        with mock.patch.object(wf, 'run', run):
            ok, caps, err = wf.resolve_org_capabilities(_cfg(), root=self.root,
                                                        pins=True)
        return ok, caps, calls

    def test_capabilities_and_pins_come_back_in_one_request(self):
        ok, caps, calls = self._resolve(
            [(0, json.dumps({'data': {'organization': self._ORG}}), '')])
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertIn('pinnedFields', calls[0][4])
        self.assertIn('Stage', caps['field_map'])
        self.assertEqual(caps['pins'], (True, [{'name': 'User Story', 'enabled': True,
                                                'pinned': ['Stage']}], ''))
        # The capability half is still cached, without the pins.
        cached = wf.load_capability_cache(self.root)
        self.assertIn('Stage', cached['field_map'])
        self.assertNotIn('pins', cached)

    def test_a_refused_pin_read_is_unknown_pins_not_a_denied_capability(self):
        refusal = {'type': 'FORBIDDEN', 'message': 'no',
                   'path': ['organization', 'issueTypes', 'nodes', 0, 'pinnedFields']}
        ok, caps, calls = self._resolve(
            [(1, json.dumps({'data': {'organization': self._ORG},
                             'errors': [refusal]}), 'gh: forbidden')])
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(caps['denied'], [])
        self.assertFalse(caps['pins'][0])

    def test_a_schema_without_pins_still_resolves_the_capabilities(self):
        plain = {k: v for k, v in self._ORG.items()}
        ok, caps, calls = self._resolve([
            (1, json.dumps({'errors': [{'message': "Field 'pinnedFields' doesn't exist"}]}),
             'gh: error'),
            (0, json.dumps({'data': {'organization': plain}}), '')])
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertIn('Stage', caps['field_map'])
        self.assertFalse(caps['pins'][0])


class TestRepoRootIsAskedOnce(unittest.TestCase):

    def test_the_toplevel_is_asked_once_per_working_directory(self):
        first, second = tempfile.mkdtemp(), tempfile.mkdtemp()
        for path in (first, second):
            self.addCleanup(shutil.rmtree, path, True)
        prev = os.getcwd()
        self.addCleanup(os.chdir, prev)
        calls = []

        def run(cmd, input_text=None):
            calls.append(list(cmd))
            return 0, os.getcwd() + '\n', ''

        with mock.patch.dict(wf._REPO_ROOTS, {}, clear=True), \
                mock.patch.object(wf, 'run', run):
            os.chdir(first)
            self.assertEqual(os.path.normcase(wf.repo_root()), os.path.normcase(os.getcwd()))
            wf.repo_root()
            os.chdir(second)
            self.assertEqual(os.path.normcase(wf.repo_root()), os.path.normcase(os.getcwd()))
            wf.repo_root()
        self.assertEqual(len(calls), 2)

    def test_an_answer_that_is_not_a_directory_is_not_remembered(self):
        calls = []

        def run(cmd, input_text=None):
            calls.append(list(cmd))
            return 0, '{}', ''

        with mock.patch.dict(wf._REPO_ROOTS, {}, clear=True), \
                mock.patch.object(wf, 'run', run):
            wf.repo_root()
            wf.repo_root()
        self.assertEqual(len(calls), 2)


def _git_available():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


@unittest.skipUnless(_git_available(), 'git is required for the real-remote test')
class TestBatchedReleaseAgainstARealRemote(unittest.TestCase):
    """git's own answer to one push deleting a held ref and an absent one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bare = os.path.join(self.tmp, 'remote.git')
        work = os.path.join(self.tmp, 'work')
        self._git(['init', '--bare', bare], self.tmp)
        self._git(['init', work], self.tmp)
        for key, val in (('user.email', 'test@example.com'), ('user.name', 'Test'),
                         ('commit.gpgsign', 'false')):
            self._git(['config', key, val], work)
        with open(os.path.join(work, 'README.md'), 'w'):
            pass
        self._git(['add', '.'], work)
        self._git(['commit', '-m', 'init'], work)
        self._git(['remote', 'add', 'origin', bare], work)
        prev = os.getcwd()
        os.chdir(work)
        self.addCleanup(os.chdir, prev)

    def _git(self, argv, cwd):
        r = subprocess.run(['git'] + argv, cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0:
            self.fail('git %s failed: %s' % (' '.join(argv), r.stderr.strip()))

    def test_a_held_ref_and_a_never_claimed_one_are_both_released(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(wf.acquire_claim('issue-1'), 'won')
            outcome = wf.release_claims(['issue-1', 'issue-2'])
        self.assertEqual(outcome, {'issue-1': True, 'issue-2': True})
        listed = subprocess.run(['git', 'ls-remote', 'origin', 'refs/claims/*'],
                                capture_output=True, text=True).stdout
        self.assertEqual(listed.strip(), '')


if __name__ == '__main__':
    unittest.main()
