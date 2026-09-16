"""
The `issue-apply` subcommand: create and update fully classified issues from a
spec.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import json
import os
import tempfile

import wf_core
from wf_candidates import fetch_issue_facets
from wf_capabilities import resolve_org_capabilities
from wf_config import field_name, label, load_config
from wf_deps import issue_edges_map
from wf_io import (
    EXIT_CAPABILITY, EXIT_ENV, EXIT_OK, EXIT_PARTIAL, EXIT_SPEC, EXIT_VERIFY,
    emit, eprint, run,
)
from wf_issue_io import (
    _values_match, add_sub_issue, issue_field_values, issue_mismatches,
    read_issue, resolve_issue_ids, resolve_spec_context, send_create_batch,
    send_link_batch, set_issue_fields, set_issue_type, verify_issue,
)
from wf_stage import NO_STAGE_FIELD, set_stages


def load_spec(path):
    """Read a spec file. Returns (ok, entries, raw, err)."""
    if not os.path.isfile(path):
        return False, None, None, 'no spec file at %s' % path
    try:
        with open(path, encoding='utf-8') as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return False, None, None, 'could not read spec: %s' % exc
    entries = raw.get('issues') if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return False, None, None, "spec must be a list, or an object with an 'issues' list"
    return True, entries, raw, ''


def entry_body(entry):
    """The entry's body, from `body` or from the file `body_file` names.

    A body is prose: fenced code, backticks, `$`, quotes and blank lines. The
    caller writing it to a file and naming the file is what keeps it intact,
    because building the JSON string by hand in a shell is where bodies get
    mangled. Read here rather than at load time so the spec file written back
    afterwards still says `body_file`, not a thousand inlined characters.

    Returns (body, err).
    """
    if entry.get('body') is not None:
        return entry['body'], ''
    path = entry.get('body_file')
    if not path:
        return None, ''
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read(), ''
    except OSError as exc:
        return None, 'could not read body_file %s: %s' % (path, exc)


def spec_body_errors(entries):
    """Every `body_file` that cannot be read, before anything is written."""
    out = []
    for entry in entries:
        _, err = entry_body(entry)
        if err:
            out.append('%s: %s' % (wf_core.entry_label(entry), err))
    return out


def write_back_numbers(path, raw, entries):
    """Write created issue numbers back into the spec file.

    So a re-run after a partial failure completes the remainder instead of
    creating everything a second time: an entry that now carries a number is an
    update, and an update whose values are already right is a no-op.
    """
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(raw if isinstance(raw, dict) else entries, fh, indent=2)
            fh.write('\n')
        return True, ''
    except OSError as exc:
        return False, str(exc)


def _resolve_reference(ref, resolved):
    """A spec reference — an issue number, or another entry's `key` — to a number."""
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str) and ref.isdigit():
        return int(ref)
    return resolved.get(ref)


def _blockers(entry, resolved):
    """(resolved numbers, references that resolve to nothing)."""
    numbers, unresolved = [], []
    for ref in entry.get('blocked_by') or []:
        number = _resolve_reference(ref, resolved)
        (numbers if number is not None else unresolved).append(
            number if number is not None else ref)
    return numbers, unresolved


def _result(entry, action):
    return {'entry': wf_core.entry_label(entry), 'key': entry.get('key'),
            'action': action, 'number': entry.get('number'), 'changed': [],
            'errors': [], 'mismatches': []}


def _parent_id(entry, resolved, node_ids):
    """(parent number, parent node id, err). (None, None, '') when there is none."""
    if entry.get('parent') is None:
        return None, None, ''
    number = _resolve_reference(entry['parent'], resolved)
    if number is None:
        return None, None, ('parent %r is neither an issue number nor a key in '
                            'this spec' % entry['parent'])
    node_id = node_ids.get(number)
    if not node_id:
        return number, None, 'parent #%s could not be resolved' % number
    return number, node_id, ''


