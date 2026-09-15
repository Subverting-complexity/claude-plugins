"""
Building a bulk set's waves: `bulk-schedule` decides which stories in a wave
may be built in parallel, and `bulk-integrate` brings the parallel builders'
temporary branches onto the shared branch.

Both used to be steps Claude carried out by hand from the skill: judging from
the plan whether stories share files, then fetching, cherry-picking, aborting,
pushing, marking and deleting once per story. The judgement is
`wf_core.schedule_waves`; the git sequence is here, so it runs the same way
every time and a conflict leaves the tree exactly as it was.
`scripts/README.md` has the module map.
"""

import json
import os
import tempfile

import wf_core
from wf_config import repo_root
from wf_io import EXIT_ENV, EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, emit, run
from wf_plan import BULK_SET, _load_set, _set_path


PLAN_FILE = os.path.join('.claude', 'plan.md')


def _write_set_atomic(record):
    """Write the bulk set through a temporary file and `os.replace`.

    A run interrupted mid-write would otherwise leave half a JSON file, and
    every later bulk command refuses a set it cannot parse.
    """
    path = _set_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.bulk-set-', suffix='.json', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(record, fh, indent=2)
            fh.write('\n')
        os.replace(temp, path)
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise


def cmd_bulk_schedule(args):
    """`wf bulk-schedule`: each wave's parallel batches, from the plan's files.

    No network. A missing plan is not an error: every story is then
    unplanned, which schedules each wave one story at a time.
    """
    record = _load_set()
    try:
        with open(os.path.join(repo_root(), PLAN_FILE), encoding='utf-8') as fh:
            plan_text = fh.read()
        plan_found = True
    except OSError:
        plan_text, plan_found = '', False
    plan = wf_core.parse_plan(plan_text)
    waves, built = wf_core.set_waves(record)
    out, next_wave, shared = wf_core.schedule_waves(
        waves, plan['stories'], plan['shared'], built)
    record['schedule'] = {'waves': out, 'next_wave': next_wave, 'shared': shared}
    _write_set_atomic(record)
    if next_wave is None:
        reason = 'every story in the set is built'
    else:
        wave = out[next_wave]
        reason = 'wave %d: %d stor%s in %d batch%s%s' % (
            next_wave, len(wave['stories']),
            'y' if len(wave['stories']) == 1 else 'ies', len(wave['batches']),
            '' if len(wave['batches']) == 1 else 'es',
            ', parallel' if wave['parallel'] else ', serial')
    emit('ok', EXIT_OK, waves=out, next_wave=next_wave, shared=shared,
         plan_found=plan_found, reason=reason)


def _git(root, *args):
    return run(['git', '-C', root] + list(args))


def _detail(out, err):
    return ((err or '').strip() or (out or '').strip())[-600:]


