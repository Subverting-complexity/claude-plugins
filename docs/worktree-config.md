# Recommended harness worktree configuration

These plugins are designed to run autonomously, and many workflows spawn
**parallel or background agents** (for example, running several stories at
once, or a background reviewer alongside a builder). The Claude Code harness
gives each parallel/background agent its **own git worktree** so the agents
cannot clobber one another's working tree.

That isolation is correct and you should keep it — but worktrees have sharp
edges, especially on Windows. This guide documents a recommended harness
configuration plus the manual recovery routine for when cleanup fails.

> **Who this is for:** anyone running these plugins with parallel/background
> agents. If you only ever run a single foreground agent, the defaults are
> fine and you can skip this.

---

## Why worktrees need configuration

The harness creates one worktree per parallel/background agent. Two problems
follow from that, both worse on Windows:

1. **`node_modules` duplication.** Each worktree gets its own checkout. In a
   JS/TS repo that means a full `node_modules` copy per worktree — gigabytes
   of duplicated files, slow setup, and (on Windows) file-lock cleanup
   failures when the harness tries to remove a worktree whose files are still
   held open. See
   [anthropics/claude-code#41740](https://github.com/anthropics/claude-code/issues/41740).
2. **Long-path overflow.** Worktrees live under a nested path
   (`.claude/worktrees/<name>/...`). Combined with deep `node_modules` trees,
   this routinely exceeds the Windows `MAX_PATH` (260-char) limit and breaks
   checkout or cleanup.

The settings below avoid the duplication, keep secrets available inside
worktrees, and make cleanup more reliable.

---

## Recommended settings

Add these to your Claude Code settings (`.claude/settings.json` for the
project, or your user settings):

```jsonc
{
  "worktree": {
    // Keep background/parallel agents isolated in their own worktree.
    // NEVER set this to "none" — that lets parallel agents share one
    // working tree and corrupt each other's checkout.
    "bgIsolation": "worktree",

    // Symlink heavy generated directories instead of copying them into
    // every worktree. This is the single biggest win on Windows: one
    // shared node_modules instead of one copy per agent.
    "symlinkDirectories": ["node_modules"]
  },

  // Reap stale worktrees sooner so locks and long paths don't pile up.
  "cleanupPeriodDays": 1
}
```

### Make secrets available inside worktrees

A fresh worktree does **not** automatically carry untracked files such as
`.env`. Add a `.worktreeinclude` file at the repo root listing the untracked
paths each worktree needs:

```
.env
.env.local
```

Without this, agents running in a worktree fail at runtime because their
secrets/config are missing.

### Optional: a `WorktreeRemove` hook (Windows)

On Windows, removal frequently fails because a process still holds a file
open or a previous run left an `index.lock` / a half-finished rebase behind.
A `WorktreeRemove` hook can clear those obstacles before the harness removes
the worktree. The hook should, for the worktree being removed:

- kill any process still holding files open under the worktree path,
- delete a stale `.git/worktrees/<name>/index.lock`, and
- abort any in-progress rebase (`git rebase --abort`) so removal is clean.

Treat this as a best-effort safety net, not a substitute for
`symlinkDirectories` and a short `cleanupPeriodDays`.

---

## Line endings: stop phantom CLAUDE.md diffs from blocking cleanup

A worktree is only auto-removed when it is **clean**. On Windows the most
common reason a worktree stays "dirty" — and so never gets reaped, leaving
its branch checked out — is a **line-ending mismatch**, not a real edit.

The repo's `.gitattributes` pins every text file to LF (`* text=auto
eol=lf`), because the `sync-skills` scripts write LF-only. But Git for
Windows installs with `core.autocrlf=true` at the **system** level, which
fights that attribute: a file can end up with CRLF in the working tree
while the committed blob is LF. `CLAUDE.md` is the usual victim (it is
loaded and rewritten often), and it then shows as perpetually "modified"
even though no content changed. Confirm with:

```bash
# A healthy text file reads "w/lf"; a churned one reads "w/crlf".
git ls-files --eol CLAUDE.md
```

**Fix it once per clone** by running the bootstrap script — it sets the
config, renormalizes, and installs the pre-commit hook (which also blocks
CRLF from being committed in future):

```bash
./bootstrap.sh      # macOS / Linux / Git Bash
./bootstrap.ps1     # Windows PowerShell
```

Or do it by hand (writes to the shared `.git/config`, so it covers the
main checkout and every worktree on the machine):

```bash
git config --local core.autocrlf false   # stop Git injecting CRLF
git config --local core.eol lf            # honor the .gitattributes intent
git add --renormalize .                   # normalize any stale CRLF blobs
# Rewrite a working copy that is still CRLF on disk:
rm CLAUDE.md && git checkout -- CLAUDE.md
git ls-files --eol CLAUDE.md              # verify it now reads "w/lf"
```

Do this in a fresh clone before running parallel agents. Without it, the
harness keeps reporting cleanup failures for worktrees that look modified
but only differ by line endings.

## Keeping worktrees clean (the session's responsibility)

Line-ending churn is the *phantom* reason a worktree stays dirty; the more
common *real* reason is simply that a session left uncommitted changes
behind. **A worktree is only auto-removed when it is clean** — so any
loose change pins it open: it is never reaped, its branch stays checked
out, and stale worktrees accumulate until cleanup fails on locks and long
paths. There is no cross-session resume, so leaving work "for a later
session" strands it rather than preserving it.

The github-workflow plugin enforces a two-ended discipline, defined once in
[`github-workflow/templates/worktree-hygiene.md`](../github-workflow/templates/worktree-hygiene.md)
and referenced from every entry/exit path (`execute` Phases 2 and Exit
cleanup, `finish-story`, `update-pr`, `block-story`):

- **Start clean.** Before branching, assert `git status --porcelain` is
  empty. If a worktree was provisioned dirty (reused/leaked, or a
  checkout-time formatter), that inherited junk is recorded, discarded to
  a pristine baseline, and reported — so it is never blamed on the new
  session or left to block cleanup.
- **End clean.** On every exit, after committing and pushing the real
  work, reconcile the tree to empty: commit a forgotten file, commit
  incidental formatting on unrelated files as a **separate `chore:`
  commit** (kept out of the feature diff), or discard disposable generated
  noise. **Never `git stash`** — the stash is shared across every worktree
  on the clone, so it leaks between agents.

The model is: *start clean → everything dirty at the end is therefore this
session's → commit it or discard it → end clean → the harness reaps the
worktree.* The biggest upstream cause of unexpected dirt is a quality gate
that runs a **whole-repo formatter** (`prettier --write .`); scope it to
staged/changed files or make it check-only so it never silently rewrites
unrelated files.

## Windows limitations to be aware of

- **File-lock cleanup failures.** Windows does not allow deleting files that
  another process holds open. A worktree whose `node_modules` (or a running
  dev server, watcher, or editor indexer) is still active cannot be removed,
  and the harness will report a cleanup failure. `symlinkDirectories` removes
  the largest source of this; the manual reap routine below handles the rest.
- **Long-path overflow.** Even with symlinks, deeply nested generated paths
  can exceed `MAX_PATH`. Enabling long paths
  (`git config --global core.longpaths true`, plus the Windows
  `LongPathsEnabled` registry/Group-Policy setting) reduces these failures.
- **Tracked by upstream.** The duplication/cleanup interaction is
  [anthropics/claude-code#41740](https://github.com/anthropics/claude-code/issues/41740);
  watch it for fixes that may make some of this configuration unnecessary.

---

## Manual reap routine

When the harness leaves stale worktrees behind (cleanup failed, a session was
killed, or you see "worktree is locked" errors), reap them by hand:

```bash
# 1. See what worktrees exist and which are stale.
git worktree list

# 2. (Windows) Kill processes still holding files in the stale worktree.
#    Find the offender first — e.g. with Sysinternals handle.exe or
#    Resource Monitor — then stop it. Common culprits: node, editors,
#    file indexers, antivirus scans.

# 3. Remove the stale worktree. --force is needed if it still looks "dirty".
git worktree remove --force .claude/worktrees/<name>

# 4. Prune any administrative entries left behind for worktrees whose
#    directories are already gone.
git worktree prune
```

If `git worktree remove` still fails after killing lock-holders, delete the
directory manually and then run `git worktree prune` to clear the dangling
metadata.

---

## Reaping stale claim refs

The github-workflow plugin locks each in-flight issue/PR with a ref under
`refs/claims/` (see `github-workflow/templates/claim-procedure.md`). The
lock is only a race-protector for the brief select-to-claim window;
**durable ownership is the assignment + the issue's lifecycle label**, not
the ref.

**Automated reaper.** Run `/github-workflow:setup reap` to scan all
active claim refs, cross-check each one against the corresponding issue
or PR's current state, and free any that no longer back live work. It
applies a staleness threshold (default 4 hours) before touching any ref,
so a normally running session is never interrupted. Use this whenever a
story is stuck and no agent will pick it, or run it as a scheduled
routine via `/schedule`.

**Manual recovery.** If you need to free a specific claim by hand —
or if the reaper flags one as "suspect" and you have confirmed no
session holds it — use:

```bash
# List all claim refs on the remote.
git ls-remote origin 'refs/claims/*'

# Inspect one to see when and by which session it was created.
git fetch origin refs/claims/issue-42 && git log -1 FETCH_HEAD

# Delete a specific orphaned claim ref.
git push origin :refs/claims/issue-42
```

Deleting a claim ref never touches the issue's assignment or labels — those
remain the source of truth for who owns the work. If you also want to hand
the item back to the pool, clear the human-visible markers too: remove the
assignee and move the lifecycle label back to `status-ready` (or
`status-blocked` if it is genuinely blocked).

---

## Quick reference

| Setting | Recommended value | Why |
| --- | --- | --- |
| `worktree.bgIsolation` | `"worktree"` (never `"none"`) | Isolate parallel agents |
| `worktree.symlinkDirectories` | `["node_modules"]` | Avoid per-worktree duplication |
| `.worktreeinclude` | list `.env` / secrets | Make untracked config available |
| `cleanupPeriodDays` | `1` (lower) | Reap stale worktrees sooner |
| `WorktreeRemove` hook | optional (Windows) | Clear locks / `index.lock` / rebases |
| `core.autocrlf` / `core.eol` | `false` / `lf` (repo-local) | Stop CRLF churn that leaves worktrees "dirty" |
