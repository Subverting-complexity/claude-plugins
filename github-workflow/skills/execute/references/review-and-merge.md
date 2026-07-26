# Execute — Phase 9 (Independent review), Phase 10 (Rework), Phase 11 (Merge)

Read this after Phase 8 has finished and the pull request is open. It
covers the rest of the story's life: a review carried out independently in
a fresh context, the rework loop that answers that review, and the merge
that settles the issue. It is kept out of `SKILL.md` because no run reaches
it until a PR exists.

The deliverable of this workflow is a **merged** pull request. An open PR
is an unfinished story, so these three phases are as much part of the run
as the build was. Every exit path still ends with **Exit cleanup**
(`references/exit-cleanup.md`).

## Phase 9 — Independent review in a fresh context

Your session planned this change and wrote it, so it cannot review it
independently: it shares every assumption the code was built on and it
already believes the work is correct. That is why the Phase 8 self-review
is only advisory. The review that decides whether this PR merges has to
start from the pull request itself, in a context that never saw the
build.

1. **Claim the PR before spawning anything.** Phase 7 released the issue
   claim when the PR opened, so nothing currently stops a scheduled
   `/github-workflow:code-review` run from selecting this PR in full mode
   and pushing to the branch you are still holding. Acquire the review
   claim with `templates/claim-procedure.md` (**Acquire**, target
   `pr-{pr_number}`). If the claim is lost, another agent owns the review:
   report that, leave the PR to it, run **Exit cleanup**, and exit without
   merging. Record the head SHA you are about to have reviewed:

   ```bash
   git rev-parse HEAD
   ```

2. **Spawn two review agents in parallel**, both in the same tool-call
   batch so they run concurrently. Use the `Reviewer` agent type when the
   harness offers plugin agents (it is defined in `agents/reviewer.md`);
   otherwise use a general-purpose subagent. Give each one:

   - The PR number **and** title, its URL, the head SHA from step 1, and
     the issue number and title it closes.
   - The command to run: `/github-workflow:code-review {pr_number}
     --read-only`.
   - Its review lens, so the two passes do not simply repeat each other.
     The first agent covers correctness and story alignment: does the
     change actually satisfy the acceptance criteria, and is the logic
     right. The second covers security, error handling, test coverage,
     and regressions in code the diff touches indirectly.
   - **That you own the verdict.** Each agent must return its findings and
     verdict to you and must **not** post a review comment or reconcile the
     PR's labels. Two concurrent reviewers relabelling would overwrite each
     other last-writer-wins, and two contradictory review comments at the
     same SHA would confuse the re-review in Phase 10. `read-only-mode.md`
     sanctions this override for a caller that owns the verdict; say so
     explicitly in the prompt, because its default is to relabel.
   - What to return: the verdict, and every finding with its `file:line`,
     a sentence on what is wrong, a suggested fix, and whether it blocks
     the merge.

   **Read-only is not optional here.** You still own the branch, and a
   reviewer pushing to it while you hold it would collide with your own
   commits. Read-only mode evaluates without claiming the PR, without
   editing files, and without merging, and it checks out **detached**
   because git refuses to check out a branch that another worktree already
   holds — which yours does. Because those agents change no files, the
   worktree the harness gives each of them is discarded cleanly (see
   `docs/worktree-config.md`).

3. **If no subagent can be spawned at all** — the harness offers no
   agent-spawning tool, or nested spawning is unavailable because execute
   is itself running as a subagent — do not skip the review. Run
   `/github-workflow:code-review {pr_number} --read-only` inline in this
   session instead, and treat the result as a self-review: it is the same
   context that wrote the code, so it is not the independent evidence this
   phase exists to produce. Phase 11 does **not** merge on a self-review;
   say plainly in the PR comment and your final report that the review
   could not be run independently, and expect the standalone
   `/github-workflow:code-review` command to finish the job. Note also that
   an inline review pulls that skill's whole hot path into this session, so
   budget for it.

4. **Merge the two reports into one findings list.** Where both agents
   raise the same problem, keep one entry and note that both found it.
   Where they disagree on severity, take the stricter reading. The
   combined verdict is the strictest of the two: any Changes Requested or
   Needs Discussion outranks an Approved.

