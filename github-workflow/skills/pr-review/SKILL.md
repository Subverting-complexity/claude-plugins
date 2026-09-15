---
name: pr-review
description: 'Review a pull request (the next one needing review, or a number) or a local change (uncommitted work, a branch, a commit, "is this ready?"). Fixes concrete issues; for a PR posts the review and labels. --read-only evaluates only.'
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

**Pull request or local change.** Review a pull request when a PR number is given, when asked to review PRs, from `execute` or `bulk-execute`, or from a scheduled routine: that is the workflow in this file. For anything else (uncommitted work, a branch with no PR, a commit, named files, "verify this feature", "is this ready?") follow `references/local-review.md` instead and skip everything below; add `references/react-native.md` when the change is React Native or Expo code.

Review one open pull request end to end: find it, claim it, read the code in context, fix what can be fixed, post one structured comment, apply labels, exit. If no PR needs review or anything goes wrong, exit.

## Prerequisites

Run `gh auth status` first. If it fails, stop and tell the user to run `gh auth login`.

**Review configuration.** Look for `./docs/review.config.md`, then `./review.config.md`, and read it fully before starting: labels, non-compliance gates, tech-stack rules and the comment footer all live there, and this workflow is otherwise generic.

- When neither exists and a user is present, follow `references/review-config-guide.md` to create one with them.
- When neither exists in an autonomous session (from `execute`, `bulk-execute` or a scheduled routine), run a minimal review: no custom gates, no tech-stack rules, the standard footer, and each label at its `review-` default. Say in the review comment that defaults were used. An interactive session that goes ahead without a file also warns: "No `review.config.md` found — using default labels. Run `/github-workflow:setup` to configure review labels for this project."

**Label names.** Every label this skill applies or filters on (`reviewing`, `approved`, `changes-requested`, …) is a **purpose key**. Resolve each through the Labels table in `review.config.md`, falling back to its `review-` default; never apply a bare name literally or guess a prefix. `wf review-finish` creates a missing verdict label, guarded and never with `--force`.

**Auto-merge.** `review.config.md` may set Auto-Merge on Approval to `enabled`; it is `disabled` when the section or file is absent. Step 11 checks it and is the only place this skill merges.

**Read-only mode.** When invoked with `--read-only` (`$ARGUMENTS.mode` is `read-only`), read `references/read-only-mode.md` before Step 1 and apply its overrides at every step: no claim, detached checkout, no fixes, nothing filed or closed, no rework, no merge, and the comment and labels handed to a caller that owns the verdict.

---

## Review Workflow

### Step 1 — Find a PR that needs review

**Handle one PR per invocation** (rework plus re-review counts as one). **Never ask the user which PR to review**: "review PRs" means find the next one and review it, not all of them and not a list to choose from.

**A pinned PR.** When the invocation names a PR (`$ARGUMENTS.pr`, or a number a user or calling skill passed), review that one and do not run the picker, which would choose a different PR by priority. Claim it (Step 2) and check out its branch, then continue at Step 1b if it carries `changes-requested`, otherwise at Step 2b. If the claim is lost, report that and exit rather than moving to a different PR.

**Otherwise, run the picker.** It selects **and claims** the next PR carrying `needs-re-review`, `changes-requested` or `needs-review` (in that tier order, lowest number first) and checks out its branch:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-next --checkout
```

- **`ok`** — the JSON gives `number`, `title`, `url`, `branch`, `labels`, `claimed`, `claim_ref` and `prior_state`. The `reviewing` marker is applied and the claim is held. Do not re-derive the choice, and surface any `side_effects`. A `prior_state` of `changes-requested` goes to Step 1b; anything else to Step 2b.
- **`all-blocked`** — every reviewable PR is claimed by another review agent. Report that and exit; a blind re-scan would surface nothing new.
- When the picker reports **`no-candidates`** or **`error`**, or Python is missing, follow `references/picker-fallback.md`.

### Step 1b — Rework cascade (changes-requested PRs only)

When the PR was picked from the `changes-requested` tier, load `references/rework-cascade.md` and follow its **Step 1b**. It returns you to Step 2b.

### Step 2 — Claim the PR

Claiming is the first mutating action of a review, before checkout, context or evaluation, because several review agents may run at once under one GitHub identity. The picker has already claimed; a pinned PR or the fallback claims here:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim --pr <number>
```

