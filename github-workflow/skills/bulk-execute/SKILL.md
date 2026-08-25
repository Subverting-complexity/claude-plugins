---
name: bulk-execute
description: >-
  Build two to five related GitHub stories together on one branch behind one
  pull request: pick the set, plan, build story by story, test, open one PR,
  have it reviewed independently in a fresh context, merge where enabled.
  Trigger on "bulk execute", "batch these stories", "do the next few related
  stories together", or several issue numbers to build as one change. Use
  execute instead when there is only one story.
depends-on:
  - code-architect
  - structured-coding
  - code-review
argument-hint: '[issue# issue# ...] [--mode feature|maintenance] [--size N] [--no-merge] [--bypass-ci]'
arguments:
  - name: story_numbers
    description: 'Optional list of issue numbers to build together, e.g. "41 43 47". Naming them is the precise way to choose the set. If omitted, the ready pool is read and a related group is chosen from it deliberately.'
  - name: mode
    description: 'Selection mode for the lead story: story (default), feature (feature stories only), maintenance (bug/security/architecture/debt). A set never mixes modes.'
  - name: size
    description: 'Maximum stories in the set, 2 to 5 (default 5). The cap is a ceiling, not a target: only genuinely related stories belong in one set.'
  - name: no-merge
    description: 'Stop after the independent review and rework instead of merging. The PR is left open carrying the reviewer verdict.'
  - name: bypass-ci
    description: 'Treat CI as satisfied when remote checks are red or absent. Explicit, never default — use only when CI cannot run for reasons outside the PR.'
---

# Bulk Execute

Take **two to five related stories** and land them as **one change**: one
branch, one set of commits, one pull request, one independent review, one
merge. Everything `execute` does for a single story, done once for a set
whose members share enough context that building them together costs less
than building them apart.

The saving is real but narrow. It comes from planning the same subsystem
once, opening the same files once, and having one reviewer read one
coherent diff. It disappears the moment the stories are unrelated, at which
point this command produces a pull request nobody can review and nobody can
revert cleanly. **Choosing the set is the hard part of this workflow**, and
most of the discipline below is about choosing it well and shrinking it
when it turns out to be wrong.

**Use `/github-workflow:execute` instead** when there is one story, when the
stories touch different subsystems, or when any one of them is large enough
to fill a session on its own.

## Plain-English output

Everything you write for a person to read (plan, progress notes, PR description, final summary) follows `skills/_shared/wording-standard.md` and avoids `skills/_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

**This workflow is fully autonomous.** Every phase flows into the next
without pausing for user input. Opening the pull request is not a stopping
point: Phases 8 to 10 need no permission, no confirmation and no green CI.
A run that reports its new PR and offers to review it if asked has stopped
half way, however finished it sounds.

The one thing this workflow does stop for is a **set it cannot justify**.
If nothing in the backlog is genuinely related to the lead story, say so
and run the lead on its own rather than padding the set.

## Invocation flags

`--no-merge` and `--bypass-ci` are read in Phase 10, long after they are
parsed, so record whichever was passed on disk now — a compaction in
between would otherwise lose them.

```
mkdir -p .claude
rm -f .claude/no-merge.flag .claude/bypass-ci.flag \
      .claude/gate-failed.flag .claude/self-review.flag \
      .claude/bulk-set.json .claude/claim-*.sha
