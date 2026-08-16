# Step 11 — Auto-merge on approval (if enabled)

Read this when the SKILL's **Step 11** trigger fires: the verdict is
**Approved** and Step 10 has sent you here. It is the heaviest, most
conditional path in the review and almost never runs (auto-merge is
off by default), so it lives outside `SKILL.md`.

Run this step **only** when all of the following hold. If any is false,
skip it and exit normally:

- The verdict is **Approved** — including the abbreviated re-review
  approvals in Step 4b, which route here before exiting.
- `review.config.md`'s **Auto-Merge on Approval** setting is `enabled`.
  If there is no `review.config.md`, or the section is absent, the
  setting is `disabled` — **never merge**. This holds for every caller,
  with no exceptions; see **Second sanctioned caller** below.
- The session is **not** in read-only mode.

Also read **`require-ci-before-merge`** from the same Auto-Merge on
Approval section. Absent ⇒ `false`. It takes three values:

- **`false`** (default) — no green-CI requirement: an unprotected branch
  merges immediately when checks exist, whatever their state. A PR with
  **no checks at all** is handled by the no-checks guard in step 3
  (CI status unknown — explicit confirmation required).
- **`true`** — the skill must see a **green CI gate** before it merges: a
  PR with no checks at all, or with a failing check it cannot fix, is
  **paused**, not merged. An absolute gate, even on a repo with no
  pipeline — the one thing that can satisfy it without green checks is
  `bypass-ci-on-billing-failure` below, and only against the evidence
  step 3a demands.
- **`if-present`** — gate on CI **only when CI exists**: a PR whose head
  SHA has checks must see them green (a red check it cannot fix pauses).
  A PR with **no checks at all** is handled by the no-checks guard in
  step 3 (CI status unknown — explicit confirmation required).

**Scope of the CI gate.** Every CI decision in this file reads the checks
GitHub reports for the PR's head SHA (`gh pr checks`) — in practice
GitHub Actions, plus any external CI that posts its status back to
GitHub. A pipeline that runs entirely outside GitHub (Buildkite,
CircleCI, Jenkins, …) without reporting to GitHub is **invisible** to
this gate. That is why a PR reporting **no checks at all** is treated as
CI status **UNKNOWN**, never as passing — see the no-checks guard in
step 3.

The exact branches are in step 3 below.

**`--bypass-ci` overrides all three.** When the skill is invoked with
`--bypass-ci`, the CI gate is treated as satisfied regardless of
`require-ci-before-merge` — red, pending, or absent checks no longer block
or pause the merge. It is a deliberate per-invocation operator override for
when CI cannot run for reasons outside the PR (most commonly GitHub Actions
billing). It never bypasses a merge **conflict** (step 2 still runs). See the
override note at the top of step 3.

Also read **`bypass-ci-on-billing-failure`** from the same Auto-Merge on
Approval section. Absent ⇒ `false`. When `true`, it is a **persistent,
billing-scoped** form of `--bypass-ci`: when the only thing blocking the merge
is that GitHub Actions **cannot run for a billing or account reason** (out of
minutes, spending limit hit, payment failed), the CI gate is treated as
satisfied. It covers both symptoms — a pipeline that ran and failed, and the
commoner one where no run is created at all and the rollup is simply empty.
Unlike `--bypass-ci` it stays narrow: a genuine red check is still fixed or
filed, and an empty rollup is bypassed only against evidence. Handled in
**step 3a**, which overrides the no-checks guard for every
`require-ci-before-merge` value.

This is opt-in and **off by default**. Merging a PR is otherwise
forbidden (see Rules); this is the one sanctioned merge, and only under
an explicit `enabled` setting. The review comment from Step 9 must
already be posted before you merge — never merge before the verdict is
on the PR.