- **Exit 0** — you hold `refs/claims/pr-<number>`, the actual lock, and the `reviewing` label is applied as the visible marker.
- **Exit 27** (`lost`) — another agent owns this PR. Change nothing. In the fallback, claim the next candidate in priority order, and if every one is lost, report that and exit. On a pinned PR, report and exit. Never retry a lost claim.
- **Exit 20** — a broken environment, usually no write access to `refs/claims/*`. Report it and stop; never fall back to a bare label as a claim.

Label semantics and concurrency rules are in `references/review-workflow.md`, read only if needed.

### Step 2b — Reconcile duplicate PRs for the same issue

If the claimed PR closes at least one issue, load `references/duplicate-reconciliation.md` and follow it. It checks for another open PR resolving the same issue, keeps the winner, closes the losers it can safely claim, and tells you whether to continue or exit. A PR that closes no issue goes straight to Step 3.

### Step 3 — Check out the PR branch

Run `gh pr checkout <number>`, a no-op when the picker already checked it out. If checkout fails: release the claim (`wf claim-release --pr <number>`), remove the `reviewing` label, apply the `failed` review-state label, post a brief failure comment with the footer, and exit.

Record `git rev-parse HEAD` for the review footer. Then run `git fetch origin <baseRef>` and diff against `origin/<baseRef>`, never the local base: in a worktree the local copy is often far behind, and the diff would report files the PR never touched.

### Step 4 — Gather context

If any of these fails, treat it as a review failure (Error Handling below).

- **PR metadata:** `gh pr view <number> --repo <org>/<repo> --json title,body,baseRefName,headRefName,files,additions,deletions`
- **Linked issue:** parse `Closes #N` or `Fixes #N` from the body, then `gh issue view <N> --repo <org>/<repo> --json title,body,milestone`. The issue is the source of truth for what the PR should do. No linked issue is a non-compliance failure where the config makes it a gate; continue the review either way.
- **Changes:** `git diff origin/<baseRef>...HEAD --name-status`, and the full `git diff origin/<baseRef>...HEAD` for reference. Never review from the diff alone.
- **Cross-check** that file list against GitHub's `files`. If the local diff shows more, re-fetch the base and re-diff; if it still disagrees, review exactly the paths GitHub lists.

### Step 4b — Assess re-review significance (re-reviews only)

If a prior review comment with a footer exists, load `references/re-review.md` and follow it. It may post an abbreviated approval and route to Step 11, or send you to Step 5 for a full re-review. First-time reviews go straight to Step 5.

---

### Step 5 — Read the code in context

For every changed file, read the **full file**, the files it imports and the files that import it, at least two levels deep. For every modified function or method, find every call site and check the change is safe for each. Run any cross-boundary checks `review.config.md` defines (DTO or interface parity, API schema alignment), and read the existing tests for the changed modules.

### Step 6 — Evaluate the PR

**Ecosystem tools.** If `.claude/ecosystem.md` exists, use the tools it lists before tracing by hand: **Graphify** (`graphify . --update`, then `graphify query` or `graphify path` to trace how changed functions connect), **Fallow** for TS/JS (unused exports and duplication the diff adds), and `npx ecc-agentshield scan` when the PR touches Claude Code config (CLAUDE.md, `.claude/`, hooks, skills, MCP config). If the file is absent, review by hand and never nag; a listed tool missing from `PATH` is one line of note.

Work through each area with the full codebase context:

- **Hard non-compliance gates** — check every gate in `review.config.md`. Any failure forces Changes Requested and is named under "Non-compliance".
- **Story alignment** — does the PR implement everything the issue describes, and nothing it does not? Are the acceptance criteria met?
- **Logic and correctness** — trace every path through the actual code, substituting concrete values into calculations. Check boundaries (zero, one, max, null, empty, negative), concurrency (races, double reads, TOCTOU) and error paths.
- **Type safety and nullability** — could a null reach a dereference? Apply the config's type-safety rules.
- **Security** — injection (SQL, XSS, command, path traversal), input validation at system boundaries, no sensitive data in logs, and the config's project-specific checks.
- **Architectural consistency** — the config's architecture rules, established codebase patterns, one responsibility per file.
- **Tests** — the config's test expectations. Every new path exercised, boundaries and error paths tested, a regression test for a bug fix. Non-trivial changed code with no tests is a hard failure where the config says so.
- **Regressions** — are callers and consumers from Step 5 broken or subtly changed?
- **Minimality** — is every changed line needed? Flag unrelated refactors, formatting or comment edits.

### Step 7 — Fix issues (blocking first, then non-blocking)

Fix concrete, objectively wrong problems directly on the PR branch, and fix **both** tiers before approving:

- **Blocking** — hard gate failures; security problems; logic and correctness errors, missing null checks, broken or incorrect tests; missing coverage on non-trivial new paths; regressions to callers or consumers.
- **Non-blocking** — formatting and missing trailing newlines; dead code or misplaced code; null-forgiving operators and unnecessary casts; obvious comment or naming fixes.

Neither tier includes a stylistic preference where several approaches are valid, or anything needing product, design or architectural judgment: raise those in the comment, or file them. Commit each fix or small logical group with a clear message, `git push`, and update the recorded SHA to the new `HEAD`.

**File what you did not fix.** For every problem detected but not fixed on the branch, run `/github-workflow:report-issue` autonomously with its actual type (bug, security, architecture or tech debt), naming the source PR (`Detected during review of #<pr-number>`) and the `file:line`. Read the stage it reports back rather than assuming `Backlog`. Record each issue's number, title and type for Step 9 and the final report. Filing a non-blocking issue does not force Changes Requested.

### Step 8 — Determine the verdict

Judge the PR as it stands after Step 7: fixed problems and filed non-blocking ones do not count against it.

- **Approved** — zero hard non-compliance failures and zero remaining blocking problems. This is the verdict whenever Step 7 resolved every blocking finding, even with non-blocking items filed.
- **Changes Requested** — any hard non-compliance failure, or a blocking problem that could not be fixed and needs human judgment (also filed in Step 7).
- **Needs Discussion** — no hard failures, but an architectural question or ambiguity needs a person before merge.

### Step 9 — Post the review

Write the comment to `_shared/wording-standard.md` and shape it, like everything you report back, to `skills/user-facing-communication/SKILL.md`: the verdict and current state first, anything outstanding where it cannot be missed, every issue and pull request named as well as numbered, no investigation history. The author may lack your context, so each finding states the problem and the suggested fix in complete sentences, with `file:line` references and identifiers in backticks. Post one comment with `gh pr comment <number> --repo <org>/<repo>`:

```
## Review by Claude

**Verdict: [Approved | Changes Requested | Needs Discussion]**

[1-2 sentence summary of what the PR does and whether it does it correctly.]

### Non-compliance
[Each hard gate failure with specifics, or "None."]

### Story alignment
[Does the PR match the issue? Anything missing or out of scope?]

### Correctness
[Findings from logic, security, nullability and architecture, with file:line.]

### Tests
[What is covered, what is missing.]

### Regressions
[Any risk to existing functionality.]

### Minimality
[Any unnecessary or bundled unrelated change.]

### Fixes applied
[Commits pushed, or "None".]

### Issues remaining (filed to backlog)
[Numbered, each naming the issue filed in Step 7 by type and number, e.g. "bug #45: null deref in `parse()` (`src/parse.ts:12`)". If none, "No issues remaining."]

<footer from review.config.md>
```

