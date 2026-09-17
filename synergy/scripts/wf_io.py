"""
Process and GitHub plumbing: exit codes, the stdout JSON contract, and the
`gh`/`git` subprocess runner every other module calls through.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import contextlib
import io
import json
import os
import subprocess
import sys


EXIT_OK = 0
EXIT_NO_CANDIDATES = 10
EXIT_ALL_BLOCKED = 11
EXIT_NEEDS_REFINEMENT = 12
EXIT_ENV = 20
EXIT_CAPABILITY = 21
EXIT_SPEC = 22
EXIT_VERIFY = 23
EXIT_PARTIAL = 24
EXIT_GAPS = 25
EXIT_DRIFT = 26
EXIT_LOST = 27
EXIT_UNSUPPORTED = 30
EXIT_USAGE = 2


# ── small I/O helpers ────────────────────────────────────────────────────────

def eprint(*args):
    print(*args, file=sys.stderr)


def emit(status, exit_code, **fields):
    """Write the single stdout JSON object and exit with the matching code."""
    payload = {'status': status}
    payload.update(fields)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write('\n')
    sys.exit(exit_code)


def emit_line(status, exit_code, **fields):
    """`emit` on one compact line, for a result the caller need not read further.

    A command whose every step succeeded prints this: the status and a short
    `reason`, with nothing else to parse. A partial or failed result uses
    `emit` instead and names what did not happen.
    """
    payload = {'status': status}
    payload.update(fields)
    sys.stdout.write(json.dumps(payload, separators=(',', ':')) + '\n')
    sys.exit(exit_code)


def call_command(func, args):
    """Run a `cmd_*` in this process and return (exit_code, payload).

    Every command ends by emitting one JSON object and exiting, so a command
    built from others captures that object instead of re-implementing them.
    Their stderr passes through, so a warning still reaches the caller.
    """
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            func(args)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    out = buf.getvalue().strip()
    try:
        payload = json.loads(out) if out else {}
    except json.JSONDecodeError:
        payload = {'status': 'error', 'reason': out[:200]}
    return code, payload


# git and gh must fail rather than ask for credentials. An unattended run (a
# `wf claim` pushing its claim ref, say) has nobody to answer a terminal prompt
# or a Git Credential Manager window, so expired credentials would hang it
# instead of failing it with a message the caller can report.
NON_INTERACTIVE_ENV = {'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}


def _non_interactive_env():
    """The current environment with credential prompts turned off. Built per
    call rather than at import, so a variable set later still reaches git."""
    env = dict(os.environ)
    env.update(NON_INTERACTIVE_ENV)
    return env


def run(args, input_text=None):
    """Run a subprocess, capturing text output. Returns (code, stdout, stderr).

    The child runs with `NON_INTERACTIVE_ENV` over the current environment, so
    a credential that needs a person fails the call instead of hanging it.

    Decoding is pinned to UTF-8 with ``errors='replace'`` rather than the
    platform locale codec. ``gh`` emits UTF-8 (issue bodies routinely carry
    smart quotes, em dashes, emoji), but on Windows ``text=True`` defaults to
    cp1252, whose reader thread dies with ``UnicodeDecodeError`` on the first
    byte it can't map — leaving ``stdout`` as ``None`` and surfacing only a
    downstream ``NoneType`` error. Pinning the codec keeps the picker working
    on any locale; ``errors='replace'`` degrades stray bytes to U+FFFD instead
    of crashing.
    """
    try:
        proc = subprocess.run(
            args, input=input_text, capture_output=True, text=True,
            encoding='utf-8', errors='replace', env=_non_interactive_env(),
        )
    except FileNotFoundError:
        return 127, '', '%s: not found' % args[0]
    return proc.returncode, proc.stdout, proc.stderr


def gh_json(args):
    """Run `gh <args>` expecting JSON on stdout. Returns (ok, parsed, stderr)."""
    code, out, err = run(['gh'] + args)
    if code != 0:
        return False, None, (err or '').strip()
    out = out or ''
    try:
        return True, json.loads(out) if out.strip() else None, ''
    except json.JSONDecodeError as exc:
        return False, None, 'could not parse gh JSON: %s' % exc


def _graphql_args(query, fields):
    """Build the `gh api graphql` argv, typing each field by its Python type.

    Each field reaches GitHub as the matching GraphQL scalar:

      - ``bool`` → ``-F key=true/false`` (typed JSON boolean → ``Boolean!``)
      - ``int``  → ``-F key=123`` (typed JSON number → ``Int!``)
      - other    → ``-f key=value`` (raw string → ``String!`` / ``ID!``)

    The type split matters: ``-F`` coerces any all-digit value to an int, so an
    ``ID!``/``String!`` variable whose value is digit-only — e.g. a numeric
    single-select option id like ``98236657`` (a `Stage` option) — would
    arrive as an Int and GitHub rejects it with *"Variable $o of type String!
    was provided invalid value"*. Routing strings through ``-f`` keeps digit-only
    ids as strings, while genuine ``Int!`` args (Python ints, e.g. an issue
    ``number``) still go through ``-F``. ``bool`` is checked before ``int``
    because ``bool`` is an ``int`` subclass.
    """
    args = ['gh', 'api', 'graphql', '-f', 'query=%s' % query]
    for key, value in fields.items():
        if isinstance(value, bool):
            args += ['-F', '%s=%s' % (key, 'true' if value else 'false')]
        elif isinstance(value, int):
            args += ['-F', '%s=%d' % (key, value)]
        else:
            args += ['-f', '%s=%s' % (key, value)]
    return args


def gh_graphql(query, **fields):
    """Run a GraphQL query/mutation via `gh api graphql`. Returns (ok, data, err).

    Fields are typed by Python type via `_graphql_args` so digit-only ID/String
    values are not coerced to ints (see that helper for the full rationale).
    """
    args = _graphql_args(query, fields)
    code, out, err = run(args)
    if code != 0:
        return False, None, err.strip()
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError as exc:
        return False, None, 'could not parse GraphQL JSON: %s' % exc
    if parsed.get('errors'):
        return False, None, json.dumps(parsed['errors'])
    return True, parsed.get('data'), ''
