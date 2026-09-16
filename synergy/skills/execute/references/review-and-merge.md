# Execute — Phase 8 (Independent review), Phase 9 (Rework), Phase 10 (Merge)

Read this after Phase 7 has finished and the pull request is open. It covers the rest of the story's life: a review carried out independently in a fresh context, the rework loop that answers that review, and the merge that settles the issue. It is kept out of `SKILL.md` because no run reaches it until a PR exists.

The deliverable of this workflow is a reviewed pull request, merged where the project has opted into that. An open, unreviewed PR is an unfinished story, so these three phases are as much part of the run as the build was. Every exit path still ends with **Exit cleanup** (`references/exit-cleanup.md`).

The **Fix in scope, file out of scope** rule in `shared-phases.md` governs all three phases, and it is what stops a review round turning into a pile of new backlog issues: a finding against this pull request's own diff is fixed here, and only a problem this PR is not the place to fix is filed. Each phase below says how that lands in its own steps.

**Start immediately, and never on a condition.** **CI** does not gate this phase: a reviewer reads the diff, not the pipeline, and Phase 10 is where the merge waits on checks. Reviewing a PR whose checks are still queued is normal and lets the two run in parallel. **The user** does not gate it either — a sentence offering to carry on when asked means you are already off the workflow.

## Phase 8 — Independent review in a fresh context

Your session planned this change and wrote it, so it cannot review it independently: it shares every assumption the code was built on and it already believes the work is correct. That is why nothing earlier in the run reviews the diff — the review that decides whether this PR merges has to start from the pull request itself, in a context that never saw the build.

1. **Claim the PR before spawning anything, and make it the first thing this phase does.** Phase 7's `handoff` took the review claim before it released the issue claim, so the PR has been locked since it opened, and a scheduled `/synergy:pr-review` run that selects it finds it claimed rather than checking out the branch you are still holding. Still nothing may be inserted between Phase 7 and here: read the PR, re-read the diff, post nothing, do nothing. Run `wf claim --pr <number> --keep-held` (**Acquire**, target `pr-{pr_number}`) anyway: when this checkout already holds the claim, `--keep-held` keeps it and applies the `reviewing` marker, and when `handoff` could not take it, this is where it is taken. If the claim is lost, another agent owns the review: report that, leave the PR to it, run **Exit cleanup**, and exit without merging — do not strip its `reviewing` marker or delete a claim ref you do not hold. Record the head SHA you are about to have reviewed:

   ```bash
   git rev-parse HEAD
   ```

2. **Spawn one review agent.** Use agent type `synergy:Reviewer` (defined in `agents/reviewer.md`); if the harness does not offer plugin agents, use a general-purpose subagent. One agent is enough: the independence this phase needs comes from a context that never saw the build, not from the number of readers. Give it:

   - The PR number **and** title, its URL, the head SHA from step 1, and the issue number and title it closes, with its acceptance criteria.
   - The command to run: `/synergy:pr-review {pr_number} --read-only`.
   - **One pass covering the whole diff**, in this order: correctness and story alignment — does the change actually satisfy the acceptance criteria, and is the logic right — then security, error handling, test coverage, and regressions in code the diff touches indirectly.
   - **The severity rubric at the end of this phase, quoted into the prompt.** It decides what the agent may raise at all, and it is the difference between a review naming three real problems and one returning twenty entries nobody will act on. Ask for each finding to carry its bucket.
   - **That you own the verdict.** The agent must return its findings to you and must **not** post a review comment or reconcile the PR's labels. You are mid-run on this branch and about to post one consolidated verdict in step 5; a reviewer labelling the PR underneath you would contradict it. `read-only-mode.md` sanctions this override for a caller that owns the verdict; say so explicitly in the prompt, because its default is to relabel.
   - What to return: the verdict, and every finding with its `file:line`, its rubric bucket, a sentence on what is wrong, a suggested fix, and **whether it sits in this PR's diff or in pre-existing code the PR does not change**. You need that last part to apply the fix-in-scope rule in Phase 9 — the first kind you fix on this branch, the second kind you file. Ask for the classification explicitly; without it you have to re-derive it from the diff yourself. The agent files nothing either way: read-only mode never files an issue.

   **Read-only is not optional here.** You still own the branch, and a reviewer pushing to it while you hold it would collide with your own commits. Read-only mode evaluates without claiming the PR, without editing files, and without merging, and it checks out **detached** because git refuses to check out a branch that another worktree already holds — which yours does. Because that agent changes no files, the worktree the harness gives it is discarded cleanly (see `docs/worktree-config.md`).

