# Execute — Phase 10 merge mechanics

Its **Release notes** section applies on every merge. Read the rest only when Phase 10 in `review-and-merge.md` found none of its stop conditions: `Auto-Merge on Approval` is `enabled`, `--no-merge` was not passed, the quality gate is green, no duplicate is flagged, and the verdict is Approved. `bulk-execute` reads it on the same condition.

A self-review (`test -f .claude/self-review.flag`) does not stop the merge. Check the flag here only to confirm Phase 8 step 3's disclosure is on the PR comment, and repeat it in your final report.

## Drive the PR to merged

Follow **steps 1 to 6** of `skills/pr-review/references/auto-merge.md`, the single specification of the merge mechanics, with these substitutions:

- The enabling conditions are already confirmed. `require-ci-before-merge` and the two config bypasses come from the same section of `review.config.md`, and nothing about the CI gate changes for this caller.
- `--bypass-ci` is set only if `.claude/bypass-ci.flag` exists. This run is autonomous: wherever that file would ask the user, take its autonomous branch.
- "The SHA you reviewed" is the head SHA you recorded in Phase 8 or Phase 9. "The review comment from Step 9" is the consolidated comment you posted.
- Where it fixes a failing check the way pr-review's Step 7 does, apply Phase 9's fix discipline instead. Its fallbacks that file a conflict or a failing check stand: each leaves the PR open and unmerged. A check that fails because of this PR's own diff is fixed on the branch, never filed.
- Its step 5 report format is the final report at the end of `review-and-merge.md`.
- Its step 6 passes `--notes .claude/release-notes.json`, written as **Release notes** below says.

## Release notes

Phase 7 wrote the notes and posted them on the PR, as `skills/release-notes/references/on-the-pr.md` says. When Phase 9 rework or the review changed what a user would notice, rewrite `.claude/release-notes.json` and post a new comment the same way before step 4: the newest comment wins. Before step 4, check the file exists and names every issue the PR closes; if the run lost it, write it again from the newest notes comment on the PR.

You are sitting on the branch being merged, and the merge deletes it. Stay on it through steps 1 to 3, where a conflict resolution or CI fix is committed. Immediately before step 4, detach, because another worktree usually holds the default branch:

```bash
git fetch origin {default-branch}
git checkout --detach origin/{default-branch}
```

If `git status --porcelain --untracked-files=no` is not empty, run **End clean** in `templates/worktree-hygiene.md` first. Ignore untracked files: this workflow's `.claude/` scratch files are untracked by design.

## When the attempt stops short

The mechanics can stop short: a head SHA that moved since the review, a conflict needing judgment, a red check that is not yours to fix, absent CI, repo-level auto-merge disabled, checks still pending when the watch window closes, or an auto-mode denial of the merge as `Merge Without Review`, which **Auto-mode denial** in `escape-hatches.md` covers. Each leaves the PR approved and unmerged with a comment saying why. That is a correct outcome.

In each of those cases also run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr {pr_number} --verdict needs-re-review`, because the review picker skips a plain `approved` PR and nothing would select it again. The exception is the successful enqueue (`autoMergeRequest` non-null at step 5): GitHub merges that PR on its own, and the next run's `wf settle-merged` sets its issues to Done with the notes you posted.

## Report

Report what step 6 settled, as it specifies, then return to the final report in `review-and-merge.md`.
