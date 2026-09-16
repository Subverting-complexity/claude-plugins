"""
Bulk sets: filling an effort budget, splitting it into pull requests, and
ordering each one; choosing from a container.

`scripts/README.md` has the module map.
"""

from wf_core_fields import _priority_rank
from wf_core_refs import ref_label
from wf_core_select import HIERARCHY_CONTAINER_TYPES


# ── Bulk set planning (bulk-execute) ─────────────────────────────────────────
# `bulk-execute` builds a set of stories that fills an effort budget, as at
# most two pull requests built one after the other. Its decisions are pure
# enough to live here rather than in prose: which dependencies still block a
# story that is being built alongside its own dependency, which stories fit
# the budget together, how the set splits into pull requests, and what order
# and which parallel waves each one has to be built in.

# The most stories `pick` offers from one Epic or Feature, and the default
# trim of `plan_bulk_order`.
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
    `max_size`) or `'dependency-cycle'`. A set that shrinks to one story is a
    single-story run, not an error.
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


# ── a set that fills an effort budget, dependencies first (`plan-set`) ───────
# The rules that decide which stories are one run and in what order, for every
# way a set is chosen: named stories, the open pool, the stories under a
# container, and `execute` asking what a blocked story is waiting on. A set is
# filled by priority until its effort budget is spent, whether or not the
# stories are linked. A dependency never removes a story from a set on its own
# account; it decides where in the order the story goes, and the story comes
# with its whole prerequisite chain or not at all. Only a blocker this run
# cannot build excludes a story outright, because then nothing in the set can
# finish it.

# The effort a set may hold, and what each `Effort` value costs. A High story
# leaves room for one Low story and nothing larger. An issue with no `Effort`
# costs Medium, the same middle `_effort_rank` sorts it as: unestimated work is
# unknown rather than large.
BULK_BUDGET = 7
EFFORT_WEIGHTS = {'low': 1, 'medium': 2, 'high': 6}
EFFORT_WEIGHT_DEFAULT = EFFORT_WEIGHTS['medium']

# The most pull requests one set is split into. A run that cannot start a
# separate reviewer passes 1, because an inline review of a second pull
# request is what fills its context.
MAX_GROUPS = 2

# How far apart two stories' `Priority` may be and still share a set: the same
# level or the next one, so urgent work never waits behind low-priority work.
PRIORITY_BAND = 1


def effort_weight(value):
    """What an `Effort` value costs against `BULK_BUDGET`."""
    if not value:
        return EFFORT_WEIGHT_DEFAULT
    return EFFORT_WEIGHTS.get(str(value).strip().lower(), EFFORT_WEIGHT_DEFAULT)


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


def split_groups(stories, max_groups=MAX_GROUPS):
    """Split a set into the pull requests it becomes. (groups, reason).

    `stories` carry `number`, `mode` and `blocked_by`, in build order. The cut
    is on the work mode, because a pull request never mixes feature and
    maintenance work; stories of one mode stay together, so a set of one mode
    is one group. A group holding a prerequisite of another group's story goes
    first, since groups are built and merged one after another.

    `groups` is a list of {'mode', 'stories'} with the stories in their input
    order, or None when the set cannot be split: it needs more than
    `max_groups` groups (None for no limit), or two groups each wait on the
    other. `reason` says which, in words, and is None otherwise.
    """
    by_mode, modes = {}, []
    for story in stories:
        mode = story.get('mode') or 'feature'
        if mode not in by_mode:
            by_mode[mode] = []
            modes.append(mode)
        by_mode[mode].append(story)
    if max_groups is not None and len(modes) > max_groups:
        return None, ('it would put %s and %s work in one pull request, and this '
                      'run opens %s' % (modes[0], modes[1],
                                        'one pull request' if max_groups == 1
                                        else 'at most %d' % max_groups))
    mode_of = {s['number']: s.get('mode') or 'feature' for s in stories}
    after = {m: set() for m in modes}
    for story in stories:
        for b in story.get('blocked_by') or ():
            other = mode_of.get(_as_ref(b))
            if other is not None and other != mode_of[story['number']]:
                after[mode_of[story['number']]].add(other)
    ordered, placed, remaining = [], set(), list(modes)
    while remaining:
        ready = [m for m in remaining if after[m] <= placed]
        if not ready:
            return None, ('its %s and %s work each wait on the other, so neither '
                          'pull request can merge first' % (remaining[0], remaining[1]))
        ordered.append(ready[0])
        placed.add(ready[0])
        remaining.remove(ready[0])
    return [{'mode': m, 'stories': by_mode[m]} for m in ordered], None


