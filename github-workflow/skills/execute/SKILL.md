---
description: 'End-to-end story execution: pick → plan → build → test → PR'
when_to_use: >-
  Trigger when the user wants development work done. Any of these:
  "next story", "start the next story", "pick up a story", "what's next",
  "work on story N", "do story N", "story #N", "#N", "do N", just a bare issue number,
  "start working", "build the next feature", "execute", "run the workflow",
  "implement", "develop", "build this", "implement story N", "develop N",
  "fix bugs", "fix the next bug", "fix security issues" (use mode=bug),
  "audit the codebase", "audit for security", "code audit", "run an audit" (use mode=audit).
  Also trigger when the user pastes a GitHub issue URL or references an issue number.
arguments:
  - name: story_number
    description: 'Optional issue number. If omitted, picks the next story from the backlog.'
  - name: mode
    description: 'Execution mode: story (default), bug (pick next bug/security issue), audit (codebase audit, no code changes)'
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

Read `ClaudeProject.md` for all project-specific settings before starting.
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

If the story is blocked or turns out to need more than one session's
worth of work, commit what you have, push the branch, open a draft PR
noting what's done and what remains, and exit. The next session can pick
up from the branch.

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`:

- **story** — Pick and implement the next user story
- **bug** — Pick and fix the next bug, security, or architecture issue
- **audit** — Audit the codebase, create issues for findings, no code changes

If mode is `audit`, skip to the Audit section at the bottom.

---

## Phase 1 — Pick

If `$ARGUMENTS.story_number` is provided, use that issue directly.
Otherwise, run the pick-story logic (including stale task recovery):

1. Read `ClaudeProject.md` for org, repo, label map, and stale-timeout.
1b. Run stale task recovery — check for issues assigned to @me with no
    branch or PR past the stale-timeout. Auto-resolve each stale issue:
    - **PR or issue has `approved` label**: skip entirely — waiting for
      human merge, do not touch.
    - **Stale PR with review feedback** (`changes-requested` or
      `needs-discussion` label): check out the branch and run
      `/github-workflow:update-pr` to address it, then continue to
      Phase 7 (Finish).
    - **Stale PR without review feedback**: check out the branch and
      continue from wherever it left off (Phase 4 if code is
      incomplete, Phase 5 if it looks done, Phase 7 if just needs
      push/PR updates).
    - **Stale branch with no PR**: check it out, assess the state, and
      continue from the appropriate phase. If the branch has no
      meaningful work, delete it and reclaim the issue.
    - **No branch or PR**: reclaim the issue (unassign, comment) and
      include it in the normal pick pool below.
    - **Not stale yet**: skip — another session may be active.
2. Check for milestones to detect backlog mode:
   ```
   gh api repos/{org}/{repo}/milestones --jq 'sort_by(.due_on) | .[] | select(.open_issues > 0) | {title, due_on, open_issues}'
   ```
3. **Sprint mode** (milestones found): pick from the earliest milestone
   with open issues, sorted by priority label then issue number.
4. **Flat mode** (no milestones): pick from open unassigned issues with
   the status-ready label, sorted by priority then issue number.
5. **Bug mode**: filter to issues with bug/security/arch type labels.

**Never ask the user which story to pick.** Always auto-select using
priority labels then lowest issue number. If no candidates have
priority labels, pick the lowest issue number.

Read the full issue body. Check it has **Context** and **Requirements**.

- If the issue has enough guidance (body, comments, linked docs): proceed.
- If truly empty with no guidance anywhere: run `/github-workflow:block-story`
  and pick the next one.

## Phase 2 — Start

1. Assign the issue:

   ```
   gh issue edit {number} --repo {org}/{repo} --add-assignee @me
   ```

2. Update project board to In Progress (if board configured in ClaudeProject.md):

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

Board operations are best-effort. If they fail, report the failure to
the user (e.g., "Board update failed: {error}. Continuing.") and proceed.

## Phase 3 — Plan

Use `/github-workflow:code-architect` to plan the implementation:

- Pass the issue requirements, relevant codebase context, and any
  reference docs listed in ClaudeProject.md.
- Code-architect should scan the existing codebase and plan changes
  based on the issue requirements. Do not run an interactive design
  interview or call grill-me.
- Consume the architecture plan output and proceed to Build.
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
   d. Repeat up to 3 times.
3. If still failing after 3 attempts, investigate the root cause
   more deeply before trying again.

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

2. Create a real PR (not a draft):

   ```
   gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body "{body}"
   ```

   - Title under 70 chars
   - Each linked issue on its own line: `Closes #42`
   - Include a test plan section
   - Summary of what was built and acceptance criteria addressed

3. Add claude labels if configured in the label map.

4. Update project board to In Review (if configured).

5. Report: display the PR URL, linked issues, and labels applied.

---

## Audit mode

When `$ARGUMENTS.mode` is `audit`:

1. Read `ClaudeProject.md` for org, repo, and label map.
2. Run `/github-workflow:code-review` on the codebase.
3. For each finding, run `/github-workflow:report-issue` to create
   a GitHub issue with the appropriate type and priority labels.
4. Report a summary of all issues created.
5. Do not make code changes. Do not create a branch or PR.

---

## Escape hatches

**Blocked**: If any phase cannot proceed, run `/github-workflow:block-story`
with details. Then pick the next story.

**Bug found**: If you discover an unrelated bug during development,
run `/github-workflow:report-issue`. Do not fix it inline unless it is
trivial and within the same scope.

**Dependency**: If this story depends on another unmerged story:

1. Build the dependency on its own branch from the default branch.
2. Branch the dependent story off the dependency branch.
3. Set the dependent PR's base to the dependency branch.
4. After merge, rebase onto the default branch and update the PR base.

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
