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

Present findings in a structured report.

### Feature Summary

One paragraph: what the feature does, which modules it touches, and the
overall verdict (clean / issues found).

### Containment

| Finding | Severity | File | Detail |
|---------|----------|------|--------|
| ... | Critical/Warning/Info | path:line | ... |

### Implementation Quality

| Finding | Severity | File | Detail |
|---------|----------|------|--------|
| ... | Critical/Warning/Info | path:line | ... |

### Downstream Side Effects

| Finding | Severity | Affected Consumer | Detail |
|---------|----------|-------------------|--------|
| ... | Critical/Warning/Info | path:line | ... |

### Acceptance Criteria Check

For each criterion from the story (or inferred scope):
- [ ] Criterion — Met / Not met / Partially met (detail)

### Fix Plan

For every Critical and Warning finding, provide:

1. **What to fix**: the specific file, line, and issue
2. **How to fix it**: the concrete change needed
3. **Why**: what breaks or degrades if left unfixed
4. **Effort**: estimated complexity (trivial / small / medium)

Order the fix plan by severity, then by dependency (fixes that unblock
other fixes come first).

If no issues are found, say so clearly in one sentence.

---

## Step 7 — Flag for the PR / Feature Creator

Produce a second, shorter deliverable alongside the report: the findings
worth putting directly in front of the person who wrote the code, in the
form they'd actually receive as a PR comment.

### What qualifies

Pull only from Critical and Warning findings, and only where a specific
person acting on it would change the outcome — a real bug, a data-loss
or data-integrity risk, a missing error/failure path, an inconsistency
that will confuse the next reader, or a completeness gap against the
acceptance criteria. Leave out anything that's a matter of taste,
already covered elsewhere, or too minor to justify interrupting someone
with it. When in doubt, ask whether a reviewer would actually leave this
comment on the PR — if not, it doesn't belong here.

If nothing clears that bar, say so in one sentence and skip the rest of
this step.

### Format

One entry per finding, in this exact shape:

```
<File name>
<full file path>
<line number>
<comment addressed directly to the PR creator>
```

Do not include the code snippet itself — the PR creator can already see
their own diff. The comment is the whole value-add.

### Voice

Write each comment the way a colleague leaves it directly on the line in
a PR review: state what's wrong or what's missing, then explain the
concrete consequence if it's left as is. Address the PR creator directly
and specifically — name the exact behavior, not a vague category of
problem.

- Lead with the issue in one direct sentence, not a hedge or a question
  framed as a suggestion.
- Explain the consequence: what breaks, what silently degrades, or what
  a user or the next developer will hit.
- If there's an existing pattern elsewhere in the same file or feature
  that already handles this correctly, point to it by name so the fix
  is obvious.
- End with a direct question only when you genuinely want the PR
  creator to make a call (e.g. "Should this have an else branch that
  notifies the user?") — don't manufacture a question when the fix is
  already clear.
- Keep it to two or three sentences. This is a review comment, not the
  fix plan entry.

For example, in the same voice as a real review comment (genericized,
not tied to any specific codebase):

> Inconsistent null handling here. A few lines up this same check goes
> through the `.HasValue` / `.Value` pair, but this comparison uses the
> nullable value directly. Both work today because of the guard above
> it, but if that guard ever moves, this line evaluates true when the
> value is actually null.

> No early return when the two values already match. As written, this
> still persists the record and stamps a new modified date/user even
> though nothing changed. Worth adding a guard at the top so an
> unrelated write doesn't get logged as a real change.

> Should this have an else branch here? Right now, if the save fails,
> the UI just goes quiet. The user has no way to tell whether it worked.

Before presenting this section, invoke the `/{{PLUGIN_NAME}}:tone` skill
on the drafted comments so they read in the user's own voice rather than
generated review-bot phrasing. Do this for every comment, even a single
one — don't skip it because the batch is small.