touch .claude/no-merge.flag    # only when --no-merge was passed
touch .claude/bypass-ci.flag   # only when --bypass-ci was passed
```

The unconditional `rm -f` comes first because a run that was hard killed
before **Exit cleanup** would otherwise leave its flags behind, and an
inherited `bypass-ci.flag` would quietly disarm the Phase 10 CI gate.
Sweeping `claim-*.sha` and `bulk-set.json` is safe here and nowhere else:
this run holds no claim and has no set yet, so any such file is a leftover
from a killed run.

**Run this block exactly once, here, at the start.** It is destructive —
re-running it later would wipe the `gate-failed.flag` Phase 5 wrote, the
`self-review.flag` Phase 8 wrote, and the set Phase 1 recorded. Later
phases only read these files.

`--size` caps the set at 2 to 5 stories, default 5. A value outside that
range is clamped, and the clamp is reported. Five is a ceiling rather than
a target: a set only reaches it when five stories are genuinely one change
and each is small enough to leave room for the review phases.

## Preflight

If `.claude/preflight-passed.txt` exists, preflight already passed this
session — skip it. Otherwise, and only if the configuration block below
does **not** print "ClaudeProject.md NOT FOUND", invoke
`/github-workflow:preflight`. If it finds issues and the user chooses
"Configure now", wait for setup and ask the user to re-run this command.
On "Continue anyway", proceed.

```
test -f .claude/preflight-passed.txt && echo "PREFLIGHT_ALREADY_PASSED"
```

## Project configuration (auto-loaded)

This emits a projection of `ClaudeProject.md`: the configuration the
pick, plan and build window needs, dropping the heavy sections needed only
later. When a later phase resolves the **board** or the **org issue
fields**, read the omitted `## Project Board` or `## Issue Types & Fields`
section straight from `ClaudeProject.md` then.

```!
if [ -f .claude/projected-config.md ] && [ .claude/projected-config.md -nt ClaudeProject.md ] 2>/dev/null; then
  cat .claude/projected-config.md
elif [ -f ClaudeProject.md ]; then
  # Drop the heavy sections only needed later. Pure POSIX shell (no
  # awk/tee) so it runs on a Windows bash whose PATH lacks Unix coreutils.
  mkdir -p .claude 2>/dev/null
  drop=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '## '*) case "$line" in
          '## Issue Types & Fields'*|'## Project Board'*|'## Story Template'*|'## Session Budget'*|'## Reference Docs'*|'## Bundled Skills'*) drop=1 ;;
          *) drop=0 ;;
        esac ;;
    esac
    [ "$drop" -eq 0 ] && printf '%s\n' "$line"
  done < ClaudeProject.md > .claude/projected-config.md
  cat .claude/projected-config.md
else
  echo "ClaudeProject.md NOT FOUND"
fi
```

If that shows "NOT FOUND", stop with exactly one message —
"ClaudeProject.md not found — run /github-workflow:setup." — and do not
chain into preflight for the same root cause.

Otherwise validate the projection: it must contain both an `## Identity`
and a `## Quality Gate` section. If either is missing, stop with
"ClaudeProject.md is missing required section: {name} — run
/github-workflow:setup."

Read `CLAUDE.md` for project rules and build principles.

## Session prewarm

Read the current API quota — the only eager warm-up:

```
gh api rate_limit --jq '.rate.remaining'
```

A bulk run makes more `gh` calls than a single-story one, because it
claims, labels, moves and settles several issues rather than one. If the
count is below **300**, do not start a bulk run: say so, and suggest
`/github-workflow:execute` for a single story instead. Below **100**, take
the rate-limit pause described below and exit after cleanup.

## Session budget

Stay under ~150k tokens for the whole set, and treat that as the constraint
that decides how many stories the set holds, not the other way round. The
run produces one shippable artifact: a merged pull request, or an open one
whose review state is recorded. (Design rationale for this and for every
other decision below: `references/bulk-rationale.md` — not read at runtime.)

- **The set is sized to the budget at Phase 1, and re-sized at Phase 3.**
  If the plan shows the set does not fit, drop stories from it before
  writing any code (`references/set-selection.md`, **Dropping a story**).
- **Commit per story, push after each.** An unexpected end then leaves
  whole stories on the branch rather than a half-written one.
- **The pull request only ever closes stories it actually implements.** If
  the budget runs out with stories unbuilt, release those claims back to
  the backlog and open the PR for what was built. Never write `Closes #N`
  for a story this run did not finish.
