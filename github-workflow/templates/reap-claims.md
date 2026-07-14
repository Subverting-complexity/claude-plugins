# Reap orphaned claim refs

Full procedure for `/github-workflow:setup` Step 10, also reachable
standalone via `/github-workflow:setup reap`.

The workflow locks each in-flight issue or PR with a git ref under
`refs/claims/`. These refs are released automatically on every normal
exit, but a crash or hard kill skips the release and leaves an
orphaned ref that silently blocks future pickup of that item. This
procedure scans all active claim refs, identifies which ones no longer
back live work, frees them, and reports anything that needs manual review.

**Parse the threshold argument.** If `$ARGUMENTS` contains
`--threshold N`, use `N` hours as the staleness threshold; otherwise
default to **4 hours**. A claim younger than the threshold is never
reaped — it may belong to a normally running session.

**List all active claims:**

```bash
git fetch --prune origin '+refs/claims/*:refs/remotes/origin/claims/*'
git ls-remote origin 'refs/claims/*'
```

If the output is empty, report "No active claim refs found." and stop.

**For each claim ref** `{sha}\trefs/claims/{target}` (where `{target}`
is `issue-{N}` or `pr-{N}`):

1. **Fetch the claim object and measure its age** (in hours):

   ```bash
   git fetch origin "refs/claims/{target}"
   CLAIM_TS=$(git log -1 --format="%ct" FETCH_HEAD)
   NOW=$(date +%s)
   AGE_H=$(( (NOW - CLAIM_TS) / 3600 ))
   ```

   If `AGE_H < threshold`, skip this ref (too recent).

2. **Cross-check for issue claims** (`issue-{N}`):

   ```bash
   gh issue view {N} --repo {org}/{repo} --json state,labels \
     --jq '{state: .state, labels: [.labels[].name]}'
   ```

   - Issue state is **CLOSED** → **reap** (work is done; the ref was
     not freed on the session's last exit).
   - Issue does **not** have the `status-in-progress` label → **reap**
     (the lifecycle label moved on — e.g. back to `status-ready` or
     to `status-in-review` — but the claim ref was never freed).
   - Issue **has** `status-in-progress` AND no open PR → **flag as
     suspect** (the in-progress marker is still set; this might be an
     active but slow session, or a crashed one — report it for manual
     review, do not auto-reap).
   - Issue **has** `status-in-progress` AND an open PR exists
     (checked below) → **reap** (the PR was opened but the
     post-create claim release failed; the normal `execute` flow
     always releases after PR creation).

   To check for an open PR, use a simplified lookup — check whether
   the issue has a `status-in-review` lifecycle label (set by
   `execute` when the PR is opened) **or** run a quick PR search:

   ```bash
   gh pr list --repo {org}/{repo} --state open \
     --search "closes #{N}" --json number,title
   ```

   A non-empty result means a PR was opened for this issue.

3. **Cross-check for PR claims** (`pr-{N}`):

   ```bash
   gh pr view {N} --repo {org}/{repo} --json state,labels \
     --jq '{state: .state, labels: [.labels[].name]}'
   ```

   - PR state is **CLOSED** or **MERGED** → **reap**.
   - PR is **OPEN** but has neither a `reviewing` nor an `updating`
     review-state label → **reap** (the review completed but the
     claim was not freed).
   - PR is **OPEN** with `reviewing` or `updating` label → **flag as
     suspect** (might be an active review session).

**When reaping** a ref:

```bash
git push origin ":refs/claims/{target}"
```

Report: `Reaped: refs/claims/{target} — {AGE_H}h old ({reason})`

**When flagging as suspect**, do not delete the ref. Report:

```
Suspect: refs/claims/{target} — {AGE_H}h old (issue #{N} is still
in-progress with no open PR). Verify no active session is running,
then free it manually:
  git push origin :refs/claims/{target}
```

**Summary line** at the end:

```
Claim refs: {N} reaped, {K} suspect (manual review needed), {M} skipped (too recent).
```

If the user wants to run this on a schedule, they can use
`/schedule` to create a routine that calls
`/github-workflow:setup reap` daily or weekly. The command is
safe to run at any time — it never reaps a ref that still backs a
running session.
