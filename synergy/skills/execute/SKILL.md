---
name: execute
description: 'Take a GitHub story end to end: pick, plan, build, test, open a PR, independent review, merge where enabled. Trigger on "next story", "work on story N", a bare issue number or an issue URL. Modes: feature, maintenance, audit.'
depends-on:
  - code-architect
  - feature-discovery
  - pr-review
argument-hint: '[issue#] [--mode feature|maintenance|audit] [--no-merge] [--bypass-ci]'
arguments:
  - name: story_number
    description: 'Optional issue number. If omitted, picks the next story from the backlog.'
  - name: mode
    description: 'Execution mode: story (default — picks highest priority issue regardless of type), feature (feature stories only), maintenance (bug/security/architecture/debt; "bug" is accepted as alias), audit (codebase audit, no code changes)'
  - name: no-merge
    description: 'When set, stop after the independent review and rework instead of merging. The PR is left open carrying the reviewer verdict. Only meaningful where merging is switched on at all — see Auto-Merge on Approval.'
  - name: bypass-ci
    description: 'Passed through to the Phase 10 merge gate: treats CI as satisfied when remote checks are red or absent. Explicit, never default — use only when CI cannot run for reasons outside the PR (e.g. GitHub Actions billing).'
---

# Execute Story

Take one story end to end: pick it, plan, build, test, open a PR, have that PR reviewed in a fresh context, apply the fixes the review asks for, and merge it where the project has opted in. A story is finished when its PR has been reviewed and answered, not when the PR opens.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## Shared rules

Once, at the start, read `references/shared-phases.md` and follow it: autonomy, invocation flags, the preflight and configuration checks, API quota, session budget, fix in scope, exit cleanup, and the plan, build, verify, commit and review hand-off rules this skill shares with `bulk-execute`. This file holds what differs.

The only reasons to stop before a PR exists:

- The issue is so underspecified that any implementation would be a guess — send it to refinement and pick the next one. Not `Blocked`: the plugin releases `Blocked` only when every blocked-by edge has closed, so an issue blocked without one is never released.
- The story needs breaking into sub-stories — run `/synergy:feature-discovery` to plan the breakdown with the user, then pick the first sub-story.

## Project configuration (auto-loaded)

A projection of `ClaudeProject.md` with the sections needed only later dropped. The shared rules say how to check it.

```!
if [ -f .claude/projected-config.md ] && [ .claude/projected-config.md -nt ClaudeProject.md ] 2>/dev/null; then
  cat .claude/projected-config.md
elif [ -f ClaudeProject.md ]; then
  # Drop the heavy sections only needed later. Pure POSIX shell (no
  # awk/tee) so it runs on a Windows bash whose PATH lacks Unix coreutils.
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
  echo "ClaudeProject.md NOT FOUND"
fi
```

## Session budget

Stay under ~100k tokens: **one story per session**, scoped to a merged PR or an open one whose review state is recorded. (Design rationale: `docs/rationale/execute-rationale.md`, not read at runtime.)

- **Too large for one session** → implement the highest-priority slice, open a PR for it, and file follow-ups with `/synergy:report-issue`.
- **45-minute timeout.** Past 45 minutes, commit and push everything. **Shippable** → run Phase 7 for a real PR, never a draft, and carry on into Phases 8 to 10, starting a rework round only if you can finish it. **Not shippable** → leave the branch pushed, run `wf stage-set {number} --stage stage-attention` with a comment listing what remains, and open no PR. Either way, file follow-ups for unfinished work, run **Exit cleanup** (`references/exit-cleanup.md`), and exit without starting a phase you may not finish.

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`:

- **story** — the next highest-priority issue regardless of type
- **feature** — feature stories only (native issue type `User Story`)
- **maintenance** — the next bug, security, architecture or tech debt issue (`bug` is accepted as an alias)
- **audit** — audit the codebase and file issues for findings, no code changes

If mode is `audit`, do not run the phases below — read `references/audit-mode.md` and follow it.

---

## Phase 1 — Pick

`wf pick` collapses select, claim, stage and branch into one deterministic call, and it is the only way to pick a story. A `wf` that cannot run is a stop, not a detour. From the repo root:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --checkout --mode {mode}
```

