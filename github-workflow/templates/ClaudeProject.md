# Project Configuration

<!-- ClaudeProject schema: v1 -->
<!-- Format spec: docs/claudeproject-spec.md in the claude-plugins repo -->

Settings for the `github-workflow` plugin. All commands and the execute skill read this file. Keep it lean — it is auto-loaded into context on every workflow command, so prefer values over prose and remove sections your project does not use.

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

Map workflow purposes to your repository's actual label names. Only include labels your project uses — remove unused rows. State machine, transitions, and defaults: `templates/default-labels.md`.

### Priority

| Purpose           | Label    |
| ----------------- | -------- |
| priority-critical | `{name}` |
| priority-high     | `{name}` |
| priority-medium   | `{name}` |
| priority-low      | `{name}` |

### Status (issue lifecycle)

Every issue carries exactly one of these lifecycle labels (the issue-side mirror of the PR review-state machine).

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

`claude-authored` is a provenance marker (not a lifecycle state) applied to Claude-authored PRs and Claude-created issues. `claude-ready` is used only when Agent Gating is enabled — a human applies it during triage to approve a story for autonomous pickup. (PR review-state labels are separate — see `docs/review.config.md`.)

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

**Required.** Not because every org has native issue types — many do not — but because "this org has none" and "nobody wrote this section" look identical at runtime, and the second one silently produced a whole backlog of unclassified issues. So the section is always present and always says which of the two it is. `wf config-audit` reports a missing one as **CRITICAL**.

`/github-workflow:setup` writes this section from `wf org-capabilities`, which resolves what the owner actually has. Re-run it after enabling issue types or adding a field.

### Capability

| Setting | Value |
| ------- | ----- |
| type-capable | `yes` |

`yes` — the owner is an org with **native GitHub issue types** enabled (Bug, Feature, User Story, Epic). The native type is then the first-class classification and the `type-*` label is dropped from an issue once the type is set.

`no` — no native types (a user account, or an org that has not enabled them). The Label Map's `type-*` labels stay the classification. Say so here rather than deleting the section.

### Field names

Every purpose key the workflow writes, mapped to the field name **this** owner uses. Override a name only where the org named a field differently from the default; leave a row out only when the org genuinely does not define that field, and note it under *Missing* below so it is a recorded decision rather than an oversight.

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

Four of these are **mandatory** on every issue the workflow creates — `field-priority`, `field-effort`, `field-type` and `field-origin` (`wf_core.MANDATORY_FIELD_KEYS`). `wf issue-apply` refuses a spec that leaves one blank rather than creating an issue with empty metadata. The other four are set where they apply.

### Missing

Fields the owner does not define, and what the workflow does instead:

| Field | Consequence |
| ----- | ----------- |
| _(none)_ | — |

A missing field is skipped at runtime, not an error. But if one of the four mandatory fields is missing, `wf issue-apply` cannot classify an issue at all — create the field in the owner's *Issue fields* settings. `Origin` is the one the workflow populates that GitHub does not create by default (single-select: Security Audit, Feature Discovery, Code Review, Development, Stakeholder Request).

The purpose→value maps — which native type each kind of work becomes, and the Priority, Effort and Origin option names — are Python data in `github-workflow/scripts/wf_core.py`, not prose here. Run `wf org-capabilities` for the live option ids rather than copying them into this file, where they would go stale.

## Ready Gate

| Setting    | Value   |
| ---------- | ------- |
| ready-gate | `label` |

How stories signal eligibility for pickup:

- `label` (default) — the `status-ready` label.
- `board-column` — the "Ready" column on the project board.
- `both` — label AND board column.
- `none` — no gate; any open unassigned issue is eligible (fully unattended pickup; pair with `agent-gating: disabled`). `off` / `disabled` are accepted synonyms and normalise to `none`.

`board-column`/`both` require a configured board with a "Ready" option; `label`/`none` need no board.

## Agent Gating

| Setting       | Value      |
| ------------- | ---------- |
| agent-gating  | `disabled` |

When `enabled`, only issues carrying `claude-ready` are picked (human approval gate). When `disabled` (default), any eligible unassigned issue can be picked.

## Refinement

| Setting          | Value               |
| ---------------- | ------------------- |
| refinement-skill | `feature-discovery` |

Skill the execute flow offers when a `needs-refinement` story is next: `feature-discovery` (default). Runs in validation mode for lightweight Q&A or discovery mode for full spec+AC.

## Session Budget

Target ~100k tokens per session. One story per session, run start-to-finish. Commit and push early so work survives an unexpected end.

## Story Template

Issues should include at minimum: **Context** (what/why), **Requirements** (acceptance criteria + constraints), and optionally **Notes** (dependencies, references, edge cases).

## Project Board (optional)

Remove this entire section if you don't use a GitHub project board. `project-title` is re-checked against `project-node-id` before any board write, so a stale id fails loudly instead of mutating the wrong board.

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

The canonical six columns. The three active workflow columns (In Progress, In Review, Blocked) must exist when a board is configured; setup creates them, preflight flags any missing. Label ⇄ column pairing: `templates/default-labels.md` → Board Columns.

| Status      | Purpose key       | Option ID |
| ----------- | ----------------- | --------- |
| Backlog     | `col-backlog`     | `{id}`    |
| Ready       | `col-ready`       | `{id}`    |
| In Progress | `col-in-progress` | `{id}`    |
| In Review   | `col-in-review`   | `{id}`    |
| Blocked     | `col-blocked`     | `{id}`    |
| Done        | `col-done`        | `{id}`    |

## Reference Docs (optional)

Paths to architecture docs or specs consulted for cross-cutting concerns not covered in individual issues.

- `{path/to/doc}`

## Bundled Skills

Available as `/github-workflow:*`: acceptance-criteria, code-architect, code-review, debugging, doc-writer, ecosystem-setup, execute, feature-discovery, pr-body, preflight, repo-scaffolding, security-audit, structured-coding, user-story, verify-feature.
