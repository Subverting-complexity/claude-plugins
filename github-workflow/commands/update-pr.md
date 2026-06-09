---
description: 'Address review feedback on a PR. Trigger: "update the PR", "fix the PR", "address review feedback", "changes were requested", "update PR N", "fix review issues", "apply feedback", "respond to review", "address comments".'
argument-hint: '[pr#]'
---

# Update PR

Address review feedback on a pull request that has changes requested,
push fixes, and flag it for re-review.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo`, `default-branch` from Identity
- Label map (for claude and review state labels)

Resolve every review-state and claude label by **purpose key** through
the single path in `templates/default-labels.md`: review-state purposes
(`needs-review`, `updating`, `approved`, `changes-requested`,
`needs-discussion`, `needs-re-review`, `failed`, …) via `review.config.md`
when present, defaults (`review-` prefix) otherwise; claude purposes via
the `ClaudeProject.md` label map. The bare names used throughout these steps are purpose keys —
resolve them, never apply them literally — so the `updating` claim this
command writes is the identical string the code-review skill filters on.
When falling back to defaults in an interactive session, warn the user:
"No `review.config.md` found — using default labels. Run
`/github-workflow:setup` to configure review labels for this project."

### 2. Find the PR to update

If a PR number is provided, use it directly. Otherwise, find PRs that
need attention:

```
gh pr list --state open --repo {org}/{repo} --assignee @me --json number,title,labels,headRefName
```

Look for PRs with any of these state labels (in priority order):

1. `changes-requested` — review found issues that need fixing
2. `needs-discussion` — questions were raised that may now be resolved
3. `needs-re-review` — changes were pushed but review hasn't run yet

**Skip** any PR that has:
- The `reviewing` label (a review agent is currently working on it)
- The `updating` label (another builder agent is already fixing it)
- The `approved` label (waiting for human merge, do not touch)
- The `needs-review` label (awaiting its first review — no feedback to
  address yet)
- The `failed` label (review could not complete — investigate the
  failure, but there is no review feedback to apply here)

If multiple PRs match, pick the one with the highest-priority state
(changes-requested first), then lowest PR number.

**Never ask the user which PR to update.** Always auto-select using the
priority rules above. If the user says "update PRs" (plural), that means
"find the next one and update it", not "update all of them" or "let me
choose".

If no PRs need updating, report that and exit.

### 2b. Claim the PR

Multiple agents may be running concurrently — possibly under the same
GitHub identity, where a shared `updating` label cannot exclude a rival
(and a reviewer holding `reviewing` must be excluded too). Acquire the PR
with the atomic claim procedure in `templates/claim-procedure.md`
(**Acquire**) using the target `pr-{pr_number}`. It pushes a unique object
to `refs/claims/pr-{pr_number}` — the same ref the code-review skill
claims, so a reviewer and an updater are mutually exclusive — and applies
the `updating` state label as the human-visible marker on success.

If Acquire reports the claim is lost, another agent (reviewer or updater)
owns this PR: exit without removing any labels and without making changes.
The `refs/claims/pr-{pr_number}` ref is the lock; the `updating` label is
a display signal other skills filter on. No label read-back is needed.

### 3. Check out the branch and read the review

```
gh pr checkout {pr_number}
```

Read the most recent review comment:

```
gh pr view {pr_number} --repo {org}/{repo} --json comments
```

Find the latest Claude review comment (identified by the review footer
marker). Extract:

- The **verdict** and summary
- The **Issues remaining** section — this is the work list
- The **Fixes applied** section — these are already done
- Any items under **Non-compliance**, **Correctness**, or **Tests**
  that were flagged as problems

If the review comment also mentions items under **Needs Discussion**,
note those but do not attempt to resolve design questions unilaterally.
Flag them for the user.

### 4. Address each issue

Work through every item in **Issues remaining**, one at a time:

1. Read the referenced file and surrounding context.
2. Understand the problem described in the review.
3. Fix it. Follow the same build principles from `CLAUDE.md`.
4. If the fix requires a test change, update the test too.

**Do not fix:**
- Items marked as needing discussion (architectural decisions)
- Stylistic preferences that weren't flagged as non-compliance
- Anything outside the scope of the review feedback

### 5. Run the quality gate

Run the quality gate command from `ClaudeProject.md`:

1. Execute the quality gate script/command.
2. If it fails, read the error output, fix the issue, and re-run.
3. Repeat up to 3 times (4 total runs maximum). If still failing,
   continue to commit and push — the review feedback fixes are still
   valuable even if the gate has a pre-existing issue.

### 6. Commit and push

Stage and commit the fixes with a clear message referencing the review:

```
git add <changed-files>
git commit -m "Address review feedback on PR #{pr_number} {pr_title}"
git push
```

### 7. Resolve merge conflicts

After pushing, check if the PR has merge conflicts with the base branch:

```
gh pr view {pr_number} --repo {org}/{repo} --json mergeable,mergeStateStatus
```

**Handle `UNKNOWN` before branching.** GitHub computes mergeability
asynchronously after a push lands; the first read can return `UNKNOWN`
for a short window. If `mergeable` is `UNKNOWN`, poll with a bounded
backoff before acting on the value:

```
# Retry at 3 s, 5 s, and 10 s (three attempts; ~18 s total)
for delay in 3 5 10; do
  sleep $delay
  result=$(gh pr view {pr_number} --repo {org}/{repo} \
    --json mergeable,mergeStateStatus)
  mergeable=$(echo "$result" | jq -r '.mergeable')
  [ "$mergeable" != "UNKNOWN" ] && break
