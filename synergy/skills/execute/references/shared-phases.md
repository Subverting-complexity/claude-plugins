# Execute and bulk-execute — shared rules

`execute` and `bulk-execute` both read this once, at the start of every run. It holds what the two workflows do identically. Where a `SKILL.md` gives its own value (a budget, a timeout, a threshold, an extra file), that value wins. Bare `wf` means `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh"`, never a system CLI to look for.

## Autonomy

Every phase flows into the next without pausing for user input, except at a stop the skill names. Opening the pull request is not a stopping point: Phases 8 to 10 need no permission, no confirmation and no green CI, so keep going in the same turn. A run that reports its new PR and offers to review and merge it if asked has stopped half way, however finished it sounds.

## Invocation flags, preflight cache and API quota

`--no-merge` and `--bypass-ci` are read in Phase 10, long after they are parsed, so `wf run-init` records them on disk now, in the same call that resets what a hard-killed prior run left behind, sweeps stray claim markers, and reports whether preflight is still cached and what the GitHub API quota looks like — one command in place of the hand-written shell this used to be. Run it exactly once, here:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" run-init \
  --no-merge      # only when --no-merge was passed \
  --bypass-ci     # only when --bypass-ci was passed \
  --unattended    # only when nobody is present to answer \
  --bulk          # bulk-execute only, also clears .claude/bulk-set.json
```

**Unattended** means nobody will answer a question: this run was spawned as an agent (the `synergy:Builder`), runs in a scheduled routine or a non-interactive `claude -p`, or the user asked for it to run without questions. Every step that would ask a person checks `.claude/unattended.flag` and takes its unattended branch instead.

**Run it exactly once, here.** Re-running it after a compaction would wipe the `gate-failed.flag` Phase 5 wrote, the `self-review.flag` Phase 8 wrote and the set Phase 1 recorded, and would drop `no-merge.flag` if the arguments are gone from context. Later phases only read these files and the `run-init` result.

**If this call is blocked.** `synergy/agents/builder.md` already carries the Bash allow pattern this needs (`Bash(bash *wf.sh*)`) and `docs/rationale/builder-tools-rationale.md` records why. A spawned `synergy:Builder` running under that allowlist should never see a permission prompt here. A configuration that still denies it — a host-side classifier judging command *content* rather than matching the allow patterns — is outside what a tool allowlist can fix from inside the agent; grant the pattern explicitly rather than trying to word the command around it.

## Preflight and project configuration

The skill's auto-loaded configuration block has already run.

1. If it printed "ClaudeProject.md NOT FOUND", stop with exactly one message, "ClaudeProject.md not found — run /synergy:setup.", and do not chain into preflight for the same cause.
2. Read `preflight_cached` from the `run-init` result above. `true` means a clean or warning-only preflight already passed within the last four hours and `ClaudeProject.md` has not changed since, so skip straight to step 3. Otherwise invoke `/synergy:preflight`. Unattended, a critical finding is a stop: report it verbatim and exit. With a user present, on "Configure now", wait for setup and ask the user to re-run the command, because the loaded configuration is stale; on "Continue anyway" or "Don't remind me", proceed.
3. The projection must contain both `## Identity` and `## Quality Gate`. If either is missing, stop with "ClaudeProject.md is missing required section: {name} — run /synergy:setup."
4. Read `CLAUDE.md` for project rules and build principles.

The projection drops sections needed only later. When a later phase resolves the org issue fields, `Stage` included, read `## Issue Types & Fields` straight from `ClaudeProject.md`.

Read `quota.remaining` from the same `run-init` result, and again before Phase 7 (`bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" run-init` with no flags, or `gh api rate_limit --jq '.rate.remaining'` directly, keeping the result in context only). Below **100** (`quota.low`), pause: commit and push current work, set every claimed issue to `Needs attention` (`wf stage-set {number} --stage stage-attention`) with a comment noting the pause, run **Exit cleanup**, and exit. The next session resumes from the pushed branch. **Once the PR is open (Phase 8 onward)**, leave the stages at `In Review` and note the pause on the PR instead, so the stages and the PR's review state agree. Never retry rate-limited requests in a loop.

## Session budget