def _create_input(cfg, ctx, caps, entry, plan, parent_id, body, dropped=None):
    """The `createIssue` input for one entry.

    The native issue type is the classification, so the two older ways of
    saying the same thing are taken back out here rather than left to every
    caller: a `type-*` label is dropped, and a `[BUG]`-style title prefix is
    stripped. This happens on every org, including one with no native types --
    a classifier nothing reads is clutter, not a fallback. Doing it at the one
    place that writes an issue is what stops the three commands that create
    issues from each having their own house style. `dropped`, when a list is
    passed, collects what was removed so the run can report it.
    """
    title = wf_core.strip_title_prefix(entry.get('title') or '')
    labels, type_labels = wf_core.strip_type_labels(entry.get('labels') or [],
                                                    cfg.get('labels'))
    if dropped is not None:
        dropped.extend(type_labels)
        raw = entry.get('title') or ''
        if title != raw:
            dropped.append(raw[:len(raw) - len(title)].strip())
    args = {'repositoryId': ctx['repo_id'], 'title': title}
    if body:
        args['body'] = body
    if plan['type']:
        args['issueTypeId'] = caps['type_map'][plan['type']]
    if parent_id:
        args['parentIssueId'] = parent_id
    milestone = entry.get('milestone')
    if milestone:
        args['milestoneId'] = ctx['milestones'][milestone]
    label_ids = sorted(ctx['labels'][label(cfg, l)] for l in labels)
    if label_ids:
        args['labelIds'] = label_ids
    fields = [f['input'] for f in plan['fields'].values()]
    if fields:
        args['issueFields'] = fields
    return args


def create_level(cfg, ctx, caps, plans, resolved, node_ids):
    """Create one hierarchy level, in batches. Returns a result per plan.

    Everything in a level is independent of everything else in it, which is
    what makes one aliased request correct: no alias needs another alias's
    output. A level of thirteen and a level of one cost the same one round
    trip, capped by `wf_core.BATCH_MAX_NODES`.
    """
    results, ready, pending = {}, [], []
    for plan in plans:
        entry = plan['entry']
        result = _result(entry, 'create')
        results[id(entry)] = result

        parent_number, parent_id, err = _parent_id(entry, resolved, node_ids)
        if err:
            result['errors'].append(err)
            continue
        result['parent_number'] = parent_number

        body, _ = entry_body(entry)
        result['sent_body'] = body
        dropped = []
        ready.append(_create_input(cfg, ctx, caps, entry, plan, parent_id, body,
                                   dropped))
        if dropped:
            # Not an error and not silent: the entry asked for something no
            # longer written anywhere, and the caller should stop asking.
            result['changed'].append(
                'dropped %s -- the issue type classifies this issue now'
                % ', '.join(repr(d) for d in dropped))
        pending.append((plan, result))

    for chunk_start in range(0, len(pending), wf_core.BATCH_MAX_NODES):
        window = slice(chunk_start, chunk_start + wf_core.BATCH_MAX_NODES)
        outcomes = send_create_batch(ready[window])
        for offset, (plan, result) in enumerate(pending[window]):
            ok, issue, err = outcomes['a%d' % offset]
            if not ok:
                result['errors'].append('create failed: %s' % err)
                continue
            result['number'] = issue['number']
            result['issue_id'] = issue['id']
            result['issue'] = issue
            result['changed'].insert(0, 'created')
            node_ids[issue['number']] = issue['id']
            if plan['entry'].get('key'):
                resolved[plan['entry']['key']] = issue['number']
            plan['entry']['number'] = issue['number']
            # The create payload carried the full selection, so the issue is
            # verified here without a second round trip.
            result['mismatches'] = issue_mismatches(
                issue['number'], issue, plan, expect_type=plan['type'],
                expect_parent=result.get('parent_number'))

    return [results[id(p['entry'])] for p in plans]


