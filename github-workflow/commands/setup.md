---
description: 'Set up or configure a project for this plugin. Trigger: "set up my project", "configure this repo", "onboard", "initialize the workflow", "help me set up", "setup", "init", "bootstrap", "configure the plugin", "first time setup", "harden auto-merge", "enforce CI before merge", "require CI".'
---

# Setup

Interactive onboarding wizard for configuring the github-workflow plugin.

## Focused mode

If `$ARGUMENTS` is `harden` (or `auto-merge`), **skip the full
onboarding** and run **only Step 7b — Harden auto-merge enforcement**
against the already-configured project. This is the easy re-entry point
for wiring up (or repairing) the CI/merge gate after the repo already
has a `ClaudeProject.md`/`review.config.md`. Verify prerequisites
(Step 1) and locate `docs/review.config.md`, then jump straight to
Step 7b. Otherwise run all steps in order.

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
gh api graphql -f query='query { node(id: "{project_id}") { ... on ProjectV2 { fields(first: 20) { nodes { ... on ProjectV2SingleSelectField { id name options { id name color description } } ... on ProjectV2Field { id name } } } } } }'
```

Record the Status single-select field's `id` as `status-field-id`, and
keep the full list of its existing `options` (each with `id`, `name`,
`color`, `description`) — you need them verbatim for the column-creation
step below.

**Ensure the board's lifecycle columns exist:**

The board must mirror the issue lifecycle (see
`templates/default-labels.md` → Board Columns). Compare the Status
field's existing option names against the canonical set and decide what
is missing:

- **Required when a board is selected:** In Progress (`col-in-progress`),
  In Review (`col-in-review`), Blocked (`col-blocked`) — the three active
  workflow columns.
- **Also required only under a `board-column`/`both` ready-gate:** Ready
  (`col-ready`).
- Backlog (`col-backlog`) and Done (`col-done`) usually already exist as
  the board's default Todo/Done options — map those purpose keys onto
  whatever the board already calls them; do not create duplicates.

Match case-insensitively and allow for the board's own naming (e.g. a
default "Todo" satisfies `col-backlog`). For each **missing** column, ask
the user what to name it, suggesting the default (`In Progress`,
`In Review`, `Blocked`, `Ready`). If every required column already
exists, skip creation.

Then create the missing columns in **one** mutation.

> **Critical:** `updateProjectV2Field`'s `singleSelectOptions` is a
> **full replace**, not additive — whatever list you pass becomes the
> complete option set. You **must** pass back every existing option with
> its `id` (preserving it) plus each new option **without** an `id`. Omit
> an existing option and it is **deleted** (along with any items in that
> column). Each option needs `name`, `color`
> (`GRAY`/`BLUE`/`GREEN`/`YELLOW`/`ORANGE`/`RED`/`PINK`/`PURPLE`), and a
> `description` (all required).

Build the `singleSelectOptions` list as: the existing options (each
`{id, name, color, description}` exactly as fetched) followed by the new
ones (no `id`). Suggested colors for new columns: Ready `GREEN`,
In Progress `BLUE`, In Review `YELLOW`, Blocked `RED`.

`gh api graphql` only binds **scalar** variables (`-f`/`-F`), so the
option-list input cannot be passed as a variable — **inline the full
`singleSelectOptions` array directly into the query text**. The `color`
values are enum literals (unquoted); `name`/`description` are quoted
strings. Existing options keep their `id`; new ones omit it:

```
gh api graphql -f query='mutation {
  updateProjectV2Field(input: {
    fieldId: "{status_field_id}"
    singleSelectOptions: [
      { id: "<existing-id-1>", name: "Todo",        color: GRAY,   description: "" },
      { id: "<existing-id-2>", name: "In Progress", color: BLUE,   description: "" },
      { id: "<existing-id-3>", name: "Done",        color: GRAY,   description: "" },
      { name: "In Review", color: YELLOW, description: "PR open, awaiting review" },
      { name: "Blocked",   color: RED,    description: "Blocked or parked — out of the pick pool" }
    ]
  }) {
    projectV2Field { ... on ProjectV2SingleSelectField { options { id name } } }
  }
}'
```

(The example adds In Review and Blocked to a default Todo/In Progress/Done
board; pass back **all** pre-existing options or they are deleted.) The
mutation returns the full option list (existing + new) with their ids. Read the returned `options` to capture the option id for every
canonical column — these become the Status Options values written to
`ClaudeProject.md` in Step 5. This step is best-effort: if the mutation
fails (permissions, etc.), warn the user that the columns must be created
manually in the board UI, record the option ids that do exist, and
continue.

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
  - `none` — no readiness gate; any open unassigned issue is eligible
    for autonomous pickup. (Pair with `agent-gating: disabled` for fully
    unattended pickup of the whole open backlog.)
  Store the choice as `ready-gate` in ClaudeProject.md. If
  `board-column` or `both` is chosen, a project board must be
  configured and must have a "Ready" status option; `label` and `none`
  need no board.
- **Issue lifecycle (status) labels** — the issue-side mirror of the PR
  review-state machine: every issue always carries exactly one. Confirm
  names for the full set (suggest the defaults from
  `templates/default-labels.md` → Issue Lifecycle State Labels):
  - `status-ready` — eligible for pickup, no unresolved dependencies
    (`#0E8A16` green). If `ready-gate` is `label` or `both` this is the
    pickup signal; under `board-column` it is optional.
  - `needs-refinement` — created with minimal spec, needs a refinement
    session (feature-discovery or grill-me) before pickup (`#D4C5F9`
    purple).
  - `status-in-progress` — an agent is actively working it (`#1D76DB`).
  - `status-parked` — a human deliberately set it aside and will resume;
    keeps it out of the pick pool without losing ownership (`#C5DEF5`).
  - `status-blocked` — cannot proceed (external/dependency blocker);
    auto-cleared when its `Blocked by #N` issues close (`#B60205`).
  - `status-in-review` — a PR is open, awaiting review/merge (`#FBCA04`).
  - `status-needs-attention` — a run failed/errored; needs human
    intervention (`#D93F0B`).
  These replace any need for an ad-hoc "blocked" marker — `status-blocked`
  is now a first-class state.
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
   (Priority, Type, Status, Claude, and Custom). "Status" now covers the
   full issue lifecycle set (`status-ready`, `needs-refinement`,
   `status-in-progress`, `status-parked`, `status-blocked`,
   `status-in-review`, `status-needs-attention`). Resolve each name
   through the label map per `templates/default-labels.md`.
