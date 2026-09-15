---
name: feature-discovery
description: 'Plan a feature, change or new project and break it into epics, features and stories with acceptance criteria. Trigger on scoping work, planning a new project, or refining an issue too thin to build.'
depends-on:
  - interview
  - code-architect
---
# Feature Discovery

Turn a feature, change, requirement or brand-new project into buildable stories. The interview that gets there is run by the `interview` skill; this skill decides what the interview must cover and what gets built from its answers. A request to stress-test a plan without producing stories is an interview on its own: run `/synergy:interview` instead.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## Skills Used

Read each skill's SKILL.md when you reach the phase that needs it.

- **interview** (`/synergy:interview`) — The interview: how questions are asked, paced and closed, and what happens when nobody is present to answer.
- **code-architect** (`/synergy:code-architect`) — Architecture design and validation.

## Scope Detection

Determine scope before the interview. It decides which coverage topics apply.

| Tier | Signal | Coverage |
|------|--------|----------|
| **Small** | Single concern: one endpoint, one screen, one config change, one bugfix | Scope, integration points. |
| **Medium** | Multi-concern feature: touches 2-4 modules, new user journey, new data model | Adds journeys, data model, API surface, dependencies. |
| **Large** | Major feature: new subsystem, significant rewrite, 5+ stories of work | Every topic. |
| **New project** | Nothing exists yet: a product idea, a greenfield repo, a new tool | Every topic, plus the three new-project topics. A single-purpose script or CLI needs only scope, tech stack and dependencies. |

After the research, state the tier and the topics it brings in, and continue: "This looks like a medium-scope feature, so the interview will cover scope, user journeys, data model, API surface, integration points and dependencies." Do not stop to ask for confirmation. The user can correct the tier at any point, and a correction changes the coverage list.

When called as the refinement skill for a story too thin to implement, the story is the subject and its missing detail is what the interview is for.

---

## Phase 1: Research

Gather what you can before the interview starts; the interview checks these sources again before each question.

**When a codebase is available:**

1. Read the README, any project documentation, or config files for project structure, conventions, and context.
2. Read any backlog docs or task lists if accessible.
3. Explore the codebase: directory structure, key files, existing patterns, architectural approach.
4. Identify the modules, files, and patterns the feature will touch or extend.

**When no codebase is available:** work from what the user has described, and note the gaps, ambiguities and unstated assumptions in it. For a new project, also read any specs, wireframes or reference projects the user names, and whatever an empty repo already holds.

Present a brief summary of what you found (relevant existing code and patterns, related existing stories or tasks, likely integration points and constraints), then state the scope tier as above.

---

## Phase 2: Interview

Read `skills/interview/SKILL.md` and run it with the feature as the plan. Its posture, question wording, `AskUserQuestion` rules, pacing and no-person-present rule govern the whole interview; this skill adds none of its own. Every resolved question informs the stories, and every deferred one becomes an open item in Phase 5.

### Coverage topics

Hand the interview the topics for the tier. They are not a script to read out: the interview asks about them in its own order and batches, and uses this list at the end as a check that nothing was missed. A topic the codebase already answers counts as covered.

1. **Scope and boundaries** (all tiers): what is being built or changed (the opening message usually says), what is out of scope, who is affected.
2. **User journeys** (medium + large): the happy path end to end, critical failure modes, edge cases.
3. **Data model** (medium + large, skip if no new entities): new entities and relationships, changes to existing ones, migration of existing data.
4. **API surface** (medium + large, skip if no new endpoints): endpoints created or changed, auth and permission changes, contract changes and backwards compatibility.
5. **Integration points** (all tiers): existing modules touched, patterns to follow, ripple effects on other features.
6. **Architecture** (large, or when trade-offs arise): patterns and trade-offs, constraints, deviations from the existing architecture and why.
7. **Dependencies and ordering** (medium + large): build order for stories, external dependencies, prerequisite changes (migrations, config, infrastructure).
8. **Testing strategy** (large, or when the user raises it): critical paths needing integration tests, edge cases, existing test patterns.
9. **Vision** (new project): the problem it solves, who the users are, what "done" means for the first usable version.
10. **Tech stack** (new project): language, framework and runtime, hosting, CI/CD, key libraries.
11. **DevOps and deployment** (new project, medium size and up): environments, deployment targets, monitoring.

