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

For each assigned issue, check for existing work and staleness:

1. **Check for a PR** linking this issue:
   ```
   gh pr list --repo {org}/{repo} --state open --json number,title,body,headRefName,labels --jq '.[] | select(.body | test("Closes #{number}|Fixes #{number}|Resolves #{number}"))'
   ```

2. **Check for a branch** matching the branch convention for this issue
   number:
   ```
   git ls-remote --heads origin | grep -i "{number}"
   ```

3. **Check staleness** — compute how long ago the issue was last
   updated. If the `updatedAt` timestamp is older than `stale-timeout`:

**If PR or issue has the `approved` label:** Skip entirely — waiting
for human merge, do not touch.

**If a PR exists with review feedback** (`changes-requested` or
`needs-discussion` label): Check out the branch and run
`/github-workflow:update-pr` to address the feedback autonomously.

**If a PR exists without review feedback:** Check out the branch and
assess state. If code looks complete, push to finish (PR updates,
labels). If incomplete, continue building from where it left off.

**If a branch exists but no PR:** Check out the branch and assess. If
it has meaningful commits, continue toward finishing. If it has no
meaningful work, delete the branch and reclaim the issue.

**If neither branch nor PR exists and the issue is stale:** The
previous session claimed the issue but produced nothing. Reclaim it:

```
gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
```

Add a comment explaining the reclamation:

```
gh issue comment {number} --repo {org}/{repo} --body "Automatically unassigned — no progress detected within the stale timeout ({stale_timeout}). This issue is available for pickup again."
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

Filter out issues with the `approved` label (e.g., `claude-approved`,
`claude:approved`, or whatever is configured in the label map). These
are waiting for human merge and must not be picked up.

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

Filter out issues with the `approved` label.

Sort by priority label, then issue number.

If no `status-ready` label is configured, list all open unassigned issues.

### 4. Select and display

**Never ask the user which story to pick.** Always auto-select using
the sort order above. If no candidates have priority labels, pick the
lowest issue number. If the user says "pick a story" or "what's next",
that means "give me the top one", not "show me a list to choose from".

Pick the first candidate. Display:

- Issue number, title, and URL
- Sprint/milestone (if applicable)
- Priority and type labels
- Brief summary of the issue body

Store the selected issue number for subsequent commands.
