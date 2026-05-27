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

| Purpose    | Label    |
| ---------- | -------- |
| type-story | `{name}` |
| type-bug   | `{name}` |
| type-debt  | `{name}` |
| type-arch  | `{name}` |

### Status

| Purpose        | Label    |
| -------------- | -------- |
| status-ready   | `{name}` |
| status-blocked | `{name}` |

### Claude

| Purpose         | Label    |
| --------------- | -------- |
| claude-reviewed | `{name}` |
| claude-approved | `{name}` |
| claude-blocked  | `{name}` |

## Story Template

Issues should include these sections at minimum:

1. **Context** — What this is about and why it matters
2. **Requirements** — Acceptance criteria and constraints
3. **Notes** (optional) — Dependencies, references, edge cases

## Issue Prefixes

| Type         | Prefix    |
| ------------ | --------- |
| Story        | `[STORY]` |
| Bug          | `[BUG]`   |
| Architecture | `[ARCH]`  |
| Tech Debt    | `[DEBT]`  |

## Project Board (optional)

Remove this entire section if you don't use a GitHub project board.

| Setting             | Value  |
| ------------------- | ------ |
| project-number      | `{n}`  |
| project-node-id     | `{id}` |
| status-field-id     | `{id}` |
| start-date-field-id | `{id}` |
| end-date-field-id   | `{id}` |

### Status Options

| Status      | Option ID |
| ----------- | --------- |
| Backlog     | `{id}`    |
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
