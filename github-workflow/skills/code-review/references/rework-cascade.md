# Code Review — Rework Cascade

Read this file when a `changes-requested` PR is selected (Step 1b) or
when the review verdict is Changes Requested and the issues are fixable
(Step 10b). It absorbs the logic formerly in the standalone `update-pr`
command.

## Step 1b — Rework cascade (changes-requested PRs)

When the selected PR was picked from the `changes-requested` tier (its
`prior_state` is `changes-requested`), the PR needs its review feedback
addressed **before** a new review.

1. **Check out the branch** (if `--checkout` didn't already):
   ```bash
   gh pr checkout <number>
   ```

2. **Read the most recent review comment** — find the latest Claude review
   comment (identified by the review footer marker). Extract:
   - The **verdict** and summary
   - The **Issues remaining** section — this is the work list
   - The **Fixes applied** section — these are already done
   - Any items under **Non-compliance**, **Correctness**, or **Tests**
     that were flagged as problems

3. **Address each issue** — work through every item in **Issues
   remaining**, one at a time:
   - Read the referenced file and surrounding context.
   - Understand the problem described in the review.
   - Fix it. Follow the build principles from `CLAUDE.md`.
   - If the fix requires a test change, update the test too.
   - **Do not fix:** items marked as needing discussion (architectural
     decisions), stylistic preferences, or anything outside the review
     scope.

4. **Run the quality gate** from `ClaudeProject.md`. Up to 4 total runs
   (retry 3 times on failure). If still failing, continue — the review
   fixes are still valuable.

5. **Commit and push:**
   ```bash
   git add <changed-files>
   git commit -m "Address review feedback on PR #<number>"
   git push
   ```

6. **Resolve merge conflicts** if the PR is now conflicting: fetch the
   base branch, rebase, resolve conflicts, run the quality gate once,
   and force-push with `--force-with-lease`.

7. **Assess significance and relabel:**
   - Release the claim (`wf claim-release --pr <number>`).
   - If all feedback was trivial AND all Issues Remaining were
     addressed → remove `changes-requested`, apply `needs-re-review`.
   - If changes were substantial → remove `changes-requested`, apply
     `needs-re-review`.
   - If some Issues Remaining were NOT addressed (need human judgment) →
     leave `changes-requested` in place.

8. **Continue to review.** After the rework push, the PR has new commits.
   Proceed to **Step 2b** (duplicate reconciliation), then Step 3 to
   review the updated PR. The re-review in Step 4b will classify the
   diff since the last review and may fast-track to approval if the
   rework was trivial.

## Step 10b — Post-verdict rework cascade

When the review verdict is `changes-requested` **and** the Issues
Remaining are all concrete, objectively fixable problems (not
architectural questions or design decisions requiring human input),
cascade into rework within the same session rather than exiting.

Follow the same procedure as Step 1b above (steps 1–7), then return to
**Step 4b** (re-review significance assessment) to evaluate the rework.

If the Issues Remaining contain **any** item that genuinely requires
human judgment, skip this cascade and exit after Step 10 — the
`changes-requested` label stays so a human can address it.
