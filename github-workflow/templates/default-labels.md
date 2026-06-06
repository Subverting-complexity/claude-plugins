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

## Issue Types & Field Values

When the target org has **native GitHub issue types** and **org issue
fields** configured, the workflow uses them as the first-class
classification and metadata — see `templates/issue-fields-resolution.md`
for the runtime resolution + mutation procedure. This section is the
**single source of truth** for the purpose→value mappings those steps
follow; a project may override any of it in `ClaudeProject.md` →
`## Issue Types & Fields`.

Capability is detected at runtime, per dimension: an org with **no** native
types, or missing a given field, transparently keeps the label-only
behaviour above for that dimension. Native types are **not** dual-tracked —
on a type-capable org the native type replaces the `type-*` label.
**Priority is** dual-tracked (the field *and* the `priority-*` label) so the
selector's priority sort stays a cheap label read.

### Native issue type map ("by nature")

The workflow's kind → native issue type, the finer `Type of issue` field
option, and the `type-*` label used as the fallback on a non-type-capable
org:

| Workflow kind | Native issue type | `Type of issue` option | `type-*` fallback label |
|---------------|-------------------|------------------------|-------------------------|
| story         | User Story        | New Feature            | `type-story` |
| bug           | Bug               | _(unset)_              | `type-bug` |
| security      | Bug               | Security               | `type-security` |
| tech debt     | Feature           | Tech Debt              | `type-debt` |
| architecture  | Feature           | Architecture           | `type-arch` |
| feature       | Feature           | New Feature            | `type-story` |
| epic          | Epic              | _(unset)_              | `type-story` |
| spike         | User Story        | Spike                  | `type-story` |
| chore         | User Story        | Chore                  | `type-bug` |

A `Type of issue` option of _(unset)_ means the native type already says
it (a `Bug` needs no sub-category); leave the field empty.

### Field-name inventory

Resolved via `ClaudeProject.md` → `## Issue Types & Fields`; defaults here.

| Purpose key            | Default field name | Data type     |
|------------------------|--------------------|---------------|
| `field-priority`       | `Priority`         | single-select |
| `field-effort`         | `Effort`           | single-select |
| `field-type`           | `Type of issue`    | single-select |
| `field-origin`         | `Origin`           | single-select |
| `field-start`          | `Start date`       | date          |
| `field-target`         | `Target date`      | date          |
| `field-parent`         | `Parent`           | text          |
| `field-status-reason`  | `Status reason`    | text          |

### Priority field option map

The `priority-*` label purpose → `Priority` field option (both are set;
see dual-tracking note above):

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

## Board Columns

The **board-side mirror** of the issue lifecycle. When a project board is
configured, every command that moves an issue to a new lifecycle *label*
also moves its board item to the paired *column* — so the board never
drifts from the labels. Board moves are best-effort: with no board
configured they no-op silently; with a board configured a failure is
reported loudly (see `templates/board-resolution.md`). The labels remain
the authoritative state; the board mirrors them.

Columns are resolved by **purpose key** through the exact same path as
labels: read the concrete column name / option ID from
`ClaudeProject.md` → `## Project Board` → `### Status Options`; fall back
to the default name below. This extends the **apply == filter** invariant
to the board — every producer and consumer resolves a column through one
path, so the column a command moves to is the same column the picker reads.

The canonical set is six columns; the three **active workflow columns**
(In Progress, In Review, Blocked) are the ones commands move *between*.

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

`status-needs-attention` stays in **In Progress** (the work is still
in-flight; the label flags it for a human). `status-parked` shares the
**Blocked** column with `status-blocked` (both mean "set aside, out of the
pick pool"); the distinct label preserves the reason.

**Required columns.** When a board is configured, the three active
columns — In Progress, In Review, Blocked — must exist (preflight emits
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
