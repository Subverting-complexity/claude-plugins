---
name: execute
description: 'End-to-end story execution: pick → plan → build → test → PR'
when_to_use: >-
  Trigger when the user wants development work done. Any of these:
  "next story", "start the next story", "pick up a story", "what's next",
  "work on story N", "do story N", "story #N", "#N", "do N", just a bare issue number,
  "start working", "build the next feature", "execute", "run the workflow",
  "implement", "develop", "build this", "implement story N", "develop N",
  "new feature", "start a feature" (use mode=feature),
  "fix bugs", "fix the next bug", "fix security issues", "tech debt", "maintenance" (use mode=maintenance),
  "audit the codebase", "audit for security", "security audit", "code audit", "run an audit" (use mode=audit).
  Also trigger when the user pastes a GitHub issue URL or references an issue number.
depends-on:
  - code-architect
  - structured-coding
  - feature-discovery
argument-hint: '[issue#] [--mode feature|maintenance|audit]'
arguments:
  - name: story_number
    description: 'Optional issue number. If omitted, picks the next story from the backlog.'
  - name: mode
    description: 'Execution mode: story (default — picks highest priority issue regardless of type), feature (feature stories only), maintenance (bug/security/architecture/debt; "bug" is accepted as alias), audit (codebase audit, no code changes)'
---

# Execute Story

End-to-end story execution workflow. Picks a story from the backlog,
plans the implementation, builds it, runs tests, and opens a PR.

**This workflow is fully autonomous.** Every phase flows into the next
without pausing for user input. Do not ask the user to choose, confirm,
or approve at any step. Do not call grill-me. The only reasons to stop
are:

- The issue is so underspecified that any implementation would be a
  guess — block the story and pick the next one.
- The story needs to be broken into sub-stories before implementation
  can begin — run `/github-workflow:feature-discovery` to plan the
  breakdown with the user, then pick the first sub-story.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command (the configuration loaded below will be stale).
If the user chooses "Continue anyway" or "Don't remind me", proceed.

## Project configuration (auto-loaded)

```!
if [ -f ClaudeProject.md ]; then
  cat ClaudeProject.md
else
  echo "ClaudeProject.md NOT FOUND"
fi
```

If the above shows "NOT FOUND" and preflight did not already handle
this, stop and tell the user to run `/github-workflow:setup` first.
Do not attempt to proceed without it — every subsequent step depends
on the values defined there.

Read `CLAUDE.md` for project rules and build principles.

## Session budget

Each agent session should stay under ~100k tokens. This means one story
per session, scoped to what can be completed within that budget. The
workflow is designed to produce a shippable artifact (branch + PR) every
session, not to run indefinitely.

**Practical guidelines:**

- **Commit early and often.** Make atomic commits as you complete each
  logical unit of work. If the session ends unexpectedly, committed work
  on a pushed branch is recoverable; uncommitted work is lost.
- **Push periodically.** After each major phase (plan complete, core
  implementation done, tests passing), push the branch. This creates a
  recovery point.
- **Scope to one session.** If Phase 3 (Plan) reveals the story is too
  large for a single session, split it: implement the highest-priority
  slice, open a PR for that slice, and create follow-up issues for the
  remainder using `/github-workflow:report-issue`.
- **Wrap up, don't run out.** If you sense you are deep into a session
  (many files read, many edits made, long planning phase), prioritise
  getting to a committable state. A partial PR with clear "remaining
  work" notes is better than an abandoned session with no artifact.
- **One story, one session.** Do not pick a second story after finishing
  the first. End the session so the next one starts with a fresh context.

**Session timeout awareness:**

Record the start time at the beginning of execution (use `date +%s` or
equivalent). Before starting each new phase, check elapsed time. If the
session has been running for more than 45 minutes:

1. Commit and push all current work immediately.
2. If you have enough for a PR, open one (draft if incomplete).
3. Create follow-up issues for any unfinished work.
4. Delete the scratch files (see **Scratch file cleanup**):
   `rm -f .claude/plan.md .claude/execution-checkpoint.md`.
5. Exit cleanly — do not start a new phase that you may not finish.

This prevents the harness from killing the session mid-work with nothing
saved.

## API rate limiting

GitHub API has rate limits (5,000 requests/hour for authenticated
users). Long autonomous sessions can accumulate many `gh` calls.

- Before making a batch of API calls (e.g., listing issues, checking
  milestones, updating board fields), check remaining quota:
  ```
  gh api rate_limit --jq '.rate.remaining'
  ```
- If remaining quota is below **100**, pause API-heavy operations.
  Commit and push any current work, delete the scratch files (see
  **Scratch file cleanup**), then exit with a message noting the rate
  limit. The next session will continue from the pushed state.
