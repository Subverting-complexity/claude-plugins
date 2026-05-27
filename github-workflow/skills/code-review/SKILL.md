---
name: code-review
description: Review open pull requests — find the first PR needing review, check out its branch, review the code in full codebase context, fix concrete issues, post a structured review comment, and apply state labels. Reviews one PR per invocation. Trigger when the user asks to review PRs, check PRs, run a PR review, do a code review, look at open PRs, or when invoked by a scheduled routine. Also trigger on "/code-review". If the user says "review", "check PRs", "any PRs to review", "run reviews", or anything about pull request quality, use this skill.
allowed-tools:
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Bash(gh *)
  - Bash(git *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
  - Bash(npm *)
  - Bash(dotnet *)
  - Bash(python *)
  - Bash(pip *)
  - Bash(cargo *)
  - Bash(go *)
  - Bash(make *)
---

# PR Review

Review one open pull request end-to-end: find it, claim it, read the code
in context, fix what can be fixed, post a structured comment, apply labels.
Exit when done. If no PRs need review or anything goes wrong, exit
immediately.

## Prerequisites

### GitHub CLI

Before doing anything else, verify `gh` is authenticated:

```bash
gh auth status
```

If this fails, stop and tell the user to run `gh auth login` first.

### Review Configuration

This skill requires a `review.config.md` file that defines repository
identity, label definitions, non-compliance gates, tech-stack review rules,
and the review comment footer.

**Finding the config:** Look in these locations, in order:

1. `./docs/review.config.md`
2. `./review.config.md`

If neither exists, stop the review workflow and run the **Config Generation**
flow (see below) to create one with the user. Do not proceed without a
config.

Read `review.config.md` fully before starting. Everything project-specific
lives there. This workflow is generic.

---

## Config Generation

When no `review.config.md` exists, walk the user through creating one.
Use interactive prompts to gather the information, then write the file.

### Step 1 — Detect what you can

Before asking anything, gather context automatically:

```bash
# Get the repo identity
gh repo view --json owner,name,defaultBranchRef

# Get existing labels
gh label list --json name,description

# Detect tech stack from file extensions and config files
find . -maxdepth 3 -type f \( -name "*.csproj" -o -name "package.json" -o -name "Cargo.toml" -o -name "go.mod" -o -name "requirements.txt" -o -name "Gemfile" -o -name "pom.xml" -o -name "build.gradle" -o -name "*.sln" -o -name "Makefile" -o -name "pyproject.toml" \) 2>/dev/null | head -20

# Check for test directories
find . -maxdepth 3 -type d \( -name "test" -o -name "tests" -o -name "__tests__" -o -name "spec" -o -name "test_*" \) 2>/dev/null | head -10
```

Use what you find to pre-fill answers and reduce the number of questions.

### Step 2 — Ask the user

Ask about the areas the auto-detection couldn't fully resolve. Group
questions by topic and use interactive selection where possible.

**Labels:** Present a default label scheme (see the template in
`references/review.config.template.md`) and ask if they want to customise
the prefix or add/remove any.

**Hard non-compliance gates:** Present sensible defaults (no linked issue,
no tests on non-trivial code, secrets in code, scope creep). Ask if they
want to add or remove any.

**Tech-stack review rules:** Based on the detected stack, suggest relevant
cross-boundary checks. For example:
- C# + TypeScript → DTO/interface parity
- Python + TypeScript → API schema validation
- Monorepo → cross-package dependency checks
- Any API project → request/response type safety

Ask what architecture rules matter to them (layer boundaries, single
responsibility, import direction).

**Security specifics:** Ask if there are project-specific security
concerns beyond the defaults (injection, input validation, no secrets in
logs).

**Test expectations:** Present defaults and ask if they want to adjust.

**Review comment footer:** Offer a default and let them customise.

### Step 3 — Create the labels

For each label defined in the config, check if it exists on the repo. If
not, create it:

```bash
gh label create "<label-name>" --description "<description>" --color "<hex>"
```

Use these default colours (adjustable by the user):
- Reviewing: `#0E8A16` (green)
- Approved: `#1D76DB` (blue)
- Changes requested: `#E4E669` (yellow)
- Needs discussion: `#D93F0B` (orange)
- Review failed: `#B60205` (red)
- Fixes applied: `#5319E7` (purple)

### Step 4 — Write the config

Write the completed `review.config.md` to `./docs/review.config.md`
(create the `docs/` directory if needed). Use the template structure from
`references/review.config.template.md` and fill in all the gathered values.

Show the user the final file and confirm before proceeding.

---

## Review Workflow

Once you have a valid `review.config.md`, proceed with the review.

### Step 1 — Find a PR that needs review

```bash
gh pr list --state open --repo <org>/<repo> --json number,title,labels,headRefName,baseRefName,headRefOid
```

Skip any PR that has:
- The `reviewing` state label (another run is in progress).
- The `approved` state label (already reviewed and approved, unless the
  label is manually removed).

For each remaining PR, determine whether it needs review:

1. Get Claude's most recent review comment:
   ```bash
   gh pr view <number> --repo <org>/<repo> --json comments
   ```
2. Filter comments for the review footer marker (defined in
   `review.config.md`).
3. If no such comment exists, it needs review.
4. If a comment exists, extract the `Reviewed at <SHA>` line. If that SHA
   differs from the current `headRefOid`, it needs review. Otherwise skip.

If no PRs need review, report that and exit. If multiple PRs need review,
pick the lowest-numbered one. Do not loop through multiple PRs.

### Step 2 — Claim the PR

Apply the `reviewing` state label immediately:

```bash
gh pr edit <number> --repo <org>/<repo> --add-label "<reviewing-label>"
```

If this fails, exit immediately.

### Step 3 — Check out the PR branch

```bash
gh pr checkout <number>
```

If checkout fails: remove the `reviewing` label, apply the `review-failed`
label, post a brief failure comment with the footer, and exit.

Record the current commit SHA:

```bash
git rev-parse HEAD
```

Save this SHA for the review footer.

### Step 4 — Gather context

Run all of the following. If any command fails, treat as a review failure
(see Error Handling below).

- **PR metadata:**
  ```bash
  gh pr view <number> --repo <org>/<repo> --json title,body,baseRefName,headRefName,files,additions,deletions
  ```

- **Linked issue:** Parse the PR body for `Closes #N` or `Fixes #N`, then:
  ```bash
  gh issue view <N> --repo <org>/<repo> --json title,body,labels,milestone
  ```
  The issue is the source of truth for what the PR should accomplish. If
  there is no linked issue and the config lists that as a hard gate, it is
  a non-compliance failure, but continue the review.

- **Changed files:**
  ```bash
  git diff <baseRef>...HEAD --name-status
  ```

- **Full diff** (for reference, but do not review from the diff alone):
  ```bash
  git diff <baseRef>...HEAD
  ```

### Step 5 — Read the code in context

For every changed file:

1. Read the **full file**, not just the changed lines. Understand what it
   does, how it is structured, and where the changes sit within it.
2. Read the **files it imports from** and the **files that import it**.
   Follow the dependency chain at least two levels deep.
3. For every **function or method modified**, grep the codebase for all
   call sites. Read each call site in context to verify the change is safe
   for all consumers.

Run any tech-stack-specific cross-boundary checks defined in
`review.config.md` (e.g., verifying DTO/interface parity, API schema
alignment).

Find and read existing **test files** for the changed modules. Understand
what was already covered and what the PR adds or modifies.

### Step 6 — Evaluate the PR

Work through each area below using the full codebase context.

#### Hard non-compliance gates

Check every gate listed in `review.config.md`. Any failure here forces a
`Changes Requested` verdict. Call out each failure explicitly in the review
comment under the "Non-compliance" section.

#### Story alignment

Does the PR implement everything the linked issue describes? Does it
implement anything not described? Are acceptance criteria met?

#### Logic and correctness

Trace every logic path step by step through the actual code. For
calculations, substitute concrete values and verify the arithmetic. Check:

- Boundary conditions (zero, one, max, null, empty, negative)
- Concurrency (race conditions, double-reads, TOCTOU)
- Error paths (what happens when dependencies fail, return null, or throw)

#### Type safety and nullability

Are nullable types handled correctly? Could a null slip through to a
dereference? Apply any tech-stack-specific type-safety rules from
`review.config.md`.

#### Security

- No injection vulnerabilities (SQL, XSS, command, path traversal)
- Input validation at system boundaries
- No sensitive data in logs
- Apply any project-specific security checks from `review.config.md`

#### Architectural consistency

Does the change follow the architecture rules in `review.config.md`? Does
it follow established codebase patterns or introduce a new one without
justification? One responsibility per file.

#### Test quality and coverage

Apply the test expectations from `review.config.md`. Is every new code
path exercised? Are boundary conditions and error paths tested? For bug
fixes, is there a regression test?

If changed code has no tests and is non-trivial, this is a hard
non-compliance failure (if configured as such in the config).

#### Regressions

From the callers and consumers found in Step 5, are any broken or subtly
changed? Are unrelated code paths in the same files untouched and correct?

#### Minimality

Is every changed line necessary for the PR's stated purpose? Flag
unrelated refactors, formatting changes, or comment edits.

### Step 7 — Fix issues

If concrete problems are found (unrealistic test mocks, missing null
checks, logic errors, missing test coverage, dead code, mismatched types),
fix them directly on the PR branch. Commit each fix with a clear message.
Push the fixes.

Do **not** fix stylistic preferences or make discretionary refactors. Only
fix things that are objectively wrong or would block merge.

If an issue is architectural or requires a design decision, do not fix it.
Flag it in the review comment as needing discussion.

After pushing fixes, update the recorded commit SHA to the new `HEAD`.

### Step 8 — Determine the verdict

- **Approved** — Zero hard non-compliance failures, zero remaining issues.
  PR is fully ready to merge.
- **Changes Requested** — Any hard non-compliance failure, or any remaining
  problem that needs human action.
- **Needs Discussion** — No hard failures, but architectural questions or
  ambiguities need human judgment before merge.

### Step 9 — Post the review

Post a single comment using `gh pr comment <number> --repo <org>/<repo>`:

```
## Review by Claude

**Verdict: [Approved | Changes Requested | Needs Discussion]**

[1-2 sentence summary of what the PR does and whether it does it correctly.]

### Non-compliance
[List any hard non-compliance failures with specifics. If none, say "None."]

### Story alignment
[Does the PR match the issue? Anything missing or out of scope?]

### Correctness
[Key findings from logic, security, nullability, and architecture review.
Reference specific file:line locations.]

### Tests
[Are tests sufficient? What is covered, what is missing?]

### Regressions
[Any risk to existing functionality?]

### Minimality
[Are all changes necessary? Any bundled unrelated work?]

### Fixes applied
[List of commits pushed, or "None" if no fixes were needed.]

### Issues remaining
[Numbered list of problems that could not be auto-fixed, with file paths
and line numbers. If none, say "No issues remaining."]

<footer from review.config.md>
```

The `Reviewed at <SHA>` line must contain the commit SHA from Step 3 (or
the updated SHA from Step 7 if fixes were pushed).

### Step 10 — Apply labels and exit

1. Remove the `reviewing` state label.
2. Remove all other state labels that don't match the new verdict (the
   remove commands will no-op if the label isn't present).
3. Apply exactly one state label matching the verdict.
4. If fixes were pushed in Step 7, ensure the `fixes-applied` action label
   is present. Do not remove it if it was already there (it is sticky).
5. Check out the original branch you were on before the review.
6. Report `Reviewed PR #<number> — <verdict>` and exit.

Use the label names from `review.config.md` for all label operations.

---

## Error Handling

If anything goes wrong (gh commands fail, branch checkout fails, a changed
file cannot be read, the PR has no diff, or the codebase is too large to
review thoroughly):

1. Remove the `reviewing` state label.
2. Apply the `review-failed` state label.
3. Post a comment explaining what failed, including the review footer so
   the failure is tied to a specific commit and future runs will retry.
4. Exit immediately. Do not attempt to recover, retry, or continue.

---

## Rules

- Never use `gh pr review --approve`. Always use `gh pr comment`.
- Do not merge or close any PR.
- Do not make discretionary refactors or stylistic changes.
- Only push fixes for objective problems that would block merge.
- Review one PR per invocation, then exit.
