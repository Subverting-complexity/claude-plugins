# Bulk Execute — Phase 1, Path C (a parent given)

Read this only if `--parent N` was given. **Claiming the set**, **Recording the set** and **Dropping a story** are in `set-selection.md`, and the two rules that hold throughout are at its top.

## Path C — the user named an Epic or Feature

`--parent N` is present. The tree under N has already said which stories belong together, so nothing is grouped by heuristics and nothing is asked. Named story numbers and `--parent` cannot be combined; if both are given, stop and say so.

**1. Read the set the tree offers.**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --mode {mode} --parent {N} --size {size}
```

It walks N's sub-issues down through its Features to the leaves (every open descendant that is not an Epic or Feature) and applies the rules settled on #239:

- **Only work a code agent may take.** A leaf is taken only when its stage is blank or `Backlog` and its `Ownership` is `Code agent`. `Non-code`, `Parked`, `Needs refinement`, `In Progress` and `In Review` leaves are never taken.
- **One exception for Blocked.** A leaf in Blocked is taken when it has an open blocker and every one is another leaf taken in the same run. A leaf blocked by anything else, or by no issue at all, stays out.
- **One Feature per run.** Under an Epic, only the Feature holding the highest-priority leaf is taken.
- **Capped by `--size`**, highest priority first, and returned in build order.

Interpret the result by its `status`: **`ok`** — the `candidates` are the set, in build order; **`no-candidates`** — nothing under N is available, so report the `excluded` list and stop; **`usage`** — N is not an Epic or Feature, so say so and stop; **`error`** — `wf` cannot run, so name the prerequisite and stop.

**2. Report what was left out.** `excluded` names every other leaf with its reason. Say in one line per Feature or stage what was not taken, so the next run can be pointed at it. The container itself is never claimed, given a stage or closed.

**3. Name the lead.** The first story in `candidates` is the lead. Then go to **Claiming the set**, passing `--sibling` for every other story exactly as for the other paths: that is also what lets a Blocked leaf be claimed, because its blocker is a sibling.
