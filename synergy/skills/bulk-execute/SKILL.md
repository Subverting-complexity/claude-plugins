---
name: bulk-execute
description: 'Build two to five related GitHub stories on one branch behind one pull request, reviewed and merged like execute. Trigger on "bulk execute", "batch these stories" or several issue numbers.'
depends-on:
  - code-architect
  - pr-review
argument-hint: '[issue# issue# ... | --parent N] [--mode feature|maintenance] [--size N] [--no-merge] [--bypass-ci]'
arguments:
  - name: story_numbers
    description: 'Optional list of issue numbers to build together, e.g. "41 43 47". Naming them is the precise way to choose the set. If omitted, the pick pool is read and a related group is chosen from it deliberately.'
  - name: parent
    description: 'An Epic or Feature number. The set is chosen from the stories under it: one Feature per run, only stories a code agent may take. Cannot be combined with story numbers.'
  - name: mode
    description: 'Selection mode for the lead story: story (default), feature (feature stories only), maintenance (bug/security/architecture/debt). A set never mixes modes.'
  - name: size
    description: 'Maximum stories in the set, 2 to 5 (default 5). The cap is a ceiling, not a target: only genuinely related stories belong in one set.'
  - name: no-merge
    description: 'Stop after the independent review and rework instead of merging. The PR is left open carrying the reviewer verdict.'
  - name: bypass-ci
    description: 'Treat CI as satisfied when remote checks are red or absent. Explicit, never default — use only when CI cannot run for reasons outside the PR.'
---

# Bulk Execute

Take **two to five related stories** and land them as **one change**: one branch, one set of commits, one pull request, one independent review, one merge. The saving is narrow: the same subsystem planned once, the same files opened once, one reviewer reading one coherent diff. It disappears when the stories are unrelated, and then this command produces a pull request nobody can review or revert cleanly. **Choosing the set is the hard part**, and so is shrinking it when it turns out to be wrong.

**Use `/synergy:execute` instead** when there is one story, when the stories touch different subsystems, or when any one of them is large enough to fill a session on its own.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## Shared rules

Once, at the start, read `skills/execute/references/shared-phases.md` and follow it: autonomy, invocation flags (including its `bulk-set.json` line), the preflight and configuration checks, API quota, session budget, fix in scope, exit cleanup, and the plan, build, verify, commit and review hand-off rules. This file holds what differs for a set. None of it is narrated to the user between phases.

The one thing this workflow stops for is a **set it cannot justify**. If nothing in the backlog is genuinely related to the lead story, say so and run the lead on its own rather than padding the set.

`--size` caps the set at 2 to 5 stories, default 5. Clamp a value outside that range and report the clamp. Five is a ceiling: a set reaches it only when five stories are genuinely one change and each is small enough to leave room for the review.

## Project configuration (auto-loaded)

A projection of `ClaudeProject.md` with the sections needed only later dropped. The shared rules say how to check it.

```!
if [ -f .claude/projected-config.md ] && [ .claude/projected-config.md -nt ClaudeProject.md ] 2>/dev/null; then
  cat .claude/projected-config.md
elif [ -f ClaudeProject.md ]; then
  # Drop the heavy sections only needed later. Pure POSIX shell (no
  # awk/tee) so it runs on a Windows bash whose PATH lacks Unix coreutils.
  mkdir -p .claude 2>/dev/null
  drop=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '## '*) case "$line" in
          '## Issue Types & Fields'*|'## Project Board'*|'## Story Template'*|'## Session Budget'*|'## Reference Docs'*|'## Bundled Skills'*) drop=1 ;;
          *) drop=0 ;;
        esac ;;
    esac
    [ "$drop" -eq 0 ] && printf '%s\n' "$line"
  done < ClaudeProject.md > .claude/projected-config.md
  cat .claude/projected-config.md
else
  echo "ClaudeProject.md NOT FOUND"
fi
```

## Session budget

A bulk run makes more `gh` calls than a single story, because it claims, labels, moves and settles several issues. If the API quota read at the start is below **300**, do not start: say so and suggest `/synergy:execute` for a single story.

Stay under ~150k tokens for the whole set, and let that decide how many stories the set holds. (Design rationale for this and every decision below: `docs/rationale/bulk-execute-rationale.md`, not read at runtime.)

