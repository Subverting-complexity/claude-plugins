---
description: 'Push the branch, create a PR, and update the board. Trigger: "finish", "done", "open a PR", "ship it", "create the PR", "submit", "wrap up", "push it", "send for review".'
---

# Finish Story

Push the branch, create a PR, and update the board.

Requires: a story in progress with committed work on a feature branch.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Current state (auto-detected)

**Branch:** !`git branch --show-current 2>/dev/null || echo "(unknown)"`

**Recent commits:**
```!
git log --oneline -5 2>/dev/null || echo "(no commits)"
```

**Project configuration:**
```!
if [ -f ClaudeProject.md ]; then
  cat ClaudeProject.md
else
  echo "ClaudeProject.md NOT FOUND"
fi
```

## Steps

### 1. Read configuration

Extract from the project configuration above:

- `org`, `repo`, `default-branch` from Identity
- Project board settings (if configured)
- Label map (for claude labels and the issue lifecycle states)

Resolve every label by **purpose key** through the single path in
`templates/default-labels.md`:

- **Issue lifecycle** purposes (`status-in-review`) and **claude**
  purposes (`claude-authored`) — via the `ClaudeProject.md` label map.
- **Review-state** purposes this command applies to the PR
  (`needs-review`, `needs-re-review`) — via `review.config.md` when
  present, defaults (`review-` prefix) otherwise.

Resolve them, never apply a bare name literally, so the labels this
command writes are the identical strings the code-review and update-pr
skills filter on. If `ClaudeProject.md` is missing or has no label map,
use the defaults from `templates/default-labels.md`. When using defaults
in an interactive session, warn the user: "Label map not configured —
using default labels. Run `/github-workflow:setup` to configure labels
for this project."

### 2. Run the quality gate

Run the quality gate command from `ClaudeProject.md` to verify the code
is clean before pushing:

1. Execute the quality gate script/command.
2. If it fails, read the error output, fix the issue, and re-run.
3. Repeat up to 3 times (4 total runs maximum).
4. If still failing after 4 runs, **do not create a draft PR** (this
   workflow never opens drafts). The work is complete but the gate is
   red, so a human still needs to see it: set a flag to open a **real
   PR** and mark it blocked-for-merge via labels in Step 7 — apply the
   `changes-requested` review-state label and add a "Quality Gate Failed"
   section to the PR body with the last error output. The blocking label
   (not draft status) is what signals "do not merge yet."

### 3. Push the branch

```
git push -u origin HEAD
```

### 4. Check for existing PR

