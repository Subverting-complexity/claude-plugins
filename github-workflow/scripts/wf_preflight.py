"""
The `config-audit` and `preflight` subcommands: gather the live state, report
findings, and apply `--fix`.

Moved verbatim out of wf.py; `scripts/README.md` has the module map.
"""

import os
import re

import wf_core
from wf_capabilities import (
    fetch_issue_type_pins, fetch_repo_state, resolve_org_capabilities,
)
from wf_config import (
    _section, check_environment, config_paths, field_name, load_config,
    repo_root,
)
from wf_io import (
    EXIT_CAPABILITY, EXIT_DRIFT, EXIT_ENV, EXIT_OK, emit, gh_graphql, run,
)
from wf_issue_io import issue_field_values
from wf_post_merge import (
    _container_node, _fix_finished_containers, _fix_stage_drift,
)
from wf_review import ensure_review_labels


# ── config-audit ─────────────────────────────────────────────────────────────
# What preflight runs. It compares three things that drift apart quietly:
# `ClaudeProject.md`, the labels the repo actually carries, and the org's own
# issue-type and field configuration. Every check is read-only.
#
# The decisions all live in `wf_core`; this half fetches and reports. The API
# calls are deliberately few: one org query for the pinning, one repo query for
# the labels, one walk of the open issues, and the capability cache for the
# rest — so preflight stays cheap enough to run at the top of every session.


# Every open issue's labels, type and sub-issues, in one walk. The
# retired-label check needs the labels and the finished-container check (#240)
# needs the rest, and two paginated scans of the same issues is a round trip
# nobody gets back.
OPEN_ISSUE_STATE_QUERY = (
    'query($owner:String!,$repo:String!,$after:String){'
    ' repository(owner:$owner,name:$repo){ issues(states:OPEN,first:100,after:$after){'
    ' pageInfo { hasNextPage endCursor }'
    ' nodes { number title state issueType { name }'
    ' subIssues(first:100){ nodes { number state } }'
    ' labels(first:50){ nodes { name } }'
    ' assignees(first:1){ nodes { login } }'
    ' closedByPullRequestsReferences(first:10,includeClosedPrs:false){'
    '  nodes { state isDraft } }'
    ' issueFieldValues(first:50){ nodes {'
    '  ... on IssueFieldSingleSelectValue {'
    '   field { ... on IssueFieldSingleSelect { name } } name } } } } } } }'
)


def fetch_open_issue_state(cfg, repo=None):
    """What the label, container and stage checks need about the open issues.

    Returns (ok, labelled, finished, drifted, err) -- every open issue that
    carries any label at all, every open Epic or Feature whose sub-issues are
    all closed (`{'number', 'title'}`), and every issue whose `Stage` says it is
    available while an assignee or an open pull request says the work has
    started (`{'number', 'title', 'stage'}`, `stage` being the purpose key it
    belongs in).

    Nothing here asks whether an issue is on a board. It used to, because the
    pool was a board column and an issue with no card could not be picked;
    since 12.0.0 an issue holds its own state, so a missing card hides nothing.
    """
    owner, name = (repo or '%s/%s' % (cfg['org'], cfg['repo'])).split('/', 1)
    stage_field = field_name(cfg, 'field-stage')
    labelled, finished, drifted, cursor = [], [], [], None
    while True:
        fields = {'owner': owner, 'repo': name}
        if cursor:
            fields['after'] = cursor
        ok, data, err = gh_graphql(OPEN_ISSUE_STATE_QUERY, **fields)
        if not ok or not data:
            return False, None, None, None, err
        page = ((data.get('repository') or {}).get('issues')) or {}
        for node in page.get('nodes') or []:
            names = [n['name'] for n
                     in (node.get('labels') or {}).get('nodes') or []
                     if n.get('name')]
            if names:
                labelled.append({'number': node['number'], 'labels': names})
            if wf_core.container_finished(_container_node(node)):
                finished.append({'number': node['number'],
                                 'title': node.get('title') or ''})
            prs = [pr for pr in ((node.get('closedByPullRequestsReferences')
                                  or {}).get('nodes') or [])
                   if pr and (pr.get('state') or '').upper() == 'OPEN']
            target = wf_core.stage_drift_target(
                issue_field_values(node).get(stage_field),
                assigned=bool((node.get('assignees') or {}).get('nodes')),
                open_prs=prs)
            if target:
                drifted.append({'number': node['number'],
                                'title': node.get('title') or '',
                                'stage': target})
        info = page.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return True, labelled, finished, drifted, ''
        cursor = info.get('endCursor')


