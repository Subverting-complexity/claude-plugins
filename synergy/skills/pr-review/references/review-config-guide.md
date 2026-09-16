# Review Config Generation Guide

When no `review.config.md` exists, walk the user through creating one. Use interactive prompts to gather the information, then write the file.

## Step 1 — Detect what you can

Before asking anything, gather context automatically:

```bash
# Get the repo identity
gh repo view --json owner,name,defaultBranchRef

# Get existing labels
gh label list --json name,description

# Detect tech stack from file extensions and config files
find . -maxdepth 3 -type f \( -name "*.csproj" -o -name "package.json" -o -name "Cargo.toml" -o -name "go.mod" -o -name "requirements.txt" -o -name "Gemfile" -o -name "pom.xml" -o -name "build.gradle" -o -name "*.sln" -o -name "Makefile" -o -name "pyproject.toml" \) 2>/dev/null | head -20

# Check for test directories
find . -maxdepth 3 -type d \( -name "test" -o -name "tests" -o -name "__tests__" -o -name "spec" -o -name "test_*" \) 2>/dev/null | head -10
```

Use what you find to pre-fill answers and reduce the number of questions.

## Step 2 — Ask the user

Ask about the areas the auto-detection couldn't fully resolve. Group questions by topic and use interactive selection where possible.

**Labels:** Present a default label scheme (see the template in `references/review.config.template.md`) and ask if they want to customise the prefix or add/remove any. Also list existing repo labels (`gh label list`) so the user can see what's already there.

**Custom labels:** Ask if the user has additional labels they want the review process to apply or check. For each custom label, ask the name and the criteria for when it should be applied. Examples:
- `breaking-change` — PR modifies a public API
- `docs-needed` — PR adds a feature with no documentation update
- `frontend` / `backend` — PR touches files in specific directories

Store these in the Custom Labels section of the config.

**Hard non-compliance gates:** Present sensible defaults (no linked issue, no tests on non-trivial code, secrets in code, scope creep). Ask if they want to add or remove any.

**Tech-stack review rules:** Based on the detected stack, suggest relevant cross-boundary checks. For example:
- C# + TypeScript → DTO/interface parity
- Python + TypeScript → API schema validation
- Monorepo → cross-package dependency checks
- Any API project → request/response type safety

Ask what architecture rules matter to them (layer boundaries, single responsibility, import direction).

**Security specifics:** Ask if there are project-specific security concerns beyond the defaults (injection, input validation, no secrets in logs).

**Test expectations:** Present defaults and ask if they want to adjust.

**Auto-merge on approval:** Ask "Automatically squash-merge a PR once Claude approves it and posts the review comment?" **Default to no**: record `auto-merge-on-approval: disabled` unless the user explicitly opts in. Say plainly what it covers, because it is the only switch that decides this: it governs `/synergy:pr-review` and the merge phase at the end of a `/synergy:execute` run. Left off, an execute run ends at an approved pull request waiting for a person, which is a complete run. If they say yes, set it to `enabled` and warn them what it implies, using the guardrails in the Auto-Merge on Approval section of `references/review.config.template.md`.

If they enable it, **run the hardening step** (`templates/harden-auto-merge.md`, which is `/synergy:setup harden`) rather than wiring the repo up by hand. It turns on repo-level auto-merge, attempts branch protection with required status checks, and sets the plugin-side fallback when GitHub cannot enforce them. Auto-merge is only safe with **one** of two configurations: **(a)** GitHub enforces required status checks through branch protection, or **(b)** `require-ci-before-merge: true` plus a real pipeline that runs on PRs.

> **Plan limitation: when (a) is simply not available.** GitHub gates required status checks behind a paid plan for private repos. Verified against GitHub docs (June 2026): branch protection covers *"public and private repositories with GitHub Pro, GitHub Team, GitHub Enterprise"* (**private + Free is excluded**), and the newer **rulesets** path is *"GitHub Team and GitHub Enterprise"* only. So on a **private repo on the Free plan, configuration (a) cannot be turned on at all** (you'll get `403 "Upgrade to GitHub Pro or make this repository public"`). The three real choices, in order of enforcement strength:
>
> 1. **Make the repo public**: free, gives real server-side enforcement.
> 2. **Pay**: GitHub **Pro** (personal) or **Team** (org-owned, the realistic option for an organization's private repo) unlocks (a).
> 3. **Stay private + Free**: configuration (a) is impossible, so **(b) is your only gate.** This is not a stopgap for these repos; it is the enforcement mechanism. `/synergy:setup harden` detects the `403` and sets `require-ci-before-merge: true` automatically.
>
> Sources: [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches), [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets).

Then ask the three follow-up questions below, only when auto-merge was enabled. The template's Auto-Merge on Approval section defines each value and its guardrails; explain them from there rather than restating them here.

1. **"Should an approved PR refuse to merge unless CI is green?"** Record `require-ci-before-merge`: `true` if yes (or if branch protection cannot be configured), `if-present` for "only when the PR actually runs CI, otherwise just merge", and the default `false` otherwise.
2. **"If CI can't run because of a GitHub Actions billing or account problem (out of minutes, spending limit hit, a failed payment), should an approved PR merge anyway?"** **Default to no.** Record `bypass-ci-on-billing-failure`.
3. **No pipeline.** Count the active workflows rather than guessing:

   ```bash
   gh api "repos/{ORG}/{REPO}/actions/workflows" \
     --jq '[.workflows[] | select(.state == "active")] | length'
   ```

   Non-zero: record `bypass-ci-when-no-pipeline: false` without asking. Only when the count is **zero** ask: **"This repo has no GitHub Actions workflows, so its PRs will never report a check. Should an approved PR merge anyway, on the strength of the local quality gate?"** **Default to no**, and say what it costs: every approved PR then pauses at the no-checks guard. At most one of the two bypass settings may be `true`.

**Review comment footer:** Offer a default and let them customise.

## Step 3 — Write the config

Write the completed `review.config.md` to `./docs/review.config.md` (create the `docs/` directory if needed). Use the template structure from `references/review.config.template.md` and fill in all the gathered values.

Show the user the final file and confirm before proceeding.

## Step 4 — Create the labels

Once the config is written, create any review label the repo lacks:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" labels-ensure
```

It reads the names from the config just written, takes colours and descriptions from `wf_core.REVIEW_LABEL_META`, and never overwrites an existing label. If it exits non-zero, report its `reason` and continue.