def plan_set(universe, rank, seeds=None, budget=BULK_BUDGET, reasons=None,
             within=None, max_groups=MAX_GROUPS):
    """Choose a set of stories that fills an effort budget, and the pull
    requests, order and waves to build it in.

    `universe` is every story a run could take, `{number: {'blockers': [open
    blocker references] or None when the edges could not all be read,
    'parent', 'epic', 'effort', 'priority', 'mode'}}` (`wf_core.story_facts`
    fills the last three). A local blocker is an issue number; one in another
    repository is `'owner/name#N'`, which this run can never build. A story
    with no open blocker is ready; one with open blockers waits, and it is
    still takeable when every blocker is takeable too. `rank` is the universe
    in priority order. `reasons` explains any other open issue (`{number: why
    it cannot be taken}`), so a blocker or a named story outside the universe
    is excluded with the reason it is out.

    Every story is taken with its whole prerequisite chain or not at all, and
    only while the set still keeps three rules:

    - **Budget.** The `effort_weight` of every story, prerequisites included,
      adds up to no more than `budget`.
    - **Priority.** No two stories are more than `PRIORITY_BAND` levels of
      `Priority` apart, each read as the priority it carries.
    - **Groups.** `split_groups` can cut the set into at most `max_groups`
      pull requests, none of them mixing modes.

    - **Named** (`seeds`): each named story, in the order given, plus every
      prerequisite it needs. A named story that breaks a rule, or waits on
      something the run cannot build, is excluded with the reason.
    - **Open** (no seeds): the takeable stories in rank order, whether or not
      they are linked. A story that would start a second group is passed over
      until every story that joins a group already started has had its turn.
      Only a story that cannot be built is excluded; with `within` (the
      stories under one container), every story inside it the set did not
      take is excluded too, with the rule that kept it out.

    `budget` None turns the three rules off and gives one group per mode,
    for a caller that wants only the build order.

    Returns `{'lead', 'selected', 'groups', 'excluded', 'weight', 'budget'}`.
    `groups` is a list of {'group' (from 1), 'mode', 'lead', 'stories',
    'waves'}, in the order they are built. `selected` is every story, group
    by group, each in build order: a story always follows every story it
    waits on. Each entry carries `number`, `group`, `wave` (inside its group),
    `blocked_by` and `unblocks` (inside the set), `mode`, `weight` and `why`.
    `weight` is the set's total.
    """
    reasons = reasons or {}
    rank_index = {n: i for i, n in enumerate(rank)}
    seeds = [int(s) for s in (seeds or ())]
    limited = budget is not None
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

    def weight(n):
        return effort_weight(universe[n].get('effort'))

    def as_stories(numbers):
        return [{'number': n, 'mode': universe[n].get('mode') or 'feature',
                 'blocked_by': list(universe[n].get('blockers') or ())}
                for n in numbers]

    def groups_of(numbers):
        return split_groups(as_stories(numbers), max_groups if limited else None)

    def breaks_rule(numbers):
        """Which rule a candidate set breaks, in words, or None."""
        if not limited:
            return groups_of(numbers)[1]
        total = sum(weight(n) for n in numbers)
        if total > budget:
            return ('its Effort, with its prerequisites, takes the set to %d '
                    'against a budget of %d' % (total, budget))
        levels = [_priority_rank(universe[n].get('priority')) for n in numbers]
        if max(levels) - min(levels) > PRIORITY_BAND:
            return ('its Priority is more than one level from another story in '
                    'the set')
        return groups_of(numbers)[1]

    def take(chosen, why, n, reason):
        for c in chain(n):
            if c not in chosen:
                chosen.append(c)
                why.setdefault(c, reason if c == n else 'prerequisite of #%d' % n)

    chosen, why = [], {}
    if seeds:
        for s in seeds:
            reason = cannot_build(s)
            if reason:
                excluded[s] = reason
                continue
            if s in chosen:
                continue
            broken = breaks_rule(chosen + [c for c in chain(s) if c not in chosen])
            if broken:
                excluded[s] = 'left out: %s' % broken
            else:
                take(chosen, why, s, 'named')
    else:
        ordered_rank = sorted((n for n in universe if within is None or n in within),
                              key=position)
        joinable = [n for n in ordered_rank if cannot_build(n) is None]
        deferred, broken_by = [], {}
        for turn in (joinable, deferred):
            for n in list(turn):
                if n in chosen:
                    continue
                candidate = chosen + [c for c in chain(n) if c not in chosen]
                broken = breaks_rule(candidate)
                if broken:
                    broken_by[n] = broken
                    continue
                if turn is joinable and chosen and (
                        len(groups_of(candidate)[0]) > len(groups_of(chosen)[0])):
                    deferred.append(n)
                    continue
                broken_by.pop(n, None)
                take(chosen, why, n, 'lead' if not chosen else 'next by priority')
        for n in ordered_rank:
            if n in chosen:
                continue
            reason = cannot_build(n)
            if reason:
                excluded[n] = reason
            elif within is not None:
                excluded[n] = 'left out: %s' % (
                    breaks_rule(chosen + [c for c in chain(n) if c not in chosen])
                    or broken_by.get(n) or 'it did not fit beside the stories taken')

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

    groups = groups_of(ordered)[0] if ordered else []
    stories, group_out = [], []
    for index, group in enumerate(groups or (), start=1):
        numbers = [s['number'] for s in group['stories']]
        entries = [{'number': n, 'group': index, 'mode': group['mode'],
                    'weight': weight(n),
                    'blocked_by': list(universe[n].get('blockers') or ()),
                    'unblocks': [m for m in ordered
                                 if n in (universe[m].get('blockers') or ())],
                    'why': why.get(n, 'named')}
                   for n in numbers]
        waves = dependency_waves(entries)
        wave_of = {n: i for i, wave in enumerate(waves) for n in wave}
        for entry in entries:
            entry['wave'] = wave_of[entry['number']]
        stories.extend(entries)
        group_out.append({'group': index, 'mode': group['mode'], 'lead': numbers[0],
                          'stories': numbers, 'waves': waves})
    return {'lead': stories[0]['number'] if stories else None, 'selected': stories,
            'groups': group_out,
            'excluded': [{'number': n, 'reason': r}
                         for n, r in sorted(excluded.items())],
            'weight': sum(s['weight'] for s in stories), 'budget': budget}
