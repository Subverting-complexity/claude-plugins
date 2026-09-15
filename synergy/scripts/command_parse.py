#!/usr/bin/env python3
"""Split a shell command into the simple commands it runs, for the guards.

A Bash or PowerShell tool call reaches the guards as one string, and a write
can sit anywhere in it: after `;`, `&&` or a pipe, inside `$( )` or
backticks, behind `if`, `timeout`, `xargs`, `eval`, `Invoke-Expression` or
`bash -lc`, in a heredoc or string piped into a shell, after a `cd`, or aimed
at a URL or remote set on an earlier line. `walk` reaches all of those, and
leaves out what only looks like a command: text inside quotes, comments, and
the body of a heredoc no shell runs.

Bash and PowerShell quote differently. In Bash a backslash escapes the next
character; in PowerShell it is an ordinary path character and the backtick
escapes instead, so `"C:\\dir\\"` closes its quote in PowerShell and not in
Bash. `walk` is told which shell the command is for.
"""
import base64
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
                'until', '!', 'time', 'nohup', 'sudo', 'command', 'exec',
                'call', '&', '.', '{', '}', 'try'}
SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ksh', 'pwsh', 'powershell', 'cmd'}
POWERSHELLS = {'pwsh', 'powershell'}
EVAL_WORDS = {'eval', 'invoke-expression', 'iex'}
EXPORT_WORDS = {'export', 'declare', 'typeset', 'local', 'readonly', 'set',
                'setx'}
ECHO_WORDS = {'echo', 'printf', 'write-output'}
CD_WORDS = {'cd', 'set-location', 'sl', 'pushd', 'chdir'}
XARGS_VALUE_FLAGS = {'-I', '-n', '-P', '-L', '-d', '-E', '-e', '-s', '-a',
                     '--max-args', '--max-procs', '--delimiter', '--arg-file',
                     '--max-lines', '--replace', '--eof'}

HTTP_TOOLS = {'curl', 'wget', 'invoke-restmethod', 'invoke-webrequest',
              'irm', 'iwr'}
DATA_FLAGS = {'--data', '--data-raw', '--data-binary', '--data-urlencode',
              '--data-ascii', '--json', '--form', '--form-string',
              '--upload-file', '--post-data', '--post-file', '--body-data',
              '--body-file'}
# curl's short flags that take no value, so they can sit in a cluster ahead
# of -X or -d, as in -sXPOST.
CURL_BARE = 'sSLkfivgnq'

HEREDOC = re.compile(r'<<-?\s*([\'"]?)([A-Za-z_][\w.-]*)\1')
# A heredoc opened on a line that runs a shell or eval is a script it runs.
SHELL_READER = re.compile(
    r'(?:^|[\s|;&(])(?:\S*[\\/])?(?:bash|sh|zsh|dash|ksh|pwsh|powershell|iex|'
    r'invoke-expression|eval|source)(?:\.exe)?(?=$|[\s|;&)<])', re.I)
# A PowerShell here-string piped into something that runs it.
HERE_STRING_RUN = re.compile(
    r'^\s*\|\s*(?:\S*[\\/])?(?:iex|invoke-expression|pwsh|powershell|bash|sh)'
    r'(?:\.exe)?\b', re.I)
PS_ASSIGN = re.compile(r'^\$(?:env:)?([A-Za-z_]\w*)\s*=\s*(\S.*)$', re.S | re.I)
SUB = '$__sub'


def program(token):
    name = re.split(r'[\\/]', token)[-1].lower()
    return re.sub(r'\.(exe|cmd|bat|com)$', '', name)


