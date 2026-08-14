---
name: execute
description: >-
  End-to-end GitHub story execution: pick → plan → build → test → PR →
  independent review → merge (where enabled). Trigger when the user wants development work
  done — "next story", "work on story N", a bare issue number, "build this",
  "implement", "run the workflow", or a pasted GitHub issue URL. Use
  mode=feature for features, mode=maintenance for bugs/security/debt,
  mode=audit for a no-code-change codebase audit.
depends-on:
  - code-architect
  - structured-coding
  - feature-discovery
  - code-review
argument-hint: '[issue#] [--mode feature|maintenance|audit] [--no-merge] [--bypass-ci]'
arguments:
  - name: story_number
    description: 'Optional issue number. If omitted, picks the next story from the backlog.'
  - name: mode
    description: 'Execution mode: story (default — picks highest priority issue regardless of type), feature (feature stories only), maintenance (bug/security/architecture/debt; "bug" is accepted as alias), audit (codebase audit, no code changes)'
  - name: no-merge
    description: 'When set, stop after the independent review and rework instead of merging. The PR is left open carrying the reviewer verdict. Only meaningful where merging is switched on at all — see Auto-Merge on Approval.'
  - name: bypass-ci
    description: 'Passed through to the Phase 10 merge gate: treats CI as satisfied when remote checks are red or absent. Explicit, never default — use only when CI cannot run for reasons outside the PR (e.g. GitHub Actions billing).'
---

# Execute Story

End-to-end story execution workflow: pick a story from the backlog, plan,
build, test, open a PR, have that PR reviewed independently in a fresh
context, apply the fixes the review asks for, and — where the project has
opted into unattended merging — merge it. A story is finished when its PR
has been reviewed and answered, not when the PR opens. Nothing in this run
reviews its own work: the review that counts happens in Phase 8, in agent
contexts that never saw the build.

## Plain-English output

Everything you write for a person to read (plan, progress notes, PR description, final summary) follows `skills/_shared/wording-standard.md` and avoids `skills/_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

**This workflow is fully autonomous.** Every phase flows into the next
without pausing for user input — except the **interactive discovery
gate** before Phase 3 (user-present sessions only). The only reasons to
stop are:

- The issue is so underspecified that any implementation would be a
  guess — block the story and pick the next one.
- The story needs to be broken into sub-stories before implementation
  can begin — run `/github-workflow:feature-discovery` to plan the
  breakdown with the user, then pick the first sub-story.

Opening the pull request is **not** one of them, and this is the most common
way the workflow fails: a run reaches Phase 7, writes a tidy summary of the
PR it opened, and offers to review and merge it if the user says the word.
That is a half-finished run reported as a finished one. Phases 8 to 10 need
no permission, no confirmation, and no green CI — keep going in the same turn.

## Invocation flags

`--no-merge` and `--bypass-ci` are read by Phase 10, long after they are
parsed, so record whichever was passed on disk now — a compaction in between
would otherwise lose them (the same reason preflight writes a marker file).
**Exit cleanup** deletes them, so each is valid for this run only.

```
mkdir -p .claude
rm -f .claude/no-merge.flag .claude/bypass-ci.flag \
      .claude/gate-failed.flag .claude/self-review.flag \
      .claude/claim-*.sha
