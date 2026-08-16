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

## Why a disclosed self-review is allowed to merge

Phase 8 exists because the session that wrote the code cannot judge it: it
shares every assumption the code was built on. Where a separate agent context
can be spawned, nothing changes — two fresh reviewers decide the verdict.

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
