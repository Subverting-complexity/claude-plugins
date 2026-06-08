---
description: 'Create a bug, security, architecture, or tech debt issue. Trigger: "report a bug", "log an issue", "found a bug", "report tech debt", "create an issue", "file a bug", "something''s broken", "found a problem", "raise an issue", "security issue", "vulnerability".'
---

# Report Issue

Create a bug, security, architecture, or tech debt issue discovered during development.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

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

Write the issue body following `templates/body-file-write.md` (temp file +
`--body-file`):

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

### 5c. Native issue type + field values (best-effort)

Upgrade the freshly-created issue from label-only classification to the
org's **native issue type** and **issue fields**, following
`templates/issue-fields-resolution.md`. This is capability-gated and
entirely best-effort: an org without native types or fields keeps the
label-only result from the steps above with no error.

1. Run **Step 1** (discover native issue types) and **Step 2** (discover
   issue fields) of `issue-fields-resolution.md`.
2. Resolve this issue's node id (**Step 3**).
3. **Native type (Step 4)** — if the org is type-capable, map the Step 2
   classification to a native type via the *Native issue type map* in
   `templates/default-labels.md`:
   - Bug → **Bug**, Security → **Bug**, Architecture → **Feature**,
     Tech Debt → **Feature**.
   - Set it with `updateIssueIssueType`, then **remove the now-redundant
     `type-*` label** you applied in Step 5 (`gh issue edit {number}
     --remove-label "{type_label}"`) — native type is not dual-tracked.
     On a non-type-capable org, skip this and leave the `type-*` label as
     the classification.
4. **Field values (Step 5)** — populate, for whichever fields the org
   defines, in one `setIssueFieldValue` call:
   - `Classification` ← choose the most accurate option from the full set
     (never leave blank):
     - Bug (default broken behaviour) → **Bug Fix**
     - Bug that is a regression (worked before) → **Regression**
     - Bug that is a speed/memory degradation → **Performance**
     - Security → **Security**
     - Architecture → **Architecture**
     - Tech Debt → **Tech Debt**
   - `Effort` ← assess scope and pick one option (always set):
     - **Low** — a targeted fix, a few files, clear solution
     - **Medium** — moderate scope, some investigation or refactoring needed
     - **High** — broad impact, architectural change, or significant
       unknowns
   - `Priority` ← the option mapped from the priority you chose in Step 3
     (Critical→Urgent, High→High, Medium→Medium, Low→Low). **Keep** the
     `priority-*` label too — priority is dual-tracked.
   - `Origin` ← **Development** (report-issue files issues found during
     development; if the report came from a security audit session, use
     **Security Audit** instead).
5. Report any failure loudly but continue — the issue already exists and
   carries its labels.

### 6. Validate issue body

After creating the issue, validate the body by reading it back and
applying the corruption test and retry in `templates/body-file-write.md`
(**Validate** + **Retry**). The `Closes #N` clause is PR-only and does not
apply to an issue body.

### 6b. Place the issue on the board (best-effort, if configured)

So the new issue mirrors its lifecycle label on the board from the moment
it is created, place it in the column paired with the lifecycle state
chosen in Step 3 (see `templates/default-labels.md` → Board Columns):

- `status-ready` → **Ready** (`col-ready`)
- `needs-refinement` → **Backlog** (`col-backlog`)

Resolve the board, the new issue's `{item_id}`, and the target column's
`{column_option_id}` following `templates/board-resolution.md`, then run
its **Step 5** mutation to set Status. The template's Step 3 **adds the
issue to the board** (a new issue is never on it yet); the
board-configured check (skip silently when unconfigured), the identity
verification, and the loud-on-failure contract all live there too.

### 7. Report

Display the created issue by number **and** title together (e.g.
`#42 Fix login crash`, never the number alone) plus its URL, whether
it blocks the current story or is deferred, and its board column (if
placed).
