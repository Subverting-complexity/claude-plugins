#!/usr/bin/env python3
"""Check that every command a flow runs is allowed by the agent or skill that runs it.

An agent's `tools:` list and a skill's `allowed-tools:` list are what an unattended run is allowed to do without a permission prompt. A command the flow tells it to run, but that the list does not allow, stops the run at a prompt nobody answers. This checker finds those gaps.

Holders are every agent with `tools:` and every skill or command with `allowed-tools:`. A holder's entry files are its own file and, for an agent, each `/synergy:<name>` its body names, resolved to `skills/<name>/SKILL.md` or `commands/<name>.md`. From the entry files the checker follows path citations transitively, with the patterns `count-tokens.sh` resolves (`references/`, `templates/`, `_shared/`, `skills/X/SKILL.md`, `skills/X/references/Y.md`, plus `commands/X.md`). It reads commands only from fenced `bash`, `sh` and `shell` blocks, and matches each against the holder's `Bash(...)` patterns.

This file lives at the repository root and is not shipped with the plugin. `lint-skills.sh` runs it. Usage: `python lint_allowlists.py [plugin_dir]`, where `plugin_dir` defaults to `synergy` next to this file. Exit 0 when every command is allowed, 1 otherwise.
"""
import os
import re
import sys

CITATION = re.compile(
    r'(?:skills/[a-zA-Z0-9_-]+/)?(?:templates|references)/[a-zA-Z0-9_-]+\.md'
    r'|(?:skills/)?_shared/[a-zA-Z0-9_-]+\.md'
    r'|(?:skills/)?[a-zA-Z0-9_-]+/SKILL\.md'
    r'|commands/[a-zA-Z0-9_-]+\.md'
)
SLASH_COMMAND = re.compile(r'/synergy:([a-z0-9][a-z0-9-]*)')
FENCE = re.compile(r'^(\s*)(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)')
SHELL_LANGS = {'bash', 'sh', 'shell'}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=')

# Words that start a segment but are not a command the permission system sees.
# Keywords are stripped and the rest of the segment is checked; builtins skip
# the whole segment. Grow this list only when a match is truly wrong.
KEYWORDS = {'if', 'then', 'else', 'elif', 'while', 'until', 'do', 'time', '!', '{', '(', 'exec'}
SKIP_SEGMENT = {
    'fi', 'done', 'esac', 'for', 'case', 'select', 'function', '}', ')', ';;',
    '[', '[[', 'cd', 'export', 'true', 'false', ':', 'set', 'local', 'return',
    'exit', 'break', 'continue', 'shift', 'unset', 'declare', 'read', 'wait',
    'trap', 'readonly',
}


def frontmatter(text):
    """Return the frontmatter lines of a markdown file, or [] when it has none."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return []
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            return lines[1:i]
    return []


def body(text):
    lines = text.splitlines()
    fm = frontmatter(text)
    return '\n'.join(lines[len(fm) + 2:]) if fm else text


def tool_list(text, key):
    """Return the entries of the `key:` list in the frontmatter, or None when absent."""
    fm = frontmatter(text)
    for i, line in enumerate(fm):
        m = re.match(r'^%s:\s*(.*)$' % re.escape(key), line)
        if not m:
            continue
        inline = m.group(1).strip()
        if inline:
            if inline.startswith('['):
                inline = inline.strip('[]')
            return [t.strip().strip('\'"') for t in re.split(r',(?![^(]*\))', inline) if t.strip()]
        items = []
        for nxt in fm[i + 1:]:
            im = re.match(r'^\s+-\s*(.+)$', nxt)
            if im:
                items.append(im.group(1).strip().strip('\'"'))
            elif nxt.strip():
                break
        return items
    return None


def pattern_matcher(tools):
    """Build a predicate that says whether a command is allowed by the Bash entries in tools."""
    regexes = []
    for tool in tools:
        if tool == 'Bash':
            return lambda cmd: True
        m = re.match(r'^Bash\((.*)\)$', tool)
        if not m:
            continue
        pat = normalise(m.group(1))
        if pat.endswith(':*'):
            pat = pat[:-2] + ' *'
        rx = '.*'.join(re.escape(part) for part in pat.split('*'))
        if pat.endswith(' *'):
            # `git *` also allows a bare `git`.
            rx = '(?:%s|%s)' % (rx, re.escape(pat[:-2]))
        regexes.append(re.compile(rx + r'\Z', re.S))
    return lambda cmd: any(r.match(cmd) for r in regexes)


def normalise(cmd):
    """Drop quotes and collapse whitespace, so quoting a path does not change a match."""
    return ' '.join(cmd.replace('"', '').replace("'", '').split())


# --- reading commands out of fenced blocks -----------------------------------

def shell_blocks(text):
    """Yield the lines of each fenced bash/sh/shell block, with the fence indent removed."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        indent, marker, lang = m.group(1), m.group(2), m.group(3).lower()
        block = []
        i += 1
        while i < len(lines):
            close = re.match(r'^\s*(`{3,}|~{3,})\s*$', lines[i])
            if close and close.group(1)[0] == marker[0] and len(close.group(1)) >= len(marker):
                break
            line = lines[i]
            if line.startswith(indent):
                line = line[len(indent):]
            block.append(line)
            i += 1
        i += 1
        if lang in SHELL_LANGS:
            yield block