When the interview closes with every applicable topic covered, go straight to Phase 3.

---

## Phase 3: Architecture (when needed)

Skip for small-scope work unless the user raises architecture concerns. For medium and large scope, use the **code-architect** skill to:
1. Design or validate the approach
2. Flag violations or tensions with existing architecture

For a new project, always run it: select and justify the architecture style, define boundaries and layers, and name the constraints. Foundation stories (project setup, CI/CD, base architecture) come first in the build order.

---

## Phase 4: Decomposition

Break the work into epics, features and stories.

### Epic → Feature → User Story

Every user story belongs to a feature. A feature belongs to an epic when the work has one: an epic groups several features toward one outcome, so work that is a single feature is filed as a feature on its own, never under an epic that restates it. `wf issue-apply` refuses a story with no feature parent, and a story or feature under the wrong type, wherever the org has the parent type enabled. A feature with no epic is allowed.

- **Epic**: an outcome that takes more than one feature. Title (short, capability-focused), goal (2–3 sentences), dependencies on other epics.
- **Feature**: one capability a user can see working on its own. Title and a one-paragraph goal. If a feature's title and goal would read the same as its epic's, there is one level too many: drop the epic.
- **User story**: one session of buildable work (sizing below), under its feature.

Attach before creating. When the work extends an epic or a feature that already exists, parent the new features or stories to it by issue number rather than filing a second one. A small change is one story under an existing feature. Where no feature fits, the plan proposes one, and proposes an epic above it only when the outcome spans more than one feature.

Bugs and chores sit outside the tree, and a parent on either is allowed and never required. Where the org has no `Chore` type, `chore` and `tech debt` are filed as `User Story` and `Feature` instead, and then they are in the tree like any other.

### Story structure

Use the story template from `references/story-template.md`. It is short on purpose: a Summary, the changes, and acceptance criteria, plus only the sections that carry information the implementer would otherwise have to guess. Read the `writing-github-issues` skill before writing stories that become GitHub issues, and follow it for the title as well as the body.

A story the interview left genuinely open keeps that uncertainty in the words the interview used. Do not resolve an open question by writing a decision into the story.

### Story sizing

- One session of work max (~100k tokens). If bigger, split it.
- One concern per story (one module, one screen, one API surface).
- Technical Notes over 10 lines means the story is too big.
- More than 5 files to create/modify means the story is too big.
- More than 3 modules touched means the story is too big.
- Dependencies must be explicit and acyclic.
- Assign a size estimate to each story: `small` (< 50k tokens), `medium` (50–100k), `large` (needs splitting). It is carried by the `Effort` field on the spec entry and nowhere else — do not also write it into the body, where nothing reads it and it goes stale the first time somebody re-estimates.
- When a story is flagged as too large, automatically split it and explain the split to the user before proceeding.
- **One story, one party.** A story whose work is partly a code agent's and partly a browser agent's or a person's is split along that line, however small the manual half is, because `Ownership` is one value and the half nothing can route would otherwise sit unfinished inside a story the pool thinks is buildable. The manual half becomes its own story, and the code story takes a `blocked_by` edge to it where it genuinely cannot start first. The rule is stated in `writing-github-issues` → **Scope: one issue, one party**, which is also where the `[Manual] ` and `[Browser] ` title prefixes are defined.

### Deferred speccing (large features)

When a large-scope feature produces more than 4 stories:

