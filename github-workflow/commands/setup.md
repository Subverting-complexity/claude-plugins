---
description: 'Set up or configure a project for this plugin. Trigger: "set up my project", "configure this repo", "onboard", "initialize the workflow", "help me set up".'
---

# Setup

Interactive onboarding wizard for configuring the github-workflow plugin.

## Steps

### 1. Check for existing configuration

Look for these files at the project root:

- `ClaudeProject.md` — project settings for this plugin
- `CLAUDE.md` — project rules

**If `ClaudeProject.md` exists**: read it, identify which sections are
present and which are missing. Offer to fill in the missing sections
rather than overwriting the file.

**If `CLAUDE.md` exists**: do not overwrite. Check if it references
`ClaudeProject.md`. If not, offer to add a reference line at the top.

### 2. Auto-detect project settings

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

### 3. Ask for remaining settings

For anything not auto-detected, ask the user interactively:

- **Branch convention** — suggest `feature/{number}/{short-desc}` as default
- **Priority labels** — what label names for critical/high/medium/low
- **Type labels** — what label names for story/bug/debt/arch
- **Status labels** — what label names for ready/blocked
- **Claude labels** — what label names for reviewed/approved/blocked/
  needs-re-review (suggest `claude:reviewed`, `claude:approved`,
  `claude:blocked`, `claude:needs-re-review`)
- **Custom labels** — ask if the user has any additional labels they
  want the workflow to apply or respect. For each custom label, ask
  the name and when it should be applied. Examples: `high-priority`,
  `frontend`, `backend`, `breaking-change`, `docs-needed`. Store
  these in the Custom section of the label map.
- **Quality gate command** — if not auto-detected
- **Issue prefixes** — suggest `[STORY]`, `[BUG]`, `[ARCH]`, `[DEBT]`

For each setting, show the detected or suggested default and let the
user confirm or override. For labels, also list any existing labels
found on the repo (`gh label list`) so the user can incorporate them.

### 4. Generate ClaudeProject.md

Use the template from `templates/ClaudeProject.md`. Fill in all
detected and user-provided values. Write to `ClaudeProject.md` at
the project root.

If enhancing an existing file, merge new sections into the existing
content without removing sections that are already there.

### 5. Generate or update CLAUDE.md

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

### 6. Verify and report

Confirm all required sections are present in `ClaudeProject.md`.
Display a summary of what was configured:

- Identity (org/repo/branch)
- Package manager
- Quality gate
- Backlog mode (sprint or flat)
- Board (configured or skipped)
- Labels configured

Suggest running `/github-workflow:execute` to start the first story.
