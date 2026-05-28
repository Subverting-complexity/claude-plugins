---
name: execute
description: 'End-to-end local task execution: plan, build, verify, commit. No issue tracker or PR integration.'
when_to_use: >-
  Trigger when the user wants development work done locally. Any of these:
  "build this", "implement this", "start working", "execute", "develop this",
  "implement the story", "build the feature", "fix this", "work on this",
  "make this change", "code this up". Also trigger when the user provides
  a user story, feature description, or task description and wants it built.
  This is the primary orchestrator for local development — prefer this over
  calling structured-coding or code-architect directly when the user wants
  end-to-end task completion. Do NOT use for reviewing existing code changes
  (use code-review instead). Do NOT use for planning or scoping features
  without building them (use feature-discovery or grill-me instead). Do NOT
  use for verifying a completed feature before merge (use verify-feature
  instead).
arguments:
  - name: mode
    description: 'Execution mode: build (default), audit (codebase audit, no code changes)'
---

# Execute Task

End-to-end local task execution workflow. Takes a task description, plans the
implementation, builds it, runs tests, and commits.

Read `CLAUDE.md` for project rules and build principles if it exists.

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
`/local-workflow:grill-me` if the task is complex enough to warrant a full
interview.

## Phase 2 -- Plan

Use `/local-workflow:code-architect` to design the implementation:

- Pass the task requirements and relevant codebase context.
- Consume the architecture plan output.
- If the plan reveals unclear requirements or significant complexity,
  use `/local-workflow:grill-me` to stress-test the plan before building.

If the plan reveals the task exceeds one session's budget, tell the user
and propose splitting it. Implement the highest-priority slice.

## Phase 3 -- Build

Use `/local-workflow:structured-coding` to implement:

- Pass the architecture plan from Phase 2 and the task requirements.
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

## Phase 6 -- Report

Summarize what was done:
- What was built
- Which files were changed
- What tests were added or modified
- Any remaining work or known limitations

---

## Audit mode

When `$ARGUMENTS.mode` is `audit`:

1. Read `CLAUDE.md` for project rules if it exists.
2. Review the codebase for issues: bugs, security vulnerabilities,
   architecture problems, code quality concerns.
3. Report findings organized by severity (critical, warning, suggestion).
4. Do not make code changes. Do not create branches or commits.

---

## When things go wrong

**Blocked**: If any phase cannot proceed (missing dependency, unclear
requirement, broken environment), tell the user what's blocking you and
what information you need to continue.

**Bug found**: If you discover an unrelated bug during development, note
it in the final report. Do not fix it inline unless it is trivial and
within the same scope.

**Task too large**: If the plan reveals the task exceeds one session's
budget, implement the highest-priority slice, commit it, and report
what remains. Do not attempt to complete everything in one session.
