---
name: bulk-execute
description: 'Build GitHub stories that fill an effort budget, as at most two pull requests, blockers first, reviewed and merged like execute. Trigger on "bulk execute", "build these stories together" or several issue numbers.'
depends-on:
  - code-architect
  - pr-review
argument-hint: '[issue# issue# ... | --parent N] [--mode feature|maintenance] [--no-merge] [--bypass-ci]'
arguments:
  - name: story_numbers
    description: 'Optional list of issue numbers to build together, e.g. "41 43 47". Their open prerequisites that this run can build join the set. If omitted, the set is planned from the pick pool.'
  - name: parent
    description: 'An Epic or Feature number. The set is planned from the stories under it. Cannot be combined with story numbers.'
  - name: mode
    description: 'Selection mode: story (default), feature (feature stories only), maintenance (bug/security/architecture/debt). A pull request never mixes modes.'
  - name: no-merge
    description: 'Stop after the independent review and rework instead of merging. The PR is left open carrying the reviewer verdict.'
  - name: bypass-ci
    description: 'Treat CI as satisfied when remote checks are red or absent. Explicit, never default — use only when CI cannot run for reasons outside the PR.'
---

# Bulk Execute

Take the stories that fill an **effort budget** and land them as **one or two groups**, each one branch, one pull request, one independent review and one merge. Group 1 is merged before group 2 is built. A story that waits on another story in the set is built after it, never left out, and independent stories in the same wave may be built in parallel.

`wf plan-set` decides the set, and every rule is enforced there: a budget of 7 where `Effort` Low is 1, Medium 2 and High 6; no two stories more than one `Priority` level apart; feature and maintenance work never in one group. Stories need not be linked.

**Use `/synergy:execute` instead** when there is one story.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## Is this the right skill?

Check this before reading anything else, and stop without running a phase if any of it holds:

- **The repository is not on GitHub.** The session was told it is hosted on Azure DevOps, GitLab, Bitbucket or an unrecognised remote. Say this workflow needs GitHub, and offer `/synergy:build` for local work or `/synergy:verify-feature` for a review.
- **The message names another synergy command.** A `/synergy:<name>` typed after other text, such as a branch name, is not run by Claude Code, so it arrives here as plain words. Read that skill's `SKILL.md` and follow it instead.
- **The only number is inside a branch name.** `feature/1963-seo-fix` names a branch, not a story. Ask what to do with the branch rather than planning a set.

## Shared rules

Once, at the start, read `skills/execute/references/shared-phases.md` and follow it: autonomy, invocation flags (including its `bulk-set.json` line), the preflight and configuration checks, API quota, session budget, fix in scope, exit cleanup, and the plan, build, verify, commit and review hand-off rules. This file holds what differs for a set. None of it is narrated to the user between phases.

**How many groups.** Check your own tool list before Phase 1. With no tool to start an agent, or running as an agent that cannot start its own, pass `--max-groups 1`: the review then runs inline, and a second one would fill the context. Otherwise pass `--max-groups 2`.

## Project configuration (auto-loaded)

A projection of `ClaudeProject.md` with the sections needed only later dropped. The shared rules say how to check it.

```!
bash "${CLAUDE_PLUGIN_ROOT}/scripts/project-config.sh"
```

## Session budget

If the API quota read at the start is below **300**, do not start: say so and suggest `/synergy:execute` for a single story.

Stay under ~150k tokens in this context for the whole run; builders spawned for a wave spend their own. (Design rationale: `docs/rationale/bulk-execute-rationale.md`, not read at runtime.)

