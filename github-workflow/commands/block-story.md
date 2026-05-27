---
description: 'Mark the current story as blocked. Trigger: "blocked", "I''m stuck", "can''t continue", "this is blocked by".'
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

### 3. Add blocked label

If a `status-blocked` or `claude-blocked` label is configured:

```
gh issue edit {number} --repo {org}/{repo} --add-label "{blocked_label}"
```

### 4. Update project board (if configured)

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

### 5. Shelve work

If there are uncommitted changes:

```
git stash push -m "blocked-{number}: {short_reason}"
```

Switch back to the default branch:

```
git checkout {default-branch}
```

### 6. Report

Display what was blocked, why, and that the story has been shelved.
Suggest running `/github-workflow:pick-story` to continue with the next story.
