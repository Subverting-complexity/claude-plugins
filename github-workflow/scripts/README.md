# `wf` — programmatic workflow picker

`wf` collapses the mechanical "select the next story, claim it, validate it" loop into a single process call that returns one already-claimed work item as JSON. It exists so the workflow commands don't have to drive a dozen sequential `gh` round-trips through the model on the hot path.

The selection rules are **not** duplicated here: the pure decision logic lives in [`wf_core.py`](wf_core.py) (priority sort, mode/refinement/gating filters, dependency parsing, branch naming), which is the single canonical, offline-testable encoding of what the `templates/` describe in prose. The offline suite (`tests/test_decision_logic.py`) imports that module directly, so the rules the CLI runs are the rules the tests check — no second copy to drift. [`wf.py`](wf.py) is the thin I/O shell that talks to `gh`/`git` around that core.

## Commands

```bash
# One-time bootstrap: pin a dedicated Python virtualenv (reused thereafter)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" setup

# Claim the next story (Priority field → lowest number → atomic claim), print it
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick

# …also move the board to In Progress and create/check out the branch
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --checkout

# Target one specific issue instead of auto-selecting (same claim/validate;
# auto-closes it + moves it to Done if a merged PR already resolved it)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue 42 --checkout

# After merging a PR: close any still-open linked issue and move it to Done,
# then release whatever that merge freed
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" post-merge --pr 123

# Release the blocked issues whose dependencies have all closed (--dry-run reports)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" unblock --dry-run

# Claim the next PR of mine that needs review feedback addressed (code-review)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" update-next --checkout

# Claim the next PR that needs reviewing (code-review)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-next --checkout

# Emit the parsed config cache (.claude/wf-config.json) from ClaudeProject.md
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config

# Resolve the org's native issue types + issue fields (cached; --refresh re-queries)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" org-capabilities

# Create or update fully classified issues from a spec file
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply spec.json

# …check the spec against the org and report what would change, writing nothing
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply spec.json --dry-run

# Report open issues missing type, fields or dependency edges (writes a backfill spec)
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

# Mirror an issue's lifecycle onto the board (best-effort, always exit 0)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" board-move 42 --column col-in-review

# The open PRs that close an issue (duplicate detection)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr 42 --exclude-branch feat/42-thing

# Hand finished stories to review: label the PR, move each issue + board, free claims
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" handoff --pr 123 --issue 42 --issue 43
```

Run from the **target repo root** so the CLI can read `ClaudeProject.md` and the git remote.

## The interpreter: a pinned virtualenv

`wf.sh` / `wf.ps1` resolve which Python runs `wf.py` like this:

1. **A dedicated virtualenv**, if `wf.sh setup` has created one. It lives under `${CLAUDE_PLUGIN_DATA}/wf-venv` (the plugin's persistent data dir, which survives plugin updates), with `requirements.txt` installed into it. This is the steady state — pinned, isolated, never affected by PATH.
2. **A probed system Python** otherwise (`python3` verified, then `py -3`, then `python` — the broken Windows `python3` Store shim fails its `--version` probe and is skipped), with a one-line hint to run setup.
3. **Nothing found** → exit 20; the caller falls back to the inline skill.

`wf.sh setup` is idempotent: a valid venv is reused, `--force` rebuilds it. If no Python 3 exists it prints the platform install command and stops (exit 20) — or, with the explicit `--install-python` opt-in, installs system Python via winget/brew/apt first. Wire it via `/github-workflow:setup wf` (or it's offered during full setup, Step 1b).

## Contract

A single JSON object goes to **stdout**; diagnostics go to **stderr**. Every run carries a `status` field and the exit code mirrors it:

| Exit | `status`        | Meaning                                                        |
| ---- | --------------- | -------------------------------------------------------------- |
| 0    | `ok`            | An item was claimed (and checked out, if asked).               |
| 10   | `no-candidates` | The ready pool was empty.                                      |
| 11   | `all-blocked`   | Every candidate was claimed away, blocked, or already resolved.|
| 20   | `error`         | Environment/auth problem (not a repo, no `gh`, no config).     |
| 21   | `no-capabilities` | The org reports no issue types and no fields, or refused to say. |
| 22   | `spec-invalid`  | An `issue-apply` spec is wrong. Nothing was written.           |
| 23   | `verify-failed` | A write was accepted but does not read back. Issues exist.     |
| 24   | `partial`       | Some entries applied, some failed. Re-run to finish.           |
| 25   | `gaps`          | `issue-audit` found issues missing metadata. Nothing written.  |
| 26   | `drift`         | `config-audit` found a configuration problem that breaks work. |
| 27   | `lost`          | `claim` — another agent holds this issue or PR. Change nothing.  |
| 30   | `unsupported`   | Path not in the CLI yet — caller falls back to the skill.      |

Mutations to the **winning** issue (claim, assign, `status-in-progress`) are silent; mutations to **other** issues (returning a dependency-blocked one to `status-blocked`, closing one already resolved by a merged PR — which also moves it to the **Done** board column) are always reported in the `side_effects` array.

## Org capabilities — `org-capabilities`

Resolves what the org can actually classify an issue with: its **enabled native issue types** and every **org issue field** with the option ids needed to write single-select and multi-select values. One GraphQL round trip, cached to `.claude/issue-fields-cache.json`; `--refresh` re-queries and rewrites its own keys while preserving any other key in that file.

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
      "labels": ["priority-high"],
      "fields": {"field-priority": "High", "field-effort": "Medium",
                 "field-origin": "Development"}
    },
    {
      "key": "first-story",
      "title": "Resolve org fields in Python",
      "kind": "story",
      "parent": "epic",
      "blocked_by": [187],
      "fields": {"field-priority": "High", "field-effort": "Medium",
                 "field-type": ["New Feature"], "field-origin": "Development"}
    }
  ]
}
```

| Key | Meaning |
| --- | ------- |
| `key` | A spec-local name, so entries can reference each other before any of them has a number. Optional, but required to be referenced. |
| `number` | An existing issue to update. Absent means create. |
| `title`, `body` | As on GitHub. A create needs a title. A `[BUG]`-style kind prefix is stripped from the title — the native type says that. |
| `body_file` | A path to read the body from, used when `body` is absent. A body is prose — fenced code, backticks, `$`, quotes — and building that into a JSON string by hand in a shell is where bodies get mangled. The spec file keeps saying `body_file` after a write-back; the body is never inlined into it. |
| `kind` | One of `wf_core.NATIVE_TYPE_MAP`'s keys (`story`, `bug`, `epic`, `spike`, …). Supplies both the native type and a default `Classification`. |
| `type` | An explicit native type name, overriding what `kind` implies. |
| `labels` | Purpose keys or literal names; resolved through the project's label map. A `type-*` label is dropped — the native type classifies the issue. A create writes only what survives that, so an entry with no `labels` gets no priority label. That does not hide it from `pick` — the pool is the board's Backlog column — but it does drop it to the bottom of the order. The command says so on stderr. |
| `parent` | An issue number, or another entry's `key`. |
| `blocked_by` | A list of issue numbers and/or `key`s. |
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

- **A missing mandatory field** — Priority, Effort, Classification or Origin — exits 22 naming the issue and the field. That is the blank-metadata failure this command exists to stop. The rule is scoped to those four rather than every field the org defines: requiring Start date, Target date, Parent and Status reason on every issue would be wrong. `wf_core.MANDATORY_FIELD_KEYS` is the list.
- **A placeholder** (`TODO`) counts as missing, so an audit's proposal cannot quietly pass as a value.
- **A dependency cycle** within the spec exits 22 before anything is written, and so does a **parent cycle** — a different fault, and equally unresolvable.
- **A label or referenced issue that does not exist** in the repo exits 22, named, before the first mutation.
- **A field this org does not define** is skipped, not an error — an org is allowed fewer fields than the default inventory. It is reported once for the run on stderr, not once per issue.
- **A refused capability read** exits 21 rather than falling back to labels, for the reason `org-capabilities` gives above.

### A dependency is an edge and nothing else

A `blocked_by` becomes a native `addBlockedBy` edge. It used to become a `## Dependencies` section in the body as well, and the two drifted apart on nine of the fourteen issues carrying both on one real backlog — the prose stale every time. Prose is not parsed now, in any command: a body naming a blocker with no edge behind it is not blocked.

