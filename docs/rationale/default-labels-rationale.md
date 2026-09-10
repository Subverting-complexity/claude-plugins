# Label Resolver Rationale

> **Not read at runtime.** This file explains the design decisions behind `default-labels.md`. Consult it for background; the data tables and resolution directives live in `default-labels.md`.

## Why purpose keys

A label is identified by its **purpose key**, never by a hardcoded concrete name. Purpose keys are stable; concrete names are project-configurable. The bare names that appear in workflow prose (`reviewing`, `updating`, `approved`, `changes-requested`, `needs-discussion`, `claude-authored`, …) **are purpose keys** — they are resolved to a concrete name through the resolution path, and are never applied literally. This means every workflow works correctly when a project renames a label (e.g. `reviewing` → `wip`), as long as the project config maps the purpose key to the new name.

The keys that survive are all review-state labels on a pull request plus the `claude-authored` provenance marker. No issue label decides anything any more, and the section below is why.

## Why the single resolution path (apply == filter invariant)

Because producers (skills that *apply* a label) and consumers (skills that *filter or skip* on a label) both start from the same purpose key and run the same three-step resolution path, a claim label written by one skill is the identical string another skill filters on — by construction.

The moment two skills each independently decide "this must be the `reviewing` label," they can silently diverge if one project has overridden it. The single path prevents this class of bug entirely.

## Why no --force at runtime (pre-creation contract)

The complete label inventory is created **once** at setup (`/github-workflow:setup`, step 5b). Skills at runtime must **not** `--force`-overwrite labels — that causes colour/description churn when two skills disagree on metadata, and it overwrites any human-customised label colour with the default.

The guarded create-if-missing pattern in `default-labels.md` is idempotent and safe: it only creates if the label is absent, and it warns when it does so (setup should have created everything; a missing label is a setup gap, not a normal flow).

## Why the column is the state and the fields are the ranking

### One record per fact

An issue's state is the board column its card sits in. Its priority, size and owner are the `Priority`, `Effort` and `Ownership` fields. Neither is also recorded anywhere else, and that is the whole design.

The version this replaced kept a second copy of both. A `status-*` label mirrored the column, and priority was **dual-tracked** — the `Priority` field for the value, a `priority-*` label so the picker's sort could be a cheap label read instead of a field query. Both second copies drift the moment anyone edits either one, and the drift is silent: the picker preferring one issue over another on a `priority-high` somebody set months ago, while the field said `Low`; a card dragged into Blocked on a board while the label still said in progress. There is no reconciliation rule that survives a person moving a card, so the second copy was removed rather than defended. The field query the label was avoiding costs one round trip, which is cheaper than being wrong.

`Ownership` came out of the same argument in the other direction: it never had a label, because `browser-agent` and `human-required` labels would have been a third record of something the field already says, and the field is what `pick` refuses on.

### The lanes

An issue moves between nine columns and is in exactly one of them.

```
                                    ┌──► Needs refinement ──┐  (too thin to build)
                                    │                       ▼
(new issue) ──► Backlog ──────────► In Progress ──────► In Review ──► Done
                  ▲  ▲               │                     (PR open)
                  │  │               └──► Needs attention   (run failed, work still in flight)
                  │  └── Blocked  ◄────── (an open blocked-by edge; wf unblock returns it)
                  │
                  └───── Parked   ◄────── (a person set it aside)

Non-code  ◄────── Ownership is Human or Browser agent  (never enters the pool)
```

Backlog is the pool, and it is the only opt-out: `pick` and `candidates` read that column and nothing else, so every other lane holds an issue out of the pool simply by holding the card.

### Why assignment plus the column, not the claim ref

The durable owner of in-flight work is the **assignment plus the column**, *not* the atomic claim ref (which is a short-lived race-protector — see `claim-procedure-rationale.md`). This is what lets a person pause an issue for days and resume it without another agent grabbing it: the picker only ever selects unassigned issues in Backlog, so an assigned card in In Progress or Parked is excluded twice over, regardless of whether the claim ref has expired.

### Required columns

A board is required, and `Backlog` is required on it: that column is the pick pool. Preflight emits `CRITICAL board-lane` for a missing board, an unresolvable `project-node-id`, or a missing Backlog column, and `WARNING board-lane` for any other missing lane; setup creates them all.

## Native issue types beyond GitHub's five defaults

`NATIVE_TYPE_MAP` is written for GitHub's five defaults, where nothing can express tech debt and `Feature` is the least wrong answer. An org may add its own types, and `wf_core.NATIVE_TYPE_PREFERENCES` is where a better answer is recorded: `tech debt` and `chore` become `Chore` on an org that has that type, and fall back to the map's `Feature` on one that does not. `org-capabilities` reports the enabled types, and `native_type_for(kind, type_map)` is the single place the choice is made, so the audit and the backfill cannot disagree about it.

Adding a preference has one easily missed consequence: `NATIVE_MAINTENANCE_TYPES` decides what `execute mode=maintenance` may pick, and a type outside that set is invisible to the picker — so a backlog that starts typing its debt `Chore` empties its own maintenance pool unless `Chore` is there too. `architecture` has no preference on purpose: the one org measured had already typed every `[ARCH]` issue `Feature`.
