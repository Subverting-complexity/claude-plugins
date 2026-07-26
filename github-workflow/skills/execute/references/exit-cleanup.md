# Execute — Exit cleanup (canonical procedure)

The single canonical specification of exit cleanup — every other mention
points here. Run it on **every** exit path (finish, block, unrecoverable
failure, timeout, rate-limit pause, one-session overflow), in this order,
as the **final** step **after** any commit/push (so the pushed branch,
not local state, is the source of truth). All three steps are idempotent.

## 1. Release the claim refs

```
git push origin :refs/claims/issue-{number}
rm -f .claude/claim-issue-{number}.sha
```

Ignore an already-gone-ref error (Phase 7 step 4 or `block-story` may
have released it).

If the run reached Phase 9, it also holds a review claim on its own PR.
Release that too, with the same idempotence:

```
git push origin :refs/claims/pr-{pr_number}
rm -f .claude/claim-pr-{pr_number}.sha
```

## 2. Delete the scratch files

```
rm -f .claude/plan.md .claude/preflight-passed.txt \
      .claude/label-cache.json .claude/issue-fields-cache.json \
      .claude/no-merge.flag .claude/bypass-ci.flag .claude/gate-failed.flag
```

The three `.flag` files carry an invocation flag or a Phase 5 outcome
across compaction, so they must not outlive the run that wrote them.

## 3. Reconcile the working tree to clean

Run **End clean** in `templates/worktree-hygiene.md` (the canonical
tree-reconcile procedure) until `git status --porcelain` ends empty.
**Never `git stash`** — the stash is shared across every worktree on the
clone.

(design rationale: `references/exit-cleanup-rationale.md` — not read at
runtime.)
