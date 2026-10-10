#!/usr/bin/env python3
"""
Tests for `wf_config.check_environment`, the check every `wf` command runs
before it touches GitHub.

It asks `gh auth token`, which reads the local credential store, instead of
`gh auth status`, which asks GitHub and cost about 750 ms per command. gh older
than 2.17 has no `auth token`, so a failure there is confirmed with
`gh auth status` before the command reports that gh is not signed in.

Run standalone (`python3 tests/test_wf_config_auth.py`) or via `run-tests.sh`.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'synergy', 'scripts'))

import wf_config  # noqa: E402


def fake_run(results):
    """Return a `run` stand-in answering each command from `results`, recording every call."""
    calls = []

    def run(cmd, *args, **kwargs):
        calls.append(cmd)
        return results[tuple(cmd)]

    return run, calls


IN_TREE = ('git', 'rev-parse', '--is-inside-work-tree')
TOKEN = ('gh', 'auth', 'token')
STATUS = ('gh', 'auth', 'status')


class CheckEnvironmentTests(unittest.TestCase):

    def check(self, results):
        run, calls = fake_run(results)
        with mock.patch.object(wf_config, 'run', run):
            return wf_config.check_environment(), [tuple(c) for c in calls]

    def test_signed_in_needs_no_network_check(self):
        err, calls = self.check({IN_TREE: (0, 'true\n', ''), TOKEN: (0, 'gho_x\n', '')})
        self.assertIsNone(err)
        self.assertNotIn(STATUS, calls)

    def test_gh_without_auth_token_falls_back_to_status(self):
        err, calls = self.check({
            IN_TREE: (0, 'true\n', ''),
            TOKEN: (1, '', 'unknown command "token" for "gh auth"'),
            STATUS: (0, '', 'Logged in to github.com'),
        })
        self.assertIsNone(err)
        self.assertEqual(calls[-1], STATUS)

    def test_signed_out_reports_the_status_error(self):
        err, _ = self.check({
            IN_TREE: (0, 'true\n', ''),
            TOKEN: (1, '', 'no oauth token found for github.com'),
            STATUS: (1, '', 'You are not logged into any GitHub hosts.'),
        })
        self.assertIn('not authenticated', err)
        self.assertIn('not logged into any GitHub hosts', err)

    def test_outside_a_work_tree_skips_gh(self):
        err, calls = self.check({IN_TREE: (128, '', 'fatal: not a git repository')})
        self.assertEqual(err, 'not inside a git work tree')
        self.assertEqual(calls, [IN_TREE])


if __name__ == '__main__':
    unittest.main()
