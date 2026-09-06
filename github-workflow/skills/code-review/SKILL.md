---
name: code-review
description: Review open pull requests — find the next PR needing review, check out its branch, review in full codebase context, fix concrete issues, post a structured review comment, and apply state labels. One PR per invocation. Trigger on review/check PRs, run a review, code review, "/code-review", or a scheduled routine. Pass --read-only to evaluate without making fixes (used by the Reviewer agent).
arguments:
  - name: mode
    description: 'Review mode: full (default) — evaluate and fix; read-only — evaluate only, no edits or pushes'
  - name: pr
    description: 'Optional PR number. When given, that PR is reviewed and the picker is skipped — used by the execute skill Phase 8 and by any caller that already knows which PR it wants reviewed.'
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

Review one open pull request end-to-end: find it, claim it, read the code in context, fix what can be fixed, post a structured comment, apply labels. Exit when done. If no PRs need review or anything goes wrong, exit immediately.

## Prerequisites

### GitHub CLI

Before doing anything else, verify `gh` is authenticated:

```bash
gh auth status
```

If this fails, stop and tell the user to run `gh auth login` first.

### Review Configuration

This skill requires a `review.config.md` file that defines repository identity, label definitions, non-compliance gates, tech-stack review rules, and the review comment footer.

**Finding the config:** Look in these locations, in order:

1. `./docs/review.config.md`
2. `./review.config.md`

If neither exists and the session is interactive (user is present), run the **Config Generation** flow (see below) to create one.

If the session is autonomous (called from `/github-workflow:execute` or a scheduled routine), skip the config generation — resolve the review-state labels through the single path in `templates/default-labels.md` (review-state purposes default to the `review-` prefix). Proceed with a minimal review (no custom gates, no tech-stack rules, standard footer). The label inventory should already exist (created at setup); if a label is missing, create it with the guarded create-if-missing pattern from `templates/default-labels.md` (no `--force`). Note in the review comment that no `review.config.md` was found and defaults were used. In interactive sessions, also warn the user: "No `review.config.md` found — using default labels. Run `/github-workflow:setup` to configure review labels for this project."

**Resolving label names.** Every label this skill applies or filters on (`reviewing`, `approved`, `changes-requested`, …) is a **purpose key**. Resolve each to its concrete name through `templates/default-labels.md` before use — never apply a bare name literally and never assume a prefix. This guarantees the claim label this skill writes is the identical string other skills filter on.

Read `review.config.md` fully before starting. Everything project-specific lives there. This workflow is generic.

**Auto-merge.** `review.config.md` may set `auto-merge-on-approval: enabled` (defaults to `disabled` when the section or file is absent — including the autonomous minimal review). Step 11 reads it and is the only place this skill merges. Full merge procedure and `require-ci-before-merge` handling are in `references/auto-merge.md`, loaded only when Step 11 fires.

---

## Config Generation

When no `review.config.md` exists and the session is interactive, follow the guide in `references/review-config-guide.md` to walk the user through creating one.

---

## Read-Only Mode

When invoked with `--read-only` (`$ARGUMENTS.mode` is `read-only`), read and follow `references/read-only-mode.md` — it overrides specific steps (no claim, detached checkout, skip the Step 7 fixes, skip the Step 10b rework cascade, skip the Step 11 auto-merge, close nothing in Step 2b, and hand the comment and labels to a caller that owns the verdict) so the review evaluates without writing to the PR. Full-mode reviews skip the reference entirely. The per-step read-only notes inline below restate the key overrides at their point of use.

---

## Review Workflow

Once you have a valid `review.config.md`, proceed with the review.

### Step 1 — Find a PR that needs review

#### Pinned PR — an explicit number was given

When the invocation names a PR (`$ARGUMENTS.pr`, or a number the user or a calling skill passed), that PR is the subject and there is nothing to select. Do **not** run the picker — it would review a different PR by priority.

