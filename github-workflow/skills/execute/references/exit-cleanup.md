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

Release frees the lock only. Acquiring a PR claim also applied the
human-visible `reviewing` marker, and the review picker skips a PR carrying
it — so if this run is exiting **before** Phase 9 recorded a verdict, the
marker would orphan the PR from every picker. Reconcile it now:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr {pr_number} --verdict changes-requested
```

`changes-requested` is the honest state for a review that did not finish, and
it is a tier the picker selects, so the next `/github-workflow:code-review`
run takes the PR from here. Skip this when a verdict was already recorded —
`review-finish` has then already replaced the marker.

## 2. Delete the scratch files

```
rm -f .claude/plan.md .claude/preflight-passed.txt \
      .claude/label-cache.json .claude/issue-fields-cache.json \
      .claude/no-merge.flag .claude/bypass-ci.flag .claude/gate-failed.flag \
      .claude/self-review.flag
```

The `.flag` files carry an invocation flag or a phase outcome across
compaction, so they must not outlive the run that wrote them.

## 3. Reconcile the working tree to clean

Run **End clean** in `templates/worktree-hygiene.md` (the canonical
tree-reconcile procedure) until `git status --porcelain` ends empty.
**Never `git stash`** — the stash is shared across every worktree on the
clone.

(design rationale: `references/exit-cleanup-rationale.md` — not read at
runtime.)
