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

```
gh api graphql -f query='query { organization(login: "{org}") { projectsV2(first: 10) { nodes { id number title } } } }'
```

If boards are found, list them and ask which to use (or none).
When a board is selected, auto-fetch its field IDs and status option IDs:

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
- **Status labels** — what label names for ready/blocked
- **Claude labels** — simple workflow markers. Suggest
  `claude:authored` and `claude:blocked`. These are separate from the
  review state labels (including `{prefix}-approved`) set up in
  Step 7.
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

For each setting, show the detected or suggested default and let the
user confirm or override. For labels, also list any existing labels
found on the repo (`gh label list`) so the user can incorporate them.

### 5. Generate ClaudeProject.md

Use the template from `templates/ClaudeProject.md`. Fill in all
detected and user-provided values. Write to `ClaudeProject.md` at
the project root.

If enhancing an existing file, merge new sections into the existing
content without removing sections that are already there.

### 5b. Create labels on GitHub

For every label configured in ClaudeProject.md (Priority, Type, Status,
Claude, and Custom), check if it already exists on the repo. If not,
create it:

```
gh label create "<label-name>" --description "<description>" --force
```

Use `gh label list --json name` to get existing labels first, then only
create missing ones. The `--force` flag updates existing labels without
error.

Suggested colours (user can override):
- Priority labels: critical `#B60205`, high `#D93F0B`, medium `#FBCA04`, low `#0E8A16`
- Type labels: story `#1D76DB` (blue), bug `#D93F0B` (red-orange), security `#B60205` (red), debt `#FBCA04` (yellow), arch `#0E8A16` (green)
- Status labels: `#5319E7` (purple)
- Claude labels: `#BFDADC` (light teal)

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
