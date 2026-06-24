---
name: debugging
description: "Systematic debugging methodology: reproduce, hypothesize, isolate, fix, verify. Use when a test is failing, something is broken, an error is occurring, or the user says 'debug this' or 'why is this failing'. Also trigger on stack traces, error messages, or 'it works locally but not in CI'. Do NOT use for code review (use code-review), general implementation (use execute), or architecture audits (use code-architect --mode audit)."
---

# Debugging

Systematic approach to finding and fixing bugs. Every step builds on the
previous one — do not skip ahead to a fix without isolating the cause.

## Plain-English output

Everything you write for a person to read (your findings, the diagnosis, and the summary of the fix) follows `_shared/wording-standard.md` and avoids `_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

## Phase 1 — Reproduce

Confirm the failure before investigating.

1. **Get the exact error.** Read the error message, stack trace, test
   output, or user-reported behavior. If the user described the problem
   verbally, reproduce it yourself first.
2. **Find the minimal reproduction.** Run the failing test, hit the
   failing endpoint, or trigger the failing path. If the failure is
   intermittent, note the conditions under which it occurs.
3. **Record the baseline.** Save the exact command, input, and output
   so you can compare after the fix.

If you cannot reproduce the failure, say so and investigate the
environment differences (config, data, dependencies, platform) before
proceeding.

## Phase 2 — Hypothesize

Form 2-3 concrete theories about the root cause.

1. **Read the error carefully.** The error message, line number, and
   stack trace usually point to the neighborhood of the bug, not
   necessarily the bug itself.
2. **Trace the data flow.** Follow the inputs from the entry point
   through the call chain to where the error occurs. What value is
   wrong, null, or missing?
3. **List hypotheses.** Each hypothesis should be a specific, testable
   claim:
   - "The `userId` parameter is null because the middleware doesn't
     set it on this route"
   - "The query returns 0 rows because the migration hasn't run in
     this environment"
   - "The test fails because it depends on insertion order but the
     query has no ORDER BY"

Do not investigate all hypotheses at once. Rank by likelihood and
test the most probable first.

## Phase 3 — Isolate

Narrow down to the exact line or condition that causes the failure.

1. **Binary search the call chain.** If the failure is deep in a call
   stack, check the intermediate values halfway through. Is the data
   correct at that point? If yes, the bug is downstream. If no,
   upstream.
2. **Check the boundaries.** Off-by-one errors, null values at
   boundaries, empty collections, and type mismatches are the most
   common root causes.
3. **Read the surrounding code.** The bug may not be on the failing
   line — it may be in the setup, the caller, or a shared utility.
4. **Confirm isolation.** Before fixing, state the root cause in one
   sentence: "The bug is in {file}:{line} — {what happens} because
   {why}."

## Phase 4 — Fix

Make the minimal change that addresses the root cause.

1. **Fix the cause, not the symptom.** If a null check would mask the
   bug, fix why the value is null instead.
2. **One logical change.** Do not refactor, clean up, or improve
   surrounding code as part of the fix. Unrelated changes make the
   fix harder to verify and review.
3. **Match existing patterns.** Use the same error handling, validation,
   and coding style as the surrounding code.

## Phase 5 — Verify

Confirm the fix works and nothing else broke.

1. **Re-run the original reproduction.** The exact same command or test
   that failed in Phase 1 should now pass.
2. **Run related tests.** Check tests in the same module, tests that
   exercise the same code path, and integration tests if available.
3. **Check edge cases.** If the bug was a boundary condition, test
   adjacent boundaries (empty input, max input, concurrent access).
4. **Run the full quality gate** if the project has one.

If the fix introduces a new test, the test should fail without the fix
and pass with it. If no test existed for this code path, write one.

## When to escalate

- The bug is in a dependency or framework — not your code.
- The reproduction is environment-specific and you can't replicate the
  environment.
- The fix requires architectural changes beyond the scope of a bug fix.
- You've been investigating for more than 30 minutes without isolating
  the cause.

In these cases, report what you've found and what you've ruled out.
Partial progress is valuable — the next person picks up from your
findings, not from scratch.
