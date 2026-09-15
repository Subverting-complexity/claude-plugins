# Bulk Execute — Phase 1 (choose the set, claim every story)

Read this at Phase 1. It is the whole of set selection: which of the three ways a set gets chosen applies (each, with the rules that decide what belongs in one pull request, is in its own file), the claim every member has to hold, and how a story leaves the set again.

Two things hold throughout:

1. **The set is chosen, not sampled.** Priority order says which story is worth doing next. It says nothing about which stories belong in one pull request. A set assembled by taking the top few off the backlog is the most likely way for this command to produce a diff nobody can review.
2. **Every story in the set holds its own atomic claim** before any code is written. The claim ref is the only thing that stops a second agent picking up a story this branch is already building.

---

## Choosing the path

Exactly one path applies. Each lives in its own file, so read only the one that applies, then come back to **Claiming the set**:

- If the user named stories (`$ARGUMENTS.story_numbers` is present, e.g. `/synergy:bulk-execute 41 43 47`), follow Path A in `references/set-selection-named.md`.
- If `--parent N` was given, follow Path C in `references/set-selection-parent.md`. Named story numbers and `--parent` cannot be combined; if both are given, stop and say so.
- If no numbers and no `--parent` were given, follow Path B in `references/set-selection-open.md`.

---

## Claiming the set

Identical for every path. Claim in **build order**, so the lead is claimed first and a run that loses claims part way still holds a coherent prefix.

For each story, in order:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout --no-branch \
  --sibling {other_number} --sibling {other_number} ...
```

Pass `--sibling` once for **every other story in the set**. That is what lets a dependency chain be built at all: `wf` normally refuses a story whose dependency is still open, because you cannot build on unmerged work you cannot see, and a sibling is the exception — it is work this same run is about to write, in the same commit series, on the same branch. A dependency that is open and **not** a sibling still blocks, exactly as it does for a single-story run.

`--checkout --no-branch` sets the stage to `In Progress` without creating a branch. Every story in the set shares the one branch Phase 2 creates; branching per story here would give each its own.

Interpret each result by `status`:

- **`ok`** — claimed. The stage is `In Progress`, the `@me` assignment is applied and the claim ref is held. Surface any `side_effects`.
- **`all-blocked`** — this story could not be claimed: taken by another agent, blocked by an open dependency outside the set, or already resolved by a merged PR. Drop it from the set, say which and why, and carry on with the rest. It is not a reason to abandon the run.
- **`error`**, or Python is missing — `wf` cannot run here. Stop the run and name the prerequisite; every story already claimed is released by the dropping procedure below.

If dropping a story leaves another story in the set depending on it, drop that one too and repeat until the set is stable — a story whose dependency is no longer being built has an open external dependency again.

## Recording the set

The set has to survive a compaction, so write it down as soon as it is claimed, and update it whenever a story joins or leaves:

```
mkdir -p .claude
cat > .claude/bulk-set.json <<'JSON'
{
  "lead": 41,
  "mode": "feature",
  "branch": null,
  "stories": [
    {"number": 41, "title": "Resolve labels by purpose key", "built": false},
    {"number": 43, "title": "Report the label that was missing", "built": false}
  ],
  "dropped": []
}
JSON
```

`branch` is filled in by Phase 2. `built` flips to `true` as each story is committed in Phase 6, and it is the field Phase 7 reads to decide which stories the pull request may close. `dropped` records each departure as `{"number": N, "reason": "..."}` so the final report can account for every story that was ever claimed.

## Dropping a story

Called from Phase 1 (unclaimable), Phase 3 (the plan shows the set does not fit), Phase 5 (a red gate stops the build) and the escape hatches (blocked, too large). Dropping is cheap and correct; carrying a story you cannot finish is neither.

If the story was **never claimed**, there is nothing to undo — remove it from `.claude/bulk-set.json` and say why in the report.

If it **was claimed**, return it to the backlog properly, in this order:

1. Release the lock:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --issue {number}
   ```
2. Give the issue back:
   ```
   gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
   ```
3. Set the stage back to `Backlog` — **this is the step that returns the issue to the pool**, because the pool is that stage:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" stage-set {number} --stage stage-backlog
   ```
   It always exits 0; read `set`, and report a failed write as "Stage update failed: {reason}. Continuing."
4. Comment on the issue saying it was claimed for a bulk run and returned unbuilt, and why, so the next run does not have to infer it:
   ```
   gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
   ```
5. Record it in `.claude/bulk-set.json` under `dropped`.

**Never leave a claimed story half-built.** If code for it is already on the branch, it is not a candidate for dropping — either finish it, or reset that work off the branch before releasing the claim. A story returned to the backlog with its code already merged into someone else's pull request is worse than either outcome on its own.

If dropping takes the set below two stories, that is fine: one claimed story is a single-story run, and the rest of the workflow handles it unchanged.
