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
# Claim the next story (priority → lowest number → atomic claim) and print it
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick

# …also move the board to In Progress and create/check out the branch
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --checkout

# Emit the parsed config cache (.claude/wf-config.json) from ClaudeProject.md
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" config
```

Run from the **target repo root** so the CLI can read `ClaudeProject.md`
and the git remote. The `wf.sh` / `wf.ps1` launchers find a working Python 3
(same detection as `run-tests`) and exec `wf.py`, preserving its exit code.

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
`status-blocked`, closing one already resolved by a merged PR) are always
reported in the `side_effects` array.

## Scope of the first cut

Implemented: `--mode story` (the default) under the `label` and `none`
ready-gates. Deferred to the skill via exit 30: `--mode feature` /
`--mode maintenance` (native-issue-type filtering) and the `board-column` /
`both` ready-gates. The empty-pool auto-ready scan also stays in the skill
(`templates/story-selection-auto-ready.md`). The callers
(`pick-story`, `start-story`) try `wf` first and fall back to the inline
procedure on any non-`ok` status or a missing interpreter, so behaviour is
identical whether or not `wf` can run.

PR-side pickers (`update-pr`, `code-review`) reuse this same core and are
the planned next increment.
