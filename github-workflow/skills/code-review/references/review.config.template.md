# Review Configuration — {PROJECT_NAME}

## Repository

- Org: {ORG}
- Repo: {REPO}
- Default branch: {DEFAULT_BRANCH}

## Labels

State labels are mutually exclusive — exactly one is applied per review.

| Label | Type | Meaning |
| ----- | ---- | ------- |
| `{PREFIX}-reviewing` | State | Review in progress — prevents concurrent reviews |
| `{PREFIX}-approved` | State | No remaining issues, ready for human merge |
| `{PREFIX}-changes-requested` | State | Concrete problems remain that a human must address |
| `{PREFIX}-needs-discussion` | State | Architectural or scope questions need human judgment |
| `{PREFIX}-review-failed` | State | Review could not be completed (checkout failed, PR too large) |
| `{PREFIX}-fixes-applied` | Action | Claude pushed fix commits to the PR branch (sticky across runs) |

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
