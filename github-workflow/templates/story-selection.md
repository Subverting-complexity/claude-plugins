# Story selection (claim-first, validate-lazily)

The single, canonical way to go from "I want a story" to "I hold a claim on
a usable story." Referenced by `pick-story` and the `execute` skill's
Phase 1 — **do not restate this loop inline anywhere**; call this procedure
so both behave identically.

## Claim-first, validate-lazily

**Claim the top candidate first, then validate only that one** — never the
whole list. (Why this is cheaper and still race-safe:
`templates/story-selection-rationale.md`, not read at runtime.)

## Inputs

From `ClaudeProject.md` (already in context — do not re-read it): `org`,
`repo`, the label map, `agent-gating`, and `ready-gate`. The auto-loaded
config is a projection that omits `## Project Board`; when `ready-gate` is
`board-column` or `both`, read that section from `ClaudeProject.md` for the
`project-node-id` the Step 1 "Ready" column query needs. Plus the caller's
`mode` (`story` / `feature` / `maintenance`)
and any explicit issue number. Resolve every label by **purpose key** from
the in-context `ClaudeProject.md` label map — never filter on a bare
literal, and do not open `templates/default-labels.md` unless a purpose key
is missing from that map.

---

## 1. Assemble the candidate list

Candidates are always drawn from the **unassigned** pool (`--assignee ""`).
Request the `milestone` field in the **same** fetch so backlog mode (Step 2)
is decided from this result without a separate API call. How "ready" is
determined depends on `ready-gate`:

- **`label`** (default) — issues carrying `status-ready`:
  ```
  gh issue list --repo {org}/{repo} --state open --assignee "" --label "{status_ready_label}" --json number,title,labels,body,milestone --jq '.[] | {number, title, labels: [.labels[].name], body, milestone: .milestone.title}'
  ```
- **`board-column`** — issues in the "Ready" column of the project board:
  ```
  gh api graphql -f query='query { node(id: "{project_node_id}") { ... on ProjectV2 { items(first: 100) { nodes { fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } content { ... on Issue { number title labels(first:10) { nodes { name } } body state milestone { title } assignees(first:1) { nodes { login } } } } } } } } }'
  ```
  Keep items where Status is "Ready", state is OPEN, assignees is empty.
- **`both`** — the `label` query, then drop any candidate not also in the
  "Ready" board column.
- **`none`** (also written `off` / `disabled`, which normalise to `none`) —
  no readiness gate at all. Any open unassigned issue is
  eligible. Use this for fully autonomous pickup where no human readiness
  signal (label or column) is required:
  ```
  gh issue list --repo {org}/{repo} --state open --assignee "" --json number,title,labels,body,milestone --jq '.[] | {number, title, labels: [.labels[].name], body, milestone: .milestone.title}'
  ```
  Then **drop any candidate carrying `status-blocked`** — those are
  unassigned but still blocked. The other non-pickable states
  (`status-parked` / `status-in-progress` / `status-in-review`) stay
  assigned, so the unassigned filter already excludes them, and
  `needs-refinement` is dropped by the refinement filter below. (Why only
  `status-blocked` needs the explicit drop:
  `templates/story-selection-rationale.md`, not read at runtime.)

## 2. Detect backlog mode (from the candidates just fetched)

Decide sprint vs flat from the `milestone` already on each candidate — no
extra API call in the common case:

- **No candidate carries a milestone** → **Flat mode**: the whole fetched
  list is the pool. This is the common case and costs **zero** extra calls.
- **Some candidates carry a milestone** → **Sprint mode**: narrow to the
  active sprint. *Only now* spend one call to order milestones by due date
  and take the earliest open one as `{sprint_title}`:
  ```
  gh api repos/{org}/{repo}/milestones --jq 'map(select(.due_on != null)) | sort_by(.due_on) | map(select(.open_issues > 0)) | .[0].title'
  ```
  (Milestones without a due date are excluded — `sort_by` misorders
  nulls. If this yields nothing because none has a due date, say so and
  treat the backlog as flat.)
  Then **locally** drop any candidate whose `milestone` ≠ `{sprint_title}`.

Then narrow the list with **local** filters (no API calls):

- **Refinement:** exclude issues with the `needs-refinement` label. (The
  caller may instead choose to surface a top-priority `needs-refinement`
  issue to the user — see `execute` Phase 1. `pick-story` always excludes.)
- **Agent gating:** if `agent-gating` is `enabled`, exclude issues that do
  **not** carry the `claude-ready` label — only human-approved stories are
  eligible. If `disabled` (default), this filter is **ignored entirely**.
