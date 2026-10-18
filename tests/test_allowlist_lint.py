"""lint_allowlists.py finds a command a flow runs that its agent or skill does not allow.

An unattended run stops at a permission prompt nobody answers when a file its flow cites runs a command missing from the agent's `tools:` or the skill's `allowed-tools:`. These tests build small plugins in a temp directory and check what the linter follows, what it reads as a command, and that the real plugin passes.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
import lint_allowlists as lint  # noqa: E402

FENCE = '```'


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def block(*lines, lang='bash'):
    return '%s%s\n%s\n%s\n' % (FENCE, lang, '\n'.join(lines), FENCE)


class AllowlistLintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.plugin = os.path.join(self.tmp, 'synergy')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def skill(self, name, tools, body):
        items = ''.join('  - %s\n' % t for t in tools)
        write(os.path.join(self.plugin, 'skills', name, 'SKILL.md'),
              '---\nname: %s\nallowed-tools:\n%s---\n\n%s' % (name, items, body))

    def ref(self, skill, name, body):
        write(os.path.join(self.plugin, 'skills', skill, 'references', name), body)

    def agent(self, name, tools, body):
        items = ''.join('  - %s\n' % t for t in tools)
        write(os.path.join(self.plugin, 'agents', name + '.md'),
              '---\nname: %s\ntools:\n%s---\n\n%s' % (name, items, body))

    def failures(self):
        return lint.check(self.plugin)

    def test_an_uncited_file_is_ignored(self):
        self.skill('s', ['Bash(gh *)'], 'Read `references/cited.md`.\n')
        self.ref('s', 'cited.md', block('gh pr view 1'))
        self.ref('s', 'uncited.md', block('curl https://example.com'))
        self.assertEqual(self.failures(), [])

    def test_a_disallowed_command_in_a_cited_reference_fails(self):
        self.skill('s', ['Bash(gh *)'], 'Read `references/cited.md`.\n')
        self.ref('s', 'cited.md', 'Wait first.\n\n' + block('sleep 60', 'gh pr view 1'))
        self.assertEqual(self.failures(), [
            "FAIL: synergy/skills/s/SKILL.md runs 'sleep 60' (cited via synergy/skills/s/references/cited.md) but does not allow it",
        ])

    def test_citations_are_followed_transitively(self):
        self.skill('s', ['Bash(gh *)'], 'Read `references/a.md`.\n')
        self.ref('s', 'a.md', 'Then read `references/b.md`.\n')
        self.ref('s', 'b.md', block('timeout 180 gh pr checks 1 --watch'))
        out = self.failures()
        self.assertEqual(len(out), 1)
        self.assertIn("runs 'timeout 180 gh pr checks 1 --watch' (cited via synergy/skills/s/references/b.md)", out[0])

    def test_a_pipe_after_a_continuation_checks_both_sides(self):
        # The shape ci-bypass.md uses: a continued gh call piped into grep on the next line.
        self.skill('s', ['Bash(gh *)'], block(
            'gh run view <run-id> --repo <org>/<repo> \\',
            "     --json conclusion --jq '.conclusion | ascii_downcase' \\",
            "     | grep -iE 'billing|spending limit'",
        ))
        out = self.failures()
        self.assertEqual(len(out), 1)
        self.assertIn("runs 'grep -iE billing|spending limit'", out[0])
        self.skill('s', ['Bash(gh *)', 'Bash(grep *)'], block(
            'gh run view 1 \\', "  | grep -iE 'billing|spending limit'"))
        self.assertEqual(self.failures(), [])

    def test_substitutions_assignments_and_builtins(self):
        self.skill('s', ['Bash(git *)'], block(
            '# a comment that names curl',
            'base=$(git symbolic-ref --short HEAD 2>/dev/null)',
            'if git fetch origin "$base"; then',
            '  cd /tmp && export X=1',
            'fi',
            "cat <<'EOF' > /dev/null",
            'curl inside a heredoc body',
            'EOF',
        ))
        self.assertEqual(self.failures(), [
            "FAIL: synergy/skills/s/SKILL.md runs 'cat > /dev/null' (cited via synergy/skills/s/SKILL.md) but does not allow it",
        ])

    def test_placeholder_choices_are_not_pipes(self):
        self.skill('s', ['Bash(bash *wf.sh*)'], block(
            'bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" plan-set --max-groups {1|2}',
            'wf review-finish --verdict <approved|changes-requested>',
        ))
        self.assertEqual(self.failures(), [])

    def test_only_shell_blocks_are_read(self):
        self.skill('s', [], block('curl https://example.com', lang='json') + block('curl x', lang=''))
        self.assertEqual(self.failures(), [])

    def test_an_agent_follows_the_skills_it_names(self):
        self.agent('A', ['Read', 'Bash(gh *)'], 'Run `/synergy:s`.\n')
        write(os.path.join(self.plugin, 'skills', 's', 'SKILL.md'),
              '---\nname: s\n---\n\nRead `references/r.md`.\n')
        self.ref('s', 'r.md', block('sleep 5'))
        write(os.path.join(self.plugin, 'skills', 'other', 'SKILL.md'),
              '---\nname: other\n---\n\n' + block('sleep 9'))
        self.assertEqual(self.failures(), [
            "FAIL: synergy/agents/A.md runs 'sleep 5' (cited via synergy/skills/s/references/r.md) but does not allow it",
        ])

    def test_a_bare_bash_allows_everything(self):
        self.agent('A', ['Bash'], block('curl https://example.com'))
        self.assertEqual(self.failures(), [])

    def test_the_real_plugin_passes(self):
        self.assertEqual(lint.check(os.path.join(ROOT, 'synergy')), [])


if __name__ == '__main__':
    unittest.main()
