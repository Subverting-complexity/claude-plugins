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
`repo`, the label map, `agent-gating`, `ready-gate`, and project-board
settings. Plus the caller's `mode` (`story` / `feature` / `maintenance`)
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
- **`none`** — no readiness gate at all. Any open unassigned issue is
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
  gh api repos/{org}/{repo}/milestones --jq 'sort_by(.due_on) | map(select(.open_issues > 0)) | .[0].title'
  ```
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
     section. For each (at most 5; if more than 5, treat as a meta-issue →
     unresolved), check state:
     ```
     gh issue view {N} --repo {org}/{repo} --json state --jq '.state'
     ```
     If **any** is `OPEN`, the dependencies are unresolved.
   - **Already resolved.** Check whether a merged PR already closes it:
     ```
     gh pr list --repo {org}/{repo} --search "closes #{number} OR fixes #{number}" --state merged --json number --jq '.[0].number'
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
   - **Already resolved by a merged PR** → close it, **release the claim**,
     and continue:
     ```
     gh issue close {number} --repo {org}/{repo} --comment "Closing — already resolved by #{pr_number}."
     git push origin :refs/claims/issue-{number}
     rm -f .claude/claim-issue-{number}.sha
     ```
   - **Valid** → you hold the claim and the `status-in-progress` marker.
     **This is the selected story.** Return it to the caller (which moves
     the board to In Progress, branches, etc.). Do not validate any
     further candidates.

If the walk exhausts every candidate without a valid claim, go to Step 4.

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
