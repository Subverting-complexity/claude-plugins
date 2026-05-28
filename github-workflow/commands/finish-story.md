---
description: 'Push the branch, create a PR, and update the board. Trigger: "finish", "done", "open a PR", "ship it", "create the PR", "submit", "wrap up", "push it", "send for review".'
---

# Finish Story

Push the branch, create a PR, and update the board.

Requires: a story in progress with committed work on a feature branch.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo`, `default-branch` from Identity
- Project board settings (if configured)
- Label map (for claude labels)

### 2. Run the quality gate

Run the quality gate command from `ClaudeProject.md` to verify the code
is clean before pushing:

1. Execute the quality gate script/command.
2. If it fails, read the error output, fix the issue, and re-run.
3. Repeat up to 3 times. If still failing, warn the user but continue
   to push — they may want to open the PR for review anyway.

### 3. Push the branch

```
git push -u origin HEAD
```

### 4. Create PR

Build the PR body from the committed changes:

- Summarize what was built (from commit messages and diff)
- List acceptance criteria addressed
- Note any technical decisions made
- Add a test plan section

Create a real PR (not a draft):

```
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body "{body}"
```

Each linked issue gets its own line in the PR body:

```
Closes #42
Closes #43
```

Each `Closes #N` must be on its own line so GitHub links them in
the Development sidebar.

### 5. Add labels to PR

If the `claude-authored` label is configured in the label map, apply it
to mark this as a Claude-built PR:

```
gh pr edit {pr_number} --add-label "{claude_authored_label}"
```

### 6. Update project board (if configured)

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

### 7. Report

Display:

- PR URL
- Linked issue(s)
- Labels applied
- Board status (if updated)
