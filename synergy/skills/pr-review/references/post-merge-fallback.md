# Auto-merge — post-merge fallback when `wf` cannot run

Read this only when `wf post-merge` returns `error`, or Python is missing. Settle the linked issues by hand. Nothing here is optional: an issue left open, out of Done or without its release notes is the failure this file exists to prevent.

```bash
gh pr view <number> --repo <org>/<repo> --json closingIssuesReferences \
  --jq '.closingIssuesReferences[].number'
# for each still-open issue:
gh issue close <N> --repo <org>/<repo> --comment "Closing — resolved by merged PR #<number>."
```

Then set each issue's `Stage` to `Done` and write its `User release notes` and `Internal release notes` from `.claude/release-notes.json`. With Python, `wf stage-set <N> --stage stage-done` sets the stage. Without it, tell the user exactly which issues still need `Done` and their notes, by number and title. Never report the PR as settled while any of them is outstanding.
