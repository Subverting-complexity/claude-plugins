# Step 11 — Auto-merge on approval

Read this only after the caller has confirmed a merge is allowed. For pr-review that is Step 11's check: the verdict is **Approved** (including a Step 4b abbreviated approval), `Auto-Merge on Approval` is `enabled`, and the session is not read-only. For `execute` and `bulk-execute` it is Phase 10's stop conditions, which name the same setting; they drive steps 1 to 6 below under identical rules and carry their own naming substitutions. The conditions are not restated here.

Read **`require-ci-before-merge`** from the Auto-Merge on Approval section of `review.config.md`. Absent ⇒ `false`. It takes three values:

- **`false`** (default) — no green-CI requirement: an unprotected branch merges immediately when checks exist, whatever their state. A PR with **no checks at all** is handled by the no-checks guard in step 3 (CI status unknown — explicit confirmation required).
- **`true`** — the skill must see a **green CI gate** before it merges: a PR with no checks at all, or with a failing check it cannot fix, is **paused**, not merged. An absolute gate, even on a repo with no pipeline — the only things that can satisfy it without green checks are `bypass-ci-on-billing-failure` and `bypass-ci-when-no-pipeline` below, and only against the evidence steps 3a and 3b of `references/ci-bypass.md` demand.
- **`if-present`** — gate on CI **only when CI exists**: a PR whose head SHA has checks must see them green (a red check it cannot fix pauses). A PR with **no checks at all** is handled by the no-checks guard in step 3 (CI status unknown — explicit confirmation required).

**Scope of the CI gate.** Every CI decision in this file reads the checks GitHub reports for the PR's head SHA — in practice GitHub Actions, plus any external CI that posts its status back to GitHub. A pipeline that runs entirely outside GitHub (Buildkite, CircleCI, Jenkins, …) without reporting to GitHub is **invisible** to this gate. That is why a PR reporting **no checks at all** is treated as CI status **UNKNOWN**, never as passing — see the no-checks guard in step 3.

