# Execute — Pick paths only some runs take

Read the section `execute`'s `SKILL.md` sends you to: an explicit story number, a thin story, or Phase 2 recovery. A run that picks through `wf pick` and gets a well-specified story reads none of this.

## An explicit story number

Claim it through the same engine, aimed at one issue. The in-flight guard is part of the call: it refuses, with `all-blocked` and the reason, an issue that is closed, already closed by an open pull request, assigned, owned by a person, or at `In Progress`, `In Review`, `Non-code` or `Done`.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout
```

Read the result as Phase 1 does, plus:

- `open_prs` is present → do not start fresh work. Report the existing PR by number **and** title and tell the user to run `/synergy:pr-review`, which handles review and rework. Stop.
- `assignees` is present or `stage` is `In Review`, with no `open_prs` → look for a pull request that GitHub links to the issue and that was **closed without merging** (a merged one means the work is done, never abandoned):
  ```
  gh pr list --repo {org}/{repo} --state closed --search "#{number}" --json number,title,mergedAt,closingIssuesReferences --jq '[.[] | select(.mergedAt == null and any(.closingIssuesReferences[]; .number == {number}))]'
  ```
  If there is one, the PR was abandoned: unassign, run `wf stage-set {number} --stage stage-backlog` (that write returns it to the pool), comment `"Resetting — PR #{N} closed without merge."`, and pick it again. If there is none, report who holds it and stop.
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

`wf pick --checkout` normally does all of this. Redo only the step its `ok` result says did not happen, or the claim state lost to compaction.

1. **The claim.** Never issue a bare `--add-assignee @me` as a claim; the `refs/claims/` ref is the lock. Re-take it (a claim you already hold is a no-op) with `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim --issue {number}`. Exit 0: you hold it. Exit 27 (`lost`): another agent does, so stop and pick a different story. Exit 20: a broken environment, not a rival; report it.
2. **The stage.** `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" stage-set {number} --stage stage-in-progress`. It always exits 0, but the stage is the issue's state, so a write that did not happen leaves the issue reading as available. Read `set` and `reason` and report a failure loudly ("Stage update failed: {reason}. Continuing.").
3. **Start clean.** Before branching by hand, run the **Start clean** check in `templates/worktree-hygiene.md`. A worktree provisioned dirty is inherited junk: reset it to a pristine baseline and report it.
4. **Branch.**
   ```
   git fetch origin {default-branch}
   git checkout -b {branch} origin/{default-branch}
   ```

**Claim–stage consistency.** If the stage write fails and the run is abandoned rather than continued, release the claim (`wf claim-release --issue {number}`), remove the `@me` assignment, and set the stage back to `stage-backlog`, which is the write that returns the issue to the pool.
