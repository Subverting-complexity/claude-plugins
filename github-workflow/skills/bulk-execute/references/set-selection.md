# Bulk Execute — Phase 1 (choose the set, claim every story)

Read this at Phase 1. It is the whole of set selection: the three ways a set gets chosen, the rules that decide what belongs in one pull request, the claim every member has to hold, and how a story leaves the set again.

Two things hold throughout:

1. **The set is chosen, not sampled.** Priority order says which story is worth doing next. It says nothing about which stories belong in one pull request. A set assembled by taking the top few off the backlog is the most likely way for this command to produce a diff nobody can review.
2. **Every story in the set holds its own atomic claim** before any code is written. The claim ref is the only thing that stops a second agent picking up a story this branch is already building.

---

## Path A — the user named the stories

`$ARGUMENTS.story_numbers` is present, e.g. `/github-workflow:bulk-execute 41 43 47`. The choice has been made, so do not re-litigate relatedness: a person who names three issues is asserting they belong together, and that assertion outranks the heuristics below. Two things still apply — the size cap, and the fact that a story which cannot be worked cannot be built.

**1. Validate each named story in one batch.** Read the pool once — it is the answer to "is this story available", because it *is* the Backlog column with the unavailable already filtered out:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --mode {mode} --limit 0
```

Then read each named number for its own content:

```
gh issue view {number} --repo {org}/{repo} --json state,assignees,title,body,milestone
```

That JSON deliberately does not ask for labels. No label says which lane a card is in, how urgent the story is or who owns it, so there is nothing in a label list to decide on — the lane is the board's answer, which `wf candidates` has already given.

Drop a named story, with a one-line reason in your report, when it is:

- **closed** — nothing to build;
- **already in flight** — its card is in the In Review column, or an open pull request already closes it. Ask once per number:
  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number}
  ```
  Exit 0 with `found: 0` means nothing closes it; exit 20 means the lookup failed, so say so rather than assuming it is free. Report any PR found by number and title and say `/github-workflow:code-review` handles it;
- **assigned to someone else** — another agent or person owns it;
- **empty** — no Context and no Requirements anywhere in the body, comments or linked docs, so any implementation would be a guess;
- **not in the pool** — the number came back in none of the `wf candidates` entries, so it is not an unassigned Backlog card a code agent may take. Its card is in Needs refinement, Parked, Blocked or Non-code, or its `Ownership` is not `Code agent`. Read the reason off the board or the issue's fields and name it; `pick --issue` refuses the same story anyway, so claiming it would only fail later.

If a named story sits in In Review but **no** open PR is found, check for a **closed, unmerged** PR (`closingIssuesReferences`, `states: CLOSED`). If there is one, the PR was abandoned: reset the issue automatically — unassign, move the card to Backlog, comment `"Resetting — PR #{N} closed without merge."` — and keep it in the set. If there is no closed PR either, surface the inconsistency and drop it.

**2. Cap the size.** More than `--size` stories (default 5, which is also the maximum) were named. Keep the first `--size` in the order the user gave them, and say which were left out and that their cards stay in the Backlog column. Do not silently build more than the cap: the cap is what keeps the pull request reviewable.

**3. Warn, but obey, on a set that looks unrelated.** If the named stories share nothing by the rules in Path B, say so in one sentence in your report and build them anyway. The user's instruction stands; your job is to make the consequence visible, not to override it.

**4. Put the survivors in build order and name the lead.** Same rule as Path B step 3: every story comes after the stories in the set it depends on, and stories with no dependency between them keep the order the user gave them. That is `plan_bulk_order` in `scripts/wf_core.py`. The first story in build order is the **lead** — it names the branch, and it is the one story never dropped while any code exists.

Then go to **Claiming the set**.

---

## Path B — no numbers given, so choose a group