def logical_lines(block):
    """Join `\\` continuations and leading-operator lines; drop comments and heredoc bodies."""
    out = []
    heredoc_end = None
    pending = ''
    for raw in block:
        if heredoc_end is not None:
            if raw.strip() == heredoc_end:
                heredoc_end = None
            continue
        line = strip_comment(raw).rstrip()
        hm = HEREDOC.search(line)
        if hm:
            heredoc_end = hm.group(2)
            line = line[:hm.start()] + line[hm.end():]
        stripped = line.strip()
        if not stripped:
            if pending:
                out.append(pending)
                pending = ''
            continue
        if pending and re.match(r'^(\|\|?|&&)', stripped):
            pending = pending + ' ' + stripped
        elif pending.endswith('\\'):
            pending = pending[:-1] + ' ' + stripped
        elif pending and re.search(r'(\|\|?|&&)\s*$', pending):
            pending = pending + ' ' + stripped
        else:
            if pending:
                out.append(pending)
            pending = stripped
    if pending:
        out.append(pending.rstrip('\\'))
    return out


def strip_comment(line):
    """Remove an unquoted `#` comment from a line."""
    quote = None
    for idx, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            elif ch == '\\' and quote == '"':
                continue
        elif ch in '\'"':
            quote = ch
        elif ch == '#' and (idx == 0 or line[idx - 1].isspace()):
            return line[:idx]
    return line


