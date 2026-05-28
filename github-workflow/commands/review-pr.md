---
description: 'Review a PR against its linked issue. Trigger: "review PR N", "check the PR", "review this pull request", "look at PR N", "check my PR", "is the PR ready", "validate the PR".'
---

# Review PR

Lightweight review of a pull request against its linked GitHub issue.
This checks acceptance criteria and basic quality. For a deep structural
review with fix application and state-label management, use
`/github-workflow:code-review` instead.

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

Post a review comment with the findings:

```
gh pr comment {pr_number} --body "{review_summary}"
```

The review summary should include:
- Acceptance criteria checklist (each criterion as checked/unchecked)
- Layer boundary assessment
- Test coverage assessment
- Verdict: Approved or Changes Requested with specific items

### 6. Apply labels

If approved and a `claude-approved` label is configured in the label
map, apply it:

```
gh pr edit {pr_number} --add-label "{claude_approved_label}"
```

If changes are requested, do not apply the approved label. The user
or a builder agent should address the feedback and re-run the review.
