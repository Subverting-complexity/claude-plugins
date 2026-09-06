# Label Resolver & Default Inventory

This file is the **single source of truth** for how every skill and
command resolves a label name, and the default inventory created at
setup. For design rationale, see `docs/rationale/default-labels-rationale.md` (not
read at runtime).

## Purpose keys

A label is identified by its **purpose key**, never by a hardcoded
concrete name. Purpose keys are stable; concrete names are
project-configurable.

## The single resolution path

> **You usually do not need to open this file.** Every workflow command
> auto-loads the full `ClaudeProject.md` (label map included) before it
> runs. When that map is in context — the normal case — resolve purpose
> keys directly from it and do **not** read this file. Open it only as a
> fallback: a purpose key is missing from the project map, or you need
> the default inventory / colours / native-type / board-column tables
> below.

When any skill needs the concrete name for a purpose key:

1. **Workflow purposes** (typing, priority, status, claude markers) —
   look up the purpose in the `ClaudeProject.md` label map.
   **Review-state purposes** (the PR review mutex) — the
   `review.config.md` Labels table, matched **by purpose** (the Purpose
   column), never by guessing a prefix.
2. If the project config defines a name for that purpose, use it.
3. If not configured, use the default name from the inventory below.

**Invariant — apply == filter.** Because producers and consumers both
start from the same purpose key and run the same three steps, a claim
label written by one skill is the identical string another skill filters
on. Do not re-derive names independently, do not hardcode a concrete
name in prose or a filter, and do not assume a prefix — always resolve
the purpose key through this path.

## Pre-creation contract

The complete inventory below is created once at setup
(`/github-workflow:setup`, step 5b). Skills must **not**
`--force`-overwrite labels at runtime — that causes colour/description
churn. A skill may only **create a missing label as a guarded fallback**:
check existence, create without `--force` if absent, warn that setup
should have created it, then proceed.

Guarded create-if-missing pattern. Never suppress the create's errors
with `|| true` (it swallows permission failures); capture stderr and
ignore only "already exists" (a benign race with another agent):

```
# resolve <name> from the purpose key via the path above, then:
existing=$(gh label list --repo {org}/{repo} --json name --jq '.[].name')
case "$existing" in
  *"<name>"*) : ;;  # already present — leave its metadata untouched
  *) err=$(gh label create "<name>" --repo {org}/{repo} \
       --description "<description>" --color "<color>" 2>&1) \
     || case "$err" in
          *already?exists*) : ;;  # benign — created concurrently
          *) echo "label create failed: $err" >&2 ;;  # surface the real error
        esac ;;
esac
```

Surface any other failure — especially a permission denial — with the
real stderr, never swallowed: an explicitly best-effort caller warns and
continues; every other caller stops.

## Label read-back policy

`gh ... edit --add-label X` fails loudly — non-zero exit, "could not add
label" — when `X` does not exist. It never drops a label silently. So the
edit's own exit status *is* the presence signal, and this is the policy
every command that applies a label follows:

- **Exit 0** → the label is set. Done. **Do not read back.**
- **Non-zero, citing an unknown or missing label** → the label was never
  created at setup. Create it with the guarded pattern above (no
  `--force`), retry the edit once, and *then* read the labels back to
  confirm (`gh issue view {number} --json labels --jq '[.labels[].name]'`,
  or `gh pr view` for a PR).

That retried case is the **only** one that reads. A read-back after a
clean apply is a round trip that can only ever confirm what the exit code
already said.

## Workflow Labels

These control prioritization and agent gating. Resolved via the label
map in `ClaudeProject.md`; defaults below.

There is deliberately no `type-*` label here: the **native issue type** and
the org's `Classification` field say what kind of work an issue is. `wf pick`
filters on the type, `wf issue-apply` strips a `type-*` label and a
`[BUG]`-style title prefix off every issue it writes, and `wf config-audit`
reports a label map that still maps one (`type-label-deprecated`).

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `priority-critical` | `priority-critical` | `B60205` | Critical priority |
| `priority-high` | `priority-high` | `D93F0B` | High priority |
| `priority-medium` | `priority-medium` | `FBCA04` | Medium priority |
| `priority-low` | `priority-low` | `0E8A16` | Low priority |
| `claude-ready` | `claude-ready` | `1D76DB` | Approved for agent work |

## Issue Types & Field Values

When the target org has **native GitHub issue types** and **org issue
fields** configured, the workflow uses them as the first-class
classification and metadata.