- **One set, one session.** Do not pick a second set after finishing.
- **Leave room for the review phases, and size the set so they fit.** Phases
  8 and 9 hand the reading of the diff to separate contexts, so here they
  cost the review reference, the merge mechanics, the findings returned, and
  the fixes you apply — plus, when no agent can be spawned, the whole
  code-review hot path inline on top of a session that has already built
  several stories. That is the reason to stop short of the cap when the
  stories are not small: running out of budget before the review strands
  every story in the set at once, not just the last one.
- **60-minute timeout.** Record the start time (`date +%s`); before each
  story and each phase, check the elapsed time. Past 60 minutes: commit and
  push, release the claims of the unbuilt stories, then run Phase 7 for a
  **real** pull request (never a draft) covering the built ones and carry
  on into Phases 8 to 10. If nothing is shippable, leave the branch pushed,
  move every claimed issue to `status-needs-attention` with a comment
  listing what remains, file follow-ups, and run **Exit cleanup**.

## API rate limiting

Before a batch of `gh` calls, check the remaining quota
(`gh api rate_limit --jq '.rate.remaining'`). If it is below **100**,
pause: commit and push current work, move every claimed issue to
`status-needs-attention` (removing `status-in-progress`) with a comment
noting the pause, run **Exit cleanup**, then exit. **Once the pull request
is open (Phase 8 onward)** leave the issues at `status-in-review` and note
the pause on the PR instead, so the labels, the board and the PR's review
state stay in agreement. Do not retry rate-limited requests in a loop.

## Mode selection

Default mode is `story`. Override with `$ARGUMENTS.mode`: `feature` (feature
stories only) or `maintenance` (bug, security, architecture, tech debt).

**A set never mixes modes.** A feature bundled with an unrelated bug fix
produces a pull request that cannot be reverted without losing one or the
other. The mode of the lead story fixes the mode of the whole set.

There is no `audit` mode here: an audit changes no code, so there is
nothing to bundle. Use `/github-workflow:execute --mode audit` for that.

---

## Fix in scope, file out of scope

One rule governs every problem this run finds, from the first line of the
build to the last review round. In a bulk run "in scope" is wider than
usual, and that is deliberate:

- **In this pull request's own diff, or in any of the stories it closes** —
  fix it here, on this branch, before the PR merges. Never file it: a
  defect in work this run is building is this run's work to finish.
- **Anywhere else** — a pre-existing bug in untouched code, a security or
  architecture problem noticed in passing, a problem belonging to a story
  that is *not* in this set — file it with `/github-workflow:report-issue`
  and carry on. Do not fix it inline; that widens a diff the reviewers
  already have plenty to hold.

Two exceptions stay filed: a finding only a person can settle (an ambiguous
requirement, an architectural choice with several defensible answers),
filed as the question with the PR left open on that verdict; and a story
dropped from the set, which is backlog work rather than a review finding.

---

## Exit cleanup

Every exit path — finish, block, failure, timeout, rate-limit pause — ends
by running `skills/execute/references/exit-cleanup.md` as the **final**
step, **after** any commit or push. Read it with one substitution: its step
1 releases **one** issue claim, and this run holds one per story in the
set. Release every `refs/claims/issue-{number}` and delete every
`.claude/claim-issue-{number}.sha` — read `.claude/bulk-set.json` for the
list if the set is no longer in context. Its step 2 also deletes
`.claude/bulk-set.json`. Everything else in that file applies unchanged,
including the review-claim reconciliation and the working-tree reconcile.

---

## Phase 1 — Choose the set, then claim every story in it

The set is **chosen**, never taken off the top of the backlog. Priority
order decides which story is worth doing next; it says nothing about which
stories belong in one pull request, and a set assembled by taking the top
few off the backlog is the failure this command is most likely to produce.
Whichever path below applies, the choice is deliberate and the reason for
each story being in the set is recorded.

