# Inline-fallback prewarm

Read this **only** when the Phase 1 fast path (`wf pick`) did **not** return
`ok` — that is, when it returned `unsupported`/`error`, or the launcher
reported that Python is missing, and you are about to run the inline story
selection. On the happy path (`wf pick` → `ok`), none of this applies: the
story is already selected, claimed, board-moved, and checked out, so there is
nothing to warm up.

## Why this lives here, not in the hot path

The github-workflow `execute` skill used to "prewarm" three `gh` calls at
session start — a candidate list, a full label inventory, and a rate check —
to front-load work for this inline fallback. But the fallback runs only when
`wf` cannot. On the common path the warm-up was pure waste: it fetched data
the happy path never reads, paying latency and rate-limit budget up front for
a path that usually never executes. Lever F1 (`docs/context-optimization-plan.md`)
moved the candidate/label warm-up off the hot pick/plan/build window. Only the
cheap rate check stays eager in `SKILL.md`.

## Candidate fetching — the inline path is self-contained

There is **no candidate prewarm and no `.claude/candidates.json` cache**. The
inline selection procedure, `templates/story-selection.md` Step 1, fetches the
unassigned candidate pool itself, the way this project's `ready-gate` defines
"ready":

- **`label`** / **`both`** — issues carrying `status-ready` (`both` then drops
  any not also in the board "Ready" column).
- **`none`** — every open unassigned issue, then drop any carrying
  `status-blocked`.
- **`board-column`** — issues in the board "Ready" column (GraphQL).

So when you enter the inline fallback, just run `templates/story-selection.md`
with the mode — it does its own ready-gate-aware fetch. (A previous version
wrote the result to `.claude/candidates.json` claiming the inline path would
read it instead of re-querying; nothing ever did, so that cache was removed.)

## Label inventory — deferred to first use at finish

There is **no eager label-inventory prewarm** either. `.claude/label-cache.json`
(label name → node ID) is consumed only at the **finish phase** (Phase 7), where
`references/finish.md` builds a single GraphQL mutation to apply
the review-state labels and move the issue to `status-in-review`. That phase
already falls back to `gh label list` when the cache is absent, so it now fetches
labels lazily, at the point of need, and only if the session actually reaches
finish. Nothing in the pick/plan/build window needs the cache. If you do build
it (during a finish-phase fallback), write it to `.claude/label-cache.json` and
append any labels you create with the guarded create-if-missing pattern in
`templates/default-labels.md`, so later writes in the same session reuse it.
