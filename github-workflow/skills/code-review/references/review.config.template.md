# Review Configuration — {PROJECT_NAME}

## Repository

- Org: {ORG}
- Repo: {REPO}
- Default branch: {DEFAULT_BRANCH}

## Labels

Replace `{PREFIX}` with your label prefix (e.g., `claude`, `review`,
`cr`). All state labels use this prefix so they're easy to filter.

State labels are mutually exclusive — exactly one is applied per review.

| Label | Type | Meaning |
| ----- | ---- | ------- |
| `{PREFIX}-reviewing` | State | Review in progress — prevents concurrent reviews |
| `{PREFIX}-approved` | State | No remaining issues, ready for human merge |
| `{PREFIX}-changes-requested` | State | Concrete problems remain that a human must address |
| `{PREFIX}-needs-discussion` | State | Architectural or scope questions need human judgment |
| `{PREFIX}-needs-re-review` | State | New commits pushed since last review — re-review required |
| `{PREFIX}-review-failed` | State | Review could not be completed (checkout failed, PR too large) |
| `{PREFIX}-fixes-applied` | Action | Claude pushed fix commits to the PR branch (sticky across runs) |

These labels are separate from the Claude labels in `ClaudeProject.md`.
Claude labels are simple workflow markers; these labels form a state
machine managed by the code-review skill.

## Custom Labels

Additional labels applied to PRs based on project-specific criteria.
These are applied alongside (not instead of) the state labels above.
Remove this section if you don't use custom labels.

| Label | When to apply |
| ----- | ------------- |
| `{LABEL}` | {CRITERIA} |

## Hard Non-Compliance Gates

Any of these force a `Changes Requested` verdict regardless of all other
findings.

{GATES}

## Tech Stack Review Rules

These are project-specific checks to run in addition to the generic review.

{TECH_STACK_RULES}

## Architecture Rules

{ARCHITECTURE_RULES}

## Security Specifics

{SECURITY_RULES}

## Test Expectations

{TEST_EXPECTATIONS}

## Review Comment Footer

```
---
Reviewed at <SHA>
🤖 Reviewed with Claude Code
```

The `Reviewed at <SHA>` line is machine-parsed by future runs to detect
whether the PR has changed since the last review.
