# Project Configuration

<!-- ClaudeProject schema: v1 -->

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

All priority, type, and status labels use their default purpose-key
names (e.g., `priority-critical`, `status-ready`). See
`github-workflow/templates/default-labels.md` for the full list and
the lifecycle state machine.

### Claude

`claude-authored` is a provenance marker (not a lifecycle state) applied
by workflow commands to Claude-authored PRs and Claude-created issues. It
is **not** part of the PR review-state machine. Review-state labels are
defined in [`docs/review.config.md`](docs/review.config.md), which keeps
the plugin's own `review-` prefix, so they resolve to the same names the
defaults in `github-workflow/templates/default-labels.md` produce.

| Purpose          | Label             | Applied by                    |
| ---------------- | ----------------- | ----------------------------- |
| claude-authored  | `claude-authored` | execute, report-issue         |

Agent gating is disabled, so no `claude-ready` label is configured.

## Issue Types & Fields

Written from `wf org-capabilities` against `Subverting-complexity`.
Re-run `/github-workflow:setup` after enabling a type or adding a field.

### Capability

| Setting | Value |
| ------- | ----- |
| type-capable | `yes` |

An organisation with native issue types enabled: **Bug**, **Chore**,
**Epic**, **Feature**, **User Story**. The native type is the first-class
classification here, so the `type-*` label is dropped from an issue once
the type is set. Priority stays dual-tracked with its label — the label
orders selection, the field drives the board's own views.

### Field names

All eight resolve to their default names.

| Purpose key          | Field name       |
| -------------------- | ---------------- |
| field-priority       | `Priority`       |
| field-effort         | `Effort`         |
| field-type           | `Classification` |
| field-origin         | `Origin`         |
| field-start          | `Start date`     |
| field-target         | `Target date`    |
| field-parent         | `Parent`         |
| field-status-reason  | `Status reason`  |

`Classification` is a **multi-select**; the rest are single-select, date or
text as `wf_core.FIELD_DATA_TYPES` records. `field-priority`,
`field-effort`, `field-type` and `field-origin` are mandatory on every
issue the workflow creates — `wf issue-apply` refuses a spec that leaves
one blank.

### Missing

| Field | Consequence |
| ----- | ----------- |
| _(none)_ | — |

The purpose→value maps are Python data in
`github-workflow/scripts/wf_core.py`. Run `wf org-capabilities` for the
live option ids rather than copying them here, where they would go stale.

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

## Project Board

Board: **claude-plugins** (org project #8) —
<https://github.com/orgs/Subverting-complexity/projects/8>

| Setting             | Value                            |
| ------------------- | -------------------------------- |
| project-number      | `8`                              |
| project-title       | `claude-plugins`                 |
| project-node-id     | `PVT_kwDODj6aos4BZkaL`           |
| status-field-name   | `Status`                         |
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

All board moves now resolve to a real column: `execute` → In Progress /
In Review, `block-story` → Blocked, and `report-issue`
places new issues in Todo/Backlog. The **issue lifecycle labels** (Status
section above) remain the authoritative state; the board mirrors them.
"Ready" stays optional because this repo's ready-gate is `label`, not
`board-column`.

## Reference Docs

- `docs/review.config.md` — review-state labels, non-compliance gates,
  tech-stack review rules, and the auto-merge settings. Auto-merge is
  **enabled** here, so an `execute` run ends at a merged PR and
  `code-review` merges what it approves; the CI gate is enforced
  plugin-side (`require-ci-before-merge: true`) because branch protection
  is not currently applied.
- `docs/worktree-config.md` — recommended harness configuration for
  parallel/background agents, and the manual reap routine for stale
  worktrees and claim refs.

## Bundled Skills

Available as `/github-workflow:*`: acceptance-criteria, bulk-execute,
code-architect, code-review, debugging, doc-writer, ecosystem-setup,
execute, feature-discovery, pr-body, preflight, repo-scaffolding,
security-audit, structured-coding, support-request, tone, user-story,
user-facing-communication, verify-feature, writing-github-issues.