2. **Review-state labels** — the nine review-state labels (including the
   `needs-review` entry state and `failed`). If the user set up
   `docs/review.config.md` (step 7) or chose a label prefix, resolve each
   name from its Purpose row there; otherwise use the `review-` defaults
   from `templates/default-labels.md`. Create these even if the user
   defers full review-config setup, so the code-review skill never has to
   create them at runtime.

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

The execute skill writes a session-local scratch file under `.claude/`
that must never be committed: `.claude/plan.md` (the per-story
architecture plan). If it lands in a commit, a stale plan can follow the
branch around and confuse a later session.

Ensure the project's `.gitignore` excludes it:

- If no `.gitignore` exists, create one with this entry.
- If one exists, check whether it already covers `.claude/`. If not,
  append the line below. Do not remove or reorder existing entries.

```
# github-workflow plugin scratch files
.claude/plan.md
```

If the project already ignores `.claude/` wholesale, leave it alone.
This step is best-effort — if `.gitignore` cannot be written, log a
warning and continue.

### 5d. Normalize line endings

Workflows spawn parallel agents in separate git worktrees, and a worktree
is only auto-reaped when it is clean. On Windows the usual reason one stays
"dirty" (blocking cleanup and leaving its branch checked out) is a
**line-ending mismatch**, not a real edit: Git for Windows defaults to
`core.autocrlf=true`, so files get CRLF on disk while the repo stores LF,
and they then read as perpetually modified. Pin the project to LF so this
never happens.