def plugin_scan_roots(explicit=None):
    """Where to look for files that tell an agent to apply a label.

    Defaults to the plugin this script ships in — `CLAUDE_PLUGIN_ROOT` at
    runtime, the script's own plugin directory otherwise, which is what makes
    the check work in this repo's own checkout.
    """
    if explicit:
        return [os.path.abspath(r) for r in explicit]
    env = os.environ.get('CLAUDE_PLUGIN_ROOT')
    if env and os.path.isdir(env):
        return [os.path.abspath(env)]
    return [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]


# The instruction files a session actually reads before it does anything: the
# project's own `CLAUDE.md` at any depth, and `ClaudeProject.md` beside it.
# Deliberately not every markdown file in the repo -- a design note describing
# what `Ready` used to be is history somebody wrote on purpose, while a
# `CLAUDE.md` saying the same thing is an instruction a session will follow.
INSTRUCTION_FILE_NAMES = ('CLAUDE.md', 'ClaudeProject.md')
INSTRUCTION_SCAN_MAX = 200


def read_instruction_files(root, exclude=()):
    """Every instruction file under `root`, as {relative path: text}.

    `exclude` is the plugin's own directory, which only sits inside the project
    in the plugin's own repository. Its templates are the plugin describing the
    workflow -- including naming what it retired, so a project knows to drop
    it -- and they are held to the plugin's own test suite rather than to a
    check about the project's instructions. Found live: the shipped
    `ClaudeProject.md` template was reported for the sentence telling projects
    that the retired labels decide nothing.
    """
    skip = {os.path.normcase(os.path.abspath(p)) for p in exclude or ()}
    out = {}
    for dirpath, dirnames, filenames in os.walk(root or '.'):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith('.') and d != 'node_modules'
                       and os.path.normcase(os.path.abspath(
                           os.path.join(dirpath, d))) not in skip]
        for name in INSTRUCTION_FILE_NAMES:
            if name not in filenames:
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding='utf-8') as fh:
                    text = fh.read()
            except OSError:
                continue
            out[os.path.relpath(path, root or '.').replace(os.sep, '/')] = text
        if len(out) >= INSTRUCTION_SCAN_MAX:
            return out
    return out


def scan_plugin_labels(roots, base=None):
    """Every concrete label the instruction files under `roots` apply."""
    references = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith('.') and d != 'node_modules']
            for name in sorted(filenames):
                if not name.endswith('.md'):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path, encoding='utf-8') as fh:
                        text = fh.read()
                except OSError:
                    continue
                rel = os.path.relpath(path, base or root).replace(os.sep, '/')
                for ref in wf_core.scan_label_references(text):
                    references.append(dict(ref, file=rel))
    return references


def cmd_config_audit(args):
    ok, cfg, err = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=err)
    findings, checked, skipped, _ = collect_config_findings(
        cfg, args, repo_root() or '.')
    return _emit_audit(findings, checked, skipped, cfg, args)