The footer's `Reviewed at <SHA>` line carries the SHA recorded at Step 3, or the updated one from Step 7.

### Step 10 — Reconcile labels

1. Release the claim: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --pr <number>` (idempotent, always exit 0).
2. Set the review-state labels to exactly the verdict:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr <number> --verdict <approved|changes-requested|needs-discussion>
   ```

   Add `--fixes-applied` when Step 7 pushed fixes, which keeps that sticky label. On `verified: false`, report the failure but do not block. If `wf` errors or Python is absent, follow **Label reconciliation fallback (Step 10)** in `references/review-workflow.md`.
3. For each custom label `review.config.md` defines, apply it when its "When to apply" criteria match, and remove it when a review applied it and they no longer do.
4. Check out the branch you were on before the review.

Then, by verdict:

- **Approved** → Step 11.
- **Changes Requested** → Step 10b when every remaining issue is concrete and fixable; otherwise report and exit.
- **Needs Discussion** → report and exit.

### Step 10b — Post-verdict rework cascade (Changes Requested only)

When every remaining issue is a concrete, fixable problem, load `references/rework-cascade.md` and follow its **Step 10b**; it returns you to Step 4b. If any item needs human judgment, report and exit, leaving `changes-requested`.

### Step 11 — Auto-merge on approval (if enabled)

Runs only when the verdict is **Approved**. Check before reading any merge mechanics: the session is not read-only, and `review.config.md`'s Auto-Merge on Approval is `enabled` (no file or no section means `disabled`: never merge). If either fails, the review is complete at Step 10.

Only when both hold, load `references/auto-merge.md` and follow it, passing `$ARGUMENTS.bypass-ci` through when set. It handles the CI gate settings and drives the PR to merged, then reports in the **Final report format** below.

#### Final report format

Lead with `Approved and merged PR #<number>: <title>`, or the queued line from auto-merge step 5, when Step 11 merged or queued the PR. Otherwise lead with `Reviewed PR #<number> <title> — <verdict>`. Always name a PR by number and title together. Then:

```
Changed:
- <each fix pushed in Step 7 or 11, one line each — or "Nothing; the PR was already correct.">

Added to the backlog:
- <each issue filed, by actual type and number — e.g. "bug #45: null deref in parse()" — or "Nothing.">
```

Name every added item by its actual issue type (bug, security, architecture, tech debt, feature, user story or epic), never just "issue". Add an **Outstanding** or **Assumptions** section under the outline when something is still blocked or assumed. Add nothing else: no reasoning behind each fix, no file list, no note that the review was thorough.

---

## Error Handling

If anything goes wrong (a `gh` command fails, checkout fails, a changed file cannot be read, the PR has no diff, or it is too large to review thoroughly):

1. Release the claim: `wf claim-release --pr <number>`.
2. Remove the `reviewing` label and apply the `failed` review-state label.
3. Post a comment explaining what failed, with the review footer, so the failure is tied to a commit and a later run retries.
4. If the failure is fixable work rather than a transient problem (the PR should be split, or a structural issue blocks review), file it with `/github-workflow:report-issue`, autonomously and referencing this PR. Skip this for auth, network or rate-limit failures, where filing would fail too.
5. Exit. Do not recover, retry or continue.

---

## Rules

- Never use `gh pr review --approve`. Always use `gh pr comment`.
- **Do not merge a PR** except through Step 11, off by default and never in read-only mode. `execute` and `bulk-execute` Phase 10 merge their own PRs under the same setting; this rule does not forbid that.
- **Do not close a PR** except to reconcile duplicates in Step 2b, never in read-only mode.
- Make no discretionary refactors or stylistic changes.
- No detected problem is silently dropped: fix it on the branch or file it, with no human approval needed.