- Do not retry rate-limited requests in a loop — that makes it worse.

If the story is blocked or turns out to need more than one session's
worth of work, commit what you have, push the branch, open a draft PR
noting what's done and what remains, delete the scratch files (see
**Scratch file cleanup**), and exit. The next session can pick up from
the branch.

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`:

- **story** — Pick and implement the next highest-priority issue regardless of type
- **feature** — Pick only feature stories (type-story label)
- **maintenance** — Pick and fix the next bug, security, architecture, or tech debt issue (alias: bug)
- **audit** — Audit the codebase, create issues for findings, no code changes

If mode is "bug", treat it as "maintenance" (backward compatibility).

If mode is `audit`, skip to the Audit section at the bottom.

---

## Session state checkpoint

Before each phase transition, write `.claude/execution-checkpoint.md`
with the current state. This allows recovery if the session ends
unexpectedly:

```markdown
# Execution Checkpoint
- Story: #{number}
- Phase: {current_phase} ({phase_name})
- Branch: {branch_name}
- Files modified: {list from git diff --name-only}
- Tests passing: {yes/no/not yet run}
- Last updated: {ISO 8601 timestamp}
```

At the start of execution, check for an existing checkpoint file. A
checkpoint is only trustworthy if it still describes live, claimable
work — a stale or orphaned checkpoint must never trigger a resume.
Before acting on one, run **all** of these validation gates and discard
the checkpoint (delete the file and start fresh) if **any** fails:

1. **Freshness** — If the `Last updated` timestamp is older than
   `stale-timeout`, the checkpoint is stale. Discard it.
2. **Issue still open** — Read the recorded story:
   ```
   gh issue view {number} --repo {org}/{repo} --json state,assignees,closedByPullRequestsReferences
   ```
   If the issue is `CLOSED` (already merged or otherwise resolved), the
   checkpoint is orphaned. Discard it.
3. **Still ours** — If the issue is open but **not** assigned to `@me`
   (another agent reclaimed it, or a human reassigned it), do not steal
   it back. Discard the checkpoint.
4. **Branch still exists** — Confirm the recorded branch is present
   locally or on the remote:
   ```
   git rev-parse --verify {branch_name} 2>/dev/null \
     || git ls-remote --exit-code --heads origin {branch_name}
   ```
   If the branch is gone, the work cannot be resumed. Discard the
   checkpoint.

If **every** gate passes, the checkpoint describes resumable work:

1. Read the checkpoint to determine where the previous session stopped.
2. Check out the recorded branch.
3. Reconcile against reality before trusting the recorded phase — run
   `git status` and `git diff --name-only`, and re-read `.claude/plan.md`
   to confirm which files are actually done. Resume from the recorded
   phase only if the on-disk state is consistent with it; otherwise fall
   back to the earliest phase the concrete state supports (the same
   resume-point logic used for stale PRs in Phase 1).

When discarding a checkpoint, delete both `.claude/execution-checkpoint.md`
and any orphaned `.claude/plan.md`, then proceed with a normal Phase 1
pick.

### Scratch file cleanup

This skill writes two per-session scratch files: `.claude/plan.md`
(Phase 3) and `.claude/execution-checkpoint.md` (rewritten before every
phase transition). Both are gitignored, but they must still be removed
on **every** exit path so no stale scratch lingers in the worktree — a
leftover scratch file is what originally blocked harness worktree
auto-cleanup. As the **final** step before the session ends, and always
**after** any commit/push (so the pushed branch — not scratch — is the
source of truth), delete both files:

```
rm -f .claude/plan.md .claude/execution-checkpoint.md
```

This applies to **all** exits without exception:

- Phase 7 completes successfully.
- Blocked via `/github-workflow:block-story`.
- Unrecoverable error (after leaving the failure comment).
- Session-budget or 45-minute timeout exit.
- API rate-limit pause.
- One-session overflow (partial slice shipped, follow-ups filed).

Cross-session resume does **not** depend on leftover scratch: a later
session recovers the work from the pushed branch through Phase 1
stale-task recovery, not from these files. (Within-session context
compaction is unaffected — no exit occurs, so the files remain on disk
for the duration of the run.)

---

## Phase 1 — Pick

If `$ARGUMENTS.story_number` is provided, use that issue directly.
Otherwise, run the pick-story logic (including stale task recovery):

1. Read `ClaudeProject.md` for org, repo, label map, stale-timeout,
   `agent-gating` mode, and the `claude-ready` label name.
1b. Run stale task recovery — check for issues assigned to @me with no
    branch or PR past the stale-timeout. Auto-resolve each stale issue:
    - **PR or issue has `approved` label**: skip entirely — waiting for
      human merge, do not touch.
    - **Stale PR with review feedback** (`changes-requested` or
      `needs-discussion` label): check out the branch and run
      `/github-workflow:update-pr` to address it, then continue to
      Phase 7 (Finish).
    - **Stale PR without review feedback**: check out the branch and
      determine the resume point by checking concrete state:
      - Run the quality gate. If it passes → Phase 7 (Finish).
      - If quality gate fails, check `git log --oneline` for commits
        beyond the branch point. If commits exist → Phase 5 (Verify).
      - If no commits beyond branch point → Phase 4 (Build).
    - **Stale branch with no PR**: check it out and check for commits
      beyond the branch point (`git log origin/{default-branch}..HEAD
      --oneline`). If commits exist, continue from Phase 5 (Verify).
      If no commits exist, delete the branch and reclaim the issue.
    - **No branch or PR**: reclaim the issue (unassign, comment) and
      include it in the normal pick pool below.
    - **Not stale yet**: skip — another session may be active.
1c. Auto-ready resolved dependencies — check issues assigned to
    `@me` that do NOT have the `status-ready` label. For each, parse
    the issue body for dependency markers (`Depends on #N`, `Blocked
    by #N`, `After #N`, `Requires #N`) and check the `## Dependencies`
    section. If all referenced issues are now `CLOSED`:
    - **Issues without `needs-refinement`**: apply `status-ready` and
      comment that dependencies are resolved. The issue re-enters the
      pick pool below.
    - **Issues with `needs-refinement`**: do NOT auto-promote to
      `status-ready`. Leave the `needs-refinement` label in place.
      Comment that dependencies are resolved and the story is ready
      for a refinement session. The story will be surfaced to the user
      when it reaches the top of the pick queue (see Phase 1 pick
      logic above).
    Best-effort — skip on API errors.