- **Mode:** filter by issue kind. **`story` (default) → no type filter at
  all: do not read `templates/issue-fields-resolution.md`, and do not run
  the native-type fetch below.** Only `feature` and `maintenance` filter by
  kind — `feature` keeps **story**-kind issues; `maintenance` keeps **bug /
  security / tech-debt / architecture** kinds. For those two modes only,
  resolve "kind" through `templates/issue-fields-resolution.md` Step 6:
  - **Type-capable org** → kind is the issue's **native issue type**. `gh`
    cannot project it (`--json issueType` is unsupported), so fetch it via
    GraphQL once and build a `number → type` map, then filter using the
    *Native issue type map* in `templates/default-labels.md` (feature keeps
    `User Story`; maintenance keeps `Bug` + any `Feature` whose
    `Type of issue` is Tech Debt/Architecture/Security):
    ```
    gh api graphql -f query='query($owner:String!,$repo:String!){
      repository(owner:$owner,name:$repo){
        issues(first:100, states:OPEN){ nodes { number issueType { name } } }
      }
    }' -F owner='{org}' -F repo='{repo}' \
      --jq '[.data.repository.issues.nodes[] | {number, type: .issueType.name}]'
    ```
    (Paginate if the open backlog exceeds 100.)
  - **Not type-capable** → kind is the `type-*` label, exactly as before:
    `feature` keeps `type-story`; `maintenance` keeps `type-bug` /
    `type-security` / `type-arch` / `type-debt`.

**Sort** the survivors by priority label (critical → high → medium → low,
per the label map) then ascending issue number. Priority is dual-tracked
(label + `Priority` field), so the sort stays a cheap label read — no
per-issue field fetch.

If the list is empty, skip to **Step 4** (lazy auto-ready).

## 3. Claim-first selection with lazy validation

Walk the sorted list from the top. For each candidate:

1. **Acquire** it with `templates/claim-procedure.md` (**Acquire**, target
   `issue-{number}`). Acquire wins the atomic ref and applies the
   `status-in-progress` + `@me` markers.
   - **Claim lost** → another agent took it. Make no changes; move to the
     next candidate.
2. **Validate the claimed issue** (only this one — never the whole list):
   - **Dependencies.** Parse the body for `Depends on #N`, `Blocked by #N`,
     `After #N`, `Requires #N`, and `#N` references in a `## Dependencies`
     section, keeping only markers whose `N` is purely numeric — discard
     anything else (e.g. `#TBD`); never pass it to `gh`. For each (at most
     5; if more than 5, treat as a meta-issue → unresolved), check state:
     ```
     gh issue view {N} --repo {org}/{repo} --json state --jq '.state'
     ```
     If **any** is `OPEN`, the dependencies are unresolved. If the view
     exits non-zero (deleted, transferred, or no access), do not surface
     the raw `gh` error — report "dependency #N not found or inaccessible
     — treating story as blocked" and count it as unresolved.
   - **Already resolved.** Check whether a **merged** PR already closes it,
     using GitHub's own `closingIssuesReferences` parse — the authoritative
     signal (same as `templates/sibling-pr-lookup.md`), not a free-text body
     search, which misfires and misses non-default-base merges:
     ```
     gh api graphql -f owner='{org}' -f repo='{repo}' -f query='
     query($owner:String!, $repo:String!) {
       repository(owner:$owner, name:$repo) {
         pullRequests(states: MERGED, first: 100,
                      orderBy: {field: CREATED_AT, direction: ASC}) {
           nodes { number closingIssuesReferences(first: 10) { nodes { number } } }
         }
       }
     }' --jq "[.data.repository.pullRequests.nodes[]
               | select(any(.closingIssuesReferences.nodes[]?; .number == {number}))]
               | .[0].number"
     ```
3. **Act on the verdict:**
   - **Unresolved dependencies** → the issue is genuinely blocked. Move it
     to `status-blocked` (remove `status-in-progress`, unassign), comment
     why, **release the claim** (`templates/claim-procedure.md`
     **Release**), and continue to the next candidate. It leaves the ready
     pool until its deps close; Step 4 restores it later.
     ```
     gh issue edit {number} --repo {org}/{repo} --remove-assignee @me \
       --remove-label "{status_in_progress_label}" --add-label "{status_blocked_label}"
     gh issue comment {number} --repo {org}/{repo} --body "Blocked — open dependency(ies): {#N list}. Returned to blocked until they close."
     git push origin :refs/claims/issue-{number}
     rm -f .claude/claim-issue-{number}.sha
     ```
   - **Already resolved by a merged PR** → close it, **move its board item to
     Done** (`col-done`, best-effort — skip silently if no board is
     configured, per `templates/board-resolution.md`), **release the claim**,
     and continue. No prompt — an already-finished story is closed and the
     walk moves to the next candidate:
     ```
     gh issue close {number} --repo {org}/{repo} --comment "Closing — already resolved by #{pr_number}."
     # then move {number} to col-done per templates/board-resolution.md Step 5
     git push origin :refs/claims/issue-{number}
     rm -f .claude/claim-issue-{number}.sha
     ```
   - **Valid** → you hold the claim and the `status-in-progress` marker.
     **This is the selected story.** Return it to the caller (which moves
     the board to In Progress, branches, etc.). Do not validate any
     further candidates.

If the walk exhausts every candidate without a valid claim, go to Step 4.

## 4. Lazy auto-ready (only when the pool is empty)

Read `templates/story-selection-auto-ready.md` now and follow Step 4
there. That file is kept separate so its contents are not in context on
the common pick path — load it only when you reach this point.
