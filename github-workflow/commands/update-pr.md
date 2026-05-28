---
description: 'Address review feedback on a PR. Trigger: "update the PR", "fix the PR", "address review feedback", "changes were requested", "update PR N".'
---

# Update PR

Address review feedback on a pull request that has changes requested,
push fixes, and flag it for re-review.

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

If multiple PRs match, pick the one with the highest-priority state
(changes-requested first), then lowest PR number.

If no PRs need updating, report that and exit.

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

Run the quality gate command from `ClaudeProject.md`. Fix any failures.
Repeat up to 3 times if needed.

### 6. Commit and push

Stage and commit the fixes with a clear message referencing the review:

```
git add <changed-files>
git commit -m "Address review feedback on PR #{pr_number}"
git push
```

### 7. Assess change significance and update labels

Classify the changes you just pushed (see the criteria in the execute
skill's "Pushing changes to a reviewed PR" section):

**If substantial** (new logic, changed APIs, modified tests):

Remove the current state label and apply `needs-re-review`:

```
gh pr edit {pr_number} --remove-label "{current_state_label}" --add-label "{needs_re_review_label}"
```

**If trivial** (only formatting, typos, dead code removal):

Leave the current state label in place. The next code-review run will
detect the SHA change and fast-track it.

### 8. Report

Display:

- PR number and title
- Issues addressed (count and summary)
- Issues skipped (needing discussion)
- Label state after update
- Whether re-review was flagged
