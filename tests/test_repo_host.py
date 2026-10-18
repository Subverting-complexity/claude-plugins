"""hooks/repo-host.sh tells Claude which platform hosts the repository.

It reads the git config file itself, so it must still answer in a repository
git refuses to open (another Windows user owns it), inside a worktree, and in
a subdirectory, and it must never print the remote URL.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

BASH = shutil.which('bash')
HOOK = os.path.join(os.path.dirname(__file__), '..', 'synergy', 'hooks',
                    'repo-host.sh').replace('\\', '/')


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='') as f:
        f.write(text)


def config(url, remote='origin'):
    return ('[core]\n\tbare = false\n[remote "%s"]\n\turl = %s\n'
            '\tfetch = +refs/heads/*:refs/remotes/%s/*\n' % (remote, url, remote))


@unittest.skipIf(not BASH or 'system32' in (BASH or '').lower(),
                 'needs a POSIX bash')
class TestRepoHost(unittest.TestCase):
    def run_hook(self, cwd, *args, proc_cwd=None):
        event = json.dumps({'hook_event_name': 'SessionStart', 'cwd': cwd})
        return subprocess.run([BASH, HOOK] + list(args), input=event, cwd=proc_cwd,
                              capture_output=True, text=True, timeout=60).stdout

    def run_hook_without_path(self, cwd, *args):
        """Source the hook in a bash whose PATH finds nothing, so any external
        command it tried to start would fail. PATH is emptied inside bash
        because Git for Windows' bin/bash.exe wrapper resets it on the way in."""
        event = json.dumps({'hook_event_name': 'SessionStart', 'cwd': cwd})
        return subprocess.run(
            [BASH, '-c', 'PATH=/nonexistent; source "$0" "$@"', HOOK] + list(args),
            input=event, capture_output=True, text=True, timeout=60).stdout

    def verdicts(self, cases):
        for url, expected in cases:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as root:
                out = self.run_hook(self.repo(root, url).replace('\\', '/'))
                self.assertIn(expected, out)

    def repo(self, root, url, remote='origin'):
        write(os.path.join(root, '.git', 'config'), config(url, remote))
        return root

    def test_each_platform_is_named(self):
        cases = (
            ('https://dev.azure.com/Org/Project%20Name/_git/System-Level', 'Azure DevOps, not GitHub'),
            ('https://org.visualstudio.com/Project/_git/repo', 'Azure DevOps, not GitHub'),
            ('git@ssh.dev.azure.com:v3/Org/Project/repo', 'Azure DevOps, not GitHub'),
            ('git@gitlab.com:group/repo.git', 'GitLab, not GitHub'),
            ('https://bitbucket.org/team/repo.git', 'Bitbucket, not GitHub'),
            ('https://github.com/Subverting-complexity/claude-plugins.git', 'Repository host: GitHub.'),
            ('https://git.example.com/repo.git', 'not a recognised GitHub remote'),
        )
        for url, expected in cases:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as root:
                out = self.run_hook(self.repo(root, url).replace('\\', '/'))
                self.assertIn(expected, out)

    def test_the_url_and_any_token_in_it_are_never_printed(self):
        with tempfile.TemporaryDirectory() as root:
            self.repo(root, 'https://user:s3cret@dev.azure.com/Org/P/_git/r')
            out = self.run_hook(root.replace('\\', '/'))
            self.assertIn('Azure DevOps', out)
            self.assertNotIn('s3cret', out)
            self.assertNotIn('dev.azure.com', out)

    def test_a_windows_path_with_escaped_backslashes_is_read(self):
        with tempfile.TemporaryDirectory() as root:
            self.repo(root, 'https://dev.azure.com/Org/P/_git/r')
            if os.name != 'nt':
                self.skipTest('Windows path form')
            out = self.run_hook(root.replace('/', '\\'))
            self.assertIn('Azure DevOps', out)

    def test_a_subdirectory_and_crlf_config_are_read(self):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, '.git', 'config'),
                  config('https://gitlab.com/g/r.git').replace('\n', '\r\n'))
            sub = os.path.join(root, 'a', 'b')
            os.makedirs(sub)
            self.assertIn('GitLab', self.run_hook(sub.replace('\\', '/')))

    def test_origin_wins_over_another_remote(self):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, '.git', 'config'),
                  config('https://github.com/me/fork.git', 'upstream')
                  + '[remote "origin"]\n\turl = https://dev.azure.com/O/P/_git/r\n')
            self.assertIn('Azure DevOps', self.run_hook(root.replace('\\', '/')))

    def test_the_first_remote_is_used_without_origin(self):
        with tempfile.TemporaryDirectory() as root:
            self.repo(root, 'https://bitbucket.org/t/r.git', remote='upstream')
            self.assertIn('Bitbucket', self.run_hook(root.replace('\\', '/')))

    def test_a_worktree_reads_the_shared_config(self):
        with tempfile.TemporaryDirectory() as root:
            main = self.repo(os.path.join(root, 'main'), 'https://dev.azure.com/O/P/_git/r')
            wt_git = os.path.join(main, '.git', 'worktrees', 'wt')
            write(os.path.join(wt_git, 'commondir'), '../..\n')
            wt = os.path.join(root, 'wt')
            write(os.path.join(wt, '.git'), 'gitdir: %s\n' % wt_git.replace('\\', '/'))
            self.assertIn('Azure DevOps', self.run_hook(wt.replace('\\', '/')))

    def test_nothing_is_printed_outside_a_repository_or_without_a_remote(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self.run_hook(root.replace('\\', '/')), '')
            write(os.path.join(root, '.git', 'config'), '[core]\n\tbare = false\n')
            self.assertEqual(self.run_hook(root.replace('\\', '/')), '')

    def test_only_the_host_decides_not_the_path_or_the_user(self):
        """The whole URL used to be matched, so a GitHub repository named for
        GitLab, or pushed by a bot named for it, told Claude not to use gh."""
        self.verdicts((
            ('https://github.com/acme/gitlab-ci-templates.git', 'Repository host: GitHub.'),
            ('https://gitlab-bot@github.com/acme/app.git', 'Repository host: GitHub.'),
            ('git@github.com:bitbucket-mirrors/app.git', 'Repository host: GitHub.'),
            ('https://dev.azure.com/Org/github-mirror/_git/r', 'Azure DevOps, not GitHub'),
            ('https://git.example.com/github/repo.git', 'not a recognised GitHub remote'),
        ))

    def test_hosts_in_every_remote_form_are_recognised(self):
        self.verdicts((
            ('ssh://git@ssh.github.com:443/acme/app.git', 'Repository host: GitHub.'),
            ('github-work:acme/app.git', 'Repository host: GitHub.'),
            ('git@github.com-work:acme/app.git', 'Repository host: GitHub.'),
            ('https://gitlab.example.com/g/r.git', 'GitLab, not GitHub'),
            ('ssh://git@gitlab.example.com:2222/g/r.git', 'GitLab, not GitHub'),
            ('git@vs-ssh.visualstudio.com:v3/Org/P/r', 'Azure DevOps, not GitHub'),
            ('https://GitLab.com/g/r.git', 'GitLab, not GitHub'),
            ('/srv/git/gitlab-backup.git', 'not a recognised GitHub remote'),
            ('C:/repos/gitlab-backup.git', 'not a recognised GitHub remote'),
        ))

    def test_config_section_and_key_names_are_case_insensitive(self):
        """Git reads `URL =` under `[Remote "origin"]` as the remote's url."""
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, '.git', 'config'),
                  '[Core]\n\tbare = false\n[Remote "origin"]\n\tURL = https://gitlab.com/a/b.git\n')
            self.assertIn('GitLab', self.run_hook(root.replace('\\', '/')))

    def test_a_push_url_is_not_read_as_the_url(self):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, '.git', 'config'),
                  '[remote "origin"]\n\tpushurl = https://gitlab.com/a/b.git\n'
                  '\turl = https://github.com/a/b.git')  # and no final newline
            self.assertIn('Repository host: GitHub.', self.run_hook(root.replace('\\', '/')))

    def test_origin_wins_when_it_comes_first_as_well(self):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, '.git', 'config'),
                  config('https://bitbucket.org/t/r.git')
                  + config('https://github.com/me/fork.git', 'upstream'))
            self.assertIn('Bitbucket', self.run_hook(root.replace('\\', '/')))

    def test_the_event_cwd_is_read_rather_than_the_process_directory(self):
        """The cwd used to be pulled out with GNU sed's `\\|`, which BSD sed on
        macOS takes literally, so the hook silently answered for wherever it
        happened to be started instead."""
        with tempfile.TemporaryDirectory() as root:
            event_repo = self.repo(os.path.join(root, 'event'), 'https://bitbucket.org/t/r.git')
            proc_repo = self.repo(os.path.join(root, 'proc'), 'https://github.com/t/r.git')
            out = self.run_hook(event_repo.replace('\\', '/'), proc_cwd=proc_repo)
            self.assertIn('Bitbucket', out)

    def test_a_relative_worktree_gitdir_and_crlf_files_are_read(self):
        with tempfile.TemporaryDirectory() as root:
            main = os.path.join(root, 'main')
            write(os.path.join(main, '.git', 'config'),
                  config('https://gitlab.com/g/r.git').replace('\n', '\r\n'))
            wt_git = os.path.join(main, '.git', 'worktrees', 'wt')
            write(os.path.join(wt_git, 'commondir'), '../..\r\n')
            wt = os.path.join(root, 'wt')
            write(os.path.join(wt, '.git'), 'gitdir: ../main/.git/worktrees/wt\r\n')
            sub = os.path.join(wt, 'src')
            os.makedirs(sub)
            self.assertIn('GitLab', self.run_hook(sub.replace('\\', '/')))

    def test_the_hook_starts_no_external_process(self):
        """It runs at every session and subagent start, and each process start
        costs tens of milliseconds on Windows, so the whole path is built-ins.
        With nothing on PATH, any command it reached for would fail."""
        with tempfile.TemporaryDirectory() as root:
            main = self.repo(os.path.join(root, 'main'), 'https://dev.azure.com/O/P/_git/r')
            wt_git = os.path.join(main, '.git', 'worktrees', 'wt')
            write(os.path.join(wt_git, 'commondir'), '../..\n')
            wt = os.path.join(root, 'wt')
            write(os.path.join(wt, '.git'), 'gitdir: %s\n' % wt_git.replace('\\', '/'))
            sub = os.path.join(wt, 'a', 'b')
            os.makedirs(sub)
            out = self.run_hook_without_path(sub.replace('\\', '/'), 'SubagentStart')
            self.assertIn('Azure DevOps', json.loads(out)['hookSpecificOutput']['additionalContext'])
            self.assertEqual(self.run_hook_without_path(root.replace('\\', '/')), '')

    def test_subagent_start_gets_valid_json_context(self):
        with tempfile.TemporaryDirectory() as root:
            self.repo(root, 'https://dev.azure.com/O/P/_git/r')
            out = json.loads(self.run_hook(root.replace('\\', '/'), 'SubagentStart'))
            spec = out['hookSpecificOutput']
            self.assertEqual(spec['hookEventName'], 'SubagentStart')
            self.assertIn('Azure DevOps', spec['additionalContext'])

    def test_a_subagent_in_a_github_repository_is_told_nothing(self):
        """GitHub is what every workflow assumes, so the line would cost every
        subagent context and change nothing; the session is still told."""
        with tempfile.TemporaryDirectory() as root:
            self.repo(root, 'https://github.com/Subverting-complexity/claude-plugins.git')
            self.assertEqual(self.run_hook(root.replace('\\', '/'), 'SubagentStart'), '')
            self.assertIn('Repository host: GitHub.', self.run_hook(root.replace('\\', '/')))
        for url in ('https://gitlab.com/g/r.git', 'https://git.example.com/repo.git'):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as root:
                self.repo(root, url)
                out = json.loads(self.run_hook(root.replace('\\', '/'), 'SubagentStart'))
                self.assertIn('GitHub', out['hookSpecificOutput']['additionalContext'])


if __name__ == '__main__':
    unittest.main()
