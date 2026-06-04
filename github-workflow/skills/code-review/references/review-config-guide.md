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
the PR is merged unattended on an approved review, red required checks
still block it, and (because Claude approves via a comment, not a GitHub
review) a branch that requires an approving review needs the merging
actor to have admin rights. See the Auto-Merge on Approval section in
`references/review.config.template.md` for the exact guardrails.

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
