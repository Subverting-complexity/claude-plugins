#!/usr/bin/env python3
"""Offline tests for the guard that asks before posting outside GitHub."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
from forge_guard import decision, evaluate, outbound_post  # noqa: E402

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
        self.assertIsNotNone(outbound_post(
            'mcp__AzureDevOps__create_pull_request', {}))
        self.assertIsNotNone(outbound_post(
            'mcp__azdo__create_pull_request', {}))
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


def event(command, tool='Bash', cwd='.', description=None):
    tool_input = {'command': command}
    if description:
        tool_input['description'] = description
    return json.dumps({'tool_name': tool, 'cwd': cwd, 'tool_input': tool_input})


class TestGapsFoundInRobustnessReview(unittest.TestCase):
    """Calls the review of 16.1.0 found judged wrongly."""

    def test_a_heredoc_with_a_backslash_delimiter_hides_nothing(self):
        command = ("cat <<\\EOF\nit's here\nEOF\n"
                   'git push https://dev.azure.com/org/p/_git/r main')
        self.assertIsNotNone(bash(command, {}))

    def test_a_call_that_cannot_be_read_and_names_a_forge_asks(self):
        post = (lambda name, tool_input, cwd:
                outbound_post(name, tool_input, cwd, remotes({})))
        out = evaluate(event(
            'echo "oops; git push https://dev.azure.com/org/p/_git/r main'),
            lambda: None, post=post)
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'ask')
        self.assertIsNone(evaluate(event('echo "oops; git status'),
                                   lambda: None, post=post))

    def test_only_the_command_of_an_unreadable_call_is_judged(self):
        allow = {'path': 'allow.json', 'account': None,
                 'owners': ['Subverting-complexity']}
        unreadable = event('echo "oops', cwd='/home/me/github/app',
                           description='write the notes')
        self.assertIsNone(evaluate(unreadable, lambda: allow))
        self.assertIsNone(evaluate(
            event('echo "oops', cwd='/home/me/gitlab/app',
                  description='push the notes'), lambda: None))

    def test_a_remote_added_with_a_tracked_branch_is_followed(self):
        self.assertIsNotNone(bash(
            'git remote add -t main az https://dev.azure.com/org/p/_git/r'
            ' && git push az main', {'origin': GITHUB}))
        self.assertIsNotNone(bash(
            'git remote add -f --tags -m main az https://dev.azure.com/org/p/_git/r'
            ' && git push az main', {'origin': GITHUB}))

    def test_a_python_too_old_for_the_script_prints_nothing(self):
        script = os.path.join(os.path.dirname(__file__), '..', 'synergy',
                              'scripts', 'forge_guard.py')
        # The script's own folder is on the path when the hook runs it.
        old = ('import os, runpy, sys; sys.version_info = (3, 6, 0); '
               'sys.argv = sys.argv[1:]; '
               'sys.path.insert(0, os.path.dirname(sys.argv[0])); '
               'runpy.run_path(sys.argv[0], run_name="__main__")')
        out = subprocess.run([sys.executable, '-c', old, script],
                             input=event('az repos pr create --title x'),
                             capture_output=True, text=True, timeout=60)
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout, '')


BASH = shutil.which('bash')
HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, '..', 'synergy', 'hooks', 'forge-guard.sh')


def hook_event(tool, tool_input, cwd):
    """A PreToolUse event shaped as Claude Code sends it."""
    return json.dumps({
        'session_id': 's1', 'transcript_path': cwd + '/s1.jsonl', 'cwd': cwd,
        'permission_mode': 'default', 'hook_event_name': 'PreToolUse',
        'tool_name': tool, 'tool_input': tool_input, 'tool_use_id': 'toolu_1'})


def recorded_writes():
    """(tool, tool_input) for every call the guard tests expect an answer on,
    found by running those tests with the guard wrapped."""
    spec = importlib.util.spec_from_file_location(
        'recorded_github_guard_tests', os.path.join(HERE, 'test_github_guard.py'))
    github_tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(github_tests)
    calls = []

    def wrap(real):
        def recorder(tool, tool_input, *args, **kwargs):
            out = real(tool, tool_input, *args, **kwargs)
            if out is not None:
                calls.append((tool, dict(tool_input or {})))
            return out
        return recorder

    this = sys.modules[__name__]
    patches = [(this, 'outbound_post'), (github_tests, 'github_block')]
    saved = [getattr(module, name) for module, name in patches]
    try:
        for module, name in patches:
            setattr(module, name, wrap(getattr(module, name)))
        for module in (this, github_tests):
            suite = unittest.TestLoader().loadTestsFromModule(module)
            cases = [case for group in suite for case in group
                     if not type(case).__name__.startswith('TestHook')]
            unittest.TestSuite(cases).run(unittest.TestResult())
    finally:
        for (module, name), real in zip(patches, saved):
            setattr(module, name, real)
    unique = {}
    for tool, tool_input in calls:
        unique[(tool, json.dumps(tool_input, sort_keys=True))] = (tool, tool_input)
    return list(unique.values())


@unittest.skipIf(not BASH or 'system32' in (BASH or '').lower(),
                 'needs a POSIX bash')
class TestHookFilter(unittest.TestCase):
    """The text check in forge-guard.sh that decides whether to start Python."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp().replace('\\', '/')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # An interpreter that notes it was started, then runs the real one.
        self.logger = self.tmp + '/logging-python'
        with open(self.logger, 'w', newline='\n') as f:
            f.write('#!/bin/sh\n: > "$CLAUDE_PLUGIN_DATA/ran"\nexec "%s" "$@"\n'
                    % sys.executable.replace('\\', '/'))
        os.chmod(self.logger, 0o755)

    def data_dir(self, name, allowlist=None, cache=None):
        data = '%s/%s' % (self.tmp, name)
        os.makedirs(data)
        if allowlist is not None:
            with open(data + '/allow.json', 'w') as f:
                json.dump(allowlist, f)
        if cache is not None:
            with open(data + '/guard-python', 'w') as f:
                f.write(cache)
        return data

    def run_hook(self, data, event):
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=data,
                   SYNERGY_GITHUB_ALLOWLIST=data + '/allow.json')
        return subprocess.run([BASH, HOOK.replace('\\', '/')], input=event,
                              capture_output=True, text=True, env=env,
                              timeout=120).stdout.strip()

    def test_every_write_the_tests_know_still_reaches_python(self):
        # An account nobody is signed in as denies each GitHub write before
        # any owner is looked up, so no call leaves this machine.
        allow = {'account': 'synergy-test-account', 'owners': ['Subverting-complexity']}
        writes = recorded_writes()
        self.assertGreater(len(writes), 150)

        def judge(item):
            index, (tool, tool_input) = item
            data = self.data_dir(str(index), allow, self.logger)
            event = hook_event(tool, tool_input, data)
            out = self.run_hook(data, event)
            expected = evaluate(event, lambda: dict(allow, path=data + '/allow.json'))
            return (tool, tool_input, os.path.exists(data + '/ran'), out,
                    json.dumps(expected) if expected else '')

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(judge, enumerate(writes)))
        for tool, tool_input, ran, out, expected in results:
            with self.subTest(tool=tool, tool_input=tool_input):
                self.assertTrue(ran, 'the hook did not start Python')
                self.assertEqual(out, expected)

    def test_github_reads_do_not_start_python(self):
        allow = {'owners': ['Subverting-complexity']}
        for index, (tool, tool_input) in enumerate((
            ('Bash', {'command': 'gh pr view 12', 'description': 'push notes'}),
            ('Bash', {'command': 'gh issue list --limit 5'}),
            ('Bash', {'command': 'git log --oneline -5'}),
            ('Bash', {'command': 'ls C:/src/github/app',
                      'description': 'write the notes to github'}),
            ('PowerShell', {'command': 'gh pr checks 12 --watch'}),
            ('mcp__github__get_repository', {'owner': 'SomeoneElse', 'repo': 'r'}),
        )):
            with self.subTest(tool=tool, tool_input=tool_input):
                data = self.data_dir(str(index), allow, self.logger)
                out = self.run_hook(data, hook_event(
                    tool, tool_input, '/home/me/github/app'))
                self.assertEqual(out, '')
                self.assertFalse(os.path.exists(data + '/ran'))

    def test_look_alike_words_and_flags_do_not_start_python(self):
        """pushd, Push-Location and flags that only share a prefix with
        -EncodedCommand used to start Python on every call."""
        for index, (tool, command) in enumerate((
            ('Bash', 'pushd src && ls && popd'),
            ('PowerShell', 'Push-Location src; Get-ChildItem; Pop-Location'),
            ('PowerShell', 'Get-Content notes.txt -Encoding utf8'),
            ('Bash', 'docker run --env A=b image'),
            ('Bash', 'systemctl --enable thing'),
            ('Bash', 'git config --get remote.origin.pushurl'),
        )):
            with self.subTest(command=command):
                data = self.data_dir('look-alike-%d' % index, cache=self.logger)
                out = self.run_hook(data, hook_event(tool, {'command': command}, data))
                self.assertEqual(out, '')
                self.assertFalse(os.path.exists(data + '/ran'))

    def test_push_and_every_encoded_command_flag_still_start_python(self):
        for index, (tool, command) in enumerate((
            ('Bash', 'git push origin main'),
            ('Bash', 'rtk git push'),
            ('mcp__someserver__push_files', None),
            ('PowerShell', '& $shell -ec AAAA'),
            ('PowerShell', '& $shell -en AAAA'),
            ('PowerShell', '& $shell -enc AAAA'),
            ('PowerShell', '& $shell -enco AAAA'),
            ('PowerShell', '& $shell -EncodedCommand AAAA'),
            ('PowerShell', '& $shell /ec AAAA'),
        )):
            with self.subTest(tool=tool, command=command):
                data = self.data_dir('starts-%d' % index, cache=self.logger)
                tool_input = {'files': []} if command is None else {'command': command}
                self.run_hook(data, hook_event(tool, tool_input, data))
                self.assertTrue(os.path.exists(data + '/ran'))

    def test_a_camel_case_forge_mcp_tool_starts_python(self):
        data = self.data_dir('camel', cache=self.logger)
        out = self.run_hook(data, hook_event(
            'mcp__myAdo__create_pull_request', {'title': 'x'}, data))
        self.assertIn('"ask"', out)

    def test_an_interpreter_that_prints_something_else_is_replaced(self):
        data = self.data_dir('echo', cache='echo')
        out = self.run_hook(data, hook_event(
            'Bash', {'command': 'az repos pr create --title x'}, data))
        self.assertIn('"ask"', out)
        with open(data + '/guard-python') as f:
            cached = f.read()
        # The interpreter's own path, so `py -3` is not started twice a call.
        self.assertTrue(os.path.isfile(cached), cached)

    def test_the_word_lists_match_the_guard(self):
        from command_parse import WRITE_VERBS
        from forge_guard import WRITE_HINT
        from github_guard import GH_ALIASES, GH_NESTED, GH_WRITES
        with open(HOOK, encoding='utf-8') as f:
            text = f.read()
        verbs = re.search(r"^\s*verbs='([^']*)'", text, re.M).group(1).split('|')
        capitals = re.search(r"^\s*Verbs='([^']*)'", text, re.M).group(1).split('|')
        words = {w for w in WRITE_VERBS if '-' not in w}
        self.assertEqual(set(verbs), words)
        self.assertEqual(set(capitals), {w.capitalize() for w in words})
        write = set(re.search(r'^write="\(\^\|\$w\)\(([^)]*)\)', text, re.M)
                    .group(1).split('|'))
        hint = re.search(r'\((.*)\)', WRITE_HINT.pattern).group(1).split('|')
        self.assertLessEqual(set(hint), write)
        # A write action is seen by its own word, a hyphenated part of it, or
        # its group: `workflow` stands for `gh workflow run`, so that
        # `gh run view` does not start Python.
        actions = [(group, a) for group, names in GH_WRITES.items() for a in names]
        actions += [(pair[1], a) for pair, names in GH_NESTED.items() for a in names]
        actions += [('', a) for a in GH_ALIASES]
        for group, action in sorted(actions):
            with self.subTest(group=group, action=action):
                self.assertTrue(action in write or group in write
                                or set(action.split('-')) & write)


class TestDecision(unittest.TestCase):
    def test_the_hook_asks_and_never_denies(self):
        out = decision('a push to dev.azure.com')['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'PreToolUse')
        self.assertEqual(out['permissionDecision'], 'ask')
        self.assertIn('dev.azure.com', out['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
