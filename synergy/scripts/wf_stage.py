"""
Stage writes, the start date, branch checkout, and the `stage-set` subcommand.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

from datetime import datetime, timezone

import wf_core
from wf_capabilities import resolve_org_capabilities
from wf_config import field_name, prepare_cfg
from wf_io import EXIT_OK, emit, gh_json, run
from wf_issue_io import (
    _batch_result, _graphql_json, resolve_issue_ids, set_issue_fields,
)


# ── Stage writes + branch (--checkout) ───────────────────────────────────────

def best_effort(step, *args):
    """Run one best-effort side effect. Returns (ok, message) and never raises.

    The steps between the claim and the branch — the `Stage` write, the start
    date — are recoverable, and the branch is not. A story that is claimed with
    no branch to work on is the worst outcome available here: the caller has
    nothing to build in and someone has to reap the claim by hand. So an
    unexpected failure inside one of these is reported in its own message and
    the run carries on, exactly as a returned error would be.
    """
    try:
        return step(*args)
    except Exception as exc:  # noqa: BLE001 - deliberate: see docstring
        label = getattr(step, '__name__', 'step').replace('_', ' ')
        return False, '%s failed unexpectedly (%s: %s)' % (
            label, type(exc).__name__, exc)


def stage_in_progress(cfg, number):
    """Set the issue's `Stage` to In Progress. Returns (written, message)."""
    return set_stage(cfg, number, wf_core.STAGE_NAMES['stage-in-progress'])


# Issues per aliased `Stage` write. The same twenty the edge writer uses, for
# the same reason: GitHub's complexity budget, not a limit of the mutation.
STAGE_BATCH = 20

# The message every write returns when the org has no `Stage` field, so a
# caller can tell a configuration gap from a failed write without parsing.
NO_STAGE_FIELD = 'the org defines no Stage field'


def stage_field_meta(cfg):
    """The org's `Stage` field, with its option ids. (ok, meta, err)."""
    ok, caps, err = resolve_org_capabilities(cfg)
    if not ok:
        return False, None, 'org capabilities unavailable (%s)' % (err or 'no detail')
    meta = (caps.get('field_map') or {}).get(field_name(cfg, 'field-stage'))
    if not meta:
        return False, None, NO_STAGE_FIELD
    return True, meta, ''


def set_stages(cfg, wanted, ids=None, extra=None):
    """Write many issues' `Stage` at once. {number: (written, message)}.

    `wanted` is {issue number: option name or `stage-*` purpose key}. Two round
    trips whatever the size, after the capability record (cached): one aliased
    read of the node ids and one aliased `setIssueFieldValue`, twenty issues to
    a request. `ids` is {number: node id} for issues the caller has already
    read, which skips the id read for them. `extra` is {number: [field
    input]} for other fields to write in the same mutation, such as the start
    date a claim stamps beside `In Progress`.

    Nothing here touches a board. Every board an issue is on groups by `Stage`,
    so the value written is the value every board shows, and an issue with no
    card is in exactly the same state as one with a card in every project.
    """
    out = {}
    if not wanted:
        return out
    ok, meta, err = stage_field_meta(cfg)
    if not ok:
        return {int(n): (False, err) for n in wanted}

    inputs = {}
    for number, stage in wanted.items():
        name = wf_core.stage_name(stage)
        if not name:
            out[int(number)] = (False, "'%s' is not a stage (it reads: %s)"
                                % (stage, ', '.join(wf_core.STAGE_NAMES.values())))
            continue
        value, verr = wf_core.field_value_input(
            meta, wf_core.option_spelling(meta, name))
        if verr:
            out[int(number)] = (False, verr)
            continue
        inputs[int(number)] = (name, value)

    ids = {int(n): i for n, i in (ids or {}).items() if i}
    unread = [n for n in inputs if n not in ids]
    if unread:
        ids.update(resolve_issue_ids(cfg, unread))
    for number in sorted(inputs):
        if number not in ids:
            out[number] = (False, 'could not read the issue node id')
            del inputs[number]

    for chunk in _chunks(sorted(inputs), STAGE_BATCH):
        decls, body, variables, aliases = [], [], {}, []
        for number in chunk:
            alias = 's%d' % number
            aliases.append(alias)
            decls.append('$%s_i:ID!,$%s_f:[IssueFieldCreateOrUpdateInput!]!'
                         % (alias, alias))
            body.append('%s: setIssueFieldValue(input:{issueId:$%s_i,'
                        'issueFields:$%s_f}){ issue { id } }'
                        % (alias, alias, alias))
            variables['%s_i' % alias] = ids[number]
            variables['%s_f' % alias] = ([inputs[number][1]]
                                         + list((extra or {}).get(number) or ()))
        code, raw, merr = _graphql_json('mutation(%s){ %s }'
                                        % (','.join(decls), ' '.join(body)),
                                        variables)
        results = _batch_result(code, raw, merr, aliases)
        for number in chunk:
            written, _node, why = results['s%d' % number]
            out[number] = ((True, 'Stage set to %s' % inputs[number][0])
                           if written else (False, why))
    return out


