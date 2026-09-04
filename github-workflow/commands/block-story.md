---
description: 'Mark the current story as blocked. Trigger: "blocked", "I''m stuck", "can''t continue", "blocked by a dependency".'
---

# Block Story

Mark the current story as blocked and record the reason.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

The **shape** of what you report follows
`../skills/user-facing-communication/SKILL.md`: lead with the outcome and
the current state, put anything outstanding, blocked or assumed where it
cannot be missed, name every work item as well as numbering it, and leave
out the investigation history. It applies to every reply you write, not
only the last one.

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

**Structured blocker metadata (best-effort, capability-gated).** Record the
blocker where the org can read it as well as a person: the **`Status
reason`** field carries a one-line "why" alongside the label, and a native
blocked-by edge makes the dependency visible in the GitHub UI. The
`## Dependencies` marker stays the source of truth for auto-unblock; this
adds to it. Write a one-entry spec and apply it:

```bash
mkdir -p .claude
cat > .claude/block-spec.json <<'JSON'
{"issues": [{"number": {number},
             "fields": {"field-status-reason": "{one-line reason}"},
             "blocked_by": [{blocking issue numbers}]}]}
JSON
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/block-spec.json
```

Drop `blocked_by` when the blocker is not another issue. Read the exit code: **0** applied it; **21** (`no-capabilities`) means the
org defines no issue fields, so skip silently — the comment and the body
marker remain the authoritative record; **22** (`spec-invalid`) means the
spec is wrong, so fix it; **24** (`partial`) means some of it landed, so
report what did not.

### 3. Release the claim and unassign

**First, the open-PR guard.** Blocking returns the issue to the
unassigned pool. If the story **already has an open PR**, that would let
another agent pick it up and open a *second* PR for the same work. A story
with a live PR is not "blocked from starting" — it is in review:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number}
```

Exit 0 with `found: 0` means no PR closes it. Exit 20 means the lookup
failed — say so and stop rather than returning the issue to the pool on an
unverified answer.

If an open PR closes this issue, **do not unassign and do not return the
issue to the pool**. Tell the user the story has an open PR (#N) and that
the blocker should be handled on the PR (push a fix, request changes via
review, or close the PR) rather than by blocking the issue. Record the
blocker comment (Step 2) if useful, then stop without unassigning. The
assignment keeps the issue out of the pick pool so no duplicate PR is
created.

Otherwise (no open PR), release the atomic claim ref so the issue can be
claimed again, then remove the assignee so the issue returns to the
unassigned pool and can be picked up by another agent or re-picked later:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --issue {number}
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

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" board-move {number} --column col-blocked
```

`col-blocked` is the column paired with `status-blocked` per
`templates/default-labels.md`. The command decides for itself whether a
board is configured (silent no-op when not), verifies the board's identity
before writing, and adds the issue if it is missing. It **always exits 0** —
a board mirrors the labels and is never the source of truth — so read
`moved` and `reason`, and report a failure rather than stopping for one.

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