def _prepare(text, powershell):
    """(text, scripts): the command without comments, heredoc bodies and
    here-strings, and the bodies of those a shell runs, as scripts of their
    own. Quotes are tracked, and reset inside `$( )`, so `<<EOF` or `#` in a
    string is text, and an apostrophe in a comment opens nothing."""
    out, scripts, stack, pending = [], [], [], []
    quote, line_start = None, 0
    escape = '`' if powershell else '\\'
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ''
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == escape and nxt:
            out.append(c + nxt)
            i += 2
            continue
        if c == '$' and nxt == '(':
            # Each open $( ), $(( )), (( )) or $[ ] is [quote outside it,
            # depth, kind]; inside arithmetic, << shifts bits.
            arith = not powershell and text[i + 2:i + 3] == '('
            out.append('$((' if arith else '$(')
            stack.append([quote, 1 if arith else 0, '((' if arith else None])
            quote = None
            i += 3 if arith else 2
            continue
        if quote == '"':
            out.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        if c == '$' and nxt == "'" and not powershell:
            end = _ansi_quote_end(text, i + 2)
            out.append(text[i:end + 1])
            i = end + 1
            continue
        if not powershell and c == '(' and nxt == '(':
            out.append('((')
            stack.append([quote, 1, '(('])
            i += 2
            continue
        if not powershell and c == '$' and nxt == '[':
            out.append('$[')
            stack.append([quote, 0, '['])
            i += 2
            continue
        if c == '@' and nxt in ('\'', '"') and text[i + 2:i + 3] == '\n':
            close = text.find('\n' + nxt + '@', i + 2)
            if close != -1:
                end = close + 3
                eol = text.find('\n', end)
                if HERE_STRING_RUN.match(text[end:n if eol == -1 else eol]):
                    scripts.append(text[i + 3:close])
                out.append("''")
                i = end
                continue
        if c in '\'"':
            quote = c
        elif c in '([' and stack and (c == '[') == (stack[-1][2] == '['):
            stack[-1][1] += 1
        elif c in ')]' and stack and (c == ']') == (stack[-1][2] == '['):
            if stack[-1][1] == 0:
                quote = stack.pop()[0]
            else:
                stack[-1][1] -= 1
        elif c == '#' and (i == 0 or text[i - 1] in ' \t\n;|&('):
            eol = text.find('\n', i)
            i = n if eol == -1 else eol
            continue
        elif powershell and c == '<' and nxt == '#':
            close = text.find('#>', i + 2)
            i = n if close == -1 else close + 2
            continue
        elif (not powershell and c == '<' and nxt == '<'
              and text[i + 2:i + 3] != '<' and (i == 0 or text[i - 1] != '<')
              and not (stack and stack[-1][2])):
            m = HEREDOC.match(text, i)
            if m:
                pending.append(m.group(2))
                out.append(' ')
                i = m.end()
                continue
        elif c == '\n' and pending:
            out.append(c)
            feeds = SHELL_READER.search(text[line_start:i]) is not None
            i += 1
            for delimiter in pending:
                body = []
                while i < n:
                    eol = text.find('\n', i)
                    eol = n if eol == -1 else eol
                    line, i = text[i:eol], eol + 1
                    if line.strip() == delimiter:
                        break
                    body.append(line)
                if feeds:
                    scripts.append('\n'.join(body))
            pending, line_start = [], i
            continue
        if c == '\n':
            line_start = i + 1
        out.append(c)
        i += 1
    if quote or stack:
        raise ValueError('a quote or $( is never closed')
    return ''.join(out), scripts


def _ansi_quote_end(text, start):
    """The index of the quote that closes a Bash $'...' string, in which a
    backslash escapes the next character."""
    j = start
    while j < len(text):
        if text[j] == '\\':
            j += 2
        elif text[j] == "'":
            return j
        else:
            j += 1
    raise ValueError('a quote is never closed')


def closing_paren(text, start, escape):
    depth, quote, j = 0, None, start
    while j < len(text):
        c = text[j]
        if c == escape and quote != "'":
            j += 2
            continue
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
        j += 1
    return len(text)


