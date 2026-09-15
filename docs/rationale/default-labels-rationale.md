# Label Resolver Rationale

> **Not read at runtime.** This file explains the design decisions behind label resolution and the `Stage` field. The data lives in `github-workflow/scripts/wf_core.py`, the review labels are described in `github-workflow/skills/pr-review/references/review-workflow.md`, and the field and stage tables are in [`../issue-fields.md`](../issue-fields.md).

## Why purpose keys

A label is identified by its **purpose key**, never by a hardcoded concrete name. Purpose keys are stable; concrete names are project-configurable. The bare names that appear in workflow prose (`reviewing`, `updating`, `approved`, `changes-requested`, `needs-discussion`, …) **are purpose keys** — they are resolved to a concrete name through the resolution path, and are never applied literally. This means every workflow works correctly when a project renames a label (e.g. `reviewing` → `wip`), as long as the project config maps the purpose key to the new name.

The keys that survive are the review-state labels on a pull request. The `claude-authored` provenance marker went in 13.2.0: it recorded who built a change, which the pull request's author and commits already say, and it decided nothing. No issue label decides anything any more, and the section below is why.

## Why the single resolution path (apply == filter invariant)

Because producers (skills that *apply* a label) and consumers (skills that *filter or skip* on a label) both start from the same purpose key and run the same three-step resolution path, a claim label written by one skill is the identical string another skill filters on — by construction.

The moment two skills each independently decide "this must be the `reviewing` label," they can silently diverge if one project has overridden it. The single path prevents this class of bug entirely.

## Why no --force at runtime (pre-creation contract)

The review labels are created at setup (`/github-workflow:setup`, step 5b) by `wf labels-ensure`. Nothing may `--force`-overwrite a label — that causes colour/description churn when two callers disagree on metadata, and it overwrites any human-customised label colour with the default.

The guarded create in `wf labels-ensure`, and the same one in `wf review-finish`'s readback, is idempotent and safe: it only creates a label that is absent, and a create that loses a race to another agent counts as done. `wf preflight` reports a missing one as `review-label`, and `--fix` runs the same create.

## Why the `Stage` field is the state and the fields are the ranking

### One record per fact

An issue's state is its org `Stage` field. Its priority, size and owner are the `Priority`, `Effort` and `Ownership` fields. Neither is also recorded anywhere else, and that is the whole design.

The version before 10.0.0 kept a second copy of both. A `status-*` label mirrored the state, and priority was **dual-tracked** — the `Priority` field for the value, a `priority-*` label so the picker's sort could be a cheap label read instead of a field query. Both second copies drift the moment anyone edits either one, and the drift is silent: the picker preferring one issue over another on a `priority-high` somebody set months ago, while the field said `Low`. There is no reconciliation rule that survives a person editing one copy, so the second copy was removed rather than defended. The field query the label was avoiding costs one round trip, which is cheaper than being wrong.

### Why a field on the issue, not a board column

From 10.0.0 until 12.0.0 the state was the `Status` column of the issue's card on a project board. That had three costs nothing could engineer away. An issue with no card had no state and could not be picked. Every transition was a board write, with a board identity to verify first. And an issue on two boards had two states. `Stage` lives on the issue, so every issue has exactly one, a blank one means available, and a board groups its columns by `Stage` to show it. Boards are for people to look at; agents never move cards.

`Ownership` came out of the same argument in the other direction: it never had a label, because `browser-agent` and `human-required` labels would have been a third record of something the field already says, and the field is what `pick` refuses on.

### The stages

An issue moves between nine stages and is at exactly one of them, or at none, which means the same as `Backlog`.

```
                                    ┌──► Needs refinement ──┐  (too thin to build)
                                    │                       ▼
(new issue) ──► Backlog ──────────► In Progress ──────► In Review ──► Done
                  ▲  ▲               │                     (PR open)
                  │  │               └──► Needs attention   (run failed, work still in flight)
                  │  └── Blocked  ◄────── (an open blocked-by edge, or a person; wf unblock returns only the first)
                  │
                  └───── Parked   ◄────── (a person set it aside)

Non-code  ◄────── Ownership is Human or Browser agent  (never enters the pool)
```

A blank or `Backlog` stage is the pool, and it is the only opt-in: `pick` and `candidates` read the repository's open, unassigned issues at those stages and nothing else, so every other stage holds an issue out of the pool. An issue with no board card is still in it.

A `Blocked` issue with no blocked-by edge was set by a person, and the plugin never changes it. Releasing it on "no open blockers" would hand work waiting on the world to an agent that cannot do it.

### Why assignment plus the stage, not the claim ref

The durable owner of in-flight work is the **assignment plus the stage**, *not* the atomic claim ref (which is a short-lived race-protector — see `claim-procedure-rationale.md`). This is what lets a person pause an issue for days and resume it without another agent grabbing it: the picker only ever selects unassigned issues at a blank or `Backlog` stage, so an assigned issue at `In Progress` or `Parked` is excluded twice over, regardless of whether the claim ref has expired.

### The required field

The org must define `Stage` with all nine options. Preflight emits `CRITICAL stage-absent` when the field is missing, because no state can be written or read, and `CRITICAL stage-options` naming any missing option, because a transition to it fails. Setup cannot create an org issue field, so it asks a person to add it in the org settings. A project board is not required.

## Native issue types beyond GitHub's five defaults

`NATIVE_TYPE_MAP` is written for GitHub's five defaults, where nothing can express tech debt and `Feature` is the least wrong answer. An org may add its own types, and `wf_core.NATIVE_TYPE_PREFERENCES` is where a better answer is recorded: `tech debt` and `chore` become `Chore` on an org that has that type, and fall back to the map's `Feature` on one that does not. `org-capabilities` reports the enabled types, and `native_type_for(kind, type_map)` is the single place the choice is made, so the audit and the backfill cannot disagree about it.

Adding a preference has one easily missed consequence: `NATIVE_MAINTENANCE_TYPES` decides what `execute mode=maintenance` may pick, and a type outside that set is invisible to the picker — so a backlog that starts typing its debt `Chore` empties its own maintenance pool unless `Chore` is there too. `architecture` has no preference on purpose: the one org measured had already typed every `[ARCH]` issue `Feature`.
