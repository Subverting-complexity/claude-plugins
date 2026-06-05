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

**Auto-merge.** `review.config.md` may define an **Auto-Merge on Approval**
setting (purpose: squash-merge a PR once the review verdict is Approved).
It is **opt-in and defaults to `disabled`** — treat it as disabled whenever
the section, or the whole file, is absent (including the autonomous minimal
review). The same section may set **`require-ci-before-merge`** (default
`false`); when `true`, Step 11 refuses to merge a PR that has no green CI
gate (no checks at all, or a red check) instead of landing it. Step 11
reads both settings and is the only place this skill merges.

---

## Config Generation

When no `review.config.md` exists and the session is interactive,
follow the guide in `references/review-config-guide.md` to walk the
user through creating one.

---

## Read-Only Mode

When `$ARGUMENTS.mode` is `read-only`:

- Execute Steps 1–6 normally (find, claim, checkout, gather, read, evaluate).
- In **Step 2b** (duplicate reconciliation), close nothing: identify the
  winner and list the duplicate set under a "Duplicate PRs" note in the
  review comment, recommending which to keep. Then continue reviewing the
  claimed PR.
- **Skip Step 7** (Fix issues) entirely — do not edit any files or push commits.
- In Step 8, determine the verdict based on raw findings (nothing was auto-fixed).
- In Step 9, post the review comment with "Fixes applied: None (read-only mode)."
- In Step 10, apply labels normally.
- **Skip Step 11** (auto-merge) entirely — read-only mode never merges,
  closes, or pushes, regardless of the Auto-Merge on Approval setting.

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
3. If no such comment exists, it needs review. A PR carrying the
   `needs-review` entry-state label (applied at PR creation) is the
   normal first-review case.
4. If a comment exists, extract the `Reviewed at <SHA>` line. If that SHA
   differs from the current `headRefOid`, it needs review. Otherwise skip.

**Prioritisation:** PRs with the `needs-re-review` state label are
reviewed first. Among those, pick the lowest-numbered one. If none have
that label, pick the lowest-numbered PR that needs review (a
`needs-review` PR or one whose SHA changed).

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

### Step 2b — Reconcile duplicate PRs for the same issue

Before spending a full review on the claimed PR, check whether **another
open PR resolves the same issue**. Duplicates should be rare — the atomic
issue claim (`refs/claims/issue-N`) stops two agents selecting one story —
but they can still arise at the boundaries the claim does not cover:
starting a story by explicit number after a PR already exists, a
`block-story` that returned an already-PR'd issue to the pool, a
hand-reaped claim ref, or a genuine create-time race where two sessions
each opened a PR on a different branch. When two open PRs close one issue,
exactly one must survive.

1. Determine the claimed PR's linked issue(s). Use GitHub's own closing
   parse, not the PR body: the claimed PR's `closingIssuesReferences`
   (returned by the lookup in `templates/sibling-pr-lookup.md`) is the
   authoritative set `{issues}`. If the PR closes no issue, skip this step.
2. For each `#N` in `{issues}`, find every open PR that will close it by
   running the lookup in `templates/sibling-pr-lookup.md` with that `N`.
   That returns the **duplicate set** `S` (oldest-first), each node already
   carrying `number`, `title`, `headRefName`, `isDraft`, and `labels` — the
   claimed PR will be in it.
3. If `S` contains only the claimed PR, there are no duplicates — skip the
   rest of this step and continue to Step 3.

**When `S` has more than one PR, pick the winner and close the rest.**

4. Determine the **winner** `W` by these criteria, in order — stop at the
   first that clearly separates them:
   a. **Mergeable & gate-green beats broken.** A PR with the `approved`
      review-state label, or whose required CI checks pass, beats one
      carrying `changes-requested` / `failed` or with failing checks.
   b. **Acceptance-criteria coverage.** The PR that satisfies more of the
      linked issue's acceptance criteria wins — but only when the gap is
      objective (one PR omits an entire criterion the other implements).
      Do not adjudicate on subjective polish.
   c. **Test coverage.** A PR that exercises its new code paths beats one
      that does not.
   d. **Tie-break — lowest PR number.** If the above do not clearly
      separate them, keep the **lowest-numbered** PR (opened first). This
      is deterministic, so two agents evaluating the same set
      independently reach the same winner and never close each other's
      keeper.

   To compare objectively, read each PR's diff against its base
   (`git fetch origin <headRefName>`, then
   `git diff origin/<baseRef>...origin/<headRefName>`) and the linked
   issue body.

