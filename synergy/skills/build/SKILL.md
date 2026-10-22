---
name: build
description: 'Build a task or story locally, no issue or PR: plan, code, quality gate, commit, then a fresh agent reviews and commits fixes. Trigger on "build this" or "implement this" outside GitHub story work.'
depends-on:
  - code-architect
  - feature-discovery
arguments:
  - name: mode
    description: 'Execution mode: build (default), audit (codebase audit, no code changes)'
---

# Build Task

End-to-end local task execution workflow. Takes a task description or a story, plans the implementation, builds it, runs tests, and commits. Then a review agent in a fresh context reviews the commits, fixes what is wrong, and commits the fixes on the same branch.

Everything here happens on your machine. There is no issue to claim, no status to set, no pull request to open, and nothing to merge — the run finishes at commits on your branch. Story work that should end in a reviewed and merged pull request is `/synergy:execute` instead, which is a different command doing a different job.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

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

# Ecosystem tools onboarding nudge (informational — never blocks). A local run
# has no workflow preflight, so this is its equivalent. Speak up only inside a real project
# (a git repo) that has neither opted in (.claude/ecosystem.md) nor out
# (.claude/ecosystem-declined). Declining once writes the marker, silencing it.
if [ -e .git ] && [ ! -f .claude/ecosystem.md ] && [ ! -f .claude/ecosystem-declined ]; then
  echo "ECOSYSTEM_TIP: companion tools (Graphify/RTK/etc.) not set up — optional"
