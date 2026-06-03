---
description: 'Pick the next story from the backlog without starting it. Supports mode filtering: default picks highest priority regardless of type, --mode feature for features only, --mode maintenance for bugs/security/arch/debt. Trigger: "what''s next", "pick a story", "show me the next story", "what should I work on", "next issue", "show backlog", "what''s in the queue", "grab a story", "next bug", "next maintenance item", "next feature".'
---

# Pick Story

Select the next story from the backlog. Before looking for new work,
check for stale in-progress stories that can be reclaimed.

## Mode

This command accepts an optional mode argument:

- **story** (default) — Pick the highest priority issue regardless of type
- **feature** — Pick only feature stories (type-story label)
- **maintenance** — Pick the next bug, security, architecture, or tech debt issue (alias: bug)

If mode is "bug", treat it as "maintenance".

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Project configuration (auto-loaded)

```!
if [ -f ClaudeProject.md ]; then
  cat ClaudeProject.md
else
  echo "ClaudeProject.md NOT FOUND — run /github-workflow:setup first."
fi
```

## Steps

### 1. Read configuration

Extract from the project configuration above:

- `org` and `repo` from Identity
- `default-branch` from Identity
- `branch-convention` from Branch Convention
- Label map (priority labels, status labels, type labels, claude labels)
- `agent-gating` from Agent Gating (`enabled` or `disabled`, default: `disabled`)
- `claude-ready` label name from the Claude label map (only needed when gating is enabled)
- `stale-timeout` from Session Budget (default: 2 hours if not set)
- `ready-gate` from Ready Gate (`label`, `board-column`, or `both`; default: `label`)
- Project board settings (if `ready-gate` is `board-column` or `both`)

Resolve every label name by **purpose key** through the single path in
`templates/default-labels.md` — the label map for workflow purposes
(`status-ready`, `priority-*`, `type-*`, claude markers) and
`review.config.md` for the review-state purposes used in stale recovery
(`approved`, `changes-requested`, `needs-discussion`). The bare names in
the steps below are purpose keys: resolve them, never filter on a bare
name literally, so the strings this command skips on match the strings
the review skills apply. When falling back to defaults in an interactive
session, warn the user: "Label map not configured — using default
labels. Run `/github-workflow:setup` to configure labels for this
project."

### 1b. Reclaim stale in-progress stories

Before picking new work, check for issues that were assigned but never
completed — the previous session may have timed out, crashed, or lost
context.

**Batch query** — Fetch all assigned issues with their linked PRs in a
single GraphQL call instead of N individual API requests:

```
gh api graphql -f query='
query($owner: String!, $repo: String!, $assignee: String!) {
  repository(owner: $owner, name: $repo) {
    issues(states: OPEN, filterBy: {assignee: $assignee}, first: 20) {
      nodes {
        number
        title
        updatedAt
        labels(first: 10) { nodes { name } }
        timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: 10) {
          nodes {
            ... on CrossReferencedEvent {
              source {
                ... on PullRequest {
                  number
                  headRefName
                  state
                  labels(first: 10) { nodes { name } }
                }
              }
            }
          }
        }
      }
    }
  }
}' -f owner="{org}" -f repo="{repo}" -f assignee="@me"
```

This returns each assigned issue with its linked PRs (via cross-reference
events), their branch names, and labels — all in one API call.

For issues without a linked PR in the GraphQL response, check for a
branch matching the branch convention:
```
git ls-remote --heads origin | grep -i "{number}"
```

Determine staleness from the `updatedAt` timestamp. If older than
`stale-timeout`:

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

### 1c. Auto-ready resolved dependencies

Before picking new work, check issues assigned to `@me` that are not
in the ready state. How to detect "not ready" depends on `ready-gate`:

- **`label`**: issues without the `status-ready` label.
- **`board-column`**: issues not in the "Ready" board column.
- **`both`**: issues missing EITHER the label OR the board column.

For each non-ready issue, read the issue body and look for dependency
markers (see Step 3c). If all referenced issues are now closed, the
dependencies are resolved — mark the issue as ready:

- **`label` or `both`**: apply the `status-ready` label:
  ```
  gh issue edit {number} --repo {org}/{repo} --add-label "{status_ready_label}"
  ```
  After applying, verify the label is present. If missing, create it
  with `gh label create --force` using the color from
  `templates/default-labels.md` and retry once.
- **`board-column` or `both`**: move the issue to the "Ready" column
  on the project board (using the `ready-option-id` from board config):
  ```
  gh api graphql -f query='mutation {
    updateProjectV2ItemFieldValue(input: {
      projectId: "{project_node_id}"
      itemId: "{item_id}"
      fieldId: "{status_field_id}"
      value: { singleSelectOptionId: "{ready_option_id}" }
    }) { projectV2Item { id } }
  }'
  ```
