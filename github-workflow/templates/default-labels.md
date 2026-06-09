# Label Resolver & Default Inventory

This file is the **single source of truth** for how every skill and
command resolves a label name, and the default inventory created at
setup. For design rationale, see `default-labels-rationale.md` (not
read at runtime).

## Purpose keys

A label is identified by its **purpose key**, never by a hardcoded
concrete name. Purpose keys are stable; concrete names are
project-configurable.

## The single resolution path

> **You usually do not need to open this file.** Every workflow command
> auto-loads the full `ClaudeProject.md` (label map included) into context
> before it runs. When that map is already in context — the normal case —
> resolve purpose keys directly from it and do **not** read this file. Open
> it only as a fallback: a purpose key is missing from the project map, or
> you need the default inventory / colours / native-type and board-column
> tables below.

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

The complete inventory below is created once at setup
(`/github-workflow:setup`, step 5b). Skills must **not**
`--force`-overwrite labels at runtime — that causes colour/description
churn. A skill may only **create a missing label as a guarded fallback**:
check whether it exists, create it without `--force` if absent, warn that
setup should have created it, then proceed.

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

## Issue Types & Field Values

When the target org has **native GitHub issue types** and **org issue
fields** configured, the workflow uses them as the first-class
classification and metadata — see `templates/issue-fields-resolution.md`
for the runtime resolution + mutation procedure. This section is the
**single source of truth** for the purpose→value mappings those steps
follow; a project may override any of it in `ClaudeProject.md` →
`## Issue Types & Fields`.

### Native issue type map ("by nature")

The workflow's kind → native issue type, the `Classification` field option
(subcategory; always set — never leave blank), and the `type-*` label used
as the fallback on a non-type-capable org:

| Workflow kind | Native issue type | `Classification` option | `type-*` fallback label |
|---------------|-------------------|-------------------------|-------------------------|
| story         | User Story        | New Feature             | `type-story` |
| bug           | Bug               | Bug Fix ¹               | `type-bug` |
| security      | Bug               | Security                | `type-security` |
| tech debt     | Feature           | Tech Debt               | `type-debt` |
| architecture  | Feature           | Architecture            | `type-arch` |
| feature       | Feature           | New Feature ²           | `type-story` |
| epic          | Epic              | New Feature             | `type-story` |
| spike         | User Story        | Spike                   | `type-story` |
| chore         | User Story        | Chore                   | `type-bug` |

¹ Use **Regression** if something previously worked and broke; use
**Performance** if the bug is a speed or memory degradation. Bug Fix is
the default for any other broken behaviour.

² Use **Enhancement** if the feature improves something existing rather
than delivering new capability. Use **Integration** if the primary work
is connecting to an external system, API, or third-party service.
Use **Documentation** if the issue is tracking docs/guides only.
Use **Performance** if the primary goal is a speed or efficiency improvement.

The full set of valid `Classification` options:
New Feature · Enhancement · Bug Fix · Regression · Performance ·
Security · Tech Debt · Architecture · Integration · Spike · Chore ·
Documentation

### Field-name inventory

Resolved via `ClaudeProject.md` → `## Issue Types & Fields`; defaults here.

| Purpose key            | Default field name | Data type     |
|------------------------|--------------------|---------------|
| `field-priority`       | `Priority`         | single-select |
| `field-effort`         | `Effort`           | single-select |
| `field-type`           | `Classification`   | single-select |
| `field-origin`         | `Origin`           | single-select |
| `field-start`          | `Start date`       | date          |
| `field-target`         | `Target date`      | date          |
| `field-parent`         | `Parent`           | text          |
| `field-status-reason`  | `Status reason`    | text          |

### Priority field option map

The `priority-*` label purpose → `Priority` field option (both are set;
priority is dual-tracked — see `default-labels-rationale.md`):

| Priority label purpose | `Priority` field option |
|------------------------|-------------------------|
| `priority-critical`    | Urgent                  |
| `priority-high`        | High                    |
| `priority-medium`      | Medium                  |
| `priority-low`         | Low                     |

### Effort & Origin field option maps

The `Effort` (size estimate) and `Origin` (creating command/session) field
option maps live in `templates/label-reference.md` — they are used only on
the **issue-creation** path (`report-issue`, `finish-story`,
`feature-discovery`), not the claim/selection path. Resolve them there.

## Issue Lifecycle State Labels