**Read `references/set-selection.md` and follow it.** It covers both paths:

- **Named stories** (`$ARGUMENTS.story_numbers` given, e.g.
  `/github-workflow:bulk-execute 41 43 47`) — the user has already made the
  choice. Validate each named story, check none is already in flight, and
  claim them all. Relatedness is not re-litigated; a named story is only
  ever dropped when it cannot be worked at all.
- **No numbers given** — read the ready pool with
  `wf candidates --mode {mode}`, which returns the same filtered,
  priority-sorted pool `execute` would pick from and claims nothing. Group
  it into genuinely related stories, choose one group against the
  relatedness rules, and only then claim.

Either way, **every story in the set gets a real atomic claim** before any
code is written — the `refs/claims/issue-{number}` ref, plus
`status-in-progress`, the `@me` assignment and the board move. A story
being built without its own claim is a story another agent can pick up
underneath you.

Phase 1 ends in one of three states:

- **Two or more stories claimed** — continue to Phase 2 with the set in
  build order.
- **One story claimed** — nothing in the pool was related enough to justify
  bundling, or only one named story survived validation. Say so plainly,
  and run the rest of this workflow for that single story. The result is an
  ordinary single-story pull request, which is a correct outcome rather
  than a failed bulk run.
- **Nothing claimed** — report why (no candidates, or every one claimed
  away) and stop.

## Phase 2 — Start

1. **Confirm the claims.** Every story in the set was claimed in Phase 1,
   with `status-in-progress` applied, `@me` assigned, and the board moved
   to In Progress. Re-run Acquire (`templates/claim-procedure.md`) for a
   story only if Phase 1's claim state was lost to compaction — its
   re-entry check makes a still-held claim a no-op. Do not issue a bare
   `--add-assignee @me` as a claim; the `refs/claims/` ref is the lock.

2. **Start clean.** Run the **Start clean** check in
   `templates/worktree-hygiene.md` before branching. A worktree provisioned
   dirty is inherited junk: reset it to a pristine baseline and report it,
   so it is never mistaken for this session's work.

3. **Create the one shared branch.** Render the `branch-convention` from
   `ClaudeProject.md` with `{number}` = the **lead** story's number and the
   slug describing what the **set** has in common, not the lead's own title
   — `feature/41/label-resolution` for a set about label resolution, rather
   than `feature/41/fix-missing-status-label`. Then:

   ```
   git fetch origin {default-branch}
   git checkout -b {branch} origin/{default-branch}
   ```

   Record the branch name in `.claude/bulk-set.json`.