- **Re-size the group at Phase 3.** If the plan does not fit, drop stories before writing any code (`references/set-selection.md`, **Dropping a story**).
- **Commit per story, push after each**, so an unexpected end leaves whole stories on the branch.
- **A pull request only ever closes stories it built.** If the budget runs out with stories unbuilt, drop them and open the PR for what was built.
- **90-minute timeout.** Before each wave and each phase, check the elapsed time. Past 90 minutes: commit and push, drop the unbuilt stories, then run Phase 7 for a real pull request covering the built ones and carry on into Phases 8 to 10. A group not yet started is dropped whole (`wf drop-group`). If nothing is shippable, leave the branch pushed, set every claimed issue to `stage-attention` with a comment listing what remains, file follow-ups, and run **Exit cleanup**.

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`: `feature` or `maintenance`. **A pull request never mixes modes**, because a feature bundled with an unrelated bug fix cannot be reverted without losing one or the other, so `story` mode splits a mixed set into a feature group and a maintenance group. There is no `audit` mode: use `/synergy:execute --mode audit`.

## Exit cleanup

Run `skills/execute/references/exit-cleanup.md` once, after the last group, with one substitution: its step 1 releases **one** issue claim, and this run holds one per story. Release them all in one `wf claim-release` call with `--issue` once per story in `.claude/bulk-set.json`. Its step 2 deletes `bulk-set.json` with the other scratch files. Everything else applies unchanged.

---

## Phase 1 — Plan and claim the set

**Read `references/set-selection.md` and follow it.** `wf plan-set` fills the budget, splits the set into groups, puts every blocker before the stories that wait on it, orders each group into waves, and with `--claim` claims, assigns and sets `In Progress` for every story in one call. Phase 1 ends in one of three states:

- **Two or more stories claimed** — continue to Phase 2.
- **One story claimed** — say so plainly and run the rest of this workflow for that story: a single-story pull request is a correct outcome.
- **Nothing claimed** — report why and stop.

## Phases 2 to 10, once per group

Run Phases 2 to 10 for group 1, then **Between groups**, then Phases 2 to 10 for group 2 if it is still there. Inside those phases, "the set" means the current group, and every `wf` bulk command takes `--group {G}`.

## Phase 2 — Start

1. **Confirm the claims.** Re-run `wf claim --issue {number}` for a story only if Phase 1's claim state was lost to compaction; a still-held claim is a no-op. Never issue a bare `--add-assignee @me` as a claim.
2. **Start clean.** Run the **Start clean** check in `templates/worktree-hygiene.md` before branching. A worktree provisioned dirty is inherited junk: reset it to a pristine baseline and report it.
3. **Create the group's branch.** Render the `branch-convention` from `ClaudeProject.md` with `{number}` = the group's **lead** story's number and a slug describing what the **group** has in common (`feature/41/label-resolution`, not `feature/41/fix-missing-status-label`), then record it:

   ```
   git fetch origin {default-branch}
   git checkout -b {branch} origin/{default-branch}
   git push -u origin {branch}
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" bulk-mark --group {G} --branch {branch}
   ```

## Phase 3 — Plan the set as one change

Use `/synergy:code-architect` **once** per group: every story's requirements together, the relevant codebase context, and any reference docs listed in `ClaudeProject.md`. Structure `.claude/plan.md` by wave and story in build order, listing the files each story touches, with a shared section for anything more than one story touches:

```
## Shared
- [ ] src/labels/resolve.ts — the lookup two stories build on