Every issue always carries exactly one lifecycle state label — mutually
exclusive; remove the old label when applying the new one. Resolved via
the label map in `ClaudeProject.md`; defaults below.

| Purpose key | Default Name | Color | Description | Applied by |
|-------------|-------------|-------|-------------|------------|
| `status-ready` | `status-ready` | `0E8A16` | Eligible for pickup, no unresolved dependencies | setup / pick-story (unblock) |
| `needs-refinement` | `needs-refinement` | `D4C5F9` | Needs a refinement session before pickup | feature-discovery / report-issue |
| `status-in-progress` | `status-in-progress` | `1D76DB` | An agent is actively working this issue now | start-story / execute |
| `status-parked` | `status-parked` | `C5DEF5` | Deliberately set aside by a human, will resume | human / update via park |
| `status-blocked` | `status-blocked` | `B60205` | Cannot proceed — external or dependency blocker | block-story |
| `status-in-review` | `status-in-review` | `FBCA04` | PR is open, awaiting review / merge | finish-story / execute |
| `status-needs-attention` | `status-needs-attention` | `D93F0B` | A run failed or errored — needs human intervention | execute (error/timeout) |

For the lifecycle transition diagram and dual-tracking rationale, see
`default-labels-rationale.md`.

### Provenance marker (not a lifecycle state)

`claude-authored` marks who built it, not what state it is in — it
coexists with any lifecycle state.

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `claude-authored` | `claude-authored` | `5319E7` | Built or created by Claude (issues and PRs) |

## Board Columns

The board-side mirror of the issue lifecycle. Columns are resolved by
**purpose key** through the same path as labels: read from
`ClaudeProject.md` → `## Project Board` → `### Status Options`; fall
back to the default name below. Board moves are best-effort (no board
configured → no-op; board configured and move fails → loud error — see
`templates/board-resolution.md`). The labels remain authoritative; the
board mirrors them. For design rationale, see `default-labels-rationale.md`.

| Purpose key      | Default Name  | Option color | Mirrors lifecycle label(s) |
|------------------|---------------|--------------|----------------------------|
| `col-backlog`    | `Backlog`     | GRAY         | `needs-refinement`, new issues |
| `col-ready`      | `Ready`       | GREEN        | `status-ready` |
| `col-in-progress`| `In Progress` | BLUE         | `status-in-progress`, `status-needs-attention` |
| `col-in-review`  | `In Review`   | YELLOW       | `status-in-review` |
| `col-blocked`    | `Blocked`     | RED          | `status-blocked`, `status-parked` |
| `col-done`       | `Done`        | GRAY         | (issue closed) |

> Option `color` values come from the GitHub enum
> `ProjectV2SingleSelectFieldOptionColor`:
> `GRAY`, `BLUE`, `GREEN`, `YELLOW`, `ORANGE`, `RED`, `PINK`, `PURPLE`.
> These name the *board* option color and are distinct from the hex label
> colors above.

**Label ⇄ column pairing (the single mapping every command follows):**

| Lifecycle transition (label set)         | Board column moved to        | Command(s) |
|------------------------------------------|------------------------------|------------|
| `status-in-progress`                     | In Progress (`col-in-progress`) | start-story, execute Phase 2 |
| `status-in-review`                       | In Review (`col-in-review`)  | finish-story, execute Phase 6 |
| `status-blocked`                         | Blocked (`col-blocked`)      | block-story |
| `status-ready` (unblock)                 | Ready (`col-ready`)          | pick-story |
| `needs-refinement` / `status-ready` (new issue) | Backlog / Ready             | report-issue (best-effort placement) |

When a board is configured, the three active columns — In Progress,
In Review, Blocked — must exist (preflight emits
`CRITICAL board-columns-incomplete` if any is missing; setup creates
them). The Ready column is additionally required only under a
`board-column`/`both` ready-gate.

## Review State Labels

The PR review-state label table (the review mutex: `needs-review`,
`reviewing`, `approved`, `changes-requested`, `needs-discussion`,
`needs-re-review`, `failed`, `updating`, `fixes-applied`) lives in
`templates/label-reference.md`. It is used only on the **review** path
(`code-review`, `update-pr`, `finish-story` PR labelling), not the
claim/selection path. Resolve review-state purposes via the Labels table in
`review.config.md` (matched by purpose key), falling back to the defaults
in `label-reference.md`.
