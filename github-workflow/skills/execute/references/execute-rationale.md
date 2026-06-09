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
