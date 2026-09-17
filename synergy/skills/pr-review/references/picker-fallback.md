# Step 1 — Inline PR picker (fallback)

Read this only when `wf review-next` reports `error`, or Python is missing.

```bash
gh pr list --state open --repo <org>/<repo> --json number,title,labels,headRefName,baseRefName,headRefOid
```

Skip any PR that has:

- the `reviewing` state label (another review agent is in progress);
- the `updating` state label (a builder agent is addressing feedback);
- the `approved` state label, **unless** it also has `needs-re-review`.

For each remaining PR, decide whether it needs attention:

1. Read its comments: `gh pr view <number> --repo <org>/<repo> --json comments`.
2. Find Claude's most recent review comment by the footer marker defined in `review.config.md`.
3. No such comment → it needs review. A `needs-review` label is the normal first-review case.
4. A comment exists → extract its `Reviewed at <SHA>` line. If that SHA differs from `headRefOid`, it needs review; otherwise skip it.
5. A PR carrying `changes-requested` always needs attention: rework, then re-review.

Pick by three tiers, highest first, lowest PR number within a tier:

1. `needs-re-review`;
2. `changes-requested` (enters Step 1b);
3. `needs-review`, or a changed SHA.

If nothing needs review or rework, report that and exit. Otherwise claim the chosen PR at Step 2 (in read-only mode, skip the claim), walking down this order on a lost claim, then check it out at Step 3.
