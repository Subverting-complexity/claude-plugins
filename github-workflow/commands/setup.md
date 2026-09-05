---
description: 'Set up or configure a project for this plugin. Trigger: "set up my project", "configure this repo", "harden auto-merge", "set up ecosystem tools", "reap claims", "audit my issues".'
argument-hint: '[harden|ecosystem|reap|wf|issues]'
---

# Setup

Interactive onboarding wizard for configuring the github-workflow plugin.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

The **shape** of what you report follows
`../skills/user-facing-communication/SKILL.md`: lead with the outcome and
the current state, put anything outstanding, blocked or assumed where it
cannot be missed, name every work item as well as numbering it, and leave
out the investigation history. It applies to every reply you write, not
only the last one.

## Focused mode

If `$ARGUMENTS` is `harden` (or `auto-merge`), **skip the full
onboarding** and run **only Step 7b — Harden auto-merge enforcement**
against the already-configured project. This is the easy re-entry point
for wiring up (or repairing) the CI/merge gate after the repo already
has a `ClaudeProject.md`/`review.config.md`. Verify prerequisites
(Step 1) and locate `docs/review.config.md`, then jump straight to
Step 7b. Otherwise run all steps in order.

If `$ARGUMENTS` is `ecosystem`, **skip the full onboarding** and run
**only Step 8 — Claude Code Ecosystem Tools** against the
already-configured project. Use this to install, update, or add tools
to an existing repo without re-running the full wizard. Verify
prerequisites (Step 1), then jump straight to Step 8.

If `$ARGUMENTS` is `reap`, **skip the full onboarding** and run
**only Step 10 — Reap orphaned claim refs** against the
already-configured project. Use this when a story or PR is stuck and
no agent will pick it up (a crashed session left a lock behind), or
as a scheduled routine to keep the claim namespace clean. Verify
prerequisites (Step 1), read `ClaudeProject.md` for org/repo, then
jump straight to Step 10.

If `$ARGUMENTS` is `issues` (or `backlog`), **skip the full onboarding**
and run **only Step 11 — Audit the backlog's issue metadata** against the
already-configured project. Use this to find issues that carry no native
type, no field values or no dependency edges, and to backfill them.
Verify prerequisites (Step 1), then jump straight to Step 11.

If `$ARGUMENTS` is `wf` (or `picker`), **skip the full onboarding** and
run **only Step 1b — Set up the `wf` picker runtime** against the
already-configured project. Use this to create (or repair, with
`--force`) the dedicated Python virtualenv the fast-path picker reuses.
Verify prerequisites (Step 1), then jump straight to Step 1b.

## Steps

### 1. Verify prerequisites

Before doing anything else, verify the required shell tools are available.

**bash** (required — all auto-run `!`-blocks in this plugin use bash syntax):

```
bash --version
```

