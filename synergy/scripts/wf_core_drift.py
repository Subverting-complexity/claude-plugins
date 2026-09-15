"""
Finished containers and stage drift: what to close or move after a merge.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

from wf_core_findings import WARNING, finding
from wf_core_select import HIERARCHY_CONTAINER_TYPES
from wf_core_stage import STAGE_NAMES


# ── closing a finished container (#240) ──────────────────────────────────────
# GitHub's native sub-issues never close a parent, and a merge closes only the
# issues its pull request names. So an Epic or Feature whose last story merged
# stayed open, in a stage nobody routinely looks at, until somebody noticed.

def container_finished(node, closed=()):
    """Whether an Epic or Feature is finished: open, and every sub-issue closed.

    `node` is `{'number', 'type', 'state', 'children': [{'number', 'state'}]}`.
    `closed` names issues this run has just closed, whose read may predate it.

    Any close counts, including "not planned": a container held open by one
    dropped story would stay open for ever. A container with no sub-issues is
    never finished, because an empty Epic may be a placeholder.
    """
    if node.get('type') not in HIERARCHY_CONTAINER_TYPES:
        return False
    if (node.get('state') or '').upper() != 'OPEN':
        return False
    children = node.get('children') or []
    if not children:
        return False
    done = set(closed or ())
    return all((c.get('state') or '').upper() == 'CLOSED' or c.get('number') in done
               for c in children)


def ancestors_to_close(origin, chain, closed=(), repo=None):
    """The ancestors closing `origin` finishes, nearest first.

    `chain` is `origin`'s parents, nearest first, each shaped as
    `container_finished` reads it plus `repo`. The walk stops at the first
    parent that is not finished, because every ancestor above it has it as an
    open child, and at the first one in another repository, which this
    repository has no business closing.

    Returns [{'number', 'finished_by'}], where `finished_by` is the child whose
    close finished it -- `origin` for the nearest, the one below for the rest.
    """
    done = set(closed or ()) | {origin}
    out, child = [], origin
    for node in chain or ():
        if repo and node.get('repo') and node['repo'] != repo:
            break
        if not container_finished(node, done):
            break
        out.append({'number': node['number'], 'finished_by': child})
        done.add(node['number'])
        child = node['number']
    return out


def finished_container_findings(containers, path='ClaudeProject.md'):
    """One warning naming every open Epic or Feature that is already finished."""
    if not containers:
        return []
    count = len(containers)
    return [finding(
        WARNING, 'container-finished',
        '%d open Epic or Feature issue%s %s every sub-issue closed, and nothing '
        'closes a container on its own: %s'
        % (count, '' if count == 1 else 's', 'has' if count == 1 else 'have',
           ', '.join('#%d' % c['number'] for c in containers)),
        'close each as completed, or run `wf preflight --fix`', path)]


def stage_drift_findings(drifted, path='ClaudeProject.md'):
    """One warning naming every issue whose `Stage` says it is available.

    `drifted` is `[{'number', 'stage'}]`, where `stage` is the purpose key
    `stage_drift_target` returned.
    """
    if not drifted:
        return []
    count = len(drifted)
    return [finding(
        WARNING, 'stage-drift',
        '%d open issue%s %s a blank or `Backlog` `Stage` although an assignee or '
        'an open pull request says the work has started, so every view grouped '
        'by `Stage` shows %s as available: %s'
        % (count, '' if count == 1 else 's', 'has' if count == 1 else 'have',
           'it' if count == 1 else 'them',
           ', '.join('#%d (should be %s)' % (d['number'], STAGE_NAMES[d['stage']])
                     for d in drifted)),
        'set each to the stage named, or run `wf preflight --fix`', path)]
