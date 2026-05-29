---
description: 'Push the branch, create a PR, and update the board. Trigger: "finish", "done", "open a PR", "ship it", "create the PR", "submit", "wrap up", "push it", "send for review".'
---

# Finish Story

Push the branch, create a PR, and update the board.

Requires: a story in progress with committed work on a feature branch.

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
gh pr edit {pr_number} --body "{updated_body}"
```

Skip to Step 6 (labels). Only create a new PR if none exists.

### 5. Create new PR

Build the PR body from the committed changes:

- Summarize what was built (from commit messages and diff)
- List acceptance criteria addressed
- Note any technical decisions made
- Add a test plan section

Create the PR. If the quality gate failed (Step 2), create a draft:

```
# Normal case — quality gate passed:
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body "{body}"

# Quality gate failed — create draft instead:
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body "{body}" --draft
```

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

### 7. Add labels to PR

If the `claude-authored` label is configured in the label map, apply it
to mark this as a Claude-built PR:

```
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
