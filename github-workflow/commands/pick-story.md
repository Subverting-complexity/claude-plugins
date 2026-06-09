---
description: 'Pick the next story from the backlog without starting it. Supports mode filtering: default picks highest priority regardless of type, --mode feature for features only, --mode maintenance for bugs/security/arch/debt. Trigger: "what''s next", "pick a story", "show me the next story", "what should I work on", "next issue", "show backlog", "what''s in the queue", "grab a story", "next bug", "next maintenance item", "next feature".'
argument-hint: '[--mode feature|maintenance]'
---

# Pick Story

Select the next story from the backlog.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

## Mode

This command accepts an optional mode argument:

- **story** (default) — Pick the highest priority issue regardless of type
- **feature** — Pick only feature stories (type-story label)
- **maintenance** — Pick the next bug, security, architecture, or tech debt issue (alias: bug)

If mode is "bug", treat it as "maintenance".

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Project configuration (auto-loaded)

This emits a **projection** of `ClaudeProject.md` — the hot-path config
sections (Identity, Branch Convention, Label Map, Ready Gate, Agent
Gating, …) and drops the heavy sections the selection path never reads
(Issue Types & Fields, Project Board, Story Template, Session Budget,
Reference Docs, Bundled Skills). Pick-story needs none of those. If a
`board-column` ready-gate later needs the board, read that section from
`ClaudeProject.md` directly.

```!
if [ -f ClaudeProject.md ]; then
  awk '/^## /{d=0} /^## Issue Types/{d=1} /^## Project Board/{d=1} /^## Story Template/{d=1} /^## Session Budget/{d=1} /^## Reference Docs/{d=1} /^## Bundled Skills/{d=1} !d' ClaudeProject.md
else
  echo "ClaudeProject.md NOT FOUND — run /github-workflow:setup first."
fi
```

## Steps

### 1. Read configuration

Extract from the project configuration above:

- `org` and `repo` from Identity
- `default-branch` from Identity
- `branch-convention` from Branch Convention
- Label map (priority labels, status labels, type labels, claude labels)
- `agent-gating` from Agent Gating (`enabled` or `disabled`, default:
  `disabled`). When `disabled`, the `claude-ready` human-approval label is
  **ignored entirely** — no extra label is required to pick an issue.
- `claude-ready` label name from the Claude label map (only needed when
  gating is enabled)
- `ready-gate` from Ready Gate (`label`, `board-column`, `both`, or
  `none`; default: `label`)
- Project board settings (only needed when `ready-gate` is `board-column`
  or `both`)

Resolve every label name by **purpose key** from the label map in the
project configuration above (already in context) — never filter on a bare
name literally, so the strings this command skips on match the strings
other commands apply. Only open `templates/default-labels.md` as a fallback
if a purpose key is missing from the project map; do not read it just to map
a name the configuration already provides.
When falling back to defaults in an interactive session, warn the user:
"Label map not configured — using default labels. Run
`/github-workflow:setup` to configure labels for this project."

### 2. Select a story

Run the canonical selection procedure in `templates/story-selection.md`
with the configuration above and this command's `mode`. It:

1. detects backlog mode (sprint vs flat),
2. assembles the unassigned candidate list per `ready-gate`
   (`label` / `board-column` / `both` / `none`), applies the agent-gating
   and mode filters, and sorts by priority then issue number,
3. **claims the top candidate first, then validates only that one**
   (dependencies + already-merged) — releasing and trying the next only if
   it fails, marking a genuinely-blocked issue `status-blocked` or closing
   an already-resolved one, and
4. runs the dependency auto-ready scan **only if the pool comes up empty**.

The procedure returns either a single **claimed** issue (the atomic claim
is held and the `status-in-progress` + `@me` markers are applied) or "No
stories available for pickup". **Never ask the user which story to pick** —
selection is fully automatic by the sort order above.

### 3. Display

Once a candidate is claimed, display:

- Issue number and title together (e.g. `#42 Add login button`, never
  the number alone), and URL
- Sprint/milestone (if applicable)
- Priority and type labels
- Brief summary of the issue body

Store the selected issue number for subsequent commands.