def _split(text, powershell):
    """(parts, subs): each simple command as (text, piped), where piped says a
    `|` fed it, and the text of each command substitution."""
    parts, subs, buf = [], [], []
    quote, piped = None, False
    escape = '`' if powershell else '\\'
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
        if c in (escape, '`') and nxt == '\n':  # a line continuation
            i += 2
            continue
        if c == escape and nxt:
            buf.append(c + nxt)
            i += 2
            continue
        if c == '$' and nxt == "'" and quote is None and not powershell:
            end = _ansi_quote_end(text, i + 2)
            buf.append(text[i:end + 1])
            i = end + 1
            continue
        if c == '$' and nxt == '(':
            end = closing_paren(text, i + 1, escape)
            subs.append(text[i + 2:end])
            buf.append(SUB)
            i = end + 1
            continue
        if c == '`' and not powershell:
            end = text.find('`', i + 1)
            if end > i + 1 and '\n' not in text[i + 1:end]:
                subs.append(text[i + 1:end])
                buf.append(SUB)
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
            parts.append((''.join(buf), piped))
            buf = []
            piped = c == '|' and nxt != '|' and (i == 0 or text[i - 1] != '|')
            i += 1
            continue
        buf.append(c)
        i += 1
    if quote:
        raise ValueError('a quote is never closed')
    parts.append((''.join(buf), piped))
    return parts, subs


def split_commands(command, powershell=False, _depth=0):
    """(text, piped) for each simple command in `command`, including the
    ones inside command substitutions and the scripts a shell is fed."""
    text, scripts = _prepare(command.replace('\r\n', '\n'), powershell)
    parts, subs = _split(text, powershell)
    found = [(p.strip(), piped) for p, piped in parts if p.strip()]
    if _depth < 4:
        for sub in subs + scripts:
            found.extend(split_commands(sub, powershell, _depth + 1))
    return found


def tokens(segment, assigns=None):
    """The words of one simple command, with assignments, `if`, `timeout`,
    `rtk proxy` and similar prefixes removed and the program name normalised.
    `NAME=value` prefixes, which set the environment of that one command, go
    into `assigns`."""
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
        low = first.lower()
        ps_assign = re.match(r'^\$[\w:]+=(.+)$', first)
        env_assign = re.match(r'^([A-Za-z_]\w*)=(.*)$', first, re.S)
        if ps_assign:
            toks[0] = ps_assign.group(1)
        elif env_assign:
            if assigns is not None:
                assigns[env_assign.group(1).lower()] = env_assign.group(2)
            toks = toks[1:]
        elif low == 'rtk':
            toks = toks[1:]
            if toks and toks[0].lower() == 'proxy':
                toks = toks[1:]
        elif low in PREFIX_WORDS:
            toks = toks[1:]
        elif (re.match(r'^\$[\w:]+$', first) and len(toks) > 1
              and toks[1] in ('=', '+=')):
            toks = toks[2:]
        elif low == 'env':
            toks = toks[1:]
            while toks and (toks[0].startswith('-') or '=' in toks[0]):
                name, eq, value = toks[0].partition('=')
                if eq and assigns is not None and not name.startswith('-'):
                    assigns[name.lower()] = value
                toks = toks[2:] if toks[0] == '-u' else toks[1:]
        elif low == 'timeout':
            toks = toks[1:]
            while toks and (toks[0].startswith('-')
                            or re.match(r'^\d+(\.\d+)?[smhd]?$', toks[0])):
                toks = toks[1:]
        else:
            break
    if toks:
        toks[0] = program(toks[0])
    return toks


def resolve_dir(cwd, target, nt=None):
    """The directory a `cd` to `target` lands in, as Python can open it:
    `~` and `$HOME` expanded, and on Windows a Git Bash `/c/...`,
    `/mnt/c/...` or `/cygdrive/c/...` path turned into `C:/...`."""
    nt = os.name == 'nt' if nt is None else nt
    path = target
    if path == '~' or path.startswith(('~/', '~\\')):
        path = os.path.expanduser('~') + path[1:]
    path = re.sub(r'\$\{?(?:env:)?(\w+)\}?',
                  lambda m: os.environ.get(m.group(1), m.group(0)), path)
    if nt:
        m = re.match(r'^/(?:mnt/|cygdrive/)?([a-zA-Z])(?:/(.*))?$', path)
        if m:
            return '%s:/%s' % (m.group(1).upper(), m.group(2) or '')
    return os.path.join(cwd or '.', path)


