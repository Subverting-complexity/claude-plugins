# Execute — Phase 8 (Independent review), Phase 9 (Rework), Phase 10 (Merge)

Read this after Phase 7 has finished and the pull request is open. It
covers the rest of the story's life: a review carried out independently in
a fresh context, the rework loop that answers that review, and the merge
that settles the issue. It is kept out of `SKILL.md` because no run reaches
it until a PR exists.

The deliverable of this workflow is a reviewed pull request, merged where
the project has opted into that. An open, unreviewed PR is an unfinished
story, so these three phases are as much part of the run as the build was.
Every exit path still ends with **Exit cleanup**
(`references/exit-cleanup.md`).

**Start immediately, and never on a condition.** **CI** does not gate this
phase: a reviewer reads the diff, not the pipeline, and Phase 10 is where the
merge waits on checks. Reviewing a PR whose checks are still queued is normal
and lets the two run in parallel. **The user** does not gate it either — a
sentence offering to carry on when asked means you are already off the
workflow.

## Phase 8 — Independent review in a fresh context

Your session planned this change and wrote it, so it cannot review it
independently: it shares every assumption the code was built on and it
already believes the work is correct. That is why nothing earlier in the
run reviews the diff — the review that decides whether this PR merges has
to start from the pull request itself, in a context that never saw the
build.

1. **Claim the PR before spawning anything, and make it the first thing
   this phase does.** Phase 7 released the issue claim when the PR opened,
   so between that release and this acquire the work is held by no lock at
   all — nothing stops a scheduled `/github-workflow:code-review` run from
   selecting this PR in full mode and pushing to the branch you are still
   holding. That window is the reason nothing may be inserted between
   Phase 7 and here: read the PR, re-read the diff, post nothing, do
   nothing. Acquire the review claim with `templates/claim-procedure.md`
   (**Acquire**, target `pr-{pr_number}`). If the claim is lost, another
   agent owns the review: report that, leave the PR to it, run **Exit
   cleanup**, and exit without merging — do not strip its `reviewing`
   marker or delete a claim ref you do not hold. Record the head SHA you
   are about to have reviewed:

   ```bash
   git rev-parse HEAD
   ```

2. **Spawn two review agents in parallel**, both in the same tool-call
   batch so they run concurrently. Use agent type `github-workflow:Reviewer`
   (defined in `agents/reviewer.md`); if the harness does not offer plugin
   agents, use a general-purpose subagent. Give each one:

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
     same SHA would confuse the re-review in Phase 9. `read-only-mode.md`
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
   is itself running as a subagent — do not skip the review. **Try the
   general-purpose subagent first**: the usual cause is that the
   `github-workflow:Reviewer` agent type is unavailable, not that spawning
   is impossible, and a
   general-purpose agent in a fresh context is still genuinely independent.
   Only when that also fails, run `/github-workflow:code-review {pr_number}
   --read-only` inline in this session, and record that this happened —
   `mkdir -p .claude && touch .claude/self-review.flag` — so the disclosure
   below survives a compaction the way the other flags do.

   An inline review is a **self-review**: the same context that wrote the code
   judges it, so it is weaker evidence than this phase is designed to produce,
   and it pulls that skill's whole hot path into this session. It does **not**
   stop the merge. What it obliges you to do is say so in both places a person
   will look — the PR comment and your final report:

   > ⚠ This review was **not independent**. No separate agent context could be
   > spawned, so the session that wrote this code also reviewed it. Its
   > findings are worth less than a fresh reviewer's.

   Merging on a disclosed self-review is deliberate (why:
   `references/execute-rationale.md`). The gates that do stop the merge — a
   failing quality gate, an unapproved verdict, red or absent CI — all still
   apply, and they are the ones carrying real evidence about the code.

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

   **One override.** If `.claude/gate-failed.flag` exists, record
   `changes-requested` whatever the reviewers concluded. Phase 7 applied that
   label deliberately to block the merge while the quality gate is red, and
   this call strips every other state label, so an approving verdict would
   quietly remove the guard. Say in the comment that the reviewers approved
   the code but the gate is still red.

