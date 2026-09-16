# `wf` — programmatic workflow picker

`wf` collapses the mechanical "select the next story, claim it, validate it" loop into a single process call that returns one already-claimed work item as JSON. It exists so the workflow commands don't have to drive a dozen sequential `gh` round-trips through the model on the hot path.

The selection rules are **not** duplicated here: the pure decision logic lives in the `wf_core_*` modules behind [`wf_core.py`](wf_core.py) (priority sort, mode/refinement/gating filters, dependency parsing, branch naming), which is the single canonical, offline-testable encoding of what the `templates/` describe in prose. The offline suite (`tests/test_decision_logic.py`) imports `wf_core` directly, so the rules the CLI runs are the rules the tests check, with no second copy to drift. The `wf_*` modules are the I/O shell that talks to `gh`/`git` around that core, and [`wf.py`](wf.py) is its entry point.

## Module layout

Code is split by concern into flat modules in this directory. Two rules hold the split together: no `wf_core_*` module runs a subprocess, reads a file or calls GitHub, and no `wf_*` shell module holds a decision rule that the tests would need a network to check.

`wf.py` builds the argument parser, dispatches to a subcommand and re-exports every name the shell modules define, so `wf.X` keeps working. It also passes any assignment to `wf.X` on to each shell module that binds `X`, which is what lets the tests replace `wf.run` or `wf.gh_graphql` once for every caller. `wf_core.py` re-exports every name the `wf_core_*` modules define in the same way. New code goes in the module whose concern it belongs to, never in either facade.

| Module | Responsibility | Lines |
|--------|----------------|-------|
| `wf.py` | Entry point: argument parser, dispatch, re-exports | 426 |
| `wf_io.py` | Exit codes, the stdout JSON contract, the `gh`/`git` subprocess runner | 142 |
| `wf_config.py` | Repo root (asked of git once per working directory), `ClaudeProject.md` parsing, the config cache, `config` | 260 |
| `wf_capabilities.py` | Org issue types, fields and type pins (one request for preflight), repo labels, the capability cache, `org-capabilities` | 498 |
| `wf_issue_io.py` | Reading, writing and verifying single issues; batched mutations | 422 |
| `wf_stage.py` | `Stage` writes, the start date, branch checkout, `stage-set` | 213 |
| `wf_candidates.py` | Open issues by stage, their facets, the candidate list, the concurrent pool read | 540 |
| `wf_claim.py` | Claim refs and markers, batched release, `claim`, `claim-release`, `claim-reap` | 463 |
| `wf_deps.py` | Blocked-by edges, already-resolved issues, marking blocked | 268 |
| `wf_unblock.py` | The unblock sweep, `unblock` | 288 |
| `wf_pick.py` | The claim and validate walk, container trees, the prerequisite redirect, `pick`, `candidates` | 933 |
| `wf_plan.py` | Planning and claiming a bulk set, `plan-set`, `drop-story`, `bulk-mark` | 391 |
| `wf_bulk_build.py` | Scheduling a bulk wave from the plan and integrating parallel builders' branches, `bulk-schedule`, `bulk-integrate` | 227 |
| `wf_post_merge.py` | Closing finished containers, batched settle reads and writes, `post-merge` | 397 |
| `wf_review.py` | PR pools and review labels, `update-next`, `review-next`, `review-finish`, `labels-ensure`, `sibling-pr`, `handoff` | 411 |
| `wf_issue_apply.py` | `issue-apply` | 777 |
| `wf_issue_audit.py` | `issue-audit` | 166 |
| `wf_preflight.py` | `config-audit` and `preflight`, including `--fix` | 659 |
| `wf_board_sync.py` | `board-sync` | 287 |
| `wf_core.py` | Facade: re-exports the rules below | 50 |
| `wf_core_findings.py` | The finding record and the helpers findings are worded with | 46 |
| `wf_core_fields.py` | Label resolution, native issue types, field vocabularies and ranks | 419 |
| `wf_core_stage.py` | `Stage` names, work scope, which stage an issue belongs in, stage drift targets | 452 |
| `wf_core_select.py` | Candidate filter and sort, native type filtering, backlog mode | 308 |
| `wf_core_pool.py` | The verdict on every open issue in the pool, waiting work and inherited priority | 375 |
| `wf_core_refs.py` | Parent parsing, closing references, branch names, dependency edges, unblock verdicts | 268 |
| `wf_core_bulk.py` | Planning a dependency-ordered bulk set and its waves | 453 |
| `wf_core_claims.py` | Sibling PRs that would duplicate a claim, claim reaping | 110 |
| `wf_core_spec.py` | The issue hierarchy, spec validation, value shaping and batching | 562 |
| `wf_core_audit.py` | What an existing issue is missing or contradicts | 344 |
| `wf_core_review.py` | Review-state label names, pools and reconciliation | 192 |
| `wf_core_drift.py` | Finished containers and stage drift findings | 96 |
| `wf_core_preflight.py` | Config sections, label and field drift, instruction files | 584 |
| `wf_core_repair.py` | File-level checks, what `--fix` may repair, editing `ClaudeProject.md` | 307 |
| `wf_core_scratch.py` | Which `.claude/` files are run scratch, the managed `info/exclude` block | 70 |
| `wf_core_schedule.py` | Reading `.claude/plan.md`, which stories in a wave share files, parallel batches | 186 |

## Commands

```bash
# One-time bootstrap: pin a dedicated Python virtualenv (reused thereafter)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" setup

# Can this project be worked on at all? (0 = nothing blocks, 26 = something does)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" preflight

# …and repair what can be repaired without guessing, then re-check
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" preflight --fix

# Claim the next story (Priority field → lowest number → atomic claim), print it
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick

# …also set the issue's Stage to In Progress and create/check out the branch
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --checkout

# Target one specific issue instead of auto-selecting (same claim/validate;
# auto-closes it + sets its Stage to Done if a merged PR already resolved it)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue 42 --checkout

# List the pool without claiming anything
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --limit 0

# …or plan a bulk set: connected stories in build order and waves, blockers
# first, from the pool, named stories (--issue) or an Epic or Feature (--parent);
# --claim claims, assigns and sets In Progress for every story in it
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" plan-set --parent 42 --size 7 --claim

# Split the recorded set's next waves into batches that share no planned file
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" bulk-schedule

# Cherry-pick a wave's parallel builder branches onto the shared branch, push once
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" bulk-integrate --wave 1

# Send a claimed issue back: Stage to Needs refinement, comment, unassign, release
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" refine --issue 42 --body-file .claude/42-body.md

# Delete this run's scratch files under .claude/ (caches and the preflight marker stay)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" scratch-clean

# After merging a PR: close any still-open linked issue and set its Stage to Done,
# close any Epic or Feature above it whose sub-issues are now all closed,
# then release whatever that merge freed
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" post-merge --pr 123

# Release the blocked issues whose dependencies have all closed (--dry-run reports)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" unblock --dry-run

# Claim the next PR of mine that needs review feedback addressed (pr-review)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" update-next --checkout

# Claim the next PR that needs reviewing (pr-review)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-next --checkout

# Emit the parsed config cache (.claude/wf-config.json) from ClaudeProject.md
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config

# Resolve the org's native issue types + issue fields (cached; --refresh re-queries)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" org-capabilities

# Create or update fully classified issues from a spec file
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply spec.json

# …check the spec against the org and report what would change, writing nothing
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply spec.json --dry-run

# Report open issues missing a type, a field value, an owner or a place in the epic tree (writes a backfill spec)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-audit

# …against another repo in the org, newest 50 only, counts only (for CI)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-audit --repo acme/other --limit 50 --quiet

# …and read the parent each body claims, for a backlog that predates spec-created issues
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-audit --parents

# Report configuration and label drift (what preflight runs)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config-audit

# …file-level checks only, no network
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config-audit --offline

# Lock one issue or PR (and advertise it: assignment / reviewing label)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim --issue 42
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim --pr 123 --no-marker

# Let one or more locks go (idempotent)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --issue 42 --pr 123

# Free every claim ref whose work has demonstrably moved on
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-reap --threshold 4 --dry-run

# Set an issue's Stage (best-effort, always exit 0)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" stage-set 42 --stage stage-in-review

# The open PRs that close each issue (duplicate detection), one read for all of them
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr 42 43 --exclude-branch feat/42-thing

# Settle a PR's review-state labels (approved, changes-requested, needs-discussion, needs-re-review)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-finish --pr 123 --verdict needs-re-review

# Hand finished stories to review: label the PR, set each issue to In Review, free claims
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" handoff --pr 123 --issue 42 --issue 43
```

