---
description: 'Push the branch, create a PR, and update the board. Trigger: "finish", "done", "open a PR", "ship it", "create the PR", "submit", "wrap up", "push it", "send for review".'
---

# Finish Story

Push the branch, create a PR, and update the board.

Requires: a story in progress with committed work on a feature branch.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Current state (auto-detected)

**Branch:** !`git branch --show-current 2>/dev/null || echo "(unknown)"`

**Recent commits:**
```!
git log --oneline -5 2>/dev/null || echo "(no commits)"
```

**Project configuration:** a **projection** — the hot-path config
(Identity, Branch Convention, Label Map, …) with the heavy sections
dropped (Issue Types & Fields, Project Board, Story Template, Session
Budget, Reference Docs, Bundled Skills). The board move (Step 8) and any
org-field write read the omitted `## Project Board` / `## Issue Types &
Fields` section from `ClaudeProject.md` at that point.
```!
if [ -f .claude/projected-config.md ] && [ .claude/projected-config.md -nt ClaudeProject.md ] 2>/dev/null; then
  cat .claude/projected-config.md
elif [ -f ClaudeProject.md ]; then
  awk '/^## /{drop=($0 ~ /^## (Issue Types & Fields|Project Board|Story Template|Session Budget|Reference Docs|Bundled Skills)/)} !drop' ClaudeProject.md | tee .claude/projected-config.md
else
  echo "ClaudeProject.md NOT FOUND"
fi
```

## Steps

### 1. Read configuration

Extract from the project configuration above:

- `org`, `repo`, `default-branch` from Identity
- Label map (for claude labels and the issue lifecycle states)
- Project board settings are **not** in the projection — Step 8 reads the
  `## Project Board` section from `ClaudeProject.md` when it moves the board

Resolve every label by **purpose key** through the single path in
`templates/default-labels.md`:

- **Issue lifecycle** purposes (`status-in-review`) and **claude**
  purposes (`claude-authored`) — via the `ClaudeProject.md` label map.
- **Review-state** purposes this command applies to the PR
  (`needs-review`, `needs-re-review`) — via `review.config.md` when
  present, defaults (`review-` prefix) otherwise.

Resolve them, never apply a bare name literally, so the labels this
command writes are the identical strings the code-review and update-pr
skills filter on. If `ClaudeProject.md` is missing or has no label map,
use the defaults from `templates/default-labels.md`. When using defaults
in an interactive session, warn the user: "Label map not configured —
using default labels. Run `/github-workflow:setup` to configure labels
for this project."

### 2. Run the quality gate

Run the quality gate command from `ClaudeProject.md` to verify the code
is clean before pushing:

1. Execute the quality gate script/command.
2. If it fails, read the error output, fix the issue, and re-run.
3. Repeat up to 3 times (4 total runs maximum).
4. If still failing after 4 runs, **do not create a draft PR** (this
   workflow never opens drafts). The work is complete but the gate is
   red, so a human still needs to see it: set a flag to open a **real
   PR** and mark it blocked-for-merge via labels in Step 7 — apply the
   `changes-requested` review-state label and add a "Quality Gate Failed"
   section to the PR body with the last error output. The blocking label
   (not draft status) is what signals "do not merge yet."

### 3. Push the branch

```
git push -u origin HEAD
```

### 4. Check for existing PR