### Every issue lands in the lane its own state names

After the edges are written, `issue-apply` puts each issue where it belongs and moves its board card to match. Nothing did this before, so a spec could write an edge and leave the issue with no lifecycle label at all, which put work whose dependency had not been built yet straight into `pick`'s pool.

| The issue is | Label | Board column |
| --- | --- | --- |
| labelled `browser-agent` or `human-required` | `status-non-code` | Non-code |
| pointing at least one open edge | `status-blocked` | Blocked |
| neither | nothing | (unchanged) |

Scope wins over a dependency. The scope is a property of the work and survives every blocker closing, so an issue that is both has to end up in the lane no sweep releases it from.

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
| `missing-field` | One of the four mandatory fields (`wf_core.MANDATORY_FIELD_KEYS`) this issue holds no value for. |
| `type-contradiction` | The native type disagrees with a legacy `type-*` label or `[BUG]`-style title prefix the issue still carries. Reported so the stale one can be removed; neither is written any more. |
| `classification-contradiction` | The `Classification` value cannot be true of the declared kind — a story classified `Bug Fix`, a bug classified `New Feature`. |
| `scope-conflict` | Both scope labels on one issue, so no single party owns it. |
| `scope-prefix` | The `[Manual] `/`[Browser] ` title prefix and the scope label disagree, or one is present without the other. |
| `scope-lifecycle` | Scoped work with no `status-non-code` label, so the picker will offer it to a code agent — or that label with no scope label, so nothing says who should do it. |
| `missing-parent` | `--parents` only. The body says it is part of an issue and GitHub shows it as free-standing. |
| `parent-closed` | `--parents` only. The parent the body names is not open. |
| `parent-differs` | `--parents` only. The body names one parent and the hierarchy has another. Reported, never changed. |

`Classification` is checked for **incompatibility**, not for agreement (`wf_core.INCOMPATIBLE_CLASSIFICATIONS`). It is a multi-select describing what the work touches, so a story classified `Documentation`, `Performance` or `Integration` is telling the truth and only a defect classification — `Bug Fix`, `Regression` — contradicts it, and vice versa for a bug. Requiring agreement instead produced false positives on every issue that had been classified carefully.

A `[DEBT]` issue typed `Feature` is **not** a type contradiction on an org whose types are GitHub's five defaults: none of them can express tech debt, which is precisely what `Classification` is for. An org that has added a `Chore` type is a different case, and `wf_core.NATIVE_TYPE_PREFERENCES` is where that is said: `tech debt` and `chore` become `Chore` where the org has one, and the `Feature` default stands where it does not. Adding a preference has a consequence beyond the audit, so read `NATIVE_MAINTENANCE_TYPES` with it — a type that is not in that set cannot be picked by `execute mode=maintenance` at all.

### Relationships

One gap above comes from body prose, and it is worth understanding before trusting a proposal.

**A parent is a native relationship, not the `Parent` field.** An issue whose first line says `Part of the Cadence Plus epic (#959)` and which GitHub renders as free-standing is invisible as a child: the epic shows no sub-issues and nothing reports that the two disagree. `wf_core.parse_parent` reads a fixed set of phrasings in precedence order, and an issue that **already has** a parent is left alone even when the body names a different one, because a deeper parent is usually the more specific truth and reparenting would flatten a hierarchy somebody built on purpose.

This one is **opt-in**, and the reason is worth stating rather than treating as caution. A story created through `feature-discovery` carries `"parent"` in the spec that creates it, so on a repo whose issues all arrive that way, parsing the sentence back out of the body only re-derives what the pipeline already knew, and every issue that politely repeats its epic in the first line shows up as a gap. Where the prose is the only record — a backlog written before any of this existed, or an issue typed into the GitHub UI — pass `--parents` and the three gaps above come back.

