# `wf` — programmatic workflow picker

`wf` collapses the mechanical "select the next story, claim it, validate
it" loop into a single process call that returns one already-claimed work
item as JSON. It exists so the workflow commands don't have to drive a
dozen sequential `gh` round-trips through the model on the hot path.

The selection rules are **not** duplicated here: the pure decision logic
lives in [`wf_core.py`](wf_core.py) (priority sort, mode/refinement/gating
filters, dependency parsing, branch naming), which is the single canonical,
offline-testable encoding of what the `templates/` describe in prose. The
offline suite (`tests/test_decision_logic.py`) imports that module directly,
so the rules the CLI runs are the rules the tests check — no second copy to
drift. [`wf.py`](wf.py) is the thin I/O shell that talks to `gh`/`git`
around that core.

## Commands

```bash
# One-time bootstrap: pin a dedicated Python virtualenv (reused thereafter)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" setup

# Claim the next story (priority → lowest number → atomic claim) and print it
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick

# …also move the board to In Progress and create/check out the branch
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --checkout

# Target one specific issue instead of auto-selecting (same claim/validate;
# auto-closes it + moves it to Done if a merged PR already resolved it)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue 42 --checkout

# After merging a PR: close any still-open linked issue and move it to Done
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" post-merge --pr 123

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

# Report configuration and label drift (what preflight runs)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config-audit

# …file-level checks only, no network
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config-audit --offline
```

Run from the **target repo root** so the CLI can read `ClaudeProject.md`
and the git remote.

## The interpreter: a pinned virtualenv

`wf.sh` / `wf.ps1` resolve which Python runs `wf.py` like this:

1. **A dedicated virtualenv**, if `wf.sh setup` has created one. It lives
   under `${CLAUDE_PLUGIN_DATA}/wf-venv` (the plugin's persistent data dir,
   which survives plugin updates), with `requirements.txt` installed into
   it. This is the steady state — pinned, isolated, never affected by PATH.
2. **A probed system Python** otherwise (`python3` verified, then `py -3`,
   then `python` — the broken Windows `python3` Store shim fails its
   `--version` probe and is skipped), with a one-line hint to run setup.
3. **Nothing found** → exit 20; the caller falls back to the inline skill.

