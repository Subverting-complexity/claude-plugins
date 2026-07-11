---
name: execute
description: 'End-to-end local task execution: plan, build, verify, commit. No issue tracker or PR integration.'
when_to_use: >-
  Trigger when the user wants development work done locally — "build this",
  "implement this", "fix this", "code this up", or a user story / task
  description to build. This is the primary local orchestrator; prefer it over
  calling structured-coding or code-architect directly for end-to-end work. Do
  NOT use for reviewing code (use code-review), scoping features without
  building (use feature-discovery), or pre-merge verification (use
  verify-feature).
depends-on:
  - code-architect
  - structured-coding
  - feature-discovery
arguments:
  - name: mode
    description: 'Execution mode: build (default), audit (codebase audit, no code changes)'
---

# Execute Task

End-to-end local task execution workflow. Takes a task description, plans the
implementation, builds it, runs tests, and commits.

## Plain-English output

Everything you write for a person to read (the plan, progress notes, and the final summary) follows `skills/_shared/wording-standard.md` and avoids `skills/_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

## Project context (auto-loaded)

**Branch:** !`git branch --show-current 2>/dev/null || echo "(not a git repo or detached HEAD)"`

```!
if [ -f CLAUDE.md ]; then
  echo "=== CLAUDE.md ==="
  head -50 CLAUDE.md
  lines=$(wc -l < CLAUDE.md)
  if [ "$lines" -gt 50 ]; then
    echo ""
    echo "... ($lines total lines — read the full file for complete rules)"
  fi
else
  echo "No CLAUDE.md found"
fi

# Ecosystem tools onboarding nudge (informational — never blocks). local-workflow
# has no preflight, so this is its equivalent. Speak up only inside a real project
# (a git repo) that has neither opted in (.claude/ecosystem.md) nor out
# (.claude/ecosystem-declined). Declining once writes the marker, silencing it.
if [ -e .git ] && [ ! -f .claude/ecosystem.md ] && [ ! -f .claude/ecosystem-declined ]; then
  echo "ECOSYSTEM_TIP: companion tools (Graphify/RTK/etc.) not set up — optional"
