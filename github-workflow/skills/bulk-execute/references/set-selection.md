# Bulk Execute — Phase 1 (choose the set, claim every story)

Read this at Phase 1. It is the whole of set selection: the two ways a set
gets chosen, the rules that decide what belongs in one pull request, the
claim every member has to hold, and how a story leaves the set again.

Two things hold throughout:

1. **The set is chosen, not sampled.** Priority order says which story is
   worth doing next. It says nothing about which stories belong in one pull
   request. A set assembled by taking the top few off the backlog is the
   most likely way for this command to produce a diff nobody can review.
2. **Every story in the set holds its own atomic claim** before any code is
   written. The claim ref is the only thing that stops a second agent
   picking up a story this branch is already building.

---

## Path A — the user named the stories

`$ARGUMENTS.story_numbers` is present, e.g.
`/github-workflow:bulk-execute 41 43 47`. The choice has been made, so do
not re-litigate relatedness: a person who names three issues is asserting
they belong together, and that assertion outranks the heuristics below. Two
things still apply — the size cap, and the fact that a story which cannot be
worked cannot be built.

**1. Validate each named story in one batch.** For each number:

```
gh issue view {number} --repo {org}/{repo} --json state,labels,assignees,title,body,milestone
```

Drop a named story, with a one-line reason in your report, when it is:

- **closed** — nothing to build;
- **already in flight** — it carries `status-in-review`, or an open pull
  request already closes it. Ask once per number:
  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number}
  ```
  Exit 0 with `found: 0` means nothing closes it; exit 20 means the lookup
  failed, so say so rather than assuming it is free. Report any PR found by
  number and title and say `/github-workflow:code-review` handles it;
- **assigned to someone else** — another agent or person owns it;
- **empty** — no Context and no Requirements anywhere in the body, comments
  or linked docs, so any implementation would be a guess;
- **carrying `needs-refinement`** — say it needs refinement first.

If a named story carries `status-in-review` but **no** open PR is found,
check for a **closed, unmerged** PR (`closingIssuesReferences`, `states:
CLOSED`). If there is one, the PR was abandoned: reset the issue
automatically — remove `status-in-review`, apply `status-ready`, unassign,
move the board to Backlog, comment `"Resetting — PR #{N} closed without
merge."` — and keep it in the set. If there is no closed PR either, surface
the inconsistency and drop it.

**2. Cap the size.** More than `--size` stories (default 5, which is also
the maximum) were named. Keep the first `--size` in the order the user gave
them, and say which were left out and that they stay ready in the backlog.
Do not silently build more than the cap: the cap is what keeps the pull
request reviewable.

**3. Warn, but obey, on a set that looks unrelated.** If the named stories
share nothing by the rules in Path B, say so in one sentence in your report
and build them anyway. The user's instruction stands; your job is to make
the consequence visible, not to override it.

**4. Put the survivors in build order and name the lead.** Same rule as
Path B step 3: every story comes after the stories in the set it depends on,
and stories with no dependency between them keep the order the user gave
them. That is `plan_bulk_order` in `scripts/wf_core.py`. The first story in
build order is the **lead** — it names the branch, and it is the one story
never dropped while any code exists.

Then go to **Claiming the set**.

---

## Path B — no numbers given, so choose a group

**1. Read the pool without claiming anything.**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --mode {mode}
```

This returns the same pool `execute` picks from — ready gate applied, sprint
narrowed, refinement and agent-gating filters applied, mode filter applied,
sorted by priority then issue number — and claims nothing. Each entry
carries `number`, `title`, `labels`, `milestone`, a truncated `body`, and
the `dependencies` parsed out of that body. `total` is the unclipped pool
size; `listed` is how many came back.

Interpret the result by its `status`:

- **`ok`** — you have the pool; continue to step 2.
- **`no-candidates`** — report "No stories available for pickup" and stop.
- **`unsupported`** / **`error`**, or the launcher reports Python is missing
  — `wf` cannot run here. Stop and name the prerequisite: `wf` needs Python
  3.8+ on `PATH` and an authenticated `gh`. Do not assemble a pool by hand;
  a set chosen from a differently-built pool is not the set this run would
  have claimed.

Ask for a bigger read only if you need it: `--limit 0` for the whole pool,
`--body-chars 0` for untruncated bodies. The default read is deliberately
small, because the decision below rarely needs more than each story's
opening Context and Requirements.

**2. Group the pool, then choose one group.** Work through the pool and
look for stories that would genuinely be built together. A candidate joins
the group around a story when it meets **either** of the two strong tests,
or **both** of the two weak ones.

**Strong — one is enough:**

- **Declared linkage.** The two name each other, or both name the same
  parent or epic: `Part of #N`, `Depends on #N`, `Blocked by #N`, a shared
  reference in a `## Dependencies` section, or sub-issues of one parent. A
  dependency chain is the single best bulk set there is, because building
  the dependency and its dependent together is what removes the wait.
- **Same deliverable surface.** Both bodies point at the same files,
  module, command, screen, endpoint or table. This is where the saving
  actually comes from: the second story costs a fraction of the first
  because the code is already open and the design decision is already made.

**Weak — both are needed:**

- **Same milestone and the same area.** The same sprint plus a shared
  `area-*`, `component-*` or scope label.
- **Same kind of change against the same subject.** Three bugs in one
  importer; two stories adding fields to one form.

