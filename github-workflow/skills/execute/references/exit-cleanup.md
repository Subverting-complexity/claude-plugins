# Execute — Exit cleanup (canonical procedure)

This is the **single canonical specification** of exit cleanup; every
other mention of it points here. Run it on **every** exit path —
successful finish, block, unrecoverable failure, timeout, rate-limit
pause, one-session overflow. All three steps are idempotent — run them
in this order, as the **final** step before the session ends and
**after** any commit/push (so the pushed branch, not local state, is the
source of truth).

## 1. Release the claim ref

```
git push origin :refs/claims/issue-{number}
rm -f .claude/claim-issue-{number}.sha
```

Idempotent — ignore an error if the ref is already gone (Phase 7 step 4
or `block-story` may have released it already).

## 2. Delete the scratch files

```
rm -f .claude/plan.md .claude/preflight-passed.txt \
      .claude/label-cache.json .claude/issue-fields-cache.json
```

## 3. Reconcile the working tree to clean

Run the **End clean** procedure in `templates/worktree-hygiene.md` —
that file is the canonical tree-reconcile procedure — until
`git status --porcelain` ends empty. **Never `git stash`** — the stash
is shared across every worktree on the clone.

(design rationale: `references/exit-cleanup-rationale.md` — not read at
runtime.)
