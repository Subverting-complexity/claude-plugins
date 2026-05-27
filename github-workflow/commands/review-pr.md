---
description: 'Review a PR against its linked issue. Trigger: "review PR N", "check the PR", "review this pull request", "look at PR N".'
---

# Review PR

Review a pull request against its linked GitHub issue.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo` from Identity
- Label map (for claude labels)

### 2. Identify the PR

If a PR number is provided, use it directly:

```
gh pr view {pr_number} --repo {org}/{repo} --json number,title,body,headRefName,baseRefName
```

Otherwise, detect from the current branch:

```
gh pr view --json number,title,body,headRefName,baseRefName
```

### 3. Extract linked issues

Parse the PR body for `Closes #N`, `Fixes #N`, or `Resolves #N` references.
Read each linked issue to extract acceptance criteria from the
**Requirements** section.

### 4. Review the diff

```
gh pr diff {pr_number}
```

Check against the acceptance criteria:

- Every criterion is addressed in the code
- No unrelated changes included
- Layer boundaries respected (domain does not import infrastructure)
- Tests exist for new logic
- No security vulnerabilities introduced

Optionally run `/github-workflow:code-review` for deeper analysis.

### 5. Submit review

If all criteria are met:

```
gh pr review {pr_number} --approve --body "{review_summary}"
```

If issues are found:

```
gh pr review {pr_number} --request-changes --body "{review_summary}"
```

### 6. Apply labels

Add the claude-reviewed label from the label map:

```
gh pr edit {pr_number} --add-label "{claude_reviewed_label}"
```

If approved and a `claude-approved` label is configured:

```
gh pr edit {pr_number} --add-label "{claude_approved_label}"
```
