# Bulk Execute — Phase 1, Path B (no numbers given)

Read this only when no story numbers and no `--parent` were given. **Claiming the set**, **Recording the set** and **Dropping a story** are in `set-selection.md`, and the two rules that hold throughout are at its top.

## Path B — no numbers given, so choose a group

**1. Read the pool without claiming anything.**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --mode {mode}
```

This returns the same pool `execute` picks from — every open issue judged by the pick rules in `scripts/README.md`, sprint narrowed, sorted by `Priority` then `Effort` then issue number — and claims nothing. Each entry carries `number`, `title`, `type`, `priority`, `scope`, `milestone`, a truncated `body`, and the `dependencies` read from the native blocked-by edges. An `Epic` or `Feature` entry also carries `stories`, the pickable stories it offers: that group is already declared by the tree, so take it with Path C (`references/set-selection-parent.md`). Issues an open blocker holds back are listed under `blocked`, so a dependency chain can still be grouped, and issues too unclear to build under `needs_refinement`. `total` is the unclipped pool size, `listed` is how many came back, and `unprioritised_count` is how many carry no `Priority` and therefore sort last.

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

- **Same milestone and the same area.** The same sprint plus a shared area, shown by both bodies pointing at the same part of the system.
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
