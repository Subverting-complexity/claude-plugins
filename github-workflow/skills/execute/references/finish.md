# Execute — Phase 7 (Finish)

Read this at Phase 7 of the `execute` workflow (quality gate passed, work
committed); kept out of `SKILL.md` to keep the pick/plan/build window
light.

## Phase 7 — Finish

1. **Push and duplicate-PR detection in parallel** (one tool-call batch —
   no ordering dependency):

   - Push the branch:
     ```
     git push -u origin HEAD
     ```
   - Check for a sibling open PR that already closes this issue on a
     different branch — run the authoritative lookup in
     `templates/sibling-pr-lookup.md` with this `{number}`.

   Wait for both before proceeding: the push must finish before Step 2's
   PR create; the sibling result optionally prepends a flag line to the
   PR body.

   Holding the issue claim through PR creation already serializes
   builders, so a sibling should never be found — this is the backstop
   for a sub-second race. If one is found, ignore any result whose
   `headRefName` equals `{branch}` (your own PR). Still create your PR in
   Step 2, but prepend:

   ```
   > ⚠ Possible duplicate of #{sibling_number} — both close #{number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
   ```

   Report the duplicate to the user. Do not pick the winner or close the
   other PR here — that is code review's job.

   The lookup can go stale before PR creation: immediately before
   composing the body in Step 2, re-verify a found sibling with
   `gh pr view {sibling_number} --repo {org}/{repo} --json state --jq '.state'`;
   if it is no longer `OPEN`, drop the flag line and proceed normally.

2. Create a real PR (never a draft). Write the body following
   `templates/body-file-write.md` (temp file + `--body-file`):

   ```
   gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
   ```

   - Title under 70 chars
   - **Always** close the associated issue: each linked issue on its own
     line as `Closes #42`. A story PR must never omit this.
   - Include a test plan section
   - Summary of what was built and acceptance criteria addressed
   - If the **gate-failed flag** is set (`test -f .claude/gate-failed.flag`,
     written in Phase 5), prepend a "Quality Gate Failed" section with the
     last error output.

2b. Validate the PR body — read it back and apply the corruption test and
   retry in `templates/body-file-write.md` (**Validate** + **Retry**). For
   a PR body the test also requires a `Closes #N` line for every linked
   issue; if any is missing, add it via `gh pr edit --body-file` before
   proceeding.

