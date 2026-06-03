# Review Configuration — {PROJECT_NAME}

## Repository

- Org: {ORG}
- Repo: {REPO}
- Default branch: {DEFAULT_BRANCH}

## Labels

Replace `{PREFIX}` with your label prefix (e.g., `claude`, `review`,
`cr`). All state labels use this prefix so they're easy to filter.

The **Purpose** column is the stable identity skills resolve against —
it never changes even when you pick a custom prefix. Producers and
consumers look a label up by purpose (see the resolution path in
`templates/default-labels.md`), so the name you set here is what every
skill applies and filters on.

State labels are mutually exclusive — exactly one is applied per review.

| Purpose | Label | Type | Meaning |
| ------- | ----- | ---- | ------- |
| `needs-review` | `{PREFIX}-needs-review` | State | Open PR awaiting its first review (entry state, applied at creation) |
| `reviewing` | `{PREFIX}-reviewing` | State | Review in progress — prevents concurrent reviews |
| `approved` | `{PREFIX}-approved` | State | No remaining issues, ready for human merge |
| `changes-requested` | `{PREFIX}-changes-requested` | State | Concrete problems remain that a human must address |
| `needs-discussion` | `{PREFIX}-needs-discussion` | State | Architectural or scope questions need human judgment |
| `needs-re-review` | `{PREFIX}-needs-re-review` | State | New commits pushed since last review — re-review required |
| `failed` | `{PREFIX}-failed` | State | Review could not be completed (checkout failed, PR too large) |
| `updating` | `{PREFIX}-updating` | State | A builder agent is addressing review feedback — prevents concurrent updates |
| `fixes-applied` | `{PREFIX}-fixes-applied` | Action | Claude pushed fix commits to the PR branch (sticky across runs) |

These labels are managed by the `/github-workflow:code-review` skill
and form the single source of truth for PR review state. Claude labels
in `ClaudeProject.md` (like `claude-authored`) are separate workflow
markers that do not participate in this state machine.

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
