# Execute — Phase 9 (Rework)

Read this at Phase 9 of `review-and-merge.md`, unless the verdict was **Approved** with no blocking findings and no quick fixes worth applying and there is no `.claude/gate-failed.flag`. Phase 8, its severity rubric and Phase 10 are in that file.

## Phase 9 — Apply the fixes, re-review only when they earn it

If the verdict is **Approved** with no blocking findings and no quick fixes worth applying, go straight to Phase 10 — **unless `.claude/gate-failed.flag` exists**. A red quality gate is outstanding work even when the review liked the code, and it is the one thing that will stop Phase 10 merging, so enter this phase to repair it: skip to step 3, fix the gate, and judge the re-review at step 4 once it is green. Without this the flag can never be cleared on the path where clearing it matters most, and the run ends with an approved PR it refuses to merge.

Otherwise work through the findings on the branch you are already on:

1. **Fix every blocking finding, and every quick fix, that sits in this PR's diff or in the story it closes.** Blocking ones first. The story's own requirements are in scope whether or not the current diff touches them: a gap found there is work this run has not finished, not new work for the backlog. A two-minute correction on a branch you are already holding costs less now than it costs to schedule, review and merge later, and an issue filed in place of a fix is that defect merged and rebadged as somebody else's backlog item.
2. **File only the two things the rubric says to file:** a defect in pre-existing code that neither the diff touches nor the story covers, and a question that genuinely needs human judgment. File either with `/synergy:report-issue` (autonomous, correct type, referencing this PR and the `file:line`). The second kind also holds the PR: see the Needs Discussion rule below. Do not guess at it, and do not drop it.
3. Re-run the quality gate from `ClaudeProject.md`, then commit and push. The same Phase 5 rule applies: if the gate is still red after a reasonable number of attempts, stop fixing, leave the PR unmerged, and report it. If the gate now **passes** and `.claude/gate-failed.flag` exists, delete it (`rm -f .claude/gate-failed.flag`) — the rework fixed what Phase 5 could not, and leaving the flag would block Phase 10 from ever merging this run.
4. **Re-review only when the rework was substantial.** A re-review costs a push, an agent and a round trip, and running one after every commit is how a run that had a working pull request an hour ago still has an open one. Spawn a re-reviewer only when the rework did at least one of these:

   - changed or added logic, rather than correcting it in place;
   - added a file, an interface, or a dependency;
   - changed behaviour a user or a caller would notice;
   - fixed a security defect;
   - touched code outside the files the first review read.

   If the rework was quick fixes only, do **not** re-review: the quality gate in step 3 is the check on that class of change and it has already run. Note in the review comment what was fixed without a second reading, so the record is honest about what a fresh context saw.

   When a re-review is warranted, record the new head SHA and spawn **one** agent the same way as Phase 8 — read-only, detached, findings returned to you, no relabelling, the same rubric quoted in — pointed at the **rework commits** rather than the whole pull request, and asked whether the blocking findings are resolved and whether the fixes introduced anything new. Post the consolidated comment and reconcile the label again, with the same gate-failed override as Phase 8 step 5: while `.claude/gate-failed.flag` exists, record `changes-requested` whatever the reviewer concluded.
5. **One re-review round, then stop.** If it comes back Approved, go to Phase 10. If it still requests changes, do not open another round: apply anything in it that is a quick fix, push, and leave the pull request carrying `changes-requested` with a comment naming what is outstanding. The next `/synergy:pr-review` run picks a `changes-requested` PR up on its own, in a context that is not several hours into this one and reads the diff fresh. Report the run as reviewed, reworked and not merged, and say what remains.

A **Needs Discussion** verdict is the one case rework cannot settle, because it means the reviewer found a question only a person can answer. It is the human-judgment exception in step 2, not a general licence to file: everything else found in this diff was fixed in step 1. Do not loop on it: file the question to the backlog with `/synergy:report-issue`, leave the PR open carrying that verdict, say in your final report what has to be decided, run **Exit cleanup**, and exit without merging.

**When the budget runs out before approval**, stop cleanly. Step 5 of Phase 8 left the PR carrying the verdict, so a `changes-requested` PR is picked up automatically by the next `/synergy:pr-review` run, which reworks and re-reviews it. Post one comment naming what is still outstanding, report it, run **Exit cleanup**, and exit without merging. Do not merge a PR whose review never reached an approved verdict.