2. Check for milestones to detect backlog mode:
   ```
   gh api repos/{org}/{repo}/milestones --jq 'sort_by(.due_on) | .[] | select(.open_issues > 0) | {title, due_on, open_issues}'
   ```
3. **Sprint mode** (milestones found): pick from the earliest milestone
   with open issues, sorted by priority label then issue number.
4. **Flat mode** (no milestones): pick from open unassigned issues in
   the ready state (per `ready-gate`: label, board column, or both),
   sorted by priority then issue number.
5. **Maintenance mode**: filter to issues with maintenance type labels (type-bug, type-security, type-arch, type-debt from the label map).
6. **Feature mode**: filter to issues with the type-story label only.
7. **Story mode (default)**: no type filter — pick the highest priority issue regardless of type label. This is the most common mode.

**Filtering (all modes):** Before selecting a candidate, apply these
filters to the candidate list:

- **Blocked:** Exclude issues with the `needs-refinement` label
  (looked up from the label map in ClaudeProject.md).
- **Agent gating:** If `agent-gating` is `enabled` in
  ClaudeProject.md, exclude issues that do **not** have the
  `claude-ready` label. Only human-approved stories are eligible.
- **Dependencies:** For each of the top 10 candidates, parse the
  issue body for dependency markers (`Depends on #N`, `Blocked by
  #N`, `After #N`, `Requires #N`) and `## Dependencies` section
  references. For each referenced `#N`, check `gh issue view {N}
  --repo {org}/{repo} --json state --jq '.state'`. Skip the
  candidate if any dependency is still `OPEN`. Check at most 5
  dependency references per candidate.

**Never ask the user which story to pick.** Always auto-select using
priority labels then lowest issue number. If no candidates have
priority labels, pick the lowest issue number.

Read the full issue body. Check it has **Context** and **Requirements**.

