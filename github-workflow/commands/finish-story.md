---
description: 'Push the branch, create a PR, and update the board. Trigger: "finish", "open a PR", "ship it", "send for review".'
---

# Finish Story

Push the branch, create a PR, and update the board.

Requires: a story in progress with committed work on a feature branch.

> **This is a building block.** It only handles the push-and-PR tail of a
> story. When you run **`/github-workflow:execute`** end-to-end it does this
> for you automatically — reach for `finish-story` only to open the PR for
> work you built by hand outside the orchestrator.

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
  # Project ClaudeProject.md → drop the heavy sections only needed later.
  # Pure POSIX shell (no awk/tee) so it works wherever bash runs, including
  # a Windows bash whose PATH lacks the Unix coreutils that ship awk/tee.
  mkdir -p .claude 2>/dev/null
  drop=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '## '*) case "$line" in
          '## Issue Types & Fields'*|'## Project Board'*|'## Story Template'*|'## Session Budget'*|'## Reference Docs'*|'## Bundled Skills'*) drop=1 ;;
          *) drop=0 ;;
        esac ;;
    esac
    [ "$drop" -eq 0 ] && printf '%s\n' "$line"
  done < ClaudeProject.md > .claude/projected-config.md
  cat .claude/projected-config.md
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

### 3–4c. Push, pre-flight reads, and duplicate detection — in parallel

Issue the following as a single tool-call batch. All four have no
ordering dependency on each other; the push just has to finish before
you can *create* the PR in Step 5:

- **Push the branch:**
  ```
  git push -u origin HEAD
  ```

