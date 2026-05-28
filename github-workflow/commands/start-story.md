---
description: 'Assign a story, update the board, and create a branch. Trigger: "start story N", "begin working on N", "assign me story N".'
---

# Start Story

Assign the story, update the board, and create a working branch.

Requires: a story number. If no number is provided, run the
`/github-workflow:pick-story` flow to auto-select the next story and
use that number. Do not ask the user which story to start.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo`, `default-branch` from Identity
- Branch convention pattern
- Project board settings (if configured)
- Label map

### 2. Assign the issue

```
gh issue edit {number} --repo {org}/{repo} --add-assignee @me
```

### 3. Update project board (if configured)

Only if `ClaudeProject.md` has a Project Board section with field IDs.

Set status to In Progress:

```
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{project_node_id}"
    itemId: "{item_id}"
    fieldId: "{status_field_id}"
    value: { singleSelectOptionId: "{in_progress_option_id}" }
  }) { projectV2Item { id } }
}'
```

Set start date to today:

```
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{project_node_id}"
    itemId: "{item_id}"
    fieldId: "{start_date_field_id}"
    value: { date: "{today}" }
  }) { projectV2Item { id } }
}'
```

Board operations are best-effort. If they fail, report the failure to
the user (e.g., "Board update failed: {error}. Continuing without board
update.") and proceed with the rest of the workflow.

### 4. Validate the issue body

Read the issue body. Check that it has at minimum:

- **Context** — what the story is about and why
- **Requirements** — acceptance criteria or expected behavior

If the issue body is empty or has no actionable guidance, flag it.
If linked docs or comments provide enough context, proceed anyway.
If truly empty with no guidance anywhere, run `/github-workflow:block-story`.

### 5. Create branch

```
git fetch origin {default-branch}
```

Apply the branch convention from config. For example, if the convention
is `feature/{number}/{short-desc}`, create `feature/42/add-user-auth`.

Check if the branch already exists (from a previous blocked attempt or
partial work):

```
git branch --list {branch}
```

If the branch exists locally, check it out and rebase onto the latest
default branch:

```
git checkout {branch}
git rebase origin/{default-branch}
```

If the branch does not exist, create it:

```
git checkout -b {branch} origin/{default-branch}
```
