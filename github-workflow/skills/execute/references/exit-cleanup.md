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

If the run **won** a review claim on its own PR in Phase 9, release that
too. The test is the file Acquire writes only on a win:

```
test -f .claude/claim-pr-{pr_number}.sha || echo "NO PR CLAIM — skip this whole step"
```

When that file is absent, do **nothing** here. A run that never reached
Phase 9 has no claim, and on the claim-lost path another agent owns the
review — deleting a claim ref or stripping a label needs only push access,
not ownership, so acting would unlock a PR that agent is actively reviewing.

When it is present, reconcile the marker **before** deleting the ref, so no
window exists in which a rival claims the PR and then has its own marker
stripped. Acquiring the claim applied the human-visible `reviewing` marker,
Release frees only the lock, and the review picker skips a PR carrying that
marker — so an exit before a verdict was recorded would otherwise orphan the
PR. Read the PR once to decide:

```
gh pr view {pr_number} --repo {org}/{repo} --json state,labels
```

- Still `OPEN` **and** carrying `reviewing` → no verdict was recorded. Run
  `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr {pr_number} --verdict changes-requested`.
  That is the honest state for a review that did not finish, and it is a tier
  the picker selects, so the next `/github-workflow:code-review` run takes
  the PR from here.
- Merged, or already carrying a verdict label → Phase 9 or Phase 10 already
  reconciled it. Change nothing.
- Any other state on an open PR (no `reviewing`, no verdict — label drift) →
  treat it as "no verdict recorded" and run the same reconcile. An open PR
  carrying neither marker matches no picker tier, so leaving it would strand
  it.

Then release the lock:

```
git push origin :refs/claims/pr-{pr_number}
rm -f .claude/claim-pr-{pr_number}.sha
```

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
