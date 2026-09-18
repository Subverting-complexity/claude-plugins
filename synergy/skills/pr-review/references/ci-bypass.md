# Step 11 — CI bypass (auto-merge step 3)

Read this only if the skill was invoked with `--bypass-ci`, or `review.config.md` sets `bypass-ci-on-billing-failure` or `bypass-ci-when-no-pipeline` to `true`. It is read at step 3 of `auto-merge.md`, and every step, the no-checks guard and "the normal rollup handling below" it names are in that file: when no bypass here applies, return to step 3 there and read the required-check rollup.

## The three overrides

**`--bypass-ci` overrides all three.** When the skill is invoked with `--bypass-ci`, the CI gate is treated as satisfied regardless of `require-ci-before-merge` — red, pending, or absent checks no longer block or pause the merge. It is a deliberate per-invocation operator override for when CI cannot run for reasons outside the PR (most commonly GitHub Actions billing). It never bypasses a merge **conflict** (step 2 still runs). See the override note at the top of step 3.

Also read **`bypass-ci-on-billing-failure`** from the same Auto-Merge on Approval section. Absent ⇒ `false`. When `true`, it is a **persistent, billing-scoped** form of `--bypass-ci`: when the only thing blocking the merge is that GitHub Actions **cannot run for a billing or account reason** (out of minutes, spending limit hit, payment failed), the CI gate is treated as satisfied. It covers both symptoms — a pipeline that ran and failed, and the commoner one where no run is created at all and the rollup is simply empty. Unlike `--bypass-ci` it stays narrow: a genuine red check is still fixed or filed, and an empty rollup is bypassed only against evidence. Handled in **step 3a**, which overrides the no-checks guard for every `require-ci-before-merge` value.

Also read **`bypass-ci-when-no-pipeline`** from the same Auto-Merge on Approval section. Absent ⇒ `false`. When `true`, it is a **persistent, absent-pipeline-scoped** form of `--bypass-ci`, for a project whose CI is permanently invisible to GitHub — no pipeline at all, or one on a system that never posts a status back (Buildkite, Jenkins, CircleCI). There an empty rollup is not a transient unknown to wait out but the steady state of every PR, so without this setting each autonomous run stops at the no-checks guard and only a human, or `--bypass-ci` re-passed every time, can land the work. It is **narrower** than `--bypass-ci`, not broader: it applies only to a rollup with **no checks in it at all**, and only against evidence. Handled in **step 3b**, which like 3a overrides the no-checks guard for every `require-ci-before-merge` value. The two config bypasses are mutually exclusive by construction: 3a-ii requires at least one active workflow, 3b requires zero.