- Add a comment:
  ```
  gh issue comment {number} --repo {org}/{repo} --body "Dependencies resolved — all blocking issues are now closed. Returning to the ready pool."
  ```

The unblocked issue is now eligible for normal picking below.

This step is best-effort. If the dependency check fails (API error,
unparseable body), skip the issue and continue.

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
gh issue list --repo {org}/{repo} --milestone "{sprint_title}" --state open --assignee "" --json number,title,labels,body --jq '.[] | {number, title, labels: [.labels[].name], body}'
```

Filter out issues that have **any** of these labels:
- The `approved` label — waiting for human merge.

**Agent gating:** If `agent-gating` is `enabled`, also filter out
issues that do **not** have the `claude-ready` label. Only
human-approved stories are eligible.

Sort candidates:

1. By priority label (critical → high → medium → low, using label map)
2. By issue number ascending

Apply the ready-gate filter to prefer ready issues (see below).

### 3b. Flat backlog mode

List candidate issues. How to find ready candidates depends on
`ready-gate`:

- **`label`**: filter by `status-ready` label:
  ```
  gh issue list --repo {org}/{repo} --state open --assignee "" --label "{status_ready_label}" --json number,title,labels,body --jq '.[] | {number, title, labels: [.labels[].name], body}'
  ```
- **`board-column`**: query the project board for issues in the
  "Ready" column:
  ```
  gh api graphql -f query='query { node(id: "{project_node_id}") { ... on ProjectV2 { items(first: 100) { nodes { fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } content { ... on Issue { number title labels(first:10) { nodes { name } } body state assignees(first:1) { nodes { login } } } } } } } } }'
  ```
  Filter to items where Status is "Ready", state is OPEN, and
  assignees is empty.
- **`both`**: use the label query, then confirm each candidate is also
  in the "Ready" board column. Drop candidates not in both.

Filter out issues with the `approved` label.

**Agent gating:** If `agent-gating` is `enabled`, also filter out
issues that do **not** have the `claude-ready` label.

Sort by priority label, then issue number.

If no ready gate is configured (no `status-ready` label and no board),
list all open unassigned issues.

### 3b-1. Apply mode filter

After assembling the candidate list (from either sprint or flat mode),
apply type-based filtering based on mode:

- **Story mode** (default): no type filter. Pick the highest priority
  issue regardless of its type label. This is the most common mode.
- **Feature mode**: keep only issues with the type-story label (from
  the label map). If no type-story issues exist, report "No feature
  stories available" and exit.
- **Maintenance mode**: keep only issues with type-bug, type-security,
  type-arch, or type-debt labels (from the label map).

The filtered list then proceeds to Step 3c (dependency checking).

### 3c. Filter out issues with unresolved dependencies

Before selecting a candidate, check the top 10 candidates for
dependency markers. Scan each issue's body for lines matching any of
these patterns (case-insensitive):

- `Depends on #N`
- `Blocked by #N`
- `After #N`
- `Requires #N`

Also check the `## Dependencies` section if present — look for
`#N` references to other issues in that section.

For each referenced issue number, check its state:

```
gh issue view {dep_number} --repo {org}/{repo} --json state --jq '.state'
```

If **any** referenced issue is still `OPEN`, skip the candidate —
it has unresolved dependencies. Move to the next candidate in
priority order.

To limit API calls, check at most 10 candidates and at most 5
dependency references per candidate. If a candidate has more than 5
dependencies, treat it as blocked (likely a meta-issue).

### 3d. Close already-completed issues

Before selecting a candidate, check the top candidates for issues that
have already been resolved. For each candidate, check if a merged PR
references it:

```
gh pr list --repo {org}/{repo} --search "closes #{number} OR fixes #{number}" --state merged --json number,title --jq '.[0]'
```

If a merged PR exists that closes or fixes this issue, the issue should
already be closed but GitHub may not have auto-linked it. Close the
issue:

```
gh issue close {number} --repo {org}/{repo} --comment "Closing — this issue was already resolved by #{pr_number}."
```

Skip the closed issue and move to the next candidate.

To limit API calls, check at most 5 candidates this way. If more need
checking, let them be caught on subsequent pick runs.

### 4. Select and display

**Never ask the user which story to pick.** Always auto-select using
the sort order above. If no candidates have priority labels, pick the
lowest issue number. If the user says "pick a story" or "what's next",
that means "give me the top one", not "show me a list to choose from".

If no candidates remain after filtering, report "No stories available
for pickup" and exit. Do not loop, retry, or ask the user to create
stories.

Pick the first candidate. Display:

- Issue number, title, and URL
- Sprint/milestone (if applicable)
- Priority and type labels
- Brief summary of the issue body

Store the selected issue number for subsequent commands.