def collect_config_findings(cfg, args, root):
    """Every drift finding, plus the live state a `--fix` would need.

    Split out of `cmd_config_audit` so that `preflight` runs exactly the same
    checks rather than a second implementation of them. Returns
    `(findings, checked, skipped, context)`; `context` carries the open-issue
    lists so a repair does not have to re-read them.

    Error paths still `emit()` and exit, because a run that cannot read the org
    has not found a clean configuration -- it has found nothing.
    """
    source = config_paths(root)[1]
    source_rel = os.path.basename(source)

    findings, checked, skipped = [], [], []
    context = {'retired_labels': []}

    # ── offline ──────────────────────────────────────────────────────────────
    headings = []
    if os.path.isfile(source):
        with open(source, encoding='utf-8') as fh:
            headings = re.findall(r'^#{1,3}\s+(.+?)\s*$', fh.read(), re.MULTILINE)
    findings.extend(wf_core.config_section_findings(headings, source_rel))
    checked.append('config-section')

    # Retired vocabulary in the project's own instructions. Offline, and worth
    # running first: a `CLAUDE.md` telling a session to look for a `Ready` label
    # sends it to do work no amount of correct field configuration will make
    # right.
    roots = plugin_scan_roots(args.scan)
    findings.extend(wf_core.instruction_findings(
        read_instruction_files(root, exclude=roots)))
    checked.append('instructions-retired')

    references = scan_plugin_labels(roots, base=root)
    checked.append('label-reference')

    if args.offline:
        skipped = ['label-reference', 'config-label', 'review-label', 'label-drift',
                   'field-unpinned', 'field-unmapped', 'field-absent',
                   'field-options', 'stage-absent', 'stage-options',
                   'label-retired', 'container-finished', 'stage-drift']
        return findings, ['config-section', 'instructions-retired'], skipped, context

    # ── the repo: labels ─────────────────────────────────────────────────────
    ok, state, err = fetch_repo_state(cfg, args.repo)
    if not ok:
        emit('error', EXIT_ENV, repo='%s/%s' % (cfg['org'], cfg['repo']),
             reason='could not read the repo\'s labels: %s' % err)
    live = state['labels']

    findings.extend(wf_core.label_reference_findings(references, live,
                                                     cfg.get('labels')))
    findings.extend(wf_core.config_label_findings(
        cfg.get('labels'), live, source_rel))
    findings.extend(wf_core.review_label_findings(
        wf_core.review_names(cfg.get('review_labels')), live))
    findings.extend(wf_core.label_drift_findings(live, cfg.get('labels')))
    findings.extend(wf_core.deprecated_label_findings(
        cfg.get('labels'), live, source_rel))
    checked.extend(['config-label', 'review-label', 'label-drift',
                    'label-deprecated'])
    context['labels'] = live

    # One walk of the open issues answers three questions: which still carry a
    # label that decides nothing, which Epic or Feature is finished with
    # nothing having closed it (#240), and which issue's `Stage` still says it
    # is available after the work on it started.
    ok, labelled, finished, drifted, err = fetch_open_issue_state(cfg, args.repo)
    if not ok:
        findings.append(wf_core.finding(
            wf_core.WARNING, 'label-retired',
            'could not read the open issues (%s), so whether any still carry a '
            'retired label, are a finished Epic or Feature, or have a `Stage` '
            'behind their work is unverified' % err,
            'check the token and re-run', source_rel))
        skipped.extend(['label-retired', 'container-finished', 'stage-drift'])
    else:
        findings.extend(wf_core.retired_label_findings(
            labelled, cfg.get('labels'), source_rel))
        findings.extend(wf_core.finished_container_findings(finished, source_rel))
        findings.extend(wf_core.stage_drift_findings(drifted, source_rel))
        checked.extend(['label-retired', 'container-finished', 'stage-drift'])
        context['retired_labels'] = labelled
        context['finished_containers'] = finished
        context['stage_drift'] = drifted

    # ── the org: field pinning, and fields nothing maps ──────────────────────
    ok, caps, err = resolve_org_capabilities(cfg, refresh=args.refresh)
    if not ok:
        emit('error', EXIT_ENV, reason=err, org=cfg['org'])
    if caps.get('denied'):
        emit('no-capabilities', EXIT_CAPABILITY, org=cfg['org'],
             denied=caps['denied'],
             reason='the authenticated account may not read %s for this org, so '
                    'the org half of the configuration cannot be checked'
                    % ' and '.join(caps['denied']))

    findings.extend(wf_core.unmapped_field_findings(caps['field_map'],
                                                    cfg.get('fields'), source_rel))
    checked.append('field-unmapped')

    # Options on a mandatory field that no decision here knows. This fails
    # silently otherwise: every issue carrying an unrecognised value sorts last.
    findings.extend(wf_core.field_option_findings(
        caps['field_map'], cfg.get('fields'), source_rel))
    checked.append('field-options')

    # A mandatory field the org has not created is the failure every other
    # check here assumes away: the picker reads these five and nothing else,
    # so a missing one is a decision with no input rather than a degraded one.
    findings.extend(wf_core.absent_field_findings(
        caps['field_map'] or {}, cfg.get('fields'), source_rel))
    checked.append('field-absent')

    # `Stage` is where every issue's state lives, so a missing field or a
    # missing option is a transition that fails at GitHub.
    findings.extend(wf_core.stage_findings(
        caps['field_map'] or {}, cfg.get('fields'), source_rel))
    checked.extend(['stage-absent', 'stage-options'])

    if caps['type_capable']:
        # Only the fields the org actually defines. A field nobody has created
        # cannot be pinned to anything, and reporting five types as "not
        # pinned to Ownership" the day that field joined the mandatory set says
        # nothing about the org and buries the findings that do. `Stage` is
        # checked beside the mandatory fields because every transition writes
        # it, and a value on an unpinned field is invisible on the issue form.
        defined = caps['field_map'] or {}
        required = [name for name in
                    (field_name(cfg, k) for k
                     in tuple(wf_core.MANDATORY_FIELD_KEYS) + ('field-stage',))
                    if name in defined]
        ok, types, err = fetch_issue_type_pins(cfg)
        if ok:
            findings.extend(wf_core.pinned_field_findings(types, required))
            checked.append('field-unpinned')
        else:
            # Not knowing is not the same as being fine, and reporting it as a
            # pass would recreate the silent blank this command exists to catch.
            findings.append(wf_core.finding(
                wf_core.WARNING, 'pin-unknown',
                'could not read `IssueType.pinnedFields` for %s (%s), so whether '
                'the tooling\'s fields appear on an issue form is unverified'
                % (cfg['org'], err),
                'check the token carries `read:org`, then re-run'))
            skipped.append('field-unpinned')
    else:
        skipped.append('field-unpinned')

    return findings, checked, skipped, context