Board failures are loud but not fatal: report them ("Board update failed:
{error}. Continuing.") and proceed. When no board is configured, skip the
board silently.

## Phase 3 — Plan the set as one change

Use `/github-workflow:code-architect` **once**, over the whole set, rather
than once per story. Pass every story's requirements together, the relevant
codebase context, and any reference docs listed in `ClaudeProject.md`.
Planning the set in one pass is where most of this command's saving comes
from: the shared design decision gets made once, with all the requirements
that depend on it visible at the same time.

Write the plan to `.claude/plan.md` so it survives compaction, structured
by story in **build order**, with a shared section for anything more than
one story touches:

```
## Shared
- [ ] src/labels/resolve.ts — the lookup all three stories build on

## Story #41 — Resolve labels by purpose key
- [ ] src/labels/resolve.ts — add the purpose-key path
- [ ] tests/labels/resolve.test.ts — purpose-key cases

## Story #43 — Report the label that was missing
- [ ] src/labels/report.ts — new reporter
- [ ] tests/labels/report.test.ts — reporter tests
```

Mark each file `[x]` as Phase 4 completes it. If the session compacts
mid-build, re-read `.claude/plan.md` for what is done, and check
`git log --oneline` and `git status` to confirm what was actually
committed.

**Then re-check the set against the plan.** This is the last cheap moment
to shrink it. If the plan shows the set will not fit the budget, or that
two stories pull the same code in different directions, drop the weakest
story now — `references/set-selection.md`, **Dropping a story** — and
re-plan without it. Dropping a story here costs one release; discovering
the same problem in Phase 9 costs the whole run.

If requirements have gaps, make reasonable assumptions and note them in the
plan. Only stop if a story is so underspecified that any implementation
would be a guess, and then drop that story rather than the run.

**Ecosystem tools.** Before reading files blind to plan, check whether
`.claude/ecosystem.md` exists. If it does, the project opted into the
codebase-intelligence tools it lists, so use them as the first move:
**Graphify** (`graphify . --update`, then `graphify query "..."` rather
than blind file search for structure questions) and **Fallow** (existing
exports and duplication, so the plan reuses what is there). If the file
does not exist, the project opted out — skip this step silently and never
nag about it. A listed tool missing from `PATH` is one line of note, not a
blocker.

## Phase 4 — Build, story by story

Use `/github-workflow:structured-coding` to implement, working through the
set **in build order**, one story at a time. Do not interleave them: a
reviewer has to be able to see which commit answers which story, and so
does anyone reverting one of them later.

For each story in order:

1. Implement it, code and tests together, following the build principles in
   `CLAUDE.md` — one responsibility per file, no domain-to-infrastructure
   imports, every module unit-testable in isolation, and a search for an
   existing utility before adding a new one.
2. Run **Phase 5**, the quality gate, for that story.
3. Run **Phase 6**, the commit, for that story.
4. Push, then move to the next story.

Shared work — the code more than one story needs — is written once, with
the first story that needs it, and that commit says so.

Do not pause for user confirmation at any point: the issue requirements and
the Phase 3 plan are the approved specification.

## Phase 5 — Verify (per story)

Run the quality gate command from `ClaudeProject.md` after each story:

1. Execute the gate.
2. If it fails: read the error output, fix the specific failing check, and
   re-run. Repeat up to 3 times (4 runs maximum). Near the token budget or
   the 60-minute mark, stop after 2 retries and treat it as still failing.
3. If it is still failing after 4 runs, **stop building**. Do not start the
   next story on a red gate: more code on top of a broken tree makes the
   failure harder to attribute, not easier. Commit what you have, set the
   gate-failed flag (`mkdir -p .claude && touch .claude/gate-failed.flag`,
   because Phase 10 reads it long after this decision and a compaction in
   between would otherwise lose it), release the claims of the unbuilt
   stories back to the backlog (`references/set-selection.md`, **Dropping a
   story**), and go to Phase 7. The pull request will be a real one
   carrying the `review-changes-requested` label and a "Quality Gate
   Failed" section, closing only the stories that were built.

## Phase 6 — Commit (per story)

1. Stage only the files belonging to this story. Never stage `.env`,
   credentials, or generated files that should be gitignored.
2. Write a commit message saying what was built and why, ending with the
   issue number it answers: `feat: resolve labels by purpose key (#41)`.
3. The quality gate hook runs automatically on commit.
4. One commit per story is the target. Where a story genuinely needs
   several, keep each one leaving the codebase in a working state.

## Phase 7 — Finish

When every story in the set is built, gated and committed, **read
`references/bulk-finish.md`** and follow it end-to-end: push, per-story
duplicate detection, one pull request closing every built story, PR labels,
the label change and board move for each issue, claim release, and the
progress note.

**Do not review your own diff anywhere in this run.** The session that
wrote the code shares every assumption it was built on, so its verdict is
worth little; Phase 8 gets a real one from contexts that never saw the
build. That governs whose judgement decides this pull request, not whether
the run continues — you still spawn the reviewers and own what they return,
and Phase 7 hands the PR to nobody. The single exception is Phase 8's
last-resort fallback below, used only when no separate context can be
spawned at all, and it is disclosed rather than silent.

## Phase 8 — Independent review, Phase 9 — Rework, Phase 10 — Merge

The moment the pull request exists, **read
`skills/execute/references/review-and-merge.md`** and follow it to the end
of the run, in the same turn as Phase 7, with no asking and no waiting on
CI. That file is the single specification of the review, rework and merge
mechanics: a review by agents in fresh contexts, a rework loop that answers
what they found, and the merge that settles the linked issues. Read it with
these substitutions, and nothing else changes:

- Where it says "the issue number and title it closes", give each reviewer
  **every** story in the set, by number and title, with its acceptance
  criteria. A reviewer who does not know a story is in scope reads its code
  as unexplained.
- **Add one question to the first reviewer's lens**, which is the failure
  mode specific to a bulk pull request: is there anything in this diff that
  belongs to **none** of the listed stories? Scope creep hides far better
  in a large multi-story diff than in a single-story one. Anything that
  turns up is either removed from the branch or explained in the PR body.
- Its Phase 9 fix-in-scope rule reads against **all** the stories the PR
  closes, not one. A gap the reviewers find in any of them is this run's
  unfinished work, and it is fixed here.
- Its Phase 10 duplicate-PR merge stopper applies **per story**: a possible
  duplicate flagged against any story in the set stops the merge for the
  whole pull request, because the PR is indivisible.
- Its Phase 10 settle step runs `wf post-merge --pr {pr_number}`, which
  already closes and moves **every** issue the pull request closes. Report
  each settled story by number and title.

### When no separate context can be spawned

Its Phase 8 step 3 — try a general-purpose subagent, then fall back to
running `/github-workflow:code-review {pr_number} --read-only` inline and
recording it with `touch .claude/self-review.flag` — applies here unchanged
in mechanism, and a bulk run is likelier to need it: this is exactly the
long, heavily-loaded session in which spawning fails. Four things follow:

- **Carry every lens yourself, one pass each**, not one undifferentiated
  read: correctness and story alignment against **each** story's acceptance
  criteria; then security, error handling, test coverage and regressions;
  then the bulk question, whether anything in this diff answers **none** of
  the listed stories.
- **The disclosure names the set.** Post step 3's warning on the pull
  request and repeat it in your final report, saying which stories it closes
  by number and title, so a reader can judge the blast radius of a verdict
  nobody else checked.
- **It does not stop the merge**, exactly as in `execute`. The gates that do
  — red quality gate, unapproved verdict, red or absent CI, a duplicate
  flagged against any story in the set — all still apply.
- **The rework loop is unchanged.** Findings against this diff, or against
  any story the PR closes, are fixed here. Being your own reviewer is not a
  reason to file what you found in your own work.

Merging is opt-in and off by default: it runs only where `review.config.md`
sets `Auto-Merge on Approval` to `enabled`. On a project that has not opted
in, the run ends at an approved pull request waiting for a person, and that
is a complete run rather than a failure.

---

## Escape hatches

Read `skills/execute/references/escape-hatches.md` when a run leaves the
happy path, with these substitutions for a set rather than a single story:

- **Blocked.** One story blocking does not block the run. Drop that story
  from the set (`references/set-selection.md`, **Dropping a story**, then
  `/github-workflow:block-story` for it) and carry on with the rest. Block
  the whole run only when the set drops below one buildable story and no
  code exists yet.
- **Dependency.** A dependency *inside* the set is the ordinary case here
  and needs no hatch: the dependency is built first, which Phase 1 already
  ordered. A dependency on an open issue *outside* the set drops that story
  from the set. Never chain a bulk branch off another feature branch: the
  pull request would then close several stories against a base that may
  never merge.
- **Too large.** Shrink the set, do not slice a story. Drop stories until
  what remains fits, and leave the dropped ones ready in the backlog for
  their own run.
- **Failure reporting.** Comment the failure on **every** claimed issue
  before exiting, and move each to `status-needs-attention`. Once the pull
  request is open, comment on the PR instead and leave the issues at
  `status-in-review`.
