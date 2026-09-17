# Execute — Escape hatches

Read this file when one of the escape conditions named in the `execute` `SKILL.md` is hit. These are rare, off-the-happy-path branches, so they are kept out of the main body to keep the pick/plan/build window light. Each heading below is one condition; jump to the one that fired.

## Failure reporting

If execution fails at any phase and cannot recover, leave a structured comment on the issue before exiting. Write the comment body to a temporary file and post using `--body-file` (avoids Windows shell-escaping issues):

```
gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
```

The comment should include: phase name, error summary, branch name, whether commits were pushed, what was completed, and what remains. Delete the temp file after.

Then run `wf stage-set {number} --stage stage-attention` so the failure is visible on the issue — the stage is the issue's state, so this is what stops the next run picking it up as available. If it exits non-zero, report "Stage update failed: {reason}. Continuing." Do **not** open a PR for failed/incomplete work.

**Once the PR is open (Phase 8 onward), do not move the issue backwards.** Phase 7 already set the stage to `In Review`, and the open, labelled PR is the visible record of the work. Comment the failure on the **PR** instead, leave the stage at `In Review`, and let the next `/synergy:pr-review` run take it from there. Setting it to `Needs attention` would put the stage and the PR's review state at odds.

This ensures the next session (or human) can pick up exactly where this one failed without guessing what happened. After the comment is posted, run **Exit cleanup** (`references/exit-cleanup.md` — it releases the claim ref so the issue can be picked again) before exiting.

## Auto-mode denial

If auto mode denies Phase 8 step 5's label call as `Self-Approval`, or Phase 10's merge as `Merge Without Review`, do not retry, reword the command or reach the API another way. Those are built-in auto-mode rules that only a machine's user settings can relax. After a denied label, leave the PR open with the verdict comment on it, skip Phase 10, and run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr {pr_number} --verdict needs-re-review`, as `merge.md` does for a merge that stops short: **Exit cleanup** would otherwise turn a leftover `reviewing` marker into `changes-requested`. After a denied merge, handle it as `merge.md` handles an attempt that stops short. Either way run **Exit cleanup**, and in the final report say which call was denied and that `docs/rationale/builder-tools-rationale.md` in the plugin's source repository gives the `autoMode.allow` entry that lets a run finish.

## Blocked

If any phase cannot proceed, run `/synergy:block-story` with details (it releases the claim for you), then run **Exit cleanup** (`references/exit-cleanup.md`; the claim release is a no-op at this point) and exit. One run builds one story, so the next story is the next run's.

## Problem found (unrelated to this story)

This hatch is for problems **outside** the change this run is making, and the **Fix in scope, file out of scope** rule in `shared-phases.md` decides which those are before this hatch does: a problem in this story's own diff is fixed here on the branch, whether it surfaced during the build or in a review round, and never filed.

What reaches this hatch is the rest: a pre-existing bug in code you did not touch, a security flaw, a layering or architecture violation, or tech debt belonging to other work. File it to the backlog so it is fixed automatically. Run `/synergy:report-issue` (autonomous — do not pause for confirmation). **No human approval is needed**: it classifies the problem, applies the **actual issue type** (bug, security, architecture, or tech debt), sets `Priority`, `Effort` and `Ownership`, and gives it the `Backlog` stage, which is what makes the normal pickup flow fix it. Do not fix it inline unless it is trivial and within the same scope — an unrelated fix widens the diff the reviewers have to judge. When you report what you did this session, name each filed item by its actual type and number (e.g. "Filed bug #45", "Filed tech-debt #46").

## Dependency

If this story depends on another unmerged story (discovered during planning, not caught by the Phase 1 filter), there is **one** rule — chaining is only allowed when the dependency's branch is already published; otherwise block:

- **Dependency branch exists on the remote** (the other story is in review or in progress and has pushed): you can chain off it.
  1. Branch the dependent story off the dependency branch.
  2. Set the dependent PR's base to the dependency branch.
  3. After the dependency merges, rebase onto the default branch and update the PR base.
- **Dependency branch does not exist on the remote** (not started, or started but unpushed — you cannot build on what you cannot fetch): do **not** fork a parallel copy. Block this story with `/synergy:block-story`, recording the dependency as a native blocked-by edge (a one-entry `issue-apply` spec, `{"issues": [{"number": {this}, "blocked_by": [{dependency}]}]}`), never as a sentence in the body: the edge is what `wf unblock` reads when the dependency closes. Then run **Exit cleanup** and exit. The next `pick --issue {this}` builds the dependency first, because a named story's open prerequisites are claimed before it.

## Story too broad

If the story covers multiple distinct changes and needs to be broken into sub-stories before implementation can begin: with a user present, run `/synergy:feature-discovery` to plan the breakdown with them, then pick the first sub-story. Unattended (`.claude/unattended.flag` exists), send it to refinement with `wf refine` (`references/pick-paths.md`), naming the sub-stories it needs, run **Exit cleanup** and exit.

## Story too large

If the plan reveals the story exceeds one session's budget, implement the highest-priority slice, open a PR for that slice, and create follow-up issues for the remaining work using `/synergy:report-issue`. Do not attempt to complete everything in one session — a partial PR with clear notes is the expected outcome. Run **Exit cleanup** (`references/exit-cleanup.md`; opening the PR already released the claim) before exiting.
