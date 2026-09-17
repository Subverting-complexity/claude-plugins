#!/usr/bin/env python3
"""
wf — programmatic front door to the synergy selection/claim machinery.

Replaces the multi-step "read markdown, fire a dozen gh calls, reason about
the result" dance with a single process that does the whole mechanical job and
hands back one already-claimed work item as JSON. The decision rules live in
`wf_core.py` (pure, offline-testable); this file is the I/O shell that talks to
`gh` and `git`.

First cut implements the story picker:

    wf pick [--mode story] [--checkout]   # claim the next story, optionally branch
    wf unblock [--dry-run]                # release what the closed edges freed
    wf config                             # emit .claude/wf-config.json from ClaudeProject.md
    wf org-capabilities [--refresh]       # resolve the org's issue types + issue fields
    wf issue-apply <spec.json>            # create/update fully classified issues

Dependencies are read from GitHub's native `blockedBy` edges and written as
the same. Prose in an issue body is never parsed: a body naming a blocker with
no edge behind it is not blocked. The two used to be kept in step and were
not, disagreeing on most of the issues carrying both, with the prose stale
every time.

Contract:
  - A single JSON object is written to **stdout**; all human diagnostics go to
    **stderr**. A caller can parse stdout without stripping prose.
  - Every run's JSON carries a `status` field; the process exit code mirrors it:
      0  status=ok            an item was claimed (and checked out, if asked)
      2  status=usage         the arguments or the recorded bulk set were wrong
      10 status=no-candidates the ready pool was empty
      11 status=all-blocked   every candidate was blocked / already resolved
                              (also status=not-merged from post-merge)
      12 status=needs-refinement the next pick is too unclear to build
      20 status=error         environment/auth problem (not in a repo, no gh, …)
      21 status=no-capabilities an org that resolves but reports neither issue
                              types nor issue fields — a broken or under-scoped
                              token looks like this, an unconfigured org does not
      22 status=spec-invalid  the spec was refused before anything was written
      23 status=verify-failed a write was accepted but the read-back disagrees
      24 status=partial       some entries landed and some did not
      25 status=gaps          issue-audit found issues missing type or fields
      26 status=drift         config-audit or preflight found a blocking finding
      27 status=lost          another run holds the claim
      30 status=unsupported   this path isn't in the CLI yet — caller should
                              fall back to the inline skill procedure
  - Mutations to the *winning* issue (claim, assign, the In Progress move) are
    silent; mutations to *other* issues (marking blocked, closing resolved) are
    always reported back in the `side_effects` array.

Selection covers `--mode story` plus `--mode feature` / `--mode maintenance`,
on both label-typed and type-capable orgs. The pool is one thing on every
project: the unassigned open issues whose `Stage` is blank or `Backlog`. On a type-capable org,
feature/maintenance filter by the native `issueType` field via a single
GraphQL query instead of the `type-*` label; if the query fails, wf
falls back to label filtering gracefully. The selection rules themselves
live in `wf_core.py`.

Layout: this file is the entry point and nothing else. It builds the argument
parser and dispatches to a subcommand. The I/O shell lives in the `wf_*`
modules, one concern each, and the decision rules in the `wf_core_*` modules
behind `wf_core.py`; `scripts/README.md` has the module map. Every name those
shell modules define is re-exported here, so `wf.X` keeps working.
"""

import argparse
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wf_core  # noqa: E402
import wf_io  # noqa: E402
import wf_config  # noqa: E402
import wf_issue_io  # noqa: E402
import wf_capabilities  # noqa: E402
import wf_stage  # noqa: E402
import wf_board_sync  # noqa: E402
import wf_candidates  # noqa: E402
import wf_claim  # noqa: E402
import wf_deps  # noqa: E402
import wf_issue_apply  # noqa: E402
import wf_issue_audit  # noqa: E402
import wf_unblock  # noqa: E402
import wf_pick_tree  # noqa: E402
import wf_pick_select  # noqa: E402
import wf_pick_candidates  # noqa: E402
import wf_pick  # noqa: E402
import wf_plan  # noqa: E402
import wf_bulk_build  # noqa: E402
import wf_post_merge  # noqa: E402
import wf_review  # noqa: E402
import wf_preflight  # noqa: E402
import wf_steps  # noqa: E402
import wf_block  # noqa: E402
import wf_pr_create  # noqa: E402

