# Board + item_id resolution

Shared procedure for every command that writes to the GitHub project
board (`start-story`, `finish-story`, `block-story`, `pick-story`, and
the `execute` skill's Phase 2). It resolves the board by **stable
identity** and produces a verified `{item_id}` for the issue so board
mutations target the right board and the right item.

Run this **once** before any `updateProjectV2ItemFieldValue` mutation.
It replaces the previously unresolved `{item_id}` placeholder — never
feed a board mutation an `{item_id}` you have not resolved here.

Inputs:

- `{number}` — the issue number being moved.
- From `ClaudeProject.md` `## Project Board`: `project-node-id`,
  `project-title`, `status-field-id`, and the relevant Status option id.
- `{org}` / `{repo}` from `## Identity`.

## Step 1 — Is a board configured?

A board is **configured** when `ClaudeProject.md` has a `## Project
Board` section AND `project-node-id` is a real id (not absent, not
`n/a`, not a `{placeholder}`).

- **Not configured** → skip all board operations **silently**. Board
  updates are best-effort only in this case. Do not emit an error. Stop
  here; the command proceeds without a board write.
- **Configured** → continue to Step 2. From here on, board failures are
  **loud**, not silent (see Step 4).

## Step 2 — Verify board identity (fail loud on mismatch)

Resolve the stored `project-node-id` and confirm it still points at the
intended board by comparing its live title to `project-title`:

```
gh api graphql -f query='query($id:ID!){ node(id:$id){ ... on ProjectV2 { title } } }' -F id='<project-node-id>' --jq '.data.node.title'
```

- Title **matches** `project-title` → identity confirmed, continue.
- Node does **not** resolve to a ProjectV2, or the resolved title
  **differs** from `project-title` → **ABORT all board writes** with a
  clear error. Do **not** guess or fall back to another board:

  ```
  Board write aborted: stored project-node-id resolves to '<resolved>'
  but ClaudeProject.md project-title is '<configured>'. Fix the board
  config (re-run /github-workflow:setup) before board updates can
  proceed. Continuing the rest of the workflow without a board update.
  ```

  Report this prominently to the user and skip the board mutation. The
  surrounding command still completes its non-board steps.

If `project-title` is absent from `ClaudeProject.md`, the identity check
cannot run — treat this as a mismatch (abort board writes, loud) and
tell the user to add `project-title` via `/github-workflow:setup`.

## Step 3 — Resolve the issue's item_id

Find the issue's item on the **configured** board. Query the issue's
project items and match the one whose `project.id` equals
`project-node-id`:

```
gh api graphql -f query='query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner, name:$repo){
    issue(number:$number){
      id
      projectItems(first:20){ nodes { id project { id title } } }
    }
  }
}' -F owner='{org}' -F repo='{repo}' -F number={number} \
  --jq '{issueId:.data.repository.issue.id, items:.data.repository.issue.projectItems.nodes}'
```

- A node with `project.id == project-node-id` exists → use its `id` as
  `{item_id}`.
- No matching node (the issue is not on the board yet) → add it, and
  capture the returned item id:

  ```
  gh api graphql -f query='mutation($project:ID!,$content:ID!){
    addProjectV2ItemById(input:{ projectId:$project, contentId:$content }){
      item { id }
    }
  }' -F project='<project-node-id>' -F content='<issueId>' \
    --jq '.data.addProjectV2ItemById.item.id'
  ```

  Use the returned `item.id` as `{item_id}`. `addProjectV2ItemById` is
  idempotent — if the item already exists it returns the existing id, so
  it is safe to call.

You now have a verified `{item_id}` on the confirmed board.

## Step 4 — Resolve the target column's option id (live, by name)

The calling command names the destination by **column purpose key**
(`col-in-progress`, `col-in-review`, `col-blocked`, `col-ready`,
`col-backlog`, `col-done`) — never by a hardcoded column name. The
snapshotted Option IDs in `ClaudeProject.md` are a setup-time convenience,
**not** the source of truth: a user who renames or reorders columns in the
GitHub UI leaves them stale, and trusting a stale id moves the issue to the
**wrong column** with no error. So resolve the option id **live by column
name** at write time, and use the snapshot only to detect drift.

1. **Resolve the expected column name.** Map the purpose key to its column
   **name** through `templates/default-labels.md` → Board Columns
   (`col-in-progress`→`In Progress`, `col-in-review`→`In Review`,
   `col-blocked`→`Blocked`, `col-ready`→`Ready`, `col-backlog`→`Backlog`,
   `col-done`→`Done`), preferring any per-project override name in
   `ClaudeProject.md` → `### Status Options`.

2. **Fetch the live Status field and its options** (one call — this also
   yields the live field id, so a renamed/stale `status-field-id` cannot
   misdirect the write either). Use the `status-field-name` from the
   `## Project Board` table (defaults to `Status` if absent):

   ```
   gh api graphql -f query='query($id:ID!,$fname:String!){ node(id:$id){ ... on ProjectV2 {
     field(name:$fname){ ... on ProjectV2SingleSelectField { id options { id name } } }
   } } }' -F id='<project-node-id>' -f fname='<status-field-name>' --jq '.data.node.field | {fieldId:.id, options:.options}'
   ```

3. **Match the option by name** (case-insensitive, trimmed) against the
   expected column name. The matched option's `id` is `{column_option_id}`
   and the returned `fieldId` is the live `{status_field_id}` for Step 5.

4. **Validate the snapshot and warn on drift.** Compare the live id to the
   purpose key's snapshotted Option ID in `ClaudeProject.md`. If they
   differ (snapshot stale, column reordered, or the id now names a
   different option), proceed with the **live** id and report it loudly,
   non-fatally:

   ```
   Board snapshot stale: column '<name>' resolves live to <live_id> but
   ClaudeProject.md records <snapshot_id>. Using the live id; run
   /github-workflow:setup to refresh the board snapshot.
   ```

5. **No option matches the expected name** → the column genuinely does not
   exist on the board. This is the `board-columns-incomplete` condition
   preflight flags — do **not** invent an id. Skip the board move and
   report it loudly (a configured board is missing a required column; run
   `/github-workflow:setup` to create it). The rest of the workflow
   continues.

If the live query itself fails (network/permission), fall back to the
snapshotted Option ID for the purpose key — a best-effort write with a
possibly-stale id beats no write — and note that live resolution could not
run. A snapshot id that is `n/a`/absent in that fallback is the
`board-columns-incomplete` case (point 5 above): skip and report.

The label ⇄ column pairing (which purpose key a given lifecycle label
moves to) is defined once in `templates/default-labels.md` — callers cite
the pairing rather than re-deriving it.

## Step 5 — Run the mutation, and fail loud on errors

With a verified `{item_id}`, `{project_node_id}`, the live
`{column_option_id}` and the live `{status_field_id}` (both resolved in
Step 4 — the snapshot is fallback only), set the issue's Status to the
target column. This is the **one** copy of the board mutation — callers
name the target column by purpose key (Step 4) and run this; they do not
inline their own:

```
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{project_node_id}"
    itemId: "{item_id}"
    fieldId: "{status_field_id}"
    value: { singleSelectOptionId: "{column_option_id}" }
  }) { projectV2Item { id } }
}'
```

**Date fields use the same mutation shape** with `value: { date:
"{today}" }` against the relevant date field id (e.g.
`start-date-field-id`, `end-date-field-id`) — a caller that stamps a board
date runs this form in addition to the Status write.

Because a board is configured, a failure of the identity check (Step 2),
the item_id resolution (Step 3), the column resolution (Step 4), or the
mutation itself is **reported loudly** to the user — never swallowed (e.g.
"Board update failed: {error}. Continuing without board update."). The
workflow still continues past the board step; only the board write is
skipped.

> Caveat (Windows / auto-run blocks): these queries contain code fences
> and must be run by hand, not inside a `!`-prefixed auto-run block — an
> auto-run block truncates at the first fence (see issue #33).