`wf.sh setup` is idempotent: a valid venv is reused, `--force` rebuilds it.
If no Python 3 exists it prints the platform install command and stops
(exit 20) — or, with the explicit `--install-python` opt-in, installs system
Python via winget/brew/apt first. Wire it via
`/github-workflow:setup wf` (or it's offered during full setup, Step 1b).

## Contract

A single JSON object goes to **stdout**; diagnostics go to **stderr**. Every
run carries a `status` field and the exit code mirrors it:

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
| 30   | `unsupported`   | Path not in the CLI yet — caller falls back to the skill.      |

Mutations to the **winning** issue (claim, assign, `status-in-progress`) are
silent; mutations to **other** issues (returning a dependency-blocked one to
`status-blocked`, closing one already resolved by a merged PR — which also
moves it to the **Done** board column) are always reported in the
`side_effects` array.

## Org capabilities — `org-capabilities`

Resolves what the org can actually classify an issue with: its **enabled
native issue types** and every **org issue field** with the option ids needed
to write single-select and multi-select values. One GraphQL round trip, cached
to `.claude/issue-fields-cache.json`; `--refresh` re-queries and rewrites its
own keys while preserving any other key in that file.

The command is GraphQL and not REST because REST
(`/orgs/{org}/issue-fields`) returns `null` for every option id, which makes
those fields readable but not writable.

Output beyond `type_map` and `field_map`:

- `owner_kind` — `organization` or `user`.
- `resolved_fields` — purpose key → the concrete field name that exists here.
- `missing_fields` — the purpose keys that do not resolve, each with the name
  that was looked for.
- `cached` — whether this run answered from the cache.

Four outcomes a caller must tell apart:

| Situation | Exit | `status` |
| --------- | ---- | -------- |
| Types and/or fields resolved | 0 | `ok`, `owner_kind: organization` |
| A user-owned repo — issue types are an org-only feature | 0 | `ok`, `owner_kind: user` |
| The account may not read a capability | 21 | `no-capabilities`, with `denied` |
| The org resolves but reports neither types nor fields | 21 | `no-capabilities` |

The last two are the cases that did not exist before, and both are the same
underlying mistake: treating "we could not find out" as "there is nothing
there". An under-scoped token, an expired one, or an account without org
access all look identical to an org that has simply not enabled issue types,
and carrying on regardless is how a repo ends up creating issues with blank
metadata and no error anywhere.

The denial case is worth calling out because GraphQL reports it *partially*:
GitHub returns the issue fields the account may read alongside a `FORBIDDEN`
error for the issue types it may not, so a naive read sees fields, sees no
types, and concludes the org is not type-capable. `wf` reads the error list
too, reports the denied paths in `denied`, and — importantly — **does not
cache the result**, because a cached `type_capable: false` that really meant
"not allowed to look" would make every later run fall back to labels in
silence. The usual fix is `gh auth switch`; `gh auth status` shows which
account is active and what scopes it has.

Field **names** are overridable per project in `ClaudeProject.md` →
`## Issue Types & Fields`; the value maps behind them are Python data in
`wf_core.py` (`NATIVE_TYPE_MAP`, `CLASSIFICATION_OPTIONS`,
`FIELD_NAME_DEFAULTS`, `FIELD_DATA_TYPES`, `PRIORITY_FIELD_OPTIONS`,
`EFFORT_FIELD_OPTIONS`, `ORIGIN_FIELD_OPTIONS`).

## Classified issues — `issue-apply`

`issue-apply <spec.json>` creates or updates issues carrying everything at
once: native type, every org field value, labels, parent, and blocked-by
edges. It exists because doing that by hand was ten-odd round trips per issue,
each described as optional — and the measured result of "optional" in one
consuming repo was 7 typed issues out of 82, no field values at all, and no
error anywhere. So the command is deliberately strict.

A spec can describe a whole epic tree, and one invocation applies all of it.

### The spec

A JSON object with an `issues` list (a bare list is accepted too). An entry
with a `number` is an update; one without is a create.

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
| `title`, `body` | As on GitHub. A create needs a title. |
| `kind` | One of `wf_core.NATIVE_TYPE_MAP`'s keys (`story`, `bug`, `epic`, `spike`, …). Supplies both the native type and a default `Classification`. |
| `type` | An explicit native type name, overriding what `kind` implies. |
| `labels` | Purpose keys or literal names; resolved through the project's label map. |
| `parent` | An issue number, or another entry's `key`. |
| `blocked_by` | A list of issue numbers and/or `key`s. |
| `fields` | Purpose key → value. Names resolve through `ClaudeProject.md`'s `## Issue Types & Fields`, then `wf_core.FIELD_NAME_DEFAULTS`. |

Created numbers are **written back into the spec file**, which is what makes a
re-run after a partial failure complete the remainder rather than creating
everything a second time.

### How a tree is applied

Aliased multi-mutations let many issues be created in one request, but an alias
cannot reference another alias's output — so a child's `parentIssueId` only
exists once its parent's request has come back. The command therefore works in
**hierarchy levels**, parents before children, and puts the dependency edges
last:

| Phase | Requests | What happens |
| ----- | -------- | ------------ |
| Prerequisite | 1 query | The repository id, every label id, and the node id of every issue the spec references but does not create — one lookup, not three. |
| Per level | 1 mutation per `wf_core.BATCH_MAX_NODES` entries | Every issue at that level is created in one aliased `createIssue`. |
| Link | 1 mutation per `BATCH_MAX_NODES` operations | Every `blocked_by` edge, plus any body whose `## Dependencies` section could not be written at create time. |

Edges come last so an edge may point at **any** issue in the tree regardless of
level, including one created in the final batch.

An epic with three features and nine stories is therefore **four mutations**
(three levels plus the link phase) on top of the one prerequisite lookup, rather
than the hundred-odd round trips a per-issue loop would take. There is a test
that asserts exactly that count against a recorded transport, because it is the
kind of property that silently regresses.

Each `createIssue` asks for the full issue selection in its own payload, so
GitHub returns the issue **as it now holds it** — verification comes back with
the create rather than costing a round trip of its own.

Updates are not batched. An update has to read the issue first to decide what
differs, and the levels only exist to make creation possible; a re-applied spec
is dominated by no-ops in any case.

### What it refuses, and why

Everything decidable offline is decided before the first mutation, because a
half-applied epic tree is far harder to reason about than a refused spec:

- **A missing mandatory field** — Priority, Effort, Classification or Origin —
  exits 22 naming the issue and the field. That is the blank-metadata failure
  this command exists to stop. The rule is scoped to those four rather than
  every field the org defines: requiring Start date, Target date, Parent and
  Status reason on every issue would be wrong. `wf_core.MANDATORY_FIELD_KEYS`
  is the list.
- **A placeholder** (`TODO`) counts as missing, so an audit's proposal cannot
  quietly pass as a value.
- **A dependency cycle** within the spec exits 22 before anything is written,
  and so does a **parent cycle** — a different fault, and equally unresolvable.
- **A label or referenced issue that does not exist** in the repo exits 22,
  named, before the first mutation.
- **A field this org does not define** is skipped, not an error — an org is
  allowed fewer fields than the default inventory. It is reported once for the
  run on stderr, not once per issue.
- **A refused capability read** exits 21 rather than falling back to labels,
  for the reason `org-capabilities` gives above.

### Dependencies are written twice, on purpose

A `blocked_by` becomes both a native `addBlockedBy` edge and a `## Dependencies`
section in the issue body. The edge is what GitHub's UI and the audit read; the
body prose is what `wf_core.parse_dependencies()` reads to decide when an issue
unblocks, so dropping it would silently break auto-unblocking.

### Every write is read back

An accepted mutation is not a changed value — an unpinned field or a
permission that stops short of writing both return success. So the command
compares every issue against the spec and exits 23 `verify-failed` naming each
mismatch. The issues still exist; the command is telling you the metadata did
not land.

### Partial failure is reported, not swallowed

A batch answers a partial failure with the aliases that worked and an error
carrying the path of each one that did not, so one bad entry does not take its
neighbours down with it. The command exits 24 `partial`, names the entries that
failed, and writes the numbers of the ones that landed back into the spec —
which turns them into no-op updates, so re-running the same spec completes the
remainder rather than creating anything twice.

## Finding the gaps — `issue-audit`

`issue-audit` reads every open issue in a repo and reports what is missing. It
exists because nothing did: the classification gap went unnoticed for months
across 82 issues, of which 7 were typed and none carried a field value, with no
error anywhere. It also produces the input to the backfill, so the unclassified
remainder does not have to be handled one at a time.

It **never writes**. Both write transports are stubbed out in its tests to
prove it.

### What it reports

| Gap | Meaning |
| --- | ------- |
| `missing-type` | The org has issue types enabled and this issue has none. |
| `missing-field` | An org field this issue holds no value for. |
| `type-contradiction` | The native type disagrees with the `type-*` label or the title prefix. |
| `classification-contradiction` | The `Classification` value disagrees with them. |
| `missing-edge` | The body's `## Dependencies` claims a blocker with no native edge. |
| `dependency-closed` | The body depends on an issue that is not open. |
| `dependency-overflow` | More than `wf_core.DEP_LIMIT` dependencies — an epic, not a story. |

A `[DEBT]` issue typed `Feature` is deliberately **not** a type contradiction.
GitHub's five native types cannot express tech debt, which is precisely what
`Classification` is for, so the contradiction to look for there is in the field.

### The spec it writes

Every issue with a gap becomes an `issue-apply` entry in
`.claude/issue-audit-spec.json` (override with `--out`). Two rules govern it:

- **Inferred dependency edges are proposed, never written.** Body prose is not
  reliable enough to build a dependency graph from unattended, so a proposed
  edge sits in the spec for a person or an agent to review.
- **What cannot be inferred becomes `TODO`.** `issue-apply`'s mandatory-field
  check treats a placeholder as missing, so the spec is refused until someone
  fills it in. Silence must not pass for a value.

Priority is inferred from the issue's own `priority-*` label and Classification
from its declared kind. Effort and Origin are not guessable from an existing
issue, so they come out as placeholders. Situational fields — Start date,
Target date, Parent, Status reason — are *reported* when empty but never
proposed: a start date nobody set is not a value a backfill should invent.

### Running it as a check

The command exits 25 when gaps exist, so it works as a gate. `--quiet` drops
the per-issue detail and keeps the exit code and the counts. `--limit` and
`--since` narrow the scan so a large backlog can be worked through in slices,
and `--repo owner/name` points it at another repo in the org without
reconfiguring anything — issue types and fields are org-scoped, so adoption can
proceed one repo at a time from a single working copy.

> Deleting an org issue field permanently destroys every value set on it, in
> every repo. Before any such change, run this audit with `--repo` against each
> repo that matters and read the values first.

## Configuration drift — `config-audit`

Three things describe how a project works, and they drift apart quietly:
`ClaudeProject.md`, the labels the repo actually carries, and the org's issue
types and fields. Nothing errors when they disagree. A label gets renamed and a
call site keeps applying the old name — `gh` refuses the edit and the issue
stays where it was. An issue type stops being pinned to a field and every value
written to it is stored correctly and shown nowhere.

`config-audit` compares all three. It is what `skills/preflight` runs, and it
never writes.

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

One question decides it: does the workflow produce a **wrong** result, or a
**degraded** one? A missing section or a label that does not exist produces
wrong behaviour — the command runs, GitHub accepts or refuses it, and the
outcome is not what anyone asked for. An org field nobody mapped or a stale
board snapshot degrades gracefully, so it warns and the run continues.

Pin asymmetry is the case that makes the distinction concrete. `Epic` is not
pinned to `Parent`, and that is correct — an epic *is* the parent. So a field
that some enabled types carry and others do not can only ever be a warning, and
only the four fields the tooling actually writes
(`wf_core.MANDATORY_FIELD_KEYS`) are ever a failure.

The fix text is written to be reported verbatim. For an unpinned field it names
the type, the fields, and the form: org settings → Planning → Issue fields →
the field's edit form → "Pin to issues". A paraphrase loses the only part that
tells someone where to click.

### Placeholders are not labels

The label scan reads `--add-label`, `--remove-label` and `--label` out of every
`.md` file under the plugin root (`--scan` points it elsewhere) and checks the
names against the repo. It only ever checks **literals**. These files write "the
label you resolved" as `{status_ready_label}`, `<verdict-label>` or a bare `X`
in an example, and none of those is a claim about any particular label.

### Cost

Two round trips: one repo query carrying the labels and the board together, and
one org query for the pinning. Org capabilities come from the cache. `--offline`
runs only the checks that need no network, `--quiet` drops the per-finding
detail and keeps the exit code, and exit 26 makes it usable as a CI gate.

## Settling a merged PR — `post-merge`

`post-merge --pr <n>` makes "the story is closed and off the board" a
deterministic step instead of trusting GitHub. It reads the PR's own
`closingIssuesReferences`, **force-closes** any of those issues still open
(GitHub only auto-closes on a default-branch merge of a recognised keyword —
a chained-story PR or an unparsed reference leaves it open), **clears any
open-state lifecycle label** the issue still carries (e.g. a `status-ready`
or `status-in-review` left behind when GitHub auto-closed it), and moves every
linked issue to the **Done** column. Each settled issue is reported with
`closed_now`, `lifecycle_label_cleared`, and `board_moved_done`. It refuses
(`status: not-merged`, exit 11) on a PR that has not actually merged, so it is
safe to call on the queued `--auto` path. Add `--issue <N>` (repeatable) to
settle a reference GitHub did not parse. `code-review`'s auto-merge step calls
this after a successful immediate merge.

## The three pickers

| Subcommand     | Pool                                              | Claims          | Marker applied        | Used by      |
| -------------- | ------------------------------------------------- | --------------- | --------------------- | ------------ |
| `pick`         | Ready, unassigned issues                          | `issue-{n}` ref | `status-in-progress`  | execute |
| `update-next`  | My open PRs with actionable review feedback       | `pr-{n}` ref    | `updating` (keeps the feedback label) | code-review |
| `review-next`  | Open PRs labelled `needs-review` / `needs-re-review` | `pr-{n}` ref | `reviewing` (removes prior) | code-review |

All share the same atomic claim/checkout core and JSON contract. `--checkout`
creates/checks out the branch (`pick`) or runs `gh pr checkout` (PR pickers).

## Scope / deferrals

- **`pick`** — `--mode story` / `feature` / `maintenance` under all four
  ready-gates (`label`, `none`, `board-column`, `both`), on both
  label-typed and type-capable orgs. On label-typed projects,
  feature/maintenance filter by the `type-*` **label**; on type-capable
  orgs they filter by the native `issueType` field via a single GraphQL
  query (`fetch_native_types`), falling back to label filtering if the
  query fails. The empty-pool auto-ready dependency scan runs inline
  before returning `no-candidates`.
- **`review-next`** — the *label-driven* subset. A PR whose head SHA changed
  since its last review (needing review without a label) is **not** detected
  here, so `code-review` treats `no-candidates` as non-conclusive and falls
  back to its inline SHA check. Pass `--no-claim` for a read-only review
  (no push access): it selects the next PR without writing a claim ref or
  applying the `reviewing` marker, and the JSON reports `claimed: false`.

## Claim outcomes vs. environment errors

A claim push that fails is only a **lost claim** (a rival got there first)
when the `refs/claims/<target>` ref actually exists on the remote afterward.
`acquire_claim` probes with `git ls-remote`; if the ref is absent the push
failed for another reason — no write access, auth, or network — and the
picker emits `status: error` rather than walking the pool and reporting a
phantom `all-blocked`. So "nothing to pick" always means the backlog is
genuinely empty, never that claims could not be written.

Every caller tries `wf` first and falls back to the inline procedure on any
non-`ok` status or a missing interpreter, so behaviour is identical whether
or not `wf` can run.
