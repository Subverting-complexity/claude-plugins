---
description: Select the next unassigned story from the backlog
---

# Pick Story

Select the next unassigned story from the backlog.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org` and `repo` from Identity
- Label map (priority labels, status labels, type labels)

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