def walk(command, cwd=None, powershell=False):
    """(tokens, cwd, variables) for each simple command in `command`,
    following `cd`, the variables and environment set along the way, and the
    remotes a `git remote add` or `set-url` names (as `remote:<name>`)."""
    found = []
    _walk(command, cwd, {}, found, 0, powershell)
    return found


def _walk(command, cwd, variables, found, depth, powershell):
    literal = None
    for segment, piped in split_commands(command, powershell):
        m = PS_ASSIGN.match(segment)
        if m:
            variables[m.group(1).lower()] = m.group(2).strip().strip('\'"')
        assigns = {}
        toks = tokens(segment, assigns)
        if not toks:
            variables.update(assigns)
            literal = None
            continue
        env = dict(variables)
        env.update(assigns)
        fed = literal if piped else None
        literal = _literal(segment, toks, env)
        head = toks[0]
        if head in EXPORT_WORDS:
            for token in toks[1:]:
                name, eq, value = token.partition('=')
                if eq and re.match(r'^[A-Za-z_]\w*$', name):
                    variables[name.lower()] = value
            continue
        if head in CD_WORDS and len(toks) > 1:
            args = [t for t in toks[1:] if not t.startswith('-')]
            if args:
                cwd = resolve_dir(cwd, expand(args[0], env))
            continue
        if head in READ_WORDS or head == 'for' or (head == 'printf' and '-v' in toks):
            # A variable these set holds text the command cannot see.
            if head == 'for':
                names = toks[1:2]
            elif head == 'printf':
                names = toks[toks.index('-v') + 1:toks.index('-v') + 2]
            else:
                names = toks[1:]
            for token in names:
                if re.match(r'^[A-Za-z_]\w*$', token):
                    variables[token.lower()] = '$__unknown'
        if head == 'git':
            rest = _git_subcommand(toks)
            words = [t for t in rest if not t.startswith('-')]
            if (len(words) >= 4 and words[0] == 'remote'
                    and words[1] in ('add', 'set-url')):
                variables['remote:' + words[2].lower()] = words[3]
            if rest[:1] == ['config']:
                _git_config(rest[1:], variables)
        _command(toks, cwd, env, found, depth, powershell, fed)


READ_WORDS = {'read', 'mapfile', 'readarray', 'getopts'}
# git's own options that take a value, before the subcommand.
GIT_VALUE_FLAGS = {'-C', '-c', '--git-dir', '--work-tree', '--namespace',
                   '--config-env'}


def _git_subcommand(toks):
    """A `git` command's subcommand and its arguments."""
    i = 1
    while i < len(toks) and toks[i].startswith('-'):
        i += 2 if toks[i] in GIT_VALUE_FLAGS else 1
    return toks[i:]


GIT_CONFIG_VALUE_FLAGS = {'-f', '--file', '--blob', '--type', '--default',
                          '--comment', '--value', '--url'}


def _git_config(toks, variables):
    """Record a remote URL or an insteadOf rewrite that `git config` sets."""
    args, skip = [], False
    for token in toks:
        if skip:
            skip = False
        elif token.startswith('-'):
            skip = token in GIT_CONFIG_VALUE_FLAGS
        else:
            args.append(token)
    if args[:1] == ['set']:
        args = args[1:]
    if len(args) < 2:
        return
    setting = re.match(r'^remote\.(.+)\.(?:push)?url$', args[0], re.I)
    if setting:
        variables['remote:' + setting.group(1).lower()] = args[1]
    elif re.match(r'^url\..+\.(?:push)?insteadof$', args[0], re.I):
        variables['url:insteadof'] = args[1]


def _literal(segment, toks, env):
    """The text this command hands to a pipe, when it is plain text: a quoted
    string, `echo`, or a variable on its own."""
    text = segment.strip()
    m = re.match(r'^([\'"])(.*)\1$', text, re.S)
    if m:
        return expand(m.group(2), env)
    if toks[0] in ECHO_WORDS:
        return expand(' '.join(t for t in toks[1:]
                               if not re.match(r'^-[neE]+$', t)), env)
    if re.match(r'^\$[\w:]+$', text):
        return expand(text, env)
    return None


