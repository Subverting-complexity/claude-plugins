"""
Bulk sets: ordering a set of stories and choosing one from a container.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""

from wf_core_refs import ref_label, ref_sort_key
from wf_core_select import HIERARCHY_CONTAINER_TYPES


# ── Bulk set planning (bulk-execute) ─────────────────────────────────────────
# `bulk-execute` builds two to seven connected stories on one branch behind
# one pull request. Its decisions are pure enough to live here rather than in
# prose: which dependencies still block a story that is being built alongside
# its own dependency, which stories are connected at all, and what order and
# which parallel waves the set has to be built in.

BULK_MIN = 2
BULK_MAX = 7


def _as_ref(n):
    """A blocker reference as one comparable value: a local number as an int,
    whether it came as an int or a digit string, and a foreign
    `'owner/name#N'` as it stands."""
    if isinstance(n, str) and n.strip().isdigit():
        return int(n)
    return n


def blocking_dependencies(deps, open_numbers, siblings=()):
    """Return the dependencies that genuinely block a story.

    A dependency blocks when it is still **open** and is **not** being built
    alongside this story. That sibling carve-out is the whole reason a bulk
    run can take a dependency chain: `execute`'s rule is "do not build on
    unmerged work you cannot see", and a story landing in the same commit
    series on the same branch is work you can see. Anything open and outside
    the set still blocks, exactly as it does for a single-story run.

    `deps` are the blocker references, `open_numbers` those of them the caller
    found still open, and `siblings` the rest of the bulk set. A reference to
    another repository (`'owner/name#N'`) is never a sibling, so it blocks
    while it is open. Returns the blocking references in the order they
    appear in `deps`.
    """
    open_set = {_as_ref(n) for n in (open_numbers or ())}
    sib = {_as_ref(n) for n in (siblings or ())}
    return [d for d in deps if _as_ref(d) in open_set and _as_ref(d) not in sib]


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
        edges = [_as_ref(d) for d in (story.get('blocked_by') or ())]
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


# ── the leaves under a container (`candidates --parent`, `plan-set --parent`) ─
# An Epic or grouping Feature is not work, but its tree is the best answer
# there is to "which stories belong in one pull request". This walk finds the
# stories under one; `plan_set(within=)` chooses among them by the same rules
# as every other set. The grouping rules were settled on #239.

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


# ── a connected set, dependencies first (`plan-set`) ─────────────────────────
# The rules that decide which stories are one change and in what order, for
# every way a set is chosen: named stories, the open pool, the stories under a
# container, and `execute` asking what a blocked story is waiting on. Two
# stories are related when a blocked-by edge joins them in either direction,
# when they share a prerequisite, when they share a parent, or when they sit
# under the same Epic. A dependency never removes a story from a set; it
# decides where in the order the story goes. Only a blocker this run cannot
# build does, because then nothing in the set can finish the story.

# How closely two stories are related, closest first. A set grows through the
# closest link it has, so an Epic's cousins join only once the stories joined
# by an edge or a parent are in.
LINK_EDGE = 0
LINK_PARENT = 1
LINK_EPIC = 2


def dependency_waves(stories):
    """Group a set into waves that can run in parallel.

    `stories` carry `number` and `blocked_by`; a blocker outside the set is
    ignored. A story's wave is one more than the latest wave of anything it
    waits on, so every story in a wave depends only on earlier waves and the
    stories inside one wave are independent of each other. The waves are
    topological levels, so they do not depend on the order `stories` came
    in; inside a wave the input order is kept. Stories caught in a cycle
    cannot be levelled and share one final wave. Returns number lists.
    """
    order = []
    for story in stories:
        if story['number'] not in order:
            order.append(story['number'])
    present = set(order)
    inside = {}
    for story in stories:
        n = story['number']
        inside.setdefault(n, set()).update(
            b for b in (_as_ref(b) for b in story.get('blocked_by') or ())
            if b in present and b != n)
    waves, placed, remaining = [], set(), order
    while remaining:
        wave = [n for n in remaining if inside[n] <= placed]
        if not wave:
            waves.append(list(remaining))
            break
        waves.append(wave)
        placed.update(wave)
        remaining = [n for n in remaining if n not in placed]
    return waves


def plan_set(universe, rank, seeds=None, max_size=BULK_MAX, reasons=None,
             within=None):
    """Choose a connected set of stories and the order and waves to build it in.

    `universe` is every story a run could take, `{number: {'blockers': [open
    blocker references] or None when the edges could not all be read,
    'parent': number or None, 'epic': number or None}}`. A local blocker is an
    issue number; one in another repository is `'owner/name#N'`, which this
    run can never build. A story with no open blocker is ready; one with open
    blockers waits, and it is still takeable when every blocker is takeable
    too. `rank` is the universe in priority order. `reasons` explains any
    other open issue (`{number: why it cannot be taken}`), so a blocker or a
    named story outside the universe is excluded with the reason it is out.

    - **Named** (`seeds`): each named story plus every prerequisite it needs
      that this run can build, even one nobody named. A named story waiting on
      something the run cannot build is excluded. Nothing else is added.
    - **Open** (no seeds): the takeable stories split into related groups,
      each ranked by its best story. A group's lead is its highest-ranked
      story whose whole prerequisite chain fits in `max_size`, ready or
      waiting, so a high-priority story pulls in the lower-priority issue that
      blocks it instead of being passed over. The group then grows through its
      closest links first (an edge or a shared prerequisite, then a shared
      parent, then the same Epic), by rank within a tier, each story with its
      whole chain or not at all. The set is the best-ranked group that comes
      to at least `BULK_MIN` stories; only when none does is it the single
      best story. Group members the cap left out are excluded and say so.

    Returns `{'lead', 'selected', 'waves', 'excluded', 'components',
    'unrelated'}`. `selected` is in build order: a story always follows every
    story it waits on, and otherwise keeps priority (or named) order. Each
    entry carries `number`, `wave`, `blocked_by` and `unblocks` (inside the
    set) and `why`. `components` groups the set by relation, and `unrelated`
    is True when a named set falls into more than one group.

    `within`, in open mode, limits which stories may lead or join the set, as
    `--parent` does to the stories under one container. A prerequisite outside
    it is still built when a story inside needs it, and its `why` says so.
    """
    reasons = reasons or {}
    rank_index = {n: i for i, n in enumerate(rank)}
    seeds = [int(s) for s in (seeds or ())]
    cap = max_size if max_size and max_size > 0 else None
    excluded = {}
    verdicts = {}

    def position(n):
        return rank_index.get(n, len(rank))

    def cannot_build(n, trail=()):
        """Why `n` cannot be built by this run, or None when it can."""
        if not isinstance(n, int):
            return 'it is in another repository, which this run cannot build'
        if n in verdicts:
            return verdicts[n]
        if n in trail:
            return 'a dependency cycle runs through it (%s)' % ' -> '.join(
                ref_label(t) for t in trail + (n,))
        if n not in universe:
            verdicts[n] = reasons.get(n) or 'not open, or not an issue this run may take'
            return verdicts[n]
        blockers = universe[n].get('blockers')
        why = None
        if blockers is None:
            why = ('its dependencies could not all be read, so whether it '
                   'waits on anything is unknown')
        else:
            for b in blockers:
                inner = cannot_build(b, trail + (n,))
                if inner and not isinstance(b, int):
                    why = 'waits on %s, in another repository, which this run cannot build' % b
                    break
                if inner:
                    why = 'waits on %s, which this run cannot build: %s' % (ref_label(b), inner)
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

    def take(chosen, why, n, reason):
        needed = [c for c in chain(n) if c not in chosen]
        if cap is not None and len(chosen) + len(needed) > cap:
            return False
        for c in needed:
            chosen.append(c)
            why.setdefault(c, reason if c == n else 'prerequisite of #%d' % n)
        return True

    chosen, why = [], {}
    if seeds:
        for s in seeds:
            reason = cannot_build(s)
            if reason:
                excluded[s] = reason
            elif s not in chosen and not take(chosen, why, s, 'named'):
                excluded[s] = ('left out by the size cap: it and its prerequisites '
                               'do not fit beside the stories named before it')
    else:
        ordered_rank = sorted((n for n in universe if within is None or n in within),
                              key=position)
        joinable = [n for n in ordered_rank if cannot_build(n) is None]
        chosen, why, group = _best_group(universe, joinable, chain, take, cap,
                                         position)
        for n in ordered_rank:
            if n in chosen:
                continue
            reason = cannot_build(n)
            if reason:
                excluded[n] = reason
            elif n in group:
                excluded[n] = ('related to the set, but left out by the size cap: '
                               'it and its prerequisites do not fit')

    order_key = {s: i for i, s in enumerate(seeds)} if seeds else rank_index
    placed, ordered = set(), []
    remaining = sorted(chosen, key=lambda n: (order_key.get(n, len(order_key)),
                                              position(n)))
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


def _best_group(universe, joinable, chain, take, cap, position):
    """Open mode's choice: (chosen, why, group) for the best-ranked related
    group that makes a set of at least `BULK_MIN`, else for the single best
    story. `group` is every joinable story in the group the set came from.

    The groups are drawn over the joinable stories and every prerequisite
    their chains pull in, so two stories joined only through a prerequisite
    outside `within` are still one group; only a joinable story may lead or
    join on its own account.
    """
    nodes = list(joinable)
    for n in joinable:
        nodes.extend(c for c in chain(n) if c not in nodes)
    groups, left = [], list(nodes)
    while left:
        members = _connected(universe, left[0], lambda n: n in nodes)
        groups.append([n for n in joinable if n in members])
        left = [n for n in left if n not in members]
    groups = sorted((g for g in groups if g), key=lambda g: position(g[0]))

    fallback = None
    for group in groups:
        chosen, why = [], {}
        lead = next((n for n in group if cap is None or len(chain(n)) <= cap), None)
        if lead is None:
            continue
        take(chosen, why, lead, 'lead')
        while True:
            best = None
            for n in group:
                if n in chosen:
                    continue
                needed = [c for c in chain(n) if c not in chosen]
                if cap is not None and len(chosen) + len(needed) > cap:
                    continue
                tiers = [t for c in needed for m in chosen
                         for t in (_link_tier(universe, c, m),) if t is not None]
                if not tiers:
                    continue
                key = (min(tiers), position(n))
                if best is None or key < best[0]:
                    best = (key, n, needed)
            if best is None:
                break
            _key, n, needed = best
            reason = _link_reason(universe, n, chosen + [c for c in needed if c != n])
            take(chosen, why, n, reason)
        if len(chosen) >= BULK_MIN:
            return chosen, why, set(group)
        if fallback is None:
            fallback = (chosen, why, set(group))
    return fallback or ([], {}, set())


def _link_tier(universe, n, m):
    """How closely a direct link joins two stories (`LINK_*`), or None: an
    edge either way or a shared prerequisite, a shared parent, the same Epic."""
    if n == m:
        return None
    mine, other = universe[n], universe[m]
    mine_b, other_b = set(mine.get('blockers') or ()), set(other.get('blockers') or ())
    if m in mine_b or n in other_b or mine_b & other_b:
        return LINK_EDGE
    if mine.get('parent') and mine.get('parent') == other.get('parent'):
        return LINK_PARENT
    if mine.get('epic') and mine.get('epic') == other.get('epic'):
        return LINK_EPIC
    return None


def _linked(universe, n, m):
    """Whether a direct link joins two stories: an edge, a shared
    prerequisite, a shared parent, or the same Epic."""
    return _link_tier(universe, n, m) is not None


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
            return 'shares prerequisite %s with #%d' % (
                ref_label(min(shared, key=ref_sort_key)), m)
    for m in chosen:
        if mine.get('parent') and mine.get('parent') == universe[m].get('parent'):
            return 'same parent (#%d) as #%d' % (mine['parent'], m)
    for m in chosen:
        if mine.get('epic') and mine.get('epic') == universe[m].get('epic'):
            return 'same Epic (#%d) as #%d' % (mine['epic'], m)
    return 'related to the set'