- **Check for an existing PR on this branch** (from a prior session that
  pushed but didn't finish cleanly):
  ```
  gh pr list --repo {org}/{repo} --head {branch} --state open --json number,title
  ```

- **Determine issue linkage** — check session context for a story number
  from `execute` or `start-story`; if none, check the branch name for an
  issue number (`feature/42/description` → #42) and verify it exists:
  ```
  gh issue view {number} --repo {org}/{repo} --json state,id --jq '{state:.state,id:.id}'
  ```
  If the branch carries no number and context has none, defer issue
  creation to after the push (Step 4b-create below).

- **Sibling-PR detection** — check for another open PR that closes the
  same issue on a different branch. Run the authoritative lookup in
  `templates/sibling-pr-lookup.md` with this `{number}` and ignore any
  result whose `headRefName` equals `{branch}`.

Wait for all four to complete, then act on the results:

**If an existing PR was found on this branch** — update it instead of
creating a new one (write body to temp file, use `gh pr edit --body-file`,
delete temp file, validate per Step 5b) and skip to Step 6. Only create
a new PR if none exists.

**If a sibling PR was found on a different branch** — still create your
PR in Step 5, but prepend this flag line to the body so code review
reconciles them:
```
> ⚠ Possible duplicate of #{sibling_number} — both close #{number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
```
Report the duplicate to the user. Do not pick the winner here.

### 4b-create. Create missing issue (if needed)

Skip this step if issue linkage was confirmed above. Only run it when no
issue number is available from context or branch name:

Use the commit history and diff to build a proper issue body:

- **Title**: derive from the branch name or first commit message; apply
  the appropriate issue prefix (`[STORY]`, `[BUG]`, `[SECURITY]`,
  `[ARCH]`, or `[DEBT]`) from ClaudeProject.md.
- **Body**: Context (what was built and why), Requirements (what the
  changes accomplish), Notes (any caveats).
- **Labels**: resolve type, priority, `claude-authored`, and
  `status-in-review` — all by purpose key via `templates/default-labels.md`.
  If `.claude/label-cache.json` exists, look up each label ID from the
  cache to confirm existence before applying; create any that are missing
  (guarded create-if-missing, no `--force`) and add them to the cache.
- **Milestone**: if in sprint mode, attach to the current milestone.

Write the body to a temp file and create:
```
gh issue create --repo {org}/{repo} --title "{title}" --body-file {tempfile} --label "{labels}"
```
Delete the temp file. Validate and apply native type + fields exactly as
`/github-workflow:report-issue` Step 5c (`templates/issue-fields-resolution.md`,
capability-gated, best-effort); set `Origin` to **Development**.

**Leave the assignee blank** — a follow-up issue must enter the unassigned
pool for normal pickup; assignment happens only at claim time.

Record the new issue number for use in Step 5.

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

### 7–8. Apply labels, move the issue, and update the board — one mutation

Skip this step entirely if Step 4 found an existing PR that already
carries a review-state label (e.g. `approved`, `needs-re-review`) — do
not reset a reviewed PR back to `needs-review`. Use the `labels` field
already read in Step 6; no extra `gh pr view` here. (Step 6 may already
have moved it to `needs-re-review` on a complex conflict.)

Otherwise, apply the following changes in a **single combined GraphQL
mutation** instead of separate `gh pr edit`, `gh issue edit`, and board
calls:

- **PR labels:** `claude-authored` (provenance) + the review-state entry
  label (`review-needs-review` when the gate passed;
  `review-changes-requested` when the gate-failed flag is set — exactly
  one). Exactly one review-state label.
- **Issue lifecycle label:** remove `status-in-progress`, add
  `status-in-review`. This is the authoritative "in review" signal — not
  the board.
- **Board move (best-effort, if configured):** set the issue to the **In
  Review** column (`col-in-review`, per the label ⇄ column pairing in
  `templates/default-labels.md`).
- **Target date (best-effort, capability-gated):** if the org defines a
  `Target date` issue field (`templates/issue-fields-resolution.md` Steps
  2–3), set it to today in the same mutation.

**Prerequisites** — resolve before building the mutation:
- PR and issue node IDs: available from Step 5 (PR create result) and
  Step 4b (issue view result). Fetch any that are missing.
- Label node IDs: look up `claude-authored`, the review-state entry
  label, `status-in-progress`, and `status-in-review`. The execute session
  no longer prewarms a label inventory, so `.claude/label-cache.json` is
  usually absent — fall back to `gh label list` to fetch the IDs (this is the
  deferred, first-use fetch); read the cache instead only if it exists from an
  earlier fallback this session. If any label is missing, create it with the
  guarded create-if-missing pattern from `templates/default-labels.md` (no
  `--force`), write/append the new entry to the cache, and use that ID.
- Board item ID, project ID, field ID, and column option ID: follow
  `templates/board-resolution.md`. Skip the board alias if no board is
  configured. Resolve the `Target date` field node ID from
  `templates/issue-fields-resolution.md` if needed.

**Combined mutation:**
```
gh api graphql -f query='
  mutation FinishCombined(
    $prId:ID!, $issueId:ID!,
    $prAddLabels:[ID!]!,
    $issueRemoveLabels:[ID!]!, $issueAddLabels:[ID!]!,
    $projId:ID!, $itemId:ID!, $fieldId:ID!, $colVal:String!
  ){
    addPRLabels:      addLabelsToLabelable(input:{labelableId:$prId, labelIds:$prAddLabels}){ __typename }
    removeIssueLabel: removeLabelsFromLabelable(input:{labelableId:$issueId, labelIds:$issueRemoveLabels}){ __typename }
    addIssueLabel:    addLabelsToLabelable(input:{labelableId:$issueId, labelIds:$issueAddLabels}){ __typename }
    moveBoard:        updateProjectV2ItemFieldValue(input:{projectId:$projId, itemId:$itemId, fieldId:$fieldId, value:{singleSelectOptionId:$colVal}}){ __typename }
  }' \
  -F prId="$PR_NODE_ID" \
  -F issueId="$ISSUE_NODE_ID" \
  -F prAddLabels="[\"$CLAUDE_AUTHORED_ID\",\"$REVIEW_STATE_LABEL_ID\"]" \
  -F issueRemoveLabels="[\"$STATUS_IN_PROGRESS_ID\"]" \
  -F issueAddLabels="[\"$STATUS_IN_REVIEW_ID\"]" \
  -F projId="$PROJ_NODE_ID" \
  -F itemId="$ITEM_ID" \
  -F fieldId="$STATUS_FIELD_ID" \
  -F colVal="$IN_REVIEW_OPTION_ID"
```

Omit the `moveBoard` alias (and its variables) when no board is
configured. Add a fifth alias for the `Target date` field when it exists.

**Fallback** — if the combined mutation fails (e.g. a label ID was stale
in the cache), fall back to the three individual calls: `gh pr edit` for
PR labels, `gh issue edit` for the lifecycle label, and
`board-resolution.md` Step 5 for the board. The label-presence guarantee
still holds: the individual calls verify via exit code and
create-if-missing as before.

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
a dirty tree is never auto-removed). Delete all per-session scratch files
and run the **End clean** procedure in `templates/worktree-hygiene.md`:

```
rm -f .claude/plan.md .claude/preflight-passed.txt \
      .claude/label-cache.json
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
