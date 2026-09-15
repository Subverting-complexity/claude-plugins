"""
Bulk sets: ordering a set of stories and choosing one from a container.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

from wf_core_select import HIERARCHY_CONTAINER_TYPES


# ── Bulk set planning (bulk-execute) ─────────────────────────────────────────
# `bulk-execute` builds two to seven connected stories on one branch behind
# one pull request. Its decisions are pure enough to live here rather than in
# prose: which dependencies still block a story that is being built alongside
# its own dependency, which stories are connected at all, and what order and
# which parallel waves the set has to be built in.

BULK_MIN = 2
BULK_MAX = 7


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


# ── a connected set, dependencies first (`plan-set`) ─────────────────────────
# The rules that decide which stories are one change and in what order, for
# every way a set is chosen: named stories, the open pool, and `execute`
# asking what a blocked story is waiting on. Two stories are connected when a
# blocked-by edge joins them, directly or through a shared prerequisite, or
# when they share a parent. A dependency never removes a story from a set; it
# decides where in the order the story goes. Only a blocker this run cannot
# build does, because then nothing in the set can finish the story.


def dependency_waves(stories):
    """Group a set already in build order into waves that can run in parallel.

    `stories` carry `number` and `blocked_by` (blockers inside the set). A
    story's wave is one more than the latest wave of anything it waits on, so
    every story in a wave depends only on earlier waves and the stories inside
    one wave are independent of each other. Returns a list of number lists.
    """
    present = {s['number'] for s in stories}
    level = {}
    for story in stories:
        inside = [b for b in story.get('blocked_by') or () if b in present]
        level[story['number']] = 1 + max((level.get(b, 0) for b in inside),
                                         default=-1)
    waves = []
    for story in stories:
        index = level[story['number']]
        while len(waves) <= index:
            waves.append([])
        waves[index].append(story['number'])
    return waves


def plan_set(universe, rank, seeds=None, max_size=BULK_MAX, reasons=None,
             within=None):
    """Choose a connected set of stories and the order and waves to build it in.

    `universe` is every story a run could take, `{number: {'blockers': [open
    blocker numbers] or None when the edges could not all be read, 'parent':
    number or None}}`. A story with no open blocker is ready; one with open
    blockers waits, and it is still takeable when every blocker is takeable
    too. `rank` is the universe in priority order. `reasons` explains any
    other open issue (`{number: why it cannot be taken}`), so a blocker or a
    named story outside the universe is excluded with the reason it is out.

    - **Named** (`seeds`): each named story plus every prerequisite it needs
      that this run can build, even one nobody named. A named story waiting on
      something the run cannot build is excluded. Nothing else is added.
    - **Open** (no seeds): the lead is the highest-ranked story whose whole
      prerequisite chain fits in `max_size`, ready or waiting, so a
      high-priority story pulls in the lower-priority issue that blocks it
      instead of being passed over. The rest of the lead's connected group
      joins in priority order while it fits, each with its own chain.

    Returns `{'lead', 'selected', 'waves', 'excluded', 'components',
    'unrelated'}`. `selected` is in build order: a story always follows every
    story it waits on, and otherwise keeps priority (or named) order. Each
    entry carries `number`, `wave`, `blocked_by` and `unblocks` (inside the
    set) and `why`. `components` groups the set by connection, and `unrelated`
    is True when a named set falls into more than one group.

    `within`, in open mode, limits which stories may lead or join the set, as
    `--parent` does to the stories under one container. A prerequisite outside
    it is still built when a story inside needs it.
    """
    reasons = reasons or {}
    rank_index = {n: i for i, n in enumerate(rank)}
    seeds = [int(s) for s in (seeds or ())]
    cap = max_size if max_size and max_size > 0 else None
    excluded = {}
    verdicts = {}

    def cannot_build(n, trail=()):
        """Why `n` cannot be built by this run, or None when it can."""
        if n in verdicts:
            return verdicts[n]
        if n in trail:
            return 'a dependency cycle runs through it (%s)' % ' -> '.join(
                '#%d' % t for t in trail + (n,))
        if n not in universe:
            verdicts[n] = reasons.get(n) or 'not open, or not an issue this run may take'
            return verdicts[n]
        blockers = universe[n].get('blockers')
        why = None
        if blockers is None:
            why = 'its blocked-by edges could not all be read'
        else:
            for b in blockers:
                inner = cannot_build(b, trail + (n,))
                if inner:
                    why = 'waits on #%d, which this run cannot build: %s' % (b, inner)
                    break
        verdicts[n] = why
        return why

    def chain(n, out=None):
        """`n` and every prerequisite under it, blockers first."""
        out = [] if out is None else out
        for b in universe[n].get('blockers') or ():
            if b not in out:
                chain(b, out)
        if n not in out:
            out.append(n)
        return out

    chosen, why = [], {}

    def take(n, reason):
        needed = [c for c in chain(n) if c not in chosen]
        if cap is not None and len(chosen) + len(needed) > cap:
            return False
        for c in needed:
            chosen.append(c)
            why.setdefault(c, reason if c == n else 'prerequisite of #%d' % n)
        return True

    lead = None
    if seeds:
        for s in seeds:
            reason = cannot_build(s)
            if reason:
                excluded[s] = reason
            elif s not in chosen and not take(s, 'named'):
                excluded[s] = ('left out by the size cap: it and its prerequisites '
                               'do not fit beside the stories named before it')
    else:
        ordered_rank = sorted((n for n in universe if within is None or n in within),
                              key=lambda n: rank_index.get(n, len(rank)))
        for n in ordered_rank:
            if cannot_build(n) is None and (cap is None or len(chain(n)) <= cap):
                lead = n
                break
        if lead is not None:
            take(lead, 'lead')
            group = _connected(universe, lead, lambda n: cannot_build(n) is None)
            for n in ordered_rank:
                if n in group and n not in chosen:
                    take(n, _link_reason(universe, n, chosen))
        for n in ordered_rank:
            if n not in chosen:
                reason = cannot_build(n)
                if reason:
                    excluded[n] = reason

    order_key = {s: i for i, s in enumerate(seeds)} if seeds else rank_index
    placed, ordered = set(), []
    remaining = sorted(chosen, key=lambda n: (order_key.get(n, len(order_key)),
                                              rank_index.get(n, len(rank))))
    while remaining:
        nxt = next(n for n in remaining
                   if set(universe[n].get('blockers') or ()) <= placed)
        ordered.append(nxt)
        placed.add(nxt)
        remaining.remove(nxt)

    stories = []
    for n in ordered:
        stories.append({
            'number': n,
            'blocked_by': list(universe[n].get('blockers') or ()),
            'unblocks': [m for m in ordered
                         if n in (universe[m].get('blockers') or ())],
            'why': why.get(n, 'named')})
    waves = dependency_waves(stories)
    wave_of = {n: i for i, wave in enumerate(waves) for n in wave}
    for story in stories:
        story['wave'] = wave_of[story['number']]

    components = _components(universe, ordered)
    return {'lead': ordered[0] if ordered else None, 'selected': stories,
            'waves': waves,
            'excluded': [{'number': n, 'reason': r}
                         for n, r in sorted(excluded.items())],
            'components': components,
            'unrelated': bool(seeds) and len(components) > 1}


def _linked(universe, n, m):
    """Whether a direct link joins two stories: an edge, a shared
    prerequisite, or a shared parent."""
    mine, other = universe[n], universe[m]
    mine_b, other_b = set(mine.get('blockers') or ()), set(other.get('blockers') or ())
    return bool(m in mine_b or n in other_b or mine_b & other_b
                or (mine.get('parent') and mine.get('parent') == other.get('parent')))


def _connected(universe, start, allowed):
    """Every story reachable from `start` through links, within `allowed`."""
    members = [n for n in universe if n == start or allowed(n)]
    seen, frontier = {start}, [start]
    while frontier:
        n = frontier.pop()
        for m in members:
            if m not in seen and _linked(universe, n, m):
                seen.add(m)
                frontier.append(m)
    return seen


def _components(universe, numbers):
    """The set split into groups joined by links, in build order."""
    left, groups = list(numbers), []
    while left:
        group = _connected(universe, left[0], lambda n: n in numbers)
        groups.append([n for n in numbers if n in group])
        left = [n for n in left if n not in group]
    return groups


def _link_reason(universe, n, chosen):
    """Why `n` belongs beside the stories already chosen, in words."""
    mine = universe[n]
    for m in chosen:
        if m in (mine.get('blockers') or ()):
            return 'depends on #%d' % m
        if n in (universe[m].get('blockers') or ()):
            return 'prerequisite of #%d' % m
    for m in chosen:
        other = universe[m]
        shared = set(mine.get('blockers') or ()) & set(other.get('blockers') or ())
        if shared:
            return 'shares prerequisite #%d with #%d' % (min(shared), m)
        if mine.get('parent') and mine.get('parent') == other.get('parent'):
            return 'same parent (#%d) as #%d' % (mine['parent'], m)
    return 'connected to the set'
