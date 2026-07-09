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

# Claim the next PR of mine that needs review feedback addressed (update-pr)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" update-next --checkout

# Claim the next PR that needs reviewing (code-review)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" review-next --checkout

# Emit the parsed config cache (.claude/wf-config.json) from ClaudeProject.md
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config
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
| 30   | `unsupported`   | Path not in the CLI yet — caller falls back to the skill.      |

Mutations to the **winning** issue (claim, assign, `status-in-progress`) are
silent; mutations to **other** issues (returning a dependency-blocked one to
`status-blocked`, closing one already resolved by a merged PR — which also
moves it to the **Done** board column) are always reported in the
`side_effects` array.

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
| `pick`         | Ready, unassigned issues                          | `issue-{n}` ref | `status-in-progress`  | pick-story, start-story |
| `update-next`  | My open PRs with actionable review feedback       | `pr-{n}` ref    | `updating` (keeps the feedback label) | update-pr |
| `review-next`  | Open PRs labelled `needs-review` / `needs-re-review` | `pr-{n}` ref | `reviewing` (removes prior) | code-review |

All share the same atomic claim/checkout core and JSON contract. `--checkout`
creates/checks out the branch (`pick`) or runs `gh pr checkout` (PR pickers).

## Scope / deferrals

- **`pick`** — `--mode story` / `feature` / `maintenance` under all four
  ready-gates (`label`, `none`, `board-column`, `both`).
  feature/maintenance filter by the `type-*` **label**, so they run here
  on label-typed projects. The empty-pool auto-ready dependency scan runs
  inline before returning `no-candidates`. Deferred to the skill via
  exit 30: feature/maintenance on a **type-capable** org (the native
  issue type is authoritative and is not resolved here).
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
