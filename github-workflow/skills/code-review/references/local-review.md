# Local review

Review a change that has no pull request: uncommitted work, a branch, a commit, named files, or "is this feature ready?". No GitHub access is needed. This replaces the separate local `code-review`, `verify-feature` and `mobile-audit` skills.

Read `CLAUDE.md` for project rules if it exists. When the change is React Native or Expo code, also work through `references/react-native.md` in Step 4.

## Step 1 — Scope

| The user says | Review |
|---------------|--------|
| "Review my changes", or no target | All uncommitted changes, staged and unstaged |
| "Review this branch", "verify this feature", "is this ready?" | The branch against its base |
| File paths | Those files in full |
| A commit or "the last commit" | That commit |
| "Everything since X" | X to `HEAD` |

For a branch, resolve the base from the remote so a stale local `main` does not widen the diff:

```sh
default_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
default_branch=${default_branch:-main}
if git remote get-url origin >/dev/null 2>&1; then
  git fetch --quiet origin "$default_branch"; base="origin/$default_branch"
else
  base="$default_branch"
fi
git log "$base"..HEAD --oneline
git diff "$base"...HEAD --name-status
```

**What the change is for.** When a story or issue is given, take its deliverable, acceptance criteria and stated boundaries as the baseline. Otherwise infer the purpose from the commits and files, and say it before going on: "This branch appears to add X. Reviewing against that; correct me if not."

## Step 2 — Read in context

For every changed file, read the whole file, the files it imports and the files that import it. For every changed function or export, find each call site and read it. Read the tests for the changed modules. Note which consumers sit inside the change and which sit outside it; that split drives Steps 3 and 4.

If `.claude/ecosystem.md` exists, use the tools it lists first: **Graphify** (`graphify . --update`, then `graphify query` or `graphify path`) to trace connections, **Fallow** for unused exports and duplication, and `npx ecc-agentshield scan` when the change touches Claude Code config. If the file is absent, review by hand and say nothing about tools. A listed tool missing from `PATH` gets one line and the review carries on.

## Step 3 — Correctness

- **Logic.** Trace each path through the code. Substitute concrete values into calculations. Check zero, one, max, null, empty and negative values, concurrency, and what happens when a dependency fails.
- **Types and nulls.** Could a null reach a dereference?
- **Security.** Injection (SQL, command, path, XSS), input validation at boundaries, secrets or personal data in code, logs or errors.
- **Tests.** Is every new path exercised, including errors and boundaries? Does a bug fix have a regression test? Are assertions exact rather than "does not throw"?
- **Acceptance criteria.** Walk each one. Look for TODOs, placeholders and unreachable code.

## Step 4 — Fit and blast radius

- **Containment.** Changes to files unrelated to the purpose, shared utilities or global config whose change reaches other features, new global side effects, exports nothing needs, and bundled formatting or refactors.
- **Duplication.** For each meaningful block of new logic, search for an existing equivalent by what it does (the endpoint, field, rule or error), not by its name, in shared utilities, base types and sibling features, and inside the diff itself. Near-duplicates count. Name the existing symbol, or say it is only a resemblance. Two similar blocks likely to diverge can stay apart.
- **Complexity.** Judged against this codebase: deep nesting, functions doing several things or switched by a boolean, indirection with one implementation, generalisation for needs that do not exist. Propose a shape only if it is genuinely simpler.
- **Patterns.** A new pattern where the codebase already has one for the same concern.
- **Downstream.** Changed signatures, behaviour or data shapes: check every consumer, including implicit ones (reflection, serialisation, config, stored data). Deleted code: check nothing still references it, dynamically included.
- **Regressions.** Read removed lines as a diff. Look for tests deleted, skipped or loosened; guards, validation, retries or catches dropped from paths others still use; changed defaults, flags, timeouts or limits; conditions that send existing callers down a new branch; work added inside loops or hot paths.

## Step 5 — Fix or report

Fix concrete, objective problems directly unless the user asked only for a report: logic and off-by-one errors, missing null checks that would crash, missing tests for new paths, dead code the change introduced, wrong types. Do not fix matters of taste. Flag anything that needs a design decision.

## Step 6 — Report

Follow `skills/user-facing-communication/SKILL.md` for the shape (verdict and current state first), `_shared/wording-standard.md` for the wording, and `_shared/banned-patterns.md`.

Report only what would change the outcome if acted on. Write each finding as a comment a colleague would leave on the change:

1. What the code does, naming the exact method, field or file, in one plain sentence.
2. What follows from that. If the code cannot confirm it, say it conditionally.
3. A real question where the answer depends on intent, or a concrete list of what is missing.

Keep genuine uncertainty. Do not paste code back. Put severity in the heading, not the prose:

```
#### `src/sync/SupportRequestSync.cs:42` (Blocking)
```

`Blocking` is wrong or breaks a consumer; `Worth resolving` should probably change first; `Note` is the author's call. Say whether each was fixed.

Then, only where they carry information:

- **Acceptance criteria:** met, not met or partly met for each, and what is missing.
- **What to do next:** for each Blocking and Worth-resolving finding, in the order that unblocks the others: what to change, what breaks if it stays, and rough effort (trivial, small, medium).

When asked "is this ready?", answer yes, no or conditionally first. If nothing needs resolving, say so in one sentence and stop.