def _command(toks, cwd, env, found, depth, powershell, fed=None):
    head = toks[0]
    if depth < 3:
        if head in SHELLS:
            script = _shell_script(toks)
            if script is None:
                script = fed
            if script is not None:
                _walk(script, cwd, dict(env), found, depth + 1,
                      head in POWERSHELLS)
                return
        elif head in EVAL_WORDS:
            args = [t for t in toks[1:] if t.lower() != '-command']
            script = expand(' '.join(args), env) if args else fed
            if script:
                _walk(script, cwd, dict(env), found, depth + 1, head != 'eval')
                return
        elif head == 'xargs':
            i = 1
            while i < len(toks) and toks[i].startswith('-'):
                i += 2 if toks[i] in XARGS_VALUE_FLAGS else 1
            if i < len(toks):
                rest = list(toks[i:])
                rest[0] = program(rest[0])
                _command(rest, cwd, env, found, depth + 1, powershell)
                return
    found.append((toks, cwd, env))


def _shell_script(toks):
    """The script a shell is told to run on its command line, or None."""
    head = toks[0]
    i = 1
    while i < len(toks):
        token, low = toks[i], toks[i].lower()
        rest = ' '.join(toks[i + 1:])
        if head in POWERSHELLS:
            if re.match(r'^[-/]c(o(m(m(a(n(d)?)?)?)?)?)?$', low):
                return rest
            flag = re.sub(r'^(?:--?|/)', '', low)
            if token[:1] in '-/' and flag and (
                    flag == 'ec' or 'encodedcommand'.startswith(flag)):
                try:
                    return base64.b64decode(toks[i + 1]).decode(
                        'utf-16-le', errors='replace')
                except (IndexError, ValueError):
                    return None
            if low in ('-f', '-file'):
                return None
            if not token.startswith(('-', '/')):
                return ' '.join(toks[i:]) if head == 'powershell' else None
            if low in ('-executionpolicy', '-ep', '-ex', '-workingdirectory',
                       '-wd', '-configurationname', '-outputformat', '-o',
                       '-inputformat', '-if', '-windowstyle', '-w'):
                i += 1
        elif head == 'cmd':
            if low in ('/c', '/k'):
                return rest
        else:
            if re.match(r'^-[a-z]*c[a-z]*$', low):
                return rest
            if low in ('-o', '+o'):
                i += 1
            elif not token.startswith(('-', '+')):
                return None
        i += 1
    return None


def expand(text, variables, environ=None):
    """`text` with `$name`, `${name}` and `$env:name` replaced from
    `variables`, then from `environ` when one is given."""
    def value(m):
        name = m.group(1)
        if name.lower() in variables:
            return variables[name.lower()]
        if (environ is not None and not name.startswith('__sub')
                and name in environ):
            return environ[name]
        return m.group(0)
    return re.sub(r'\$\{?(?:env:)?(\w+)\}?', value, text)


def flag_value(toks, names, ignore_case=True):
    """The value of the first flag in `names`, written as `-X POST`, `-XPOST`,
    `--request=POST` or `-Method:Post`. PowerShell names compare
    case-insensitively; pass `ignore_case=False` for a CLI such as `gh`, where
    `-r` and `-R` are different flags."""
    fold = str.lower if ignore_case else (lambda s: s)
    wanted = {fold(n) for n in names}
    for i, token in enumerate(toks):
        key = fold(token)
        if token.startswith('-'):
            for sep in ('=', ':'):
                if sep in key and key.split(sep, 1)[0] in wanted:
                    return token.split(sep, 1)[1]
        if key in wanted and i + 1 < len(toks):
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


def not_read(method):
    return bool(method) and method.upper() not in READ_METHODS


