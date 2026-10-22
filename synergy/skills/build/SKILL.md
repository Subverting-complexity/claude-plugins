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
- Are the acceptance criteria sufficient?

Judge the acceptance criteria by `skills/_shared/judging-acceptance-criteria.md`. Do not take them as complete because the story has them. Use the full set, given and derived, in the plan, the tests and the review. Tell the user which criteria you derived.

If the task is underspecified, or a criterion would be a guess, ask focused questions to fill the gaps. Use `/synergy:feature-discovery` if the task is complex enough to warrant a full interview.

## Phase 2 -- Plan

Use `/synergy:code-architect` to plan the implementation:

- Pass the task requirements and relevant codebase context.
- Code-architect should scan the existing codebase and plan changes based on the task description. Do not run an interactive design interview or call feature-discovery.
- Consume the architecture plan output and proceed to Build.
- Do not pause for confirmation.
- If requirements have gaps, make reasonable assumptions and note them in the plan. Only stop if the task is so underspecified that any implementation would be a guess.
- For each acceptance criterion, the plan names the test that will prove it. A criterion with no test is a gap in the plan.
- For each new file or unit, the plan names the closest existing example it will follow, found as `skills/_shared/codebase-patterns.md` says. Where the codebase has two patterns for the same concern, the plan says which one it follows.

If the plan reveals the task exceeds one session's budget, tell the user and propose splitting it. Implement the highest-priority slice.

**Ecosystem tools.** Before reading files blind to plan, check whether `.claude/ecosystem.md` exists. If it does, the project has opted into the codebase-intelligence tools it lists — use them here as the first move, not an afterthought:

- **Graphify** listed → run `graphify . --update` first (fast, 0 tokens from the committed cache), then prefer `graphify query "..."` / `graphify explain X` over blind file search for any "how does X connect to Y" structure question. It is a planning accelerant, not a mandate — reach for it when a graph view beats opening files, skip it when the answer is obvious.
- **Fallow** listed (TS/JS) → query it for existing exports and duplication so the plan reuses what is there rather than rebuilding it.

If `.claude/ecosystem.md` does **not** exist, the project opted out — skip this whole step silently, plan as normal, and never nag about it. If the file lists a tool but the command is not on `PATH`, note that in one line and carry on with normal planning — a missing tool never blocks the run.

## Phase 3 -- Build

**Start clean.** Before making any edits, run the **Start clean** check in `templates/worktree-hygiene-local.md`: `git status --porcelain`. If the tree is already dirty, record the baseline and tell the user — a local session may run in their own checkout, so pre-existing changes may be *their* work. Leave those untouched and treat only the files you change from here on as yours. This baseline is what lets the Exit cleanup tell your work apart from what was already there. Also record the commit you start from, `start_sha=$(git rev-parse HEAD)`: Phase 6 reviews `{start_sha}..HEAD`.

Implement the Phase 2 plan by `templates/coding-method.md`:

- Do not pause for user confirmation. The task description and architecture plan from Phase 2 serve as the approved specification.
- Write code and tests together. Do not defer tests to a later phase.
- Follow build principles from `CLAUDE.md` if it exists.

## Phase 4 -- Verify with the related tests

Do not run the full test suite or the full quality gate here. It runs once, in Phase 7. Run only the tests related to the change, so each run is fast:

- the tests the plan named for each acceptance criterion;
- the tests for the changed modules, and the tests that import them.

Run them with the test runner's own filter, such as a file or folder path for `pytest` or `jest`, `dotnet test --filter`, or `cargo test <name>`. If the project cannot run a subset, run the smallest unit it can, such as one test project or one package.

If a related test fails:

1. Read the failure, and decide which of these 3 it is:
   - **Caused by the change.** The failure is in, or reaches, code this run changed. Fix it.
   - **Already failing.** The failure is in code this run did not touch, and has nothing to do with the change. Do not fix it inside this task. Record it for the report.
   - **A local problem.** The test needs something this machine does not have: a service, a database, a credential, an environment variable, network access, a port or a tool version. Do not fix it and do not change the test. Record it for the report.
2. After a fix, re-run only the tests that failed, then the related tests. Repeat up to 3 times.
3. If a test caused by the change still fails after 3 attempts, work through **When something fails** in `templates/coding-method.md` before trying again.

If you cannot tell which of the 3 it is, record it as unclear. Do not run the full suite to find out.

The related tests count only if they still test the same thing. Before you commit, read `git diff {start_sha} --` on the test files. If a test was deleted, skipped or had its assertion loosened to make it pass, undo that and fix the code instead. A test may change only where the task changes the behaviour it checks; say so in the commit message. Then check that each acceptance criterion has the test the plan named.

## Phase 5 -- Commit

1. Stage only relevant files. Never stage `.env`, credentials, or generated files that should be gitignored.
2. Write a clear commit message: what was built and why.
3. If you need multiple logical commits, prefer atomic commits that each leave the codebase in a working state.

Do not push or create PRs. This is a local workflow. The user decides what happens next.

## Phase 6 -- Independent review

Read `references/independent-review.md` and follow it. One review agent reads the commits from this run in a fresh context, fixes the Blocking findings and Quick fixes, and commits the fixes on this branch. A second agent reviews those fixes only when they were substantial. Nothing is pushed or posted.

## Phase 7 -- Run the full suite once, at the end

Run the project's full quality gate once, after the review and its fixes are committed. If no quality gate command is configured, run the project's full test suite (e.g. `npm test`, `pytest`, `dotnet test`, `cargo test`). Do not run it earlier, and do not run it a second time.

Sort each failure as Phase 4 does. Fix a failure caused by the change, re-run only the tests that failed, and commit the fix. Do not fix the others: record each one for the report as already failing, a local problem, or unclear.

Then run the **Exit cleanup** below so the tree ends clean.

## Phase 8 -- Report

Write this to `skills/user-facing-communication/SKILL.md`. Open with what was built and the current state, and be exact about that state: this run ends at **commits on your branch**, reviewed and fixed. Nothing is pushed, no pull request exists, and nothing is merged unless you say otherwise. Say so plainly, because a report that only says "done" reads as shipped.

Then include only the parts that carry information:

- What was built, in plain language.
- The review verdict, what the reviewer fixed, and each finding still open.
- Each test that still fails, by name, with its class: already failing, a local problem with what the machine lacks, or unclear. If none fail, say the full suite passed.
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
