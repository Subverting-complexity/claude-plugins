# Worktree hygiene

When the harness runs this skill as a parallel/background agent it gives each agent its own git worktree and **only auto-removes a worktree once it is clean** (see `docs/worktree-config.md`). Any uncommitted change — yours, a previous session's, or a formatter's — pins the worktree open: it is never reaped, its branch stays checked out, and stale worktrees pile up until cleanup fails on locks and long paths. There is **no cross-session resume**, so a worktree left dirty for "a later session to inspect" is never inspected — the work is simply stranded.

This protocol keeps the tree clean at both ends of a session. It has two halves: **Start clean** (run once, before any edits) and **End clean** (run on every exit). This is a **local** workflow — there is no issue tracker, no claim ref, and no PR. Reconcile with **local commits** only; do not push.

## Local caveat: the tree may be the user's own checkout

Unlike a freshly provisioned worktree, a local session can run directly in the user's working directory. So a dirty tree at **start** is not automatically "leaked junk" — it may be **the user's in-progress work**. Never discard pre-existing changes you did not make. Record them, leave them alone, and only reconcile what *this session* produced.

## The model

> Note what was already dirty at start → everything dirty at the end that is **not** in that set was produced by this session → commit it (feature
> + a `chore:` formatting commit) or discard it as disposable noise → the only thing left is the user's pre-existing work (ideally nothing) → the harness can reap the worktree.

## Never `git stash`

The stash is shared across **every worktree on the clone**. Stashing in one worktree can surface in or collide with another agent's worktree. Reconcile by **commit** or **discard**, never by stash. (Stashing would also bury the user's pre-existing changes — another reason not to.)

## Start clean

Run this **before any edits**, at the start of Build.

```
git status --porcelain
```

- **Empty** → the tree is pristine. Proceed; everything dirty at exit is yours.
- **Non-empty** → the tree already has changes. **Record the baseline** so you can tell your work apart from what was already here, and so it is recoverable from the transcript:
  ```
  git status --porcelain
  git --no-pager diff HEAD
  ```
  Then **tell the user** the tree was already dirty, list the pre-existing paths, and proceed **without touching them** — do not stage, revert, or `git clean` them. They may be the user's own work. Only files **you** create or modify from here on are yours to commit.

  (If you can confirm this is a freshly provisioned, leaked worktree — not the user's live checkout — you may reset it to a clean baseline with `git restore --staged --worktree -- .` and `git clean -fd` (never `-x`, so gitignored `.env`/`node_modules` survive) and report what was discarded. When in doubt, leave it alone.)

## End clean

Run this as the **final** exit-cleanup step, *after* the real work has been committed.

```
git status --porcelain
```

- **Empty** → done. The worktree is reapable.
- **Non-empty** → for each remaining entry, decide which bucket it is in (skip anything in the start-of-session baseline — that is the user's, leave it), then re-check until only the baseline (ideally nothing) remains:

  - **Work you forgot to commit** — an edited or new file that is part of the task. Commit it; do not discard real work.
  - **Incidental formatting / normalization on files outside the task** — e.g. a repo-wide `prettier`/`lint --fix` reflowed unrelated files, or line endings were normalized. These are committable hygiene but do not belong in the task's commit. Commit them as a **separate `chore:` commit** so the task's diff stays focused:
    ```
    git add <formatting-only-files>
    git commit -m "chore: formatting"
    ```
  - **Disposable generated noise** — regenerated build output or lockfile churn you do not intend to track and that is not gitignored. Discard it (`git restore` / `git clean -fd`). If it keeps reappearing, it should be gitignored — note that to the user.

  Then confirm:
  ```
  git status --porcelain    # empty, or only the recorded pre-existing baseline
  ```

## Why trees go dirty (and how to stop it at the source)

A session should never *end* dirty (beyond a pre-existing baseline you were careful not to touch). When unexpected dirt appears, the cause is almost always one of:

1. **A whole-repo formatter in the quality gate.** A gate that runs `prettier --write .` (or `lint --fix` across the tree) reformats files the change never touched, manufacturing dirt in unrelated files every run. Fix at the source: format **staged/changed files only** (lint-staged style), or make the gate **check-only** (`prettier --check`) so it fails loudly instead of silently rewriting.
2. **Line-ending churn.** `core.autocrlf` rewriting LF↔CRLF leaves files "modified" with no content change. Run `bootstrap.{sh,ps1}` once per clone (`docs/worktree-config.md`).