1. **Fully spec** the first 2–3 stories in the dependency chain (the fundamentals that later stories depend on).
2. **Defer speccing** for stories deeper in the dependency chain. Create them with minimal spec: title, one-line Overview, a `blocked_by` list naming what they wait on, and a note: "This story needs refinement after its dependencies are complete." The dependency is the edge `blocked_by` writes; nothing reads a dependency out of a body.
3. Give each deferred story the **Needs refinement** stage rather than `Backlog`, by setting `"state": "refinement"` on its spec entry. The pool is the issues at a blank or `Backlog` stage, so that is what keeps a half-specced story out of it until its dependencies are resolved and a refinement session has been run.

### Dependency chain enforcement

Every story must declare its dependencies in its spec entry's `blocked_by`, which `wf issue-apply` writes as a native blocked-by edge. That edge is the dependency; a sentence in the body is not read by anything.

After decomposition:

1. Build a text-based dependency graph showing the ordering.
2. Validate the graph is a DAG — no cycles allowed. If a cycle is detected, surface it to the user and resolve before proceeding.
3. Include the dependency graph in the Phase 5 review output.

### Cross-referencing

After decomposition, verify:
- Every interview question is covered by at least one story
- No gaps in the user journey
- Dependencies are acyclic (validated by the DAG check above)
- No overlap with existing stories
- Story ordering respects dependency chain

---

## Phase 5: Review

Present the plan before finalising:
1. Story list with one-line summaries, grouped under their features and epics, naming the issue number of any existing epic or feature they attach to
2. Dependency graph (text or visual)
3. Coverage check against interview findings
4. Open issues or deferred items

Use `AskUserQuestion`:

- "Approve (Recommended)"
- "I have changes"
- "Redo a section"

Iterate until confirmed.

---

## Output

The final deliverable is stories, grouped under features and epics, with acceptance criteria and dependency ordering. Do **not** write decision documents, design specs, or summary files to the filesystem. The conversation is the decision record; the stories are the actionable output.

### Creating issues on GitHub

When the user approves the plan, offer to create the stories as GitHub issues. If they accept:

0. Write each title and body to the `writing-github-issues` standard (its story shape is `references/story-template.md`). The interview produces far more material than a story needs, so this is where most of it gets left behind: no discovery history, no restating the Summary under another heading, and no section that would be empty. Write each paragraph on one unwrapped line (`_shared/body-standard.md`).

   A story that cannot be finished without a person, because it needs a permission or an approval no agent can give, is marked three ways together: `[Manual]` at the front of the title, `Ownership` set to `Human`, and a `## Manual step` section saying what has to be done and why. The field is the one that matters — it is what keeps the story out of the code agent's pool, and `issue-apply` sets its stage to `Non-code` from it.

   Check once, before the first issue, whether the repository publishes an issue template, either its own or one inherited from the organisation's `.github` repository. Where one applies, every story uses its headings and order. This is resolved through `templates/issue-template-resolution.md`; the result is cached, so check once rather than per story.