def update_entry(cfg, ctx, caps, plan, resolved, node_ids):
    """Bring an existing issue in line with the spec, setting only what differs.

    An update that changes nothing is what makes re-running a spec safe, so
    every property is compared before it is written.
    """
    entry = plan['entry']
    result = _result(entry, 'update')
    repo = ctx['repo']

    parent_number, parent_id, err = _parent_id(entry, resolved, node_ids)
    if err:
        result['errors'].append(err)
        return result
    result['parent_number'] = parent_number

    ok, current, err = read_issue(cfg, entry['number'], repo)
    if not ok:
        result['errors'].append(err)
        return result
    result['issue_id'] = current['id']
    result['issue'] = current
    node_ids[int(entry['number'])] = current['id']

    if plan['type'] and (current.get('issueType') or {}).get('name') != plan['type']:
        ok, _, err = set_issue_type(current['id'], caps['type_map'][plan['type']])
        if not ok:
            result['errors'].append('set type failed: %s' % err)
            return result
        result['changed'].append('type')

    have = issue_field_values(current)
    stale = [f['input'] for name, f in plan['fields'].items()
             if not _values_match(f['value'], have.get(name))]
    if stale:
        ok, _, err = set_issue_fields(current['id'], stale)
        if not ok:
            result['errors'].append('set fields failed: %s' % err)
            return result
        result['changed'].append('fields')

    if parent_id and (current.get('parent') or {}).get('number') != parent_number:
        ok, _, err = add_sub_issue(parent_id, current['id'])
        if not ok:
            result['errors'].append('set parent failed: %s' % err)
            return result
        result['changed'].append('parent')

    milestone = entry.get('milestone')
    if milestone and (current.get('milestone') or {}).get('title') != milestone:
        code, _, merr = run(['gh', 'issue', 'edit', str(entry['number']),
                             '--repo', repo, '--milestone', milestone])
        if code != 0:
            result['errors'].append('milestone update failed: %s' % merr.strip())
            return result
        result['changed'].append('milestone')

    wanted = {label(cfg, l) for l in entry.get('labels') or []}
    present = {n['name'] for n in (current.get('labels') or {}).get('nodes') or []}
    add = sorted(wanted - present)
    if add:
        code, _, lerr = run(['gh', 'issue', 'edit', str(entry['number']),
                             '--repo', repo]
                            + sum((['--add-label', n] for n in add), []))
        if code != 0:
            result['errors'].append('label update failed: %s' % lerr.strip())
            return result
        result['changed'].append('labels')

    # The title and body, which an update used to leave as they were without
    # a word (#242). Compared first, so re-running a spec that already
    # matches writes nothing, and the body goes through a file for the reason
    # `entry_body` gives. A key the entry leaves out leaves that one alone.
    title = entry.get('title')
    if title is not None:
        title = wf_core.strip_title_prefix(title)
    body, berr = entry_body(entry)
    if berr:
        result['errors'].append(berr)
        return result
    edit, edited, body_path = [], [], None
    if title is not None and not wf_core.same_text(title, current.get('title')):
        edit += ['--title', title]
        edited.append('title')
    if body is not None and not wf_core.same_text(body, current.get('body')):
        fd, body_path = tempfile.mkstemp(suffix='.md')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(body)
        edit += ['--body-file', body_path]
        edited.append('body')
    if edit:
        code, _, eerr = run(['gh', 'issue', 'edit', str(entry['number']),
                             '--repo', repo] + edit)
        if body_path:
            try:
                os.remove(body_path)
            except OSError:
                pass
        if code != 0:
            result['errors'].append('%s update failed: %s'
                                    % (' and '.join(edited), eerr.strip()))
            return result
        result['changed'].extend(edited)

    if result['changed']:
        _, result['mismatches'] = verify_issue(
            cfg, entry['number'], plan, expect_type=plan['type'],
            expect_parent=parent_number, repo=repo,
            expect_title=title if 'title' in edited else None,
            expect_body=body if 'body' in edited else None)
    return result