def _emit_audit(findings, checked, skipped, cfg, args):
    summary = wf_core.preflight_summary(findings)
    payload = {'org': cfg['org'], 'repo': args.repo or '%s/%s' % (cfg['org'],
                                                                  cfg['repo']),
               'summary': summary, 'checked': checked, 'skipped': skipped}
    if not args.quiet:
        payload['findings'] = findings

    if summary['critical']:
        emit('drift', EXIT_DRIFT,
             reason='%d configuration problem%s will produce wrong behaviour, '
                    'and %d more will degrade it'
                    % (summary['critical'], '' if summary['critical'] == 1 else 's',
                       summary['warning']),
             **payload)
    if summary['warning']:
        # Warnings alone exit zero: they describe a workflow that still does the
        # right thing, and a preflight that blocks on them would train everyone
        # to skip it.
        emit('ok', EXIT_OK,
             reason='no configuration problem will produce wrong behaviour; %d '
                    'will degrade it' % summary['warning'], **payload)
    if skipped:
        # Never report agreement between things this run did not compare.
        emit('ok', EXIT_OK,
             reason='nothing wrong in the %d check%s that ran; %s did not run'
                    % (len(checked), '' if len(checked) == 1 else 's',
                       ', '.join(sorted(set(skipped)))), **payload)
    emit('ok', EXIT_OK,
         reason='ClaudeProject.md, the repo\'s labels and the org\'s issue '
                'configuration agree', **payload)


# ── preflight ────────────────────────────────────────────────────────────────
# `config-audit` answers "does ClaudeProject.md agree with the live repo
# and org?". `preflight` answers the question a command actually has before it
# runs: "can this project be worked on at all?" -- which is that, plus the
# file-level checks, plus a `--fix` that repairs the subset a run can repair
# without guessing.
#
# Those file-level checks used to be shell blocks inside
# `skills/preflight/SKILL.md`. Two implementations of one gate is one too many:
# the shell one could not be tested, could not be reused by `bulk-execute`, and
# quietly disagreed with this one about what counted as critical.

_FENCE_RE = re.compile(r'```[a-zA-Z0-9_+-]*\n(.*?)```', re.DOTALL)


def quality_gate_command(text):
    """The command inside the `## Quality Gate` fenced block, or ''."""
    match = _FENCE_RE.search(_section(text, 'Quality Gate'))
    if not match:
        return ''
    for line in match.group(1).splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            return line
    return ''


_REVIEW_CONFIG_RE = re.compile(r'[A-Za-z0-9._/-]*review\.config\.md')


def review_config_reference(text):
    """The review-state label file `ClaudeProject.md` points at, or None."""
    match = _REVIEW_CONFIG_RE.search(text or '')
    return match.group(0) if match else None


