# Bulk Execute — design rationale

Background for the decisions in `SKILL.md` and `references/set-selection.md`.
**Not read at runtime** — it exists so a later change does not silently undo
a decision that was made for a reason.

## Why a separate command rather than a flag on `execute`

`execute` is built around one story: one claim, one branch derived from that
story's number and title, one `Closes #N`, one issue to settle. Adding a
`--stories 41,43,47` flag would have put a second shape through every one of
those steps, and the phases where the two differ (selection, finish, the
per-story build loop) are exactly the phases carrying the most instruction
weight. The two would have spent most of their text saying "unless there are
several".

Keeping them apart also keeps `execute`'s measured token footprint where it
is. That footprint is gated in CI at two budgets, and the build window in
particular has been trimmed deliberately. A bulk branch inside it would have
grown the window every run pays for, in service of the runs that use it
rarely.

What the two **do** share is everything after the pull request exists.
`bulk-execute` reads `skills/execute/references/review-and-merge.md`,
`exit-cleanup.md` and `escape-hatches.md` directly, with substitutions listed
in its `SKILL.md`, rather than restating them. Those files are the canonical
specification of review, merge and cleanup, and a second copy would drift.

## Why the set is chosen rather than taken off the top

The first version of this command claimed the highest-priority story and
then gathered relatives around it. That is a cheaper procedure and it is
wrong in a specific way: the pool's priority order answers "what is worth
doing next", and the set needs an answer to "what belongs in one pull
request". Those are different questions, and letting the first stand in for
the second produces sets whose only common property is that they were near
each other in a sorted list.

So selection now reads the pool first (`wf candidates`, which claims
nothing), groups it, and chooses a group. Priority still decides **which**
group — the group holding the highest-priority story wins when it has two
members — so the most important work still goes first. It just brings its
relatives with it rather than its neighbours.

The user naming issue numbers is the precise form of the same thing, which
is why Path A does not re-run the heuristics. Someone naming three issues is
asserting the relationship directly, and a heuristic overriding that would
be the tool second-guessing the person holding the context.

## Why `wf candidates` exists

`wf pick` deliberately collapses select, claim, board-move and branch into
one call, because a single-story run wants exactly that and every seam
between those steps is a race. A bulk run needs the pool **before** it can
decide anything, so it needs the read without the write.

Putting that read in `wf` rather than in prose keeps one encoding of the
filters. Ready gate, sprint narrowing, refinement and agent-gating filters,
mode filter and priority sort are all tested logic in `wf_core`; an inline
`gh issue list` in the skill would have been a second, untested copy that
drifts the first time a filter changes. The inline path in
`templates/story-selection.md` remains as the fallback for a machine with no
Python, where a drifting second copy is better than no selection at all.

## Why a sibling dependency does not block

`execute` refuses a story whose dependency is still open, and that rule is
right: you cannot build on unmerged work you cannot fetch. A bulk set
breaks the premise rather than the rule. When the dependency is in the same
set, it is not unmerged work you cannot see — it is work this same run
writes, into the same commit series, on the same branch, under the same
review. By the time anything merges, both have.

That is why `wf pick --sibling` exists, and why the carve-out is expressed
as data (the sibling list) rather than as a bypass flag. `blocking_dependencies`
in `wf_core` takes the parsed dependencies, the ones found open, and the
siblings, and returns what still blocks. An open dependency outside the set
still blocks, so the rule survives intact for every case it was written for.

A dependency chain is also the best possible bulk set, which is worth saying
plainly: two stories where one waits on the other are two stories that would
otherwise be two runs and a merge apart.

## Why the branch is created by the skill, not by `wf`

`wf pick --checkout` names the branch from the story it claimed. With
several stories that produces several branches, one per claim, and the
second checkout would leave the first story's commits behind. `--no-branch`
keeps everything else that `--checkout` does — the board move especially,
which is per-issue and worth reusing — and leaves the branch to the caller,
which creates exactly one and records it in `.claude/bulk-set.json`.

The branch is named for the **lead** story's number and the **set's** shared
theme rather than the lead's own title, because a branch called
`feature/41/fix-missing-status-label` carrying three stories misdescribes
itself to everyone who sees it later.

## Why the pull request may only close stories it built

This is the invariant the whole finish phase is arranged around. A `Closes
#N` line is not a description; on merge it closes the issue, moves it to
Done and takes it out of the backlog. A line for a story that was dropped or
never finished deletes that work from the project's memory, and nothing
downstream will notice: the issue looks completed, the board looks clean,
and the code does not exist.

Hence `built` in `.claude/bulk-set.json`, flipped per story at commit time,
and hence the body validation step counting `Closes` lines against it rather
than reading them over. It is the one check in this workflow that fails
silently and expensively if skipped.

The mirror of the same rule is that a story which cannot be finished goes
**back to the backlog properly** — claim released, `status-ready` restored,
unassigned, board back to Backlog, and a comment saying what happened. A
story left assigned and `status-in-progress` after the run ends is invisible
to the picker and to the person who wrote it.

## Why the build is serial and one commit per story

Nothing technical requires it. It is for the reviewer and for whoever
reverts one story later. A bulk pull request's specific failure mode is
that its diff cannot be attributed — a reviewer cannot tell which change
answers which requirement, so they either approve it wholesale or reject it
wholesale, and the second review is no better than the first. One commit per
story, each naming its issue number, makes the diff readable in the order it
was written and makes `git revert` a real option.

The same reasoning is behind stopping the build when the quality gate stays
red rather than moving on to the next story. Code stacked on a broken tree
is harder to attribute, not easier, and the run has a better outcome
available: ship what is green, release the rest.

## Why the reviewers are asked about scope creep

Two reviewers with the usual lenses catch what they catch in a single-story
diff. A multi-story diff adds one failure mode they will not go looking for:
a change that belongs to none of the stories, which in a large diff reads as
just more of the same. Asking the question explicitly is cheap and it is the
one thing a bulk review needs that a single-story review does not.

## Budget and size

The ~150k token budget is ~1.5x `execute`'s, for up to five stories, because
the shared costs — the plan, the review, the merge, the configuration read —
are paid once. The saving is in the shared work, not in the per-story work,
so the number does not scale with the set.

That is also why the default size is 3 rather than 5, and why the guidance
says the smaller set is usually the better one. Five stories fit only when
each is genuinely small and they overlap heavily. The set being re-checked
against the plan in Phase 3 exists because that judgement is much better
informed after planning than before it, and dropping a story then costs one
release rather than a failed run.

## Why the disclosed self-review carries over unchanged

`execute` merges on a self-review when no separate agent context can be
spawned, provided the run says so on the pull request and in its report. The
reasoning is in `skills/execute/references/execute-rationale.md`: a workflow
that can only finish when the harness happens to offer subagents is a
workflow that stops half way in every nested run, leaving an unreviewed pull
request that nothing is scheduled to pick up.

A set makes that outcome worse rather than better, which is the argument for
keeping the same answer here. A stranded single-story pull request holds up
one story; a stranded bulk one holds up three to five, and every one of them
has already been claimed, built and labelled `status-in-review`, so nothing
else will touch them either. Refusing to merge without an independent
reviewer would trade weaker evidence for a larger backlog of work that is
finished but cannot land.

What does change is the standard the fallback is held to. Both review lenses
plus the scope-creep question are carried explicitly, one pass each, because
the failure mode of an inline review of a large diff is a single skim that
reports nothing; and the disclosure lists the stories the pull request
closes, because how much a weak verdict matters depends on how much it
covers. The real merge gates are untouched: they carry evidence about the
code rather than about who read it.
