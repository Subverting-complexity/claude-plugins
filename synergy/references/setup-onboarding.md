# Setup: full onboarding

Read by `/synergy:setup` with no argument, after Step 1 (prerequisites) in the command. Run every step in order. Each step reads its own template or guide at the point it runs, not before.

## 1b. Set up the `wf` picker runtime (recommended)

Follow `references/setup-wf.md`.

## 2. Check for existing configuration

Look for these files at the project root:

- `ClaudeProject.md`: project settings for this plugin
- `CLAUDE.md`: project rules

**If `ClaudeProject.md` exists**: read it, identify which sections are present and which are missing. Offer to fill in the missing sections rather than overwriting the file.

**If `CLAUDE.md` exists**: do not overwrite. Check if it references `ClaudeProject.md`. If not, offer to add a reference line at the top.

## 3. Auto-detect project settings

Run these detections and report what was found.

**Repository identity:**

```
gh repo view --json owner,name,defaultBranchRef --jq '{org: .owner.login, repo: .name, branch: .defaultBranchRef.name}'
```

**Package manager**, from lock files: `pnpm-lock.yaml` → pnpm; `package-lock.json` → npm; `yarn.lock` → yarn; `*.sln` or `*.csproj` → dotnet; `go.mod` → go; `Cargo.toml` → cargo; `uv.lock` → python (uv); `requirements.txt` or `pyproject.toml` → python; `Gemfile.lock` → ruby (bundler); `pubspec.lock` → dart/flutter; `mix.lock` → elixir; `build.gradle`, `build.gradle.kts` or `gradlew` → JVM (gradle).

**Quality gate**: look for `scripts/*quality*` or `scripts/*test*`, `package.json` scripts (test, lint, typecheck), `Makefile` targets (test, check, lint), or `dotnet test`.

**The `Stage` field:** an issue's state is the org issue field `Stage`, a single-select with nine options: `Backlog`, `In Progress`, `In Review`, `Blocked`, `Non-code`, `Needs refinement`, `Parked`, `Needs attention` and `Done`. A blank `Stage` means available, the same as `Backlog`. Setup does not create the field and does not create or rename board columns. Step 5e reads whether the org has it.

When the field or an option is missing, stop and ask the user to add it by hand, because the API this runs on cannot create an org issue field: org settings → *Planning* → *Issue fields* → create `Stage` as a single-select with the nine options, then pin it to every enabled issue type. Without it no transition can be written and preflight fails with `stage-absent` or `stage-options`.

**Project board (optional):** a board is a view for people. Nothing in the workflow reads a column from it or moves a card on it, so a project without one works the same. A board can be owned by an **organization** or by a **user**, so query both (the org query errors or returns empty when `{org}` is a personal account):

```
gh api graphql -f query='query { organization(login: "{org}") { projectsV2(first: 20) { nodes { id number title } } } }'
gh api graphql -f query='query { user(login: "{org}") { projectsV2(first: 20) { nodes { id number title } } } }'
```

List what comes back by **title** (and number) and ask which to record, or none. Zero boards can also mean the token lacks the `read:project` scope, so mention `gh auth status` if the user expected one. Record the chosen board's `number` as `project-number`, its `id` as `project-node-id` and its `title` as `project-title`. Then tell the user the one manual step that makes the board show state: add the `Stage` field to the board and set each view's "Column by" to `Stage`. GitHub's built-in "Auto-add to project" workflow keeps new issues on it.

**Milestones:**

```
gh api repos/{org}/{repo}/milestones --state open --jq '.[] | {title, due_on, open_issues}'
```

If milestones with due dates exist, note that sprint mode is available.

## 4. Ask for remaining settings

For anything not auto-detected, ask the user, showing the detected or suggested default for them to confirm or override:

- **Branch convention**: suggest `feature/{number}/{short-desc}` as default
- **Quality gate command**: if not auto-detected
- **Refinement skill**: which skill to use when a story is too thin to implement. Default: `feature-discovery` (runs the `grill` interview, then writes the fuller spec and acceptance criteria). Store as `refinement-skill` in ClaudeProject.md.