- **Full mode:** claim it (`wf claim --pr <number>`, see Step 2) and check out its branch, then continue at Step 2b — or at **Step 1b** first if it carries `changes-requested`, exactly as the picker routes that tier. If the claim is lost, another agent owns this PR: report that and exit rather than moving to a different one.
- **Read-only mode:** no claim, and check out **detached** (`gh pr checkout
  <number> --detach`) because another worktree on this clone may already hold
  the branch and git refuses to check out a branch twice. Continue at Step 2b; read-only never enters Step 1b, which pushes.

#### Fast path — the bundled `wf` picker

Try the `wf` CLI first. It selects **and claims** the next PR carrying a `needs-review`, `needs-re-review`, or `changes-requested` label (re-review first, then changes-requested, then needs-review; lowest number within each tier) and, with `--checkout`, checks out its branch — Steps 1–2 plus the Step 3 checkout in one call:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-next --checkout
```

In **read-only mode**, add `--no-claim` — read-only has no push access, so it must select **without** writing a claim ref or applying the `reviewing` marker (otherwise every claim push fails and the picker reports a phantom `all-blocked`):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-next --checkout --no-claim
```

- **`ok`** — a PR is selected: the JSON gives `number`, `title`, `url`, `branch`, `labels`, `claimed`, and **`prior_state`** (the label it was picked from — `needs-review`, `needs-re-review`, or `changes-requested`). In full mode `claimed` is `true` — the `reviewing` marker is applied (the prior review-state label removed), the claim ref is held (`claim_ref`), and you proceed owning the PR. In read-only mode `claimed` is `false` — nothing was locked or relabelled and there is no claim ref to release later. Either way, **stop selecting — the picker already chose; do not re-derive it.** If `prior_state` is `changes-requested`, the PR needs **rework before review** — jump to **Step 1b (Rework cascade)** below. Otherwise proceed to **Step 2b** (duplicate reconciliation), then Step 3. Surface any `side_effects`.
- **`no-candidates`** — no open PR carries an explicit review-needed label. This is **not** conclusive: a PR whose head SHA changed since its last review needs review *without* a label, and `wf` does not detect that. Fall back to the inline procedure below before concluding there is nothing to review.
- **`all-blocked`** — every reviewable PR is currently claimed by another review agent. Report that all candidate PRs are being handled by other agents and exit cleanly. Do **not** fall through to the inline procedure below — a blind re-scan would just skip the same `reviewing`-labelled PRs and surface nothing new. (This status only arises in full mode; read-only passes `--no-claim`, so its picker never claims and never reports `all-blocked` — see the phantom-`all-blocked` note above.)
- **`error`**, or the launcher reports Python is missing — use the inline procedure below.

#### Inline procedure (fallback)

```bash
gh pr list --state open --repo <org>/<repo> --json number,title,labels,headRefName,baseRefName,headRefOid
```

Skip any PR that has:
- The `reviewing` state label (another review agent is in progress).
- The `updating` state label (a builder agent is addressing feedback).
- The `approved` state label **unless** it also has `needs-re-review` (approved PRs that received new commits still need re-review).

For each remaining PR, determine whether it needs attention:

1. Get Claude's most recent review comment:
   ```bash
   gh pr view <number> --repo <org>/<repo> --json comments
   ```
2. Filter comments for the review footer marker (defined in `review.config.md`).
3. If no such comment exists, it needs review. A PR carrying the `needs-review` entry-state label (applied at PR creation) is the normal first-review case.
4. If a comment exists, extract the `Reviewed at <SHA>` line. If that SHA differs from the current `headRefOid`, it needs review. Otherwise skip.
5. A PR carrying `changes-requested` always needs attention — it needs rework followed by re-review.

**Prioritisation:** Three tiers, highest first:
1. `needs-re-review` — pick the lowest-numbered one.
2. `changes-requested` — pick the lowest-numbered one (enters rework cascade, Step 1b).
3. `needs-review` or SHA-changed — pick the lowest-numbered one.

If no PRs need review or rework, report that and exit. Do not loop through multiple PRs.

**Never ask the user which PR to review.** Always auto-select using the prioritisation rules above. If the user says "review PRs" or "review pull requests" (plural), that means "find the next one and review it", not "review all of them" or "let me choose".

### Step 1b — Rework cascade (changes-requested PRs only)

