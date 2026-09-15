"""
The org's issue types, issue fields and type pins, and the repo's labels: the
capability cache, partial GraphQL reads, and the `org-capabilities` subcommand.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import json
import os
import time

import wf_core
from wf_config import field_name, load_config, repo_root
from wf_io import (
    EXIT_CAPABILITY, EXIT_ENV, EXIT_OK, _graphql_args, emit, eprint,
    gh_graphql, run,
)


CAPABILITY_CACHE_NAME = 'issue-fields-cache.json'

# Bumped when a cached record could have been written by a version whose
# conclusion is no longer trusted. An empty record is only believed when it
# carries the current schema, so a cache poisoned by an older version heals
# itself on the next run instead of waiting for someone to know about
# `--refresh`. Version 2: before it, a capability query that failed with a
# NOT_FOUND error was recorded as `owner_kind: user` -- an org read as a
# personal account, cached forever, every issue thereafter created with no
# type and no field values and no error anywhere. Version 3: records carry
# `fetched_at`, so a record written before it has no age and is re-queried.
CAPABILITY_CACHE_SCHEMA = 3

# How long a successful answer is trusted. Before this, any record carrying a
# type or a field was trusted forever, and the org's fields are not fixed: an
# org that created `Stage` after the cache was written went on being reported
# as having no `Stage`, and a field deleted since was still offered. The file
# also outlives the run that wrote it -- a main checkout never runs Exit
# cleanup, and a new worktree can start with a copy of that checkout's
# `.claude/` -- so the age is stamped inside the record rather than read from
# the file's mtime, which a copy resets.
CAPABILITY_CACHE_MAX_AGE = 3600

# A record missing a field the workflow cannot run without is re-queried once
# it is older than this, whatever `CAPABILITY_CACHE_MAX_AGE` says. The short
# grace stops an org that genuinely lacks the field from paying a round trip on
# every call, while an org that has since created it is seen within minutes.
CAPABILITY_CACHE_GAP_RECHECK = 300

# Both halves of the org's capability surface in one round trip: the enabled
# native issue types, and every issue field with its option ids.
#
# This is GraphQL and not REST on purpose. The REST endpoint
# `/orgs/{org}/issue-fields` returns `null` for every option id, which makes a
# single-select or multi-select field impossible to write -- you can read the
# option names but never name one in a mutation. Do not "simplify" this back to
# REST.
#
# The selection is shared with preflight's pin check, which needs the same
# issue types and which fields each pins. `_capability_query(pins=True)` asks
# for both at once, so preflight makes one request where it made two (#300).
_ISSUE_TYPE_PINS = (
    '   pinnedFields {'
    '    __typename'
    '    ... on IssueFieldSingleSelect { name }'
    '    ... on IssueFieldMultiSelect { name }'
    '    ... on IssueFieldDate { name }'
    '    ... on IssueFieldText { name }'
    '    ... on IssueFieldNumber { name }'
    '   }'
)


def _capability_query(pins=False):
    return (
        'query($login:String!){'
        ' organization(login:$login){'
        '  issueTypes(first:50){ nodes { id name isEnabled%s } }'
        '  issueFields(first:50){ nodes {'
        '   __typename'
        '   ... on IssueFieldSingleSelect { id name options { id name } }'
        '   ... on IssueFieldMultiSelect { id name options { id name } }'
        '   ... on IssueFieldDate { id name }'
        '   ... on IssueFieldText { id name }'
        '   ... on IssueFieldNumber { id name }'
        '  } }'
        ' } }'
    ) % (_ISSUE_TYPE_PINS if pins else '')


ORG_CAPABILITY_QUERY = _capability_query()
ORG_CAPABILITY_PINS_QUERY = _capability_query(pins=True)

_FIELD_TYPENAMES = {
    'IssueFieldSingleSelect': 'single-select',
    'IssueFieldMultiSelect': 'multi-select',
    'IssueFieldDate': 'date',
    'IssueFieldText': 'text',
    'IssueFieldNumber': 'number',
}


def capability_cache_path(root=None):
    return os.path.join(root or repo_root(), '.claude', CAPABILITY_CACHE_NAME)


def load_capability_cache(root=None):
    """Read the capability cache. Returns {} when absent or unreadable."""
    path = capability_cache_path(root)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as fh:
            cached = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        eprint('wf: ignoring unreadable capability cache (%s)' % exc)
        return {}
    return cached if isinstance(cached, dict) else {}


def merge_capability_cache(values, root=None):
    """Merge keys into the capability cache, preserving every other key.

    Merged rather than overwritten because this file is shared: `issue-apply`
    and `issue-audit` write their own keys into it, and a capability refresh
    must not discard them.
    """
    path = capability_cache_path(root)
    cached = load_capability_cache(root)
    cached.update(values)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(cached, fh, indent=2, sort_keys=True)
        fh.write('\n')
    return cached


def parse_org_capabilities(data):
    """Shape the GraphQL response into (type_capable, type_map, field_map).

    `type_map` is {type name: node id} for enabled types only -- a disabled type
    cannot be set, so carrying it would only invite a mutation that fails.
    `field_map` is {field name: {id, data_type, options: {option name: id}}}.
    """
    org = (data or {}).get('organization')
    if not org:
        # A user-owned repo resolves `organization` to null. Issue types are an
        # org-only feature, so this is a valid configuration, not a failure.
        return False, {}, {}

    type_map = {}
    for node in (org.get('issueTypes') or {}).get('nodes') or []:
        if node and node.get('isEnabled') and node.get('name'):
            type_map[node['name']] = node['id']

    field_map = {}
    for node in (org.get('issueFields') or {}).get('nodes') or []:
        if not node or not node.get('name'):
            continue
        field_map[node['name']] = {
            'id': node['id'],
            'data_type': _FIELD_TYPENAMES.get(node.get('__typename'), 'unknown'),
            'options': {o['name']: o['id'] for o in (node.get('options') or [])},
        }

    return bool(type_map), type_map, field_map


def gh_graphql_partial(query, **fields):
    """Like `gh_graphql`, but keeps the data GitHub returned alongside errors.

    GraphQL answers a partly-authorised query with both: the fields the token
    may read, and a `FORBIDDEN` error naming the ones it may not. `gh` exits
    non-zero in that case and `gh_graphql` discards the whole response, which
    is right everywhere else — a half-applied mutation is not a result. Here it
    is the difference between "this org has no issue types" and "this token may
    not see them", and those two must not be reported the same way.

    Returns (data, errors, err) where `errors` is the GraphQL error list.
    """
    code, out, err = run(_graphql_args(query, fields))
    try:
        parsed = json.loads(out) if (out or '').strip() else None
    except json.JSONDecodeError:
        parsed = None
    if parsed is None:
        return None, [], (err or '').strip() or 'no response from gh api graphql'
    return parsed.get('data'), parsed.get('errors') or [], (
        '' if code == 0 else (err or '').strip())


# The GraphQL error types that mean "this account could not read it", as
# opposed to "it is not there". `NOT_FOUND` is in here because that is what
# GitHub answers for an org the token may not see -- the same org read by an
# authorised token answers normally. Treating it as an absence is what let a
# real organisation be cached as a personal account.
UNREADABLE_ERROR_TYPES = frozenset({'FORBIDDEN', 'NOT_FOUND', 'UNAUTHORIZED'})


def _denied_paths(errors):
    """The query fields an error says this account could not read.

    Returns e.g. {'issueTypes'}, or {'organization'} when the whole org was
    unreadable. An error carrying no usable path still counts, under the name
    `organization`, so a refusal is never silently discarded for want of a
    path.
    """
    denied = set()
    for e in errors or []:
        if (e.get('type') or '').upper() not in UNREADABLE_ERROR_TYPES:
            continue
        named = {part for part in (e.get('path') or []) if isinstance(part, str)}
        denied |= named or {'organization'}
    return denied


def _capability_record_gaps(cached, project_fields=None):
    """What a workflow cannot run without and the cached record does not hold.

    The mandatory fields, `Stage`, and every `Stage` option a transition
    writes. Each one missing is a critical preflight finding, so a cached
    record that lacks one is worth a round trip to confirm before reporting it.
    Returns a list of names; empty when nothing is missing.
    """
    field_map = cached.get('field_map') or {}
    keys = tuple(wf_core.MANDATORY_FIELD_KEYS) + ('field-stage',)
    gaps = [n for n in (wf_core.resolve_field_name(k, project_fields or {})
                        for k in keys) if n not in field_map]
    stage = field_map.get(
        wf_core.resolve_field_name('field-stage', project_fields or {})) or {}
    have = {str(o).strip().lower() for o in (stage.get('options') or {})}
    if stage:
        gaps.extend(n for n in wf_core.STAGE_NAMES.values() if n.lower() not in have)
    return gaps


def _capability_record_is_usable(cached, project_fields=None, now=None):
    """Whether a cached capability record can be trusted without re-querying.

    A record carrying no types and no fields is indistinguishable from never
    having resolved. For an org that is almost always a failed lookup that got
    written, so it is treated as a cache miss and re-queried, which lets an
    already-poisoned cache heal itself without anyone knowing to pass
    `--refresh`. A user-owned repo has no issue types by design, so its empty
    record is legitimate and is trusted -- which is what `owner_kind` is for.
    A record written before that key existed, or by a schema version whose
    conclusion is no longer trusted, has no claim to being empty on purpose, so
    it is re-queried once and rewritten -- which is how a cache poisoned by an
    earlier version heals without anyone knowing to pass `--refresh`.

    A populated record is not trusted forever either. It expires after
    `CAPABILITY_CACHE_MAX_AGE`, and sooner -- after
    `CAPABILITY_CACHE_GAP_RECHECK` -- when it lacks a field or `Stage` option
    the workflow needs, because that is exactly what an org that has changed
    its fields since the record was written looks like. A record with no
    `fetched_at`, or one stamped in the future, has no trustworthy age.
    """
    if cached.get('schema') != CAPABILITY_CACHE_SCHEMA:
        return False
    fetched = cached.get('fetched_at')
    if not isinstance(fetched, (int, float)):
        return False
    age = (time.time() if now is None else now) - fetched
    if age < 0 or age >= CAPABILITY_CACHE_MAX_AGE:
        return False
    if cached.get('owner_kind') == 'user':
        return True
    if not (cached.get('type_map') or cached.get('field_map')):
        return False
    if age >= CAPABILITY_CACHE_GAP_RECHECK and _capability_record_gaps(
            cached, project_fields):
        return False
    return True


def resolve_org_capabilities(cfg, refresh=False, root=None, pins=False):
    """Resolve the org's issue types and fields, through the cache.

    Returns (ok, capabilities, err). `capabilities` carries `type_capable`,
    `type_map` and `field_map`. A cache hit skips the round trip entirely;
    `refresh=True` forces the query and rewrites those three keys.

    `pins=True` reads which fields each issue type pins in the same request
    and returns them as `capabilities['pins']`, shaped as
    `fetch_issue_type_pins` answers: (ok, types, err). Pins are never cached:
    preflight tells a person to fix pinning and re-run, and a cached answer
    would report the fix as not done. So asking for them skips the cache read,
    and the capability half is written to the cache exactly as a refresh is.
    """
    if not refresh and not pins:
        cached = load_capability_cache(root)
        if 'type_capable' in cached and 'field_map' in cached and (
                _capability_record_is_usable(cached, cfg.get('fields'))):
            return True, {'type_capable': cached['type_capable'],
                          'type_map': cached.get('type_map') or {},
                          'field_map': cached.get('field_map') or {},
                          'owner_kind': cached.get('owner_kind') or '',
                          'cached': True}, ''

    data, errors, err = gh_graphql_partial(
        ORG_CAPABILITY_PINS_QUERY if pins else ORG_CAPABILITY_QUERY,
        login=cfg['org'])
    pin_result = None
    if pins:
        # A refusal to read `pinnedFields` leaves the pin check unverified. It
        # says nothing about the types or fields, so it must never become a
        # denied capability.
        pin_errors = [e for e in errors if 'pinnedFields' in (e.get('path') or [])]
        errors = [e for e in errors if 'pinnedFields' not in (e.get('path') or [])]
        if data is None:
            # A schema without `pinnedFields` refuses the whole request. That
            # has to cost the pin check only, as it did when pins were a
            # request of their own, so the capabilities are asked for alone.
            pin_result = (False, [], err or (json.dumps(errors) if errors else '')
                          or 'the pin query failed')
            data, errors, err = gh_graphql_partial(ORG_CAPABILITY_QUERY,
                                                   login=cfg['org'])
        elif not data.get('organization'):
            pin_result = (False, [], err or (json.dumps(errors) if errors else '')
                          or 'no issue types returned for %s' % cfg['org'])
        elif pin_errors:
            pin_result = (False, [], json.dumps(pin_errors))
        else:
            pin_result = (True, _parse_type_pins(data['organization']), '')
    if data is None:
        return False, None, 'org capability query failed: %s' % (
            err or json.dumps(errors))

    denied = _denied_paths(errors)
    type_capable, type_map, field_map = parse_org_capabilities(data)
    owner_kind = 'organization' if (data or {}).get('organization') else 'user'
    caps = {'type_capable': type_capable, 'type_map': type_map,
            'field_map': field_map, 'cached': False,
            'owner_kind': owner_kind,
            'denied': sorted(denied),
            'errors': [e.get('message', '') for e in errors]}
    if pins:
        caps['pins'] = pin_result

    # Never cache a capability the token was refused. A cached `type_capable:
    # false` that really meant "not allowed to look" would make every later run
    # quietly fall back to labels — the silent-blank failure this whole feature
    # exists to stop.
    #
    # An org that answers with no types and no fields is the same failure
    # wearing different clothes: it is what an under-scoped or expired token
    # looks like, and GitHub does not always attach a FORBIDDEN error to say so.
    # Caching that turns one bad round trip into a permanent silent fallback, so
    # it is not written. A user-owned repo genuinely has neither, so that empty
    # is cached and marked, and does not cost a round trip on every run.
    #
    # An empty answer that arrived alongside *any* GraphQL error is not an
    # answer at all, whatever the error says, so `errors` is checked rather
    # than only the ones recognised as refusals.
    empty = not type_map and not field_map
    if not denied and not (empty and (owner_kind == 'organization' or errors)):
        merge_capability_cache({'type_capable': type_capable, 'type_map': type_map,
                                'field_map': field_map,
                                'owner_kind': owner_kind,
                                'fetched_at': int(time.time()),
                                'schema': CAPABILITY_CACHE_SCHEMA}, root)
    return True, caps, ''


def org_exists(cfg):
    """Whether the configured owner resolves as an organization at all.

    Separates the two ways `resolve_org_capabilities` can come back empty: a
    user-owned repo, which is valid, from an org whose capabilities the token
    cannot see, which is not.
    """
    ok, data, _ = gh_graphql(
        'query($login:String!){ organization(login:$login){ id } }',
        login=cfg['org'])
    return bool(ok and (data or {}).get('organization'))


def cmd_org_capabilities(args):
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)

    ok, caps, err = resolve_org_capabilities(cfg, refresh=args.refresh)
    if not ok:
        emit('error', EXIT_ENV, reason=err, org=cfg['org'])

    # A refused capability is not an absent one. An org that has not enabled
    # issue types is a valid configuration to fall back from; a token that may
    # not read them tells us nothing about the org, and carrying on would
    # create issues with blank metadata and no error — the exact failure this
    # command exists to prevent. Stop and name the account.
    if caps.get('denied'):
        emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
             denied=caps['denied'], errors=caps['errors'],
             reason='the account signed in to gh may not read %s for %s; switch '
                    'accounts (gh auth switch) or grant it access — this is not '
                    'the same as the org having none, and nothing was cached'
                    % (' and '.join(caps['denied']), cfg['org']))

    # An org that resolves but reports neither types nor fields is not the same
    # as a user account, and not the same as an org that simply has not enabled
    # them: it is what an under-scoped or expired token looks like. Exiting
    # non-zero here is the only thing that tells those apart.
    if not caps['type_capable'] and not caps['field_map']:
        if org_exists(cfg):
            emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
                 reason='org resolves but reports no issue types and no issue '
                        'fields; check the token carries the read:org scope',
                 type_capable=False, type_map={}, field_map={})
        emit('ok', EXIT_OK, org=cfg['org'], owner_kind='user',
             type_capable=False, type_map={}, field_map={},
             cached=caps.get('cached', False),
             note='user-owned repo: native issue types are an org-only feature')

    # Report which purpose keys actually resolve against this org, so a caller
    # does not have to re-derive the mapping to know what it can set.
    resolved, missing = {}, []
    for key in wf_core.FIELD_NAME_DEFAULTS:
        name = field_name(cfg, key)
        if name in caps['field_map']:
            resolved[key] = name
        else:
            missing.append({'purpose': key, 'expected_name': name})

    emit('ok', EXIT_OK, org=cfg['org'], owner_kind='organization',
         type_capable=caps['type_capable'], type_map=caps['type_map'],
         field_map=caps['field_map'], cached=caps.get('cached', False),
         resolved_fields=resolved, missing_fields=missing,
         cache=os.path.relpath(capability_cache_path(), repo_root()))


PINNED_FIELD_QUERY = (
    'query($login:String!){'
    ' organization(login:$login){'
    '  issueTypes(first:50){ nodes {'
    '   name isEnabled'
    + _ISSUE_TYPE_PINS +
    '  } }'
    ' } }'
)

_LABEL_PAGE = (
    '  labels(first:100,after:$after){'
    '   pageInfo { hasNextPage endCursor } nodes { name }'
    '  }'
)

REPO_LABEL_QUERY = (
    'query($owner:String!,$repo:String!,$after:String){'
    ' repository(owner:$owner,name:$repo){' + _LABEL_PAGE + ' } }'
)


def fetch_issue_type_pins(cfg):
    """Which org fields each issue type pins to its form. (ok, types, err).

    `pinnedFields` is a plain list on `IssueType`, not a connection. A token
    that may not read it, or a schema that does not have it, comes back as
    `ok=False` — preflight reports that as a warning rather than pretending
    every type is pinned correctly.
    """
    data, errors, err = gh_graphql_partial(PINNED_FIELD_QUERY, login=cfg['org'])
    org = (data or {}).get('organization') if data else None
    if not org:
        return False, [], (err or json.dumps(errors)
                           or 'no issue types returned for %s' % cfg['org'])
    return True, _parse_type_pins(org), ''


def _parse_type_pins(org):
    """Each issue type's name, whether it is enabled, and the fields it pins."""
    types = []
    for node in (org.get('issueTypes') or {}).get('nodes') or []:
        if not node or not node.get('name'):
            continue
        types.append({'name': node['name'],
                      'enabled': bool(node.get('isEnabled')),
                      'pinned': [f['name'] for f in node.get('pinnedFields') or []
                                 if f and f.get('name')]})
    return types


def fetch_repo_state(cfg, repo=None):
    """Every label in the repo. (ok, state, err)."""
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    labels, cursor = [], None
    while True:
        fields = {'owner': owner, 'repo': name}
        if cursor:
            fields['after'] = cursor
        ok, data, err = gh_graphql(REPO_LABEL_QUERY, **fields)
        if not ok:
            return False, None, err
        page = (((data or {}).get('repository') or {}).get('labels')) or {}
        labels.extend(n['name'] for n in page.get('nodes') or [] if n.get('name'))
        info = page.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return True, {'labels': labels}, ''
        cursor = info.get('endCursor')
