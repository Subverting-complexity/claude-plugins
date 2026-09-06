# Execute — Phase 8 (Independent review), Phase 9 (Rework), Phase 10 (Merge)

Read this after Phase 7 has finished and the pull request is open. It covers the rest of the story's life: a review carried out independently in a fresh context, the rework loop that answers that review, and the merge that settles the issue. It is kept out of `SKILL.md` because no run reaches it until a PR exists.

The deliverable of this workflow is a reviewed pull request, merged where the project has opted into that. An open, unreviewed PR is an unfinished story, so these three phases are as much part of the run as the build was. Every exit path still ends with **Exit cleanup** (`references/exit-cleanup.md`).

`SKILL.md`'s **Fix in scope, file out of scope** rule governs all three phases, and it is what stops a review round turning into a pile of new board issues: a finding against this pull request's own diff is fixed here, and only a problem this PR is not the place to fix is filed. Each phase below says how that lands in its own steps.

**Start immediately, and never on a condition.** **CI** does not gate this phase: a reviewer reads the diff, not the pipeline, and Phase 10 is where the merge waits on checks. Reviewing a PR whose checks are still queued is normal and lets the two run in parallel. **The user** does not gate it either — a sentence offering to carry on when asked means you are already off the workflow.

## Phase 8 — Independent review in a fresh context

Your session planned this change and wrote it, so it cannot review it independently: it shares every assumption the code was built on and it already believes the work is correct. That is why nothing earlier in the run reviews the diff — the review that decides whether this PR merges has to start from the pull request itself, in a context that never saw the build.

1. **Claim the PR before spawning anything, and make it the first thing this phase does.** Phase 7 released the issue claim when the PR opened, so between that release and this acquire the work is held by no lock at all — nothing stops a scheduled `/github-workflow:code-review` run from selecting this PR in full mode and pushing to the branch you are still holding. That window is the reason nothing may be inserted between Phase 7 and here: read the PR, re-read the diff, post nothing, do nothing. Acquire the review claim with `wf claim --pr <number>` (**Acquire**, target `pr-{pr_number}`). If the claim is lost, another agent owns the review: report that, leave the PR to it, run **Exit cleanup**, and exit without merging — do not strip its `reviewing` marker or delete a claim ref you do not hold. Record the head SHA you are about to have reviewed:

   ```bash
   git rev-parse HEAD
   ```

2. **Spawn one review agent.** Use agent type `github-workflow:Reviewer` (defined in `agents/reviewer.md`); if the harness does not offer plugin agents, use a general-purpose subagent. One agent is enough: the independence this phase needs comes from a context that never saw the build, not from the number of readers. Give it:

   - The PR number **and** title, its URL, the head SHA from step 1, and the issue number and title it closes, with its acceptance criteria.
   - The command to run: `/github-workflow:code-review {pr_number} --read-only`.
   - **One pass covering the whole diff**, in this order: correctness and story alignment — does the change actually satisfy the acceptance criteria, and is the logic right — then security, error handling, test coverage, and regressions in code the diff touches indirectly.
   - **The severity rubric at the end of this phase, quoted into the prompt.** It decides what the agent may raise at all, and it is the difference between a review naming three real problems and one returning twenty entries nobody will act on. Ask for each finding to carry its bucket.
   - **That you own the verdict.** The agent must return its findings to you and must **not** post a review comment or reconcile the PR's labels. You are mid-run on this branch and about to post one consolidated verdict in step 5; a reviewer labelling the PR underneath you would contradict it. `read-only-mode.md` sanctions this override for a caller that owns the verdict; say so explicitly in the prompt, because its default is to relabel.
   - What to return: the verdict, and every finding with its `file:line`, its rubric bucket, a sentence on what is wrong, a suggested fix, and **whether it sits in this PR's diff or in pre-existing code the PR does not change**. You need that last part to apply the fix-in-scope rule in Phase 9 — the first kind you fix on this branch, the second kind you file. Ask for the classification explicitly; without it you have to re-derive it from the diff yourself. The agent files nothing either way: read-only mode never writes to the board.

   **Read-only is not optional here.** You still own the branch, and a reviewer pushing to it while you hold it would collide with your own commits. Read-only mode evaluates without claiming the PR, without editing files, and without merging, and it checks out **detached** because git refuses to check out a branch that another worktree already holds — which yours does. Because that agent changes no files, the worktree the harness gives it is discarded cleanly (see `docs/worktree-config.md`).

