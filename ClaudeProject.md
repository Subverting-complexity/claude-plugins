# Project Configuration

<!-- ClaudeProject schema: v1 -->

Settings for the `synergy` plugin. All commands and the execute skill read this file.

## Identity

| Setting        | Value                   |
| -------------- | ----------------------- |
| org            | `Subverting-complexity` |
| repo           | `claude-plugins`        |
| default-branch | `main`                  |

## Package Manager

`none` — this repo is Markdown skill/command definitions plus shell scripts. There is nothing to install.

## Quality Gate

Command to run before each commit:

```
bash lint-skills.sh && bash run-tests.sh
```

This mirrors CI: lints skill frontmatter and the wiring between skills, and runs the offline decision logic tests. Plugin version-bump and manifest validation are enforced at PR time by `.github/workflows/ci.yml`.

`run-tests.sh` automatically picks the right Python interpreter (`python3`, then the Windows Python Launcher `py -3`, then `python`). On Windows, you can also run `.\run-tests.ps1` directly from PowerShell — it does the same detection and prints a `winget` install hint if Python is not found.

## Branch Convention

Pattern for feature branches:

```
feature/{number}/{short-desc}
```

Example: `feature/27/fix-wrong-board`

## Issue Types & Fields

Written from `wf org-capabilities` against `Subverting-complexity`. Re-run `/synergy:setup` after enabling a type or adding a field.

### Capability

| Setting | Value |
| ------- | ----- |
| type-capable | `yes` |

An organisation with native issue types enabled: **Bug**, **Chore**, **Epic**, **Feature**, **User Story**. The native type is the classification here, so `wf issue-apply` strips any `type-*` label off an issue it writes.

### Field names

All eleven resolve to their default names.

| Purpose key          | Field name       |
| -------------------- | ---------------- |
| field-stage          | `Stage`          |
| field-priority       | `Priority`       |
| field-effort         | `Effort`         |
| field-ownership      | `Ownership`      |
| field-type           | `Classification` |
| field-origin         | `Origin`         |
| field-user-release-notes     | `User release notes`     |
| field-internal-release-notes | `Internal release notes` |
| field-shipped-version        | `Shipped in version`     |

`Classification` is a **multi-select**; `Stage` and the rest are single-select or text as `wf_core.FIELD_DATA_TYPES` records.

`field-priority`, `field-effort` and `field-ownership` are **required** on every issue: they are the pool's order, its size ceiling and whether a code agent may take the issue at all, so `wf issue-apply` refuses a spec that leaves one blank. `field-stage` is the issue's state, with ten options (`Backlog`, `In Progress`, `In Review`, `Blocked`, `Non-code`, `Needs refinement`, `Parked`, `Needs attention`, `Done`, `Area`); a blank `Stage` means available, the same as `Backlog`. `Area` marks a permanent area epic that other issues sit under (`synergy/references/area-epics.md`); it is never picked, closed or moved. `field-type` and `field-origin` are optional — nothing selects on them, and a create that leaves one unset gets a comment on the issue saying so.

### Missing

| Field | Consequence |
| ----- | ----------- |
| _(none)_ | — |

The purpose→value maps are Python data in `synergy/scripts/wf_core.py`. Run `wf org-capabilities` for the live option ids rather than copying them here, where they would go stale.

## Refinement

| Setting          | Value               |
| ---------------- | ------------------- |
| refinement-skill | `feature-discovery` |

## Session Budget

Agent sessions should target ~100k tokens. One story per session, run start-to-finish. Commit and push early so committed work survives a session that ends unexpectedly.

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

This section is informational. The board is a view for people, with its columns grouped by `Stage`, and it is recorded here for them and for GitHub's own "Auto-add to project" workflow. Nothing in the workflow reads a column from it or moves a card on it.

## Reference Docs

- `docs/review.config.md` — review-state labels, non-compliance gates, tech-stack review rules, and the auto-merge settings. Auto-merge is **enabled** here, so an `execute` run ends at a merged PR and `pr-review` merges what it approves; the CI gate is enforced plugin-side (`require-ci-before-merge: true`) because branch protection is not currently applied.
- `docs/worktree-config.md` — recommended harness configuration for parallel/background agents, and the manual reap routine for stale worktrees and claim refs.

## Bundled Skills

Available as `/synergy:*`: acceptance-criteria, build, bulk-execute, code-architect, pr-review, ecosystem-setup, execute, feature-discovery, grill, pr-body, preflight, spec-hardening, support-request, tone, user-story, user-facing-communication, verify-feature, writing-github-issues.