**None of these counts as relatedness**, however tempting: both are small,
both are high priority, both are `type-bug`, both are in this repo, both are
in this sprint on their own, or the pool happens to hold exactly three
stories.

Then choose **one** group, by this order:

1. The group containing the **highest-priority story in the pool**, if that
   group has at least two members. This keeps bulk runs honest about
   priority: the most important work still goes first, it just brings its
   relatives with it.
2. Otherwise the group with the strongest linkage — a declared dependency
   chain beats a shared surface, which beats the two weak tests together.
3. Break a tie on the highest-priority member, then the lowest issue number,
   so two agents reading the same pool make the same choice.

**3. Cap it, then order it.** Trim to `--size` (default 5, which is also
the maximum), keeping the highest-priority members, then put the survivors
in **build order**: every story comes after the stories in the set it
depends on, and stories with no dependency between them keep priority
order. Trimming happens first, so a story cut by the cap cannot drag its
dependent out of order. That whole rule is `plan_bulk_order` in
`scripts/wf_core.py`, which is its executable statement. A dependency cycle
inside a set cannot be ordered: if you find one, say so and drop the
lowest-priority story in it.

The first story in build order is the **lead**. It names the branch and it
is the one story that is never dropped while any code exists.

**4. State the choice before claiming it.** In one short paragraph: which
stories are in the set, and what makes them one change. If you cannot write
that sentence without hedging, the group is not a group — fall back to the
highest-priority story alone and run it as a single story.

Then go to **Claiming the set**.

---

## Claiming the set

Identical for both paths. Claim in **build order**, so the lead is claimed
first and a run that loses claims part way still holds a coherent prefix.

For each story, in order:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pick --issue {number} --checkout --no-branch \
  --sibling {other_number} --sibling {other_number} ...
```

Pass `--sibling` once for **every other story in the set**. That is what
lets a dependency chain be built at all: `wf` normally refuses a story whose
dependency is still open, because you cannot build on unmerged work you
cannot see, and a sibling is the exception — it is work this same run is
about to write, in the same commit series, on the same branch. A dependency
that is open and **not** a sibling still blocks, exactly as it does for a
single-story run.

`--checkout --no-branch` applies the board move to In Progress without
creating a branch. Every story in the set shares the one branch Phase 2
creates; branching per story here would give each its own.

Interpret each result by `status`:

- **`ok`** — claimed. `status-in-progress` and the `@me` assignment are
  applied and the claim ref is held. Surface any `side_effects`.
- **`all-blocked`** — this story could not be claimed: taken by another
  agent, blocked by an open dependency outside the set, or already resolved
  by a merged PR. Drop it from the set, say which and why, and carry on with
  the rest. It is not a reason to abandon the run.
- **`error`**, or Python is missing — `wf` cannot run here. Stop the run and
  name the prerequisite; every story already claimed is released by the
  dropping procedure below.

If dropping a story leaves another story in the set depending on it, drop
that one too and repeat until the set is stable — a story whose dependency
is no longer being built has an open external dependency again.

## Recording the set

The set has to survive a compaction, so write it down as soon as it is
claimed, and update it whenever a story joins or leaves:

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

`branch` is filled in by Phase 2. `built` flips to `true` as each story is
committed in Phase 6, and it is the field Phase 7 reads to decide which
stories the pull request may close. `dropped` records each departure as
`{"number": N, "reason": "..."}` so the final report can account for every
story that was ever claimed.

## Dropping a story

Called from Phase 1 (unclaimable), Phase 3 (the plan shows the set does not
fit), Phase 5 (a red gate stops the build) and the escape hatches (blocked,
too large). Dropping is cheap and correct; carrying a story you cannot
finish is neither.

If the story was **never claimed**, there is nothing to undo — remove it from
`.claude/bulk-set.json` and say why in the report.

If it **was claimed**, return it to the backlog properly, in this order:

1. Release the lock:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --issue {number}
   ```
2. Restore the pool state, so the picker can select it again. Resolve both
   names through `## Label Map` in ClaudeProject.md rather than typing the
   purpose keys: a project that renamed `status-in-progress` gets a `gh`
   failure and an issue left assigned, and a project on the `none`
   ready-gate has no ready label at all, so `--add-label` names one that
   does not exist and the whole edit is refused, the unassign with it.
   ```
   gh issue edit {number} --repo {org}/{repo} --remove-assignee @me \
     --remove-label {in-progress-label} --add-label {ready-label}
   ```
   Drop the `--add-label` clause entirely when `ready-gate` is `none`.
   There is nothing to restore there: unassigning is what returns the issue
   to the pool.
3. Move the board back to Backlog:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" board-move {number} --column col-backlog
   ```
   It exits 0 whether or not a board is configured; read `moved`.
4. Comment on the issue saying it was claimed for a bulk run and returned
   unbuilt, and why, so the next run does not have to infer it:
   ```
   gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
   ```
5. Record it in `.claude/bulk-set.json` under `dropped`.

**Never leave a claimed story half-built.** If code for it is already on the
branch, it is not a candidate for dropping — either finish it, or reset that
work off the branch before releasing the claim. A story returned to the
backlog with its code already merged into someone else's pull request is
worse than either outcome on its own.

If dropping takes the set below two stories, that is fine: one claimed story
is a single-story run, and the rest of the workflow handles it unchanged.
