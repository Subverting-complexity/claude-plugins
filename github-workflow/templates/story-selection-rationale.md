# Story selection — rationale

Background for `templates/story-selection.md`. Maintainer documentation,
**not part of the runtime path**.

## Why claim-first

The atomic claim (`templates/claim-procedure.md`) is the **cheapest**
operation in the whole flow — two git pushes. Dependency checks and
already-merged checks are the **expensive** ones (one `gh` call per
dependency, per candidate). The old design validated up to ten candidates
*before* claiming one — dozens of API calls to pick a single story.

Invert it: **claim the top candidate first, then validate only that one.**
In the common case (the top candidate is fine) this is ~3 calls instead of
~60. It stays race-safe because the atomic ref is still acquired before any
side effect — validation happens *after* you provably own the item, so no
two agents ever validate or mutate the same issue. The only cost is a
little label/assignee churn on the rare candidate that fails validation,
and that churn does useful work (it marks a genuinely-blocked issue
`status-blocked` or closes an already-resolved one).