3. **If no subagent can be spawned at all** — the harness offers no agent-spawning tool, or nested spawning is unavailable because execute is itself running as a subagent — do not skip the review. **Try the general-purpose subagent first**: the usual cause is that the `github-workflow:Reviewer` agent type is unavailable, not that spawning is impossible, and a general-purpose agent in a fresh context is still genuinely independent. Only when that also fails, run `/github-workflow:code-review {pr_number} --read-only` inline in this session, and record that this happened — `mkdir -p .claude && touch .claude/self-review.flag` — so the disclosure below survives a compaction the way the other flags do. The severity rubric governs an inline review exactly as it governs an agent's.

   An inline review is a **self-review**: the same context that wrote the code judges it, so it is weaker evidence than this phase is designed to produce, and it pulls that skill's whole hot path into this session. It does **not** stop the merge. What it obliges you to do is say so in both places a person will look — the PR comment and your final report:

   > ⚠ This review was **not independent**. No separate agent context could be spawned, so the session that wrote this code also reviewed it. Its findings are worth less than a fresh reviewer's.

   Merging on a disclosed self-review is deliberate (why: `docs/rationale/execute-rationale.md`). The gates that do stop the merge — a failing quality gate, an unapproved verdict, red or absent CI — all still apply, and they are the ones carrying real evidence about the code.

4. **Sift what comes back.** Drop anything the agent raised that the rubric says is not a finding, and take the stricter reading where a finding is genuinely ambiguous between blocking and quick fix. What survives is the findings list; one agent means there is nothing to reconcile.