def link_phase(cfg, plans, results, resolved, node_ids):
    """Apply every dependency edge and body rewrite, in one batch per chunk.

    Last, deliberately: an edge may point at any issue in the tree, including
    one created in the final level, and an alias cannot reference another
    alias's output. Waiting until everything exists is what makes a reference
    to any level legal.

    The edge is the whole record. A dependency used to be written twice, once
    as the edge and once as `## Dependencies` prose in the body, and the two
    drifted apart on most of the issues carrying both. Only the edge is written
    now, and only the edge is read.

    **An entry that carries `blocked_by` describes the whole set.** An edge the
    issue holds and the entry does not name is removed, which is how a
    dependency that turned out not to exist is taken back off: `wf unblock`
    releases an issue when its blockers *close*, and nothing else could undo an
    edge somebody added by mistake. An entry with no `blocked_by` key says
    nothing about edges, and nothing is added or removed.
    """
    ops, owners, pending_removals = [], [], []
    for plan, result in zip(plans, results):
        entry = plan['entry']
        if result['errors'] or not result.get('number'):
            continue
        restated = 'blocked_by' in entry
        numbers, unresolved = _blockers(entry, resolved)
        if unresolved:
            result['errors'].append(
                'blocked-by references nothing in this spec or repo: %s'
                % ', '.join(str(u) for u in unresolved))
            continue
        issue = result.get('issue') or {}
        connection = issue.get('blockedBy') or {}
        if restated and wf_core.edges_incomplete(connection):
            # Diffing against a partial read would remove the edges past it
            # as "not named" and miss the ones the entry already has.
            result['errors'].append(
                'the issue holds %d blocked-by edges and the read returned %d, so '
                'which to add or remove is unknown; no edge was changed'
                % (connection['totalCount'], len(connection.get('nodes') or [])))
            continue
        result['blocked_by'] = numbers
        if not restated:
            continue

        # Local edges only. An edge to `org/other#5` is not the local #5, so it
        # is neither kept as #5 nor removed for not being named.
        have = sorted(wf_core.local_blocker_numbers(issue))
        to_add, to_remove = wf_core.edge_diff(have, numbers)
        for blocker in to_add:
            blocking_id = node_ids.get(blocker)
            if not blocking_id:
                result['errors'].append('blocker #%s could not be resolved' % blocker)
                continue
            owners.append((result, 'blocked-by', blocker))
            ops.append(('blocked-by', {'issue_id': result['issue_id'],
                                       'blocking_id': blocking_id}))
        for blocker in to_remove:
            pending_removals.append((result, blocker))

    # An edge being removed points at an issue the spec never mentions, so its
    # node id was not in the prerequisite lookup. One query for all of them,
    # after the loop, rather than one per edge.
    if pending_removals:
        missing = sorted({b for _result, b in pending_removals
                          if b not in node_ids})
        node_ids.update(resolve_issue_ids(cfg, missing))
        for result, blocker in pending_removals:
            blocking_id = node_ids.get(blocker)
            if not blocking_id:
                result['errors'].append(
                    'this entry drops blocked-by #%s, which is on the issue, '
                    'but that issue could not be resolved to remove the edge'
                    % blocker)
                continue
            owners.append((result, 'unblocked-by', blocker))
            ops.append(('unblocked-by', {'issue_id': result['issue_id'],
                                         'blocking_id': blocking_id}))


    for chunk_start in range(0, len(ops), wf_core.BATCH_MAX_NODES):
        window = slice(chunk_start, chunk_start + wf_core.BATCH_MAX_NODES)
        batch = [('b%d' % n, kind, args)
                 for n, (kind, args) in enumerate(ops[window])]
        outcomes = send_link_batch(batch)
        for offset, (result, kind, blocker) in enumerate(owners[window]):
            ok, node, err = outcomes['b%d' % offset]
            if not ok:
                result['errors'].append(
                    '%s #%s failed: %s'
                    % ('removing blocked-by' if kind == 'unblocked-by'
                       else 'blocked-by', blocker, err))
                continue
            result['changed'].append(
                'removed blocked-by #%s' % blocker if kind == 'unblocked-by'
                else 'blocked-by #%s' % blocker)
            result['issue'] = dict(result.get('issue') or {},
                                   blockedBy=node.get('blockedBy') or {})

    # The edge mutations returned the issue's blockers, so the check is free.
    for result in results:
        if 'blocked_by' not in result:
            continue
        have = set(wf_core.local_blocker_numbers(result.get('issue') or {}))
        for want in result['blocked_by']:
            if want not in have:
                result['mismatches'].append('#%s: missing blocked-by edge to #%s'
                                            % (result['number'], want))
        for _result, blocker in pending_removals:
            if _result is result and blocker in have:
                result['mismatches'].append(
                    '#%s: blocked-by edge to #%s is still there'
                    % (result['number'], blocker))
    return results


