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

These control issue typing and prioritization. Resolved via the label
map in `ClaudeProject.md`; defaults below.

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
| `claude-ready` | `claude-ready` | `1D76DB` | Approved for agent work |

## Issue Lifecycle State Labels

These are the **issue-side mirror** of the PR review-state machine: every
issue always carries exactly one lifecycle state, so the issues list
shows what is happening to each issue at a glance — without depending on
a project board (board updates are best-effort and may not be
configured). Resolved via the label map in `ClaudeProject.md`; defaults
below.

State labels are **mutually exclusive — exactly one per issue.** A
command that moves an issue to a new state removes the previous state
label in the same edit (`--remove-label <old> --add-label <new>`).

| Purpose key | Default Name | Color | Description | Applied by |
|-------------|-------------|-------|-------------|------------|
| `status-ready` | `status-ready` | `0E8A16` | Eligible for pickup, no unresolved dependencies | setup / pick-story (unblock) |
| `needs-refinement` | `needs-refinement` | `D4C5F9` | Needs a refinement session before pickup | feature-discovery / report-issue |
| `status-in-progress` | `status-in-progress` | `1D76DB` | An agent is actively working this issue now | start-story / execute |
| `status-parked` | `status-parked` | `C5DEF5` | Deliberately set aside by a human, will resume | human / update via park |
| `status-blocked` | `status-blocked` | `B60205` | Cannot proceed — external or dependency blocker | block-story |
| `status-in-review` | `status-in-review` | `FBCA04` | PR is open, awaiting review / merge | finish-story / execute |
| `status-needs-attention` | `status-needs-attention` | `D93F0B` | A run failed or errored — needs human intervention | execute (error/timeout) |

**Lifecycle transitions:**

```
                          ┌──────────────► needs-refinement ──┐
                          │                                    ▼
(new issue) ─► status-ready ─► status-in-progress ─► status-in-review ─► (closed)
                  ▲   ▲              │   │
                  │   │              │   └─► status-needs-attention (run failed)
                  │   └──────────────┘        │
                  │     (parked/blocked        │ (human resumes)
                  │      cleared)              ▼
                  └──── status-parked ◄── (human pauses)
                  └──── status-blocked ◄─ (block-story; cleared when deps close)
```

`status-parked` and `status-blocked` both remove the issue from the pick
pool. The durable owner of in-flight work is the **assignment + the
`status-in-progress`/`status-parked` label**, *not* the atomic claim ref
(which is a short-lived race-protector — see `claim-procedure.md`). This
is what lets a human pause an issue for days and resume it without
another agent grabbing it: the picker only ever selects *unassigned*
issues, so an assigned + labelled issue is excluded regardless of whether
the claim ref has expired.

### Provenance marker (not a lifecycle state)

`claude-authored` is orthogonal to the lifecycle states above — it marks
*who built it*, not *what state it is in*, so it coexists with any
lifecycle state. It is applied to **both** Claude-authored PRs and
Claude-created issues.

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `claude-authored` | `claude-authored` | `5319E7` | Built or created by Claude (issues and PRs) |

## Review State Labels

These control the PR review workflow. Resolved via the Labels table in
`review.config.md` (matched by purpose key); defaults below use the
prefix `review`.

State labels are mutually exclusive — exactly one per PR. A PR enters
the machine at `needs-review` the moment it is opened (so a new PR is
never unlabelled), and the reviewer moves it from there.

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `needs-review` | `review-needs-review` | `C2E0C6` | Open PR awaiting its first review |
| `reviewing` | `review-reviewing` | `0E8A16` | Review in progress |
| `approved` | `review-approved` | `1D76DB` | Ready for human merge |
| `changes-requested` | `review-changes-requested` | `E4E669` | Issues need human action |
| `needs-discussion` | `review-needs-discussion` | `D93F0B` | Architectural questions |
| `needs-re-review` | `review-needs-re-review` | `FBCA04` | New commits since last review |
| `failed` | `review-failed` | `B60205` | Review could not complete |
| `updating` | `review-updating` | `0E8A16` | Builder addressing feedback |
| `fixes-applied` | `review-fixes-applied` | `5319E7` | Claude pushed fix commits (sticky) |