## Phase 9 — Apply the fixes and re-review

If the combined verdict is **Approved** with no blocking findings, go
straight to Phase 10 — **unless `.claude/gate-failed.flag` exists**. A red
quality gate is outstanding work even when the reviewers liked the code, and
it is the one thing that will stop Phase 10 merging, so enter this phase to
repair it: skip to step 3, fix the gate, and re-review from step 4 once it is
green. Without this the flag can never be cleared on the path where clearing
it matters most, and the run ends with an approved PR it refuses to merge.

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
   report it. If the gate now **passes** and `.claude/gate-failed.flag`
   exists, delete it (`rm -f .claude/gate-failed.flag`) — the rework fixed
   what Phase 5 could not, and leaving the flag would block Phase 10 from
   ever merging this run.
4. **Re-review.** Record the new head SHA, then spawn one fresh reviewer
   the same way as Phase 8 — read-only, detached, findings returned to you,
   no relabelling — asked to confirm whether the previous findings are
   resolved and whether the fixes introduced anything new. One agent is
   enough for a re-review; the two lenses already ran against the original
   diff. Post the consolidated comment and reconcile the label again — with
   the same gate-failed override as Phase 8 step 5: while
   `.claude/gate-failed.flag` exists, record `changes-requested` whatever the
   reviewer concluded. When this round was entered only to repair a red
   quality gate and the reviewers had already approved, the re-review is
   still worth its cost: the gate fix is new code that nobody has read.
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
8 left the PR carrying the combined verdict, so a `changes-requested` PR is
picked up automatically by the next `/github-workflow:code-review` run,
which reworks and re-reviews it. Post one comment naming what is still
outstanding, report it, run **Exit cleanup**, and exit without merging. Do
not merge a PR whose review never reached an approved verdict.

## Phase 10 — Merge and settle

Merging is **opt-in**, and the switch is the same one that governs the
standalone `/github-workflow:code-review` command: `Auto-Merge on Approval`
in `review.config.md`. One setting, one meaning, wherever a PR gets merged
— a project that has not asked for unattended merges does not get them
because it happened to reach the PR through `execute` rather than through a
review run. Read it the way `auto-merge.md` specifies (`docs/review.config.md`
then `./review.config.md`; absent file or absent section ⇒ `disabled`).

**Do not even attempt the merge** when any of these holds. In each case
leave the PR open with its verdict on it, say why in your final report, and
exit through **Exit cleanup**:

- `Auto-Merge on Approval` is not `enabled` — including the common case
  where the project has no `review.config.md` at all. This is the default,
  so the ordinary end of a run is an approved PR waiting for a person.
- The run was invoked with `--no-merge` (`test -f .claude/no-merge.flag`).
- The Phase 5 quality gate failed (`test -f .claude/gate-failed.flag`).
- Phase 7 flagged a possible duplicate PR closing the same issue. Its flag
  line is the first line of the PR body (`⚠ Possible duplicate of #N`), so
  read the body if the flag is no longer in context. Reconciling duplicates
  belongs to code review, which keeps the better-implemented PR and closes
  the other.
- The combined verdict is not Approved.

A self-review (`test -f .claude/self-review.flag`) is **not** on that list.
It merges, provided Phase 8 step 3's disclosure is on the PR comment and
repeated in your final report. Check the flag here for exactly that reason:
to confirm the disclosure was made, and to repeat it in the report.

Those are the conditions checked **before** the attempt. The merge
mechanics themselves can also stop short — a head SHA that moved since the
review, a conflict needing human judgment, a red check that is not yours to
fix, absent CI, repo-level auto-merge disabled, or checks still pending when
the watch window closes. Each of those leaves the PR approved and unmerged
with a comment saying why, which is a correct outcome, not a failure to hide.

