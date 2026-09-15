# Issue fields and stages

> **Not read at runtime.** The data lives in `synergy/scripts/wf_core.py`, where the tests cover it. This page says what each field and stage is for. Design rationale: [`rationale/default-labels-rationale.md`](rationale/default-labels-rationale.md).

## What labels decide: nothing

An issue's state, priority, size and owner are **structured fields**, and a label is none of those things. Two records of one fact drift the moment anyone edits either, and the drift is silent: the picker preferring one issue over another on a `priority-high` somebody set months ago, while the `Priority` field said Low.

So the workflow puts no label on an issue. The only labels it applies are the review-state labels on a pull request, described in `synergy/skills/pr-review/references/review-workflow.md` and created by `wf labels-ensure`. The four questions labels used to answer are answered once each:

| Question | Where the answer lives | Who reads it |
|----------|------------------------|--------------|
| What state is this in? | the org's `Stage` field | `pick`, `candidates`, `unblock`, every stage write |
| How urgent is it? | the org's `Priority` field | the pool's sort order |
| How big is it? | the org's `Effort` field | `--max-effort`, and the tie-break inside a priority band |
| Who has to do it? | the org's `Ownership` field | whether a code agent may pick it up at all |

Removing a label is the migration, not a cleanup after it: `wf issue-apply` strips any retired label off every issue it writes, `wf config-audit` reports a label map that still claims one (`label-deprecated`), and `wf issue-audit` proposes the field values an old issue is missing, which `wf issue-apply` then writes. The labels themselves are left alone in the repository, because deleting one removes it from every issue that ever carried it.

## Issue types and field values

When the target org has **native GitHub issue types** and **org issue fields** configured, the workflow uses them as the classification and metadata.

`pick` reads them too, not just writes them: the pool is ordered by the org's `Priority` field, sized by its `Effort` field, routed by its `Ownership` field, and a `Feature` counts as maintenance work only when its `Classification` says so. None of them has a label fallback. An issue with no `Priority` sorts last and is named; an issue with no `Ownership` is not offered to a code agent at all; an untyped issue is left out of a `feature` or `maintenance` pool and named, and an org with no native types cannot run those modes (`--mode story` still works).

The purpose→value maps live as Python data in `scripts/wf_core.py`:

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
| Stage purpose key → option name | `STAGE_NAMES` |

To see what a specific org actually has enabled, run `wf org-capabilities`. It reports the enabled native types, every issue field with its option ids, which purpose keys resolve against this org, and which do not. It caches to `.claude/issue-fields-cache.json`; `--refresh` re-queries.

A project overrides any **field name** in `ClaudeProject.md` → `## Issue Types & Fields`, resolved through `wf_core.resolve_field_name()`. A project does not override the value maps; those are the workflow's own vocabulary.

**Three of these fields are required and two are not**, and the line between them is whether a decision reads the value. `Priority`, `Effort` and `Ownership` are the picker's whole input, so an org that has not defined one is a `CRITICAL field-absent` finding and a spec that leaves one empty is refused before anything is written. `Classification` and `Origin` are worth having and not worth refusing an issue over: a create that leaves one unset gets a comment on the issue naming it, and the run carries on.

### When the org has more than the five default types

`NATIVE_TYPE_MAP` is written for GitHub's five defaults, where nothing expresses tech debt. An org that adds its own types records the better answer in `wf_core.NATIVE_TYPE_PREFERENCES`, and `native_type_for(kind, type_map)` is the single place the choice is made. `NATIVE_MAINTENANCE_TYPES` decides what `execute mode=maintenance` may pick, so a type outside that set is invisible to the picker.

## Stages

**An issue's `Stage` field is its state.** There is no second record to keep in step, and no board column is read: every command that touches an issue writes the stage its own state names. A blank `Stage` means available, the same as `Backlog`.

Stages are resolved by **purpose key**: the field name through `field-stage` in `ClaudeProject.md` → `## Issue Types & Fields` (default `Stage`), and the option by its default name below.

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

**Which command writes which stage:**

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
