# Review Configuration — {PROJECT_NAME}

## Repository

- Org: {ORG}
- Repo: {REPO}
- Default branch: {DEFAULT_BRANCH}

## Labels

Replace `{PREFIX}` with your label prefix (e.g., `claude`, `review`,
`cr`). All state labels use this prefix so they're easy to filter.

The **Purpose** column is the stable identity skills resolve against —
it never changes even when you pick a custom prefix. Producers and
consumers look a label up by purpose (see the resolution path in
`templates/default-labels.md`), so the name you set here is what every
skill applies and filters on.

State labels are mutually exclusive — exactly one is applied per review.

| Purpose | Label | Type | Meaning |
| ------- | ----- | ---- | ------- |
| `needs-review` | `{PREFIX}-needs-review` | State | Open PR awaiting its first review (entry state, applied at creation) |
| `reviewing` | `{PREFIX}-reviewing` | State | Review in progress — prevents concurrent reviews |
| `approved` | `{PREFIX}-approved` | State | No remaining issues, ready for human merge |
| `changes-requested` | `{PREFIX}-changes-requested` | State | Concrete problems remain that a human must address |
| `needs-discussion` | `{PREFIX}-needs-discussion` | State | Architectural or scope questions need human judgment |
| `needs-re-review` | `{PREFIX}-needs-re-review` | State | New commits pushed since last review — re-review required |
| `failed` | `{PREFIX}-failed` | State | Review could not be completed (checkout failed, PR too large) |
| `updating` | `{PREFIX}-updating` | State | A builder agent is addressing review feedback — prevents concurrent updates |
| `fixes-applied` | `{PREFIX}-fixes-applied` | Action | Claude pushed fix commits to the PR branch (sticky across runs) |

These labels are managed by the `/github-workflow:code-review` skill
and form the single source of truth for PR review state. Claude labels
in `ClaudeProject.md` (like `claude-authored`) are separate workflow
markers that do not participate in this state machine.

## Custom Labels

Additional labels applied to PRs based on project-specific criteria.
These are applied alongside (not instead of) the state labels above.
Remove this section if you don't use custom labels.

| Label | When to apply |
| ----- | ------------- |
| `{LABEL}` | {CRITERIA} |

## Auto-Merge on Approval

| Setting                      | Value      |
| ---------------------------- | ---------- |
| auto-merge-on-approval       | `disabled` |
| require-ci-before-merge      | `false`    |
| bypass-ci-on-billing-failure | `false`    |

When `enabled`, the code-review skill squash-merges a PR (deleting its
branch) as soon as the review verdict is **Approved** and the review
comment has been posted. When `disabled` (the default), an approved PR is
left for a human to merge.

`require-ci-before-merge` (default `false`) hardens the merge gate for
repos that intend to gate on CI but cannot mark checks **required** (e.g.
a private repo on a free plan, where branch protection is unavailable). It
takes three values:

- **`false`** (default, backward-compatible) — an approved PR on a branch
  with no *required* checks merges immediately, whether or not other
  checks exist.
- **`true`** — the skill refuses to merge a PR that has **no green CI
  gate**: if the head SHA has no checks at all, or a check it cannot fix
  is red, it pauses and leaves the `approved` verdict. An absolute gate —
  it pauses even on a repo that runs no pipeline.
- **`if-present`** — gate on CI **only when CI exists**: if the head SHA
  has checks they must be green (a red check it cannot fix pauses), but a
  PR with **no checks at all merges**. Use this for "require CI to pass if
  there is CI, otherwise merge."

Set it `true` (or `if-present`) whenever auto-merge is enabled but GitHub
itself is not enforcing required status checks — `/github-workflow:setup
harden` sets `true` for you when it cannot wire up server-side
enforcement.

> **Only `true` and configuration (a) are absolute gates.** Because
> `if-present` merges when a head SHA has no checks, it guarantees "CI
> green before merge" only on a repo that **actually runs a PR pipeline**.
> For a hard guarantee that an approved PR can *never* merge without green
> CI — including before any check has reported — use GitHub-enforced
> required status checks (configuration (a) in the setup guide) or `true`.

