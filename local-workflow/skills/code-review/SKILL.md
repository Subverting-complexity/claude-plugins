---
name: code-review
description: >-
  Review code changes for correctness, security, architecture, and quality.
  Use when the user asks to review changes, check their code, audit a diff,
  look at what changed, or review before committing or pushing. Trigger on
  "review this", "review my changes", "check this code", "look at this diff",
  "audit these changes", "is this ready to commit", "review before I push",
  "code review", "review the last commit", or any request to evaluate code
  quality on a set of changes. Also trigger when the user shares a diff or
  branch and asks for feedback on correctness or quality. Do NOT use for
  architecture-level audits of an entire codebase (use code-architect audit
  mode instead). Do NOT use for writing or implementing code (use execute or
  structured-coding instead). Do NOT use for feature-level verification with
  containment and downstream analysis (use verify-feature instead). Do NOT
  use for React Native / Expo-specific audits (use mobile-audit instead).
allowed-tools:
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git status *)
  - Bash(git show *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
---

# Code Review

Review code changes for correctness, security, architecture, and quality.
Works on uncommitted changes, branch diffs, specific commits, or named files.
No platform integration required.

Read `CLAUDE.md` for project rules and coding standards if it exists.

---

## Determine Review Scope

Infer the scope from the user's request:

| User says | Review scope |
|-----------|-------------|
| "Review my changes" / no specific target | All uncommitted changes (staged + unstaged) |
| "Review this branch" / branch name | Diff from base branch to HEAD |
| "Review this file" / file paths | Those specific files in full |
| "Review the last commit" / a SHA | That specific commit |
| "Review everything since X" | Diff from X to HEAD |

If ambiguous, check `git status` and `git log --oneline -5` to understand
the current state and ask if needed.

---

## Step 1 — Gather the Change Set

Run the appropriate git commands for the scope:

**Uncommitted changes:**
- `git status` for the file list
- `git diff` for unstaged changes
- `git diff --cached` for staged changes

**Branch diff:**
- `git log main..HEAD --oneline` for the commit list
- `git diff main...HEAD --name-status` for the file list
- `git diff main...HEAD` for the full diff

**Specific commit:**
- `git show <sha> --stat` for the file list
- `git show <sha>` for the full diff

Identify every changed file and classify the type of change (added,
modified, deleted, renamed).

---

## Step 2 — Read the Code in Context

For every changed file:

1. Read the **full file**, not just the changed lines. Understand what it
   does, how it is structured, and where the changes sit within it.
2. Read the **files it imports from** and the **files that import it**.
   Follow the dependency chain at least two levels deep.
3. For every **function or method modified**, grep the codebase for all
   call sites. Read each call site in context to verify the change is
   safe for all consumers.

Find and read existing **test files** for the changed modules. Understand
what was already covered and what the changes add or modify.

---

## Step 3 — Evaluate

Work through each area using the full codebase context.

**Ecosystem tools (if configured).** If `.claude/ecosystem.md` exists, it
lists codebase-intelligence tools installed for this project — use them to
sharpen the relevant areas below and fold their output into the matching
finding:

- **Graphify** → `graphify . --update` then `graphify query`/`graphify path`
  to trace how the changed functions connect to the rest of the tree
  (feeds *Regressions* and *Architectural consistency*).
- **Fallow** (TS/JS) → run it to surface unused exports and duplication the
  diff introduces (feeds *Minimality* and dead-code findings).
- **ecc-agentshield** → when the diff touches Claude Code config (CLAUDE.md,
  `.claude/`, hooks, skills, MCP config), `npx ecc-agentshield scan` and
  fold any finding into *Security*.

Skip silently for any tool not listed or not relevant to this diff.

### Logic and correctness

Trace every logic path step by step through the actual code. For
calculations, substitute concrete values and verify the arithmetic. Check:

- Boundary conditions (zero, one, max, null, empty, negative)
- Concurrency (race conditions, double-reads, TOCTOU)
- Error paths (what happens when dependencies fail, return null, or throw)

### Type safety and nullability

Are nullable types handled correctly? Could a null slip through to a
dereference?

### Security

- No injection vulnerabilities (SQL, XSS, command, path traversal)
- Input validation at system boundaries
- No sensitive data in logs or error messages
- No secrets, credentials, or connection strings in code

### Architectural consistency

Does the change follow established codebase patterns, or introduce a new
one without justification? One responsibility per file. Dependencies
point in the right direction.

If `CLAUDE.md` or architecture docs define rules, check against them.

### Test quality and coverage

Is every new code path exercised? Are boundary conditions and error paths
tested? For bug fixes, is there a regression test? Are test assertions
specific (not just "doesn't throw")?

### Regressions

From the callers and consumers found in Step 2, are any broken or subtly
changed by this diff? Are unrelated code paths in the same files
untouched and still correct?

### Minimality

Is every changed line necessary for the stated purpose? Flag unrelated
refactors, formatting changes, or comment edits that are bundled in.

---

## Step 4 — Fix Issues (when appropriate)

If the review finds concrete, objective problems, fix them directly:

- Logic errors and off-by-one mistakes
- Missing null checks that would cause runtime failures
- Unrealistic test mocks that don't match real behavior
- Missing test coverage for new code paths
- Dead code introduced by the change
- Mismatched types or incorrect casts

Do **not** fix stylistic preferences or make discretionary refactors.
Only fix things that are objectively wrong.

If an issue is architectural or requires a design decision, flag it in
the findings rather than fixing it.

---

## Step 5 — Report Findings

Write findings in plain English, following `_shared/wording-standard.md`.
State **the problem and the suggested fix** in complete sentences that a
reader without the full context can follow. Avoid telegraphic fragments
and stacked clauses, define or avoid jargon, and keep `file:line`
references and identifiers precise in backticks.

Present findings organized by severity:

### Critical

Problems that would cause bugs, security vulnerabilities, or data loss.
Must be fixed before commit or merge.

### Warning

Issues that won't immediately break things but indicate risk: missing
tests for complex logic, architectural violations, fragile assumptions.

### Suggestion

Improvements that would make the code better but aren't blocking:
naming, organization, patterns.

For each finding:
- Name the file and line number
- Describe the issue concretely
- Explain why it matters (what breaks, what risk it creates)
- State whether it was fixed or needs attention

**If no issues are found**, say so clearly in one sentence. Do not pad
the output with praise or filler.

---

## When the User Asks "Is This Ready?"

Give a direct answer: yes, no, or conditionally. If no, list what needs
to change. Don't hedge with "it depends" when the code gives a clear
answer.
