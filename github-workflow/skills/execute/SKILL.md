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
2. If the work has reached a shippable state, run Phase 7 to open a
   **real** PR (never a draft). If it has not, leave the branch pushed
   and move the issue to the `status-needs-attention` lifecycle label
   (removing `status-in-progress`) with a comment listing what remains —
   do **not** open a PR for incomplete work.
3. Create follow-up issues for any unfinished work.
4. Run **Exit cleanup** — release the claim ref and delete the scratch
   file.
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
  Commit and push any current work, move the issue to
  `status-needs-attention` (removing `status-in-progress`) with a comment
  noting the rate-limit pause, run **Exit cleanup** (release the claim ref
  and delete the scratch file), then exit. The next session will continue
  from the pushed state.
- Do not retry rate-limited requests in a loop — that makes it worse.

If the story turns out to need more than one session's worth of work,
ship the shippable slice as a **real** PR via Phase 7 and file follow-up
issues for the remainder (see **Story too large** below). Never open a
draft. If no slice is shippable, leave the branch pushed, move the issue
to `status-needs-attention` with a comment on what remains, run **Exit
cleanup** (release the claim ref and delete the scratch file), and exit.
The next session can pick up from the branch.

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`:

- **story** — Pick and implement the next highest-priority issue regardless of type
- **feature** — Pick only feature stories (type-story label)
- **maintenance** — Pick and fix the next bug, security, architecture, or tech debt issue (alias: bug)
- **audit** — Audit the codebase, create issues for findings, no code changes

If mode is "bug", treat it as "maintenance" (backward compatibility).

If mode is `audit`, skip to the Audit section at the bottom.

---

## Exit cleanup

Every exit path must leave three things clean: the **atomic claim ref**,
the **per-session scratch file**, and the **working tree itself**. All
three cleanups are idempotent, so run them on *every* exit without
reasoning about which earlier step may already have handled them. Do this
as the **final** step before the session ends, and always **after** any
commit/push (so the pushed branch — not local state — is the source of
truth). Run them in order: release the claim, delete the scratch file,
then reconcile the tree (so the scratch file is gone before the tree
check runs).

### 1. Release the claim ref

Phase 1 acquired `refs/claims/issue-{number}` as the exclusive lock
(`templates/claim-procedure.md`). Because each session is self-contained
and **there is no cross-session resume**, a session that exits for *any*
reason no longer needs the claim. Holding it past exit would block every
future agent from ever picking the issue — and nothing reaps an
abandoned claim ref, so the issue would silently drop out of the pool
forever. Release it (idempotent — a harmless no-op if Phase 7.5 or
`block-story` already released it):

```
git push origin :refs/claims/issue-{number}
rm -f .claude/claim-issue-{number}.sha
```

Releasing frees only the **lock**. The human-visible marker (the
assignment) is intentionally left in place on a failed or timed-out exit
as a "this was attempted" signal next to the failure comment; only
`block-story` and a successful finish also clear ownership.

### 2. Delete the scratch file

This skill writes one per-session scratch file: `.claude/plan.md`
(Phase 3). It is gitignored, but it must still be removed so no stale
scratch lingers in the worktree — a leftover scratch file is what
originally blocked harness worktree auto-cleanup:

```
rm -f .claude/plan.md
```

### 3. Reconcile the working tree to clean

A worktree is auto-removed by the harness **only when it is clean**
(`docs/worktree-config.md`). A leftover uncommitted change — even a stray
formatter reflow — pins the worktree open forever. Run the **End clean**
procedure in `templates/worktree-hygiene.md`: `git status --porcelain`
must end empty. Because Phase 2 started from a clean tree, anything still
dirty here was produced by this session — commit a forgotten story file,
commit incidental formatting on unrelated files as a **separate `chore:`
commit** (do not fold it into the feature diff), or discard disposable
generated noise. **Never `git stash`** — the stash is shared across every
worktree on the clone. Leaving the tree dirty is never an option.

### Applies to all exits without exception

- Phase 7 completes successfully (claim already released in 7.5; the
  re-run here is a harmless no-op).
- Blocked via `/github-workflow:block-story` (which releases the claim
  for you — the re-run here is a no-op).
- Unrecoverable error (after leaving the failure comment).
- Session-budget or 45-minute timeout exit.
- API rate-limit pause.
- One-session overflow (partial slice shipped, follow-ups filed).

A crash, hard kill, or machine reboot can still skip this cleanup
entirely and orphan a claim ref. That residue cannot be prevented from
inside a session — see **Reaping orphaned claims** in
`templates/claim-procedure.md` for the manual one-liner that frees a
stuck ref. (Within-session context compaction is unaffected — no exit
occurs, so the files remain on disk for the duration of the run.)

---

## Phase 1 — Pick

If `$ARGUMENTS.story_number` is provided, use that issue directly — but
first run the **already-in-flight guard**. The auto-pick pool below
already excludes issues that are assigned or in any non-ready lifecycle
state, so this guard only matters for an explicit number: it stops a
second PR being built for a story that is already in review or already has
an open PR (the claim ref was released the moment that first PR opened, so
a fresh claim would otherwise succeed and duplicate the work).

```
gh issue view {number} --repo {org}/{repo} --json state,labels,assignees
```

Then find any open PR that already closes this issue by running the
authoritative lookup in `templates/sibling-pr-lookup.md` with this
`{number}`.

- If the issue is **closed**, report it and stop.
- If an **open PR already closes this issue**, do not start fresh work.
  Report the existing PR by number and title and tell the user to use
  `/github-workflow:update-pr` (to address feedback) or let code review
  reconcile it — then stop. Do not claim, branch, or build.
- If the issue carries `status-in-review` but no open PR is found, the PR
  may have been closed without the label being reset — surface this to the
  user and stop rather than guessing.
- Otherwise proceed to claim and build as normal.

If no number is provided, **select a story** with the canonical procedure
in `templates/story-selection.md`, passing `$ARGUMENTS.mode` (default
`story`). That procedure:

1. detects backlog mode (sprint vs flat),
2. assembles the unassigned candidate list per `ready-gate`
   (`label` / `board-column` / `both` / `none`), applies the agent-gating
   and mode filters, and sorts by priority then issue number,
3. **claims the top candidate first, then validates only that one**
   (dependencies + already-merged) — releasing and trying the next only on
   failure, marking a genuinely-blocked issue `status-blocked` or closing
   an already-resolved one, and
4. runs the dependency auto-ready scan **only if the pool comes up empty**.

It returns either a single **claimed** story (the atomic claim is held and
`status-in-progress` + `@me` are applied) or "No stories available" — in
which case stop. `agent-gating: disabled` (the default) means the
`claude-ready` human-approval label is **ignored entirely**; no extra label
is required. The atomic claim is acquired *before* any side effect, so two
agents never validate or build the same issue.

**Then, on the claimed story**, read the full issue body and confirm it has
**Context** and **Requirements**:

- Enough guidance (body, comments, linked docs) → proceed to Phase 2.
- Carries `needs-refinement` (a configuration may surface such an issue) →
  offer refinement: "The next priority story (#{number}: {title}) needs
  refinement before it can be implemented. Would you like to refine it
  now?" Use `AskUserQuestion`:
  - "Refine now (Recommended)" — run the refinement skill from
    `refinement-skill` (default `feature-discovery`; alternative
    `grill-me`). After refinement, remove `needs-refinement`, apply
    `status-ready`, and continue with Phase 2.
  - "Skip and pick next" — release the claim
    (`templates/claim-procedure.md` **Release**) and re-run the selection.
- Truly empty with no guidance anywhere → run
  `/github-workflow:block-story` (which releases the claim) and re-run the
  selection for the next story.

## Phase 2 — Start

1. Confirm the claim. The story was already claimed (and assigned) at the
   end of Phase 1 via `templates/claim-procedure.md` (**Acquire**). Re-run
   Acquire here only if Phase 1's claim state was lost to compaction — its
   re-entry check makes a still-held claim a no-op. Do **not** issue a bare
   `--add-assignee @me` as a claim; the `refs/claims/` ref is the lock.

2. Update project board to In Progress (if board configured in ClaudeProject.md).
   First resolve the board, the issue's `{item_id}`, and the target
   column's `{column_option_id}` following `templates/board-resolution.md`
   — it decides whether a board is configured, verifies the stored
   `project-node-id` resolves to a board whose title matches
   `project-title` (aborting loudly on a mismatch), adds the issue to the
   board if missing, and resolves the target column by purpose key. The
   target column for `status-in-progress` is **In Progress**
   (`col-in-progress`) per the label ⇄ column pairing in
   `templates/default-labels.md`. Only run the mutation once it returns a
   verified `{item_id}` and `{column_option_id}`:

   ```
   gh api graphql -f query='mutation {
     updateProjectV2ItemFieldValue(input: {
       projectId: "{project_node_id}"
       itemId: "{item_id}"
       fieldId: "{status_field_id}"
       value: { singleSelectOptionId: "{column_option_id}" }
     }) { projectV2Item { id } }
   }'
   ```

3. Set start date on board (if configured). Also set the org-level
   **`Start date`** issue field to today (best-effort, capability-gated)
   per `templates/issue-fields-resolution.md` — independent of the board,
   skipped silently if the org does not define the field.

4. **Start clean.** Before branching, run the **Start clean** check in
   `templates/worktree-hygiene.md`. If the worktree was provisioned dirty
   (a reused or leaked worktree, or a checkout-time formatter), that is
   inherited junk — reset it to a pristine baseline and report it, so it
   is never mistaken for this session's work or left to block worktree
   cleanup. The session must begin from a clean tree.

5. Fetch and branch:
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
3. If still failing after 4 total runs, the code is complete but the gate
   is red. Commit what you have and proceed to Phase 7, but set the
   **gate-failed flag**: Phase 7 will open a **real** PR (never a draft)
   carrying the `changes-requested` review-state label and a "Quality
   Gate Failed" section in the body, so a human sees it and the blocking
   label prevents merge until the gate is green. Do not continue
   retrying — the issue likely requires changes outside the story's scope.

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

1b. **Duplicate-PR detection.** Before creating, check whether another
   open PR already closes this issue on a different branch. Holding the
   issue claim through PR creation (it is released only in step 5, below)
   already serializes builders, so this should never fire — it is the
   backstop for a sub-second create-time race. Run the authoritative
   lookup in `templates/sibling-pr-lookup.md` with this `{number}` and
   ignore any result whose `headRefName` equals `{branch}` (that is your
   own about-to-be-pushed PR).

   If a sibling PR exists, still create your PR (so both are real and
   comparable) but prepend a flag line to the body so code review
   reconciles them and keeps the better one:

   ```
   > ⚠ Possible duplicate of #{sibling_number} — both close #{number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
   ```

   Report the duplicate to the user. Do not attempt to pick the winner or
   close the other PR here — that is code review's job (Step 2b of the
   code-review skill), where both PRs have full context.

2. Create a real PR (never a draft — this workflow does not open drafts).
   Write the body to a temporary file first, then use `--body-file` to
   avoid Windows/PowerShell shell-escaping issues:

   ```
   gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
   ```

   Delete the temp file after creation.

   - Title under 70 chars
   - **Always** close the associated issue: each linked issue on its own
     line as `Closes #42`. A story PR must never omit this.
   - Include a test plan section
   - Summary of what was built and acceptance criteria addressed
   - If the **gate-failed flag** is set (Phase 5), prepend a "Quality
     Gate Failed" section with the last error output.

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
   warn the user. Also confirm the body contains a `Closes #N` line for
   every linked issue; if any is missing, add it before proceeding.

