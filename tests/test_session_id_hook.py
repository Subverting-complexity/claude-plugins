"""hooks/session-id.sh records the Claude Code session id for wf (#440).

It reads `session_id` from the hook's stdin JSON and appends
`export WF_SESSION_ID=<id>` to the file CLAUDE_ENV_FILE names. It prints
nothing, and does nothing without an id or without the file.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

BASH = shutil.which('bash')
HOOK = os.path.join(os.path.dirname(__file__), '..', 'synergy', 'hooks',
                    'session-id.sh').replace(os.sep, '/')
SID = 'f0028945-9bea-4127-ae04-221153a20946'


@unittest.skipIf(not BASH or 'system32' in (BASH or '').lower(),
                 'needs a POSIX bash')
class TestSessionIdHook(unittest.TestCase):

    def run_hook(self, event, env_file=True):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'env.sh')
            env = dict(os.environ)
            env.pop('CLAUDE_ENV_FILE', None)
            if env_file:
                env['CLAUDE_ENV_FILE'] = path.replace(os.sep, '/')
            done = subprocess.run([BASH, HOOK], input=json.dumps(event), env=env,
                                  capture_output=True, text=True, timeout=60)
            text = open(path, encoding='utf-8').read() if os.path.exists(path) else None
            return done.stdout, text

    def test_the_session_id_is_exported_for_later_commands(self):
        out, text = self.run_hook({'session_id': SID, 'hook_event_name': 'SessionStart',
                                   'source': 'startup'})
        self.assertEqual(out, '')
        self.assertEqual(text, 'export WF_SESSION_ID=%s\n' % SID)

    def test_nothing_is_written_without_an_id(self):
        self.assertEqual(self.run_hook({'hook_event_name': 'SessionStart'}), ('', None))

    def test_nothing_is_written_without_the_env_file(self):
        self.assertEqual(self.run_hook({'session_id': SID}, env_file=False), ('', None))

    def test_an_id_that_could_inject_shell_is_refused(self):
        _, text = self.run_hook({'session_id': 'x; rm -rf /'})
        self.assertIsNone(text)


if __name__ == '__main__':
    unittest.main()
