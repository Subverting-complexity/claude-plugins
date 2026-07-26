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

1. **Spawn two review agents in parallel**, both in the same tool-call
   batch so they run concurrently. Use the `Reviewer` agent type when the
   harness offers plugin agents (it is defined in `agents/reviewer.md`);
   otherwise use a general-purpose subagent. Give each one:

   - The PR number **and** title, its URL, the head SHA you pushed, and
     the issue number and title it closes.
   - The command to run: `/github-workflow:code-review {pr_number}
     --read-only`.
   - Its review lens, so the two passes do not simply repeat each other.
     The first agent covers correctness and story alignment: does the
     change actually satisfy the acceptance criteria, and is the logic
     right. The second covers security, error handling, test coverage,
     and regressions in code the diff touches indirectly.
   - What to return: the verdict, and every finding with its `file:line`,
     a sentence on what is wrong, a suggested fix, and whether it blocks
     the merge.

   **Read-only is not optional here.** You still own the branch, and a
   reviewer pushing to it while you hold it would collide with your own
   commits. Read-only mode evaluates without claiming the PR, without
   editing files, and without merging, while still posting its comment and
   reconciling the PR's review-state labels. Because those agents change
   no files, the worktree the harness gives each of them is discarded
   cleanly (see `docs/worktree-config.md`).

2. **If the harness cannot spawn a subagent at all**, do not skip the
   review. Run `/github-workflow:code-review {pr_number} --read-only`
   inline in this session instead, and say plainly in the PR comment and
   your final report that the review was performed by the same context
   that wrote the code, so it is weaker evidence than an independent pass.

3. **Merge the two reports into one findings list.** Where both agents
   raise the same problem, keep one entry and note that both found it.
   Where they disagree on severity, take the stricter reading. The
   combined verdict is the strictest of the two: any Changes Requested or
   Needs Discussion outranks an Approved.

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
4. **Re-review.** Spawn one fresh reviewer the same way as Phase 9, told
   the new head SHA and asked to confirm whether the previous findings are
   resolved and whether the fixes introduced anything new. One agent is
   enough for a re-review; the two lenses already ran against the original
   diff.
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

**When the budget runs out before approval**, stop cleanly. The last
reviewer already reconciled the PR's labels, so a PR still carrying the
`changes-requested` verdict is picked up automatically by the next
`/github-workflow:code-review` run, which reworks and re-reviews it.
Post one comment naming what is still outstanding, report it, run **Exit
cleanup**, and exit without merging. Do not merge a PR whose review never
reached an approved verdict.

## Phase 11 — Merge and settle

Merging is part of this workflow's contract, so an approved PR merges here
without needing the `Auto-Merge on Approval` setting that governs the
standalone `/github-workflow:code-review` command. **Do not merge** when
any of these holds — in each case leave the PR open with the reviewer's
verdict on it, say why in your final report, and exit through **Exit
cleanup**:

- The run was invoked with `--no-merge`.
- The Phase 5 **gate-failed flag** is set, so the quality gate is red.
- Phase 7 flagged a possible duplicate PR closing the same issue.
  Reconciling duplicates belongs to code review, which keeps the
  better-implemented PR and closes the other.
- The combined verdict is not Approved.

Otherwise drive the PR to merged by following **steps 1 to 6** of
`skills/code-review/references/auto-merge.md`, which is the single
specification of the merge mechanics — confirming the PR is still what was
reviewed, resolving conflicts, gating on CI, squash-merging or enqueuing
`--auto`, verifying the outcome, and settling the linked issues with `wf
post-merge`. Read it with these substitutions:

- Its precondition that `Auto-Merge on Approval` is `enabled` is satisfied
  by this phase's own contract. Everything else it gates on still applies:
  `require-ci-before-merge`, the no-checks guard, `--bypass-ci`, and
  `bypass-ci-on-billing-failure` all behave exactly as written when a
  `review.config.md` exists, and default as that file describes when none
  does.
- Where it refers to the SHA recorded at its Step 3, use the head SHA you
  last pushed. Where it refers to the review comment from its Step 9, use
  the review comments the Phase 9 and Phase 10 agents posted.
- Where it says to fix a failing check the way its Step 7 does, apply
  Phase 10's fix discipline instead: fix what is objectively wrong, file
  what needs judgment.

One practical difference from a review session: you are sitting **on** the
branch being merged, and the merge deletes it. Stay on the PR branch
through its steps 1 to 3, because that is where a conflict resolution or a
CI fix has to be committed. Immediately before its step 4 merge, move off
the branch, so deleting it cannot fail and the session does not end on a
branch that no longer exists:

```bash
git fetch origin {default-branch}
git checkout {default-branch} && git pull origin {default-branch}
```

Its step 6 runs `wf post-merge --pr {pr_number}`, which closes every issue
the PR closes, clears the stale lifecycle label, and moves each one to the
board's **Done** column. Report each settled issue by number and title.

Then run **Exit cleanup** (`references/exit-cleanup.md`) as the final step
and report the run in full: the story implemented, the PR merged, what the
reviewers found and what you changed in response, anything filed to the
board, and the issues now closed.
