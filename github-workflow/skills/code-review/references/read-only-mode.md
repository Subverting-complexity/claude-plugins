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
  PR by the prioritisation rules and go straight to checkout. Because no
  claim was held, **Step 10's claim release is a no-op** and there is no
  `reviewing` label to remove.
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
- In Step 10, apply labels normally.
- **Skip Step 11** (auto-merge) entirely — read-only mode never merges,
  closes, or pushes, regardless of the Auto-Merge on Approval setting.