def set_stage(cfg, number, stage):
    """Write one issue's `Stage`. (written, message)."""
    return set_stages(cfg, {int(number): stage})[int(number)]


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def start_date_input(cfg):
    """Today's value for the org's `Start date` field. (input, message).

    `input` is None, with `message` saying why, when the org defines no such
    field or its capabilities cannot be read: best-effort in both directions,
    because neither is a misconfiguration a claim should stop on.
    """
    ok, caps, err = resolve_org_capabilities(cfg)
    if not ok:
        return None, 'org capabilities unavailable (%s)' % (err or 'no detail')
    name = field_name(cfg, 'field-start')
    meta = (caps.get('field_map') or {}).get(name)
    if not meta:
        return None, 'the org does not define a %s field' % name
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    value, verr = wf_core.field_value_input(meta, today)
    if verr:
        return None, verr
    return value, 'set %s to %s' % (name, today)


def set_start_date(cfg, number):
    """Stamp the org's `Start date` issue field with today. Returns (set, why).

    Best-effort and capability-gated in both directions: an org that does not
    define the field is not misconfigured, and neither is one that denies the
    field API to this token.
    """
    value, why = start_date_input(cfg)
    if value is None:
        return False, why
    name = field_name(cfg, 'field-start')
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    ok, data, jerr = gh_json(['issue', 'view', str(number), '--repo',
                              '%s/%s' % (cfg['org'], cfg['repo']), '--json', 'id'])
    if not ok or not data or not data.get('id'):
        return False, 'could not read the issue node id (%s)' % jerr.strip()
    # Three values, not two: `set_issue_fields` answers (ok, node, err) like
    # every other `_mutation_result` caller. Unpacking two raised ValueError
    # *after* the claim, the label, the assignment and the Stage write had all
    # landed, so the run looked failed and was not.
    applied, _, merr = set_issue_fields(data['id'], [value])
    if not applied:
        return False, merr
    return True, 'set %s to %s' % (name, today)


def checkout_branch(cfg, issue):
    """Create/check out the working branch. Returns (branch, checked_out, message)."""
    default = cfg['default_branch']
    branch = wf_core.branch_name(cfg['branch_convention'], issue['number'], issue['title'])
    run(['git', 'fetch', 'origin', default])
    local = run(['git', 'branch', '--list', branch])[1].strip()
    remote = run(['git', 'ls-remote', '--heads', 'origin', branch])[1].strip()
    if local or remote:
        code, _, err = run(['git', 'checkout', branch])
        if code != 0:
            return branch, False, 'branch exists but checkout failed (%s)' % err.strip()
        code, _, err = run(['git', 'rebase', 'origin/%s' % default])
        if code != 0:
            run(['git', 'rebase', '--abort'])
            return branch, True, 'checked out, but rebase onto %s conflicts — resolve before working' % default
        return branch, True, 'checked out existing branch, rebased onto %s' % default
    code, _, err = run(['git', 'checkout', '-b', branch, 'origin/%s' % default])
    if code != 0:
        return branch, False, 'could not create branch (%s)' % err.strip()
    return branch, True, 'created from origin/%s' % default


# ── stage-set and claim-release ──────────────────────────────────────────────
# The two pieces a caller still needs to reach on their own: setting an issue's
# `Stage`, and letting a claim go. Everything else — resolving the field and
# its option id, the node id, the compare-and-swap — is already the body of
# `set_stage()` and `release_claim()` above.


def cmd_stage_set(args):
    cfg = prepare_cfg()
    # Accept the purpose key as well as the option's own name, because the
    # instructions name the purpose and the org field holds the name.
    stage = wf_core.stage_name(args.stage) or args.stage
    written, message = set_stage(cfg, args.number, args.stage)
    if written:
        emit('ok', EXIT_OK, number=args.number, stage=stage, set=True,
             reason='#%d Stage set to %s' % (args.number, stage))
    # A failed write is reported and never fatal, but it is not harmless
    # either: `Stage` *is* the state, so an issue whose write failed keeps the
    # stage it had. Callers surface the reason.
    emit('ok', EXIT_OK, number=args.number, stage=stage, set=False,
         reason='Stage not set: %s' % message)
