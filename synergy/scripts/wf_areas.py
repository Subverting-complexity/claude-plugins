"""
The `areas` subcommand: the repository's area epics, or the one an issue
resolves to.

An area epic is a native `Epic` whose `Stage` is `Area`, standing for one
permanent part of the product. An issue's area is the nearest area epic above
it in its parent chain. This reads; it never writes.
"""

import wf_core
from wf_config import field_name, load_config
from wf_io import EXIT_ENV, EXIT_OK, emit, gh_graphql
from wf_issue_audit import scan_open_issues
from wf_issue_io import issue_field_values
from wf_post_merge import STAGE_VALUES_SELECTION


# How far up an issue's parents `--issue` reads: a story, its Feature, the
# area above that, and room for a tree nested deeper than the model asks for.
AREA_CHAIN_DEPTH = 6

_AREA_NODE = 'number title url issueType { name }' + STAGE_VALUES_SELECTION


def _area_chain_selection(depth):
    """The issue and its parents, `depth` levels deep, each with its `Stage`.

    The deepest level asks only whether it has a parent, so a chain that runs
    past the depth is told apart from one that ends there.
    """
    if depth <= 0:
        return 'number'
    return _AREA_NODE + ' parent { %s }' % _area_chain_selection(depth - 1)


def area_chain_query(depth=AREA_CHAIN_DEPTH):
    return ('query($owner:String!,$repo:String!,$number:Int!){'
            ' repository(owner:$owner,name:$repo){ issue(number:$number){ %s } } }'
            % _area_chain_selection(depth))


def _area_entry(node):
    return {'number': node.get('number'), 'title': node.get('title') or '',
            'url': node.get('url') or ''}


def nearest_area(node, stage_field, depth=AREA_CHAIN_DEPTH):
    """The nearest area epic at or above `node`. (area or None, reason or None).

    `node` is the issue as `area_chain_query` returns it. The issue itself
    counts: an area epic resolves to itself.
    """
    number = node.get('number')
    current, level = node, 0
    while current:
        if level >= depth:
            return None, ('#%d has no area epic within %d levels above it, and '
                          'the chain goes on beyond that' % (number, depth))
        if wf_core.is_area_stage(issue_field_values(current).get(stage_field)):
            return _area_entry(current), None
        current, level = current.get('parent'), level + 1
    return None, ('#%d resolves to no area: no area epic sits above it in its '
                  'parent chain' % number)


def cmd_areas(args):
    """`wf areas`: list the open area epics, or resolve one issue's area."""
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    repo = args.repo or '%s/%s' % (cfg['org'], cfg['repo'])
    stage_field = field_name(cfg, 'field-stage')

    if args.issue is not None:
        owner, name = repo.split('/', 1)
        ok, data, err = gh_graphql(area_chain_query(), owner=owner, repo=name,
                                   number=int(args.issue))
        if not ok:
            emit('error', EXIT_ENV, repo=repo, issue=args.issue,
                 reason='could not read the parents of #%d in %s: %s'
                        % (args.issue, repo, err))
        node = ((data or {}).get('repository') or {}).get('issue')
        if not node:
            emit('error', EXIT_ENV, repo=repo, issue=args.issue,
                 reason='issue #%d not found in %s' % (args.issue, repo))
        area, why = nearest_area(node, stage_field)
        if area:
            emit('ok', EXIT_OK, issue=args.issue, area=area)
        emit('ok', EXIT_OK, issue=args.issue, area=None, reason=why)

    ok, issues, err = scan_open_issues(cfg, args.repo)
    if not ok:
        emit('error', EXIT_ENV, repo=repo,
             reason='could not read the open issues in %s: %s' % (repo, err))
    areas = [{'number': i['number'], 'title': i.get('title') or '',
              'url': i.get('url') or '', 'body': i.get('body') or ''}
             for i in issues
             if (i.get('issueType') or {}).get('name') == 'Epic'
             and wf_core.is_area_stage(issue_field_values(i).get(stage_field))]
    areas.sort(key=lambda a: (a['title'].lower(), a['number']))
    emit('ok', EXIT_OK, areas=areas, count=len(areas))