_SHELL_MODULES = (
    wf_io,
    wf_config,
    wf_issue_io,
    wf_capabilities,
    wf_stage,
    wf_board_sync,
    wf_candidates,
    wf_claim,
    wf_deps,
    wf_issue_apply,
    wf_issue_audit,
    wf_unblock,
    wf_pick_tree,
    wf_pick_select,
    wf_pick_candidates,
    wf_pick,
    wf_plan,
    wf_bulk_build,
    wf_post_merge,
    wf_review,
    wf_preflight,
    wf_steps,
    wf_block,
    wf_pr_create,
)

for _module in _SHELL_MODULES:
    globals().update((name, value) for name, value in vars(_module).items()
                     if not name.startswith('__'))
del _module


class _Shell(types.ModuleType):
    """`wf` as one namespace for anything that assigns to one of its names.

    The shell used to be a single file, so replacing `wf.run` (as
    `mock.patch.object(wf, 'run', ...)` does) replaced it for every caller.
    Each shell module now holds its own binding of every name it defines or
    imports, so an assignment to `wf.X` is passed on to each shell module that
    binds `X`. Restoring the original, as `patch` does on exit, is an
    assignment too. Nothing in the CLI assigns to `wf`; this exists so the
    seam the offline tests patch is the same seam it was.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for module in _SHELL_MODULES:
            if name in vars(module):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _Shell

from wf_block import cmd_block
from wf_board_sync import SYNC_CLOSED_DAYS, cmd_board_sync
from wf_bulk_build import cmd_bulk_integrate, cmd_bulk_schedule
from wf_capabilities import cmd_org_capabilities
from wf_claim import cmd_claim, cmd_claim_reap, cmd_claim_release
from wf_config import cmd_config, cmd_scratch_clean
from wf_issue_apply import cmd_issue_apply
from wf_issue_audit import AUDIT_SPEC_DEFAULT, cmd_issue_audit
from wf_pick import cmd_pick, cmd_refine
from wf_pick_candidates import cmd_candidates
from wf_plan import cmd_bulk_mark, cmd_drop_group, cmd_drop_story, cmd_plan_set
from wf_post_merge import cmd_post_merge
from wf_pr_create import cmd_pr_create
from wf_preflight import cmd_config_audit, cmd_preflight
from wf_review import (
    cmd_handoff, cmd_labels_ensure, cmd_review_finish, cmd_review_next,
    cmd_sibling_pr, cmd_update_next,
)
from wf_stage import cmd_stage_set
from wf_steps import cmd_exit_cleanup, cmd_start, cmd_tree_clean
from wf_unblock import cmd_unblock


def build_parser():
    # `bug` is the documented shorthand for maintenance; main() maps it before
    # any command sees it, so selection only ever handles the three real modes.
    parser = argparse.ArgumentParser(prog='wf', description='synergy programmatic picker')
    sub = parser.add_subparsers(dest='command', required=True)

    pick = sub.add_parser('pick', help='claim the next story and return it as JSON')
    pick.add_argument('--mode', default='story', choices=MODE_CHOICES,
                      help='selection mode; feature and maintenance filter the pool '
                           "by the org's native issueType (bug is an alias for maintenance)")
    pick.add_argument('--issue', type=int, default=None,
                      help='target this specific issue instead of auto-selecting; runs the '
                           'same claim + validate machinery (auto-closes it if a merged PR '
                           'already resolved it)')
    pick.add_argument('--checkout', action='store_true',
                      help='also set Stage to In Progress and create/check out the branch')
    pick.add_argument('--no-branch', action='store_true',
                      help='with --checkout, set Stage but do not create or check out '
                           'a branch — for bulk runs where several stories share one branch '
                           'the caller creates')
    pick.add_argument('--max-effort', default=None, choices=['low', 'medium', 'high'],
                      help='skip anything the org has estimated larger than this. '
                           'An issue with no Effort value is always kept: a '
                           'ceiling is a statement about known size, not a '
                           'reason to hide unestimated work')
    pick.add_argument('--sibling', type=int, action='append', default=None,
                      help='an issue being built alongside this one on the same branch '
                           '(repeatable); a dependency on one of them does not block the '
                           'pick, because this run writes it too')
    pick.add_argument('--body', action='store_true',
                      help='include the issue body in the result (left out by default)')
    pick.add_argument('--unattended', action='store_true',
                      help='nobody is there to answer questions: an unclear issue '
                           'ahead of the pick is set to Needs refinement and passed '
                           'over, instead of stopping the run with needs-refinement')
    pick.set_defaults(func=cmd_pick)

    cand = sub.add_parser('candidates',
                          help='list the pick pool in priority order without claiming '
                               'anything (bulk-execute plans with plan-set instead)')
    cand.add_argument('--mode', default='story', choices=MODE_CHOICES,
                      help='selection mode, applied exactly as `pick` applies it')
    cand.add_argument('--max-effort', default=None, choices=['low', 'medium', 'high'],
                      help='skip anything the org has estimated larger than this. '
                           'An issue with no Effort value is always kept: a '
                           'ceiling is a statement about known size, not a '
                           'reason to hide unestimated work')
    cand.add_argument('--limit', type=int, default=25,
                      help='maximum candidates to list, highest priority first (default 25; '
                           '0 for all). `total` always reports the unclipped pool size')
    cand.add_argument('--body-chars', type=int, default=600,
                      help='truncate each body to this many characters (default 600; '
                           '0 for the whole body)')
    cand.add_argument('--parent', type=int, default=None,
                      help='the set `plan-set --parent` would choose under this '
                           'Epic or Feature: leaves in build order, '
                           'prerequisites outside the tree pulled in, within '
                           'the effort budget; everything else is listed in '
                           '`excluded` with its reason')
    cand.add_argument('--max-groups', type=int, default=wf_core.MAX_GROUPS,
                      choices=range(1, wf_core.MAX_GROUPS + 1),
                      help='with --parent, the most pull requests the set may '
                           'be split into (default %d)' % wf_core.MAX_GROUPS)
    cand.set_defaults(func=cmd_candidates)

    ps = sub.add_parser('plan-set',
                        help='choose a set of stories for one bulk run that fills '
                             'an effort budget of %d, split into pull requests, '
                             'in build order and waves; --claim claims it'
                             % wf_core.BULK_BUDGET)
    ps.add_argument('--issue', type=int, action='append', default=None,
                    help='a story the set must hold (repeatable); every open '
                         'prerequisite this run can build joins it')
    ps.add_argument('--parent', type=int, default=None,
                    help='choose from the stories under this Epic or Feature')
    ps.add_argument('--mode', default='story', choices=MODE_CHOICES,
                    help='selection mode, applied exactly as `pick` applies it')
    ps.add_argument('--max-effort', default=None, choices=['low', 'medium', 'high'],
                    help='skip anything the org has estimated larger than this')
    ps.add_argument('--max-groups', type=int, default=wf_core.MAX_GROUPS,
                    choices=range(1, wf_core.MAX_GROUPS + 1),
                    help='the most pull requests the set may be split into: 1 '
                         'when this run cannot start a separate reviewer '
                         '(default %d)' % wf_core.MAX_GROUPS)
    ps.add_argument('--body-chars', type=int, default=600,
                    help='truncate each body to this many characters (0 for all)')
    ps.add_argument('--claim', action='store_true',
                    help='claim, assign and set In Progress every story in the '
                         'plan, and record it in .claude/bulk-set.json')
    ps.set_defaults(func=cmd_plan_set)

    dr = sub.add_parser('drop-story',
                        help='return an unbuilt story in the bulk set to the pool, '
                             'with every unbuilt story waiting on it')
    dr.add_argument('--issue', type=int, required=True, help='the story to drop')
    dr.add_argument('--reason', required=True,
                    help='why, in a few words; it is commented on the issue')
    dr.set_defaults(func=cmd_drop_story)

    dg = sub.add_parser('drop-group',
                        help='return every story in one unbuilt group of the bulk '
                             'set to the pool, with every unbuilt story waiting '
                             'on one of them')
    dg.add_argument('--group', type=int, required=True, help='the group to drop')
    dg.add_argument('--reason', required=True,
                    help='why, in a few words; it is commented on each issue')
    dg.set_defaults(func=cmd_drop_group)

    bm = sub.add_parser('bulk-mark',
                        help="record a group's branch, or a story as built")
    bm.add_argument('--group', type=int, default=1,
                    help='the group whose branch --branch records (default 1)')
    bm.add_argument('--branch', default=None, help="the group's branch")
    bm.add_argument('--built', type=int, action='append', default=None,
                    help='a story now committed on the branch (repeatable)')
    bm.set_defaults(func=cmd_bulk_mark)

    bsc = sub.add_parser('bulk-schedule',
                         help="split each wave of one group of the bulk set into "
                              "batches that can be built in parallel, from the "
                              "files .claude/plan.md lists (no network)")
    bsc.add_argument('--group', type=int, default=1,
                     help='the group to schedule (default 1)')
    bsc.set_defaults(func=cmd_bulk_schedule)

    bi = sub.add_parser('bulk-integrate',
                        help="cherry-pick a wave's builder branches onto the shared "
                             'branch, push, mark them built and delete them')
    bi.add_argument('--group', type=int, default=1,
                    help='the group whose branch the wave lands on (default 1)')
    bi.add_argument('--wave', type=int, required=True, help='the wave to integrate')
    bi.add_argument('--keep-branches', action='store_true',
                    help='leave the temporary {branch}--{number} branches on the remote')
    bi.set_defaults(func=cmd_bulk_integrate)

    pm = sub.add_parser('post-merge',
                        help='settle a merged PR: close any still-open linked issue and '
                             'set every linked issue\'s Stage to Done')
    pm.add_argument('--pr', type=int, required=True, help='the merged PR number')
    pm.add_argument('--issue', type=int, action='append', default=None,
                    help='also settle this issue (repeatable) — for a reference GitHub did '
                         'not parse into closingIssuesReferences')
    pm.add_argument('--no-unblock', action='store_true',
                    help='settle the linked issues without running the unblock sweep '
                         'afterwards (the sweep is the half that releases whatever was '
                         'waiting on them, so skip it only when running it separately)')
    pm.set_defaults(func=cmd_post_merge)

    ub = sub.add_parser('unblock',
                        help='release every blocked issue whose native blocked-by '
                             'edges have all closed, and report the rest')
    ub.add_argument('--issue', type=int, action='append', default=None,
                    help='consider only this issue (repeatable); the default is every '
                         'open issue whose Stage is Blocked')
    ub.add_argument('--dry-run', action='store_true',
                    help='report what would be released without writing anything')
    ub.set_defaults(func=cmd_unblock)

    upd = sub.add_parser('update-next',
                         help='claim the next PR of mine that needs review feedback addressed')
    upd.add_argument('--checkout', action='store_true',
                     help='also check out the PR branch (gh pr checkout)')
    upd.set_defaults(func=cmd_update_next)

    rev = sub.add_parser('review-next', help='claim the next PR that needs reviewing')
    rev.add_argument('--checkout', action='store_true',
                     help='also check out the PR branch (gh pr checkout)')
    rev.add_argument('--no-claim', action='store_true',
                     help='select without pushing a claim ref or applying the '
                          'reviewing marker (read-only review, which has no push access)')
    rev.set_defaults(func=cmd_review_next)

    fin = sub.add_parser('review-finish',
                         help='reconcile a reviewed PR to exactly its verdict label '
                              '(strip stale state labels, readback-verify, create-if-missing)')
    fin.add_argument('--pr', type=int, required=True, help='the reviewed PR number')
    fin.add_argument('--verdict', required=True,
                     choices=list(wf_core.REVIEW_VERDICT_KEYS),
                     help='the review verdict; resolves to exactly one state label')
    fin.add_argument('--fixes-applied', action='store_true',
                     help='also ensure the sticky fixes-applied label is present '
                          '(set when Step 7 pushed fix commits)')
    fin.set_defaults(func=cmd_review_finish)

    le = sub.add_parser('labels-ensure',
                        help='create each review-state label the repo lacks '
                             '(guarded: never overwrites an existing label)')
    le.set_defaults(func=cmd_labels_ensure)

    cfg = sub.add_parser('config', help='emit .claude/wf-config.json from ClaudeProject.md')
    cfg.set_defaults(func=cmd_config)

    sc = sub.add_parser('scratch-clean',
                        help="delete this run's scratch files under .claude/ and "
                             "keep them in the clone's info/exclude (no network)")
    sc.set_defaults(func=cmd_scratch_clean)

    caps = sub.add_parser('org-capabilities',
                          help="resolve the org's enabled native issue types and its "
                               'issue fields (with option ids) into '
                               '.claude/issue-fields-cache.json')
    caps.add_argument('--refresh', action='store_true',
                      help='re-query the org instead of reading the cache')
    caps.set_defaults(func=cmd_org_capabilities)

    ia = sub.add_parser('issue-apply',
                        help='create or update fully classified issues from a spec file')
    ia.add_argument('spec', help='path to the JSON spec file')
    ia.add_argument('--repo', default=None,
                    help='apply against this owner/name instead of the configured repo')
    ia.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    ia.add_argument('--dry-run', action='store_true',
                    help='validate the spec and report what would be applied, '
                         'without writing anything')
    ia.set_defaults(func=cmd_issue_apply)

    au = sub.add_parser('issue-audit',
                        help='report open issues missing type, fields or '
                             'dependency edges, and write a backfill spec')
    au.add_argument('--repo', default=None,
                    help='audit this owner/name instead of the configured repo')
    au.add_argument('--limit', type=int, default=None,
                    help='stop after this many issues, newest first')
    au.add_argument('--since', default=None,
                    help='only issues updated since this ISO-8601 timestamp')
    au.add_argument('--out', default=None,
                    help='where to write the backfill spec '
                         '(default .claude/%s)' % AUDIT_SPEC_DEFAULT)
    au.add_argument('--parents', action='store_true',
                    help='also read the parent each body claims ("Part of the '
                         'X epic (#N)") and propose it where the issue has '
                         'none. Off by default: an issue created from a spec '
                         'already carries its parent, so this is for a backlog '
                         'written before that, or issues filed by hand')
    au.add_argument('--quiet', action='store_true',
                    help='report counts only, keeping the exit code, for CI')
    au.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    au.set_defaults(func=cmd_issue_audit)

    ca = sub.add_parser('config-audit',
                        help='report configuration and label drift between '
                             'ClaudeProject.md, the repo and the org')
    ca.add_argument('--repo', default=None,
                    help='audit this owner/name instead of the configured repo')
    ca.add_argument('--scan', action='append', default=None,
                    help='directory of instruction files to scan for label '
                         'references (repeatable; defaults to the plugin root)')
    ca.add_argument('--offline', action='store_true',
                    help='run only the checks that need no network')
    ca.add_argument('--quiet', action='store_true',
                    help='report counts only, keeping the exit code, for CI')
    ca.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    ca.set_defaults(func=cmd_config_audit)

    pf = sub.add_parser('preflight',
                        help='is this project in a state a workflow command '
                             'can run against? `--fix` repairs what can be '
                             'repaired without guessing')
    pf.add_argument('--fix', action='store_true',
                    help='repair every finding that has a safe automatic fix, '
                         'then re-run the checks and report what is left')
    pf.add_argument('--repo', default=None,
                    help='check this owner/name instead of the configured repo')
    pf.add_argument('--scan', action='append', default=None,
                    help='directory of instruction files to scan for label '
                         'references (repeatable; defaults to the plugin root)')
    pf.add_argument('--offline', action='store_true',
                    help='run only the checks that need no network')
    pf.add_argument('--quiet', action='store_true',
                    help='report counts only, keeping the exit code, for CI')
    pf.add_argument('--refresh', action='store_true',
                    help='re-query org capabilities instead of reading the cache')
    pf.set_defaults(func=cmd_preflight)

    rf = sub.add_parser('refine',
                        help='send a claimed issue back for refinement: Stage to '
                             'Needs refinement, the comment, unassign, release '
                             'the claim')
    rf.add_argument('--issue', type=int, required=True, help='issue number')
    rf.add_argument('--body-file', required=True,
                    help='the comment saying what a person must add')
    rf.set_defaults(func=cmd_refine)

    ss = sub.add_parser('stage-set',
                        help="set an issue's Stage field (exits 20 when the "
                             'write did not land)')
    ss.add_argument('number', type=int, help='issue number')
    ss.add_argument('--stage', required=True,
                    help='option name ("In Review") or purpose key (stage-in-review)')
    ss.set_defaults(func=cmd_stage_set)

    cl = sub.add_parser('claim',
                        help='take the atomic claim on a named issue or PR')
    cl.add_argument('--issue', type=int, default=None, help='issue number')
    cl.add_argument('--pr', type=int, default=None, help='PR number')
    cl.add_argument('--no-marker', dest='marker', action='store_false',
                    default=True,
                    help='take the lock without advertising it on GitHub '
                         '(assignment / reviewing label)')
    cl.add_argument('--keep-held', action='store_true',
                    help='keep a claim this checkout already holds (the PR '
                         'claim `handoff` took) instead of reporting it lost')
    cl.set_defaults(func=cmd_claim)

    cr = sub.add_parser('claim-release',
                        help='release the claim ref an interrupted run left behind')
    cr.add_argument('--issue', type=int, action='append', default=None,
                    help='issue number to release (repeatable)')
    cr.add_argument('--pr', type=int, action='append', default=None,
                    help='PR number to release (repeatable)')
    cr.set_defaults(func=cmd_claim_release)

    rp = sub.add_parser('claim-reap',
                        help='free claim refs a crashed run left behind')
    rp.add_argument('--threshold', type=int, default=wf_core.REAP_THRESHOLD_HOURS,
                    help='minimum age in hours before a ref may be reaped '
                         '(default %d)' % wf_core.REAP_THRESHOLD_HOURS)
    rp.add_argument('--dry-run', action='store_true',
                    help='report the verdicts without deleting any ref')
    rp.set_defaults(func=cmd_claim_reap)

    sp = sub.add_parser('sibling-pr',
                        help='list the open PRs that will close an issue')
    sp.add_argument('number', type=int, nargs='+',
                    help='issue number (several share one read; `by_issue` '
                         'answers each)')
    sp.add_argument('--exclude-branch', default=None,
                    help='drop the PR on this head branch (your own)')
    sp.set_defaults(func=cmd_sibling_pr)

    bs = sub.add_parser('board-sync',
                        help="add missing board cards and correct every "
                             "issue's Stage across the org (totals only)")
    bs.add_argument('--closed-days', type=int, default=SYNC_CLOSED_DAYS,
                    help='how far back to read closed issues, in days '
                         '(default %d; 0 reads every closed issue, which '
                         'corrects the Stage of one closed long ago)'
                         % SYNC_CLOSED_DAYS)
    bs.add_argument('--dry-run', action='store_true',
                    help='report what would change without writing anything')
    bs.set_defaults(func=cmd_board_sync)

    ho = sub.add_parser('handoff',
                        help='hand a finished story to review: label the PR, '
                             'set each issue to In Review, release the claim')
    ho.add_argument('--pr', type=int, required=True, help='the PR just opened')
    ho.add_argument('--issue', type=int, action='append', default=None,
                    help='issue the PR closes (repeatable)')
    ho.add_argument('--gate-failed', action='store_true',
                    help='the quality gate failed, so enter review as '
                         'changes-requested rather than needs-review')
    ho.set_defaults(func=cmd_handoff)

    st = sub.add_parser('start',
                        help='claim, stage, clean tree and branch before a build: '
                             '--issue N, or --group G --branch B for a bulk group')
    st.add_argument('--issue', type=int, default=None, help='the story to start')
    st.add_argument('--group', type=int, default=None, help='the bulk group to start')
    st.add_argument('--branch', default=None, help="with --group, the group's branch")
    st.set_defaults(func=cmd_start)

    ec = sub.add_parser('exit-cleanup',
                        help='end a run: release claims, reconcile a held review '
                             'claim, delete scratch files, report the tree')
    ec.add_argument('--issue', type=int, action='append', default=None,
                    help='issue claim to release (repeatable)')
    ec.add_argument('--bulk', action='store_true',
                    help='also release every story in .claude/bulk-set.json')
    ec.add_argument('--pr', type=int, default=None,
                    help="the run's PR; its review claim is reconciled and "
                         'released only when this checkout won it')
    ec.set_defaults(func=cmd_exit_cleanup)

    tc = sub.add_parser('tree-clean',
                        help='discard uncommitted paths the caller chose, then '
                             're-check the tree')
    tc.add_argument('--discard', action='append', default=None,
                    help='a path to discard (repeatable)')
    tc.add_argument('--all', action='store_true', help='discard every uncommitted path')
    tc.set_defaults(func=cmd_tree_clean)

    pc = sub.add_parser('pr-create',
                        help='push, flag duplicate PRs, open the PR and check its body')
    pc.add_argument('--title', required=True, help='the PR title')
    pc.add_argument('--body-file', required=True, help='the PR body')
    pc.add_argument('--issue', type=int, action='append', default=None,
                    help='an issue the PR closes (repeatable, at least one)')
    pc.add_argument('--base', default=None, help='base branch (default: the configured one)')
    pc.set_defaults(func=cmd_pr_create)

    bk = sub.add_parser('block',
                        help='block a story: comment, record the blocker, release, '
                             'unassign and set Blocked (or Non-code)')
    bk.add_argument('--issue', type=int, required=True, help='the story to block')
    bk.add_argument('--body-file', required=True, help='the blocker comment')
    bk.add_argument('--blocked-by', type=int, action='append', default=None,
                    help='an issue this one waits on (repeatable; the complete set)')
    bk.add_argument('--non-code', choices=['human', 'browser'], default=None,
                    help='the work needs a person or a browser agent: set '
                         'Ownership and Non-code instead of Blocked')
    bk.set_defaults(func=cmd_block)

    return parser


MODE_CHOICES = ['story', 'feature', 'maintenance', 'bug']


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, 'mode', None) == 'bug':
        args.mode = 'maintenance'
    args.func(args)


if __name__ == '__main__':
    main()