5. Close every loser `L` in `S \ {W}` — but only one you can safely take:
   a. Acquire `refs/claims/pr-L` (`templates/claim-procedure.md`
      **Acquire**, target `pr-L`) — skip this for the PR you already hold.
      If Acquire fails, another agent is reviewing or updating `L` right
      now: **skip it this round** and note it. That agent runs this same
      reconciliation, finds the same winner, and closes its own PR.
   b. Close it with an explaining comment that links the winner:
      ```bash
      gh pr close L --repo <org>/<repo> \
        --comment "Closing as a duplicate of #W, which resolves the same issue (#N) and is the better-implemented of the two (<one-line reason>). Work here is preserved on branch \`<headRefName>\` if anything needs salvaging into #W."
      ```
      Do not delete the branch — leave it so the work is recoverable.
   c. Release the claim you took on `L` (`templates/claim-procedure.md`
      **Release**, target `pr-L`). Do **not** touch the linked issue's
      assignee or lifecycle label — the surviving PR `W` still drives it.
6. Resolve where the PR you hold sits:
   - **You hold the winner `W`:** continue to Step 3 and review it.
   - **You hold a loser:** you just closed it in 5b. Remove its
     `reviewing` label, release your claim
     (`templates/claim-procedure.md` **Release**), and **exit** — never
     review a closed PR. The winner keeps its current review-state label
     and is reviewed on this or a later run.

Closing a duplicate PR is the **only** circumstance in which this skill
closes a PR (see Rules). In **read-only mode**, close nothing: identify
the winner, list the duplicate set under a "Duplicate PRs" note in the
review comment (Step 9) recommending which to keep, and continue the
normal review of the claimed PR.

### Step 3 — Check out the PR branch

```bash
gh pr checkout <number>
```

If checkout fails: release the claim (`templates/claim-procedure.md`
**Release** for target `pr-<number>`: `git push origin :refs/claims/pr-<number>`),
remove the `reviewing` label, apply the `failed` review-state label
(purpose key `failed`, default name `review-failed`), post a brief
failure comment with the footer, and exit.

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
present, then run **Step 11** (auto-merge on approval, if enabled) and
exit. Do not proceed to Step 5.

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
`approved`, then run **Step 11** (auto-merge on approval, if enabled) and
exit. Do not proceed to Step 5.

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

Write the comment in plain English, following `_shared/wording-standard.md`.
The author reading this review may not have the context you built up, so
each finding should state **the problem and the suggested fix** in
complete sentences a reader can follow without the diff in front of them.
Avoid telegraphic fragments and stacked clauses; define or avoid jargon;
keep `file:line` references and identifiers precise in backticks. The
section headings below give structure — the text under them is prose, not
a stripped list of identifiers.

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
   and `rm -f .claude/claim-pr-<number>.sha`. Idempotent — ignore an
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
8. Report `Reviewed PR #<number> <title> — <verdict>` (always name the
   PR by number **and** title together, never the number alone) and exit.

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

If the verdict is **Approved**, proceed to Step 11 before exiting.
Otherwise the review is complete — exit here.

### Step 11 — Auto-merge on approval (if enabled)

Run this step **only** when all of the following hold. If any is false,
skip it and exit normally:

- The verdict is **Approved** — including the abbreviated re-review
  approvals in Step 4b, which route here before exiting.
- `review.config.md`'s **Auto-Merge on Approval** setting is `enabled`.
  If there is no `review.config.md`, or the section is absent, the
  setting is `disabled` — **never merge**.
- The session is **not** in read-only mode.

Also read **`require-ci-before-merge`** from the same Auto-Merge on
Approval section. Absent ⇒ `false`. When `true`, the skill must see a
**green CI gate** before it merges: a PR with no checks at all, or with a
failing check it cannot fix, is **paused**, not merged (the exact branches
are in step 3 below). When `false`, behaviour is unchanged.

This is opt-in and **off by default**. Merging a PR is otherwise
forbidden (see Rules); this is the one sanctioned merge, and only under
an explicit `enabled` setting. The review comment from Step 9 must
already be posted before you merge — never merge before the verdict is
on the PR.

When all conditions hold, drive the PR to a merged state. Conflicts and
red CI are **blockers to clear, not reasons to give up** — fix them on the
branch (the same auto-fix discipline as Step 7: fix concrete, objectively
correct problems; never guess at changes that need product or design
judgment), then merge. You are already on the PR branch from Step 3.

