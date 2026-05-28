---
description: 'Create a bug, architecture, or tech debt issue. Trigger: "report a bug", "log an issue", "found a bug", "report tech debt", "create an issue", "file a bug", "something''s broken", "found a problem", "raise an issue".'
---

# Report Issue

Create a bug, architecture, or tech debt issue discovered during development.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo` from Identity
- Label map (for type and priority labels)
- Issue prefixes

### 2. Classify the issue

Determine the type:

- **Bug** — Something is broken or behaves incorrectly
- **Architecture** — Layer violation, coupling, design problem
- **Tech Debt** — Working but needs improvement

### 3. Assess severity

- **Blocks current story** → Create and fix first on its own branch
- **Same scope and trivial** → Fix inline in current PR
- **Everything else** → Create issue for later

### 4. Detect current milestone

If in sprint mode, find the current milestone so the new issue lands
in the right sprint:

```
gh api repos/{org}/{repo}/milestones --jq 'sort_by(.due_on) | .[] | select(.open_issues > 0) | .title' | head -1
```

### 5. Create the issue

```
gh issue create --repo {org}/{repo} \
  --title "{prefix} {title}" \
  --body "{description}" \
  --label "{type_label},{priority_label}" \
  --milestone "{current_milestone}"
```

Where `{prefix}` is `[BUG]`, `[ARCH]`, or `[DEBT]` from the Issue Prefixes
table in `ClaudeProject.md`.

Include in the body:

- What was found
- Where in the codebase (file paths, line numbers)
- Impact assessment
- Suggested fix (if known)
- Whether it blocks the current story

### 6. Report

Display the created issue number and URL, and whether it blocks
the current story or is deferred.
