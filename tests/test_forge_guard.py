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


class TestHiddenWrites(unittest.TestCase):
    """Writes written the way a run usually writes them, found in review."""

    def test_writes_inside_substitutions_wrappers_and_variables_ask(self):
        for command in (
            'pr=$(az repos pr create --title x --query pullRequestId -o tsv)',
            'resp=$(curl -s -X POST https://dev.azure.com/o/p/_apis/wit/workitems -d @b.json)',
            '$r = Invoke-RestMethod -Method Post -Uri https://dev.azure.com/o/_apis/x -Body $b',
            '(Invoke-RestMethod -Uri https://dev.azure.com/o/_apis/x -Method Post -Body $b).id',
            'curl -d@body.json https://dev.azure.com/o/_apis/x',
            'curl -sXPOST https://dev.azure.com/o/_apis/x',
            'Invoke-RestMethod -Uri https://dev.azure.com/o/_apis/x -Method:Post',
            '$uri = "https://dev.azure.com/o/_apis/x"\nInvoke-RestMethod -Uri $uri -Method Patch -Body $json',
            'timeout 30 git push origin main',
            'bash -c "az repos pr create --title x"',
            'pwsh -Command "Invoke-RestMethod -Method Post -Uri https://dev.azure.com/o/_apis/x"',
            'if git push; then echo ok; fi',
            'C:\\tools\\az.cmd repos pr create --title x',
            'Invoke-RestMethod -Uri https://dev.azure.com/o/_apis/x `\n  -Method Post',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(bash(command))

    def test_a_push_after_cd_uses_that_repository(self):
        lookup = (lambda cwd, remote:
                  AZURE if 'azrepo' in (cwd or '') else GITHUB)
        self.assertIsNotNone(outbound_post(
            'Bash', {'command': 'cd ../azrepo && git push'}, '.', lookup))
        self.assertIsNotNone(outbound_post(
            'Bash', {'command': '(cd ../azrepo && git push)'}, '.', lookup))
        self.assertIsNone(outbound_post(
            'Bash', {'command': 'git push'}, '.', lookup))

    def test_camel_case_mcp_writes_ask(self):
        self.assertIsNotNone(outbound_post('mcp__gitlab__createMergeRequest', {}))
        self.assertIsNotNone(outbound_post('mcp__bitbucket__createPullRequest', {}))


class TestNoFalsePrompts(unittest.TestCase):
    def test_mcp_reads_and_azure_cloud_tools_pass(self):
        for name in (
            'mcp__gitlab__list_merge_requests',
            'mcp__gitlab__get_merge_request',
            'mcp__gitlab__get_merge_request_diffs',
            'mcp__gitlab__get_merge_request_notes',
            'mcp__gitlab__get_issue_link',
            'mcp__ado__pipelines_get_run',
            'mcp__bitbucket__get_pull_request_comment',
            'mcp__azure__storage_blob_upload',
            'mcp__azure-mcp__appservice_create',
        ):
            with self.subTest(name=name):
                self.assertIsNone(outbound_post(name, {}))

    def test_pushes_to_github_and_other_hosts_pass(self):
        for command, urls in (
            ('git push git@github.com-work:org/repo.git main', None),
            ('git push', {'origin': 'git@github.com-personal:me/r.git'}),
            ('git push', {'origin': 'https://github.mycorp.com/o/r.git'}),
            ('git push heroku main', {'heroku': 'https://git.heroku.com/app.git'}),
        ):
            with self.subTest(command=command, urls=urls):
                self.assertIsNone(bash(command, urls))

    def test_text_inside_quotes_and_heredocs_passes(self):
        for command in (
            'git commit -m "fix: tidy; git push later"',
            "cat > doc.md <<'EOF'\naz repos pr create --title x\nEOF",
            'gh pr create --body "line one\naz boards work-item update --id 1"',
            "gh pr create --body \"$(cat <<'EOF'\nthen git push to azure\nEOF\n)\"",
        ):
            with self.subTest(command=command):
                self.assertIsNone(bash(command))


def pwsh(command, urls=None):
    return outbound_post('PowerShell', {'command': command}, '.',
                         remotes({'origin': AZURE} if urls is None else urls))


class TestParserGaps(unittest.TestCase):
    """Inputs that hid a write from the parser, found after 14.1.0."""

    def test_comments_and_quoted_markers_do_not_hide_what_follows(self):
        for command in (
            "# Don't forget the review\naz repos pr create --title x",
            "echo ok # it's done\ngit push",
            'git commit -m "explain <<EOF"\naz repos pr create --title x',
            'grep -q x <<< foo\naz repos pr create --title x',
            'echo $((1<<2))\naz repos pr create --title x',
            'echo $[1<<2]\naz repos pr create --title x',
            'if((1<<2)); then :; fi\naz repos pr create --title x',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(bash(command))
        for command in (
            'Set-Location "C:\\work\\repo\\"\naz repos pr create --title x',
            "<# it's a note #>\naz boards work-item create --title x",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(pwsh(command))

    def test_commands_run_through_a_wrapper_ask(self):
        for command in (
            'bash -lc "az repos pr create --title x"',
            'eval "az repos pr create --title x"',
            'echo 5 | xargs az repos pr update --status completed --id',
            "bash <<'EOF'\naz repos pr create --title x\nEOF",
            "cat <<'EOF' | bash\naz repos pr create --title x\nEOF",
            'echo "az repos pr create --title x" | sh',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(bash(command))
        for command in (
            'Invoke-Expression "az repos pr create --title x"',
            "'az repos pr create --title x' | iex",
            "@'\naz repos pr create --title x\n'@ | Invoke-Expression",
            'pwsh -NoProfile -Command "az repos pr create --title x"',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(pwsh(command))

    def test_push_targets_set_in_the_same_command_ask(self):
        for command in (
            'git remote add gl https://gitlab.com/o/r.git && git push gl main',
            'url=https://gitlab.com/o/r.git; git push "$url" main',
            'git -c remote.origin.pushurl=https://gitlab.com/o/r.git push origin main',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(bash(command, {'origin': GITHUB}))

    def test_text_no_shell_runs_still_passes(self):
        for command in (
            "cat > run.sh <<'EOF'\naz repos pr create --title x\nEOF",
            'git commit -m "# not a comment; az repos pr create"',
        ):
            with self.subTest(command=command):
                self.assertIsNone(bash(command))
        self.assertIsNone(pwsh(
            "$body = @'\naz repos pr create --title x\n'@\ngh pr comment 1 --body $body"))


class TestDecision(unittest.TestCase):
    def test_the_hook_asks_and_never_denies(self):
        out = decision('a push to dev.azure.com')['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'PreToolUse')
        self.assertEqual(out['permissionDecision'], 'ask')
        self.assertIn('dev.azure.com', out['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
