---
name: code-review-rationale
description: Rationale behind the code-review skill's design decisions. Not read at runtime. Maintainers read this; the runtime workflow does not load it.
---

# Code-review skill — rationale (not read at runtime)

The "why" behind the imperative rules in `SKILL.md`. Maintainers and
contributors read this; the runtime review workflow does **not** load it.
Keep `SKILL.md` imperative; keep the reasoning here.

---

## Why fix non-blocking issues before approving (not "deferred for budget")

Earlier versions of this skill deferred non-blocking findings to a follow-up
pass to stay within a context budget. This caused a subtle problem: the
PR was approved and merged while known issues — trailing newlines, misplaced
utilities, dead code — sat in a "deferred" list that was never guaranteed to
be picked up. The tighter rule ("fix both tiers before approving, file
anything you genuinely can't fix") gives a clearer contract: an Approved PR
has had all objective problems addressed, either on the branch or on the
board. Nothing falls through the cracks silently.

Non-blocking fixes are cheap — they are formatting, placement, and naming
changes that are objectively correct and low-risk. Pushing them before
approval is almost never a budget concern in practice; it avoids a
round-trip that would otherwise require a separate review pass.

---

## Why filing to the board counts as "resolved" for the verdict

When a blocking problem genuinely needs design judgment — the reviewer
cannot make an objectively correct choice — the right action is to file it
to the board and leave it for a human or a later session. Holding the PR at
"Changes Requested" for a problem the reviewer filed to the board would mean
the PR is blocked indefinitely until the board item is resolved and someone
re-reviews. The board item tracks the work; the PR verdict signals whether
the code is structurally sound. A problem that needs human judgment is not
a structural defect in the current diff — it's a separate concern that the
board handles.

Non-blocking items follow the same logic: they are noted, filed for automatic
pickup, and the PR proceeds. Blocking the merge on non-blocking cleanups would
penalise the PR author for issues that do not affect correctness.

---

## Why the auto-merge feature defaults to disabled

Auto-merge commits to fully unattended operation: conflicts are resolved, CI
failures are fixed on the branch, and the PR is merged without human
confirmation. This is powerful but carries real risk — a misjudged merge
resolution or a "fix" that breaks an unrelated test could land silently. The
opt-in model means every project that enables it has made an explicit decision
to trust the reviewer's automated judgment end-to-end. Keeping it off by
default means mistakes in new projects are visible to a human before they
land.

The `require-ci-before-merge` gate (default `false`) is a companion control.
Without branch protection (unavailable on private repos with the Free plan),
it is the only server-side gate against merging a broken PR. Setting it `true`
means the reviewer will wait for CI and pause rather than merge if CI is red
or absent — trading some latency for a real quality guarantee.
