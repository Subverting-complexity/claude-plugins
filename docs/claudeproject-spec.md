# ClaudeProject.md — format specification (schema v1)

`ClaudeProject.md` is the single source of truth for a project using the `github-workflow` plugin. It lives at the **repository root** — the `wf` picker resolves it via `git rev-parse --show-toplevel`, so one file covers the whole repo (per-subproject configs are unsupported). The template is `github-workflow/templates/ClaudeProject.md`; the setup wizard (`/github-workflow:setup`) generates and refreshes it.

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
| `## Label Map` | Purpose → label tables (may use `###` sub-tables). |

**Recommended** — read by commands, default-covered when absent: `## Story Template`, `## Session Budget`, `## Refinement`, `## Issue Types & Fields`.

**Optional** — remove if unused: `## Project Board` (with `### Status Options`), `## Reference Docs`, `## Bundled Skills`, the `### Custom` label table.

## Heading rules

- Preflight matches the **exact literal text** (`grep -q "## Identity"`, case-sensitive substring). Do not rename or re-level the required headings.
- `wf.py` matches headings case-insensitively, level-aware, and **tolerates a trailing parenthetical qualifier** — this is the "(optional)" suffix convention: `## Project Board (optional)` parses identically to `## Project Board`. Any other rewording makes the section invisible to the picker, which then falls back to defaults.

## Value formats

- **Tables** are 2+ column markdown tables: first cell is a lowercase kebab-case key, second is the value. Backticks around cells are stripped. `n/a` or an empty cell means "unset" for board/field ids.
- **Quality gate**: the command inside the section's fenced code block. Empty or still `{quality_gate_command}` → preflight WARNING.
- **Branch convention**: the first whitespace-delimited token containing `{number}` anywhere in the section (the fenced block, or the backtick-wrapped `Example:` line if the block was left unfilled).
- **Label map rows**: kept only when the purpose key matches `^[a-z]+-[a-z-]+$` (e.g. `claude-authored`). Unmapped purposes resolve to defaults in `templates/default-labels.md` (WARNING, never blocking). There is one issue label left to map, so a row naming a retired one is reported as `label-deprecated` and should be deleted.
- **Ready gate and agent gating**: both gone — the gate as of 9.0.0, the gating as of 10.0.0. A `## Ready Gate` or `## Agent Gating` section left in a file is read and ignored. The pool is the board's `Backlog` column, which no setting turns off, and human approval is the card being in that column rather than a label anyone applies.
- **Type capability**: the literal phrase `is type-capable` (bold tolerated) anywhere in the file switches on native issue-type handling.
- **Project board**: `project-number`, `project-title`, `project-node-id`, `status-field-name` (default `Status`), `status-field-id`, `start-date-field-id`, `end-date-field-id`. In `### Status Options`, each row needs a cell starting `col-` (the purpose key) and an option id — the first cell matching lowercase hex of 6+ chars (`^[0-9a-f]{6,}`).
- **Placeholders**: unreplaced `{org}`-style tokens anywhere trigger a preflight WARNING listing the offending lines. Not repaired by `--fix`: the replacement values are the project's to supply.

## Behaviour on deviation

- **Missing file, missing required section, or `gh` unauthenticated** — preflight CRITICAL: the calling command stops and offers `wf preflight --fix`, the setup wizard, "continue anyway" or "don't remind me". A missing file is reported on its own and stops before the network: with no file there is nothing to compare anything against.
- **Missing recommended/optional content** — WARNING at most; commands proceed on defaults (`templates/default-labels.md` for labels and columns, `main` for the default branch, `feature/{number}/{short-desc}` for branches).
- **Board section absent or unparseable** — CRITICAL `board-lane`. The board is where the pick pool lives, so a project without one selects nothing. A board that **is** configured but has no `Backlog` column, or whose `project-node-id` no longer resolves to the recorded `project-title` is CRITICAL too.
- **`wf.py` parse failures** are never fatal — the picker returns a non-`ok` status and callers fall back to the inline (slower) procedure, so a malformed file degrades performance, not correctness.
