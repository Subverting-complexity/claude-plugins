---
description: 'Set up or configure a project for this plugin. Trigger: "set up my project", "configure this repo", "onboard", "initialize the workflow", "help me set up", "setup", "init", "bootstrap", "configure the plugin", "first time setup".'
---

# Setup

Interactive onboarding wizard for configuring the github-workflow plugin.

## Steps

### 1. Verify prerequisites

Before doing anything else, verify `gh` is authenticated:

```
gh auth status
```

If this fails, stop and tell the user to run `gh auth login` first.

### 2. Check for existing configuration

Look for these files at the project root:

- `ClaudeProject.md` — project settings for this plugin
- `CLAUDE.md` — project rules

**If `ClaudeProject.md` exists**: read it, identify which sections are
present and which are missing. Offer to fill in the missing sections
rather than overwriting the file.

**If `CLAUDE.md` exists**: do not overwrite. Check if it references
`ClaudeProject.md`. If not, offer to add a reference line at the top.

### 3. Auto-detect project settings

Run these detections and report what was found:

**Repository identity:**

```
gh repo view --json owner,name,defaultBranchRef --jq '{org: .owner.login, repo: .name, branch: .defaultBranchRef.name}'
```

**Package manager** — check for lock files:

- `pnpm-lock.yaml` → pnpm
- `package-lock.json` → npm
- `yarn.lock` → yarn
- `*.sln` or `*.csproj` → dotnet
- `go.mod` → go
- `Cargo.toml` → cargo
- `requirements.txt` or `pyproject.toml` → python

**Quality gate** — look for common patterns:

- `scripts/*quality*` or `scripts/*test*`
- `package.json` scripts (test, lint, typecheck)
- `Makefile` targets (test, check, lint)
- `dotnet test`

**Project board:**

A project board can be owned by an **organization** or by a **user**.
Query both so user-owned boards are not missed (the org query errors or
returns empty when `{org}` is a personal account):

```
gh api graphql -f query='query { organization(login: "{org}") { projectsV2(first: 20) { nodes { id number title } } } }'
gh api graphql -f query='query { user(login: "{org}") { projectsV2(first: 20) { nodes { id number title } } } }'
```

Merge the results. If boards are found, list them by **title** (and
number) and ask which to use (or none). Record the chosen board's
`number` as `project-number`, its `id` as `project-node-id`, and its
`title` as `project-title` — `project-title` lets later commands confirm
the stored node id still points at the intended board before they mutate
it (see `templates/board-resolution.md`). When a board is selected,
auto-fetch its field IDs and status option IDs:

```
gh api graphql -f query='query { node(id: "{project_id}") { ... on ProjectV2 { fields(first: 20) { nodes { ... on ProjectV2SingleSelectField { id name options { id name } } ... on ProjectV2Field { id name } } } } } }'
```

**Milestones:**

```
gh api repos/{org}/{repo}/milestones --state open --jq '.[] | {title, due_on, open_issues}'
```

If milestones with due dates exist, note that sprint mode is available.

### 4. Ask for remaining settings

For anything not auto-detected, ask the user interactively:

- **Branch convention** — suggest `feature/{number}/{short-desc}` as default
- **Priority labels** — what label names for critical/high/medium/low
- **Type labels** — what label names for story/bug/security/debt/arch.
  Explain that type labels control mode filtering:
  `/github-workflow:execute` (default) picks the highest priority issue
  regardless of type; `--mode feature` picks feature stories only;
  `--mode maintenance` picks from bug/security/debt/arch issues.
  All five types should be configured for full mode support.
- **Ready gate** — ask "How do you signal that a story is ready for
  pickup?" Options:
  - `label` (default) — a `status-ready` label on the issue.
  - `board-column` — a "Ready" column on the project board.
  - `both` — requires the label AND the board column.
  Store the choice as `ready-gate` in ClaudeProject.md. If
  `board-column` or `both` is chosen, a project board must be
  configured and must have a "Ready" status option.
- **Status labels** — what label names for ready/needs-refinement.
  If `ready-gate` is `label` or `both`, ask for the `status-ready`
  label name. This is the positive signal that a story is eligible
  for pickup (no unresolved dependencies). Suggest `status:ready` with
  colour `#0E8A16` (green). If `ready-gate` is `board-column`, this
  label is optional — skip unless the user wants both signals. The
  `needs-refinement` label marks stories that were created with
  minimal spec during feature decomposition and need a refinement
  session (feature-discovery or grill-me) before they can be picked
  up. Suggest `needs-refinement` with colour `#D4C5F9` (purple). No
  "blocked" label is needed — dependencies are tracked in the issue
  body and the absence of ready state keeps the story out of the pick
  pool.
- **Claude labels** — simple workflow markers. Suggest
  `claude:authored`. These are separate from the review state labels
  (including `{prefix}-approved`) set up in Step 7.
- **Agent gating** — ask "Require human approval before Claude
  picks up stories?" If yes, set `agent-gating` to `enabled` in
  ClaudeProject.md and ask for the approval label name (suggest
  `claude:ready`). Store as `claude-ready` in the Claude label map.
  If no, set `agent-gating` to `disabled` — the `claude-ready` row
  can be removed from the label map.
- **Custom labels** — ask if the user has any additional labels they
  want workflow commands to apply or respect. For each custom label,
  ask the name and when it should be applied. Examples:
  `breaking-change`, `docs-needed`, `frontend`, `backend`. Store
  these in the Custom section of the label map in ClaudeProject.md.
  (The code-review skill also supports its own custom labels — those
  are configured separately in `review.config.md` during Step 7.)
