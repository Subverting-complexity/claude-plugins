# Bulk Execute — design rationale

Background for the decisions in `SKILL.md`, `references/set-selection.md` and `wf plan-set`. **Not read at runtime** — it exists so a later change does not silently undo a decision that was made for a reason.

## Why a separate command rather than a flag on `execute`

`execute` is built around one story: one claim, one branch derived from that story's number and title, one `Closes #N`, one issue to settle. Adding a `--stories 41,43,47` flag would have put a second shape through every one of those steps, and the phases where the two differ (selection, finish, the per-story build loop) are exactly the phases carrying the most instruction weight. The two would have spent most of their text saying "unless there are several".

Keeping them apart also keeps `execute`'s measured token footprint where it is. That footprint is gated in CI at two budgets, and the build window in particular has been trimmed deliberately. A bulk branch inside it would have grown the window every run pays for, in service of the runs that use it rarely.

What the two **do** share is everything after the pull request exists. `bulk-execute` reads `skills/execute/references/review-and-merge.md`, `exit-cleanup.md` and `escape-hatches.md` directly, with substitutions listed in its `SKILL.md`, rather than restating them. Those files are the canonical specification of review, merge and cleanup, and a second copy would drift.

## Why the set is chosen rather than taken off the top

The first version of this command claimed the highest-priority story and then gathered relatives around it. That is a cheaper procedure and it is wrong in a specific way: the pool's priority order answers "what is worth doing next", and the set needs an answer to "what belongs in one pull request". Those are different questions, and letting the first stand in for the second produces sets whose only common property is that they were near each other in a sorted list.

Selection then read the pool (`wf candidates`), and Claude grouped it by reading the listing. That was too strict in a way that mattered: `pick` set every story with an open blocker to `Blocked`, which took it out of the listing, so a story waiting on another story was never offered beside it, and a named story in `Blocked` was dropped as "not in the pool" even when its blocker was named too. The pair that most needed one run became two runs a merge apart.

So since 17.0.0 the set is planned in `wf plan-set` (`wf_core.plan_set`) from structure rather than prose. A story waiting on work this run can build is in the universe, and a dependency decides where a story goes in the build order, never whether it is in on its own account. Priority decides what is taken first, and a blocker inherits the priority of what waits on it, so the most important work still finishes first. Since 17.4.0 every rule is in `wf`, so no judgement about which stories to add is left to the skill.

The user naming issue numbers is the precise form of the same thing. `plan-set` adds the prerequisites they need and holds a named set to the same budget, priority and group rules, reporting any named story it leaves out with the rule that did it.

The same rule reaches `execute`: `pick --issue N` on a story whose blockers this run can build claims the first blocker and reports `prerequisite_for`, instead of refusing the story the user asked for.

## Why `wf candidates` exists

`wf pick` deliberately collapses select, claim, stage write and branch into one call, because a single-story run wants exactly that and every seam between those steps is a race. A bulk run needs the pool **before** it can decide anything, so it needs the read without the write.

Putting that read in `wf` rather than in prose keeps one encoding of the filters. Pool membership, sprint narrowing, refinement and ownership filters, mode filter and the priority/effort sort are all tested logic in `wf_core`; an inline `gh issue list` in the skill would have been a second, untested copy that drifts the first time a filter changes. An inline selection procedure was kept for a while as the fallback for a machine with no Python, on the argument that a drifting second copy beat no selection at all. That argument lost: the copy drifted, nothing tested it, and it has been deleted. `wf` is now a hard prerequisite here, and its absence is an error naming the missing prerequisite rather than a silent second implementation.

## Why a sibling dependency does not block

`execute` refuses a story whose dependency is still open, and that rule is right: you cannot build on unmerged work you cannot fetch. A bulk set breaks the premise rather than the rule. When the dependency is in the same set, it is not unmerged work you cannot see — it is work this same run writes, into the same commit series, on the same branch, under the same review. By the time anything merges, both have.

That is why `wf pick --sibling` exists, and why the carve-out is expressed as data (the sibling list) rather than as a bypass flag. `blocking_dependencies` in `wf_core` takes the parsed dependencies, the ones found open, and the siblings, and returns what still blocks. An open dependency outside the set still blocks, so the rule survives intact for every case it was written for.

A dependency chain is also the best possible bulk set, which is worth saying plainly: two stories where one waits on the other are two stories that would otherwise be two runs and a merge apart.

## Why the branch is created by the skill, not by `wf`

`wf pick --checkout` names the branch from the story it claimed. With several stories that produces several branches, one per claim, and the second checkout would leave the first story's commits behind. `--no-branch` keeps everything else that `--checkout` does — the `In Progress` stage especially, which is per-issue and worth reusing — and leaves the branch to the caller, which creates exactly one and records it in `.claude/bulk-set.json`.

The branch is named for the **lead** story's number and the **set's** shared theme rather than the lead's own title, because a branch called `feature/41/fix-missing-status-label` carrying three stories misdescribes itself to everyone who sees it later.

## Why the pull request may only close stories it built

This is the invariant the whole finish phase is arranged around. A `Closes #N` line is not a description; on merge it closes the issue, moves it to Done and takes it out of the backlog. A line for a story that was dropped or never finished deletes that work from the project's memory, and nothing downstream will notice: the issue looks completed, the backlog looks clean, and the code does not exist.

