# Worktree hygiene

The harness gives each parallel/background agent its own git worktree and **only auto-removes a worktree once it is clean** (see `docs/worktree-config.md`). Any uncommitted change — yours, a previous session's, or a formatter's — pins the worktree open: it is never reaped, its branch stays checked out, and stale worktrees pile up until cleanup fails on locks and long paths. There is **no cross-session resume**, so a worktree left dirty for "a later session to inspect" is never inspected — the work is simply stranded.

Both ends of a session are one `wf` call. **Never `git stash`**: the stash is shared across every worktree on the clone, so stashing in one can surface in or collide with another agent's.

## Start clean

`wf pick --checkout` branches from `origin/{default-branch}`, and `wf start` (`--issue N`, or `--group G --branch B` for a bulk group) resets a tree provisioned dirty before it branches. A dirty tree at the start is inherited junk, not this session's work, so it is discarded and the result names each path. Report those paths to the user. `git clean` runs without `-x`, so gitignored files such as `.env` and `node_modules` are kept.

## End clean

`wf exit-cleanup` checks the tree last and prints `dirty` with the paths still uncommitted. Every one was produced by this session, because the start was clean:

- **A story file you forgot to commit** — commit it to the feature branch and push.
- **Formatting on files outside the story** — commit it as a separate `chore: formatting` commit and push. If the session opened a PR, the commit rides the same branch, clearly labelled.
- **Generated noise** you do not track — discard it with `wf tree-clean --discard {path}` (or `--all`), which re-checks the tree. If it keeps reappearing, it should be gitignored; tell the user.

Repeat until `tree-clean` prints `ok`.

Why the protocol is shaped this way, and how to stop trees going dirty at the source: `docs/rationale/worktree-hygiene-rationale.md` (not read at runtime).
