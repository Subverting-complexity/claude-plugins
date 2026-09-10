---
name: preflight
description: >-
  Check project configuration health before running workflow commands.
  Verifies critical files exist, required sections are present, and
  settings are consistent. Invoked automatically by other commands —
  can also be run directly as a diagnostic. Trigger on "check my
  config", "preflight", or "validate setup".
---

# Preflight Check

Verify project configuration is complete and consistent before running workflow commands.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## 1. Run the check

One command answers the whole question. Do not re-derive any part of it by reading files, and do not run `gh` by hand: every check `preflight` makes is in Python, is covered by the offline test suite, and gives the same answer twice for the same project. A second implementation in shell is what this replaced.

```!
if [ -f .claude/preflight-passed.txt ]; then
  echo "PREFLIGHT_ALREADY_PASSED"
elif [ -f .claude/preflight-dismiss.md ]; then
  echo "PREFLIGHT_SUPPRESSED"
elif [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" ]; then
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" preflight
  echo "PREFLIGHT_EXIT: $?"
else
  echo "PREFLIGHT_UNAVAILABLE"
fi
```

**React to the token, do not re-derive it.**

- `PREFLIGHT_ALREADY_PASSED` — preflight passed earlier this session. **Return silently and immediately**; the calling command proceeds.
- `PREFLIGHT_SUPPRESSED` — the user dismissed preflight reminders. Return silently; the calling command proceeds. They re-enable by deleting `.claude/preflight-dismiss.md` or running `/github-workflow:setup`.
- `PREFLIGHT_UNAVAILABLE` — the plugin's scripts are not on disk, so nothing was checked. Say so in one line and let the command proceed; do not substitute a hand-run version of the checks.
- Otherwise read the JSON object it printed. `PREFLIGHT_EXIT` is `0` when nothing blocks and `26` when something does.

## 2. Read the result

The object carries `summary` (counts by level and by check), `checked` and `skipped` (which checks ran, so silence can be told from absence), and `findings`. Each finding has `level`, `check`, `detail`, `fix`, `where` — the file to open — and two fields that say what `wf preflight --fix` would do with it:

- `auto: true` — a run can repair this without guessing. `fixable` says how.
- `auto: false` — it must not. `fixable` says why: the value is the project's to choose, or two configured things disagree and either could be the right one, or the repair happens in the org settings rather than through the API.

**If `summary.critical` is `0`.** Nothing blocks. Write the pass marker so later commands in this session skip the re-run, then return control **silently** — do not compose a report, and do not mention preflight:

```
mkdir -p .claude
echo "preflight-passed" > .claude/preflight-passed.txt
```

If `summary.warning` is above zero, print **one** line first naming what is running on a default (e.g. "Quality gate not configured; run `/github-workflow:setup` to set one") and then do exactly the same. A warning is a thing that still works, so it never prompts and never blocks.

**If `summary.critical` is above zero.** Go to Section 3. Report every critical finding's `detail` and `fix` **verbatim** rather than paraphrasing — the fix for an unpinned field is a specific form in the org settings, and a paraphrase loses it.

## 3. Present the findings and ask

Show a brief summary using these markers:

- `[pass]` — briefly, what came back clean
- `[action needed]` — each critical finding: its `detail`, then its `fix`
- `[recommended]` — each warning, as informational; they are proceeding on defaults, not reasons to configure

Then use `AskUserQuestion`. Offer the repair option **only when at least one critical finding has `auto: true`**; a run that would repair nothing must not offer to:

- **"Fix what can be fixed (Recommended)"** — run `wf preflight --fix`. It repairs every finding it can repair without guessing, re-runs the checks, and reports the state it leaves behind rather than the state it found. Read the `fixed` and `unfixed` arrays it returns and say what changed. If `summary.critical` is then `0`, write the pass marker and continue.
- **"Configure now"** — run `/github-workflow:setup`. Afterwards, tell the user to re-run the command they originally asked for, because the configuration loaded at the start of that command is now stale.
- **"Continue anyway"** — return immediately. The calling command proceeds on whatever configuration exists. Preflight runs again next time.
- **"Don't remind me"** — write `.claude/preflight-dismiss.md`, then return:

```
# Preflight checks dismissed

Configuration checks have been suppressed. To re-enable:

- Delete this file, OR
- Run `/github-workflow:setup`
```

## What each check means

Named here so a finding can be acted on without reading the source. `wf preflight --help` lists the flags; `--offline` skips every network check, `--quiet` reports counts only for CI.

