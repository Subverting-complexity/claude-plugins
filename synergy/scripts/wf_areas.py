"""
The `areas` subcommand: the repository's areas, or the one an issue carries.

An area is one row of the `## Areas` table in `ClaudeProject.md`, standing for
one part of the product. An issue's area is its `area: {name}` label, and
every issue carries exactly 1. Nothing here reads an issue's parents: GitHub
allows a parent at most 100 sub-issues, so an area kept in the parent chain
fills up and refuses new issues. This reads; it never writes.
"""

import wf_core
from wf_config import load_config
from wf_io import EXIT_ENV, EXIT_OK, emit, gh_graphql


# The issue's own labels and nothing above it. Fifty is the page the other
# label reads use, far more than an issue carries.
AREA_LABEL_QUERY = (
    'query($owner:String!,$repo:String!,$number:Int!){'
    ' repository(owner:$owner,name:$repo){ issue(number:$number){'
    ' number title labels(first:50){ nodes { name } } } } }')


def area_rows(cfg):
    """The rows of the `## Areas` table. `[{'name', 'description', 'label'}]`,
    in table order.

    `name` is what an issue spec passes as `area`, and `label` is the label
    that name becomes. A repository with no table has no rows.
    """
    return [{'name': row['name'],
             'description': (row.get('description') or '').strip(),
             'label': wf_core.area_label(row['name'])}
            for row in cfg.get('areas') or []
            if (row.get('name') or '').strip()]


def issue_area(number, label_names, rows):
    """The area the labels on issue `number` name. (area or None, reason or None).

    `area` is the table row, as `area_rows` shapes it. There is no area, and a
    reason says why, when the issue carries no area label, when it carries
    more than 1, and when its 1 label names no row of the table. None of them
    is guessed at: which part of the product an issue belongs to is a
    decision, and `wf area-set` is where it is made.
    """
    carried = wf_core.area_labels_on(label_names)
    if not carried:
        return None, ('#%d carries no area label; run `wf area-set --issue %d` '
                      'to give it one' % (number, number))
    if len(carried) > 1:
        return None, ('#%d carries %d area labels (%s) and an issue has exactly '
                      '1; run `wf area-set --issue %d --area NAME` to keep one'
                      % (number, len(carried), ', '.join(carried), number))
    row = wf_core.area_row(rows, carried[0].split(':', 1)[1])
    if row is None:
        return None, ('#%d carries `%s`, which names no row of the Areas table '
                      'in ClaudeProject.md' % (number, carried[0]))
    return row, None


def cmd_areas(args):
    """`wf areas`: list the rows of the areas table, or read one issue's area."""
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    rows = area_rows(cfg)

    if args.issue is None:
        emit('ok', EXIT_OK, areas=rows, count=len(rows))

    repo = args.repo or '%s/%s' % (cfg['org'], cfg['repo'])
    owner, name = repo.split('/', 1)
    ok, data, err = gh_graphql(AREA_LABEL_QUERY, owner=owner, repo=name,
                               number=int(args.issue))
    if not ok:
        emit('error', EXIT_ENV, repo=repo, issue=args.issue,
             reason='could not read the labels of #%d in %s: %s'
                    % (args.issue, repo, err))
    node = ((data or {}).get('repository') or {}).get('issue')
    if not node:
        emit('error', EXIT_ENV, repo=repo, issue=args.issue,
             reason='issue #%d not found in %s' % (args.issue, repo))
    labels = [n.get('name') or ''
              for n in (node.get('labels') or {}).get('nodes') or [] if n]
    area, why = issue_area(int(args.issue), labels, rows)
    if area:
        emit('ok', EXIT_OK, issue=args.issue, area=area)
    emit('ok', EXIT_OK, issue=args.issue, area=None, reason=why)
