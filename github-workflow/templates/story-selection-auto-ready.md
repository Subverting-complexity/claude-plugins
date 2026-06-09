# Story selection — Step 4: Lazy auto-ready scan

Read this file **only when the candidate pool is empty** (Steps 1–3 in
`templates/story-selection.md` produced no valid claim). Keeping it
separate means the scan logic is not in context on the common pick path.

## 4. Lazy auto-ready (only when the pool is empty)

Reached only when Steps 1–2 produced no candidates, or Step 3 exhausted
them all. *Now* — and only now — spend API calls to see whether anything
can be unblocked, because there is nothing else to pick. (Why this scan is
off the hot path: `templates/story-selection-rationale.md`, not read at
runtime.)

Scan two groups, regardless of assignee, for issues whose dependencies may
now be resolved:

- **Blocked issues** — carry the `status-blocked` label (found by label;
  `block-story` and Step 3 unassign them):
  ```
  gh issue list --repo {org}/{repo} --state open --label "{status_blocked_label}" --json number,body
  ```
- **Your non-ready issues** — assigned to `@me` and not in the ready state
  (missing `status-ready`, or not in the "Ready" column, per `ready-gate`).

For each, parse the body for the same dependency markers (Step 3). If
**all** referenced issues are now `CLOSED`, restore it to ready:

- **`label`, `both`, or `none`**: move it to `status-ready`, removing its
  current lifecycle label:
  ```
  gh issue edit {number} --repo {org}/{repo} \
    --remove-label "{current_lifecycle_label}" --add-label "{status_ready_label}"
  ```
- **`board-column` or `both`**: also move it to the **Ready** column
  (`col-ready`) per `templates/board-resolution.md`.

Comment that dependencies are resolved. Best-effort — skip an issue on any
API/parse error.

**If this restored at least one issue**, return to **Step 1** once and run
the selection again (the newly-ready work is now eligible). **If it
restored nothing**, report "No stories available for pickup" and stop — do
not loop, retry, or ask the user to create stories.
