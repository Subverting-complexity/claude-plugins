"""
The `issue-audit` subcommand: scan open issues and write the spec that would
fix them.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import json
import os

import wf_core
from wf_capabilities import resolve_org_capabilities
from wf_config import load_config, repo_root
from wf_io import (
    EXIT_CAPABILITY, EXIT_ENV, EXIT_GAPS, EXIT_OK, emit, gh_graphql,
)
from wf_issue_io import ISSUE_SELECTION


# ── issue-audit ──────────────────────────────────────────────────────────────
# Reads. Never writes. It exists because nothing detected that the metadata was
# never applied, and it produces the spec that `issue-apply` uses to backfill.

AUDIT_PAGE = 100
AUDIT_SPEC_DEFAULT = 'issue-audit-spec.json'

AUDIT_QUERY = (
    'query($owner:String!,$repo:String!,$after:String,$since:DateTime){'
    ' repository(owner:$owner,name:$repo){'
    '  issues(states:OPEN,first:%d,after:$after,filterBy:{since:$since},'
    '         orderBy:{field:CREATED_AT,direction:DESC}){'
    '   pageInfo { hasNextPage endCursor }'
    '   nodes {' % AUDIT_PAGE
    + ISSUE_SELECTION +
    '   }'
    '  }'
    ' } }'
)


def scan_open_issues(cfg, repo=None, limit=None, since=None):
    """Every open issue in the repo, newest first. Returns (ok, issues, err).

    `since` narrows to issues updated after a timestamp and `limit` caps the
    scan, so a large backlog can be worked through in slices rather than all at
    once.
    """
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    issues, cursor = [], None
    while True:
        fields = {'owner': owner, 'repo': name}
        if cursor:
            fields['after'] = cursor
        if since:
            fields['since'] = since
        ok, data, err = gh_graphql(AUDIT_QUERY, **fields)
        if not ok:
            return False, None, err
        page = (((data or {}).get('repository') or {}).get('issues')) or {}
        issues.extend(page.get('nodes') or [])
        if limit and len(issues) >= limit:
            return True, issues[:limit], ''
        info = page.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return True, issues, ''
        cursor = info.get('endCursor')


def write_audit_spec(path, entries):
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'issues': entries}, fh, indent=2)
            fh.write('\n')
        return True, ''
    except OSError as exc:
        return False, str(exc)


def cmd_issue_audit(args):
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)

    ok, caps, err = resolve_org_capabilities(cfg, refresh=args.refresh)
    if not ok:
        emit('error', EXIT_ENV, reason=err, org=cfg['org'])
    if caps.get('denied'):
        emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
             denied=caps['denied'],
             reason='the authenticated account may not read %s for this org, so '
                    'there is nothing to audit issues against'
                    % ' and '.join(caps['denied']))

    repo = args.repo or '%s/%s' % (cfg['org'], cfg['repo'])
    ok, issues, err = scan_open_issues(cfg, args.repo, args.limit, args.since)
    if not ok:
        emit('error', EXIT_ENV, reason='could not read issues in %s: %s'
                                       % (repo, err), repo=repo)

    open_numbers = {i['number'] for i in issues}
    # Every scanned issue's parent, stage and type, so each issue's area (the
    # nearest area epic above it) is found without a read per issue. Only once
    # the project has an area epic at all: before that, every issue would be a
    # `no-area` gap with one cause, and `preflight` names it once as
    # `area-epics` instead.
    chain = wf_core.area_chain_map(issues, cfg.get('fields') or {})
    if not any(wf_core.is_area_stage(stage) for _, stage, _ in chain.values()):
        chain = None
    audited = [wf_core.audit_issue(issue, caps['field_map'],
                                   type_capable=caps['type_capable'],
                                   project_map=cfg.get('labels') or {},
                                   project_fields=cfg.get('fields') or {},
                                   open_numbers=open_numbers,
                                   type_map=caps.get('type_map') or {},
                                   parents=args.parents, chain=chain)
               for issue in issues]
    with_gaps = [a for a in audited if a['gaps']]
    summary = wf_core.audit_summary(audited)

    # Normalised because `repo_root()` comes back from git with forward
    # slashes and `os.path.join` adds the platform's, which produced a mixed
    # path the user then had to retype by hand.
    # An explicit `--out` is used exactly as the caller typed it, and needs no
    # repo lookup at all.
    root = None if args.out else repo_root()
    spec_path = os.path.normpath(
        args.out or os.path.join(root or '.', '.claude', AUDIT_SPEC_DEFAULT))
    wrote, write_err = (True, '')
    if with_gaps:
        wrote, write_err = write_audit_spec(spec_path,
                                            [a['proposed'] for a in with_gaps])

    # `spec_written` says whether a spec was written, so a clean run says
    # `false` rather than `true` beside a null path -- which read as "the file
    # is there" every time somebody checked whether the backfill had run.
    payload = {'repo': repo, 'summary': summary,
               'spec': spec_path if with_gaps else None,
               'spec_written': bool(with_gaps) and wrote}
    if not wrote:
        payload['write_error'] = write_err
    if not args.quiet:
        payload['issues'] = [{'number': a['number'], 'title': a['title'],
                              'gaps': a['gaps']} for a in with_gaps]

    if not with_gaps:
        emit('ok', EXIT_OK, reason='every open issue in %s carries its type, its '
                                   'field values, an owner and a place in the '
                                   'epic tree' % repo, **payload)

    # Non-zero so the audit can run as a check. The spec it just wrote is the
    # input to the backfill, but it is deliberately not applied here: every gap
    # it cannot fill deterministically is left as a placeholder for a person to
    # decide, and applying a spec full of `TODO` would write the blank metadata
    # this command exists to find.
    # The path is reported relative to the repo when it sits inside it: the
    # absolute form is long enough that printing it twice buried the counts
    # that are the actual result.
    shown = spec_path
    if root:
        try:
            relative = os.path.relpath(spec_path, root)
        except ValueError:
            relative = spec_path
        if not relative.startswith('..'):
            shown = relative
    emit('gaps', EXIT_GAPS,
         reason='%d of %d open issues in %s are missing metadata. Review %s, '
                'fill in every %s, then run: wf.sh issue-apply %s'
                % (summary['issues_with_gaps'], summary['issues_scanned'], repo,
                   shown, wf_core.SPEC_PLACEHOLDER, shown),
         **payload)
