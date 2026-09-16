#!/usr/bin/env python3
"""Offline tests for the per-machine GitHub write allowlist."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
from command_parse import resolve_dir  # noqa: E402
from forge_guard import evaluate  # noqa: E402
from github_guard import (  # noqa: E402
    ACCOUNT, ALSO, CURRENT, GH_WRITES, HUB_RULES, HUB_VERB_RULES, NODES,
    OWNER_RULES, STRATEGIES, active_account, denial, github_block,
    github_owner, github_writes, load_allowlist)

ALLOW = {'path': '~/.claude/synergy/github-allowlist.json',
         'account': 'AdrienneBosch', 'owners': ['Subverting-complexity']}
ORG = 'https://github.com/Subverting-complexity/claude-plugins.git'
OTHER = 'git@github.com:SomeoneElse/their-repo.git'
SAME = object()


def check(command, here='Subverting-complexity', signed_in='AdrienneBosch',
          urls=None, allowlist=ALLOW, tool='Bash', tool_input=None,
          project=SAME, nodes=None, environ=None):
    return github_block(
        tool, tool_input if tool_input is not None else {'command': command},
        '.', allowlist,
        account=lambda: signed_in,
        owner_of=lambda cwd: here,
        lookup=lambda cwd, remote: (urls or {'origin': ORG}).get(
            remote or 'origin', ''),
        project_of=lambda cwd: here if project is SAME else project,
        nodes=lambda ids: {i: (nodes or {}).get(i) for i in ids},
        ssh_host=lambda alias: None,
        environ=environ or {})


def pwsh(command, **kwargs):
    return check(command, tool='PowerShell', **kwargs)


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


class TestWritesToOtherOwnersFoundAfterRelease(unittest.TestCase):
    """Writes to another owner that 14.1.0 let through."""

    def assertBlocked(self, reason, owner='SomeoneElse'):
        self.assertIsNotNone(reason)
        self.assertIn(owner, reason)

    def test_the_repo_flag_before_the_subcommand(self):
        self.assertBlocked(check('gh -R SomeoneElse/r pr create --title t'))
        self.assertBlocked(check('gh pr -R SomeoneElse/r create --title t'))
        self.assertBlocked(check('gh --repo=SomeoneElse/r issue close 3'))

    def test_gh_repo_in_the_environment(self):
        for command in (
            'GH_REPO=SomeoneElse/r gh pr create --fill',
            'export GH_REPO=SomeoneElse/r; gh issue create --title t',
            'env GH_REPO=SomeoneElse/r gh pr merge 3',
        ):
            with self.subTest(command=command):
                self.assertBlocked(check(command))
        self.assertBlocked(pwsh("$env:GH_REPO = 'SomeoneElse/r'\ngh pr merge 3"))
        self.assertBlocked(check('gh pr create --fill',
                                 environ={'GH_REPO': 'SomeoneElse/r'}))
        self.assertIsNone(check(
            'GH_REPO=Subverting-complexity/claude-plugins gh pr create --fill'))

    def test_commands_run_through_a_wrapper(self):
        for command in (
            'bash -lc "gh pr create -R SomeoneElse/r --fill"',
            'eval "gh issue close 1 -R SomeoneElse/r"',
            'c="gh pr merge 3 -R SomeoneElse/r"; eval "$c"',
            'echo 3 | xargs gh pr merge -R SomeoneElse/r',
            'echo 3 | xargs -I{} gh pr merge {} -R SomeoneElse/r',
            "bash <<'EOF'\ngh pr create -R SomeoneElse/r --fill\nEOF",
            "cat <<'EOF' | bash\ngh pr create -R SomeoneElse/r --fill\nEOF",
        ):
            with self.subTest(command=command):
                self.assertBlocked(check(command))
        for command in (
            'Invoke-Expression "gh pr merge 3 -R SomeoneElse/r"',
            '$c = "gh pr merge 3 -R SomeoneElse/r"; iex $c',
            "@'\ngh pr merge 3 -R SomeoneElse/r\n'@ | Invoke-Expression",
        ):
            with self.subTest(command=command):
                self.assertBlocked(pwsh(command))

    def test_text_that_used_to_leave_a_quote_or_heredoc_open(self):
        self.assertBlocked(check(
            "# Don't push to the wrong place\ngh pr create -R SomeoneElse/r --fill"))
        self.assertBlocked(check(
            'git commit -m "explain <<EOF"\ngh pr create -R SomeoneElse/r --fill'))
        self.assertBlocked(pwsh(
            'cd "C:\\Users\\me\\repo\\"\ngh pr create -R SomeoneElse/r --fill'))

    def test_rest_calls_and_hub(self):
        for command in (
            'curl -X POST https://api.github.com/repos/SomeoneElse/r/issues -d @b.json',
            "curl -d '{\"title\":\"x\"}' https://api.github.com/repos/SomeoneElse/r/issues",
            'hub api -X POST repos/SomeoneElse/r/issues',
        ):
            with self.subTest(command=command):
                self.assertBlocked(check(command))
        self.assertBlocked(pwsh(
            'Invoke-RestMethod -Method Post -Uri https://api.github.com/repos/SomeoneElse/r/issues -Body $b'))
        self.assertBlocked(check(
            "curl -d '{\"query\":\"mutation { addStar(input:{starrableId:\\\"R_kgDOabc12\\\"}) { clientMutationId } }\"}' https://api.github.com/graphql",
            nodes={'R_kgDOabc12': 'SomeoneElse'}))
        self.assertBlocked(check('hub pull-request -m x', here='SomeoneElse'))
        self.assertBlocked(check('hub issue create -m x', here='SomeoneElse'))
        self.assertBlocked(check('hub fork'), owner='AdrienneBosch')
        self.assertIsNone(check('curl https://api.github.com/repos/SomeoneElse/r'))
        self.assertIsNone(check(
            'curl -X POST https://api.github.com/repos/Subverting-complexity/claude-plugins/issues -d x'))
        self.assertIsNone(check('hub browse SomeoneElse/r'))

    def test_a_push_whose_target_is_set_in_the_command(self):
        for command in (
            'git remote add evil https://github.com/SomeoneElse/r.git && git push evil main',
            'url=https://github.com/SomeoneElse/r.git; git push "$url" HEAD',
            'git -c remote.origin.pushurl=https://github.com/SomeoneElse/r.git push origin main',
        ):
            with self.subTest(command=command):
                self.assertBlocked(check(command))
        for command in (
            'git push "$DESTINATION" main',
            'git -c url.https://github.com/SomeoneElse/.insteadOf=https://github.com/Subverting-complexity/ push',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(check(command))
        self.assertIsNotNone(check('git push origin main', urls={'other': ORG}))

    def test_gh_api_values_attached_to_the_flag(self):
        self.assertBlocked(check('gh api repos/SomeoneElse/r/issues -ftitle=t'))
        self.assertBlocked(check('gh api repos/SomeoneElse/r/labels --raw-field=name=x'))
        self.assertIsNotNone(check("gh api graphql -fquery='mutation { x }'",
                                   here='SomeoneElse'))
        self.assertIsNotNone(check(
            "gh api graphql --raw-field=query='mutation { x }'", here='SomeoneElse'))

    def test_graphql_mutations_are_judged_by_their_node_ids(self):
        command = ("gh api graphql -f query='mutation($id: ID!) { addComment("
                   "input: {subjectId: $id, body: \"hi\"}) { clientMutationId } }' "
                   "-f id=I_kwDOAbCdEf")
        self.assertBlocked(check(command, nodes={'I_kwDOAbCdEf': 'SomeoneElse'}))
        self.assertIsNone(check(command,
                                nodes={'I_kwDOAbCdEf': 'Subverting-complexity'}))
        self.assertIsNotNone(check(command, nodes={}))
        self.assertIsNotNone(check('gh api graphql --input missing-body.json'))
        self.assertIsNotNone(check('gh api graphql --input -'))
        self.assertIsNone(check(
            "gh api graphql -f query='query { node(id: \"I_kwDOAbCdEf\") { id } }'",
            nodes={}))

    def test_mcp_connectors_without_github_in_the_name(self):
        other = {'owner': 'SomeoneElse', 'repo': 'r'}
        self.assertBlocked(check(None, tool='mcp__7f3c9a__create_pull_request',
                                 tool_input=other))
        self.assertBlocked(check(None, tool='mcp__claude_ai_GitHub__create_issue',
                                 tool_input=other))
        self.assertIsNone(check(None, tool='mcp__7f3c9a__create_pull_request',
                                tool_input={'owner': 'Subverting-complexity',
                                            'repo': 'r'}))
        self.assertIsNone(check(None, tool='mcp__7f3c9a__list_pull_requests',
                                tool_input=other))
        self.assertIsNone(check(None, tool='mcp__slack__send_message',
                                tool_input={'channel': 'x'}))

    def test_a_fork_goes_to_the_account_unless_an_org_is_named(self):
        source = {'owner': 'Subverting-complexity', 'repo': 'x'}
        self.assertBlocked(check(None, tool='mcp__github__fork_repository',
                                 tool_input=source), owner='AdrienneBosch')
        self.assertIsNone(check(None, tool='mcp__github__fork_repository',
                                tool_input=dict(source,
                                                organization='Subverting-complexity')))

    def test_keys_ssh_keys_and_rtk_proxy(self):
        self.assertBlocked(check('gh repo deploy-key add key.pub -R SomeoneElse/r'))
        self.assertBlocked(check('gh repo deploy-key add key.pub', here='SomeoneElse'))
        self.assertBlocked(check('gh ssh-key add key.pub'), owner='AdrienneBosch')
        self.assertBlocked(check('rtk proxy gh pr create -R SomeoneElse/r --fill'))
        self.assertIsNone(check('gh repo deploy-key list -R SomeoneElse/r'))

    def test_wf_is_judged_by_the_org_in_claude_project(self):
        self.assertBlocked(check('bash scripts/wf.sh claim --issue 4',
                                 project='SomeoneElse'))
        self.assertIsNone(check('bash scripts/wf.sh post-merge --pr 3'))
        self.assertIsNone(check('bash scripts/wf.sh stage-set 4 --stage x',
                                project=None))


class TestWritesInsideTheOrgThatWereDenied(unittest.TestCase):
    def test_an_allowlist_with_a_byte_order_mark_loads(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                         encoding='utf-8-sig') as f:
            json.dump({'account': 'A', 'owners': ['B']}, f)
        try:
            allow = load_allowlist(f.name)
        finally:
            os.unlink(f.name)
        self.assertNotIn('error', allow)
        self.assertEqual(allow['owners'], ['B'])

    def test_cd_paths_windows_python_cannot_follow_are_resolved(self):
        self.assertEqual(resolve_dir('.', '/c/Users/me/repo', nt=True),
                         'C:/Users/me/repo')
        self.assertEqual(resolve_dir('.', '/mnt/d/work', nt=True), 'D:/work')
        home = os.path.expanduser('~')
        self.assertEqual(resolve_dir('.', '~/repo', nt=False),
                         os.path.join('.', home + '/repo'))
        seen = []
        reason = github_block(
            'Bash', {'command': 'cd ~/repo && gh pr create --fill'}, '.', ALLOW,
            account=lambda: 'AdrienneBosch',
            owner_of=lambda cwd: seen.append(cwd) or 'Subverting-complexity',
            environ={})
        self.assertIsNone(reason)
        self.assertTrue(seen[0].startswith(home))

    def test_ssh_alias_remotes_are_github(self):
        for url in ('git@github-work:Subverting-complexity/x.git',
                    'ssh://git@ssh.github.com:443/Subverting-complexity/x.git',
                    'git@github.com-personal:Subverting-complexity/x.git'):
            with self.subTest(url=url):
                self.assertEqual(github_owner(url), 'Subverting-complexity')
        self.assertEqual(github_owner('git@work:Org/x.git',
                                      ssh_host=lambda alias: 'github.com'), 'Org')
        self.assertIsNone(github_owner('https://github.mycorp.com/o/r.git'))
        self.assertIsNone(github_owner('https://api.github.com/repos/o/r'))

    def test_api_placeholders_and_variables(self):
        self.assertIsNone(check('gh api repos/:owner/:repo/issues -f title=x'))
        self.assertIsNotNone(check('gh api repos/:owner/:repo/issues -f title=x',
                                   here='SomeoneElse'))
        view = ('slug=$(gh repo view --json nameWithOwner --jq .nameWithOwner)\n'
                'gh api -X PATCH "repos/$slug" -F allow_auto_merge=true')
        self.assertIsNone(check(view))
        self.assertIsNotNone(check(view, here='SomeoneElse'))
        self.assertIsNone(check(
            'slug=Subverting-complexity/claude-plugins; gh api -X PATCH repos/$slug -f x=y'))
        self.assertIsNotNone(check('gh api -X PATCH repos/$UNSET/x -f a=b'))

    def test_project_item_edit_is_judged_by_its_project(self):
        command = ('gh project item-edit --id PVTI_lADOabc12 --project-id '
                   'PVT_kwDOabc12 --field-id F --text x')
        self.assertIsNone(check(command,
                                nodes={'PVT_kwDOabc12': 'Subverting-complexity'}))
        self.assertIsNotNone(check(command, nodes={}))

    def test_a_reviewer_flag_is_not_a_repository(self):
        self.assertIsNone(check('gh pr create -r AdrienneBosch --fill'))


class TestThePluginsOwnFlows(unittest.TestCase):
    def test_workflow_commands_pass_inside_the_allowed_org(self):
        for command in (
            'bash "$CLAUDE_PLUGIN_ROOT/scripts/wf.sh" pick --issue 295 --checkout',
            'bash "C:/Users/me/.claude/plugins/cache/subverting-complexity/synergy/14.1.0/scripts/wf.sh" claim-release --issue 1',
            'export CLAUDE_PLUGIN_ROOT="/p"; bash "$CLAUDE_PLUGIN_ROOT/scripts/wf.sh" post-merge --pr 3',
            'gh pr create --title x --body-file .claude/pr-body.md --base main',
            'gh pr merge 297 --squash --delete-branch',
            'gh issue comment 295 --body-file .claude/comment.md',
            'git push -u origin feature/295/close-the-gaps',
            'git push origin refs/claims/issue-295',
            'git push origin :refs/claims/issue-295',
        ):
            with self.subTest(command=command):
                self.assertIsNone(check(command))
        self.assertIsNone(pwsh(
            '& "$env:CLAUDE_PLUGIN_ROOT\\scripts\\wf.ps1" stage-set 1 --stage stage-backlog'))


class TestUnreadableCalls(unittest.TestCase):
    def test_a_call_the_guard_cannot_read_is_denied_when_it_looks_like_a_write(self):
        def broken(*args):
            raise ValueError('boom')
        out = evaluate('{not json: gh pr create --fill', lambda: ALLOW)
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')
        event = json.dumps({'tool_name': 'Bash',
                            'tool_input': {'command': 'gh pr merge 3'}})
        out = evaluate(event, lambda: ALLOW, block=broken)
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_reads_and_machines_without_a_list_still_pass(self):
        def broken(*args):
            raise ValueError('boom')
        event = json.dumps({'tool_name': 'Bash',
                            'tool_input': {'command': 'gh pr view 3'}})
        self.assertIsNone(evaluate(event, lambda: ALLOW, block=broken))
        self.assertIsNone(evaluate('{not json: gh pr create', lambda: None))

    def test_an_mcp_repo_that_is_not_text_is_denied(self):
        self.assertIsNotNone(check(None, tool='mcp__github__create_issue',
                                   tool_input={'repo': {'name': 'r'}}))
        self.assertIsNotNone(check(None, tool='mcp__github__create_issue',
                                   tool_input={'owner': ['SomeoneElse'],
                                               'repo': 'r'}))


class TestGapsFoundInReview(unittest.TestCase):
    """Writes the independent review of PR #297 found still passing."""

    def test_here_strings_and_shifts_are_not_heredocs(self):
        for command in (
            'grep -q x <<< foo\ngh pr create -R SomeoneElse/r --title t --body b',
            'echo $((x<<y))\ngh pr create -R SomeoneElse/r --fill',
            '(( n = 1 << 2 ))\ngh pr create -R SomeoneElse/r --fill',
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))

    def test_owner_placeholders_follow_gh_repo(self):
        for command in (
            'GH_REPO=SomeoneElse/r gh api repos/{owner}/{repo}/issues -f title=t',
            'export GH_REPO=SomeoneElse/r; gh api repos/:owner/:repo/labels -f name=x',
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))
        self.assertIn('SomeoneElse', check(
            'gh api repos/{owner}/{repo}/issues -f title=t',
            environ={'GH_REPO': 'SomeoneElse/r'}))

    def test_only_a_view_of_the_current_repository_is_current(self):
        for command in (
            'slug=$(gh repo view SomeoneElse/r --json nameWithOwner -q .nameWithOwner); gh api repos/$slug/issues -f title=t',
            'export GH_REPO=SomeoneElse/r; slug=$(gh repo view --json nameWithOwner -q .nameWithOwner); gh api -X PATCH repos/$slug -f a=b',
            'gh api repos/$(gh repo view SomeoneElse/r --json nameWithOwner -q .nameWithOwner)/issues -f title=t',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(check(command))
        self.assertIsNone(check(
            'gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/issues -f title=t'))

    def test_a_node_id_held_in_a_variable_cannot_be_judged(self):
        command = ('ID=$(gh api repos/SomeoneElse/r/issues/1 -q .node_id); '
                   "gh api graphql -f query='mutation($id: ID!) { addComment("
                   "input: {subjectId: $id, body: \"x\"}) { clientMutationId } }' "
                   '-f id="$ID"')
        self.assertIsNotNone(check(command))
        self.assertIsNotNone(check('gh api graphql -f query="$QUERY"'))

    def test_gh_aliases_for_write_actions(self):
        for command in (
            'gh pr new -R SomeoneElse/r -t t -b b',
            'gh issue new -R SomeoneElse/r -t t',
            'gh release new v1 -R SomeoneElse/r',
            'gh repo new SomeoneElse/x --private',
            'gh variable remove X -R SomeoneElse/r',
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))
        self.assertIn('AdrienneBosch', check('gh gist new notes.md'))

    def test_git_config_remote_urls_set_in_the_command(self):
        for command in (
            'git config remote.origin.pushurl https://github.com/SomeoneElse/r.git && git push origin main',
            'git config set remote.evil.url https://github.com/SomeoneElse/r.git; git push evil main',
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))

    def test_ansi_quotes_and_unclosed_quotes(self):
        self.assertIn('SomeoneElse', check(
            "echo $'don\\'t'; gh pr create -R SomeoneElse/r -t t -b b"))
        event = json.dumps({'tool_name': 'Bash', 'tool_input': {
            'command': 'echo "oops; gh pr create -R SomeoneElse/r --fill'}})
        out = evaluate(event, lambda: ALLOW)
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')
        read = json.dumps({'tool_name': 'Bash', 'tool_input': {
            'command': 'echo "oops; gh pr view 3'}})
        self.assertIsNone(evaluate(read, lambda: ALLOW))

    def test_an_encoded_powershell_command_is_decoded(self):
        import base64
        script = base64.b64encode(
            'gh pr create -R SomeoneElse/r --fill'.encode('utf-16-le')).decode()
        self.assertIn('SomeoneElse', pwsh('pwsh -NoProfile -EncodedCommand ' + script))