| Check | Level | What it means |
| ----- | ----- | ------------- |
| `gh-auth` | critical | The GitHub CLI cannot act for this repository. Nothing else can run. |
| `file-config` | critical | There is no `ClaudeProject.md`, so every value the workflow reads is a default nobody chose. |
| `config-section` | critical | A section the plugin reads is absent, so its values fall back silently. |
| `board-lane` | critical | No board, a `project-node-id` that resolves to nothing, or no `Backlog` column. The pool *is* that column, so any of the three means selection reads nothing. A missing lane other than Backlog warns instead: it costs one state's move. |
| `board-orphan` | critical | An open, unassigned issue with no card. Invisible to `pick` whatever it carries. |
| `board-unset` | critical | A card in no lane. The column is the state, so the issue has none. |
| `field-absent` | critical | The org defines no `Priority`, `Effort` or `Ownership`, and the picker reads all three. |
| `label-reference` | critical | An instruction file tells an agent to apply a label the repo does not have. `gh` refuses it and the issue stays as it was. |
| `field-unpinned` | critical | An issue type does not pin a field the tooling writes, so values written to it never appear on the issue form. |
| `config-retired` | warning | A `## Ready Gate` or `## Agent Gating` section survives. Nothing reads it, and leaving it there means the next person believes it. |
| `label-deprecated` | warning | The label map names a label nothing applies any more. |
| `placeholders` | warning | Template placeholders nobody replaced. |
| `quality-gate` | warning | No pre-commit command, so nothing checks a change before it is committed. |
| `claude-md-ref` | warning | `CLAUDE.md` never mentions `ClaudeProject.md`, so a session that runs no workflow command never finds the configuration. |
| `review-config` | warning | `ClaudeProject.md` points at a review-state label file that is not there, so every review label falls back to its default name. |
| `board-column` | warning | A recorded option id no longer resolves. Moves still work — they resolve by name — so this prompts a snapshot refresh. |
| `board-title` | warning | `project-title` and the node id disagree. Not repaired automatically: either could be the right one. |
| `field-options` | critical or warning | An option on `Priority`, `Effort` or `Ownership` that no decision here knows. Critical for `Ownership`, because nothing can route an issue carrying it; a warning for the other two, because the issue still sorts, just last or as `Medium`. |
| `board-retired` | warning | The board still has a `Ready` column. Nothing selects from it, so a card there is invisible to every command. |
| `label-retired` | warning | Open issues still carry a label the fields replaced (`status-*`, `priority-*`, `browser-agent`, `human-required`, `needs-refinement`, `claude-ready`). It decides nothing, and it misleads anyone filtering the issues list by hand. |
| `instructions-retired` | warning | A `CLAUDE.md` or `ClaudeProject.md` in the project still describes the `Ready` opt-in, a lifecycle, priority or scope label, or a dependency written as prose. A session reading it is told to do something the tooling no longer does. |
| `container-finished` | warning | An open Epic or Feature whose sub-issues are all closed. Nothing else closes a container, so finished ones pile up out of sight. A container with no sub-issues is never flagged. |

## What `--fix` will and will not do

It repairs ten things, all idempotent: it creates a missing board column, rewrites the `### Status Options` table from the live board, deletes a retired section, deletes a deprecated label-map row, adds the `ClaudeProject.md` pointer to an existing `CLAUDE.md`, puts an orphaned issue or an unset card into `Backlog`, takes retired labels off the open issues carrying them, empties a `Ready` column into `Backlog` before deleting the column, and closes an open Epic or Feature whose sub-issues are all closed, as completed, moving it to Done.

`Backlog` and not "wherever it belongs", because nothing on an orphaned issue says where it belongs and the pool is the one lane that means "nobody has decided anything about this yet". Somebody moving it straight back out is a decision; leaving it invisible is not. The `Ready` column is emptied first and deleted second, and only when every card in it moved: deleting a column deletes the value from each card in it, which would leave those issues in no lane at all.

It will not create a `CLAUDE.md` that does not exist, invent an `## Identity` section, create or delete an org-level issue field, rename a field's options, pin a field to an issue type, choose between two disagreeing values, rewrite a sentence in somebody's `CLAUDE.md`, or write a quality gate. Each of those is either a decision only the project can make or a change that happens in the GitHub org settings rather than through the API this runs on. A finding it leaves alone comes back with `auto: false` and a reason, and after `--fix` it is still in `findings` — which is the point: what the command reports is the state it leaves behind.

## Auto-merge safety checks

`wf preflight` reports `review-config` when the file `ClaudeProject.md` names is missing. It does not check the repo's own "Allow auto-merge" setting or whether a CI gate exists, because both cost a round trip that only matters to a project that opted in. If `docs/review.config.md` sets `auto-merge-on-approval: enabled`, read `references/review-auto-merge-checks.md` and run its two checks. Otherwise skip it entirely.
