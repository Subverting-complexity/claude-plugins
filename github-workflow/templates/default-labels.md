# Label Resolver & Default Inventory

This file is the **single source of truth** for how every skill and command resolves a label name, and the default inventory created at setup. For design rationale, see `docs/rationale/default-labels-rationale.md` (not read at runtime).

## The single resolution path

> **You usually do not need to open this file.** Every workflow command auto-loads the full `ClaudeProject.md` (label map included) before it runs. When that map is in context — the normal case — resolve purpose keys directly from it and do **not** read this file. Open it only as a fallback: a purpose key is missing from the project map, or you need the default inventory / colours / native-type / stage tables below.

A label is identified by its **purpose key**, never by a hardcoded concrete name. Purpose keys are stable; concrete names are project-configurable. To get the concrete name for one: look it up in the `ClaudeProject.md` label map (or, for a **review-state purpose**, the `review.config.md` Labels table, matched by the Purpose column and never by guessing a prefix); use that name if it is configured; use the default from the inventory below if it is not.

**Invariant — apply == filter.** Because producers and consumers both start from the same purpose key and run the same steps, a label written by one skill is the identical string another skill filters on. Do not re-derive names independently, do not hardcode a concrete name in prose or a filter, and do not assume a prefix.

## Creating and applying a label

The complete inventory below is created once at setup (`/github-workflow:setup`, step 5b). At runtime a skill may only **create a missing label as a guarded fallback** — never `--force`-overwrite one, which churns its colour and description. Never suppress the create's errors with `|| true`; capture stderr and ignore only "already exists" (a benign race with another agent):

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

Surface any other failure — especially a permission denial — with the real stderr: an explicitly best-effort caller warns and continues; every other caller stops.

**Do not read a label back after applying it.** `gh ... edit --add-label X` fails loudly when `X` does not exist and never drops one silently, so the exit status *is* the presence signal. The one exception is a non-zero exit citing an unknown label: create it with the guarded pattern above, retry the edit once, and then read back to confirm.

## What labels decide: nothing

An issue's state, priority, size and owner are **structured fields**, and a label is none of those things. Two records of one fact drift the moment anyone edits either, and the drift is silent — the picker preferring one issue over another on a `priority-high` somebody set months ago, while the `Priority` field said Low.

So there is no `status-*` label, no `priority-*` label, no `scope-*` label and no `type-*` label in this inventory. The four questions they used to answer are answered once each:

| Question | Where the answer lives | Who reads it |
|----------|------------------------|--------------|
| What state is this in? | the org's `Stage` field | `pick`, `candidates`, `unblock`, every stage write |
| How urgent is it? | the org's `Priority` field | the pool's sort order |
| How big is it? | the org's `Effort` field | `--max-effort`, and the tie-break inside a priority band |
| Who has to do it? | the org's `Ownership` field | whether a code agent may pick it up at all |

Removing the label is the migration, not a cleanup after it: `wf issue-apply` strips any retired label off every issue it writes, `wf config-audit` reports a label map that still claims one (`label-deprecated`), and `wf issue-audit` proposes the field values an old issue is missing, which `wf issue-apply` then writes. The labels themselves are left alone in the repository — deleting one removes it from every issue that ever carried it, which is history nobody asked to lose.

## Issue Types & Field Values

When the target org has **native GitHub issue types** and **org issue fields** configured, the workflow uses them as the first-class classification and metadata.

`pick` reads them too, not just writes them: the pool is ordered by the org's `Priority` field, sized by its `Effort` field, routed by its `Ownership` field, and a `Feature` counts as maintenance work only when its `Classification` says so. None of them has a label fallback. An issue with no `Priority` sorts last and is named; an issue with no `Ownership` is not offered to a code agent at all; an untyped issue is left out of a `feature` or `maintenance` pool and named, and an org with no native types cannot run those modes (`--mode story` still works).

**The purpose→value maps are not in this file.** They live as Python data in `scripts/wf_core.py`, and the tooling applies them directly:

| Map | Constant in `wf_core.py` |
|-----|--------------------------|
| Workflow kind → native type and `Classification` | `NATIVE_TYPE_MAP` |
| Every valid `Classification` option | `CLASSIFICATION_OPTIONS` |
| Purpose key → field name, and its data type | `FIELD_NAME_DEFAULTS`, `FIELD_DATA_TYPES` |
| The three fields every issue must carry | `MANDATORY_FIELD_KEYS` |
| The two the workflow fills in and does not require | `OPTIONAL_FIELD_KEYS` |
| Scope → `Ownership` option | `OWNERSHIP_FIELD_OPTIONS` |
| Legacy `priority-*` label → `Priority` option (backfill only) | `PRIORITY_FIELD_OPTIONS` |
| `Priority` option → pick order | `PRIORITY_FIELD_RANK` |
| Size estimate → `Effort` option | `EFFORT_FIELD_OPTIONS` |
| Creating command → `Origin` option | `ORIGIN_FIELD_OPTIONS` |

Data in prose could not be validated and drifted unnoticed, so do not restate any of it here. Add a value by editing `wf_core.py`, where the tests cover it.

To see what a specific org actually has enabled, resolve it rather than assuming:

    wf org-capabilities

That reports the enabled native types, every issue field with its option ids, which purpose keys resolve against this org, and which do not. It caches to `.claude/issue-fields-cache.json`; `--refresh` re-queries.

A project overrides any **field name** in `ClaudeProject.md` → `## Issue Types & Fields`, resolved through `wf_core.resolve_field_name()` — the same project-map-then-default path labels use. A project does not override the value maps; those are the workflow's own vocabulary.