- If the issue has the `needs-refinement` label (from the label map):
  surface it to the user. Tell them: "The next priority story
  (#{number}: {title}) needs refinement before it can be implemented.
  Would you like to refine it now?" Use `AskUserQuestion` with options:
  - "Refine now (Recommended)" — run the refinement skill configured
    in `refinement-skill` from ClaudeProject.md (default:
    `feature-discovery` in continuous mode; alternative: `grill-me`).
    After refinement completes, remove the `needs-refinement` label,
    apply `status-ready`, and continue with Phase 2.
  - "Skip and pick next" — leave the label, pick the next eligible
    story instead.
- If the issue has enough guidance (body, comments, linked docs): proceed.
- If truly empty with no guidance anywhere: run `/github-workflow:block-story`
  and pick the next one.

## Phase 2 — Start

1. Assign the issue:

   ```
   gh issue edit {number} --repo {org}/{repo} --add-assignee @me
   ```

2. Update project board to In Progress (if board configured in ClaudeProject.md).
   First resolve the board and the issue's `{item_id}` following
   `templates/board-resolution.md` — it decides whether a board is
   configured, verifies the stored `project-node-id` resolves to a board
   whose title matches `project-title` (aborting loudly on a mismatch),
   and adds the issue to the board if missing. Only run the mutation once
   it returns a verified `{item_id}`:

   ```
   gh api graphql -f query='mutation {
     updateProjectV2ItemFieldValue(input: {
       projectId: "{project_node_id}"
       itemId: "{item_id}"
       fieldId: "{status_field_id}"
       value: { singleSelectOptionId: "{in_progress_option_id}" }
     }) { projectV2Item { id } }
   }'
   ```

3. Set start date on board (if configured).

4. Fetch and branch:
   ```
   git fetch origin {default-branch}
   git checkout -b {branch} origin/{default-branch}
   ```

When **no** board is configured, skip the board update silently. When a
board **is** configured, board failures are loud: report the failure to
the user (e.g., "Board update failed: {error}. Continuing.") and proceed.

## Phase 3 — Plan

Use `/github-workflow:code-architect` to plan the implementation:

- Pass the issue requirements, relevant codebase context, and any
  reference docs listed in ClaudeProject.md.
- Code-architect should scan the existing codebase and plan changes
  based on the issue requirements. Do not run an interactive design
  interview or call grill-me.
- Write the architecture plan to `.claude/plan.md` so it survives
  context compaction. Include a checklist of files to create or modify,
  each with a `[ ]` checkbox. Example:
  ```
  ## Files
  - [ ] src/services/auth.ts — new auth service
  - [ ] src/routes/login.ts — add login endpoint
  - [ ] tests/auth.test.ts — auth service tests
  ```
- During Phase 4 (Build), mark each file `[x]` as you complete it.
  If the session compacts mid-build, re-read `.claude/plan.md` to see
  which files are done and which remain. Also check `git status` and
  `git diff --name-only` to confirm what has actually been modified.
- Consume the plan output and proceed to Build.
- Do not pause for confirmation.
- If requirements have gaps, make reasonable assumptions and note
  them in the plan. Only stop if the issue is so underspecified that
  any implementation would be a guess.

## Phase 4 — Build

Use `/github-workflow:structured-coding` to implement:

- Pass the architecture plan from Phase 3 and the issue requirements.
- Do not pause for user confirmation. The issue requirements and
  architecture plan from Phase 3 serve as the approved specification.
- Write code and tests together. Do not defer tests to a later phase.
- Follow build principles from `CLAUDE.md`:
  - One responsibility per file
  - Domain must not import from infrastructure. Strict layer boundaries.
  - Every module unit-testable in isolation. Inject dependencies.
  - Search for existing utilities before creating new ones
  - Write tests alongside the code, not after

## Phase 5 — Verify

Run the quality gate command from `ClaudeProject.md`:

1. Execute the quality gate script/command.
2. If it fails:
   a. Read the error output carefully.
   b. Fix the specific failing check.
   c. Re-run the quality gate.
   d. Repeat up to 3 times (4 total runs maximum).
3. If still failing after 4 total runs, commit what you have, open a
   draft PR noting the quality gate failure, and exit. Do not
   continue retrying — the issue likely requires changes outside the
   story's scope.

## Phase 6 — Commit

1. Stage only relevant files. Never stage `.env`, credentials, or
   generated files that should be gitignored.
2. Write a clear commit message: what was built and why.
3. The quality gate hook runs automatically on commit.
4. If you need multiple logical commits, prefer atomic commits that
   each leave the codebase in a working state.

## Phase 7 — Finish

1. Push the branch:

   ```
   git push -u origin HEAD
   ```

2. Create a real PR (not a draft). Write the body to a temporary
   file first, then use `--body-file` to avoid Windows/PowerShell
   shell-escaping issues:

   ```
   gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
   ```

   Delete the temp file after creation.

   - Title under 70 chars
   - Each linked issue on its own line: `Closes #42`
   - Include a test plan section
   - Summary of what was built and acceptance criteria addressed

2b. Validate the PR body was written correctly:

   ```
   gh pr view {pr_number} --repo {org}/{repo} --json body --jq '.body'
   ```

   If the body is empty, only whitespace, or consists of just `@`
   (a known Windows/PowerShell shell-escaping issue), write the body
   to a temporary file and retry with `--body-file`:

   ```
   gh pr edit {pr_number} --repo {org}/{repo} --body-file {tempfile}
   ```

   Clean up the temp file after. Re-validate. If still corrupted,
   warn the user.

3. Add claude labels. Resolve the `claude-authored` purpose key to its
   concrete name through the single path in `templates/default-labels.md`
   (the `ClaudeProject.md` label map, default `claude-authored`). After
   applying, verify the label was applied by reading back the PR
   labels. If missing, create the label with the guarded
   create-if-missing pattern from `templates/default-labels.md` (no
   `--force`) and retry once.

4. Update project board to In Review (if configured).

5. Delete both scratch files now that the work is shipped (see
   **Scratch file cleanup**):
   `rm -f .claude/plan.md .claude/execution-checkpoint.md`.

6. Report: display the PR URL, linked issues, and labels applied.

## Phase 8 — Self-Review

After the PR is created, perform a brief self-check to catch obvious
gaps before a human reviewer sees the PR.

1. Re-read the full PR diff:
   ```
   git diff origin/{default-branch}...HEAD
   ```

2. Re-read the original issue body and acceptance criteria.

3. For each acceptance criterion, verify it is addressed in the diff:
   - If addressed: note it as covered.
   - If missing or only partially addressed: flag it.

4. Check for common oversights:
   - New public functions without tests
   - TODO/FIXME comments left in committed code
   - Hardcoded values that should be configurable
   - Missing error handling on new external calls

5. If any gaps are found, write the comment body to a temporary file
   and post using `--body-file` (avoids Windows shell-escaping issues
   with multi-line content):
   ```
   gh pr comment {pr_number} --repo {org}/{repo} --body-file {tempfile}
   ```
   Delete the temp file after.

6. If no gaps are found, skip the comment — a clean PR needs no noise.

This phase is advisory only. It never blocks the PR or changes the
verdict. Its purpose is to surface issues early so the reviewer can
focus on deeper concerns.

---

## Audit mode

When `$ARGUMENTS.mode` is `audit`:

1. Read `ClaudeProject.md` for org, repo, and label map.
2. Audit the default branch — read the codebase structure, key files,
   and patterns. Check for architecture violations, security issues,
   test gaps, dead code, and tech debt. Use the evaluation criteria
   from the code-review skill (non-compliance gates, correctness,
   security, test coverage) but apply them to the codebase at large,
   not to a specific PR diff.
3. For each finding, run `/github-workflow:report-issue` to create
   a GitHub issue with the appropriate type and priority labels.
   Cap at 10 issues per audit session to keep scope manageable.
4. Report a summary of all issues created.
5. Do not make code changes. Do not create a branch or PR.

---

## Escape hatches

**Failure reporting**: If execution fails at any phase and cannot
recover, leave a structured comment on the issue before exiting.
Write the comment body to a temporary file and post using
`--body-file` (avoids Windows shell-escaping issues):

```
gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
```

The comment should include: phase name, error summary, branch name,
whether commits were pushed, what was completed, and what remains.
Delete the temp file after.

This ensures the next session (or human) can pick up exactly where
this one failed without guessing what happened. After the comment is
posted, delete the scratch files (see **Scratch file cleanup**) before
exiting.

**Blocked**: If any phase cannot proceed, run `/github-workflow:block-story`
with details, then delete the scratch files (see **Scratch file
cleanup**). Then pick the next story.

**Bug found**: If you discover an unrelated bug during development,
run `/github-workflow:report-issue`. Do not fix it inline unless it is
trivial and within the same scope.

**Dependency**: If this story depends on another unmerged story
(discovered during planning, not caught by the Phase 1 filter):

1. Build the dependency on its own branch from the default branch.
2. Branch the dependent story off the dependency branch.
3. Set the dependent PR's base to the dependency branch.
4. After merge, rebase onto the default branch and update the PR base.

If the dependency is not yet started, block this story instead
(`/github-workflow:block-story`) and pick the dependency — or the
next available story — instead.

**Story too broad**: If the story covers multiple distinct changes and
needs to be broken into sub-stories before implementation can begin,
run `/github-workflow:feature-discovery` to plan the breakdown with the
user, then pick the first sub-story.

**Review feedback**: After the PR is created, the code-review skill may
flag issues. Run `/github-workflow:update-pr` to address the feedback,
push fixes, and flag the PR for re-review.

**Story too large**: If the plan reveals the story exceeds one session's
budget, implement the highest-priority slice, open a PR for that slice,
and create follow-up issues for the remaining work using
`/github-workflow:report-issue`. Do not attempt to complete everything
in one session — a partial PR with clear notes is the expected outcome.
Delete the scratch files (see **Scratch file cleanup**) before exiting.