`bypass-ci-on-billing-failure` (default `false`) is a narrow escape hatch
for a specific, common situation: GitHub Actions stops running because of a
**billing or account problem** — the org ran out of included Actions
minutes, a spending limit was hit, or a payment failed — so the pipeline
cannot report green no matter how correct the PR is. CI here is red (or
never starts) for a reason that has nothing to do with the change.

- **`false`** (default) — a billing-induced CI failure is treated like any
  other red check: the skill tries to fix it, cannot (it is not a code
  problem), and so pauses or files it. The PR does not merge.
- **`true`** — when the **only** thing blocking the merge is a billing or
  account failure, the skill treats the CI gate as satisfied and merges the
  approved PR anyway. A normal red check — a real test or build failure — is
  **never** bypassed by this setting; it is still fixed or filed as usual.

Billing shows up in two shapes, and the setting covers both:

- **The pipeline ran and failed.** Every failing check is attributable to
  billing and no genuine code/test/lint check is red.
- **The pipeline never started.** No run is created, so the PR carries an
  empty check rollup — indistinguishable, on its face, from a repo with no
  CI. This is the commoner shape and the one worth turning the setting on
  for. Because an empty rollup is ambiguous, it is bypassed only on
  evidence: the repo must have active workflows that should have run, no run
  may exist for the head SHA after a wait, and the project's own quality gate
  must have passed **locally** on that SHA. Absent that local green, the PR
  pauses exactly as it would with the setting off — the merge is never made
  on no evidence at all.

This is the persistent, per-project, billing-scoped form of the
per-invocation `--bypass-ci` flag (which bypasses the CI gate for *any*
reason, for one run only). Turn it on for repos on a plan where Actions
billing can lapse and you would rather an approved review land than sit
blocked behind a pipeline that cannot run. Like `--bypass-ci`, it never
bypasses a merge **conflict**, and it only takes effect when
`auto-merge-on-approval` is `enabled`.

This is **off by default** — turn it on only for repos where you trust an
approved Claude review to land unattended. When on, the skill drives the
PR all the way to merged. Conflicts and red CI are blockers it clears, not
reasons it gives up (enforced in Step 11 of the code-review skill):

- The PR must still be open and unchanged by **others** since the review
  (a commit the skill did not review forces a re-review instead of a
  merge; fixes the skill pushes itself in the steps below do not).
- **Merge conflicts are resolved automatically** — the skill merges the
  base branch into the PR branch, resolves the conflicts (preserving both
  the PR's intent and the incoming base change), re-runs the quality gate,
  and pushes. It only pauses for a human when the two sides made
  incompatible product/design decisions with no objectively correct merge.
- **A failing required check is fixed, then merged** — the skill reads the
  failing run's logs, fixes the cause on the branch (compile/type/lint
  errors, tests the change broke, stale snapshots/lockfiles), reproduces
  the check locally to confirm it passes, and pushes. Because the push
  re-runs the pipeline, it enqueues GitHub-native auto-merge so the PR
  lands the moment the fixed pipeline is green. It only pauses for a human
  when the failure is flaky/infrastructure or needs design judgment — it
  never force-merges over a genuinely red check.
- Claude records its approval as a review comment and the `approved`
  label, not as a GitHub *review*. So if the branch requires an approving
  review, the merge needs admin rights to satisfy that rule
  administratively. Grant the merging actor merge (admin, if reviews are
  required) permissions, or the merge stays queued.

## Hard Non-Compliance Gates

Any of these force a `Changes Requested` verdict regardless of all other
findings.

{GATES}

## Tech Stack Review Rules

These are project-specific checks to run in addition to the generic review.

{TECH_STACK_RULES}

## Architecture Rules

{ARCHITECTURE_RULES}

## Security Specifics

{SECURITY_RULES}

## Test Expectations

{TEST_EXPECTATIONS}

## Review Comment Footer

```
---
Reviewed at <SHA>
🤖 Reviewed with Claude Code
```

The `Reviewed at <SHA>` line is machine-parsed by future runs to detect
whether the PR has changed since the last review.
