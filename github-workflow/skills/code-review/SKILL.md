---
name: code-review
description: Review open pull requests — find the first PR needing review, check out its branch, review the code in full codebase context, fix concrete issues, post a structured review comment, and apply state labels. Reviews one PR per invocation. Trigger when the user asks to review PRs, check PRs, run a PR review, do a code review, look at open PRs, or when invoked by a scheduled routine. Also trigger on "/code-review". If the user says "review", "check PRs", "any PRs to review", "run reviews", or anything about pull request quality, use this skill. Pass --read-only to evaluate without making fixes (used by the Reviewer agent).
arguments:
  - name: mode
    description: 'Review mode: full (default) — evaluate and fix; read-only — evaluate only, no edits or pushes'
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

If neither exists and the session is interactive (user is present),
run the **Config Generation** flow (see below) to create one.

If the session is autonomous (called from `/github-workflow:execute`
or a scheduled routine), skip the config generation — resolve the
review-state labels through the single path in
`templates/default-labels.md` (review-state purposes default to the
`review-` prefix). Proceed with a minimal review (no custom gates, no
tech-stack rules, standard footer). The label inventory should already
exist (created at setup); if a label is missing, create it with the
guarded create-if-missing pattern from `templates/default-labels.md`
(no `--force`). Note in the review comment that no `review.config.md`
was found and defaults were used. In interactive sessions, also warn
the user: "No `review.config.md` found — using default labels. Run
`/github-workflow:setup` to configure review labels for this project."

**Resolving label names.** Every label this skill applies or filters on
(`reviewing`, `approved`, `changes-requested`, …) is a **purpose key**.
Resolve each to its concrete name through `templates/default-labels.md`
before use — never apply a bare name literally and never assume a
prefix. This guarantees the claim label this skill writes is the
identical string other skills filter on.

Read `review.config.md` fully before starting. Everything project-specific
lives there. This workflow is generic.

---

## Config Generation

When no `review.config.md` exists and the session is interactive,
follow the guide in `references/review-config-guide.md` to walk the
user through creating one.

---

## Read-Only Mode

When `$ARGUMENTS.mode` is `read-only`:

- Execute Steps 1–6 normally (find, claim, checkout, gather, read, evaluate).
- **Skip Step 7** (Fix issues) entirely — do not edit any files or push commits.
- In Step 8, determine the verdict based on raw findings (nothing was auto-fixed).
- In Step 9, post the review comment with "Fixes applied: None (read-only mode)."
- In Step 10, apply labels normally.

Read-only mode is intended for the Reviewer agent, which has no write
access. It produces the same structured evaluation without modifying
the PR branch.

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

Multiple agents may be running code-review concurrently — possibly under
the same GitHub identity, where a shared `reviewing` label cannot exclude
a rival (it reads present for both). Acquire the PR with the atomic claim
procedure in `templates/claim-procedure.md` (**Acquire**), using the
target `pr-<number>`. It pushes a unique object to `refs/claims/pr-<number>`
— a genuine server-side compare-and-swap — and applies the `reviewing`
state label as the human-visible marker on success.

If Acquire reports the claim is lost, another agent owns this PR: exit
without removing any labels and without making changes. The `reviewing`
label remains a display signal that other skills filter on; the
`refs/claims/pr-<number>` ref is the actual lock. No label read-back is
needed — the atomic push already proved exclusivity.

### Step 3 — Check out the PR branch

```bash
gh pr checkout <number>
```

If checkout fails: release the claim (`templates/claim-procedure.md`
**Release** for target `pr-<number>`: `git push origin :refs/claims/pr-<number>`),
remove the `reviewing` label, apply the `review-failed` label, post a
brief failure comment with the footer, and exit.

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
Check whether the trivial changes address every item in the previous
review's Issues Remaining list. If they do — all flagged issues are
resolved by the diff — post an abbreviated approval:

```
## Re-review by Claude

**Verdict: Approved**

All previously flagged issues have been addressed with trivial fixes.

<footer from review.config.md>
```

Remove the `needs-re-review` and `changes-requested` labels, apply
`approved`, and exit. Do not proceed to Step 5.

If the trivial changes do NOT address all Issues Remaining, proceed to
Step 5 for a full re-review — the original issues are still unresolved.

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

### Step 7 — Fix issues (critical-first, budget-aware)

Fix concrete, objectively wrong problems directly on the PR branch. Work
in priority order so that if the session runs out of budget, the most
important fixes have already landed.

#### 7a — Triage findings into tiers

Sort every finding from Step 6 into two tiers:

- **Critical** — must be fixed before the PR is mergeable:
  - Hard non-compliance gate failures
  - Security problems (injection, missing input validation, secrets in
    logs)
  - Logic and correctness errors, missing null checks, broken or
    incorrect tests
  - Missing test coverage on non-trivial new code paths
  - Regressions to existing callers or consumers
