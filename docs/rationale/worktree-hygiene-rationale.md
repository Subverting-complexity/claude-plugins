# Worktree hygiene — design rationale

Background for the protocol in `github-workflow/templates/worktree-hygiene.md`.
**Not read at runtime** — it exists so a later change does not silently undo
a decision that was made for a reason.

## The model

> Start clean → so everything dirty at the end was produced by **this**
> session → commit it (feature + a `chore:` formatting commit) → end clean
> → the harness reaps the worktree.

Because the worktree starts clean, there is no "foreign work I didn't
author" case at exit to agonize over: inherited dirt is dealt with once,
at the start. Everything still dirty at exit is yours, so it is either
committed or discarded as disposable noise — never left loose.

## Why trees go dirty (and how to stop it at the source)

A worktree should never *start* dirty and a session should never *end*
dirty. When it happens, the cause is almost always one of:

1. **A whole-repo formatter in the quality gate.** A gate that runs
   `prettier --write .` (or `lint --fix` across the tree) reformats files
   the change never touched, manufacturing foreign-looking dirt in
   unrelated packages every run. Fix at the source: format **staged/changed
   files only** (lint-staged style), or make the gate **check-only**
   (`prettier --check`) so it fails loudly instead of silently rewriting.
2. **A reused worktree.** A prior dirty session was never reaped, so the
   next session inherited its mess. Keep `cleanupPeriodDays` low and use a
   `WorktreeRemove` hook (`docs/worktree-config.md`) so dirty worktrees do
   not linger to be reused.
3. **Line-ending churn.** `core.autocrlf` rewriting LF↔CRLF leaves files
   "modified" with no content change. Run `bootstrap.{sh,ps1}` once per
   clone (`docs/worktree-config.md`).
