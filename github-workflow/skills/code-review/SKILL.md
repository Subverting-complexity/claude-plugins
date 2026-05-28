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
  - Bash(npx *)
  - Bash(pnpm *)
  - Bash(yarn *)
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
the prefix or add/remove any. Also list existing repo labels
(`gh label list`) so the user can see what's already there.

**Custom labels:** Ask if the user has additional labels they want the
review process to apply or check. For each custom label, ask the name
and the criteria for when it should be applied. Examples:
- `breaking-change` — PR modifies a public API
- `docs-needed` — PR adds a feature with no documentation update
- `frontend` / `backend` — PR touches files in specific directories

Store these in the Custom Labels section of the config.

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
- Updating: `#0E8A16` (green)
- Approved: `#1D76DB` (blue)
- Changes requested: `#E4E669` (yellow)
- Needs re-review: `#FBCA04` (gold)
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
- The `reviewing` state label (another review agent is in progress).
- The `updating` state label (a builder agent is addressing feedback).
- The `approved` state label **unless** it also has `needs-re-review`
  (approved PRs that received new commits still need re-review).

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

**Prioritisation:** PRs with the `needs-re-review` state label are
reviewed first. Among those, pick the lowest-numbered one. If none have
that label, pick the lowest-numbered PR that needs review.

If no PRs need review, report that and exit. Do not loop through multiple
PRs.

**Never ask the user which PR to review.** Always auto-select using the
prioritisation rules above. If the user says "review PRs" or "review
pull requests" (plural), that means "find the next one and review it",
not "review all of them" or "let me choose".

### Step 2 — Claim the PR

Multiple agents may be running code-review concurrently. The
`reviewing` label acts as a distributed lock. Apply it, then verify
you own the claim.

1. Apply the `reviewing` state label:

   ```bash
   gh pr edit <number> --repo <org>/<repo> --add-label "<reviewing-label>"
   ```

   If this fails, exit immediately.

2. Wait 2 seconds, then re-read the PR labels to confirm:

   ```bash
   gh pr view <number> --repo <org>/<repo> --json labels
   ```

   If the `reviewing` label is present, you own the claim — proceed.
   If another state label has appeared (e.g., another agent removed
   `reviewing` and applied its own verdict in the meantime), another
   agent won the race. Exit without removing any labels.

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

### Step 4b — Assess re-review significance (re-reviews only)

This step applies only when reviewing a PR that was previously reviewed
(a prior review comment with a footer exists). Skip this step for
first-time reviews.

Extract the SHA from the previous review footer. Compute the diff between
that SHA and the current HEAD:

```bash
git diff <previous-review-SHA>..HEAD --stat
git diff <previous-review-SHA>..HEAD
```

Classify the changes since the last review as **trivial** or
**substantial**:

**Trivial** — all of the following are true:
- Only whitespace, formatting, or import-ordering changes
- Comment or documentation text fixes (typos, wording)
- Renaming that doesn't change behaviour (variable names, file renames
  with no logic change)
- Removing dead code that was flagged in the previous review

**Substantial** — any of the following:
- New or modified logic, control flow, or calculations
- New files, new dependencies, or changed APIs
- Test additions or changes to test assertions
- Security-relevant changes (auth, input validation, data handling)
- Anything that alters the observable behaviour of the code

**If trivial and previous verdict was `approved`:**
Skip the full re-review. Post an abbreviated comment:

```
## Re-review by Claude

**Verdict: Approved**

Changes since last review are trivial (formatting / typos / cleanup).
Original approval stands.

<footer from review.config.md>
```

Remove the `needs-re-review` label, ensure the `approved` label is
present, and exit. Do not proceed to Step 5.

**If trivial and previous verdict was `changes-requested`:**
Proceed to Step 5 for a full re-review — the original issues may still
be unresolved.

**If substantial:**
Proceed to Step 5 for a full re-review regardless of previous verdict.

---

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
2. Remove the `needs-re-review` state label (no-op if not present).
3. Remove all other state labels that don't match the new verdict (the
   remove commands will no-op if the label isn't present).
4. Apply exactly one state label matching the verdict.
5. If fixes were pushed in Step 7, ensure the `fixes-applied` action label
   is present. Do not remove it if it was already there (it is sticky).
6. If `review.config.md` defines custom labels, evaluate each one's
   "When to apply" criteria against the PR. Apply matching labels and
   remove non-matching ones that were previously applied by a review.
