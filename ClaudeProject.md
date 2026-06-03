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
bash sync-skills.sh --verify && bash lint-skills.sh
```

This mirrors CI: verifies shared skills are in sync (no drift between
`_shared-skills/` and the deployed plugin copies) and lints skill
frontmatter for unreplaced placeholders. Plugin version-bump and
manifest validation are enforced at PR time by `.github/workflows/ci.yml`.

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
without depending on the project board (whose lifecycle columns are not
yet configured here).

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

## Ready Gate

| Setting    | Value   |
| ---------- | ------- |
| ready-gate | `label` |

How stories signal they are eligible for pickup:

- `label` (default) — the `status-ready` label in the label map.
- `board-column` — the "Ready" column on the project board.
- `both` — story must have the label AND be in the board column.

Using `label` because the project board's Status field currently has
only the default options (Todo / In Progress / Done) — there is no
"Ready" column. Add a "Ready" option to the board and switch this to
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

The board uses GitHub's **default** Status options. "Ready" and
"In Review" columns do not exist yet — add them in the board UI to get
full status tracking, then fill in their option IDs below.

| Status      | Option ID            |
| ----------- | -------------------- |
| Backlog     | `f75ad846` (Todo)    |
| Ready       | `n/a` (add column)   |
| In Progress | `47fc9ee4`           |
| In Review   | `n/a` (add column)   |
| Done        | `98236657`           |
| On Hold     | `n/a` (add column)   |

Board updates are best-effort: `start-story` → In Progress works today;
`finish-story` → In Review and `block-story` → On Hold will no-op until
those columns are added. This no-op is now harmless for state visibility:
the **issue lifecycle labels** (Status section above) always carry the
authoritative state, so an issue in review or blocked is visible by label
even while the board lacks those columns.

## Reference Docs

- `docs/worktree-config.md` — recommended harness configuration for
  parallel/background agents, and the manual reap routine for stale
  worktrees and claim refs.

## Bundled Skills

These skills are bundled with the plugin and available as `/github-workflow:*`:

| Skill                              | Used in          |
| ---------------------------------- | ---------------- |
| /github-workflow:code-architect    | Planning         |
| /github-workflow:structured-coding | Implementation   |
| /github-workflow:code-review       | Review and audit |
| /github-workflow:grill-me          | Plan validation  |
| /github-workflow:feature-discovery | Backlog creation |
| /github-workflow:repo-scaffolding  | Project setup    |
