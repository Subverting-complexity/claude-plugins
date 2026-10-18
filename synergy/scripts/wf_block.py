"""
`wf block`: block a story in one call.

It replaces the comment, spec, `issue-apply`, `sibling-pr`, `claim-release`,
`gh issue edit` and `stage-set` sequence `commands/block-story.md` used to
spell out. `scripts/README.md` has the module map.
"""

import argparse
import json
import os

import wf_core
from wf_claim import release_claims
from wf_config import prepare_cfg, repo_root
from wf_io import (
    EXIT_ALL_BLOCKED, EXIT_ENV, EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, call_command,
    emit, emit_line, gh_json, run,
)
from wf_stage import set_stage

NON_CODE = {
    'human': ('[Manual] ', 'Human'),
    'browser': ('[Browser] ', 'Browser agent'),
}


def _apply_spec(number, entry):
    """Write a one-entry spec and apply it. Returns (ok, reason)."""
    from wf_issue_apply import cmd_issue_apply
    folder = os.path.join(repo_root(), '.claude')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, 'block-spec.json')
    entry = dict(entry, number=number)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump({'issues': [entry]}, fh)
    code, payload = call_command(cmd_issue_apply, argparse.Namespace(
        spec=path, repo=None, refresh=False, dry_run=False))
    if code == EXIT_OK:
        return True, None
    return False, payload.get('reason') or 'issue-apply exited %s' % code


def cmd_block(args):
    """Comment the blocker, record it, and take the story out of the pool.

    An issue blocker becomes native blocked-by edges (`--blocked-by`, the
    complete set), which is what `wf unblock` releases it on. Non-code work
    (`--non-code human|browser`) is routed by `Ownership` and set to
    `Non-code` instead, because an edge would hand it back to a code agent.
    A story with an open pull request keeps its assignee and stage: blocking
    it would let another agent open a second PR for the same work.
    """
    from wf_review import cmd_sibling_pr

    if args.non_code and args.blocked_by:
        emit('usage', EXIT_USAGE, reason='--non-code work has no blocked-by edge; '
                                         'pass one or the other')
    try:
        with open(args.body_file, encoding='utf-8') as fh:
            if not fh.read().strip():
                emit('usage', EXIT_USAGE, reason='the blocker comment is empty')
    except OSError as exc:
        emit('usage', EXIT_USAGE, reason='could not read %s (%s)' % (args.body_file, exc))

    cfg = prepare_cfg()
    number = args.issue
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, issue, err = gh_json(['issue', 'view', str(number), '--repo', repo,
                              '--json', 'number,title'])
    if not ok or not issue:
        emit('error', EXIT_ENV, reason='could not read #%d (%s)' % (number, err))
    title = issue.get('title') or ''
    label = '#%d %s' % (number, title)
    problems = []

    code, _, cerr = run(['gh', 'issue', 'comment', str(number), '--repo', repo,
                         '--body-file', args.body_file])
    commented = code == 0
    if not commented:
        problems.append('comment not posted (%s)' % cerr.strip())

    recorded = None
    if args.blocked_by and not args.non_code:
        recorded, why = _apply_spec(number, {'blocked_by': list(args.blocked_by)})
        if not recorded:
            problems.append('blocked-by edges not written (%s)' % why)

    scode, siblings = call_command(cmd_sibling_pr, argparse.Namespace(
        number=[number], exclude_branch=None))
    if scode != EXIT_OK:
        emit('error', EXIT_ENV, issue=number, title=title, commented=commented,
             recorded=recorded, reason='could not check for an open PR, so %s '
             'was left assigned and in its stage (%s)'
             % (label, siblings.get('reason') or 'no detail'))
    if siblings.get('found'):
        prs = [{'number': p['number'], 'title': p['title']} for p in siblings.get('prs') or ()]
        emit('has-pr', EXIT_ALL_BLOCKED, issue=number, title=title, prs=prs,
             commented=commented, recorded=recorded,
             reason='%s has an open PR (%s); handle the blocker on the PR. The '
                    'issue stays assigned and in its stage'
                    % (label, ', '.join('#%d %s' % (p['number'], p['title']) for p in prs)))

    # The open-PR check comes before the non-code write: a story with an
    # open PR is handled on the PR, so its title and Ownership stay as they are.
    if args.non_code:
        prefix, owner = NON_CODE[args.non_code]
        entry = {'title': title if title.startswith(prefix) else prefix + title,
                 'fields': {'field-ownership': owner}}
        recorded, why = _apply_spec(number, entry)
        if not recorded:
            problems.append('ownership not set (%s)' % why)

    released = release_claims(['issue-%d' % number]).get('issue-%d' % number, False)
    if not released:
        problems.append('claim not released')
    code, _, uerr = run(['gh', 'issue', 'edit', str(number), '--repo', repo,
                         '--remove-assignee', '@me'])
    if code != 0:
        problems.append('not unassigned (%s)' % uerr.strip())

    stage_key = 'stage-non-code' if args.non_code else 'stage-blocked'
    stage = wf_core.STAGE_NAMES[stage_key]
    staged, stage_msg = set_stage(cfg, number, stage)
    if not staged:
        problems.append('Stage not set: %s' % stage_msg)

    if problems:
        emit('partial', EXIT_PARTIAL, issue=number, title=title, stage=stage,
             reason='%s: %s' % (label, '; '.join(problems)))
    emit_line('ok', EXIT_OK, issue=number,
              reason='%s set to %s, unassigned and released' % (label, stage))