**Do not ask about labels, and create none except the review-state labels in Step 5b.** No label decides anything: an issue's state is its `Stage` field, and its priority, size and owner are the `Priority`, `Effort` and `Ownership` fields. A repository that already has priority, type, status or scope labels keeps them (deleting a label strips it from every issue that ever carried it), and `wf issue-apply` takes one off any issue it writes.

**Do not ask about agent gating.** There is no approval label. A person approves an issue for autonomous pickup by setting its `Stage` to `Backlog` or leaving it blank, and withholds approval by setting `Needs refinement` or `Parked`.

## 5. Generate ClaudeProject.md

Read `templates/ClaudeProject.md` once and fill in all detected and user-provided values. Write to `ClaudeProject.md` at the project root. When enhancing an existing file, merge new sections into it without removing sections already there.

## 5b. Create the review-state labels

The nine review-state labels on a pull request are the only labels the workflow applies, so creating them is the whole of label setup. Create them even if the user defers the review config in Step 7, so the pr-review skill never has to create one mid-run:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" labels-ensure
```

It names each label through `docs/review.config.md` when that exists, falling back to the `review-` defaults, and creates only the ones the repo lacks, never with `--force`, so an existing label keeps its colour and description. This step is best-effort: on a non-zero exit, log a warning naming its `reason` and any `failed` labels, and continue.

## 5c. Ignore plugin scratch files

The workflow writes session-local scratch files under `.claude/` that must never be committed. A committed plan can follow the branch around and confuse a later session, and any stray untracked scratch file can send an exit-time or pre-merge tree check looking for something to commit. Ensure `.gitignore` excludes them: create it if absent; if it exists and does not already cover `.claude/` wholesale, append the lines below without removing or reordering existing entries.

```
# synergy plugin scratch files (per-session, never commit)
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

Best-effort: if `.gitignore` cannot be written, log a warning and continue.

## 5d. Normalize line endings

Workflows spawn parallel agents in separate git worktrees, and a worktree is only auto-reaped when it is clean. On Windows the usual reason one stays "dirty" is a **line-ending mismatch**, not a real edit: Git for Windows defaults to `core.autocrlf=true`, so files get CRLF on disk while the repo stores LF. Pin the project to LF:

1. **`.gitattributes`**: if the repo has none, create it with `* text=auto eol=lf`. If one exists but has no `eol` rule, offer to append that line. Never overwrite or reorder existing rules.
2. **Git config (this clone)**: `git config core.autocrlf false` and `git config core.eol lf`.
3. **Renormalize** files already stored with CRLF: `git add --renormalize .`. If this stages changes, tell the user to commit them once.

Best-effort: if any command fails, log a warning and continue.

## 5e. Write the Issue Types & Fields section

The workflow prefers the org's **native GitHub issue types** (Bug, Feature, User Story, Epic) and **org issue fields** over `type-*` labels where they exist. Resolve what this owner actually has, then write the section from that, never from a static default, and never leave it out.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" org-capabilities --refresh
```

One call answers both questions and caches the result. Read from it:

- `owner_kind`: `organization` or `user`. Issue types are org-only.
- `type_map`: the enabled native types. Non-empty means **type-capable**.
- `resolved_fields`: each purpose key mapped to the field name that exists here, which is what the section's table records.
- `missing_fields`: the purpose keys that do not resolve, each with the name that was looked for.

Then write `## Issue Types & Fields` into `ClaudeProject.md` following the template's section:

1. **Capability**: `type-capable: yes` when `type_map` is non-empty, `no` otherwise.
2. **Field names**: one row per entry in `resolved_fields`, using the concrete name this owner uses rather than the default.
3. **Missing**: one row per entry in `missing_fields`, saying what the workflow does without it.

**Write the section either way**, but read exit **21** (`no-capabilities`) carefully first, because it covers two different answers and only one of them may be written down:

