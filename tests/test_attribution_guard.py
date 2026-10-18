"""Tests for the AI attribution guard and its hook."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'))

from attribution_guard import ATTRIBUTION, attribution, evaluate  # noqa: E402

BASH = shutil.which('bash')
HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, '..', 'synergy', 'hooks', 'attribution-guard.sh')
SCRIPT = os.path.join(HERE, '..', 'synergy', 'scripts', 'attribution_guard.py')

COMMIT = ('git commit -m "$(cat <<\'EOF\'\nFix the thing\n\n'
          'Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>\nEOF\n)"')


def hook_event(tool, tool_input, cwd='.'):
    """A PreToolUse event shaped as Claude Code sends it."""
    return json.dumps({
        'session_id': 's1', 'transcript_path': cwd + '/s1.jsonl', 'cwd': cwd,
        'permission_mode': 'default', 'hook_event_name': 'PreToolUse',
        'tool_name': tool, 'tool_input': tool_input, 'tool_use_id': 'toolu_1'})


class TestAttribution(unittest.TestCase):
    """A commit, pull request or comment must not say an AI wrote it."""

    def denied(self, tool, tool_input):
        out = evaluate(hook_event(tool, tool_input))
        return out and out['hookSpecificOutput']['permissionDecision']

    def test_a_commit_with_a_trailer_is_denied(self):
        self.assertEqual(self.denied('Bash', {'command': COMMIT}), 'deny')
        self.assertEqual(self.denied('PowerShell', {'command': COMMIT}), 'deny')

    def test_a_pull_request_with_a_generation_line_is_denied(self):
        for command in (
            'gh pr create --title x --body "Done\n\n'
            '\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)"',
            'gh pr edit 4 --body "Reviewed with Claude Code"',
            'gh issue comment 4 --body "Co-authored-by: Claude <a@b.c>"',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.denied('Bash', {'command': command}), 'deny')

    def test_an_mcp_write_with_a_trailer_is_denied(self):
        for tool in ('mcp__github__create_pull_request',
                     'mcp__github__addIssueComment'):
            with self.subTest(tool=tool):
                self.assertEqual(self.denied(tool, {
                    'title': 'x',
                    'body': 'Co-Authored-By: Claude <noreply@anthropic.com>'}),
                    'deny')

    def test_a_human_co_author_passes(self):
        self.assertIsNone(attribution('Bash', {
            'command': 'git commit -m "x\n\nCo-Authored-By: Sam <sam@example.com>"'}))

    def test_a_command_that_only_searches_for_the_phrase_passes(self):
        for command in (
            'grep -rn "Co-Authored-By: Claude" docs',
            'echo "Generated with Claude Code"',
            'cat CHANGELOG.md',
        ):
            with self.subTest(command=command):
                self.assertIsNone(attribution('Bash', {'command': command}))

    def test_an_mcp_read_passes(self):
        self.assertIsNone(attribution(
            'mcp__github__get_pull_request', {'body': 'Co-Authored-By: Claude'}))

    def test_the_reason_tells_the_run_what_to_do(self):
        out = evaluate(hook_event('Bash', {'command': COMMIT}))['hookSpecificOutput']
        self.assertIn('Remove the line', out['permissionDecisionReason'])

    def test_a_call_that_cannot_be_read_passes(self):
        self.assertIsNone(evaluate('not json'))
        self.assertIsNone(evaluate('[1, 2]'))

    def test_a_python_too_old_for_the_script_prints_nothing(self):
        old = ('import runpy, sys; sys.version_info = (3, 6, 0); '
               'sys.argv = sys.argv[1:]; '
               'runpy.run_path(sys.argv[0], run_name="__main__")')
        out = subprocess.run([sys.executable, '-c', old, SCRIPT],
                             input=hook_event('Bash', {'command': COMMIT}),
                             capture_output=True, text=True, timeout=60)
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout, '')


@unittest.skipIf(not BASH or 'system32' in (BASH or '').lower(),
                 'needs a POSIX bash')
class TestHook(unittest.TestCase):
    """The text check in attribution-guard.sh that decides whether to start
    Python, and the interpreter it keeps."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp().replace('\\', '/')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # An interpreter that notes it was started, then runs the real one.
        self.logger = self.tmp + '/logging-python'
        with open(self.logger, 'w', newline='\n') as f:
            f.write('#!/bin/sh\n: > "$CLAUDE_PLUGIN_DATA/ran"\nexec "%s" "$@"\n'
                    % sys.executable.replace('\\', '/'))
        os.chmod(self.logger, 0o755)

    def data_dir(self, name, cache=None):
        data = '%s/%s' % (self.tmp, name)
        os.makedirs(data)
        if cache is not None:
            with open(data + '/guard-python', 'w') as f:
                f.write(cache)
        return data

    def run_hook(self, data, event):
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=data)
        return subprocess.run([BASH, HOOK.replace('\\', '/')], input=event,
                              capture_output=True, text=True, env=env,
                              timeout=120).stdout.strip()

    def test_an_attribution_line_reaches_python_and_is_denied(self):
        for index, (tool, tool_input) in enumerate((
            ('Bash', {'command': COMMIT}),
            ('PowerShell', {'command': 'gh pr edit 4 --body "Reviewed with Claude Code"'}),
            ('mcp__github__create_pull_request',
             {'body': 'Co-Authored-By: Claude <noreply@anthropic.com>'}),
        )):
            with self.subTest(tool=tool):
                data = self.data_dir('deny-%d' % index, self.logger)
                out = self.run_hook(data, hook_event(tool, tool_input, data))
                self.assertTrue(os.path.exists(data + '/ran'))
                self.assertEqual(out, json.dumps(evaluate(
                    hook_event(tool, tool_input, data))))

    def test_ordinary_calls_do_not_start_python(self):
        for index, (tool, tool_input) in enumerate((
            ('Bash', {'command': 'git push origin feature/1/x'}),
            ('Bash', {'command': 'gh pr create --title x --body "Closes #1"'}),
            ('PowerShell', {'command': 'az repos pr create --title x'}),
            ('mcp__github__create_issue', {'owner': 'o', 'repo': 'r', 'title': 'x'}),
        )):
            with self.subTest(tool=tool, tool_input=tool_input):
                data = self.data_dir('pass-%d' % index, self.logger)
                out = self.run_hook(data, hook_event(tool, tool_input, data))
                self.assertEqual(out, '')
                self.assertFalse(os.path.exists(data + '/ran'))

    def test_an_interpreter_that_prints_something_else_is_replaced(self):
        data = self.data_dir('echo', cache='echo')
        out = self.run_hook(data, hook_event('Bash', {'command': COMMIT}, data))
        self.assertIn('"deny"', out)
        with open(data + '/guard-python') as f:
            cached = f.read()
        # The interpreter's own path, so `py -3` is not started twice a call.
        self.assertTrue(os.path.isfile(cached), cached)

    def test_the_text_check_covers_every_attribution_match(self):
        with open(HOOK, encoding='utf-8') as f:
            text = f.read()
        words = re.search(r"^pattern='([^']*)'", text, re.M).group(1).split('|')
        for line in ('Co-Authored-By: Claude <a@b.c>',
                     'Generated with [Claude Code](https://claude.com)',
                     'noreply@anthropic.com', 'Reviewed with Claude Code',
                     'co-authored-by: Anthropic bot'):
            with self.subTest(line=line):
                self.assertTrue(ATTRIBUTION.search(line))
                self.assertTrue(any(w in line.lower() for w in words))


if __name__ == '__main__':
    unittest.main()
