# Story selection — rationale (not read at runtime)

The "why" behind story selection, now encoded in `wf_core.py` and run by `wf pick`. Maintainers read this; the runtime selection loop does **not** load it. Keep the runtime file imperative; keep the reasoning here.

## Why claim-first, validate-lazily

The selection loop claims the top candidate **first**, then validates only that one — never the whole list up front.

The atomic claim is two cheap git pushes; the dependency and already-merged checks are the expensive per-candidate `gh` calls. Claiming first makes the common case ~3 calls instead of ~60, and it stays race-safe because the ref is acquired before any side effect — validation runs only after you provably own the item. The rare failed candidate costs a little assignee and board churn, which itself does useful work: it moves the card to Blocked, or closes the issue a merged PR already resolved.

Validating the whole sorted list before claiming would invert this: dozens of `gh` calls on issues another agent may grab a moment later, and a time-of-check/time-of-use gap between "looks valid" and "is mine."

## Why the unblock sweep is off the hot path

`pick` runs the `wf unblock` sweep — the pass that returns a Blocked card to Backlog once every issue it waits on has closed — **only** when the Backlog pool produced no claimable candidate, and then retries once. In the common case a story is claimed on the first pass and the sweep's extra API calls never run. Spending those calls to release something is only worthwhile when there is nothing else to pick, so the sweep is deliberately the last resort rather than part of the normal pass.

## Why a blocked issue is never in the pool

A blocked issue is unassigned, so an assignee filter does not exclude it, yet it has an open blocked-by edge. Including it would just claim, re-check, re-block and waste calls every pass. The exclusion is structural rather than a filter: a blocked issue's card sits in the Blocked column, and the pool is the Backlog column. Every other non-pickable state needs no special handling for the same reason — In Progress, In Review, Parked, Needs refinement and Non-code are all lanes that are not Backlog. `wf unblock` moves a card back to Backlog once every edge it waits on has closed, which is the only way an issue re-enters the pool.
