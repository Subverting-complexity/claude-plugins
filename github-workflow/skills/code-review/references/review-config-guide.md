# Review Config Generation Guide

When no `review.config.md` exists, walk the user through creating one.
Use interactive prompts to gather the information, then write the file.

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

Ask about the areas the auto-detection couldn't fully resolve. Group
questions by topic and use interactive selection where possible.

**Labels:** Present a default label scheme (see the template in
`references/review.config.template.md`) and ask if they want to customise
the prefix or add/remove any. Also list existing repo labels
(`gh label list`) so the user can see what's already there.

**Custom labels:** Ask if the user has additional labels they want the
review process to apply or check. For each custom label, ask the name
and the criteria for when it should be applied. Examples:
- `breaking-change` — PR modifies a public API
- `docs-needed` — PR adds a feature with no documentation update
- `frontend` / `backend` — PR touches files in specific directories

Store these in the Custom Labels section of the config.

**Hard non-compliance gates:** Present sensible defaults (no linked issue,
no tests on non-trivial code, secrets in code, scope creep). Ask if they
want to add or remove any.

**Tech-stack review rules:** Based on the detected stack, suggest relevant
cross-boundary checks. For example:
- C# + TypeScript → DTO/interface parity
- Python + TypeScript → API schema validation
- Monorepo → cross-package dependency checks
- Any API project → request/response type safety

Ask what architecture rules matter to them (layer boundaries, single
responsibility, import direction).

**Security specifics:** Ask if there are project-specific security
concerns beyond the defaults (injection, input validation, no secrets in
logs).

**Test expectations:** Present defaults and ask if they want to adjust.

**Auto-merge on approval:** Ask "Automatically squash-merge a PR once
Claude approves it and posts the review comment?" **Default to no** —
record `auto-merge-on-approval: disabled` unless the user explicitly opts
in. If they say yes, set it to `enabled` and warn them what it implies:
the PR is merged unattended on an approved review; merge conflicts are
resolved automatically and a failing pipeline is fixed on the branch and
then merged (the skill only pauses for a human on judgment-call conflicts
or flaky/infra failures); and (because Claude approves via a comment, not
a GitHub review) a branch that requires an approving review needs the
merging actor to have admin rights. See the Auto-Merge on Approval section
in `references/review.config.template.md` for the exact guardrails.

If they enable it, **run the wizard's hardening step**
(`/github-workflow:setup harden`, Step 7b of the setup command) rather
than wiring the repo up by hand. It enables repo-level auto-merge,
attempts branch protection with required status checks, and — when GitHub
can't enforce those — sets the plugin-side fallback below. Auto-merge is
only safe with **one** of these two configurations:

- **(a) GitHub enforces it** — required status checks via branch
  protection on the default branch. GitHub itself blocks the merge until
  the checks pass. Requires branch protection (a public repo, or GitHub
  Pro/Team on a private one).
- **(b) The plugin enforces it** — `require-ci-before-merge: true` **plus
  a real pipeline** that runs on PRs. The skill waits for a green CI gate
  and pauses if there are no checks or a red check. Use this when (a)
  isn't available. (A lighter variant, **`if-present`**, gates the same way
  *when checks exist* but merges a PR that has none — convenient for a mix
  of repos where some have CI and some don't, at the cost of not being an
  absolute gate. Prefer `true` when you want the guarantee.)

> **Plan limitation — when (a) is simply not available.** GitHub gates
> required status checks behind a paid plan for private repos. Verified
> against GitHub docs (June 2026): branch protection covers *"public and
> private repositories with GitHub Pro, GitHub Team, GitHub Enterprise"*
> — **private + Free is excluded** — and the newer **rulesets** path is
> *"GitHub Team and GitHub Enterprise"* only. So on a **private repo on
> the Free plan, configuration (a) cannot be turned on at all** (you'll
> get `403 "Upgrade to GitHub Pro or make this repository public"`). The
> three real choices, in order of enforcement strength:
>
> 1. **Make the repo public** — free, gives real server-side enforcement.
> 2. **Pay** — GitHub **Pro** (personal) or **Team** (org-owned, the
>    realistic option for an organization's private repo) unlocks (a).
> 3. **Stay private + Free** — configuration (a) is impossible, so **(b)
>    is your only gate.** This is not a stopgap for these repos; it is the
>    enforcement mechanism. `/github-workflow:setup harden` detects the
>    `403` and sets `require-ci-before-merge: true` automatically.
>
> Sources: [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
> [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets).

So after enabling auto-merge, also ask: **"Should an approved PR refuse
to merge unless CI is green?"** If yes (or if branch protection can't be
configured), record `require-ci-before-merge: true`. If the answer is
"only when the PR actually runs CI — otherwise just merge," record
`require-ci-before-merge: if-present` instead (it gates when checks exist
and merges when none do; not an absolute gate). Default `false` keeps
today's behaviour — an approved PR with no *required* checks merges
immediately, which is only safe under configuration (a). Without either
(a) or (b), an approved PR can land with no CI guarantee at all.

Then ask one more, about the **billing edge case**: **"If CI can't run
because of a GitHub Actions billing or account problem (out of minutes,
spending limit hit, a failed payment), should an approved PR merge anyway?"**
**Default to no** — record `bypass-ci-on-billing-failure: false`. If they say
yes, set it to `true` and explain the guardrail: it merges an approved PR
over red CI **only** when the sole blocker is a billing/account failure that
keeps the pipeline from running; a real test, build, or lint failure is never
bypassed (it is still fixed or filed), and a merge conflict is still
resolved. This is the persistent, per-project form of the one-off
`--bypass-ci` flag, scoped to billing. It is worth turning on for repos on a
plan where Actions billing can lapse and you would rather an approved review
land than sit blocked behind a pipeline that cannot run. See the Auto-Merge
on Approval section in `references/review.config.template.md` for the exact
semantics.

The repo-level auto-merge toggle the skill's `gh pr merge --auto` needs
is handled by the same hardening step:

```bash
gh api -X PATCH repos/{ORG}/{REPO} -F allow_auto_merge=true
```

Best-effort: if it fails (permissions/org policy), tell the user an admin
must turn on "Allow auto-merge" in the repo's Settings → Pull Requests,
or queued merges will not complete.

**Review comment footer:** Offer a default and let them customise.

## Step 3 — Create the labels

For each label defined in the config, check if it exists on the repo. If
not, create it:

```bash
gh label create "<label-name>" --description "<description>" --color "<hex>"
```

Use these default colours (adjustable by the user):
- Needs review (entry state): `#C2E0C6` (pale green)
- Reviewing: `#0E8A16` (green)
- Updating: `#0E8A16` (green)
- Approved: `#1D76DB` (blue)
- Changes requested: `#E4E669` (yellow)
- Needs re-review: `#FBCA04` (gold)
- Needs discussion: `#D93F0B` (orange)
- Failed (`{prefix}-failed`): `#B60205` (red)
- Fixes applied: `#5319E7` (purple)

## Step 4 — Write the config

Write the completed `review.config.md` to `./docs/review.config.md`
(create the `docs/` directory if needed). Use the template structure from
`references/review.config.template.md` and fill in all the gathered values.

Show the user the final file and confirm before proceeding.
