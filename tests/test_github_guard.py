#!/usr/bin/env python3
"""Offline tests for the per-machine GitHub write allowlist."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
from github_guard import (  # noqa: E402
    active_account, denial, github_block, load_allowlist)

ALLOW = {'path': '~/.claude/synergy/github-allowlist.json',
         'account': 'AdrienneBosch', 'owners': ['Subverting-complexity']}
ORG = 'https://github.com/Subverting-complexity/claude-plugins.git'
OTHER = 'git@github.com:SomeoneElse/their-repo.git'


def check(command, here='Subverting-complexity', signed_in='AdrienneBosch',
          urls=None, allowlist=ALLOW, tool='Bash', tool_input=None):
    return github_block(
        tool, tool_input if tool_input is not None else {'command': command},
        '.', allowlist,
        account=lambda: signed_in,
        owner_of=lambda cwd: here,
        lookup=lambda cwd, remote: (urls or {'origin': ORG}).get(
            remote or 'origin', ''))


class TestAllowedOrg(unittest.TestCase):
    def test_writes_in_the_allowed_org_pass(self):
        for command in (
            'gh pr create --title x --body-file b.md',
            'gh pr merge 294 --squash --delete-branch',
            'gh issue comment 12 --body "see https://github.com/other/x"',
            'gh label create review-approved',
            'gh api repos/Subverting-complexity/claude-plugins/issues -f title=x',
            'gh api -X PATCH repos/{owner}/{repo}/issues/1',
            'gh api graphql -f query="mutation { addStar }"',
            'gh repo create Subverting-complexity/new-repo --private',
            'git push -u origin feature/x',
            'bash "$CLAUDE_PLUGIN_ROOT/scripts/wf.sh" post-merge --pr 293',
        ):
            with self.subTest(command=command):
                self.assertIsNone(check(command))


class TestOtherOwners(unittest.TestCase):
    def test_writes_to_another_owner_are_blocked(self):
        for command in (
            'gh pr create -R SomeoneElse/their-repo --title x',
            'gh issue create --repo SomeoneElse/their-repo --title x',
            'gh pr comment https://github.com/SomeoneElse/r/pull/3 --body hi',
            'gh api repos/SomeoneElse/r/issues -f title=x',
            'gh api -X DELETE orgs/SomeoneElse/members/x',
            'gh repo create SomeoneElse/new',
            'gh project item-add 3 --owner SomeoneElse --url u',
            'gh secret set TOKEN --org SomeoneElse',
            'n=$(gh pr create -R SomeoneElse/r --fill)',
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))

    def test_writes_in_a_repository_of_another_owner_are_blocked(self):
        for command in (
            'gh pr create --title x',
            'gh pr merge 3',
            'gh api graphql -f query="mutation { x }"',
            'wf.sh claim --issue 4',
            'bash scripts/wf.sh preflight --fix',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(check(command, here='SomeoneElse'))

    def test_the_personal_account_is_not_allowed(self):
        self.assertIn('AdrienneBosch', check('gh repo create scratch --public'))
        self.assertIn('AdrienneBosch', check('gh repo fork Subverting-complexity/x'))
        self.assertIn('AdrienneBosch', check('gh gist create notes.md'))
        self.assertIsNotNone(check('gh pr create', here='AdrienneBosch'))

    def test_a_push_to_another_owner_is_blocked(self):
        urls = {'origin': OTHER, 'org': ORG}
        self.assertIn('SomeoneElse', check('git push origin main', urls=urls))
        self.assertIsNone(check('git push org main', urls=urls))
        self.assertIsNotNone(
            check('git push https://github.com/SomeoneElse/r.git HEAD'))
        self.assertIsNotNone(
            check('git push git@github.com-work:SomeoneElse/r.git main'))

    def test_an_owner_that_cannot_be_worked_out_is_blocked(self):
        self.assertIsNotNone(check('gh pr create', here=None))
        self.assertIsNotNone(check('gh api -X POST markdown'))
        self.assertIsNotNone(check('gh repo create'))

    def test_cd_into_another_repository_is_followed(self):
        reason = github_block(
            'Bash', {'command': 'cd ../theirs && gh pr create --fill'}, '.',
            ALLOW, account=lambda: 'AdrienneBosch',
            owner_of=lambda cwd: 'SomeoneElse' if 'theirs' in cwd
            else 'Subverting-complexity')
        self.assertIn('SomeoneElse', reason)


class TestAccount(unittest.TestCase):
    def test_another_signed_in_account_blocks_every_write(self):
        reason = check('gh pr create --fill', signed_in='VantageAB')
        self.assertIn('VantageAB', reason)
        self.assertIsNotNone(check('git push', signed_in='VantageAB'))

    def test_an_unknown_account_blocks_writes(self):
        self.assertIsNotNone(check('gh pr merge 3', signed_in=None))

    def test_the_account_name_is_not_case_sensitive(self):
        self.assertIsNone(check('gh pr merge 3', signed_in='adriennebosch'))

    def test_no_account_in_the_list_checks_only_owners(self):
        allow = dict(ALLOW, account=None)
        self.assertIsNone(check('gh pr merge 3', signed_in='VantageAB',
                                allowlist=allow))


class TestReads(unittest.TestCase):
    def test_reads_anywhere_pass(self):
        for command in (
            'gh pr view 3 -R SomeoneElse/r',
            'gh issue list --repo SomeoneElse/r',
            'gh api repos/SomeoneElse/r/pulls',
            'gh api graphql -f query="query { viewer { login } }"',
            'gh repo clone SomeoneElse/r',
            'git clone https://github.com/SomeoneElse/r.git',
            'git fetch origin',
            'gh auth status',
            'git commit -m "gh pr create later"',
            'bash wf.sh candidates --limit 5',
            'bash wf.sh preflight',
            'bash wf.sh unblock --dry-run',
            'bash wf.sh review-next --no-claim',
        ):
            with self.subTest(command=command):
                self.assertIsNone(check(command, here='SomeoneElse',
                                        signed_in='VantageAB'))


class TestMcp(unittest.TestCase):
    def test_github_mcp_writes_follow_the_list(self):
        blocked = check(None, tool='mcp__github__create_issue',
                        tool_input={'owner': 'SomeoneElse', 'repo': 'r'})
        self.assertIn('SomeoneElse', blocked)
        self.assertIsNone(check(None, tool='mcp__github__create_issue',
                                tool_input={'owner': 'Subverting-complexity',
                                            'repo': 'r'}))
        self.assertIsNone(check(None, tool='mcp__github__list_issues',
                                tool_input={'owner': 'SomeoneElse'}))
        self.assertIsNone(check(None, tool='mcp__github__pull_request_read',
                                tool_input={'owner': 'SomeoneElse'}))


class TestNoList(unittest.TestCase):
    def test_a_machine_without_a_list_is_not_restricted(self):
        self.assertIsNone(check('gh pr create -R SomeoneElse/r', allowlist=None))

    def test_a_missing_file_means_no_list(self):
        self.assertIsNone(load_allowlist(os.path.join(tempfile.gettempdir(),
                                                      'no-such-allowlist.json')))

    def test_a_broken_file_blocks_writes_but_not_reads(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            f.write('{"owners": "Subverting-complexity"}')
        try:
            allow = load_allowlist(f.name)
        finally:
            os.unlink(f.name)
        self.assertIn('error', allow)
        self.assertIn('could not be read', check('gh pr merge 3', allowlist=allow))
        self.assertIsNone(check('gh pr view 3', allowlist=allow))

    def test_a_valid_file_loads(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump({'account': 'A', 'owners': ['B']}, f)
        try:
            allow = load_allowlist(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual((allow['account'], allow['owners']), ('A', ['B']))


class TestActiveAccount(unittest.TestCase):
    def test_reads_the_active_user_not_the_list_of_users(self):
        hosts = ('github.com:\n    git_protocol: https\n    users:\n'
                 '        VantageAB:\n        AdrienneBosch:\n'
                 '    user: AdrienneBosch\n')
        with tempfile.NamedTemporaryFile('w', suffix='.yml', delete=False) as f:
            f.write(hosts)
        saved = {k: os.environ.pop(k, None) for k in ('GH_TOKEN', 'GITHUB_TOKEN')}
        try:
            self.assertEqual(active_account(f.name), 'AdrienneBosch')
            os.environ['GH_TOKEN'] = 'x'
            self.assertIsNone(active_account(f.name))
        finally:
            os.environ.pop('GH_TOKEN', None)
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
            os.unlink(f.name)


class TestDenial(unittest.TestCase):
    def test_the_hook_denies_outright(self):
        out = denial('`gh pr create` to SomeoneElse', ALLOW)['hookSpecificOutput']
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('Subverting-complexity', out['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
