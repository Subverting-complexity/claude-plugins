# Bulk Execute — Phase 1 (plan and claim the set)

Read this at Phase 1. `wf plan-set` chooses the set, orders it and claims it. Which stories are connected, which waits on which, and what order and waves to build them in are decided there from the blocked-by edges and the issue tree, so none of it is judged here.

## What `plan-set` decides

- **A set is related.** Two stories belong together when a blocked-by edge joins them either way, when they wait on the same prerequisite, or when they share a parent or an Epic. A group reached through those links is one set. An open pool gets its best-ranked related group of two or more, and a single story only when no group exists.
- **A dependency never excludes a story.** A story waiting on another story in the set goes in a later wave. A story's open prerequisites join the set even when nobody named them, as long as this run can build them, and `--mode` or `--max-effort` never hold one back.
- **Only a blocker nobody here may build excludes a story**: one owned by a person, assigned or claimed elsewhere, already closed by an open pull request, open in another repository, waiting on such an issue itself, in a dependency cycle, or with edges that could not be read. Each exclusion carries its reason.
- **A `Blocked` story whose blockers have all closed is ready.** It is listed in `released` and planned in the same round; `--claim` writes its stage and comment.
- **Waves.** `waves[0]` is built first. The stories in one wave do not depend on each other, so Phase 4 may build them in parallel.
- **Priority.** A story inherits the priority of the most urgent story waiting on it, so an open pool leads with whatever finishes the most urgent work soonest.

## Plan

Exactly one form applies. Named stories and `--parent` together is a usage error: stop and say so.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" plan-set --mode {mode} --size {size} --issue 41 --issue 43
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" plan-set --mode {mode} --size {size} --parent {N}
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" plan-set --mode {mode} --size {size}
```

With named stories or `--parent`, nothing is left to judge: add `--claim` to that first call and go to **Read the claim**.

With neither, run it once without `--claim` and read the result:

- **`no-candidates`** — nothing can be built. Report each `excluded` story by number, title and reason, and stop.
- **`ok`** — `stories` in build order, each with `wave`, `blocked_by`, `unblocks`, `why` and a truncated body; `excluded`; and `nearby`, the highest-ranked stories ready now that nothing links to the set.
  - Add a `nearby` story only when its body shows it changes the same files or serves the same objective as the set, and the set is below `--size`. Otherwise leave it in the pool: an unlinked story in the pull request makes the diff harder to review.
  - A story too underspecified to build without guessing is left out now, before anything is claimed.
  - Claim with `--issue` once for every story kept, so the claim takes exactly the plan you read.

`size_clamped` set means `--size` was outside 2 to 7 and was clamped: say so. For named stories, `unrelated: true` means they fall into separate groups: say so in one sentence and build them anyway, because the user's choice stands.

## Read the claim

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" plan-set --mode {mode} --size {size} --issue {n} --issue {n} --claim
```

- **`ok`** — every story in `stories` holds its claim ref, is assigned and is `In Progress`, and `.claude/bulk-set.json` records the set with its waves. `dropped` lists stories claimed away, blocked or already resolved, and every story that waited on one of them; report each by number, title and reason. A story whose `stage_set` is false is reported as "Stage update failed: {stage_message}. Continuing."
- **`all-blocked`** — nothing is held. Report `dropped` and stop.
- **`error`** — a claim ref could not be written, which is an environment problem rather than a rival. Every claim already taken was released. Stop and name the problem.

One story claimed is a correct outcome: say so and run the rest of the workflow for it.

## Recording progress

Never edit `.claude/bulk-set.json` by hand. `wf bulk-mark --branch {branch}` records the branch in Phase 2, and `wf bulk-mark --built {number}` records each story once its commit is on the branch. Phase 7 closes only the stories `built` marks.

## Dropping a story

Called when the plan shows the set will not fit, when a gate stays red, or from the escape hatches:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" drop-story --issue {number} --reason "{why, in a few words}"
```

It releases the claim, unassigns, comments the reason on the issue, sets the `Stage` back to `Backlog` (or `Blocked` when the story still waits on an open issue), updates `.claude/bulk-set.json`, and does the same for every unbuilt story that waits on it. Report `dropped` by number, title and reason.

It refuses a story already built. Finish that story, or reset its commits off the branch, before dropping it: a story returned to the backlog with its code in someone's pull request is worse than either outcome.
