"""
`wf pr-create`: push, flag duplicates, open the pull request and check its
body, in one call.

It replaces the push, `sibling-pr`, the stale-sibling `gh pr view`, `gh pr
create`, and the read-back, corruption test and retry that `finish.md`,
`bulk-finish.md` and `templates/body-file-write.md` described. Where GraphQL
is blocked, the create, the read-back and the rewrite go through REST
(`wf_rest_pr.py`).
`scripts/README.md` has the module map.
"""

import argparse
import os
import re

import wf_core
import wf_rest_pr
from wf_config import prepare_cfg, repo_root
from wf_io import (
    EXIT_ENV, EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, call_command, emit, emit_line,
    gh_json, graphql_blocked, run, run_gh,
)

_PR_URL = re.compile(r'/pull/(\d+)')
FINAL_BODY = 'pr-create-body.md'


def _write(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def _read_pr(cfg, ref):
    """The pull request `ref` names, with its number, URL and stored body.
    (pr_or_None, err). Through REST when GraphQL is blocked."""
    if not graphql_blocked():
        ok, data, err = gh_json(['pr', 'view', str(ref), '--repo', _repo(cfg),
                                 '--json', 'number,url,body'])
        if ok and data:
            return data, ''
        if not graphql_blocked():
            return None, err
    return wf_rest_pr.rest_pr_view(cfg, ref)


def _repo(cfg):
    return '%s/%s' % (cfg['org'], cfg['repo'])


def _create(cfg, base, branch, title, final, text):
    """Open the pull request. (created, ref, note); `ref` is None when the
    create failed, and `note` then says why.

    `gh pr create` reads through GraphQL, so where GraphQL is blocked the
    pull request is opened through REST with the same title, body and base.
    """
    if not graphql_blocked():
        code, out, err = run_gh(['gh', 'pr', 'create', '--repo', _repo(cfg),
                                 '--base', base, '--head', branch, '--title', title,
                                 '--body-file', final])
        if code == 0:
            match = _PR_URL.search(out or '')
            return True, match.group(1) if match else branch, None
        if 'already exists' in (err or ''):
            return False, branch, ''
        if not graphql_blocked():
            return False, None, 'gh pr create failed (%s)' % err.strip()
    raw, existed, err = wf_rest_pr.rest_pr_create(cfg, base, branch, title, text)
    if raw is None:
        return False, None, 'REST pull request create failed (%s)' % err
    return not existed, raw['number'], '' if existed else None


def _edit_body(cfg, number, final, text):
    if not graphql_blocked():
        code, _, _ = run_gh(['gh', 'pr', 'edit', str(number), '--repo', _repo(cfg),
                             '--body-file', final])
        if code == 0 or not graphql_blocked():
            return
    wf_rest_pr.rest_pr_edit_body(cfg, number, text)


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

    created, ref, why = _create(cfg, base, branch, args.title, final, text)
    if ref is None:
        emit('error', EXIT_ENV, reason=why)
    if why == '':
        notes.append('a PR for this branch already existed; its body was checked')

    pr, rerr = _read_pr(cfg, ref)
    if pr is None:
        emit('partial', EXIT_PARTIAL, created=created, duplicates=duplicates,
             reason='PR created but could not be read back (%s)' % rerr)
    problems = wf_core.body_problems(pr.get('body'), issues)
    if problems:
        _edit_body(cfg, pr['number'], final, text)
        again, _ = _read_pr(cfg, pr['number'])
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