def _config_file_findings(root, source_rel, text):
    """Everything preflight reads out of the two markdown files themselves."""
    findings = []
    headings = re.findall(r'^#{1,3}\s+(.+?)\s*$', text, re.MULTILINE)
    findings.extend(wf_core.retired_section_findings(headings, source_rel))
    findings.extend(wf_core.placeholder_findings(text, source_rel))
    findings.extend(wf_core.quality_gate_findings(quality_gate_command(text),
                                                  source_rel))

    claude_md = os.path.join(root, 'CLAUDE.md')
    exists = os.path.isfile(claude_md)
    references = False
    if exists:
        with open(claude_md, encoding='utf-8') as fh:
            references = 'ClaudeProject.md' in fh.read()
    findings.extend(wf_core.claude_md_findings(exists, references))

    referenced = review_config_reference(text)
    if referenced:
        findings.extend(wf_core.review_config_findings(
            referenced, os.path.isfile(os.path.join(root, referenced)),
            source_rel))
    return findings


def _fix_config_file(root, source, findings):
    """Repairs that rewrite `ClaudeProject.md`. Returns a list of descriptions."""
    with open(source, encoding='utf-8') as fh:
        original = fh.read()
    text, done = original, []

    retired = [f for f in findings if f['check'] == 'config-retired']
    if retired:
        text, removed = wf_core.strip_sections(
            text, sorted(wf_core.RETIRED_CONFIG_SECTIONS))
        for name in removed:
            done.append('deleted the `## %s` section from ClaudeProject.md' % name)

    deprecated = [f for f in findings if f['check'] == 'label-deprecated']
    if deprecated:
        purposes = sorted(wf_core.RETIRED_LABELS)
        text, removed = wf_core.strip_label_map_rows(text, purposes)
        for name in removed:
            done.append('deleted the `%s` row from the label map' % name)

    if text != original:
        with open(source, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
    return done


def _fix_claude_md(root):
    """Point an existing CLAUDE.md at ClaudeProject.md. Never creates one."""
    path = os.path.join(root, 'CLAUDE.md')
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    updated, changed = wf_core.add_config_pointer(text)
    if not changed:
        return []
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(updated)
    return ['added a ClaudeProject.md pointer to CLAUDE.md']


def _fix_retired_labels(cfg, labelled, repo=None):
    """Take every retired label off the open issues still carrying one.

    The only write this command makes to an issue's own content, and it is safe
    because the labels decide nothing: `pick` and `unblock` read fields now. What a stale label still does is mislead a person filtering the
    issues list by hand, which is why it is worth removing rather than leaving
    for the write path to clear one issue at a time.
    """
    repo = repo or '%s/%s' % (cfg['org'], cfg['repo'])
    project_map = cfg.get('labels')
    cleared, failed, names = [], [], set()
    for issue in labelled or ():
        stale = wf_core.retired_label_variants(issue.get('labels'), project_map)
        if not stale:
            continue
        args = []
        for name in stale:
            args.extend(['--remove-label', name])
        code, _out, err = run(['gh', 'issue', 'edit', str(issue['number']),
                               '--repo', repo] + args)
        if code != 0:
            failed.append('#%s (%s)' % (issue['number'],
                                        (err or '').strip() or 'edit failed'))
            continue
        cleared.append(issue['number'])
        names.update(stale)
    done, blocked = [], []
    if cleared:
        done.append('took %s off %d issue%s'
                    % (wf_core._names(sorted(names)), len(cleared),
                       '' if len(cleared) == 1 else 's'))
    if failed:
        blocked.append('could not clear the retired labels on %s'
                       % ', '.join(failed))
    return done, blocked


def cmd_preflight(args):
    """Is this project in a state a workflow command can run against?

    One command, one JSON object, one exit code — 0 when nothing critical is
    wrong, 26 when something is. `--fix` repairs the subset that can be
    repaired without guessing (`wf_core.FIXABLE_CHECKS`) and re-runs the checks
    afterwards, so what it reports is the state it leaves behind rather than
    the state it found.
    """
    root = repo_root() or '.'
    source = config_paths(root)[1]
    source_rel = os.path.basename(source)

    findings, checked, skipped = [], [], []

    err = check_environment()
    if err:
        findings.append(wf_core.finding(
            wf_core.CRITICAL, 'gh-auth',
            'the GitHub CLI cannot act for this repository (%s)' % err,
            'run `gh auth login`, and run this from inside the repository'))
    checked.append('gh-auth')

    if not os.path.isfile(source):
        findings.append(wf_core.finding(
            wf_core.CRITICAL, 'file-config',
            'there is no %s at %s, so every value the workflow reads is a '
            'default nobody chose' % (source_rel, root),
            'run `/github-workflow:setup`', source_rel))
        return _emit_preflight(findings, checked + ['file-config'],
                               ['config-section'], None, args, [], [])

    checked.append('file-config')
    with open(source, encoding='utf-8') as fh:
        text = fh.read()
    findings.extend(_config_file_findings(root, source_rel, text))
    checked.extend(['config-retired', 'placeholders', 'quality-gate',
                    'claude-md-ref', 'review-config'])

    ok, cfg, cerr = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=cerr)

    audit, audit_checked, audit_skipped, context = collect_config_findings(
        cfg, args, root)
    findings.extend(audit)
    checked.extend(audit_checked)
    skipped.extend(audit_skipped)

    if not args.fix:
        return _emit_preflight(findings, checked, skipped, cfg, args, [], [])

    fixable, _ = wf_core.fix_plan(findings)
    if not fixable:
        return _emit_preflight(findings, checked, skipped, cfg, args, [], [])

    done, blocked = [], []
    done.extend(_fix_config_file(root, source, fixable))
    done.extend(_fix_claude_md(root))
    if not args.offline:
        label_done, label_blocked = _fix_retired_labels(
            cfg, context.get('retired_labels'), args.repo)
        done.extend(label_done)
        blocked.extend(label_blocked)
        container_done, container_blocked = _fix_finished_containers(
            cfg, context.get('finished_containers'))
        done.extend(container_done)
        blocked.extend(container_blocked)
        drift_done, drift_blocked = _fix_stage_drift(
            cfg, context.get('stage_drift'))
        done.extend(drift_done)
        blocked.extend(drift_blocked)
        if any(f['check'] == 'review-label' for f in fixable):
            created, failed, lerr = ensure_review_labels(
                cfg, context.get('labels'), args.repo)
            done.extend('created the `%s` label' % name for name in created)
            blocked.extend('could not create the %s label' % f for f in failed)
            if lerr:
                blocked.append("could not read the repo's labels (%s)" % lerr)

    # Re-run against the state the repairs left behind, so the findings a
    # person reads are the ones that are still true. A `--fix` that reported
    # what it found rather than what it left would make the second run of an
    # idempotent command look like it had done nothing.
    ok, cfg, cerr = load_config()
    if not ok:
        emit('error', EXIT_ENV, reason=cerr)
    with open(source, encoding='utf-8') as fh:
        text = fh.read()
    findings = [f for f in findings if f['check'] in ('gh-auth', 'file-config')]
    findings.extend(_config_file_findings(root, source_rel, text))
    audit, audit_checked, audit_skipped, _ = collect_config_findings(
        cfg, args, root)
    findings.extend(audit)
    return _emit_preflight(findings, checked, skipped, cfg, args, done, blocked)


