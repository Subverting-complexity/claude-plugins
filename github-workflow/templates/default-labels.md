# Label Resolver & Default Inventory

This file is the **single source of truth** for how every skill and
command resolves a label name, and the default inventory created at
setup. All producers (skills that *apply* a label) and all consumers
(skills that *filter or skip* on a label) resolve through the one path
below, so the string that is applied always equals the string that is
filtered — by construction.

## Purpose keys

A label is identified by its **purpose key**, never by a hardcoded
concrete name. Purpose keys are stable; concrete names are
project-configurable. The bare names that appear in workflow prose
(`reviewing`, `updating`, `approved`, `changes-requested`,
`needs-discussion`, `claude-authored`, `status-ready`, …) **are purpose
keys** — they are resolved to a concrete name through this file, and are
never applied literally.

## The single resolution path

When any skill needs the concrete name for a purpose key:

1. **Workflow purposes** (typing, priority, status, claude markers) —
   look up the purpose in the `ClaudeProject.md` label map.
   **Review-state purposes** (the PR review mutex) — look up the purpose
   in `review.config.md`'s Labels table, matched **by purpose** (the
   Purpose column), not by guessing a prefix.
2. If the project config defines a name for that purpose, use it.
3. If not configured, use the default name from the inventory below.

**Invariant — apply == filter.** Because producers and consumers both
start from the same purpose key and run the same three steps, a claim
label written by one skill is the identical string another skill filters
on. Do not re-derive names independently, do not hardcode a concrete
name in prose or a filter, and do not assume a prefix — always resolve
the purpose key through this path.

## Pre-creation contract

The complete inventory below (workflow **and** review-state labels) is
created once at setup (`/github-workflow:setup`, step 5b). Skills at
runtime must **not** `--force`-overwrite labels — that causes
colour/description churn when two skills disagree on metadata. A skill
may only **create a missing label as a guarded fallback**: check whether
it exists, create it without `--force` if absent, warn that setup should
have created it, then proceed.

Guarded create-if-missing pattern:

```
# resolve <name> from the purpose key via the path above, then:
existing=$(gh label list --repo {org}/{repo} --json name --jq '.[].name')
case "$existing" in
  *"<name>"*) : ;;  # already present — leave its metadata untouched
  *) gh label create "<name>" --repo {org}/{repo} \
       --description "<description>" --color "<color>" || true ;;
esac
```

After applying any label, verify it took effect by reading back:

```
gh issue view {number} --json labels --jq '[.labels[].name]'
gh pr view {number} --json labels --jq '[.labels[].name]'
```

If a label is missing after apply, it did not exist and `gh` silently
skipped it. Create it with the guarded pattern above and retry once.

## Workflow Labels

These control issue management — typing, prioritization, and status.
Resolved via the label map in `ClaudeProject.md`; defaults below.

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `type-story` | `type-story` | `1D76DB` | Feature story |
| `type-bug` | `type-bug` | `D93F0B` | Bug fix |
| `type-security` | `type-security` | `B60205` | Security issue |
| `type-debt` | `type-debt` | `FBCA04` | Technical debt |
| `type-arch` | `type-arch` | `0E8A16` | Architecture issue |
| `priority-critical` | `priority-critical` | `B60205` | Critical priority |
| `priority-high` | `priority-high` | `D93F0B` | High priority |
| `priority-medium` | `priority-medium` | `FBCA04` | Medium priority |
| `priority-low` | `priority-low` | `0E8A16` | Low priority |
| `status-ready` | `status-ready` | `0E8A16` | Ready for pickup |
| `claude-authored` | `claude-authored` | `5319E7` | Built by Claude |
| `claude-ready` | `claude-ready` | `1D76DB` | Approved for agent work |

## Review State Labels

These control the PR review workflow. Resolved via the Labels table in
`review.config.md` (matched by purpose key); defaults below use the
prefix `review`.

State labels are mutually exclusive — exactly one per PR.

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `reviewing` | `review-reviewing` | `0E8A16` | Review in progress |
| `approved` | `review-approved` | `1D76DB` | Ready for human merge |
| `changes-requested` | `review-changes-requested` | `E4E669` | Issues need human action |
| `needs-discussion` | `review-needs-discussion` | `D93F0B` | Architectural questions |
| `needs-re-review` | `review-needs-re-review` | `FBCA04` | New commits since last review |
| `review-failed` | `review-review-failed` | `B60205` | Review could not complete |
| `updating` | `review-updating` | `0E8A16` | Builder addressing feedback |
| `fixes-applied` | `review-fixes-applied` | `5319E7` | Claude pushed fix commits (sticky) |
