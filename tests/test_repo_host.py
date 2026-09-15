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
    def run_hook(self, cwd, *args):
        event = json.dumps({'hook_event_name': 'SessionStart', 'cwd': cwd})
        return subprocess.run([BASH, HOOK] + list(args), input=event,
                              capture_output=True, text=True, timeout=60).stdout

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

    def test_subagent_start_gets_valid_json_context(self):
        with tempfile.TemporaryDirectory() as root:
            self.repo(root, 'https://dev.azure.com/O/P/_git/r')
            out = json.loads(self.run_hook(root.replace('\\', '/'), 'SubagentStart'))
            spec = out['hookSpecificOutput']
            self.assertEqual(spec['hookEventName'], 'SubagentStart')
            self.assertIn('Azure DevOps', spec['additionalContext'])


if __name__ == '__main__':
    unittest.main()
