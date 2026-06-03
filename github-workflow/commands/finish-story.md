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
- Label map (for claude labels)

If `ClaudeProject.md` is missing or has no label map, use the default
label names from `templates/default-labels.md`. When using defaults in
an interactive session, warn the user: "Label map not configured —
using default labels. Run `/github-workflow:setup` to configure labels
for this project."

### 2. Run the quality gate

Run the quality gate command from `ClaudeProject.md` to verify the code
is clean before pushing:

1. Execute the quality gate script/command.
2. If it fails, read the error output, fix the issue, and re-run.
3. Repeat up to 3 times (4 total runs maximum).
4. If still failing after 4 runs, set a flag to create a **draft PR**
   instead of a real PR. Include a "Quality Gate Failed" section in
   the PR body with the last error output. Draft PRs cannot be
   accidentally merged, giving reviewers a clear signal.

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
   - **Labels**: apply the appropriate type and priority labels. Run
     label validation (check existence, create if missing) before
     applying:
     ```
     gh label list --repo {org}/{repo} --json name --jq '.[].name'
     gh label create "{label}" --repo {org}/{repo} --description "{desc}" --force
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

   Record the new issue number for use in Step 5.

The issue number (from context, branch, or newly created) is used in
Step 5 to add `Closes #N` to the PR body.

### 5. Create new PR

Build the PR body from the committed changes:

- Summarize what was built (from commit messages and diff)
- List acceptance criteria addressed
- Note any technical decisions made
- Add a test plan section

Write the PR body to a temporary file first, then create the PR
using `--body-file` to avoid Windows/PowerShell shell-escaping issues.
If the quality gate failed (Step 2), create a draft:

```
# Normal case — quality gate passed:
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}

# Quality gate failed — create draft instead:
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile} --draft
```

Delete the temp file after creation.

When creating a draft PR due to quality gate failure, prepend a section
to the body:

```
> **⚠ Quality gate failed** — this PR was opened as a draft because
> the quality gate did not pass after 4 attempts. See error details
> below. Convert to ready-for-review after fixing.
>
> **Last error:**
> {quality_gate_error_output}
```

Each linked issue gets its own line in the PR body:

```
Closes #42
Closes #43
```

Each `Closes #N` must be on its own line so GitHub links them in
the Development sidebar.

### 5b. Validate PR body

After creating or updating the PR, immediately read it back and
verify the body was written correctly:

```
gh pr view {pr_number} --repo {org}/{repo} --json body --jq '.body'
```

If the body is empty, only whitespace, or consists of just `@` (a
known Windows/PowerShell shell-escaping issue):

1. Write the intended body to a temporary file.
2. Update the PR using `--body-file`:
   ```
   gh pr edit {pr_number} --repo {org}/{repo} --body-file {tempfile}
   ```
3. Delete the temporary file.
4. Re-read the PR to confirm the fix.
5. If still corrupted after retry, warn the user.

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
  depended on): apply the `needs-re-review` label so the reviewer
  evaluates the rebased result:
  ```
  gh pr edit {pr_number} --add-label "{needs_re_review_label}"
  ```

  After applying, verify the label is present (same as Step 7 below).
  If missing, create it and retry.

### 7. Add labels to PR

Resolve the `claude-authored` purpose key to its concrete name through
the single path in `templates/default-labels.md` (the `ClaudeProject.md`
label map, default `claude-authored`), then apply it to mark this as a
Claude-built PR:

```
gh pr edit {pr_number} --add-label "{claude_authored_label}"
```

After applying, verify the label was applied:

```
gh pr view {pr_number} --repo {org}/{repo} --json labels --jq '[.labels[].name]'
```

If missing, the label was not created at setup. Create it with the
guarded create-if-missing pattern from `templates/default-labels.md` —
**without `--force`** so existing metadata is never overwritten — then
retry:

```
gh label create "{claude_authored_label}" --repo {org}/{repo} --description "Built by Claude" --color "5319E7"
gh pr edit {pr_number} --add-label "{claude_authored_label}"
```

### 8. Update project board (if configured)

Set status to In Review:

```
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{project_node_id}"
    itemId: "{item_id}"
    fieldId: "{status_field_id}"
    value: { singleSelectOptionId: "{in_review_option_id}" }
  }) { projectV2Item { id } }
}'
```

Board operations are best-effort. If they fail, report the failure to
the user (e.g., "Board update failed: {error}. Continuing without board
update.") and proceed with the rest of the workflow.

### 9. Report

Display:

- PR URL
- Linked issue(s)
- Labels applied
- Board status (if updated)
