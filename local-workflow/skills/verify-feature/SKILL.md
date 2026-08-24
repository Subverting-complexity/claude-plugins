---
name: verify-feature
description: >-
  Verify that the feature on the current branch is contained, complete, and free
  of unexpected downstream side effects, producing a structured report with a fix
  plan per issue. Use to check a feature before merge, audit its blast radius, or
  confirm completeness. Uses a linked story/issue as the scope baseline when
  available, else the branch diff. Do NOT use for general code review without
  feature context (use code-review) or architecture-level codebase audits (use
  code-architect audit mode).
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git status *)
  - Bash(git show *)
  - Bash(git branch *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Feature Verification

Verify that the current branch's feature is contained, complete, correct,
and safe. Produce a structured report with a concrete fix plan for every
issue found.

Read `CLAUDE.md` for project rules and coding standards if it exists.

## Plain-English output

Everything you write for a person to read (the report, each issue, and the fix plan) follows `_shared/wording-standard.md` and avoids `_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

---

## Step 1 — Establish Feature Scope

The scope defines what this feature is supposed to do. Everything in the
verification is measured against it.

### When a user story or issue is provided

Read the story or issue. Extract:
- What the feature delivers (the "what")
- Acceptance criteria (the "done" definition)
- Boundaries (what's explicitly in and out of scope)

### When no story or issue is provided

Derive the scope from the code changes. First resolve the comparison base:
local `main` is often stale (especially in worktrees), so prefer the remote's
default branch when an `origin` remote exists, and fetch it so the ref is
current. This is a local verification skill that may run in a repo with no
`origin`, so fall back to local `main` when there is no remote.

```sh
default_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
default_branch=${default_branch:-main}
if git remote get-url origin >/dev/null 2>&1; then
  git fetch --quiet origin "$default_branch"
  base="origin/$default_branch"
else
  base="$default_branch"
fi

git log "$base"..HEAD --oneline
git diff "$base"...HEAD --stat
```

Read the commit messages and the changed files to infer:
- What capability is being added or changed
- Which modules are involved
- What the intended behavior appears to be

State the inferred scope to the user before proceeding:
> "Based on the branch, this feature appears to: [description]. Verifying
> against that scope. Correct me if I'm wrong."

---

## Step 2 — Map the Change Surface

Build a complete picture of what changed and what it touches.

1. **List all changed files** with change type (added, modified, deleted,
   renamed). Resolve the comparison base the same way as in Step 1 (prefer
   the remote default branch, fall back to local `main`) — do this here too,
   since the base may not have been resolved if a story was provided:
   ```sh
   default_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
   default_branch=${default_branch:-main}
   if git remote get-url origin >/dev/null 2>&1; then
     git fetch --quiet origin "$default_branch"
     base="origin/$default_branch"
   else
     base="$default_branch"
   fi

   git diff "$base"...HEAD --name-status
   ```

2. **For each changed file**, read the full file and identify:
   - New exports (functions, classes, types, components)
   - Changed signatures (parameters added/removed/retyped)
   - Changed behavior (logic, control flow, return values)
   - Removed exports

3. **Map the dependency graph outward**. For every changed export:
   - Grep the codebase for all import sites and call sites
   - Read each consuming file to understand how it uses the changed code
   - Note which consumers are inside the feature boundary and which are
     outside

This map is the foundation for the containment and downstream analysis.

---

## Step 3 — Containment Analysis

Determine whether the feature stays within its boundary or leaks.

### Scope leaks

- Are there changes to files that are unrelated to the feature? Flag each
  with the file path and what changed.
- Are shared utilities, base classes, or global config files modified?
  If so, do those changes affect only this feature's code path, or do
  they change behavior for other features too?
- Are new global side effects introduced (modifying shared state, global
  event listeners, singleton mutations, environment variables)?

### Unintended exports

- Does the feature export anything that isn't required by its scope?
  New public APIs, new types, new components that nothing outside the
  feature consumes yet.
- Are internal implementation details exposed that should be private?

### Bundled unrelated changes

- Are there formatting changes, refactors, or fixes to code outside the
  feature boundary? These should be in a separate branch.

---

## Step 4 — Implementation Quality

Evaluate whether the feature is well built.

### Completeness

- Does the implementation cover every acceptance criterion from the story
  or inferred scope? Walk through each one explicitly.
- Are there TODO comments, placeholder implementations, or commented-out
  code left in the changes?
- Are all new code paths reachable? Is there dead code in the diff?

### Pattern adherence

- Does the new code follow existing codebase patterns for similar
  concerns (error handling, data access, state management, API calls,
  component structure)?
- Are there new patterns introduced where an existing one would work?

### Edge cases

- Boundary conditions: zero, one, max, null, empty, negative values
- Error states: what happens when dependencies fail, return unexpected
  values, or timeout?
- Concurrency: race conditions, double-submits, stale data

### Test coverage

- Are new code paths tested?
- Do tests cover the acceptance criteria?
- Are edge cases and error paths tested, not just the happy path?
- Are tests specific (asserting exact expected behavior) rather than
  generic (just checking "no error")?

---

## Step 5 — Downstream Side Effect Analysis

Trace the impact of every change on code outside the feature boundary.

### Changed signatures

For every function, method, or component whose signature changed:
- Find all call sites in the codebase
- Verify each call site is compatible with the new signature
- Check for implicit callers (reflection, dynamic dispatch, framework
  conventions, serialization)

### Changed behavior

For every function whose behavior changed (different return value,
different side effects, different error handling):
- Find all consumers
- Verify each consumer still works correctly with the new behavior
- Pay attention to consumers that rely on specific error types, null
  returns, or ordering guarantees

### Changed data shapes

For any modified data model, DTO, config structure, or API contract:
- Find all code that reads or writes this data
- Verify serialization/deserialization still works
- Check for downstream consumers (other services, stored data, caches)
  that expect the old shape

### Removed code

For any deleted function, class, type, or export:
- Verify nothing still references it
- Check for dynamic references that grep might miss (string-based
  lookups, config files, reflection)

---

## Step 6 — Report

Present the findings as a review a colleague would write on the pull
request, not as an audit log.

### How to write a finding

Every finding is a short comment addressed to the person who wrote the
code. Keep it to a few sentences, in this shape:

1. **Say what the code does**, in one plain sentence, naming the exact
   method, field, or file involved and what it does. Describe the
   mechanics you can see, not a judgement about them.
2. **Say what follows from that**, in the next sentence. If you cannot
   confirm the consequence from the code, phrase it conditionally
   ("if there is anything downstream that ...") rather than asserting it.
3. **End with a question or a concrete list.** Where the right answer
   depends on intent you cannot read from the code, ask the author
   directly. Where the gap is plainly a gap, list the specific cases you
   think are missing.

Rules for the voice:

- Ask real questions and leave them open. "Is this intentional, or
  should it go through the full pipeline?" is a question. "This should
  go through the full pipeline" is an instruction, and you usually do
  not have enough context to give one.
- Keep the uncertainty that is actually there. "I think we would
  probably want tests for ..." is honest when you are proposing, not
  confirming. Do not upgrade it to "this must have tests".
- Name things exactly as they appear in the code, in backticks, and say
  what each one does the first time it appears. The reader may not know
  this codebase.
- Be specific about what is missing. A list of named cases is useful.
  "Test coverage is insufficient" is not.
- No severity language in the prose, no restating the finding at the end
  of it, and no closing line that adds nothing. Stop once the point and
  the question are clear.
- Follow `_shared/wording-standard.md` and avoid everything in
  `_shared/banned-patterns.md`.

**Example of a finding that raises a possible side effect:**

> The sync sets `StatusId` directly on the entity and calls
> `SaveChangesAsync` on the database context, so the change is written
> straight to storage. If anything downstream reacts to a support
> request being resolved (notifications, monitoring updates, any domain
> events), none of that fires through this path.
>
> Is this intentional, or should it go through the full pipeline?

**Example of a finding that reports a gap:**

> There are no tests covering `SyncSupportRequestsAsync`, which pulls
> open requests and updates them, or `MapDevOpsStateToStatus`, which
> translates the external state name into a local status value.
>
> I think we would probably want tests for:
>
> - No open requests, so the method exits early.
> - Completed work maps across correctly.
> - A `closed` state maps to `ManuallyResolved`.
> - An unknown state leaves the status unchanged.
> - A missing work item is skipped rather than throwing.
> - The decimal conversion from the external field value.

### Report structure

**Feature summary.** One paragraph: what the feature does, which parts
of the system it touches, and whether it looks clean or has issues worth
resolving before merge.

**Findings**, grouped under `Containment`, `Implementation Quality`, and
`Downstream Side Effects`. Write each one as described above, under a
heading that carries the location and how much it matters:

```
#### `src/sync/SupportRequestSync.cs:42` (Blocking)
```

Use `Blocking` for something that is wrong or will break a consumer,
`Worth resolving` for something that should probably change before
merge, and `Note` for an observation the author may reasonably decide to
leave. Severity belongs in the heading, not in the sentences.

Skip a group entirely when it has no findings. Do not write a heading
followed by "no issues found".

**Acceptance criteria.** For each criterion from the story, or from the
scope you inferred, say whether it is met, not met, or partly met, and
what is missing in the last two cases.

**What to do next.** For every Blocking and Worth-resolving finding, in
severity order and with fixes that unblock other fixes first:

1. The file and line, and what needs to change.
2. What breaks or degrades if it stays as it is.
3. Rough effort: trivial, small, or medium.

Where a finding ended in a question rather than a proposed fix, say that
the next step is an answer from the author, and repeat the question.

If nothing needs resolving, say so in one sentence and stop.
