# Auto-merge — post-merge fallback when `wf` cannot run

Read this only when `wf post-merge` cannot run at all — Python is missing, or it returns `error`. Read the linked issues yourself and settle them by hand:

```bash
gh pr view <number> --repo <org>/<repo> --json closingIssuesReferences \
  --jq '.closingIssuesReferences[].number'
# for each still-open issue:
gh issue close <N> --repo <org>/<repo> --comment "Closing — resolved by merged PR #<number>."
# then set its stage with: wf stage-set {number} --stage stage-done
```
