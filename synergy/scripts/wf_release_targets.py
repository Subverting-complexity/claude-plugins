"""
The `release-targets` subcommand: what a run needs to decide where each issue
a pull request closes will ship.

A merged pull request leaves each issue it closes with a `release: {target}`
label for each release target its work ships in, named after a row of the
`## Release Targets` table in `ClaudeProject.md`. `post-merge` writes the
labels, but it is a script and cannot judge where work ships, so the targets
are decided before the merge and posted on the pull request beside the
release notes. This command gathers what that decision reads.

For each issue it finds the file paths the issue's own work changed. A pull
request that closes 1 issue gives that issue every path it changed. One that
closes several gives each issue the paths of its own commits, matched by the
`(#N)` that ends a commit's first line, so one story's files never decide
where another ships. Jev is then asked its `target` check, and each `high`
answer is returned as decided. Every other target comes back under `decide`
for the caller. Jev is optional: with no key, or with Jev off for the
repository, every target goes to `decide`.

The pull request's commits are read from GitHub, where they stay readable
after a squash merge deletes the branch, so the command also serves a pull
request that merged with no targets on it. It writes nothing.

`scripts/README.md` has the module map.
"""

import wf_core
from wf_config import load_config
from wf_io import EXIT_ENV, EXIT_OK, emit, emit_line, gh_json
from wf_jev import jev_ask
from wf_post_merge import _aliased_repository_read


RELEASE_TARGETS_SELECTION = 'number title body labels(first:50){ nodes { name } }'
# GitHub lists this many of a pull request's commits on one page. A pull
# request with more is read to here, and the later commits count for no story.
PR_COMMITS_PAGE = 100
# How many folders an issue's entry shows. The decision reads where the work
# is, and a longer list says no more.
FOLDERS_SHOWN = 20


def pr_commits(repo, pr, stories):
    """The pull request's commits that name one of `stories`, each with the
    paths it changed. (ok, [{'message', 'paths'}], err).

    One read for the commit list, then one for each commit that ends its
    first line with a story's `(#N)`. A commit that names no story is never
    read, because its paths count for no story.
    """
    ok, listed, err = gh_json(['api', 'repos/%s/pulls/%d/commits?per_page=%d'
                               % (repo, pr, PR_COMMITS_PAGE)])
    if not ok:
        return False, [], err or 'could not list the commits'
    wanted, out = {int(n) for n in stories}, []
    for entry in listed or []:
        message = ((entry or {}).get('commit') or {}).get('message') or ''
        if wf_core.commit_story(message) not in wanted or not entry.get('sha'):
            continue
        ok, commit, err = gh_json(['api', 'repos/%s/commits/%s'
                                   % (repo, entry['sha'])])
        if not ok:
            return False, [], err or 'could not read commit %s' % entry['sha']
        out.append({'message': message,
                    'paths': [f.get('filename') for f
                              in (commit or {}).get('files') or []
                              if f and f.get('filename')]})
    return True, out, ''


def _jev_targets(items, names):
    """Ask Jev where each item ships. ({number: {target: bool}}, `jev` value).

    Only `high` answers are returned, yes and no alike: a sure no is a
    decision too, and leaves the caller one target fewer to judge.
    """
    outcome, result = jev_ask('target', {'items': items})
    if outcome != 'ok':
        return {}, 'unavailable'
    by_key = {name.lower(): name for name in names}
    sure = {}
    for row in result.get('rows') or ():
        target = by_key.get(str(row.get('target') or '').lower())
        if row.get('level') != 'high' or target is None \
                or not isinstance(row.get('answer'), bool):
            continue
        try:
            number = int(row.get('id'))
        except (TypeError, ValueError):
            continue
        sure.setdefault(number, {})[target] = row['answer']
    return sure, ('used' if sure else 'not-sure')


def cmd_release_targets(args):
    """`wf release-targets`: what decides each closed issue's release targets."""
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    names = [name for name, _ in wf_core.jev_table_rows(cfg.get('release_targets'))]
    if not names:
        emit_line('ok', EXIT_OK, issues=[],
                  reason='ClaudeProject.md has no Release Targets table, so no '
                         'release label is set and no targets are written')
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ok, data, err = gh_json(['pr', 'view', str(args.pr), '--repo', repo, '--json',
                             'number,closingIssuesReferences,files'])
    if not ok or not data:
        emit('error', EXIT_ENV, reason='could not read PR #%d (%s)' % (args.pr, err))
    numbers = wf_core.closing_issue_numbers(data.get('closingIssuesReferences'))
    for extra in args.issue or []:
        if extra not in numbers:
            numbers.append(extra)
    if not numbers:
        emit_line('ok', EXIT_OK, issues=[],
                  reason='PR #%d closes no issue, so there is no target to '
                         'decide' % args.pr)

    titles, bodies, labels = {}, {}, {}
    for number, read, node, err in _aliased_repository_read(
            cfg, numbers, 'r', RELEASE_TARGETS_SELECTION):
        if not read or not node:
            emit('error', EXIT_ENV, repo=repo, issue=number,
                 reason='could not read #%d in %s: %s'
                        % (number, repo, err or 'no such issue'))
        titles[number] = node.get('title') or ''
        bodies[number] = node.get('body') or ''
        labels[number] = wf_core.release_labels_on(
            [n.get('name') or '' for n in (node.get('labels') or {}).get('nodes') or []])

    if len(numbers) == 1:
        paths = {numbers[0]: [f.get('path') for f in data.get('files') or []
                              if f and f.get('path')]}
    else:
        ok, commits, err = pr_commits(repo, args.pr, numbers)
        if not ok:
            emit('error', EXIT_ENV, reason='could not read the commits of PR '
                                           '#%d (%s)' % (args.pr, err))
        paths = wf_core.story_paths(commits, numbers)

    items = [{'id': n, 'title': titles[n], 'body': bodies[n], 'paths': paths[n]}
             for n in numbers]
    sure, jev = _jev_targets(items, names)
    issues = []
    for number in numbers:
        answers = sure.get(number) or {}
        folders = wf_core.jev_folders(paths[number])
        issues.append({
            'number': number, 'title': titles[number],
            'folders': folders[:FOLDERS_SHOWN], 'paths': len(paths[number]),
            'targets': [n for n in names if answers.get(n) is True],
            'decide': [n for n in names if n not in answers],
            'labels': labels[number]})
    emit('ok', EXIT_OK, pr=args.pr, issues=issues, valid=names, jev=jev,
         reason="for each issue, keep `targets`, judge each name under "
                "`decide` yourself from the issue and its `folders`, and write "
                "the names that apply as that issue's `targets` in "
                ".claude/release-notes.json; write [] when none applies, "
                "which sets `release: internal`")