`pick` reads them too, not just writes them: the pool is ordered by the
org's `Priority` field and a `Feature` counts as maintenance work only when
its `Classification` says so. The `priority-*` labels are the fallback for
issues the `Priority` field was never set on. The **type** has no fallback:
an untyped issue is left out of a `feature` or `maintenance` pool and named,
and an org with no native types cannot run those modes (`--mode story` still
works).

**The purpose→value maps are not in this file.** They live as Python data
in `scripts/wf_core.py`, and the tooling applies them directly:

| Map | Constant in `wf_core.py` |
|-----|--------------------------|
| Workflow kind → native type and `Classification` | `NATIVE_TYPE_MAP` |
| Every valid `Classification` option | `CLASSIFICATION_OPTIONS` |
| Purpose key → field name, and its data type | `FIELD_NAME_DEFAULTS`, `FIELD_DATA_TYPES` |
| The four fields set on every issue | `MANDATORY_FIELD_KEYS` |
| `priority-*` label → `Priority` option | `PRIORITY_FIELD_OPTIONS` |
| `Priority` option → pick order | `PRIORITY_FIELD_RANK` |
| Size estimate → `Effort` option | `EFFORT_FIELD_OPTIONS` |
| Creating command → `Origin` option | `ORIGIN_FIELD_OPTIONS` |

They were tables here until the mechanism moved into `wf`. Data in prose
could not be validated and drifted unnoticed — 82 issues in one consuming
repo had 7 native types between them and no field values at all. Restating
any of it here would recreate that. Add a value by editing `wf_core.py`,
where the tests cover it.

To see what a specific org actually has enabled, resolve it rather than
assuming:

    wf org-capabilities

That reports the enabled native types, every issue field with its option
ids, which purpose keys resolve against this org, and which do not. It
caches to `.claude/issue-fields-cache.json`; `--refresh` re-queries.

A project overrides any **field name** in `ClaudeProject.md` →
`## Issue Types & Fields`, resolved through `wf_core.resolve_field_name()`
— the same project-map-then-default path labels use. A project does not
override the value maps; those are the workflow's own vocabulary.

### When the org has more than the five default types

`NATIVE_TYPE_MAP` is written for GitHub's five defaults, where nothing can
express tech debt and `Feature` is the least wrong answer. An org may add
its own types, and `wf_core.NATIVE_TYPE_PREFERENCES` is where a better
answer is recorded: `tech debt` and `chore` become `Chore` on an org that
has that type, and fall back to the map's `Feature` on one that does not.
`org-capabilities` reports the enabled types, and `native_type_for(kind,
type_map)` is the single place the choice is made, so the audit and the
backfill cannot disagree about it.

Adding a preference has one easily missed consequence:
`NATIVE_MAINTENANCE_TYPES` decides what `execute mode=maintenance` may pick,
and a type outside that set is invisible to the picker — so a backlog that
starts typing its debt `Chore` empties its own maintenance pool unless
`Chore` is there too. `architecture` has no preference on purpose: the one
org measured had already typed every `[ARCH]` issue `Feature`.

### Choosing a `Classification`

`NATIVE_TYPE_MAP` gives each workflow kind a default. It is the "by nature"
answer, not the only valid one, and a better one is a judgement the map
cannot make:

- For a bug, prefer **Regression** when something previously worked and
  broke, or **Performance** when the defect is speed or memory.
- For a feature, prefer **Enhancement** when it improves something that
  already exists, **Integration** when the work is connecting to an
  external system or third-party service, **Documentation** when it
  tracks docs only, or **Performance** when speed is the point.

## Issue Lifecycle State Labels

Every issue always carries exactly one lifecycle state label — mutually
exclusive; remove the old label when applying the new one. Resolved via
the label map in `ClaudeProject.md`; defaults below.

| Purpose key | Default Name | Color | Description | Applied by |
|-------------|-------------|-------|-------------|------------|
| `status-ready` | `status-ready` | `0E8A16` | Eligible for pickup, no unresolved dependencies | setup / execute (unblock) |
| `needs-refinement` | `needs-refinement` | `D4C5F9` | Needs a refinement session before pickup | feature-discovery / report-issue |
| `status-in-progress` | `status-in-progress` | `1D76DB` | An agent is actively working this issue now | execute |
| `status-parked` | `status-parked` | `C5DEF5` | Deliberately set aside by a human, will resume | human / update via park |
| `status-blocked` | `status-blocked` | `B60205` | Cannot proceed — external or dependency blocker | block-story |
| `status-in-review` | `status-in-review` | `FBCA04` | PR is open, awaiting review / merge | execute |
| `status-needs-attention` | `status-needs-attention` | `D93F0B` | A run failed or errored — needs human intervention | execute (error/timeout) |