touch .claude/no-merge.flag    # only when --no-merge was passed
touch .claude/bypass-ci.flag   # only when --bypass-ci was passed
```

The unconditional `rm -f` comes first because a previous run that was hard
killed before **Exit cleanup** would otherwise leave its flags behind, and an
inherited `bypass-ci.flag` would quietly disarm the Phase 10 CI gate.

Sweeping `claim-*.sha` is safe here and nowhere else: this run holds no
claim yet, so any such file is a leftover from a killed run, and leaving one
could make a later phase's won-claim guard read a lock this run does not hold.

**Run this block exactly once, here, at the start.** It is now destructive:
re-running it later — after a compaction, say — would wipe the
`gate-failed.flag` Phase 5 wrote and the `self-review.flag` Phase 8 wrote,
and would drop `no-merge.flag` if the invocation arguments are no longer in
context. Later phases only read these files.

## Preflight

First check whether preflight already passed this session — if
`.claude/preflight-passed.txt` exists, skip the invocation and go straight
to the project configuration block below. The file is written by
`preflight` on a clean or WARNING-only run and deleted by **Exit
cleanup**, so it is valid for exactly this session:

```
test -f .claude/preflight-passed.txt && echo "PREFLIGHT_ALREADY_PASSED"
```

If the file is absent and the block below did **not** print
"ClaudeProject.md NOT FOUND", invoke `/github-workflow:preflight` to
verify project configuration. (On NOT FOUND, skip preflight — the
handling below the block already produces the one actionable message.)
If preflight finds issues and the user chooses "Configure now", wait for
setup, then ask the user to re-run this command (the configuration loaded
below will be stale). On "Continue anyway" / "Don't remind me", proceed.

## Project configuration (auto-loaded)

This emits a **projection** of `ClaudeProject.md`: the hot-path config
the pick/plan/build window needs (Identity, Branch Convention, Label Map,
Ready Gate, Agent Gating, Quality Gate, Package Manager, Refinement),
dropping the heavy sections needed only later and only sometimes (Issue
Types & Fields, Project Board, Story Template, Session Budget, Reference
Docs, Bundled Skills). When a later phase resolves the **board** (Phase 2,
Phase 7) or **org issue fields**, read the omitted `## Project Board` /
`## Issue Types & Fields` section straight from `ClaudeProject.md` then —
the board/field templates already say they read it.

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

If the above shows "NOT FOUND", stop with exactly one message —
"ClaudeProject.md not found — run /github-workflow:setup." — and do not
chain into preflight for the same root cause. Do not proceed: every
subsequent step depends on the values defined there.

Otherwise validate the projection before proceeding: it must contain both
an `## Identity` and a `## Quality Gate` section. If either is missing,
stop with "ClaudeProject.md is missing required section: <name> — run
/github-workflow:setup."

Read `CLAUDE.md` for project rules and build principles.

## Session prewarm

Once preflight passes and the projected config is loaded, read the
current API quota — the only eager warm-up:

```
gh api rate_limit --jq '.rate.remaining'
```

Keep the result in context only. If the count is already below 100 here,
treat this as the rate-limit pause described in **API rate limiting** below
and exit after cleanup. (Skip the check in `audit` mode if you prefer —
the audit flow makes few writes.)

**Candidate and label fetches are deliberately *not* prewarmed** — the
happy path (`wf pick` → `ok`) never reads them: the inline fallback
fetches its own candidate list (`templates/story-selection.md` Step 1)
and Phase 7 fetches the label inventory on first use. On entering the
inline fallback, read `references/inline-fallback-prewarm.md`.

## Session budget

Stay under ~100k tokens: **one story per session**, scoped to a shippable
artifact — a merged PR, or an open one whose review state is recorded.
(design rationale: `references/execute-rationale.md` — not read at runtime.)

- **Commit early, push periodically.** Atomic commits per logical unit;
  push after each major phase (plan done, core done, tests passing) so an
  unexpected end leaves recoverable work on the branch.
- **One story, one session.** Do not pick a second story after finishing.
- **Wrap up, don't run out.** Deep into a session, prioritise getting to a
  committable state; a partial PR with "remaining work" notes beats an
  abandoned session.
- **Too large for one session** → implement the highest-priority slice,
  open a PR for it, and file follow-ups with `/github-workflow:report-issue`.
- **Retries respect the budget.** If the Phase 5 gate still fails after 2
  retries near the token budget or the 45-minute mark, stop retrying —
  take Phase 5's gate-failed exit (commit what you have) or block the
  story rather than burning the remaining budget on more runs.
- **The review phases spend some of their budget elsewhere.** Phases 8 and
  9 hand the reading and evaluating of the diff to separate agent
  contexts. What they cost *here* is `references/review-and-merge.md`, the
  merge mechanics Phase 10 loads, the findings the agents return, and the
  fixes you apply — and, if no subagent can be spawned, the whole
  code-review hot path inline. The rework loop stops once this session's
  budget is nearly spent.

**45-minute timeout.** Record the start time (`date +%s`); before each
phase, check elapsed. Past 45 minutes:

1. Commit and push everything now.
2. **Shippable** → run Phase 7 for a **real** PR (never a draft), then carry
   on into Phases 8 to 10: a reviewed PR is the point of the run, and the
   reviewing happens in other agents' contexts. Start a rework round only if
   you can finish it.
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
session resumes from the pushed branch. **Once the PR is open (Phase 8
onward)** the same carve-out as the failure hatch applies: leave the issue at
`status-in-review` and note the pause on the PR instead, so the label, the
board, and the PR's review state stay in agreement. Do **not** retry rate-limited
requests in a loop. (design rationale: `references/execute-rationale.md`
— not read at runtime.)

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`:

- **story** — Pick and implement the next highest-priority issue regardless of type
- **feature** — Pick only feature stories (type-story label)
- **maintenance** — Pick and fix the next bug, security, architecture, or
  tech debt issue ("bug" is accepted as an alias and treated as
  maintenance, for backward compatibility)
- **audit** — Audit the codebase, create issues for findings, no code changes

If mode is `audit`, do not run the phases below — read
`references/audit-mode.md` and follow it (a no-code-change codebase audit
that files issues for findings).

---

## Exit cleanup

Every exit path — successful finish, block, failure, timeout, rate-limit
pause — ends by running the canonical procedure in
`references/exit-cleanup.md` (release the claim ref, delete the scratch
files, reconcile the working tree to clean) as the **final** step,
**after** any commit/push. That file is the only place the procedure is
specified — read it rather than improvising the steps.

---

## Phase 1 — Pick

### Fast path — pick + start in one call (no explicit number)

With no `$ARGUMENTS.story_number` and mode `story`, `feature`, or
`maintenance` (not `audit`), the bundled `wf` picker collapses the whole
select → claim → board-move → branch loop — Phase 1's selection *and*
Phase 2's claim/board/branch — into one deterministic call. **Prefer
it.** From the repo root:

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
- **`unsupported`** — `wf` deferred this case (not expected; reserved for
  future unrecognised configurations). Use the inline selection below.
- **`error`**, or the launcher reports Python is missing — `wf` cannot run
  here. Use the inline selection below.

On any fall-through to the inline selection (any case other than `ok`),
first read `references/inline-fallback-prewarm.md` — it covers lazy
candidate fetching and label caching on this degraded path. Skip the fast
path entirely for an explicit number (it auto-selects) and for `audit`
mode.

### Explicit number / inline fallback

If `$ARGUMENTS.story_number` is provided, use that issue directly — but
first run the **already-in-flight guard** (needed only for an explicit
number; the auto-pick pool below already excludes assigned or non-ready
issues). It stops a second PR being built for a story already in review
or with an open PR — the claim ref was released the moment that PR
opened, so a fresh claim would otherwise succeed and duplicate the work.

```
gh issue view {number} --repo {org}/{repo} --json state,labels,assignees
```

Then find any open PR that already closes this issue by running the
authoritative lookup in `templates/sibling-pr-lookup.md` with this
`{number}`.

- If the issue is **closed**, report it and stop.
- If an **open PR already closes this issue**, do not start fresh work.
  Report the existing PR by number and title and tell the user to use
  `/github-workflow:code-review` (which handles both review and rework)
  — then stop. Do not claim, branch, or build.
- If the issue carries `status-in-review` but no open PR is found, check
  for a **closed (not merged)** PR (`closingIssuesReferences`, `states:
  CLOSED`). If found, the PR was abandoned — reset automatically: remove
  `status-in-review`, apply `status-ready`, unassign, move board to
  Backlog, comment `"Resetting — PR #{N} closed without merge."` The
  issue re-enters the pick pool.
  If no closed PR either — surface the inconsistency and stop.
- Otherwise **delegate the claim to the same engine the auto-pick fast
  path uses** — it targets this one issue, validates it, and **auto-closes
  it without a prompt if a merged PR already resolved it**:
  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout
  ```
  Interpret the result exactly as the fast path above: `ok` → on the
  branch, do only the body-validation check; Phase 2 is a no-op. A
  `closed-already-resolved` side effect then `status: all-blocked` means
  the story was already finished (closed and moved to Done) — report that
  and pick the **next** story instead of stopping. Fall back to the inline
  claim/validate below only on `error` or a missing interpreter; there,
  run the **already-resolved check** from `templates/story-selection.md`
  Step 3 (authoritative `closingIssuesReferences` over merged PRs) and
  auto-close + move to Done + advance the same way — never rebuild a story
  a merged PR already closed.