1. **Confirm the PR is still what you reviewed.** Re-read its state:
   ```bash
   gh pr view <number> --repo <org>/<repo> --json state,mergeable,headRefOid
   ```
   - `state` not `OPEN` (already merged or closed) → nothing to do;
     report and exit.
   - `headRefOid` differs from the SHA you reviewed (recorded in Step 3,
     or the updated SHA from Step 7, and written to the footer) → commits
     you did not review landed mid-run. Do **not** merge: ensure
     `needs-re-review` is applied and exit so the next run re-reviews the
     new head. (Commits **you** push in steps 2–3 below are excluded —
     update your recorded SHA as you push them.)

2. **Resolve merge conflicts if there are any.** When `mergeable` is
   `CONFLICTING`, bring the base branch in and resolve, rather than
   bailing:
   ```bash
   git fetch origin <baseRef>
   git merge origin/<baseRef>
   ```
   For each conflicted file, read **both** sides in full context (not just
   the hunk) and resolve so the PR's intent **and** the incoming base
   change are both preserved. Then re-run the project quality gate locally
   to prove the resolution compiles and the tests pass. Commit the
   resolution and push:
   ```bash
   git add -A && git commit -m "Resolve merge conflicts with <baseRef>"
   git push
   ```
   Update your recorded SHA to the new `HEAD` and append a line to the
   review comment noting the conflict resolution.

   **Fallback — only when the resolution genuinely needs human judgment**
   (the two sides made incompatible product/design decisions and no
   objectively correct merge exists): `git merge --abort`, post a one-line
   comment that auto-merge is paused pending a human rebase, leave the
   `approved` verdict, and exit. Do not guess.

