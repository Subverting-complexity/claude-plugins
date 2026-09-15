"""
Bulk sets: ordering a set of stories and choosing one from a container.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

from wf_core_select import HIERARCHY_CONTAINER_TYPES


# ── Bulk set planning (bulk-execute) ─────────────────────────────────────────
# `bulk-execute` builds two to five related stories on one branch behind one
# pull request. Two of its decisions are pure enough to live here rather than
# in prose: which dependencies still block a story that is being built
# alongside its own dependency, and what order the set has to be built in.

BULK_MIN = 2
BULK_MAX = 5


def blocking_dependencies(deps, open_numbers, siblings=()):
    """Return the dependencies that genuinely block a story.

    A dependency blocks when it is still **open** and is **not** being built
    alongside this story. That sibling carve-out is the whole reason a bulk
    run can take a dependency chain: `execute`'s rule is "do not build on
    unmerged work you cannot see", and a story landing in the same commit
    series on the same branch is work you can see. Anything open and outside
    the set still blocks, exactly as it does for a single-story run.

    `deps` are the numbers parsed out of the issue body, `open_numbers` those
    of them the caller found still open, and `siblings` the rest of the bulk
    set. Returns the blocking numbers in the order they appear in `deps`.
    """
    open_set = {int(n) for n in (open_numbers or ())}
    sib = {int(n) for n in (siblings or ())}
    return [d for d in deps if int(d) in open_set and int(d) not in sib]


def plan_bulk_order(stories, max_size=BULK_MAX):
    """Trim a proposed bulk set to size and put it in build order.

    `stories` is the proposed set in preference order, **lead first** — dicts
    carrying `number`, and `blocked_by` when the story has native dependency
    edges (a list of issue numbers). Two passes:

      1. **Trim** to `max_size`, keeping input order, so the lead and the
         highest-preference siblings are the ones that survive.
      2. **Order** so each story is built after every story in the set it
         depends on. Stories that are ready at the same time keep their input
         order, so a set with no internal dependencies comes back unchanged.

    A dependency cycle inside the set cannot be ordered. Once no story is
    ready, the ones still unplaced are appended in input order and reported,
    so the caller can say so rather than silently choosing an order.

    Returns (ordered, notes). `ordered` is the story dicts in build order.
    `notes` is a list of {'number', 'reason'} with reason `'trimmed'` (cut by
    `max_size`) or `'dependency-cycle'`. Enforcing `BULK_MIN` is the caller's
    job: a set that shrinks to one story is a single-story run, not an error.
    """
    stories = list(stories or [])
    notes = []
    if max_size is not None and max_size > 0 and len(stories) > max_size:
        for extra in stories[max_size:]:
            notes.append({'number': extra['number'], 'reason': 'trimmed'})
        stories = stories[:max_size]
    if not stories:
        return [], notes

    present = {s['number'] for s in stories}
    deps_in_set = {}
    for story in stories:
        edges = [int(d) for d in (story.get('blocked_by') or ())]
        deps_in_set[story['number']] = {d for d in edges
                                        if d in present and d != story['number']}

    ordered, placed, remaining = [], set(), list(stories)
    while remaining:
        ready = [s for s in remaining if deps_in_set[s['number']] <= placed]
        if not ready:
            for stuck in remaining:
                notes.append({'number': stuck['number'], 'reason': 'dependency-cycle'})
            ordered.extend(remaining)
            break
        for story in ready:
            ordered.append(story)
            placed.add(story['number'])
        remaining = [s for s in remaining if s['number'] not in placed]
    return ordered, notes


# ── a bulk set chosen from a container (`candidates --parent`) ───────────────
# An Epic or grouping Feature is not work, but its tree is the best answer
# there is to "which stories belong in one pull request". These two functions
# are the decision half of that answer; `cmd_candidates --parent` does the
# reading. The rules were settled on #239.

def parent_leaf_groups(root, repo=None):
    """Walk a container's sub-issue tree and group its open leaves.

    `root` is `{'number', 'type', 'state', 'repo', 'children': [...]}`,
    nested. A leaf is an open descendant that is not a container. Each leaf is
    grouped under its nearest `Feature` ancestor, or under the root itself when
    it hangs directly off it.

    Returns (groups, empty, foreign). `groups` maps a group number to its
    leaves in tree order. `empty` lists the open Features with no open leaf
    under them: building a whole Feature as one story is the oversized unit
    the tree exists to prevent. `foreign` lists open descendants in another
    repository, which this repository's board and claims cannot speak for.
    """
    groups, empty, foreign = {}, [], []

    def walk(node, group):
        found = False
        for child in node.get('children') or ():
            if (child.get('state') or '').upper() != 'OPEN':
                continue
            if repo and child.get('repo') and child['repo'] != repo:
                foreign.append(child['number'])
                continue
            kind = child.get('type')
            if kind in HIERARCHY_CONTAINER_TYPES:
                inner = child['number'] if kind == 'Feature' else group
                if walk(child, inner):
                    found = True
                elif kind == 'Feature' and not child.get('unread'):
                    # A Feature whose stories were past the tree read is
                    # not empty; the caller reports it as unread instead.
                    empty.append(child['number'])
                continue
            groups.setdefault(group, []).append(child['number'])
            found = True
        return found

    walk(root, root['number'])
    return groups, empty, foreign


def choose_parent_set(root, pool_order, deps, reasons=None, max_size=BULK_MAX,
                      repo=None):
    """Choose one bulk set from the leaves under an Epic or Feature.

    `pool_order` is every leaf a run could take, in priority order: the pool
    -- Backlog, owned by the code agent, unassigned -- with the Blocked
    leaves the code agent owns ranked in among it, so a waiting leaf keeps
    its priority. `deps` maps each of them to its **open** blockers.
    `reasons` is the caller's explanation for any other leaf: its stage, its
    owner. Nothing else is ever taken, so Non-code work never is.

    - **One group per run.** The Feature (or the root, for leaves hanging off
      it directly) holding the highest-priority pool leaf with no open
      blocker. A group is one deliverable surface; leaves from two are the
      unrelated bundle bulk-execute exists to avoid.
    - **A leaf with open blockers is taken only when every one of them is
      taken too.** That is the only way a Blocked leaf gets in: its blocker is
      a sibling being built in the same run.
    - **Put in build order, then cut to `max_size`.** The order is greedy:
      the next leaf is always the highest-priority one whose blockers are
      already placed, so a waiting leaf keeps its priority and every prefix
      carries its own blockers. The set only comes back short when the tree
      is short.

    Returns {'group', 'selected', 'excluded'}: `selected` is story dicts in
    build order, each carrying `blocked_by`; `excluded` is every other leaf
    as {'number', 'reason'}.
    """
    reasons = reasons or {}
    groups, empty, foreign = parent_leaf_groups(root, repo)
    order = [leaf for leaves in groups.values() for leaf in leaves]
    group_of = {leaf: g for g, leaves in groups.items() for leaf in leaves}
    in_pool = [n for n in pool_order if n in group_of]
    takeable = in_pool + [n for n in deps if n in group_of and n not in in_pool]
    ready = [n for n in in_pool if not deps.get(n)]
    group = group_of[ready[0]] if ready else None

    kept, trimmed = [], set()
    if group is not None:
        members = [n for n in takeable if group_of[n] == group]
        chosen = {n for n in members if not deps.get(n)}
        grew = True
        while grew:
            grew = False
            for n in members:
                if n not in chosen and set(deps.get(n) or ()) <= chosen:
                    chosen.add(n)
                    grew = True
        stories = [{'number': n, 'blocked_by': list(deps.get(n) or ())}
                   for n in members if n in chosen]
        # Greedy, not `plan_bulk_order`'s rounds: a round puts every ready
        # leaf ahead of any leaf waiting on one, whatever their priority, so
        # the cut would take a higher-priority dependent before a ready leaf
        # below it. Every blocker of a chosen leaf was chosen before it, so
        # there is always a next one, and every prefix carries its blockers.
        ordered, placed, remaining = [], set(), list(stories)
        while remaining:
            story = next(s for s in remaining if set(s['blocked_by']) <= placed)
            ordered.append(story)
            placed.add(story['number'])
            remaining.remove(story)
        cap = max_size if max_size and max_size > 0 else len(ordered)
        kept = ordered[:cap]
        trimmed = {s['number'] for s in ordered[cap:]}

    selected = {s['number'] for s in kept}
    excluded = []
    for n in order:
        if n in selected:
            continue
        if n in trimmed:
            reason = ('left out by --size; the stories ahead of it in priority '
                      'and build order were kept')
        elif group is not None and group_of[n] != group and n in takeable:
            reason = 'under #%d, not the Feature this run takes' % group_of[n]
        elif deps.get(n):
            reason = 'blocked by %s, which this run is not building' % ', '.join(
                '#%d' % d for d in deps[n])
        else:
            reason = reasons.get(n, 'not in the pool')
        excluded.append({'number': n, 'reason': reason})
    excluded += [{'number': n, 'reason': 'a Feature with no open stories yet'}
                 for n in empty]
    excluded += [{'number': n, 'reason': 'in another repository'}
                 for n in foreign]
    return {'group': group, 'selected': kept, 'excluded': excluded}
