---
name: feature-discovery
description: 'Plan a feature, change or new project and break it into features and stories with acceptance criteria. Trigger on scoping work, planning a new project, or refining an issue too thin to build.'
depends-on:
  - grill
  - code-architect
---
# Feature Discovery

Turn a feature, change, requirement or brand-new project into buildable stories. The interview that gets there is the `grill` skill's; this skill decides what the interview must cover and what gets built from its answers. A request to stress-test a plan without producing stories is a grill on its own: run `/synergy:grill` instead.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## Skills Used

Read each skill's SKILL.md when you reach the phase that needs it.

- **grill** (`/synergy:grill`) — The interview: how questions are asked, paced and closed, and what happens when nobody is present to answer.
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

Gather what you can before the interview starts; the grill checks these sources again before each question.

**When a codebase is available:**

1. Read the README, any project documentation, or config files for project structure, conventions, and context.
2. Read any backlog docs or task lists if accessible.
3. Explore the codebase: directory structure, key files, existing patterns, architectural approach.
4. Identify the modules, files, and patterns the feature will touch or extend.

**When no codebase is available:** work from what the user has described, and note the gaps, ambiguities and unstated assumptions in it. For a new project, also read any specs, wireframes or reference projects the user names, and whatever an empty repo already holds.

Present a brief summary of what you found (relevant existing code and patterns, related existing stories or tasks, likely integration points and constraints), then state the scope tier as above.

---

## Phase 2: Interview

Read `skills/grill/SKILL.md` and run it with the feature as the plan. Its posture, question wording, `AskUserQuestion` rules, pacing and no-person-present rule govern the whole interview; this skill adds none of its own. Every resolved question informs the stories, and every deferred one becomes an open item in Phase 5.

### Coverage topics

Hand the grill the topics for the tier. They are not a script to read out: the grill asks about them in its own order and batches, and uses this list at the end as a check that nothing was missed. A topic the codebase already answers counts as covered.

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

When the grill closes with every applicable topic covered, go straight to Phase 3.

---

## Phase 3: Architecture (when needed)

Skip for small-scope work unless the user raises architecture concerns. For medium and large scope, use the **code-architect** skill to:
1. Design or validate the approach
2. Flag violations or tensions with existing architecture

For a new project, always run it: select and justify the architecture style, define boundaries and layers, and name the constraints. Foundation stories (project setup, CI/CD, base architecture) come first in the build order.

---

## Phase 4: Decomposition

Break the work into features and stories, each placed under an area.

### Area → Feature → User Story

Every project keeps its issues under **area epics**: an `Epic` at `Stage` `Area` is one permanent part of the product, such as Library or Listening, and is never closed. Release notes are grouped by area, so every issue has to resolve to one. Planned work never gets an `Epic` of its own: this skill files features and stories, and never an epic.

- **Feature**: one piece of planned work under an area. Title and a one-paragraph goal. Work that would once have been an epic is a feature, and what would have been its features are its stories, or features beside it under the same area.
- **User story**: one session of buildable work (sizing below), under its feature. `wf issue-apply` refuses a story with no feature parent, and a story or feature under the wrong type, wherever the org has the parent type enabled.

**Choose each feature's area.** Once, before planning the tree, list the open area epics and read their bodies, which say what each covers: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" areas`. Give each feature the area whose body best covers it. When nothing fits well, use the closest area and say so in one line of the feature's body, so a person can move it. Do not create an area: that is a decision for a person. Only when the command returns a `count` of 0, the project has no area epics: file the features without a parent, and tell the user so, pointing at `references/area-epics.md`.

Attach before creating. When the work extends a feature that already exists, parent the new stories to it by issue number rather than filing a second one. A small change is one story under an existing feature. Where no feature fits, the plan proposes one under an area.

Bugs and chores sit under a feature or directly under an area. Where the org has no `Chore` type, `chore` and `tech debt` are filed as `User Story` and `Feature` instead, and then they are in the tree like any other.

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
- **One story, one party.** A story whose work is partly a code agent's and partly a browser agent's or a person's is split along that line, however small the manual half is, because `Ownership` is one value and the half nothing can route would otherwise sit unfinished inside a story the pool thinks is buildable. The manual half becomes its own story, and the code story takes a `blocked_by` edge to it where it genuinely cannot start first. Only when a story needs this split, read `skills/writing-github-issues/references/scope-and-hierarchy.md` → **Scope: one issue, one party**, which is also where the `[Manual] ` and `[Browser] ` title prefixes are defined.

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
1. Story list with one-line summaries, grouped under their features and each feature's area, naming the issue number of the area and of any existing feature they attach to
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

The final deliverable is stories, grouped under features and areas, with acceptance criteria and dependency ordering. Do **not** write decision documents, design specs, or summary files to the filesystem. The conversation is the decision record; the stories are the actionable output.

### Creating issues on GitHub

When the user approves the plan, offer to create the stories as GitHub issues. If they accept, follow `references/creating-issues.md`: it writes each story to the `writing-github-issues` standard, resolves the repository's issue template through `templates/issue-template-resolution.md`, writes each body by `templates/body-file-write.md`, and creates the whole set in one `wf issue-apply` call.

---

## Continuous Mode

When the feature area already has stories:
1. Read all existing tasks and their status
2. Identify gaps (missing stories, stale stories, incomplete AC)
3. Present findings
4. Run the grill on the gaps only
5. Produce only the missing stories
