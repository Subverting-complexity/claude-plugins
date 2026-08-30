---
description: 'Mark the current story as blocked. Trigger: "blocked", "I''m stuck", "can''t continue", "blocked by a dependency".'
---

# Block Story

Mark the current story as blocked and record the reason.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

Requires: a story in progress with a known blocker.

## What "blocked" means

An issue is **blocked** when it cannot make progress because of something
outside its own control: another unfinished issue, an external decision,
missing access or credentials, or an upstream fix. Blocked is **not**
"I gave up" and **not** "this needs more spec" — that second case is
`needs-refinement`, a different state.

A blocked issue carries the `status-blocked` lifecycle label (so it is
visibly blocked in the issues list, not silently indistinguishable from
the backlog) and is kept out of the pick pool by the absence of
`status-ready`.

**How it becomes unblocked:**

- **Automatically** — when the blocker is another issue recorded as
  `Blocked by #N`, `execute`'s dependency-resolution step detects that
  all `#N` are closed, removes `status-blocked`, restores `status-ready`,
  and comments. The issue re-enters the pick pool.
- **Manually** — for non-issue blockers (a decision, access granted), a
  human removes `status-blocked` and applies `status-ready`.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo` from Identity
- Project board settings (if configured)
- Label map (for status labels)

If `ClaudeProject.md` is missing or has no label map, use the default
label names from `templates/default-labels.md`. When using defaults in
an interactive session, warn the user: "Label map not configured —
using default labels. Run `/github-workflow:setup` to configure labels
for this project."

### 2. Comment the blocker

Post a comment — write it following `templates/body-file-write.md` (temp
file + `--body-file`):

```
gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
```

The comment should include: the blocker reason, what was attempted,
what failed or is missing, and a suggested resolution if known.

If the blocker is another issue, also record it in the issue body under a
`## Dependencies` section as `Blocked by #N` (edit the body via
`--body-file`). This is what lets `execute` auto-unblock the issue when
`#N` closes. If the `## Dependencies` section already lists it, skip.

Add the marker and nothing else. The blocker narrative stays in the
comment, so do not restate it in the body, and leave the rest of the
body as it is. If you are editing the body for any other reason, the
result has to satisfy `../skills/writing-github-issues/SKILL.md`.

**Structured blocker metadata (best-effort, capability-gated).** Following
`templates/issue-fields-resolution.md`, also:

- Populate the **`Status reason`** field (Step 5) with a one-line summary
  of the blocker — the same reason from the comment, condensed — so the
  blocked state carries a machine-readable "why" alongside the label.
- When the blocker is another issue, add a native **`addBlockedBy`**
  relationship (Step 7) in addition to the `## Dependencies` marker (the
  marker stays the source of truth for auto-unblock; the relationship adds
  GitHub-UI visibility).

Skip silently on an org that does not define these — the comment and the
body marker remain the authoritative record.

### 3. Release the claim and unassign

**First, the open-PR guard.** Blocking returns the issue to the
unassigned pool. If the story **already has an open PR**, that would let
another agent pick it up and open a *second* PR for the same work. A story
with a live PR is not "blocked from starting" — it is in review. Check for
an open PR that closes this issue by running the authoritative lookup in
`templates/sibling-pr-lookup.md` with this `{number}`.

If an open PR closes this issue, **do not unassign and do not return the
issue to the pool**. Tell the user the story has an open PR (#N) and that
the blocker should be handled on the PR (push a fix, request changes via
review, or close the PR) rather than by blocking the issue. Record the
blocker comment (Step 2) if useful, then stop without unassigning. The
assignment keeps the issue out of the pick pool so no duplicate PR is
created.

Otherwise (no open PR), release the atomic claim ref so the issue can be
claimed again, following `templates/claim-procedure.md` (**Release**),
then remove the assignee so the issue returns to the unassigned pool and
can be picked up by another agent or re-picked later:

```
git push origin :refs/claims/issue-{number}
gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
```

The claim-ref delete is idempotent — ignore an error if the ref is
already gone.

### 4. Move the issue to the blocked state

Move the issue to the `status-blocked` lifecycle label, removing whatever
lifecycle label it currently has (`status-in-progress`, `status-ready`,
etc.) so exactly one state is present. Resolve both names by purpose key
through `templates/default-labels.md`:

```
gh issue edit {number} --repo {org}/{repo} \
  --remove-label "{current_lifecycle_label}" --add-label "{status_blocked_label}"
```

After applying, verify per `templates/default-labels.md` (read back the
labels; guarded create-if-missing without `--force` if the label is
absent, then retry once).

`status-blocked` keeps the issue out of the pick pool (it lacks
`status-ready`) **and** makes the blocked state visible in the issues
list. The blocker detail lives in the issue body (`## Dependencies`) and
the Step 2 comment.

If `ready-gate` is `board-column` or `both`, also move the issue out of
the "Ready" board column — to the **Blocked** column (`col-blocked`), the
column paired with `status-blocked` in `templates/default-labels.md` — so
the board agrees with the label. (This is the same move as Step 5; under a
board ready-gate it is required rather than best-effort.)

These commands are idempotent — a label remove no-ops if the label is
not present.

### 5. Update project board (if configured)

Resolve the board, the issue's `{item_id}`, and the target column's
`{column_option_id}` following `templates/board-resolution.md`, then run
its **Step 5** mutation to set Status. The target column for
`status-blocked` is **Blocked** (`col-blocked`) per the label ⇄ column
pairing in `templates/default-labels.md`. The board-configured check (skip
silently when unconfigured), the identity verification, and the
loud-on-failure contract all live in that template.

### 6. Reconcile the working tree to clean

Do **not** leave uncommitted work sitting in the worktree. There is no
cross-session resume, so a worktree left dirty "for a later session to
inspect" is never inspected — the work is stranded **and** the dirty tree
blocks the harness from ever reaping the worktree (`docs/worktree-config.md`).

Run the **End clean** procedure in `templates/worktree-hygiene.md`:

- **Real partial work** worth keeping — commit it to the story branch and
  **push** it (`git push -u origin HEAD`) so it survives the worktree
  being reaped. The pushed branch, not local state, is what a future
  session can build on.
- **Disposable scratch / generated noise** — discard it.

Do **not** `git stash` — the stash is shared across every worktree on this
clone, so shelving here can collide with another agent's work. End with
`git status --porcelain` empty. Releasing the claim (above) returns the
story to the backlog; reconciling the tree lets the worktree be reaped.

### 7. Report

Display what was blocked — naming the story by number **and** title
together (e.g. `#42 Add login button`, never the number alone) — why,
and that the story has been blocked and returned to the backlog.
Suggest running `/github-workflow:execute` to continue with the next story.
