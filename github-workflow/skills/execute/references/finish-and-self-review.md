# Execute — Phase 7 (Finish) & Phase 8 (Self-Review)

Read this file when you reach Phase 7 of the `execute` workflow (after the
quality gate passes and work is committed). It is kept out of the main
`SKILL.md` so it does not weigh on the pick/plan/build window — the steps
here are only needed once you are ready to open the PR.

## Phase 7 — Finish

1. **Push and duplicate-PR detection in parallel.** Issue both calls in
   a single tool-call batch — they have no ordering dependency on each
   other:

   - Push the branch:
     ```
     git push -u origin HEAD
     ```
   - Check for a sibling open PR that already closes this issue on a
     different branch — run the authoritative lookup in
     `templates/sibling-pr-lookup.md` with this `{number}`.

   Wait for both to complete before proceeding. The push must finish
   before you can create the PR in Step 2; the sibling lookup result is
   used to optionally prepend a flag line to the PR body.

   Holding the issue claim through PR creation (released only in step 5)
   already serializes builders, so a sibling should never be found — this
   is the backstop for a sub-second race. If one is found, ignore any
   result whose `headRefName` equals `{branch}` (that is your own PR).
   Still create your PR in Step 2, but prepend:

   ```
   > ⚠ Possible duplicate of #{sibling_number} — both close #{number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
   ```

   Report the duplicate to the user. Do not pick the winner or close the
   other PR here — that is code review's job.

2. Create a real PR (never a draft — this workflow does not open drafts).
   Write the body following `templates/body-file-write.md` (temp file +
   `--body-file`):

   ```
   gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
   ```

   - Title under 70 chars
   - **Always** close the associated issue: each linked issue on its own
     line as `Closes #42`. A story PR must never omit this.
   - Include a test plan section
   - Summary of what was built and acceptance criteria addressed
   - If the **gate-failed flag** is set (Phase 5), prepend a "Quality
     Gate Failed" section with the last error output.

2b. Validate the PR body — read it back and apply the corruption test and
   retry in `templates/body-file-write.md` (**Validate** + **Retry**). For
   a PR body the test also requires a `Closes #N` line for every linked
   issue; if any is missing, add it via `gh pr edit --body-file` before
   proceeding.