**Three of these fields are required and two are not**, and the line between them is whether a decision reads the value. `Priority`, `Effort` and `Ownership` are the picker's whole input, so an org that has not defined one is a `CRITICAL field-absent` finding and a spec that leaves one empty is refused before anything is written. `Classification` and `Origin` are worth having and not worth refusing an issue over: a create that leaves one unset gets a comment on the issue naming it, and the run carries on.

### When the org has more than the five default types

`NATIVE_TYPE_MAP` is written for GitHub's five defaults, where nothing expresses tech debt. An org that adds its own types records the better answer in `wf_core.NATIVE_TYPE_PREFERENCES`, and `native_type_for(kind, type_map)` is the single place the choice is made. Adding one has a consequence worth knowing: `NATIVE_MAINTENANCE_TYPES` decides what `execute mode=maintenance` may pick, so a type outside that set is invisible to the picker. Both are covered in `docs/rationale/default-labels-rationale.md`.

### Choosing a `Classification`

`NATIVE_TYPE_MAP` gives each workflow kind a default. It is the "by nature" answer, not the only valid one, and a better one is a judgement the map cannot make:

- For a bug, prefer **Regression** when something previously worked and broke, or **Performance** when the defect is speed or memory.
- For a feature, prefer **Enhancement** when it improves something that already exists, **Integration** when the work is connecting to an external system or third-party service, **Documentation** when it tracks docs only, or **Performance** when speed is the point.

## Provenance marker

`claude-authored` marks who built it, not what state it is in. It is the only label the issue workflow applies, and it decides nothing.

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `claude-authored` | `claude-authored` | `5319E7` | Built or created by Claude (issues and PRs) |

## Stages

**An issue's `Stage` field is its state.** There is no second record to keep in step, and no board column is read: every command that touches an issue writes the stage its own state names. A blank `Stage` means available, the same as `Backlog`.

Stages are resolved by **purpose key**: the field name through `field-stage` in `ClaudeProject.md` → `## Issue Types & Fields` (default `Stage`), and the option by its default name below. Design rationale: `docs/rationale/default-labels-rationale.md`.

| Purpose key         | Stage              | What it means |
|---------------------|--------------------|---------------|
| `stage-backlog`     | `Backlog` (or blank) | available: the pick pool |
| `stage-refinement`  | `Needs refinement` | not ready to start; needs a refinement session |
| `stage-in-progress` | `In Progress`      | an agent is working it now |
| `stage-in-review`   | `In Review`        | a pull request is open against it |
| `stage-attention`   | `Needs attention`  | a run failed or timed out; a person has to look |
| `stage-blocked`     | `Blocked`          | waiting on something; the plugin releases it only when every blocked-by edge has closed |
| `stage-non-code`    | `Non-code`         | a browser agent or a person owns it; no sweep ever releases it |
| `stage-parked`      | `Parked`           | deliberately set aside; will resume |
| `stage-done`        | `Done`             | the issue is closed |

**Which command writes which stage (the single mapping every command follows):**

| Stage | Command(s) |
|-------|------------|
| In Progress (`stage-in-progress`) | `wf pick --checkout`, `wf claim --issue` |
| In Review (`stage-in-review`)  | `wf handoff`, when the pull request opens |
| Blocked (`stage-blocked`)      | `wf pick` (an open blocked-by edge), `wf issue-apply` (an open blocked-by edge), block-story |
| Non-code (`stage-non-code`)    | `wf issue-apply`, `wf unblock` (`Ownership` is `Human` or `Browser agent`) |
| Needs refinement (`stage-refinement`) | `wf issue-apply` (`"state": "refinement"` on the entry), feature-discovery (a deferred story), execute (a story too thin to build) |
| Parked (`stage-parked`)        | a person, or `wf issue-apply` (`"state": "parked"` on the entry) |
| Needs attention (`stage-attention`) | execute and bulk-execute, when a run gives up |
| Backlog (`stage-backlog`)      | `wf issue-apply` (`"state": "backlog"`), `wf unblock` (every blocked-by edge closed), a reverted claim |
| Done (`stage-done`)            | `wf post-merge` (at merge), `wf pick` (closing an issue already resolved) |

`issue-apply` writes only an issue whose `Stage` is blank, `Backlog`, `Blocked` or `Non-code`, unless the entry names a `"state"`. Any other stage is kept (`stage_kept`), so an update never drags in-flight work back into the pool.

**`Blocked` with no blocked-by edge was set by a person**, and the plugin never changes it. `wf unblock` only releases a `Blocked` issue that has edges, and only once every one of them is closed.

**The `Stage` field is required, with all nine options.** Preflight reports an org with no `Stage` field as `CRITICAL stage-absent`, and a `Stage` missing an option as `CRITICAL stage-options`, naming it. A project board is not required: boards are views for people, grouped by `Stage`, and GitHub's "Auto-add to project" workflow keeps cards on them, and the scheduled `wf board-sync` adds any it missed. Agents never move cards.

## Review State Labels

These control the PR review workflow and are used only on the **review** path (`code-review`, `execute` PR labelling), never the claim/selection path. Resolve them through the Labels table in `review.config.md` (matched by purpose key), falling back to the defaults below — `wf_core.REVIEW_DEFAULT_LABELS` is the same list, so `wf` resolves them the same way without a lookup here.

State labels are mutually exclusive — exactly one per PR. A PR enters the machine at `needs-review` the moment it is opened, so a new PR is never unlabelled, and the reviewer moves it from there.

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
