# Step 2b — Reconcile duplicate PRs for the same issue

Read this when the SKILL's **Step 2b** trigger fires (you have just claimed
a PR and are about to reconcile duplicates). It is kept out of `SKILL.md`
so the common single-PR review path does not carry it — duplicates are the
exception, not the rule.

Before spending a full review on the claimed PR, check whether **another
open PR resolves the same issue**. Duplicates should be rare — the atomic
issue claim (`refs/claims/issue-N`) stops two agents selecting one story —
but they can still arise at the boundaries the claim does not cover:
starting a story by explicit number after a PR already exists, a
`block-story` that returned an already-PR'd issue to the pool, a
hand-reaped claim ref, or a genuine create-time race where two sessions
each opened a PR on a different branch. When two open PRs close one issue,
exactly one must survive.

1. Determine the claimed PR's linked issue(s). Use GitHub's own closing
   parse, not the PR body: the claimed PR's `closingIssuesReferences`
   (returned by `wf sibling-pr {number}`) is the
   authoritative set `{issues}`. If the PR closes no issue, skip this step.
2. For each `#N` in `{issues}`, find every open PR that will close it by
   running `wf sibling-pr N` with that issue number.
   That returns the **duplicate set** `S` (oldest-first), each node already
   carrying `number`, `title`, `headRefName`, `isDraft`, and `labels` — the
   claimed PR will be in it.
3. If `S` contains only the claimed PR, there are no duplicates — skip the
   rest of this step and continue to Step 3.

**When `S` has more than one PR, pick the winner and close the rest.**

4. Determine the **winner** `W` by these criteria, in order — stop at the
   first that clearly separates them:
   a. **Mergeable & gate-green beats broken.** A PR with the `approved`
      review-state label, or whose required CI checks pass, beats one
      carrying `changes-requested` / `failed` or with failing checks.
   b. **Acceptance-criteria coverage.** The PR that satisfies more of the
      linked issue's acceptance criteria wins — but only when the gap is
      objective (one PR omits an entire criterion the other implements).
      Do not adjudicate on subjective polish.
   c. **Test coverage.** A PR that exercises its new code paths beats one
      that does not.
   d. **Tie-break — lowest PR number.** If the above do not clearly
      separate them, keep the **lowest-numbered** PR (opened first). This
      is deterministic, so two agents evaluating the same set
      independently reach the same winner and never close each other's
      keeper.

   To compare objectively, read each PR's diff against its base
   (`git fetch origin <headRefName>`, then
   `git diff origin/<baseRef>...origin/<headRefName>`) and the linked
   issue body.

5. Close every loser `L` in `S \ {W}` — but only one you can safely take:
   a. Acquire `refs/claims/pr-L` (`wf claim --pr L`
      **Acquire**, target `pr-L`) — skip this for the PR you already hold.
      If Acquire fails, another agent is reviewing or updating `L` right
      now: **skip it this round** and note it. That agent runs this same
      reconciliation, finds the same winner, and closes its own PR.
   b. Close it with an explaining comment that links the winner:
      ```bash
      gh pr close L --repo <org>/<repo> \
        --comment "Closing as a duplicate of #W, which resolves the same issue (#N) and is the better-implemented of the two (<one-line reason>). Work here is preserved on branch \`<headRefName>\` if anything needs salvaging into #W."
      ```
      Do not delete the branch — leave it so the work is recoverable.
   c. Release the claim you took on `L` (`wf claim-release --pr L`
      **Release**, target `pr-L`). Do **not** touch the linked issue's
      assignee or lifecycle label — the surviving PR `W` still drives it.
6. Resolve where the PR you hold sits:
   - **You hold the winner `W`:** continue to Step 3 and review it.
   - **You hold a loser:** you just closed it in 5b. Remove its
     `reviewing` label, release your claim
     (`wf claim-release --pr <number>`), and **exit** — never
     review a closed PR. The winner keeps its current review-state label
     and is reviewed on this or a later run.

Closing a duplicate PR is the **only** circumstance in which this skill
closes a PR (see Rules). In **read-only mode**, close nothing: identify
the winner, list the duplicate set under a "Duplicate PRs" note in the
review comment (Step 9) recommending which to keep, and continue the
normal review of the claimed PR.
