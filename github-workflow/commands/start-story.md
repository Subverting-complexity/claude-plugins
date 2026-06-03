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

Multiple agents may be running concurrently — possibly under the same
GitHub identity, where assignment cannot exclude a rival. Acquire the
issue with the atomic claim procedure in `templates/claim-procedure.md`
(**Acquire**). It pushes a unique object to `refs/claims/issue-{number}`,
which is a genuine server-side compare-and-swap: the first agent wins and
proceeds; a losing agent exits cleanly having made no changes.

If Acquire reports the claim is lost, stop — another agent owns this
story. Do not assign, branch, or touch the board. If `pick-story` already
claimed this issue in the same flow, Acquire's re-entry check treats it as
a no-op and proceeds. Acquire performs the durable ownership markers for
you — it assigns `@me` **and** moves the issue to the `status-in-progress`
lifecycle label (removing `status-ready` or any prior lifecycle label, so
exactly one state is present). Do not assign or set a status label
separately; just verify the read-back per `templates/default-labels.md`.

### 3. Update project board (if configured)

First resolve the board, the issue's `{item_id}`, and the target column's
`{column_option_id}` following `templates/board-resolution.md`. That step
decides whether a board is configured at all, verifies the stored
`project-node-id` still resolves to a board whose title matches
`project-title` (aborting loudly on a mismatch), adds the issue to the
board if it is not there yet, and resolves the target column by purpose
key. The target column for `status-in-progress` is **In Progress**
(`col-in-progress`) per the label ⇄ column pairing in
`templates/default-labels.md`. Only proceed with the mutations below once
it has handed back a verified `{item_id}` and `{column_option_id}`.

Set status to In Progress:

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

If `git checkout {branch}` fails because the branch is **already checked
out in another worktree**, that is a lost claim — another agent on this
machine owns the work. Stop and exit cleanly per the claim-procedure
**Lost-claim path**: change nothing, fork nothing. (With the atomic claim
in step 2 this is rare, but a lingering worktree can still hold the
branch.)

If the rebase fails with conflicts, do **not** fork a parallel branch.
Abort and block the story so the divergence can be resolved deliberately:

```
git rebase --abort
```

Then run `/github-workflow:block-story` with the conflict details. The
atomic claim in step 2 guarantees no rival agent shares this branch, so a
conflict is a genuine divergence to resolve — never a collision to route
around with a `-retry` fork.

If the branch does not exist, create it:

```
git checkout -b {branch} origin/{default-branch}
```