3. **Apply PR labels, move the issue, and update the board in one
   combined GraphQL mutation** — a single `gh api graphql` call instead
   of separate `gh pr edit` / `gh issue edit` / board calls.

   **Prerequisites** — resolve before building the mutation:
   - PR node ID: `gh pr view {pr_number} --repo {org}/{repo} --json id --jq '.id'`
   - Label node IDs: look up `claude-authored`, the review-state entry label
     (`review-needs-review` or `review-changes-requested`),
     `status-in-progress`, and `status-in-review` by name. No label
     inventory is prewarmed, so `.claude/label-cache.json` is usually
     absent here — fetch the IDs now with `gh label list --repo
     {org}/{repo} --json name,id --limit 1000` (the deferred, first-use
     fetch); if the cache *does* exist from an earlier fallback this
     session, read it instead of re-querying. If any label is missing,
     create it with the guarded create-if-missing pattern from
     `templates/default-labels.md` (no `--force`), write/append its
     `{name, id}` entry to `.claude/label-cache.json`, and use that ID.
   - Issue node ID: from context (stored at Phase 2's board add); if not
     in context, `gh issue view {number} --repo {org}/{repo} --json id
     --jq '.id'`.
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
     -f prId="$PR_NODE_ID" \
     -f issueId="$ISSUE_NODE_ID" \
     -f 'prAddLabels[]'="$CLAUDE_AUTHORED_ID" \
     -f 'prAddLabels[]'="$REVIEW_STATE_LABEL_ID" \
     -f 'issueRemoveLabels[]'="$STATUS_IN_PROGRESS_ID" \
     -f 'issueAddLabels[]'="$STATUS_IN_REVIEW_ID" \
     -f projId="$PROJ_NODE_ID" \
     -f itemId="$ITEM_ID" \
     -f fieldId="$STATUS_FIELD_ID" \
     -f colVal="$IN_REVIEW_OPTION_ID"
   ```

   Build each `[ID!]!` label array by repeating `-f 'name[]'=<id>` once
   per label — how `gh api graphql` constructs a JSON array variable. Do
   **not** collapse them into a single `-F name="[...]"`: `-F` never
   parses `[...]` as JSON, so the array arrives as one literal string and
   GitHub rejects the `[ID!]!` variable (the "array-label" failure that
   forces the per-name fallback). Pass every other field with `-f` too —
   all are `ID!`/`String!`, and `-f` keeps a digit-only option id in
   `colVal` from being coerced to `Int` (rejected against `String!`).

   **If no board is configured**, omit the `moveBoard` alias and its
   variables; the PR and issue label changes still go in the same call.
   **If the org's `Target date` field exists** (per the
   `templates/issue-fields-resolution.md` capability probe), add a fifth
   alias to the same mutation to record today's date.

   **Fallback** — if the combined mutation fails (e.g. a stale cached
   label ID), run three individual calls, in order:

   1. `gh pr edit {pr_number} --repo {org}/{repo} --add-label
      claude-authored --add-label {review-state-label}`
      (`review-needs-review`, or `review-changes-requested` when
      `.claude/gate-failed.flag` exists).
   2. `gh issue edit {number} --repo {org}/{repo} --remove-label
      status-in-progress --add-label status-in-review`.
   3. Board move — `templates/board-resolution.md` Step 5, targeting
      `col-in-review` (skip when no board is configured).

   The atomic-claim and label-presence guarantees still hold: the
   individual calls verify via exit code and create-if-missing as before.

4. Release the atomic claim now that the PR exists — the open PR plus the
   assignment are the ownership markers, so the claim ref is no longer
   needed (`templates/claim-procedure.md` **Release**). Same release
   **Exit cleanup** runs; doing it here just frees the ref sooner. Then
   delete the scratch files:
   ```
   git push origin :refs/claims/issue-{number}
   rm -f .claude/claim-issue-{number}.sha .claude/plan.md \
         .claude/preflight-passed.txt .claude/label-cache.json
   ```
   The claim-ref delete is idempotent — ignore an error if it is already
   gone. The issue stays assigned to @me through review.

5. Note what now exists, in a line or two: the PR by number **and** title
   together (e.g. `#123 Add login button`, never the number alone) plus its
   URL, the linked issues (each by number **and** title), and the labels
   applied. A **progress note, not the run's final report** — do not
   summarise the work as though it were done, and do not end your turn on it.

   `skills/user-facing-communication/SKILL.md` governs how this reads, and
   the part that matters most here is being exact about state. The pull
   request is **open and not yet reviewed**. Say that. A note that reads
   like a finished run invites the user to treat it as one, which is the
   failure the next section describes.

6. **Go to Phase 8 now**: read `references/review-and-merge.md` and follow
   it, in the same turn as step 5. Without asking the user, without waiting
   for CI, and without checking whether merging is switched on — that setting
   is read in Phase 10 and decides nothing here.

## Why step 6 is the one that gets skipped

Steps 3 and 4 read like the end of a run: claim released, scratch files
deleted, board on In Review, PR labelled `review-needs-review`. All four are
housekeeping done early, and that label marks a PR **this run is about to
review**, not one queued for someone else. The failure has happened — a run
posts its Phase 7 summary, says the PR is waiting on code review and on CI,
and offers to review and merge it if the user says the word. Nothing here
asks for that. An open, unreviewed PR is an unfinished story: the run ends at
Phase 10 or at an exit Phases 8 to 10 name, nowhere else.

**Do not review your own diff on the way there.** An earlier version did, and
it was removed: this session wrote the code, so it shares every assumption
the code was built on and cannot judge it, and anything it files duplicates
what the Phase 8 agents file minutes later. Note the limit. The diff goes
to a reviewer **you** spawn and its findings come back to **you**. Your
judgement of the code is set aside, never your ownership of the run.
