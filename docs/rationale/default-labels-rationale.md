# Label Resolver Rationale

> **Not read at runtime.** This file explains the design decisions behind `default-labels.md`. Consult it for background; the data tables and resolution directives live in `default-labels.md`.

## Why purpose keys

A label is identified by its **purpose key**, never by a hardcoded concrete name. Purpose keys are stable; concrete names are project-configurable. The bare names that appear in workflow prose (`reviewing`, `updating`, `approved`, `changes-requested`, `needs-discussion`, `claude-authored`, `status-ready`, …) **are purpose keys** — they are resolved to a concrete name through the resolution path, and are never applied literally. This means every workflow works correctly when a project renames a label (e.g. `reviewing` → `wip`), as long as the project config maps the purpose key to the new name.

## Why the single resolution path (apply == filter invariant)

Because producers (skills that *apply* a label) and consumers (skills that *filter or skip* on a label) both start from the same purpose key and run the same three-step resolution path, a claim label written by one skill is the identical string another skill filters on — by construction.

The moment two skills each independently decide "this must be the `reviewing` label," they can silently diverge if one project has overridden it. The single path prevents this class of bug entirely.

## Why no --force at runtime (pre-creation contract)

The complete label inventory is created **once** at setup (`/github-workflow:setup`, step 5b). Skills at runtime must **not** `--force`-overwrite labels — that causes colour/description churn when two skills disagree on metadata, and it overwrites any human-customised label colour with the default.

The guarded create-if-missing pattern in `default-labels.md` is idempotent and safe: it only creates if the label is absent, and it warns when it does so (setup should have created everything; a missing label is a setup gap, not a normal flow).

## Issue lifecycle: dual-tracking and state transitions

### Dual-tracking for priority

Priority is **dual-tracked** — both the `Priority` native field *and* the `priority-*` label are set when creating or updating an issue. The field carries the rich enum value; the label makes the selector's priority sort a cheap label read without a field-query round-trip.

Native issue types are **not** dual-tracked: on a type-capable org the native type replaces the `type-*` label entirely.

Capability is detected at runtime, per dimension: an org with **no** native types, or missing a given field, transparently keeps the label-only behaviour for that dimension.

### Lifecycle state transition diagram

The lifecycle state labels are the **issue-side mirror** of the PR review-state machine. Every issue always carries exactly one lifecycle state, so the issues list shows what is happening at a glance — without depending on a project board (board updates are best-effort and may not be configured).

```
                          ┌──────────────► needs-refinement ──┐
                          │                                    ▼
(new issue) ─► status-ready ─► status-in-progress ─► status-in-review ─► (closed)
                  ▲   ▲              │   │
                  │   │              │   └─► status-needs-attention (run failed)
                  │   └──────────────┘        │
                  │     (parked/blocked        │ (human resumes)
                  │      cleared)              ▼
                  └──── status-parked ◄── (human pauses)
                  └──── status-blocked ◄─ (block-story; cleared when deps close)
```

### Why parked + assignment, not the claim ref

`status-parked` and `status-blocked` both remove the issue from the pick pool. The durable owner of in-flight work is the **assignment + the `status-in-progress`/`status-parked` label**, *not* the atomic claim ref (which is a short-lived race-protector — see `claim-procedure-rationale.md`). This is what lets a human pause an issue for days and resume it without another agent grabbing it: the picker only ever selects *unassigned* issues, so an assigned + labelled issue is excluded regardless of whether the claim ref has expired.

## Board columns rationale

The board is the **board-side mirror** of the issue lifecycle. When a project board is configured, every command that moves an issue to a new lifecycle *label* also moves its board item to the paired *column* — so the board never drifts from the labels.

This extends the **apply == filter** invariant to the board — every producer and consumer resolves a column through one path, so the column a command moves to is the same column the picker reads.

### Column behaviour notes

- `status-needs-attention` stays in **In Progress** — the work is still in-flight; the label flags it for a human.
- `status-parked` shares the **Blocked** column with `status-blocked` (both mean "set aside, out of the pick pool"); the distinct label preserves the reason.

### Required columns

When a board is configured, the three active columns — In Progress, In Review, Blocked — must exist (preflight emits `CRITICAL board-columns-incomplete` if any is missing; setup creates them). The Ready column is additionally required only under a `board-column`/`both` ready-gate.
