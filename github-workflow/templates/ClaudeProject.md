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

Map workflow purposes to your repository's actual label names. Only include labels your project uses — remove unused rows. Defaults and the resolution path: `templates/default-labels.md`.

**No label decides anything.** An issue's state is the board column its card is in; its priority, size and owner are the `Priority`, `Effort` and `Ownership` fields. If your project still has `status-*`, `priority-*`, `browser-agent`, `human-required`, `needs-refinement` or `claude-ready` labels, leave them out of this map: `wf config-audit` reports a map row for one (`label-deprecated`), and `wf issue-apply` takes the label off any issue it writes. The labels themselves can stay in the repository — deleting one strips it from every issue that ever carried it.

### Claude

`claude-authored` is a provenance marker applied to Claude-authored PRs and Claude-created issues. It is the only label this workflow puts on an issue, and it decides nothing. (PR review-state labels are separate — see `docs/review.config.md`.)

| Purpose          | Label    | Applied by                     |
| ---------------- | -------- | ------------------------------ |
| claude-authored  | `{name}` | execute (PRs), report-issue / execute (issues) |

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

`yes` — the owner is an org with **native GitHub issue types** enabled (Bug, Feature, User Story, Epic). The native type is the classification, and `wf issue-apply` strips any `type-*` label off an issue it writes.

`no` — no native types (a user account, or an org that has not enabled them). `--mode feature` and `--mode maintenance` cannot run, because nothing classifies an issue; `--mode story` is unaffected. Say so here rather than deleting the section.

### Field names

Every purpose key the workflow writes, mapped to the field name **this** owner uses. Override a name only where the org named a field differently from the default; leave a row out only when the org genuinely does not define that field, and note it under *Missing* below so it is a recorded decision rather than an oversight.

| Purpose key          | Field name       |
| -------------------- | ---------------- |
| field-priority       | `Priority`       |
| field-effort         | `Effort`         |
| field-type           | `Classification` |
| field-origin         | `Origin`         |
| field-ownership      | `Ownership`      |
| field-start          | `Start date`     |
| field-target         | `Target date`    |
| field-parent         | `Parent`         |

**Three of these are required**, and the line is whether a decision reads the value: `field-priority` is the pool's order, `field-effort` its size ceiling, `field-ownership` whether a code agent may take the issue at all (`wf_core.MANDATORY_FIELD_KEYS`). An org that has not defined one is a critical preflight finding, and `wf issue-apply` refuses a spec that leaves one blank rather than creating an issue nothing can rank, size or route.

`field-type` (`Classification`) and `field-origin` are **optional**: nothing selects on them, so a create that leaves one unset gets a comment on the issue naming it and carries on. The rest are set where they apply.

There is a fourth required answer and it is not a field: **state**, which is the board column the card sits in. Every write places the card, and preflight fails on an open issue with no card or a card in no lane.

### Missing

Fields the owner does not define, and what the workflow does instead:

| Field | Consequence |
| ----- | ----------- |
| _(none)_ | — |

A missing optional field is skipped at runtime, not an error. A missing **required** field is refused: `wf issue-apply` will not create an issue the picker cannot rank, size or route, and `wf config-audit` reports it as `CRITICAL field-absent`. Create it in the owner's *Issue fields* settings and pin it to every enabled issue type. `Ownership` (single-select: Code agent, Browser agent, Human) and `Origin` (single-select: Security Audit, Feature Discovery, Code Review, Development, Stakeholder Request) are the two GitHub does not create by default.

The purpose→value maps — which native type each kind of work becomes, and the Priority, Effort and Origin option names — are Python data in `github-workflow/scripts/wf_core.py`, not prose here. Run `wf org-capabilities` for the live option ids rather than copying them into this file, where they would go stale.

## Refinement

| Setting          | Value               |
| ---------------- | ------------------- |
| refinement-skill | `feature-discovery` |

Skill the execute flow offers when a story is too thin to implement: `feature-discovery` (default). Runs in validation mode for lightweight Q&A or discovery mode for full spec+AC. A story a person has not approved yet belongs in the board's Needs refinement column, which keeps it out of the pool without needing a label.

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

The canonical nine columns. **Backlog is not optional**: it is the pool `pick` and `candidates` read, so a board without it can select nothing and preflight fails the run. The rest are lanes an issue is moved into and out of; a missing one warns. Setup creates them all, preflight flags any missing. Label ⇄ column pairing: `templates/default-labels.md` → Board Columns.

| Status           | Purpose key       | Option ID |
| ---------------- | ----------------- | --------- |
| Backlog          | `col-backlog`     | `{id}`    |
| In Progress      | `col-in-progress` | `{id}`    |
| In Review        | `col-in-review`   | `{id}`    |
| Blocked          | `col-blocked`     | `{id}`    |
| Non-code         | `col-non-code`    | `{id}`    |
| Needs refinement | `col-refinement`  | `{id}`    |
| Parked           | `col-parked`      | `{id}`    |
| Needs attention  | `col-attention`   | `{id}`    |
| Done             | `col-done`        | `{id}`    |

## Reference Docs (optional)

Paths to architecture docs or specs consulted for cross-cutting concerns not covered in individual issues.

- `{path/to/doc}`

## Bundled Skills

Available as `/github-workflow:*`: acceptance-criteria, code-architect, code-review, debugging, doc-writer, ecosystem-setup, execute, feature-discovery, pr-body, preflight, repo-scaffolding, security-audit, structured-coding, user-story, verify-feature.
