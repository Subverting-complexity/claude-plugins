# Execute — Exit cleanup rationale (not read at runtime)

The "why" behind the three cleanup commands in the `execute` `SKILL.md`
**Exit cleanup** section. Maintainers read this; the runtime workflow runs
the commands inline and does **not** need to load this file. The section
keeps the commands; the reasoning lives here.

## Why all three cleanups run on every exit, in order

Every exit path must leave three things clean: the **atomic claim ref**, the
**per-session scratch files**, and the **working tree itself**. All three
cleanups are idempotent, so they run on *every* exit without reasoning about
which earlier step may already have handled them. They run as the **final**
step before the session ends, and always **after** any commit/push (so the
pushed branch — not local state — is the source of truth). The order matters:
release the claim, delete the scratch files, then reconcile the tree — so the
scratch files are gone before the tree check runs.

## Why release the claim ref

Phase 1 acquired `refs/claims/issue-{number}` as the exclusive lock
(`templates/claim-procedure.md`). Because each session is self-contained and
**there is no cross-session resume**, a session that exits for *any* reason no
longer needs the claim. Holding it past exit would block every future agent
from ever picking the issue — and nothing reaps an abandoned claim ref, so the
issue would silently drop out of the pool forever. Releasing it is idempotent
— a harmless no-op if Phase 7.5 or `block-story` already released it.

Releasing frees only the **lock**. The human-visible marker (the assignment)
is intentionally left in place on a failed or timed-out exit as a "this was
attempted" signal next to the failure comment; only `block-story` and a
successful finish also clear ownership.

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
formatter reflow — pins the worktree open forever. The **End clean** procedure
in `templates/worktree-hygiene.md` requires `git status --porcelain` to end
empty. Because Phase 2 started from a clean tree, anything still dirty at exit
was produced by this session — commit a forgotten story file, commit
incidental formatting on unrelated files as a **separate `chore:` commit** (do
not fold it into the feature diff), or discard disposable generated noise.
**Never `git stash`** — the stash is shared across every worktree on the
clone. Leaving the tree dirty is never an option.

## Which exits this applies to

Every one, without exception:

- Phase 7 completes successfully (claim already released in 7.5; the re-run
  here is a harmless no-op).
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
