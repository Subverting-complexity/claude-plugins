# Review Workflow Reference

Reference material for agents interacting with PR review state.
The code-review skill's SKILL.md contains the step-by-step workflow;
this file covers the supporting context.

---

## Addressing Review Feedback

### Automatic (during this review run)

Step 7 fixes all objective issues and pushes them. Step 8 then
re-evaluates the verdict **after** those fixes. If every issue was
auto-fixed (Issues Remaining is empty), the verdict is **Approved** and
the PR gets the `approved` label. The reviewer should fix aggressively —
minor observations (missing trailing newline, utility placement, etc.)
are cheap to fix and should not generate a "Changes Requested" round-trip.

### Manual (separate invocation)

When issues remain that the reviewer could not auto-fix, the PR is
left with the `changes-requested` label. To address that feedback:

- A human or **builder** agent runs `/github-workflow:update-pr` to
  read the review comment, fix each item in Issues Remaining, push
  changes, and update labels. (The reviewer agent is read-only and
  cannot run this command — it requires file editing and git push
  access.)
- Alternatively, anyone (human or agent) can push commits to the PR
  branch directly. The next code-review run will detect the SHA change
  (Step 1) and re-review the PR automatically — no explicit
  `/update-pr` invocation required.
- The next code-review run will pick up PRs with `needs-re-review`
  (they are prioritised in Step 1) and perform a re-review.

### Change significance on update

When changes are pushed to a reviewed PR (by `update-pr`, ad-hoc push,
or any other process), the change significance determines what happens
next.

**Trivial changes — auto-approve if all issues addressed:**
- Whitespace, formatting, or import-order fixes
- Typo corrections in comments or documentation
- Removing dead code flagged in the review
- Variable renames with no behaviour change

If the pusher is `update-pr` and all Issues Remaining were addressed:
remove the current state label and apply `approved`. No re-review needed.

If changes are trivial but pushed ad-hoc (no explicit update-pr run):
leave the existing state label in place. The next code-review run will
detect the SHA change, fast-track the re-review (Step 4b), and apply
the appropriate verdict.

**Substantial changes — re-review required:**
- New or modified logic, control flow, or calculations
- New files, dependencies, or changed APIs
- Test additions or modified assertions
- Security-relevant changes
- Anything that alters observable behaviour

Remove the current state label and apply `needs-re-review`:

```bash
gh pr edit <number> --remove-label "<current-state-label>" --add-label "<needs-re-review-label>"
```

The code-review skill's Step 4b will then assess whether the re-review
can be fast-tracked (trivial changes on an approved PR) or requires a
full pass.

---

## Duplicate PRs for one issue

The atomic issue claim (`refs/claims/issue-N`) prevents two agents from
selecting the same story concurrently, so duplicate PRs should be rare.
They can still appear at the edges the claim ref does not cover:

- A story started by **explicit number** (`/execute 42`, `/start-story 42`)
  after a PR already exists — the claim ref was released when the first PR
  opened, so a fresh claim succeeds. The pre-start guards in `execute`
  Phase 1 and `start-story` stop most of these before any work happens.
- `block-story` run on an issue that **already has an open PR** — without
  the guard in its release step, it would unassign the issue and return it
  to the pool, inviting a second PR.
- A hand-reaped claim ref (manual orphan recovery) deleted while a PR was
  still live.
- A true create-time race: two sessions that each passed every earlier
  gate and opened a PR on a different branch.

When two open PRs close the same issue, **code-review Step 2b** reconciles
them: it picks the winner — mergeable/gate-green over broken, then
acceptance-criteria coverage, then test coverage, then **lowest PR number**
as a deterministic tie-break — and closes the loser(s) with a comment
linking the survivor. The deterministic tie-break matters: two reviewers
evaluating the same set independently must agree on the winner, so neither
closes the other's keeper. A loser is closed by whichever agent can claim
its `refs/claims/pr-N` ref (its own holder, or the winner's reviewer if it
is free); a PR being actively reviewed or updated is left for the next
round. Closing a duplicate is the **only** time the review flow closes a
PR. The losing branch is never deleted, so its work can be salvaged into
the survivor.

`execute` Phase 7 and `finish-story` add a lighter, detection-only guard
at PR-creation time: if a sibling open PR already closes the issue, the
new PR is flagged as a possible duplicate so this reconciliation reliably
fires on the next review.

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

### Concurrency rules

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
