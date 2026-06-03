---
description: 'Mark the current story as blocked. Trigger: "blocked", "I''m stuck", "can''t continue", "this is blocked by", "stuck on", "waiting for", "dependency issue", "can''t proceed".'
---

# Block Story

Mark the current story as blocked and record the reason.

Requires: a story in progress with a known blocker.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo` from Identity
- Project board settings (if configured)
- Label map (for status labels)

If `ClaudeProject.md` is missing or has no label map, use the default
label names from `templates/default-labels.md`. When using defaults in
an interactive session, warn the user: "Label map not configured —
using default labels. Run `/github-workflow:setup` to configure labels
for this project."

### 2. Comment the blocker

Write the comment body to a temporary file and post using `--body-file`
(avoids Windows shell-escaping issues with multi-line content):

```
gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
```

The comment should include: the blocker reason, what was attempted,
what failed or is missing, and a suggested resolution if known.
Delete the temp file after.

### 3. Release the claim and unassign

Release the atomic claim ref so the issue can be claimed again, following
`templates/claim-procedure.md` (**Release**), then remove the assignee so
the issue returns to the unassigned pool and can be picked up by another
agent or re-picked later:

```
git push origin :refs/claims/issue-{number}
gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
```

The claim-ref delete is idempotent — ignore an error if the ref is
already gone.

### 4. Remove from ready state

Remove the issue from the ready state so it cannot re-enter the pick
pool while blocked. What to do depends on `ready-gate`:

- **`label` or `both`**: remove the `status-ready` label:
  ```
  gh issue edit {number} --repo {org}/{repo} --remove-label "{status_ready_label}"
  ```
- **`board-column` or `both`**: move the issue back to "Backlog" (or
  "On Hold" if configured) on the project board.

Do NOT apply a "blocked" label. The dependency information lives in
the issue body (`## Dependencies` section) and in the comment from
Step 2. The absence of ready state is sufficient to keep the issue
out of the pick pool.

These commands are idempotent — the label remove will no-op if the
label is not present.

### 5. Update project board (if configured)

First resolve the board and the issue's `{item_id}` following
`templates/board-resolution.md` (board-configured check, identity
verification by title, add-to-board-if-missing). Only run the mutation
below once it returns a verified `{item_id}`.

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

When **no** board is configured, skip this step silently. When a board
**is** configured, board failures are loud: report the failure to the
user (e.g., "Board update failed: {error}. Continuing without board
update.") and proceed with the rest of the workflow.

### 6. Leave the work in place

Do **not** `git stash` — the stash is shared across every worktree on
this clone, so shelving here can collide with another agent's work.
Committed work stays on the story branch (preserved under the claim);
uncommitted scratch work stays in this worktree, left as-is for a later
session to inspect. Releasing the claim (above) returns the story to the
backlog without disturbing the working tree.

### 7. Report

Display what was blocked — naming the story by number **and** title
together (e.g. `#42 Add login button`, never the number alone) — why,
and that the story has been blocked and returned to the backlog.
Suggest running `/github-workflow:pick-story` to continue with the next story.