7. Check out the original branch you were on before the review.
8. Report `Reviewed PR #<number> — <verdict>` and exit.

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

## Addressing Review Feedback

After a review concludes with a `Changes Requested` verdict, the PR
needs updates before it can be re-reviewed. This can happen in two ways:

### Automatic (during this review run)

Step 7 already fixes objective issues and pushes them. If Step 7
resolved **all** issues — meaning the Issues Remaining list is empty
after fixes — re-evaluate the verdict before posting. The PR may now
qualify for `Approved`.

### Manual (separate invocation)

When issues remain that the reviewer could not auto-fix, the PR is
left with the `changes-requested` label. To address that feedback:

- A human or **builder** agent runs `/github-workflow:update-pr` to
  read the review comment, fix each item in Issues Remaining, push
  changes, and apply `needs-re-review`. (The reviewer agent is
  read-only and cannot run this command — it requires file editing
  and git push access.)
- The next code-review run will pick up PRs with `needs-re-review`
  (they are prioritised in Step 1) and perform a re-review.

### Change significance on update

When changes are pushed to a reviewed PR (by `update-pr` or any other
process), the pusher classifies the changes:

**Trivial (no re-review needed):**
- Whitespace, formatting, or import-order fixes
- Typo corrections in comments or documentation
- Removing dead code flagged in the review
- Variable renames with no behaviour change

Leave the existing state label in place.

**Substantial (re-review required):**
- New or modified logic, control flow, or calculations
- New files, dependencies, or changed APIs
- Test additions or modified assertions
- Security-relevant changes
- Anything that alters observable behaviour

Remove the current state label and apply `needs-re-review`:

```bash
gh pr edit <number> --remove-label "<current-state-label>" --add-label "<needs-re-review-label>"
```

The code-review skill's Step 4b will then assess whether the re-review
can be fast-tracked (trivial changes on an approved PR) or requires a
full pass.

---

## Label Reference for Agents

Any agent encountering these labels on a PR should understand what they
mean and what action (if any) to take. Labels use the prefix defined in
`review.config.md`.

### State labels (mutually exclusive — exactly one per PR)

| Label | Meaning | Agent action |
| ----- | ------- | ------------ |
| `{PREFIX}-reviewing` | A review agent is actively reviewing this PR. | **Do not touch.** Wait for the review to complete. Do not start a review, update, or push to this PR. |
| `{PREFIX}-updating` | A builder agent is addressing review feedback. | **Do not touch.** Wait for the update to complete. Do not start a review or competing update. |
| `{PREFIX}-approved` | Review passed, no remaining issues. | Ready for human merge. No agent action needed unless new commits are pushed (see `needs-re-review`). |
| `{PREFIX}-changes-requested` | Review found issues requiring human or builder action. | **Builder**: Run `/github-workflow:update-pr` to address the feedback. **Reviewer**: Skip, waiting on builder. |
| `{PREFIX}-needs-re-review` | New commits pushed since last review. | **Reviewer**: Prioritise this PR for re-review. **Builder**: No action — wait for review. |
| `{PREFIX}-needs-discussion` | Architectural or scope questions need human judgment. | **All agents**: Do not auto-fix. Flag to human. |
| `{PREFIX}-review-failed` | Review could not complete (checkout failed, PR too large). | **Reviewer**: May retry on next run if root cause is resolved. **Builder**: Investigate the failure. |

### Action labels (sticky, not mutually exclusive)

| Label | Meaning | Agent action |
| ----- | ------- | ------------ |
| `{PREFIX}-fixes-applied` | Claude pushed fix commits to this PR branch. | Informational. Do not remove — it persists across review cycles. |

### Concurrency rules

- **Before reviewing**: Check for `reviewing` and `updating` labels.
  If either is present, skip the PR entirely.
- **Before updating**: Check for `reviewing` and `updating` labels.
  If either is present, skip the PR entirely.
- **Claiming**: Apply your claim label (`reviewing` or `updating`),
  wait 2 seconds, re-read labels to confirm you still own the claim.
- **On exit or error**: Always remove your claim label so other agents
  can proceed.

---

## Rules

- Never use `gh pr review --approve`. Always use `gh pr comment`.
- Do not merge or close any PR.
- Do not make discretionary refactors or stylistic changes.
- Only push fixes for objective problems that would block merge.
- Review one PR per invocation, then exit.
