---
name: execute
description: >-
  End-to-end story execution: pick → plan → build → test → PR.
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

## Plain-English output

Everything you write for a person to read (the plan, progress notes, the PR description, and the final summary) follows `skills/_shared/wording-standard.md` and avoids `skills/_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

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

This emits a **projection** of `ClaudeProject.md`: the hot-path config
the pick/plan/build window needs (Identity, Branch Convention, Label Map,
Ready Gate, Agent Gating, Quality Gate, Package Manager, Refinement) and
drops the heavy sections that are only needed later, and only sometimes
(Issue Types & Fields, Project Board, Story Template, Session Budget,
Reference Docs, Bundled Skills). When a later phase resolves the **board**
(Phase 2, Phase 7) or **org issue fields**, read the omitted `## Project
Board` / `## Issue Types & Fields` section straight from `ClaudeProject.md`
at that point — the board/field templates already say they read it.

```!
if [ -f ClaudeProject.md ]; then
  awk '/^## /{d=0} /^## Issue Types/{d=1} /^## Project Board/{d=1} /^## Story Template/{d=1} /^## Session Budget/{d=1} /^## Reference Docs/{d=1} /^## Bundled Skills/{d=1} !d' ClaudeProject.md
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

Stay under ~100k tokens: **one story per session**, scoped to a shippable
artifact (branch + PR). (Why: `references/execute-rationale.md`, not read
at runtime.)

- **Commit early, push periodically.** Atomic commits per logical unit;
  push after each major phase (plan done, core done, tests passing) so an
  unexpected end leaves recoverable work on the branch.
- **One story, one session.** Do not pick a second story after finishing.
- **Wrap up, don't run out.** Deep into a session, prioritise getting to a
  committable state; a partial PR with "remaining work" notes beats an
  abandoned session.
- **Too large for one session** → implement the highest-priority slice,
  open a PR for it, and file follow-ups with `/github-workflow:report-issue`.

**45-minute timeout.** Record the start time (`date +%s`); before each
phase, check elapsed. Past 45 minutes:

1. Commit and push everything now.
2. **Shippable** → run Phase 7 for a **real** PR (never a draft).
   **Not shippable** → leave the branch pushed, move the issue to
   `status-needs-attention` (remove `status-in-progress`) with a comment
   listing what remains; do **not** open a PR.
3. File follow-up issues for unfinished work.
4. Run **Exit cleanup** (release the claim ref, delete the scratch file).
5. Exit — do not start a phase you may not finish.

## API rate limiting

Before a batch of `gh` calls, check remaining quota:

```
gh api rate_limit --jq '.rate.remaining'
```

If it is below **100**, pause: commit and push current work, move the
issue to `status-needs-attention` (remove `status-in-progress`) with a
comment noting the pause, run **Exit cleanup**, then exit — the next
session resumes from the pushed branch. Do **not** retry rate-limited
requests in a loop. (Why: `references/execute-rationale.md`, not read at
runtime.)

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
inside a session — run `/github-workflow:setup reap` to scan and free
stale refs automatically, or see **Reaping orphaned claims** in
`templates/claim-procedure-rationale.md` for the manual one-liner.
(Within-session context compaction is unaffected — no exit occurs, so
the files remain on disk for the duration of the run.)

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
   The auto-loaded projection dropped `## Project Board`, so read that
   section from `ClaudeProject.md` now for `project-node-id`,
   `project-title`, `status-field-id`, and the Status option ids.
   Resolve the board, the issue's `{item_id}`, and the target column's
   `{column_option_id}` following `templates/board-resolution.md`, then run
   its **Step 5** mutation to set Status — it decides whether a board is
   configured (skipping silently when not), verifies the stored
   `project-node-id` resolves to a board whose title matches `project-title`
   (aborting loudly on a mismatch), adds the issue to the board if missing,
   and resolves the target column by purpose key. The target column for
   `status-in-progress` is **In Progress** (`col-in-progress`) per the label
   ⇄ column pairing in `templates/default-labels.md`.

3. Set start date on board (if configured) — the Step 5 date-field form in
   `templates/board-resolution.md`. Also set the org-level
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

**Ecosystem tools (if configured).** If `.claude/ecosystem.md` exists, it
lists the codebase-intelligence tools installed for this project and how
to use them — honor it here:

- **Graphify** listed → run `graphify . --update` (fast, 0 tokens from the
  committed cache), then use `graphify query "..."` / `graphify explain X`
  to ground the plan in how the codebase actually connects, instead of
  reading files blind.
- **Fallow** listed (TS/JS) → query it for existing exports and duplication
  so the plan reuses what is there rather than rebuilding it.

Skip silently if the file does not exist or lists neither tool.

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

## Phase 7 — Finish & Phase 8 — Self-Review

When the quality gate has passed and the work is committed, **read
`references/finish-and-self-review.md`** and follow it. It covers Phase 7
(push, duplicate-PR detection, create the PR, apply review-state labels,
move the issue to `status-in-review`, release the claim, report) and
Phase 8 (the advisory self-review pass over the diff against the
acceptance criteria).

These steps live in a reference file, read only when you reach this point,
so the PR-creation machinery does not weigh on the pick/plan/build window
earlier in the session.

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

   **Ecosystem tools (if configured).** If `.claude/ecosystem.md` exists,
   run the tools it lists as part of the audit and turn their findings
   into issues like any other:
   - **Graphify** → `graphify . --update` then `graphify query` for
     architecture/dependency questions across the whole tree.
   - **Fallow** (TS/JS) → run it for unused exports, duplication, and
     complexity hotspots.
   - **ecc-agentshield** → `npx ecc-agentshield scan` to audit the Claude
     Code config (CLAUDE.md, `.claude/`, hooks, skills, MCP) for secrets,
     prompt-injection openings, and over-broad allowlists.
   Skip silently for any tool not listed.
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

**Problem found**: If you detect any problem during development that you
are not fixing in this story — an unrelated bug, a security flaw, a
layering/architecture violation, or tech debt — file it to the board so
it is fixed automatically. Run `/github-workflow:report-issue`
(autonomous — do not pause for confirmation). **No human approval is
needed**: it classifies the problem, applies the **actual issue type**
(bug, security, architecture, or tech debt) and priority, sets
`status-ready`, and places it on the board so the normal pickup flow
fixes it. Do not fix it inline unless it is trivial and within the same
scope. When you report what you did this session, name each filed item by
its actual type and number (e.g. "Filed bug #45", "Filed tech-debt
#46").

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
