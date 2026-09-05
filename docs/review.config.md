# Review Configuration — claude-plugins

Read by `/github-workflow:code-review`, and by the merge phase that ends a
`/github-workflow:execute` run. This repo dogfoods its own plugin, so this
file is both a real configuration and a worked example.

## Repository

- Org: Subverting-complexity
- Repo: claude-plugins
- Default branch: main

## Labels

The prefix is `review`, which is also the plugin's default, so these names
match what `templates/default-labels.md` resolves to when no config exists.
That is deliberate: the labels already on this repo keep working, and
nothing had to be renamed to introduce this file.

The **Purpose** column is the stable identity skills resolve against. Every
producer and consumer looks a label up by purpose, so the name set here is
what gets applied and filtered on.

State labels are mutually exclusive — exactly one is applied per review.

| Purpose | Label | Type | Meaning |
| ------- | ----- | ---- | ------- |
| `needs-review` | `review-needs-review` | State | Open PR awaiting its first review (entry state, applied at creation) |
| `reviewing` | `review-reviewing` | State | Review in progress — prevents concurrent reviews |
| `approved` | `review-approved` | State | No remaining issues, ready to merge |
| `changes-requested` | `review-changes-requested` | State | Concrete problems remain to be addressed |
| `needs-discussion` | `review-needs-discussion` | State | Architectural or scope questions need human judgment |
| `needs-re-review` | `review-needs-re-review` | State | New commits pushed since last review — re-review required |
| `failed` | `review-failed` | State | Review could not be completed (checkout failed, PR too large) |
| `updating` | `review-updating` | State | A builder agent is addressing review feedback — prevents concurrent updates |
| `fixes-applied` | `review-fixes-applied` | Action | Claude pushed fix commits to the PR branch (sticky across runs) |

`claude-authored` in `ClaudeProject.md` is a separate provenance marker and
takes no part in this state machine.

## Auto-Merge on Approval

| Setting                      | Value        |
| ---------------------------- | ------------ |
| auto-merge-on-approval       | `enabled`    |
| require-ci-before-merge      | `true`       |
| bypass-ci-on-billing-failure | `false`      |
| bypass-ci-when-no-pipeline   | `false`      |

**Why enabled.** This is the switch that lets a review land its own work,
and it governs both entry points: `/github-workflow:code-review` and the
merge phase at the end of a `/github-workflow:execute` run. Turning it on
here is what makes an `execute` run finish at a merged pull request rather
than an approved one waiting for a person.

**Why `require-ci-before-merge: true` rather than `false`.** The stronger
guarantee would be GitHub-enforced required status checks on `main`, which
this repo qualifies for (it is public). That protection is **not currently
applied** — see *Enforcement status* below — so the plugin-side gate is the
only thing standing between an approving verdict and a merge. `true` is the
absolute form: an approved PR whose head SHA has no checks at all, or has a
red check the review cannot fix, is **paused** rather than merged. That
costs nothing here because CI runs on every pull request, so the checks are
always present; and it fails safe if CI ever stops reporting.

`if-present` was the alternative. It behaves identically to `true` on a repo
that runs a pipeline, but merges an unchecked PR instead of pausing it,
which makes it not an absolute gate. Given that nothing server-side is
enforcing anything on this repo, the absolute form is the right one.

**Why `bypass-ci-on-billing-failure: false`.** This is a public repo, so
GitHub Actions minutes are free and a billing-induced pipeline failure is
not a situation that arises. Leaving the escape hatch shut means a red
pipeline always means something real.

**Why `bypass-ci-when-no-pipeline: false`.** This one is not a judgement
call — it cannot apply here. It only ever engages on a repo with **zero**
active GitHub Actions workflows, and this repo has two (`CI` and
`Copilot`), so an empty check rollup on a PR here would mean something has
gone wrong rather than that there is nothing to report. The setting exists
for projects whose CI is permanently invisible to GitHub — no pipeline, or
one running on Buildkite/Jenkins/CircleCI that never posts a status back —
where without it every approved PR pauses at the no-checks guard forever.

### Enforcement status

Two configurations can make "merge only after CI passes" enforceable. The
plugin's hardening step aims for either:

| | Mechanism | Status |
| - | --------- | ------ |
| (a) | GitHub branch protection with required status checks on `main` | **Not applied** |
| (b) | `require-ci-before-merge` above, plus a real PR pipeline | **Active** |

Configuration (b) is what currently guards this repo, and it is sufficient:
CI runs on every PR, and the review pauses rather than merges when it is
not green. It is, however, enforced by the agent rather than by GitHub, so
it does not constrain a human pushing directly to `main`.

To add (a) as well — belt and braces, and the only thing that also binds
humans — apply protection requiring these six contexts, which are the job
names in `.github/workflows/ci.yml`:

- `Verify shared skills are in sync`
- `Lint skill metadata`
- `Test workflow decision logic and wf.py I/O shell`
- `Check plugin versions are bumped`
- `Check instruction-token footprint budgets`
- `Validate plugin manifests`

Set `strict` to `false` when doing so. Strict mode additionally requires a
branch to be up to date with `main` before it merges, which stalls the
second of any two PRs built in parallel — and parallel agents are this
repo's normal working mode. Requiring the checks without requiring
up-to-dateness gates what actually matters: the pull request's own head SHA
was green.

Leave `required_pull_request_reviews` unset. The review records its verdict
as a comment and the `review-approved` label, not as a GitHub review, so a
required-review rule would force every merge through `--admin`.

## Hard Non-Compliance Gates

