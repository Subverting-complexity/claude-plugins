# Coding method

How `execute`, `bulk-execute` and `build` write code once a plan exists. It replaces the `structured-coding` and `debugging` skills, which restated general practice at length; only the rules a run actually needs are kept here.

## Before editing

- Read the code the change touches, what calls it and what it calls, and the tests that cover it. Know what it assumes about its inputs and which edge cases it already handles.
- Read the other parts of the system that handle the same data or concept, and the project documentation or wiki page that describes it, when there is one. Use Graphify to find them when `.claude/ecosystem.md` lists it.
- Search for an existing utility, pattern or dependency before adding one. The codebase's way of doing API calls, errors, state and structure is the way to do it here, unless that pattern is actively broken, in which case say so in the plan rather than quietly deviating.
- Match the codebase's standards by `skills/_shared/codebase-patterns.md`: for each new file or unit, find the closest existing example of the same kind, read it whole, and follow it.

## Writing

- Keep the change to what the plan names. Do not refactor unrelated code in the same change.
- Give each unit one job, in the layer where the codebase puts that kind of work. Reuse an existing function rather than write a second copy.
- Write the tests with the code, not after it. For a bug fix, write the test first and see it fail.
- Handle errors explicitly and validate input at system boundaries. For each call that can fail, decide what happens when it fails: no error swallowed, no work left half done.
- Name things the way the surrounding code does. A comment explains why, never what.
- When the project's formatter and linter can run on single files, run them on the files you changed. They are fast, and they settle the rules the repository enforces.

## When something fails

1. Reproduce it: run the exact failing command and keep its output.
2. Isolate the cause before changing anything. Follow the data from the entry point to the failure, check boundaries first, and state the cause in one sentence: file, line, what happens and why.
3. Fix the cause, not the symptom. A null check that hides a value that should never be null is not a fix.
4. Re-run the original failing command, then the related tests. A new test should fail without the fix and pass with it.

Stop and report rather than push on when the cause is in a dependency, only reproduces in an environment you cannot reach, or needs a change larger than the work in hand. Say what was found and what was ruled out.