The parent is the **only** thing read out of a body. Dependencies used to be read the same way, and it went badly enough to be worth recording: the parser missed a `## Blocked by` heading whose references sat on the next line, and read "Nothing. This **was** blocked by #980" as a live dependency — wrong in both directions on the same backlog, and each fault silently invisible. A sentence is not structured data and no amount of regex makes it so, so the audit no longer proposes an edge from one. What it checks in that slot instead is **scope**, where the three signals genuinely can be compared against each other.

## Configuration drift — `config-audit`

Three things describe how a project works, and they drift apart quietly: `ClaudeProject.md`, the labels the repo actually carries, and the org's issue types and fields. Nothing errors when they disagree. A label gets renamed and a call site keeps applying the old name — `gh` refuses the edit and the issue stays where it was. An issue type stops being pinned to a field and every value written to it is stored correctly and shown nowhere.

`config-audit` compares all three. It is what `skills/preflight` runs, and it never writes.

### What it reports

| Finding | Level | Meaning |
| ------- | ----- | ------- |
| `config-section` | critical | `ClaudeProject.md` is missing a section the plugin reads, so its values fall back to defaults silently. |
| `label-missing` | critical | An instruction file tells an agent to apply a label the repo does not have. |
| `config-label` | critical | The project's own label map names a label the repo does not have. |
| `field-unpinned` | critical | An enabled issue type is not pinned to a field the tooling writes. |
| `label-drift` | warning | Two live labels mean the same thing (`priority:medium` beside `priority-medium`, `bug` beside `type-bug`). |
| `pin-asymmetry` | warning | A field some enabled types pin and others do not. |
| `field-unmapped` | warning | An org field no purpose key resolves to, so nothing ever sets it. |
| `board-column` / `board-title` | warning | The recorded board snapshot no longer matches the live board. |
| `pin-unknown` | warning | `IssueType.pinnedFields` could not be read, so pinning is unverified. |

### Why the split is where it is

One question decides it: does the workflow produce a **wrong** result, or a **degraded** one? A missing section or a label that does not exist produces wrong behaviour — the command runs, GitHub accepts or refuses it, and the outcome is not what anyone asked for. An org field nobody mapped or a stale board snapshot degrades gracefully, so it warns and the run continues.

Pin asymmetry is the case that makes the distinction concrete. `Epic` is not pinned to `Parent`, and that is correct — an epic *is* the parent. So a field that some enabled types carry and others do not can only ever be a warning, and only the four fields the tooling actually writes (`wf_core.MANDATORY_FIELD_KEYS`) are ever a failure.

The fix text is written to be reported verbatim. For an unpinned field it names the type, the fields, and the form: org settings → Planning → Issue fields → the field's edit form → "Pin to issues". A paraphrase loses the only part that tells someone where to click.

### Placeholders are not labels

The label scan reads `--add-label`, `--remove-label` and `--label` out of every `.md` file under the plugin root (`--scan` points it elsewhere) and checks the names against the repo. It only ever checks **literals**. These files write "the label you resolved" as `{status_ready_label}`, `<verdict-label>` or a bare `X` in an example, and none of those is a claim about any particular label.

### Cost

Two round trips: one repo query carrying the labels and the board together, and one org query for the pinning. Org capabilities come from the cache. `--offline` runs only the checks that need no network, `--quiet` drops the per-finding detail and keeps the exit code, and exit 26 makes it usable as a CI gate.

## Settling a merged PR — `post-merge`

`post-merge --pr <n>` makes "the story is closed and off the board" a deterministic step instead of trusting GitHub. It reads the PR's own `closingIssuesReferences`, **force-closes** any of those issues still open (GitHub only auto-closes on a default-branch merge of a recognised keyword — a chained-story PR or an unparsed reference leaves it open), **clears any open-state lifecycle label** the issue still carries (e.g. a `status-in-progress` or `status-in-review` left behind when GitHub auto-closed it), and moves every linked issue to the **Done** column. Each settled issue is reported with `closed_now`, `lifecycle_label_cleared`, and `board_moved_done`. It refuses (`status: not-merged`, exit 11) on a PR that has not actually merged, so it is safe to call on the queued `--auto` path. Add `--issue <N>` (repeatable) to settle a reference GitHub did not parse. `code-review`'s auto-merge step calls this after a successful immediate merge.