Run from the **target repo root** so the CLI can read `ClaudeProject.md` and the git remote.

## The interpreter: a pinned virtualenv

`wf.sh` / `wf.ps1` resolve which Python runs `wf.py` like this:

1. **A dedicated virtualenv.** It lives under `${CLAUDE_PLUGIN_DATA}/wf-venv` (the plugin's persistent data dir, which survives plugin updates), with `requirements.txt` installed into it. This is the steady state — pinned, isolated, never affected by PATH. `wf.sh setup` creates it explicitly, but so does the first ordinary call that finds none and a usable system Python: it builds the venv in place before running, silently, so most projects never need to run `setup` by hand.
2. **A probed system Python**, only when no venv exists and the auto-bootstrap above could not build one (e.g. no `venv` module, a locked-down filesystem, or a losing race against another concurrent `wf` call already building it) — `python3` verified, then `py -3`, then `python` (the broken Windows `python3` Store shim fails its `--version` probe and is skipped), with a one-line hint to run setup.
3. **Nothing found** → exit 20; the caller falls back to the inline skill.

Probing launches Python, about 420 ms on Windows, so the answer is cached: `wf.sh` writes the kind (`venv` or `base`) and the interpreter's absolute path to `wf-python` under the data dir, and `wf.ps1` to `wf-python-ps1`. A later call trusts it without running anything while that path exists, and a cached system Python gives way as soon as a venv exists. If the cached interpreter will not launch (exit 126 or 127 in bash, command not found in PowerShell), the cache is deleted and the probe runs once. `setup` always rewrites it.

`wf.sh setup` is idempotent: a valid venv is reused, `--force` rebuilds it. If no Python 3 exists it prints the platform install command and stops (exit 20) — or, with the explicit `--install-python` opt-in, installs system Python via winget/brew/apt first. Wire it via `/synergy:setup wf` (or it's offered during full setup, Step 1b).

## Contract

A single JSON object goes to **stdout**; diagnostics go to **stderr**. Every run carries a `status` field and the exit code mirrors it:

| Exit | `status`        | Meaning                                                        |
| ---- | --------------- | -------------------------------------------------------------- |
| 0    | `ok`            | An item was claimed (and checked out, if asked).               |
| 10   | `no-candidates` | The ready pool was empty.                                      |
| 11   | `all-blocked`   | Every candidate was claimed away, blocked, or already resolved.|
| 12   | `needs-refinement` | The next pick is too unclear to build. Nothing was claimed. |
| 20   | `error`         | Environment/auth problem (not a repo, no `gh`, no config).     |
| 21   | `no-capabilities` | The org reports no issue types and no fields, or refused to say. |
| 22   | `spec-invalid`  | An `issue-apply` spec is wrong. Nothing was written.           |
| 23   | `verify-failed` | A write was accepted but does not read back. Issues exist.     |
| 24   | `partial`       | Some entries applied, some failed. Re-run to finish.           |
| 25   | `gaps`          | `issue-audit` found issues missing metadata. Nothing written.  |
| 26   | `drift`         | `config-audit` found a configuration problem that breaks work. |
| 27   | `lost`          | `claim` — another agent holds this issue or PR. Change nothing.  |
| 30   | `unsupported`   | Path not in the CLI yet — caller falls back to the skill.      |

Mutations to the **winning** issue (claim, assign, the `In Progress` stage) are silent; mutations to **other** issues (setting a dependency-blocked one to `Blocked`, closing one already resolved by a merged PR, which also sets its stage to `Done`) are always reported in the `side_effects` array, each with `stage_set`.

## Org capabilities — `org-capabilities`

Resolves what the org can actually classify an issue with: its **enabled native issue types** and every **org issue field** with the option ids needed to write single-select and multi-select values. One GraphQL round trip, cached to `.claude/issue-fields-cache.json`; `--refresh` re-queries and rewrites its own keys while preserving any other key in that file. The record carries `fetched_at` and is trusted for an hour, or for five minutes when it lacks `Priority`, `Effort`, `Ownership`, `Stage` or a `Stage` option, because an org's fields change and the file outlives the run that wrote it — a new worktree can start with a copy of the main checkout's.

The command is GraphQL and not REST because REST (`/orgs/{org}/issue-fields`) returns `null` for every option id, which makes those fields readable but not writable.

Output beyond `type_map` and `field_map`:

- `owner_kind` — `organization` or `user`.
- `resolved_fields` — purpose key → the concrete field name that exists here.
- `missing_fields` — the purpose keys that do not resolve, each with the name that was looked for.
- `cached` — whether this run answered from the cache.

Four outcomes a caller must tell apart:

| Situation | Exit | `status` |
| --------- | ---- | -------- |
| Types and/or fields resolved | 0 | `ok`, `owner_kind: organization` |
| A user-owned repo — issue types are an org-only feature | 0 | `ok`, `owner_kind: user` |
| The account may not read a capability | 21 | `no-capabilities`, with `denied` |
| The org resolves but reports neither types nor fields | 21 | `no-capabilities` |

The last two are the cases that did not exist before, and both are the same underlying mistake: treating "we could not find out" as "there is nothing there". An under-scoped token, an expired one, or an account without org access all look identical to an org that has simply not enabled issue types, and carrying on regardless is how a repo ends up creating issues with blank metadata and no error anywhere.

The denial case is worth calling out because GraphQL reports it *partially*: GitHub returns the issue fields the account may read alongside a `FORBIDDEN` error for the issue types it may not, so a naive read sees fields, sees no types, and concludes the org is not type-capable. `wf` reads the error list too, reports the denied paths in `denied`, and — importantly — **does not cache the result**, because a cached `type_capable: false` that really meant "not allowed to look" would make every later run fall back to labels in silence. The usual fix is `gh auth switch`; `gh auth status` shows which account is active and what scopes it has.

`NOT_FOUND` counts as a denial for the same reason. GitHub returns it when the account may not see the organisation at all, and reading it as "no such org" recorded `owner_kind: user` — an org filed away as a personal account, cached with no expiry, every issue created after that with no type and no field values and nothing reporting it. An empty result is now only believed when it carries the current `CAPABILITY_CACHE_SCHEMA`, so a cache written by a version whose conclusion is no longer trusted heals itself on the next run instead of waiting for someone to know about `--refresh`.

Field **names** are overridable per project in `ClaudeProject.md` → `## Issue Types & Fields`; the value maps behind them are Python data in `wf_core.py` (`NATIVE_TYPE_MAP`, `CLASSIFICATION_OPTIONS`, `FIELD_NAME_DEFAULTS`, `FIELD_DATA_TYPES`, `PRIORITY_FIELD_OPTIONS`, `EFFORT_FIELD_OPTIONS`, `ORIGIN_FIELD_OPTIONS`).

## Classified issues — `issue-apply`

`issue-apply <spec.json>` creates or updates issues carrying everything at once: native type, every org field value, labels, parent, and blocked-by edges. It exists because doing that by hand was ten-odd round trips per issue, each described as optional — and the measured result of "optional" in one consuming repo was 7 typed issues out of 82, no field values at all, and no error anywhere. So the command is deliberately strict.

A spec can describe a whole epic tree, and one invocation applies all of it.

### The spec

A JSON object with an `issues` list (a bare list is accepted too). An entry with a `number` is an update; one without is a create.

```json
{
  "issues": [
    {
      "key": "epic",
      "title": "Ship the classifier",
      "body": "Why this matters.",
      "kind": "epic",
      "fields": {"field-priority": "High", "field-effort": "High",
                 "field-ownership": "Code agent", "field-origin": "Development"}
    },
    {
      "key": "feature",
      "title": "Classify issues from the org's own fields",
      "kind": "feature",
      "parent": "epic",
      "fields": {"field-priority": "High", "field-effort": "Medium",
                 "field-ownership": "Code agent", "field-origin": "Development"}
    },
    {
      "key": "first-story",
      "title": "Resolve org fields in Python",
      "kind": "story",
      "parent": "feature",
      "blocked_by": [187],
      "fields": {"field-priority": "High", "field-effort": "Medium",
                 "field-ownership": "Code agent",
                 "field-type": ["New Feature"], "field-origin": "Development"}
    }
  ]
}
```

| Key | Meaning |
| --- | ------- |
| `key` | A spec-local name, so entries can reference each other before any of them has a number. Optional, but required to be referenced. |
| `number` | An existing issue to update. Absent means create. |
| `title`, `body` | As on GitHub. A create needs a title. A `[BUG]`-style kind prefix is stripped from the title — the native type says that. An update compares each with the issue and writes it only when it differs, so re-running a matching spec writes nothing; a written one is listed in `changed` and read back, and a read-back that does not match is a mismatch. An update entry that leaves one out leaves that one as it is. |
| `body_file` | A path to read the body from, used when `body` is absent. A body is prose — fenced code, backticks, `$`, quotes — and building that into a JSON string by hand in a shell is where bodies get mangled. The spec file keeps saying `body_file` after a write-back; the body is never inlined into it. |
| `kind` | One of `wf_core.NATIVE_TYPE_MAP`'s keys (`story`, `feature`, `epic`, `bug`, `spike`, …). Supplies both the native type and a default `Classification`. |
| `type` | An explicit native type name, overriding what `kind` implies. |
| `labels` | Literal names, or purpose keys a surviving label map resolves. Labels decide nothing and the workflow passes none: a `type-*` label or a retired one (`status-*`, `priority-*`, a scope label) is dropped. |
| `parent` | An issue number, or another entry's `key`. A `User Story` needs a `Feature` parent; a `Feature` that has a parent needs an `Epic` one (see below). |
| `blocked_by` | A list of issue numbers and/or `key`s. **The complete set**: an issue already carrying an edge the list omits has it removed, and `[]` removes them all. Leave the key out to leave the edges alone. |
| `state` | `backlog`, `refinement` or `parked`: the stage to write, overriding the one the issue's fields name. Absent means the fields decide. It never moves `Browser agent` or `Human` work out of Non-code. |
| `fields` | Purpose key → value. Names resolve through `ClaudeProject.md`'s `## Issue Types & Fields`, then `wf_core.FIELD_NAME_DEFAULTS`. |
| `milestone` | An open milestone's title, so a sprint placement rides in the same write. A title that names no open milestone fails the spec before anything is written. |

Created numbers are **written back into the spec file**, which is what makes a re-run after a partial failure complete the remainder rather than creating everything a second time.

### How a tree is applied

Aliased multi-mutations let many issues be created in one request, but an alias cannot reference another alias's output — so a child's `parentIssueId` only exists once its parent's request has come back. The command therefore works in **hierarchy levels**, parents before children, and puts the dependency edges last:

| Phase | Requests | What happens |
| ----- | -------- | ------------ |
| Prerequisite | 1 query | The repository id, every label id, and the node id of every issue the spec references but does not create — one lookup, not three. |
| Per level | 1 mutation per `wf_core.BATCH_MAX_NODES` entries | Every issue at that level is created in one aliased `createIssue`. |
| Link | 1 mutation per `BATCH_MAX_NODES` operations | Every `blocked_by` edge. |

Edges come last so an edge may point at **any** issue in the tree regardless of level, including one created in the final batch.

An epic with three features and nine stories is therefore **four mutations** (three levels plus the link phase) on top of the one prerequisite lookup, rather than the hundred-odd round trips a per-issue loop would take. There is a test that asserts exactly that count against a recorded transport, because it is the kind of property that silently regresses.

Each `createIssue` asks for the full issue selection in its own payload, so GitHub returns the issue **as it now holds it** — verification comes back with the create rather than costing a round trip of its own.

Updates are not batched. An update has to read the issue first to decide what differs, and the levels only exist to make creation possible; a re-applied spec is dominated by no-ops in any case.

### What it refuses, and why

Everything decidable offline is decided before the first mutation, because a half-applied epic tree is far harder to reason about than a refused spec:

- **A missing required field** — Priority, Effort or Ownership — exits 22 naming the issue and the field. A create must name all three. An update names only what it changes, and is refused when a value it leaves out is not on the issue either; a `TODO` it writes is refused whatever the issue carries. That is the blank-metadata failure this command exists to stop, and the three are exactly what a decision reads: the pool's order, its size ceiling, and whether a code agent may take the issue at all. `wf_core.MANDATORY_FIELD_KEYS` is the list.
- **An org that defines no such field** exits 22 as well, naming the field and saying to create it. Skipping is what let a repository run for weeks with no `Ownership` field while `config-audit` reported a clean configuration.
- **A missing optional field** — Classification or Origin — is not refused. `wf_core.OPTIONAL_FIELD_KEYS` is that list, nothing selects on either, and a create that leaves one unset gets a comment on the issue naming it.
- **A placeholder** (`TODO`) counts as missing, so an audit's proposal cannot quietly pass as a value.
- **A dependency cycle** within the spec exits 22 before anything is written, and so does a **parent cycle** — a different fault, and equally unresolvable.
- **A label or referenced issue that does not exist** in the repo exits 22, named, before the first mutation.
- **An issue outside the epic tree.** A `User Story` with no `Feature` parent, or a story or feature under the wrong type, exits 22. A `Feature` with no parent is allowed: it sits under an `Epic` when the work has one, and an epic invented to hold a single feature would only restate it. A parent that already exists is judged by its live type, and an update that does not restate its parent is judged by the parent it already has. Enforced only where the org has the parent type enabled; `Bug`, `Chore` and `Epic` need no parent. `wf_core.HIERARCHY_PARENT_TYPE` is the rule.
- **One issue, two parties.** A title prefix and an `Ownership` value that disagree, such as `[Manual]` owned by `Code agent` or `Human` with no prefix, exits 22. One of the two is wrong, and the issue would mislead whoever reads it.
- **A `state` that is not one of the three** exits 22. There is no `ready`.
- **A field this org does not define** is skipped, not an error — an org is allowed fewer fields than the default inventory. It is reported once for the run on stderr, not once per issue.
- **A refused capability read** exits 21 rather than falling back to labels, for the reason `org-capabilities` gives above.

### A dependency is an edge and nothing else

A `blocked_by` becomes a native `addBlockedBy` edge. It used to become a `## Dependencies` section in the body as well, and the two drifted apart on nine of the fourteen issues carrying both on one real backlog — the prose stale every time. Prose is not parsed now, in any command: a body naming a blocker with no edge behind it is not blocked.

### Every issue gets the stage its own state names

After the edges are written, `issue-apply` writes each issue's `Stage`. Nothing did this before, so a spec could write an edge and leave the issue sitting in the pool, which put work whose dependency had not been built yet straight into `pick`'s reach.

| The issue is | Stage |
| --- | --- |
| owned by a browser agent or a person (`Ownership`) | Non-code |
| given a `state` on its spec entry | the stage it names |
| owned by nobody | Needs refinement |
| pointing at least one open edge | Blocked |
| none of these | Backlog |

**A stage this phase does not own is kept.** It may write `Backlog`, `Blocked` and `Non-code`, and fill a blank `Stage`; an issue at `In Progress`, `In Review`, `Parked`, `Needs refinement`, `Needs attention` or `Done` keeps its stage and is reported as `stage_kept`. Found live: an update setting one field on an in-progress issue sent it back to the pool, where a second agent could pick up the same work. An entry that names a `state` overrides this, because asking for a stage is a decision rather than an inference.

Each entry's result carries `stage` (the stage the issue now has), `stage_kept`, `stage_set`, and a `stage_message` saying why when the write did not happen.

**An issue whose edges or stage cannot be read is not written**, and its entry fails. A failed read is not the answer "nothing blocks it", and re-running the spec completes the write because every write before it is idempotent.

Ownership wins over a dependency. It is a property of the work and survives every blocker closing, so an issue that is both ends up in the stage no sweep releases it from.

**A retired label is taken off.** Whatever `status-*`, `priority-*`, scope or `needs-refinement` label an issue still carries from the label workflow is removed here, which is how an existing backlog migrates without anyone sweeping it. The removal is best-effort: the stage write is the part that decides anything.

### Every write is read back

An accepted mutation is not a changed value — an unpinned field or a permission that stops short of writing both return success. So the command compares every issue against the spec and exits 23 `verify-failed` naming each mismatch. The issues still exist; the command is telling you the metadata did not land.

### Partial failure is reported, not swallowed

A batch answers a partial failure with the aliases that worked and an error carrying the path of each one that did not, so one bad entry does not take its neighbours down with it. The command exits 24 `partial`, names the entries that failed, and writes the numbers of the ones that landed back into the spec — which turns them into no-op updates, so re-running the same spec completes the remainder rather than creating anything twice.

## Finding the gaps — `issue-audit`

`issue-audit` reads every open issue in a repo and reports what is missing. It exists because nothing did: the classification gap went unnoticed for months across 82 issues, of which 7 were typed and none carried a field value, with no error anywhere. It also produces the input to the backfill, so the unclassified remainder does not have to be handled one at a time.

It **never writes**. Both write transports are stubbed out in its tests to prove it.

### What it reports

| Gap | Meaning |
| --- | ------- |
| `missing-type` | The org has issue types enabled and this issue has none. |
| `missing-field` | One of the three required fields (`wf_core.MANDATORY_FIELD_KEYS`) this issue holds no value for. An unset `Ownership` is reported here, once. The proposal fills `Ownership` from a `[Manual] ` or `[Browser] ` prefix and leaves everything else it cannot know as `TODO`: no label is read, and an unprefixed title is not taken to mean `Code agent`. |
| `missing-optional-field` | `Classification` or `Origin` unset. Worth filling in, never worth refusing an issue over. |
| `type-contradiction` | The native type disagrees with a legacy `type-*` label or `[BUG]`-style title prefix the issue still carries. Reported so the stale one can be removed; neither is written any more. |
| `classification-contradiction` | The `Classification` value cannot be true of the declared kind — a story classified `Bug Fix`, a bug classified `New Feature`. |
| `scope-option` | An `Ownership` value the workflow does not recognise, usually a renamed option. |
| `scope-prefix` | The `[Manual] `/`[Browser] ` title prefix and the `Ownership` value disagree. |
| `hierarchy` | A `User Story` with no `Feature` parent, or a story or feature under the wrong type. Reported and never proposed: which feature a story belongs to is a judgement about the work. |
| `missing-parent` | `--parents` only. The body says it is part of an issue and GitHub shows it as free-standing. |
| `parent-closed` | `--parents` only. The parent the body names is not open. |
| `parent-differs` | `--parents` only. The body names one parent and the hierarchy has another. Reported, never changed. |

`Classification` is checked for **incompatibility**, not for agreement (`wf_core.INCOMPATIBLE_CLASSIFICATIONS`). It is a multi-select describing what the work touches, so a story classified `Documentation`, `Performance` or `Integration` is telling the truth and only a defect classification — `Bug Fix`, `Regression` — contradicts it, and vice versa for a bug. Requiring agreement instead produced false positives on every issue that had been classified carefully.

A `[DEBT]` issue typed `Feature` is **not** a type contradiction on an org whose types are GitHub's five defaults: none of them can express tech debt, which is precisely what `Classification` is for. An org that has added a `Chore` type is a different case, and `wf_core.NATIVE_TYPE_PREFERENCES` is where that is said: `tech debt` and `chore` become `Chore` where the org has one, and the `Feature` default stands where it does not. Adding a preference has a consequence beyond the audit, so read `NATIVE_MAINTENANCE_TYPES` with it — a type that is not in that set cannot be picked by `execute mode=maintenance` at all.

### Relationships

One gap above comes from body prose, and it is worth understanding before trusting a proposal.

**A parent is GitHub's native Parent issue relationship.** An issue whose first line says `Part of the Cadence Plus epic (#959)` and which GitHub renders as free-standing is invisible as a child: the epic shows no sub-issues and nothing reports that the two disagree. `wf_core.parse_parent` reads a fixed set of phrasings in precedence order, and an issue that **already has** a parent is left alone even when the body names a different one, because a deeper parent is usually the more specific truth and reparenting would flatten a hierarchy somebody built on purpose.

This one is **opt-in**, and the reason is worth stating rather than treating as caution. A story created through `feature-discovery` carries `"parent"` in the spec that creates it, so on a repo whose issues all arrive that way, parsing the sentence back out of the body only re-derives what the pipeline already knew, and every issue that politely repeats its epic in the first line shows up as a gap. Where the prose is the only record — a backlog written before any of this existed, or an issue typed into the GitHub UI — pass `--parents` and the three gaps above come back.

The parent is the **only** thing read out of a body. Dependencies used to be read the same way, and it went badly enough to be worth recording: the parser missed a `## Blocked by` heading whose references sat on the next line, and read "Nothing. This **was** blocked by #980" as a live dependency — wrong in both directions on the same backlog, and each fault silently invisible. A sentence is not structured data and no amount of regex makes it so, so the audit no longer proposes an edge from one. What it checks in that slot instead is **scope**, where the three signals genuinely can be compared against each other.

## Configuration drift — `config-audit`

Three things describe how a project works, and they drift apart quietly: `ClaudeProject.md`, the labels the repo actually carries, and the org's issue types and fields. Nothing errors when they disagree. A label gets renamed and a call site keeps applying the old name — `gh` refuses the edit and the issue stays where it was. An issue type stops being pinned to a field and every value written to it is stored correctly and shown nowhere.

`config-audit` compares all three, and it never writes. `preflight` below runs every one of these checks plus the file-level ones, and is what `skills/preflight` calls; reach for `config-audit` directly when only the drift half is wanted, or as a CI gate.

### What it reports

| Finding | Level | Meaning |
| ------- | ----- | ------- |
| `config-section` | critical | `ClaudeProject.md` is missing a section the plugin reads, so its values fall back to defaults silently. |
| `label-missing` | critical | An instruction file tells an agent to apply a label the repo does not have. |
| `config-label` | critical | A `## Label Map` left in `ClaudeProject.md` names a label the repo does not have. |
| `field-unpinned` | critical | An enabled issue type is not pinned to a field the tooling writes, `Stage` included. |
| `field-absent` | critical | The org defines no `Priority`, `Effort` or `Ownership` field, and the picker reads all three. |
| `stage-absent` | critical | The org defines no `Stage` field, so no issue's state can be written or read. |
| `stage-options` | critical | `Stage` lacks one of its nine options, named, so a transition to it fails. |
| `field-options` | critical / warning | An option on a mandatory field that no decision knows. Critical on `Ownership`, where nothing can route the issue; a warning on `Priority` (sorts last) and `Effort` (sized as `Medium`). |
| `label-deprecated` | warning | The label map still names a label nothing reads. |
| `review-label` | warning | A review-state label the repo lacks, so a pull request cannot carry that state. `--fix` creates it, as `labels-ensure` does. |
| `label-retired` | warning | Open issues still carry a label the fields replaced. `--fix` takes it off. |
| `field-absent-optional` | warning | The org defines no `Classification` or `Origin`, so issues are filed with less on them. |
| `label-drift` | warning | Two live labels mean the same thing (`type:bug` beside `type-bug`, `bug` beside `type-bug`). A pair of retired labels is `label-retired`'s, whose advice is the opposite: take both off. |
| `pin-asymmetry` | warning | A field some enabled types pin and others do not. |
| `field-unmapped` | warning | An org field no purpose key resolves to, so nothing ever sets it. |
| `pin-unknown` | warning | `IssueType.pinnedFields` could not be read, so pinning is unverified. |

### Why the split is where it is

One question decides it: does the workflow produce a **wrong** result, or a **degraded** one? A missing section or a label that does not exist produces wrong behaviour — the command runs, GitHub accepts or refuses it, and the outcome is not what anyone asked for. An org field nobody mapped degrades gracefully, so it warns and the run continues.

Pin asymmetry is the case that makes the distinction concrete. A type that cannot hold a field should not pin it, so a field that some enabled types carry and others do not can only ever be a warning, and only the three fields the tooling actually writes (`wf_core.MANDATORY_FIELD_KEYS`) are ever a failure.

The fix text is written to be reported verbatim. For an unpinned field it names the type, the fields, and the form: org settings → Planning → Issue fields → the field's edit form → "Pin to issues". A paraphrase loses the only part that tells someone where to click.

### Placeholders are not labels

The label scan reads `--add-label`, `--remove-label` and `--label` out of every `.md` file under the plugin root (`--scan` points it elsewhere) and checks the names against the repo. It only ever checks **literals**. These files write "the label you resolved" as `{status_ready_label}`, `<verdict-label>` or a bare `X` in an example, and none of those is a claim about any particular label.

### Cost

Three round trips: one repo query carrying the labels, one walk of the open issues (which still carry a retired label), and one org query for the pinning. Org capabilities come from the cache. `--offline` runs only the checks that need no network, `--quiet` drops the per-finding detail and keeps the exit code, and exit 26 makes it usable as a CI gate.

## Can this project be worked on at all — `preflight`

`config-audit` answers "does `ClaudeProject.md` agree with the live repo and org?". `preflight` answers the question a command actually has before it runs: **can this project be worked on at all?** That is every `config-audit` check, plus the ones that read the two markdown files themselves, plus a `--fix` that repairs the subset a run can repair without guessing.

```
# Before a command. Exit 0 means nothing blocks; 26 means something does.
wf preflight

# Repair what can be repaired, then re-run and report what is left.
wf preflight --fix
```

The file-level checks used to be shell blocks inside `skills/preflight/SKILL.md`: `gh auth status`, the required-section `grep`, the placeholder scan, the quality-gate read, the `CLAUDE.md` check. Two implementations of one gate is one too many. The shell one could not be tested, could not be reused by `bulk-execute`, and disagreed with this one about what counted as critical.

### What it adds over `config-audit`

| Finding | Level | Meaning |
| ------- | ----- | ------- |
| `gh-auth` | critical | The GitHub CLI cannot act for this repository. Nothing else runs. |
| `file-config` | critical | There is no `ClaudeProject.md`. Reported alone: with no file there is nothing to compare anything against, and the network is never touched. |
| `config-retired` | warning | A `## Ready Gate` or `## Agent Gating` section survives. Nothing reads it, which is exactly why it has to go — left there, the next person to read the file believes it. |
| `placeholders` | warning | Template placeholders nobody replaced, named by line. |
| `quality-gate` | warning | No pre-commit command, or the placeholder is still there. |
| `file-claude-md` / `claude-md-ref` | warning | No `CLAUDE.md`, or one that never mentions `ClaudeProject.md` — so a session that runs no workflow command never finds the configuration. |
| `review-config` | warning | `ClaudeProject.md` names a review-state label file that is not there, so every review label falls back to its default name. |
| `instructions-retired` | warning | A `CLAUDE.md` or `ClaudeProject.md` in the project still describes the `Ready` opt-in, a lifecycle, priority or scope label, or a dependency written as prose, named by line. Never rewritten: the lines are somebody's own sentences. The plugin's own directory is not scanned, since its templates name what was retired on purpose. |
| `container-finished` | warning | An open Epic or Feature whose sub-issues are all closed. `post-merge` closes the ones a merge finishes; this finds the ones that finished before it did, and `--fix` closes them as completed and sets their stage to `Done`. A container with no sub-issues is never flagged. |
| `stage-drift` | warning | An open issue's `Stage` is blank or `Backlog` although an open pull request closes it or somebody is assigned. `--fix` sets it to `In Review` for a ready pull request and `In Progress` for a draft one or an assignee. Only a blank or `Backlog` stage is judged, so nothing a run or a person chose is overwritten. The usual cause is a run on a version before 12.0.0, which never wrote `Stage`; a `Stage` write that failed after its claim is the other. |

### Every finding says whether `--fix` would touch it

Each finding comes back with `auto` and `fixable`. `auto: true` means a run can repair it and `fixable` says how; `auto: false` means it must not, and `fixable` says why. The split is decided offline, in `wf_core.FIXABLE_CHECKS` and `wf_core.UNFIXABLE_REASONS`, which is what makes "would running `--fix` change anything?" answerable without a network call.

`--fix` repairs six things, all idempotent:

| It does | Because |
| ------- | ------- |
| deletes a retired section | Nothing reads it. |
| deletes a deprecated label-map row | Nothing applies the label. The label itself stays in the repo — deleting one strips it from every issue that ever carried it. |
| adds the `ClaudeProject.md` pointer to an existing `CLAUDE.md` | One sentence, and it is idempotent on the filename rather than the wording, so a project that worded its own pointer keeps it. |
| takes retired labels off the open issues carrying them | They decide nothing, and the write path already strips them from any issue it touches; this reaches the ones no command has. |
| closes a finished Epic or Feature, setting its stage to `Done` | Every sub-issue is closed, and nothing else closes a container. |
| sets a drifted issue's stage to `In Review` or `In Progress` | An open pull request or an assignee already says the work started, and only a blank or `Backlog` stage is ever changed. |

It will not create a `CLAUDE.md`, invent an `## Identity` section, create or delete an org-level issue field (`Stage` included), add or rename a field's options, pin a field to an issue type, choose between two disagreeing values, rewrite a sentence in somebody's instructions, or write a quality gate. Each is either a decision only the project can make or a change that happens in the org settings rather than through the API this runs on.

### It reports the state it leaves, not the state it found

`--fix` re-runs every check after repairing, and the `findings` it prints are the ones still true. Anything else would make the second run of an idempotent command look like it had done nothing — and it is the second run that tells you whether the first one worked.

## Settling a merged PR — `post-merge`

`post-merge --pr <n>` makes "the story is closed and at `Done`" a deterministic step instead of trusting GitHub. It reads the PR's own `closingIssuesReferences`, **force-closes** any of those issues still open (GitHub only auto-closes on a default-branch merge of a recognised keyword — a chained-story PR or an unparsed reference leaves it open), and sets every linked issue's stage to **Done**. Each settled issue is reported with `closed_now` and `stage_set`. It refuses (`status: not-merged`, exit 11) on a PR that has not actually merged, so it is safe to call on the queued `--auto` path. Add `--issue <N>` (repeatable) to settle a reference GitHub did not parse. `pr-review`'s auto-merge step calls this after a successful immediate merge. It costs the same five GitHub requests however many issues the PR closes: the PR, one aliased read of every issue, one mutation closing them and removing any retired label, one `Stage` write, and one read of their parents. A close GitHub refuses is still reported against its own issue.

## Releasing what a merge freed — `unblock`

Nothing did this. `post-merge` settles only the issues a pull request *closes*, so one that closes none returns `settled: []` — which reads as a finished run and is not: whatever was waiting stays `Blocked`, and a `Blocked` issue is invisible to the picker.

`unblock` reads every open issue in the repository whose `Stage` is `Blocked` and sorts it five ways. Only the first two write anything.

| Bucket | What it means | What it does |
| --- | --- | --- |
| `released` | every native blocked-by edge points at a closed issue | sets `Stage` to `Backlog`, comments |
| `rescoped` | browser or human work at `Blocked` | sets `Stage` to `Non-code`, comments; the entry carries `stage` |
| `held` | at least one blocker is still open | nothing |
| `partials` | held, but a blocker merged something in the last 14 days | reports it, never acts |
| `no_edges` | `Blocked` with no dependency edge at all, so a person set it | counts them, never changes them |

**The scope check runs before the edge check, and that order is the safety property.** Both issues the first real run would have released were `[Manual]` device passes whose blockers happened to close; releasing them would have put a job needing a phone in someone's hand into the code agent's pool.

**Nothing is released without at least one edge.** Two thirds of one real backlog's blocked issues have none, and they are waiting on a bank account, a device pass, a store upload. Reading "no open blockers" as "release" would put every one of them in front of an agent that cannot do any of them.

**The comment is load-bearing.** A bare state change reads to the next agent as damage to repair, and one repaired exactly this: three issues released by hand were re-blocked two minutes later by a concurrent session that took the release for automation gone wrong.

`--dry-run` reports without writing; `--issue N` (repeatable) narrows it. `post-merge` runs the sweep and returns it as `unblocked` whether or not it settled anything (`--no-unblock` opts out). `pick` and `plan-set` need no sweep first: a `Blocked` issue whose blockers have all closed is released and considered in the same round, in one batched stage write and one batched comment.

## The three pickers

| Subcommand     | Pool                                              | Claims          | Marker applied        | Used by      |
| -------------- | ------------------------------------------------- | --------------- | --------------------- | ------------ |
| `pick`         | Every open issue, judged by the rules below       | `issue-{n}` ref | `Stage` In Progress   | execute |
| `update-next`  | My open PRs with actionable review feedback       | `pr-{n}` ref    | `updating` (keeps the feedback label) | pr-review |
| `review-next`  | Open PRs labelled `needs-review` / `needs-re-review` | `pr-{n}` ref | `reviewing` (removes prior) | pr-review |

All share the same atomic claim/checkout core and JSON contract. `--checkout` creates/checks out the branch (`pick`) or runs `gh pr checkout` (PR pickers).

### Choosing from the issue tree

`pick` and `candidates` read every open issue in the repository in one paged query: type, fields, assignees, blocked-by edges, sub-issues, parent and the pull requests that close it. No board is read. Each issue is judged by these rules, and the first that applies decides (`wf_core.evaluate_pool`):

1. `Stage` is anything but blank or `Backlog`: not pickable.
2. Assigned, held by a claim ref, or closed by an open pull request: not pickable.
3. `Ownership` is not `Code agent`: not pickable. A `User Story` or `Bug` with no `Ownership` counts as `Code agent`; any other type with none does not.
4. An open blocked-by edge: not pickable, and `pick` sets `Stage` to `Blocked`. A blocker holds back only the issues it blocks, and it inherits the priority of the most urgent story waiting on it, directly or down a chain, so the pool puts first whatever finishes urgent work soonest. The entry carries `unblocks`, and `inherited_priority` when it rose.
5. Under an Epic or Feature whose `Stage` is `Parked`: not pickable. This is the one rule that passes down the tree.
6. Any other story, bug or chore: pickable as itself.
7. A `Feature` with pickable stories: pickable. `pick` claims its highest-priority story and returns the rest in `offered`; `candidates` lists them in `stories`.
8. An `Epic` with a pickable `Feature`: pickable, taking its highest-priority `Feature`.
9. An Epic or Feature with no sub-issues, or a story whose body is nearly empty or has no acceptance criteria: needs refinement. `pick` stops with `needs-refinement` (exit 12) and claims nothing, so a person can clarify it; with `--unattended` it sets `Stage` to `Needs refinement`, comments why, and walks on. `candidates` lists these under `needs_refinement`.

The pool is ordered by `Priority`, then `Effort`, then issue number. `--mode` and `--max-effort` apply to stories, bugs and chores; in `maintenance` mode a story under a `Feature` classified as maintenance work counts too. Nothing here sets an Epic or Feature to `In Progress`, `In Review` or `Parked`.

### Dependencies decide order, not membership

`pick --issue N` on an issue with open blockers does not refuse it when this run can build them. It plans the chain (`wf_core.plan_set`), sets N to `Blocked`, claims the first prerequisite that is ready, and returns it with `prerequisite_for` (`number`, `title`, `build_order`). Only a blocker nobody here may build ends the pick, with `all-blocked` and a reason naming it. A pick with `--sibling` is never redirected, because a bulk claim must take exactly the story it names.

`plan-set` does the same for a bulk run. Its universe is every pool story plus every waiting story (blank, `Backlog` or `Blocked`, code work, unassigned, unclaimed, its edges fully read); a `Blocked` story whose blockers have all closed counts as ready and is listed in `released`. Two stories are related by a blocked-by edge either way, a shared prerequisite, a shared parent, or the same Epic. A blocker in another repository is kept as `owner/name#N`: open, it excludes the story; closed, it is satisfied. `--mode` and `--max-effort` never hold back a prerequisite a code agent may build. Named (`--issue`, repeatable): each named story plus the prerequisites it needs. `--parent N`: the lead and its group come from the stories under N, and a prerequisite outside N still joins; `candidates --parent N` returns the same set without claiming. Neither: the best-ranked related group of at least two whose chains fit `--size` (2 to 7), stories added by closeness to the lead and a blocker never cut while its dependent stays; a single story only when no group exists. `waves` groups the build order so no story shares a wave with anything it waits on. Without `--claim` it only reads, and `nearby` lists the best unlinked ready stories. With `--claim` it takes every claim ref at once, drops a story claimed away, blocked or resolved together with everything waiting on it, then assigns in one mutation and writes `Stage` and `Start date` in another, and records the set in `.claude/bulk-set.json`. `drop-story` returns a story and its unbuilt dependents to the pool, and `bulk-mark` records the branch and each story built.

## Scope / deferrals

- **`pick`** — `--mode story` / `feature` / `maintenance`, reading the open, unassigned issues whose `Stage` is blank or `Backlog` as the pool, from the repository's issues rather than a board. One GraphQL query (`fetch_issue_facets`) reads the native type, the `Priority` field and the `Classification` field for the open backlog, and the pool is ordered by `Priority` — `Urgent` → `High` → `Medium` → `Low`, then lowest issue number. An issue with no `Priority` value sorts last and is named on stderr; there is no label fallback, on purpose. No mode offers an `Epic`: it is the outcome its features and stories deliver, not a piece of work. **Type has none**: `feature` and `maintenance` filter on the native `issueType` alone, so an issue the org has not typed — or a `Feature` it left unclassified — is out of the pool and named on stderr rather than guessed at from a `type-*` label or a `[PREFIX]` title. An org whose backlog carries no native type at all cannot answer those modes and `pick` exits `no-capabilities` (21) saying so; `--mode story` is unaffected. Membership of the pool is the `Stage` field's answer: an issue is in it because its `Stage` is blank or `Backlog` and nobody is assigned, whether or not it has a card on any board. Every other stage takes an issue out of the pool. No label is read at any point in the selection.
- **`review-next`** — the *label-driven* subset. A PR whose head SHA changed since its last review (needing review without a label) is **not** detected here, so `pr-review` treats `no-candidates` as non-conclusive and falls back to its inline SHA check. Pass `--no-claim` for a read-only review (no push access): it selects the next PR without writing a claim ref or applying the `reviewing` marker, and the JSON reports `claimed: false`.

## Locks, stage and handoff

These five commands replaced the markdown procedures the skills used to follow step by step. Each is one call with a defined exit code, so a call site states the command and what to do about each outcome rather than describing the mechanism.

### `claim` / `claim-release` / `claim-reap`

`claim --issue N` or `claim --pr N` takes `refs/claims/{issue,pr}-N` — a server-side compare-and-swap, which is what makes it safe between two agents running under the same GitHub identity, where a shared label cannot exclude a rival.

The ref is the lock but it is ephemeral, so on success the command also advertises ownership where a later picker will look: an issue is assigned to `@me` and its `Stage` set to `In Progress`; a PR swaps `needs-review` for `reviewing`. Pass `--no-marker` to take the lock silently. The marker is best-effort — the lock is already held, and failing to advertise it is worth a warning, not giving the item back.

| Exit | Meaning |
| ---- | ------- |
| 0 | You hold it. |
| 27 | Another agent holds it. Make **no** changes: move to the next item, or report and stop on a named one. |
| 20 | A broken environment, not a rival — usually no write access to `refs/claims/*`. Never fall back to a bare label as a "soft" claim; that reintroduces the race the ref removes. |

`claim-release` takes repeatable `--issue` / `--pr` and is idempotent — releasing a ref that is already gone is not a failure, so it always exits 0. A ref it could not delete, and which the remote still holds or could not be asked about, is listed under `failed` rather than `released`, and named in `reason`: it keeps the item out of every pool until it is released again or `claim-reap` frees it. `pick` reports the same thing as `claim_released` on each side effect that released a claim, and `handoff` on each issue it hands off.

`claim-reap` frees the refs a crash left behind. It always exits 0 and returns three lists: `reaped` (freed — the issue is closed, no longer in progress, or already has a PR; the PR is closed, merged, or open with no review under way), `suspect` (deliberately left, because the evidence does not say the work stopped) and `skipped` (younger than `--threshold`, default 4 hours). `--dry-run` reports the verdicts without freeing anything. The judgement is `wf_core.reap_verdict`, which is offline-tested; everything in `wf.py` around it is I/O.

### `stage-set`

`stage-set N --stage stage-in-review` writes an issue's `Stage` field, which is the only place its state is recorded. `--stage` takes a purpose key (`stage-backlog`, `stage-in-progress`, `stage-in-review`, `stage-blocked`, `stage-non-code`, `stage-refinement`, `stage-parked`, `stage-attention`, `stage-done`) or the stage name itself. No board is read or written.

It **always exits 0**, so a failed write never costs a run its work. Read `set`, `stage` (the name) and `reason`. A write that did not happen is reported loudly, because the stage is the issue's state: an issue whose `In Progress` write failed still reads as available.

### `sibling-pr`

`sibling-pr N [M ...]` returns the open PRs that close issue N, oldest first (with several numbers, `by_issue` holds one answer per issue from the same single read), using GitHub's own parse of closing references rather than a free-text body search. `--exclude-branch` drops your own PR, so anything returned is someone else's. Exit 0 with `found: 0` is the expected answer before starting work; exit 20 means the lookup failed, which is not the same as "no duplicate" and must be reported as such.

### `labels-ensure`

`labels-ensure` creates each of the nine review-state labels the repo lacks, named through `docs/review.config.md` with the `review-` defaults, with the colours and descriptions in `wf_core.REVIEW_LABEL_META`. These are the only labels the workflow applies. It never passes `--force`, so an existing label keeps its colour, and a create that loses a race ("already exists") counts as created. Read `created`, `failed` and `labels`; it exits non-zero when the labels cannot be read or a create fails.

### `handoff`

`handoff --pr P --issue N [--issue M …]` ends a build: it takes the PR's review claim (`refs/claims/pr-P`) first, so the work is never unlocked between the build and its review, and reports that as `pr_claimed` (`won`, `lost` or `error`). A later `claim --pr P --keep-held` from the same checkout keeps the claim it holds; without `--keep-held` it reports `lost`, so a second session sharing the checkout cannot take the PR. Then it labels the PR with the review-state entry label, then sets each issue's `Stage` to `In Review` and releases every issue claim ref in one push, as `claim-release` does, with one `ls-remote` to tell which refs are still held when that push fails. Finally it deletes `.claude/plan.md` and `label-cache.json`; the preflight marker stays, so an issue filed during review does not re-run preflight. `--gate-failed` enters review as changes-requested rather than needs-review.

It **always exits 0**: once the pull request exists, none of this is a reason to stop. Read `pr_labelled` and the per-issue `stage_set` and `stage_message` instead. A failure on one issue does not affect the others.

### `board-sync`

`board-sync` is what `.github/workflows/board-sync.yml` runs every 6 hours. It is the backup for everything a run or a person did not keep in step, across every unarchived repository in the org that has issues turned on:

- **Cards.** Each open issue gets a card on every open board linked to its repository (`Repository.projectsV2`) that does not already hold one. GitHub's own "Auto-add to project" workflow stays the primary way issues reach a board; this adds what it missed. A repository with no linked board gets no cards.
- **Stage.** Each open issue, and each issue closed in the last `--closed-days` days (default 7), has its `Stage` set by `wf_core.reconcile_stage`: `Done` when closed; `Non-code` when its `Ownership` is `Human` or `Browser agent` and it is blank, `Backlog` or `Blocked` (such work a person has moved to `In Progress` or `In Review` is left there); for a blank or `Backlog` issue somebody has started, `In Review` for a ready pull request and `In Progress` for a draft one or an assignee, which is `wf_core.stage_drift_target`, the same rule `preflight --fix` repairs `stage-drift` with; `In Review` for `In Progress` work once a ready pull request closes it; `Backlog` (or `Blocked`, if an edge is still open) when it sits in `In Progress` or `In Review` with no assignee, no `refs/claims/issue-N` and no open pull request; `Blocked` when it is blank or `Backlog` with an open blocked-by edge and nobody has started it; and, when it is `Blocked` and every blocker has closed, `Backlog`, or straight to where the started rule puts it; and `Backlog` for any open issue whose `Stage` is still blank after those rules, so no card sits under "No Stage". The plugin itself still treats a blank `Stage` as available; only the sync writes it.

It never changes `Parked`, `Needs refinement`, `Needs attention` or `Non-code`, and it never clears a `Blocked` that has no blocked-by edge, because a person set that. A claim ref it cannot read counts as held, so an unreadable lock never releases somebody's work. For the same reason a blocked-by edge it cannot read counts as open, and an issue with more edges than one page reads is left as it is unless an open one was seen. Every result is a fixed point, so a second run over unchanged issues writes nothing.

The output is **totals only** (`repos`, `repos_with_boards`, `repos_failed`, `claims_unread`, `issues_read`, `cards_added`, `cards_failed`, `stages_set`, `stages_failed`, `stages_by_value`). A workflow's logs are public on a public repository, so no repository name, issue number, title or error text is printed. `--dry-run` counts what would change and writes nothing. It exits 0 when everything landed, 24 (`partial`) when any repository could not be read or any write failed, 21 when the org has no `Stage` field, and 20 when the org cannot be read at all.

**Setting up the workflow.** It authenticates as a GitHub App, so its writes do not depend on anybody's personal token:

1. Create a GitHub App owned by the organisation, with repository permissions *Issues: read and write*, *Contents: read* and *Pull requests: read*, and organisation permissions *Projects: read and write* and *Issue fields: read*. *Metadata: read* is added automatically. This set was confirmed by a passing run on this organisation: field values are written through the Issues permission, and *Contents: read* is what lets it read claim refs on a private repository.
2. Install it on every repository the sync should cover.
3. Add the App's id as the `BOARD_SYNC_APP_ID` Actions secret and its private key as `BOARD_SYNC_PRIVATE_KEY`, on this repository.
4. Run the workflow once by hand (*Actions* → *Board sync* → *Run workflow*) and check the totals.

The workflow is triggered only by `schedule` and `workflow_dispatch`. It never runs on `pull_request` or `pull_request_target`, so a fork cannot reach the secrets.

## Claim outcomes vs. environment errors

A claim push that fails is only a **lost claim** (a rival got there first) when the `refs/claims/<target>` ref actually exists on the remote afterward. `acquire_claim` probes with `git ls-remote`; if the ref is absent the push failed for another reason — no write access, auth, or network — and the picker emits `status: error` rather than walking the pool and reporting a phantom `all-blocked`. So "nothing to pick" always means the backlog is genuinely empty, never that claims could not be written.

There is no inline fallback. The markdown procedures these commands replaced have been deleted, so a call site that cannot run `wf` fails with a message naming the missing prerequisite rather than quietly running a second implementation that nothing tests.
