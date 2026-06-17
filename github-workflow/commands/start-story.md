---
description: 'Start a story and take it all the way to a pull request — assign it, branch, then plan, build, test, and open the PR. Trigger: "start story N", "begin working on N", "work on N".'
argument-hint: '[issue#]'
---

# Start Story

Start a story and carry it through to a pull request: assign it, move the
board, create the working branch, then plan, build, test, and open the PR.
The setup half (assign + board + branch) is the manual single-step
equivalent of `execute` Phase 1–2 and shares the same procedures; once setup
is done this command hands straight off to `execute` Phase 3 onward, so the
end result is identical to running `execute` on a named story — one
invocation finishes the story.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

Requires a story number. If none is given, run the
`/github-workflow:pick-story` flow to auto-select the next story and use
that number. Do not ask the user which story to start.

## Preflight

Check whether preflight already ran and passed this session — if
`.claude/preflight-passed.txt` exists, skip the invocation entirely and
proceed directly to Step 1. The file is written by `preflight` on a clean
or WARNING-only run and deleted on exit, so it is valid for exactly this
session:

```
test -f .claude/preflight-passed.txt && echo "PREFLIGHT_ALREADY_PASSED"
```

If the file is absent, invoke `/github-workflow:preflight`. If it finds
issues and the user chooses "Configure now", wait for setup, then ask the
user to re-run this command. Otherwise proceed.

## Steps

### Fast path — pick + start in one call

The bundled `wf` picker selects (or targets), claims, validates, moves the
board to In Progress, and creates the working branch in a single call — the
mechanical whole of Steps 1–4 and 6. Run it from the repo root:

```bash
# no explicit number — auto-select the next story:
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --checkout

# explicit number — target that issue (run Step 2's in-flight guard first):
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout
```

For an **explicit number**, first run the **Step 2 already-in-flight guard**
below (it stops a second PR for a story already in review). If the guard
clears, pass the number to `wf pick --issue` — it runs the *same* claim +
validate machinery as auto-pick, so a story a merged PR already resolved is
**auto-closed and moved to Done with no prompt** (reported as a
`closed-already-resolved` side effect, then `status: all-blocked` — report it
and pick the next story).

On `status: ok` it returns the claimed issue plus `branch`, `checked_out`,
`board_moved`, and `side_effects`. The claim ref and the
`status-in-progress` + `@me` markers are held and you are on the working
branch, so do **Step 5** (validate the issue body) next, then continue into
**Step 7** (build the story end-to-end). Surface anything in `side_effects`.
If `checked_out` is false, read `branch_message` (e.g. a rebase conflict
against the default branch) and run `/github-workflow:block-story` instead of
continuing.

Fall back to the numbered steps below when any of these hold: the status is
`unsupported`, `no-candidates`, `all-blocked`, or `error`; or the launcher
reports Python is missing. The steps are the same logic `wf` encodes, kept as
the source of truth and the degraded-mode path.

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
- **A merged PR already closes it** (no open PR, but a **merged** PR lists
  this issue in its `closingIssuesReferences` — the same authoritative lookup,
  `states: MERGED`) → the story is already done but was never closed.
  **Auto-close it and move on — do not ask:** close the issue, move its board
  item to Done (`col-done`, best-effort), and re-run `/github-workflow:pick-story`
  for the next story.
  ```
  gh issue close {number} --repo {org}/{repo} --comment "Closing — already resolved by #{pr_number}."
  # then move {number} to col-done per templates/board-resolution.md Step 5
  ```
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

### 7. Build the story end-to-end

Setup is complete — the story is claimed and assigned, it carries
`status-in-progress`, the board is at In Progress, and you are on the working
branch. Do not stop here. Carry the story the rest of the way by continuing
with the `execute` workflow from **Phase 3 (Plan)** onward.

Read `../skills/execute/SKILL.md` and follow its **Phases 3–8** (Plan →
Build → Verify → Commit → Finish → Self-Review) on issue `{number}`, together
with that skill's **Exit cleanup** and **Escape hatches**. Phases 1 (Pick) and
2 (Start) are already done — the claim ref, the `status-in-progress` + `@me`
markers, the board move, and the branch this command just made all carry
straight through, so treat those phases as no-ops. Do **not** re-pick,
re-claim, or select a different story, and do not re-run `wf pick`.

This is what makes one `start-story` invocation finish the story: it ends with
a pull request open and the issue moved to In Review, exactly as `execute`
would. The only reasons to stop short are the ones `execute` itself defines —
the issue is too underspecified to implement (block it), it must be broken into
sub-stories first, or a phase hits a blocker — all handled by that skill's
escape hatches.