**Reading the rollup — CI checks only, not every check GitHub shows.** GitHub also posts checks from things that are not a pipeline validating the diff: an automatic reviewer app (e.g. Copilot's `copilot-pull-request-reviewer`), a required-review bot, or any other App-based check with no build behind it. These never gate anything here, in either direction — a red one is not a CI failure to fix, and its presence does not make a PR with no real CI look like it has some. `gh pr checks --json` distinguishes them for you: a check tied to an Actions run carries a non-empty `workflow` field; an App-posted check does not. Every rollup read in this file and in `references/ci-bypass.md` uses the filtered form:

```bash
gh pr checks <number> --repo <org>/<repo> --json name,bucket,state,link,workflow \
  --jq '[.[] | select(.workflow != null and .workflow != "")]'
```

Add `--required` for the required-only variant. Treat this filtered list as "the rollup" everywhere below and in `ci-bypass.md` — a PR whose only checks are App-posted ones is a PR with **no checks at all** for every purpose here.

The exact branches are in step 3 below.

Also read **`bypass-ci-on-billing-failure`** and **`bypass-ci-when-no-pipeline`** from the same Auto-Merge on Approval section; absent ⇒ `false`. Only if one of them is `true`, or the skill was invoked with `--bypass-ci`, does step 3 load `references/ci-bypass.md`, which can override the CI gate described here. None of them ever bypasses a merge **conflict**.

The review comment must already be on the PR before you merge.

Drive the PR to a merged state. Conflicts and red CI are **blockers to clear, not reasons to give up** — fix them on the branch (the same auto-fix discipline as Step 7: fix concrete, objectively correct problems; never guess at changes that need product or design judgment), then merge. You are already on the PR branch from Step 3. Whenever a conflict or a failing check is genuinely **not yours to fix**, do not just pause for a human: file it to the backlog with `/synergy:report-issue` (autonomous, correct type, referencing this PR) so the fix is picked up automatically — it lands at the `Backlog` stage, available — then leave `approved` and exit. The fallbacks below say where.

1. **Confirm the PR is still what you reviewed.** Re-read its state:
   ```bash
   gh pr view <number> --repo <org>/<repo> --json state,mergeable,headRefOid
   ```
   - `state` not `OPEN` (already merged or closed) → nothing to do; report and exit.
   - `headRefOid` differs from the SHA you reviewed (recorded in Step 3, or the updated SHA from Step 7, and written to the footer) → commits you did not review landed mid-run. Do **not** merge: ensure `needs-re-review` is applied and exit so the next run re-reviews the new head. (Commits **you** push in steps 2–3 below are excluded — update your recorded SHA as you push them.)

2. **Resolve merge conflicts if there are any.** When `mergeable` is `CONFLICTING`, do not bail: load `references/conflict-resolution.md` and follow it, with the PR branch (already checked out) as the working branch and `<baseRef>` as the incoming branch. On success, update your recorded SHA to the new `HEAD` and append a line to the review comment noting the conflict resolution.

   If the reference **escalates** (it aborted the merge because the resolution genuinely needs human judgment), file the rebase to the backlog with `/synergy:report-issue` (autonomous, referencing this PR and the conflicting files) so it is picked up automatically — no human approval needed. Post a one-line comment naming the filed issue, leave the `approved` verdict, and exit. Do not guess at the merge.

3. **Fix a failing pipeline if there is one.**

   Only if the skill was invoked with `--bypass-ci`, or `bypass-ci-on-billing-failure` or `bypass-ci-when-no-pipeline` is `true`, read `references/ci-bypass.md` and follow it first (the `--bypass-ci` override and steps 3a and 3b); it merges through step 4 or sends you back here.

   Otherwise, or when `references/ci-bypass.md` sends you back, read the required-check rollup (the filtered form from the scope note above, `--required` added):
   ```bash
   gh pr checks <number> --repo <org>/<repo> --required --json name,bucket,state,link,workflow \
     --jq '[.[] | select(.workflow != null and .workflow != "")]'
   ```
   - Any **required** check **failing** → fetch the failure detail and fix the cause on the branch:
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
     judgment): file the failing check to the backlog with
     `/synergy:report-issue` (autonomous,
     referencing this PR and naming the check) so the fix is picked up
     automatically — no human approval needed. Post a one-line comment
     naming the filed issue, leave `approved`, and exit. Never force a
     merge over a genuinely red required check.
   - Required checks **pending** (including right after you pushed a fix) → enqueue auto-merge: step 4 (`--auto`).
   - Required checks **passing** → merge now (step 4, immediate path), provided you pushed nothing in steps 2–3 (a push leaves checks pending → enqueue `--auto` instead).
   - **No required checks reported** → the branch is unprotected. Read the full check rollup (not just required ones — the filtered form from the scope note above):
     ```bash
     gh pr checks <number> --repo <org>/<repo> --json name,bucket,state,link,workflow \
       --jq '[.[] | select(.workflow != null and .workflow != "")]'
     ```
     - **No checks at all** on the head SHA → the **no-checks guard**
       applies, for every `require-ci-before-merge` value. CI status is
       **UNKNOWN**, not passing — this gate sees only checks reported to
       GitHub, and the project may run its CI elsewhere (Buildkite,
       CircleCI, Jenkins, …) where the gate cannot see it. Never treat
       an empty rollup as green.

       **Steps 3a-ii and 3b (in `ci-bypass.md`) ran before this guard, for every value below.**
       If `bypass-ci-on-billing-failure` or `bypass-ci-when-no-pipeline` is
       `true` and its conditions held, the merge already happened and you
       never reach here; what follows is the path for an empty rollup that
       neither setting explains:
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
         reported — CI status unknown; merge manually, re-run with
         `--bypass-ci`, or set `bypass-ci-when-no-pipeline` if this
         project has no GitHub-visible pipeline"), leave `approved`, and
         exit. Absent checks are treated as satisfied only by the explicit
         `--bypass-ci` override (top of this step), or by a config bypass
         whose evidence held (steps 3a-ii and 3b).
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
   - **Immediate** (nothing pushed in steps 2–3, required checks already green or none):
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
   - **Enqueue** (checks pending — including after a fix push — or admin unavailable):
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
     enable it with `/synergy:setup harden`"), leave `approved`,
     and exit. Confirm the enqueue actually took in step 5 below.

