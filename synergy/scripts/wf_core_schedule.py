"""
Scheduling a bulk wave: which stories in it may be built at the same time.

Whether a wave is built serially or in parallel used to be a judgement read
off `.claude/plan.md`: do these stories share a file? It is decided here from
the files the plan lists under each story, so two stories that edit the same
file are never handed to parallel builders whose cherry-picks would then
conflict. `scripts/README.md` has the module map.
"""

import re


# A heading naming a story: `## Wave 0 — Story #41 — Resolve labels`. The
# first `#<number>` in it is the story; the wave number is informational,
# because the bulk set, not the plan, decides the waves.
_HEADING = re.compile(r'^(#{2,})\s+(.*?)\s*#*\s*$')
_STORY_REF = re.compile(r'(?<![\w&])#(\d+)\b')
_SHARED = re.compile(r'^shared\b', re.IGNORECASE)
_TASK = re.compile(r'^\s*[-*+]\s+\[[ xX]\]\s+(.*)$')
_PATH_CHARS = re.compile(r'^[\w.\-/@+~]+$')
_TRAILING = '.,;:)]}\'"'


def normalise_plan_path(text):
    """A plan path as one comparable spelling, or '' when nothing is left.

    The plan is written by a model, so one file arrives as `src/a.ts`,
    `./src/a.ts`, `src\\a.ts` or `src/a.ts,`. Two stories only overlap if the
    spellings agree, so every form is brought to forward slashes with no
    leading `./`, no backticks and no trailing punctuation.
    """
    path = (text or '').strip().strip('`').strip()
    path = path.replace('\\', '/')
    while path.startswith('./'):
        path = path[2:]
    path = path.rstrip(_TRAILING).strip('`')
    return path


def _item_path(rest):
    """The path a task item names first, or None when it names none.

    A backticked first token is taken as written, since the backticks say it
    is a path. A bare token counts only when it looks like one (holds a `/`
    or a `.`), so an item that opens with a word is not mistaken for a file.
    """
    rest = rest.strip()
    if rest.startswith('`'):
        end = rest.find('`', 1)
        if end > 1:
            path = normalise_plan_path(rest[1:end])
            return path or None
        return None
    token = rest.split(None, 1)[0] if rest else ''
    path = normalise_plan_path(token)
    if not path or not _PATH_CHARS.match(path) or not re.search(r'\w', path):
        return None
    if '/' not in path and '.' not in path:
        return None
    return path


def parse_plan(text):
    """Read `.claude/plan.md` into the files each story and the shared section list.

    Returns {'stories': {number: [path, ...]}, 'shared': [path, ...]}, each
    list in first-seen order without repeats. A level-2 heading holding
    `#<number>` starts that story's section and `## Shared` the shared one;
    any other level-2 heading ends the current section. A deeper heading with
    no story number stays inside the section it sits in, so a `### Tests`
    subheading does not orphan the items under it.
    """
    stories, shared = {}, []
    current = None
    for line in (text or '').splitlines():
        heading = _HEADING.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            ref = _STORY_REF.search(title)
            if ref:
                current = int(ref.group(1))
                stories.setdefault(current, [])
            elif level == 2:
                current = 'shared' if _SHARED.match(title) else None
            continue
        task = _TASK.match(line)
        if not task or current is None:
            continue
        path = _item_path(task.group(1))
        if not path:
            continue
        bucket = shared if current == 'shared' else stories[current]
        if path not in bucket:
            bucket.append(path)
    return {'stories': stories, 'shared': shared}


