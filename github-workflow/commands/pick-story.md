---
description: 'Pick the next story from the backlog without starting it. Trigger: "what''s next", "pick a story", "show me the next story", "what should I work on", "next issue", "show backlog", "what''s in the queue", "grab a story".'
---

# Pick Story

Select the next story from the backlog. Before looking for new work,
check for stale in-progress stories that can be reclaimed.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org` and `repo` from Identity
- `default-branch` from Identity
- `branch-convention` from Branch Convention
- Label map (priority labels, status labels, type labels)
- `stale-timeout` from Session Budget (default: 2 hours if not set)

### 1b. Reclaim stale in-progress stories

Before picking new work, check for issues that were assigned but never
completed — the previous session may have timed out, crashed, or lost
context.

List issues assigned to the current agent that are still open:

```
gh issue list --repo {org}/{repo} --state open --assignee @me --json number,title,labels,updatedAt
```

For each assigned issue, check whether meaningful progress was made:

1. **Check for a PR** linking this issue:
   ```
   gh pr list --repo {org}/{repo} --state open --json number,title,body,headRefName --jq '.[] | select(.body | test("Closes #{number}|Fixes #{number}|Resolves #{number}"))'
   ```

2. **Check for a branch** matching the branch convention for this issue
   number:
   ```
   git ls-remote --heads origin | grep -i "{number}"
   ```

3. **Check staleness** — compute how long ago the issue was last
   updated. If the `updatedAt` timestamp is older than `stale-timeout`:

**If a PR exists:** The story has a PR but no session is working on it.
Report it as available for continuation rather than picking a new story.
Display the PR and suggest running `/github-workflow:update-pr` if it
has review feedback, or resuming the branch if it's still in progress.

**If a branch exists but no PR:** The previous session pushed code but
didn't finish. Report this — the user or next session should check out
the branch, verify the state, and either finish or block the story.

**If neither branch nor PR exists and the issue is stale:** The
previous session claimed the issue but produced nothing. Reclaim it:

```
gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
```

Add a comment explaining the reclamation:

```
gh issue comment {number} --repo {org}/{repo} --body "Automatically unassigned — no branch or PR was created within the stale timeout. This issue is available for pickup again."
```

The reclaimed issue is now eligible for the normal pick logic below.

**If the issue is not stale yet:** Skip it — another session may still
be actively working on it.

### 2. Detect backlog mode

Check for milestones with open issues:

```
gh api repos/{org}/{repo}/milestones --jq 'sort_by(.due_on) | .[] | select(.open_issues > 0) | {title, due_on, open_issues}'
```

- **Milestones with due dates and open issues exist** → Sprint mode
- **Otherwise** → Flat backlog mode

### 3a. Sprint mode — find current sprint

Pick the earliest milestone (by due date) that has open issues.
This is the current sprint — no hardcoded sprint order needed.

List candidate issues in that milestone:

```
gh issue list --repo {org}/{repo} --milestone "{sprint_title}" --state open --assignee "" --json number,title,labels --jq '.[] | {number, title, labels: [.labels[].name]}'
```

Sort candidates:

1. By priority label (critical → high → medium → low, using label map)
2. By issue number ascending

If a `status-ready` label is configured in the label map, prefer
issues that have it. If none do, fall back to all unassigned issues.

### 3b. Flat backlog mode

List candidate issues:

```
gh issue list --repo {org}/{repo} --state open --assignee "" --label "{status_ready_label}" --json number,title,labels --jq '.[] | {number, title, labels: [.labels[].name]}'
```

Sort by priority label, then issue number.

If no `status-ready` label is configured, list all open unassigned issues.

### 4. Select and display

Pick the first candidate. Display:

- Issue number, title, and URL
- Sprint/milestone (if applicable)
- Priority and type labels
- Brief summary of the issue body

Store the selected issue number for subsequent commands.
