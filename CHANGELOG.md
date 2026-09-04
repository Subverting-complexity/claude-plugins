# Changelog

Notable changes to the plugins in this marketplace. Both plugins version
independently; each entry says which one it applies to.

See [README.md](README.md#picking-up-a-new-version) for how to pick up a
new version, and why a stale marketplace cache is the usual reason an
update appears to do nothing.

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
