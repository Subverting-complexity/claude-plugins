---
name: execute
description: >-
  End-to-end GitHub story execution: pick → plan → build → test → PR →
  independent review → merge (where enabled). Trigger when the user wants
  development work done — "next story", "work on story N", "start story N",
  "pick a story", "pick story N", "what's next", a bare issue number,
  "build this", "implement", "run the workflow", or a pasted GitHub issue
  URL. Use mode=feature for features, mode=maintenance for
  bugs/security/debt, mode=audit for a no-code-change codebase audit.
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

## Output standard

Everything a person reads — plans, questions, findings, summaries, and
anything posted or committed — follows `skills/_shared/wording-standard.md`
for how it reads, `skills/user-facing-communication/SKILL.md` for what it
contains and in what order (outcome and current state first, then anything
outstanding, blocked or assumed, every work item named as well as numbered,
no investigation history), and `skills/_shared/banned-patterns.md` for what
must never appear. Every reply, not only the last one.

**This workflow is fully autonomous.** Every phase flows into the next
without pausing for user input — except the **interactive discovery
gate** before Phase 3 (user-present sessions only). The only reasons to
stop are:

- The issue is so underspecified that any implementation would be a
  guess — block the story and pick the next one.
- The story needs to be broken into sub-stories before implementation
  can begin — run `/github-workflow:feature-discovery` to plan the
  breakdown with the user, then pick the first sub-story.

Opening the pull request is **not** one of them. Phases 8 to 10 need no
permission, no confirmation and no green CI: the moment the PR exists, keep
going in the same turn. A run that reports its new PR and offers to review
and merge it if asked has stopped half way, however finished it sounds.

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

**Candidate and label fetches are deliberately *not* prewarmed.** `wf`
fetches what each command needs when it needs it, and nothing in this
workflow assembles a candidate list or a label inventory by hand.

## Session budget

Stay under ~100k tokens: **one story per session**, scoped to a shippable
artifact — a merged PR, or an open one whose review state is recorded.
(design rationale: `docs/rationale/execute-rationale.md` — not read at runtime.)

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
requests in a loop. (design rationale: `docs/rationale/execute-rationale.md`
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

## Fix in scope, file out of scope

One rule governs every problem this run finds, from the first line of the
build to the last review round:

- **In this PR's own diff, or in the story it closes** — fix it here, on
  this branch, before the PR merges. Never file it: a defect in the feature
  this run is building is this run's work to finish.
- **Anywhere else** — a pre-existing bug in untouched code, a security or
  architecture problem noticed in passing, tech debt belonging to other work
  — file it with `/github-workflow:report-issue` and carry on. Do not fix it
  inline; that widens the diff the reviewer has to judge.

Two exceptions stay filed: a finding only a person can settle (an ambiguous
requirement, an architectural choice with several defensible answers), filed
as the **question** with the PR left open on that verdict; and scope
deliberately deferred from a too-large story, which is remaining work rather
than a review finding. (why: `docs/rationale/execute-rationale.md` — not read at
runtime.)

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

`wf pick` collapses the whole select → claim → board-move → branch loop —
Phase 1's selection *and* Phase 2's claim, board move and branch — into one
deterministic call. It is the only way to pick a story. There is no inline
procedure behind it: a `wf` that cannot run is a stop, not a detour.

From the repo root:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --checkout --mode {mode}
```

`{mode}` is `$ARGUMENTS.mode`, default `story` (`audit` never reaches this
phase). The command detects backlog mode (sprint or flat), assembles the
unassigned candidates the project's `ready-gate` allows, applies the
agent-gating and mode filters, sorts by priority then issue number, **claims
the top candidate before any side effect** and validates only that one —
walking down the list on a lost claim, marking a genuinely blocked issue
`status-blocked`, closing one a merged PR already resolved, and running the
dependency auto-ready scan if the pool comes up empty. `agent-gating:
disabled` (the default) means the `claude-ready` human-approval label is
ignored entirely.

Read the result by its `status`; the exit code mirrors it:

| `status` | exit | What you do |
| -------- | ---- | ----------- |
| `ok` | 0 | A story is claimed and you are on its branch. **Stop selecting — do not re-derive anything.** |
| `no-candidates` | 10 | Nothing was pickable. Stop with "No stories available for pickup". |
| `all-blocked` | 11 | Every candidate was blocked or already claimed. Stop the same way. |
| `unsupported` | 30 | `wf` deferred this configuration (reserved; not expected). Stop and report what it named. |
| `error` | 20, or the launcher reports Python is missing | `wf` cannot run here. Stop and name the prerequisite: `wf` needs Python 3.8+ on `PATH` and an authenticated `gh`. Do not select a story by hand. |

On `ok` the JSON carries `number`, `title`, `url`, `labels`, `milestone`,
`body`, `claim_ref`, `branch`, `checked_out`, `board_moved`,
`start_date_set` and `side_effects`. The `status-in-progress` label and the
`@me` assignment are applied and the claim ref is held. Surface any
`side_effects` (issues returned to blocked, or closed as already resolved),
then do **only** the body-validation check at the end of this phase and go
to Phase 2 — whose claim, board and branch steps are already done. If
`checked_out` is false, read `branch_message` (e.g. a rebase conflict
against the default branch) and run `/github-workflow:block-story` instead
of building.

### An explicit story number

With `$ARGUMENTS.story_number`, run the **already-in-flight guard** first.
The auto-pick pool excludes assigned and non-ready issues, but a named
number bypasses that, and the claim ref is released the moment a PR opens —
so a fresh claim on a story already in review would succeed and duplicate
the work.

```bash
gh issue view {number} --repo {org}/{repo} --json state,labels,assignees
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number}
```

`sibling-pr` answers "which open PRs will close this issue on merge?" from
GitHub's own parse of closing references — the same parse that auto-closes
the issue — so every site that asks gets the same answer. Exit 0 with
`found: 0` is the normal result; exit 20 means the lookup failed, so stop
rather than assume there is no duplicate.

- The issue is **closed** → report it and stop.
- `found` is above zero → do not start fresh work. Report the existing PR by
  number **and** title and tell the user to run
  `/github-workflow:code-review`, which handles both review and rework. Stop
  — do not claim, branch or build.
- The issue carries `status-in-review` but `found` is `0` → look for a
  **closed, unmerged** PR:
  ```
  gh pr list --repo {org}/{repo} --state closed --search "closes #{number}" --json number,title
  ```
  If there is one the PR was abandoned — reset automatically: remove
  `status-in-review`, apply `status-ready`, unassign, run `wf board-move
  {number} --column col-backlog`, and comment `"Resetting — PR #{N} closed
  without merge."` The issue re-enters the pick pool. If there is no closed
  PR either, surface the inconsistency and stop.
