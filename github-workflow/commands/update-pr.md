---
description: 'Address review feedback on a PR. Trigger: "update the PR", "fix the PR", "address review feedback", "changes were requested", "update PR N", "fix review issues", "apply feedback", "respond to review", "address comments".'
---

# Update PR

Address review feedback on a pull request that has changes requested,
push fixes, and flag it for re-review.

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

If `docs/review.config.md` or `review.config.md` exists, read the
state label definitions from there.

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

If multiple PRs match, pick the one with the highest-priority state
(changes-requested first), then lowest PR number.

**Never ask the user which PR to update.** Always auto-select using the
priority rules above. If the user says "update PRs" (plural), that means
"find the next one and update it", not "update all of them" or "let me
choose".

If no PRs need updating, report that and exit.

### 2b. Claim the PR

Multiple builder agents may be running concurrently. Apply the
`updating` label to claim the PR before starting work:

```
gh pr edit {pr_number} --add-label "{updating_label}"
```

Wait 2 seconds, then re-read the PR labels:

```
gh pr view {pr_number} --repo {org}/{repo} --json labels
```

If `updating` is present, you own the claim — proceed. If it was
removed or another agent's label appeared, exit without removing labels.

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
git commit -m "Address review feedback on PR #{pr_number}"
git push
```

### 7. Resolve merge conflicts

After pushing, check if the PR has merge conflicts with the base
branch:

```
gh pr view {pr_number} --repo {org}/{repo} --json mergeable,mergeStateStatus
```

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

Remove the `updating` label (your claim is done):

```
gh pr edit {pr_number} --remove-label "{updating_label}"
```

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

### 9. Error handling

If anything goes wrong (checkout fails, quality gate can't pass, push
fails), remove the `updating` label before exiting so another agent
can pick up the PR.

### 10. Report

Display:

- PR number and title
- Issues addressed (count and summary)
- Issues skipped (needing discussion)
- Label state after update
- Whether re-review was flagged