When you leave a PR **approved and unmerged because the merge was attempted
and stopped short**, also apply the `needs-re-review` label (resolve the name
through `templates/default-labels.md`). The review picker skips a plain
`approved` PR, so without that label nothing selects it again and the work is
orphaned until a person notices. Two cases are excluded:

- The successful **enqueue** outcome — `autoMergeRequest` non-null at
  auto-merge step 5 — where GitHub merges the PR on its own once its
  requirements clear. Labelling a PR that is about to land would put it at the
  top of the review queue for pointless rework.
- The merge was never attempted because it is **switched off** — auto-merge
  is not `enabled`, or `--no-merge` was passed. Nothing is outstanding: the PR
  is reviewed, approved, and deliberately waiting for a person. Sending it back
  through the review picker would just re-review an approved PR that no run is
  allowed to merge anyway. Leave it `approved` and say in your report that it
  is ready to merge.

Otherwise drive the PR to merged by following **steps 1 to 6** of
`skills/code-review/references/auto-merge.md`, which is the single
specification of the merge mechanics — confirming the PR is still what was
reviewed, resolving conflicts, gating on CI, squash-merging or enqueuing
`--auto`, verifying the outcome, and settling the linked issues with `wf
post-merge`. Read it with these substitutions:

- Its enabling conditions are read exactly as written — you already
  confirmed `Auto-Merge on Approval` is `enabled` above, and
  `require-ci-before-merge` comes from that same section of the same file.
  Nothing about the CI gate changes for this caller.
- `--bypass-ci` is set for this run only if the invocation passed it
  (`test -f .claude/bypass-ci.flag`); otherwise treat it as absent. When a
  PR reports **no checks at all**, its steps 3a-ii and 3b decide first, and
  which of them can apply is settled by whether the repo has active
  workflows: 3a-ii covers a project whose pipeline exists but was stopped by
  Actions billing (`bypass-ci-on-billing-failure: true`), and 3b covers a
  project that has no GitHub-visible pipeline at all
  (`bypass-ci-when-no-pipeline: true`). Either way the merge proceeds on the
  local quality gate, and either way Phase 5 already produced it: an absent
  `.claude/gate-failed.flag` **is** the green local gate, so read the flag
  rather than re-run the suite. Failing both, CI status is unknown and this
  run is autonomous: do not ask the user, and do not merge. Post the one-line
  comment that guard specifies, leave the PR approved, and report it as
  approved but unmerged. An operator whose project has no GitHub-visible
  pipeline sets `bypass-ci-when-no-pipeline` once instead of re-running with
  `--bypass-ci` every time.
- Where it refers to the SHA recorded when the branch was checked out (its
  step 1 calls this "the SHA you reviewed", recorded at code-review's Step
  3), use the head SHA you recorded in Phase 8 or Phase 9. Where it refers
  to the review comment from code-review's Step 9, use the consolidated
  comment you posted.
- Where it says to fix a failing check the way code-review's Step 7 does,
  apply Phase 9's fix discipline instead: fix what is objectively wrong,
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

If `git status --porcelain --untracked-files=no` is not empty, run **End
clean** in `templates/worktree-hygiene.md` first — the detach will not move
with tracked modifications in the way. Ignore untracked files here: this
workflow's own `.claude/` scratch files are untracked by design, and routing
a mid-merge run into End clean over them would risk committing scratch to the
PR.

Its step 6 runs `wf post-merge --pr {pr_number}`, which closes every issue
the PR closes, clears the stale lifecycle label, and moves each one to the
board's **Done** column. Report each settled issue by number and title.

Then run **Exit cleanup** (`references/exit-cleanup.md`) as the final step,
which releases the `pr-{pr_number}` claim, and report the run in full: the
story implemented, the PR merged, what the reviewers found and what you
changed in response, anything filed to the board, and the issues now
closed.
