# Story selection — rationale (not read at runtime)

The "why" behind `templates/story-selection.md`. Maintainers read this;
the runtime selection loop does **not** load it. Keep the runtime file
imperative; keep the reasoning here.

## Why claim-first, validate-lazily

The selection loop claims the top candidate **first**, then validates only
that one — never the whole list up front.

The atomic claim is two cheap git pushes; the dependency and
already-merged checks are the expensive per-candidate `gh` calls. Claiming
first makes the common case ~3 calls instead of ~60, and it stays
race-safe because the ref is acquired before any side effect — validation
runs only after you provably own the item. The rare failed candidate
costs a little label/assignee churn, which itself does useful work (it
marks the issue `status-blocked` or closes it).

Validating the whole sorted list before claiming would invert this: dozens
of `gh` calls on issues another agent may grab a moment later, and a
time-of-check/time-of-use gap between "looks valid" and "is mine."

## Why the auto-ready scan is off the hot path

Step 4 (the dependency auto-ready scan) runs **only** when Steps 1–3
produced no claimable candidate. In the common case a story is claimed in
Step 3 and Step 4's extra API calls never run. Spending those calls to
unblock something is only worthwhile when there is nothing else to pick —
so the scan is deliberately the last resort, not part of the normal pass.

## Why drop `status-blocked` under a `none` ready-gate

Under `ready-gate: none` every open unassigned issue is eligible, but a
`status-blocked` issue is unassigned (so `--assignee ""` does not exclude
it) yet has an unresolved blocker. Including it would just claim, re-check,
re-block, and waste calls each pass. The other non-pickable states need no
special handling: `status-parked` / `status-in-progress` /
`status-in-review` stay assigned (already excluded), and `needs-refinement`
is dropped by the refinement filter. A `status-blocked` issue whose
dependencies have actually closed is restored to `status-ready` by Step 4
on a later pass.