- **Quality gate command** — if not auto-detected
- **Issue prefixes** — suggest `[STORY]`, `[BUG]`, `[SECURITY]`, `[ARCH]`, `[DEBT]`
- **Stale timeout** — how long an assigned issue can go without a
  branch or PR before `pick-story` reclaims it. Suggest `2h` as
  default. Accepts values like `30m`, `1h`, `4h`.
- **Refinement skill** — which skill to use when a `needs-refinement`
  story is next in the queue. Options: `feature-discovery` (default,
  code-aware) or `grill-me` (lightweight Q&A). Store as
  `refinement-skill` in ClaudeProject.md.

For each setting, show the detected or suggested default and let the
user confirm or override. For labels, also list any existing labels
found on the repo (`gh label list`) so the user can incorporate them.

### 5. Generate ClaudeProject.md

Use the template from `templates/ClaudeProject.md`. Fill in all
detected and user-provided values. Write to `ClaudeProject.md` at
the project root.

If enhancing an existing file, merge new sections into the existing
content without removing sections that are already there.

### 5b. Create the complete label inventory on GitHub

Setup is the **only** place the full label inventory is created. Skills
at runtime rely on these already existing and only create-if-missing as
a guarded fallback (see the pre-creation contract in
`templates/default-labels.md`). Create the **complete** inventory now —
both the workflow labels and the review-state mutex labels — so no skill
has to lazily create labels mid-workflow.

1. **Workflow labels** — every label configured in ClaudeProject.md
   (Priority, Type, Status, Claude, and Custom). Resolve each name
   through the label map per `templates/default-labels.md`.
2. **Review-state labels** — the eight review-state labels. If the user
   set up `docs/review.config.md` (step 7) or chose a label prefix,
   resolve each name from its Purpose row there; otherwise use the
   `review-` defaults from `templates/default-labels.md`. Create these
   even if the user defers full review-config setup, so the code-review
   skill never has to create them at runtime.

First fetch existing labels, then create only the missing ones —
**without `--force`**, so existing labels keep their colour and
description (no churn):

```
existing=$(gh label list --repo {org}/{repo} --json name --jq '.[].name')
# for each resolved <name> not in $existing:
gh label create "<name>" --repo {org}/{repo} --description "<description>" --color "<color>"
```

Use the colours from the inventory tables in
`templates/default-labels.md` (review-state labels there;
needs-refinement `#D4C5F9` light purple). The user may override any
colour during setup.

This step is best-effort. If label creation fails (permissions, etc.),
log a warning and continue.

### 5c. Ignore plugin scratch files

The execute skill writes session-local scratch files under `.claude/`
that must never be committed: `.claude/execution-checkpoint.md` (resume
state) and `.claude/plan.md` (the per-story architecture plan). If they
land in a commit, a stale checkpoint can follow the branch around and
trigger a bad resume in a later session.

Ensure the project's `.gitignore` excludes them:

- If no `.gitignore` exists, create one with these entries.
- If one exists, check whether it already covers `.claude/`. If not,
  append the two lines below. Do not remove or reorder existing entries.

```
# github-workflow plugin scratch files
.claude/execution-checkpoint.md
.claude/plan.md
```

If the project already ignores `.claude/` wholesale, leave it alone.
This step is best-effort — if `.gitignore` cannot be written, log a
warning and continue.

### 6. Generate or update CLAUDE.md

The user's `CLAUDE.md` is their own file. The goal here is to add
lightweight pointers to supplementary files, not to take over the file
with plugin-specific rules.

**If no `CLAUDE.md` exists**: use `templates/CLAUDE.md` as a starting
point. Write it to the project root. Tell the user this is a starting
template they should customise to match their project.

**If `CLAUDE.md` exists**: check if it already has a
"Supplementary Files" section (or references `ClaudeProject.md`).

- If neither exists, append the Supplementary Files section from the
  template to the end of the existing file. This section is a table of
  pointers to `ClaudeProject.md`, `docs/review.config.md`, and any
  other reference docs the user mentioned during setup.
- If a reference to `ClaudeProject.md` exists but there's no
  Supplementary Files table, offer to upgrade it to the table format.
- If the section already exists, leave it alone.

Do not overwrite, reorder, or remove any existing CLAUDE.md content.
The plugin's guidance is additive only.

### 7. Set up review configuration (optional)

Ask the user if they plan to use the code-review skill for automated
PR reviews. If yes:

1. Check if `docs/review.config.md` already exists. If so, skip.
2. If not, offer to generate it now by running the code-review skill's
   **Config Generation** flow (defined in
   `skills/code-review/SKILL.md`). This will:
   - Ask for a label prefix (e.g., `claude`, `review`)
   - Define review state labels (`{prefix}-reviewing`,
     `{prefix}-approved`, `{prefix}-changes-requested`,
     `{prefix}-needs-re-review`, etc.)
   - Set up non-compliance gates, tech-stack rules, and test
     expectations
   - Create the labels on the GitHub repo
   - Write `docs/review.config.md`
3. If the user declines, note that the code-review skill will prompt
   for this config on first run.

Review state labels are separate from the Claude labels in
ClaudeProject.md. The Claude labels are simple workflow markers; review
state labels are a mutex managed by the code-review skill.

### 8. Verify and report

Confirm all required sections are present in `ClaudeProject.md`.
Display a summary of what was configured:

- Identity (org/repo/branch)
- Package manager
- Quality gate
- Backlog mode (sprint or flat)
- Board (configured or skipped)
- Labels configured

Suggest running `/github-workflow:execute` to start the first story.