## Wave 0 — Story #41 — Resolve labels by purpose key
- [ ] src/labels/resolve.ts — add the purpose-key path
```

**Then re-check the group against the plan.** This is the last cheap moment to shrink it. If the group will not fit the session budget, or two stories pull the same code in different directions, drop the weakest story now (`references/set-selection.md`, **Dropping a story**) and re-plan without it. A story so underspecified that any implementation would be a guess is dropped, not the run.

## Phase 4 — Build, wave by wave

Build the waves in order. Shared code is written once, with the first story that needs it, and that commit says so.

Before each wave, run `wf bulk-schedule --group {G}` and read that wave's entry. It splits the wave's unbuilt stories into `batches` from the files `.claude/plan.md` lists: stories in one batch share no file, and batches run one after another. A story in `unplanned` names no files, so it gets a batch of its own. Files under `shared` go in with the first story that names them.

**A batch of one story, or any batch when no separate agent context can be spawned**, is built serially on the shared branch: implement it as the shared rules specify, run Phase 5's per-story checks, commit it (Phase 6), push, then run `wf bulk-mark --built {number}`.

**A batch of two or more stories** is built in parallel. Push the branch first, then spawn one `synergy:Builder` agent per story in a single message, each with `isolation: "worktree"`. Give each its story's number, title, body and plan section, the group's branch name, and these instructions: start from `origin/{branch}`, create `{branch}--{number}`, implement only this story, run the checks covering what it touched, commit with the message Phase 6 describes, push `{branch}--{number}`, and report the check results. When they have all returned, run `wf bulk-integrate --group {G} --wave {K}`: it cherry-picks each branch in build order, pushes once, marks what landed as built and deletes those branches. On `partial`, rebuild each story in `conflicted`, `missing` or `empty` serially. On `error`, stop and report `push_error`. A builder that failed its checks is treated as Phase 5's red check for that story.

After the last wave, run Phase 5's full gate for the group before Phase 7.

## Phase 5 — Verify (after each story, and once for the set)

**After each story**, run the checks covering what it touched: linter, type check, and the test suites for the changed areas, or the whole gate when that is cheap.

**Once per group, after its last wave**, run the full quality gate whatever ran during the build. That run is the gate the shared rules describe: it sets `gate-failed.flag`, and the per-story checks never replace it.

If a check is still failing after the shared retry limit, **stop**: do not start the next wave, because more code on a red tree makes the failure harder to attribute. Commit what you have, set the gate-failed flag, drop the unbuilt stories (`references/set-selection.md`, **Dropping a story**), and go to Phase 7. The pull request closes only the stories that were built.

## Phase 6 — Commit (per story)

Stage only this story's files. End the message with the issue it answers: `feat: resolve labels by purpose key (#41)`. One commit per story is the target; where a story needs several, each leaves the codebase working.

## Phase 7 — Finish

Once every story in the group is built, gated and committed, **read `references/bulk-finish.md`** and follow it end to end: push, per-story duplicate detection, one pull request closing every built story, labels, the `In Review` stage for each issue, claim release, and the progress note.

## Phases 8 to 10 — Review, rework, merge

Read `skills/execute/references/review-and-merge.md` as the shared rules say, with these substitutions:

- Where it says "the issue number and title it closes", give the reviewer **every** story in the group, by number and title, with its acceptance criteria. A reviewer who does not know a story is in scope reads its code as unexplained.
- **Add one question to the reviewer's lens:** is there anything in this diff that belongs to **none** of the listed stories? Read it per story, not by theme: a group can hold unrelated stories, and scope creep hides far better in a multi-story diff. Anything found is removed from the branch or explained in the PR body.
- Its **severity rubric** is unchanged. A larger diff invites more observations, and the rubric is what stops them being raised.
- Its Phase 9 fix-in-scope rule reads against **all** the stories the PR closes. Its re-review test is unchanged.
- Its Phase 10 duplicate-PR stop condition applies **per story**: a possible duplicate flagged against any story stops the merge for the whole pull request, because the PR is indivisible.
- When Phase 10 merges, it reads `skills/execute/references/merge.md` unchanged. Its settle step, `wf post-merge --pr {pr_number}`, already closes and moves **every** issue the pull request closes; report each settled story by number and title, and the `unblocked` sweep, because a bulk set is the run most likely to free downstream work.
- Its closing **Exit cleanup** and final report wait for the last group. After group 1, go to **Between groups** instead.

**When no separate context can be spawned**, its Phase 8 step 3 applies unchanged, and a long bulk session is likelier to need it. Carry the whole lens yourself in one deliberate pass, in the reference's order and under the same rubric, ending with the bulk question: the failure mode of an inline review of a large diff is a skim that reports nothing. The disclosure lists every story the PR closes by number and title. It does not stop the merge; the gates that do all still apply.

## Between groups

Group 1's pull request is merged, or stopped at a condition Phase 10 names. Before group 2:

1. **Drop group 2 unbuilt** with `wf drop-group --group 2 --reason "{why}"` when any of these holds, and report each story it returns by number, title and reason:
   - `.claude/self-review.flag` exists: group 1's review ran inline, so group 2's would too.
   - Group 1 did not merge and a story in group 2 waits on a story in group 1.
   - The 90-minute timeout or the session budget is spent.
2. Otherwise, `rm -f .claude/gate-failed.flag`, which belonged to group 1, and run Phases 2 to 10 for group 2 from `origin/{default-branch}`, fetched again so it holds group 1's merge.

---

## Escape hatches

Read `skills/execute/references/escape-hatches.md` when a run leaves the happy path, with these substitutions for a set:

- **Blocked.** One story blocking does not block the run. Drop it (`references/set-selection.md`, **Dropping a story**, then `/synergy:block-story` for it) and carry on. Block the whole run only when the set drops below one buildable story and no code exists yet.
- **Dependency.** A dependency *inside* the set needs no hatch: `plan-set` already built it into the waves. A dependency on an open issue *outside* the set that appears mid-run drops that story. Never chain a bulk branch off another feature branch.
- **Too large.** Shrink the group, do not slice a story. Leave the dropped ones in the pool for their own run.
- **Failure reporting.** Comment the failure on **every** claimed issue before exiting and set each to `Needs attention`. Once the pull request is open, comment on the PR instead and leave the stages at `In Review`.