Before creating a new PR, check if one already exists for this branch
(e.g., from a previous session that pushed but didn't finish cleanly):

```
gh pr list --repo {org}/{repo} --head {branch} --state open --json number,title
```

If a PR already exists, update it instead of creating a new one:

```
gh pr edit {pr_number} --body-file {tempfile}
```

Write the updated body to a temporary file first, then use
`--body-file` to avoid Windows/PowerShell shell-escaping issues.
Delete the temp file after. Then validate the body was applied
(same as Step 5b).

Skip to Step 6 (labels). Only create a new PR if none exists.

### 4b. Ensure issue linkage

Every PR must link to a GitHub issue for traceability. Before creating
a new PR, determine whether the current work has an associated issue:

1. Check session context for a story number from `/github-workflow:execute`
   or `/github-workflow:start-story`.
2. If no story number is known, check the branch name for an issue
   number (e.g., `feature/42/description` → issue #42). Verify it
   exists:
   ```
   gh issue view {number} --repo {org}/{repo} --json state --jq '.state'
   ```
3. If no issue is found from context or branch name, create one now.
   Use the commit history and diff to build a proper issue body:

   - **Title**: derive from the branch name or first commit message.
     Apply the appropriate issue prefix (`[STORY]`, `[BUG]`,
     `[SECURITY]`, `[ARCH]`, or `[DEBT]`) from ClaudeProject.md.
   - **Body**: include Context (what was built and why), Requirements
     (what the changes accomplish), and Notes (any caveats).
   - **Labels**: resolve the appropriate type and priority labels, the
     `claude-authored` provenance marker (this issue is Claude-created),
     and the `status-in-review` lifecycle label (a PR is being opened for
     it now) — all by purpose key via `templates/default-labels.md`. Then
     run label validation (check existence, create-if-missing without
     `--force`) before applying:
     ```
     gh label list --repo {org}/{repo} --json name --jq '.[].name'
     gh label create "{label}" --repo {org}/{repo} --description "{desc}" --color "{color}"
     ```
   - **Milestone**: if in sprint mode, attach to the current milestone.

   Write the issue body to a temporary file, then create using
   `--body-file` to avoid Windows/PowerShell shell-escaping issues:

   ```
   gh issue create --repo {org}/{repo} --title "{title}" --body-file {tempfile} --label "{labels}"
   ```

   Delete the temp file after. Then validate the issue body and
   labels were applied correctly — read back and verify, same as
   the validation in `/github-workflow:report-issue` Steps 5b and 6.

   **Leave the assignee blank.** Do not pass `--assignee`/`--add-assignee`
   on this `gh issue create`, and do not edit the new issue to assign it.
   A follow-up issue must enter the unassigned pool so it is eligible for
   normal pickup; assignment happens only at claim time, never at
   creation.

   Record the new issue number for use in Step 5.

The issue number (from context, branch, or newly created) is used in
Step 5 to add `Closes #N` to the PR body.

### 4c. Duplicate-PR detection

Step 4 already ruled out an existing PR on **this** branch. Now check for
a sibling open PR that closes the **same issue** on a **different** branch
(a second session may have built the same story — see the duplicate
vectors in `skills/code-review/references/review-workflow.md`). Run the
authoritative lookup in `templates/sibling-pr-lookup.md` with this
`{number}` and ignore any result whose `headRefName` equals `{branch}`.

If a sibling PR exists, still create your PR in Step 5 (so both are real
and comparable) but prepend this flag line to the body so code review
reconciles them:

```
> ⚠ Possible duplicate of #{sibling_number} — both close #{number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
```

Report the duplicate to the user. Do not pick the winner or close the
other PR here — code review's Step 2b does that with full context.

### 5. Create new PR

Build the PR body from the committed changes:

- Summarize what was built (from commit messages and diff)
- List acceptance criteria addressed
- Note any technical decisions made
- Add a test plan section
- **Always** close the associated issue: include a `Closes #N` line for
  every issue this PR resolves (see the linked-issue format below). A PR
  for a story must never omit this — if no issue is linked, that is a
  workflow error to resolve before opening the PR.

Write the PR body to a temporary file first, then create the PR
using `--body-file` to avoid Windows/PowerShell shell-escaping issues.
**Always create a real PR — never a draft.** The same command is used
whether or not the quality gate passed; a failed gate is signalled by a
blocking label in Step 7, not by draft status:

```
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
```

Delete the temp file after creation.

When the quality gate failed (Step 2), prepend this section to the body
so the failure is visible (the `changes-requested` label applied in
Step 7 is what actually blocks merge):

```
> **⚠ Quality gate failed** — the quality gate did not pass after 4
> attempts. This PR carries the `changes-requested` label and must not
> be merged until the gate is green. See error details below.
>
> **Last error:**
> {quality_gate_error_output}
```

Every PR **must** close its associated issue(s). Each linked issue gets
its own `Closes #N` line in the PR body:

```
Closes #42
Closes #43
```

Each `Closes #N` must be on its own line so GitHub links them in
the Development sidebar and auto-closes the issue on merge. The Step 5b
validation must confirm a `Closes #N` line is present for every linked
issue before the PR is considered done.

### 5b. Validate PR body

**Always pass the body with `--body-file {tempfile}`. Never pass it
inline** with `--body "..."` or, worse, `--body -` — inline bodies hit
Windows/PowerShell shell-escaping bugs, and `--body -` does **not** read
stdin (it sets the body to the literal string `-`). Both produce the
corrupt one-character bodies this step exists to catch.

After creating or updating the PR, immediately read it back and
verify the body was written correctly:

```
gh pr view {pr_number} --repo {org}/{repo} --json body --jq '.body'
```

Treat the body as **corrupt** if any of these is true (not just the
single `@` case — the same escaping/stdin bugs also leave `-`, `.`, `#`,
or other lone punctuation):

- It is empty or only whitespace.
- After trimming whitespace it is shorter than ~10 characters.
- After trimming it consists only of punctuation/symbols (e.g. `-`, `@`,
  `.`, `#`) with no words — a stray shell artifact, not a description.
- It is missing a required `Closes #N` line (see below).

When the body is corrupt:

1. Write the intended body to a temporary file.
2. Update the PR using `--body-file`:
   ```
   gh pr edit {pr_number} --repo {org}/{repo} --body-file {tempfile}
   ```
3. Delete the temporary file.
4. Re-read the PR to confirm the fix — apply the same corruption test
   again, not just "non-empty".
5. If still corrupt after retry, warn the user.

Also confirm the body contains a `Closes #N` line for every linked
issue. If any is missing, add it (via `gh pr edit --body-file`) before
proceeding — a PR must always close its associated issue.

### 6. Resolve merge conflicts

Check if the PR has merge conflicts with the base branch:

```
gh pr view {pr_number} --repo {org}/{repo} --json mergeable,mergeStateStatus
```

If `mergeable` is `CONFLICTING`:

1. Fetch the latest base branch and rebase onto it:
   ```
   git fetch origin {default-branch}
   git rebase origin/{default-branch}
   ```
2. Resolve conflicts one commit at a time as the rebase progresses.
   Read each conflicted file, understand both sides, and pick the
   correct resolution. Then continue:
   ```
   git add <resolved-files>
   git rebase --continue
   ```
3. After the rebase completes, run the quality gate again (1 run —
   if it fails, fix and retry once more, 2 total).
4. Force-push the rebased branch:
   ```
   git push --force-with-lease
   ```

**Classify the conflict resolution:**

- **Trivial conflicts** (import ordering, adjacent-line edits,
  whitespace, auto-resolved renames): no re-review needed.
- **Complex conflicts** (overlapping logic changes, altered control
  flow, modified function signatures, deleted code that the PR
  depended on): the rebased result needs a reviewer's eyes.
  - **New PR** (this `finish-story` just created it, no prior review):
    the `needs-review` entry label set in Step 7 already routes it to a
    reviewer — no extra label needed here.
  - **Existing PR** (Step 4 path — it was opened in a prior session and
    may already have been reviewed): move it to `needs-re-review`,
    removing any current review-state label so exactly one is present:
    ```
    gh pr edit {pr_number} --remove-label "{current_state_label}" --add-label "{needs_re_review_label}"
    ```

  After applying, verify the label is present (same as Step 7 below).
  If missing, create it and retry.

### 7. Add labels to PR

Apply two labels, both resolved by purpose key through the single path in
`templates/default-labels.md`:

1. **Provenance** — `claude-authored` (default `claude-authored`), to
   mark this as a Claude-built PR.
2. **Review-state entry label** — so the PR is never unlabelled and the
   reviewer can find it:
   - Quality gate passed → `needs-review` (default `review-needs-review`).
   - Quality gate failed (Step 2 flag) → `changes-requested` (default
     `review-changes-requested`), which blocks merge until the gate is
     green. Do **not** also apply `needs-review` — exactly one
     review-state label.

Skip this entirely if Step 4 found an existing PR that already carries a
review-state label (e.g. `approved`, `needs-re-review`) — do not reset a
reviewed PR back to `needs-review`; leave its existing state (Step 6 may
have moved it to `needs-re-review`).

```
gh pr edit {pr_number} --add-label "{claude_authored_label}" --add-label "{needs_review_label}"
```

After applying, verify the labels were applied:

```
gh pr view {pr_number} --repo {org}/{repo} --json labels --jq '[.labels[].name]'
```

If a label is missing, it was not created at setup. Create it with the
guarded create-if-missing pattern from `templates/default-labels.md` —
**without `--force`** so existing metadata is never overwritten — then
retry. Use the colours from `templates/default-labels.md`.

### 8. Move the issue to In Review

**Issue lifecycle label (authoritative).** Move the linked issue to the
`status-in-review` lifecycle label, removing its current lifecycle label
(`status-in-progress`) so exactly one state is present. Resolve both
names by purpose key through `templates/default-labels.md`:

```
gh issue edit {number} --repo {org}/{repo} \
  --remove-label "{status_in_progress_label}" --add-label "{status_in_review_label}"
```

Verify per `templates/default-labels.md` (read back; guarded
create-if-missing without `--force` if absent, then retry once). This
label — not the board — is the authoritative "in review" signal, so it
works even when no board is configured.

**Project board (best-effort, if configured).** First resolve the board,
the issue's `{item_id}`, and the target column's `{column_option_id}`
following `templates/board-resolution.md` (board-configured check,
identity verification by title, add-to-board-if-missing, column-option-id
resolution). The target column for `status-in-review` is **In Review**
(`col-in-review`) per the label ⇄ column pairing in
`templates/default-labels.md`. Only run the mutation below once it returns
a verified `{item_id}` and `{column_option_id}`.

Set status to In Review:

```
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{project_node_id}"
    itemId: "{item_id}"
    fieldId: "{status_field_id}"
    value: { singleSelectOptionId: "{column_option_id}" }
  }) { projectV2Item { id } }
}'
```

When **no** board is configured, skip this step silently. When a board
**is** configured, board failures are loud: report the failure to the
user (e.g., "Board update failed: {error}. Continuing without board
update.") and proceed with the rest of the workflow.

### 9. Release the claim

The PR now exists, so the issue's assignment and the open PR are the
ownership markers — the select-to-start race window is closed and the
atomic claim ref is no longer needed. Release it (following
`templates/claim-procedure.md` **Release**) so `refs/claims/` stays
bounded to in-flight work:

```
git push origin :refs/claims/issue-{number}
rm -f .claude/claim-issue-{number}.sha
```

Idempotent — ignore an error if the ref is already gone. This does
**not** unassign the issue; it stays assigned to @me through review.

### 9b. Reconcile the working tree to clean

The PR is pushed, so local state is no longer the source of truth. Leave
the worktree clean so the harness can reap it (`docs/worktree-config.md` —
a dirty tree is never auto-removed). Delete the per-session scratch file
and run the **End clean** procedure in `templates/worktree-hygiene.md`:

```
rm -f .claude/plan.md
git status --porcelain    # reconcile until empty
```

Commit any incidental formatting on unrelated files as a **separate
`chore:` commit** and push it (it rides the PR branch); discard disposable
generated noise. **Never `git stash`** — the stash is shared across every
worktree on the clone. End with `git status --porcelain` empty.

### 10. Report

Display:

- PR number, title, and URL — always name the PR by number **and**
  title together (e.g. `#123 Add login button`), never the number alone
- Linked issue(s), each by number **and** title
- Labels applied
- Board status (if updated)