def lifecycle_phase(cfg, plans, results):
    """Write every issue the spec touched the `Stage` its own state names.

    The rule is `wf_core.stage_for`, applied after the edges exist because two
    of its five inputs depend on them: an owner who is a person or a browser
    agent means Non-code, an explicit `state` on the entry means what the entry
    asked, an issue nothing owns goes to Needs refinement, an open edge means
    Blocked, and everything else is Backlog.

    `Stage` is the whole of the answer, and it lives on the issue. No card is
    added or moved: a board groups by `Stage`, so every board an issue is on
    shows the value written here without anything writing to the board.

    **A stage this phase does not own is left as it is.** The rule above
    describes an issue nobody is working on, and it was applied to every issue
    a spec touched: an update setting a field value on an issue that was in
    progress put it back in Backlog, where a second agent could pick up work
    already underway, and an update to a parked issue silently un-parked it.
    `wf_core.AUTO_MANAGED_STAGES` is the set this phase may write -- Backlog,
    Blocked, Non-code, plus a blank `Stage` -- and an entry that names a
    `state` overrides even that, because asking for a stage is a decision
    rather than an inference.

    **An issue whose edges could not be read is not written at all**, and the
    entry is failed. The stage depends on whether anything blocks the issue,
    and a failed query is not the same answer as "nothing does" -- re-running
    the spec completes the write, because every write before it is idempotent.

    **A retired label is taken off.** Whatever `status-*`, `priority-*`,
    scope or `needs-refinement` label an issue is still carrying from the label
    workflow is removed here, which is how an existing backlog migrates without
    anyone sweeping it: an issue is cleaned the next time a command touches it,
    and `config-audit` names the ones no command has reached. Labels are read
    live where the run has them (`result['issue']`, which `update_entry` fills
    from its own read-back) and from the spec otherwise, which is what a create
    just applied.

    Ownership is read from the field the spec just wrote where the spec wrote
    one, and from the issue's own value otherwise: an update about a milestone
    says nothing about ownership, and re-deciding the stage without it would
    read an owned issue as unowned.
    """
    numbers = [r['number'] for r in results
               if r.get('number') and not r.get('errors')]
    # Every issue this phase decides about, not only the ones whose spec entry
    # restated a dependency. An update that did not restate `blocked_by` would
    # otherwise look dependency-free and be taken out of Blocked. The edges are
    # the record, so they are read for every issue whose stage is about to be
    # decided.
    edge_map, edges_unknown = issue_edges_map(cfg, numbers)
    stages_ok, stage_facets, stages_err = fetch_issue_facets(
        cfg, numbers, stage_field=field_name(cfg, 'field-stage'))
    current_stages = (stage_facets or {}).get('stage') or {}
    repo = '%s/%s' % (cfg['org'], cfg['repo'])
    ownership_field = field_name(cfg, 'field-ownership')
    placements, by_number = {}, {}
    for plan, result in zip(plans, results):
        number = result.get('number')
        if number not in numbers:
            continue
        entry = plan['entry']
        live = result.get('issue') or {}
        live_labels = (live.get('labels') or {}).get('nodes')
        if live_labels is not None:
            names = [n['name'] for n in live_labels]
        else:
            names = [label(cfg, l) for l in (entry.get('labels') or [])]
        owner = (plan.get('fields') or {}).get(ownership_field, {}).get('value')
        if owner is None:
            owner = issue_field_values(live).get(ownership_field)
        scope = wf_core.ownership_scope(owner)
        open_blockers, _closed = wf_core.edge_states(edge_map.get(number) or [], repo)

        retired = wf_core.retired_labels_on(names, cfg.get('labels') or {})
        if retired:
            args = ['gh', 'issue', 'edit', str(number), '--repo', repo]
            for name in retired:
                args.extend(['--remove-label', name])
            code, _, err = run(args)
            if code != 0:
                # Not fatal, and deliberately: the label is cosmetic and the
                # `Stage` write below is the part that decides anything. Failing
                # the issue over a label nothing reads would be the old model
                # again, with the label mattering more than the state.
                result['warnings'] = result.get('warnings') or []
                result['warnings'].append('could not remove retired label(s) %s: %s'
                                          % (', '.join(retired), err.strip()))
            else:
                result['changed'].append('cleared retired label(s) %s'
                                         % ', '.join(retired))

        if number in edges_unknown:
            result['errors'].append(
                'could not read the blocked-by edges, so the stage it belongs '
                'in is unknown and it was not written — re-run the spec')
            continue

        requested = plan.get('state')
        stage = wf_core.STAGE_NAMES[
            wf_core.stage_for(scope, open_blockers, requested)]
        result['stage'] = stage

        if not stages_ok:
            result['errors'].append(
                'could not read its current stage (%s), so it was not written '
                '— re-run the spec' % stages_err)
            continue

        allowed, held_in = wf_core.may_set_stage(current_stages.get(number),
                                                 requested)
        if not allowed:
            # Somebody, or some other run, set that stage. An update about a
            # field value does not overrule that.
            result['stage'] = held_in
            result['stage_kept'] = held_in
            by_number[number] = result
            continue

        placements[number] = stage
        by_number[number] = result

    # One aliased write for the whole spec, not one per issue.
    for number, (written, message) in set_stages(cfg, placements).items():
        result = by_number[number]
        result['stage_set'] = written
        if written:
            continue
        result['stage_message'] = message
        if message == NO_STAGE_FIELD:
            # An org with no `Stage` field is a configuration `preflight` fails
            # on, once, rather than something to fail every entry over.
            result['warnings'] = result.get('warnings') or []
            result['warnings'].append('the org defines no Stage field, so the '
                                      'issue records no state')
            continue
        # `Stage` is the state. An issue whose write failed keeps the stage it
        # had, so the entry has not finished, and re-running the spec does.
        result['errors'].append('Stage was not set to %s (%s) — re-run the '
                                'spec' % (result.get('stage'), message))

    # `Classification` and `Origin` are not worth refusing an issue over, and
    # they are worth saying out loud. A one-line stderr warning reaches whoever
    # ran the command and nobody else; a comment reaches whoever opens the
    # issue, which is the person who can actually fill the field in. Creates
    # only: an update that did not restate an optional field is not a gap, it
    # is an update about something else.
    for plan, result in zip(plans, results):
        number = result.get('number')
        # `result['action']`, not `entry['number']`: a create writes its new
        # number back onto the entry so the spec file can be updated, so by the
        # time this loop runs every entry has one.
        if number not in by_number or result.get('action') != 'create':
            continue
        body = wf_core.unset_optional_comment(plan.get('unset_optional'))
        if not body:
            continue
        code, _, err = run(['gh', 'issue', 'comment', str(number),
                            '--repo', repo, '--body', body])
        if code == 0:
            result['changed'].append('commented on unset optional field(s)')
        else:
            eprint('wf: warning — could not comment on #%s (%s)'
                   % (number, err.strip()))
    return results


