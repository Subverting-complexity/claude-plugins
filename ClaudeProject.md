# Project Configuration

Settings for the `github-workflow` plugin. All commands and the
execute skill read this file.

## Identity

| Setting        | Value                   |
| -------------- | ----------------------- |
| org            | `Subverting-complexity` |
| repo           | `claude-plugins`        |
| default-branch | `main`                  |

## Package Manager

`none` — this repo is Markdown skill/command definitions plus shell
scripts. There is nothing to install.

## Quality Gate

Command to run before each commit:

```
bash sync-skills.sh --verify && bash lint-skills.sh && bash run-tests.sh
```

This mirrors CI: verifies shared skills are in sync (no drift between
`_shared-skills/` and the deployed plugin copies), lints skill
frontmatter for unreplaced placeholders, and runs the offline decision
logic tests. Plugin version-bump and manifest validation are enforced at
PR time by `.github/workflows/ci.yml`.

`run-tests.sh` automatically picks the right Python interpreter (`python3`,
then the Windows Python Launcher `py -3`, then `python`). On Windows,
you can also run `.\run-tests.ps1` directly from PowerShell — it does the
same detection and prints a `winget` install hint if Python is not found.

## Branch Convention

Pattern for feature branches:

```
feature/{number}/{short-desc}
```

Example: `feature/27/fix-wrong-board`

## Label Map

Map workflow purposes to this repository's actual label names.

### Priority

| Purpose           | Label                |
| ----------------- | -------------------- |
| priority-critical | `priority-critical`  |
| priority-high     | `priority-high`      |
| priority-medium   | `priority-medium`    |
| priority-low      | `priority-low`       |

### Type

| Purpose       | Label           |
| ------------- | --------------- |
| type-story    | `type-story`    |
| type-bug      | `type-bug`      |
| type-security | `type-security` |
| type-debt     | `type-debt`     |
| type-arch     | `type-arch`     |

### Status (issue lifecycle)

Every issue always carries exactly one of these lifecycle labels — the
issue-side mirror of the PR review-state machine (see
`github-workflow/templates/default-labels.md` → Issue Lifecycle State
Labels). They make each issue's current state visible in the issues list
without depending on the project board — and the board now mirrors them
(its active lifecycle columns are configured; see Project Board below).

| Purpose                | Label                    |
| ---------------------- | ------------------------ |
| status-ready           | `status-ready`           |
| needs-refinement       | `needs-refinement`       |
| status-in-progress     | `status-in-progress`     |
| status-parked          | `status-parked`          |
| status-blocked         | `status-blocked`         |
| status-in-review       | `status-in-review`       |
| status-needs-attention | `status-needs-attention` |

### Claude

`claude-authored` is a provenance marker (not a lifecycle state) applied
by workflow commands to Claude-authored PRs and Claude-created issues. It
is **not** part of the PR review-state machine. This repo has no
`docs/review.config.md`, so the code-review skill resolves review-state
labels from their defaults (the `review-` prefix) in
`github-workflow/templates/default-labels.md`.

| Purpose          | Label             | Applied by                    |
| ---------------- | ----------------- | ----------------------------- |
| claude-authored  | `claude-authored` | finish-story, report-issue    |

Agent gating is disabled, so no `claude-ready` label is configured.

## Issue Types & Fields

This org (`Subverting-complexity`) **is** type-capable: it has native
GitHub issue types — **Bug**, **Feature**, **User Story**, **Epic** — and
org issue fields. The workflow uses them as the first-class classification
and metadata, not just labels; on a type-capable org the native type
replaces the `type-*` label (priority stays dual-tracked with its label).
Resolution and mutations follow `github-workflow/templates/issue-fields-resolution.md`;
the purpose→value maps (the "by nature" type mapping, priority/effort/origin
maps) live in `github-workflow/templates/default-labels.md` → *Issue Types
& Field Values*.

Field names match the defaults:

| Purpose key          | Field name      |
| -------------------- | --------------- |
| field-priority       | `Priority`      |
| field-effort         | `Effort`        |
| field-type           | `Classification` |
| field-origin         | `Origin`        |
| field-start          | `Start date`    |
| field-target         | `Target date`   |
| field-parent         | `Parent`        |
| field-status-reason  | `Status reason` |