def http_writes(toks):
    """Whether a curl, wget or Invoke-RestMethod call sends a write."""
    if toks[0] in ('curl', 'wget'):
        method, data = None, False
        for i, token in enumerate(toks[1:], 1):
            after = toks[i + 1] if i + 1 < len(toks) else ''
            if token.startswith('--'):
                name, eq, value = token.partition('=')
                if name in ('--request', '--method'):
                    method = value if eq else after
                elif name in DATA_FLAGS:
                    data = True
            elif token.startswith('-'):
                cluster = re.match(r'^-[%s]*X(.*)$' % CURL_BARE, token)
                if cluster:
                    method = cluster.group(1) or after
                elif re.match(r'^-[%s]*[dFT]' % CURL_BARE, token):
                    data = True
        return data or not_read(method)
    return (has_flag(toks, ['-Body', '-InFile'])
            or not_read(flag_value(toks, ['-Method'])))


def http_data(toks):
    """The request bodies written on an HTTP tool's command line."""
    out = []
    for i, token in enumerate(toks):
        after = toks[i + 1] if i + 1 < len(toks) else ''
        name, eq, value = token.partition('=')
        if token.startswith('--') and name in DATA_FLAGS:
            out.append(value if eq else after)
        elif re.match(r'^-[%s]*d$' % CURL_BARE, token) or token.lower() == '-body':
            out.append(after)
        elif re.match(r'^-[%s]*d.' % CURL_BARE, token):
            out.append(token[token.index('d') + 1:])
    return out


def host(url):
    m = re.match(r'^[a-z][\w+.-]*://(?:[^@/]+@)?([^/:]+)', url or '', re.I)
    if m:
        return m.group(1).lower()
    m = re.match(r'^(?:[^@/\s]+@)?([^:/\s]+):(?!\\)', url or '')
    if m and '.' in m.group(1):
        return m.group(1).lower()
    return None


def _location(target):
    """Whether a push target is a URL or path rather than a remote name."""
    return bool('://' in target or host(target)
                or re.match(r'^[\w.-]+@[\w.-]+:', target)
                or re.match(r'^(?:[/.~]|[A-Za-z]:[\\/])', target))


def push_target(toks, cwd):
    """(remote, cwd, config) for a `git push`: the remote None when not named,
    and config the `-c key=value` settings it was given. None when this is
    not a push."""
    if not toks or toks[0] != 'git':
        return None
    i, config = 1, {}
    while i < len(toks) and toks[i].startswith('-'):
        token = toks[i]
        if token in ('-C', '-c') and i + 1 < len(toks):
            if token == '-C':
                cwd = resolve_dir(cwd, toks[i + 1])
            else:
                key, _, value = toks[i + 1].partition('=')
                config[key.lower()] = value
            i += 2
        elif token in ('--git-dir', '--work-tree', '--namespace'):
            i += 2
        else:
            i += 1
    if i >= len(toks) or toks[i] != 'push':
        return None
    rest, j = toks[i + 1:], 0
    while j < len(rest):
        token = rest[j]
        if token == '--repo' and j + 1 < len(rest):
            return rest[j + 1], cwd, config
        if token in ('-o', '--push-option', '--receive-pack', '--exec'):
            j += 2
            continue
        if token.startswith('--repo='):
            return token.split('=', 1)[1], cwd, config
        if not token.startswith('-'):
            return token, cwd, config
        j += 1
    return None, cwd, config


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


def push_url(toks, cwd, lookup=remote_url, variables=None):
    """The URL a `git push` goes to, '' when it cannot be worked out, None
    when this is not a push."""
    target = push_target(toks, cwd)
    if target is None:
        return None
    remote, where, config = target
    variables = variables or {}
    if variables.get('url:insteadof') or any(k.startswith('url.') for k in config):
        return ''  # an insteadOf rewrite can send the push anywhere
    if remote:
        remote = expand(remote, variables)
        if '$' in remote:
            return ''
        if _location(remote):
            return remote
        name = remote.lower()
        override = (config.get('remote.%s.pushurl' % name)
                    or config.get('remote.%s.url' % name)
                    or variables.get('remote:' + name))
    else:
        named = ([v for k, v in config.items()
                  if re.match(r'^remote\..+\.(push)?url$', k)]
                 + [v for k, v in variables.items() if k.startswith('remote:')])
        if len(set(named)) > 1:
            return ''
        override = named[0] if named else None
    if override:
        override = expand(override, variables)
        return '' if '$' in override else override
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