- **Size the set to the budget at Phase 1, and re-size it at Phase 3.** If the plan does not fit, drop stories before writing any code (`references/set-selection.md`, **Dropping a story**).
- **Commit per story, push after each**, so an unexpected end leaves whole stories on the branch.
- **The pull request only ever closes stories it actually implements.** If the budget runs out with stories unbuilt, release those claims back to the backlog and open the PR for what was built. Never write `Closes #N` for a story this run did not finish.
- **Stop short of the cap when the stories are not small.** Running out of budget before the review strands every story in the set at once.
- **60-minute timeout.** Before each story and each phase, check the elapsed time. Past 60 minutes: commit and push, release the claims of the unbuilt stories, then run Phase 7 for a real pull request, never a draft, covering the built ones and carry on into Phases 8 to 10. If nothing is shippable, leave the branch pushed, set every claimed issue to `stage-attention` with a comment listing what remains, file follow-ups, and run **Exit cleanup**.

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`: `feature` (feature stories only) or `maintenance` (bug, security, architecture, tech debt).

**A set never mixes modes.** A feature bundled with an unrelated bug fix cannot be reverted without losing one or the other, so the lead story's mode fixes the mode of the whole set. There is no `audit` mode: an audit changes no code, so use `/synergy:execute --mode audit`.

## Exit cleanup

Run `skills/execute/references/exit-cleanup.md` with one substitution: its step 1 releases **one** issue claim, and this run holds one per story. Release every `refs/claims/issue-{number}` and delete every `.claude/claim-issue-{number}.sha`, reading `.claude/bulk-set.json` for the list if the set is no longer in context. Its step 2 also deletes `.claude/bulk-set.json`. Everything else applies unchanged.

---

## Phase 1 — Choose the set, then claim every story in it

The set is **chosen**, never taken off the top of the backlog. Priority says which story is worth doing next, not which stories belong in one pull request. Whichever path applies, the reason for each story being in the set is recorded.

**Read `references/set-selection.md` and follow it.** It covers three paths:

- **Named stories** (`$ARGUMENTS.story_numbers`, e.g. `/synergy:bulk-execute 41 43 47`) — the user has made the choice. Validate each, check none is already in flight, and claim them all. Relatedness is not re-litigated; a named story is dropped only when it cannot be worked at all.
- **No numbers given** — `wf candidates --mode {mode}` returns the same filtered, priority-sorted pool `execute` would pick from and claims nothing. Group it into genuinely related stories, choose one group against the relatedness rules, and only then claim.
- **A parent given** (`--parent N`, an Epic or Feature) — `wf candidates --parent N` returns one Feature's stories a code agent may take, plus any Blocked story waiting only on another story in the set. Nothing is asked; what was left out is reported.

Every story in the set gets a real atomic claim before any code is written: the `refs/claims/issue-{number}` ref, the `@me` assignment and the `In Progress` stage. Phase 1 ends in one of three states:

- **Two or more stories claimed** — continue to Phase 2 in build order.
- **One story claimed** — nothing was related enough, or only one named story survived validation. Say so plainly and run the rest of this workflow for that story: a single-story pull request is a correct outcome.
- **Nothing claimed** — report why and stop.

## Phase 2 — Start

1. **Confirm the claims.** Re-run `wf claim --issue {number}` for a story only if Phase 1's claim state was lost to compaction; a still-held claim is a no-op. Never issue a bare `--add-assignee @me` as a claim.
2. **Start clean.** Run the **Start clean** check in `templates/worktree-hygiene.md` before branching. A worktree provisioned dirty is inherited junk: reset it to a pristine baseline and report it.
3. **Create the one shared branch.** Render the `branch-convention` from `ClaudeProject.md` with `{number}` = the **lead** story's number and a slug describing what the **set** has in common (`feature/41/label-resolution`, not `feature/41/fix-missing-status-label`):

   ```
   git fetch origin {default-branch}
   git checkout -b {branch} origin/{default-branch}
   ```

   Record the branch name in `.claude/bulk-set.json`.

Stage failures are loud but not fatal: report them ("Stage update failed: {reason}. Continuing.") and proceed.

## Phase 3 — Plan the set as one change

Use `/synergy:code-architect` **once**, over the whole set: every story's requirements together, the relevant codebase context, and any reference docs listed in `ClaudeProject.md`. Structure `.claude/plan.md` by story in **build order**, with a shared section for anything more than one story touches:

```
## Shared
- [ ] src/labels/resolve.ts — the lookup all three stories build on