done
```

If `mergeable` is still `UNKNOWN` after all retries, treat it as
`MERGEABLE` and say so: "Merge status remained UNKNOWN after polling;
assuming no conflict — a reviewer will catch any issues before merge."

If `mergeable` is `CONFLICTING`:

1. Fetch the latest base branch and rebase onto it:
   ```
   git fetch origin {default-branch}
   git rebase origin/{default-branch}
   ```
2. Resolve conflicts one commit at a time as the rebase progresses.
   Read each conflicted file, understand both sides, and pick the
   correct resolution. Then continue:
   ```
   git add <resolved-files>
   git rebase --continue
   ```
3. After the rebase completes, run the quality gate once (retry once
   if it fails, 2 total).
4. Force-push the rebased branch:
   ```
   git push --force-with-lease
   ```

Conflict resolution counts as a change when classifying significance
in the next step — complex conflicts (overlapping logic, altered
control flow, modified signatures) make the overall change
**substantial** regardless of how trivial the review fixes were.

### 8. Assess change significance and update labels

Release the atomic claim (your work is done) and remove the `updating`
label (`templates/claim-procedure.md` **Release** for target
`pr-{pr_number}`):

```
git push origin :refs/claims/pr-{pr_number}
rm -f .claude/claim-pr-{pr_number}.sha
gh pr edit {pr_number} --remove-label "{updating_label}"
```

The claim-ref delete is idempotent — ignore an error if it is already
gone.

Then classify the changes you pushed and determine the label outcome:

**If trivial AND all Issues Remaining were addressed:**

All review feedback has been resolved with minor fixes. Remove the
current state label and apply `approved` — no re-review needed:

```
gh pr edit {pr_number} --remove-label "{current_state_label}" --add-label "{approved_label}"
```

**If substantial** (new logic, changed APIs, modified tests):

Remove the current state label and apply `needs-re-review`:

```
gh pr edit {pr_number} --remove-label "{current_state_label}" --add-label "{needs_re_review_label}"
```

**If trivial BUT some Issues Remaining were NOT addressed:**

Leave the current state label in place (`changes-requested` stays).
The next code-review run will detect the SHA change and evaluate
whether the unaddressed items are still relevant.

### 8b. Verify labels were applied

After updating labels in Step 8, read back the PR labels:

```
gh pr view {pr_number} --repo {org}/{repo} --json labels --jq '[.labels[].name]'
```

Confirm the expected state label is present and the `updating` label
was removed. If the state label is missing, create it with the guarded
create-if-missing pattern from `templates/default-labels.md` —
**without `--force`** so existing label metadata is never overwritten —
then retry:

```
gh label create "{label}" --repo {org}/{repo} --description "{desc}" --color "{color}"
gh pr edit {pr_number} --add-label "{label}"
```

Use label colors from `templates/default-labels.md`.

### 9. Error handling

If anything goes wrong (checkout fails, quality gate can't pass, push
fails), release the atomic claim and remove the `updating` label before
exiting so another agent can pick up the PR
(`templates/claim-procedure.md` **Release** for target `pr-{pr_number}`):

```
git push origin :refs/claims/pr-{pr_number}
rm -f .claude/claim-pr-{pr_number}.sha
gh pr edit {pr_number} --remove-label "{updating_label}"
```

### 9b. Reconcile the working tree to clean

The fixes are pushed, so leave the worktree clean for the harness to reap
(`docs/worktree-config.md` — a dirty tree is never auto-removed). Delete
the per-session scratch file and run the **End clean** procedure in
`templates/worktree-hygiene.md`:

```
rm -f .claude/plan.md
git status --porcelain    # reconcile until empty
```

Commit incidental formatting on unrelated files as a **separate `chore:`
commit** and push it (it rides the PR branch); discard disposable
generated noise. **Never `git stash`** — the stash is shared across every
worktree on the clone. This applies on the error-handling exit (Step 9)
too: end with `git status --porcelain` empty.

### 10. Report

Display:

- PR number and title
- Issues addressed (count and summary)
- Issues skipped (needing discussion)
- Label state after update
- Whether re-review was flagged