5. **Verify the outcome — never assume.** Re-read the state:
   ```bash
   gh pr view <number> --repo <org>/<repo> --json state,mergedAt,autoMergeRequest
   ```
   - `state` `MERGED` → report in the **final report format** (in `pr-workflow.md`, shared with Step 10), leading with `Approved and merged PR #<number>: <title>`.
   - `autoMergeRequest` is non-null (auto-merge enqueued) → report in the same format, leading with `Approved PR #<number>: <title> — auto-merge queued, will land when checks / branch protection clear`.
   - You took the **Enqueue** path but `autoMergeRequest` is null and `state` is still `OPEN` → the `--auto` call did not take (repo auto-merge disabled). Pause per step 4: post the one-line comment, leave `approved`, and exit. Do not claim success.
   - Neither merged nor queued → report exactly why the merge did not complete. Do not claim success.

6. **Settle the linked issues — close them and set their stage to Done.** Run this **only when Step 5 confirmed `state` is `MERGED`** (the immediate path). On the **queued** path (`autoMergeRequest` non-null, still `OPEN`), the PR has not merged yet — skip this step; `wf post-merge` would correctly refuse with `not-merged`. The issue is settled when the queued merge lands (by GitHub's auto-close, and `wf post-merge` once the merge has landed for the stage), not in this run.

   Do **not** assume the merge closed the issue. GitHub auto-closes a linked issue only when the PR carried a recognised closing keyword **and** merged into the default branch — a chained-story PR (non-default base) or an unparsed reference leaves the issue open, and even a clean auto-close never changes the stage from `In Review`. Make both deterministic with one call (the branch was already deleted by the merge):

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" post-merge --pr <number>
   ```

   If `.claude/release-notes.json` does not already exist — meaning neither `execute` nor `bulk-execute` wrote one for this run, which is the normal case for a merge finished by a standalone `pr-review` pass — generate it here, before settling. Fetch the PR's own closing issues, since nothing earlier in this file has read them yet:
   ```bash
   gh pr view <number> --repo <org>/<repo> --json closingIssuesReferences
   ```
   Read `synergy/skills/release-notes/SKILL.md`'s "When another skill calls this" section and follow it, treating the PR's whole merged diff as the change, for every issue this returns. Write the result with the Write tool to `.claude/release-notes.json`, in the same `{"<number>": {"user": "...", "internal": "..."}}` shape `execute`'s own `merge.md` documents. This write is already capability-gated on the org's own issue fields, inside `wf_stage.release_note_inputs` — a project without the fields is unaffected, so nothing needs to be checked up front.

   It reads the PR's own `closingIssuesReferences`, force-closes any of those issues still open, and sets every one of them to the **Done** stage, which is where the issue's state is recorded. When every close, stage write and release landed, it prints one line: `settled` lists the issues now closed and `Done`, `containers_closed` each Epic or Feature whose sub-issues are all closed, and `released` each blocked issue now back in the pool. Report each by number and title. Otherwise the full payload follows, and the rest of this step says how to read it: report each `settled` entry whose `closed_now` or `stage_set` is false by number and title. If the PR body used a closing keyword GitHub did not parse, pass the issue explicitly: `... post-merge --pr <number> --issue <N>`. Whenever `.claude/release-notes.json` exists — written by `execute`/`bulk-execute` before calling this file, or by this step just above — add `--notes .claude/release-notes.json`: each issue's `User release notes` and `Internal release notes` are written in the same write as Done, and the one-line result lists them under `release_notes`. A `settled` entry whose `release_notes.error` is set reached Done without its notes; report it by number and title. A notes file that could not be read is reported in `release_note_errors`: report it too, because no issue received its notes.

   It then runs the **unblock sweep**, because closing this PR's own issues is only half of a merge. In a full payload it is `unblocked`; report all three of its parts: `released` (blocked issues whose native blocked-by edges have all closed — name each by number and title, they are back in the pool), `partials` (still held, but a blocker just merged something, so a person has to judge whether that freed them), and the `no_edges` count (labelled blocked with no dependency edge, so the sweep cannot speak to them either way — the number only, never the list). A `settled` array that came back empty does **not** mean there was nothing to do: a PR that deliberately closes nothing can still release work, and the sweep is what finds it. Use `--no-unblock` only when running `wf unblock` separately.

   Only when `wf post-merge` cannot run at all, read `references/post-merge-fallback.md` and follow it.