If bash is not found, stop and tell the user to install it. On Windows,
[Git for Windows](https://git-scm.com) includes Git Bash; alternatively
enable WSL. Without bash on PATH the plugin's auto-run blocks will not
work.

**GitHub CLI** (required — all workflow commands use `gh`):

```
gh auth status
```

If this fails, stop and tell the user to run `gh auth login` first.

### 1b. Set up the `wf` picker runtime (recommended)

`execute` has a **fast
path**: a bundled `wf` CLI that runs the whole select → claim → validate
loop in one call instead of a dozen sequential `gh` round-trips. It needs a
Python 3 interpreter. This step pins a **dedicated virtualenv** for it —
created once under the plugin's persistent data dir and reused on every
later call — so the picker never depends on whatever Python is on PATH (and
sidesteps the broken `python3` Store shim on Windows).

Run the bootstrap. It finds a working Python 3, creates the venv, installs
`requirements.txt`, and verifies it; it is idempotent — a valid venv is
reused, not rebuilt:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" setup
```

- **Exit 0** — the virtualenv is ready; report the interpreter it pinned.
- **Exit 20, "Python 3 … not found"** — no Python is available. Show the
  user the platform install command it printed and ask them to install
  Python, then re-run this step. If they want it done for them, re-run as
  `wf.sh setup --install-python` — that installs system Python via
  winget/brew/apt, and runs **only** with this explicit opt-in.

This step is **optional but recommended**. Without it the launcher still
probes a system Python and uses that. But `wf` itself is not optional:
`execute` and `bulk-execute` have no markdown fallback, so if the probe
finds no Python 3 those commands fail naming the missing prerequisite. To
rebuild a broken venv, re-run with `--force`.

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
- `uv.lock` → python (uv)
- `requirements.txt` or `pyproject.toml` → python
- `Gemfile.lock` → ruby (bundler)
- `pubspec.lock` → dart/flutter
- `mix.lock` → elixir
- `build.gradle`, `build.gradle.kts`, or `gradlew` → JVM (gradle)

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

Merge the results. **Zero boards returned does not prove none exists** —
the token may lack the `read:project` scope, or the board may be private
and invisible to it. Say so, suggest checking `gh auth status` (scopes)
and the board's visibility, and get the user's explicit confirmation
that there is no board before configuring the project boardless. If
boards are found, list them by **title** (and
number) and ask which to use (or none). Record the chosen board's
`number` as `project-number`, its `id` as `project-node-id`, and its
`title` as `project-title` — `project-title` lets later commands confirm
the stored node id still points at the intended board before they mutate
it, which `wf board-move` does on every write. When a board is selected,
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
fails (non-zero exit, or a response with an `errors` array — GraphQL can
return HTTP 200 with errors), warn the user that the columns must be created
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
    session (feature-discovery) before pickup (`#D4C5F9` purple).
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
  story is next in the queue. Default: `feature-discovery` (runs in
  validation mode for lightweight Q&A, or discovery mode for full
  spec+AC). Store as `refinement-skill` in ClaudeProject.md.

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

The workflow writes session-local scratch files under `.claude/` that must
never be committed: the per-story architecture plan, the projected config,
the marker and cache files, and the claim and flag files the phases use to
carry state across a compaction. A committed plan can follow the branch
around and confuse a later session, and any stray untracked scratch file can
send an exit-time or pre-merge tree check looking for something to commit.

Ensure the project's `.gitignore` excludes them:

- If no `.gitignore` exists, create one with these entries.
- If one exists, check whether it already covers `.claude/`. If not, append
  the lines below. Do not remove or reorder existing entries.

```
# github-workflow plugin scratch files (per-session, never commit)
.claude/plan.md
.claude/projected-config.md
.claude/preflight-passed.txt
.claude/label-cache.json
.claude/issue-fields-cache.json
.claude/candidates.json
.claude/claim-*.sha
.claude/wf-config.json
.claude/*.flag
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

### 5e. Write the Issue Types & Fields section

The workflow prefers the org's **native GitHub issue types** (Bug, Feature,
User Story, Epic) and **org issue fields** over `type-*` labels where they
exist. Resolve what this owner actually has, then write the section from
that — never from a static default, and never leave it out.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" org-capabilities --refresh
```

One call answers both questions and caches the result. Read from it:

- `owner_kind` — `organization` or `user`. Issue types are org-only.
- `type_map` — the enabled native types. Non-empty means **type-capable**.
- `resolved_fields` — each purpose key mapped to the field name that exists
  here, which is what the section's table records.
- `missing_fields` — the purpose keys that do not resolve, each with the
  name that was looked for.

Then write `## Issue Types & Fields` into `ClaudeProject.md` following
`templates/ClaudeProject.md`:

1. **Capability** — `type-capable: yes` when `type_map` is non-empty, `no`
   otherwise.
2. **Field names** — one row per entry in `resolved_fields`, using the
   concrete name this owner uses rather than the default.
3. **Missing** — one row per entry in `missing_fields`, saying what the
   workflow does without it.

**Write the section either way**, but read exit **21**
(`no-capabilities`) carefully first, because it covers two different
answers and only one of them may be written down:

- The payload carries a **`denied`** list — the signed-in account may not
  read this org's types and fields, so nothing is known about them. Say
  which account and what it could not read, point at `gh auth switch`, and
  **leave any existing section alone**. Writing `type-capable: no` here
  records a failed lookup as a fact, and every issue created afterwards
  gets no type and no field values with nothing reporting it.
- No `denied` list — the org genuinely has neither: write the section
  saying exactly that (`type-capable: no`, every field under *Missing*).

An org without types and fields is fully supported on the label-only path
— but "this org has none" and "nobody wrote this section" must not look
the same, which is the failure this step exists to prevent. `wf
config-audit` reports a missing section as CRITICAL, so leaving it out
breaks preflight in the consumer's repo.

Flag the mandatory four — `field-priority`, `field-effort`, `field-type`,
`field-origin` — if any is missing, because `wf issue-apply` refuses to
create an issue without them. `Origin` is the one the workflow populates
that GitHub does not create by default; point the user at the owner's
*Issue fields* settings to add it as a single-select (Security Audit,
Feature Discovery, Code Review, Development, Stakeholder Request).

On exit **20** the capability read failed (auth, network, no `wf`). Say so
and leave any existing section alone — do not overwrite a good section with
a guess.

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
     as `auto-merge-on-approval` in `docs/review.config.md`. Say plainly
     what it covers, because it is the **only** switch that decides this:
     it governs `/github-workflow:code-review` **and** the merge phase at
     the end of a `/github-workflow:execute` run. Left off, an execute run
     ends at an approved pull request waiting for a person, which is a
     complete run. **If the user enables it, run Step 7b** (Harden
     auto-merge enforcement) before finishing — that step turns on
     repo-level auto-merge, attempts branch protection with required
     checks, and sets the `require-ci-before-merge` fallback when GitHub
     can't enforce them.
   - Ask, **only if auto-merge was enabled**, what to do when CI can't run
     because of a GitHub Actions **billing or account** problem (out of
     minutes, spending limit hit, a failed payment): should an approved PR
     merge anyway? Default **no**. Stored as `bypass-ci-on-billing-failure`
     in `docs/review.config.md` — `true` merges an approved PR only when a
     billing/account failure is the sole blocker (a real test/build/lint
     failure is never bypassed). It covers billing stopping the pipeline from
     being created at all, not only one that runs and fails; in that case the
     merge also requires the project's quality gate to have passed locally. It
     is the persistent, per-project form of the one-off `--bypass-ci` flag.
   - Ask, **only if auto-merge was enabled and the repo has zero active
     GitHub Actions workflows** (count them first — the question is
     meaningless otherwise): its PRs will never report a check, so should an
     approved PR merge anyway, on the strength of the local quality gate?
     Default **no**. Stored as `bypass-ci-when-no-pipeline` in
     `docs/review.config.md` — `true` merges an approved PR only when the
     rollup is completely empty, the repo really has no active workflows, and
     the project's quality gate passed locally on that SHA. Any check at all,
     in any state, is gated normally. This is the setting for a project whose
     CI lives where GitHub cannot see it (Buildkite, Jenkins, CircleCI) as
     much as for one with no CI; left `false`, every approved PR on such a
     repo pauses at the no-checks guard. It is mutually exclusive with
     `bypass-ci-on-billing-failure`, which needs workflows to exist.
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
after CI passes" actually enforceable — without it, an approved PR on a
branch with no **required** checks merges immediately.

Follow the full procedure in `templates/harden-auto-merge.md`. Resolve
`{org}`, `{repo}`, `{branch}` from `ClaudeProject.md` first. It aims for
one of two safe configurations — GitHub-enforced branch protection, or
the plugin-side `require-ci-before-merge` fallback — and each sub-step is
best-effort, degrading to a warning. Report what landed.

### 8. Claude Code Ecosystem Tools (recommended, skippable)

This is where a project actually starts *using* the companion tools, so
present it as a recommended step rather than a footnote — but one the user
can wave off in a sentence. Give the one-line reason it is worth a minute:
the workflow's `execute` and `code-review` skills read `.claude/ecosystem.md`
to run a codebase knowledge graph (Graphify) and token/cost/security tools
automatically; without that cheat-sheet they have no idea the tools are
installed, so the tools sit unused. Set them up once and every future run
benefits.

Offer to set up commonly used Claude Code companion tools (Graphify, RTK,
ccusage, ecc-agentshield, Fallow) and record what was enabled in
`.claude/ecosystem.md` — the cheat-sheet that `/github-workflow:execute`
and `/github-workflow:code-review` read to use those tools automatically.
If the user declines everything, the step is a clean no-op: it leaves a
small opt-out marker so onboarding never nags again, and nothing is
blocked.

This is handled by the shared **`ecosystem-setup`** skill
(`skills/ecosystem-setup/SKILL.md`), so the github-workflow and
local-workflow plugins stay in lockstep instead of each carrying their own
copy of the tool list. Run that skill now: it asks once whether the user
wants any tools, detects/installs/configures each one they choose, offers
the optional commit-reminder hook, and writes `.claude/ecosystem.md`
(adding a row to the CLAUDE.md Supplementary Files table from Step 6 when
one exists). If the user wants nothing, it writes no file — zero impact on
future context windows.

The focused mode `/github-workflow:setup ecosystem` is just this step on
its own — equivalent to invoking the `ecosystem-setup` skill directly.

---

### 9. Verify and report

Confirm all required sections are present in `ClaudeProject.md`.
Display a summary of what was configured:

- Identity (org/repo/branch)
- Package manager
- Quality gate
- Backlog mode (sprint or flat)
- Board (configured or skipped)
- Labels configured
- Ecosystem tools enabled (if any)

Suggest running `/github-workflow:execute` to start the first story.

---

### 10. Reap orphaned claim refs

The workflow locks each in-flight issue or PR with a git ref under
`refs/claims/`. A crash or hard kill can leave an orphaned ref that
silently blocks future pickup of that item. This step scans active claim
refs, frees those that no longer back live work, and flags anything that
needs manual review.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-reap
```

Add `--threshold N` to change the age below which a ref is left alone
(default **4** hours), or `--dry-run` to see the verdicts without freeing
anything.

It always exits 0 and reports three lists. `reaped` are the refs it freed:
the issue is closed, no longer marked in progress, or already has a PR
open; the PR is closed, merged, or open with no review under way.
`suspect` are the refs it deliberately left, because the evidence does not
say the work has stopped — an issue still in progress with no PR, a PR
under active review, or a target it could not read. `skipped` are refs
younger than the threshold. Report the counts, and name every `suspect`
ref with its reason so a person can decide.

It is safe to run at any time — it never reaps a ref that still backs a
running session — and is schedulable via `/schedule` calling
`/github-workflow:setup reap`.

### 11. Audit the backlog's issue metadata

Step 5e records what the org *can* classify an issue with. This checks
what the open issues actually carry, because nothing else does: an issue
created outside the workflow, or before the org enabled types, sits there
with no type and no field values, and no error anywhere says so. It only
reads.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-audit
```

Add `--repo owner/name` to audit a different repository, `--limit N` or
`--since 2026-01-01` to work through a large backlog in slices, and
`--parents` to also report the parent an issue's body claims but the
hierarchy does not have (off by default — a story created through
`feature-discovery` already carries its epic, so reading it back out of
the body only re-derives what the pipeline knew).

Read the exit code: **0** means every open issue carries its type, its
field values and its dependency edges — say so and stop. **25** means it
found gaps and wrote a spec, by default `.claude/issue-audit-spec.json`.
**21** means the org's capabilities could not be read, so there is nothing
to audit against; fix that first (Step 5e) rather than reporting a clean
backlog.

On **25**, open the spec. Every value the audit could not infer is the
placeholder `TODO`, and `issue-apply` refuses a spec that still contains
one, so fill each in — priority, effort and origin are the usual ones.
Then apply it:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/issue-audit-spec.json
```

Dependency edges are **proposed, never applied unattended**: they are read
out of body prose, which is not reliable enough to build a graph from
without someone looking. Check each `blocked_by` before applying, and
delete the ones that are wrong.

Report the counts by gap kind and name what you changed. A
`dependency-closed` finding is not fixed by the spec — the body cites an
issue that is no longer open, so either the body is stale or the
dependency was resolved; say which issues and leave them to the user.

## Troubleshooting

### A story or PR is stuck and no agent will pick it

The workflow locks each in-flight issue or PR with a ref under
`refs/claims/`. These refs are released automatically on every normal
exit, but a crash or hard kill can leave an orphaned ref that silently
blocks future pickup.

**The fast fix:** run `/github-workflow:setup reap`. It scans all
claim refs, cross-checks each against the issue's current state, and
frees any that no longer back live work — without touching anything
that still does.

If the reaper flags the stuck ref as "suspect" (the issue is still
in-progress with no open PR), confirm no session is running for it,
then free it manually:

```bash
git ls-remote origin 'refs/claims/*'           # list all active claims
git push origin :refs/claims/issue-{number}    # free a specific claim
```

Full background and safety notes: `docs/rationale/claim-procedure-rationale.md`.
