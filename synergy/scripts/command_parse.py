#!/usr/bin/env python3
"""Split a shell command into the simple commands it runs, for the guards.

A Bash or PowerShell tool call reaches the guards as one string, and a write
can sit anywhere in it: after `;`, `&&` or a pipe, inside `$( )` or
backticks, behind `if`, `timeout` or `bash -c`, after a `cd`, or aimed at a
URL held in a variable set on an earlier line. `walk` reaches all of those,
and leaves out what only looks like a command: text inside quotes and the
body of a heredoc.
"""
import os
import re
import shlex
import subprocess

READ_METHODS = {'GET', 'HEAD', 'OPTIONS'}

# Words in a CLI subcommand or an MCP tool name that change something.
WRITE_VERBS = {
    'create', 'update', 'delete', 'add', 'remove', 'set', 'set-vote', 'vote',
    'abandon', 'complete', 'reactivate', 'run', 'trigger', 'queue', 'import',
    'link', 'unlink', 'approve', 'merge', 'note', 'comment', 'close',
    'reopen', 'revoke', 'retry', 'rerun', 'cancel', 'publish', 'upload',
    'post', 'reply', 'resolve', 'edit', 'push', 'write', 'assign', 'fork',
    'dismiss', 'star', 'transfer', 'lock', 'unlock', 'archive', 'rename',
    'move', 'submit', 'send', 'dispatch', 'patch', 'put', 'modify', 'save',
    'manage',
}

# Words that make an MCP tool a read when they come before any write word,
# so `list_merge_requests` and `get_issue_link` read.
READ_VERBS = {
    'get', 'list', 'search', 'read', 'view', 'fetch', 'describe', 'show',
    'query', 'find', 'download', 'export', 'check', 'count', 'compare',
    'diff', 'preview', 'whoami', 'lookup', 'browse', 'inspect',
}

PREFIX_WORDS = {'if', 'then', 'elif', 'else', 'fi', 'do', 'done', 'while',
                'until', '!', 'time', 'nohup', 'rtk', 'sudo', 'command',
                'exec', 'call', '&', '.', '{', '}', 'try'}
SHELLS = {'bash', 'sh', 'zsh', 'pwsh', 'powershell', 'cmd'}
SHELL_COMMAND_FLAGS = {'-c', '-command', '/c', '/k'}
CD_WORDS = {'cd', 'set-location', 'sl', 'pushd', 'chdir'}


def program(token):
    name = re.split(r'[\\/]', token)[-1].lower()
    return re.sub(r'\.(exe|cmd|bat|com)$', '', name)


def strip_heredocs(command):
    """The command without heredoc bodies or PowerShell here-strings, which
    are text a command reads, not commands."""
    out, end = [], None
    for line in command.split('\n'):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = re.search(r'<<-?\s*([\'"]?)([A-Za-z_]\w*)\1', line)
        if m and '<<<' not in line:
            end = m.group(2)
    return re.sub(r'@([\'"])\n.*?\n\1@', "''", '\n'.join(out), flags=re.S)


def _closing_paren(text, start):
    depth, quote = 0, None
    for j in range(start, len(text)):
        c = text[j]
        if quote:
            if c == quote:
                quote = None
        elif c in '\'"':
            quote = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return j
    return len(text)


