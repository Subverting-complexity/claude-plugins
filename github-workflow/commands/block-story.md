---
description: 'Mark the current story as blocked. Trigger: "blocked", "I''m stuck", "can''t continue", "this is blocked by", "stuck on", "waiting for", "dependency issue", "can''t proceed".'
---

# Block Story

Mark the current story as blocked and record the reason.

Requires: a story in progress with a known blocker.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo` from Identity
- Project board settings (if configured)
- Label map (for blocked labels)

### 2. Comment the blocker

```
gh issue comment {number} --repo {org}/{repo} --body "**Blocked**: {reason}

Blocked during automated execution. Details:
- What was attempted
- What failed or is missing
- Suggested resolution (if known)"
```

### 3. Unassign the issue

Remove the current assignee so the issue returns to the unassigned pool
and can be picked up by another agent or re-picked later:

```
gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
```

### 4. Add blocked label

Apply the `status-blocked` label if configured. If no `status-blocked`
label exists, fall back to the `claude-blocked` label. Apply whichever
is available — if both are configured, prefer `status-blocked`.

```
gh issue edit {number} --repo {org}/{repo} --add-label "{blocked_label}"
```

### 5. Update project board (if configured)

Set status to On Hold:

```
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{project_node_id}"
    itemId: "{item_id}"
    fieldId: "{status_field_id}"
    value: { singleSelectOptionId: "{on_hold_option_id}" }
  }) { projectV2Item { id } }
}'
```

Board operations are best-effort. If they fail, report the failure to
the user (e.g., "Board update failed: {error}. Continuing without board
update.") and proceed with the rest of the workflow.

### 6. Shelve work

If there are uncommitted changes:

```
git stash push -m "blocked-{number}: {short_reason}"
```

Switch back to the default branch:

```
git checkout {default-branch}
```

### 7. Report

Display what was blocked, why, and that the story has been shelved.
Suggest running `/github-workflow:pick-story` to continue with the next story.