**Second sanctioned caller.** The `execute` skill's Phase 10 drives this
file directly, to merge the PR its own run built and had reviewed. It is
subject to the **identical** conditions — the same `Auto-Merge on Approval`
setting read from the same file, the same `require-ci-before-merge`
handling, the same everything below. That is the point: one switch decides
whether a repository gets unattended merges, wherever the merge is driven
from, so an operator never has to work out which command is about to merge
in order to know what the setting means.

What differs is only naming. That caller records its own head SHA and posts
its own consolidated review comment, so where this file says "the SHA you
reviewed" or "the review comment from Step 9", its equivalents are the ones
its own Phase 8 or Phase 9 produced. It carries that list of substitutions
itself, and nothing here needs to read them, so the dependency runs one way
only.

When all conditions hold, drive the PR to a merged state. Conflicts and
red CI are **blockers to clear, not reasons to give up** — fix them on the
branch (the same auto-fix discipline as Step 7: fix concrete, objectively
correct problems; never guess at changes that need product or design
judgment), then merge. You are already on the PR branch from Step 3.
Whenever a conflict or a failing check is genuinely **not yours to fix**,
do not just pause for a human: file it to the board with
`/github-workflow:report-issue` (autonomous, `status-ready`, correct
type, referencing this PR) so the fix is picked up automatically, then
leave `approved` and exit. The fallbacks below say where.

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
   `CONFLICTING`, do not bail: load `references/conflict-resolution.md`
   and follow it, with the PR branch (already checked out) as the working
   branch and `<baseRef>` as the incoming branch. On success, update your
   recorded SHA to the new `HEAD` and append a line to the review comment
   noting the conflict resolution.

   If the reference **escalates** (it aborted the merge because the
   resolution genuinely needs human judgment), file the rebase to the
   board with `/github-workflow:report-issue` (autonomous, `status-ready`,
   referencing this PR and the conflicting files) so it is picked up
   automatically — no human approval needed. Post a one-line comment
   naming the filed issue, leave the `approved` verdict, and exit. Do not
   guess at the merge.

