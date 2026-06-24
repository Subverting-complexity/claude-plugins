---
description: 'Pick the next story from the backlog without starting it. Supports mode filtering: default picks highest priority regardless of type, --mode feature for features only, --mode maintenance for bugs/security/arch/debt. Trigger: "what''s next", "pick a story", "next bug", "next feature".'
argument-hint: '[--mode feature|maintenance]'
---

# Pick Story

Select the next story from the backlog.

> **This is a building block.** It only *shows* the next story; it does not
> claim, branch, or implement it. To actually work a story end-to-end, use
> **`/github-workflow:execute`**. Use `pick-story` when you just want to see
> what is next without committing to it.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

## Mode

This command accepts an optional mode argument:

- **story** (default) — Pick the highest priority issue regardless of type
- **feature** — Pick only feature stories (type-story label)
- **maintenance** — Pick the next bug, security, architecture, or tech debt issue (alias: bug)

If mode is "bug", treat it as "maintenance".

## Preflight

Check whether preflight already ran and passed this session — if
`.claude/preflight-passed.txt` exists, skip the invocation entirely and
proceed to the project configuration below. The file is written by
`preflight` on a clean or WARNING-only run and is valid for exactly this
session:

```
test -f .claude/preflight-passed.txt && echo "PREFLIGHT_ALREADY_PASSED"
```

If the file is absent, invoke `/github-workflow:preflight` to verify
project configuration. If it finds issues and the user chooses "Configure
now", wait for setup to complete, then ask the user to re-run this
command. Otherwise, proceed.

## Project configuration (auto-loaded)

This emits a **projection** of `ClaudeProject.md` — the hot-path config
sections (Identity, Branch Convention, Label Map, Ready Gate, Agent
Gating, …) and drops the heavy sections the selection path never reads
(Issue Types & Fields, Project Board, Story Template, Session Budget,
Reference Docs, Bundled Skills). Pick-story needs none of those. If a
`board-column` ready-gate later needs the board, read that section from
`ClaudeProject.md` directly.

```!
if [ -f .claude/projected-config.md ] && [ .claude/projected-config.md -nt ClaudeProject.md ] 2>/dev/null; then
  cat .claude/projected-config.md
elif [ -f ClaudeProject.md ]; then
  # Project ClaudeProject.md → drop the heavy sections only needed later.
  # Pure POSIX shell (no awk/tee) so it works wherever bash runs, including
  # a Windows bash whose PATH lacks the Unix coreutils that ship awk/tee.
  mkdir -p .claude 2>/dev/null
  drop=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '## '*) case "$line" in
          '## Issue Types & Fields'*|'## Project Board'*|'## Story Template'*|'## Session Budget'*|'## Reference Docs'*|'## Bundled Skills'*) drop=1 ;;
          *) drop=0 ;;
        esac ;;
    esac
    [ "$drop" -eq 0 ] && printf '%s\n' "$line"
  done < ClaudeProject.md > .claude/projected-config.md
  cat .claude/projected-config.md
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

Selection is fully mechanical — priority order, then lowest issue number,
then an atomic claim. There are two ways to run it; **prefer the fast
path**, which collapses the whole select → claim → validate loop into one
process call instead of a dozen sequential `gh` round-trips.

#### Fast path — the bundled `wf` picker

The plugin ships a `wf` CLI (`scripts/wf.py`, with a `wf.sh` launcher that
finds a working Python 3) that does the entire selection and claim in a
single call and returns the chosen story as JSON. Run it from the repo root
so it can read `ClaudeProject.md` and the git remote (pass the command's
`mode` through):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --mode {mode}
```

Interpret the result by its `status` field (the process exit code mirrors
it):

- **`ok`** — a story is claimed. The JSON carries `number`, `title`, `url`,
  `labels`, `milestone`, `body`, and `claim_ref`; the
  `status-in-progress` + `@me` markers are already applied and the claim ref
  is held. Go straight to Step 3 — **do not re-run any selection or
  re-derive the choice; the picker already chose and locked it.** If
  `side_effects` is non-empty, tell the user what it touched (issues it
  returned to blocked, or closed as already-resolved by a merged PR).
- **`no-candidates`** or **`all-blocked`** — nothing was pickable. Run
  **only Step 4** (lazy auto-ready) of `templates/story-selection.md`; if it
  restores anything, retry the fast path once, else report "No stories
  available for pickup".
- **`unsupported`** — `wf` deferred this case (a `feature` / `maintenance`
  mode on a **type-capable** org, where the native issue type is
  authoritative, or a `board-column` / `both` ready-gate). Use the inline
  procedure below.
- **`error`**, or the launcher prints that Python is missing — `wf` can't
  run in this environment. Use the inline procedure below.

`wf pick` covers **story, feature, and maintenance** modes on label-typed
projects (it filters by the `type-*` label). It defers to the inline
procedure only on a type-capable org, where feature/maintenance must filter
by the native issue type.

#### Inline procedure (fallback)

Run the canonical selection procedure in `templates/story-selection.md`
with the configuration above and this command's `mode`. It is the same
logic `wf` encodes, kept here as the source of truth and the degraded-mode
path when `wf` is unavailable. It:

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
