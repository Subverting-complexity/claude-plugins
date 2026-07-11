---
name: execute
description: >-
  End-to-end GitHub story execution: pick → plan → build → test → PR. Trigger
  when the user wants development work done — "next story", "work on story N",
  a bare issue number, "build this", "implement", "run the workflow", or a pasted
  GitHub issue URL. Use mode=feature for features, mode=maintenance for
  bugs/security/debt, mode=audit for a no-code-change codebase audit.
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
or approve at any step. Do not call feature-discovery. The only reasons to stop
are:

- The issue is so underspecified that any implementation would be a
  guess — block the story and pick the next one.
- The story needs to be broken into sub-stories before implementation
  can begin — run `/github-workflow:feature-discovery` to plan the
  breakdown with the user, then pick the first sub-story.

## Preflight

Before doing anything else, check whether preflight already ran and
passed this session — if `.claude/preflight-passed.txt` exists, skip
the invocation entirely and proceed directly to the project configuration
block below. The file is written by `preflight` on a clean or
WARNING-only run and deleted by **Exit cleanup**, so it is valid for
exactly this session:

```
test -f .claude/preflight-passed.txt && echo "PREFLIGHT_ALREADY_PASSED"
```

If the file is absent and the configuration block below did **not** print
"ClaudeProject.md NOT FOUND", invoke `/github-workflow:preflight` to
verify project configuration. (On NOT FOUND, skip preflight — the handling
below the block produces the single actionable message, and invoking
preflight would only repeat the same root cause.) If preflight finds
issues and the user chooses "Configure now", wait for setup to complete,
then ask the user to re-run this command (the configuration loaded below
will be stale). If the user chooses "Continue anyway" or "Don't remind
me", proceed.

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
if [ -f .claude/projected-config.md ] && [ .claude/projected-config.md -nt ClaudeProject.md ] 2>/dev/null; then
  cat .claude/projected-config.md
elif [ -f ClaudeProject.md ]; then
  # Project ClaudeProject.md → drop the heavy sections only needed later.
  # Pure POSIX shell (no awk/tee) so it works wherever bash runs, including
  # a Windows bash whose PATH lacks the Unix coreutils that ship awk/tee.
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

If the above shows "NOT FOUND", stop with exactly one message —
"ClaudeProject.md not found — run /github-workflow:setup." — and do not
chain into preflight for the same root cause. Do not attempt to proceed:
every subsequent step depends on the values defined there.

Otherwise validate the projection before proceeding: it must contain both
an `## Identity` and a `## Quality Gate` section. If either is missing,
stop with "ClaudeProject.md is missing required section: <name> — run
/github-workflow:setup." A projection silently missing them would fail
much later, far from the cause.

Read `CLAUDE.md` for project rules and build principles.

## Session prewarm

Immediately after preflight passes and the projected config is loaded, read
the current API quota — this is the only eager warm-up:

```
gh api rate_limit --jq '.rate.remaining'
```

Keep the result in context only. If the count is already below 100 here,
treat this as the rate-limit pause described in **API rate limiting** below
and exit after cleanup. (Skip the check in `audit` mode if you prefer —
the audit flow makes few writes.)

**Candidate and label fetches are deliberately *not* prewarmed** — the
happy path (`wf pick` → `ok`) never reads them, so each is fetched lazily
on the only path that needs it: the inline fallback fetches its own
candidate list (`templates/story-selection.md` Step 1), and Phase 7
fetches the label inventory on first use. When you enter the inline
fallback, read `references/inline-fallback-prewarm.md` for the details.

## Session budget

Stay under ~100k tokens: **one story per session**, scoped to a shippable
artifact (branch + PR). (design rationale: `references/execute-rationale.md`
— not read at runtime.)

- **Commit early, push periodically.** Atomic commits per logical unit;
  push after each major phase (plan done, core done, tests passing) so an
  unexpected end leaves recoverable work on the branch.
- **One story, one session.** Do not pick a second story after finishing.
- **Wrap up, don't run out.** Deep into a session, prioritise getting to a
  committable state; a partial PR with "remaining work" notes beats an
  abandoned session.
- **Too large for one session** → implement the highest-priority slice,
  open a PR for it, and file follow-ups with `/github-workflow:report-issue`.
- **Retries respect the budget.** If the Phase 5 quality gate still fails
  after 2 retries and the session is near its token budget or the
  45-minute mark, stop retrying — take Phase 5's gate-failed exit (commit
  what you have) or block the story rather than burning the remaining
  budget on more runs.

**45-minute timeout.** Record the start time (`date +%s`); before each
phase, check elapsed. Past 45 minutes:

1. Commit and push everything now.
2. **Shippable** → run Phase 7 for a **real** PR (never a draft).
   **Not shippable** → leave the branch pushed, move the issue to
   `status-needs-attention` (remove `status-in-progress`) with a comment
   listing what remains; do **not** open a PR.
3. File follow-up issues for unfinished work.
4. Run **Exit cleanup** (`references/exit-cleanup.md`).
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
requests in a loop. (design rationale: `references/execute-rationale.md`
— not read at runtime.)

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`:

- **story** — Pick and implement the next highest-priority issue regardless of type
- **feature** — Pick only feature stories (type-story label)
- **maintenance** — Pick and fix the next bug, security, architecture, or tech debt issue (alias: bug)
- **audit** — Audit the codebase, create issues for findings, no code changes

If mode is "bug", treat it as "maintenance" (backward compatibility).

If mode is `audit`, do not run the phases below — read
`references/audit-mode.md` and follow it (a no-code-change codebase audit
that files issues for findings).

---

## Exit cleanup

Every exit path — successful finish, block, failure, timeout, rate-limit
pause — ends by running the canonical procedure in
`references/exit-cleanup.md`: release the claim ref, delete the scratch
files, reconcile the working tree to clean. Run it as the **final** step,
**after** any commit/push. That file is the only place the procedure is
specified — read it rather than improvising the steps. (design rationale:
`references/exit-cleanup-rationale.md` — not read at runtime.)

---

## Phase 1 — Pick

### Fast path — pick + start in one call (no explicit number)

When you were **not** given a `$ARGUMENTS.story_number` and the mode is
`story`, `feature`, or `maintenance` (not `audit`), the bundled `wf` picker
collapses the whole select → claim → board-move → branch loop — Phase 1's
selection *and* Phase 2's claim/board/branch — into a single deterministic
call. **Prefer it.** Run it from the repo root:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --checkout --mode {mode}
```