def cmd_bulk_integrate(args):
    """`wf bulk-integrate --wave K`: cherry-pick each builder's branch onto
    the shared branch, push once, then mark and delete what landed.

    Each story is taken in build order. Its commits are the ones on its
    temporary branch that are not already on HEAD, found through the merge
    base (`HEAD...tip`, right side only) rather than `origin/{branch}`:
    earlier stories in this wave have moved HEAD on since the builder
    branched. A failed cherry-pick is aborted, which returns HEAD and the
    tree to where they were, and the story stays unbuilt for a serial
    rebuild. Nothing is marked built until the push has landed, so the bulk
    set never claims a story the remote does not hold.
    """
    record = _load_set()
    branch = record.get('branch')
    if not branch:
        emit('usage', EXIT_USAGE,
             reason='no shared branch is recorded; run bulk-mark --branch first')
    waves, built = wf_core.set_waves(record)
    if not 0 <= args.wave < len(waves):
        emit('usage', EXIT_USAGE, reason='the set has no wave %d (it has %d)'
                                         % (args.wave, len(waves)))
    root = repo_root()

    code, out, err = _git(root, 'rev-parse', '--abbrev-ref', 'HEAD')
    if code != 0:
        emit('error', EXIT_ENV, reason='could not read the current branch (%s)'
                                       % _detail(out, err))
    if out.strip() != branch:
        emit('usage', EXIT_USAGE,
             reason='check out %s first; the current branch is %s'
                    % (branch, out.strip()))
    code, out, err = _git(root, 'status', '--porcelain', '--untracked-files=no')
    if code != 0:
        emit('error', EXIT_ENV, reason='could not read the working tree (%s)'
                                       % _detail(out, err))
    if out.strip():
        emit('usage', EXIT_USAGE,
             reason='the working tree has uncommitted changes to tracked files; '
                    'commit or discard them before integrating')

    integrated, conflicted, missing, empty = [], [], [], []
    state = {'integrated': integrated, 'conflicted': conflicted,
             'missing': missing, 'empty': empty}

    def fail(reason):
        emit('error', EXIT_ENV, pushed=False, branches_deleted=[],
             remaining=[s['number'] for s in record.get('stories') or ()
                        if not s.get('built')], reason=reason, **state)

    for number in [n for n in waves[args.wave] if n not in built]:
        temp = '%s--%d' % (branch, number)
        code, out, err = _git(root, 'fetch', 'origin', 'refs/heads/%s' % temp)
        if code != 0:
            missing.append({'number': number, 'branch': temp,
                            'detail': _detail(out, err)})
            continue
        code, out, err = _git(root, 'rev-parse', 'FETCH_HEAD')
        if code != 0:
            fail('could not read the fetched tip of %s (%s)' % (temp, _detail(out, err)))
        tip = out.strip()
        code, out, err = _git(root, 'rev-list', '--reverse', '--no-merges',
                              '--right-only', '--cherry-pick', 'HEAD...%s' % tip)
        if code != 0:
            conflicted.append({'number': number, 'branch': temp,
                               'detail': 'no history shared with %s (%s)'
                                         % (branch, _detail(out, err))})
            continue
        commits = out.split()
        if not commits:
            code, out, _ = _git(root, 'rev-list', '--no-merges', 'HEAD..%s' % tip)
            if code == 0 and out.split():
                # Every commit is already on HEAD (an earlier run picked it
                # but did not push): it landed, so it is integrated.
                integrated.append({'number': number, 'branch': temp, 'commits': []})
            else:
                empty.append({'number': number, 'branch': temp})
            continue
        code, before, err = _git(root, 'rev-parse', 'HEAD')
        if code != 0:
            fail('could not read HEAD (%s)' % _detail(before, err))
        code, out, err = _git(root, 'cherry-pick', *commits)
        if code == 0:
            integrated.append({'number': number, 'branch': temp, 'commits': commits})
            continue
        detail = _detail(out, err)
        acode, aout, aerr = _git(root, 'cherry-pick', '--abort')
        _, after, _ = _git(root, 'rev-parse', 'HEAD')
        if acode != 0 or after.strip() != before.strip():
            fail('the cherry-pick of %s failed and could not be aborted cleanly '
                 '(%s; abort: %s). Resolve the repository by hand.'
                 % (temp, detail, _detail(aout, aerr)))
        conflicted.append({'number': number, 'branch': temp, 'detail': detail})

    pushed, push_error, deleted, delete_error = False, None, [], None
    if integrated:
        code, out, err = _git(root, 'push', 'origin', branch)
        pushed = code == 0
        if not pushed:
            push_error = _detail(out, err)
    if pushed:
        record = _load_set()
        landed = {e['number'] for e in integrated}
        for story in record.get('stories') or ():
            if story['number'] in landed:
                story['built'] = True
        _write_set_atomic(record)
        if not args.keep_branches:
            names = [e['branch'] for e in integrated]
            code, out, err = _git(root, 'push', 'origin', '--delete', *names)
            if code == 0:
                deleted = names
            else:
                delete_error = _detail(out, err)

    remaining = [s['number'] for s in record.get('stories') or () if not s.get('built')]
    payload = dict(state, pushed=pushed, branches_deleted=deleted,
                   remaining=remaining, wave=args.wave, branch=branch,
                   bulk_set=BULK_SET.replace(os.sep, '/'))
    if push_error:
        payload['push_error'] = push_error
    if delete_error:
        payload['delete_error'] = delete_error
    if integrated and not pushed:
        emit('error', EXIT_ENV, reason='integrated %d stor%s but the push of %s '
                                       'failed; nothing was marked built'
                                       % (len(integrated),
                                          'y' if len(integrated) == 1 else 'ies',
                                          branch), **payload)
    if conflicted or missing or empty:
        emit('partial', EXIT_PARTIAL,
             reason='%d integrated, %d conflicted, %d missing, %d empty; rebuild '
                    'the rest serially' % (len(integrated), len(conflicted),
                                           len(missing), len(empty)), **payload)
    emit('ok', EXIT_OK, reason='integrated %d stor%s from wave %d'
                               % (len(integrated),
                                  'y' if len(integrated) == 1 else 'ies',
                                  args.wave), **payload)