3. **Apply PR labels, move the issue, and update the board in one
   combined GraphQL mutation.** Instead of a separate `gh pr edit`, a
   `gh issue edit`, and a board mutation, send them all in a single
   `gh api graphql` call.

   **Prerequisites** — resolve before building the mutation:
   - PR node ID: `gh pr view {pr_number} --repo {org}/{repo} --json id --jq '.id'`
   - Label node IDs from `.claude/label-cache.json` (written by session
     prewarm): look up `claude-authored`, the review-state entry label
     (`review-needs-review` or `review-changes-requested`),
     `status-in-progress`, and `status-in-review` by name. If any label
     is missing from the cache, create it with the guarded
     create-if-missing pattern from `templates/default-labels.md`
     (no `--force`), append the new `{name, id}` entry to the cache, and
     use that ID.
   - Issue node ID: available from context (stored when the issue was
     added to the board in Phase 2); if not in context, fetch it with
     `gh issue view {number} --repo {org}/{repo} --json id --jq '.id'`.
   - Board item ID and column option ID: follow
     `templates/board-resolution.md`; the target column for
     `status-in-review` is `col-in-review`.

   **Combined mutation:**
   ```
   gh api graphql -f query='
     mutation FinishCombined(
       $prId:ID!, $issueId:ID!,
       $prAddLabels:[ID!]!,
       $issueRemoveLabels:[ID!]!, $issueAddLabels:[ID!]!,
       $projId:ID!, $itemId:ID!, $fieldId:ID!, $colVal:String!
     ){
       addPRLabels:       addLabelsToLabelable(input:{labelableId:$prId, labelIds:$prAddLabels}){ __typename }
       removeIssueLabel:  removeLabelsFromLabelable(input:{labelableId:$issueId, labelIds:$issueRemoveLabels}){ __typename }
       addIssueLabel:     addLabelsToLabelable(input:{labelableId:$issueId, labelIds:$issueAddLabels}){ __typename }
       moveBoard:         updateProjectV2ItemFieldValue(input:{projectId:$projId, itemId:$itemId, fieldId:$fieldId, value:{singleSelectOptionId:$colVal}}){ __typename }
     }' \
     -F prId="$PR_NODE_ID" \
     -F issueId="$ISSUE_NODE_ID" \
     -F prAddLabels="[\"$CLAUDE_AUTHORED_ID\",\"$REVIEW_STATE_LABEL_ID\"]" \
     -F issueRemoveLabels="[\"$STATUS_IN_PROGRESS_ID\"]" \
     -F issueAddLabels="[\"$STATUS_IN_REVIEW_ID\"]" \
     -F projId="$PROJ_NODE_ID" \
     -F itemId="$ITEM_ID" \
     -F fieldId="$STATUS_FIELD_ID" \
     -F colVal="$IN_REVIEW_OPTION_ID"
   ```

   **If no board is configured**, omit the `moveBoard` alias (build the
   mutation without that variable/alias); the PR label and issue label
   changes still go in the same call. **If the org's `Target date` field
   exists** (check via `templates/issue-fields-resolution.md` capability
   probe), add a fifth alias to the same mutation to record today's date.

   **Fallback** — if the combined mutation fails (e.g. a label ID was
   stale in the cache), fall back to the three individual calls:
   `gh pr edit` for PR labels, `gh issue edit` for the lifecycle label,
   and `board-resolution.md` Step 5 for the board. The atomic-claim and
   label-presence guarantees still hold: the individual calls verify via
   exit code and create-if-missing as before.

5. Release the atomic claim now that the PR exists — the open PR plus the
   assignment are the ownership markers, so the claim ref is no longer
   needed (`templates/claim-procedure.md` **Release**). This is the same
   release **Exit cleanup** runs; doing it here, the moment the PR is
   live, just frees the ref sooner. Then delete the scratch file now that
   the work is shipped:
   ```
   git push origin :refs/claims/issue-{number}
   rm -f .claude/claim-issue-{number}.sha .claude/plan.md \
         .claude/preflight-passed.txt .claude/label-cache.json .claude/candidates.json
   ```
   The claim-ref delete is idempotent — ignore an error if it is already
   gone. The issue stays assigned to @me through review.

6. Report: display the PR by number **and** title together (e.g.
   `#123 Add login button`, never the number alone) plus its URL, the
   linked issues (each by number **and** title), and labels applied.

## Phase 8 — Self-Review

After the PR is created, perform a brief self-check to catch obvious
gaps before a human reviewer sees the PR.

1. Re-read the full PR diff:
   ```
   git diff origin/{default-branch}...HEAD
   ```

2. Re-read the original issue body and acceptance criteria.

3. For each acceptance criterion, verify it is addressed in the diff:
   - If addressed: note it as covered.
   - If missing or only partially addressed: flag it.

4. Check for common oversights:
   - New public functions without tests
   - TODO/FIXME comments left in committed code
   - Hardcoded values that should be configurable
   - Missing error handling on new external calls

5. If any gaps are found, post a comment — write it following
   `templates/body-file-write.md` (temp file + `--body-file`):
   ```
   gh pr comment {pr_number} --repo {org}/{repo} --body-file {tempfile}
   ```
   Then, for each **material** gap that you
   are not fixing before exiting (a missing acceptance criterion, an
   untested public function, missing error handling), file it to the
   board with `/github-workflow:report-issue` (autonomous, `status-ready`,
   correct type, referencing this PR) so it is picked up and fixed
   automatically — no human approval needed.

6. If no gaps are found, skip the comment — a clean PR needs no noise.

This phase never blocks the PR or changes the verdict. Its purpose is to
surface gaps early and queue any it cannot close for automatic pickup, so
the reviewer can focus on deeper concerns.
