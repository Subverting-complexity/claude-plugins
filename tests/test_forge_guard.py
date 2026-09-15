#!/usr/bin/env python3
"""Offline tests for the guard that asks before posting outside GitHub."""
import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
from forge_guard import decision, outbound_post  # noqa: E402

AZURE = 'https://org@dev.azure.com/org/project/_git/repo'
GITHUB = 'git@github.com:Subverting-complexity/claude-plugins.git'


def remotes(urls):
    return lambda cwd, remote: urls.get(remote or 'origin', '')


def bash(command, urls=None):
    return outbound_post('Bash', {'command': command}, '.',
                         remotes({'origin': AZURE} if urls is None else urls))


class TestAzureDevOpsCli(unittest.TestCase):
    def test_writes_ask(self):
        for command in (
            'az repos pr create --title x',
            'az repos pr update --id 4 --status completed',
            'az repos pr set-vote --id 4 --vote approve',
            'az repos pr reviewer add --id 4 --reviewers a',
            'az boards work-item create --title x --type Bug',
            'az boards work-item update --id 9 --state Done',
            'az devops invoke --area git --resource threads --http-method POST',
            'az rest --method post --uri https://dev.azure.com/org/_apis/x',
            'rtk az repos pr create --title x',
            'cd repo && az repos pr create --title x',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(bash(command))

    def test_reads_pass(self):
        for command in (
            'az repos pr list',
            'az repos pr show --id 4',
            'az boards work-item show --id 9',
            'az devops invoke --area git --resource repositories',
            'az rest --uri https://dev.azure.com/org/_apis/x',
            'az login',
            'az group create --name rg',
        ):
            with self.subTest(command=command):
                self.assertIsNone(bash(command))


class TestRestCalls(unittest.TestCase):
    def test_writes_to_a_forge_host_ask(self):
        for command in (
            'curl -X POST https://dev.azure.com/org/_apis/wit/workitems',
            'curl -XPATCH https://dev.azure.com/org/_apis/x',
            "curl -d '{}' https://org.visualstudio.com/_apis/x",
            'curl --json @body.json https://gitlab.com/api/v4/projects/1/notes',
            'Invoke-RestMethod -Uri https://dev.azure.com/org/_apis/x -Method Post -Body $b',
            'irm https://dev.azure.com/org/_apis/x -Method PATCH',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(bash(command))

    def test_reads_and_other_hosts_pass(self):
        for command in (
            'curl https://dev.azure.com/org/_apis/projects',
            'curl -X GET https://dev.azure.com/org/_apis/projects',
            'Invoke-RestMethod -Uri https://dev.azure.com/org/_apis/x',
            'curl -X POST https://api.example.com/hook',
            'curl -d x https://api.github.com/repos/o/r/issues',
        ):
            with self.subTest(command=command):
                self.assertIsNone(bash(command))


class TestGitLab(unittest.TestCase):
    def test_writes_ask_and_reads_pass(self):
        self.assertIsNotNone(bash('glab mr create --fill'))
        self.assertIsNotNone(bash('glab mr note 3 -m hi'))
        self.assertIsNotNone(bash('glab api -X POST projects/1/issues'))
        self.assertIsNone(bash('glab mr list'))
        self.assertIsNone(bash('glab api projects/1'))


class TestGitPush(unittest.TestCase):
    def test_push_to_a_non_github_remote_asks(self):
        reason = bash('git push -u origin feature/x')
        self.assertIn('dev.azure.com', reason)
        self.assertIsNotNone(bash('git push'))
        self.assertIsNotNone(bash('rtk git push --force-with-lease'))
        self.assertIsNotNone(
            bash('git push git@ssh.dev.azure.com:v3/org/project/repo HEAD'))

    def test_push_to_github_passes(self):
        self.assertIsNone(bash('git push -u origin feature/x',
                               {'origin': GITHUB}))
        self.assertIsNone(bash('git push upstream main',
                               {'origin': AZURE, 'upstream': GITHUB}))

    def test_push_to_an_unknown_or_local_remote_passes(self):
        self.assertIsNone(bash('git push', {}))
        self.assertIsNone(bash('git push origin', {'origin': '/srv/repo.git'}))

    def test_other_git_commands_pass(self):
        for command in ('git status', 'git commit -m "push the fix"',
                        'git fetch origin', 'git log --oneline'):
            with self.subTest(command=command):
                self.assertIsNone(bash(command))


class TestMcpTools(unittest.TestCase):
    def test_forge_writes_ask_and_reads_pass(self):
        self.assertIsNotNone(outbound_post(
            'mcp__azure-devops__repo_create_pull_request', {}))
        self.assertIsNotNone(outbound_post(
            'mcp__ado__wit_add_work_item_comment', {}))
        self.assertIsNone(outbound_post(
            'mcp__azure-devops__repo_list_pull_requests', {}))
        self.assertIsNone(outbound_post('mcp__github__create_issue', {}))


class TestDecision(unittest.TestCase):
    def test_the_hook_asks_and_never_denies(self):
        out = decision('a push to dev.azure.com')['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'PreToolUse')
        self.assertEqual(out['permissionDecision'], 'ask')
        self.assertIn('dev.azure.com', out['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
