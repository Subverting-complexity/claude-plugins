---
description: 'Assign a story, update the board, and create a working branch. Trigger: "start story N", "begin working on N", "assign me story N".'
argument-hint: '[issue#]'
---

# Start Story

Assign the story, update the board, and create a working branch. This is
the manual single-step equivalent of `execute` Phase 1–2; it shares the
same procedures, so behaviour is identical.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

Requires a story number. If none is given, run the
`/github-workflow:pick-story` flow to auto-select the next story and use
that number. Do not ask the user which story to start.

## Preflight

Invoke `/github-workflow:preflight` first. If it finds issues and the user
chooses "Configure now", wait for setup, then ask the user to re-run this
command. Otherwise proceed.

**Skip preflight if it already passed this session.** When this command
runs straight after `/github-workflow:pick-story` in the same session,
preflight has already run green and nothing has changed — do **not** invoke
it again. Only run it on a fresh, standalone start.

## Steps

### 1. Read configuration

Extract `org`, `repo`, `default-branch`, the branch convention, the label
map, and project-board settings from `ClaudeProject.md`. **If `pick-story`
already loaded it into context this session, reuse that copy — do not read
the file again.** Read it only if it is not already in context. Resolve
every label by **purpose key** from that label map — never a bare literal,
and only fall back to `templates/default-labels.md` for a purpose key the
map omits.

### 2. Already-in-flight guard (explicit number only)

`pick-story` only hands back unassigned, ready issues, but an explicit
number can name a story that already has a PR — and the claim ref is
released the moment that PR opens, so a fresh claim would otherwise
duplicate it. Before claiming:

```
gh issue view {number} --repo {org}/{repo} --json state,labels,assignees
```

Then find any open PR that already closes this issue via the authoritative
lookup in `templates/sibling-pr-lookup.md` with this `{number}`.

- Issue **closed** → report and stop.
- **Open PR already closes it** → do not start fresh; report the PR
  (number + title), point the user at `/github-workflow:update-pr`, stop.
- Carries `status-in-review` with no open PR found → surface the
  inconsistency and stop rather than guessing.
- Otherwise → proceed to claim.

### 3. Claim the issue

Acquire it with `templates/claim-procedure.md` (**Acquire**, target
`issue-{number}`). The atomic ref is a genuine compare-and-swap; the first
agent wins, a loser exits cleanly having made no changes. Acquire also
applies the durable markers — it assigns `@me` **and** moves the issue to
`status-in-progress` (removing any prior lifecycle label). Do not assign or
set a status label separately, and do not read the labels back: Acquire's
Step 4 already applies the verify-after-create-only contract (trust the
`gh issue edit` exit code; only the rare missing-label branch reads).

If Acquire reports the claim is lost, stop — another agent owns this story.
If `pick-story` already claimed it in this same flow, Acquire's re-entry
check treats it as a no-op and proceeds.

### 4. Update project board (if configured)

Resolve the board, the issue's `{item_id}`, and the target column's
`{column_option_id}` via `templates/board-resolution.md`, then run its
**Step 5** mutation. The target column for `status-in-progress` is **In
Progress** (`col-in-progress`) per the label ⇄ column pairing in
`templates/default-labels.md`.

Set the board start date too if a `start-date-field-id` is configured (the
Step 5 date-field form, `value: { date: "{today}" }`). Independently of the
board,
set the org-level **`Start date`** issue field to today (best-effort,
capability-gated) per `templates/issue-fields-resolution.md` (Steps 2, 3,
5) — skip silently if the org does not define it.

When **no** board is configured, skip this step silently. When a board
**is** configured, board failures are loud: report and continue.

### 5. Validate the issue body

Read the issue body. It needs at minimum **Context** (what and why) and
**Requirements** (acceptance criteria / expected behavior). If linked docs
or comments supply enough context, proceed. If truly empty with no guidance
anywhere, run `/github-workflow:block-story`.

### 6. Create branch

```
git fetch origin {default-branch}
```

Apply the branch convention from config. Generate `{short-desc}` from the
issue title: lowercase; replace spaces/special chars with hyphens; collapse
consecutive hyphens; truncate to 40 chars; strip trailing hyphens. (Issue
"Fix: User login broken!!!" with `feature/{number}/{short-desc}` →
`feature/42/fix-user-login-broken`.)

Check whether the branch already exists (from a prior blocked or partial
attempt):

```
git branch --list {branch}
git ls-remote --heads origin {branch}
```

- **Exists locally or remotely** → check it out and rebase onto the latest
  default branch:
  ```
  git checkout {branch}
  git rebase origin/{default-branch}
  ```
  - If `git checkout` fails because the branch is **already checked out in
    another worktree**, that is a lost claim — another agent on this machine
    owns the work. Stop and exit cleanly per the claim-procedure
    **Lost-claim path**: change nothing.
  - If the rebase **conflicts**, do not fork a parallel branch — the atomic
    claim guarantees no rival shares this branch, so a conflict is a genuine
    divergence. `git rebase --abort`, then run `/github-workflow:block-story`
    with the conflict details.
- **Does not exist** → create it:
  ```
  git checkout -b {branch} origin/{default-branch}
  ```
