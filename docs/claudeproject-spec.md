# ClaudeProject.md — format specification (schema v1)

`ClaudeProject.md` is the single source of truth for a project using the `synergy` plugin. It lives at the **repository root** — the `wf` picker resolves it via `git rev-parse --show-toplevel`, so one file covers the whole repo (per-subproject configs are unsupported). The template is `synergy/templates/ClaudeProject.md`; the setup wizard (`/synergy:setup`) generates and refreshes it.

## Who parses it

| Parser | How it reads the file |
| ------ | --------------------- |
| Workflow commands / skills | Auto-load the whole file into context and read it as prose + tables. |
| `wf preflight` | The same `parse_claude_project()`, plus heading, placeholder and quality-gate reads of its own. The `preflight` skill runs this command and reads its JSON; nothing greps the file any more. |
| `wf.py` (story-picker) | `parse_claude_project()` — regex section extraction + table-row parsing. Fallback path only; the fast path is the `.claude/wf-config.json` cache emitted by `wf config`. |

## Schema version line

Immediately after the `# Project Configuration` H1:

```
<!-- ClaudeProject schema: v1 -->
```

An HTML comment so it renders invisibly. Consumers currently treat any file as v1; the line exists so a future format change can be detected instead of silently misparsed.

## Sections

**Required** — `wf preflight` emits a CRITICAL (blocking, offers the setup wizard) if the literal level-2 heading is absent:

| Heading | Content |
| ------- | ------- |
| `## Identity` | Table: `org`, `repo`, `default-branch`. |
| `## Package Manager` | One value (e.g. `pnpm`, `none`). |
| `## Quality Gate` | The pre-commit command inside a fenced code block. |
| `## Branch Convention` | Branch pattern containing `{number}` in a fenced block. |
| `## Issue Types & Fields` | Purpose key → field name table, plus what the org does not define. `Stage` is the issue's state, and `Priority`, `Effort` and `Ownership` are the picker's only other inputs, so a project that has not written this section cannot rank, size or route anything; `wf config-audit` reports the missing section as CRITICAL. |

**Recommended** — read by commands, default-covered when absent: `## Story Template`, `## Session Budget`, `## Refinement`.

**Optional** — remove if unused: `## Project Board`, `## Reference Docs`, `## Bundled Skills`, `## Pre-release test pass`, `## Pre-release privacy pass`. `## Pre-release test pass` holds one setting, `pre-release-test-title`: the title text of the open issue that device and real-browser checks are added to as checkboxes instead of becoming `[Manual]` issues of their own. `## Pre-release privacy pass` holds one setting, `pre-release-privacy-title`, which does the same for a person's half of a privacy policy change: publishing the wording and entering the store privacy answers. A `## Label Map` from an older file is still read, but the workflow applies no label it names and nothing requires it.

**Label tables and the Jev switch** — read by `wf` into the configuration. A file with none of them still loads, with empty lists and Jev on. Nothing acts on the two tables yet:

| Heading | Content |
| ------- | ------- |
| `## Areas` | One row for each permanent part of the product. Columns: `Name`, `Description`, `Colour`, and the optional `Epic` (the number of the area epic the row replaces) and `Was` (the name the area had before a rename). Read as `areas`. |
| `## Release Targets` | One row for each thing the project releases separately. Columns: `Name`, `Description`, `Colour`. Read as `release_targets`. |
| `## Jev` | One setting, `jev`, with the value `on` or `off`. `off` makes `wf jev` answer `unavailable` (exit 30) even when `TYPESAFE_API_KEY` is set, for a repository whose content must stay on the machine. No row means `on`. Read as `jev`. |

## Heading rules

- Preflight matches the **exact literal text** (`grep -q "## Identity"`, case-sensitive substring). Do not rename or re-level the required headings.
- `wf.py` matches headings case-insensitively, level-aware, and **tolerates a trailing parenthetical qualifier**, so `## Project Board (optional)` parses identically to `## Project Board`. Any other rewording makes the section invisible to the picker, which then falls back to defaults.

## Value formats

- **Tables** are 2+ column markdown tables: first cell is a lowercase kebab-case key, second is the value. Backticks around cells are stripped. `n/a` or an empty cell means "unset" for board/field ids.
- **A `|` inside a cell**: write it `\|`, or put it inside a backtick code span. Either way it stays in the cell and does not start a new one.
- **Areas and release targets**: the columns are found by their header text, so an optional column may be left out. `Description` becomes a GitHub label description, so a row with more than 100 characters there is refused, and so is a name that appears 2 times in one table (compared without case). `wf` then stops with the row named, because the alternative is a label that is silently not created. `Colour` is 6 hex digits, with or without a leading `#`. A row whose name is blank or still a `{placeholder}` is not a row.
- **Configuration cache**: `.claude/wf-config.json` is rebuilt when `ClaudeProject.md` or `docs/review.config.md` is newer than it, and also when it has no `areas`, `release_targets` or `jev` key, which means a version before 18.14.0 wrote it.
- **Quality gate**: the command inside the section's fenced code block. Empty or still `{quality_gate_command}` → preflight WARNING.
- **Branch convention**: the first whitespace-delimited token containing `{number}` anywhere in the section (the fenced block, or the backtick-wrapped `Example:` line if the block was left unfilled).
- **Label map rows**: kept only when the purpose key matches `^[a-z]+-[a-z-]+$`. The workflow applies no issue label, so a map is read only in a file that still has one, and a row naming a retired label is reported as `label-deprecated` and should be deleted.
- **Ready gate and agent gating**: both gone — the gate as of 9.0.0, the gating as of 10.0.0. A `## Ready Gate` or `## Agent Gating` section left in a file is read and ignored. The pool is the open, unassigned issues whose `Stage` is blank or `Backlog`, which no setting turns off, and human approval is the issue's `Stage` rather than a label anyone applies.
- **Type capability**: the literal phrase `is type-capable` (bold tolerated) anywhere in the file switches on native issue-type handling.
- **Project board**: `project-number`, `project-title`, `project-node-id`. Informational, for people and for GitHub's own "Auto-add to project" workflow. Nothing in the workflow reads a column from the board.
- **Placeholders**: unreplaced `{org}`-style tokens anywhere trigger a preflight WARNING listing the offending lines. Not repaired by `--fix`: the replacement values are the project's to supply.

## Behaviour on deviation

- **Missing file, missing required section, or `gh` unauthenticated** — preflight CRITICAL: the calling command stops and offers `wf preflight --fix`, the setup wizard, "continue anyway" or "don't remind me". A missing file is reported on its own and stops before the network: with no file there is nothing to compare anything against.
- **Missing recommended/optional content** — WARNING at most; commands proceed on defaults (the `review-` prefix for review labels, `main` for the default branch, `feature/{number}/{short-desc}` for branches).
- **Org `Stage` field absent** — CRITICAL `stage-absent`: no state can be written or read. **`Stage` missing one of its nine options** (`Area` included) — CRITICAL `stage-options`, naming the option, because a transition to it fails. **No open area epic** in the repository — WARNING `area-epics`, because issues filed now resolve to no area (`synergy/references/area-epics.md`). A missing `## Project Board` section is not a finding.
- **`wf.py` parse failures stop the run.** The picker returns a non-`ok` status and the calling command reports it and stops. There is no inline procedure to fall back to: selection, claiming, stage writes, handoff and issue creation are `wf` commands and nothing else implements them, so a `wf` that cannot read this file is a stop, not a slow path.
