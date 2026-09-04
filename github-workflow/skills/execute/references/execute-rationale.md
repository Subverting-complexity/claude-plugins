# Execute skill — rationale (not read at runtime)

The "why" behind the imperative rules in `skills/execute/SKILL.md`.
Maintainers read this; the runtime workflow does **not** load it. Keep
the SKILL.md steps imperative; keep the reasoning here.

## Why the ~100k session budget and one-story-per-session rule

A single execute run loads a large instruction surface before any feature
code is touched, and context quality degrades as a session grows. Capping
each session at roughly 100k tokens and one story keeps each run able to
produce a shippable artifact (branch + PR) rather than drifting. Committing
and pushing early matters because a session can end unexpectedly: committed
work on a pushed branch is recoverable, uncommitted work is lost. Pushing
after each major phase (plan done, core implementation done, tests passing)
creates explicit recovery points.

## Why the 45-minute timeout check

The harness can kill a long-running session mid-work. Checking elapsed time
before each phase and, past ~45 minutes, getting to a committable state and
exiting cleanly means the harness never kills the session with nothing
saved. A partial PR with clear "remaining work" notes is worth more than an
abandoned session with no artifact — which is why the timeout path ships a
real PR when the work is shippable, and otherwise marks the issue
`status-needs-attention` with a comment rather than opening a PR for
incomplete work.

## Why the rate-limit pause

GitHub's authenticated API allows 5,000 requests/hour. A long autonomous
session accumulates many `gh` calls, and exhausting the quota mid-run
leaves work in an unknown state. Pausing when remaining quota drops below
~100 — commit, push, mark `status-needs-attention`, exit — lets the next
session resume from the pushed branch. Retrying rate-limited requests in a
loop only deepens the hole, so the rule is to stop, not retry.

## Why no draft PRs

Every shippable exit opens a **real** PR, never a draft. A draft signals
"not ready to look at," but the workflow's contract is that an opened PR is
a finished, reviewable slice — even a partial slice is complete and
self-contained, with follow-up issues filed for the remainder. Incomplete
work that is *not* shippable does not get a PR at all; it stays on the
pushed branch with the issue marked `status-needs-attention`.

## Why one reviewer, and why the severity rubric

Phase 8 used to spawn two reviewers with different lenses. The second one
mostly returned the first one's findings again, at a second reviewer's cost,
and every extra finding had to be reconciled by hand into one verdict. The
independence the phase needs comes from a context that never saw the build,
which one agent supplies as well as two.

What actually decided whether a review was useful was not how many agents
read the diff but what they were allowed to raise. An unfiltered review of a
real diff returns a long list in which two blocking defects sit among
fifteen preferences, and the run then spends its remaining budget answering
the preferences. The rubric is the filter: blocking findings, quick fixes,
the two things worth filing, and an explicit fourth bucket of observations
that are not findings at all and are left unsaid.

## Why a re-review has to be earned

Re-reviewing after every push turned a finished pull request into an open
one. Each round costs a push, an agent and a round trip, and most rounds
were spent re-reading a diff whose only change since the last reading was a
deleted unused import or a filled-in test case. The quality gate already
covers that class of change.

So the trigger is the nature of the rework rather than the fact of it: new
or changed logic, a new file or dependency, a behaviour change, a security
fix, or a file the first review never read. Anything smaller is pushed with
the gate as its evidence and named in the review comment, so the record
stays honest about what a fresh context did and did not see. The loop is
capped at one round for the same reason the budget is capped: a PR that is
still contested after one round of rework is better handed to the next
`/github-workflow:code-review` run, which reads it fresh, than argued with
by a session that has been on it for hours.

## Why a disclosed self-review is allowed to merge

Phase 8 exists because the session that wrote the code cannot judge it: it
shares every assumption the code was built on. Where a separate agent context
can be spawned, nothing changes — a fresh reviewer decides the verdict.

The question is what to do when no separate context is available at all,
which happens when `execute` is itself running as a subagent and the harness
does not allow nesting. Refusing to merge there sounded safe, but it made the
run structurally unable to finish its own work: an autonomous or scheduled run
in a nested context would build, self-review, and then always stop at an open
PR, waiting for a person the setup assumes is not there.

Weighed against that, the value of the block was small. It did not add
evidence about the code; it withheld an action. Everything that actually
carries evidence — the quality gate, the verdict, the CI gate, the conflict
check — is unaffected by how the reviewer was spawned, and all of it still
applies. What the block bought was a hedge against a review being weaker than
it looks, and a disclosure buys that more honestly: the PR comment and the
final report both say the review was not independent, so a reader can discount
it. The label travels with the work, which a silently unmerged PR does not.

The order matters too. The fallback tries a general-purpose subagent before
giving up, because the common cause is the `Reviewer` plugin agent type being
unavailable rather than spawning being impossible, and a general-purpose agent
in a fresh context is fully independent. The inline self-review is the last
resort, not the first fallback.

## Why in-scope findings are fixed rather than filed

Filing was once the answer to everything a review round turned up. Phase 9
split findings into "objectively correct answer" and "needs human judgment"
and said nothing about where the problem lived, so a non-blocking defect in
the run's own diff was as easy to file as to fix. That reads as diligent —
nothing is dropped, everything is tracked — and it is the wrong trade in
three ways.

It merges the defect. An issue on the board is not a fix; the pull request
still lands with the problem in it, and the board carries a promise that
somebody will come back. Multiply that by every run and the backlog fills
with a workflow's own leftovers, each one costing another pick, branch,
review and merge to settle what one edit on an already-checked-out branch
would have settled.

It is also the cheapest possible moment to fix. The branch is checked out,
the context that wrote the code is live, the reviewer has just read it,
and the pull request has not merged. Every one of those advantages is gone
by the time a filed issue is picked up.

The two exceptions are narrow for the same reason. A question only a person
can answer cannot be fixed by anyone in this run whatever the scope, so it
is filed and the pull request is held open on that verdict rather than
merged over it. Scope deliberately left out of a too-large story was never
a defect: it is the remainder of the work, and filing it is how the next run
finds it.

Out-of-scope problems keep going to the board because fixing them here would
be the opposite mistake. A pre-existing bug repaired mid-review widens a diff
the reviewer has already read, and the wider the diff the less the review
means.