def grouped_record(record):
    """A bulk set record in its grouped form, as a new dict.

    A set is split into groups, each one pull request with its own `branch`
    and `waves`, and every story names its `group`. A record written before
    groups existed has one top-level `branch` and `waves`; it is read as a
    single group 1 holding every story, so a run already under way carries on.
    """
    record = dict(record or {})
    stories = [dict(s) for s in record.get('stories') or ()]
    groups = record.get('groups')
    if not groups:
        groups = [{'group': 1, 'mode': record.get('mode'), 'lead': record.get('lead'),
                   'branch': record.get('branch'), 'waves': record.get('waves')}]
    for story in stories:
        story.setdefault('group', 1)
    record.pop('branch', None)
    record.pop('waves', None)
    record.update(stories=stories, groups=[dict(g) for g in groups])
    return record


def set_waves(record, group=1):
    """The waves and built stories of one group of a bulk set record.

    Returns (waves, built): waves as lists of story numbers in build order,
    built as a set, both for `group` only. The group's `waves` is
    authoritative; a group without it is grouped by each story's `wave`, in
    the order the stories are listed.
    """
    record = grouped_record(record)
    stories = [s for s in record['stories'] if s['group'] == group]
    built = {s['number'] for s in stories if s.get('built')}
    known = {s['number'] for s in stories}
    waves = next((g.get('waves') for g in record['groups'] if g['group'] == group), None)
    if waves:
        return [[n for n in wave if n in known] for wave in waves], built
    grouped = {}
    for story in stories:
        grouped.setdefault(story.get('wave') or 0, []).append(story['number'])
    return [grouped[k] for k in sorted(grouped)], built


def schedule_waves(waves, files_by_story, shared=(), built=()):
    """Partition each wave's unbuilt stories into batches that can run together.

    `waves` is a list of story-number lists in build order; `files_by_story`
    maps a story to the files its plan section lists; `shared` is the plan's
    shared section; `built` the stories already on the branch, which are
    skipped.

    Two stories conflict when their files intersect outside the shared
    section, or when either lists no files at all: an unplanned story's
    overlap cannot be judged, so it is scheduled as if it touched everything.
    Shared files do not conflict, because the orchestrator writes them first,
    with the first story that needs them, before any batch runs in parallel.
    Batches are formed greedily in build order: each story joins the first
    batch holding nothing it conflicts with. Batches run one after another;
    the stories inside one run in parallel.

    Returns (waves_out, next_wave, shared_out). Each wave entry is
    {index, stories, batches, parallel, overlaps, unplanned}; `next_wave` is
    the first index with an unbuilt story, or None; `shared_out` lists each
    shared file with the stories, in build order, whose sections name it.
    """
    built = set(built or ())
    shared_list = []
    for path in shared or ():
        path = normalise_plan_path(path)
        if path and path not in shared_list:
            shared_list.append(path)
    shared_set = set(shared_list)
    own = {}
    for number, paths in (files_by_story or {}).items():
        own[number] = {normalise_plan_path(p) for p in paths or ()} - {''}

    out, next_wave = [], None
    for index, wave in enumerate(waves or ()):
        stories = [n for n in wave if n not in built]
        unplanned = [n for n in stories if not own.get(n)]
        private = {n: own.get(n, set()) - shared_set for n in stories}

        def conflicts(a, b):
            return (a in unplanned or b in unplanned
                    or bool(private[a] & private[b]))

        batches = []
        for n in stories:
            for batch in batches:
                if not any(conflicts(n, m) for m in batch):
                    batch.append(n)
                    break
            else:
                batches.append([n])

        holders = {}
        for n in stories:
            for path in sorted(private[n]):
                holders.setdefault(path, []).append(n)
        overlaps = [{'file': path, 'stories': holders[path]}
                    for path in sorted(holders) if len(holders[path]) > 1]
        out.append({'index': index, 'stories': stories, 'batches': batches,
                    'parallel': any(len(b) > 1 for b in batches),
                    'overlaps': overlaps, 'unplanned': unplanned})
        if next_wave is None and stories:
            next_wave = index

    order = [n for wave in waves or () for n in wave]
    shared_out = [{'file': path,
                   'stories': [n for n in order if path in own.get(n, ())]}
                  for path in shared_list]
    return out, next_wave, shared_out