## Releasing what a merge freed — `unblock`

Nothing did this. `post-merge` settles only the issues a pull request *closes*, so one that closes none returns `settled: []` — which reads as a finished run and is not: whatever was waiting keeps `status-blocked`, and a blocked issue is invisible to the picker.

`unblock` reads every open issue carrying the blocked label and sorts it five ways. Only the first two write anything.

| Bucket | What it means | What it does |
| --- | --- | --- |
| `released` | every native blocked-by edge points at a closed issue | removes the label, moves the card to Backlog, comments |
| `rescoped` | browser or human work sitting in the blocked lane | swaps the label for `status-non-code`, moves the card to Non-code, comments |
| `held` | at least one blocker is still open | nothing |
| `partials` | held, but a blocker merged something in the last 14 days | reports it, never acts |
| `no_edges` | labelled blocked with no dependency edge at all | counts them |

**The scope check runs before the edge check, and that order is the safety property.** Both issues the first real run would have released were `[Manual]` device passes whose blockers happened to close; releasing them would have put a job needing a phone in someone's hand into the code agent's pool.

**Nothing is released without at least one edge.** Two thirds of one real backlog's blocked issues have none, and they are waiting on a bank account, a device pass, a store upload. Reading "no open blockers" as "release" would put every one of them in front of an agent that cannot do any of them.

**The comment is load-bearing.** A bare label removal reads to the next agent as damage to repair, and one repaired exactly this: three issues released by hand were re-blocked two minutes later by a concurrent session that took the removal for automation stripping labels.

`--dry-run` reports without writing; `--issue N` (repeatable) narrows it. `post-merge` runs the sweep and returns it as `unblocked` whether or not it settled anything (`--no-unblock` opts out), and `pick` runs it when it finds nothing to pick.

## The three pickers

| Subcommand     | Pool                                              | Claims          | Marker applied        | Used by      |
| -------------- | ------------------------------------------------- | --------------- | --------------------- | ------------ |
| `pick`         | Ready, unassigned issues                          | `issue-{n}` ref | `status-in-progress`  | execute |
| `update-next`  | My open PRs with actionable review feedback       | `pr-{n}` ref    | `updating` (keeps the feedback label) | code-review |
| `review-next`  | Open PRs labelled `needs-review` / `needs-re-review` | `pr-{n}` ref | `reviewing` (removes prior) | code-review |

All share the same atomic claim/checkout core and JSON contract. `--checkout` creates/checks out the branch (`pick`) or runs `gh pr checkout` (PR pickers).

## Scope / deferrals

- **`pick`** — `--mode story` / `feature` / `maintenance`, reading the board's Backlog column as the pool. One GraphQL query (`fetch_issue_facets`) reads the native type, the `Priority` field and the `Classification` field for the open backlog, and the pool is ordered by `Priority` — `Urgent` → `High` → `Medium` → `Low`, then lowest issue number. An issue with no `Priority` value is ordered by its `priority-*` label, which is the only surviving label fallback. **Type has none**: `feature` and `maintenance` filter on the native `issueType` alone, so an issue the org has not typed — or a `Feature` it left unclassified — is out of the pool and named on stderr rather than guessed at from a `type-*` label or a `[PREFIX]` title. An org whose backlog carries no native type at all cannot answer those modes and `pick` exits `no-capabilities` (21) saying so; `--mode story` is unaffected. Membership of the pool is the board's answer rather than a label's: an issue is in it because its card sits in `Backlog` and nobody is assigned. Every other state has a column of its own, so an issue in one is already out of the pool and no label has to say so. `needs-refinement` is the one label still filtered, for a project that applies it without moving the card.
- **`review-next`** — the *label-driven* subset. A PR whose head SHA changed since its last review (needing review without a label) is **not** detected here, so `code-review` treats `no-candidates` as non-conclusive and falls back to its inline SHA check. Pass `--no-claim` for a read-only review (no push access): it selects the next PR without writing a claim ref or applying the `reviewing` marker, and the JSON reports `claimed: false`.

## Locks, board and handoff