- **Commit early, push periodically**, so an unexpected end leaves recoverable work on the branch.
- **One run, one session.** Do not pick more work after finishing.
- **Wrap up, don't run out.** Deep into a session, get to a committable state; a PR with remaining-work notes beats an abandoned session.
- **Leave room for the review.** Phases 8 and 9 hand the diff to a separate context, so here they cost the review reference, the findings returned and the fixes applied, plus the whole pr-review hot path inline if no agent can be spawned. The rework loop stops once the budget is nearly spent.
- **Record the start time** (`date +%s`) and check the elapsed time against the skill's timeout before each phase.

## Fix in scope, file out of scope

One rule governs every problem a run finds, from the first line of the build to the last review round:

- **In the PR's own diff, or in any story it closes** — fix it here, on this branch, before the PR merges. Never file it: a defect in work this run is building is this run's work to finish.
- **Anywhere else** — a pre-existing bug in untouched code, a problem noticed in passing, work belonging to a story this run does not close — file it with `/synergy:report-issue` and carry on. Fixing it inline widens the diff the reviewer has to judge.

Two exceptions stay filed: a finding only a person can settle (an ambiguous requirement, an architectural choice with several defensible answers), filed as the question with the PR left open on that verdict; and scope deliberately deferred or dropped, which is backlog work rather than a review finding.

## Exit cleanup

Every exit path (finish, block, failure, timeout, rate-limit pause) ends with `skills/execute/references/exit-cleanup.md` as the final step, after any commit or push. It is the only specification of the procedure: read it rather than improvising the steps.

## Phase 3 — Planning aids

Write the plan to `.claude/plan.md` so it survives compaction, as a checklist of files with a `[ ]` box each, and mark each `[x]` as Phase 4 completes it. After a compaction, re-read it and confirm what actually changed with `git status` and `git log --oneline`. Where requirements have gaps, make reasonable assumptions and note them in the plan.

**Ecosystem tools.** Before reading files blind, check whether `.claude/ecosystem.md` exists. If it does, the project opted into the tools it lists, so use them first: **Graphify** (`graphify . --update`, then `graphify query "..."` or `graphify explain X` rather than blind file search for structure questions) and **Fallow** for TS/JS (existing exports and duplication, so the plan reuses what is there). If it does not exist, skip this silently and never nag. A listed tool missing from `PATH` is one line of note, not a blocker.

## Phase 4 — Build

Implement by `templates/coding-method.md`, code and tests together, following the build principles in `CLAUDE.md`. Do not pause for confirmation: the issue requirements and the Phase 3 plan are the approved specification.

## Phase 5 — Verify

Run the quality gate command from `ClaudeProject.md`. On a failure, read the error output, fix the failing check and re-run, up to 3 retries. Near the token budget or the timeout, stop after 2.

Still failing after that, the gate is red and the cause is likely outside the story's scope: stop retrying, commit what you have, set the gate-failed flag (`mkdir -p .claude && touch .claude/gate-failed.flag`; Phase 10 reads it long after this decision, and a compaction in between would otherwise lose it and merge a red PR), and go to Phase 7. Phase 7 opens a real PR, never a draft, that enters review as changes-requested and carries a "Quality gate failed" section, so a person sees it and the label blocks the merge.

## Phase 6 — Commit

Stage only relevant files, never `.env`, credentials or generated files that should be gitignored. Write a message saying what was built and why. The quality gate hook runs on commit. Keep each commit leaving the codebase in a working state.

## Phases 7 to 10 — Finish, review, rework, merge

**Do not review your own diff anywhere in the run.** The session that wrote the code shares every assumption it was built on. That decides whose judgement counts, not whether the run continues: you still spawn the reviewer, own what it returns, and hand the PR to nobody (not the user, not a later session, not a standalone `/synergy:pr-review`). Phase 8's last-resort inline fallback is the one exception, and it is disclosed.

The moment the PR exists, read `skills/execute/references/review-and-merge.md` and follow it to the end of the run, in the same turn. The review is unconditional. Merging is opt-in through `Auto-Merge on Approval` in `review.config.md`, off by default; a project that has not opted in ends at an approved PR waiting for a person, which is a complete run. The conditions that stop a merge decide only whether an already-reviewed PR merges, never whether it is reviewed.
