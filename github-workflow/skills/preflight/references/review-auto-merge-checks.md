# Preflight — auto-merge safety checks

Deep checks for the **opt-in** `auto-merge-on-approval` feature. Read and
run these **only when** `ClaudeProject.md` references a `review.config.md`
**and** that file has `auto-merge-on-approval: enabled`. In the default
configuration (no `review.config.md`, or auto-merge disabled) none of this
runs — skip it entirely; it is off the common path on purpose.

Gating on that one setting is safe because it is the only thing that
enables a merge anywhere in the plugin: it governs both
`/github-workflow:code-review`'s merge step and the merge phase that ends a
`/github-workflow:execute` run. There is no second path that merges without
it, so a project this block skips is a project where nothing merges
unattended.

When auto-merge is enabled, an approved PR is squash-merged automatically,
so two repo-side settings must hold or a queued merge silently never fires:

1. the repo's **Allow auto-merge** setting is on, and
2. **something enforces "CI green before merge"** — either GitHub required
   status checks, or the plugin-side `require-ci-before-merge` flag.

Run this block (it makes at most two `gh` calls, enabled case only):

```!
path=$(grep -oE '[A-Za-z0-9._/-]*review\.config\.md' ClaudeProject.md 2>/dev/null | head -1)
path=${path:-docs/review.config.md}
automerge=$(grep -E 'auto-merge-on-approval' "$path" 2>/dev/null | grep -oiE 'enabled|disabled' | head -1)
if [ "$automerge" = "enabled" ]; then
  echo "OK review-auto-merge: enabled — approved PRs are squash-merged automatically"
  slug=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)
  if [ -n "$slug" ]; then
    allowed=$(gh api "repos/$slug" --jq '.allow_auto_merge' 2>/dev/null)
    if [ "$allowed" = "true" ]; then
      echo "OK review-auto-merge-repo: repo allows auto-merge"
    else
      echo "WARNING review-auto-merge-repo: auto-merge-on-approval is enabled but the repo's 'Allow auto-merge' setting is off — queued merges will not fire. Enable it with 'gh api -X PATCH repos/$slug -F allow_auto_merge=true' or re-run /github-workflow:setup harden"
    fi
    requireci=$(grep -E 'require-ci-before-merge' "$path" 2>/dev/null | grep -oiE 'if-present|true|false|enabled|disabled' | head -1)
    if [ "$requireci" = "true" ] || [ "$requireci" = "enabled" ]; then
      echo "OK review-auto-merge-ci: require-ci-before-merge=true — the skill enforces a green CI gate (pauses an approved PR that has no checks)"
    elif [ "$requireci" = "if-present" ]; then
      echo "OK review-auto-merge-ci: require-ci-before-merge=if-present — the skill gates on CI when checks exist (a PR with no checks merges; not an absolute gate)"
    else
      branch=$(gh repo view "$slug" --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null)
      reqchecks=$(gh api "repos/$slug/branches/$branch/protection/required_status_checks/contexts" --jq 'length' 2>/dev/null)
      if [ -n "$reqchecks" ] && [ "$reqchecks" -gt 0 ] 2>/dev/null; then
        echo "OK review-auto-merge-ci: $reqchecks required status check(s) gate '$branch' — GitHub enforces CI before merge"
      else
        echo "WARNING review-auto-merge-ci: auto-merge-on-approval is enabled but NEITHER GitHub required status checks NOR require-ci-before-merge is configured — an approved PR can merge with no CI guarantee. Run /github-workflow:setup harden to wire up the gate."
      fi
    fi
  fi
elif [ -n "$automerge" ]; then
  echo "OK review-auto-merge: disabled"
fi
```

Classify the output: a `WARNING` here is informational (reviews still run;
only the queued-merge step is affected) — it never escalates to the wizard.
`/github-workflow:setup harden` wires up the gate.
