---
description: 'Assign a story, update the board, and create a branch. Trigger: "start story N", "begin working on N", "assign me story N".'
---

# Start Story

Assign the story, update the board, and create a working branch.

Requires: a story number. If no number is provided, run the
`/github-workflow:pick-story` flow to auto-select the next story and
use that number. Do not ask the user which story to start.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo`, `default-branch` from Identity
- Branch convention pattern
- Project board settings (if configured)
- Label map

### 2. Claim the issue

Multiple agents may be running concurrently. Use assignment as a claim
lock to prevent two agents from starting the same story:

```
gh issue edit {number} --repo {org}/{repo} --add-assignee @me
```

Wait 2 seconds, then re-read the issue to verify your claim:

```
gh issue view {number} --repo {org}/{repo} --json assignees
```

If you are the only assignee, proceed. If another user or agent was
assigned first (multiple assignees), remove yourself and exit — the
other agent owns this story:

```
gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
```

### 3. Update project board (if configured)

First resolve the board and the issue's `{item_id}` following
`templates/board-resolution.md`. That step decides whether a board is
configured at all, verifies the stored `project-node-id` still resolves
to a board whose title matches `project-title` (aborting loudly on a
mismatch), and adds the issue to the board if it is not there yet. Only
proceed with the mutations below once it has handed back a verified
`{item_id}`.

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

When **no** board is configured, skip this step silently. When a board
**is** configured, board failures are loud: report the failure to the
user (e.g., "Board update failed: {error}. Continuing without board
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

Apply the branch convention from config. To generate `{short-desc}`
from the issue title:

1. Lowercase the title
2. Replace spaces and special characters with hyphens
3. Remove consecutive hyphens
4. Truncate to 40 characters max
5. Remove trailing hyphens

Example: issue "Fix: User login broken!!!" with convention
`feature/{number}/{short-desc}` → `feature/42/fix-user-login-broken`

Check if the branch already exists (from a previous blocked attempt or
partial work):

```
git branch --list {branch}
git ls-remote --heads origin {branch}
```

If the branch exists locally or remotely, check it out and rebase onto
the latest default branch:

```
git checkout {branch}
git rebase origin/{default-branch}
```

If rebase fails with conflicts, abort and recreate the branch:

```
git rebase --abort
git checkout -b {branch}-retry origin/{default-branch}
```

Use the `-retry` branch and note in the PR that the original branch
had conflicts.

If the branch does not exist, create it:

```
git checkout -b {branch} origin/{default-branch}
```