## Step 3 — the bypass checks

   **CI bypass override.** If the skill was invoked with `--bypass-ci`, skip this entire step: do **not** read the check rollup, fix a failing check for the gate's sake, or pause on red/absent CI. Treat the CI gate as satisfied and go to **step 4's immediate path** — and because CI is being overridden (a red or never-completing pipeline must not strand the merge behind `--auto`), prefer the immediate `--squash --delete-branch` merge, falling back to `--admin` if branch protection requires an approving review. Do this even if you pushed a conflict resolution in step 2. This override is for when CI cannot run for reasons outside the PR (e.g. Actions billing); it does **not** bypass the step-2 conflict resolution, only the CI gate. Skip the rest of this step.

   **3a — CI that cannot run for billing reasons (config bypass).** If `--bypass-ci` was **not** passed but `review.config.md`'s `bypass-ci-on-billing-failure` is `true`, work out whether GitHub Actions is *unable to run* before treating anything here as a real failure. Read the full rollup first, using the filtered form from `auto-merge.md`'s scope note (App-posted checks like an automatic reviewer are never CI and never counted here) — which of the two branches below applies depends on whether it is empty:

   ```bash
   gh pr checks <number> --repo <org>/<repo> --json name,bucket,state,link,workflow \
     --jq '[.[] | select(.workflow != null and .workflow != "")]'
   ```

   **3a-i — checks exist and some are failing.** Inspect each non-green check's run:

   ```bash
   # for each failing / never-started check, find its run id, then:
   gh run view <run-id> --repo <org>/<repo> --json conclusion --jq .conclusion
   gh run view <run-id> --repo <org>/<repo> 2>&1 \
     | grep -iE 'billing|spending limit|recent account payments|payment(s)? (have )?failed|exceeded.*(minutes|spending)'
   ```

   A check is **billing-induced** when its run never executed for an account reason: a `startup_failure` conclusion (or a run that was created but never ran) **together with** a billing/account/spending/payment signal in the run detail or annotations. A `startup_failure` with no such signal (e.g. malformed workflow YAML) is **not** billing — do not bypass it.

   Then decide:

   - There is at least one failing check, **every** failing check is billing-induced, and **no** genuine red check remains (no real test/build/lint failure) → the only thing blocking the merge is billing. Treat the CI gate as satisfied and go to **step 4's immediate path** — prefer the immediate `--squash --delete-branch` merge, falling back to `--admin` if branch protection requires an approving review (a red or never-completing pipeline must not strand the merge behind `--auto`). Append a line to the review comment: "Merged despite red CI: GitHub Actions billing/account failure, bypassed per `bypass-ci-on-billing-failure`." Skip the rest of this step. This never bypasses a merge **conflict** — step 2 already ran.
   - **Any** failing check is a genuine code failure (not billing) → do **not** bypass. Fall through to the normal rollup handling below; the genuine failure is fixed or filed, and the PR does not merge over it. (The billing check among them is "not yours to fix" and is handled as such there.)

   **3a-ii — the rollup is empty.** This is the ordinary symptom of exhausted Actions billing: no runs are created, so there is no failing check to inspect and the PR looks identical to one in a repo with no CI. That ambiguity is why an empty rollup is never bypassed on assumption — only when all three of these hold:

   1. **Workflows exist that should have run.** At least one repo-authored one is active — filter to `.github/workflows/*`, because GitHub also lists App-based automations here (an automatic PR reviewer, for example) under a synthetic `dynamic/agents/...` path, and those never produce a run to wait for:
      ```bash
      gh api "repos/<org>/<repo>/actions/workflows" \
        --jq '[.workflows[] | select(.state == "active" and (.path | startswith(".github/workflows/")))] | length'
      ```
      Zero → the project has no GitHub-hosted CI and nothing is being
      bypassed. Fall through to the no-checks guard.
   2. **No run was created for this head SHA, and it is not merely slow.** Give a slow start time to appear before concluding it never will:
      ```bash
      sleep 60
      gh api "repos/<org>/<repo>/actions/runs?head_sha=<sha>" --jq '.total_count'
      ```
      Non-zero → runs do exist after all. Re-read the rollup and handle them
      through the normal path below.
   3. **The change was verified locally.** Remote evidence is what is missing, so local evidence stands in its place — merging with neither is how a broken change lands unseen. Confirm the quality gate from `ClaudeProject.md` passed on this head SHA: for the `execute` caller an absent `.claude/gate-failed.flag` is that proof, and a review session that has not run the gate runs it now and sees it green. A red gate, or one that cannot run here → do **not** bypass; pause per the no-checks guard.

   All three → treat the CI gate as satisfied and go to **step 4's immediate path**, again preferring `--squash --delete-branch` over `--auto`, which would wait forever for checks that are never coming. Append to the review comment: "Merged despite absent CI: no GitHub Actions run was created for this SHA though active workflows are configured; bypassed per `bypass-ci-on-billing-failure`, with the local quality gate green."

   Anything else (no checks failing, or the three conditions not met) → fall through to the normal rollup handling below.

   **3b — a project with no GitHub-visible pipeline (config bypass).** If neither path above merged and `review.config.md`'s `bypass-ci-when-no-pipeline` is `true`, an empty rollup may be this project's permanent condition rather than an unknown. Bypass it only when **all three** hold:

   1. **The rollup is genuinely empty** — no checks at all on the head SHA, using the filtered form from `auto-merge.md`'s scope note (if step 3a did not already read it). Any check present, in any state → the setting does not apply; fall through. A red check is still red.
   2. **The repo has no active workflows** — step 3a-ii's call, read for the opposite outcome:
      ```bash
      gh api "repos/<org>/<repo>/actions/workflows" \
        --jq '[.workflows[] | select(.state == "active" and (.path | startswith(".github/workflows/")))] | length'
      ```
      Zero → no GitHub-hosted pipeline exists, so no run was ever coming.
      Non-zero → workflows exist and should have produced a run; that is
      3a-ii's territory or a real problem. Fall through.
   3. **The change was verified locally** — 3a-ii's third condition, for a stronger reason: no remote proof exists for this project at all, so local proof is the only thing between an approval and a merge. An absent `.claude/gate-failed.flag` is that proof for the `execute` caller; a review session runs the `ClaudeProject.md` gate now and sees it green. Red, or unrunnable here → do **not** bypass; pause per the no-checks guard.

   All three → treat the CI gate as satisfied and go to **step 4's immediate path** (`--squash --delete-branch`, never `--auto`, which would wait for checks that are never coming). Append to the review comment: "Merged with no CI checks: this project has no GitHub-visible pipeline; bypassed per `bypass-ci-when-no-pipeline`, with the local quality gate green." Never bypasses a merge **conflict** — step 2 already ran.