`{mode}` is `$ARGUMENTS.mode`, default `story`. Add `--unattended` when nobody is present to answer a question. It reads every open issue, judges each by the pick rules in `scripts/README.md`, sorts by `Priority` then `Effort`, and **claims the top candidate before any side effect**, walking down the list on a lost claim, setting a genuinely blocked issue to `Blocked`, closing one a merged PR already resolved, and running the unblock scan if the pool comes up empty.

Read the result by its `status`; the exit code mirrors it:

| `status` | exit | What you do |
| -------- | ---- | ----------- |
| `ok` | 0 | A story is claimed and you are on its branch. **Stop selecting — do not re-derive anything.** |
| `no-candidates` | 10 | Nothing was pickable. Stop with "No stories available for pickup". |
| `all-blocked` | 11 | Every candidate was blocked or already claimed. Stop the same way. |
| `needs-refinement` | 12 | The next pick is too unclear to build; nothing was claimed and `detail` says why. Run `/synergy:interview` on issue `number` with the user, then `pick --issue {number} --checkout`; for an Epic or Feature, run `refinement-skill` and re-run `pick`. If they skip it, send it to refinement (`references/pick-paths.md`) and re-run `pick`. |
| `unsupported` | 30 | `wf` deferred this configuration (reserved). Stop and report what it named. |
| `error` | 20, or Python is missing | `wf` cannot run here. Stop and name the prerequisite: Python 3.8+ on `PATH` and an authenticated `gh`. Do not select a story by hand. |

On `ok` the JSON carries `number`, `title`, `url`, `labels`, `milestone`, `body`, `claim_ref`, `branch`, `checked_out`, `stage_set`, `stage_message`, `start_date_set` and `side_effects`. The stage is `In Progress`, `@me` is assigned, and the claim ref is held. Surface any `side_effects`. If `checked_out` is false, read `branch_message` (a rebase conflict, say) and run `/synergy:block-story` instead of building.

When the pick came through an Epic or Feature, `container` names it and `offered` lists its other pickable stories. Decide in Phase 3 whether they belong in this PR: to add one, claim it with `pick --issue {n} --checkout --no-branch --sibling {number}` and build the set as `bulk-execute` does; otherwise leave them in the pool.

**When `$ARGUMENTS.story_number` is given**, do not run the pick above. Follow **An explicit story number** in `references/pick-paths.md`, which guards against a story already in flight and then claims it.

**Then, on the claimed story**, read the full issue body and confirm it has **Context** and **Requirements**. Enough guidance (body, comments, linked docs) → Phase 2. If it is thin or empty, follow **A thin or empty story** in `references/pick-paths.md`.

## Phase 2 — Start

`wf pick --checkout` already took the claim, set the stage and start date, and created the branch. Only when its `ok` result says a step did not happen (`stage_set` or `checked_out` false), or the claim state was lost to compaction, follow **Phase 2 recovery** in `references/pick-paths.md`.

**Interactive discovery gate.** When a user is present and mode is `story` or `feature`, run `/synergy:interview` on the story's requirements before planning. Skip it in an autonomous session, in `maintenance` or `audit` mode, or when the issue body already has discovery output (`## Stories` or `## Architecture`).

## Phase 3 — Plan

Use `/synergy:code-architect` to plan the implementation, passing the issue requirements, the relevant codebase context, and any reference docs listed in `ClaudeProject.md`. The plan file and ecosystem tools are in the shared rules.

## Phases 4 to 6 — Build, verify, commit

As the shared rules specify, for this one story.

## Phase 7 — Finish

Once the work is committed, **read `references/finish.md`** and follow it end to end: push, duplicate-PR detection, PR create, labels, stage, claim release, progress note.

## Phases 8 to 10 — Review, rework, merge

The moment the PR exists, **read `references/review-and-merge.md`** and follow it to the end of the run, in the same turn as Phase 7. Phase 8 spawns one reviewer in a fresh context, Phase 9 fixes what it found and re-reviews only substantial rework, and Phase 10 merges where `Auto-Merge on Approval` is `enabled`.

---

## Escape hatches

If a run leaves the happy path — execution **fails** unrecoverably, a phase is **blocked**, you find an unrelated **problem** to file, the story has an unmerged **dependency**, it is **too broad** to start or **too large** for one session, or **review feedback** arrives after the PR opens — **read `references/escape-hatches.md`** and follow the procedure for that condition.