3. **Fix a failing pipeline if there is one.** Read the required-check
   rollup:
   ```bash
   gh pr checks <number> --repo <org>/<repo> --required
   ```
   - Any **required** check **failing** → fetch the failure detail and fix
     the cause on the branch:
     ```bash
     gh run view <run-id> --repo <org>/<repo> --log-failed
     ```
     Diagnose the actual failure — a compile/type error, a lint
     violation, a test the change broke, a stale snapshot/lockfile — and
     fix it the same way Step 7 fixes findings. Reproduce the failing
     check locally (run that test/lint/build) to confirm it now passes,
     then commit and push:
     ```bash
     git add -A && git commit -m "Fix <check> failure"
     git push
     ```
     Update your recorded SHA and note the fix in the review comment.
     Pushing re-triggers the pipeline, so the checks will be **pending**
     again — proceed to step 4 and enqueue `--auto` so the PR merges the
     moment the now-fixed pipeline is green.

     **Fallback — only when the failure is not yours to fix** (flaky or
     infrastructure failures outside the diff, or a fix that needs design
     judgment): post a one-line comment naming the check and that
     auto-merge is paused pending a fix, leave `approved`, and exit. Never
     force a merge over a genuinely red required check.
   - Required checks **pending** (including right after you pushed a fix)
     → enqueue auto-merge: step 4 (`--auto`).
   - Required checks **passing** → merge now (step 4, immediate path),
     provided you pushed nothing in steps 2–3 (a push leaves checks
     pending → enqueue `--auto` instead).
   - **No required checks reported** → the branch is unprotected. What to
     do depends on `require-ci-before-merge`:
     - **`false` (default)** → preserve today's behaviour: if you pushed
       nothing in steps 2–3, merge now (step 4, immediate path).
     - **`true`** → require a green CI gate before merging. Read the
       full check rollup (not just required ones):
       ```bash
       gh pr checks <number> --repo <org>/<repo>
       ```
       - **No checks at all** on the head SHA → **pause**: post a
         one-line comment "auto-merge paused: require-ci-before-merge is
         set but no CI checks are configured", leave `approved`, and
         exit. Never merge.
       - Some checks **failing** → fix-or-pause exactly as for a failing
         required check above (read the run logs, fix the cause on the
         branch and push — which makes the checks pending, then enqueue
         `--auto`; or, when the failure is not yours to fix, pause with a
         one-line comment and leave `approved`).
       - All checks **passing** and you pushed nothing in steps 2–3 →
         merge now (step 4, immediate path).
       - Any check **pending** (none required, so `--auto` would *not*
         wait for them) → **watch for a short, bounded window** to catch a
         fast pipeline in this run, then hand off if it is still running.
         Do **not** block indefinitely — this skill reviews one PR per
         invocation and exits. Watch for ~3 minutes (or any bounded poll —
         the point is a short wait, not an open-ended block):
         ```bash
         timeout 180 gh pr checks <number> --repo <org>/<repo> --watch
         ```
         - Settles **green** within the window → merge now (step 4,
           immediate path).
         - Settles **red** within the window → fix-or-pause exactly as for
           a failing check above.
         - **Still pending** when the window elapses → stop watching and
           hand off. Leave the `approved` verdict, post a one-line comment
           ("auto-merge deferred: CI still running — PR stays approved and
           will merge once green via a re-run or a human"), and exit. The
           PR is safe — it is never merged without a green gate. It
           completes when a human merges it, or when a later review pass
           re-selects it (after new commits land).

4. **Merge.** Squash-merge and delete the branch.
   - **Immediate** (nothing pushed in steps 2–3, required checks already
     green or none):
     ```bash
     gh pr merge <number> --repo <org>/<repo> --squash --delete-branch
     ```
     If this fails because branch protection requires an approving review,
     retry once as an admin merge — this skill records its approval as a
     comment and the `approved` label, **not** as a GitHub review (see
     Rules), so the required-review rule must be satisfied
     administratively:
     ```bash
     gh pr merge <number> --repo <org>/<repo> --squash --delete-branch --admin
     ```
     If the admin retry also fails (the actor lacks admin rights), fall
     back to the enqueue path below.
   - **Enqueue** (checks pending — including after a fix push — or admin
     unavailable):
     ```bash
     gh pr merge <number> --repo <org>/<repo> --squash --delete-branch --auto
     ```
     GitHub merges automatically once its branch-protection requirements
     (the now-fixed checks, any required review) are met.

     `--auto` requires the repo's "Allow auto-merge" setting to be on. If
     this call **fails** because auto-merge is disabled on the repo, do
     **not** fall back to an unguarded immediate merge — that would defeat
     the gate you just enqueued behind. Instead **pause**: post a one-line
     comment ("auto-merge paused: repo-level auto-merge is disabled —
     enable it with `/github-workflow:setup harden`"), leave `approved`,
     and exit. Confirm the enqueue actually took in step 5 below.

5. **Verify the outcome — never assume.** Re-read the state:
   ```bash
   gh pr view <number> --repo <org>/<repo> --json state,mergedAt,autoMergeRequest
   ```
   - `state` `MERGED` → report `Merged PR #<number> <title> (squash)`.
   - `autoMergeRequest` is non-null (auto-merge enqueued) → report
     `Auto-merge queued for PR #<number> <title> — will land when checks
     / branch protection clear`.
   - You took the **Enqueue** path but `autoMergeRequest` is null and
     `state` is still `OPEN` → the `--auto` call did not take (repo
     auto-merge disabled). Pause per step 4: post the one-line comment,
     leave `approved`, and exit. Do not claim success.
   - Neither merged nor queued → report exactly why the merge did not
     complete. Do not claim success.

6. **The linked issue closes itself.** The PR's `closingIssuesReferences`
   close the issue on merge — do not close it by hand. The branch was
   deleted by the merge; there is nothing else to clean up.

Report the merge outcome alongside the Step 10 review line, then exit.

---

## Error Handling

If anything goes wrong (gh commands fail, branch checkout fails, a changed
file cannot be read, the PR has no diff, or the codebase is too large to
review thoroughly):

1. Release the atomic claim (`templates/claim-procedure.md` **Release**
   for target `pr-<number>`): `git push origin :refs/claims/pr-<number>`
   and `rm -f .claude/claim-pr-<number>.sha`. Idempotent.
2. Remove the `reviewing` state label.
3. Apply the `failed` review-state label (purpose key `failed`, default
   name `review-failed`).
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
- Do not merge a PR **except** the one sanctioned auto-merge in Step 11 —
  only when the verdict is Approved, `review.config.md` sets Auto-Merge on
  Approval to `enabled` (off by default), and the review comment is already
  posted. Step 11 first resolves any merge conflicts and fixes any failing
  required check on the branch, then merges (or enqueues `--auto`); it
  never force-merges over a genuinely red required check. When
  `require-ci-before-merge` is set, it also never merges a PR that has no
  CI gate at all (no checks, or a red check it cannot fix) — it pauses and
  leaves `approved`. Never merge in read-only mode.
- Do not close a PR **except** to reconcile duplicates in Step 2b — when
  two or more open PRs close the same issue, close the losers and keep the
  winner. That is the one sanctioned close; never close a PR for any other
  reason, and never in read-only mode.
- Do not make discretionary refactors or stylistic changes.
- Push fixes for all concrete, objectively wrong problems (blocking and minor).
- Review one PR per invocation, then exit.