- Otherwise claim it through the same engine, aimed at one issue:
  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout
  ```
  Read the result exactly as above. A `closed-already-resolved` side effect
  followed by `all-blocked` means the story was already finished — report
  that and pick the **next** story rather than stopping.

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
  - "Skip and pick next" — release the claim (`wf claim-release --issue
    {number}`) and re-run the selection.
- Truly empty with no guidance anywhere → run
  `/github-workflow:block-story` (which releases the claim) and re-run the
  selection for the next story.

## Phase 2 — Start

`wf pick --checkout` already did every step here. Read on only when the `ok`
result says one did not happen — `board_moved` or `checked_out` false, or the
claim state lost to compaction.

1. **The claim.** Held since Phase 1. Never issue a bare `--add-assignee @me`
   as a claim; the `refs/claims/` ref is the lock. To re-take a claim whose
   state was lost — a claim you already hold is a no-op:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim --issue {number}
   ```
   Exit 0: you hold it. Exit 27 (`lost`): another agent does — stop and pick a
   different story. Exit 20: a broken environment, not a rival; report it.

2. **The board.**
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" board-move {number} --column col-in-progress
   ```
   It decides for itself whether a board is configured (silent no-op when not),
   verifies the board's identity before writing, adds the issue if it is
   missing, and resolves the column by purpose key. It **always exits 0**: a
   board mirrors the lifecycle labels and is never the source of truth. Read
   `moved` and `reason`, and when a board *is* configured report a failure
   loudly ("Board update failed: {reason}. Continuing.") rather than stopping.

3. **Start date.** Set by `wf pick --checkout`; `start_date_set` says whether
   the org defines the field. Nothing to do here.

4. **Start clean.** Before branching, run the **Start clean** check in
   `templates/worktree-hygiene.md`. A worktree provisioned dirty (a reused or
   leaked worktree, or a checkout-time formatter) is inherited junk — reset it
   to a pristine baseline and report it, so it is never mistaken for this
   session's work or left to block worktree cleanup. The session must begin
   from a clean tree.

5. **Branch.** `wf pick --checkout` created and checked it out. By hand:
   ```
   git fetch origin {default-branch}
   git checkout -b {branch} origin/{default-branch}
   ```

**Claim–board consistency:** the claim from Phase 1 must never outlive the
session's intent to build. If the board move fails and the run is abandoned
rather than continued, release the claim (`wf claim-release --issue
{number}`) and restore the prior lifecycle state — remove
`status-in-progress` and the `@me` assignment, re-apply `status-ready` — so
the claim does not leak.

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
you still spawn the reviewer and own what it returns, and Phase 7 hands the
PR to nobody: not the user, not a later session, not the standalone
`/github-workflow:code-review` command. Going straight from PR creation to
Phase 8 matters for a second reason too — see the claim window there.

## Phase 8 — Independent review, Phase 9 — Rework, Phase 10 — Merge

The moment the PR exists, **read `references/review-and-merge.md`** and
follow it to the end of the run — same turn as Phase 7, no asking, no waiting
on CI. Unlike merging, the review is **unconditional**. Phase 8 claims the PR, then
spawns **one** review agent in a fresh context to read it read-only — your
session built this code and cannot judge it independently — carrying a
severity rubric that says what is worth raising at all, and posts the
verdict. Phase 9 fixes what it found on this branch — both the blocking
findings and the quick ones, repaired here rather than filed as issues for
somebody else — and re-reviews **only when the rework was substantial
enough to need a second reading**, once at most. Phase 10 merges the PR and
settles the linked issues.

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