def split_commands(command, _depth=0):
    """Each simple command in `command`, as a string, including the ones
    inside command substitutions."""
    text = command.replace('\r\n', '\n')
    if _depth == 0:
        text = strip_heredocs(text)
    parts, subs, buf, quote = [], [], [], None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ''
        if quote == "'":
            buf.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c in '\\`' and nxt == '\n':  # a line continuation
            i += 2
            continue
        if c == '\\' and nxt:
            buf.append(c + nxt)
            i += 2
            continue
        if c == '$' and nxt == '(':
            end = _closing_paren(text, i + 1)
            subs.append(text[i + 2:end])
            buf.append('$_')
            i = end + 1
            continue
        if c == '`':
            end = text.find('`', i + 1)
            if end > i + 1 and '\n' not in text[i + 1:end]:
                subs.append(text[i + 1:end])
                buf.append('$_')
                i = end + 1
                continue
        if quote == '"':
            buf.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        if c in '\'"':
            quote = c
        elif c in ';\n|&()':
            parts.append(''.join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append(''.join(buf))
    found = [p.strip() for p in parts if p.strip()]
    if _depth < 4:
        for sub in subs:
            found.extend(split_commands(sub, _depth + 1))
    return found


def tokens(segment):
    """The words of one simple command, with assignments, `if`, `timeout`
    and similar prefixes removed and the program name normalised."""
    lexer = shlex.shlex(segment, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ''  # keep Windows paths intact
    lexer.commenters = ''
    try:
        toks = list(lexer)
    except ValueError:
        toks = segment.split()
    while toks:
        first = toks[0]
        ps_assign = re.match(r'^\$[\w:]+=(.+)$', first)
        if ps_assign:
            toks[0] = ps_assign.group(1)
        elif first.lower() in PREFIX_WORDS or re.match(r'^[A-Za-z_]\w*=', first):
            toks = toks[1:]
        elif (re.match(r'^\$[\w:]+$', first) and len(toks) > 1
              and toks[1] in ('=', '+=')):
            toks = toks[2:]
        elif first.lower() == 'env':
            toks = toks[1:]
            while toks and (toks[0].startswith('-') or '=' in toks[0]):
                toks = toks[2:] if toks[0] == '-u' else toks[1:]
        elif first.lower() == 'timeout':
            toks = toks[1:]
            while toks and (toks[0].startswith('-')
                            or re.match(r'^\d+(\.\d+)?[smhd]?$', toks[0])):
                toks = toks[1:]
        else:
            break
    if toks:
        toks[0] = program(toks[0])
    return toks


def walk(command, cwd=None):
    """(tokens, cwd, variables) for each simple command in `command`,
    following `cd` and the variables assigned along the way."""
    found = []
    _walk(command, cwd, {}, found, 0)
    return found


def _walk(command, cwd, variables, found, depth):
    for segment in split_commands(command):
        m = re.match(r'^\$?([A-Za-z_]\w*)\s*=\s*(\S.*)$', segment, re.S)
        if m:
            variables[m.group(1).lower()] = m.group(2).strip().strip('\'"')
        toks = tokens(segment)
        if not toks:
            continue
        if toks[0] in CD_WORDS and len(toks) > 1:
            cwd = os.path.join(cwd or '.', toks[1])
            continue
        if toks[0] in SHELLS and depth < 3:
            flag = next((i for i, t in enumerate(toks)
                         if t.lower() in SHELL_COMMAND_FLAGS), None)
            if flag is not None:
                _walk(' '.join(toks[flag + 1:]), cwd, variables, found,
                      depth + 1)
                continue
        found.append((toks, cwd, dict(variables)))


def expand(text, variables):
    return re.sub(r'\$\{?(?:env:)?(\w+)\}?',
                  lambda m: variables.get(m.group(1).lower(), m.group(0)),
                  text)


def flag_value(toks, names):
    """The value of the first flag in `names`, written as `-X POST`, `-XPOST`,
    `--request=POST` or `-Method:Post`. Names compare case-insensitively."""
    lowered = {n.lower() for n in names}
    for i, token in enumerate(toks):
        low = token.lower()
        if token.startswith('-'):
            for sep in ('=', ':'):
                if sep in low and low.split(sep, 1)[0] in lowered:
                    return token.split(sep, 1)[1]
        if low in lowered and i + 1 < len(toks):
            return toks[i + 1]
        for name in names:
            if (len(name) == 2 and not token.startswith('--')
                    and token.startswith(name) and len(token) > 2):
                return token[2:]
    return None


def has_flag(toks, names):
    lowered = {n.lower() for n in names}
    return any(t.lower().split('=', 1)[0].split(':', 1)[0] in lowered
               for t in toks if t.startswith('-'))


def host(url):
    m = re.match(r'^[a-z][\w+.-]*://(?:[^@/]+@)?([^/:]+)', url or '', re.I)
    if m:
        return m.group(1).lower()
    m = re.match(r'^(?:[^@/\s]+@)?([^:/\s]+):(?!\\)', url or '')
    if m and '.' in m.group(1):
        return m.group(1).lower()
    return None


def push_target(toks, cwd):
    """(remote, cwd) for a `git push`, the remote None when not named; None
    when this is not a push."""
    if not toks or toks[0] != 'git':
        return None
    i = 1
    while i < len(toks) and toks[i].startswith('-'):
        if toks[i] in ('-C', '-c'):
            if toks[i] == '-C' and i + 1 < len(toks):
                cwd = os.path.join(cwd or '.', toks[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(toks) or toks[i] != 'push':
        return None
    rest, j = toks[i + 1:], 0
    while j < len(rest):
        token = rest[j]
        if token == '--repo' and j + 1 < len(rest):
            return rest[j + 1], cwd
        if token in ('-o', '--push-option', '--receive-pack', '--exec'):
            j += 2
            continue
        if token.startswith('--repo='):
            return token.split('=', 1)[1], cwd
        if not token.startswith('-'):
            return token, cwd
        j += 1
    return None, cwd


def remote_url(cwd, remote):
    """The push URL for `remote`, or for the current branch's push remote."""
    def git(*args):
        try:
            out = subprocess.run(['git'] + list(args), cwd=cwd or None,
                                 capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return ''
        return out.stdout.strip() if out.returncode == 0 else ''

    if remote is None:
        push = git('rev-parse', '--abbrev-ref', '--symbolic-full-name',
                   '@{push}')
        remote = push.split('/', 1)[0] if push else 'origin'
    return git('remote', 'get-url', '--push', remote)


def push_url(toks, cwd, lookup=remote_url):
    """The URL a `git push` goes to, '' when unknown, None when not a push."""
    target = push_target(toks, cwd)
    if target is None:
        return None
    remote, where = target
    if remote and ('://' in remote or host(remote)):
        return remote
    return lookup(where, remote) or ''


def name_words(name):
    return [w.lower() for w in
            re.findall(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+', name)]


def mcp_writes(tool_name):
    """Whether an MCP tool changes something, judged from its action name:
    the first read or write word decides."""
    action = '__'.join(tool_name.split('__')[2:])
    for word in name_words(action):
        if word in READ_VERBS:
            return False
        if word in WRITE_VERBS:
            return True
    return False