1. **One write for the whole set.** Every issue is created by `wf issue-apply` from a single spec — title, body, native issue type, field values, labels, parent and dependency edges together. Not a `gh issue create` loop, and not create-then-upgrade: an issue that exists for a few seconds carrying only labels is what put half-classified stories in the backlog.

   The command works in dependency order for you. Entries reference each other by `key` before any of them has a number, parents are created before children, and edges are written last, so the whole tree is one command whatever its shape.

   Write each story's body to its own file in `.claude/` with the Write tool, then the spec beside them:

   ```bash
   mkdir -p .claude
   cat > .claude/discovery-spec.json <<'JSON'
   {"issues": [{"key": "epic",
                "title": "{epic title}",
                "body_file": ".claude/epic-body.md",
                "kind": "epic",
                "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                           "field-effort": "{Low|Medium|High}",
                           "field-ownership": "Code agent",
                           "field-origin": "Feature Discovery"}},
               {"key": "feature-1",
                "title": "{feature title}",
                "body_file": ".claude/feature-1-body.md",
                "kind": "feature",
                "parent": "epic",
                "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                           "field-effort": "{Low|Medium|High}",
                           "field-ownership": "Code agent",
                           "field-origin": "Feature Discovery"}},
               {"key": "story-1",
                "title": "{story title}",
                "body_file": ".claude/story-1-body.md",
                "kind": "story",
                "parent": "feature-1",
                "blocked_by": ["{other key or issue number}"],
                "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                           "field-effort": "{Low|Medium|High}",
                           "field-ownership": "Code agent",
                           "field-origin": "Feature Discovery"}}]}
   JSON
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/discovery-spec.json
   ```

   - Each body goes in its own file and the entry names it (`body_file`) rather than carrying the text, so fenced code, backticks, `$` and quotes survive intact. The rule is stated once in `templates/body-file-write.md`.
   - `kind` supplies the native type **and** the `Classification` value together (a story → User Story / New Feature, a feature → Feature, an epic → Epic), so neither is chosen by hand. Use `spike` for a research story.
   - `parent` is required on every story, naming its feature, and set on a feature that belongs to an epic, by spec `key` or by the issue number of one that already exists. Drop the epic entry and the feature's `parent` when the work is a single feature. An epic takes none.
   - **No labels at all**, and no `[STORY]` title prefix. The native type classifies the issue and the fields carry everything a decision reads; `issue-apply` strips a retired label or a type prefix if a spec still names one, and says that it did.
   - `field-effort` comes from the story's size estimate: large → **High**, medium → **Medium**, small → **Low**.
   - `field-priority`, `field-effort` and `field-ownership` are **required on every entry** — they are the pool's order, its size ceiling and whether a code agent may take the story at all, and `issue-apply` refuses a spec that leaves one blank. `field-ownership` is `Code agent` for a story a code agent will build, and `Browser agent` or `Human` for one it cannot.
   - `blocked_by` writes a native edge, and `issue-apply` then sets the stage to `Blocked` for any entry whose edges point at something still open.
   - Add `"milestone": "{title}"` to an entry in sprint mode. It must name an open milestone.
2. Name every dependency in the entry's `blocked_by`. Where the dependency is another entry in the same spec and has no number yet, reference it by `key` and `issue-apply` resolves it once both exist.
3. **Do not set a stage by hand.** `issue-apply` writes every stage from the issue's own fields: one owned by a person or a browser agent goes to `Non-code`; one whose edges point at something still open goes to `Blocked`; everything else goes to `Backlog`, which is what available means. A **deferred** story (see "Deferred speccing") is the one case the fields cannot express, because nothing on the issue says its spec is thin — say so with `"state": "refinement"` on the entry, which is read before the edges and sets the stage to `Needs refinement`.
4. **Read the exit code.** **0** created them, and every issue number is written back into the spec file, so a re-run after a partial failure completes the remainder rather than filing duplicates. **21** (`no-capabilities`) means the org defines no types or fields — report that the stories could not be classified rather than filing them unclassified by hand. **22** means the spec is wrong (an unknown label, a milestone that is not open, a missing required field, a story with no feature parent, or an org that defines no `Priority`, `Effort` or `Ownership` field at all), so fix it and re-run. **23** and **24** mean the issues exist but some metadata did not land, so name what failed and carry on.

   Where the command is unavailable, say so and stop rather than hand-writing the mutations.
5. After creation, check the dependency graph against the edges `issue-apply` reports back, not against anything in the bodies — a body never records a dependency. `issue-apply` reads each body back in the same request, so body corruption is already reported; only if it flagged a mismatch, apply the corruption test and retry in `templates/body-file-write.md`.
6. Present a summary: issue numbers, titles, native type, priority and effort, and the dependency graph with issue numbers filled in.

**Leave the assignee blank.** Do not assign created stories to anyone — not the creator, not an agent. Pass no `--assignee`/`--add-assignee` on creation and do not edit issues to assign them afterward. Backlog stories must enter the unassigned pool so `execute` can select them; assignment happens only at claim time, never at creation.

---

## Continuous Mode

When the feature area already has stories:
1. Read all existing tasks and their status
2. Identify gaps (missing stories, stale stories, incomplete AC)
3. Present findings
4. Run the interview on the gaps only
5. Produce only the missing stories
