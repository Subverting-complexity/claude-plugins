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
| field-stage          | `Stage`          |
| field-priority       | `Priority`       |
| field-effort         | `Effort`         |
| field-type           | `Classification` |
| field-origin         | `Origin`         |
| field-ownership      | `Ownership`      |
| field-start          | `Start date`     |
| field-target         | `Target date`    |

**Three of these are required**, and the line is whether a decision reads the value: `field-priority` is the pool's order, `field-effort` its size ceiling, `field-ownership` whether a code agent may take the issue at all (`wf_core.MANDATORY_FIELD_KEYS`). An org that has not defined one is a critical preflight finding, and `wf issue-apply` refuses a spec that leaves one blank rather than creating an issue nothing can rank, size or route.

`field-type` (`Classification`) and `field-origin` are **optional**: nothing selects on them, so a create that leaves one unset gets a comment on the issue naming it and carries on. The rest are set where they apply.

`field-stage` answers a different question: **state**. The org must define it, but an issue may leave it blank. It is a single-select with nine options, `Backlog`, `In Progress`, `In Review`, `Blocked`, `Non-code`, `Needs refinement`, `Parked`, `Needs attention` and `Done`, and a blank `Stage` means available, the same as `Backlog`. Preflight fails the run when the org has no `Stage` field (`stage-absent`) or when it lacks one of the nine options (`stage-options`), because a transition to a missing option fails.

### Missing

Fields the owner does not define, and what the workflow does instead:

| Field | Consequence |
| ----- | ----------- |
| _(none)_ | — |

A missing optional field is skipped at runtime, not an error. A missing **required** field is refused: `wf issue-apply` will not create an issue the picker cannot rank, size or route, and `wf config-audit` reports it as `CRITICAL field-absent`. Create it in the owner's *Issue fields* settings and pin it to every enabled issue type. `Stage` (single-select, the nine options above), `Ownership` (single-select: Code agent, Browser agent, Human) and `Origin` (single-select: Security Audit, Feature Discovery, Code Review, Development, Stakeholder Request) are the three GitHub does not create by default. Create them in the org settings under *Planning* → *Issue fields*.

The purpose→value maps — which native type each kind of work becomes, and the Priority, Effort and Origin option names — are Python data in `github-workflow/scripts/wf_core.py`, not prose here. Run `wf org-capabilities` for the live option ids rather than copying them into this file, where they would go stale.

## Refinement

| Setting          | Value               |
| ---------------- | ------------------- |
| refinement-skill | `feature-discovery` |

Skill the execute flow offers when a story is too thin to implement: `feature-discovery` (default). It runs the `grill` interview and turns the answers into a fuller spec with acceptance criteria. A story a person has not approved yet belongs at `Stage` `Needs refinement`, which keeps it out of the pool without needing a label.

## Session Budget

Target ~100k tokens per session. One story per session, run start-to-finish. Commit and push early so work survives an unexpected end.

## Story Template

Issues should include at minimum: **Context** (what/why), **Requirements** (acceptance criteria + constraints), and optionally **Notes** (dependencies, references, edge cases).

## Project Board (optional)

Informational only. A board is a view for people: group its columns by `Stage` and it shows each issue's state. It is recorded here for them and for GitHub's own "Auto-add to project" workflow, which keeps cards on it. Nothing in the workflow reads a column from it or moves a card on it, so remove this section if the project has no board.

| Setting             | Value      |
| ------------------- | ---------- |
| project-number      | `{n}`      |
| project-title       | `{title}`  |
| project-node-id     | `{id}`     |
| start-date-field-id | `{id}`     |
| end-date-field-id   | `{id}`     |

## Reference Docs (optional)

Paths to architecture docs or specs consulted for cross-cutting concerns not covered in individual issues.

- `{path/to/doc}`

## Bundled Skills

Available as `/github-workflow:*`: acceptance-criteria, build, bulk-execute, code-architect, pr-review, ecosystem-setup, execute, feature-discovery, grill, pr-body, preflight, support-request, tone, user-story, writing-github-issues.