Any of these forces a `Changes Requested` verdict regardless of all other
findings. They are the repo's `CLAUDE.md` critical rules, restated as
things a reviewer checks on a diff.

1. **A synced skill copy was edited directly.** Any changed file carrying
   the `<!-- SYNCED from _shared-skills/ -->` banner is generated output.
   The canonical source in `_shared-skills/` is the only editable copy.
   The pre-commit hook blocks this, so seeing it in a diff means the hook
   was bypassed.
2. **A shared skill changed without its synced copies.** If the diff
   touches `_shared-skills/`, every deployed copy must change in the same
   commit. `sync-skills.sh --verify` returning non-zero is the test.
3. **A plugin changed without a version bump.** Any diff touching files
   under `github-workflow/` or `local-workflow/` — directly or through a
   sync — must bump that plugin's `version` in
   `.claude-plugin/plugin.json`. Patch for fixes and wording, minor for new
   skills or behaviour changes, major for breaking changes.
4. **CRLF line endings.** The repo is pinned to LF via `.gitattributes`.
   CRLF leaves worktrees permanently dirty on Windows and blocks their
   cleanup, so it is a correctness problem here, not a style one.
5. **An unreplaced template placeholder shipped.** `{{PLUGIN_NAME}}`,
   `{{PLUGIN_VERSION}}`, or a `{PLACEHOLDER}` left in a deployed skill or
   command. `lint-skills.sh` catches these.

## Tech Stack Review Rules

This repo is instruction text plus a small amount of tooling. What that
means for a review:

- **Markdown skill and command definitions are the product.** Review them
  the way you would review code: an ambiguous instruction is a bug, a
  contradiction between two files is a bug, and a step that cannot be
  executed as written is a bug. An agent reading these files has no author
  to ask.
- **Cross-file consistency is the most common defect.** These files
  reference each other constantly — by phase number, step number, file
  path, purpose key, and flag name. When a diff renames or renumbers
  anything, check every citing file. `grep` for the old name is the test.
- **One canonical specification per procedure.** Claiming, board
  resolution, label defaults, exit cleanup, and merge mechanics each live in
  exactly one file that others cite. A diff that restates one of these
  inline instead of citing it is a finding, however correct the restatement.
- **The instruction-token budget is real.** Anything added to a `SKILL.md`
  body is paid for on every invocation of that skill. Detail needed only on
  some runs belongs in a `references/` file loaded at its trigger — the
  pattern is documented in `docs/reference-lazy-loading.md`. CI enforces
  ceilings via `count-tokens.sh` and `check-budgets.sh`.
- **Shell must be portable.** Scripts and the `!`-blocks inside commands run
  under Git Bash on Windows as well as Linux and macOS. Avoid GNU-only flags
  and anything assuming Unix coreutils are on `PATH`.
- **Python in `scripts/` must stay offline-testable.** The decision logic in
  `wf_core.py` is pure by design so `tests/` can exercise it without network
  or GitHub. A change that pushes side effects into it is an architecture
  finding.

## Architecture Rules

- **Purpose keys, never literal names.** Labels and board columns resolve
  through `templates/default-labels.md`. A hardcoded label string in a skill
  is a finding: it silently breaks every project that renamed that label.
- **Nothing project-specific in a skill.** Repo names, board IDs, and label
  names belong in `ClaudeProject.md` or this file. The skills are generic.
- **Shared skills stay plugin-agnostic.** Anything in `_shared-skills/`
  deploys to both plugins, so it must not assume GitHub, a board, or an
  issue tracker. Use `{{PLUGIN_NAME}}` for anything plugin-specific.
- **References are cited, not duplicated.** See the canonical-specification
  rule above; this is its architectural form.

## Security Specifics

- **Tool allowlists are least-privilege.** Every agent in `agents/`
  enumerates the tools it needs and records why each family is present. A
  diff widening an allowlist must justify the widening in that file. Watch
  particularly for `Bash(git *)` replacing the explicit subcommand list, or
  `bash *.sh` growing into unrestricted `bash`.
- **No credentials, tokens, or org-internal identifiers** in committed
  files. Board node IDs and field IDs in `ClaudeProject.md` are fine — they
  are not secrets — but tokens never are.
- **Claim refs are a lock, not a hint.** A change touching `wf`'s claim
  commands (`claim`, `claim-release`, `claim-reap`) or any call site of
  them needs care: a weakened claim lets two agents build the same story
  or review the same PR.
  Check that the claim is still acquired before any side effect, held across
  PR creation, and released on every exit path.
- **When the diff touches Claude Code configuration** — `CLAUDE.md`,
  `.claude/`, hooks, skill definitions, or MCP config — run
  `npx ecc-agentshield scan` and fold anything it reports into the Security
  section of the review.

## Test Expectations

- **Decision logic changes need tests.** Anything altering how `wf_core.py`
  selects, filters, sorts, or classifies belongs in
  `tests/test_decision_logic.py`, and I/O-shell behaviour in
  `tests/test_io_shell.py`. Both run offline.
- **Bug fixes need a regression test** that fails before the fix.
- **Instruction-only changes need no unit test**, since there is nothing to
  execute. What they need instead is the consistency check above: every file
  citing the changed thing was updated in the same commit.
- **The quality gate must pass** —
  `bash sync-skills.sh --verify && bash lint-skills.sh && bash run-tests.sh`
  — and CI additionally enforces version bumps, token budgets, and manifest
  validity.

## Review Comment Footer

```
---
Reviewed at <SHA>
🤖 Reviewed with Claude Code
```

The `Reviewed at <SHA>` line is machine-parsed by future runs to detect
whether the PR has changed since the last review.
