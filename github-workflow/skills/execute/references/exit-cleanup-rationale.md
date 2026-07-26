# Execute — Exit cleanup rationale (not read at runtime)

The "why" behind the canonical exit-cleanup procedure in
`references/exit-cleanup.md`. Maintainers read this; the runtime workflow
runs the canonical procedure and does **not** need to load this file. The
canonical file keeps the steps; the reasoning lives here.

## Why all three cleanups run on every exit, in order

All three cleanups are idempotent, so they run on *every* exit without
reasoning about which earlier step may already have handled them — and
always after any commit/push, so the pushed branch, not local state, is
the source of truth. The order matters because the scratch files must be
gone before the working-tree check runs, or they would show up as dirt.

## Why release the claim ref

Phase 1 acquired `refs/claims/issue-{number}` as the exclusive lock
(`templates/claim-procedure.md`). Because each session is self-contained and
**there is no cross-session resume**, a session that exits for *any* reason no
longer needs the claim. Holding it past exit would block every future agent
from ever picking the issue — and nothing reaps an abandoned claim ref, so the
issue would silently drop out of the pool forever. Releasing it is idempotent
— a harmless no-op if Phase 7 step 4 or `block-story` already released it.

Releasing frees only the **lock**. The human-visible marker (the assignment)
is intentionally left in place on a failed or timed-out exit as a "this was
attempted" signal next to the failure comment; only `block-story` and a
successful finish also clear ownership.

## Why the PR claim is guarded differently

A run that reaches Phase 9 also holds `refs/claims/pr-{number}` over its own
PR, and that one is **not** released unconditionally. Phase 9 has a path where
it acquires nothing because a rival agent already owns the review, and a ref
delete or a label edit needs push access rather than ownership — so an
unconditional release there would unlock a PR another agent was actively
reviewing. The guard is the file Acquire writes only on a win
(`.claude/claim-pr-{number}.sha`), which is why this claim is released inside a
conditional while the issue claim is not.

The PR claim's marker is also handled differently from the assignment above.
The `reviewing` label is not a "this was attempted" signal: the review picker
skips any PR carrying it, so leaving it would strand the PR outside every
tier. That is why the procedure reconciles it to a real verdict before
releasing the lock, rather than leaving it in place.

Note also that Phase 7 is no longer a terminal exit: the run continues through
review, rework, and the merge, so a successful finish now exits from Phase 11.
That says nothing about the other exit paths. A block, an unrecoverable
failure, a rate-limit pause, or the timeout's not-shippable branch can all fire
before a PR exists, which is exactly why the PR-claim release is gated on
`.claude/claim-pr-{number}.sha` rather than on having reached a phase number.

## Why delete the scratch files

This skill writes several per-session scratch files that must be removed so no
stale data lingers in the worktree — leftover scratch files are what
originally blocked harness worktree auto-cleanup. All are gitignored, but they
must still be cleaned up explicitly.

(`.claude/candidates.json` is no longer written — the candidate fetch was
removed as dead weight — so it is not in the delete command. A stray copy from
an older session is still swept by the working-tree reconcile step.)

## Why reconcile the working tree to clean

A worktree is auto-removed by the harness **only when it is clean**
(`docs/worktree-config.md`). A leftover uncommitted change — even a stray
formatter reflow — pins the worktree open forever. Because Phase 2 started
from a clean tree, anything still dirty at exit was produced by this
session, so it can always be committed or discarded with confidence.
Leaving the tree dirty is never an option. (The how — what to commit
versus discard — is the **End clean** procedure in
`templates/worktree-hygiene.md`, not restated here.)

## Which exits this applies to

Every one, without exception:

- Phase 7 completes successfully (claim already released in its step 4; the
  re-run here is a harmless no-op).
- Blocked via `/github-workflow:block-story` (which releases the claim for you
  — the re-run here is a no-op).
- Unrecoverable error (after leaving the failure comment).
- Session-budget or 45-minute timeout exit.
- API rate-limit pause.
- One-session overflow (partial slice shipped, follow-ups filed).

## When cleanup cannot run from inside the session

A crash, hard kill, or machine reboot can skip this cleanup entirely and
orphan a claim ref. That residue cannot be prevented from inside a session —
run `/github-workflow:setup reap` to scan and free stale refs automatically,
or see **Reaping orphaned claims** in
`templates/claim-procedure-rationale.md` for the manual one-liner.
(Within-session context compaction is unaffected — no exit occurs, so the
files remain on disk for the duration of the run.)