fi
```

**`ECOSYSTEM_TIP` is informational, not a gate.** If the block above printed an
`ECOSYSTEM_TIP` line, this project has not opted into *or* out of the companion
tools. Surface it as **one** plain line early in your response — e.g. "Tip:
companion tools like Graphify aren't set up. Run `/local-workflow:ecosystem-setup`
to enable them, or skip — it's optional." — then carry on with the task. It never
blocks, never repeats within a run, and stops entirely once the user sets up or
declines (declining writes `.claude/ecosystem-declined`). If no `ECOSYSTEM_TIP`
line was printed, say nothing about ecosystem tools.

## Session budget

Each session should stay under ~100k tokens. This means one task per session,
scoped to what can be completed within that budget.

**Practical guidelines:**

- **Commit early and often.** Make atomic commits as you complete each logical
  unit of work. If the session ends unexpectedly, committed work is recoverable.
- **Scope to one session.** If Phase 2 (Plan) reveals the task is too large
  for a single session, implement the highest-priority slice, commit it, and
  note the remaining work for a follow-up session.
- **Wrap up, don't run out.** If you sense you are deep into a session, get
  to a committable state. A partial implementation with clear notes about
  what remains is better than an abandoned session with no artifact.
- **One task, one session.** Do not start a second task after finishing the
  first. End the session so the next one starts fresh.

## Mode selection

Default mode is `build`. Override with `$ARGUMENTS.mode`:

- **build** -- Take a task and implement it
- **audit** -- Audit the codebase, report findings, no code changes

If mode is `audit`, skip to the Audit section at the bottom.

---

## Phase 1 -- Understand

Read the task description provided by the user. If the user hasn't provided
one, ask for it.

Check if the task has enough guidance to proceed:

- What needs to be built or changed?
- What does "done" look like?
- Are there acceptance criteria?

If the task is underspecified, ask focused questions to fill the gaps. Use
`/local-workflow:feature-discovery` if the task is complex enough to warrant a full
interview.

## Phase 2 -- Plan

Use `/local-workflow:code-architect` to plan the implementation:

- Pass the task requirements and relevant codebase context.
- Code-architect should scan the existing codebase and plan changes
  based on the task description. Do not run an interactive design
  interview or call feature-discovery.
- Consume the architecture plan output and proceed to Build.
- Do not pause for confirmation.
- If requirements have gaps, make reasonable assumptions and note
  them in the plan. Only stop if the task is so underspecified that
  any implementation would be a guess.

If the plan reveals the task exceeds one session's budget, tell the user
and propose splitting it. Implement the highest-priority slice.

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

## Phase 3 -- Build

**Start clean.** Before making any edits, run the **Start clean** check in
`templates/worktree-hygiene.md`: `git status --porcelain`. If the tree is
already dirty, record the baseline and tell the user — a local session may
run in their own checkout, so pre-existing changes may be *their* work.
Leave those untouched and treat only the files you change from here on as
yours. This baseline is what lets the Exit cleanup tell your work apart
from what was already there.

Use `/local-workflow:structured-coding` to implement:

- Pass the architecture plan from Phase 2 and the task requirements.
- Do not pause for user confirmation. The task description and
  architecture plan from Phase 2 serve as the approved specification.
- Write code and tests together. Do not defer tests to a later phase.
- Follow build principles from `CLAUDE.md` if it exists.

## Phase 4 -- Verify

Run the project's test or quality gate command:

1. Execute the test/build/lint command.
2. If it fails:
   a. Read the error output carefully.
   b. Fix the specific failing check.
   c. Re-run.
   d. Repeat up to 3 times.
3. If still failing after 3 attempts, investigate the root cause more
   deeply before trying again.

If no quality gate command is configured, run whatever test commands the
project supports (e.g. `npm test`, `pytest`, `dotnet test`, `cargo test`).

## Phase 5 -- Commit

1. Stage only relevant files. Never stage `.env`, credentials, or generated
   files that should be gitignored.
2. Write a clear commit message: what was built and why.
3. If you need multiple logical commits, prefer atomic commits that each
   leave the codebase in a working state.

Do not push or create PRs. This is a local workflow. The user decides
what happens next.

After committing, run the **Exit cleanup** below so the tree ends clean.

## Phase 6 -- Report

Summarize what was done:
- What was built
- Which files were changed
- What tests were added or modified
- Any remaining work or known limitations

## Exit cleanup -- reconcile the working tree to clean

Run this as the **final** step on **every** exit path — success, blocked,
task-too-large, audit, or error — and always **after** any commit. It is
idempotent; run it without reasoning about which earlier phase may have
left the tree dirty.

A worktree is auto-removed by the harness **only when it is clean**
(`docs/worktree-config.md`). A leftover uncommitted change — even a stray
formatter reflow — pins the worktree open forever and strands the work
(there is no cross-session resume). Run the **End clean** procedure in
`templates/worktree-hygiene.md`: `git status --porcelain` must end empty
(or show only the pre-existing baseline you recorded at Start clean, which
is the user's and must be left untouched).

Because Start clean recorded what was already dirty, anything dirty here
that is **not** in that baseline was produced by this session — so:

- **Commit** a forgotten task file into the work.
- **Commit incidental formatting** on files outside the task as a
  **separate `chore:` commit** — do not fold it into the task's diff.
- **Discard** disposable generated noise (`git restore` / `git clean -fd`).

**Never `git stash`** — the stash is shared across every worktree on the
clone, and stashing would also bury the user's pre-existing changes.
Leaving the tree dirty (beyond the recorded baseline) is never an option.

---

## Audit mode

When `$ARGUMENTS.mode` is `audit`:

1. Read `CLAUDE.md` for project rules if it exists.
2. Review the codebase for issues: bugs, security vulnerabilities,
   architecture problems, code quality concerns.

   **Ecosystem tools.** If `.claude/ecosystem.md` exists, the project has
   opted into the tools it lists — run them as part of the audit and fold
   their findings into the report:
   - **Graphify** → `graphify . --update` then `graphify query` for
     architecture/dependency questions across the whole tree.
   - **Fallow** (TS/JS) → run it for unused exports, duplication, and
     complexity hotspots.
   - **ecc-agentshield** → `npx ecc-agentshield scan` to audit the Claude
     Code config (CLAUDE.md, `.claude/`, hooks, skills, MCP) for secrets,
     prompt-injection openings, and over-broad allowlists.
   If `.claude/ecosystem.md` is absent the project opted out — skip this
   step silently. If a listed tool is not installed, note it in one line
   and continue the audit; a missing tool never blocks it.
3. Report findings organized by severity (critical, warning, suggestion).
4. Do not make code changes. Do not create branches or commits.
5. Run the **Exit cleanup** so the tree ends clean. Audit makes no code
   changes, so the tree should already be clean — but the quality gate or
   a tool may have left incidental churn; reconcile it (or confirm
   `git status --porcelain` is empty) before ending.

---

## When things go wrong

**Blocked**: If any phase cannot proceed (missing dependency, unclear
requirement, broken environment), tell the user what's blocking you and
what information you need to continue. Then run the **Exit cleanup**:
commit any real partial work worth keeping (do **not** `git stash` it —
the stash is shared across worktrees, and there is no cross-session resume
to pick it back up) or discard disposable noise, so the tree ends clean
and the worktree can be reaped.

**Abandoning an approach**: If the current approach is wrong and pushing
on would make the codebase worse, stop rather than force it. Restore the
working tree to the Start clean baseline — discard only *your* session's
changes (`git restore` / `git clean -fd` on files you touched), never the
user's pre-existing edits. Then report what was attempted and why it was
abandoned, so the next attempt starts from that knowledge instead of
repeating it.

**Partial progress**: If only part of the work passes the quality gate,
commit the passing part as its own atomic commit and leave the failing
part out — discard it or note it, but never commit code that fails the
gate. In the final report, list exactly what was committed and what
remains, with enough detail that a fresh session can finish the job.

**Bug found**: If you discover an unrelated bug during development, note
it in the final report. Do not fix it inline unless it is trivial and
within the same scope.

**Task too large**: If the plan reveals the task exceeds one session's
budget, implement the highest-priority slice, commit it, and report
what remains. Do not attempt to complete everything in one session. Run
the **Exit cleanup** after committing the slice so the tree ends clean —
uncommitted remainder left in the worktree is stranded, not resumed.
