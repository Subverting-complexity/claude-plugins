# Default Labels

All skills that apply labels use these defaults. Project configuration
overrides them — `ClaudeProject.md` for workflow labels,
`review.config.md` for review state labels. When no override is
configured, use the names and colors below.

## Label Resolution

When a skill needs a label name:

1. Check the project config (ClaudeProject.md label map or
   review.config.md) for the label purpose.
2. If configured, use that name.
3. If not configured, use the default name from this file.

Before applying any label, ensure it exists on the repo. If missing,
create it:

```
gh label create "{name}" --repo {org}/{repo} --description "{description}" --color "{color}" --force
```

After applying labels, verify they were applied by reading back:

```
gh issue view {number} --json labels --jq '[.labels[].name]'
gh pr view {number} --json labels --jq '[.labels[].name]'
```

If a label is missing after apply, the label likely didn't exist and
`gh` silently skipped it. Create it and retry once.

## Workflow Labels

These control issue management — typing, prioritization, and status.
Overridden by the label map in `ClaudeProject.md`.

| Purpose | Default Name | Color | Description |
|---------|-------------|-------|-------------|
| Story type | `type-story` | `1D76DB` | Feature story |
| Bug type | `type-bug` | `D93F0B` | Bug fix |
| Security type | `type-security` | `B60205` | Security issue |
| Debt type | `type-debt` | `FBCA04` | Technical debt |
| Arch type | `type-arch` | `0E8A16` | Architecture issue |
| Critical priority | `priority-critical` | `B60205` | Critical priority |
| High priority | `priority-high` | `D93F0B` | High priority |
| Medium priority | `priority-medium` | `FBCA04` | Medium priority |
| Low priority | `priority-low` | `0E8A16` | Low priority |
| Ready status | `status-ready` | `0E8A16` | Ready for pickup |
| Claude-authored | `claude-authored` | `5319E7` | Built by Claude |
| Claude-ready | `claude-ready` | `1D76DB` | Approved for agent work |

## Review State Labels

These control the PR review workflow. Overridden by label definitions
in `review.config.md`. Default prefix: `review`.

State labels are mutually exclusive — exactly one per PR.

| Purpose | Default Name | Color | Description |
|---------|-------------|-------|-------------|
| Reviewing | `review-reviewing` | `0E8A16` | Review in progress |
| Approved | `review-approved` | `1D76DB` | Ready for human merge |
| Changes requested | `review-changes-requested` | `E4E669` | Issues need human action |
| Needs discussion | `review-needs-discussion` | `D93F0B` | Architectural questions |
| Needs re-review | `review-needs-re-review` | `FBCA04` | New commits since last review |
| Review failed | `review-review-failed` | `B60205` | Review could not complete |
| Updating | `review-updating` | `0E8A16` | Builder addressing feedback |
| Fixes applied | `review-fixes-applied` | `5319E7` | Claude pushed fix commits (sticky) |
