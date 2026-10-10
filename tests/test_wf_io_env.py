#!/usr/bin/env python3
"""`wf_io.run` must never let git or gh stop to ask for credentials.

An unattended `wf claim` pushes a claim ref. With expired credentials, git
would otherwise wait on a terminal prompt or a Git Credential Manager window
that nobody is there to answer, and the run would hang rather than fail.
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
import wf_io  # noqa: E402


class TestNonInteractiveSubprocesses(unittest.TestCase):

    def _env_passed(self):
        done = subprocess.CompletedProcess([], 0, '', '')
        with mock.patch.object(wf_io.subprocess, 'run', return_value=done) as call:
            wf_io.run(['git', 'push', 'origin', 'x:refs/claims/issue-1'])
        return call.call_args[1]['env']

    def test_prompts_are_turned_off_for_every_child(self):
        env = self._env_passed()
        self.assertEqual(env['GIT_TERMINAL_PROMPT'], '0')
        self.assertEqual(env['GCM_INTERACTIVE'], 'never')

    def test_the_rest_of_the_environment_is_passed_through(self):
        """gh needs its token and git its config, so nothing else is dropped."""
        with mock.patch.dict(os.environ, {'WF_TEST_SENTINEL': 'kept',
                                          'GIT_TERMINAL_PROMPT': '1'}):
            env = self._env_passed()
            self.assertEqual(env['WF_TEST_SENTINEL'], 'kept')
            # A prompt switched on outside is still switched off for the child,
            # and the caller's own environment is left as it was.
            self.assertEqual(env['GIT_TERMINAL_PROMPT'], '0')
            self.assertEqual(os.environ['GIT_TERMINAL_PROMPT'], '1')

    def test_a_real_child_sees_the_switches(self):
        code, out, _ = wf_io.run([
            sys.executable, '-c',
            'import os; print(os.environ.get("GIT_TERMINAL_PROMPT"), '
            'os.environ.get("GCM_INTERACTIVE"))'])
        self.assertEqual(code, 0)
        self.assertEqual(out.split(), ['0', 'never'])


if __name__ == '__main__':
    unittest.main()
