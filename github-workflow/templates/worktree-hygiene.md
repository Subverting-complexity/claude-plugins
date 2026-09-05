# Worktree hygiene

The harness gives each parallel/background agent its own git worktree and
**only auto-removes a worktree once it is clean** (see
`docs/worktree-config.md`). Any uncommitted change — yours, a previous
session's, or a formatter's — pins the worktree open: it is never reaped,
its branch stays checked out, and stale worktrees pile up until cleanup
fails on locks and long paths. There is **no cross-session resume**, so a
worktree left dirty for "a later session to inspect" is never inspected —
the work is simply stranded.

This protocol guarantees the worktree is clean at both ends of a session.
It has two halves: **Start clean** (run once, before any work) and **End
clean** (run on every exit). A caller references this file from its start
step and its exit-cleanup step.

## Never `git stash`

The stash is shared across **every worktree on the clone**. Stashing in
one worktree can surface in or collide with another agent's worktree.
Reconcile by **commit** or **discard**, never by stash.

## Start clean

Run this in the **Start** phase, *before* creating the story branch and
before any edits.

```
git status --porcelain
```

- **Empty** → the worktree was provisioned clean. Proceed.
- **Non-empty** → the worktree was provisioned dirty (a reused or leaked
  worktree from an earlier session, or a checkout-time formatter). This is
  **inherited junk**, not your work — the session has not done anything
  yet. Reconcile to a pristine baseline:

  1. **Record what was there**, so it is recoverable from the transcript
     if it ever mattered:
     ```
     git status --porcelain
     git --no-pager diff HEAD
     ```
  2. **Discard it.** Restore tracked files and remove untracked ones.
     `git clean` honours `.gitignore`, so secrets and generated dirs
     (`.env`, `node_modules`) listed there are **not** touched:
     ```
     git restore --staged --worktree -- .
     git clean -fd          # NOT -x — keep gitignored files (.env, node_modules)
     ```
  3. **Report** to the user that the worktree was provisioned dirty and
     was reset to a clean baseline, listing the files that were discarded.

  The branch is created from `origin/{default-branch}` regardless, so a
  clean baseline costs nothing and removes the dirt before it can be
  blamed on this session's PR.

## End clean

Run this as the **final** exit-cleanup step, *after* the real work has
been committed and pushed (so the pushed branch — not local state — is the
source of truth) and after the per-session scratch file is deleted.

```
git status --porcelain
```

- **Empty** → done. The worktree is reapable.
- **Non-empty** → every remaining entry was produced by this session
  (start was clean). Reconcile each, then re-check until empty:

  - **A story file you forgot to commit** — an edited or new file that is
    part of the work. Commit it into the feature branch; do not discard
    real work.
  - **Incidental formatting / normalization on files outside the story**
    — e.g. a repo-wide `prettier`/`lint --fix` reflowed unrelated files,
    or line endings were normalized. These are committable hygiene, but
    they do not belong in the feature diff. Commit them as a **separate
    `chore:` commit** so the feature PR stays focused, then push:
    ```
    git add <formatting-only-files>
    git commit -m "chore: formatting"
    git push
    ```
    If the session also opened a PR, this commit rides the same branch and
    is part of it; that is fine — it is clearly labelled and separable.
  - **Disposable generated noise** — regenerated build output or lockfile
    churn you do not intend to track and that is not gitignored. Discard
    it (`git restore` / `git clean -fd`). If it keeps reappearing, it
    should be gitignored — note that to the user.

  Then confirm:
  ```
  git status --porcelain    # must be empty
  ```

Why the protocol is shaped this way, and how to stop trees going dirty at
the source: `docs/rationale/worktree-hygiene-rationale.md` (not read at
runtime).
