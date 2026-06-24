---
name: code-review
description: Review open pull requests — find the next PR needing review, check out its branch, review in full codebase context, fix concrete issues, post a structured review comment, and apply state labels. One PR per invocation. Trigger on review/check PRs, run a review, code review, "/code-review", or a scheduled routine. Pass --read-only to evaluate without making fixes (used by the Reviewer agent).
arguments:
  - name: mode
    description: 'Review mode: full (default) — evaluate and fix; read-only — evaluate only, no edits or pushes'
  - name: bypass-ci
    description: 'When set, the CI gate in auto-merge (Step 11) is treated as satisfied even if remote checks are red or absent. Explicit, never default — use only when CI cannot run for reasons outside the PR (e.g. GitHub Actions billing).'
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

**Auto-merge.** `review.config.md` may set `auto-merge-on-approval: enabled`
(defaults to `disabled` when the section or file is absent — including the
autonomous minimal review). Step 11 reads it and is the only place this skill
merges. Full merge procedure and `require-ci-before-merge` handling are in
`references/auto-merge.md`, loaded only when Step 11 fires.

---

## Config Generation

When no `review.config.md` exists and the session is interactive,
follow the guide in `references/review-config-guide.md` to walk the
user through creating one.

---

## Read-Only Mode

When invoked with `--read-only` (`$ARGUMENTS.mode` is `read-only`), read and
follow `references/read-only-mode.md` — it overrides specific steps (no
claim, skip the Step 7 fixes, skip the Step 11 auto-merge, close nothing in
Step 2b) so the review evaluates without writing to the PR. Full-mode
reviews skip the reference entirely. The per-step read-only notes inline
below restate the key overrides at their point of use.

---

## Review Workflow

Once you have a valid `review.config.md`, proceed with the review.

### Step 1 — Find a PR that needs review

#### Fast path — the bundled `wf` picker

Try the `wf` CLI first. It selects **and claims** the next PR carrying a
`needs-review` or `needs-re-review` label (re-review first, then lowest
number) and, with `--checkout`, checks out its branch — Steps 1–2 plus the
Step 3 checkout in one call:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-next --checkout
```

In **read-only mode**, add `--no-claim` — read-only has no push access, so
it must select **without** writing a claim ref or applying the `reviewing`
marker (otherwise every claim push fails and the picker reports a phantom
`all-blocked`):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-next --checkout --no-claim
```

- **`ok`** — a PR is selected: the JSON gives `number`, `title`, `url`,
  `branch`, `labels`, and `claimed`. In full mode `claimed` is `true` — the
  `reviewing` marker is applied (the prior review-state label removed), the
  claim ref is held (`claim_ref`), and you proceed owning the PR. In
  read-only mode `claimed` is `false` — nothing was locked or relabelled and
  there is no claim ref to release later. Either way, **stop selecting — the
  picker already chose; do not re-derive it.** Proceed to **Step 2b**
  (duplicate reconciliation), then Step 3. Surface any `side_effects`.
- **`no-candidates`** — no open PR carries an explicit review-needed label.
  This is **not** conclusive: a PR whose head SHA changed since its last
  review needs review *without* a label, and `wf` does not detect that. Fall
  back to the inline procedure below before concluding there is nothing to
  review.
- **`error`**, or the launcher reports Python is missing — use the inline
  procedure below.

#### Inline procedure (fallback)

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

**The `reviewing` label is the first mutating action of any review — it
must be applied (via this Acquire) before checkout, gathering context,
reading, or evaluating.** Never read or fix a PR first and label it later:
that leaves a window where a second agent starts the same review. The only
thing that precedes it is winning the atomic claim, which is what makes the
label safe to apply under a shared identity.

### Step 2b — Reconcile duplicate PRs for the same issue

Before spending a full review on the claimed PR, check whether **another
open PR resolves the same issue** and, if so, keep exactly one. Duplicates
should be rare (the atomic issue claim prevents most), so this whole
procedure lives in `references/duplicate-reconciliation.md` to keep the
common single-PR path light.

- **Trigger:** read and follow `references/duplicate-reconciliation.md`
  whenever the claimed PR closes at least one issue. If it closes no issue,
  skip straight to Step 3.