5. **Post one consolidated review comment and set the label yourself.** Write the comment following `templates/body-file-write.md` (temp file plus `--body-file`), naming what was reviewed, the verdict, and each finding with its bucket. Then reconcile the PR's review-state label, which is why the reviewer was told not to:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr {pr_number} --verdict <approved|changes-requested|needs-discussion>
   ```

   **One override.** If `.claude/gate-failed.flag` exists, record `changes-requested` whatever the reviewer concluded. Phase 7 applied that label deliberately to block the merge while the quality gate is red, and this call strips every other state label, so an approving verdict would quietly remove the guard. Say in the comment that the review approved the code but the gate is still red.

### The severity rubric

Every finding lands in one of four buckets, and the reviewer is asked to say which. A note that fits none of them is not a finding.

**Blocking.** The pull request does not merge until it is fixed:

- an acceptance criterion the change does not meet;
- a logic error that produces a wrong result, or a crash or unhandled failure on a path this change introduces;
- a security defect — injection, a committed secret, a new surface with no authorisation check, unvalidated input reaching something dangerous;
- a regression in behaviour the diff touches;
- new behaviour the story specifies with no test, or a test asserting the wrong thing.

**Quick fix.** Real, objectively wrong, and settled in a couple of minutes with no new design: dead code, a duplicate of a helper that already exists, a missing null or error check on a minor path, a formatting violation, an obvious missing edge case in a test, a name that says the wrong thing. Phase 9 fixes these without ceremony. They do not block the merge, and on their own they do not earn a re-review.

**File, do not fix.** Exactly two kinds qualify: a defect in pre-existing code that neither the diff touches nor the story covers, and a question only a person can answer. Nothing else. "It could be filed" is not a reason to file something sitting in a diff you are already holding.

**Not a finding.** Say nothing about a style preference the codebase has no rule about, a different structure that is not better, a rename with no defect behind it, an extension the story did not ask for, a performance worry with nothing measured, or a comment and documentation nit. Each one buries the findings that matter.

The rubric is a filter, not a quota. A clean diff that returns no findings is an ordinary outcome and reads as one.

## Phase 9 — Apply the fixes, re-review only when they earn it

If the verdict is **Approved** with no blocking findings and no quick fixes worth applying, go straight to Phase 10 — **unless `.claude/gate-failed.flag` exists**. A red quality gate is outstanding work even when the review liked the code, and it is the one thing that will stop Phase 10 merging, so enter this phase to repair it: skip to step 3, fix the gate, and judge the re-review at step 4 once it is green. Without this the flag can never be cleared on the path where clearing it matters most, and the run ends with an approved PR it refuses to merge.

Otherwise work through the findings on the branch you are already on:

1. **Fix every blocking finding, and every quick fix, that sits in this PR's diff or in the story it closes.** Blocking ones first. The story's own requirements are in scope whether or not the current diff touches them: a gap found there is work this run has not finished, not new work for the board. A two-minute correction on a branch you are already holding costs less now than it costs to schedule, review and merge later, and an issue filed in place of a fix is that defect merged and rebadged as somebody else's backlog item.
2. **File only the two things the rubric says to file:** a defect in pre-existing code that neither the diff touches nor the story covers, and a question that genuinely needs human judgment. File either with `/github-workflow:report-issue` (autonomous, `status-ready`, correct type, referencing this PR and the `file:line`). The second kind also holds the PR: see the Needs Discussion rule below. Do not guess at it, and do not drop it.
3. Re-run the quality gate from `ClaudeProject.md`, then commit and push. The same Phase 5 rule applies: if the gate is still red after a reasonable number of attempts, stop fixing, leave the PR unmerged, and report it. If the gate now **passes** and `.claude/gate-failed.flag` exists, delete it (`rm -f .claude/gate-failed.flag`) — the rework fixed what Phase 5 could not, and leaving the flag would block Phase 10 from ever merging this run.
4. **Re-review only when the rework was substantial.** A re-review costs a push, an agent and a round trip, and running one after every commit is how a run that had a working pull request an hour ago still has an open one. Spawn a re-reviewer only when the rework did at least one of these:

   - changed or added logic, rather than correcting it in place;
   - added a file, an interface, or a dependency;
   - changed behaviour a user or a caller would notice;
   - fixed a security defect;
   - touched code outside the files the first review read.

   If the rework was quick fixes only, do **not** re-review: the quality gate in step 3 is the check on that class of change and it has already run. Note in the review comment what was fixed without a second reading, so the record is honest about what a fresh context saw.

   When a re-review is warranted, record the new head SHA and spawn **one** agent the same way as Phase 8 — read-only, detached, findings returned to you, no relabelling, the same rubric quoted in — pointed at the **rework commits** rather than the whole pull request, and asked whether the blocking findings are resolved and whether the fixes introduced anything new. Post the consolidated comment and reconcile the label again, with the same gate-failed override as Phase 8 step 5: while `.claude/gate-failed.flag` exists, record `changes-requested` whatever the reviewer concluded.
5. **One re-review round, then stop.** If it comes back Approved, go to Phase 10. If it still requests changes, do not open another round: apply anything in it that is a quick fix, push, and leave the pull request carrying `changes-requested` with a comment naming what is outstanding. The next `/github-workflow:code-review` run picks a `changes-requested` PR up on its own, in a context that is not several hours into this one and reads the diff fresh. Report the run as reviewed, reworked and not merged, and say what remains.

A **Needs Discussion** verdict is the one case rework cannot settle, because it means the reviewer found a question only a person can answer. It is the human-judgment exception in step 2, not a general licence to file: everything else found in this diff was fixed in step 1. Do not loop on it: file the question to the board with `/github-workflow:report-issue`, leave the PR open carrying that verdict, say in your final report what has to be decided, run **Exit cleanup**, and exit without merging.

**When the budget runs out before approval**, stop cleanly. Step 5 of Phase 8 left the PR carrying the verdict, so a `changes-requested` PR is picked up automatically by the next `/github-workflow:code-review` run, which reworks and re-reviews it. Post one comment naming what is still outstanding, report it, run **Exit cleanup**, and exit without merging. Do not merge a PR whose review never reached an approved verdict.

## Phase 10 — Merge and settle

Merging is **opt-in**, and the switch is the same one that governs the standalone `/github-workflow:code-review` command: `Auto-Merge on Approval` in `review.config.md`. One setting, one meaning, wherever a PR gets merged — a project that has not asked for unattended merges does not get them because it happened to reach the PR through `execute` rather than through a review run. Read it the way `auto-merge.md` specifies (`docs/review.config.md` then `./review.config.md`; absent file or absent section ⇒ `disabled`).

**Do not even attempt the merge** when any of these holds. In each case leave the PR open with its verdict on it, say why in your final report, and exit through **Exit cleanup**:

- `Auto-Merge on Approval` is not `enabled` — including the common case where the project has no `review.config.md` at all. This is the default, so the ordinary end of a run is an approved PR waiting for a person.
- The run was invoked with `--no-merge` (`test -f .claude/no-merge.flag`).
- The Phase 5 quality gate failed (`test -f .claude/gate-failed.flag`).
- Phase 7 flagged a possible duplicate PR closing the same issue. Its flag line is the first line of the PR body (`⚠ Possible duplicate of #N`), so read the body if the flag is no longer in context. Reconciling duplicates belongs to code review, which keeps the better-implemented PR and closes the other.
- The verdict is not Approved.

A self-review (`test -f .claude/self-review.flag`) is **not** on that list. It merges, provided Phase 8 step 3's disclosure is on the PR comment and repeated in your final report. Check the flag here for exactly that reason: to confirm the disclosure was made, and to repeat it in the report.

Those are the conditions checked **before** the attempt. The merge mechanics themselves can also stop short — a head SHA that moved since the review, a conflict needing human judgment, a red check that is not yours to fix, absent CI, repo-level auto-merge disabled, or checks still pending when the watch window closes. Each of those leaves the PR approved and unmerged with a comment saying why, which is a correct outcome, not a failure to hide.

