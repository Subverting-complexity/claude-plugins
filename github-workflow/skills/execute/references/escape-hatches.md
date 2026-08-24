# Execute — Escape hatches

Read this file when one of the escape conditions named in the `execute`
`SKILL.md` is hit. These are rare, off-the-happy-path branches, so they are
kept out of the main body to keep the pick/plan/build window light. Each
heading below is one condition; jump to the one that fired.

## Failure reporting

If execution fails at any phase and cannot recover, leave a structured
comment on the issue before exiting. Write the comment body to a temporary
file and post using `--body-file` (avoids Windows shell-escaping issues):

```
gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
```

The comment should include: phase name, error summary, branch name,
whether commits were pushed, what was completed, and what remains.
Delete the temp file after.

Then move the issue to the `status-needs-attention` lifecycle label
(removing `status-in-progress` so exactly one state is present, resolved
by purpose key) so the failure is visible in the issues list. Do **not**
open a PR for failed/incomplete work.

**Once the PR is open (Phase 8 onward), do not move the issue backwards.**
Phase 7 already set `status-in-review` and moved the board to In Review, and
the open, labelled PR is the visible record of the work. Comment the failure
on the **PR** instead, leave the issue at `status-in-review`, and let the
next `/github-workflow:code-review` run take it from there. Moving it to
`status-needs-attention` would desynchronise the lifecycle label, the board,
and the PR's review state.

This ensures the next session (or human) can pick up exactly where
this one failed without guessing what happened. After the comment is
posted, run **Exit cleanup** (`references/exit-cleanup.md` — it releases
the claim ref so the issue can be picked again) before exiting.

## Blocked

If any phase cannot proceed, run `/github-workflow:block-story`
with details (it releases the claim for you), then run **Exit cleanup**
(`references/exit-cleanup.md`; the claim release is a no-op at this
point). Then pick the next story.

## Problem found (unrelated to this story)

This hatch is for problems **outside** the change this run is making, and
`SKILL.md`'s **Fix in scope, file out of scope** rule decides which those
are before this hatch does: a problem in this story's own diff is fixed here
on the branch, whether it surfaced during the build or in a review round,
and never filed.

What reaches this hatch is the rest: a pre-existing bug in code you did not
touch, a security flaw, a layering or architecture violation, or tech debt
belonging to other work. File it to the board so it is fixed automatically.
Run `/github-workflow:report-issue` (autonomous — do not pause for
confirmation). **No human approval is needed**: it classifies the problem,
applies the **actual issue type** (bug, security, architecture, or tech
debt) and priority, sets `status-ready`, and places it on the board so the
normal pickup flow fixes it. Do not fix it inline unless it is trivial and
within the same scope — an unrelated fix widens the diff the reviewers have
to judge. When you report what you did this session, name each filed item by
its actual type and number (e.g. "Filed bug #45", "Filed tech-debt #46").

## Dependency

If this story depends on another unmerged story (discovered during
planning, not caught by the Phase 1 filter), there is **one** rule —
chaining is only allowed when the dependency's branch is already
published; otherwise block:

- **Dependency branch exists on the remote** (the other story is in
  review or in progress and has pushed): you can chain off it.
  1. Branch the dependent story off the dependency branch.
  2. Set the dependent PR's base to the dependency branch.
  3. After the dependency merges, rebase onto the default branch and
     update the PR base.
- **Dependency branch does not exist on the remote** (not started, or
  started but unpushed — you cannot build on what you cannot fetch):
  do **not** fork a parallel copy. Block this story
  (`/github-workflow:block-story`, recording `Blocked by #N`) and pick
  the dependency — or the next available story — instead.

This is the same policy the Phase 1 dependency filter enforces (skip a
dependent story while its dependency issue is open): chaining is the
narrow exception for a dependency that is already pushed, not a parallel
route around an unfinished one.

## Story too broad

If the story covers multiple distinct changes and needs to be broken into
sub-stories before implementation can begin, run
`/github-workflow:feature-discovery` to plan the breakdown with the user,
then pick the first sub-story.

## Review feedback

Review feedback is no longer an escape hatch: Phases 8 and 9 review the
PR in a fresh context and answer the findings inside this same run
(`references/review-and-merge.md`). Feedback that arrives **after** the run
ends — a human reviewer's comment, or a rework round the session budget cut
short — is picked up by the next `/github-workflow:code-review` invocation,
which selects the `changes-requested` PR automatically, addresses the
feedback, and re-reviews. No separate command is needed for it.

## Story too large

If the plan reveals the story exceeds one session's budget, implement the
highest-priority slice, open a PR for that slice, and create follow-up
issues for the remaining work using `/github-workflow:report-issue`. Do not
attempt to complete everything in one session — a partial PR with clear
notes is the expected outcome. Run **Exit cleanup**
(`references/exit-cleanup.md`; opening the PR already released the claim)
before exiting.