## Story #41 — Resolve labels by purpose key
- [ ] src/labels/resolve.ts — add the purpose-key path
- [ ] tests/labels/resolve.test.ts — purpose-key cases
```

**Then re-check the set against the plan.** This is the last cheap moment to shrink it. If the set will not fit the budget, or two stories pull the same code in different directions, drop the weakest story now (`references/set-selection.md`, **Dropping a story**) and re-plan without it. A story so underspecified that any implementation would be a guess is dropped, not the run.

## Phase 4 — Build, story by story

Work through the set **in build order**, one story at a time, never interleaved: a reviewer, and anyone reverting one story later, has to see which commit answers which story. For each story:

1. Implement it as the shared rules specify.
2. Run Phase 5's per-story checks.
3. Commit it (Phase 6).
4. Push, then move to the next story.

Shared code is written once, with the first story that needs it, and that commit says so. After the last story, run Phase 5's full gate for the set before Phase 7.

## Phase 5 — Verify (after each story, and once for the set)

**After each story**, run the checks covering what it touched: linter, type check, and the test suites for the changed areas, or the whole gate when that is cheap.

**Once, after the last story**, run the full quality gate whatever ran during the build. That run is the gate the shared rules describe: it sets `gate-failed.flag`, and the per-story checks never replace it.

If a check is still failing after the shared retry limit, **stop**: on a per-story check do not start the next story, because more code on a red tree makes the failure harder to attribute. Either way, commit what you have, set the gate-failed flag, release the claims of the unbuilt stories (`references/set-selection.md`, **Dropping a story**), and go to Phase 7. The pull request closes only the stories that were built.

## Phase 6 — Commit (per story)

Stage only this story's files. End the message with the issue it answers: `feat: resolve labels by purpose key (#41)`. One commit per story is the target; where a story needs several, each leaves the codebase working.

## Phase 7 — Finish

Once every story in the set is built, gated and committed, **read `references/bulk-finish.md`** and follow it end to end: push, per-story duplicate detection, one pull request closing every built story, labels, the `In Review` stage for each issue, claim release, and the progress note.

## Phases 8 to 10 — Review, rework, merge

Read `skills/execute/references/review-and-merge.md` as the shared rules say, with these substitutions:

- Where it says "the issue number and title it closes", give the reviewer **every** story in the set, by number and title, with its acceptance criteria. A reviewer who does not know a story is in scope reads its code as unexplained.
- **Add one question to the reviewer's lens:** is there anything in this diff that belongs to **none** of the listed stories? Scope creep hides far better in a multi-story diff. Anything found is removed from the branch or explained in the PR body.
- Its **severity rubric** is unchanged. A larger diff invites more observations, and the rubric is what stops them being raised.
- Its Phase 9 fix-in-scope rule reads against **all** the stories the PR closes. Its re-review test is unchanged.
- Its Phase 10 duplicate-PR stop condition applies **per story**: a possible duplicate flagged against any story stops the merge for the whole pull request, because the PR is indivisible.
- When Phase 10 merges, it reads `skills/execute/references/merge.md` unchanged. Its settle step, `wf post-merge --pr {pr_number}`, already closes and moves **every** issue the pull request closes; report each settled story by number and title, and the `unblocked` sweep, because a bulk set is the run most likely to free downstream work.

**When no separate context can be spawned**, its Phase 8 step 3 applies unchanged, and a long bulk session is likelier to need it. Carry the whole lens yourself in one deliberate pass, in the reference's order and under the same rubric, ending with the bulk question: the failure mode of an inline review of a large diff is a skim that reports nothing. The disclosure lists every story the PR closes by number and title. It does not stop the merge; the gates that do all still apply.

---

## Escape hatches

Read `skills/execute/references/escape-hatches.md` when a run leaves the happy path, with these substitutions for a set:

- **Blocked.** One story blocking does not block the run. Drop it (`references/set-selection.md`, **Dropping a story**, then `/synergy:block-story` for it) and carry on. Block the whole run only when the set drops below one buildable story and no code exists yet.
- **Dependency.** A dependency *inside* the set needs no hatch: it is built first, as Phase 1 ordered. A dependency on an open issue *outside* the set drops that story. Never chain a bulk branch off another feature branch.
- **Too large.** Shrink the set, do not slice a story. Leave the dropped ones in the pool for their own run.
- **Failure reporting.** Comment the failure on **every** claimed issue before exiting and set each to `Needs attention`. Once the pull request is open, comment on the PR instead and leave the stages at `In Review`.
