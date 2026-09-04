# Label reference — issue-creation & review-state tables

The cold tables split out of `templates/default-labels.md` so the
claim/selection/board path doesn't load them. **Read this only on the
issue-creation path** (`report-issue`, `execute`'s retroactive issue,
`feature-discovery`) or the **review path** (`code-review`,
`execute` PR labelling). The resolution rules, workflow/status/type
labels, native-type map, priority map, and board columns all stay in
`default-labels.md` — resolve through the single path described there; the
tables below are the value maps for the dimensions used off the claim path.

## Effort and Origin field option maps

These moved into `scripts/wf_core.py` as `EFFORT_FIELD_OPTIONS` (story size
estimate → `Effort` option) and `ORIGIN_FIELD_OPTIONS` (creating command or
session → `Origin` option), alongside the rest of the issue-field value maps.
`wf` applies them directly, so there is nothing to look up by hand. See
`templates/default-labels.md` → *Issue Types & Field Values*.

## Review State Labels

These control the PR review workflow. Resolved via the Labels table in
`review.config.md` (matched by purpose key); defaults below use the
prefix `review`.

State labels are mutually exclusive — exactly one per PR. A PR enters
the machine at `needs-review` the moment it is opened (so a new PR is
never unlabelled), and the reviewer moves it from there.

| Purpose key | Default Name | Color | Description |
|-------------|-------------|-------|-------------|
| `needs-review` | `review-needs-review` | `C2E0C6` | Open PR awaiting its first review |
| `reviewing` | `review-reviewing` | `0E8A16` | Review in progress |
| `approved` | `review-approved` | `1D76DB` | Ready for human merge |
| `changes-requested` | `review-changes-requested` | `E4E669` | Issues need human action |
| `needs-discussion` | `review-needs-discussion` | `D93F0B` | Architectural questions |
| `needs-re-review` | `review-needs-re-review` | `FBCA04` | New commits since last review |
| `failed` | `review-failed` | `B60205` | Review could not complete |
| `updating` | `review-updating` | `0E8A16` | Builder addressing feedback |
| `fixes-applied` | `review-fixes-applied` | `5319E7` | Claude pushed fix commits (sticky) |
