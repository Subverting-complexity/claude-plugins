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

## Label Reference for Agents

Any agent encountering these labels on a PR should understand what they
mean and what action (if any) to take. Labels use the prefix defined in
`review.config.md`.

### State labels (mutually exclusive — exactly one per PR)

| Label | Meaning | Agent action |
| ----- | ------- | ------------ |
| `{PREFIX}-reviewing` | A review agent is actively reviewing this PR. | **Do not touch.** Wait for the review to complete. Do not start a review, update, or push to this PR. |
| `{PREFIX}-updating` | A builder agent is addressing review feedback. | **Do not touch.** Wait for the update to complete. Do not start a review or competing update. |
| `{PREFIX}-approved` | Review passed, no remaining issues. | Ready for human merge. No agent action needed unless new commits are pushed (see `needs-re-review`). |
| `{PREFIX}-changes-requested` | Review found issues requiring human or builder action. | **Builder**: Run `/github-workflow:update-pr` to address the feedback. **Reviewer**: Skip, waiting on builder. |
| `{PREFIX}-needs-re-review` | New commits pushed since last review. | **Reviewer**: Prioritise this PR for re-review. **Builder**: No action — wait for review. |
| `{PREFIX}-needs-discussion` | Architectural or scope questions need human judgment. | **All agents**: Do not auto-fix. Flag to human. |
| `{PREFIX}-review-failed` | Review could not complete (checkout failed, PR too large). | **Reviewer**: May retry on next run if root cause is resolved. **Builder**: Investigate the failure. |

### Action labels (sticky, not mutually exclusive)

| Label | Meaning | Agent action |
| ----- | ------- | ------------ |
| `{PREFIX}-fixes-applied` | Claude pushed fix commits to this PR branch. | Informational. Do not remove — it persists across review cycles. |

### Concurrency rules

- **Before reviewing**: Check for `reviewing` and `updating` labels.
  If either is present, skip the PR entirely.
- **Before updating**: Check for `reviewing` and `updating` labels.
  If either is present, skip the PR entirely.
- **Claiming**: Apply your claim label (`reviewing` or `updating`),
  wait 2 seconds, re-read labels to confirm you still own the claim.
- **On exit or error**: Always remove your claim label so other agents
  can proceed.
