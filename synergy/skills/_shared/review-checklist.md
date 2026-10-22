# Review checklist

The single checklist for reading a change and finding what is wrong with it. `verify-feature` uses it to write a report, and the local review that `build` runs uses it to find what to fix, so both judge a change the same way. Each caller decides what to do with a finding; this file only says how to find one.

## 1 — Read the change in its system

Read the code as it is on the change under review. When that ref is not checked out, read each file with `git show {ref}:{path}`, never from the working tree, which holds a different version.

- **The change.** Read each changed file whole, and the whole function or class around each changed line, not only the hunk.
- **Its inputs and outputs.** Read the code that builds the values a changed function receives, and the code that uses what it returns or writes.
- **Its connections.** Read the files it imports and the files that import it. For every changed or removed export, find and read each call site, including implicit ones: reflection, serialisation, config and stored data. Note which consumers sit inside the change and which sit outside it.
- **The related parts of the system.** Find the other code that handles the same data or concept: what else writes the same table, calls the same API, handles the same event or validates the same field. A change that is correct alone can still disagree with them.
- **The tests** for the changed modules.
- **The baseline for style and structure.** Read the standards the repository enforces and states, and the closest existing example of each new or heavily changed file or unit, as `_shared/codebase-patterns.md` says.
- **The project's documentation, as needed.** When the change touches a concept, a rule or an integration that the repository documents, read that page: `docs/`, architecture decision records, or a wiki page that `CLAUDE.md` or the README links to. Do not read documentation the change does not touch.

If `.claude/ecosystem.md` exists, use the tools it lists first: **Graphify** (`graphify . --update`, then `graphify query`, `graphify path` or `graphify explain`) to find the connections and the related parts of the system, **Fallow** for unused exports and duplication, and `npx ecc-agentshield scan` when the change touches Claude Code config. If the file is absent, work by hand and say nothing about tools. A listed tool missing from `PATH` gets one line, and the review carries on.

When the change is large, skip lockfiles, generated files, vendored code and snapshots, and read the code that carries the purpose first.

## 2 — Look for problems

- **Containment.** Changes unrelated to the purpose; edits to shared utilities, base types or global config that reach other features; new global side effects; unneeded exports; bundled formatting or refactors.
- **Completeness.** Each acceptance criterion, given and derived; TODOs, placeholders, commented-out code, unreachable paths.
- **Correctness.** Trace each path through the code with concrete values, and substitute them into calculations. Could a null reach a dereference? Injection (SQL, command, path, XSS), validation at boundaries, and secrets or personal data in code, logs or errors.
- **Robustness.** For each call that can fail (I/O, a network call, a parse, another service), what does the code do when it fails? Look for errors swallowed or logged and ignored, work left half done, a retry that repeats a side effect, and an assumption about order, timing or input that the caller does not guarantee. Judge the code's design for failure, not a list of every possible input.
- **Modularity.** Does each unit have one job and one reason to change? Look for logic in the wrong layer (a controller or screen doing domain work, domain code doing I/O), dependencies pointing the wrong way, new cycles, one module reaching into another's internals, and units that cannot be tested without their neighbours.
- **Extensibility.** Would the next case of the same kind (another type, provider, field or rule) mean editing existing code in several places? Look for type or string switches repeated across files, hard-coded lists and constants, and behaviour fixed in code where the codebase already uses config, a registry or an interface. Report it only where a second case already exists or the codebase already has the pattern. Never ask for an abstraction against a need that has not appeared.
- **Duplication.** For each meaningful block of new logic, search for an existing equivalent by what it does (the endpoint, field, rule or error), not by its name, in shared utilities, base types, sibling features, the related parts of the system and the diff itself. Near-duplicates count. Name the existing symbol, or say it is only a resemblance. Two similar blocks likely to diverge can stay apart.
- **Patterns and conventions.** Judge by `_shared/codebase-patterns.md`. Compare each new file or unit with its closest existing example: location, structure, naming, dependencies, configuration, validation, error handling, logging and test layout. Look for a new pattern where the codebase already has one for the same concern, and for the older of two patterns where the codebase is moving to the newer one. Each finding names what it departs from: the stated or enforced rule, or the existing example ("`OrdersController` validates with the shared `Validator`; this one validates by hand"). A finding that can name neither is a matter of taste, so drop it. A deviation from a rule the repository states or enforces counts; a lone departure from the neighbours, or a whitespace-only one, is minor.
- **Complexity.** Judged against this codebase: deep nesting, a function doing several things or switched by a boolean, indirection with one implementation, generalisation for needs that do not exist. Propose a shape only if it is simpler.
- **Downstream and regressions.** Read removed lines as a diff. Changed signatures, behaviour or data shapes against every consumer; deleted code still referenced, dynamically included; tests deleted, skipped or loosened; guards, validation, retries or catches dropped from paths others still use; changed defaults, flags, timeouts or limits; conditions that send existing callers down a new branch; work added inside loops or hot paths.
- **Tests.** Every new path exercised, errors and boundaries included, with exact assertions rather than "does not throw". A bug fix has a regression test.

## 3 — Check each finding again

Before you report or fix anything, try to prove each finding wrong:

1. Go back to the code at the location, and read the code around it again.
2. Look for what would make the finding false: a caller that already validates the value, a framework or type that guarantees it, a guard further up, a test that covers the case, or a documented reason.
3. If the finding is false, drop it. If you cannot confirm it from the code, keep it only as a question, and say what you could not confirm.

Then ask once: which related part of the system that this change could affect have you not read yet? Read it, and check the new findings it gives the same way.
