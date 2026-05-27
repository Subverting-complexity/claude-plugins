---
description: Push the branch, create a PR, and update the board
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

### 2. Push the branch

```
git push -u origin HEAD
```

### 3. Create PR

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

### 4. Add labels to PR

If claude labels are configured in the label map, apply them:

```
gh pr edit {pr_number} --add-label "{claude_reviewed_label}"
```

### 5. Update project board (if configured)

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

If board operations fail, log a warning and continue.

### 6. Report

Display:

- PR URL
- Linked issue(s)
- Labels applied
- Board status (if updated)
