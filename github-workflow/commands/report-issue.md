---
description: 'Create a bug, architecture, or tech debt issue. Trigger: "report a bug", "log an issue", "found a bug", "report tech debt", "create an issue", "file a bug", "something''s broken", "found a problem", "raise an issue".'
---

# Report Issue

Create a bug, architecture, or tech debt issue discovered during development.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

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

### 3. Assess severity and select labels

First decide what happens to the issue:

- **Blocks current story** → Create and fix first on its own branch
- **Same scope and trivial** → Fix inline in current PR
- **Everything else** → Create issue for later

Then map the severity to a **priority label** from the label map in
`ClaudeProject.md`:

- **Critical** — security hole, data loss, or a crash on a core path →
  `priority-critical` label
- **High** — broken feature, blocks other work, or a clear regression →
  `priority-high` label
- **Medium** — incorrect behaviour with a workaround, or notable debt →
  `priority-medium` label
- **Low** — cosmetic, minor cleanup, or nice-to-have → `priority-low`
  label

Also select the **type label** (`type-bug`, `type-arch`, or `type-debt`)
from the label map based on the classification in Step 2.

Build the label list from whichever of these the project actually
defines in its label map. Skip any purpose that has no label configured
— never pass a placeholder or an empty label name to `gh`.

### 4. Detect current milestone

If in sprint mode, find the current milestone so the new issue lands
in the right sprint:

```
gh api repos/{org}/{repo}/milestones --jq 'sort_by(.due_on) | .[] | select(.open_issues > 0) | .title' | head -1
```

If this returns nothing (flat backlog mode, or no open milestones), the
issue is created without a milestone — do **not** pass an empty
`--milestone` flag, as `gh` rejects it.

### 5. Create the issue

Assemble the label list from the type and priority labels selected in
Step 3, comma-separated, omitting any that are not configured.

```
# Sprint mode (a current milestone was found):
gh issue create --repo {org}/{repo} \
  --title "{prefix} {title}" \
  --body "{description}" \
  --label "{type_label},{priority_label}" \
  --milestone "{current_milestone}"

# Flat mode (no milestone) — omit the --milestone flag entirely:
gh issue create --repo {org}/{repo} \
  --title "{prefix} {title}" \
  --body "{description}" \
  --label "{type_label},{priority_label}"
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
