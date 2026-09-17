# Execute — Exit cleanup (canonical procedure)

The single canonical specification of exit cleanup — every other mention points here. Run it on **every** exit path (finish, block, unrecoverable failure, timeout, rate-limit pause, one-session overflow), as the **final** step **after** any commit and push, so the pushed branch, not local state, is the source of truth. It is idempotent.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" exit-cleanup --issue {number} --pr {pr_number}
```

Leave out `--pr` when no PR was opened. It releases the issue claim, and the PR's review claim only when this checkout won it: then it first records a review that never reached a verdict as changes-requested, so the picker can find the PR again. A claim another agent holds is never touched. It deletes the run's scratch files under `.claude/` and keeps the caches, and needs no network for that part.

Read the result by `status`:

- **`ok`** (exit 0), one line — done. The worktree is clean and can be reaped.
- **`dirty`** (exit 24) — `remaining` lists what is still uncommitted. Everything else is done. Decide each path, because only you know which is work:
  - **A story file you forgot to commit** — commit it to the feature branch and push. Never discard real work.
  - **Formatting on files outside the story** (a repo-wide formatter, line endings) — commit it separately as `chore: formatting` and push, so the feature diff stays focused.
  - **Generated noise** you do not track — discard it. If it keeps reappearing it should be gitignored; tell the user.

  Then discard what is left and re-check in one call, repeating until it prints `ok`:

  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" tree-clean --discard {path} --discard {path}
  ```

  `--all` discards every remaining path. It restores tracked files and removes untracked ones, never touches gitignored files, and never stashes: the stash is shared by every worktree on the clone.
- **`partial`** (exit 24) — `reason` names what did not happen, such as a claim that could not be released. Report it and carry on; a held claim is freed by `claim-reap`.

(design rationale: `docs/rationale/exit-cleanup-rationale.md` — not read at runtime.)