When you leave a PR **approved and unmerged because the merge was attempted and stopped short**, also apply the `needs-re-review` label (resolve the name through `templates/default-labels.md`). The review picker skips a plain `approved` PR, so without that label nothing selects it again and the work is orphaned until a person notices. Two cases are excluded:

- The successful **enqueue** outcome — `autoMergeRequest` non-null at auto-merge step 5 — where GitHub merges the PR on its own once its requirements clear. Labelling a PR that is about to land would put it at the top of the review queue for pointless rework.
- The merge was never attempted because it is **switched off** — auto-merge is not `enabled`, or `--no-merge` was passed. Nothing is outstanding: the PR is reviewed, approved, and deliberately waiting for a person. Sending it back through the review picker would just re-review an approved PR that no run is allowed to merge anyway. Leave it `approved` and say in your report that it is ready to merge.

Otherwise drive the PR to merged by following **steps 1 to 6** of `skills/code-review/references/auto-merge.md`, which is the single specification of the merge mechanics — confirming the PR is still what was reviewed, resolving conflicts, gating on CI, squash-merging or enqueuing `--auto`, verifying the outcome, and settling the linked issues with `wf post-merge`. Read it with these substitutions:

- Its enabling conditions are read exactly as written — you already confirmed `Auto-Merge on Approval` is `enabled` above, and `require-ci-before-merge` comes from that same section of the same file. Nothing about the CI gate changes for this caller.
- `--bypass-ci` is set for this run only if the invocation passed it (`test -f .claude/bypass-ci.flag`); otherwise treat it as absent. When a PR reports **no checks at all**, its steps 3a-ii and 3b decide first, and which of them can apply is settled by whether the repo has active workflows: 3a-ii covers a project whose pipeline exists but was stopped by Actions billing (`bypass-ci-on-billing-failure: true`), and 3b covers a project that has no GitHub-visible pipeline at all (`bypass-ci-when-no-pipeline: true`). Either way the merge proceeds on the local quality gate, and either way Phase 5 already produced it: an absent `.claude/gate-failed.flag` **is** the green local gate, so read the flag rather than re-run the suite. Failing both, CI status is unknown and this run is autonomous: do not ask the user, and do not merge. Post the one-line comment that guard specifies, leave the PR approved, and report it as approved but unmerged. An operator whose project has no GitHub-visible pipeline sets `bypass-ci-when-no-pipeline` once instead of re-running with `--bypass-ci` every time.
- Where it refers to the SHA recorded when the branch was checked out (its step 1 calls this "the SHA you reviewed", recorded at code-review's Step 3), use the head SHA you recorded in Phase 8 or Phase 9. Where it refers to the review comment from code-review's Step 9, use the consolidated comment you posted.
- Where it says to fix a failing check the way code-review's Step 7 does, apply Phase 9's fix discipline instead: fix what is objectively wrong, file what needs judgment.
- Its fallbacks that **file** a conflict or a failing check stand as written, and they do not contradict **Fix in scope, file out of scope**. Each covers an in-scope problem this run genuinely cannot resolve — a rebase whose resolution needs human judgment, or an infrastructure or flaky failure originating outside the diff — and each leaves the PR open and unmerged rather than filing the problem away and merging over it. A check that fails **because of this PR's own diff** is not one of them: fix it on the branch.
- Where its step 5 refers to the final report format in code-review's `SKILL.md`, use the report described at the end of this file instead — execute never loads that file.

One practical difference from a review session: you are sitting **on** the branch being merged, and the merge deletes it. Stay on the PR branch through its steps 1 to 3, because that is where a conflict resolution or a CI fix has to be committed. Immediately before its step 4 merge, move off the branch. Detach rather than checking the default branch out, because another worktree on this clone usually holds it and git refuses to check out a branch twice:

```bash
git fetch origin {default-branch}
git checkout --detach origin/{default-branch}
```

If `git status --porcelain --untracked-files=no` is not empty, run **End clean** in `templates/worktree-hygiene.md` first — the detach will not move with tracked modifications in the way. Ignore untracked files here: this workflow's own `.claude/` scratch files are untracked by design, and routing a mid-merge run into End clean over them would risk committing scratch to the PR.

Its step 6 runs `wf post-merge --pr {pr_number}`, which closes every issue the PR closes, clears the stale lifecycle label, and moves each one to the board's **Done** column. Report each settled issue by number and title.

Then run **Exit cleanup** (`references/exit-cleanup.md`) as the final step, which releases the `pr-{pr_number}` claim, and report the run in full: the story implemented, the PR merged, what the review found and what you changed in response, anything filed to the board, and the issues now closed. Keep those last two apart in the report and say why each filed item was filed — unrelated to this PR, or an open question for a person. A run that fixed its review findings here and filed nothing is the ordinary outcome, not a gap in the report.
