# Execute — Pick paths only some runs take

Read the section `execute`'s `SKILL.md` sends you to: an explicit story number, a thin story, or Phase 2 recovery. A run that picks through `wf pick` and gets a well-specified story reads none of this.

## An explicit story number

Claim it through the same engine, aimed at one issue. The in-flight guard is part of the call: it refuses, with `all-blocked` and the reason, an issue that is closed, already closed by an open pull request, assigned, owned by a person, or at `In Progress`, `In Review`, `Non-code` or `Done`.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout --body
```

An issue that is assigned or `In Review` only because a pull request closing it was **closed without merging** is reset first: unassigned, returned to `Backlog` with a comment, and then claimed. The result carries a `reset-abandoned-pr` side effect naming that PR; report it. A merged PR never counts, because it means the work is done.

Read the result as Phase 1 does, plus:

- `open_prs` is present → do not start fresh work. Report the existing PR by number **and** title and tell the user to run `/synergy:pr-review`, which handles review and rework. Stop.
- `assignees` is present or `stage` is `In Review` → somebody holds it and no abandoned PR explains it. Report who holds it and stop.
- `ok` with `prerequisite_for` → the story waits on open work this run can build, so `number` is its first prerequisite, already claimed. `SKILL.md` Phase 1 says how to go on.
- `all-blocked` whose reason names a blocker → the story waits on work nobody here may build. Report the reason and stop.
- A `closed-already-resolved` side effect followed by `all-blocked` → the story was already finished: report that and pick the **next** story rather than stopping.

## A thin or empty story

- **Thin**, a real topic but not enough to implement without guessing, in a user-present session (no `.claude/unattended.flag`) → ask with `AskUserQuestion`: "The next priority story (#{number}: {title}) needs refinement before it can be implemented. Would you like to refine it now?"
  - "Refine now (Recommended)" — run `/synergy:grill` on the story with the user, or the `refinement-skill` (default `feature-discovery`) when it needs breaking down, then continue with Phase 2. The stage is already `In Progress`.
  - "Skip and pick next" — send it to refinement as below.
- **Truly empty**, or thin with nobody present to answer → send it to refinement and re-run the selection for the next story. Do **not** run `/synergy:block-story`: blocked means an open blocked-by edge, and this issue has none, so nothing would ever release it.

Sending a story to refinement is one call. Write the comment to a file first, to `skills/writing-github-issues/SKILL.md`: say what a person would have to add before it can be built, not that you could not build it.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" refine --issue {number} --body-file {tempfile}
```

It sets the stage to `Needs refinement` first, then comments, unassigns and releases the claim, and reports each as `stage_set`, `commented`, `unassigned` and `claim_released`. Report any that is false.

## Phase 2 recovery

`wf pick --checkout` normally does all of this. Only when its `ok` result says a step did not happen (`stage_set` or `checked_out` false), or the claim state was lost to compaction, redo it in one call:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" start --issue {number}
```

It re-takes the claim (a claim this checkout holds is kept), sets `In Progress`, resets a tree provisioned dirty, and creates or checks out the story branch from `origin/{default-branch}`. Never issue a bare `--add-assignee @me` as a claim; the `refs/claims/` ref is the lock.

- **`ok`** (exit 0), one line — on the branch, ready to build. If `reason` names discarded paths, the worktree was provisioned dirty: report them.
- **`lost`** (exit 27) — another agent holds the story. Stop and pick a different one.
- **`partial`** (exit 24) — `reason` names what did not happen. A failed stage write is worth a loud line ("Stage update failed: {reason}. Continuing."), because the issue still reads as available. A branch that could not be created is a stop: run `/synergy:block-story`.
- **`error`** (exit 20) — a broken environment, not a rival. Report it.

**Claim–stage consistency.** If the stage write fails and the run is abandoned rather than continued, run `wf exit-cleanup --issue {number}`, remove the `@me` assignment, and set the stage back with `wf stage-set {number} --stage stage-backlog`, which is the write that returns the issue to the pool.