Hence `built` in `.claude/bulk-set.json`, flipped per story at commit time, and hence the body validation step counting `Closes` lines against it rather than reading them over. It is the one check in this workflow that fails silently and expensively if skipped.

The mirror of the same rule is that a story which cannot be finished goes **back to the backlog properly** — claim released, unassigned, stage set back to `Backlog`, and a comment saying what happened. The stage write is the part that returns it to the pool; the rest is bookkeeping. A story left assigned at `In Progress` after the run ends is invisible to the picker and to the person who wrote it.

## Why stories build wave by wave, one commit per story

A wave holds only stories that do not wait on each other, so building them at once cannot put a story ahead of its blocker. They are built in parallel only when their planned files do not overlap, each by a builder in its own worktree on a temporary branch, and cherry-picked onto the shared branch in build order. A conflict falls back to a serial rebuild rather than a hand merge, because a merge resolved without the story's context is where a parallel build goes wrong. Everything else is serial. Deciding which stories share a file (`wf bulk-schedule`) and fetching, cherry-picking, aborting and pushing (`wf bulk-integrate`) are done by `wf`, not by the model: both are mechanical, and a hand-run sequence of a dozen git commands per wave was slow and easy to get half-done.

One commit per story is for the reviewer and for whoever reverts one story later. A bulk pull request's specific failure mode is that its diff cannot be attributed — a reviewer cannot tell which change answers which requirement, so they either approve it wholesale or reject it wholesale, and the second review is no better than the first. One commit per story, each naming its issue number, makes the diff readable in the order it was written and makes `git revert` a real option.

The same reasoning is behind stopping the build when the quality gate stays red rather than moving on to the next story. Code stacked on a broken tree is harder to attribute, not easier, and the run has a better outcome available: ship what is green, release the rest.

## Why the reviewer is asked about scope creep

A reviewer with the usual lens catches what it catches in a single-story diff. A multi-story diff adds one failure mode it will not go looking for: a change that belongs to none of the stories, which in a large diff reads as just more of the same. Asking the question explicitly is cheap and it is the one thing a bulk review needs that a single-story review does not.

## Budget and size

The ~150k token budget is ~1.5x `execute`'s, for up to seven stories, because the shared costs — the plan, the review, the merge, the configuration read — are paid once, and builders spawned for a parallel wave spend their own contexts. The saving is in the shared work, not in the per-story work, so the number does not scale with the set.

Until 17.4.0 a set was capped by a count of stories (`--size`, 2 to 7). A count cannot tell five small stories against one module from three large ones across three subsystems, so 17.4.0 replaced it with an effort budget of 7, where `Effort` Low is 1, Medium 2 and High 6: a High story leaves room for one Low story and nothing larger. `--size` was removed rather than kept as an alias, so no existing value silently changed meaning. The Phase 3 re-check stays, because that judgement is much better informed after planning than before it, and dropping a story then costs one release rather than a failed run.

## Why a set is split into at most two pull requests

Requiring stories to be linked meant a backlog of unrelated stories gave a bulk run one story, which is `execute` with more ceremony. Since 17.4.0 the budget is filled by priority whether or not the stories are linked, with two limits that keep the result reviewable. Stories more than one `Priority` level apart never share a set, so urgent work is not held up by low-priority work. Feature and maintenance work never share a pull request, because a feature bundled with a bug fix cannot be reverted without losing both, so a mixed set becomes two groups.

The groups are built one after another rather than in parallel. Group 1 goes through build, review and merge before group 2 is written, for two reasons. A run can have a tool to start agents and still fail to start a reviewer, and group 1's review shows whether it can before more code exists; if that review ran inline (`.claude/self-review.flag`), group 2 is returned to the backlog unbuilt, because a second inline review is what fills the context. And a group holding a prerequisite of the other is merged first, so the second group builds on `main` rather than on another feature branch. A run with no tool to start agents passes `--max-groups 1` from the start. Two groups run in sequence take roughly twice as long as one, so a two-group run sits nearer the timeout; a group not yet started when it passes is dropped whole.

## Why the disclosed self-review carries over unchanged

`execute` merges on a self-review when no separate agent context can be spawned, provided the run says so on the pull request and in its report. The reasoning is in `docs/rationale/execute-rationale.md`: a workflow that can only finish when the harness happens to offer subagents is a workflow that stops half way in every nested run, leaving an unreviewed pull request that nothing is scheduled to pick up.

A set makes that outcome worse rather than better, which is the argument for keeping the same answer here. A stranded single-story pull request holds up one story; a stranded bulk one holds up three to five, and every one of them has already been claimed, built and set to `In Review`, so nothing else will touch them either. Refusing to merge without an independent reviewer would trade weaker evidence for a larger backlog of work that is finished but cannot land.

What does change is the standard the fallback is held to. The whole lens plus the scope-creep question is carried explicitly and in order, because the failure mode of an inline review of a large diff is a single skim that reports nothing; and the disclosure lists the stories the pull request closes, because how much a weak verdict matters depends on how much it covers. The real merge gates are untouched: they carry evidence about the code rather than about who read it.
