# Project Configuration

Settings for the `github-workflow` plugin. All commands and the
execute skill read this file.

## Identity

| Setting        | Value              |
| -------------- | ------------------ |
| org            | `{org}`            |
| repo           | `{repo}`           |
| default-branch | `{default_branch}` |

## Package Manager

`{package_manager}`

## Quality Gate

Command to run before each commit:

```
{quality_gate_command}
```

## Branch Convention

Pattern for feature branches:

```
{branch_pattern}
```

Example: `feature/{number}/{short-description}`

## Label Map

Map workflow purposes to your repository's actual label names.
Only include labels your project uses — remove unused rows.

### Priority

| Purpose           | Label    |
| ----------------- | -------- |
| priority-critical | `{name}` |
| priority-high     | `{name}` |
| priority-medium   | `{name}` |
| priority-low      | `{name}` |

### Type

| Purpose       | Label    |
| ------------- | -------- |
| type-story    | `{name}` |
| type-bug      | `{name}` |
| type-security | `{name}` |
| type-debt     | `{name}` |
| type-arch     | `{name}` |

### Status

| Purpose            | Label    |
| ------------------ | -------- |
| status-ready       | `{name}` |
| needs-refinement   | `{name}` |

### Claude

Simple markers applied by workflow commands. These are **not** the
review state labels — those are defined in `docs/review.config.md`
and managed by the code-review skill.

| Purpose          | Label    | Applied by       |
| ---------------- | -------- | ---------------- |
| claude-authored  | `{name}` | finish-story     |
| claude-ready     | `{name}` | human triage     |

The `claude-ready` label is used only when Agent Gating is enabled
(see below). A human applies it during triage to approve a story for
autonomous agent pickup.

### Custom (optional)

Additional labels your project uses. Remove this section if not needed.
The code-review skill also supports custom labels — those are defined
in `docs/review.config.md`, not here.

| Label    | When to apply |
| -------- | ------------- |
| `{name}` | {criteria}    |

## Ready Gate

| Setting    | Value   |
| ---------- | ------- |
| ready-gate | `label` |

How stories signal they are eligible for pickup:

- `label` (default) — the `status-ready` label in the label map.
- `board-column` — the "Ready" column on the project board.
- `both` — story must have the label AND be in the board column.

When using `board-column` or `both`, a project board must be
configured (see Project Board section below) and must have a "Ready"
status option.

## Agent Gating

| Setting       | Value      |
| ------------- | ---------- |
| agent-gating  | `disabled` |

When `enabled`, the agent only picks up issues that carry the
`claude-ready` label (see Claude labels above). A human must apply
this label during triage to approve the story for autonomous
execution. When `disabled` (default), any eligible unassigned issue
can be picked — no extra label is required.

## Refinement

| Setting          | Value               |
| ---------------- | ------------------- |
| refinement-skill | `feature-discovery` |

When a `needs-refinement` story is next in the pick queue, the execute
skill surfaces it to the user and offers to start a refinement session
using the skill configured here.

- `feature-discovery` (default) — code-aware: explores the codebase,
  interviews the user, and updates the story with full spec and AC.
- `grill-me` — lightweight Q&A interrogation without codebase
  exploration, for stories where requirements just need sharpening.

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

## Project Board (optional)

Remove this entire section if you don't use a GitHub project board.

| Setting             | Value     |
| ------------------- | --------- |
| project-number      | `{n}`     |
| project-title       | `{title}` |
| project-node-id     | `{id}`    |
| status-field-id     | `{id}`    |
| start-date-field-id | `{id}`    |
| end-date-field-id   | `{id}`    |

`project-title` is the human-readable board name. Workflow commands
re-check that `project-node-id` still resolves to a board with this
title before writing to the board, so a stale or wrong id fails loudly
instead of silently mutating the wrong board.

### Status Options

| Status      | Option ID |
| ----------- | --------- |
| Backlog     | `{id}`    |
| Ready       | `{id}`    |
| In Progress | `{id}`    |
| In Review   | `{id}`    |
| Done        | `{id}`    |
| On Hold     | `{id}`    |

## Reference Docs (optional)

Paths to architecture docs, specs, or other references consulted
for cross-cutting concerns not covered in individual issues.

- `{path/to/doc}`

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