For the lifecycle transition diagram and dual-tracking rationale, see
`docs/rationale/default-labels-rationale.md`.

### Provenance marker (not a lifecycle state)

`claude-authored` marks who built it, not what state it is in — it
coexists with any lifecycle state.

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `claude-authored` | `claude-authored` | `5319E7` | Built or created by Claude (issues and PRs) |

## Board Columns

The board-side mirror of the issue lifecycle. Columns are resolved by
**purpose key** through the same path as labels: read from
`ClaudeProject.md` → `## Project Board` → `### Status Options`; fall
back to the default name below. Board moves are best-effort (no board →
no-op; configured board + failed move → reported, never fatal — `wf
board-move` writes them). Labels remain authoritative; the board
mirrors them. Design rationale: `docs/rationale/default-labels-rationale.md`.

| Purpose key      | Default Name  | Option color | Mirrors lifecycle label(s) |
|------------------|---------------|--------------|----------------------------|
| `col-backlog`    | `Backlog`     | GRAY         | `needs-refinement`, new issues |
| `col-ready`      | `Ready`       | GREEN        | `status-ready` |
| `col-in-progress`| `In Progress` | BLUE         | `status-in-progress`, `status-needs-attention` |
| `col-in-review`  | `In Review`   | YELLOW       | `status-in-review` |
| `col-blocked`    | `Blocked`     | RED          | `status-blocked`, `status-parked` |
| `col-done`       | `Done`        | GRAY         | (issue closed) |

> Option `color` values come from the GitHub enum
> `ProjectV2SingleSelectFieldOptionColor`:
> `GRAY`, `BLUE`, `GREEN`, `YELLOW`, `ORANGE`, `RED`, `PINK`, `PURPLE`.
> These name the *board* option color and are distinct from the hex label
> colors above.

**Label ⇄ column pairing (the single mapping every command follows):**

| Lifecycle transition (label set)         | Board column moved to        | Command(s) |
|------------------------------------------|------------------------------|------------|
| `status-in-progress`                     | In Progress (`col-in-progress`) | execute |
| `status-in-review`                       | In Review (`col-in-review`)  | execute |
| `status-blocked`                         | Blocked (`col-blocked`)      | block-story |
| `status-ready` (unblock)                 | Ready (`col-ready`)          | execute |
| `needs-refinement` / `status-ready` (new issue) | Backlog / Ready             | report-issue (best-effort placement) |
| issue **closed** (resolved / merged)     | Done (`col-done`)            | `wf pick` (already-resolved), `wf post-merge` (after merge), code-review auto-merge |

The Done move has no lifecycle *label* (a closed issue carries none — the
GitHub closed state is authoritative); the commands above mirror the board
to `col-done` so a finished story leaves the In Review column. Best-effort,
like every board move: a no-op when no board is configured.

When a board is configured, the three active columns — In Progress,
In Review, Blocked — must exist (preflight emits
`CRITICAL board-columns-incomplete` if any is missing; setup creates
them). The Ready column is additionally required only under a
`board-column`/`both` ready-gate.

## Review State Labels

These control the PR review workflow and are used only on the **review**
path (`code-review`, `execute` PR labelling), never the claim/selection
path. Resolve them through the Labels table in `review.config.md` (matched
by purpose key), falling back to the defaults below —
`wf_core.REVIEW_DEFAULT_LABELS` is the same list, so `wf` resolves them the
same way without a lookup here.

State labels are mutually exclusive — exactly one per PR. A PR enters the
machine at `needs-review` the moment it is opened, so a new PR is never
unlabelled, and the reviewer moves it from there.

The colours and descriptions are what setup creates the labels with:

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `needs-review` | `review-needs-review` | `C2E0C6` | Open PR awaiting its first review |
| `reviewing` | `review-reviewing` | `0E8A16` | Review in progress |
| `approved` | `review-approved` | `1D76DB` | Ready for human merge |
| `changes-requested` | `review-changes-requested` | `E4E669` | Issues need human action |
| `needs-discussion` | `review-needs-discussion` | `D93F0B` | Architectural questions |
| `needs-re-review` | `review-needs-re-review` | `FBCA04` | New commits since last review |
| `failed` | `review-failed` | `B60205` | Review could not complete |
| `updating` | `review-updating` | `0E8A16` | Builder addressing feedback |
| `fixes-applied` | `review-fixes-applied` | `5319E7` | Claude pushed fix commits (sticky) |