3. **If no subagent can be spawned at all** — the harness offers no agent-spawning tool, or nested spawning is unavailable because execute is itself running as a subagent — do not skip the review. **Try the general-purpose subagent first**: the usual cause is that the `synergy:Reviewer` agent type is unavailable, not that spawning is impossible, and a general-purpose agent in a fresh context is still genuinely independent. Only when that also fails, run `/synergy:pr-review {pr_number} --read-only` inline in this session, and record that this happened — `mkdir -p .claude && touch .claude/self-review.flag` — so the disclosure below survives a compaction the way the other flags do. The severity rubric governs an inline review exactly as it governs an agent's.

   An inline review is a **self-review**: the same context that wrote the code judges it, so it is weaker evidence than this phase is designed to produce, and it pulls that skill's whole hot path into this session. It does **not** stop the merge. What it obliges you to do is say so in both places a person will look — the PR comment and your final report:

   > ⚠ This review was **not independent**. No separate agent context could be spawned, so the session that wrote this code also reviewed it. Its findings are worth less than a fresh reviewer's.

   Merging on a disclosed self-review is deliberate (why: `docs/rationale/execute-rationale.md`). The gates that do stop the merge — a failing quality gate, an unapproved verdict, red or absent CI — all still apply, and they are the ones carrying real evidence about the code.

4. **Sift what comes back.** Drop anything the agent raised that the rubric says is not a finding, and take the stricter reading where a finding is genuinely ambiguous between blocking and quick fix. What survives is the findings list; one agent means there is nothing to reconcile.

5. **Post one consolidated review comment and set the label yourself.** Write the comment following `templates/body-file-write.md` (temp file plus `--body-file`), naming what was reviewed, the verdict, and each finding with its bucket. Then reconcile the PR's review-state label (if auto mode denies it, read `references/escape-hatches.md`):

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

If the verdict is **Approved** with no blocking findings and no quick fixes worth applying, and `.claude/gate-failed.flag` does not exist, go straight to Phase 10. Otherwise follow `references/rework.md`, which holds every step of this phase, including the fix discipline and re-review test that other files cite as Phase 9's.

## Phase 10 — Merge and settle

Merging is **opt-in**. The switch is `Auto-Merge on Approval` in `review.config.md`, the same one pr-review's Step 11 reads, so one setting decides unattended merges wherever a PR is merged from. Read it from `docs/review.config.md`, then `./review.config.md`; an absent file or section means `disabled`.

**Check these before reading any merge mechanics.** If any holds, do not attempt the merge: leave the PR open with its verdict on it, say in your final report which condition it was, and exit through **Exit cleanup**:

- `Auto-Merge on Approval` is not `enabled`, the default. The PR is reviewed, approved and deliberately waiting for a person: leave it `approved`, add no other label, and report it as ready to merge.
- The run was invoked with `--no-merge` (`test -f .claude/no-merge.flag`). Handle it the same way.
- The Phase 5 quality gate failed (`test -f .claude/gate-failed.flag`).
- Phase 7 flagged a possible duplicate PR. The flag is the first line of the PR body (`⚠ Possible duplicate of #N`), so read the body if it is no longer in context. Code review reconciles duplicates.
- The verdict is not Approved.

Only when none of them holds, read `references/merge.md` and follow it: it drives the PR to merged and settles the linked issues.

## Final report

Run **Exit cleanup** (`references/exit-cleanup.md`) as the final step, which also releases the `pr-{pr_number}` claim. Then report the run in full: the story implemented, whether the PR merged or which condition stopped it, what the review found and what you changed in response, anything filed to the backlog, and the issues now closed. Keep filed and closed apart, and say why each filed item was filed: unrelated to this PR, or an open question for a person. If `.claude/self-review.flag` exists, repeat Phase 8 step 3's disclosure. A run that fixed its findings and filed nothing is the ordinary outcome.
