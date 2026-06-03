# Finding the PRs that close an issue

Single, canonical way to answer "which **open** pull requests will close
issue `#{number}` on merge?" Referenced by every site that detects or
reconciles duplicate PRs: `pick-story`/`execute` Phase 1 and `start-story`
(already-in-flight guard), `execute` Phase 7 and `finish-story`
(create-time duplicate flag), `block-story` (open-PR guard), and the
`code-review` skill's duplicate reconciliation (Step 2b). **Do not inline a
different lookup anywhere** — call this procedure so every site identifies
the same set.

## Why not regex the PR body

The obvious approach — listing open PRs and grepping each body for
`Closes #N` — is fragile. It misses closing keywords it didn't enumerate,
cross-repo references (`owner/repo#N`), issues linked through the GitHub UI
rather than the body, and bodies mangled by the known Windows/PowerShell
`@`-escaping corruption. Worse, two call sites with slightly different
regexes would disagree about what counts as a duplicate.

GitHub already parses closing references itself — it is exactly the parse
that auto-closes an issue when the PR merges — and exposes the result as
`closingIssuesReferences` on the PR. Ask GitHub; do not re-implement its
parser.

## Primary lookup (authoritative)

One batched GraphQL call returns every open PR together with the issues it
will close; a `--jq` filter keeps only the PRs whose
`closingIssuesReferences` include `{number}`. The issue number is the
*literal* `{number}` substituted into the jq filter — it is **not** a
GraphQL variable (GraphQL rejects a declared-but-unused variable, and the
filtering happens in jq, not in the query):

```
gh api graphql -f owner='{org}' -f repo='{repo}' -f query='
query($owner:String!, $repo:String!) {
  repository(owner:$owner, name:$repo) {
    pullRequests(states: OPEN, first: 100,
                 orderBy: {field: CREATED_AT, direction: ASC}) {
      nodes {
        number title headRefName isDraft
        labels(first: 20) { nodes { name } }
        closingIssuesReferences(first: 10) { nodes { number } }
      }
    }
  }
}' --jq "[.data.repository.pullRequests.nodes[]
          | select(any(.closingIssuesReferences.nodes[]?; .number == {number}))]"
```

The result is the **duplicate set** for `#{number}` — zero, one, or more
open PRs that will close it. Each node carries `number`, `title`,
`headRefName`, `isDraft`, and `labels` so the caller can compare them
without further queries. PRs are returned oldest-first, so the first
element is the lowest-numbered (the deterministic tie-break winner when
nothing else separates the set).

If the repo can have more than 100 open PRs, paginate with the
`pageInfo`/`endCursor` fields; for normal backlogs the first 100 covers
every open PR.

## Fallback (only when the API field is empty)

`closingIssuesReferences` is populated only when GitHub recognised a
closing reference. If a PR you expect to be a duplicate is **not** in the
result but you have specific reason to believe it targets `#{number}`
(e.g. its body says `Closes #{number}` but GitHub failed to link it), the
body almost certainly used a malformed reference — the correct fix is to
repair that PR's body so GitHub links it, not to widen the matcher. As a
last resort for a read-only check, scan bodies directly:

```
gh pr list --repo {org}/{repo} --state open --json number,title,headRefName,body \
  --jq "[.[] | select(.body | test(\"(?i)\\\\b(close[sd]?|fix(e[sd])?|resolve[sd]?) +#{number}\\\\b\"))]"
```

Treat anything found only by this fallback as **suspect** and report it for
a human to confirm, rather than auto-closing on its basis.