> The `Origin` field must exist in the org for it to be populated (single
> select: Grill-Me Session, Security Audit, Feature Discovery, Code Review,
> Development, Stakeholder Request). All other fields above already exist.

## Ready Gate

| Setting    | Value   |
| ---------- | ------- |
| ready-gate | `label` |

How stories signal they are eligible for pickup:

- `label` (default) — the `status-ready` label in the label map.
- `board-column` — the "Ready" column on the project board.
- `both` — story must have the label AND be in the board column.

Using `label` because the board has the active workflow columns (In
Progress / In Review / Blocked) but no "Ready" column — pickup is
label-driven here. Add a "Ready" option to the board and switch this to
`board-column` or `both` if you prefer board-driven pickup.

## Agent Gating

| Setting       | Value      |
| ------------- | ---------- |
| agent-gating  | `disabled` |

When `disabled` (current), any eligible unassigned issue with the
`status-ready` label can be picked. Set to `enabled` and add a
`claude-ready` row to the Claude label map to require human approval
before autonomous pickup.

## Refinement

| Setting          | Value               |
| ---------------- | ------------------- |
| refinement-skill | `feature-discovery` |

## Session Budget

Agent sessions should target ~100k tokens. One story per session, run
start-to-finish. Commit and push early so committed work survives a
session that ends unexpectedly.

## Story Template

Issues should include these sections at minimum:

1. **Context** — What this is about and why it matters
2. **Requirements** — Acceptance criteria and constraints
3. **Notes** (optional) — Dependencies, references, edge cases

## Issue Prefixes

| Type         | Prefix       |
| ------------ | ------------ |
| Story        | `[STORY]`    |
| Bug          | `[BUG]`      |
| Security     | `[SECURITY]` |
| Architecture | `[ARCH]`     |
| Tech Debt    | `[DEBT]`     |

## Project Board

Board: **claude-plugins** (org project #8) —
<https://github.com/orgs/Subverting-complexity/projects/8>

| Setting             | Value                            |
| ------------------- | -------------------------------- |
| project-number      | `8`                              |
| project-title       | `claude-plugins`                 |
| project-node-id     | `PVT_kwDODj6aos4BZkaL`           |
| status-field-id     | `PVTSSF_lADODj6aos4BZkaLzhUiKRs` |
| start-date-field-id | `n/a`                            |
| end-date-field-id   | `n/a`                            |

`project-title` is recorded so workflow commands can verify the stored
node ID still resolves to the intended board before writing to it (see
issue #27). Always confirm the live board's title matches
`claude-plugins` before mutating board state.

### Status Options

The board now carries all three active workflow columns. Each column
mirrors one or more issue lifecycle states — see
`github-workflow/templates/default-labels.md` → Board Columns for the full
label ⇄ column pairing. (`col-backlog` maps onto the board's default
"Todo" option; `col-done` onto "Done".)

| Status      | Purpose key       | Option ID            |
| ----------- | ----------------- | -------------------- |
| Backlog     | `col-backlog`     | `f75ad846` (Todo)    |
| Ready       | `col-ready`       | `n/a` (optional — label ready-gate) |
| In Progress | `col-in-progress` | `47fc9ee4`           |
| In Review   | `col-in-review`   | `9b47c867`           |
| Blocked     | `col-blocked`     | `28e51b4e`           |
| Done        | `col-done`        | `98236657`           |

All board moves now resolve to a real column: `start-story` → In Progress,
`finish-story` → In Review, `block-story` → Blocked, and `report-issue`
places new issues in Todo/Backlog. The **issue lifecycle labels** (Status
section above) remain the authoritative state; the board mirrors them.
"Ready" stays optional because this repo's ready-gate is `label`, not
`board-column`.

## Reference Docs

- `docs/worktree-config.md` — recommended harness configuration for
  parallel/background agents, and the manual reap routine for stale
  worktrees and claim refs.

## Bundled Skills

These skills are bundled with the plugin and available as `/github-workflow:*`:

| Skill                              | Used in          |
| ---------------------------------- | ---------------- |
| /github-workflow:code-architect    | Planning                        |
| /github-workflow:structured-coding | Implementation                  |
| /github-workflow:code-review       | Review and audit                |
| /github-workflow:feature-discovery | Backlog creation + plan validation |
| /github-workflow:repo-scaffolding  | Project setup                   |