class TestGapsFoundInReReview(unittest.TestCase):
    """Writes the second review of PR #297 found still passing."""

    def test_substitutions_inside_arithmetic_are_read(self):
        for command in (
            'echo $((echo x) | gh pr create -R SomeoneElse/r --fill)',
            'echo $(( $(gh pr create -R SomeoneElse/r --fill >/dev/null; echo 1) + 1 ))',
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))
        self.assertIn('SomeoneElse', pwsh(
            'Write-Output $((gh pr create -R SomeoneElse/r --fill))'))

    def test_every_arithmetic_form_is_not_a_heredoc(self):
        for command in (
            'echo $[x<<y]\ngh pr create -R SomeoneElse/r --fill',
            'if((x<<y)); then :; fi\ngh pr create -R SomeoneElse/r --fill',
            'while((x<<y)); do :; done\ngh pr create -R SomeoneElse/r --fill',
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))
        self.assertIsNone(check('(( n++ ))\ngh pr create --fill'))
        self.assertIsNone(check(
            "gh pr create --fill --body \"$(cat <<'EOF'\nx << y\nEOF\n)\""))

    def test_a_view_given_gh_repo_is_not_current(self):
        for command in (
            'slug=$(GH_REPO=SomeoneElse/r gh repo view --json nameWithOwner -q .nameWithOwner); gh api repos/$slug/issues -f title=t',
            'slug=$(env GH_REPO=SomeoneElse/r gh repo view --json nameWithOwner -q .nameWithOwner); gh api repos/$slug/issues -f title=t',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(check(command))

    def test_graphql_values_from_the_shell_or_a_file_cannot_be_judged(self):
        for command in (
            'ID=$(gh api repos/SomeoneElse/r/issues/1 -q .node_id); gh api graphql -f query="mutation { addComment(input: {subjectId: \\"$ID\\", body: \\"x\\"}) { clientMutationId } }"',
            "gh api graphql -f query='mutation($id: ID!) { addComment(input: {subjectId: $id, body: \"x\"}) { clientMutationId } }' -F id=@id.txt",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(check(command))

    def test_git_config_with_a_file_or_an_insteadof_rewrite(self):
        self.assertIn('SomeoneElse', check(
            'git config -f .git/config remote.origin.pushurl https://github.com/SomeoneElse/r.git && git push origin main'))
        self.assertIsNotNone(check(
            'git config url.https://github.com/SomeoneElse/.pushInsteadOf https://github.com/Subverting-complexity/ && git push origin main'))

    def test_every_prefix_of_the_encoded_command_flag(self):
        import base64
        script = base64.b64encode(
            'gh pr create -R SomeoneElse/r --fill'.encode('utf-16-le')).decode()
        for flag in ('-en', '-enco', '-encoded', '/ec', '--EncodedCommand'):
            with self.subTest(flag=flag):
                self.assertIn('SomeoneElse', pwsh(
                    'pwsh -NoProfile %s %s' % (flag, script)))


class TestGapsFoundInThirdReview(unittest.TestCase):
    """Writes the third review of PR #297 found still passing."""

    def test_quoted_or_commented_arithmetic_hides_no_heredoc(self):
        for command in (
            'echo "((" ; cat <<EOF\nit\'s\nEOF\ngh pr create -R SomeoneElse/r --fill #\'',
            "echo '$[' ; cat <<EOF\nit's\nEOF\ngh pr create -R SomeoneElse/r --fill #'",
            "# ((\ncat <<EOF\nit's\nEOF\ngh pr create -R SomeoneElse/r --fill #'",
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))
        for command in (
            "gh pr create --title \"Handle (( in the parser\" --body \"$(cat <<'EOF'\nIt's fixed.\nEOF\n)\"",
            "gh pr create --fill --body \"$(cat <<'EOF'\nuse $[ here, it's fine\nEOF\n)\"",
        ):
            with self.subTest(command=command):
                self.assertIsNone(check(command))

    def test_an_encoded_script_python_cannot_decode_cleanly(self):
        import base64
        raw = 'gh pr create -R SomeoneElse/r --fill'.encode('utf-16-le')
        for extra in (b'\x00', b'\x00\xd8'):
            with self.subTest(extra=extra):
                script = base64.b64encode(raw + extra).decode()
                self.assertIn('SomeoneElse', pwsh('pwsh -NoProfile -enc ' + script))

    def test_a_graphql_declaration_must_be_in_the_signature(self):
        self.assertIsNotNone(check(
            'ID=$(gh api repos/SomeoneElse/r/issues/1 -q .node_id); gh api graphql -f query="mutation { addComment(input: {subjectId: \\"$ID\\", body: \\"$ID: x\\"}) { clientMutationId } }"'))

    def test_a_graphql_variable_named_like_a_shell_variable(self):
        self.assertIsNotNone(check(
            'ID=$(gh api repos/SomeoneElse/r/issues/1 -q .node_id); gh api graphql -f query="mutation(\\$ID: ID) { addComment(input: {subjectId: \\"$ID\\", body: \\"x\\"}) { clientMutationId } }"'))

    def test_git_config_after_git_options(self):
        for command in (
            'git -C . config remote.origin.pushurl https://github.com/SomeoneElse/r.git && git push origin main',
            'git -c core.x=y config remote.origin.pushurl https://github.com/SomeoneElse/r.git && git push origin main',
        ):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))

    def test_a_view_whose_output_is_rewritten_or_replaced(self):
        for command in (
            'slug=$(gh repo view --json nameWithOwner -q \'"SomeoneElse/r"\'); gh api repos/$slug/issues -f title=t',
            'slug=$(gh repo view --json nameWithOwner -q .nameWithOwner); read slug <<< SomeoneElse/r; gh api repos/$slug/issues -f title=t',
            'slug=$(gh repo view --json nameWithOwner -q .nameWithOwner | sed s/Subverting-complexity/SomeoneElse/); gh api repos/$slug/issues -f title=t',
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(check(command))
        self.assertIsNone(check(
            'REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner); gh api repos/$REPO/issues -f title=t'))


class TestGapsFoundInRobustnessReview(unittest.TestCase):
    """Pushes inside the allowed org that the review of 16.1.0 found denied."""

    def block(self, command):
        # Only the repository the call starts in has remotes, so a push
        # followed into a directory synergy made up finds none.
        return github_block(
            'Bash', {'command': command}, '.', ALLOW,
            account=lambda: 'AdrienneBosch',
            owner_of=lambda cwd: 'Subverting-complexity',
            lookup=lambda cwd, remote: ORG if cwd == '.' else '',
            ssh_host=lambda alias: None, environ={})

    def test_a_computed_directory_keeps_the_working_directory(self):
        for command in (
            'cd "$(git rev-parse --show-toplevel)" && git push origin HEAD',
            'git -C "$(git rev-parse --show-toplevel)" push origin HEAD',
            'cd "$UNSET_DIR" && git push origin HEAD',
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.block(command))

    def test_a_push_naming_no_remote_is_not_sent_to_an_added_one(self):
        self.assertIsNone(check(
            'git remote add upstream https://github.com/upstream-org/app.git'
            ' && git fetch upstream && git rebase upstream/main'
            ' && git push --force-with-lease'))
        self.assertIn('SomeoneElse', check(
            'git remote set-url origin https://github.com/SomeoneElse/r.git'
            ' && git push'))

    def test_a_push_remote_the_command_sets_is_followed(self):
        # A push naming no remote goes to origin only when nothing in the
        # command chooses another push remote.
        for command in (
                'git -c remote.pushDefault=evil'
                ' -c remote.evil.url=https://github.com/SomeoneElse/r.git push',
                'git -c branch.main.pushRemote=evil'
                ' -c remote.evil.url=https://github.com/SomeoneElse/r.git push',
                'git remote add evil https://github.com/SomeoneElse/r.git'
                ' && git config remote.pushDefault evil && git push'):
            with self.subTest(command=command):
                self.assertIn('SomeoneElse', check(command))

    def test_a_remote_added_with_a_tracked_branch_is_followed(self):
        self.assertIn('SomeoneElse', check(
            'git remote add -t main evil https://github.com/SomeoneElse/r.git'
            ' && git push evil main'))
        self.assertIn('SomeoneElse', check(
            'git remote add --track=main evil https://github.com/SomeoneElse/r.git'
            ' && git push evil main'))


BASH = shutil.which('bash')
HOOK = os.path.join(os.path.dirname(__file__), '..', 'synergy', 'hooks',
                    'forge-guard.sh')


@unittest.skipIf(not BASH or 'system32' in (BASH or '').lower(),
                 'needs a POSIX bash')
class TestHookInterpreter(unittest.TestCase):
    def test_the_hook_starts_the_guard_for_a_write_on_a_later_line(self):
        with tempfile.TemporaryDirectory() as data:
            data = data.replace('\\', '/')
            allow = data + '/allow.json'
            with open(allow, 'w') as f:
                json.dump({'owners': ['Subverting-complexity']}, f)
            env = dict(os.environ, CLAUDE_PLUGIN_DATA=data,
                       SYNERGY_GITHUB_ALLOWLIST=allow)
            for command in (
                'echo ok\ngh pr create -R SomeoneElse/r --fill',
                'cat <<EOF\nhello\nEOF\ngh pr create -R SomeoneElse/r --fill',
                'echo ok\n\tgh issue create -R SomeoneElse/r -t t',
            ):
                event = json.dumps({'tool_name': 'Bash', 'cwd': '.',
                                    'tool_input': {'command': command}})
                out = subprocess.run([BASH, HOOK.replace('\\', '/')], input=event,
                                     capture_output=True, text=True, env=env,
                                     timeout=120)
                self.assertIn('"deny"', out.stdout, command)

    def test_the_hook_starts_the_guard_for_an_encoded_powershell_command(self):
        import base64
        script = base64.b64encode(
            'gh pr create -R SomeoneElse/r --fill'.encode('utf-16-le')).decode()
        with tempfile.TemporaryDirectory() as data:
            data = data.replace('\\', '/')
            allow = data + '/allow.json'
            with open(allow, 'w') as f:
                json.dump({'owners': ['Subverting-complexity']}, f)
            env = dict(os.environ, CLAUDE_PLUGIN_DATA=data,
                       SYNERGY_GITHUB_ALLOWLIST=allow)
            for flag in ('-EncodedCommand', '-enco', "'-enc'", '"-EncodedCommand"'):
                event = json.dumps({
                    'tool_name': 'PowerShell', 'cwd': '.',
                    'tool_input': {'command': 'pwsh -NoProfile %s %s' % (flag, script)}})
                out = subprocess.run([BASH, HOOK.replace('\\', '/')], input=event,
                                     capture_output=True, text=True, env=env,
                                     timeout=120)
                self.assertIn('"deny"', out.stdout, flag)

    def test_a_cached_interpreter_that_does_not_run_the_script_is_replaced(self):
        with tempfile.TemporaryDirectory() as data:
            data = data.replace('\\', '/')
            cache = data + '/guard-python'
            with open(cache, 'w') as f:
                f.write('true')
            allow = data + '/allow.json'
            with open(allow, 'w') as f:
                json.dump({'owners': ['Subverting-complexity']}, f)
            env = dict(os.environ, CLAUDE_PLUGIN_DATA=data,
                       SYNERGY_GITHUB_ALLOWLIST=allow)
            event = json.dumps({
                'tool_name': 'Bash', 'cwd': '.',
                'tool_input': {'command': 'gh pr create -R SomeoneElse/r --fill'}})
            out = subprocess.run([BASH, HOOK.replace('\\', '/')], input=event,
                                 capture_output=True, text=True, env=env,
                                 timeout=120)
            self.assertIn('"deny"', out.stdout)
            with open(cache) as f:
                self.assertNotEqual(f.read().strip(), 'true')


def writes(command):
    """The (owner, what) pairs github_writes finds in one Bash command."""
    return [w[:2] for w in github_writes(
        'Bash', {'command': command}, '.', lookup=lambda cwd, remote: '',
        ssh_host=lambda alias: None, environ={})]


class TestOwnerExtraction(unittest.TestCase):
    """Characterisation of where each `gh` and `hub` write's owner comes
    from, captured before those rules were moved into a table."""

    def assertWrites(self, cases):
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(writes(command), expected)

    def test_issue_transfer_yields_the_destination_then_the_source(self):
        what = '`gh issue transfer`'
        self.assertWrites((
            ('gh issue transfer 12 SomeoneElse/dest',
             [('SomeoneElse', what), (CURRENT, what)]),
            ('gh issue transfer 12 SomeoneElse/dest -R Other/src',
             [('SomeoneElse', what), ('Other', what)]),
            ('gh issue transfer -R Other/src 12 SomeoneElse/dest',
             [('SomeoneElse', what), ('Other', what)]),
            ('gh issue transfer 12 https://github.com/SomeoneElse/dest',
             [('SomeoneElse', what), (CURRENT, what)]),
            ('gh issue transfer 12', [(CURRENT, what)]),
        ))

    def test_issue_transfer_needs_both_owners_allowed(self):
        self.assertIn('SomeoneElse',
                      check('gh issue transfer 12 SomeoneElse/dest'))
        self.assertIn('SomeoneElse', check(
            'gh issue transfer 12 Subverting-complexity/dest -R SomeoneElse/src'))
        self.assertIsNone(check(
            'gh issue transfer 12 Subverting-complexity/dest'))

    def test_project_owners(self):
        self.assertWrites((
            ('gh project field-delete --id PVTF_lADOABCDEF',
             [((NODES, ('PVTF_lADOABCDEF',)), '`gh project field-delete`')]),
            ('gh project field-delete --id notanode',
             [(None, '`gh project field-delete`')]),
            ('gh project field-delete', [(None, '`gh project field-delete`')]),
            ('gh project item-edit --project-id PVT_kwDOABCDEF --id x',
             [((NODES, ('PVT_kwDOABCDEF',)), '`gh project item-edit`')]),
            ('gh project item-add 3 --owner @me --url u',
             [(ACCOUNT, '`gh project item-add`')]),
            ('gh project create --title t', [(ACCOUNT, '`gh project create`')]),
            ('gh project item-add 3 --owner SomeoneElse --url u',
             [('SomeoneElse', '`gh project item-add`')]),
        ))

    def test_secret_and_variable_owners(self):
        self.assertWrites((
            ('gh secret set TOKEN --org SomeoneElse',
             [('SomeoneElse', '`gh secret set`')]),
            ('gh secret set TOKEN -o SomeoneElse',
             [('SomeoneElse', '`gh secret set`')]),
            ('gh secret set TOKEN --user', [(ACCOUNT, '`gh secret set`')]),
            ('gh secret set TOKEN -u', [(ACCOUNT, '`gh secret set`')]),
            ('gh variable set X --org SomeoneElse',
             [('SomeoneElse', '`gh variable set`')]),
            ('gh variable delete X -o SomeoneElse',
             [('SomeoneElse', '`gh variable delete`')]),
            ('gh variable set X --user', [(ACCOUNT, '`gh variable set`')]),
            ('gh variable remove X -u', [(ACCOUNT, '`gh variable delete`')]),
            ('gh variable set X -R SomeoneElse/r',
             [('SomeoneElse', '`gh variable set`')]),
            ('gh secret set X --org SomeoneElse -R Other/r',
             [('SomeoneElse', '`gh secret set`')]),
            ('gh secret set X', [(CURRENT, '`gh secret set`')]),
        ))

    def test_nested_and_account_owners(self):
        self.assertWrites((
            ('gh repo autolink create --key-prefix T- --url-template u',
             [(CURRENT, '`gh repo autolink create`')]),
            ('gh repo autolink delete 3 -R SomeoneElse/r',
             [('SomeoneElse', '`gh repo autolink delete`')]),
            ('gh repo autolink list', []),
            ('gh repo deploy-key add k.pub -R SomeoneElse/r',
             [('SomeoneElse', '`gh repo deploy-key add`')]),
            ('gh gpg-key add key.asc', [(ACCOUNT, '`gh gpg-key add`')]),
            ('gh gpg-key delete 1', [(ACCOUNT, '`gh gpg-key delete`')]),
            ('gh ssh-key add k.pub -R SomeoneElse/r',
             [(ACCOUNT, '`gh ssh-key add`')]),
            ('gh gist create notes.md', [(ACCOUNT, '`gh gist create`')]),
        ))

    def test_repository_owners(self):
        self.assertWrites((
            ('gh repo fork SomeoneElse/r', [(ACCOUNT, '`gh repo fork`')]),
            ('gh repo fork SomeoneElse/r --org MyOrg',
             [('MyOrg', '`gh repo fork`')]),
            ('gh repo create scratch', [(ACCOUNT, '`gh repo create`')]),
            ('gh repo create', [(None, '`gh repo create`')]),
            ('gh repo create SomeoneElse/new',
             [('SomeoneElse', '`gh repo create`')]),
            ('gh repo delete SomeoneElse/r',
             [('SomeoneElse', '`gh repo delete`')]),
            ('gh repo edit https://github.com/SomeoneElse/r',
             [('SomeoneElse', '`gh repo edit`')]),
            ('gh pr comment https://github.com/SomeoneElse/r/pull/3 --body hi',
             [('SomeoneElse', '`gh pr comment`')]),
            ('gh pr create --fill', [(CURRENT, '`gh pr create`')]),
            ('gh pr new --fill', [(CURRENT, '`gh pr create`')]),
            ('GH_REPO=SomeoneElse/r gh pr create --fill',
             [('SomeoneElse', '`gh pr create`')]),
            ('gh label remove x', [(CURRENT, '`gh label delete`')]),
            ('gh pr view 3', []),
        ))

    def test_every_rule_names_known_strategies_and_ends_in_a_decision(self):
        # Steps that can fall through, so cannot be a row's last step.
        falls_through = {'flag', 'switch', 'spec-flag', 'url-arg', 'slug-arg',
                         'env-repo', 'positional'}
        tables = {'OWNER_RULES': OWNER_RULES, 'HUB_RULES': HUB_RULES,
                  'HUB_VERB_RULES': HUB_VERB_RULES}
        for table, rules in tables.items():
            for key, rule in rules.items():
                with self.subTest(table=table, key=key):
                    steps = [s[1:] if s[0] == ALSO else s for s in rule]
                    for step in steps:
                        self.assertIn(step[0], STRATEGIES)
                    self.assertNotEqual(rule[-1][0], ALSO)
                    self.assertNotIn(rule[-1][0], falls_through)
        for key in OWNER_RULES:
            group = key[0] if isinstance(key, tuple) else key
            with self.subTest(key=key):
                self.assertIn(group, GH_WRITES)

    def test_hub_owners(self):
        self.assertWrites((
            ('hub pull-request -m x', [(CURRENT, '`hub pull-request`')]),
            ('hub merge x', [(CURRENT, '`hub merge`')]),
            ('hub sync', [(CURRENT, '`hub sync`')]),
            ('hub fork', [(ACCOUNT, '`hub fork`')]),
            ('hub fork --org MyOrg', [('MyOrg', '`hub fork`')]),
            ('hub create', [(ACCOUNT, '`hub create`')]),
            ('hub create SomeoneElse/r', [('SomeoneElse', '`hub create`')]),
            ('hub delete r', [(ACCOUNT, '`hub delete`')]),
            ('hub issue create -m x', [(CURRENT, '`hub issue create`')]),
            ('hub release create v1', [(CURRENT, '`hub release create`')]),
            ('hub gist create f', [(ACCOUNT, '`hub gist create`')]),
            ('hub issue list', []),
            ('hub browse SomeoneElse/r', []),
        ))


class TestDenial(unittest.TestCase):
    def test_the_hook_denies_outright(self):
        out = denial('`gh pr create` to SomeoneElse', ALLOW)['hookSpecificOutput']
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('Subverting-complexity', out['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