def cmd_issue_apply(args):
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)

    ok, entries, raw, err = load_spec(args.spec)
    if not ok:
        emit('spec-invalid', EXIT_SPEC, reason=err, spec=args.spec)

    ok, caps, err = resolve_org_capabilities(cfg, refresh=args.refresh)
    if not ok:
        emit('error', EXIT_ENV, reason=err, org=cfg['org'])
    if caps.get('denied'):
        emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
             denied=caps['denied'],
             reason='the authenticated account may not read %s for this org, so a '
                    'spec cannot be checked against it'
                    % ' and '.join(caps['denied']))

    # Everything that can be decided offline is decided before the first write.
    # A spec that is wrong should cost nothing, and a half-applied tree is much
    # harder to reason about than a refused one.
    body_errors = spec_body_errors(entries)
    if body_errors:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec, errors=body_errors,
             reason='a body_file the spec names could not be read')

    cycles = wf_core.spec_cycles(entries)
    if cycles:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='dependency cycle in the spec',
             cycles=[' -> '.join(str(n) for n in c) for c in cycles])

    levels, unplaceable = wf_core.spec_levels(entries)
    if unplaceable:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='parent cycle in the spec: these entries can never be created '
                    'because each waits on another in the group',
             entries=[wf_core.entry_label(e) for e in unplaceable])

    errors, skipped, plans = wf_core.validate_spec(
        entries, caps['field_map'], caps['type_map'], cfg.get('fields', {}))
    if errors:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec, errors=errors,
             reason='%d spec %s; nothing was written'
                    % (len(errors), 'error' if len(errors) == 1 else 'errors'))

    # One line for the run, not one per issue: an org with fewer fields than the
    # spec names is a normal configuration, and repeating it per issue buries
    # the errors that matter.
    if skipped:
        eprint('wf: skipped %d field(s) this org does not define: %s'
               % (len(skipped), ', '.join(sorted(skipped))))

    label_names = sorted({label(cfg, l) for e in entries
                          for l in (e.get('labels') or [])})
    referenced = set()
    for entry in entries:
        candidates = [entry.get('number'), entry.get('parent')]
        candidates.extend(entry.get('blocked_by') or [])
        for ref in candidates:
            if isinstance(ref, int):
                referenced.add(ref)
            elif isinstance(ref, str) and ref.isdigit():
                referenced.add(int(ref))
    milestones = [e['milestone'] for e in entries if e.get('milestone')]
    ok, ctx, err = resolve_spec_context(cfg, label_names, referenced, args.repo,
                                        milestones)
    if not ok:
        emit('error', EXIT_ENV, reason='could not resolve the repository: %s' % err)
    if ctx['missing_labels']:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='labels the spec names do not exist in this repo',
             labels=ctx['missing_labels'])
    if ctx['missing_milestones']:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='milestones the spec names are not open in this repo',
             milestones=ctx['missing_milestones'])
    if ctx['missing_issues']:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec,
             reason='issues the spec references do not exist in this repo',
             issues=ctx['missing_issues'])

    # Epic → Feature → User Story. Checked here rather than in `validate_spec`
    # because a parent may be an issue that already exists, and its type is only
    # known once the referenced issues have been read.
    hierarchy = wf_core.spec_hierarchy_errors(
        plans, ctx['issue_types'], ctx['issue_parents'], caps['type_map'])
    if hierarchy:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec, errors=hierarchy,
             reason='%d %s outside the epic → feature → story tree; nothing '
                    'was written'
                    % (len(hierarchy),
                       'entry sits' if len(hierarchy) == 1 else 'entries sit'))

    # The rules an update can only break against the issue it updates.
    live_errors = wf_core.spec_live_errors(plans, ctx['issue_live'],
                                           cfg.get('fields', {}))
    if live_errors:
        emit('spec-invalid', EXIT_SPEC, spec=args.spec, errors=live_errors,
             reason='%d spec %s against the issues it updates; nothing was written'
                    % (len(live_errors),
                       'error' if len(live_errors) == 1 else 'errors'))

    if args.dry_run:
        emit('ok', EXIT_OK, spec=args.spec, dry_run=True,
             levels=[[wf_core.entry_label(e) for e in level] for level in levels],
             would_apply=[{'entry': wf_core.entry_label(p['entry']),
                           'action': 'update' if p['entry'].get('number') else 'create',
                           'type': p['type'],
                           'fields': sorted(p['fields'])} for p in plans],
             skipped_fields=sorted(skipped))

    plan_by_entry = {id(p['entry']): p for p in plans}
    resolved = {e['key']: int(e['number']) for e in entries
                if e.get('key') and e.get('number')}
    node_ids = dict(ctx['issues'])

    ordered_plans, results = [], []
    wb_failure = None
    for level in levels:
        level_plans = [plan_by_entry[id(e)] for e in level]
        creates = [p for p in level_plans if not p['entry'].get('number')]
        updates = [p for p in level_plans if p['entry'].get('number')]
        if creates:
            ordered_plans.extend(creates)
            results.extend(create_level(cfg, ctx, caps, creates, resolved, node_ids))
            # Written back as each level lands, not once at the end: a run that
            # dies part way through the tree must not leave issues it created
            # unrecorded, or the re-run creates them a second time.
            done, err = write_back_numbers(args.spec, raw, entries)
            if not done and wb_failure is None:
                wb_failure = err
        for plan in updates:
            ordered_plans.append(plan)
            results.append(update_entry(cfg, ctx, caps, plan, resolved, node_ids))

    link_phase(cfg, ordered_plans, results, resolved, node_ids)
    lifecycle_phase(cfg, ordered_plans, results)

    wrote_back, wb_err = write_back_numbers(args.spec, raw, entries)
    if wrote_back and wb_failure is not None:
        wrote_back, wb_err = False, wb_failure

    payload = {'spec': args.spec, 'applied': results,
               'skipped_fields': sorted(skipped),
               'numbers_written_back': wrote_back}
    if not wrote_back:
        payload['write_back_error'] = wb_err

    failed = [r for r in results if r['errors']]
    mismatched = [r for r in results if r['mismatches']]

    if failed:
        landed = [r for r in results if r.get('number') and not r['errors']]
        emit('partial', EXIT_PARTIAL,
             reason='%d of %d entries failed; %d landed. Re-run the spec to '
                    'complete the rest — the numbers written back turn the ones '
                    'that landed into no-op updates'
                    % (len(failed), len(results), len(landed)),
             failed=[{'entry': r['entry'], 'errors': r['errors']} for r in failed],
             **payload)
    if mismatched:
        emit('verify-failed', EXIT_VERIFY,
             reason='%d issue(s) were written but do not read back as specified'
                    % len(mismatched),
             mismatches=sum((r['mismatches'] for r in mismatched), []),
             **payload)

    emit('ok', EXIT_OK, **payload)