If no number is provided, **select a story** with the canonical procedure
in `templates/story-selection.md`, passing `$ARGUMENTS.mode` (default
`story`). It detects backlog mode (sprint vs flat); assembles the
unassigned candidate list per `ready-gate` (`label` / `board-column` /
`both` / `none`), applies the agent-gating and mode filters, and sorts by
priority then issue number; **claims the top candidate first, then
validates only that one** (dependencies + already-merged) — releasing and
trying the next only on failure, marking a genuinely-blocked issue
`status-blocked` or closing an already-resolved one; and runs the
dependency auto-ready scan **only if the pool comes up empty**. It returns
either a single **claimed** story (the atomic claim is held and
`status-in-progress` + `@me` are applied) or "No stories available" — in
which case stop. `agent-gating: disabled` (the default) means the
`claude-ready` human-approval label is **ignored entirely**. The atomic
claim is acquired *before* any side effect, so two agents never validate
or build the same issue.

**Then, on the claimed story**, read the full issue body and confirm it has
**Context** and **Requirements**:

- Enough guidance (body, comments, linked docs) → proceed to Phase 2.
- Carries `needs-refinement` (a configuration may surface such an issue) →
  offer refinement: "The next priority story (#{number}: {title}) needs
  refinement before it can be implemented. Would you like to refine it
  now?" Use `AskUserQuestion`:
  - "Refine now (Recommended)" — run the refinement skill from
    `refinement-skill` (default `feature-discovery`). After refinement,
    remove `needs-refinement`, apply `status-ready`, and continue with
    Phase 2.
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

2. Update the project board to In Progress. The auto-loaded projection
   dropped `## Project Board`, so read that section from
   `ClaudeProject.md` now for `project-node-id`, `project-title`,
   `status-field-id`, and the Status option ids. Resolve the board, the
   issue's `{item_id}`, and the target column's `{column_option_id}` per
   `templates/board-resolution.md`, then run its **Step 5** mutation to
   set Status — it decides whether a board is configured (silent skip when
   not), verifies board identity (loud abort on mismatch), adds the issue
   to the board if missing, and resolves the target column by purpose key.
   The target column for `status-in-progress` is **In Progress**
   (`col-in-progress`) per the pairing in `templates/default-labels.md`.

3. Set start date on board (if configured) — the Step 5 date-field form in
   `templates/board-resolution.md`. Also set the org-level
   **`Start date`** issue field to today (best-effort, capability-gated)
   per `templates/issue-fields-resolution.md` — independent of the board,
   skipped silently if the org does not define the field.

4. **Start clean.** Before branching, run the **Start clean** check in
   `templates/worktree-hygiene.md`. A worktree provisioned dirty (a reused
   or leaked worktree, or a checkout-time formatter) is inherited junk —
   reset it to a pristine baseline and report it, so it is never mistaken
   for this session's work or left to block worktree cleanup. The session
   must begin from a clean tree.

5. Fetch and branch:
   ```
   git fetch origin {default-branch}
   git checkout -b {branch} origin/{default-branch}
   ```