Before creating a new PR, check if one already exists for this branch
(e.g., from a previous session that pushed but didn't finish cleanly):

```
gh pr list --repo {org}/{repo} --head {branch} --state open --json number,title
```

If a PR already exists, update it instead of creating a new one:

```
gh pr edit {pr_number} --body-file {tempfile}
```

Write the updated body to a temporary file first, then use
`--body-file` to avoid Windows/PowerShell shell-escaping issues.
Delete the temp file after. Then validate the body was applied
(same as Step 5b).

Skip to Step 6 (labels). Only create a new PR if none exists.

### 4b. Ensure issue linkage

Every PR must link to a GitHub issue for traceability. Before creating
a new PR, determine whether the current work has an associated issue:

1. Check session context for a story number from `/github-workflow:execute`
   or `/github-workflow:start-story`.
2. If no story number is known, check the branch name for an issue
   number (e.g., `feature/42/description` → issue #42). Verify it
   exists:
   ```
   gh issue view {number} --repo {org}/{repo} --json state --jq '.state'
   ```
3. If no issue is found from context or branch name, create one now.
   Use the commit history and diff to build a proper issue body:

   - **Title**: derive from the branch name or first commit message.
     Apply the appropriate issue prefix (`[STORY]`, `[BUG]`,
     `[SECURITY]`, `[ARCH]`, or `[DEBT]`) from ClaudeProject.md.
   - **Body**: include Context (what was built and why), Requirements
     (what the changes accomplish), and Notes (any caveats).
   - **Labels**: resolve the appropriate type and priority labels, the
     `claude-authored` provenance marker (this issue is Claude-created),
     and the `status-in-review` lifecycle label (a PR is being opened for
     it now) — all by purpose key via `templates/default-labels.md`. Then
     run label validation (check existence, create-if-missing without
     `--force`) before applying:
     ```
     gh label list --repo {org}/{repo} --json name --jq '.[].name'
     gh label create "{label}" --repo {org}/{repo} --description "{desc}" --color "{color}"
     ```
   - **Milestone**: if in sprint mode, attach to the current milestone.

   Write the issue body to a temporary file, then create using
   `--body-file` to avoid Windows/PowerShell shell-escaping issues:

   ```
   gh issue create --repo {org}/{repo} --title "{title}" --body-file {tempfile} --label "{labels}"
   ```

   Delete the temp file after. Then validate the issue body and
   labels were applied correctly — read back and verify, same as
   the validation in `/github-workflow:report-issue` Steps 5b and 6.

   - **Native type + fields**: then upgrade the issue exactly as
     `/github-workflow:report-issue` **Step 5c**
     (`templates/issue-fields-resolution.md`, capability-gated,
     best-effort): set the native issue type per the *Native issue type
     map* in `templates/default-labels.md`, populate `Classification` (per
     that map's classification column), `Effort` (assess scope: Low/Medium/High),
     `Priority` (dual-tracked with the label), and remove the redundant
     `type-*` label on a type-capable org. `Origin` here is **Development**
     (the issue is being filed as the work is wrapped up).

   **Leave the assignee blank.** Do not pass `--assignee`/`--add-assignee`
   on this `gh issue create`, and do not edit the new issue to assign it.
   A follow-up issue must enter the unassigned pool so it is eligible for
   normal pickup; assignment happens only at claim time, never at
   creation.

   Record the new issue number for use in Step 5.

The issue number (from context, branch, or newly created) is used in
Step 5 to add `Closes #N` to the PR body.

### 4c. Duplicate-PR detection

Step 4 already ruled out an existing PR on **this** branch. Now check for
a sibling open PR that closes the **same issue** on a **different** branch
(a second session may have built the same story — see the duplicate
vectors in `skills/code-review/references/review-workflow.md`). Run the
authoritative lookup in `templates/sibling-pr-lookup.md` with this
`{number}` and ignore any result whose `headRefName` equals `{branch}`.

If a sibling PR exists, still create your PR in Step 5 (so both are real
and comparable) but prepend this flag line to the body so code review
reconciles them:

```
> ⚠ Possible duplicate of #{sibling_number} — both close #{number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
```

Report the duplicate to the user. Do not pick the winner or close the
other PR here — code review's Step 2b does that with full context.

### 5. Create new PR

Build the PR body from the committed changes:

- Summarize what was built (from commit messages and diff)
- List acceptance criteria addressed
- Note any technical decisions made
- Add a test plan section
- **Always** close the associated issue: include a `Closes #N` line for
  every issue this PR resolves (see the linked-issue format below). A PR
  for a story must never omit this — if no issue is linked, that is a
  workflow error to resolve before opening the PR.

Write the PR body following `templates/body-file-write.md` (temp file +
`--body-file`). **Always create a real PR — never a draft.** The same
command is used whether or not the quality gate passed; a failed gate is
signalled by a blocking label in Step 7, not by draft status:

```
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
```

When the quality gate failed (Step 2), prepend this section to the body
so the failure is visible (the `changes-requested` label applied in
Step 7 is what actually blocks merge):

```
> **⚠ Quality gate failed** — the quality gate did not pass after 4
> attempts. This PR carries the `changes-requested` label and must not
> be merged until the gate is green. See error details below.
>
> **Last error:**
> {quality_gate_error_output}
```

Every PR **must** close its associated issue(s). Each linked issue gets
its own `Closes #N` line in the PR body:

```
Closes #42
Closes #43
```

Each `Closes #N` must be on its own line so GitHub links them in
the Development sidebar and auto-closes the issue on merge. The Step 5b
validation must confirm a `Closes #N` line is present for every linked
issue before the PR is considered done.

### 5b. Validate PR body

After creating or updating the PR, validate the body by reading it back
and applying the corruption test and retry in
`templates/body-file-write.md` (**Validate** + **Retry**).

For a PR body the test additionally requires a `Closes #N` line for every
linked issue — a PR must always close its associated issue. If any is
missing, add it (via `gh pr edit --body-file`) before proceeding.

### 6. Resolve merge conflicts

Read the PR's post-create state, fetching every field the remaining steps
need in a single round trip — the conflict status here plus the labels
Step 7 confirms — instead of one `gh pr view` per step:

```
gh pr view {pr_number} --repo {org}/{repo} --json number,mergeable,mergeStateStatus,labels
```

**Handle `UNKNOWN` before branching.** GitHub computes mergeability
asynchronously after a PR is created or a force-push lands; the first
read can return `UNKNOWN` for a short window. If `mergeable` is
`UNKNOWN`, poll with a bounded backoff before acting on the value:

```
# Retry at 3 s, 5 s, and 10 s (three attempts; ~18 s total)
for delay in 3 5 10; do
  sleep $delay
  result=$(gh pr view {pr_number} --repo {org}/{repo} \
    --json number,mergeable,mergeStateStatus,labels)
  mergeable=$(echo "$result" | jq -r '.mergeable')
  [ "$mergeable" != "UNKNOWN" ] && break
done
```

If `mergeable` is still `UNKNOWN` after all retries, treat it as
`MERGEABLE` and say so: "Merge status remained UNKNOWN after polling;
assuming no conflict — a reviewer will catch any issues before merge."
This is the safe default: spuriously triggering a rebase on a branch
that GitHub just hasn't evaluated yet is more disruptive than leaving a
real conflict for the reviewer, who will catch it before merge.

Keep the final result object; Step 7 reuses its `labels` field rather
than issuing its own read. If `mergeable` is `CONFLICTING`:

1. Fetch the latest base branch and rebase onto it:
   ```
   git fetch origin {default-branch}
   git rebase origin/{default-branch}
   ```
2. Resolve conflicts one commit at a time as the rebase progresses.
   Read each conflicted file, understand both sides, and pick the
   correct resolution. Then continue:
   ```
   git add <resolved-files>
   git rebase --continue
   ```
3. After the rebase completes, run the quality gate again (1 run —
   if it fails, fix and retry once more, 2 total).
4. Force-push the rebased branch:
   ```
   git push --force-with-lease
   ```

**Classify the conflict resolution:**

- **Trivial conflicts** (import ordering, adjacent-line edits,
  whitespace, auto-resolved renames): no re-review needed.
- **Complex conflicts** (overlapping logic changes, altered control
  flow, modified function signatures, deleted code that the PR
  depended on): the rebased result needs a reviewer's eyes.
  - **New PR** (this `finish-story` just created it, no prior review):
    the `needs-review` entry label set in Step 7 already routes it to a
    reviewer — no extra label needed here.
  - **Existing PR** (Step 4 path — it was opened in a prior session and
    may already have been reviewed): move it to `needs-re-review`,
    removing any current review-state label so exactly one is present:
    ```
    gh pr edit {pr_number} --remove-label "{current_state_label}" --add-label "{needs_re_review_label}"
    ```

  After applying, verify the label is present (same as Step 7 below).
  If missing, create it and retry.

### 7. Add labels to PR

Apply two labels, both resolved by purpose key through the single path in
`templates/default-labels.md`:

1. **Provenance** — `claude-authored` (default `claude-authored`), to
   mark this as a Claude-built PR.
2. **Review-state entry label** — so the PR is never unlabelled and the
   reviewer can find it:
   - Quality gate passed → `needs-review` (default `review-needs-review`).
   - Quality gate failed (Step 2 flag) → `changes-requested` (default
     `review-changes-requested`), which blocks merge until the gate is
     green. Do **not** also apply `needs-review` — exactly one
     review-state label.

Skip this entirely if Step 4 found an existing PR that already carries a
review-state label (e.g. `approved`, `needs-re-review`) — do not reset a
reviewed PR back to `needs-review`; leave its existing state (Step 6 may
have moved it to `needs-re-review`). Decide this from the `labels` field
already read in Step 6 — no extra `gh pr view` here.

```
gh pr edit {pr_number} --add-label "{claude_authored_label}" --add-label "{needs_review_label}"
```

Do not read the labels back to confirm: `gh pr edit --add-label X` fails
loudly (non-zero exit, "could not add label") when `X` does not exist, so
the edit's exit status is the presence signal. Apply the contract:

- **Exit 0** → both labels are set; done.
- **Non-zero citing an unknown/missing label** → it was not created at
  setup. Create it with the guarded create-if-missing pattern from
  `templates/default-labels.md` — **without `--force`** so existing
  metadata is never overwritten, using the colours there — then retry the
  edit once.

### 8. Move the issue to In Review

**Issue lifecycle label (authoritative).** Move the linked issue to the
`status-in-review` lifecycle label, removing its current lifecycle label
(`status-in-progress`) so exactly one state is present. Resolve both
names by purpose key through `templates/default-labels.md`:

```
gh issue edit {number} --repo {org}/{repo} \
  --remove-label "{status_in_progress_label}" --add-label "{status_in_review_label}"
```

Trust the edit's exit code — do not read the labels back. `gh issue edit
--add-label X` fails loudly when `X` does not exist, so exit 0 already
confirms the label is set. Only on a non-zero exit citing a missing label
do you create it (guarded create-if-missing, no `--force`, per
`templates/default-labels.md`) and retry the edit once. This label — not
the board — is the authoritative "in review" signal, so it works even when
no board is configured.

**Project board (best-effort, if configured).** The auto-loaded
projection dropped `## Project Board`, so read that section from
`ClaudeProject.md` now for the board id, title, status field, and option
ids. Resolve the board, the
issue's `{item_id}`, and the target column's `{column_option_id}`
following `templates/board-resolution.md`, then run its **Step 5**
mutation to set Status. The target column for `status-in-review` is **In
Review** (`col-in-review`) per the label ⇄ column pairing in
`templates/default-labels.md`. The board-configured check (skip silently
when unconfigured), the identity verification, and the loud-on-failure
contract all live in that template.

**Target date (best-effort, capability-gated).** Record today as the
actual completion date by setting the org-level `Target date` issue field
following `templates/issue-fields-resolution.md` (Steps 2, 3, 5 — use
the date field form with `dateValue: "YYYY-MM-DD"` for today's date).
The issue node id is already available from Step 4b. Skip silently if the
org does not define this field.

### 9. Release the claim

The PR now exists, so the issue's assignment and the open PR are the
ownership markers — the select-to-start race window is closed and the
atomic claim ref is no longer needed. Release it (following
`templates/claim-procedure.md` **Release**) so `refs/claims/` stays
bounded to in-flight work:

```
git push origin :refs/claims/issue-{number}
rm -f .claude/claim-issue-{number}.sha
```

Idempotent — ignore an error if the ref is already gone. This does
**not** unassign the issue; it stays assigned to @me through review.

### 9b. Reconcile the working tree to clean

The PR is pushed, so local state is no longer the source of truth. Leave
the worktree clean so the harness can reap it (`docs/worktree-config.md` —
a dirty tree is never auto-removed). Delete the per-session scratch file
and run the **End clean** procedure in `templates/worktree-hygiene.md`:

```
rm -f .claude/plan.md
git status --porcelain    # reconcile until empty
```

Commit any incidental formatting on unrelated files as a **separate
`chore:` commit** and push it (it rides the PR branch); discard disposable
generated noise. **Never `git stash`** — the stash is shared across every
worktree on the clone. End with `git status --porcelain` empty.

### 10. Report

Display:

- PR number, title, and URL — always name the PR by number **and**
  title together (e.g. `#123 Add login button`), never the number alone
- Linked issue(s), each by number **and** title
- Labels applied
- Board status (if updated)