- The payload carries a **`denied`** list: the signed-in account may not read this org's types and fields, so nothing is known about them. Say which account and what it could not read, point at `gh auth switch`, and **leave any existing section alone**. Writing `type-capable: no` here records a failed lookup as a fact, and every issue created afterwards gets no type and no field values with nothing reporting it.
- No `denied` list: the org genuinely has neither. Write the section saying exactly that (`type-capable: no`, every field under *Missing*).

"This org has none" and "nobody wrote this section" must not look the same. `wf config-audit` reports a missing section as CRITICAL, so leaving it out breaks preflight in the consumer's repo.

Flag `field-stage` if it is missing or lacks one of its nine options (the manual step in Step 3). Flag the three mandatory fields, `field-priority`, `field-effort` and `field-ownership`, if any is missing, because `wf issue-apply` refuses to create an issue without them: they are the pool's order, its size ceiling, and whether a code agent may take the issue at all. `field-type` (`Classification`) and `field-origin` are optional; an issue created without one gets a comment saying so. For `Origin`, point the user at the owner's *Issue fields* settings to add it as a single-select (Security Audit, Feature Discovery, Code Review, Development, Stakeholder Request).

On exit **20** the capability read failed (auth, network, no `wf`). Say so and leave any existing section alone.

## 6. Generate or update CLAUDE.md

The user's `CLAUDE.md` is their own file. The goal is to add lightweight pointers to supplementary files, not to take it over with plugin rules. Do not overwrite, reorder or remove any existing content.

If no `CLAUDE.md` exists, write `templates/CLAUDE.md` to the project root as a starting point and tell the user to customise it.

If `CLAUDE.md` exists, check for a "Supplementary Files" section or a reference to `ClaudeProject.md`:

- Neither: append a Supplementary Files table of pointers to `ClaudeProject.md`, `docs/review.config.md`, and any other reference docs the user mentioned during setup.
- A reference to `ClaudeProject.md` but no table: offer to upgrade it to the table format.
- The section already exists: leave it alone.

## 7. Set up review configuration (optional)

Ask whether the user plans to use the pr-review skill for automated PR reviews. If they decline, note that the pr-review skill will prompt for this config on first run.

If they accept and `docs/review.config.md` does not exist yet, follow `skills/pr-review/references/review-config-guide.md` to generate it. It asks for the label prefix, gates, tech-stack rules and test expectations, asks the auto-merge questions, writes the file and runs `labels-ensure` again.

Review-state labels are a mutex managed by the pr-review skill, and the only labels the workflow applies.

## 7b. Harden auto-merge enforcement

Run this only if the user enabled `auto-merge-on-approval` in Step 7. Without it, an approved PR on a branch with no **required** checks merges immediately. Follow `templates/harden-auto-merge.md` and report what landed.

## 8. Claude Code Ecosystem Tools (recommended, skippable)

Present this as a recommended step the user can wave off in a sentence. The reason it is worth a minute: `execute` and `pr-review` read `.claude/ecosystem.md` to run a codebase knowledge graph (Graphify) and token, cost and security tools automatically; without that cheat-sheet they do not know the tools are installed.

Read `skills/ecosystem-setup/SKILL.md` and follow it now, rather than invoking the skill: it sets `disable-model-invocation`, so only a person can run it as a slash command. It asks once which tools the user wants, installs and configures each, and writes `.claude/ecosystem.md` (adding a row to the CLAUDE.md Supplementary Files table from Step 6). If the user wants nothing, it leaves only an opt-out marker and nothing is blocked.

## 9. Verify and report

Confirm all required sections are present in `ClaudeProject.md`. Report what was configured:

- Identity (org/repo/branch)
- Package manager
- Quality gate
- Backlog mode (sprint or flat)
- `Stage` field (present with all nine options, or what is missing)
- Board (recorded or none)
- Labels configured
- Ecosystem tools enabled (if any)

Suggest running `/synergy:execute` to start the first story. Mention `/synergy:setup reap` for a story or PR that is stuck behind a crashed session's claim, and `/synergy:setup issues` to backfill issues created outside the workflow.