**1. Read the pool without claiming anything.**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --mode {mode}
```

This returns the same pool `execute` picks from — the board's Backlog column, sprint narrowed, the mode filter applied, anything `Ownership` does not mark `Code agent` removed, sorted by `Priority` then `Effort` then issue number — and claims nothing. Each entry carries `number`, `title`, `priority`, `scope`, `milestone`, a truncated `body`, and the `dependencies` read from the native blocked-by edges. `total` is the unclipped pool size, `listed` is how many came back, and `unprioritised_count` is how many carry no `Priority` and therefore sort last.

Interpret the result by its `status`:

- **`ok`** — you have the pool; continue to step 2.
- **`no-candidates`** — report "No stories available for pickup" and stop.
- **`unsupported`** / **`error`**, or the launcher reports Python is missing — `wf` cannot run here. Stop and name the prerequisite: `wf` needs Python 3.8+ on `PATH` and an authenticated `gh`. Do not assemble a pool by hand; a set chosen from a differently-built pool is not the set this run would have claimed.

Ask for a bigger read only if you need it: `--limit 0` for the whole pool, `--body-chars 0` for untruncated bodies. The default read is deliberately small, because the decision below rarely needs more than each story's opening Context and Requirements.

**2. Group the pool, then choose one group.** Work through the pool and look for stories that would genuinely be built together. A candidate joins the group around a story when it meets **either** of the two strong tests, or **both** of the two weak ones.

**Strong — one is enough:**

- **Declared linkage.** A native blocked-by edge between the two (`wf candidates` reports each candidate's `dependencies` and `dependencies_open`), a shared parent or epic, or sub-issues of one parent. A dependency chain is the single best bulk set there is, because building the dependency and its dependent together is what removes the wait.
- **Same deliverable surface.** Both bodies point at the same files, module, command, screen, endpoint or table. This is where the saving actually comes from: the second story costs a fraction of the first because the code is already open and the design decision is already made.

**Weak — both are needed:**

- **Same milestone and the same area.** The same sprint plus a shared area, named by whatever custom `area-*` or `component-*` label the project happens to keep, or by both bodies pointing at the same part of the system.
- **Same kind of change against the same subject.** Three bugs in one importer; two stories adding fields to one form.

**None of these counts as relatedness**, however tempting: both are small, both are high priority, both are typed `Bug`, both are in this repo, both are in this sprint on their own, or the pool happens to hold exactly three stories.

Then choose **one** group, by this order:

1. The group containing the **highest-priority story in the pool**, if that group has at least two members. This keeps bulk runs honest about priority: the most important work still goes first, it just brings its relatives with it.
2. Otherwise the group with the strongest linkage — a declared dependency chain beats a shared surface, which beats the two weak tests together.
3. Break a tie on the highest-priority member, then the lowest issue number, so two agents reading the same pool make the same choice.

**3. Cap it, then order it.** Trim to `--size` (default 5, which is also the maximum), keeping the highest-priority members, then put the survivors in **build order**: every story comes after the stories in the set it depends on, and stories with no dependency between them keep priority order. Trimming happens first, so a story cut by the cap cannot drag its dependent out of order. That whole rule is `plan_bulk_order` in `scripts/wf_core.py`, which is its executable statement. A dependency cycle inside a set cannot be ordered: if you find one, say so and drop the lowest-priority story in it.

The first story in build order is the **lead**. It names the branch and it is the one story that is never dropped while any code exists.

**4. State the choice before claiming it.** In one short paragraph: which stories are in the set, and what makes them one change. If you cannot write that sentence without hedging, the group is not a group — fall back to the highest-priority story alone and run it as a single story.

Then go to **Claiming the set**.

---

## Path C — the user named an Epic or Feature

`--parent N` is present. The tree under N has already said which stories belong together, so nothing is grouped by heuristics and nothing is asked. Named story numbers and `--parent` cannot be combined; if both are given, stop and say so.

**1. Read the set the tree offers.**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --mode {mode} --parent {N} --size {size}
```

It walks N's sub-issues down through its Features to the leaves (every open descendant that is not an Epic or Feature) and applies the rules settled on #239:

- **Only work a code agent may take.** A leaf is taken only when its card is in Backlog and its `Ownership` is `Code agent`. Non-code, Parked, Needs refinement, In Progress and In Review leaves are never taken.
- **One exception for Blocked.** A leaf in Blocked is taken when it has an open blocker and every one is another leaf taken in the same run. A leaf blocked by anything else, or by no issue at all, stays out.
- **One Feature per run.** Under an Epic, only the Feature holding the highest-priority leaf is taken.
- **Capped by `--size`**, highest priority first, and returned in build order.

Interpret the result by its `status`: **`ok`** — the `candidates` are the set, in build order; **`no-candidates`** — nothing under N is available, so report the `excluded` list and stop; **`usage`** — N is not an Epic or Feature, so say so and stop; **`error`** — `wf` cannot run, so name the prerequisite and stop.

**2. Report what was left out.** `excluded` names every other leaf with its reason. Say in one line per Feature or column what was not taken, so the next run can be pointed at it. The container itself is never claimed, moved or closed.

**3. Name the lead.** The first story in `candidates` is the lead. Then go to **Claiming the set**, passing `--sibling` for every other story exactly as for the other paths: that is also what lets a Blocked leaf be claimed, because its blocker is a sibling.

---

## Claiming the set

Identical for every path. Claim in **build order**, so the lead is claimed first and a run that loses claims part way still holds a coherent prefix.

For each story, in order:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout --no-branch \
  --sibling {other_number} --sibling {other_number} ...
```

Pass `--sibling` once for **every other story in the set**. That is what lets a dependency chain be built at all: `wf` normally refuses a story whose dependency is still open, because you cannot build on unmerged work you cannot see, and a sibling is the exception — it is work this same run is about to write, in the same commit series, on the same branch. A dependency that is open and **not** a sibling still blocks, exactly as it does for a single-story run.

`--checkout --no-branch` applies the board move to In Progress without creating a branch. Every story in the set shares the one branch Phase 2 creates; branching per story here would give each its own.

Interpret each result by `status`:

- **`ok`** — claimed. The card is in In Progress, the `@me` assignment is applied and the claim ref is held. Surface any `side_effects`.
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
3. Move the card back to Backlog — **this is the step that returns the issue to the pool**, because the pool is that column:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" board-move {number} --column col-backlog
   ```
   It exits 0 whether or not a board is configured; read `moved`.
4. Comment on the issue saying it was claimed for a bulk run and returned unbuilt, and why, so the next run does not have to infer it:
   ```
   gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
   ```
5. Record it in `.claude/bulk-set.json` under `dropped`.

**Never leave a claimed story half-built.** If code for it is already on the branch, it is not a candidate for dropping — either finish it, or reset that work off the branch before releasing the claim. A story returned to the backlog with its code already merged into someone else's pull request is worse than either outcome on its own.

If dropping takes the set below two stories, that is fine: one claimed story is a single-story run, and the rest of the workflow handles it unchanged.
