# Execute — Pick paths only some runs take

Read the section `execute`'s `SKILL.md` sends you to: an explicit story number, a thin story, or Phase 2 recovery. A run that picks through `wf pick` and gets a well-specified story reads none of this.

## An explicit story number

Run the **already-in-flight guard** first. A named number bypasses the auto-pick pool, and the claim ref is released the moment a PR opens, so a fresh claim on a story already in review would succeed and duplicate the work.

```bash
gh issue view {number} --repo {org}/{repo} --json state,assignees
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number}
```

No label is read: state is the `Stage` field, and `pick --issue` refuses a story at `In Progress`, `In Review`, `Non-code` or `Done`. `sibling-pr` answers "which open PRs will close this issue on merge?" from GitHub's own closing-reference parse. Exit 0 with `found: 0` is the normal result; exit 20 means the lookup failed, so stop rather than assume there is no duplicate.

- The issue is **closed** → report it and stop.
- `found` is above zero → do not start fresh work. Report the existing PR by number **and** title and tell the user to run `/github-workflow:code-review`, which handles review and rework. Stop: do not claim, branch or build.
- The stage is `In Review` but `found` is `0` → look for a **closed, unmerged** PR:
  ```
  gh pr list --repo {org}/{repo} --state closed --search "closes #{number}" --json number,title
  ```
  If there is one, the PR was abandoned: unassign, run `wf stage-set {number} --stage stage-backlog` (that write returns it to the pool), and comment `"Resetting — PR #{N} closed without merge."` If there is none either, surface the inconsistency and stop.
- Otherwise claim it through the same engine, aimed at one issue:
  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout
  ```
  Read the result exactly as Phase 1 does. A `closed-already-resolved` side effect followed by `all-blocked` means the story was already finished: report that and pick the **next** story rather than stopping.

## A thin or empty story

- **Thin**, a real topic but not enough to implement without guessing, in a user-present session → ask with `AskUserQuestion`: "The next priority story (#{number}: {title}) needs refinement before it can be implemented. Would you like to refine it now?"
  - "Refine now (Recommended)" — run `/github-workflow:grill` on the story with the user, or the `refinement-skill` (default `feature-discovery`) when it needs breaking down, then continue with Phase 2. The stage is already `In Progress`.
  - "Skip and pick next" — send it to refinement as below.
- **Truly empty**, or thin with nobody present to answer → send it to refinement and re-run the selection for the next story. Do **not** run `/github-workflow:block-story`: blocked means an open blocked-by edge, and this issue has none, so nothing would ever release it.

Sending a story to refinement is a comment saying what is missing, the stage set to `Needs refinement`, and the assignment and claim given up:

```bash
gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" stage-set {number} --stage stage-refinement
gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --issue {number}
```

Write the comment to `skills/writing-github-issues/SKILL.md`: say what a person would have to add before it can be built, not that you could not build it.

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