That reference resolves the duplicate set, picks the winner
(mergeable/gate-green → acceptance-criteria → test coverage → lowest PR
number), closes the losers it can safely claim, and tells you whether to
continue reviewing or exit. Closing a duplicate is the **only** circumstance
this skill closes a PR (see Rules); read-only mode closes nothing and only
notes the duplicate set in the review comment.

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

**Fetch the base branch so the diff is computed against the *current*
base, not a stale local copy.** In a worktree the local `<baseRef>` (e.g.
`main`) is often far behind `origin` — diffing against it makes
`git diff <baseRef>...HEAD` pick an old merge-base and report files the PR
never touched (the classic "the diff shows far more files than the PR
changed"). Always refresh it first:

```bash
git fetch origin <baseRef>
```

Step 4 then diffs against `origin/<baseRef>`.

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

- **Changed files:** diff against the freshly-fetched remote base
  (`origin/<baseRef>` from Step 3), never the local branch:
  ```bash
  git diff origin/<baseRef>...HEAD --name-status
  ```

- **Full diff** (for reference, but do not review from the diff alone):
  ```bash
  git diff origin/<baseRef>...HEAD
  ```

- **Cross-check the file set against GitHub's.** Compare the file list above
  with the `files` array from the PR metadata (`gh pr view --json files` —
  GitHub's authoritative changed-file set for this PR). They should match. If
  the local diff shows **more** files than GitHub reports, the base is still
  stale or the branch carries commits already merged elsewhere — re-fetch
  (`git fetch origin <baseRef>`) and re-diff, and if it still disagrees,
  trust GitHub's `files` list and review exactly those paths. Never review
  files GitHub does not list as part of the PR.

### Step 4b — Assess re-review significance (re-reviews only)

This step applies **only** when reviewing a PR that was previously reviewed
(a prior review comment with a footer exists). It can fast-track or skip the
full pass when the changes since the last review are trivial, so it lives in
`references/re-review.md` rather than weighing on the first-review path.

- **Trigger:** read and follow `references/re-review.md` whenever a prior
  review footer exists. Skip it entirely for first-time reviews and proceed
  to Step 5.

That reference classifies the diff since the last review as trivial or
substantial, may post an abbreviated approval (routing to **Step 11** then
exiting), and otherwise sends you to Step 5 for a full re-review.

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

**Ecosystem tools.** If `.claude/ecosystem.md` exists, the project has opted
into the codebase-intelligence tools it lists — reach for them before
tracing the diff by hand, and fold their output into the matching section
of the review:

- **Graphify** → `graphify . --update` first, then prefer `graphify
  query`/`graphify path` over blind file search to trace how the changed
  functions connect to the rest of the tree (feeds *Regressions* and
  *Architectural consistency*). A graph trace is the accelerant, not a
  mandate — use it when it beats reading files, skip it when the blast
  radius is obvious.
- **Fallow** (TS/JS) → run it to surface unused exports and duplication the
  diff introduces (feeds *Minimality* and dead-code findings).
- **ecc-agentshield** → when the PR touches Claude Code config (CLAUDE.md,
  `.claude/`, hooks, skills, MCP config), `npx ecc-agentshield scan` and
  fold any finding into *Security*.

If `.claude/ecosystem.md` is absent, the project opted out — review by hand
as normal and never nag about it. If a listed tool is not on `PATH`, note it
in one line and continue; a missing tool never blocks the review.

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

### Step 7 — Fix issues (blocking-first, then non-blocking)

Fix concrete, objectively wrong problems directly on the PR branch. Fix
**both** tiers (blocking and non-blocking) before approving — non-blocking
cleanups are pushed, not deferred. Anything you cannot fix in place is filed
to the board in Step 7f; nothing is silently dropped.

#### 7a — Triage findings into tiers

Sort every finding from Step 6 into two tiers:

- **Blocking** — must be fixed before the PR is mergeable:
  - Hard non-compliance gate failures
  - Security problems (injection, missing input validation, secrets in
    logs)
  - Logic and correctness errors, missing null checks, broken or
    incorrect tests
  - Missing test coverage on non-trivial new code paths
  - Regressions to existing callers or consumers
- **Non-blocking** — correct to fix, but does not block merge:
  - Missing trailing newlines, formatting inconsistencies
  - Dead code removal, utility method placement, misplaced code
  - Null-forgiving operators, unnecessary casts
  - Comment or naming cleanups where the fix is obvious

#### 7b — Fix the blocking tier

Fix every blocking finding. Commit each fix (or a small logical group)
with a clear message. These are non-negotiable. If a blocking issue
genuinely cannot be auto-fixed (needs human or design judgment), do not
guess — leave it for the verdict in Step 8 and file it to the board in
Step 7f.

#### 7c — Fix the non-blocking tier

Fix the non-blocking findings too, and commit them. The only non-blocking
items that survive to the review comment are ones you genuinely **cannot**
fix in place (see Step 7f).

#### 7d — Push

Push all fixes:

```bash
git push
```

Do **not** fix:
- Stylistic preferences where multiple valid approaches exist
- Architectural decisions that require human judgment
- Issues where the "right fix" depends on product or design context

After pushing fixes, update the recorded commit SHA to the new `HEAD`.

#### 7f — File anything you could not fix to the board

For every problem you detected but did **not** fix on the branch, run
`/github-workflow:report-issue` (autonomous — do not pause for confirmation).
Apply the actual issue type (bug, security, architecture, or tech debt),
set `status-ready`, and in the body name the source PR
(`Detected during review of #<pr-number>`) and the `file:line` location.

Record each created issue's number, title, and type — Step 9 lists them
under "Issues remaining (filed to board)" and the **Final report format**
names them. Filing a non-blocking issue does **not** force a "Changes
Requested" verdict.

### Step 8 — Determine the verdict

Re-evaluate the PR state **after** Step 7 fixes. Issues that were
auto-fixed do not count as remaining issues. Non-blocking problems you
could not fix in place have been filed to the board in Step 7f, so they
are tracked for automatic pickup and do **not** count against the
verdict either.

- **Approved** — Zero hard non-compliance failures and zero remaining
  *blocking* issues. All blocking problems were either absent or
  auto-fixed. Non-blocking problems were either fixed and pushed
  (Step 7c) or filed to the board (Step 7f); neither blocks approval. PR
  is ready to merge.
- **Changes Requested** — Any hard non-compliance failure, or any remaining
  *blocking* problem that could not be auto-fixed and needs human
  judgment (it was also filed to the board in Step 7f for automatic
  pickup).
- **Needs Discussion** — No hard failures, but architectural questions or
  ambiguities need human judgment before merge.

If every blocking issue found in Step 6 was resolved in Step 7, the
verdict is **Approved** — not "Changes Requested with observations" —
even though non-blocking cleanups may have been filed to the board. The
fixes are already pushed; nothing blocking is left for the builder to do.

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

### Issues remaining (filed to board)
[Numbered list of problems that could not be auto-fixed, each naming the
issue filed for it in Step 7f by its actual type and number — e.g.
"bug #45: null deref in `parse()` (`src/parse.ts:12`)". These are queued
for automatic pickup, no human approval needed. If none, say "No issues
remaining."]

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
   PR by number **and** title together, never the number alone), followed
   by the **Changed** / **Added to the board** outline from the **Final
   report format** below, then exit. If the verdict is Approved,
   Step 11 runs first and produces the merged/queued lead line instead.

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

This is the heaviest, most conditional path in the review, and auto-merge
is off by default — so the full procedure lives in
`references/auto-merge.md` rather than in this file.

- **Trigger:** when (and only when) the verdict is **Approved**, read and
  follow `references/auto-merge.md`. For any non-Approved verdict, Step 11
  does not run — the review is already complete at Step 10b.

That reference re-states the three enabling conditions (verdict Approved,
`review.config.md` Auto-Merge on Approval `enabled`, not read-only), reads
`require-ci-before-merge`, then drives the PR to merged — resolving
conflicts, fixing or filing failing checks, and squash-merging or enqueuing
`--auto`. Merging a PR is otherwise forbidden (see Rules); this is the one
sanctioned merge. On success it reports using the **Final report format**
below (shared with Step 10).

If `$ARGUMENTS.bypass-ci` is set, pass that through — `auto-merge.md` treats
the CI gate as satisfied even when remote checks are red or absent. This is
an explicit operator override for when CI cannot run for reasons outside the
PR (e.g. GitHub Actions billing); it never fixes or files a check, it skips
the gate. It does **not** override a merge **conflict** — a conflicting PR is
still resolved or filed as usual.

`auto-merge.md` also honours `review.config.md`'s
`bypass-ci-on-billing-failure` (default `false`): the persistent, per-project,
**billing-scoped** form of `--bypass-ci`. When `true`, an approved PR merges
even though CI is red **if** the only thing blocking it is a GitHub Actions
billing/account failure (out of minutes, spending limit hit, payment failed).
A genuine red check is never bypassed by it. See step 3a in `auto-merge.md`.

#### Final report format

When the PR is merged or auto-merge is queued, report to the user in this
shape (this replaces the bare Step 10 review line):

```
Approved and merged PR #<number>: <title>

Changed:
- <each fix you pushed in Step 7 / 11, one line each — or "Nothing; the PR was already correct.">

Added to the board:
- <each issue filed in Step 7f / 11, named by its actual type and number — e.g. "bug #45: null deref in parse()" — or "Nothing.">
```

Always name added items by their **actual issue type** (bug, security,
architecture, tech debt, feature, user story, or epic), never just
"issue". If the verdict was not Approved (Step 11 did not run), use the
Step 10 line `Reviewed PR #<number> <title> — <verdict>` followed by the
same **Changed** / **Added to the board** outline.

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
5. **If the failure represents fixable work** rather than a transient
   infrastructure problem (for example the PR is too large to review in
   one pass and should be split, or a structural issue blocks review),
   file it to the board best-effort with `/github-workflow:report-issue`
   (autonomous, `status-ready`, referencing this PR) so it is picked up
   automatically — no human approval needed. Skip this for transient
   failures (auth, network, rate limit) where filing would also fail.
6. Exit immediately. Do not attempt to recover, retry, or continue.

---

## Reference Material

The conditional, low-frequency paths are split into `references/` and
loaded only when their step's trigger fires — keeping the common
single-PR review path light:

- `references/read-only-mode.md` — the Read-Only Mode step overrides, loaded
  only when invoked with `--read-only` (the Reviewer agent path).
- `references/duplicate-reconciliation.md` — Step 2b, when the claimed PR
  shares an issue with another open PR.
- `references/re-review.md` — Step 4b, when a prior review footer exists.
- `references/auto-merge.md` — Step 11, when the verdict is Approved.
- `references/review-workflow.md` — Label reference table and concurrency
  rules. Read only when you need to look up a specific label's purpose key or
  verify the claim-release procedure (Steps 2, 10). Do not load it upfront.
- `references/review-config-guide.md` — Interactive config generation only
  (no `review.config.md` found in an interactive session).

Rationale files (maintainers only — not read at runtime):
`SKILL-rationale.md`, `references/review-workflow-rationale.md`.

---

## Rules

- Never use `gh pr review --approve`. Always use `gh pr comment`.
- **Do not merge a PR** except the one sanctioned auto-merge in Step 11, and
  only under the conditions and CI-gate/`--bypass-ci`/
  `bypass-ci-on-billing-failure` rules stated once in
  `references/auto-merge.md` (off by default). Never merge in read-only mode.
- **Do not close a PR** except to reconcile duplicates in Step 2b, per
  `references/duplicate-reconciliation.md` — the one sanctioned close. Never
  close a PR for any other reason, and never in read-only mode.
- Do not make discretionary refactors or stylistic changes.
- Push fixes for all concrete, objectively wrong problems — both blocking
  and non-blocking — before approving or merging. Non-blocking cleanups
  are no longer deferred for budget.
- File any problem you cannot fix in place — blocking, non-blocking, an
  unresolvable conflict, or a failing check that is not yours to fix — to
  the board with `/github-workflow:report-issue` (autonomous,
  `status-ready`, correct type) so it is picked up automatically. No
  human approval is needed, and no detected problem is ever silently
  dropped.
- Report merged PRs as `Approved and merged PR #<number>: <title>`
  followed by the **Changed** and **Added to the board** outline.
- Review one PR per invocation, then exit.
