# Review workflow — rationale (not read at runtime)

Background context for maintainers and other agents learning how the
PR review state machine works. The runtime code-review skill does
**not** load this file. The imperative procedures are in
`references/review-workflow.md` (label table, concurrency rules) and
`SKILL.md` (the review steps).

---

## Addressing review feedback

### Automatic (during the review run)

Step 7 of the review fixes all objective issues and pushes them. Step 8
then re-evaluates the verdict **after** those fixes. If every issue was
auto-fixed (Issues Remaining is empty), the verdict is **Approved** and
the PR gets the `approved` label. The reviewer fixes aggressively —
minor observations (missing trailing newline, utility placement, etc.)
are cheap to fix and should not generate a "Changes Requested" round-trip.

### Manual (separate invocation)

When issues remain that the reviewer could not auto-fix, the PR is left
with the `changes-requested` label. To address that feedback:

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

## Why duplicate PRs arise

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
- A true create-time race: two sessions that each passed every earlier gate
  and opened a PR on a different branch.

When two open PRs close the same issue, **code-review Step 2b** reconciles
them using the procedure in `references/duplicate-reconciliation.md`.
`execute` Phase 7 and `finish-story` add a lighter, detection-only guard
at PR-creation time: if a sibling open PR already closes the issue, the
new PR is flagged as a possible duplicate so this reconciliation reliably
fires on the next review.