def split_commands(line):
    """Split a logical line into simple commands, pulling out every `$( )` and backtick substitution."""
    segments = []
    current = []
    quote = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if quote == "'":
            current.append(ch)
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == '\\' and i + 1 < n:
            current.append(line[i:i + 2])
            i += 2
            continue
        if ch == '$' and line[i + 1:i + 2] == '(' and line[i + 2:i + 3] != '(':
            end = matching_paren(line, i + 1)
            segments.extend(split_commands(line[i + 2:end]))
            current.append('X')
            i = end + 1
            continue
        if ch == '`':
            end = line.find('`', i + 1)
            end = n if end < 0 else end
            segments.extend(split_commands(line[i + 1:end]))
            current.append('X')
            i = end + 1
            continue
        if quote == '"':
            current.append(ch)
            if ch == '"':
                quote = None
            i += 1
            continue
        if ch in '\'"':
            quote = ch
            current.append(ch)
            i += 1
            continue
        two = line[i:i + 2]
        if two in ('&&', '||'):
            segments.append(''.join(current))
            current = []
            i += 2
            continue
        if ch == '|' and i > 0 and i + 1 < n and not line[i - 1].isspace() and not line[i + 1].isspace():
            # `{1|2}` and `<approved|changes-requested>` are placeholders that
            # list the choices, not pipes; a pipe in these files has spaces.
            current.append(ch)
            i += 1
            continue
        if ch in '|;' or (ch == '&' and line[i - 1:i] not in ('>', '<') and line[i + 1:i + 2] != '>'):
            segments.append(''.join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    segments.append(''.join(current))
    return [s for s in segments if s.strip()]


def matching_paren(text, start):
    depth = 0
    quote = None
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in '\'"':
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i
    return len(text)


def command_of(segment):
    """Return the command a segment runs, normalised, or None when it runs nothing to check."""
    words = segment.strip().split()
    while words:
        word = words[0]
        if word in KEYWORDS:
            words = words[1:]
        elif word.startswith('(') and len(word) > 1:
            words[0] = word.lstrip('(')
        elif ASSIGNMENT.match(word):
            words = words[1:]
        else:
            break
    if not words:
        return None
    if words[0] in SKIP_SEGMENT or words[0].startswith('[') or re.match(r'^[^\s()]+\)$', words[0]):
        return None
    cmd = ' '.join(words).rstrip(')').rstrip()
    if words[0] == 'wf':
        # Bare `wf` is shorthand for the plugin's launcher (shared-phases.md).
        cmd = 'bash ${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh' + cmd[2:]
    cmd = normalise(cmd)
    return cmd or None


def commands_in(text):
    for block in shell_blocks(text):
        for line in logical_lines(block):
            for segment in split_commands(line):
                cmd = command_of(segment)
                if cmd:
                    yield cmd


# --- following citations ------------------------------------------------------

def resolve(plugin, citer, ref, ref_base):
    name = ref.rsplit('/', 1)[-1]
    if '_shared/' in ref:
        return os.path.join(plugin, 'skills', '_shared', name)
    if ref.endswith('/SKILL.md'):
        skill = ref[:-len('/SKILL.md')].rsplit('/', 1)[-1]
        return os.path.join(plugin, 'skills', skill, 'SKILL.md')
    if ref.startswith('commands/'):
        return os.path.join(plugin, 'commands', name)
    if ref.startswith('skills/') and '/references/' in ref:
        return os.path.join(plugin, 'skills', ref.split('/')[1], 'references', name)
    if '/templates/' in ref or ref.startswith('templates/'):
        return os.path.join(plugin, 'templates', name)
    parts = os.path.normpath(citer).split(os.sep)
    if 'references' in parts[-2:-1]:
        citer_base = os.path.dirname(citer)
    elif 'skills' in parts:
        citer_base = os.path.join(os.path.dirname(citer), 'references')
    else:
        citer_base = ref_base
    for base in (citer_base, ref_base):
        candidate = os.path.join(base, name)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(plugin, 'references', name)


def ref_base_for(plugin, path):
    rel = os.path.relpath(path, plugin).replace(os.sep, '/')
    if rel.startswith('skills/'):
        return os.path.join(os.path.dirname(path), 'references')
    return os.path.join(plugin, 'references')


def closure(plugin, root):
    """Return every file reached from root by path citations, root first."""
    ref_base = ref_base_for(plugin, root)
    seen = [os.path.normpath(root)]
    queue = list(seen)
    while queue:
        current = queue.pop(0)
        text = read(current)
        for ref in sorted(set(CITATION.findall(text))):
            path = os.path.normpath(resolve(plugin, current, ref, ref_base))
            if path not in seen and os.path.isfile(path):
                seen.append(path)
                queue.append(path)
    return seen


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def holders(plugin):
    """Yield (holder file, tool list, entry files) for every agent, skill and command with a list."""
    agents = os.path.join(plugin, 'agents')
    for name in sorted(os.listdir(agents)) if os.path.isdir(agents) else []:
        path = os.path.join(agents, name)
        if not name.endswith('.md'):
            continue
        text = read(path)
        tools = tool_list(text, 'tools')
        if tools is None:
            continue
        entries = [path]
        for cmd in SLASH_COMMAND.findall(body(text)):
            for candidate in (os.path.join(plugin, 'skills', cmd, 'SKILL.md'),
                              os.path.join(plugin, 'commands', cmd + '.md')):
                if os.path.isfile(candidate) and candidate not in entries:
                    entries.append(candidate)
                    break
        yield path, tools, entries
    files = []
    skills = os.path.join(plugin, 'skills')
    for name in sorted(os.listdir(skills)) if os.path.isdir(skills) else []:
        files.append(os.path.join(skills, name, 'SKILL.md'))
    commands = os.path.join(plugin, 'commands')
    for name in sorted(os.listdir(commands)) if os.path.isdir(commands) else []:
        if name.endswith('.md'):
            files.append(os.path.join(commands, name))
    for path in files:
        if not os.path.isfile(path):
            continue
        tools = tool_list(read(path), 'allowed-tools')
        if tools is not None:
            yield path, tools, [path]


def check(plugin):
    """Return the FAIL lines for every disallowed command, in a stable order."""
    plugin = os.path.normpath(plugin)
    base = os.path.dirname(plugin)

    def rel(p):
        return os.path.relpath(p, base).replace(os.sep, '/')

    failures = []
    for holder, tools, entries in holders(plugin):
        allowed = pattern_matcher(tools)
        reported = set()
        for entry in entries:
            for path in closure(plugin, entry):
                for cmd in commands_in(read(path)):
                    if allowed(cmd) or (cmd, path) in reported:
                        continue
                    reported.add((cmd, path))
                    failures.append("FAIL: %s runs '%s' (cited via %s) but does not allow it"
                                    % (rel(holder), cmd, rel(path)))
    return failures


def main(argv):
    plugin = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'synergy')
    failures = check(plugin)
    for line in failures:
        print(line)
    if failures:
        return 1
    print('Allowlists cover every command the flows run.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