Interpret the result by its `status` field (the exit code mirrors it):

- **`ok`** — a story is claimed and you are on its branch. The JSON carries
  `number`, `title`, `url`, `labels`, `milestone`, `body`, `claim_ref`,
  `branch`, `checked_out`, `board_moved`, and `side_effects`; the
  `status-in-progress` + `@me` markers are applied and the claim ref is held.
  **Stop selecting — do not run the inline procedure or re-derive anything.**
  Surface any `side_effects` (issues returned to blocked, or closed as
  already-resolved). Then do **only** the body-validation check at the end of
  this phase (Context + Requirements), and go to Phase 2 — its claim/board/
  branch steps are already done, so treat them as no-ops. If `checked_out` is
  false, read `branch_message` (e.g. a rebase conflict against the default
  branch) and run `/github-workflow:block-story` instead of building.
- **`no-candidates`** / **`all-blocked`** — nothing was pickable. `wf`
  already ran the auto-ready dependency scan and retried once internally;
  stop with "No stories available for pickup".
- **`unsupported`** — `wf` deferred this case (not expected under normal
  conditions; reserved for future unrecognised configurations). Use the
  inline selection below.
- **`error`**, or the launcher reports Python is missing — `wf` cannot run
  here. Use the inline selection below.

When you fall through to the inline selection (any case other than `ok`),
first read `references/inline-fallback-prewarm.md` — it covers how candidate
fetching and label caching are handled lazily on this degraded path. Skip the
fast path entirely for an explicit number (it auto-selects) and for `audit`
mode.

### Explicit number / inline fallback

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
- Otherwise **delegate the claim to the same engine the auto-pick fast path
  uses** — it targets this one issue, validates it, and (the point of this
  change) **auto-closes it without a prompt if a merged PR already resolved
  it**:
  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout
  ```
  Interpret the result exactly as the fast path above: `ok` → on the branch,
  do only the body-validation check, then Phase 2 is a no-op. A
  `closed-already-resolved` side effect followed by `status: all-blocked`
  means the story was already finished — it has been closed and moved to Done;
  report that and pick the **next** story instead of stopping. Fall back to
  the inline claim/validate below only on `error` or a missing interpreter; in
  that fallback, run the **already-resolved check** from
  `templates/story-selection.md` Step 3 (authoritative `closingIssuesReferences`
  over merged PRs) and auto-close + move to Done + advance the same way — never
  rebuild a story a merged PR already closed.

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
    `feature-discovery`). After refinement, remove `needs-refinement`, apply
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
**Claim–board consistency:** the claim acquired in Phase 1 must never
outlive the session's intent to build. If the board move fails and the
run is abandoned rather than continued, release the claim
(`templates/claim-procedure.md` **Release**) and restore the prior
lifecycle state — remove `status-in-progress` and the `@me` assignment,
re-apply `status-ready` — so the claim does not leak.

## Phase 3 — Plan

Use `/github-workflow:code-architect` to plan the implementation:

- Pass the issue requirements, relevant codebase context, and any
  reference docs listed in ClaudeProject.md.
- Code-architect should scan the existing codebase and plan changes
  based on the issue requirements. Do not run an interactive design
  interview or call feature-discovery.
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

**Ecosystem tools.** Before reading files blind to plan, check whether
`.claude/ecosystem.md` exists. If it does, the project has opted into the
codebase-intelligence tools it lists — use them here as the first move, not
an afterthought:

- **Graphify** listed → run `graphify . --update` first (fast, 0 tokens from
  the committed cache), then prefer `graphify query "..."` / `graphify
  explain X` over blind file search for any "how does X connect to Y"
  structure question. It is a planning accelerant, not a mandate — reach for
  it when a graph view beats opening files, skip it when the answer is
  obvious.
- **Fallow** listed (TS/JS) → query it for existing exports and duplication
  so the plan reuses what is there rather than rebuilding it.

If `.claude/ecosystem.md` does **not** exist, the project opted out — skip
this whole step silently, plan as normal, and never nag about it. If the
file lists a tool but the command is not on `PATH`, note that in one line
and carry on with normal planning — a missing tool never blocks the run.

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
   d. Repeat up to 3 times (4 total runs maximum). If the gate still
      fails after 2 retries (3 runs) and the session is near its token
      budget or the 45-minute mark, stop retrying early and treat it as
      still-failing (step 3) — do not burn the remaining budget on runs.
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
`references/finish-and-self-review.md`** and follow it end-to-end. It
covers Phase 7 (push, duplicate-PR detection, create the PR, labels,
board move, claim release, report) and Phase 8 (the advisory self-review
pass against the acceptance criteria).

---

## Escape hatches

If a run leaves the happy path — execution **fails** unrecoverably, a phase
is **blocked**, you find an unrelated **problem** to file, the story has an
unmerged **dependency**, it is **too broad** to start or **too large** for
one session, or **review feedback** arrives after the PR opens — **read
`references/escape-hatches.md`** and follow the procedure for that condition.
