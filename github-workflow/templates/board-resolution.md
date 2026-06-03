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

## Step 4 — Use it, and fail loud on errors

Pass the resolved `{item_id}` (and `{project_node_id}`) into the board
mutation the calling command runs. Because a board is configured, a
failure of the identity check (Step 2), the item_id resolution (Step 3),
or the mutation itself is **reported loudly** to the user — never
swallowed. The workflow still continues past the board step; only the
board write is skipped.

> Caveat (Windows / auto-run blocks): these queries contain code fences
> and must be run by hand, not inside a `!`-prefixed auto-run block — an
> auto-run block truncates at the first fence (see issue #33).
