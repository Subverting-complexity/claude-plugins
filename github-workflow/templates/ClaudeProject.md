# Project Configuration

<!-- ClaudeProject schema: v1 -->
<!-- Format spec: docs/claudeproject-spec.md in the claude-plugins repo -->

Settings for the `github-workflow` plugin. All commands and the execute
skill read this file. Keep it lean — it is auto-loaded into context on
every workflow command, so prefer values over prose and remove sections
your project does not use.

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

Example: `feature/{number}/{short-desc}`

## Label Map

Map workflow purposes to your repository's actual label names. Only include
labels your project uses — remove unused rows. State machine, transitions,
and defaults: `templates/default-labels.md`.

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

### Status (issue lifecycle)

Every issue carries exactly one of these lifecycle labels (the issue-side
mirror of the PR review-state machine).

| Purpose                | Label    |
| ---------------------- | -------- |
| status-ready           | `{name}` |
| needs-refinement       | `{name}` |
| status-in-progress     | `{name}` |
| status-parked          | `{name}` |
| status-blocked         | `{name}` |
| status-in-review       | `{name}` |
| status-needs-attention | `{name}` |

### Claude

`claude-authored` is a provenance marker (not a lifecycle state) applied to
Claude-authored PRs and Claude-created issues. `claude-ready` is used only
when Agent Gating is enabled — a human applies it during triage to approve
a story for autonomous pickup. (PR review-state labels are separate — see
`docs/review.config.md`.)

| Purpose          | Label    | Applied by                     |
| ---------------- | -------- | ------------------------------ |
| claude-authored  | `{name}` | execute (PRs), report-issue / execute (issues) |
| claude-ready     | `{name}` | human triage                   |

### Custom (optional)

Additional labels your project uses. Remove if not needed.

| Label    | When to apply |
| -------- | ------------- |
| `{name}` | {criteria}    |

## Issue Types & Fields

Optional. When the org has **native GitHub issue types** (Bug, Feature,
User Story, Epic) and **org issue fields**, the workflow uses them as
first-class classification/metadata instead of labels. Capability is
auto-detected per dimension at runtime (`templates/issue-fields-resolution.md`);
an org without them keeps label-only behaviour. The purpose→value mappings
live in `templates/default-labels.md`. Override a **field name** below only
if your org named one differently from the default.

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

## Ready Gate

| Setting    | Value   |
| ---------- | ------- |
| ready-gate | `label` |

How stories signal eligibility for pickup:

- `label` (default) — the `status-ready` label.
- `board-column` — the "Ready" column on the project board.
- `both` — label AND board column.
- `none` — no gate; any open unassigned issue is eligible (fully unattended
  pickup; pair with `agent-gating: disabled`). `off` / `disabled` are accepted
  synonyms and normalise to `none`.

`board-column`/`both` require a configured board with a "Ready" option;
`label`/`none` need no board.

## Agent Gating

| Setting       | Value      |
| ------------- | ---------- |
| agent-gating  | `disabled` |

When `enabled`, only issues carrying `claude-ready` are picked (human
approval gate). When `disabled` (default), any eligible unassigned issue
can be picked.

## Refinement

| Setting          | Value               |
| ---------------- | ------------------- |
| refinement-skill | `feature-discovery` |

Skill the execute flow offers when a `needs-refinement` story is next:
`feature-discovery` (default). Runs in validation mode for lightweight
Q&A or discovery mode for full spec+AC.

## Session Budget

Target ~100k tokens per session. One story per session, run
start-to-finish. Commit and push early so work survives an unexpected end.

## Story Template

Issues should include at minimum: **Context** (what/why), **Requirements**
(acceptance criteria + constraints), and optionally **Notes**
(dependencies, references, edge cases).

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
`project-title` is re-checked against `project-node-id` before any board
write, so a stale id fails loudly instead of mutating the wrong board.

| Setting             | Value      |
| ------------------- | ---------- |
| project-number      | `{n}`      |
| project-title       | `{title}`  |
| project-node-id     | `{id}`     |
| status-field-name   | `Status`   |
| status-field-id     | `{id}`     |
| start-date-field-id | `{id}`     |
| end-date-field-id   | `{id}`     |

### Status Options

The canonical six columns. The three active workflow columns (In Progress,
In Review, Blocked) must exist when a board is configured; setup creates
them, preflight flags any missing. Label ⇄ column pairing:
`templates/default-labels.md` → Board Columns.

| Status      | Purpose key       | Option ID |
| ----------- | ----------------- | --------- |
| Backlog     | `col-backlog`     | `{id}`    |
| Ready       | `col-ready`       | `{id}`    |
| In Progress | `col-in-progress` | `{id}`    |
| In Review   | `col-in-review`   | `{id}`    |
| Blocked     | `col-blocked`     | `{id}`    |
| Done        | `col-done`        | `{id}`    |

## Reference Docs (optional)

Paths to architecture docs or specs consulted for cross-cutting concerns
not covered in individual issues.

- `{path/to/doc}`

## Bundled Skills

Available as `/github-workflow:*`: acceptance-criteria, code-architect,
code-review, debugging, doc-writer, ecosystem-setup, execute,
feature-discovery, pr-description, preflight, repo-scaffolding,
security-audit, structured-coding, user-story, verify-feature.
