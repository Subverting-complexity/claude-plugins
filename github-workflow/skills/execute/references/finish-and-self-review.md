# Execute — Phase 7 (Finish) & Phase 8 (Self-Review)

Read this file when you reach Phase 7 of the `execute` workflow (after the
quality gate passes and work is committed). It is kept out of the main
`SKILL.md` so it does not weigh on the pick/plan/build window — the steps
here are only needed once you are ready to open the PR.

## Phase 7 — Finish

1. Push the branch:

   ```
   git push -u origin HEAD
   ```

1b. **Duplicate-PR detection.** Before creating, check whether another
   open PR already closes this issue on a different branch. Holding the
   issue claim through PR creation (it is released only in step 5, below)
   already serializes builders, so this should never fire — it is the
   backstop for a sub-second create-time race. Run the authoritative
   lookup in `templates/sibling-pr-lookup.md` with this `{number}` and
   ignore any result whose `headRefName` equals `{branch}` (that is your
   own about-to-be-pushed PR).

   If a sibling PR exists, still create your PR (so both are real and
   comparable) but prepend a flag line to the body so code review
   reconciles them and keeps the better one:

   ```
   > ⚠ Possible duplicate of #{sibling_number} — both close #{number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
   ```

   Report the duplicate to the user. Do not attempt to pick the winner or
   close the other PR here — that is code review's job (Step 2b of the
   code-review skill), where both PRs have full context.

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

3. Add PR labels — both resolved by purpose key through
   `templates/default-labels.md`:
   - `claude-authored` (provenance, default `claude-authored`).
   - The review-state **entry label**: `needs-review` (default
     `review-needs-review`) when the gate passed, or `changes-requested`
     (default `review-changes-requested`) when the gate-failed flag is
     set. Exactly one review-state label. This ensures the PR is never
     unlabelled and the reviewer can find it.

   After applying, verify by reading back the PR labels. If a label is
   missing, create it with the guarded create-if-missing pattern from
   `templates/default-labels.md` (no `--force`) and retry once.

4. Move the linked issue to the `status-in-review` lifecycle label,
   removing `status-in-progress` so exactly one state is present (resolve
   both by purpose key). This — not the board — is the authoritative
   "in review" signal:
   ```
   gh issue edit {number} --repo {org}/{repo} \
     --remove-label "{status_in_progress_label}" --add-label "{status_in_review_label}"
   ```
   Verify per `templates/default-labels.md`. Then update the project
   board to the **In Review** column (`col-in-review`) — best-effort, if
   configured. The auto-loaded projection dropped `## Project Board`, so
   read that section from `ClaudeProject.md` now for the board id/title/
   field/option ids, then follow `templates/board-resolution.md` (which resolves
   the column option id by purpose key); the label ⇄ column pairing lives
   in `templates/default-labels.md`.

5. Release the atomic claim now that the PR exists — the open PR plus the
   assignment are the ownership markers, so the claim ref is no longer
   needed (`templates/claim-procedure.md` **Release**). This is the same
   release **Exit cleanup** runs; doing it here, the moment the PR is
   live, just frees the ref sooner. Then delete the scratch file now that
   the work is shipped:
   ```
   git push origin :refs/claims/issue-{number}
   rm -f .claude/claim-issue-{number}.sha .claude/plan.md
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
