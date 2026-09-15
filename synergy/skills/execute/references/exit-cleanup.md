# Execute — Exit cleanup (canonical procedure)

The single canonical specification of exit cleanup — every other mention points here. Run it on **every** exit path (finish, block, unrecoverable failure, timeout, rate-limit pause, one-session overflow), in this order, as the **final** step **after** any commit/push (so the pushed branch, not local state, is the source of truth). All three steps are idempotent.

## 1. Release the claim refs

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --issue {number}
rm -f .claude/claim-issue-{number}.sha
```

`claim-release` is idempotent, so releasing a ref Phase 7 step 4 or `block-story` already released is a no-op rather than an error.

If the run **won** a review claim on its own PR, in Phase 7's `handoff` or in Phase 8, release that too. The test is the file Acquire writes only on a win:

```
test -f .claude/claim-pr-{pr_number}.sha || echo "NO PR CLAIM — skip this whole step"
```

When that file is absent, do **nothing** here. A run that never reached the Phase 7 hand-off has no claim, and on the claim-lost path another agent owns the review: deleting its claim ref or label needs only push access, so acting would unlock a PR that agent is reviewing.

When it is present, reconcile the marker **before** deleting the ref, so a rival never claims the PR and then has its own marker stripped. Phase 8's claim applied the `reviewing` marker, Release frees only the lock, and the picker skips a PR carrying that marker, so an exit before a verdict would orphan the PR. Read the PR once to decide:

```
gh pr view {pr_number} --repo {org}/{repo} --json state,labels
```

- Still `OPEN` **and** carrying `reviewing` → no verdict was recorded. Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr {pr_number} --verdict changes-requested`. That is the honest state for an unfinished review, and a tier the picker selects.
- Merged, or already carrying a verdict label → Phase 8 or Phase 9 already reconciled it. Change nothing.
- Still `OPEN`, carrying `needs-review` and no `reviewing` → no review started. Change nothing: the picker selects that label.
- Any other open state (no `reviewing`, no verdict: label drift) → run the same reconcile, because an open PR carrying no marker matches no picker tier.

Then release the lock:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --pr {pr_number}
rm -f .claude/claim-pr-{pr_number}.sha
```

## 2. Delete the scratch files

```
rm -f .claude/plan.md .claude/preflight-passed.txt \
      .claude/label-cache.json .claude/issue-fields-cache.json \
      .claude/no-merge.flag .claude/bypass-ci.flag .claude/gate-failed.flag \
      .claude/self-review.flag
```

The `.flag` files carry an invocation flag or a phase outcome across compaction, so they must not outlive the run that wrote them.

## 3. Reconcile the working tree to clean

Run **End clean** in `templates/worktree-hygiene.md` (the canonical tree-reconcile procedure) until `git status --porcelain` ends empty. **Never `git stash`** — the stash is shared across every worktree on the clone.

(design rationale: `docs/rationale/exit-cleanup-rationale.md` — not read at runtime.)
