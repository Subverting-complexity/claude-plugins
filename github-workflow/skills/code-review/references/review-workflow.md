# Review Workflow Reference

Read this when you need to look up a **label purpose** or verify the
**claim/release procedure** for a PR. Skip it on the common path when
label names and claim steps are already clear from `SKILL.md`.

For background on the feedback loop (how builders address review
comments, how change significance is classified) and why duplicate PRs
arise, see `references/review-workflow-rationale.md` — not read at
runtime.

---

## Label Reference for Agents

Any agent encountering these labels on a PR should understand what they
mean and what action (if any) to take. Labels use the prefix defined in
`review.config.md`. The bare names below (`reviewing`, `updating`,
`approved`, …) are **purpose keys** — resolve each to its concrete name
through the single path in `templates/default-labels.md` before applying
or filtering. Never apply a bare name literally.

### State labels (mutually exclusive — exactly one per PR)

| Label | Meaning | Agent action |
| ----- | ------- | ------------ |
| `{PREFIX}-needs-review` | Open PR awaiting its first review (entry state set at creation). | **Reviewer**: Pick it up for review (after `needs-re-review` PRs). **Builder**: No action — wait for review. |
| `{PREFIX}-reviewing` | A review agent is actively reviewing this PR. | **Do not touch.** Wait for the review to complete. Do not start a review, update, or push to this PR. |
| `{PREFIX}-updating` | A builder agent is addressing review feedback. | **Do not touch.** Wait for the update to complete. Do not start a review or competing update. |
| `{PREFIX}-approved` | Review passed, no remaining issues. | Ready for human merge. No agent action needed unless new commits are pushed (see `needs-re-review`). |
| `{PREFIX}-changes-requested` | Review found issues requiring human or builder action. | **Builder**: Run `/github-workflow:update-pr` to address the feedback. **Reviewer**: Skip, waiting on builder. |
| `{PREFIX}-needs-re-review` | New commits pushed since last review. | **Reviewer**: Prioritise this PR for re-review. **Builder**: No action — wait for review. |
| `{PREFIX}-needs-discussion` | Architectural or scope questions need human judgment. | **All agents**: Do not auto-fix. Flag to human. |
| `{PREFIX}-failed` | Review could not complete (checkout failed, PR too large). | **Reviewer**: May retry on next run if root cause is resolved. **Builder**: Investigate the failure. |

### Action labels (sticky, not mutually exclusive)

| Label | Meaning | Agent action |
| ----- | ------- | ------------ |
| `{PREFIX}-fixes-applied` | Claude pushed fix commits to this PR branch. | Informational. Do not remove — it persists across review cycles. |

---

## Concurrency rules

The real lock is an atomic claim ref, **not** a label. Both reviewing and
updating a PR claim the same `refs/claims/pr-<number>` ref via
`templates/claim-procedure.md`, so a reviewer and an updater are mutually
exclusive on a PR even under a shared GitHub identity (a shared label
cannot guarantee this — it reads present for every agent). The `reviewing`
/ `updating` labels remain **human-visible display markers** that the
skip checks below still read.

- **Before reviewing**: Check for `reviewing` and `updating` labels as a
  cheap first filter — if either is present, skip the PR entirely. The
  atomic claim is the authoritative gate if the labels race.
- **Before updating**: Same label pre-check, then claim atomically.
- **Claiming**: Run `templates/claim-procedure.md` **Acquire** for target
  `pr-<number>`. On success it applies your display label (`reviewing` or
  `updating`). If the claim is lost, exit without changes — do not fall
  back to a label-only claim.
- **On exit or error**: Run **Release** for `pr-<number>` (delete the
  ref), then remove your display label so other agents can proceed.

**Push-race safety.** A reviewer records HEAD at checkout, may push fixes,
and footers `Reviewed at <SHA>`. A concurrent builder push between checkout
and the reviewer's push would make that push a non-fast-forward reject —
but the shared `refs/claims/pr-<number>` mutex means a reviewer and an
updater can never hold the PR at the same time, so this race cannot occur.
The claim ref, not the labels, is what guarantees it.