3. **Fix a failing pipeline if there is one.**

   **CI bypass override.** If the skill was invoked with `--bypass-ci`, skip
   this entire step: do **not** read the check rollup, fix a failing check
   for the gate's sake, or pause on red/absent CI. Treat the CI gate as
   satisfied and go to **step 4's immediate path** — and because CI is being
   overridden (a red or never-completing pipeline must not strand the merge
   behind `--auto`), prefer the immediate `--squash --delete-branch` merge,
   falling back to `--admin` if branch protection requires an approving
   review. Do this even if you pushed a conflict resolution in step 2. This
   override is for when CI cannot run for reasons outside the PR (e.g. Actions
   billing); it does **not** bypass the step-2 conflict resolution, only the
   CI gate. Skip the rest of this step.

   **3a — CI that cannot run for billing reasons (config bypass).** If
   `--bypass-ci` was **not** passed but `review.config.md`'s
   `bypass-ci-on-billing-failure` is `true`, work out whether GitHub Actions
   is *unable to run* before treating anything here as a real failure. Read
   the full rollup first — which of the two branches below applies depends on
   whether it is empty:

   ```bash
   gh pr checks <number> --repo <org>/<repo>
   ```

   **3a-i — checks exist and some are failing.** Inspect each non-green
   check's run:

   ```bash
   # for each failing / never-started check, find its run id, then:
   gh run view <run-id> --repo <org>/<repo> --json conclusion --jq .conclusion
   gh run view <run-id> --repo <org>/<repo> 2>&1 \
     | grep -iE 'billing|spending limit|recent account payments|payment(s)? (have )?failed|exceeded.*(minutes|spending)'
   ```

   A check is **billing-induced** when its run never executed for an account
   reason: a `startup_failure` conclusion (or a run that was created but never
   ran) **together with** a billing/account/spending/payment signal in the run
   detail or annotations. A `startup_failure` with no such signal (e.g.
   malformed workflow YAML) is **not** billing — do not bypass it.

   Then decide:

   - There is at least one failing check, **every** failing check is
     billing-induced, and **no** genuine red check remains (no real
     test/build/lint failure) → the only thing blocking the merge is billing.
     Treat the CI gate as satisfied and go to **step 4's immediate path** —
     prefer the immediate `--squash --delete-branch` merge, falling back to
     `--admin` if branch protection requires an approving review (a red or
     never-completing pipeline must not strand the merge behind `--auto`).
     Append a line to the review comment: "Merged despite red CI: GitHub
     Actions billing/account failure, bypassed per
     `bypass-ci-on-billing-failure`." Skip the rest of this step. This never
     bypasses a merge **conflict** — step 2 already ran.
   - **Any** failing check is a genuine code failure (not billing) → do **not**
     bypass. Fall through to the normal rollup handling below; the genuine
     failure is fixed or filed, and the PR does not merge over it. (The billing
     check among them is "not yours to fix" and is handled as such there.)

   **3a-ii — the rollup is empty.** This is the ordinary symptom of exhausted
   Actions billing: no runs are created, so there is no failing check to
   inspect and the PR looks identical to one in a repo with no CI. That
   ambiguity is why an empty rollup is never bypassed on assumption — only
   when all three of these hold:

   1. **Workflows exist that should have run.** At least one is active:
      ```bash
      gh api "repos/<org>/<repo>/actions/workflows" \
        --jq '[.workflows[] | select(.state == "active")] | length'
      ```
      Zero → the project has no GitHub-hosted CI and nothing is being
      bypassed. Fall through to the no-checks guard.
   2. **No run was created for this head SHA, and it is not merely slow.**
      Give a slow start time to appear before concluding it never will:
      ```bash
      sleep 60
      gh api "repos/<org>/<repo>/actions/runs?head_sha=<sha>" --jq '.total_count'
      ```
      Non-zero → runs do exist after all. Re-read the rollup and handle them
      through the normal path below.
   3. **The change was verified locally.** Remote evidence is what is missing,
      so local evidence stands in its place — merging with neither is how a
      broken change lands unseen. Confirm the quality gate from
      `ClaudeProject.md` passed on this head SHA: for the `execute` caller an
      absent `.claude/gate-failed.flag` is that proof, and a review session
      that has not run the gate runs it now and sees it green. A red gate, or
      one that cannot run here → do **not** bypass; pause per the no-checks
      guard.

   All three → treat the CI gate as satisfied and go to **step 4's immediate
   path**, again preferring `--squash --delete-branch` over `--auto`, which
   would wait forever for checks that are never coming. Append to the review
   comment: "Merged despite absent CI: no GitHub Actions run was created for
   this SHA though active workflows are configured; bypassed per
   `bypass-ci-on-billing-failure`, with the local quality gate green."

   Anything else (no checks failing, or the three conditions not met) → fall
   through to the normal rollup handling below.

   Otherwise, read the required-check rollup:
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
     judgment): file the failing check to the board with
     `/github-workflow:report-issue` (autonomous, `status-ready`,
     referencing this PR and naming the check) so the fix is picked up
     automatically — no human approval needed. Post a one-line comment
     naming the filed issue, leave `approved`, and exit. Never force a
     merge over a genuinely red required check.
   - Required checks **pending** (including right after you pushed a fix)
     → enqueue auto-merge: step 4 (`--auto`).
   - Required checks **passing** → merge now (step 4, immediate path),
     provided you pushed nothing in steps 2–3 (a push leaves checks
     pending → enqueue `--auto` instead).
   - **No required checks reported** → the branch is unprotected. Read
     the full check rollup (not just required ones):
     ```bash
     gh pr checks <number> --repo <org>/<repo>
     ```
     - **No checks at all** on the head SHA → the **no-checks guard**
       applies, for every `require-ci-before-merge` value. CI status is
       **UNKNOWN**, not passing — this gate sees only checks reported to
       GitHub, and the project may run its CI elsewhere (Buildkite,
       CircleCI, Jenkins, …) where the gate cannot see it. Never treat
       an empty rollup as green.

       **Step 3a-ii ran before this guard, for every value below.** If
       `bypass-ci-on-billing-failure` is `true` and its conditions held, the
       merge already happened and you never reach here; what follows is the
       path for an empty rollup a billing failure does not explain:
       - **`true`** → **pause** (strictest): post a one-line
         comment "auto-merge paused: require-ci-before-merge is set but
         no CI checks are configured", leave `approved`, and exit. Never
         merge.
       - **`false` or `if-present`** → merge only with **explicit user
         confirmation**. In an interactive session, ask: "PR #<number>
         reports no CI checks at all — CI status is unknown (the project
         may use a CI system that does not report to GitHub). Merge
         anyway?" Merge (step 4, immediate path) only on an explicit yes.
         In an autonomous session (no user to ask), do **not** merge:
         post a one-line comment ("auto-merge paused: no CI checks
         reported — CI status unknown; merge manually or re-run with
         `--bypass-ci`"), leave `approved`, and exit. Only the explicit
         `--bypass-ci` override (top of this step) treats absent checks
         as satisfied.
     - Checks exist and `require-ci-before-merge` is **`false`**
       (default) → no green-CI requirement: if you pushed nothing in
       steps 2–3, merge now (step 4, immediate path) regardless of the
       checks' state.
     - Checks exist and it is **`true` or `if-present`** → gate on them:
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
   - `state` `MERGED` → report in the **final report format** (in
     `SKILL.md`, shared with Step 10), leading with `Approved and merged
     PR #<number>: <title>`.
   - `autoMergeRequest` is non-null (auto-merge enqueued) → report in the
     same format, leading with `Approved PR #<number>: <title> —
     auto-merge queued, will land when checks / branch protection clear`.
   - You took the **Enqueue** path but `autoMergeRequest` is null and
     `state` is still `OPEN` → the `--auto` call did not take (repo
     auto-merge disabled). Pause per step 4: post the one-line comment,
     leave `approved`, and exit. Do not claim success.
   - Neither merged nor queued → report exactly why the merge did not
     complete. Do not claim success.

6. **Settle the linked issues — close them and move the board to Done.**
   Run this **only when Step 5 confirmed `state` is `MERGED`** (the immediate
   path). On the **queued** path (`autoMergeRequest` non-null, still `OPEN`),
   the PR has not merged yet — skip this step; `wf post-merge` would correctly
   refuse with `not-merged`. The issue is settled when the queued merge lands
   (by GitHub's auto-close, and a later board reconcile or its built-in
   automation), not in this run.

   Do **not** assume the merge closed the issue. GitHub auto-closes a linked
   issue only when the PR carried a recognised closing keyword **and** merged
   into the default branch — a chained-story PR (non-default base) or an
   unparsed reference leaves the issue open, and even a clean auto-close never
   moves the board item out of In Review. Make both deterministic with one
   call (the branch was already deleted by the merge):

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" post-merge --pr <number>
   ```

   It reads the PR's own `closingIssuesReferences`, force-closes any of those
   issues still open, and moves every one of them to the **Done** board column
   (best-effort — a no-op when no board is configured). Report each entry in
   the returned `settled` array (`closed_now`, `board_moved_done`). If the PR
   body used a closing keyword GitHub did not parse, pass the issue explicitly:
   `... post-merge --pr <number> --issue <N>`.

   **Fallback** when `wf` cannot run (Python missing, or it returns `error`):
   read the linked issues yourself and settle them by hand —
   ```bash
   gh pr view <number> --repo <org>/<repo> --json closingIssuesReferences \
     --jq '.closingIssuesReferences[].number'
   # for each still-open issue:
   gh issue close <N> --repo <org>/<repo> --comment "Closing — resolved by merged PR #<number>."
   # then move its board item to col-done per templates/board-resolution.md Step 5.
   ```