1. **`.gitattributes`** — if the repo has none, create it with:
   ```
   * text=auto eol=lf
   ```
   If one exists but has no `eol`/line-ending rule, offer to append that
   line. Never overwrite or reorder existing rules.
2. **Git config (this clone)** — set the working tree to honor it:
   ```
   git config core.autocrlf false
   git config core.eol lf
   ```
3. **Renormalize** any files already stored with CRLF (no-op if clean):
   ```
   git add --renormalize .
   ```
   If this stages changes, tell the user to commit them once.

This step is best-effort — if any command fails (permissions, no git),
log a warning and continue.

### 5e. Detect native issue types & fields (best-effort)

The workflow prefers the org's **native GitHub issue types** (Bug, Feature,
User Story, Epic) and **org issue fields** over `type-*` labels when they
exist (see `templates/issue-fields-resolution.md`). Detect capability and
record it so the generated `ClaudeProject.md` reflects reality.

1. **Issue types** — list the owner's enabled types:
   ```
   gh api graphql -f query='query($login:String!){ organization(login:$login){ issueTypes(first:20){ nodes { name isEnabled } } } }' -F login='{org}' --jq '[.data.organization.issueTypes.nodes[] | select(.isEnabled) | .name]'
   ```
   If this errors or the owner is a user account (issue types are
   org-only), the project is **not** type-capable — leave the
   `## Issue Types & Fields` section out (the Label Map's `type-*` labels
   remain the classification) and skip step 2.
2. **Issue fields** — list configured fields:
   ```
   gh api "orgs/{org}/issue-fields" --jq '[.[] | .name]'
   ```
3. **Write the section** — if the org is type-capable, fill in the
   `## Issue Types & Fields` section of `ClaudeProject.md` from the
   template, mapping each `field-*` purpose to the **actual** field name
   detected in step 2 (override the default only where the org's name
   differs). Note which expected fields are **missing** so the user can
   create them — the workflow simply skips a missing field at runtime.
4. **Origin field** — if `Origin` is absent, point the user at
   `/github-workflow:setup`'s field guidance or the GitHub *Issue fields*
   settings UI to add it (single-select: Grill-Me Session, Security Audit,
   Feature Discovery, Code Review, Development, Stakeholder Request). It is
   the one field the workflow populates that GitHub does not create by
   default.

This step is best-effort and **non-blocking**: a project with no native
types/fields is fully supported on the label-only path.

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
   - Define review state labels (`{prefix}-needs-review`,
     `{prefix}-reviewing`, `{prefix}-approved`,
     `{prefix}-changes-requested`, `{prefix}-needs-re-review`,
     `{prefix}-failed`, etc.)
   - Set up non-compliance gates, tech-stack rules, and test
     expectations
   - Ask whether to **auto-merge approved PRs** (squash-merge once Claude
     approves and posts its comment). This defaults to **off**; enable it
     only for repos that should merge approved reviews unattended. Stored
     as `auto-merge-on-approval` in `docs/review.config.md`. **If the user
     enables it, run Step 7b** (Harden auto-merge enforcement) before
     finishing — that step turns on repo-level auto-merge, attempts
     branch protection with required checks, and sets the
     `require-ci-before-merge` fallback when GitHub can't enforce them.
   - Create the labels on the GitHub repo
   - Write `docs/review.config.md`
3. If the user declines, note that the code-review skill will prompt
   for this config on first run.

Review state labels are separate from the Claude labels in
ClaudeProject.md. The Claude labels are simple workflow markers; review
state labels are a mutex managed by the code-review skill.

### 7b. Harden auto-merge enforcement

Run this when the user **enables `auto-merge-on-approval`** (from Step 7),
or standalone via `/github-workflow:setup harden`. It makes "merge only
after CI passes" actually enforceable. Without it, an approved PR on a
branch with no **required** checks merges immediately — no CI guarantee.

