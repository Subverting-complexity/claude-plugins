"""
`wf pr-create`: push, flag duplicates, open the pull request and check its
body, in one call.

It replaces the push, `sibling-pr`, the stale-sibling `gh pr view`, `gh pr
create`, and the read-back, corruption test and retry that `finish.md`,
`bulk-finish.md` and `templates/body-file-write.md` described.
`scripts/README.md` has the module map.
"""

import argparse
import os
import re

import wf_core
from wf_config import prepare_cfg, repo_root
from wf_io import (
    EXIT_ENV, EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, call_command, emit, emit_line,
    gh_json, run,
)

_PR_URL = re.compile(r'/pull/(\d+)')
FINAL_BODY = 'pr-create-body.md'


def _write(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def _read_pr(repo, ref):
    ok, data, err = gh_json(['pr', 'view', str(ref), '--repo', repo,
                             '--json', 'number,url,body'])
    return (data if ok and data else None), err


def cmd_pr_create(args):
    """Open a real pull request for the committed branch.

    The duplicate check runs after the push and immediately before the create,
    so the flag line it adds cannot be stale. Every issue the PR is for gets a
    `Closes #N` line, and the stored body is read back and rewritten once if
    it came back corrupt. Re-running on a branch whose PR already exists
    checks that PR's body rather than failing.
    """
    try:
        with open(args.body_file, encoding='utf-8') as fh:
            body = fh.read()
    except OSError as exc:
        emit('usage', EXIT_USAGE, reason='could not read %s (%s)' % (args.body_file, exc))
    issues = [int(n) for n in args.issue or ()]
    if not issues:
        emit('usage', EXIT_USAGE, reason='name every issue the PR closes with --issue N')

    cfg = prepare_cfg()
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    base = args.base or cfg['default_branch']

    code, branch, _ = run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
    branch = (branch or '').strip()
    if code != 0 or not branch or branch == 'HEAD':
        emit('error', EXIT_ENV, reason='not on a branch; check out the story branch first')
    code, _, err = run(['git', 'push', '-u', 'origin', 'HEAD'])
    if code != 0:
        emit('error', EXIT_ENV, reason='push failed (%s)' % err.strip())

    from wf_review import cmd_sibling_pr
    notes = []
    scode, siblings = call_command(cmd_sibling_pr, argparse.Namespace(
        number=issues, exclude_branch=branch))
    duplicates = []
    if scode != EXIT_OK:
        notes.append('duplicate check failed (%s), so none is flagged'
                     % (siblings.get('reason') or 'no detail'))
    else:
        for entry in siblings.get('by_issue') or ():
            for pr in entry.get('prs') or ():
                duplicates.append({'issue': entry['issue'], 'pr': pr['number'],
                                   'title': pr['title']})
    flags = wf_core.duplicate_flag_lines(siblings.get('by_issue') if scode == EXIT_OK else ())
    text = body.lstrip('\n')
    fresh = [line for line in flags if line not in text]
    if fresh:
        text = '\n'.join(fresh) + '\n\n' + text
    text = wf_core.with_closes_lines(text, issues)
    final = os.path.join(repo_root(), '.claude', FINAL_BODY)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    _write(final, text)

    code, out, err = run(['gh', 'pr', 'create', '--repo', repo, '--base', base,
                          '--head', branch, '--title', args.title,
                          '--body-file', final])
    created = code == 0
    if created:
        match = _PR_URL.search(out or '')
        ref = match.group(1) if match else branch
    elif 'already exists' in (err or ''):
        ref = branch
        notes.append('a PR for this branch already existed; its body was checked')
    else:
        emit('error', EXIT_ENV, reason='gh pr create failed (%s)' % err.strip())

    pr, rerr = _read_pr(repo, ref)
    if pr is None:
        emit('partial', EXIT_PARTIAL, created=created, duplicates=duplicates,
             reason='PR created but could not be read back (%s)' % rerr)
    problems = wf_core.body_problems(pr.get('body'), issues)
    if problems:
        run(['gh', 'pr', 'edit', str(pr['number']), '--repo', repo, '--body-file', final])
        again, _ = _read_pr(repo, pr['number'])
        problems = wf_core.body_problems((again or {}).get('body'), issues)
    try:
        os.remove(final)
    except OSError:
        pass

    fields = dict(pr=pr['number'], url=pr['url'])
    if duplicates:
        fields['duplicates'] = duplicates
    if problems or notes:
        emit('partial' if problems else 'ok', EXIT_PARTIAL if problems else EXIT_OK,
             created=created, problems=problems, notes=notes, **fields,
             reason='; '.join(problems + notes) + ('; the body may need editing by '
                                                   'hand' if problems else ''))
    emit_line('ok', EXIT_OK, **fields,
              reason='PR #%d opened%s' % (pr['number'],
                                          '; possible duplicate flagged'
                                          if duplicates else ''))
