# Read-Only Mode

Read this when (and only when) the skill is invoked with `--read-only`
(`$ARGUMENTS.mode` is `read-only`) — the SKILL body carries just a pointer
so a full-mode review never loads it. Read-only mode is intended for the
Reviewer agent, which has no write access: it produces the same structured
evaluation without modifying the PR branch.

When `$ARGUMENTS.mode` is `read-only`:

- Execute Steps 1–6, but **do not claim**. Selection uses the fast path with
  `--no-claim` (Step 1) — read-only has no push access, so it never writes a
  `refs/claims/pr-<number>` ref or applies the `reviewing` marker. In the
  inline fallback (Step 1), skip **Step 2** (Claim) entirely: just pick the
  PR by the prioritisation rules and go straight to checkout. A **pinned PR**
  (an explicit number, Step 1) is the third selection route and behaves the
  same way: no claim, straight to checkout. Because no claim was held, **Step
  10's claim release is a no-op** and there is no `reviewing` label to remove.
- **Check out detached** — `gh pr checkout <number> --detach`. The branch may
  already be checked out in another worktree on this clone (the session that
  built it, or a sibling reviewer), and git refuses to check out a branch
  twice. Read-only needs the commit, not the branch.
- In **Step 2b** (duplicate reconciliation), close nothing: identify the
  winner and list the duplicate set under a "Duplicate PRs" note in the
  review comment, recommending which to keep. Then continue reviewing the
  selected PR.
- **Skip Step 7** (Fix issues) entirely — do not edit any files or push
  commits, and do not file anything to the board (Step 7f is a mutation).
- In Step 8, determine the verdict based on raw findings (nothing was auto-fixed).
- In Step 9, post the review comment with "Fixes applied: None (read-only
  mode)." The "Issues remaining" section lists the raw findings (nothing
  was filed to the board), so drop the "(filed to board)" qualifier.
  **Unless the caller owns the verdict** (see the Step 10 bullet below):
  then post nothing and return the findings and verdict to it instead. Decide
  this here, at Step 9, not after the comment is already posted.
- In Step 10, apply labels normally — **unless the caller says it owns the
  verdict**. A caller that runs several read-only reviews of the same PR at
  once (execute's Phase 9 spawns two) must reconcile the label itself from the
  combined verdict, because `wf review-finish` leaves exactly one verdict label
  and concurrent reviewers would otherwise overwrite each other last-writer-
  wins. When the caller has said so, skip the relabel and the Step 9 comment,
  and return the findings and verdict to it instead.
- **Skip Step 10b** (rework cascade) entirely. A Changes Requested verdict
  exits at Step 10 in read-only mode; the cascade checks out the branch, fixes,
  and pushes, which read-only must never do.
- **Skip Step 11** (auto-merge) entirely — read-only mode never merges,
  closes, or pushes, regardless of the Auto-Merge on Approval setting.
