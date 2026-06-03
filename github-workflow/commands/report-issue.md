---
description: 'Create a bug, security, architecture, or tech debt issue. Trigger: "report a bug", "log an issue", "found a bug", "report tech debt", "create an issue", "file a bug", "something''s broken", "found a problem", "raise an issue", "security issue", "vulnerability".'
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

If `ClaudeProject.md` is missing or has no label map, use the default
label names from `templates/default-labels.md`. When using defaults in
an interactive session, warn the user: "Label map not configured —
using default labels. Run `/github-workflow:setup` to configure labels
for this project."

### 2. Classify the issue

Determine the type:

- **Bug** — Something is broken or behaves incorrectly
- **Security** — Vulnerability, insecure pattern, or missing protection
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

Also select the **type label** (`type-bug`, `type-security`, `type-arch`, or `type-debt`)
from the label map based on the classification in Step 2.

Also include:

- **Lifecycle state** — exactly one, so the new issue is never
  unlabelled: `status-ready` when the report is actionable as written
  (it includes where and a suggested fix — the usual case), or
  `needs-refinement` when the report is too vague to implement without a
  refinement session.
- **Provenance** — `claude-authored`, since this issue is Claude-created.

Build the label list from whichever of these the project actually
defines in its label map. Skip any purpose that has no label configured
— never pass a placeholder or an empty label name to `gh`. Resolve every
name by purpose key through `templates/default-labels.md`.

### 4. Detect current milestone

If in sprint mode, find the current milestone so the new issue lands
in the right sprint:

```
gh api repos/{org}/{repo}/milestones --jq 'sort_by(.due_on) | .[] | select(.open_issues > 0) | .title' | head -1
```

If this returns nothing (flat backlog mode, or no open milestones), the
issue is created without a milestone — do **not** pass an empty
`--milestone` flag, as `gh` rejects it.

### 4b. Validate and create labels

Before creating the issue, ensure all selected labels exist on the
repository. Fetch the current label list:

```
gh label list --repo {org}/{repo} --json name --jq '.[].name'
```

For each label in the assembled list (type, priority, lifecycle state,
and `claude-authored`), resolve its name by purpose key via
`templates/default-labels.md` and check if it appears in the output. If a
label is missing (setup should
have created it), create it with the guarded create-if-missing pattern
from `templates/default-labels.md` — **without `--force`** so existing
label metadata is never overwritten:

```
gh label create "{label_name}" --repo {org}/{repo} --description "{description}" --color "{color}"
```

Use these colours (matching the setup wizard defaults):
- Priority: critical `#B60205`, high `#D93F0B`, medium `#FBCA04`, low `#0E8A16`
- Type: story `#1D76DB`, bug `#D93F0B`, security `#B60205`, debt `#FBCA04`, arch `#0E8A16`

This step is best-effort. If label creation fails (permissions, etc.),
log a warning and proceed — `gh issue create` will still apply labels
that already exist.

### 5. Create the issue

Assemble the label list from the type, priority, lifecycle-state, and
`claude-authored` labels selected in Step 3, comma-separated, omitting
any that are not configured.

Write the issue body to a temporary file first, then create using
`--body-file` to avoid Windows/PowerShell shell-escaping issues:

```
# Sprint mode (a current milestone was found):
gh issue create --repo {org}/{repo} \
  --title "{prefix} {title}" \
  --body-file {tempfile} \
  --label "{type_label},{priority_label}" \
  --milestone "{current_milestone}"

# Flat mode (no milestone) — omit the --milestone flag entirely:
gh issue create --repo {org}/{repo} \
  --title "{prefix} {title}" \
  --body-file {tempfile} \
  --label "{type_label},{priority_label}"
```

Delete the temp file after creation.

**Leave the assignee blank.** Do not pass `--assignee`/`--add-assignee`
here, and do not follow up with a `gh issue edit --add-assignee`.
Creating an issue is never an act of claiming it: new issues must enter
the unassigned pool so `pick-story` / `execute` (which query
`--assignee ""`) can select them. Assignment happens only at claim time
(`start-story` / `execute` Acquire), never at creation.

Where `{prefix}` is `[BUG]`, `[SECURITY]`, `[ARCH]`, or `[DEBT]` from the Issue Prefixes
table in `ClaudeProject.md`.

Include in the body:

- What was found
- Where in the codebase (file paths, line numbers)
- Impact assessment
- Suggested fix (if known)
- Whether it blocks the current story

### 5b. Verify labels were applied

After creating the issue, verify the labels were actually applied:

```
gh issue view {number} --repo {org}/{repo} --json labels --jq '[.labels[].name]'
```

For each expected label (type, priority, lifecycle state, and
`claude-authored`), if missing, create it with the guarded
create-if-missing pattern from `templates/default-labels.md`
— **without `--force`** — and reapply:

```
gh label create "{label}" --repo {org}/{repo} --description "{desc}" --color "{color}"
gh issue edit {number} --repo {org}/{repo} --add-label "{label}"
```

Use label colors from `templates/default-labels.md`. If the label map
in `ClaudeProject.md` is missing or incomplete, use the default names
from `templates/default-labels.md`.

### 6. Validate issue body

After creating the issue, immediately read it back and verify the body
was written correctly:

```
gh issue view {number} --repo {org}/{repo} --json body --jq '.body'
```

If the body is empty, only whitespace, or consists of just `@` (a
known Windows/PowerShell shell-escaping issue):

1. Write the intended body to a temporary file.
2. Update the issue using `--body-file`:
   ```
   gh issue edit {number} --repo {org}/{repo} --body-file {tempfile}
   ```
3. Delete the temporary file.
4. Re-read the issue to confirm the fix.
5. If still corrupted after retry, warn the user that the issue body
   may need manual editing.

### 7. Report

Display the created issue by number **and** title together (e.g.
`#42 Fix login crash`, never the number alone) plus its URL, and whether
it blocks the current story or is deferred.