When **no** board is configured, skip the board update silently. When one
**is**, board failures are loud: report them (e.g., "Board update failed:
{error}. Continuing.") and proceed. **Claim–board consistency:** the
claim acquired in Phase 1 must never outlive the session's intent to
build. If the board move fails and the run is abandoned rather than
continued, release the claim (`templates/claim-procedure.md` **Release**)
and restore the prior lifecycle state — remove `status-in-progress` and
the `@me` assignment, re-apply `status-ready` — so the claim does not leak.

## Interactive discovery gate (before planning)

When **interactive** (user present, not an agent/cron run) and mode is
`story` or `feature`: run `/github-workflow:feature-discovery --mode
validation` to stress-test requirements before planning.

**Skip** when: autonomous/agent session, `maintenance`/`audit` mode, or
the issue body already has discovery output (`## Stories` /
`## Architecture` from a prior session).

## Phase 3 — Plan

Use `/github-workflow:code-architect` to plan the implementation:

- Pass the issue requirements, relevant codebase context, and any
  reference docs listed in ClaudeProject.md.
- Code-architect should scan the existing codebase and plan changes
  based on the issue requirements.
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
  If the session compacts mid-build, re-read `.claude/plan.md` for what
  is done and what remains, and check `git status` / `git diff
  --name-only` to confirm what was actually modified.
- Consume the plan output and proceed to Build.
- Do not pause for confirmation.
- If requirements have gaps, make reasonable assumptions and note
  them in the plan. Only stop if the issue is so underspecified that
  any implementation would be a guess.

**Ecosystem tools.** Before reading files blind to plan, check whether
`.claude/ecosystem.md` exists. If it does, the project opted into the
codebase-intelligence tools it lists — use them as the first move, not an
afterthought:

- **Graphify** listed → run `graphify . --update` first (fast, 0 tokens
  from the committed cache), then prefer `graphify query "..."` /
  `graphify explain X` over blind file search for "how does X connect to
  Y" structure questions. An accelerant, not a mandate — skip it when the
  answer is obvious.
- **Fallow** listed (TS/JS) → query it for existing exports and
  duplication so the plan reuses what is there rather than rebuilding it.

If the file does **not** exist, the project opted out — skip this whole
step silently, plan as normal, and never nag about it. If a listed tool is
not on `PATH`, note that in one line and carry on with normal planning — a
missing tool never blocks the run.

## Phase 4 — Build

Use `/github-workflow:structured-coding` to implement:

- Pass the architecture plan from Phase 3 and the issue requirements.
- Do not pause for user confirmation — the issue requirements and Phase 3
  plan are the approved specification.
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
   d. Repeat up to 3 times (4 total runs maximum). Near the token budget
      or the 45-minute mark, stop after 2 retries (3 runs) and treat it as
      still-failing (step 3) — do not burn the remaining budget on runs.
3. If still failing after 4 total runs, the code is complete but the gate
   is red. Commit what you have and proceed to Phase 7, but set the
   **gate-failed flag** — `mkdir -p .claude && touch .claude/gate-failed.flag`,
   because Phase 10 reads it long after this decision and a compaction in
   between would otherwise lose it and merge a red-gate PR. Phase 7 will
   open a **real** PR (never a draft)
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

When the quality gate has passed and the work is committed, **read
`references/finish.md`** and follow it end-to-end: push, duplicate-PR
detection, PR create, labels, board move, claim release, report.

**Do not review your own diff anywhere in this run.** The session that wrote
the code shares every assumption it was built on, so its verdict is worth
little; Phase 8 gets a real one from contexts that never saw the build. That
governs **whose judgement decides this PR, not whether the run continues** —
you still spawn the reviewers and own what they return, and Phase 7 hands the
PR to nobody: not the user, not a later session, not the standalone
`/github-workflow:code-review` command. Going straight from PR creation to
Phase 8 matters for a second reason too — see the claim window there.

## Phase 8 — Independent review, Phase 9 — Rework, Phase 10 — Merge

The moment the PR exists, **read `references/review-and-merge.md`** and
follow it to the end of the run — same turn as Phase 7, no asking, no waiting
on CI. Unlike merging, the review is **unconditional**: nothing switches it
off, and a run that ends at an unreviewed PR has not finished. Phase 8 claims the PR, then spawns two review agents
in parallel, each in a fresh context, to review it read-only — your session
built this code and cannot judge it independently — and posts one
consolidated verdict. Phase 9 fixes what they found, pushes, and re-reviews
with a fresh agent, looping until the verdict is approved as far as the
session budget allows. Phase 10 merges the PR and settles the linked issues.

**Merging is opt-in and off by default.** It runs only where
`review.config.md` sets `Auto-Merge on Approval` to `enabled` — the same
single switch that governs the standalone `/github-workflow:code-review`
command, so a project gets unattended merges because it asked for them, not
because of which command reached the PR. On a project that has not opted in,
the run ends at an approved PR waiting for a person, and that is a complete
run, not a failure. Several further conditions stop the merge before it is
attempted, and the mechanics themselves can stop short on absent or red CI
or a conflict needing judgment. The reference lists all of them. In every
one the PR is left open with its verdict on it and the report says what
remains. None of them is a reason to stop **before** Phase 8: they decide
only whether an already-reviewed PR merges.

---

## Escape hatches

If a run leaves the happy path — execution **fails** unrecoverably, a phase
is **blocked**, you find an unrelated **problem** to file, the story has an
unmerged **dependency**, it is **too broad** to start or **too large** for
one session, or **review feedback** arrives after the PR opens — **read
`references/escape-hatches.md`** and follow the procedure for that condition.
