# Harden auto-merge enforcement

Full procedure for `/github-workflow:setup` Step 7b. Run this when the
user **enables `auto-merge-on-approval`** (from Step 7), or standalone via
`/github-workflow:setup harden`. It makes "merge only after CI passes"
actually enforceable. Without it, an approved PR on a branch with no
**required** checks merges immediately — no CI guarantee.

The goal is **one** of two safe configurations:

- **(a) GitHub enforces it** — branch protection with required status
  checks. Preferred, but needs a public repo or GitHub Pro/Team on a
  private one.
- **(b) The plugin enforces it** — `require-ci-before-merge: true` in
  `docs/review.config.md` + a real PR pipeline. The fallback when (a)
  isn't available.

Resolve `{org}`, `{repo}`, `{branch}` from `ClaudeProject.md`. Each
sub-step is **best-effort** and degrades to a warning.

1. **Enable repo-level auto-merge** (needed by `gh pr merge --auto`):
   ```bash
   gh api -X PATCH repos/{org}/{repo} -F allow_auto_merge=true
   allowed=$(gh api repos/{org}/{repo} --jq '.allow_auto_merge')
   ```
   **Read it back** — some orgs accept the PATCH (200) but silently keep
   it `false` via policy. If `allowed` is not `true`, warn: repo-level
   auto-merge is blocked by org/repo policy; an admin must enable "Allow
   auto-merge" in Settings → Pull Requests, or queued merges never fire.

2. **Branch protection + required checks.** Find candidate check
   contexts — the job names in `.github/workflows/*.yml`, or the check
   names on a recent PR (`gh pr checks <recent-pr> --repo {org}/{repo}`).
   Ask the user which contexts must pass before merge. Apply protection
   with **strict** mode (require branches up to date):
   ```bash
   gh api -X PUT repos/{org}/{repo}/branches/{branch}/protection \
     --input - <<'JSON'
   {
     "required_status_checks": { "strict": true, "contexts": ["<ctx>", "..."] },
     "enforce_admins": false,
     "required_pull_request_reviews": null,
     "restrictions": null
   }
   JSON
   ```
   If this returns **403** ("Upgrade to GitHub Pro or make this
   repository public"), GitHub cannot enforce required checks on this
   repo — required status checks are paid-plan-only for private repos, so
   a private repo on the Free plan can never use configuration (a). Note
   it and proceed to step 3 (the plugin-side fallback is the only gate
   available); to get server-side enforcement instead, the repo must go
   public or move to GitHub Pro/Team. See the "Plan limitation" note in
   `skills/code-review/references/review-config-guide.md`. If there are no
   CI workflows at all, say so: there is nothing to require yet (merge the
   pipeline first), and step 3 is the only available guard.

3. **Plugin-side fallback.** If step 1 or 2 could **not** be fully
   enforced (repo auto-merge stuck off, branch protection unavailable, or
   no required checks now exist), set in `docs/review.config.md`'s
   Auto-Merge on Approval section:
   ```
   | require-ci-before-merge | `true` |
   ```
   Tell the user why: GitHub isn't enforcing the gate, so the code-review
   skill will — it waits for a green CI run and **pauses** an approved PR
   that has no checks or a red check, instead of merging it. (If
   server-side enforcement via step 2 fully succeeded, leaving this
   `false` is fine; configuration (a) already covers it.)

   Harden sets `true` because that is the strict guarantee — it pauses
   even when a repo runs no pipeline. If the user instead wants "gate when
   the PR runs CI, otherwise just merge," offer **`if-present`**: it
   behaves identically to `true` on a repo that has a pipeline, and merges
   an unchecked PR rather than pausing it. Note the trade-off — `if-present`
   is **not** an absolute gate, so a repo with no pipeline merges
   unguarded. When no pipeline exists at all, say so plainly: neither
   value gates anything until a PR pipeline is running.

4. **Report** what landed: repo auto-merge on/off, branch protection
   applied or blocked, and which enforcement configuration ((a), (b), or
   "neither — auto-merge is unguarded; merge a CI pipeline first") is now
   in effect.