These five commands replaced the markdown procedures the skills used to follow step by step. Each is one call with a defined exit code, so a call site states the command and what to do about each outcome rather than describing the mechanism.

### `claim` / `claim-release` / `claim-reap`

`claim --issue N` or `claim --pr N` takes `refs/claims/{issue,pr}-N` — a server-side compare-and-swap, which is what makes it safe between two agents running under the same GitHub identity, where a shared label cannot exclude a rival.

The ref is the lock but it is ephemeral, so on success the command also advertises ownership where a later picker will look: an issue is assigned to `@me` and moved to `status-in-progress`; a PR swaps `needs-review` for `reviewing`. Pass `--no-marker` to take the lock silently. The marker is best-effort — the lock is already held, and failing to advertise it is worth a warning, not giving the item back.

| Exit | Meaning |
| ---- | ------- |
| 0 | You hold it. |
| 27 | Another agent holds it. Make **no** changes: move to the next item, or report and stop on a named one. |
| 20 | A broken environment, not a rival — usually no write access to `refs/claims/*`. Never fall back to a bare label as a "soft" claim; that reintroduces the race the ref removes. |

`claim-release` takes repeatable `--issue` / `--pr` and is idempotent — releasing a ref that is already gone is not a failure, so it always exits 0.

`claim-reap` frees the refs a crash left behind. It always exits 0 and returns three lists: `reaped` (freed — the issue is closed, no longer in progress, or already has a PR; the PR is closed, merged, or open with no review under way), `suspect` (deliberately left, because the evidence does not say the work stopped) and `skipped` (younger than `--threshold`, default 4 hours). `--dry-run` reports the verdicts without freeing anything. The judgement is `wf_core.reap_verdict`, which is offline-tested; everything in `wf.py` around it is I/O.

### `board-move`

`board-move N --column col-in-review` mirrors an issue's lifecycle onto the board. It takes a column **purpose key** (`col-backlog`, `col-in-progress`, `col-in-review`, `col-blocked`, `col-non-code`, `col-refinement`, `col-parked`, `col-attention`, `col-done`), resolves the option id live by column name so a stale snapshot self-heals, verifies the board's identity **and the column's existence before it adds the card**, and adds the issue if it is not on the board yet. Resolving first is what stops an issue destined for a column the board does not have being added and then stranded in `No Status`.

It **always exits 0**, including when no board is configured. A board mirrors the labels and is never the source of truth, so a failed move is something to report, never something to stop for: read `moved` and `reason`.

### `sibling-pr`

`sibling-pr N` returns the open PRs that close issue N, oldest first, using GitHub's own parse of closing references rather than a free-text body search. `--exclude-branch` drops your own PR, so anything returned is someone else's. Exit 0 with `found: 0` is the expected answer before starting work; exit 20 means the lookup failed, which is not the same as "no duplicate" and must be reported as such.

### `handoff`

`handoff --pr P --issue N [--issue M …]` ends a build: it labels the PR `claude-authored` plus the review-state entry label, then for each issue swaps `status-in-progress` for `status-in-review`, moves its board item to In Review, and releases its claim ref. Finally it deletes `.claude/plan.md`, `preflight-passed.txt` and `label-cache.json`. `--gate-failed` enters review as changes-requested rather than needs-review.

It **always exits 0**: once the pull request exists, none of this is a reason to stop. Read `pr_labelled` and the per-issue `relabelled`, `board_moved` and `board` reason instead. A failure on one issue does not affect the others.

## Claim outcomes vs. environment errors

A claim push that fails is only a **lost claim** (a rival got there first) when the `refs/claims/<target>` ref actually exists on the remote afterward. `acquire_claim` probes with `git ls-remote`; if the ref is absent the push failed for another reason — no write access, auth, or network — and the picker emits `status: error` rather than walking the pool and reporting a phantom `all-blocked`. So "nothing to pick" always means the backlog is genuinely empty, never that claims could not be written.

There is no inline fallback. The markdown procedures these commands replaced have been deleted, so a call site that cannot run `wf` fails with a message naming the missing prerequisite rather than quietly running a second implementation that nothing tests.