- **Trivial** — correct to fix, but non-blocking:
  - Missing trailing newlines, formatting inconsistencies
  - Dead code removal, utility method placement, misplaced code
  - Null-forgiving operators, unnecessary casts
  - Comment or naming cleanups where the fix is obvious

#### 7b — Fix the critical tier

Fix every critical finding. Commit each fix (or a small logical group)
with a clear message. These are non-negotiable — do not skip them for
budget reasons. If a critical issue genuinely cannot be auto-fixed
(needs human or design judgment), leave it for the verdict in Step 8
rather than guessing.

#### 7c — Assess remaining budget

Before starting the trivial tier, check whether there is room to
continue. Treat the budget as spent if **any** of these is true:

- The session has been running a long time or context is approaching its
  limit.
- Many files have already been read and edited this session.

If the budget is spent, **skip to Step 7e** and record the unfixed
trivial findings so Step 9 can list them under "Issues remaining" as
non-blocking cleanups for a follow-up.

#### 7d — Fix the trivial tier

If budget remains, fix the trivial findings too. Commit them.

#### 7e — Push

Push all fixes:

```bash
git push
```

Do **not** fix:
- Stylistic preferences where multiple valid approaches exist
- Architectural decisions that require human judgment
- Issues where the "right fix" depends on product or design context

Flag anything you cannot fix — and any trivial items deferred for budget
in Step 7c — in the review comment. Deferred trivial items are
non-blocking and do not by themselves force a "Changes Requested"
verdict.

After pushing fixes, update the recorded commit SHA to the new `HEAD`.

### Step 8 — Determine the verdict

Re-evaluate the PR state **after** Step 7 fixes. Issues that were
auto-fixed do not count as remaining issues.

- **Approved** — Zero hard non-compliance failures and zero remaining
  *critical* issues. All critical problems were either absent or
  auto-fixed. Trivial cleanups that were deferred for budget (Step 7c)
  do **not** block approval — list them as non-blocking notes. PR is
  ready to merge.
- **Changes Requested** — Any hard non-compliance failure, or any remaining
  *critical* problem that could not be auto-fixed and needs human action.
- **Needs Discussion** — No hard failures, but architectural questions or
  ambiguities need human judgment before merge.

If every critical issue found in Step 6 was resolved in Step 7, the
verdict is **Approved** — not "Changes Requested with observations" —
even if some trivial cleanups were deferred for budget. The fixes are
already pushed; nothing blocking is left for the builder to do.

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

1. Remove the `reviewing` state label, then release the atomic claim now
   that the verdict is being recorded (`templates/claim-procedure.md`
   **Release** for target `pr-<number>`): `git push origin :refs/claims/pr-<number>`
   and `rm -f .claude/claim-pr-<number>.sha`. Best-effort — ignore an
   error if the ref is already gone.
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

Resolve every label name by purpose key through the single path in
`templates/default-labels.md` (review-state purposes via
`review.config.md` when present, defaults otherwise). Do not hardcode a
concrete name.

### Step 10b — Verify labels were applied

After applying labels in Step 10, immediately read back the PR labels:

```bash
gh pr view <number> --repo <org>/<repo> --json labels --jq '[.labels[].name]'
```

Confirm the expected state label is present. If missing, the label
likely doesn't exist on the repo (setup should have created it). Create
it with the guarded create-if-missing pattern from
`templates/default-labels.md` — **without `--force`** so existing label
metadata is never overwritten — then retry:

```bash
gh label create "<label>" --repo <org>/<repo> --description "<desc>" --color "<color>"
gh pr edit <number> --repo <org>/<repo> --add-label "<label>"
```

If still missing after retry, report the failure but do not block.

---

## Error Handling

If anything goes wrong (gh commands fail, branch checkout fails, a changed
file cannot be read, the PR has no diff, or the codebase is too large to
review thoroughly):

1. Release the atomic claim (`templates/claim-procedure.md` **Release**
   for target `pr-<number>`): `git push origin :refs/claims/pr-<number>`
   and `rm -f .claude/claim-pr-<number>.sha`. Best-effort.
2. Remove the `reviewing` state label.
3. Apply the `review-failed` state label.
4. Post a comment explaining what failed, including the review footer so
   the failure is tied to a specific commit and future runs will retry.
5. Exit immediately. Do not attempt to recover, retry, or continue.

---

## Reference Material

For label definitions, state transitions, concurrency rules, and
feedback workflow details, see `references/review-workflow.md`.

---

## Rules

- Never use `gh pr review --approve`. Always use `gh pr comment`.
- Do not merge or close any PR.
- Do not make discretionary refactors or stylistic changes.
- Push fixes for all concrete, objectively wrong problems (blocking and minor).
- Review one PR per invocation, then exit.