def _emit_preflight(findings, checked, skipped, cfg, args, fixed, blocked):
    summary = wf_core.preflight_summary(findings)
    payload = {'summary': summary, 'checked': sorted(set(checked)),
               'skipped': sorted(set(skipped))}
    if cfg:
        payload['org'] = cfg.get('org')
        payload['repo'] = '%s/%s' % (cfg.get('org'), cfg.get('repo'))
    if not args.quiet:
        payload['findings'] = [
            dict(f, fixable=wf_core.FIXABLE_CHECKS.get(f['check'])
                 or wf_core.unfixable_reason(f['check']),
                 auto=f['check'] in wf_core.FIXABLE_CHECKS)
            for f in findings]
    if args.fix:
        payload['fixed'] = fixed
        payload['unfixed'] = blocked

    if summary['critical']:
        emit('blocked', EXIT_DRIFT,
             reason='%d problem%s stop%s a workflow command from running '
                    'correctly here%s'
                    % (summary['critical'],
                       '' if summary['critical'] == 1 else 's',
                       's' if summary['critical'] == 1 else '',
                       '' if not summary['warning']
                       else '; %d more will degrade it' % summary['warning']),
             **payload)
    emit('ok', EXIT_OK,
         reason=('nothing blocks a workflow command'
                 + ('' if not summary['warning']
                    else '; %d thing%s will run on a default'
                    % (summary['warning'],
                       '' if summary['warning'] == 1 else 's'))),
         **payload)