fi
```

If the block above printed an `ECOSYSTEM_TIP` line, follow `references/ecosystem-tip.md`; it is informational and never blocks the run. If it printed none, say nothing about ecosystem tools.

## Session budget

Each session should stay under ~100k tokens. This means one task per session, scoped to what can be completed within that budget.

**Practical guidelines:**

- **Commit early and often.** Make atomic commits as you complete each logical unit of work. If the session ends unexpectedly, committed work is recoverable.
- **Scope to one session.** If Phase 2 (Plan) reveals the task is too large for a single session, implement the highest-priority slice, commit it, and note the remaining work for a follow-up session.
- **Wrap up, don't run out.** If you sense you are deep into a session, get to a committable state. A partial implementation with clear notes about what remains is better than an abandoned session with no artifact.
- **One task, one session.** Do not start a second task after finishing the first. End the session so the next one starts fresh.

## Mode selection

Default mode is `build`. Override with `$ARGUMENTS.mode`:

- **build** -- Take a task and implement it
- **audit** -- Audit the codebase, report findings, no code changes

If mode is `audit`, follow `references/audit-mode.md` instead of the phases below, then run the **Exit cleanup**.

---

## Phase 1 -- Understand

Read the task description or story provided by the user: pasted text, a file, or a story from another tracker. If the user hasn't provided one, ask for it. Do not set a status or post anything to the tracker it came from.

Check if the task has enough guidance to proceed:

- What needs to be built or changed?
- What does "done" look like?
- Are there acceptance criteria?

If the task is underspecified, ask focused questions to fill the gaps. Use `/synergy:feature-discovery` if the task is complex enough to warrant a full interview.

## Phase 2 -- Plan

Use `/synergy:code-architect` to plan the implementation:

- Pass the task requirements and relevant codebase context.
- Code-architect should scan the existing codebase and plan changes based on the task description. Do not run an interactive design interview or call feature-discovery.
- Consume the architecture plan output and proceed to Build.
- Do not pause for confirmation.
- If requirements have gaps, make reasonable assumptions and note them in the plan. Only stop if the task is so underspecified that any implementation would be a guess.
- For each acceptance criterion, the plan names the test that will prove it. A criterion with no test is a gap in the plan.

If the plan reveals the task exceeds one session's budget, tell the user and propose splitting it. Implement the highest-priority slice.

**Ecosystem tools.** Before reading files blind to plan, check whether `.claude/ecosystem.md` exists. If it does, the project has opted into the codebase-intelligence tools it lists — use them here as the first move, not an afterthought:

- **Graphify** listed → run `graphify . --update` first (fast, 0 tokens from the committed cache), then prefer `graphify query "..."` / `graphify explain X` over blind file search for any "how does X connect to Y" structure question. It is a planning accelerant, not a mandate — reach for it when a graph view beats opening files, skip it when the answer is obvious.
- **Fallow** listed (TS/JS) → query it for existing exports and duplication so the plan reuses what is there rather than rebuilding it.

If `.claude/ecosystem.md` does **not** exist, the project opted out — skip this whole step silently, plan as normal, and never nag about it. If the file lists a tool but the command is not on `PATH`, note that in one line and carry on with normal planning — a missing tool never blocks the run.

## Phase 3 -- Build

**Start clean.** Before making any edits, run the **Start clean** check in `templates/worktree-hygiene-local.md`: `git status --porcelain`. If the tree is already dirty, record the baseline and tell the user — a local session may run in their own checkout, so pre-existing changes may be *their* work. Leave those untouched and treat only the files you change from here on as yours. This baseline is what lets the Exit cleanup tell your work apart from what was already there. Also record the commit you start from, `start_sha=$(git rev-parse HEAD)`: Phase 6 reviews `{start_sha}..HEAD`.

**Run the quality gate once before any edit**, the same command Phase 4 uses, and record which checks fail. A check that fails before this run is not caused by it: do not fix it inside this task, and name it in the report. From here on, the gate passes when no check fails that passed at this baseline. Without this baseline, Phase 4 cannot tell a failure the change caused from one that was already there.

Implement the Phase 2 plan by `templates/coding-method.md`:

- Do not pause for user confirmation. The task description and architecture plan from Phase 2 serve as the approved specification.
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
3. If still failing after 3 attempts, work through **When something fails** in `templates/coding-method.md` before trying again.

If no quality gate command is configured, run whatever test commands the project supports (e.g. `npm test`, `pytest`, `dotnet test`, `cargo test`).

A green gate counts only if the tests still test the same thing. Before you commit, read `git diff {start_sha} --` on the test files. If a test was deleted, skipped or had its assertion loosened to make the gate pass, undo that and fix the code instead. A test may change only where the task changes the behaviour it checks; say so in the commit message. Then check that each acceptance criterion has the test the plan named.

## Phase 5 -- Commit

1. Stage only relevant files. Never stage `.env`, credentials, or generated files that should be gitignored.
2. Write a clear commit message: what was built and why.
3. If you need multiple logical commits, prefer atomic commits that each leave the codebase in a working state.

Do not push or create PRs. This is a local workflow. The user decides what happens next.

## Phase 6 -- Independent review

Read `references/independent-review.md` and follow it. One review agent reads the commits from this run in a fresh context, fixes the Blocking findings and Quick fixes, and commits the fixes on this branch. A second agent reviews those fixes only when they were substantial. Nothing is pushed or posted.

After the review, run the **Exit cleanup** below so the tree ends clean.

## Phase 7 -- Report

Write this to `skills/user-facing-communication/SKILL.md`. Open with what was built and the current state, and be exact about that state: this run ends at **commits on your branch**, reviewed and fixed. Nothing is pushed, no pull request exists, and nothing is merged unless you say otherwise. Say so plainly, because a report that only says "done" reads as shipped.

Then include only the parts that carry information:

- What was built, in plain language.
- The review verdict, what the reviewer fixed, and each finding still open.
- Anything outstanding: work left undone, a known limitation, or something the user has to do next.
- Any meaningful assumption you had to make, or anything you could not verify.

Name the files you changed only when the user needs them. Leave out the test names, the commands you ran, and the problems you hit and then fixed.

## Exit cleanup -- reconcile the working tree to clean

Run this as the **final** step on **every** exit path — success, blocked, task-too-large, audit, or error — and always **after** any commit. It is idempotent; run it without reasoning about which earlier phase may have left the tree dirty.

A worktree is auto-removed by the harness **only when it is clean** (`docs/worktree-config.md`). A leftover uncommitted change — even a stray formatter reflow — pins the worktree open forever and strands the work (there is no cross-session resume). Run the **End clean** procedure in `templates/worktree-hygiene-local.md`: `git status --porcelain` must end empty (or show only the pre-existing baseline you recorded at Start clean, which is the user's and must be left untouched).

Because Start clean recorded what was already dirty, anything dirty here that is **not** in that baseline was produced by this session — so:

- **Commit** a forgotten task file into the work.
- **Commit incidental formatting** on files outside the task as a **separate `chore:` commit** — do not fold it into the task's diff.
- **Discard** this run's noise by path: `git restore -- <path>` if tracked, else `git clean -fd -- <path>`.

**Never `git stash`** — the stash is shared across every worktree on the clone, and stashing would also bury the user's pre-existing changes. Leaving the tree dirty (beyond the recorded baseline) is never an option.

---

## When things go wrong

If a phase is blocked or fails, the approach has to be abandoned, only part of the work passes the gate, an unrelated bug turns up, or the task proves too large, follow `references/when-things-go-wrong.md`.