The goal is **one** of two safe configurations:

- **(a) GitHub enforces it** — branch protection with required status
  checks. Preferred, but needs a public repo or GitHub Pro/Team on a
  private one.
- **(b) The plugin enforces it** — `require-ci-before-merge: true` in
  `docs/review.config.md` + a real PR pipeline. The fallback when (a)
  isn't available.

Resolve `{org}`, `{repo}`, `{branch}` from `ClaudeProject.md`. Each
sub-step is **best-effort** and degrades to a warning.

1. **Enable repo-level auto-merge** (needed by `gh pr merge --auto`):
   ```bash
   gh api -X PATCH repos/{org}/{repo} -F allow_auto_merge=true
   allowed=$(gh api repos/{org}/{repo} --jq '.allow_auto_merge')
   ```
   **Read it back** — some orgs accept the PATCH (200) but silently keep
   it `false` via policy. If `allowed` is not `true`, warn: repo-level
   auto-merge is blocked by org/repo policy; an admin must enable "Allow
   auto-merge" in Settings → Pull Requests, or queued merges never fire.

2. **Branch protection + required checks.** Find candidate check
   contexts — the job names in `.github/workflows/*.yml`, or the check
   names on a recent PR (`gh pr checks <recent-pr> --repo {org}/{repo}`).
   Ask the user which contexts must pass before merge. Apply protection
   with **strict** mode (require branches up to date):
   ```bash
   gh api -X PUT repos/{org}/{repo}/branches/{branch}/protection \
     --input - <<'JSON'
   {
     "required_status_checks": { "strict": true, "contexts": ["<ctx>", "..."] },
     "enforce_admins": false,
     "required_pull_request_reviews": null,
     "restrictions": null
   }
   JSON
   ```
   If this returns **403** ("Upgrade to GitHub Pro or make this
   repository public"), GitHub cannot enforce required checks on this
   repo — required status checks are paid-plan-only for private repos, so
   a private repo on the Free plan can never use configuration (a). Note
   it and proceed to step 3 (the plugin-side fallback is the only gate
   available); to get server-side enforcement instead, the repo must go
   public or move to GitHub Pro/Team. See the "Plan limitation" note in
   `skills/code-review/references/review-config-guide.md`. If there are no
   CI workflows at all, say so: there is nothing to require yet (merge the
   pipeline first), and step 3 is the only available guard.

3. **Plugin-side fallback.** If step 1 or 2 could **not** be fully
   enforced (repo auto-merge stuck off, branch protection unavailable, or
   no required checks now exist), set in `docs/review.config.md`'s
   Auto-Merge on Approval section:
   ```
   | require-ci-before-merge | `true` |
   ```
   Tell the user why: GitHub isn't enforcing the gate, so the code-review
   skill will — it waits for a green CI run and **pauses** an approved PR
   that has no checks or a red check, instead of merging it. (If
   server-side enforcement via step 2 fully succeeded, leaving this
   `false` is fine; configuration (a) already covers it.)

4. **Report** what landed: repo auto-merge on/off, branch protection
   applied or blocked, and which enforcement configuration ((a), (b), or
   "neither — auto-merge is unguarded; merge a CI pipeline first") is now
   in effect.

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

## Troubleshooting

### A story or PR is stuck and no agent will pick it

Exclusive ownership is enforced by atomic refs under `refs/claims/`
(see `templates/claim-procedure.md`), not by labels or assignment. These
refs are released automatically on every normal exit, but an ungraceful
exit — a hard-killed session, a crash, or a machine reboot — can leave an
orphaned ref with no live owner. Every future attempt to claim that item
then fails and it silently drops out of the pool.

To recover, list the active claims and free the abandoned one **after**
confirming no live session holds it:

```
git ls-remote origin 'refs/claims/*'
git push origin :refs/claims/issue-{number}   # or :refs/claims/pr-{number}
```

Full procedure and safety checks: **Reaping orphaned claims** in
`templates/claim-procedure.md`.
