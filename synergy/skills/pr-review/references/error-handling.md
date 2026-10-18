# PR review — error handling

Read this only if something goes wrong during the review: a `gh` command fails, checkout fails, a changed file cannot be read, the PR has no diff, or it is too large to review thoroughly.

1. Release the claim: `wf claim-release --pr <number>`.
2. Remove the `reviewing` label and apply the `failed` review-state label.
3. Post a comment explaining what failed, with the review footer, so the failure is tied to a commit and a later run retries.
4. If the failure is fixable work rather than a transient problem (the PR should be split, or a structural issue blocks review), file it with `/synergy:report-issue`, autonomously and referencing this PR. Skip this for auth, network or rate-limit failures, where filing would fail too.
5. Exit. Do not recover, retry or continue.
