---
name: verify-feature
description: >-
  Verify that the feature on the current branch is contained, complete, and free
  of duplication, needless complexity, regressions, and unexpected downstream
  side effects, reporting each issue with a fix plan. Use to check a feature
  before merge or audit its blast radius. Uses a linked story/issue as the scope
  baseline when available, else the branch diff. Do NOT use for general code
  review without feature context (use code-review) or architecture-level codebase
  audits (use code-architect audit mode).
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

## Output standard

Everything a person reads — plans, questions, findings, summaries, and
anything posted or committed — follows `skills/_shared/wording-standard.md`
for how it reads, `skills/user-facing-communication/SKILL.md` for what it
contains and in what order (outcome and current state first, then anything
outstanding, blocked or assumed, every work item named as well as numbered,
no investigation history), and `skills/_shared/banned-patterns.md` for what
must never appear. Every reply, not only the last one.

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

### Duplication

Code that repeats something the codebase already has is the most common
avoidable problem on a feature branch, and it stays invisible unless you
go looking. For each meaningful block of new logic, look for an existing
equivalent before accepting it.

- **Search by what the code does, not by what it is called.** Grep for
  the operation itself — the endpoint it calls, the field it maps, the
  rule it validates, the error it formats. An existing helper rarely
  shares the new code's name.
- **Check the likely homes first**: shared utility modules, the base
  class or interface the new type sits under, and any sibling feature
  that already solves the same problem.
- **Look inside the diff as well.** The same block pasted into two or
  three new files is duplication that arrived with this branch.
- **Near-duplicates count.** Logic that differs only in a literal, a type
  parameter, or one extra branch is still duplication.

Where an existing equivalent exists, name it — file and symbol — and say
what the new code would have to change to use it. Where you only see a
resemblance, say that instead of asserting a duplicate.

Not every repetition is worth removing. Two similar blocks that serve
different callers and are likely to diverge are often better left apart;
say so rather than proposing an abstraction over them.

### Complexity

Judge the new code against how the rest of this codebase is written, not
against an ideal. Flag it when it is harder to follow than the problem
requires:

- Nesting more than about three levels deep, or a function long enough
  that its parts have to be held in the reader's head at once.
- A function doing several unrelated things, or taking a boolean flag
  that selects between two behaviours.
- Indirection with a single implementation — an interface, factory,
  wrapper, or configuration switch that has one caller and no second
  case in prospect.
- Generalisation for requirements that do not exist yet.
- Expressions that need a comment to be readable, where a plain version
  would not.
- State for one concern spread across several places when one would do.

For each, say what makes it hard to follow and what the simpler shape
would be. The proposed replacement has to be genuinely simpler than what
it replaces — do not trade nesting for a layer of abstraction that costs
the reader more.

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

## Step 5 — Downstream Side Effects and Regressions

Trace the impact of every change on code outside the feature boundary,
and on behaviour that already worked before this branch.

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

### Regressions in existing behaviour

A regression is behaviour that worked before this branch and does not
work, or works differently, after it. Read the changed hunks as a diff
rather than reading the final file — a removed line leaves no trace in
the new version. For every hunk that touches a pre-existing code path,
ask what depended on the line that changed, and check:

- **Tests deleted, skipped, or weakened.** An assertion loosened from an
  exact value to "not null", a case removed rather than updated, a test
  marked skipped. Say which behaviour is no longer covered.
- **Behaviour quietly dropped.** A validation check, guard clause, null
  check, retry, or catch block removed from a path that other callers
  still use.
- **Defaults and configuration changed.** A default value, feature flag,
  timeout, or limit that now differs for existing users as well as for
  the new feature.
- **Existing callers taking a new branch.** A condition widened or
  narrowed so that code which used to take one path now takes another.
- **Work added to an existing path.** A call, query, or await placed
  inside a loop or a hot path that previously did without it.

Where you cannot tell from the code whether the old behaviour was
deliberate, say what was removed and ask the author.

### Removed code

For any deleted function, class, type, or export:
- Verify nothing still references it
- Check for dynamic references that grep might miss (string-based
  lookups, config files, reflection)

---

## Step 6 — Report

Present the findings as a review a colleague would write on the pull
request, not as an audit log.

### What is worth writing up

Only report what would change the outcome if the author acted on it: a
real bug, a data-loss or data-integrity risk, a missing failure path, an
inconsistency that will confuse the next reader, or a gap against the
acceptance criteria. Leave out matters of taste, anything already
covered by another finding, and anything too minor to justify
interrupting someone with. When in doubt, ask whether a reviewer would
actually leave this comment on the pull request — if not, drop it.

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
- Do not paste the code back. The author can already see their own
  diff; the comment is the whole value-add.
- Follow `_shared/wording-standard.md` and avoid everything in
  `_shared/banned-patterns.md`.

Before presenting the report, run the findings through the
`/{{PLUGIN_NAME}}:tone` skill so they read in the user's own voice
rather than generated review-bot phrasing. Do this even for a single
finding.

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

**Findings**, grouped under `Containment`, `Implementation Quality`
(which carries duplication and complexity), and `Downstream Side Effects
and Regressions`. Write each one as described above, under a
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
