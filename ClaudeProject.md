# Project Configuration

<!-- ClaudeProject schema: v1 -->

Settings for the `github-workflow` plugin. All commands and the execute skill read this file.

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
bash sync-skills.sh --verify && bash lint-skills.sh && bash run-tests.sh
```

This mirrors CI: verifies shared skills are in sync (no drift between `_shared-skills/` and the deployed plugin copies), lints skill frontmatter for unreplaced placeholders, and runs the offline decision logic tests. Plugin version-bump and manifest validation are enforced at PR time by `.github/workflows/ci.yml`.

`run-tests.sh` automatically picks the right Python interpreter (`python3`, then the Windows Python Launcher `py -3`, then `python`). On Windows, you can also run `.\run-tests.ps1` directly from PowerShell — it does the same detection and prints a `winget` install hint if Python is not found.

## Branch Convention

Pattern for feature branches:

```
feature/{number}/{short-desc}
```

Example: `feature/27/fix-wrong-board`

## Label Map

No label decides anything here. An issue's state is the board column its card is in; its priority, size and owner are the `Priority`, `Effort` and `Ownership` fields. The repository still carries `status-*`, `priority-*` and scope labels from before 10.0.0 and they are deliberately absent from this map: `wf issue-apply` takes one off any issue it writes, and deleting them outright would strip them from every issue that ever carried them. Defaults and the resolution path: `github-workflow/templates/default-labels.md`.

### Claude

`claude-authored` is a provenance marker applied by workflow commands to Claude-authored PRs and Claude-created issues. It is the only label the issue workflow applies. It is **not** part of the PR review-state machine. Review-state labels are defined in [`docs/review.config.md`](docs/review.config.md), which keeps the plugin's own `review-` prefix, so they resolve to the same names the defaults in `github-workflow/templates/default-labels.md` produce.

| Purpose          | Label             | Applied by                    |
| ---------------- | ----------------- | ----------------------------- |
| claude-authored  | `claude-authored` | execute, report-issue         |

## Issue Types & Fields

Written from `wf org-capabilities` against `Subverting-complexity`. Re-run `/github-workflow:setup` after enabling a type or adding a field.

### Capability

| Setting | Value |
| ------- | ----- |
| type-capable | `yes` |

An organisation with native issue types enabled: **Bug**, **Chore**, **Epic**, **Feature**, **User Story**. The native type is the classification here, so `wf issue-apply` strips any `type-*` label off an issue it writes.

### Field names

All eight resolve to their default names.

| Purpose key          | Field name       |
| -------------------- | ---------------- |
| field-priority       | `Priority`       |
| field-effort         | `Effort`         |
| field-ownership      | `Ownership`      |
| field-type           | `Classification` |
| field-origin         | `Origin`         |
| field-start          | `Start date`     |
| field-target         | `Target date`    |
| field-parent         | `Parent`         |

`Classification` is a **multi-select**; the rest are single-select, date or text as `wf_core.FIELD_DATA_TYPES` records.

`field-priority`, `field-effort` and `field-ownership` are **required** on every issue: they are the pool's order, its size ceiling and whether a code agent may take the issue at all, so `wf issue-apply` refuses a spec that leaves one blank. `field-type` and `field-origin` are optional — nothing selects on them, and a create that leaves one unset gets a comment on the issue saying so.

### Missing

| Field | Consequence |
| ----- | ----------- |
| _(none)_ | — |

The purpose→value maps are Python data in `github-workflow/scripts/wf_core.py`. Run `wf org-capabilities` for the live option ids rather than copying them here, where they would go stale.

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
| status-field-name   | `Status`                         |
| status-field-id     | `PVTSSF_lADODj6aos4BZkaLzhUiKRs` |
| start-date-field-id | `n/a`                            |
| end-date-field-id   | `n/a`                            |

`project-title` is recorded so workflow commands can verify the stored node ID still resolves to the intended board before writing to it (see issue #27). Always confirm the live board's title matches `claude-plugins` before mutating board state.

### Status Options

The board now carries all three active workflow columns. Each column mirrors one or more issue lifecycle states — see `github-workflow/templates/default-labels.md` → Board Columns for the full label ⇄ column pairing.

`col-backlog` used to map onto the board's default "Todo" option, which is why `BOARD_COLUMN_NAMES` said "Todo" for as long as it did. The column has since been renamed to "Backlog", keeping option id `f75ad846` so nothing in it moved, and the board and the plugin now use one name for it.

| Status            | Purpose key       | Option ID  |
| ----------------- | ----------------- | ---------- |
| Backlog           | `col-backlog`     | `f75ad846` |
| In Progress       | `col-in-progress` | `47fc9ee4` |
| In Review         | `col-in-review`   | `9b47c867` |
| Blocked           | `col-blocked`     | `28e51b4e` |
| Non-code          | `col-non-code`    | `1803d9dc` |
| Done              | `col-done`        | `98236657` |
| Needs refinement  | `col-refinement`  | `n/a`      |
| Parked            | `col-parked`      | `n/a`      |
| Needs attention   | `col-attention`   | `n/a`      |

**Backlog is the pool.** `pick` and `candidates` read that column and nothing else, so an issue with no card on this board cannot be selected at all — which is why `issue-apply` places every issue it touches. Everything outside Backlog is out of the pool by virtue of being somewhere else, and no label is consulted to decide it.

The last three rows are lanes the plugin can move an issue into that this board does not have yet. `/github-workflow:preflight` warns about each one until they are added; nothing breaks in the meantime, because a move to a column that does not exist is reported and skipped rather than silently landing the card in `No Status`.

## Reference Docs

- `docs/review.config.md` — review-state labels, non-compliance gates, tech-stack review rules, and the auto-merge settings. Auto-merge is **enabled** here, so an `execute` run ends at a merged PR and `code-review` merges what it approves; the CI gate is enforced plugin-side (`require-ci-before-merge: true`) because branch protection is not currently applied.
- `docs/worktree-config.md` — recommended harness configuration for parallel/background agents, and the manual reap routine for stale worktrees and claim refs.

## Bundled Skills

Available as `/github-workflow:*`: acceptance-criteria, bulk-execute, code-architect, code-review, debugging, doc-writer, ecosystem-setup, execute, feature-discovery, pr-body, preflight, repo-scaffolding, security-audit, structured-coding, support-request, tone, user-story, user-facing-communication, verify-feature, writing-github-issues.