3. Add PR labels — both resolved by purpose key through
   `templates/default-labels.md`:
   - `claude-authored` (provenance, default `claude-authored`).
   - The review-state **entry label**: `needs-review` (default
     `review-needs-review`) when the gate passed, or `changes-requested`
     (default `review-changes-requested`) when the gate-failed flag is
     set. Exactly one review-state label. This ensures the PR is never
     unlabelled and the reviewer can find it.

   After applying, verify by reading back the PR labels. If a label is
   missing, create it with the guarded create-if-missing pattern from
   `templates/default-labels.md` (no `--force`) and retry once.

4. Move the linked issue to the `status-in-review` lifecycle label,
   removing `status-in-progress` so exactly one state is present (resolve
   both by purpose key). This — not the board — is the authoritative
   "in review" signal:
   ```
   gh issue edit {number} --repo {org}/{repo} \
     --remove-label "{status_in_progress_label}" --add-label "{status_in_review_label}"
   ```
   Verify per `templates/default-labels.md`. Then update the project
   board to the **In Review** column (`col-in-review`) — best-effort, if
   configured — following `templates/board-resolution.md` (which resolves
   the column option id by purpose key); the label ⇄ column pairing lives
   in `templates/default-labels.md`.

5. Release the atomic claim now that the PR exists — the open PR plus the
   assignment are the ownership markers, so the claim ref is no longer
   needed (`templates/claim-procedure.md` **Release**). This is the same
   release **Exit cleanup** runs; doing it here, the moment the PR is
   live, just frees the ref sooner. Then delete the scratch file now that
   the work is shipped:
   ```
   git push origin :refs/claims/issue-{number}
   rm -f .claude/claim-issue-{number}.sha .claude/plan.md
   ```
   The claim-ref delete is idempotent — ignore an error if it is already
   gone. The issue stays assigned to @me through review.