5. **Post one consolidated review comment and set the label yourself.**
   Write the comment following `templates/body-file-write.md` (temp file
   plus `--body-file`), naming the two lenses, the combined verdict, and
   each finding. Then reconcile the PR's review-state label to the combined
   verdict, which is why the reviewers were told not to:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr {pr_number} --verdict <approved|changes-requested|needs-discussion>
   ```

## Phase 10 — Apply the fixes and re-review

If the combined verdict is **Approved** with no blocking findings, go
straight to Phase 11.

Otherwise work through the findings on the branch you are already on:

1. Fix every finding that has an objectively correct answer — a logic
   error, a missing null check, a missing or wrong test, unhandled
   failure on a new external call, dead code, a formatting violation.
   Fix the blocking findings first, then the non-blocking ones.
2. File anything that genuinely needs human judgment — an architectural
   decision, an ambiguous requirement, a fix whose right shape is a
   product question — to the board with `/github-workflow:report-issue`
   (autonomous, `status-ready`, correct type, referencing this PR). Do not
   guess at it, and do not drop it.
3. Re-run the quality gate from `ClaudeProject.md`, then commit and push.
   The same Phase 5 rule applies: if the gate is still red after a
   reasonable number of attempts, stop fixing, leave the PR unmerged, and
   report it.
4. **Re-review.** Record the new head SHA, then spawn one fresh reviewer
   the same way as Phase 9 — read-only, detached, findings returned to you,
   no relabelling — asked to confirm whether the previous findings are
   resolved and whether the fixes introduced anything new. One agent is
   enough for a re-review; the two lenses already ran against the original
   diff. Post the consolidated comment and reconcile the label again.
5. Repeat this loop — fix, push, re-review — until the verdict is
   Approved, **as far as the session budget allows**. Before starting
   another round, check the elapsed time and how much of the token budget
   is left, and start the round only if you can finish it: a round costs a
   push plus one agent's review. In practice this settles in one or two
   rounds.

A **Needs Discussion** verdict is the one case more rework cannot settle,
because it means a reviewer found a question only a person can answer. Do
not loop on it: file the question to the board with
`/github-workflow:report-issue`, leave the PR open carrying that verdict,
say in your final report what has to be decided, run **Exit cleanup**, and
exit without merging.

**When the budget runs out before approval**, stop cleanly. Step 5 of Phase
9 left the PR carrying the combined verdict, so a `changes-requested` PR is
picked up automatically by the next `/github-workflow:code-review` run,
which reworks and re-reviews it. Post one comment naming what is still
outstanding, report it, run **Exit cleanup**, and exit without merging. Do
not merge a PR whose review never reached an approved verdict.

## Phase 11 — Merge and settle

Merging is part of this workflow's contract, so an approved PR merges here
without needing the `Auto-Merge on Approval` setting that governs the
standalone `/github-workflow:code-review` command. `auto-merge.md` names
this phase as its second sanctioned caller, so the passage there about
merging being forbidden without that setting is not a contradiction to
resolve or a reason to stop.

**Do not even attempt the merge** when any of these holds. In each case
leave the PR open with its verdict on it, say why in your final report, and
exit through **Exit cleanup**:

- The run was invoked with `--no-merge` (`test -f .claude/no-merge.flag`).
- The Phase 5 quality gate failed (`test -f .claude/gate-failed.flag`).
- Phase 7 flagged a possible duplicate PR closing the same issue.
  Reconciling duplicates belongs to code review, which keeps the
  better-implemented PR and closes the other.
- The combined verdict is not Approved.
- Phase 9 had to review inline because no subagent could be spawned. A
  self-review is not the independent review this merge is predicated on.

Those are the conditions checked **before** the attempt. The merge
mechanics themselves can also stop short — a head SHA that moved since the
review, a conflict needing human judgment, a red check that is not yours to
fix, absent CI, repo-level auto-merge disabled, or checks still pending when
the watch window closes. Each of those leaves the PR approved and unmerged
with a comment saying why, which is a correct outcome, not a failure to
hide.

Otherwise drive the PR to merged by following **steps 1 to 6** of
`skills/code-review/references/auto-merge.md`, which is the single
specification of the merge mechanics — confirming the PR is still what was
reviewed, resolving conflicts, gating on CI, squash-merging or enqueuing
`--auto`, verifying the outcome, and settling the linked issues with `wf
post-merge`. Read it with these substitutions:

- Its precondition that `Auto-Merge on Approval` is `enabled` is satisfied
  by this phase's own contract, as that file now states. Because this phase
  supplies the `enabled`, it also supplies the CI gate: when no
  `review.config.md` sets `require-ci-before-merge`, treat it as
  `if-present`, **not** the `false` that file defaults to. That default was
  safe only while merging required a deliberate opt-in, and `false` would
  merge an approved PR over a failing pipeline. Where a `review.config.md`
  does set it, honour what it says.
- `--bypass-ci` is set for this run only if the invocation passed it
  (`test -f .claude/bypass-ci.flag`); otherwise treat it as absent. When a
  PR reports **no checks at all**, CI status is unknown, and this run is
  autonomous: do not ask the user, and do not merge. Post the one-line
  comment that guard specifies, leave the PR approved, and report it as
  approved but unmerged. An operator who knows the project's CI runs
  somewhere GitHub cannot see re-runs with `--bypass-ci`.
- Where it refers to the SHA recorded when the branch was checked out (its
  step 1 calls this "the SHA you reviewed", recorded at code-review's Step
  3), use the head SHA you recorded in Phase 9 or Phase 10. Where it refers
  to the review comment from code-review's Step 9, use the consolidated
  comment you posted.
- Where it says to fix a failing check the way code-review's Step 7 does,
  apply Phase 10's fix discipline instead: fix what is objectively wrong,
  file what needs judgment.
- Where its step 5 refers to the final report format in code-review's
  `SKILL.md`, use the report described at the end of this file instead —
  execute never loads that file.

One practical difference from a review session: you are sitting **on** the
branch being merged, and the merge deletes it. Stay on the PR branch
through its steps 1 to 3, because that is where a conflict resolution or a
CI fix has to be committed. Immediately before its step 4 merge, move off
the branch. Detach rather than checking the default branch out, because
another worktree on this clone usually holds it and git refuses to check
out a branch twice:

```bash
git fetch origin {default-branch}
git checkout --detach origin/{default-branch}
```

If `git status --porcelain` is not empty, run **End clean** in
`templates/worktree-hygiene.md` first — the detach will not move with
tracked modifications in the way.

Its step 6 runs `wf post-merge --pr {pr_number}`, which closes every issue
the PR closes, clears the stale lifecycle label, and moves each one to the
board's **Done** column. Report each settled issue by number and title.

Then run **Exit cleanup** (`references/exit-cleanup.md`) as the final step,
which releases the `pr-{pr_number}` claim, and report the run in full: the
story implemented, the PR merged, what the reviewers found and what you
changed in response, anything filed to the board, and the issues now
closed.