When the selected PR was picked from the `changes-requested` tier, load `references/rework-cascade.md` and follow **Step 1b** there — it reads the prior review, addresses each issue, pushes fixes, relabels, then returns you to **Step 2b** to review the updated PR.

### Step 2 — Claim the PR

Multiple review agents may run concurrently — possibly under the same GitHub identity, where a shared label cannot exclude a rival. **Claiming is the first mutating action of any review:** it must precede checkout, gathering context, reading and evaluating, or a second agent may start the same review.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim --pr <number>
```

- **Exit 0** — you hold it. `refs/claims/pr-<number>` is the actual lock (a server-side compare-and-swap), and the command has already applied the `reviewing` state label as the human-visible marker. No label read-back.
- **Exit 27** (`lost`) — another agent owns this PR. Make **no** changes. In the picker loop, claim the next candidate in Step 1's priority order; if every candidate is lost, report that all PRs are being handled by other agents and exit cleanly. On a named PR, report that and exit rather than reviewing a different one. Never retry a lost claim.
- **Exit 20** — a broken environment, not a rival (usually no write access to `refs/claims/*`). Report it and stop; never fall back to a bare label as a "soft" claim, which reintroduces the race the ref removes.

Label semantics and concurrency rules live in `references/review-workflow.md` (load only if needed).

### Step 2b — Reconcile duplicate PRs for the same issue

If the claimed PR closes at least one issue, load `references/duplicate-reconciliation.md` and follow it — it checks whether another open PR resolves the same issue, picks the winner, closes the losers it can safely claim (the **only** circumstance this skill closes a PR — see Rules; read-only mode closes nothing), and tells you whether to continue reviewing or exit. If the PR closes no issue, skip straight to Step 3.

### Step 3 — Check out the PR branch

```bash
gh pr checkout <number>
```

In **read-only mode** add `--detach` — another worktree on this clone may already hold the branch, and git refuses to check out a branch twice. If the pinned-PR path already checked out that SHA detached, this step is a no-op.

If checkout fails: release the claim (`wf claim-release --pr <number>`), remove the `reviewing` label, apply the `failed` review-state label (purpose key `failed`, default name `review-failed`), post a brief failure comment with the footer, and exit. In read-only mode there is no claim and no marker to remove: report the failure to the caller and exit without labelling the PR `failed`, which no picker tier selects.

Record the current commit SHA:

```bash
git rev-parse HEAD
```

Save this SHA for the review footer.

**Fetch the base branch so the diff is computed against the *current* base, not a stale local copy.** In a worktree the local `<baseRef>` (e.g. `main`) is often far behind `origin` — diffing against it makes `git diff <baseRef>...HEAD` pick an old merge-base and report files the PR never touched (the classic "the diff shows far more files than the PR changed"). Always refresh it first:

```bash
git fetch origin <baseRef>
```

Step 4 then diffs against `origin/<baseRef>`.

### Step 4 — Gather context

Run all of the following. If any command fails, treat as a review failure (see Error Handling below).

- **PR metadata:**
  ```bash
  gh pr view <number> --repo <org>/<repo> --json title,body,baseRefName,headRefName,files,additions,deletions
  ```

- **Linked issue:** Parse the PR body for `Closes #N` or `Fixes #N`, then:
  ```bash
  gh issue view <N> --repo <org>/<repo> --json title,body,labels,milestone
  ```
  The issue is the source of truth for what the PR should accomplish. If there is no linked issue and the config lists that as a hard gate, it is a non-compliance failure, but continue the review.

- **Changed files:** diff against the freshly-fetched remote base (`origin/<baseRef>` from Step 3), never the local branch:
  ```bash
  git diff origin/<baseRef>...HEAD --name-status
  ```

- **Full diff** (for reference, but do not review from the diff alone):
  ```bash
  git diff origin/<baseRef>...HEAD
  ```

- **Cross-check the file set against GitHub's.** Compare the file list above with the `files` array from the PR metadata (`gh pr view --json files` — GitHub's authoritative changed-file set for this PR). They should match. If the local diff shows **more** files than GitHub reports, the base is still stale or the branch carries commits already merged elsewhere — re-fetch (`git fetch origin <baseRef>`) and re-diff, and if it still disagrees, trust GitHub's `files` list and review exactly those paths. Never review files GitHub does not list as part of the PR.

### Step 4b — Assess re-review significance (re-reviews only)

If a prior review comment with a footer exists, load `references/re-review.md` and follow it — it classifies the diff since the last review as trivial or substantial, may post an abbreviated approval (routing to **Step 11**, then exiting), and otherwise sends you to Step 5 for a full re-review. First-time reviews skip it entirely and proceed to Step 5.

---

### Step 5 — Read the code in context

For every changed file:

1. Read the **full file**, not just the changed lines. Understand what it does, how it is structured, and where the changes sit within it.
2. Read the **files it imports from** and the **files that import it**. Follow the dependency chain at least two levels deep.
3. For every **function or method modified**, grep the codebase for all call sites. Read each call site in context to verify the change is safe for all consumers.

Run any tech-stack-specific cross-boundary checks defined in `review.config.md` (e.g., verifying DTO/interface parity, API schema alignment).

Find and read existing **test files** for the changed modules. Understand what was already covered and what the PR adds or modifies.

### Step 6 — Evaluate the PR

Work through each area below using the full codebase context.

**Ecosystem tools.** If `.claude/ecosystem.md` exists, the project has opted into the codebase-intelligence tools it lists — reach for them before tracing the diff by hand, and fold their output into the matching section of the review:

- **Graphify** → `graphify . --update` first, then prefer `graphify query`/`graphify path` over blind file search to trace how the changed functions connect to the rest of the tree (feeds *Regressions* and *Architectural consistency*). A graph trace is the accelerant, not a mandate — use it when it beats reading files, skip it when the blast radius is obvious.
- **Fallow** (TS/JS) → run it to surface unused exports and duplication the diff introduces (feeds *Minimality* and dead-code findings).
- **ecc-agentshield** → when the PR touches Claude Code config (CLAUDE.md, `.claude/`, hooks, skills, MCP config), `npx ecc-agentshield scan` and fold any finding into *Security*.

If `.claude/ecosystem.md` is absent, the project opted out — review by hand as normal and never nag about it. If a listed tool is not on `PATH`, note it in one line and continue; a missing tool never blocks the review.

#### Hard non-compliance gates

Check every gate listed in `review.config.md`. Any failure here forces a `Changes Requested` verdict. Call out each failure explicitly in the review comment under the "Non-compliance" section.

#### Story alignment

Does the PR implement everything the linked issue describes? Does it implement anything not described? Are acceptance criteria met?

#### Logic and correctness

Trace every logic path step by step through the actual code. For calculations, substitute concrete values and verify the arithmetic. Check:

- Boundary conditions (zero, one, max, null, empty, negative)
- Concurrency (race conditions, double-reads, TOCTOU)
- Error paths (what happens when dependencies fail, return null, or throw)

#### Type safety and nullability

Are nullable types handled correctly? Could a null slip through to a dereference? Apply any tech-stack-specific type-safety rules from `review.config.md`.

#### Security

- No injection vulnerabilities (SQL, XSS, command, path traversal)
- Input validation at system boundaries
- No sensitive data in logs
- Apply any project-specific security checks from `review.config.md`

#### Architectural consistency

Does the change follow the architecture rules in `review.config.md`? Does it follow established codebase patterns or introduce a new one without justification? One responsibility per file.

#### Test quality and coverage

Apply the test expectations from `review.config.md`. Is every new code path exercised? Are boundary conditions and error paths tested? For bug fixes, is there a regression test?

If changed code has no tests and is non-trivial, this is a hard non-compliance failure (if configured as such in the config).

#### Regressions

From the callers and consumers found in Step 5, are any broken or subtly changed? Are unrelated code paths in the same files untouched and correct?

#### Minimality

Is every changed line necessary for the PR's stated purpose? Flag unrelated refactors, formatting changes, or comment edits.

### Step 7 — Fix issues (blocking-first, then non-blocking)

Fix concrete, objectively wrong problems directly on the PR branch. Fix **both** tiers (blocking and non-blocking) before approving — non-blocking cleanups are pushed, not deferred. Anything you cannot fix in place is filed to the board in Step 7e; nothing is silently dropped.

#### 7a — Triage findings into tiers

Sort every finding from Step 6 into two tiers:

- **Blocking** — must be fixed before the PR is mergeable:
  - Hard non-compliance gate failures
  - Security problems (injection, missing input validation, secrets in logs)
  - Logic and correctness errors, missing null checks, broken or incorrect tests
  - Missing test coverage on non-trivial new code paths
  - Regressions to existing callers or consumers
- **Non-blocking** — correct to fix, but does not block merge:
  - Missing trailing newlines, formatting inconsistencies
  - Dead code removal, utility method placement, misplaced code
  - Null-forgiving operators, unnecessary casts
  - Comment or naming cleanups where the fix is obvious

Neither tier includes stylistic preferences where several approaches are valid, architectural decisions that need human judgment, or anything whose right answer depends on product or design context. Those are not findings you fix; raise them in the review comment or file them in Step 7e.

#### 7b — Fix the blocking tier

Fix every blocking finding. Commit each fix (or a small logical group) with a clear message. These are non-negotiable. If a blocking issue genuinely cannot be auto-fixed (needs human or design judgment), do not guess — leave it for the verdict in Step 8 and file it to the board in Step 7e.

#### 7c — Fix the non-blocking tier

Fix the non-blocking findings too, and commit them. The only non-blocking items that survive to the review comment are ones you genuinely **cannot** fix in place (see Step 7e).

#### 7d — Push

Push all fixes:

```bash
git push
```

After pushing fixes, update the recorded commit SHA to the new `HEAD`.

#### 7e — File anything you could not fix to the board

For every problem you detected but did **not** fix on the branch, run `/github-workflow:report-issue` (autonomous — do not pause for confirmation). Apply the actual issue type (bug, security, architecture, or tech debt), set `status-ready`, and in the body name the source PR (`Detected during review of #<pr-number>`) and the `file:line` location.

Record each created issue's number, title, and type — Step 9 lists them under "Issues remaining (filed to board)" and the **Final report format** names them. Filing a non-blocking issue does **not** force a "Changes Requested" verdict.

### Step 8 — Determine the verdict

Re-evaluate the PR state **after** Step 7 fixes. Issues that were auto-fixed do not count as remaining issues. Non-blocking problems you could not fix in place have been filed to the board in Step 7e, so they are tracked for automatic pickup and do **not** count against the verdict either.

- **Approved** — Zero hard non-compliance failures and zero remaining *blocking* issues. All blocking problems were either absent or auto-fixed. Non-blocking problems were either fixed and pushed (Step 7c) or filed to the board (Step 7e); neither blocks approval. PR is ready to merge.
- **Changes Requested** — Any hard non-compliance failure, or any remaining *blocking* problem that could not be auto-fixed and needs human judgment (it was also filed to the board in Step 7e for automatic pickup).
- **Needs Discussion** — No hard failures, but architectural questions or ambiguities need human judgment before merge.

If every blocking issue found in Step 6 was resolved in Step 7, the verdict is **Approved** — not "Changes Requested with observations" — even though non-blocking cleanups may have been filed to the board. The fixes are already pushed; nothing blocking is left for the builder to do.

### Step 9 — Post the review

Write the comment in plain English, following `_shared/wording-standard.md`. The author reading this review may not have the context you built up, so each finding should state **the problem and the suggested fix** in complete sentences a reader can follow without the diff in front of them. Avoid telegraphic fragments and stacked clauses; define or avoid jargon; keep `file:line` references and identifiers precise in backticks. The section headings below give structure — the text under them is prose, not a stripped list of identifiers.

The **shape** of the review comment, and of what you report back when the review is done, follows `skills/user-facing-communication/SKILL.md`: the verdict and the current state first, anything outstanding or assumed where it cannot be missed, every issue and pull request named as well as numbered, and no investigation history.

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
issue filed for it in Step 7e by its actual type and number — e.g.
"bug #45: null deref in `parse()` (`src/parse.ts:12`)". These are queued
for automatic pickup, no human approval needed. If none, say "No issues
remaining."]

<footer from review.config.md>
```

The `Reviewed at <SHA>` line must contain the commit SHA from Step 3 (or the updated SHA from Step 7 if fixes were pushed).

### Step 10 — Reconcile labels and exit

1. Release the atomic claim now that the verdict is being recorded:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --pr <number>
   ```
   Idempotent and always exit 0 — releasing a ref that is already gone is not a failure.

2. Reconcile the PR's review-state labels to exactly the verdict. This is a deterministic dance — strip every stale state label, leave exactly the one verdict label, then read back and create-if-missing — so it runs as a tested code path rather than by hand. Run it from the repo root:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr <number> --verdict <approved|changes-requested|needs-discussion>
   ```

   Add `--fixes-applied` when Step 7 pushed fix commits, so the sticky `fixes-applied` label is kept. The JSON reports `verdict_label`, the `added`/`removed` labels, `created_label` (whether a missing verdict label had to be created), and `verified`. On `verified: true` the label state is correct — continue. On `verified: false`, report the failure but do not block. `wf review-finish` resolves every name by purpose key (`review.config.md` overrides, `review-` defaults otherwise) and creates a missing verdict label guarded — never with `--force`.

   **Thin fallback** — only when `wf` errors or Python is absent: load `references/review-workflow.md` and follow its **Label reconciliation fallback (Step 10)** section — it applies the verdict label and strips the stale state labels with plain `gh`, creating a missing verdict label guarded (never `--force`).

3. If `review.config.md` defines custom labels, evaluate each one's "When to apply" criteria against the PR. Apply matching labels and remove non-matching ones that were previously applied by a review. (`wf review-finish` reconciles only the standard review-state labels; project-specific custom labels stay your judgment.)

4. Check out the original branch you were on before the review.

5. Report `Reviewed PR #<number> <title> — <verdict>` (always name the PR by number **and** title together, never the number alone), followed by the **Changed** / **Added to the board** outline from the **Final report format** below, then exit. If the verdict is Approved, Step 11 runs first and produces the merged/queued lead line instead.

**Next step by verdict:**
- **Approved** → proceed to Step 11 (auto-merge).
- **Changes Requested** → proceed to Step 10b (rework cascade) if the remaining issues are concrete and addressable (not "needs human judgment"). Otherwise exit.
- **Needs Discussion** → exit here.

### Step 10b — Post-verdict rework cascade (Changes Requested only)

When the Issues Remaining are all concrete, fixable problems (not human- judgment items), load `references/rework-cascade.md` and follow **Step 10b** — it re-reads the review, fixes the issues, pushes, relabels, and returns you to **Step 4b** to re-review. If any item needs human judgment, skip this step and exit — `changes-requested` stays.

### Step 11 — Auto-merge on approval (if enabled)

Runs when (and only when) the verdict is **Approved** — for any other verdict the review is already complete at Step 10. Load `references/auto-merge.md` and follow it. It re-states the enabling conditions (verdict Approved, `review.config.md` Auto-Merge on Approval `enabled`, not read-only), handles `require-ci-before-merge`, the `--bypass-ci` override (pass `$ARGUMENTS.bypass-ci` through when set) and `review.config.md`'s `bypass-ci-on-billing-failure` and `bypass-ci-when-no-pipeline`, and drives the PR to merged — resolving conflicts, fixing or filing failing checks, and squash-merging or enqueuing `--auto`. Merging a PR is otherwise forbidden (see Rules); this is the one sanctioned merge. On success it reports using the **Final report format** below (shared with Step 10).

#### Final report format

When the PR is merged or auto-merge is queued, report to the user in this shape (this replaces the bare Step 10 review line):

```
Approved and merged PR #<number>: <title>

Changed:
- <each fix you pushed in Step 7 / 11, one line each — or "Nothing; the PR was already correct.">

Added to the board:
- <each issue filed in Step 7e / 11, named by its actual type and number — e.g. "bug #45: null deref in parse()" — or "Nothing.">
```

Always name added items by their **actual issue type** (bug, security, architecture, tech debt, feature, user story, or epic), never just "issue". If the verdict was not Approved (Step 11 did not run), use the Step 10 line `Reviewed PR #<number> <title> — <verdict>` followed by the same **Changed** / **Added to the board** outline.

This shape is the one `skills/user-facing-communication/SKILL.md` asks for: outcome and state in the first line, then only what changed and what is now outstanding. Keep it that way. Do not append the reasoning behind each fix, a file list, or a note that the review was thorough. If something is still blocked, or you had to assume something to reach the verdict, add an **Outstanding** or **Assumptions** section under the outline rather than burying it in the lines above.

---

## Error Handling

If anything goes wrong (gh commands fail, branch checkout fails, a changed file cannot be read, the PR has no diff, or the codebase is too large to review thoroughly):

1. Release the atomic claim: `wf claim-release --pr <number>`. Idempotent.
2. Remove the `reviewing` state label.
3. Apply the `failed` review-state label (purpose key `failed`, default name `review-failed`).
4. Post a comment explaining what failed, including the review footer so the failure is tied to a specific commit and future runs will retry.
5. **If the failure represents fixable work** rather than a transient infrastructure problem (for example the PR is too large to review in one pass and should be split, or a structural issue blocks review), file it to the board best-effort with `/github-workflow:report-issue` (autonomous, `status-ready`, referencing this PR) so it is picked up automatically — no human approval needed. Skip this for transient failures (auth, network, rate limit) where filing would also fail.
6. Exit immediately. Do not attempt to recover, retry, or continue.

---

## Reference Material

The conditional, low-frequency paths are split into `references/` and loaded only when their step's trigger fires — keeping the common single-PR review path light:

- `references/read-only-mode.md` — the Read-Only Mode step overrides, loaded only when invoked with `--read-only` (the Reviewer agent path).
- `references/duplicate-reconciliation.md` — Step 2b, when the claimed PR shares an issue with another open PR.
- `references/re-review.md` — Step 4b, when a prior review footer exists.
- `references/rework-cascade.md` — Steps 1b and 10b, when a `changes-requested` PR is picked up or the post-review verdict triggers rework.
- `references/auto-merge.md` — Step 11, when the verdict is Approved. It loads `references/conflict-resolution.md` (a reusable merge-conflict procedure) only when the PR is actually conflicting.
- `references/review-workflow.md` — Label reference table, concurrency rules, and the Step 10 label-reconciliation fallback. Read only to look up a label's purpose key, verify the claim-release procedure (Steps 2, 10), or run the fallback when `wf` is unavailable. Do not load it upfront.
- `references/review-config-guide.md` — Interactive config generation only (no `review.config.md` found in an interactive session).

Rationale files (maintainers only — not read at runtime): `docs/rationale/code-review-rationale.md`, `docs/rationale/review-workflow-rationale.md`.

---

## Rules

- Never use `gh pr review --approve`. Always use `gh pr comment`.
- **Do not merge a PR** except the one sanctioned auto-merge in Step 11, and only under the conditions and the CI-gate rules — `--bypass-ci`, `bypass-ci-on-billing-failure`, `bypass-ci-when-no-pipeline` — stated once in `references/auto-merge.md` (off by default). Never merge in read-only mode. That reference has one other sanctioned caller, named in it: the `execute` skill's Phase 10, which merges the PR its own run built and had reviewed, under the same setting and the same conditions. This rule governs this skill; it does not forbid that one.
- **Do not close a PR** except to reconcile duplicates in Step 2b, per `references/duplicate-reconciliation.md` — the one sanctioned close. Never close a PR for any other reason, and never in read-only mode.
- Do not make discretionary refactors or stylistic changes.
- Push fixes for all concrete, objectively wrong problems — both blocking and non-blocking — before approving or merging. Non-blocking cleanups are no longer deferred for budget.
- File any problem you cannot fix in place — blocking, non-blocking, an unresolvable conflict, or a failing check that is not yours to fix — to the board with `/github-workflow:report-issue` (autonomous, `status-ready`, correct type) so it is picked up automatically. No human approval is needed, and no detected problem is ever silently dropped.
- Report merged PRs as `Approved and merged PR #<number>: <title>` followed by the **Changed** and **Added to the board** outline.
- Handle one PR per invocation (rework + re-review counts as one), then exit.