6. Report: display the PR by number **and** title together (e.g.
   `#123 Add login button`, never the number alone) plus its URL, the
   linked issues (each by number **and** title), and labels applied.

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

Then move the issue to the `status-needs-attention` lifecycle label
(removing `status-in-progress` so exactly one state is present, resolved
by purpose key) so the failure is visible in the issues list. Do **not**
open a PR for failed/incomplete work.

This ensures the next session (or human) can pick up exactly where
this one failed without guessing what happened. After the comment is
posted, run **Exit cleanup** (release the claim ref so the issue can be
picked again, and delete the scratch file) before exiting.

**Blocked**: If any phase cannot proceed, run `/github-workflow:block-story`
with details (it releases the claim for you), then run **Exit cleanup**
(release is a no-op at this point; delete the scratch file). Then pick
the next story.

**Bug found**: If you discover an unrelated bug during development,
run `/github-workflow:report-issue`. Do not fix it inline unless it is
trivial and within the same scope.

**Dependency**: If this story depends on another unmerged story
(discovered during planning, not caught by the Phase 1 filter), there is
**one** rule — chaining is only allowed when the dependency's branch is
already published; otherwise block:

- **Dependency branch exists on the remote** (the other story is in
  review or in progress and has pushed): you can chain off it.
  1. Branch the dependent story off the dependency branch.
  2. Set the dependent PR's base to the dependency branch.
  3. After the dependency merges, rebase onto the default branch and
     update the PR base.
- **Dependency branch does not exist on the remote** (not started, or
  started but unpushed — you cannot build on what you cannot fetch):
  do **not** fork a parallel copy. Block this story
  (`/github-workflow:block-story`, recording `Blocked by #N`) and pick
  the dependency — or the next available story — instead.

This is the same policy the Phase 1 dependency filter enforces (skip a
dependent story while its dependency issue is open): chaining is the
narrow exception for a dependency that is already pushed, not a parallel
route around an unfinished one.

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
Run **Exit cleanup** (the open PR already released the claim in Phase
7.5; delete the scratch file) before exiting.
