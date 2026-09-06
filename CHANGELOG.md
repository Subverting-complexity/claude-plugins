# Changelog

Notable changes to the plugins in this marketplace. Both plugins version
independently; each entry says which one it applies to.

See [README.md](README.md#picking-up-a-new-version) for how to pick up a
new version, and why a stale marketplace cache is the usual reason an
update appears to do nothing.

## github-workflow 6.4.1

Claiming a story with `--checkout` crashed on any org that defines a
`Start date` field, and the start-of-run cleanup could delete tracked
files.

- Fixed: `wf pick --checkout` raised `ValueError: too many values to
  unpack` while stamping the start date, because `set_issue_fields`
  answers three values and two were read. It fired after the claim, the
  label, the assignment and the board move had all landed, so the run
  exited non-zero with no JSON result and looked failed when it had
  succeeded. Nothing showed it until an org defined the field, which is
  what makes the mutation reachable at all.
- Fixed: the board move and the start-date stamp are both best-effort,
  but an exception in either stopped `checkout_branch` from running,
  leaving a claimed story with no branch to work in. Both now report an
  unexpected failure in their own result message and the branch is
  created regardless.
- Fixed: the `execute` and `bulk-execute` start-of-run blocks swept
  `.claude/claim-*.sha` with a plain `rm -f`, which stages the deletion
  of those markers in a project that commits them, and can delete a PR
  claim held by a review session sharing the checkout. The sweep now
  covers untracked `claim-issue-*.sha` only.

## github-workflow 6.4.0 · local-workflow 2.11.0

Consolidation pass across both plugins. No behaviour changes to any
workflow; the changes are to what the instructions say and how much of
it there is.

- Changed: the output standard every skill and command carries is now one
  block naming the three files that govern a reply (how it reads, what it
  contains and in what order, and what must never appear) instead of two
  paragraphs restating them. Roughly 45% shorter, in about 30 files.
- Fixed: `code-review` Step 2 said both "make no changes and move on" and,
  a paragraph later, that a lost claim should be retried against other
  candidates. It now says the first, once. The undefined term "Acquire" is
  gone, and the claim-ordering rule is a heading sentence rather than a
  run-on inside an unrelated exit-code bullet.
- Fixed: `code-review` Step 7 skipped from 7d to 7f, and its "do not fix"
  list sat under *Push* rather than under triage. Renumbered to 7a–7e with
  the exclusions where the triage happens.
- Removed: the runtime-variant compiler in `sync-skills.sh` and
  `sync-skills.ps1` (~190 lines of duplicated logic). It compiled
  `github-workflow/templates/runtime/worktree-hygiene.md`, which nothing
  ever loaded. The rationale it stripped now lives in
  `docs/rationale/worktree-hygiene-rationale.md`, matching every other
  template, and the template itself is 30 lines shorter at runtime.
- Fixed: the instruction-token footprint budgets in CI sat ~48% above what
  the files actually measure, so the gate had been passing vacuously.
  Re-ratcheted to measured + 2%, and the accreted recalibration history
  replaced by one statement of the convention.
- Fixed: `banned-patterns.md` banned words the plugins require as names —
  *harness*, *ecosystem*, *framework*, backlog *refinement*. Names are now
  explicitly exempt; the ban is on reaching for the word as filler.
- Fixed: both plugin READMEs told you to install with `--plugin-dir` and
  said the marketplace was unpublished. `github-workflow`'s claimed 8 slash
  commands (there are 4) and listed its skills twice; `local-workflow`'s
  omitted `debugging`, `doc-writer`, `security-audit` and `preflight`, and
  described six shared skills as local-only.
- Fixed: the shared-skill count (15, was stated as 12), the `ClaudeProject.md`
  skill list, and a dangling path in `docs/rationale/bulk-execute-rationale.md`.
- Changed: the "how to edit a shared skill" procedure was written out in
  three places. `CLAUDE.md` now holds it; `README.md` and
  `_shared-skills/MANIFEST.md` point there.
- Moved: the internal consumer inventory out of the public marketplace
  README into `docs/consumers.md`.

## github-workflow 6.3.0

- Fixed: a capability lookup that came back `NOT_FOUND` was recorded as
  `owner_kind: user`, filing an organisation away as a personal account. GitHub
  returns that error when the signed-in account may not see the org at all, so
  the result was a cache saying the org has no issue types and no fields, with
  no expiry — after which every issue was created with no type, no field values
  and no error anywhere. `NOT_FOUND` now counts as a denial alongside
  `FORBIDDEN` and `UNAUTHORIZED`, and an empty result is only believed when it
  carries the current cache schema, so a cache written by an earlier version
  heals itself on the next run instead of waiting for someone to know about
  `--refresh`.
- Fixed: `issue-audit` reported a `Classification` gap on issues that were
  classified correctly. It required the value to agree with the issue's kind,
  but `Classification` is a multi-select describing what the work touches, so a
  story marked `Documentation` or `Performance` was telling the truth. It now
  reports only genuine incompatibilities — a story classified `Bug Fix`, a bug
  classified `New Feature`.
- Fixed: `issue-audit` checked every org field, including Start date, Target
  date, Parent and Status reason, which nobody sets on most issues. On one
  69-issue backlog that produced 275 findings that no amount of work could
  clear, which made the audit useless as a check. It now checks the four
  mandatory fields only. The same backlog now reports two findings, both real.
- Fixed: an untyped issue was routed by looking its declared kind up in the
  type map, which put `[CHORE]` in feature mode and made `[FEATURE]` and
  `[EPIC]` vanish from every mode. Feature and maintenance now have their own
  explicit kind sets.
- Changed: `issue-apply` says on stderr when a spec creates an issue that names
  no labels. Nothing else supplies them, so such an issue carries no ready-gate
  label and no priority and `pick` will never select it.
- Changed: `setup` gained an `issues` focus and a step that audits the
  backlog's metadata, so `issue-audit` is reachable from a command rather than
  only from the CLI. Its exit-21 guidance now separates "the account may not
  look" from "the org genuinely has none", which are opposite situations that
  read identically.
- Changed: `report-issue` lost a redundant step that re-applied labels the
  previous step had already set, and both of its command samples now include
  the lifecycle label — without it the issue is filed but never picked up.
- Changed: the audit spec path is reported relative to the repository, and
  `.claude/issue-audit-spec.json` is now ignored by git like every other `wf`
  scratch file.

## github-workflow 6.2.1

- Changed: the parent an issue's body claims is now read only under
  `issue-audit --parents`, and a routine audit no longer proposes one. 6.2.0
  added the parsing to backfill a hierarchy that had been written in prose and
  never applied, which it did. Going forward it re-derives something the
  pipeline already knows: `feature-discovery` writes `"parent"` into the spec
  that creates a story, so on a repo whose issues arrive that way every issue
  that names its epic in the first line was reported as a gap carrying a value
  it already had. The capability stays, because a backlog written before any of
  this existed and an issue typed into the GitHub UI still have nowhere else to
  say it — it just has to be asked for. `missing-parent`, `parent-closed` and
  `parent-differs` are `--parents` only.

  The dependency half is deliberately **not** gated. `parse_dependencies` is
  not backfill code at all: `wf pick`, `wf candidates` and the unblock sweep
  read it on every run, and before 6.2.0 it classed four stories on one backlog
  as meta-issues that `execute` could never select, and reported a fifth
  blocked on the strength of a prose mention.

## github-workflow 6.2.0

- Added: `issue-audit` now proposes the **parent** an issue's body claims. An
  issue whose first line says `Part of the Cadence Plus epic (#959)` and which
  GitHub renders as free-standing was invisible as a child — the epic showed no
  sub-issues, and nothing anywhere reported that the two disagreed. Nothing in
  the plugin had ever read that sentence, though `issue-apply` could already
  write the relationship, so the capability existed and the audit simply never
  asked for it. On the backlog this was found in, one epic had 21 issues
  claiming membership and zero children. An issue that already has *a* parent
  is reported and left alone: a deeper parent is usually the more specific
  truth, and reparenting would flatten a hierarchy somebody built on purpose.

- Fixed: `parse_dependencies` treated every bare `#N` under a `## Dependencies`
  heading as a blocker. Real bodies put all of this under that heading —
  `Changes the scope of #982 and #1000`, `Supersedes #981`, `None of the three
  manual tasks block it`, `Depends on nothing. #863 does not have to land
  first` — so the edges it proposed pointed the wrong way, named work the body
  says is explicitly *not* required, and made issues block each other for
  merely mentioning each other. Measured against one 70-issue backlog it
  proposed 44 edges of which seven formed cycles, and the whole set had to be
  discarded by hand. A marker now has to sit in front of the reference, a
  negated marker (`No longer blocked on #1004`) is excluded, and a clause about
  some other issue (an epic's status list) no longer contributes the epic's own
  edges.

- Fixed: a dependency marker only ever captured the **first** reference after
  it, so `Depends on #977 and #1032` silently became one edge. This was the
  quieter half of the same defect and cost roughly half the real edges in the
  backlog measured.

- Added: `Blocks #N` is read and folded onto the issue it names. The edge
  belongs to the other issue, so only a whole-repo pass can place it, and until
  now nothing did — in practice the provisioning task is the one that knows
  what it holds up, and none of that reached the graph.

- Added: `NATIVE_TYPE_PREFERENCES`, so an org that has added a `Chore` issue
  type gets `Chore` for `tech debt` and `chore` rather than the `Feature` that
  GitHub's five defaults force. `NATIVE_MAINTENANCE_TYPES` gains `Chore` with
  it, which is not cosmetic: without it a backlog that types its debt correctly
  empties its own `execute mode=maintenance` pool, because the filter kept only
  `Bug`.

- Fixed: `issue-apply` refuses a spec entry that leaves a mandatory field blank
  and does not first check whether the issue already carries one, so an entry
  the audit proposed purely to add a parent or an edge was rejected for
  "missing" a value that was sitting on the issue. The audit now repeats the
  existing value, which makes the write a no-op and lets the spec round-trip.

- Fixed: `skills/bulk-execute/references/set-selection.md` told an agent to
  return a dropped story to the backlog with a literal `--add-label
  status-ready`. A project that renamed the label, or that runs the `none`
  ready-gate and has no ready label at all, got the whole `gh issue edit`
  refused — including the unassign, so the story stayed claimed by an agent
  that had already walked away. Both label names now resolve through the
  project's label map, and the ready label is dropped entirely under the `none`
  gate.

## github-workflow 6.1.3

- Fixed: `setIssueFieldValue` declared its `issueFields` variable as
  `[IssueFieldCreateOrUpdateInput!]` where the input object requires
  `[IssueFieldCreateOrUpdateInput!]!`, so GitHub rejected **every** field write
  with "Nullability mismatch on variable $f". Nothing about the values being
  sent was wrong, which is why the failure read as a data problem. All issue
  field writes went through this one function, so while it was malformed no
  issue metadata reached GitHub at all: `issue-apply` set native types happily
  and then failed on all four mandatory fields, and `set_start_date` never
  stamped a date. Every existing test of that path mocked the layer the defect
  was in, so the query itself is now asserted directly.

## github-workflow 6.1.2

- Fixed: a failed org capability lookup was written to
  `.claude/issue-fields-cache.json` and then trusted forever, so the plugin fell
  back to labels in silence. `resolve_org_capabilities` only refused to cache a
  capability GitHub named in a `FORBIDDEN` error, but an under-scoped or expired
  token can also answer with empty `issueTypes` and `issueFields` and no error at
  all. An org answering with neither types nor fields is no longer cached, and an
  all-empty cached record is now re-queried rather than trusted, so a cache that
  was already poisoned heals itself without anyone knowing to pass `--refresh`. A
  user-owned repo genuinely has neither, so a new `owner_kind` key marks that
  empty as deliberate and keeps it a cache hit.

## github-workflow 6.1.1

- Fixed: on a type-capable org, `execute --mode feature`/`--mode maintenance`
  silently dropped an issue that had no native issue type set yet, instead of
  falling back to its `type-*` label or `[PREFIX]` title. An org with zero
  typed issues got an empty pool from either mode with no error — plain
  `execute` (story mode) was unaffected, which is why it went unnoticed.
  `filter_by_native_type` now classifies an untyped issue the same way the
  label path would, and `wf pick`/`wf candidates` report how many candidates
  were classified this way, pointing at `wf issue-audit` to backfill the
  native type.

## github-workflow 6.1.0

- `## Issue Types & Fields` in `templates/ClaudeProject.md` is a complete,
  required section with a capability row, a field-name table and a
  *Missing* table, so a repo scaffolded from it cannot end up without one.
- `/github-workflow:setup` writes that section from `wf org-capabilities`
  rather than a static default, and writes it **even when the org has no
  native types** — saying so explicitly instead of leaving it out.
- `CHANGELOG.md`, consumer-pickup instructions and a consumer inventory
  added.

## github-workflow 6.0.0 — breaking

The workflow's mechanism moved out of markdown procedures and into the `wf`
CLI. Three things break for an existing consumer.

### Metadata that was best-effort is now mandatory

Issue creation goes through `wf issue-apply`, which **refuses** a spec that
leaves `Priority`, `Effort`, `Classification` or `Origin` blank. Commands
that previously created an issue with empty fields — and reported success —
now fail naming the issue and the field.

This is the point of the release. In one consuming repo the old
best-effort path produced 7 typed issues out of 82, no field values at all,
and no error anywhere.

**What to do:** make sure the four fields exist in your org's *Issue
fields* settings before upgrading. `Origin` is the one GitHub does not
create by default. Then run `/github-workflow:setup` so
`ClaudeProject.md` carries a `## Issue Types & Fields` section written from
your org's live capabilities. `wf issue-audit` reports which of your
existing issues are missing metadata and writes a backfill spec; `wf
config-audit` reports configuration problems, including a missing section.

### The inline fallbacks are gone

`execute` and `bulk-execute` previously carried a markdown copy of the
selection and claim procedures, used when Python was unavailable. The copy
drifted, nothing tested it, and it has been deleted.

**Python ≥ 3.8 is now a hard prerequisite** for those commands. Without it
they fail naming the missing prerequisite rather than running a second,
untested implementation. Run `/github-workflow:setup wf` to pin a
dedicated virtualenv. `code-review` keeps its own PR-selection fallback,
which detects SHA-changed PRs that `wf` cannot.

### Nine markdown templates were deleted

Any repo-local documentation citing these by path is now broken:

`templates/issue-fields-resolution.md`, `templates/board-resolution.md`,
`templates/story-selection.md`, `templates/story-selection-auto-ready.md`,
`templates/claim-procedure.md`, `templates/sibling-pr-lookup.md`,
`templates/label-reference.md`, `templates/reap-claims.md`, and
`skills/execute/references/inline-fallback-prewarm.md`.

Their behaviour is now `wf claim`, `wf claim-release`, `wf claim-reap`, `wf
board-move`, `wf sibling-pr`, `wf handoff`, `wf pick`, `wf issue-apply` and
`wf org-capabilities`. The review-state label table and the label read-back
policy moved into `templates/default-labels.md`; every `*-rationale.md`
moved to `docs/rationale/`, out of the agent read path.

### Also in this release

- New exit code **27 `lost`** — a claim another agent holds.
- `wf claim` applies the human-visible ownership marker (assignment plus
  the in-progress label, or the `reviewing` label on a PR), so ownership
  outlives the session that took the lock.
- `wf pick --checkout` sets the `Start date` field where the org has one.
- `## Issue Types & Fields` is a **required** section of
  `ClaudeProject.md`. It is required even on an org with no native types,
  because "this org has none" and "nobody wrote this section" otherwise
  look identical at runtime.

## local-workflow 2.10.0

- `feature-discovery` creates issues through `wf issue-apply` under
  github-workflow, so a discovery run classifies what it files instead of
  leaving the fields blank. No change on the local path.
